#!/usr/bin/env python3
# ---------------------------------------------------------------------------
# VVE GPU-Statusbeleuchtung — faerbt die RGB-Beleuchtung der Grafikkarte(n)
# nach Auslastung ein. Zwei Zustaende, und der Unterschied ist Absicht:
#
#   ARBEITET      Farbverlauf weiss -> rot mit steigender Auslastung, auf
#                 der ganzen Leiste — unveraendert das Verhalten von vorher.
#                 Man soll von der Seite her sehen, dass die Maschine
#                 rechnet, ohne hinzusehen. Dieser Zustand wird SOFORT
#                 eingenommen, ohne Verzoegerung.
#   ARBEITET NICHT  nur DREI Segmente oben links, in Blau. Eine Karte, die
#                 nichts tut, soll nicht aussehen wie eine, die arbeitet —
#                 vorher war der Leerlauf volles Weiss, also die hellste
#                 Anzeige ueberhaupt fuer den Zustand, in dem am wenigsten
#                 passiert. Dieser Zustand braucht mehrere Messungen in
#                 Folge, siehe RUHE_BESTAETIGUNGEN weiter unten.
#
# DER BLAUTON IST GEMESSEN, NICHT AUSGESUCHT. Veikos Vorgabe war "derselbe
# Blauton wie die Steckdosenringe und die Anschalter der DEG-Docks". Der
# Ring der Shelly Plug S Gen3 laesst sich auslesen:
#     curl -s http://<ip>/rpc/PLUGS_UI.GetConfig
# Beide Dosen (192.168.178.159 und .161) melden am 05.09.2026
# leds.colors."switch:0".on.rgb = [0.0, 0.0, 100.0] bei Helligkeit 100 —
# also reines Blau ohne Rot- und Gruenanteil, 0000FF. Der Anschalter am
# DEG1 ist eine feste Leuchtdiode ohne Schnittstelle und damit nicht
# auslesbar; er wird hier NICHT als Beleg herangezogen, sondern nur die
# Dose. Steht am Ende ein anderer Blauton daneben, ist RUHE_FARBE die eine
# Stelle, an der er geaendert wird.
#
# Dieselbe Farbe zeigt das Cockpit nach (ledFarbe() im Layer, Kachel
# "RTX-LED") — die Rechnung steht deshalb zweimal, einmal hier in Python
# fuer die echte Leuchte, einmal im Layer in JavaScript fuer die Anzeige im
# Browser. Zwei getrennte Ausgaben (Hardware und Bildschirm) vertragen zwei
# Berechnungen; eine gemeinsame Datenquelle waere hier unnoetiger Aufwand
# fuer zwei Zeilen Code. Wer hier die Farbregel aendert, aendert sie dort
# mit — sonst zeigt der Bildschirm etwas anderes als die Karte.
#
# Lag bis zum 04.09.2026 nur unversioniert unter /usr/local/bin — wie
# vve-status.py und vve-admin.py vorher auch, aus demselben Grund jetzt
# hier im Repo: eine Datei, von der etwas Sichtbares abhaengt, sollte nicht
# nur an einer Stelle existieren, unversioniert und ausserhalb jeder
# Sicherung.
# ---------------------------------------------------------------------------
import os
import re
import subprocess
import sys
import time

ZUSTAND = "/etc/vve/rgb.state"
# Welche LED-Nummern im Leerlauf leuchten. Von Hand aenderbar, ohne dass
# dafuer ein Paket ausgeliefert werden muss: welche Nummer physisch oben
# links sitzt, sieht man nur, indem man die Karte ansieht — und wer davor
# steht, soll das ohne Entwicklungsrechner geradeziehen koennen.
# Eine Zeile, Nummern ab 0, z. B. "0,1,2" oder "5,6,7".
SEGMENT_DATEI = "/etc/vve/rgb.segmente"

