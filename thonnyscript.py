import time
from machine import Pin, I2C

# =============================================================
# I2C VERBINDING
# I2C is een communicatieprotocol met 2 draden:
#   SDA = datalijn (Pin 0)
#   SCL = klok    (Pin 1)
# freq=400000 = 400kHz communicatiesnelheid
# =============================================================
i2c = I2C(0, sda=Pin(0), scl=Pin(1), freq=400000)

# Vast I2C adres van de TCS3472 sensor
ADDR = 0x29

# =============================================================
# SENSOR REGISTERS
# De sensor heeft interne geheugenplaatsen (registers).
# Je schrijft ernaar om instellingen te doen,
# en leest eruit om meetwaarden op te halen.
# =============================================================
ENABLE  = 0x80   # Sensor aan/uit
ATIME   = 0x81   # Integratietijd (hoe lang licht verzamelen)
CONTROL = 0x8F   # Gain (signaalversterking)
CDATAL  = 0x94   # Startadres kleurdata (clear, r, g, b)

# =============================================================
# SENSOR INITIALISEREN
# Op basis van meetrapport: gain=1x + 154ms beste instelling
#   - Geen verzadiging bij felle kleuren
#   - Verhoudingen stabiel en consistent
#
# 0x03 = bit0 (power on) + bit1 (meting starten)
# 0xC0 = integratietijd 154ms  → (256 - 0xC0) x 2.4ms = 154ms
# 0x00 = gain 1x (geen versterking)
# =============================================================
i2c.writeto_mem(ADDR, ENABLE,  bytes([0x03]))
time.sleep(0.3)  # Wachten tot sensor opgestart is
i2c.writeto_mem(ADDR, ATIME,   bytes([0xC0]))
i2c.writeto_mem(ADDR, CONTROL, bytes([0x00]))

# =============================================================
# SMOOTHING BUFFERS
# Drie lijsten die de laatste 5 metingen onthouden per kanaal.
# Zo berekenen we een voortschrijdend gemiddelde en heeft
# één uitschietende meting veel minder invloed.
# =============================================================
buf_r = []
buf_g = []
buf_b = []

# =============================================================
# STABILITEIT TRACKING
# Bijhouden hoe vaak op rij dezelfde kleurnaam uitkomt.
# Pas na 3 keer op rij wordt de kleur als stabiel gezien.
#
# last_name    = de kleur die momenteel als stabiel geldt
#                (buffer wordt gewist als DEZE wisselt)
# last_stable  = de vorige uitkomst van get_color_name,
#                gebruikt om stable_count bij te houden
# =============================================================
stable_count = 0
last_stable  = None
last_name    = None

# =============================================================
# FUNCTIE: read_word
# De sensor geeft elke kleurwaarde als 2 losse bytes (16-bit).
# We lezen 2 bytes en plakken ze samen tot één getal.
# Voorbeeld: byte1=0x04, byte0=0x00 → 0x0400 = 1024
# =============================================================
def read_word(reg):
    data = i2c.readfrom_mem(ADDR, reg, 2)
    return data[1] << 8 | data[0]  # High byte links, low byte rechts

# =============================================================
# FUNCTIE: smooth
# Voortschrijdend gemiddelde over de laatste 5 metingen.
# Nieuwe waarde wordt toegevoegd, oudste wordt verwijderd.
# Geeft het gemiddelde terug.
# =============================================================
def smooth(val, buf, size=5):
    buf.append(val)
    if len(buf) > size:
        buf.pop(0)           # Oudste meting weggooien
    return sum(buf) / len(buf)

# =============================================================
# FUNCTIE: clear_buffers
# Leegt alle smoothing buffers.
# Wordt alleen aangeroepen als een nieuwe kleur stabiel bewezen
# is (3x op rij), zodat uitschieters de buffer niet onnodig
# wissen en nuttige data verloren gaat.
# =============================================================
def clear_buffers():
    buf_r.clear()
    buf_g.clear()
    buf_b.clear()

