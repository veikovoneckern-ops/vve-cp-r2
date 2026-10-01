# Stand der neuen Fassung

## 01.10.2026, nachts (2) — Advisory Board, moderne Bezeichnungen

**Advisory Board** als eigener Bereich (`board.py`, `board.js`): links der Tisch (19 Advisors in 5 Gruppen, Filter, an den Tisch holen per Klick, Profil mit Prinzipien, typischen Fragen, Stärken, blinden Flecken und dem nächtlich aufgefrischten öffentlichen Stand samt Quellen), rechts das Gespräch. Antworten werden je Advisor in eigene Sprechblasen geteilt; Einzelgespräch mit einer Person; optionaler Projektbezug; Schnellstarts; Gespräche bleiben gespeichert. Profile einmalig aus BOARD_DATA des alten Cockpits (`cockpit/board_profile.json`), Tischbesetzung beim ersten Mal aus dessen Zustand; `board-stand.json` wird nur gelesen. Geprüft mit echtem Modell: Runde (4 von 10 sprachen, 26 s), Einzelgespräch, Profil, 375 px.

**Bezeichnungen** (sichtbare Texte und Talk-Auftrag): Stab → Team, Akte → Case, Gedächtnis → Memory, Beirat/Vordenker → Advisory Board/Advisors, Vertrauensstufen → Freigaben, Rückfrage → Frage. Bezeichner im Code und Datenbankfelder bleiben (`stab_aktiv`, `quelle='stab'` usw.), damit gespeicherte Daten passen.

Doppelter Weg entfernt: Reiter „Beirat“ unter Team (das Board hat jetzt einen eigenen Bereich).

## 01.10.2026, nachts — Struktur wie im alten Cockpit, Neo mit Bildern, Diktat zum Mitlesen, Knöpfe

| Gemeldet / gewünscht | Ursache / Umsetzung |
|---|---|
| Struktur wie im alten Cockpit | Projekt links als farbige Wurzel, Aufgaben rechts als Baum, Linien in Projektfarbe. Ziehen am ganzen Knoten; ungültige Ziele (unter sich selbst) werden schon beim Ziehen rot. Neu: + am Knoten legt eine Unteraufgabe an, + am Projekt eine Aufgabe, Doppelklick benennt um, Termin am Knoten, Fortschritt je Ast („2/5“), alles auf/zu. `POST /aufgaben` nimmt `eltern_id` |
| Neo nahm das angehängte Logo nicht | Er hatte kein Werkzeug für Binärdateien und hat den Dateinamen nur eingetragen, nie kopiert; die Seite zeigte ein leeres Bild, Neo meldete „erledigt“. Jetzt: Werkzeug `datei_kopieren`; ein Bild-Anhang sagt Neo genau, was zu tun ist; `vorschau_zeigen` meldet „NICHT FERTIG“, wenn die Seite auf fehlende Dateien verweist; Neos Auftrag nennt, wo das Cockpit-Logo liegt. Geprüft mit echtem Modell: kopiert, geschrieben, gezeigt |
| Diktat zum Mitlesen | `diktieren()` in `stimme.js`: Aufnahme an Sprechpausen in Stücke geteilt; fertige Stücke werden fest erkannt, das laufende alle 1,5 s vorläufig (eigener Whisper, kein Google). Geprüft mit eingespeistem Piper-Ton: erster Text nach 2,8 s, am Ende wortgenau |
| Keine weißen Knöpfe | Normale Knöpfe auf getönter Fläche (`--knopf-grund`), Hauptknöpfe im Dunkelmodus Schiefergrau statt hell |
| Sprechen ohne Beschriftung | Nur das Mikrofon (violett); Zustand und Bedeutung im Hinweis |
| Hinweis beim Überfahren | `tippsEinrichten()` in `ui.js`: jedes Element mit `title` bekommt denselben Hinweis im Cockpit-Stil nach 0,3 s; der graue Browser-Hinweis entfällt |

Doppelter Weg entfernt: „+ Aufgabe“ über dem Baum (dasselbe wie + am Projektknoten).

## 01.10.2026, spät — Kopfzeile und Server-Sektion wie im alten Cockpit, Projektansichten, Sprechen im Projekt

| Gewünscht | Umgesetzt |
|---|---|
| Favicon wie im alten Cockpit (rot) | Der rote Orbit-Ring aus `einbau.py` (`frontend/bilder/favicon.png`) |
| Logo dreht sich und zeigt die Last | Farbe = LED-Leiste der Grafikkarten (`ledFarbe()` in `kopf.js`, gleiche Rechnung wie `vve-rgb.py`): weiß bei wenig, rot unter Volllast. Feiner Schatten hält Weiß im hellen Modus sichtbar |
| Kopfzeile wie im alten Cockpit, bündig | Titel (im Projekt: Projektname / „Projekt-Detail“) · Cockpit-Leiste (Letzter Abruf, Letzte Notiz, Inbox) · Server-Kästchen (Wert oben, Bezeichnung darunter) · Sprechen · Suche · Gespräch. Alles 44 px hoch auf einer Mittellinie; die Hostzeile steht jetzt im Kopf der Server-Sektion |
| Server-Status 1:1 wie im alten Cockpit | `server.js`: klappt unter der Kopfzeile auf (Klick auf die Kästchen, Esc schließt). Aufbau-Schaubild · Updates/Sicherungen/Empfehlungen · Software (8 Karten) · Womit Sie arbeiten · Was die Maschine meldet. Neu-Start-Knöpfe für Ollama und Caddy (sudo-Freigabe vorhanden) |
| Kacheln nebeneinander gleich hoch/breit | Raster mit `grid-auto-rows:1fr`; als feste Regel in CLAUDE.md |
| Projektansichten (Gantt, Ziehen) | Reiter **Zeitplan** (Zeitachse, Beginn und Fälligkeit direkt änderbar) und **Struktur** (Baum, Ziehen: Mitte = Unteraufgabe, Rand = davor/danach, freie Fläche = oberste Ebene, Zyklen abgelehnt, scrollt am Rand mit). Neue Spalten `eltern_id`, `sortierung`, `start`; Unteraufgaben einmalig aus dem alten Cockpit übernommen. Reiter steht in der Adresse |
| Sprechen im Projekt | Rahmen sofort gesetzt und angesagt („Wir sprechen über das Projekt …“). Neue Aktionen: `zeigen` (öffnet einen Reiter, ohne Rückfrage) und `aufgabe_aendern` (Titel/Termin/Status, mit Ja). Neues landet ohne Angabe im Projekt |

Doppelte Wege entfernt: System zeigt nur noch Stab, Daten, Einstellungen (die Maschine steht in der Server-Sektion); „Besprechen“ im Projektkopf entfällt (Sprechen und die Gesprächsspalte haben den Projektbezug).

Bewusst noch nicht: **Ablauf** (Stufen nach Abhängigkeiten mit KI-Planung) — braucht Abhängigkeiten zwischen Aufgaben und einen Planungsschritt; eigener Schritt.

Geprüft in einer Testinstanz (Kopie der echten Daten): Kopfzeile alle Elemente Mitte 34 px; Server-Sektion jede Reihe gleich hoch und breit (4 × 354 px); Struktur mit echten Pointer-Ereignissen (Unteraufgabe, oberste Ebene mit Mitscrollen, Zyklus abgelehnt); Zeitplan (Beginn gesetzt → Balken, Linien auf Monatsgrenzen); Talk im Projekt („Zeig mir die Aufgaben“ → Reiter; Aufgabe anlegen landet im Projekt; Termin verschieben nach Ja); 375 px ohne Überstand.

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