RUHE_GRENZE = 5          # bis hierher gilt die Karte als "arbeitet nicht"
# Wie viele Messungen in Folge unter der Grenze liegen muessen, bevor auf
# Leerlauf umgeschaltet wird.
#
# GEMESSEN am 06.09.2026 an den Zeitstempeln im Journal: drei Messungen
# sind hier rund 15 Sekunden, nicht neun. Ein Takt kostet mehr als die
# blosse Wartezeit unten — nvidia-smi und vor allem openrgb (das bei jedem
# Aufruf erneut alle Geraete sucht) brauchen ihre Zeit. Wer die Zahl
# aendert, rechnet also nicht mit drei Sekunden je Schritt.
#
# 15 Sekunden sind lang genug, um jede Luecke zwischen zwei
# Antwortschritten zu ueberbruecken, und kurz genug, dass die Leiste nach
# dem Ende einer Anfrage nicht auffaellig nachleuchtet.
RUHE_BESTAETIGUNGEN = 3
RUHE_FARBE = "0000FF"    # gemessen an den Shelly-Ringen, siehe oben
RUHE_ANZAHL = 3          # drei Segmente
AUS = "000000"


def melde(text):
    """Eine Zeile ins Journal.

    Der Dienst laeuft als root und ist damit der einzige Ort, an dem sich
    die Beleuchtung ueberhaupt ansprechen laesst: /dev/i2c-* gehoert root
    und ist auf 0600 — ein Blick von einem gewoehnlichen Konto aus
    (vveadmin ueber ssh) findet KEINE Geraete und beweist deshalb gar
    nichts, weder in die eine noch in die andere Richtung. Was der Dienst
    tatsaechlich vorfindet, ist von aussen also nur ueber das Journal zu
    erfahren:  journalctl -u vve-rgb
    Deshalb wird der erkannte Aufbau einmal ausgeschrieben statt
    stillschweigend benutzt.
    """
    print(text, flush=True)


def gpu_last():
    """Hoechste Auslastung ueber ALLE erkannten Karten.

    Bis zur zweiten RTX 3090 (04.09.2026) lieferte nvidia-smi genau eine
    Zeile, und nur die erste zu lesen war kein Fehler. Seitdem liefert es
    eine Zeile je Karte — wer nur split("\\n")[0] nimmt, sieht die zweite
    Karte nie, egal wie sehr sie rechnet. Genommen wird das Maximum, nicht
    der Durchschnitt: die Leuchte soll reagieren, sobald IRGENDEINE Karte
    arbeitet, nicht erst wenn beide zusammen im Schnitt hoch liegen.

    Kein Wert lesbar heisst hier 0 und damit Leerlauf. Das ist bewusst die
    zurueckhaltende Annahme: eine Karte, ueber die nichts bekannt ist, als
    "unter Volllast" darzustellen waere eine Behauptung.
    """
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        werte = [int(z) for z in r.stdout.strip().split("\n") if z.strip()]
        return max(werte) if werte else 0
    except Exception:
        return 0


