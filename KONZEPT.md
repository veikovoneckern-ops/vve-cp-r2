# Konzept: das neue VvE Cockpit

Kurzfassung des Vorschlags vom 01.10.2026 (ausführlich als Artifact „Cockpit-Neuaufbau“). Veiko hat ihn am selben Tag freigegeben, mit dem Wunsch nach englischen Bereichsnamen, einem eigenen Knopf für Neo samt Matrix-Animation und größter Sorgfalt bei Anhängen, Mikrofon und Bedienung.

## Die Zielsetzung

Ein Stab aus KI-Modellen, der Veikos Plaud-Notizen von selbst liest und daraus so eigenständig wie möglich weiterarbeitet. Veiko spricht mit dem Cockpit über die Vorschläge der Teammitglieder und sieht sich die Ergebnisse an. Daraus folgt ein Kreislauf, dem jede Funktion dienen muss:

**Hören → Einordnen → Vorschlagen → Besprechen → Entscheiden → Erledigen**

## Was am alten Cockpit nicht trug (Befunde)

- Zu viele Türen zum selben Raum: rund 30 Einträge in der Leiste, 13 Gesprächsflächen, 8 Stellen für eine Notiz.
- Der Kern war der kleinste Teil: die Vorgänge-Ansicht ~1.400 Zeilen, Maschine und Neo-Werkzeuge ~15.000.
- Die Ergebnisqualität war der eigentliche Engpass: 44 Vorgänge, Prüfung 25-mal „nachbessern“, einmal „tragfähig“; erfundene Fakten, fremde Schriftzeichen. Das beste Ergebnis war das einfachste (vier klare Aufgaben).
- Ein dreiwöchiger Stillstand des Plaud-Abrufs fiel niemandem auf.
- Das Fundament (ganzer Zustand als eine Datei, Layer per Textersetzung in die Basis) erzeugte ganze Fehlerklassen.
- Gespräche gingen verloren.

## Die neue Struktur

| Bereich | Wozu |
|---|---|
| **Briefing** | Startseite: was auf deine Entscheidung wartet, was der Stab erledigt hat (mit Rückgängig), was läuft, deine nächsten Aufgaben, ob die Pipeline gesund ist |
| **Inbox** | Jede Notiz, jeder Auftrag als Akte mit Verlauf |
| **Projects** | Portfolio; je Projekt Aufgaben, Notizen, Ergebnisse, Verlauf, Dateien |
| **Neo** | Mit dem Cockpit Engineer arbeiten wie mit Claude Code; Vorschau-Spalte mit Matrix-Regen |
| **Team** | Mitglieder und Modelle, Gedächtnis, was der Stab ohne Rückfrage darf, Beirat |
| **System** | Maschine, Modelle, Stimme, Abgleich mit dem alten Cockpit, Einstellungen |
| **Talk** (überall) | Ein Gespräch mit Kontext; tippen, diktieren, freisprechen, Entscheidungen per Stimme durchgehen |
| **Capture** (überall) | Etwas an den Stab geben, wie eine Plaud-Notiz |

## Der Stab

1. **Einordnen** (immer, Jason): Projekt, Anliegen, Zusammenfassung, Rückfragen.
2. **Ableiten** (immer, Jason): Aufgaben für Veiko, je Aufgabe ihr Projekt; Vorschläge für neue Projekte und Gedächtnis.
3. **Ausarbeiten** (nur auf ausdrücklichen Auftrag): Fachrolle mit Recherche über die eigene Suchmaschine, Daniel prüft, eine Nachbesserungsrunde.

Vertrauensstufen: Zuordnen und Aufgaben anlegen „selbst, mit Rückgängig“; neue Projekte und Gedächtnis „erst fragen“; Geld, Mails, Löschen nie.

Das **Gedächtnis** (Personen, Organisationen, Begriffe, Hörfehler) geht in jede Arbeit des Stabs, Hörfehler werden vor dem Lesen korrigiert, Namen helfen Whisper beim Zuhören.

## Technik

SQLite statt Zustandsdatei, ein Schreiber, Protokoll für Rückgängig. Preact + htm ohne Bauschritt. Parallelbetrieb: eigener Dienst (127.0.0.1:8790, Tailscale Serve auf 8443), der alte Bestand wird nur gelesen.

## Fahrplan

0 Vorschlag abstimmen · 1 Fundament · 2 Inbox, Stab, Entscheidungen, Gedächtnis · 3 Talk mit Stimme · 4 Projekte, Ergebnisse, Ausarbeitung · 5 Team, System, Neo · 6 Umschalten (das alte Cockpit wird erst abgeschaltet, wenn Veiko es ausdrücklich sagt).
