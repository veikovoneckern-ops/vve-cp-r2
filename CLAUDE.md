# CLAUDE.md — neue Fassung des VvE Cockpits

**Antworte immer auf Deutsch.** Bezeichner, Kommentare und Dokumentation sind deutsch.

## Was das ist

Die Neufassung des VvE Cockpits, parallel zum alten (Repo `vve-cp`, Arbeitskopie `C:\Projekte\VvE-CP`). Hauptzielsetzung wie dort beschrieben: ein Stab aus KI-Modellen, der Veikos Plaud-Notizen von selbst liest und eigenständig weiterarbeitet; Veiko spricht mit dem Cockpit über die Vorschläge und sieht die Ergebnisse. Das Konzept dazu: `KONZEPT.md`.

Veiko ist kein Entwickler von Beruf. Erklären ohne Jargon, eine Empfehlung statt drei Varianten, bei Befehlen sagen, was sie tun und woran man den Erfolg erkennt.

## Die Bauregeln (aus dem Konzept)

1. Jede Funktion dient einem Schritt des Kreislaufs (Hören, Einordnen, Vorschlagen, Besprechen, Entscheiden, Erledigen) oder steht im Bereich System.
2. Kein zweiter Weg zum selben Ziel. Wer einen neuen Weg baut, ersetzt den alten.
3. Neue Funktionen kommen dazu, wenn eine vorhandene nicht reicht.
4. Dokumentation hält Entscheidungen fest (warum), keine Fehlerprotokolle. Was aus einem Fehler gelernt wurde, gehört als Prüfung in den Code.

## Feste Regeln

- **Das alte Cockpit wird nie geschrieben.** `importer.py` und `stab.py` lesen `/var/lib/vvec` nur. Neo darf dort und in `/opt/vvec`, `/srv/www` nicht schreiben (Sperrliste in `neo.py`).
- **Ein Schreiber.** Der Browser schickt einzelne Änderungen an die API, nie einen ganzen Zustand.
- **Was der Stab selbst ändert, steht im Protokoll** (`db.anlegen`/`db.aendern` mit `wer=<rolle>`) und lässt sich zurücknehmen. Wer neuen Stab-Code schreibt, benutzt diese Funktionen, nicht rohes SQL.
- **Vertrauensstufen** (`stab.VERTRAUEN_VORGABE`): neue Projekte und Gedächtnis-Einträge nur auf Ja. Geld, Mails nach außen, Löschen: nie vom Stab.
- **Nichts erfinden.** Fehlt ein Wert, sagt die Oberfläche „nicht verfügbar“.
- **Alle Pfade relativ**, nie einen Hostnamen in `fetch()`.
- **Kein Bauschritt.** ES-Module, Preact + htm aus `frontend/vendor/`.

## Prüfen

```bash
# Python (auf dem Server, im Repo)
.venv/bin/python -c "import ast,sys;[ast.parse(open(f).read(),f) for f in sys.argv[1:]]" server.py cockpit/*.py
# JavaScript (hier oder dort): Kopie mit .mjs, dann node --check
```

Im Browser prüfen: per SSH-Tunnel auf `localhost` (der eingebaute Browser scheitert an der Tailnet-Adresse):
`ssh -N -L 8790:100.65.221.106:8790 vveki`, dann `http://localhost:8790` (der Dienst lauscht auf der Tailnet-Adresse).
Für Tests ohne echte Daten: eine zweite Instanz mit `VVEC_PORT=8791 VVEC_NEU_DATEN=<leeres Verzeichnis>` und einem Testkonto; danach Verzeichnis löschen. Prozesse nie per `pkill -f` über den Namen beenden (trifft die eigene SSH-Sitzung), sondern über den Port (`ss -ltnp`).

## Ausliefern

Kein ZIP, kein Manifest. Committen, nach GitHub pushen, auf dem Server `git pull` und `systemctl --user restart vve-cp-r2`.
