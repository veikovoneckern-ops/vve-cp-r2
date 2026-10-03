"""
Alle Einstellungen an EINER Stelle. Werte kommen aus der Umgebung
(~/.config/vve-cp-r2.env auf dem Server), sonst gelten die Vorgaben.

Bewusst keine Geheimnisse hier: die neue Fassung laeuft als vveadmin und kann
/etc/vvec/secrets.env nicht lesen. Was einen Schluessel braucht (Cloud-Modelle,
SMTP), sagt das offen, statt still zu fehlen.
"""
from __future__ import annotations

import os
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
FRONTEND = WURZEL / "frontend"
DATEN = Path(os.environ.get("VVEC_NEU_DATEN", str(WURZEL / "daten")))
DB_DATEI = DATEN / "cockpit.sqlite"
UPLOADS = DATEN / "uploads"
ERGEBNIS_DIR = DATEN / "ergebnisse"
VORSCHAU_DIR = DATEN / "vorschau"
BENUTZER_DATEI = DATEN / "benutzer.json"

# Der alte Bestand -- wird NUR GELESEN. Die neue Fassung schreibt dort nie.
ALT_DATEN = Path(os.environ.get("VVEC_ALT_DATEN", "/var/lib/vvec"))
ALT_STATE = ALT_DATEN / "cockpit-state.json"
ALT_VORGAENGE = ALT_DATEN / "vorgaenge.json"
PLAUD_DIR = ALT_DATEN / "plaud"
ALT_ROLLEN = Path(os.environ.get("VVEC_ALT_ROLLEN", "/opt/vvec/team_rollen.json"))

HOST = os.environ.get("VVEC_HOST", "127.0.0.1")
PORT = int(os.environ.get("VVEC_PORT", "8790"))

OLLAMA = os.environ.get("VVEC_OLLAMA", "http://127.0.0.1:11434").rstrip("/")
PIPER = os.environ.get("VVEC_PIPER", "http://127.0.0.1:5050").rstrip("/")
PIPER_STIMME = os.environ.get("VVEC_PIPER_STIMME", "kerstin")
SEARX = os.environ.get("VVEC_SEARX", "http://127.0.0.1:8888").rstrip("/")
STATUS_URL = os.environ.get("VVEC_STATUS_URL", "http://127.0.0.1:9099").rstrip("/")
ALT_BACKEND = os.environ.get("VVEC_ALT_BACKEND", "http://127.0.0.1:8770").rstrip("/")
# Cockpit-Token des alten Backends -- NUR fuer dessen Wartungsdienst (Ollama-Update
# laeuft dort als root; vveadmin hat dafuer kein sudo). Einmal von Veiko in
# ~/.config/vve-cp-r2.env eingetragen, sonst leer: dann steht dort der Einrichtungsbefehl.
ALT_TOKEN = os.environ.get("VVEC_ALT_TOKEN", "").strip()
# Adresse des alten Cockpits, fuer Links aus dem Bereich System dorthin.
ALT_COCKPIT_URL = os.environ.get("VVEC_ALT_COCKPIT_URL", "https://vveorgxais.tail4ca1ab.ts.net/")

# large-v3-turbo statt small (03.10.2026): small hoerte englische Woerter im deutschen
# Satz ("Briefing", "Use Case") oft falsch. Turbo ist auf der Karte kaum langsamer
# und braucht rund 1,6 GB VRAM. Laedt es nicht, faellt stimme.py auf medium/small zurueck.
WHISPER_MODELL = os.environ.get("VVEC_WHISPER_MODELL", "large-v3-turbo")
WHISPER_GERAET = os.environ.get("VVEC_WHISPER_GERAET", "cuda")

# Vorgaben fuer Modelle, falls im Team nichts eingetragen ist.
MODELL_STAB = os.environ.get("VVEC_MODELL_STAB", "llama3.3:70b")
MODELL_ARBEIT = os.environ.get("VVEC_MODELL_ARBEIT", "qwen3.8:27b")
MODELL_TALK = os.environ.get("VVEC_MODELL_TALK", "qwen3.8:27b")
MODELL_NEO = os.environ.get("VVEC_NEO_MODELL", "qwen3-coder-neo:30b")

STAB_TAKT_SEK = int(os.environ.get("VVEC_STAB_TAKT", "120"))
COOKIE_SICHER = os.environ.get("VVEC_COOKIE_SICHER", "true").strip().lower() == "true"

# Bilder und Visualisierungen aus dem Gespraech (medien.py).
MEDIEN_DIR = DATEN / "medien"
COMFY = os.environ.get("VVEC_COMFY", "http://127.0.0.1:8188").rstrip("/")
# Der WatchDog (vve-health, laeuft als vveadmin wie diese Fassung) liest Notfall-
# Anfragen auch aus seinem eigenen Ordner -- dorthin schreibt diese Fassung.
HEALTH_DIR = Path(os.environ.get("VVEC_HEALTH_DIR", "~/vve-health")).expanduser()

for _d in (DATEN, UPLOADS, ERGEBNIS_DIR, VORSCHAU_DIR, MEDIEN_DIR):
    _d.mkdir(parents=True, exist_ok=True)
