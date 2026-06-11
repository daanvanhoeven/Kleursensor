# Colour Sensor Dashboard

## Overzicht
Dit project gebruikt een TCS34725 kleursensor in combinatie met een Raspberry Pi Pico W om kleuren te detecteren. De Pico W leest de sensor uit en stuurt de gegevens via Wi-Fi naar een webpagina. Op deze pagina worden de gedetecteerde kleur, de RGB-waarden en een kleurvak weergegeven.

## Hardware
- Raspberry Pi Pico W
- TCS34725 Colour Sensor
- USB-kabel
- Computer of laptop

## Software
- Thonny
- MicroPython
- Visual Studio Code
- Webbrowser (bijvoorbeeld Google Chrome)

## Installatie

### 1. Raspberry Pi Pico W instellen
1. Installeer MicroPython op de Pico W.
2. Open Thonny.
3. Upload het Python-bestand naar de Pico W.
4. Vul de juiste Wi-Fi gegevens in:

```python
ssid = "JouwWifi"
password = "JouwWachtwoord"
```

5. Start het programma.

### 2. Website instellen
1. Open `index.html` in Visual Studio Code.
2. Controleer het IP-adres:

```javascript
let ip = "http://192.168.xxx.xxx";
```

3. Vervang dit door het IP-adres dat de Pico W in Thonny toont.
4. Open het HTML-bestand in een browser.

## Werking
1. De TCS34725 meet de kleur van een object.
2. De Pico W verwerkt de RGB-waarden.
3. De ingebouwde webserver verstuurt de gegevens via Wi-Fi.
4. De website toont:
   - De gedetecteerde kleur
   - De RGB-waarden
   - Een kleurvlak met de bijbehorende kleur

## Ondersteunde kleuren
- Rood
- Groen
- Blauw
- Geel
- Roze
- Wit
- Zwart
- Onbekend

## Gebruikte technologieën
- Python (MicroPython)
- HTML
- CSS
- JavaScript
- Raspberry Pi Pico W
- TCS34725 Colour Sensor

## Auteur
Project ontwikkeld als kleurdetectiesysteem met live webdashboard.