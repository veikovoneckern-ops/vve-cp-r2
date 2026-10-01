# Stand der neuen Fassung

## 01.10.2026, abends — Logo, Kopfzeile, Sprechen, Knopffarben

| Gewünscht | Umgesetzt |
|---|---|
| Logo oben links wieder, ohne Schriftzug „VvE Cockpit“ | Veikos Logo aus dem alten Cockpit, freigestellt (`frontend/bilder/logo-maske.png`) und als CSS-Maske gezeichnet: nimmt die Schriftfarbe an, sauber in hell und dunkel. Auch als Favicon und auf der Anmeldeseite. Auf dem Telefon steht es links in der Kopfzeile. |
| Logo dreht sich, wenn die lokale KI arbeitet | `llm.AKTIV` zählt laufende Ollama-Aufrufe dieses Dienstes (Stab, Talk, Neo gehen alle durch `llm.py`); zusätzlich zählt die Kartenlast ≥ 20 % (altes Cockpit, ComfyUI). Während dessen dreht sich das Logo und wird grün. Beim Senden in Talk/Neo läuft es sofort an. |
| Mehr Status in der Kopfzeile, kompakter | `GET /api/kopf` (`systeminfo.kopf()`): Ampel-Satz (das Dringendste zuerst), dahinter Netz, CPU, RAM, GPU-Temperaturen, VRAM, Strom, Updates, Backups — dieselbe Auswahl wie die Kästchen im alten Cockpit. Was nicht passt, fällt nach Wichtigkeit weg; die Ampel bleibt. Klick → Bereich System mit allen Einzelheiten. Die apt-Simulation wird dafür nie angestoßen, nur ihr letzter Stand gelesen. |
| Ein zentraler Knopf fürs Gespräch | „Sprechen“ oben rechts: ein Klick öffnet Talk und hört sofort zu; der Knopf zeigt, was gerade passiert (höre zu / denke nach / spreche), ein zweiter Klick beendet. Der Freisprech-Knopf im Talk-Kopf ist entfallen (ein Weg, nicht zwei). Das Sprechblasen-Symbol daneben öffnet Talk zum Tippen. |
| Ohne Klick beenden | „Dialog beenden“, „wir beenden das Gespräch“, „beende die Unterhaltung“, „Ende“, „Tschüss“ … beenden das Gespräch; über den Kopf begonnen, schließt sich Talk dann auch. Nur in kurzen Sätzen, damit „bereite das Gespräch mit Frau Schwarz vor“ nicht beendet. |
| Mikro zu groß, Wellen strahlen über andere Dinge | Sprechleiste statt großem Kreis: 44 px Kreis in einem festen 64-px-Feld, die Wellen laufen darin aus (48 × 1,3 = 62 px). |
| Knopffarben | Hauptknöpfe graphit (Farbe des Logos) mit weißer Schrift; im Dunkelmodus umgekehrt (helle Fläche, dunkle Schrift). Bestätigen grün getönt statt grün gefüllt, Rot nur für Eingriffe ins System, Violett nur als Akzent beim Sprechen. |

Nebenbei behoben: Die Stille-Erkennung beim Freisprechen lief über `requestAnimationFrame` und stand still, sobald der Tab nicht sichtbar war — das Gespräch hing dann im „Ich höre zu“. Jetzt ein Zeitgeber.

Geprüft in einer Testinstanz (Kopie der echten Daten, Stab aus, eigenes Testkonto, per SSH-Tunnel):
- `/api/kopf` liefert die Live-Werte; während einer echten Talk-Anfrage `aufrufe: 1`, danach `0`.
- Sprechen-Knopf → Talk öffnet und hört zu → Kopf zeigt „Ich höre zu“ → zweiter Klick beendet.
- Ende per Stimme durchgehend: Piper sprach „Okay, Dialog beenden“ als künstliches Mikrofon, Whisper erkannte „Ok, Dialog beendet“, das Cockpit antwortete und schloss Talk (8 s).
- 16 Sätze gegen die Ende-Erkennung: 10 beenden, 6 normale Sätze beenden nicht.
- 375 px, hell und dunkel: nichts ragt über den Rand.

Nicht geprüft: ein echtes Mikrofon (der eingebaute Browser sperrt es) — die Kette dahinter ist mit eingespeistem Ton geprüft.


## 01.10.2026, nachmittags — Rückmeldung von Veiko eingearbeitet

