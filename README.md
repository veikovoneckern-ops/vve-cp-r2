# VVE Cockpit Release 2 (`vve-cp-r2`)

Eigenes Projekt neben Release 1. Alter Bestand: `vve-cp`, Site `https://cockpit.vveorgxais.org`.
Neue Site spaeter: `https://cockpit-v1-r2.vveorgxais.org`. Dieses Repo aendert Caddy nicht.

## Lokal starten

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export VVEC_OLLAMA=http://127.0.0.1:11434
export VVEC_NEO_MODELL=qwen3.6:27b
python3 server.py
```

Dann im Browser: `http://127.0.0.1:8780`

Ohne Ollama startet die Huelle trotzdem. Neo sagt dann ehrlich, dass das Modell nicht erreichbar ist.

## Was Iteration 1 kann

- Leiste: Start, Themen, Stab, Eingang, Reports, Server, Einstellungen
- Arbeitsschild oben bei jedem Ortswechsel
- Schrift und Hell/Dunkel in Einstellungen (gespeichert unter `daten/einstellungen.json`)
- Gespraech auf der Startseite, standardmaessig mit **Neo**
- Neo liest den Dateibaum, schlaegt Aenderungen vor, spielt sie erst nach dem Knopf "Einspielen"

## Was bewusst fehlt

Jason-Autonomie, Whisper/Piper, Comfy-Erzeugen, Org-Chart-Ziehen, Plaud-Abzug, Caddy, Graph-Sicherung verdrahtet.

Sicherung soll spaeter in die OneDrive-**Cloud** (Graph), nie nach `C:\`.