def gpu_lasten():
    """Auslastung JE KARTE, Schluessel ist die PCI-Adresse ("c5:00.0").

    16.10.2026: Veiko sah beide Leisten rot, obwohl nur eine Karte rechnete
    (ComfyUI auf Karte 2, die andere bei 0 %, Luefter aus). gpu_last() oben
    nimmt das Maximum und faerbt damit beide gleich. Jetzt bekommt jede
    Leiste die Last IHRER Karte. Die PCI-Adresse ist der Schluessel, weil
    OpenRGB und nvidia-smi verschieden nummerieren -- nachgesehen: OpenRGB [0]
    sitzt auf C6 (nvidia-smi 1), OpenRGB [1] auf C5 (nvidia-smi 0). Nach der
    Nummer zugeordnet haette genau die falsche Karte rot geleuchtet."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=pci.bus_id,utilization.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        out = {}
        for z in r.stdout.strip().split("\n"):
            teile = [t.strip() for t in z.split(",")]
            if len(teile) == 2 and teile[1].isdigit():
                out[teile[0].lower()[-7:]] = int(teile[1])
        return out
    except Exception:
        return {}


def farbe(last):
    # 0 % = weiss (FFFFFF), 100 % = rot (FF0000)
    wert = int(255 * (1 - last / 100))
    return f"FF{wert:02X}{wert:02X}"


def openrgb(*args, timeout=15):
    return subprocess.run(["openrgb", *args],
                          capture_output=True, text=True, timeout=timeout)


# --- Aufbau der Leuchten ---------------------------------------------------
# Fuer den Leerlauf reicht "eine Farbe fuer alles" nicht mehr: es sollen
# einzelne Segmente leuchten und der Rest dunkel bleiben. Dafuer muss man
# wissen, wie viele einzeln ansprechbare Punkte eine Karte ueberhaupt hat —
# das ist von Karte zu Karte verschieden (manche 3090 haben genau EINEN
# logischen Punkt, andere ein Dutzend), und geraten wird das hier nicht.
_aufbau = {"wann": 0.0, "geraete": None}
_ruhe_gezeigt = {"ja": False}
AUFBAU_TTL = 300


def aufbau_lesen():
    """Geraete, Zonen und LED-Zahl aus 'openrgb --list-devices'.

    Die Ausgabe unterscheidet sich zwischen OpenRGB-Fassungen, deshalb
    wird sie nachgiebig gelesen (Regeln auf Zeilenanfang, keine feste
    Reihenfolge) und beim ersten Mal ROH ins Journal geschrieben. Ein
    Parser, der still das Falsche versteht, waere hier besonders
    unangenehm: man saehe es der Karte nicht an, man saehe nur, dass
    "irgendwie nichts leuchtet".
    """
    if _aufbau["geraete"] is not None and time.time() - _aufbau["wann"] < AUFBAU_TTL:
        return _aufbau["geraete"]
    try:
        r = openrgb("--list-devices", timeout=25)
    except Exception as e:                                # noqa: BLE001
        melde(f"Geraete nicht abfragbar: {e}")
        return []
    roh = r.stdout or ""
    if _aufbau["geraete"] is None:
        # Genau einmal, damit im Journal nachlesbar ist, worauf sich alles
        # Weitere stuetzt. Gekuerzt, weil OpenRGB je Geraet die komplette
        # Modusliste ausgibt.
        melde("OpenRGB meldet (roh, gekuerzt):\n" + roh[:4000])

    geraete, jetzt = [], None
    for zeile in roh.splitlines():
        kopf = re.match(r"^\s*(\d+):\s*(.+?)\s*$", zeile)
        if kopf:
            jetzt = {"nr": int(kopf.group(1)), "name": kopf.group(2),
                     "zonen": [], "leds": 0}
            geraete.append(jetzt)
            continue
        if not jetzt:
            continue
        ort = re.match(r"^\s*Location:\s*I2C:\s*/dev/i2c-(\d+)", zeile)
        if ort:
            # Welche Karte? Der i2c-Bus traegt die PCI-Adresse im Namen
            # ("NVIDIA i2c adapter 1 at c6:00.0") -- dieselbe, die nvidia-smi meldet.
            try:
                with open(f"/sys/bus/i2c/devices/i2c-{ort.group(1)}/name") as f:
                    m = re.search(r"at ([0-9a-f]{2}:[0-9a-f]{2}\.\d)", f.read().lower())
                jetzt["pci"] = m.group(1) if m else None
            except OSError:
                jetzt["pci"] = None
            continue
        if re.match(r"^\s*Zones?:", zeile):
            # Namen mit Leerzeichen stehen in Anfuehrungszeichen, einzelne
            # Woerter nicht. Die 3090 hier meldet schlicht "Zones: Unknown"
            # — wer nur nach Anfuehrungszeichen sucht, zaehlt null Zonen und
            # schreibt das auch so ins Journal. Der Ablauf lief trotzdem
            # richtig (max(1, …) faengt es ab), aber ein Protokoll, das
            # "0 Zone(n)" behauptet, waere beim naechsten Fehlersuchen die
            # falsche Spur.
            rest = zeile.split(":", 1)[1]
            jetzt["zonen"] = (re.findall(r"'([^']*)'", rest)
                              or [w for w in rest.split() if w])
        elif re.match(r"^\s*LEDs?:", zeile):
            rest = zeile.split(":", 1)[1]
            jetzt["leds"] = len(re.findall(r"'([^']*)'", rest)
                                or [w for w in rest.split() if w])

    _aufbau["geraete"] = geraete
    _aufbau["wann"] = time.time()
    if geraete:
        melde("Erkannt: " + "; ".join(
            f"[{g['nr']}] {g['name']} — {g['leds']} LED, "
            f"{len(g['zonen'])} Zone(n), Karte {g.get('pci') or 'unbekannt'}" for g in geraete))
    else:
        melde("Keine RGB-Geraete erkannt. Ohne geladene i2c-Schnittstelle "
              "sieht OpenRGB die Grafikkarten nicht; die Beleuchtung bleibt "
              "dann so, wie die Karte sie von sich aus setzt.")
    return geraete


def segmente_gewuenscht(anzahl_leds):
    """Welche LED-Nummern im Leerlauf leuchten sollen.

    Vorgabe sind die ersten drei. Ob die physisch oben links sitzen, kann
    dieses Skript nicht wissen — die Reihenfolge in OpenRGB folgt der
    Verdrahtung der Karte, nicht der Blickrichtung. Wer davorsteht und
    sieht, dass es die falschen sind, traegt die richtigen in
    /etc/vve/rgb.segmente ein; das wirkt beim naechsten Durchlauf, ohne
    Auslieferung und ohne Neustart.
    """
    try:
        with open(SEGMENT_DATEI) as f:
            wunsch = [int(x) for x in re.findall(r"\d+", f.read())]
        if wunsch:
            return [i for i in wunsch if i < anzahl_leds]
    except Exception:                                     # noqa: BLE001
        pass
    return list(range(min(RUHE_ANZAHL, anzahl_leds)))


def setze_last(hexfarbe):
    """Eine Farbe fuer ALLE erkannten Geraete.

    OHNE --device, und das ist Absicht: stand bis zum 04.09.2026 fest auf
    "--device 0" — mit einer Karte war das dieselbe Karte, mit zwei blieb
    die zweite unangetastet und zeigte weiterhin nur die
    Werksbeleuchtung, waehrend die erste korrekt auf Auslastung
    reagierte. Mainboard- und RAM-RGB werden hier ohnehin nicht erkannt
    (siehe OpenRGB-Warnung beim Start), die einzigen Geraete, die "alle"
    trifft, sind die Grafikkarten.
    """
    openrgb("--mode", "direct", "--color", hexfarbe)


def setze_last_geraet(g, hexfarbe):
    """Die Lastfarbe fuer genau EINE Leiste (Gegenstueck zu setze_last)."""
    return openrgb("--device", str(g["nr"]), "--mode", "direct", "--color", hexfarbe)


def setze_ruhe(nur=None):
    """Drei Segmente blau, der Rest dunkel — je Karte einzeln.
    nur: eine Liste von Geraeten; ohne sie alle (bisheriges Verhalten).

    Anders als bei der Last-Faerbung geht das NICHT mit einem Aufruf fuer
    alles: eine Farbliste bezieht sich in OpenRGB auf die Punkte EINES
    Geraets, und beide Karten haben ihre eigene Nummerierung.

    Hat eine Karte weniger als drei ansprechbare Punkte, wird sie
    vollstaendig blau gefaerbt statt gar nicht — "drei Segmente" ist dann
    physisch nicht darstellbar, und eine Karte im Leerlauf dunkel zu
    lassen waere die schlechtere Naeherung: man koennte sie nicht mehr von
    einer ausgeschalteten unterscheiden.
    """
    geraete = aufbau_lesen()
    if not geraete:
        return False
    ok = True
    # Einmal den WIRKLICHEN Aufruf ins Journal. Ein Rueckgabewert 0 von
    # openrgb beweist naemlich nichts: derselbe Aufruf endet auch dann mit
    # 0, wenn ueberhaupt kein Geraet gefunden wurde (nachgestellt von einem
    # Konto ohne i2c-Rechte). Steht der Befehl samt Antwort im Protokoll,
    # laesst sich hinterher entscheiden, ob es an der Ansteuerung liegt
    # oder daran, dass die falschen Punkte gewaehlt wurden.
    zeigen = not _ruhe_gezeigt["ja"]
    for g in (nur if nur is not None else geraete):
        n = g["leds"]
        if n < RUHE_ANZAHL:
            r = openrgb("--device", str(g["nr"]), "--mode", "direct",
                        "--color", RUHE_FARBE)
        else:
            an = set(segmente_gewuenscht(n))
            liste = ",".join(RUHE_FARBE if i in an else AUS for i in range(n))
            # Mit --zone gilt die Farbliste je LED innerhalb der Zone;
            # ohne sie je Zone. Hat die Karte genau eine Zone, ist das
            # dasselbe — bei mehreren waere es das nicht, deshalb wird
            # jede Zone einzeln bedient.
            r = None
            for zi in range(max(1, len(g["zonen"]))):
                args = ("--device", str(g["nr"]), "--zone", str(zi),
                        "--mode", "direct", "--color", liste)
                r = openrgb(*args)
                if zeigen:
                    antwort = ((r.stdout or "") + (r.stderr or "")).strip()
                    antwort = "\n".join(
                        z for z in antwort.splitlines()
                        if "i2c_smbus" not in z and not z.startswith("<"))
                    melde("Leerlauf gesetzt: openrgb " + " ".join(args) +
                          f"\n  -> rc {r.returncode}, Antwort: " +
                          (antwort[:300] or "(keine)"))
        if r is not None and r.returncode != 0:
            ok = False
            melde(f"Leerlauf-Faerbung fuer [{g['nr']}] {g['name']} "
                  f"fehlgeschlagen (rc {r.returncode}): "
                  f"{(r.stderr or r.stdout or '').strip()[:200]}")
    _ruhe_gezeigt["ja"] = True
    return ok


def an():
    return not os.path.exists(ZUSTAND) or open(ZUSTAND).read().strip() != "off"


def main():
    melde("VVE GPU-Statusbeleuchtung startet. Ueber "
          f"{RUHE_GRENZE} % Auslastung sofort Verlauf weiss->rot auf der "
          f"ganzen Leiste; darunter nach {RUHE_BESTAETIGUNGEN} Messungen "
          f"{RUHE_ANZAHL} Segmente in #{RUHE_FARBE}.")
    letzte = {}            # je Leiste (OpenRGB-Nummer, oder "alle"): zuletzt gesetzter Zustand
    ruhe_zaehler = {}
    aus = False
    while True:
        if an():
            aus = False
            geraete = aufbau_lesen()
            lasten = gpu_lasten()
            # Je Karte, wenn sich JEDE Leiste ihrer Karte zuordnen laesst; sonst
            # wie bisher eine gemeinsame Farbe nach der hoechsten Last -- lieber
            # beide gleich als eine geratene Zuordnung, die die falsche Karte faerbt.
            if geraete and all(g.get("pci") in lasten for g in geraete):
                einheiten = [(g["nr"], g, lasten[g["pci"]]) for g in geraete]
            else:
                einheiten = [("alle", None, gpu_last())]
            for schluessel, g, last in einheiten:
                name = f"Karte {g['pci']} (Leiste {g['nr']})" if g else "Alle Karten"
                vorher = letzte.get(schluessel)
                # ASYMMETRISCH, UND DAS IST DER PUNKT: in den Lastverlauf wird
                # SOFORT gewechselt, in den Leerlauf erst nach mehreren
                # Messungen hintereinander.
                #
                # Grund: nvidia-smi liefert eine Momentaufnahme, keinen
                # Mittelwert. Waehrend Ollama antwortet, faellt die Auslastung
                # zwischen zwei Schritten (und besonders zwischen Einlesen und
                # Schreiben) durchaus kurz auf 0 % zurueck — bei einem Takt von
                # drei Sekunden trifft man das frueher oder spaeter. Ohne diese
                # Bestaetigung wuerde die Leiste mitten im Rechnen kurz auf
                # Blau springen, also genau das anzeigen, was gerade NICHT der
                # Fall ist. Dieselbe Ueberlegung wie beim Logo im Cockpit, das
                # deshalb ledFarbe(..., ohneRuhe) benutzt.
                #
                # Umgekehrt darf es keine Verzoegerung geben: fangen die Karten
                # an zu arbeiten, soll man das sofort sehen. Ein spaeter
                # Ausschlag waere hier der schlechtere Fehler — man sieht nicht
                # hin, weil "steht ja noch auf Leerlauf".
                if last > RUHE_GRENZE:
                    ruhe_zaehler[schluessel] = 0
                    zustand = farbe(last)
                else:
                    ruhe_zaehler[schluessel] = ruhe_zaehler.get(schluessel, 0) + 1
                    zustand = "ruhe" if ruhe_zaehler[schluessel] >= RUHE_BESTAETIGUNGEN else vorher
                if zustand is not None and zustand != vorher:
                    if zustand == "ruhe":
                        setze_ruhe([g] if g else None)
                        melde(f"{name}: Leerlauf ({last} % ueber {RUHE_BESTAETIGUNGEN} Messungen): "
                              f"{RUHE_ANZAHL} Segmente in #{RUHE_FARBE}")
                    else:
                        setze_last_geraet(g, zustand) if g else setze_last(zustand)
                        melde(f"{name}: Arbeitet ({last} %): ganze Leiste #{zustand}")
                    letzte[schluessel] = zustand
        else:
            if not aus:
                openrgb("--mode", "off")
                aus, letzte, ruhe_zaehler = True, {}, {}
        time.sleep(3)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
