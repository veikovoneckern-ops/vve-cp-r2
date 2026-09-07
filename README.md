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

### Neo wahlweise ueber Claude statt lokal

Vorgabe bleibt der lokale Ollama (digitale Souveraenitaet, kein Token-Preis). Wer Neo stattdessen
mit Claude laufen lassen will:

```bash
export VVEC_NEO_ANBIETER=claude
export ANTHROPIC_API_KEY=sk-ant-...
export VVEC_NEO_CLAUDE_MODELL=claude-sonnet-5   # genaue Modell-ID eintragen
```

Fehlt einer der beiden letzten Werte, meldet Neo das im Gespraech klar statt zu raten.

## Was Iteration 2 kann

- Leiste: Start, Themen, Stab, Eingang, Reports, Server, Einstellungen
- Arbeitsschild oben bei jedem Ortswechsel
- Schrift und Hell/Dunkel in Einstellungen (gespeichert unter `daten/einstellungen.json`)
- Gespraech auf der Startseite, standardmaessig mit **Neo**
- **Neo arbeitet jetzt mit echten Werkzeugen**, nicht mehr mit einem einzelnen Textblock: er kann
  den Dateibaum auflisten, einzelne Dateien lesen, das Projekt durchsuchen und -- erst danach --
  eine vollstaendige neue Fassung einer Datei vorschlagen. Mehrere Werkzeugaufrufe hintereinander
  sind moeglich (bis zu `VVEC_NEO_MAX_SCHRITTE`, Vorgabe 8), bevor er antwortet. Jede Antwort zeigt
  aufklappbar, welche Schritte er dafuer gemacht hat.
- Geschrieben wird weiterhin **nichts von allein** -- ein Vorschlag landet erst nach Klick auf
  "Einspielen" auf der Platte, und nur innerhalb der erlaubten Pfade (`server.py`, `frontend/`,
  `anforderungen/`, `doku/`, `tests/`, `werkzeug/`, `systemd/`, `rollen.json`, `requirements.txt`,
  `README.md`, `STATUS.md`, `.gitignore`). `daten/` ist gesperrt, das ist Laufzeitbestand.

## Was bewusst fehlt

Jason-Autonomie, Whisper/Piper, Comfy-Erzeugen, Org-Chart-Ziehen, Plaud-Abzug, Caddy, Graph-Sicherung
verdrahtet, ein eigenes Shell-Werkzeug fuer Neo (bewusst nicht gebaut, siehe STATUS.md).

Sicherung soll spaeter in die OneDrive-**Cloud** (Graph), nie nach `C:\`.