| Gemeldet | Ursache | Behoben |
|---|---|---|
| Dialog endet in einer Endlosschleife | Die Freisprech-Schleife sah die Gesprächskennung vom Start (null): jeder Satz begann ein neues Gespräch, ein „Ja" fand nie den Vorschlag | Kennung und Verlauf in Refs; ein kurzes „Ja“ (gesprochen oder getippt) führt den letzten Vorschlag aus, „Nein“ verwirft ihn; doppelte Vorschläge werden zusammengefasst; Talk sagt nie mehr „ich mache das“, sondern fragt |
| „Dokument erstellen“ funktioniert nicht | (1) kein Werkzeug für Word auf dem Server; (2) Neo ahmte ein Format aus seinem Verlauf nach und erfand Arbeitsschritte als Text; (3) qwen3-coder schreibt Werkzeugaufrufe bei langen Inhalten als XML-Text, den Ollama nicht erkennt | `cockpit/dokumente.py` (Markdown → Word/PowerPoint/HTML, python-docx/pptx); Werkzeug `dokument_erstellen` mit Download-Knopf; Verlauf ohne Schritte-Format; Übersetzer für das XML-Format; Behauptung ohne Werkzeugaufruf wird erkannt und Neo zurückgeschickt; Stab-Ergebnisart „Dokument (Word)“, jedes Ergebnis als Word/PowerPoint herunterladbar |
| Vorschau zeigt nichts | Neo hatte die Seite nie geschrieben (siehe oben); außerdem lehnte vorschau_zeigen Pfade außerhalb der Ablage ab | vorschau_zeigen nimmt jede HTML-Datei an und kopiert sie in die Ablage; Neos Auftrag nennt den echten Ordner |
| Box mitten im Matrix-Regen | — | entfernt; nur noch eine kleine Zeile unten |
| Ausführliche Server-Darstellung fehlt | — | Bereich System: Empfehlungen (einspielen / nicht einspielen / Achtung, gleich hohe Kästen), Aufbau-Schaubild, Updates im Einzelnen (apt-Simulation, gestaffelt), Dienste, Zeitgeber, Fassungen, Modelle mit Teamzuordnung, Sicherungen, Sicherheit; „Einspielen“ und „Neustart“ über die freigegebenen sudo-Regeln von vveadmin |
| Visualisierung beim Sprechen | — | Sprechkreis im Talk: rot beim Zuhören (folgt der Lautstärke), drehender Ring beim Nachdenken, Wellen beim Sprechen |
| Hellblaue Knöpfe | Dunkelmodus-Akzent #8bb4e6 als Füllung | Petrol (#0F5E68) mit weißer Schrift in beiden Modi; Bestätigen in Grün, Talk in Violett |

Geprüft in einer Testinstanz mit einer Kopie der echten Daten: Neo erzeugt ein Word-Dokument (37 KB, Download funktioniert) und legt eine Seite in die Vorschau; Talk: Vorschlag → „ja“ → ausgeführt, ein Gespräch statt vieler; „Word-Dokument erstellen“ über Talk → Neal → Daniel → Word-Download. Telefonbreite: nichts ragt über den Rand. Nicht gedrückt: „Einspielen“ (hätte Docker wirklich aktualisiert).

## 01.10.2026 — erste vollständige Fassung, parallel zum alten Cockpit

Gebaut nach dem freigegebenen Konzept (KONZEPT.md). Das alte Cockpit ist unverändert, es läuft weiter und wird nur gelesen.

### Was da ist

| Bereich | Stand |
|---|---|
| **Briefing** | Gruß, Gesundheitszeile (Plaud-Abruf, letzte Notiz, Stab, Neo), offene Entscheidungen mit „Per Stimme durchgehen“, „Der Stab hat erledigt“ mit Rückgängig, neue Ergebnisse, läuft gerade, nächste Aufgaben zum Abhaken, Wochenzahlen |
| **Inbox** | Akten nach Stand (wartet / in Arbeit / fertig / erledigt), Suche, Akte mit Verlauf, offenen Entscheidungen, Rückgängig je Stab-Änderung, Aufgaben, Ergebnissen; Erledigt, Verwerfen (mit Grund, nimmt Stab-Aufgaben mit), Wieder öffnen, Neu einordnen, Projekt ändern, Ausarbeiten lassen, Besprechen |
| **Projects** | Kacheln mit Fortschritt; Alle Aufgaben, Alle Notizen; je Projekt Überblick, Aufgaben (anlegen, abhaken, umbenennen, Termin, archivieren), Notizen, Ergebnisse, Verlauf, Dateien (Hochladen, Ziehen); Umbenennen merkt den alten Namen für Jason |
| **Neo** | Gesprächsliste, Verlauf mit allen Arbeitsschritten aufklappbar, Matrix-Zeichen während der Arbeit, Abbrechen, Modellwahl, Vollbild (Esc verlässt), Vorschau-Spalte mit Matrix-Regen, Anhänge, Diktat; Aufträge laufen auf dem Server weiter, auch wenn die Seite gewechselt wird |
| **Team** | Mitglieder mit Modellwahl und aktiv/pausiert, Details mit änderbarem Auftrag, Gedächtnis (anlegen, ändern, vergessen), Was der Stab darf (Vertrauensstufen, Stab an/aus), Beirat (Verweis aufs alte Cockpit; im Talk erfragbar) |
| **System** | Stab-Pipeline, Maschine (Temperaturen, Speicher, GPUs, Strom, Netz, Updates), Modelle, Stimme, Daten, Abgleich mit dem alten Cockpit, Pflege-Hinweis, Einstellungen |
| **Talk** | Seitenspalte (Telefon: ganze Seite), kennt Lage und die gerade offene Akte bzw. das Projekt oder Ergebnis, streamt, Vorschläge mit „Ausführen“ / „Alle ausführen“, Vorlesen, Freisprechen (zuhören → antworten → vorlesen → weiter), Entscheidungen per Stimme durchgehen (ja / nein / später / frei antworten / stopp) |
| **Capture** | Fenster mit Projektwahl, Text, Diktat, Anhänge → Akte, Jason ordnet ein |
| **Composer** | ein Eingabefeld überall: Plus (Datei), Mikrofon (eigener Whisper), Ziehen und Einfügen, Fortschritt beim Hochladen, Enter senden, Umschalt+Enter neue Zeile |

