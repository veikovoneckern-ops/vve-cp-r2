# VvE Cockpit — neue Fassung

Die übersichtliche Neufassung des VvE Cockpits. Sie läuft **parallel** zum alten Cockpit (Repo `vve-cp`) und fasst es nicht an: eigener Dienst, eigener Port, eigene Datenbank. Den alten Bestand liest sie nur.

Warum es sie gibt und wie sie gedacht ist: [KONZEPT.md](KONZEPT.md). Was gebaut ist und was offen: [STATUS.md](STATUS.md). Regeln für die Arbeit am Repo: [CLAUDE.md](CLAUDE.md).

## Adresse

`https://vveorgxais.tail4ca1ab.ts.net:8443` — nur im Tailnet, HTTPS kommt von Tailscale Serve (nötig fürs Mikrofon). Anmeldung mit den Zugangsdaten aus `daten/benutzer.json`.

## Aufbau

```
server.py               FastAPI, Anmeldung, statische Dateien, Start der Stab-Schleife
cockpit/
  konfig.py             alle Einstellungen (Umgebung: ~/.config/vve-cp-r2.env)
  db.py                 SQLite (daten/cockpit.sqlite), Protokoll + Rückgängig
  importer.py           liest das alte Cockpit, fügt nur hinzu, schreibt dort nie
  stab.py               Jason ordnet ein, Rollen arbeiten aus, Daniel prüft
  gespraech.py          Talk: ein Gespräch mit Kontext, Vorschläge zum Bestätigen
  neo.py                Neo: Werkzeugkreislauf als vveadmin, Aufträge laufen weiter
  stimme.py             Whisper (im Prozess) und Piper
  anhang.py             Text aus PDF, Word, Excel, PowerPoint (aus dem alten Cockpit)
  api.py                alle Endpunkte
frontend/
  index.html, css/app.css
  vendor/preact-htm.js  Preact + htm, im Repo statt von einem CDN
  js/                   app (Gerüst), briefing, inbox, projects, team, system,
                        neo, talk, composer, entscheidung, matrix, stimme, ui, api
systemd/vve-cp-r2.service   User-Dienst (systemctl --user)
NEO-KONTEXT.md          was Neo über die Maschine und beide Cockpits weiß
archiv/iteration-1/     das frühere Neo-Experiment dieses Repos (nicht gelöscht)
```

## Betrieb auf dem Server

```bash
cd ~/vve-cp-r2 && git pull
.venv/bin/pip install -r requirements.txt      # nur wenn sich requirements.txt geändert hat
systemctl --user restart vve-cp-r2
journalctl --user -u vve-cp-r2 -n 50
```

Einmalig eingerichtet: `tailscale serve --bg --https=8443 http://127.0.0.1:8790` und `loginctl enable-linger vveadmin`.

Umgebung (`~/.config/vve-cp-r2.env`), alles optional:

| Variable | Vorgabe | Bedeutung |
|---|---|---|
| `VVEC_PORT` | 8790 | Port des Dienstes (nur 127.0.0.1) |
| `VVEC_MODELL_STAB` | llama3.3:70b | Jason, wenn im Team nichts eingetragen ist |
| `VVEC_MODELL_ARBEIT` | qwen3.8:27b | Fachrollen und Daniel |
| `VVEC_MODELL_TALK` | qwen3.8:27b | Talk |
| `VVEC_NEO_MODELL` | qwen3-coder-neo:30b | Neo |
| `VVEC_STAB_TAKT` | 120 | Sekunden zwischen zwei Stab-Durchgängen |
| `VVEC_WHISPER_MODELL` | small | Whisper-Modell |
