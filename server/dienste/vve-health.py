#!/usr/bin/env python3
"""VVE Health-Watchdog — prueft GPU-Temperatur und Kern-Dienste, greift bei
einer echten Gefahr selbst ein, statt nur zu melden.

ANLASS (10.09.2026): Veiko ist oft nicht in der Naehe seines Setups und
wollte eine Instanz, die selbststaendig erkennt, wenn etwas nicht stimmt,
und im Ernstfall auch selbst eingreift — nicht nur eine Anzeige.

ZWEI STUFEN, UNTERSCHIEDLICH SCHARF:

  WEICH  — ein Dienst antwortet nicht (Ollama, Caddy, ComfyUI-Container).
           Wird automatisch neu gestartet, sonst nichts. Geringes Risiko,
           genau wie ein haengendes Programm neu zu starten.

  HART   — eine Grafikkarte ist zu heiss (VVEC_HEALTH_TEMP_C, Vorgabe 90 C).
           Zuerst auf 85 C gesetzt, von Veiko am 10.09.2026 auf 90 C
           angehoben, nachdem die erste echte Messung zeigte, dass die
           Karten im Alltag weit darunter bleiben (41/38 C bei normaler
           Last) — 85 C war also unnoetig vorsichtig gegenueber der
           tatsaechlichen Drosselgrenze der RTX 3090 (~90-93 C). Der
           Wert liegt damit bewusst NAH an der Drosselgrenze, nicht mehr
           deutlich darunter — das ist Veikos ausdruecklicher Wunsch,
           kein Versehen.
           Das Kappen und Wiedereinschalten der Docks allein reicht NICHT,
           um die Karten sauber zurueckzubekommen (live geprueft am
           10.09.2026: nvidia-smi fand sie danach nicht mehr, obwohl der
           PCI-Bus sie schon sah — der Treiber braucht einen echten
           Neustart). Der Ablauf ist deshalb: Dock-Strom aus, abkuehlen
           lassen, Dock-Strom an, warten, dann die SERVER-Steckdose selbst
           kurz aus und automatisch wieder an (shelly_server_zyklus(),
           Shelly toggle_after — der Server kann sich diesen letzten
           Schritt nicht selbst geben, siehe die Begruendung dort).

           GEAENDERT AM 11.09.2026 — UND DAMIT EIN BEWUSST AUFGEGEBENER
           KOMPROMISS: bis dahin endete der Ablauf mit einem blossen
           "sudo reboot" (Software-Neustart, die Server-Steckdose blieb
           die ganze Zeit an) — ausdruecklich DESHALB, damit der Mini-PC
           und mit ihm dieses Cockpit waehrend des ganzen Vorgangs fuer
           die Fernwartung erreichbar bleiben. Ein echter Test zeigte
           aber: nach dem blossen Neustart brauchten Ollama und ComfyUI
           mehrere Anlaeufe, kurz danach gab es einen zweiten, ungeplanten
           Neustart — erst ein ECHTES Aus-und-wieder-Einschalten der
           Server-Steckdose von Hand brachte alles zuverlaessig zurueck.
           Genau das bildet der Ablauf jetzt automatisch nach. Der Preis:
           fuer die Dauer von SERVER_WIEDERANLAUF_SEK ist auch der Mini-PC
           selbst nicht erreichbar, nicht nur die Karten — wer waehrenddessen
           nach dem Rechten sehen will, kommt in diesem Fenster nur ueber
           die Shelly-App an die Steckdose, nicht ueber das Cockpit.
           toggle_after ist ein dokumentiertes Shelly-Gen2/3-RPC-Feld, auf
           DIESEM Geraet aber noch nicht real erprobt — der Rueckfallweg,
           falls es nicht wie erwartet wirkt, ist derselbe wie am
           11.09.2026 von Hand: Server-Steckdose in der Shelly-App wieder
           einschalten.

           Dass ein echter Steckdosenzyklus danach zuverlaessig alles
           zurueckbringt, OHNE einen Knopf vor Ort, ist am 10.09.2026
           zweimal echt getestet (dort noch als reiner Server-Steckdosen-
           test, Docks liefen durchgehend) — Voraussetzung dafuer war eine
           BIOS-Einstellung (AMD CBS > FCH Common Options > AC Power Loss
           Options > AC Loss Control = "Always On"), die Veiko an diesem
           Tag gesetzt hat. Ohne sie bootet der Server nach dem
           Stromwechsel nicht von selbst, und dieser Ablauf liefe ins
           Leere.

KEIN ZWEITER NOTFALL INNERHALB VON WIEDERHOLUNG_SPERRE: Bleibt die Karte
nach einem Notfall-Neustart weiter zu heiss (z.B. ein wirklicher
Kuehlungsdefekt statt nur zu viel Last), waere ein zweiter automatischer
Neustart binnen Minuten kein Fix mehr, sondern eine Neustart-Schleife.
Ab dem zweiten Auftreten innerhalb der Sperrzeit bleibt der Dock-Strom
AUS und die Automatik haelt an — das ist dann ein echter Defekt, der
einen Menschen braucht, kein Software-Problem mehr.

Laeuft als eigener, dauerhafter Dienst (wie vve-rgb.py), nicht als Timer:
die Temperaturpruefung muss schnell genug sein, um eine echte Gefahr
rechtzeitig zu erkennen, haeufige Prozess-Neustarts waeren nur Ballast.
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

## NICHT /var/lib/vvec: das gehoert vvec:vvec mit 755 -- vveadmin (dieser
## Dienst laeuft als vveadmin, siehe vve-health.service) hat dort keinen
## Schreibzugriff. Live geprueft (10.09.2026): "Permission denied:
## /var/lib/vvec/health-status.tmp" bei jedem Durchlauf. Eine gemeinsame
## Gruppe wie beim Werkstatt-Verzeichnis waere eine weitere root-Aktion
## nur fuer dieses eine Feature; das eigene Home-Verzeichnis braucht
## keine. vve-status.py (anderer Nutzer) liest trotzdem mit -- die Datei
## wird unten ausdruecklich world-readable gesetzt (644/755), nicht der
## ererbten umask ueberlassen.
DATEN_DIR = Path(os.getenv("VVEC_HEALTH_DIR", os.path.expanduser("~/vve-health")))
STATUS_DATEI = DATEN_DIR / "health-status.json"

TAKT_SEK = 15
TEMP_NOTFALL_C = float(os.getenv("VVEC_HEALTH_TEMP_C", "90"))
AUTO_AN = os.getenv("VVEC_HEALTH_AUTO", "1") != "0"

ABKUEHL_SEK = 90          # Dock-Strom bleibt so lange aus, bevor er zurueckkommt
DOCK_STABIL_SEK = 10      # Wartezeit nach Dock-Strom-an, bevor der Server neu startet
WIEDERHOLUNG_SPERRE_SEK = 15 * 60   # zweiter Notfall in dieser Zeit -> Automatik haelt an

# Kill Switch / Safety Shutdown & Reboot aus dem Cockpit: das Backend
# (Nutzer vvec) kann nicht ins Home-Verzeichnis von vveadmin schreiben
# (derselbe Rechte-Graben wie beim Statusstand, nur umgekehrt) — die
# Anfrage liegt deshalb dort, wo vvec
# schon Schreibrechte hat: /var/lib/vvec, das dieser Dienst nur LESEND
# anfasst. Verarbeitet wird ueber einen Zeitstempel-Vergleich, nicht durch
# Loeschen der Anfrage-Datei — vveadmin darf in einem fremden Verzeichnis
# lesen (755), aber nicht darin loeschen (dafuer fehlt das Schreibrecht
# auf den ELTERN-Ordner).
ANFRAGE_DATEI = Path("/var/lib/vvec/health-notfall-anfrage.json")
# Zweiter Briefkasten fuer die neue Fassung des Cockpits (vve-cp-r2, 01.10.2026):
# sie laeuft als vveadmin und darf nicht nach /var/lib/vvec schreiben, wohl
# aber in den eigenen Ordner dieses Dienstes. Gleiches Format, gleiche
# Positivliste der Arten; der Ablauf danach ist fuer beide Briefkaesten
# DERSELBE -- es gibt nur eine Notabschaltung.
ANFRAGE_DATEIEN = (ANFRAGE_DATEI, DATEN_DIR / "notfall-anfrage.json")

# Dieselbe Shelly-Adresse wie vve-status.py (power.dock) — absichtlich hier
# noch einmal eingetragen statt importiert: vve-status.py bleibt rein
# lesend, dieses Skript ist das einzige mit Schreibzugriff auf die
# Steckdose, und die beiden sollen unabhaengig voneinander lauffaehig
# bleiben, auch wenn eines der beiden Skripte fehlerhaft ist.
DOCK_HOST = os.getenv("VVEC_SHELLY_DOCK_IP", "192.168.178.161")
# Dieselbe Adresse wie vve-status.py unter power.server (dort als Name
# "MINISFORUM" aufgeloest, siehe _SHELLY_IP) — hier direkt die IP, aus
# demselben Unabhaengigkeits-Grund wie bei DOCK_HOST.
SERVER_HOST = os.getenv("VVEC_SHELLY_SERVER_IP", "192.168.178.159")
# Wie lange die Server-Steckdose nach dem Kappen aus bleibt, bevor der
# Shelly sie SELBST wieder einschaltet (toggle_after, siehe unten) —
# grosszuegig ueber die ueblichen Sekunden eines Hard-Resets, damit
# Netzteil und Board wirklich spannungsfrei waren.
SERVER_WIEDERANLAUF_SEK = 15
SHELLY_TIMEOUT = 3.0

DIENSTE_WEICH = {
    # name -> (Pruef-URL, Startbefehl)
    "ollama": ("http://127.0.0.1:11434/api/tags", ["sudo", "-n", "systemctl", "restart", "ollama"]),
    "caddy": ("http://127.0.0.1:8000/", ["sudo", "-n", "systemctl", "restart", "caddy"]),
    "comfyui": ("http://127.0.0.1:8188/queue", ["docker", "restart", "comfyui"]),
}
DIENST_TIMEOUT = 4.0


def _jetzt():
    return time.time()


def _lesen():
    try:
        return json.loads(STATUS_DATEI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _schreiben(stand):
    """Atomar wie ueberall sonst im Projekt (.tmp + replace) — ein halb
    geschriebener Stand waere schlimmer als ein alter. Rechte werden
    ausdruecklich gesetzt statt der ererbten umask ueberlassen — vve-
    status.py liest als ANDERER Nutzer mit, ein zu enges Verzeichnis
    liesse die Anzeige im Cockpit still auf "unbekannt" stehen."""
    DATEN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DATEN_DIR, 0o755)
    except OSError:
        pass
    tmp = STATUS_DATEI.with_suffix(".tmp")
    tmp.write_text(json.dumps(stand, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATUS_DATEI)
    try:
        os.chmod(STATUS_DATEI, 0o644)
    except OSError:
        pass


def gpu_temps():
    """[(index, temp_c), ...] — leer, wenn nvidia-smi nichts liefert (z.B.
    weil die Karten gerade stromlos sind, mitten im eigenen Notfallablauf)."""
    try:
        roh = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8)
        aus = []
        for zeile in roh.stdout.strip().splitlines():
            teile = [t.strip() for t in zeile.split(",")]
            if len(teile) == 2 and teile[1].isdigit():
                aus.append((int(teile[0]), int(teile[1])))
        return aus
    except (OSError, subprocess.SubprocessError):
        return []


def dienst_antwortet(url):
    try:
        with urllib.request.urlopen(url, timeout=DIENST_TIMEOUT) as ant:
            return 200 <= ant.status < 500   # 4xx ist "lebt", nur 5xx/Timeout nicht
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def shelly_schalten(host, an):
    """POST-artiger RPC-Aufruf ueber GET, wie Shelly Gen3 es anbietet.
    Gibt zurueck, ob der Aufruf angekommen ist — NICHT, ob die Steckdose
    wirklich geschaltet hat (das wird danach ueber GetStatus geprueft)."""
    url = "http://%s/rpc/Switch.Set?id=0&on=%s" % (host, "true" if an else "false")
    try:
        with urllib.request.urlopen(url, timeout=SHELLY_TIMEOUT) as ant:
            json.loads(ant.read().decode("utf-8", "replace"))
        return True
    except Exception as e:
        _protokoll("Shelly-Schaltung fehlgeschlagen (%s -> %s): %s" % (host, an, e))
        return False


def shelly_server_zyklus(host, nach_sek):
    """Server-Steckdose SOFORT aus, automatischer Wiederanlauf nach
    nach_sek Sekunden — ueber die Shelly-eigene toggle_after-Funktion
    (Gen2/Gen3-RPC, Switch.Set mit toggle_after), NICHT ueber ein zweites
    time.sleep()+shelly_schalten() hier im Skript.

    DER GRUND, WARUM DAS SO SEIN MUSS: dieses Skript LAEUFT AUF DEM
    SERVER. Sobald die Steckdose wirklich aus ist, stirbt der Prozess
    mit — er koennte ein "warte 15s, dann wieder an" niemals selbst zu
    Ende bringen. Der Shelly selbst haengt an der Wand und bleibt dabei
    am Strom; die Verzoegerung muss deshalb in SEINER Firmware stecken.

    ANLASS (11.09.2026): der bisherige letzte Schritt war ein blosses
    "sudo reboot" (Software-Neustart, die Steckdose blieb die ganze Zeit
    an). Bei einem echten Test brauchten Ollama/ComfyUI danach mehrere
    Anlaeufe, kurz darauf gab es einen zweiten, ungeplanten Neustart —
    Veiko musste von Hand eingreifen (Server-Steckdose selbst aus und
    wieder ein), und DAS funktionierte zuverlaessig. Genau das bildet
    dieser Aufruf jetzt automatisch nach: ein echter Steckdose-Zyklus
    statt eines blossen OS-Neustarts.

    UNGETESTETER SCHRITT, ausdruecklich markiert: toggle_after ist ein
    dokumentiertes Shelly-Gen2/3-RPC-Feld, aber auf DIESEM Geraet noch
    nicht real erprobt. Schlaegt es fehl oder unterstuetzt die Firmware
    es nicht, bleibt der Server AUS — der Rueckfallweg ist dann derselbe
    wie am 11.09.2026: die Server-Steckdose in der Shelly-App von Hand
    wieder einschalten."""
    url = ("http://%s/rpc/Switch.Set?id=0&on=false&toggle_after=%d"
           % (host, nach_sek))
    try:
        with urllib.request.urlopen(url, timeout=SHELLY_TIMEOUT) as ant:
            json.loads(ant.read().decode("utf-8", "replace"))
        return True
    except Exception as e:
        # Erwartbar: der Prozess (und mit ihm diese Verbindung) kann
        # mitten in der Antwort sterben, sobald die Steckdose tatsaechlich
        # aus geht — das ist dann kein Fehlschlag der Schaltung selbst.
        _protokoll("Server-Steckdosenzyklus (%s): %s — falls die Steckdose "
                   "trotzdem aus ging, war das erwartbar (der Prozess stirbt "
                   "mit ihr)" % (host, e))
        return False


def _protokoll(text):
    print("[vve-health] %s" % text, flush=True)


def _reparieren(name, url, befehl):
    if dienst_antwortet(url):
        return None
    _protokoll("%s antwortet nicht — starte neu: %s" % (name, " ".join(befehl)))
    try:
        subprocess.run(befehl, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return "%s: Neustart fehlgeschlagen (%s)" % (name, e)
    return "%s neu gestartet (antwortete nicht)" % name


def _sicherer_zyklus(grund, temps, stand):
    """Der eigentliche, sichere Ablauf — gemeinsamer Kern fuer den
    AUTOMATISCHEN Notfall (_notfall_ausloesen) und den manuellen Knopf
    "Safety Shutdown & Reboot" (_safety_shutdown_reboot): Dock-Strom aus,
    abkuehlen, Dock-Strom an, stabilisieren, Server-Steckdose zyklisch
    (Shelly toggle_after, siehe shelly_server_zyklus() fuer die
    Begruendung) — ein reiner Software-Neustart reichte am 11.09.2026
    nicht zuverlaessig, der echte Steckdosenzyklus schon."""
    eintrag = {"zeit": _jetzt(), "grund": grund, "temps": temps, "wiederholt": False}

    _protokoll("%s — kappe Dock-Strom" % grund)
    shelly_schalten(DOCK_HOST, False)
    eintrag["aktion"] = "dock-strom-aus"
    _schreiben({**stand, "notfall": eintrag})

    time.sleep(ABKUEHL_SEK)

    _protokoll("Dock-Strom wieder an, warte auf Stabilisierung")
    shelly_schalten(DOCK_HOST, True)
    time.sleep(DOCK_STABIL_SEK)

    _protokoll("Server-Steckdose kappen, automatischer Wiederanlauf in %d s "
               "(Shelly toggle_after)" % SERVER_WIEDERANLAUF_SEK)
    eintrag["aktion"] = "dock-strom-an-server-steckdosenzyklus"
    _schreiben({**stand, "notfall": eintrag})
    shelly_server_zyklus(SERVER_HOST, SERVER_WIEDERANLAUF_SEK)


def _notfall_ausloesen(grund, temps):
    """AUTOMATISCHE Ausloesung bei echter Ueberhitzung. Bleibt bewusst
    unveraendert samt Wiederholungssperre (WIEDERHOLUNG_SPERRE_SEK): ein
    zweiter echter Notfall binnen 15 Minuten ist vermutlich ein
    Kuehlungsdefekt, kein Software-Fix mehr — Strom bleibt dann AUS, ein
    Mensch muss hinsehen. Diese automatische Erkennung ist von den beiden
    manuellen Knoepfen (Kill Switch, Safety Shutdown & Reboot) unberuehrt
    und laeuft unveraendert im Hintergrund weiter."""
    stand = _lesen()
    letzter = (stand.get("notfall") or {}).get("zeit")
    wiederholt = bool(letzter) and (_jetzt() - letzter) < WIEDERHOLUNG_SPERRE_SEK

    if wiederholt:
        _protokoll("ZWEITER Notfall binnen %d Min — Automatik haelt an, "
                   "Dock-Strom bleibt AUS: %s" % (WIEDERHOLUNG_SPERRE_SEK // 60, grund))
        eintrag = {"zeit": _jetzt(), "grund": grund, "temps": temps,
                   "wiederholt": True, "aktion": "dock-strom-aus-automatik-gestoppt"}
        shelly_schalten(DOCK_HOST, False)
        _schreiben({**stand, "notfall": eintrag, "automatik_angehalten": True})
        return

    _sicherer_zyklus("NOTFALL: %s" % grund, temps, stand)


def _kill_switch_ausloesen(stand):
    """Kill Switch (11.09.2026) — Veikos ausdruecklicher Wunsch nach einem
    Knopf, der WIRKLICH sofort alles abschaltet: ohne Abkuehlpause und
    OHNE automatischen Wiederanlauf. Anders als _sicherer_zyklus() bleibt
    die Server-Steckdose deshalb bewusst OHNE toggle_after aus —
    zurueckgeholt wird nur von Hand (Shelly-App), genau wie bei einem
    echten Not-Aus-Schalter."""
    _protokoll("KILL SWITCH — manuell ausgeloest: Dock- UND Server-Strom "
               "sofort aus, kein automatischer Wiederanlauf")
    eintrag = {"zeit": _jetzt(), "grund": "Kill Switch manuell ausgeloest",
               "temps": gpu_temps(), "wiederholt": False, "aktion": "kill-switch"}
    _schreiben({**stand, "notfall": eintrag})
    # Reihenfolge ist Absicht: Dock zuerst (unkritisch), Server zuletzt --
    # danach stirbt dieser Prozess mit dem Server, es kaeme ohnehin nichts
    # mehr danach.
    shelly_schalten(DOCK_HOST, False)
    shelly_schalten(SERVER_HOST, False)


def _safety_shutdown_reboot(stand):
    """Manueller Knopf "Safety Shutdown & Reboot" — derselbe echte Ablauf
    wie ein automatischer Notfall (_sicherer_zyklus), aber OHNE
    Wiederholungssperre: eine bewusste menschliche Entscheidung soll
    nicht daran scheitern, dass kurz zuvor schon einmal einer lief. Hebt
    eine haengengebliebene automatik_angehalten-Sperre gleich mit auf —
    wer diesen Knopf drueckt, hat die Lage selbst beurteilt."""
    stand = dict(stand)
    stand["automatik_angehalten"] = False
    _sicherer_zyklus("Manuell ausgeloest: Safety Shutdown & Reboot",
                     gpu_temps(), stand)


def _manuelle_anfrage_neu(stand):
    """Liegt eine noch nicht verarbeitete Anfrage aus dem Cockpit vor?
    Gibt (zeitstempel, art) zurueck oder None. art ist "neustart" (Safety
    Shutdown & Reboot) oder "kill" (Kill Switch) — eine Positivliste,
    dieselbe Haltung wie bei der Wartung: in der Anfrage steht eine ART,
    niemals ein Befehl.

    Vergleich per Zeitstempel statt Datei-Vorhandensein: die Anfrage-Datei
    kann dieser Dienst nicht loeschen (siehe ANFRAGE_DATEI), sie bliebe
    also fuer immer liegen und wuerde bei "existiert die Datei" jedesmal
    erneut ausloesen."""
    # Zwei Briefkaesten, ein Zeitstempel: verarbeitet wird nur, was NEUER ist
    # als die zuletzt verarbeitete Anfrage -- mit "ungleich" loeste die aeltere
    # Anfrage des anderen Briefkastens danach erneut aus.
    letzte = stand.get("letzte_anfrage_verarbeitet") or 0
    beste = None
    for datei in ANFRAGE_DATEIEN:
        try:
            anfrage = json.loads(datei.read_text(encoding="utf-8"))
            gestellt = float(anfrage.get("angefordert_um") or 0)
            art = anfrage.get("art")
        except (OSError, ValueError, TypeError):
            continue
        if gestellt <= letzte or art not in ("neustart", "kill"):
            continue
        if beste is None or gestellt > beste[0]:
            beste = (gestellt, art)
    return beste


def _durchlauf():
    stand = _lesen()
    automatik_angehalten = bool(stand.get("automatik_angehalten"))

    temps = gpu_temps()
    max_temp = max((t for _, t in temps), default=None)

    reparaturen = []
    for name, (url, befehl) in DIENSTE_WEICH.items():
        vermerk = _reparieren(name, url, befehl)
        if vermerk:
            reparaturen.append(vermerk)

    neuer_stand = {
        "zeit": _jetzt(),
        "gpu_temps": [{"index": i, "temp_c": t} for i, t in temps],
        "max_temp_c": max_temp,
        "schwelle_c": TEMP_NOTFALL_C,
        "auto_an": AUTO_AN,
        "automatik_angehalten": automatik_angehalten,
        "reparaturen": reparaturen,
        "notfall": stand.get("notfall"),
        "letzte_anfrage_verarbeitet": stand.get("letzte_anfrage_verarbeitet"),
    }

    manuell = _manuelle_anfrage_neu(stand)
    if manuell:
        # Beide manuellen Wege wirken UNABHAENGIG von automatik_angehalten:
        # Kill Switch soll immer sofort greifen, und Safety Shutdown &
        # Reboot hebt die Sperre selbst auf (siehe _safety_shutdown_reboot)
        # -- anders als frueher beim blossen "Test", der die Sperre
        # respektierte.
        zeitstempel, art = manuell
        neuer_stand["letzte_anfrage_verarbeitet"] = zeitstempel
        _schreiben(neuer_stand)   # merken, BEVOR der Ablauf laeuft (der kann den Prozess beenden)
        if art == "kill":
            _kill_switch_ausloesen(neuer_stand)
        else:
            _safety_shutdown_reboot(neuer_stand)
        return

    if AUTO_AN and not automatik_angehalten and max_temp is not None and max_temp >= TEMP_NOTFALL_C:
        _notfall_ausloesen("GPU-Temperatur %d C >= Schwelle %d C" % (max_temp, TEMP_NOTFALL_C), temps)
        return   # _notfall_ausloesen hat den Stand schon geschrieben (mehrfach, live)

    _schreiben(neuer_stand)


def main():
    _protokoll("Start — Takt %ds, Notfallschwelle %.0f C, Automatik %s"
              % (TAKT_SEK, TEMP_NOTFALL_C, "an" if AUTO_AN else "aus (nur Beobachtung)"))
    while True:
        try:
            _durchlauf()
        except Exception as e:
            _protokoll("Durchlauf fehlgeschlagen, naechster Versuch in %ds: %s" % (TAKT_SEK, e))
        time.sleep(TAKT_SEK)


if __name__ == "__main__":
    main()