# =============================================================
# FUNCTIE: get_color_name
# Bepaalt de kleurnaam op basis van:
#   r, g, b  = genormaliseerde RGB waarden (0-255)
#   c_raw    = ruwe clear waarde rechtstreeks van sensor
#
# We gebruiken VERHOUDINGEN (rr, gr, br) in plaats van
# absolute waarden. Verhoudingen zijn stabieler omdat ze
# niet veranderen bij meer of minder omgevingslicht.
#
# Gemeten verhoudingen uit meetrapport:
#   rood:  RR=0.50  GR=0.28  BR=0.22
#   groen: RR=0.31  GR=0.43  BR=0.27
#   blauw: RR=0.31  GR=0.35  BR=0.34
# =============================================================
def get_color_name(r, g, b, c_raw):
    total = r + g + b

    if total < 50:
        return "none"

    # Verhoudingen berekenen
    # Hoe groot is elk kanaal ten opzichte van het totaal
    rr = r / total   # rood verhouding
    gr = g / total   # groen verhouding
    br = b / total   # blauw verhouding

    # ---------------------------------------------------------
    # GEEL: eerst checken want heeft hoge c net als wit
    # Kenmerk: R en G allebei hoog, B duidelijk laag
    # Meting: rr=0.44, gr=0.39, br=0.17
    # ---------------------------------------------------------
    if rr > 0.38 and gr > 0.33 and br < 0.25 and abs(rr - gr) < 0.12:
        return "geel"

    # ---------------------------------------------------------
    # WIT: c heel hoog, alle kanalen hoog
    # Meting: c=649
    # rr < 0.42 voorkomt dat geel hier ook invalt
    # ---------------------------------------------------------
    if c_raw > 550 and rr < 0.42:
        return "wit"

    # ---------------------------------------------------------
    # ZWART: c laag, net boven object detectie drempel
    # Meting: c=270, alles laag en ongeveer gelijk
    # Drempel op 300 gehouden — hogere waarden zijn blauw/paars
    # Verhoudingscheck strikt op 0.05 zodat blauw (rr≈0.33,
    # gr≈0.36, br≈0.31) hier niet meer invalt
    # ---------------------------------------------------------
    # Check 1: alle kanalen vrijwel gelijk (grijsachtig zwart)
    if c_raw < 300 and abs(rr - gr) < 0.05 and abs(gr - br) < 0.05:
        return "zwart"
    # Check 2: absolute waarden laag maar verhoudingen ongelijk
    # Meting: r=78,g=83,b=64 → donker object, geen gelijke verhoudingen
    # max < 90 en min > 50 voorkomt overlap met blauw (r=71,g=80,b=78)
    if c_raw < 320 and max(r, g, b) < 90 and min(r, g, b) > 65:
        return "zwart"

    # ---------------------------------------------------------
    # PAARS: B iets groter dan G, R het laagst
    # Meting: c=351, r=99, g=108, b=111
    # c < 400 voorkomt overlap met blauw (c=434)
    # ---------------------------------------------------------
    if br > gr and br > rr and c_raw < 400:
        return "paars"

    # ---------------------------------------------------------
    # ROZE: R dominant, G en B bijna gelijk aan elkaar
    # Meting: rr=0.49, gr=0.26, br=0.25
    # abs(gr - br) < 0.04 onderscheidt roze van rood
    # want bij rood zijn G en B verder uit elkaar
    # ---------------------------------------------------------
    if rr > 0.42 and abs(gr - br) < 0.04:
        return "roze"

    # ---------------------------------------------------------
    # ROOD: R veel groter dan G en B
    # Meting: rr=0.50, gr=0.28, br=0.22
    # ---------------------------------------------------------
    if rr > 0.45 and rr > gr + 0.15 and rr > br + 0.15:
        return "rood"

    # ---------------------------------------------------------
    # GROEN: G duidelijk hoger dan B, R lager dan G
    # Meting: GR=0.43, BR=0.27 → verschil = 0.16
    # gr > 0.40 en (gr - br) > 0.12 voorkomt overlap met blauw
    # ---------------------------------------------------------
    if gr > 0.40 and (gr - br) > 0.12:
        return "groen"

    # ---------------------------------------------------------
    # BLAUW: G en B beide groter dan R, dicht bij elkaar
    # Meting: GR=0.35, BR=0.34 → verschil slechts 0.01
    # abs(gr - br) < 0.05 is het belangrijkste kenmerk
    # ---------------------------------------------------------
    if gr > rr and br > rr and abs(gr - br) < 0.05:
        return "blauw"

    return "onbekend"

