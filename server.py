#!/usr/bin/env python3
"""
server.py — Brug tussen Raspberry Pi Pico (USB serieel) en browser (WebSocket)

Installeer dependencies:
    pip install pyserial websockets

Gebruik:
    python server.py

De server luistert op:
    - Serieel:    automatisch zoeken naar Pico op COM-poorten (Windows) of /dev/tty* (Linux/Mac)
    - WebSocket:  ws://localhost:8765
    - HTTP:       http://localhost:8080  (serveert index.html)
"""

import asyncio
import serial
import serial.tools.list_ports
import websockets
import threading
import http.server
import socketserver
import os
import json
import time
from pathlib import Path

# ── Instellingen ──────────────────────────────────────────────
SERIAL_BAUDRATE  = 115200
WEBSOCKET_PORT   = 8765
HTTP_PORT        = 8080
RECONNECT_DELAY  = 3       # Seconden wachten voor herverbinding na USB disconnect
SCRIPT_DIR       = Path(__file__).parent

# ── Globale state ─────────────────────────────────────────────
connected_clients = set()
clients_lock      = threading.Lock()   # Voorkomt race conditions bij gelijktijdige toegang
latest_data       = {"r": 0, "g": 0, "b": 0, "name": "none"}


def find_pico_port():
    """Zoekt automatisch de Pico op alle beschikbare seriële poorten."""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        desc = (port.description or "").lower()
        hwid = (port.hwid or "").lower()
        # Pico herkend via USB vendor ID 2E8A of beschrijving
        if "2e8a" in hwid or "pico" in desc or "micropython" in desc or "usb serial" in desc.lower():
            print(f"[SERIEEL] Pico gevonden op: {port.device}")
            return port.device
    # Fallback: eerste beschikbare poort
    if ports:
        print(f"[SERIEEL] Pico niet herkend, gebruik eerste poort: {ports[0].device}")
        return ports[0].device
    return None


async def broadcast(message: str):
    """Stuur bericht naar alle verbonden browsers."""
    # Maak een kopie van de set onder de lock zodat we de set
    # niet vasthouden tijdens het versturen (kan lang duren)
    with clients_lock:
        clients_snapshot = set(connected_clients)

    if clients_snapshot:
        await asyncio.gather(
            *[client.send(message) for client in clients_snapshot],
            return_exceptions=True
        )


async def websocket_handler(websocket):
    """Nieuwe browserverbinding: registreer en stuur laatste bekende data."""
    with clients_lock:
        connected_clients.add(websocket)
    print(f"[WS] Browser verbonden. Totaal: {len(connected_clients)}")
    try:
        # Stuur meteen de laatste bekende meting
        await websocket.send(json.dumps(latest_data))
        # Blijf open totdat browser verbreekt
        await websocket.wait_closed()
    finally:
        with clients_lock:
            connected_clients.discard(websocket)
        print(f"[WS] Browser verbroken. Totaal: {len(connected_clients)}")


def serial_reader(loop, port):
    """
    Leest seriële data van de Pico in een aparte thread.
    Elke regel heeft formaat: r,g,b,naam  (bijv. 143,67,52,rood)

    Herverbindt automatisch als de Pico even loskomt (USB disconnect).
    """
    global latest_data

    while True:
        print(f"[SERIEEL] Verbinding openen op {port} @ {SERIAL_BAUDRATE} baud...")
        try:
            ser = serial.Serial(port, SERIAL_BAUDRATE, timeout=1)
            print(f"[SERIEEL] Verbonden!")
        except serial.SerialException as e:
            print(f"[SERIEEL] FOUT: {e}")
            print(f"[SERIEEL] Opnieuw proberen in {RECONNECT_DELAY} seconden...")
            time.sleep(RECONNECT_DELAY)
            continue  # Probeer opnieuw te verbinden

        # Lees data zolang de verbinding open is
        while True:
            try:
                line = ser.readline().decode("utf-8").strip()
                if not line:
                    continue

                parts = line.split(",")
                if len(parts) != 4:
                    continue

                r_str, g_str, b_str, name = parts[0], parts[1], parts[2], parts[3]

                # Valideer dat r/g/b getallen zijn
                r, g, b = int(r_str), int(g_str), int(b_str)

                # Valideer dat r/g/b binnen geldig RGB bereik vallen
                if not all(0 <= v <= 255 for v in (r, g, b)):
                    print(f"[SERIEEL] Ongeldige RGB waarden ontvangen: {r},{g},{b} — overgeslagen")
                    continue

                latest_data = {"r": r, "g": g, "b": b, "name": name}
                payload = json.dumps(latest_data)

                # Stuur naar alle browsers via de asyncio event loop
                asyncio.run_coroutine_threadsafe(broadcast(payload), loop)

            except (ValueError, UnicodeDecodeError):
                continue  # Ongeldige regel, overslaan
            except serial.SerialException as e:
                print(f"[SERIEEL] Verbinding verbroken: {e}")
                print(f"[SERIEEL] Herverbinden in {RECONNECT_DELAY} seconden...")
                break  # Breek de binnenste loop, buitenste loop herverbindt

        # Korte pauze voor herverbindingspoging
        time.sleep(RECONNECT_DELAY)


class HTTPHandler(http.server.SimpleHTTPRequestHandler):
    """Serveert bestanden vanuit de scriptmap."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SCRIPT_DIR), **kwargs)

    def log_message(self, format, *args):
        pass  # HTTP logs onderdrukken


def start_http_server():
    """Start de HTTP-server in een aparte thread."""
    try:
        with socketserver.TCPServer(("", HTTP_PORT), HTTPHandler) as httpd:
            print(f"[HTTP] index.html beschikbaar op http://localhost:{HTTP_PORT}")
            httpd.serve_forever()
    except OSError as e:
        print(f"[HTTP] FOUT: Poort {HTTP_PORT} is al in gebruik — {e}")
        print(f"[HTTP] Sluit het andere programma dat poort {HTTP_PORT} gebruikt en herstart.")


async def main():
    loop = asyncio.get_event_loop()

    # Zoek Pico poort
    port = find_pico_port()
    if not port:
        print("[FOUT] Geen seriële poort gevonden. Sluit de Pico aan en herstart.")
        return

    # Start HTTP server in thread
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    # Start seriële reader in thread
    serial_thread = threading.Thread(
        target=serial_reader, args=(loop, port), daemon=True
    )
    serial_thread.start()

    # Start WebSocket server
    print(f"[WS] WebSocket server op ws://localhost:{WEBSOCKET_PORT}")
    async with websockets.serve(websocket_handler, "localhost", WEBSOCKET_PORT):
        print("\n=== Alles draait! Open http://localhost:8080 in je browser ===\n")
        await asyncio.Future()  # Blijf draaien


if __name__ == "__main__":
    asyncio.run(main())