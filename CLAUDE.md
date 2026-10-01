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
- **Symmetrie (Veikos Vorgabe).** Kacheln nebeneinander sind gleich hoch und gleich breit: Raster mit `grid-auto-rows:1fr` (`.sv-raster`, `.raster-gleich`), kein Mehrspaltensatz. Langer Inhalt scrollt in seiner Kachel, statt die Reihe zu strecken. In der Kopfzeile sitzt alles auf einer Mittellinie (`--kasten`).
- **Ein Ort je Sache.** Maschine und Server stehen nur in der Server-Sektion (klappt über die Kästchen im Kopf auf), nicht zusätzlich unter System. Wer etwas baut, das es woanders schon gibt, sagt das Veiko vorher.
- **Ziehen über Pointer Events**, nie über natives HTML5-Drag (im alten Cockpit dreimal gescheitert).
- **Ein Ja reicht (Talk).** Hat Veiko zugestimmt oder ausdrücklich einen Auftrag ans Team/Neo erteilt, führt `gespraech.senden` aus, statt noch einmal einen Knopf zu zeigen. Liefert das Modell nach einem Ja keinen Vorschlag, wird er einmal gezielt nachgefordert; sonst steht ehrlich da, dass nichts gestartet ist.
- **Neue Ansichten können mit Talk sprechen.** Wer eine Ansicht baut, setzt `talk-kontext` und gibt `gespraech.kontext_text` den Stand dazu (Vorbild: BrainStrom, ExO, WatchDog in `verfahren.py`/`watchdog.js`). Die Notabschaltung gibt es nie über Talk.
- **Neo wird nachgeprüft, nicht geglaubt** (`neo._abschluss_pruefen`): ungezeigte Seiten zeigt das Cockpit selbst, fehlende Anhänge legt es neben die Seite, als Text geschriebene Werkzeugaufrufe führt es aus, und in einem Gespräch voller falscher Erzählungen macht es einen frischen Anlauf ohne Neos alte Antworten.

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