# =============================================================
# HOOFDLUS
# Elke 0.1 seconde:
#   1. Ruwe sensorwaarden uitlezen
#   2. Controleren of er een object is
#   3. Normaliseren naar 0-255
#   4. Smoothing toepassen
#   5. Kleurnaam bepalen
#   6. Stabiliteitsindicator checken
#   7. Versturen via seriële poort naar de browser
# =============================================================
while True:

    # --- Stap 1: Ruwe waarden uitlezen ---
    # CDATAL+0 = clear (totale lichtsterkte)
    # CDATAL+2 = rood kanaal
    # CDATAL+4 = groen kanaal
    # CDATAL+6 = blauw kanaal
    c = read_word(CDATAL)
    r = read_word(CDATAL + 2)
    g = read_word(CDATAL + 4)
    b = read_word(CDATAL + 6)

    # --- Stap 2: Object detectie ---
    # niks heeft c=244, zwart heeft c=270
    # drempel op 260 filtert niks eruit maar laat zwart door
    # Opmerking: c==0 kan hier niet voorkomen (c < 260 vangt dat al op),
    # maar de check staat hieronder als veiligheidsnet voor normalisatie.
    total = r + g + b
    if c < 260 or total < 180:
        if last_name != "none":
            clear_buffers()
            last_name    = "none"
            stable_count = 0
            last_stable  = None
        print("0,0,0,none")
        time.sleep(0.1)
        continue  # Sla de rest van de lus over

    # Veiligheidsnet: voorkom deling door nul bij normalisatie
    # (kan in theorie niet meer voorkomen na bovenstaande check)
    if c == 0:
        c = 1

    # --- Stap 3: Normalisatie via clear kanaal ---
    # Ruwe waarden delen door c elimineert effect van
    # omgevingslicht. Daarna schalen naar 0-255.
    rn = (r / c) * 255
    gn = (g / c) * 255
    bn = (b / c) * 255

    # --- Stap 4: Smoothing ---
    # Gemiddelde over laatste 5 metingen voor stabiliteit
    rn = smooth(rn, buf_r)
    gn = smooth(gn, buf_g)
    bn = smooth(bn, buf_b)

    # Afronden en begrenzen op geldig RGB bereik (0-255)
    ri = max(0, min(255, int(rn)))
    gi = max(0, min(255, int(gn)))
    bi = max(0, min(255, int(bn)))

    # --- Stap 5: Kleurnaam bepalen ---
    name = get_color_name(ri, gi, bi, c)

    # --- Stap 6: Stabiliteitsindicator ---
    # Kleur wordt pas getoond na 3 keer op rij hetzelfde.
    # Voorkomt geflicker door losse uitschieters.
    if name == last_stable:
        stable_count += 1
    else:
        stable_count = 1
        last_stable  = name

    # --- Stap 7: Buffer legen bij STABIELE kleurwissel ---
    # VERBETERING t.o.v. vorige versie: buffer wordt alleen gewist
    # als de nieuwe kleur al 3x stabiel bewezen is. Dit voorkomt
    # dat één uitschietende meting de opgebouwde buffer weggooit.
    if stable_count >= 3 and name != last_name:
        clear_buffers()
        last_name = name

    if stable_count >= 3:
        # Stabiel: stuur kleur naar browser
        # Format: "r,g,b,naam" bijvoorbeeld "255,0,0,rood"
        print("{},{},{},{}".format(ri, gi, bi, name))
    else:
        # Nog niet stabiel genoeg, stuur none
        print("0,0,0,none")

    time.sleep(0.1)