### Geprüft (01.10.2026, Testinstanz auf dem Server, Browser per SSH-Tunnel)

- Übernahme: 17 Projekte, 45 Aufgaben, 276 Notizen (102 aus dem Cockpit, 174 Plaud-Notizen, die das alte nie übernommen hatte), 44 Akten.
- Stab mit einer echten Eingabe (Skript OTH, Frau Schwarz anrufen, Seebestattungen recherchieren): zwei Aufgaben, je mit eigenem Projekt; Recherche über SearXNG (8 Treffer); Daniel fand im ersten Entwurf erfundene Telefonnummern, nach der Überarbeitung blieb „mit Mängeln“ ehrlich stehen.
- Neo: zwei echte Befehle, Antwort nach 16 s; Anhang hochgeladen, gelesen, von Neo richtig zitiert.
- Talk: „Was liegt an?“ mit drei Vorschlägen; „Ausführen“ schrieb den Hörfehler Kronis → Krones ins Gedächtnis.
- Stimme: Piper spricht; Whisper erkennt auf der Grafikkarte in 0,19 s je Satz, „Krones“ und „Neo“ richtig dank Namensvorlage.
- Telefonbreite 375: auf allen acht Ansichten ragt kein Element über den Rand.
- Keine Konsolenfehler in allen Ansichten.

### Nicht geprüft

- Mikrofon im echten Browser (Freisprechen, Diktat, Durchgehen): braucht ein echtes Gerät mit Mikrofon. Die Wege dahinter (Aufnahme → /api/stimme/hoeren → Text) sind mit einer Piper-Aufnahme geprüft.
- Bildschirmfotos: der eingebaute Browser lieferte keine; geprüft wurde über Seitentext und Messungen.

### Bewusst noch nicht drin

- Updates, Sicherungen, Firmware, WatchDog-Knöpfe: bleiben im alten Cockpit (der Bereich System zeigt den Stand und verlinkt).
- Mail-Versand: die SMTP-Zugangsdaten liegen nur beim alten Backend (`/etc/vvec/secrets.env`, für vveadmin nicht lesbar). Ergebnisse lassen sich kopieren.
- Cloud-Modelle (Dario, Elon, Demmis): kein Schlüssel in dieser Fassung.
- Ketten, Org-Chart, Bildwerk: laut Konzept „später“.
- Präsentationen als .pptx: python-pptx ist nicht installiert; Präsentationen erscheinen als HTML-Folien in der Ansicht.

### Braucht einmal Veikos Passwort (vveadmin hat dafür kein sudo)

1. **https fürs Mikrofon:** `sudo tailscale serve --bg --https=8443 http://100.65.221.106:8790`
   → danach `https://vveorgxais.tail4ca1ab.ts.net:8443`. Bis dahin läuft alles unter
   `http://100.65.221.106:8790`, nur das Mikrofon gibt der Browser dort nicht frei.
2. **Fernsicherung:** Die Datenbank wird täglich um 03:30 nach `daten/sicherungen/` gesichert
   (30 Stände, `vve-cp-r2-sicherung.timer`). Das liegt auf derselben Platte. Damit sie auch
   nach OneDrive geht, muss `~/vve-cp-r2/daten` in `vvec-sicherung.sh` des alten Cockpits
   aufgenommen werden (läuft als root; Änderung im Repo `vve-cp`, nicht hier).

### Parallelbetrieb

Beide Fassungen lesen dieselbe Plaud-Ablage. Neue Notizen ab dem ersten Start der neuen Fassung bearbeitet der Stab hier UND die alte Pipeline dort, jede in ihrer eigenen Ablage. Wer ganz umsteigt, schaltet im alten Cockpit unter Setup Settings die automatische Verarbeitung aus.
