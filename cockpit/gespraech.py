"""
TALK -- ein Gespraech, ueberall, das weiss, worauf Veiko gerade schaut.

Ersetzt die 13 Gespraechsflaechen des alten Cockpits (Befund B1). Jede kannte
etwas anderes; dieses hier bekommt immer dieselbe Lage (offene
Entscheidungen, was laeuft, was erledigt ist) plus den Kontext der Ansicht.

Aendern tut das Gespraech NICHTS still. Es haengt Vorschlaege als
```aktionen-Block an; das Cockpit zeigt sie mit einem Knopf, und erst der
Klick (oder ein gesprochenes "ja") fuehrt sie aus. Eine Positivliste, kein
Function-Calling -- dieselbe Haltung wie im alten dialog.py, weil lokale
Modelle Werkzeugaufrufe unzuverlaessig liefern.
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import re
import time
from typing import Any, AsyncIterator

from . import db, llm, stab
from .konfig import MODELL_TALK

_LAUFEND: set[asyncio.Task] = set()   # Hintergrundarbeit aus Talk (Daniels Pruefung), damit nichts verloren geht

AKTIONEN = {
    "entscheiden": ("entscheidung_id", "antwort"),
    "antworten": ("entscheidung_id", "text"),
    "aufgabe_neu": ("titel",),
    "aufgabe_erledigt": ("aufgabe_id",),
    "aufgabe_aendern": ("aufgabe_id",),
    "zeigen": ("ziel",),
    "oeffnen": ("art",),   # dazu id ODER titel (oeffnen_aufloesen)
    "werkzeug": ("was",),  # Capture, Suche, hell/dunkel, zurueck, Fenster zu (18.10.2026)
    "bild": ("prompt",),
    "visualisierung": ("beschreibung",),
    "ausarbeiten": ("auftrag",),
    "merken": ("begriff", "bedeutung"),
    "notiz": ("text",),
    "projekt_neu": ("name",),
    "neo": ("auftrag",),
    # Einen Begriff in einem Projekt durchgaengig ersetzen (19.10.2026): vorher ging so
    # etwas an Neo, und Neo aenderte Code statt der Daten.
    "ersetzen": ("alt", "neu", "projekt_id"),
    # Daniel prueft ein vorhandenes Ergebnis (19.10.2026). ergebnis_id oder titel (beschriften loest auf).
    "pruefen": (),
    # Ein Externer (Dario, Demmis, Elon) prueft ein vorhandenes LongRun-Ergebnis abschliessend
    # (22.10.2026): "lass Demmis das Buch pruefen" wurde zweimal zu Daniel und einmal zu einem
    # neuen LongRun, der ein Feedback SCHRIEB -- die Aktion dafuer fehlte Talk schlicht.
    "extern_pruefen": ("wer",),
    # Ein LongRun aus Talk (19.10.2026): Veiko sagte "als Long Run … unter Einbeziehung von
    # Demmis", Talk machte eine gewoehnliche Ausarbeitung daraus -- bei LongRuns stand nichts.
    "langlauf": ("auftrag",),
    # BrainStrom und ExO (verfahren.py) -- Veiko, 01.10.: "wenn ich mit dem Cockpit
    # spreche, muss das auch fuer diese Elemente funktionieren".
    "brainstrom": ("thema",),
    "brainstrom_antwort": ("text",),
    "brainstrom_weg": ("nummer",),
    "brainstrom_genug": (),
    "brainstrom_uebernehmen": (),
    "exo": (),
    # Daily Tasks (22.10.2026): anlegen, aendern, jetzt ausfuehren, pausieren, fortsetzen, loeschen.
    "daily": ("was",),
    # E-Mails (22.10.2026, mail.py): Entwurf anlegen und formulieren, aendern, abschicken.
    "mail": ("was",),
    # Vorgemerktes im Gespraech klaeren (21.10.2026, Veiko: "im direkten Dialog weiter entscheiden,
    # was mit dieser Art von Notizen, Eingaengen, Ideen passiert").
    "vorgemerkt": ("vorgang_id", "was"),
}
# Laufen sofort, ohne Knopf: sie aendern nur den Stand des Verfahrens, nicht den
# Bestand (Projekte, Aufgaben). Uebernehmen in Projekte bleibt ein Vorschlag mit Ja.
SOFORT_VERFAHREN = ("brainstrom", "brainstrom_antwort", "brainstrom_weg", "brainstrom_genug", "exo")

# Ein kurzes Ja ohne Nein -- dieselbe Regel wie im Browser (talk.js istJa).
_JA = re.compile(r"\b(ja|jawohl|jep|genau|klar|gerne|gern|ok|okay|einverstanden|passt|richtig|bitte|mach(e|t)? (das|es)|tu (das|es)|so machen|leg los|legt los|los geht)\b", re.I)
_NEIN = re.compile(r"\b(nein|nee|nö|nicht|lieber nicht|ablehnen|falsch|stopp)\b", re.I)
# Ein ausdruecklicher Auftrag ans Team oder an Neo ("lasst das Team ... erstellen").
AUFTRAG_AN_TEAM = re.compile(r"\b(lass|lasst|lassen)\b.{0,60}\b(team|neo|jason|clayton|neal|annie|ridley|daniel)\b"
                             r"|\b(team|neo|annie|clayton|neal|ridley)\b.{0,40}\b(soll|sollen|mach|macht|erstell|erstellt|bau|baut|schreib|schreibt|recherchier|arbeite|arbeitet)", re.I)

# Das Modell sagt, das Team arbeite schon -- ohne den Block (19.10.2026: "Ich lasse Neal
# eine PowerPoint-Präsentation erstellen", vorschlaege leer, nichts lief). Dieselbe Lage
# wie bei Recherche und Oeffnen: einmal nachfordern, sonst ehrlich sagen.
TEAM_BEHAUPTET = re.compile(r"[^.!?\n]*(\b(ich )?(lasse|gebe (das|es|den auftrag|deinen auftrag) (an|weiter))\b[^.!?\n]{0,60}\b(team|neo|jason|clayton|neal|annie|ridley|daniel|demmis)\b"
                            r"|\b(neal|annie|clayton|ridley|neo|jason|das team)\b[^.!?\n]{0,30}\b(macht sich|erstellt|baut|schreibt|arbeitet|kümmert sich|legt los)\b)[^.!?\n]*[.!?]?", re.I)

# "Ich korrigiere die Bezeichnung" ohne Block und ohne Frage (19.10.2026): nichts geschah.
AENDERUNG_BEHAUPTET = re.compile(r"Noch nicht ausgeführt: [^\n]*|[^.!?\n]*\bich (korrigiere|ändere|aendere|benenne|ersetze|aktualisiere|lege|trage|markiere|verschiebe|lösche|loesche|beauftrage|fordere|starte|stoße|stosse|veranlasse)\b[^.!?\n]*[.!?]?", re.I)

# Zustimmung oder Auftrag MITTEN in einem laengeren Satz (gemessen am 16.10.:
# "Okay, du kannst Jensen sagen, er soll das Projekt anlegen und was muss ich
# beim Buchprojekt machen" -- 18 Woerter, ist_ja() griff nicht, das Projekt blieb
# offen, und Talk behauptete trotzdem "ich gebe das an Jason weiter"). Das Modell
# markiert die gemeinte Aktion mit "zugestimmt"; ausgefuehrt wird nur, wenn
# zusaetzlich hier ein Zustimmungs- oder Auftragswort steht. Beides zusammen --
# das Modell allein koennte eine Zustimmung erfinden.
ZUSTIMMUNG_IM_SATZ = re.compile(
    r"\b(ja|okay|ok|einverstanden|gerne?|bitte|du kannst|kannst du|sag (ihm|ihr|jason|\w+) .{0,20}soll|"
    r"leg\w*|anlegen|lege|mach\w*|erstell\w*|übernimm|uebernimm|bestätig\w*|freigeb\w*|soll(en)? .{0,30}(anlegen|machen|erstellen|übernehmen)|"
    # Befehle zum Eintragen (17.10.2026, Veiko: "es soll die Dinge machen, die ich sage")
    r"trag\w*|eintragen|markier\w*|änder\w*|aender\w*|setz\w*|verschieb\w*|notier\w*|hak\w*|schreib\w* .{0,20}(auf|ein|dazu))\b",
    re.I)
# Ein Befehl AM SATZANFANG ist die Zustimmung -- auch wenn das Modell "zugestimmt" vergisst
# (19.10.2026: "Leg mir eine Aufgabe an: beim Verlag Campus anrufen, bis Freitag" -- Talk
# fragte trotzdem "Soll ich das so machen?"). Nur fuer Aktionen, die zum Verb passen und
# sich zuruecknehmen lassen (BEFEHL_AKTIONEN); ZUSTIMMUNG_IM_SATZ allein ist zu breit
# ("ja", "bitte" irgendwo im Satz).
BEFEHL = re.compile(r"^\s*((okay|ok|gut|ja|dann|und|also|bitte)[,.]?\s+)*(leg|trag|markier|hak|verschieb|änder|aender|setz|notier|merk|"
                    r"ersetz|korrigier|benenn|erstell|mach|prüf|pruef|lass|schreib)\w*\b", re.I)
# "Gib das frei", "leg das ab", "verwirf das" zu Vorgemerktem ist die Zustimmung (21.10.2026).
VORGEMERKT_BEFEHL = re.compile(r"\b(freigeb\w*|freigab\w*|gib\b.{0,50}\bfrei|leg\w*\b.{0,40}\bab\b|ablegen|verwirf|verwerfen|weg\s+damit|kann\s+weg)", re.I)
BEFEHL_AKTIONEN = ("aufgabe_neu", "aufgabe_erledigt", "aufgabe_aendern", "notiz", "merken", "ersetzen", "pruefen", "projekt_neu", "daily", "mail")
# "Schick das an Hanna", "formulier das freundlicher" -- legt an oder aendert einen ENTWURF; abgeschickt
# wird davon nie etwas (22.10.2026). Senden braucht ein Ja auf den gezeigten Entwurf.
MAIL_ABSICHT = re.compile(r"\b(schick|send|verschick|mail|maile|weiterleit)\w*\b.{0,120}\ban\s+\w|\b(e-?mail|mail)\b.{0,60}\b(an|schreib|formulier|kürzer|kuerzer|freundlicher|förmlicher|englisch|abschick|schick)", re.I)
MAIL_BEFEHL = re.compile(r"\b(schick|send|verschick|mail|maile|formulier|schreib|antwort|füg|fueg|häng|haeng|setz)\w*", re.I)
# "Fuehr den Daily Task jetzt aus", "pausier ihn", "setz ihn fort" -- Befehle zu Daily Tasks (22.10.2026).
DAILY_BEFEHL = re.compile(r"\b(führ\w*|fuehr\w*|start\w*|lass\w*)\b.{0,50}\b(aus|laufen|jetzt|sofort|nochmal|noch einmal)\b|"
                          r"\bpausier\w*|\bfortsetz\w*|\bsetz\w*\b.{0,30}\bfort\b|\bwieder (an|aktiv)\b|\bänder\w*|\baender\w*|\bstell\w*\b.{0,30}\bum\b", re.I)
# "Lass Daniel … pruefen" -- immer eine echte Pruefung, auch wenn das Modell meint, es sei schon geschehen.
# Ein Externer soll pruefen (22.10.2026). Whisper schreibt "Demis", "Dennis", "Dario", "Elan" ...
EXTERN_NAME = {"dario": "dario", "claude": "dario", "demmis": "demmis", "demis": "demmis", "dennis": "demmis", "gemini": "demmis",
               "elon": "elon", "grok": "elon"}
EXTERN_PRUEFEN = re.compile(r"\b(dario|claude|demmis|demis|dennis|gemini|elon|grok)\b.{0,80}\b(prüf|pruef|überprüf|review|gegenles|begutacht)\w*"
                            r"|\b(prüf|pruef|überprüf|review|gegenles|begutacht)\w*\b.{0,60}\b(dario|claude|demmis|demis|dennis|gemini|elon|grok)\b", re.I)
DANIEL_PRUEFEN = re.compile(r"\bdaniel\b.{0,60}\b(prüf|pruef|überprüf|anseh|anschau|begutacht)\w*|\b(prüf|pruef)\w*\b.{0,40}\bdaniel\b", re.I)
# Eine Behauptung, eine Recherche laufe (19.10.2026) -- die ganze Zeile, damit kein halber Satz stehen bleibt.
RECHERCHE_BEHAUPTET = re.compile(r"[^\n]*\b(Recherche gestartet|Recherche (läuft|ist gestartet|startet)|starte (die |eine )?(gründliche |neue |erneute )?Recherche)[^\n]*", re.I)
# Was das Cockpit selbst an eine Antwort haengt (dossier.aus_antwort), sieht das Modell im Verlauf nur
# als Vermerk -- sonst schreibt es die Zeile beim naechsten Mal ab, ohne etwas zu starten.
_COCKPIT_ZEILE = re.compile(r"^Recherche gestartet: .*$", re.M)
_ABLEHNUNG = re.compile(r"\b(nein|nee|lieber nicht|nicht anlegen|nicht machen|ablehnen|stopp)\b", re.I)


def zustimmung_im_satz(text: str) -> bool:
    return bool(ZUSTIMMUNG_IM_SATZ.search(text or "")) and not _ABLEHNUNG.search(text or "")


def ist_ja(text: str) -> bool:
    t = (text or "").strip()
    # Beginnt der Satz mit Ja, darf er laenger sein (19.10.2026, wie talk.istJa).
    lang = len(t.split()) <= 18 and bool(re.match(r"(ja|jawohl|genau|okay|ok|gerne|klar|einverstanden)\b", t, re.I))
    return (len(t.split()) <= 10 and bool(_JA.search(t)) or lang) and not _NEIN.search(t)

SYSTEM = """Du bist das VvE Cockpit: die Stimme von Veikos persönlichem KI-Team. Veiko von Eckern ist Head of Corporate HR Transformation bei Krones. Sein Team: Jason (Head of PMO, ordnet ein), Neo (Cockpit Engineer), Clayton (Strategie), Neal (Texte, Bücher), Daniel (Red Team, prüft), Annie (Gestaltung), Ridley (Video).

So antwortest du:
- Deutsch, direkt, freundlich, ohne Vorrede. Zuerst die Antwort, dann wenn nötig die Begründung.
- Erfinde nichts. Du kennst nur, was unten in LAGE und KONTEXT steht. Wenn etwas fehlt, sag es.
- Nenne, wer gearbeitet hat, aber nur, wenn es in LAGE oder KONTEXT steht. Schreib niemandem eine Arbeit zu, die dort nicht vorkommt.
- Nenne im Text NIE interne Kennungen (e…, t…, p…, v…). Die gehören nur in den aktionen-Block. Im Text sagst du den Titel.
- Auf "Was liegt an?" antwortest du knapp: höchstens sechs Punkte, in DIESER Reihenfolge -- wie das Briefing, das Veiko daneben sieht: 1. OFFENE ENTSCHEIDUNGEN (stehen dort „keine“, sag genau das), 2. NEU ENTSTANDEN (zuletzt bearbeitete zuerst, mit Daniels Urteil in einfachen Worten), 3. WAS GERADE LÄUFT (steht dort „nichts“, sag genau das), 4. OFFENE AUFGABEN (die ersten drei, in der Reihenfolge der Liste), 5. VORGEMERKT, falls dort etwas steht: nenne es und frag, was damit passieren soll (freigeben mit Anweisung, ablegen oder verwerfen). Nur, was in LAGE steht. Einen eigenen, noch nicht ausgeführten Vorschlag aus diesem Gespräch nennst du getrennt am Ende („Aus unserem Gespräch noch offen: …“) -- er ist keine Entscheidung des Teams. Keine vollständigen Listen.
- Kein Fachjargon ohne Erklärung.
- Wortwahl wie im Cockpit: „Team“ (nicht „Stab“), „Case“ (nicht „Akte“), „Memory“ (nicht „Gedächtnis“), „Advisory Board“ (nicht „Beirat“), „LongRun“ (nicht „Langläufer“), „Stack“ (nicht „Maschine“), „Usage“ für den Verbrauch, „Explorer“ für alle erzeugten Inhalte, „Settings“ (nicht „Einstellungen“), „Recommendations“ für alle Empfehlungen.
{STIMME}

Wenn Veiko etwas tun lassen will, schlägst du es vor. Hänge dafür GANZ ANS ENDE einen Block in genau dieser Form an:
```aktionen
[{"aktion": "...", ...}]
```
Erlaubte Aktionen (nur diese, nur mit ids aus LAGE/KONTEXT):
- {"aktion":"entscheiden","entscheidung_id":"e…","antwort":"ja|nein","text":"optional, z. B. anderer Projektname"}
- {"aktion":"antworten","entscheidung_id":"e…","text":"Veikos Antwort auf eine Rückfrage"}
- {"aktion":"aufgabe_neu","titel":"…","projekt_id":"p… oder null","faellig":"JJJJ-MM-TT oder null"}
- {"aktion":"aufgabe_erledigt","aufgabe_id":"t…"}
- {"aktion":"aufgabe_aendern","aufgabe_id":"t…","titel":"neuer Titel oder weglassen","faellig":"JJJJ-MM-TT oder weglassen","status":"offen|erledigt oder weglassen"}
- {"aktion":"zeigen","ziel":"ueberblick|aufgaben|zeitplan|struktur|notizen|ergebnisse|verlauf|dateien","projekt_id":"p…"} -- öffnet eine Ansicht des Projekts sofort, ohne Rückfrage (ändert nichts)
- {"aktion":"bild","prompt":"ausführliche Bildbeschreibung auf ENGLISCH (Motiv, Stil, Licht, Perspektive)","titel":"kurzer deutscher Titel","format":"quadrat|quer|hoch","vorlage":"z-image"} -- erzeugt ein Bild auf dem eigenen Server. Vorlage IMMER z-image (etwa 15 Sekunden), auch für fotorealistische Bilder; qwen nur, wenn lesbarer Text im Bild stehen soll; flux2 nur, wenn Veiko ausdrücklich höchste Qualität verlangt (dauert mehrere Minuten). Läuft sofort.
- {"aktion":"visualisierung","beschreibung":"was dargestellt werden soll, mit allen Inhalten (Schritte, Begriffe, Zahlen) auf Deutsch","titel":"kurzer Titel"} -- zeichnet ein Schaubild (Ablauf, Mindmap, Diagramm, Vergleich). Läuft sofort.
- {"aktion":"oeffnen","art":"ergebnis|langlauf|aufgabe|vorgang|projekt|notiz|gespraech|datei","id":"r…|l…|t…|v…|p…|n…|d… aus LAGE/KONTEXT","titel":"der Titel, wie Veiko ihn nennt"} -- öffnet GENAU DIESES eine Ding sofort, ohne Rückfrage (ändert nichts): „öffne das Ergebnis zu X“ = art ergebnis, „zeig mir den Langläufer X“ = art langlauf. Das Ergebnis eines Langläufers steht in LANGLÄUFER als „Ergebnis r…“. Kennst du die id nicht sicher, lass sie weg und gib nur den titel -- das Cockpit sucht dann selbst.
- {"aktion":"zeigen","ziel":"board|briefing|inbox|projects|team|neo|system|watchdog|website_stand|brainstrom|exo|langlauf|aktionen|modelle|einstellungen|memory|versionen|usage|explorer|empfehlungen|uebersicht_modelle|installiert|optimierung|neue_modelle|alle_aufgaben|alle_notizen|neuer_langlaeufer"} -- öffnet einen Bereich oder Abschnitt des Cockpits sofort (system = Stack: Server, Updates, WatchDog, ganz unten website_stand = Stand der Website; langlauf = LongRuns; usage = Verbrauch an Token, Kosten und Strom nach Projekt, Aufgabe, Modell; explorer = alle erzeugten Inhalte zum Suchen und Filtern; memory = was das Team über Veiko weiß, unter Settings; versionen = Versionsverlauf des Cockpits (was sich wann geändert hat), unter Settings; empfehlungen = Recommendations, alle Empfehlungen zu Server, Software, Modellen und Website; optimierung = Modell-Revision, neue_modelle = Neu bei Ollama).
- {"aktion":"zeigen","ziel":"chat","wer":"Name des Teammitglieds"} -- öffnet den Chat mit diesem Mitglied (Neo: ziel neo).
- {"aktion":"werkzeug","was":"erfassen|suche|hell|dunkel|zurueck|fenster_zu|ueberblick|runter|hoch|anfang|ende"} -- Capture öffnen, Suche öffnen, helle oder dunkle Darstellung, eine Seite zurück, oberstes Fenster schließen; ueberblick = Fenster mit den neuesten Ergebnissen und Vorschaubildern („gib mir einen Überblick“, „zeig mir den aktuellen Stand“); runter/hoch/anfang/ende = im offenen Fenster bzw. auf der Seite blättern. Sofort, ohne Rückfrage. Will Veiko „mit dem Advisory Board sprechen“: ziel board. Stellt er dabei schon eine Frage ans Board, gib sie als "frage" mit -- das Board antwortet dann selbst, du antwortest nicht an seiner Stelle.
- {"aktion":"ausarbeiten","rolle":"stratege|buch|designer|video","form":"text|aufstellung|konzept|dokument|webseite|praesentation|video","auftrag":"…","recherche":"Suchanfrage oder null","vorgang_id":"v… oder null","projekt_id":"p… oder null","aufgabe_id":"t… oder null (die Aufgabe, zu der das gehört)","stil":"vveorg|cockpit|eigen oder null","stil_text":"…"} -- stil nur bei einer Präsentation und nur, wenn Veiko das Aussehen nennt: „im VVEORG-Look“/„in meiner Vorlage“ = vveorg, „im Cockpit-Design“ = cockpit, eigene Gestaltungswünsche (Farben, Schrift, Footer) = eigen mit stil_text in seinen Worten. Sonst weglassen (dann gilt die Vorgabe, die VVEORG-Vorlage).
- {"aktion":"merken","art":"person|organisation|begriff|hoerfehler|aussprache","begriff":"…","bedeutung":"…"} -- aussprache: wie das Cockpit ein (meist englisches) Wort VORLESEN soll, in deutscher Lautschrift, z. B. begriff "Slides", bedeutung "Slaids".
- {"aktion":"notiz","text":"…","projekt_id":"p… oder null"}
- {"aktion":"projekt_neu","name":"…"}
- {"aktion":"daily","was":"anlegen|aendern|ausfuehren|pausieren|fortsetzen|loeschen","daily_id":"d… aus DAILY TASKS oder KONTEXT, bei anlegen null","titel":"kurzer Titel","auftrag":"was das Team JEDEN TAG untersuchen soll, in Veikos Worten, ausführlich","uhrzeit":"HH:MM oder null","tage":"werktags|täglich|mo,mi,fr oder null","rolle":"stratege|buch|designer|video|cockpit oder null","projekt_id":"p… oder null"} -- ein Daily Task: ein täglicher Auftrag ans Team, aus dem jeden Tag ein Briefing entsteht (Seite Daily Tasks). „Lass das Team jeden Morgen … beobachten“, „ich will täglich ein Briefing zu …“ = anlegen (Vorgabe werktags 06:30, Clayton). „Führ ihn jetzt aus“ = ausfuehren. Bei aendern nur die Felder, die sich ändern. Fragen ZUM Briefing beantwortest du selbst aus dem KONTEXT; „untersuche das tiefer“ ist ausarbeiten mit ergebnis_id des Briefings.
- {"aktion":"mail","was":"entwurf|aendern|senden","mail_id":"m… aus KONTEXT oder MAIL-ENTWÜRFE, bei entwurf null","an":"Name aus dem ADRESSBUCH oder E-Mail-Adresse","bezug_art":"ergebnis|aufgabe|notiz|datei|projekt oder null","bezug_id":"Kennung aus LAGE/KONTEXT oder null","titel":"Titel des Dings, falls die Kennung fehlt","anweisung":"was in der Mail stehen soll, in Veikos Worten (Ton, du/Sie, Bitte, Frist)","stil":"kuerzer|freundlicher|foermlicher|klarer|englisch|korrektur oder null"} -- eine E-Mail. „Schick das Ergebnis an Hanna“ = entwurf: das Cockpit legt den Entwurf an, formuliert ihn, hängt das Ding an und zeigt ihn; abgeschickt wird erst auf Veikos Ja. „Mach sie kürzer“, „füg Lisa in Kopie hinzu“ (dann an = alle Empfänger) = aendern. senden NUR, wenn Veiko den Entwurf abschicken will. Formuliere den Mailtext NIE selbst in deiner Antwort -- das macht das Cockpit.
- {"aktion":"vorgemerkt","vorgang_id":"v… aus VORGEMERKT","was":"freigeben|erledigt|verwerfen","anweisung":"bei freigeben: was das Team jetzt tun soll, in Veikos Worten, oder leer"} -- entscheidet über einen vorgemerkten Case (eine Notiz, an der das Team noch nicht arbeiten sollte): freigeben = Jason plant jetzt mit der Anweisung, was das Team tut (nennt Veiko jemanden, z. B. „Clayton soll …“, steht das in der Anweisung); erledigt = ablegen, nichts mehr tun; verwerfen = weg samt der Aufgaben dazu. Braucht Veikos Ja.
- {"aktion":"neo","auftrag":"was Neo am Cockpit oder Server tun soll"} -- NUR für Programm und Server des Cockpits, NIE für Inhalte (Projekte, Aufgaben, Ergebnisse, Notizen).
- {"aktion":"langlauf","titel":"kurzer Titel","auftrag":"was in Etappen entstehen soll, in mehreren Sätzen, mit allem, was Veiko dazu gesagt hat","art":"buch|dokument|praesentation|bilder|webseite|video","rolle":"buch|stratege|designer|video oder null","projekt_id":"p… oder null","aufgabe_id":"t… oder null","pruefer":"dario|demmis","pruef_alle":3,"budget":5} -- ein LongRun: ein großes Vorhaben (ein ganzes Buch, eine große Präsentation, ein ausführliches Konzept, eine Studie, eine Strategie, ein Leitfaden, ein langes Dokument, ein langes Video), das in Etappen entsteht und von Dario (Claude) oder Demmis (Gemini) geprüft wird. Sagt Veiko „Long Run“, „in Etappen“, „durchgängig und tief“, „komplett“, „vollständig“, „ausführlich“, „umfassend“ oder „gründlich“ zu einem Werk, das er HABEN will: IMMER langlauf, nie ausarbeiten. art praesentation für Präsentationen und Foliensätze, bilder für Bildserien und viele Bilder, webseite für Webseiten, buch für Bücher, video für Videos, sonst dokument. Nennt er Demmis/Gemini, ist pruefer demmis, sonst dario. pruef_alle: nach wie vielen Kapiteln/Teilen geprüft wird; 0 = NUR AM ENDE, wenn alles fertig ist -- immer dann, wenn Veiko „danach“, „am Ende“, „wenn es fertig ist“ oder „wenn du fertig bist“ sagt. Vorhandene Ergebnisse und Unterlagen des Projekts nimmt das Cockpit selbst dazu. Die Prüfungen kosten Geld: nenne das Budget (Vorgabe 5 Dollar) und frag immer „Soll ich das so machen?“.
- {"aktion":"pruefen","ergebnis_id":"r… aus LAGE/KONTEXT","titel":"Titel des Ergebnisses"} -- Daniel (Red Team) prüft ein VORHANDENES Ergebnis, z. B. ein Recherche-Dossier („ungeprüft“). „Lass Daniel das prüfen“ ist IMMER pruefen, NIE ausarbeiten -- eine Ausarbeitung macht etwas Neues, und sie macht nie Daniel.
- {"aktion":"extern_pruefen","wer":"dario|demmis|elon","ergebnis_id":"r… aus LAGE/KONTEXT","titel":"Titel des Ergebnisses"} -- ein Externer (Dario = Claude, Demmis = Gemini, Elon = Grok) prüft ein VORHANDENES Werk abschließend, z. B. „lass Demmis das Buch prüfen“. Kostet Geld, deshalb immer erst nach Veikos Ja. NIE pruefen (das ist Daniel) und NIE langlauf (der schreibt etwas Neues). Ob ein Externer ein Werk schon geprüft hat, steht im Steckbrief GENAU dieses Ergebnisses.
- {"aktion":"ersetzen","projekt_id":"p…","alt":"genauer bisheriger Begriff, z. B. OODA-Loop","neu":"neuer Begriff"} -- ersetzt einen Begriff in einem Projekt überall (Projektname und Ziel, Aufgaben, Ergebnisse, Cases). Für „benenne … um“, „korrigiere die Bezeichnung … durchgängig“. Braucht Veikos Ja.
- {"aktion":"brainstrom","thema":"die Idee in ein, zwei Sätzen","projekt_id":"p… oder null"} -- startet BrainStrom (eine Idee Frage für Frage zuspitzen) und öffnet die Ansicht. Läuft sofort.
- {"aktion":"brainstrom_antwort","text":"Veikos Antwort, ausformuliert"} -- beantwortet die AKTUELLE FRAGE in BrainStrom (siehe KONTEXT). „Die zweite“ oder „Option B“ heißt: der Text dieser Antwortmöglichkeit. Läuft sofort.
- {"aktion":"brainstrom_genug"} -- genug gefragt, direkt zu den Wegen. Läuft sofort.
- {"aktion":"brainstrom_weg","nummer":1} -- wählt einen der WEGE ZUR WAHL (Nummer ab 1); dann entsteht der Entwurf. Läuft sofort.
- {"aktion":"brainstrom_uebernehmen"} -- macht aus dem fertigen Entwurf ein Projekt mit Aufgaben (braucht Veikos Ja).
- {"aktion":"exo","umfang":"portfolio|projekt","projekt_id":"p… oder null"} -- startet die ExO-Bewertung (MTP, SCALE, IDEAS) und öffnet die Ansicht. Läuft sofort.
Schlage nur vor, was Veiko erkennbar will. Ohne Handlungswunsch kein Block.
WICHTIG: Du selbst führst NICHTS aus. Schreib nie „ich mache das“, „ich korrigiere“, „ich merke mir“ oder „erledigt“. Sag in einem Satz, was du vorschlägst, und schließ mit der Frage „Soll ich das so machen?“. Ausgeführt wird erst, wenn Veiko bestätigt; das Cockpit meldet es dann selbst.
PFLICHT: Jede Antwort, die mit „Soll ich das so machen?“ endet, trägt den aktionen-Block in DERSELBEN Antwort. Ohne Block kann Veikos „Ja“ nichts ausführen, und er müsste ein zweites Mal bestätigen -- genau das soll nie passieren.
AUSNAHME ausarbeiten und neo bei einem klaren Auftrag: Sagt Veiko ausdrücklich, dass das Team oder Neo etwas tun soll („Lass das Team eine Präsentation erstellen“, „Neo, bau …“), ist das schon die Bestätigung. Dann KEINE Frage, sondern ein kurzer Satz, wer sich woran macht -- und IMMER der aktionen-Block dazu. Ohne Block passiert nichts; ein solcher Satz ohne Block wäre gelogen.
Sagt Veiko „ja“ auf deinen Vorschlag, gehört derselbe Vorschlag als aktionen-Block in deine Antwort.
ZUSTIMMUNG IM SATZ: Verlangt Veikos LETZTE Nachricht selbst ausdrücklich genau diese Aktion („leg das Projekt an“, „sag Jason, er soll es anlegen“, „ja, die Aufgabe kannst du anlegen“), dann setze in dieser Aktion "zugestimmt": true -- auch wenn die Nachricht noch eine weitere Frage enthält. Dann KEINE Rückfrage dazu, sondern ein kurzer Satz, was passiert; das Cockpit führt es aus. Ohne ausdrücklichen Wunsch in seiner letzten Nachricht nie "zugestimmt".
EIN KLARER BEFEHL IST DIE ZUSTIMMUNG (Veiko, 17.10.: „es soll die Dinge machen, die ich sage“): „trag ein …“, „leg eine Aufgabe an …“, „markier … als erledigt“, „verschieb … auf Freitag“, „notier dir …“, „mach ein Projekt …“ -- dann "zugestimmt": true und ein kurzer Satz, was passiert. Nachfragen nur, wenn etwas wirklich unklar ist (welche Aufgabe gemeint ist, welches Datum).
AUSNAHME bild und visualisierung: die laufen sofort los, das Ergebnis erscheint gleich im Gespräch zum Ansehen und Herunterladen. Sag nur kurz „Ich erstelle dir das Bild, es erscheint gleich hier.“ bzw. „… die Visualisierung …“ -- keine Frage. Beziehen sie sich auf das Gespräch oder KONTEXT, nimm dessen Inhalte in prompt bzw. beschreibung auf.
AUSNAHME BrainStrom und ExO (brainstrom, brainstrom_antwort, brainstrom_genug, brainstrom_weg, exo): laufen sofort. Sag nur kurz, was passiert („Ich gebe deine Antwort an BrainStrom.“) -- KEINE Frage und nicht selbst die nächste BrainStrom-Frage erfinden; die stellt BrainStrom, das Cockpit liest sie vor. Ist Veiko in BrainStrom und antwortet auf die aktuelle Frage, ist das IMMER brainstrom_antwort.
DIE NOTABSCHALTUNG (Kill Switch, Safety Shutdown) gibt es NIE über das Gespräch, auch nicht auf ausdrücklichen Wunsch: sag, dass sie nur über die Knöpfe im WatchDog geht, und biete an, den WatchDog zu öffnen.
AUSNAHME zeigen, oeffnen und werkzeug: das bedient nur das Cockpit und passiert sofort. Veiko kann das ganze Cockpit per Sprache bedienen: jede Seite, jeden Reiter, jedes Ding mit Titel. Dann KEINE Frage, sondern ein kurzer Satz wie „Ich öffne dir das Advisory Board.“ Schreibst du „ich öffne“ oder „ich zeige dir“, MUSS der Block mit zeigen oder oeffnen in derselben Antwort stehen -- ohne ihn öffnet sich nichts, und der Satz wäre gelogen. Reichst du eine Frage ans Board weiter, sag „Ich gebe deine Frage ans Advisory Board weiter.“ und antworte nicht selbst an seiner Stelle.
Wenn Veiko eine offene Entscheidung bestätigt oder ablehnt, gehört genau EINE passende entscheiden-Aktion in den Block, nicht mehr.
aufgabe_erledigt nur, wenn Veiko sagt, dass er etwas erledigt hat. Überfällig heißt nicht erledigt.
Schaut Veiko auf ein PROJEKT (siehe KONTEXT), dann geht es um dieses Projekt, solange er nichts anderes sagt: neue Aufgaben, Notizen und Ausarbeitungen gehören dorthin. Will er etwas sehen („zeig mir die Aufgaben“), nimm zeigen.
Wünscht Veiko ein Dokument, eine Präsentation, eine Recherche oder einen Entwurf: ausarbeiten (form dokument für Word, praesentation für Folien; ein Video: rolle video, form video -- das Cockpit rechnet daraus ein echtes Erklärvideo mit Sprecherstimme). Geht es um das Cockpit, den Server oder Software: neo.

Arbeitsweisen auf Zuruf: Will Veiko eine Idee zuspitzen, „brainstormen“ oder „BrainStrom“: aktion brainstrom. Will er eine „ExO-Bewertung“ oder „ExO-Analyse“: aktion exo. Ist nur ein kurzes Ideensammeln im Gespräch gemeint, antworte selbst mit nummerierten Ideen und den drei stärksten."""

STIMME_ZUSATZ = ("- Die Antwort wird VORGELESEN: höchstens vier kurze Sätze (eine erbetene Zusammenfassung bis zu acht), keine Tabellen, keine Aufzählungszeichen, keine Markdown-Zeichen.\n"
                 "- Sprich wie ein Mensch, der jemandem gegenübersitzt (22.10.2026, Veiko: „fühlt sich sehr technisch an“): ganze Sätze, "
                 "kurze Übergänge („Außerdem …“, „Und noch etwas: …“), keine Überschriften wie „Offene Entscheidungen:“. "
                 "Keine Dateinamen, Kennungen, Modellnamen oder Adressen -- sag „drei Bilder“, „die Präsentation zu ExO“. "
                 "Zahlen rund und hörbar („rund 600.000 Zeichen“, „etwa 70 Cent“).\n"
                 "- Bittet Veiko um eine Zusammenfassung, IST sie die Antwort: das Wichtigste zuerst, ganze Sätze, danach nichts mehr -- "
                 "kein Angebot, keine Rückfrage.\n"
                 "- Daten im Text so, wie man sie sagt („Freitag, 9. Oktober“), nie als 2026-10-09. Im aktionen-Block bleibt JJJJ-MM-TT.\n"
                 "- Veiko antwortet gesprochen. Ein „ja“, „mach das“, „das kannst du so tun“ auf deinen Vorschlag führt das Cockpit selbst aus; "
                 "wiederhole dann nicht denselben Vorschlag.")


def _zeit(ts: float | None) -> str:
    if not ts:
        return "?"
    d = time.time() - ts
    if d < 3600:
        return f"vor {int(d // 60)} Min."
    if d < 86400:
        return f"vor {int(d // 3600)} Std."
    return time.strftime("%d.%m.", time.localtime(ts))


WOERTER_JE_SEITE = 250   # gedruckte Sachbuchseite; so steht es auch in der Antwort


def _langlauf_zum_ergebnis(eid: str) -> dict[str, Any] | None:
    lid = db.wert("SELECT id FROM langlaeufe WHERE json_extract(daten,'$.ergebnis_id')=? ORDER BY geaendert DESC LIMIT 1", (eid,))
    return db.holen("langlaeufe", lid) if lid else None


def ergebnis_steckbrief(e: dict[str, Any], lang: bool = False) -> str:
    """Was man ueber ein Ergebnis wissen muss, ohne es zu lesen (22.10.2026). Veiko fragte im Talk
    „Wie viele Seiten hat die aktuelle Fassung?“ und „Hat Demmis das Buch schon geprueft?“ -- beides
    stand im System (95.000 Woerter; Dario hat das Buch geprueft, Demmis nur Neals Feedback dazu),
    aber nirgends, wo Talk es lesen konnte. Talk behauptete daraufhin das Falsche."""
    inhalt = e.get("inhalt") or ""
    if not inhalt and e.get("id"):
        inhalt = db.wert("SELECT inhalt FROM ergebnisse WHERE id=?", (e["id"],)) or ""
    w = len(inhalt.split())
    teile = [f"erstellt {time.strftime('%d.%m. %H:%M', time.localtime(e.get('erstellt') or 0))}",
             f"Umfang {w:,} Wörter".replace(",", ".") + (f", etwa {max(1, round(w / WOERTER_JE_SEITE))} Buchseiten (gerechnet mit {WOERTER_JE_SEITE} Wörtern je Seite)" if w >= 400 else "")]
    p = e.get("pruefung")
    if isinstance(p, str):
        try:
            p = json.loads(p or "{}")
        except ValueError:
            p = {}
    p = p or {}
    teile.append("Prüfung: " + stab.urteil_klartext(p))
    l = _langlauf_zum_ergebnis(e["id"]) if e.get("id") else None
    if l:
        d = l.get("daten") or {}
        wer: dict[str, int] = {}
        for x in d.get("pruefungen") or []:
            n = x.get("name") or x.get("wer") or "?"
            wer[n] = wer.get(n, 0) + 1
        if wer:
            teile.append("externe Prüfungen im LongRun: " + ", ".join(f"{n} {k}×" for n, k in wer.items()))
        grundlage = [m["id"] for m in d.get("material") or [] if m.get("art") == "ergebnis"]
        if grundlage:
            titel = [t for t in (db.wert("SELECT titel FROM ergebnisse WHERE id=?", (g,)) for g in grundlage[:3]) if t]
            if titel:
                teile.append("Grundlage (worauf es sich bezieht): " + "; ".join(f"„{t[:60]}“" for t in titel)
                             + (f" und {len(grundlage) - 3} weitere" if len(grundlage) > 3 else ""))
        teile.append(f"aus LongRun {l['id']}")
    if lang and p.get("begruendung"):
        teile.append("Begründung der Prüfung: " + str(p["begruendung"])[:600])
    return "; ".join(teile)


def system_kern() -> str:
    """Der feste Anfang jeder Talk-Anweisung: Regeln und Lage. senden() haengt den Rest an,
    aufwaermen() rechnet genau diesen Teil vorab durch."""
    return SYSTEM.replace("{STIMME}", "") + "\n\nLAGE:\n" + lage_text()


async def aufwaermen() -> dict[str, Any]:
    """Talk wurde geoeffnet: das Talk-Modell laden und den festen Anfang vorrechnen."""
    modell = await llm.talk_modell()
    if not modell:
        return {"ok": False, "grund": "kein Talk-Modell installiert"}
    return {"ok": True, **await llm.aufwaermen(modell, system_kern())}


def lage_text() -> str:
    teile = []
    ents = db.alle("SELECT e.*, v.titel AS vtitel FROM entscheidungen e LEFT JOIN vorgaenge v ON v.id=e.vorgang_id "
                   "WHERE e.stand='offen' ORDER BY e.erstellt LIMIT 15")
    if ents:
        teile.append("OFFENE ENTSCHEIDUNGEN:\n" + "\n".join(
            f"- {e['id']} [{e['art']}] von {stab.rollen_name(e['wer'])}: {e['frage']}" +
            (f" (Vorgang: {e['vtitel']})" if e.get("vtitel") else "") for e in ents))
    else:
        teile.append("OFFENE ENTSCHEIDUNGEN: keine")
    # Dieselbe Liste wie im Briefing links daneben (stab.neu_entstanden) --
    # vorher kannte Talk die neuen Ergebnisse gar nicht und erzaehlte etwas anderes.
    # Zeitanker (22.10.2026): "Was ist seit unserem letzten Gespraech geschehen?" liess sich nicht
    # beantworten -- Talk kannte weder die Uhrzeit noch, wann Veiko zuletzt gesprochen hatte.
    # Das "letzte Gespraech" ist das vor der laufenden Sitzung: Nachrichten mit weniger als 30 Minuten
    # Abstand gehoeren zur selben Sitzung.
    zeiten = [r["zeit"] for r in db.alle("SELECT n.zeit FROM nachrichten n JOIN gespraeche g ON g.id=n.gespraech_id "
                                         "WHERE g.art='talk' AND n.rolle='du' ORDER BY n.zeit DESC LIMIT 200")]
    davor, grenze = None, time.time()
    for z in zeiten:
        if grenze - z > 1800:
            davor = z
            break
        grenze = z
    tag = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")[time.localtime().tm_wday]
    teile.append(f"JETZT: {tag}, {time.strftime('%d.%m.%Y %H:%M')}.")
    neu = stab.neu_entstanden()
    if davor:
        seit = [e for e in neu if (e.get("bearbeitet") or 0) > davor]
        ll_fertig = db.alle("SELECT titel, geaendert FROM langlaeufe WHERE stand='fertig' AND geaendert>? ORDER BY geaendert DESC LIMIT 5", (davor,))
        teile.append(f"SEIT DEM LETZTEN GESPRÄCH ({time.strftime('%d.%m. %H:%M', time.localtime(davor))}) -- nur das gilt bei „seit unserem letzten "
                     "Gespräch“ oder „was ist inzwischen passiert“; alles andere ist älter und gehört NICHT in die Antwort:\n"
                     + ("\n".join([f"- Ergebnis {e['id']}: {e['titel'][:90]} ({time.strftime('%d.%m. %H:%M', time.localtime(e['bearbeitet']))})" for e in seit]
                                  + [f"- LongRun fertig: {l['titel'][:80]} ({time.strftime('%d.%m. %H:%M', time.localtime(l['geaendert']))})" for l in ll_fertig])
                        or "- nichts Neues: kein Ergebnis entstanden oder bearbeitet, kein LongRun fertig geworden. Sag das so und nenne zur "
                           "Orientierung das jüngste Ergebnis mit Datum."))
    if neu:
        teile.append("NEU ENTSTANDEN (letzte sieben Tage, zuletzt bearbeitete zuerst -- so steht es auch im Briefing):\n" + "\n".join(
            f"- {e['id']}: {e['titel'][:90]} (von {e['wer_name']}, bearbeitet {time.strftime('%d.%m. %H:%M', time.localtime(e['bearbeitet']))}"
            + (f", Projekt {e['projekt_name']}" if e.get("projekt_name") else "") + f") -- {ergebnis_steckbrief(e)}" for e in neu)
            + "\nWer ein Ergebnis abschließend geprüft hat, steht bei GENAU diesem Ergebnis. Ein Feedback oder Review ZU einem Werk "
              "ist ein eigenes Ergebnis; wer DAS geprüft hat, hat nicht das Werk selbst geprüft.")
    # Dieselbe Auswahl wie "Läuft gerade" im Briefing. Ist sie leer, steht das da --
    # ohne den Satz nannte Talk am 16.10. Erledigtes als "läuft gerade".
    lauf = [v for v in db.alle("SELECT id, titel, auftrag, stand FROM vorgaenge WHERE stand IN ('neu','in_arbeit','wartet') "
                               "AND quelle!='alt' ORDER BY geaendert DESC LIMIT 30")
            if v["stand"] != "wartet" or stab.auftrag_offen(v)][:6]
    teile.append("WAS GERADE LÄUFT:\n" + ("\n".join(f"- {v['id']}: {v['titel']}" for v in lauf) if lauf
                                         else "nichts -- das Team arbeitet gerade an keinem Case"))
    # Vorgemerkt (21.10.2026): geparkte Notizen, die auf Veikos Freigabe warten -- wie im Briefing.
    vm = db.alle("SELECT id, titel FROM vorgaenge WHERE stand='vorgemerkt' ORDER BY erstellt DESC LIMIT 8")
    if vm:
        teile.append("VORGEMERKT (Veiko hat gesagt: noch nicht bearbeiten; wartet auf seine Freigabe in der Inbox -- "
                     "nichts davon von selbst anfangen):\n" + "\n".join(f"- {v['id']}: {v['titel']}" for v in vm))
    # Daily Tasks (22.10.2026): was heute an taeglichen Briefings da ist oder noch kommt.
    try:
        from . import daily
        dt = daily.heute_text()
    except Exception:  # noqa: BLE001 -- die Lage darf nie an den Daily Tasks scheitern
        dt = ""
    try:
        from . import mail
        mt = mail.talk_text()
    except Exception:  # noqa: BLE001 -- die Lage darf nie an der Mail scheitern
        mt = ""
    if mt:
        teile.append(mt)
    if not dt:
        try:
            n_dt = db.wert("SELECT count(*) FROM daily") or 0
        except Exception:  # noqa: BLE001
            n_dt = 0
        teile.append("DAILY TASKS: " + (f"{n_dt} angelegt, heute noch kein Briefing." if n_dt else
                                        "keine angelegt. Auf Fragen danach sag genau das -- schlag keinen Daily Task ohne Thema vor."))
    if dt:
        teile.append("DAILY TASKS HEUTE (tägliche Briefings des Teams; Kennung d…, Briefing als Ergebnis e…):\n" + dt)
    erl = db.alle("SELECT id, titel, einordnung, geaendert FROM vorgaenge WHERE stand='fertig' AND quelle!='alt' "
                  "ORDER BY geaendert DESC LIMIT 6")
    if erl:
        teile.append("ZULETZT VOM STAB ERLEDIGT:\n" + "\n".join(
            f"- {v['id']}: {v['titel']} ({_zeit(v['geaendert'])}) {v['einordnung'][:120]}" for v in erl))
    auf = db.alle("SELECT a.id, a.titel, a.faellig, p.name FROM aufgaben a LEFT JOIN projekte p ON p.id=a.projekt_id "
                  "WHERE a.status!='erledigt' AND a.archiviert=0 ORDER BY (a.faellig='' OR a.faellig IS NULL), a.faellig, a.prio, a.erstellt DESC LIMIT 12")
    if auf:
        teile.append("OFFENE AUFGABEN:\n" + "\n".join(
            f"- {a['id']}: {a['titel']}" + (f" [{a['name']}]" if a.get("name") else "") +
            (f" fällig {a['faellig']}" if a.get("faellig") else "") for a in auf))
    # Langlaeufer mit ihrem Ergebnis (17.10.2026): "oeffne das Ergebnis zu Mensch &
    # Oekonomie" braucht die Kennung des Ergebnisses, und die stand nirgends.
    try:
        from . import langlauf
        ll = langlauf.liste()[:8]
    except Exception:  # noqa: BLE001 -- die Lage darf nie am Langlaeufer scheitern
        ll = []
    if ll:
        teile.append("LANGLÄUFER (zuletzt zuerst):\n" + "\n".join(
            f"- {x['id']}: {x['titel']} ({x['stand']}" + (f", {x['fertig']} von {x['etappen']} {x.get('etappen_name') or 'Etappen'}" if x.get("etappen") else "")
            + (f", Ergebnis {x['ergebnis_id']}" if x.get("ergebnis_id") else ", noch kein Ergebnis") + ")" for x in ll))
    # Recherche-Dossiers der letzten sieben Tage (19.10.2026): sie sind Unterlagen, keine
    # Ergebnisse, und fehlten deshalb in NEU ENTSTANDEN -- Talk wusste nichts von ihnen.
    dos = db.alle("SELECT d.id, d.name, d.erstellt, p.name AS pname, a.titel AS atitel FROM dateien d "
                  "LEFT JOIN projekte p ON p.id=d.projekt_id LEFT JOIN aufgaben a ON a.id=d.aufgabe_id "
                  "WHERE (d.name LIKE 'Recherche-Dossier%' OR d.name LIKE 'Dossier%') AND d.erstellt>? ORDER BY d.erstellt DESC LIMIT 5",
                  (time.time() - 7 * 86400,))
    if dos:
        teile.append("RECHERCHE-DOSSIERS (Unterlagen, öffnen mit art datei):\n" + "\n".join(
            f"- {x['id']}: {x['name'][:90]} ({_zeit(x['erstellt'])}" + (f", Projekt {x['pname']}" if x.get("pname") else ", ohne Projekt")
            + (f", Aufgabe {x['atitel']}" if x.get("atitel") else "") + ")" for x in dos))
    teile.append("PROJEKTE:\n" + stab.projektliste_text())
    teile.append("GEDÄCHTNIS:\n" + stab.gedaechtnis_text())
    return "\n\n".join(teile)


def beirat_text() -> str:
    """Der Beirat des alten Cockpits (nachts aufgefrischt, board.py) -- nur lesen."""
    from .konfig import ALT_DATEN
    try:
        d = json.loads((ALT_DATEN / "board-stand.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    zeilen = [f"- {p.get('name')}: {(p.get('stand') or '')[:300]}" for p in (d.get("personen") or {}).values()]
    return ("ADVISORY BOARD (Veikos Advisors, öffentlicher Stand; nichts darüber hinaus erfinden):\n"
            + "\n".join(zeilen)) if zeilen else ""


def kontext_text(k: dict[str, Any] | None) -> str:
    if not k or not k.get("id"):
        return ""
    art, kid = k.get("art"), k.get("id")
    if art in ("brainstrom", "exo"):
        from . import verfahren
        return verfahren.kontext_text(art)
    if art == "ueberblick":
        from . import ueberblick
        return ueberblick.kontext_text(k)
    if art == "daily":
        # Daily Tasks (22.10.2026): der Task mit seinem neusten Briefing, oder die Liste.
        from . import daily
        return daily.kontext_text(None if kid == "alle" else kid)
    if art == "mail":
        from . import mail
        m = mail.holen(kid) if kid != "alle" else None
        if not m:
            return "VEIKO IST AUF DER MAIL-SEITE (Entwürfe, Gesendet, Adressbuch).\n" + mail.talk_text()
        return (f"VEIKO SCHAUT AUF {'DIE GESENDETE MAIL' if m['stand'] == 'gesendet' else 'DEN MAIL-ENTWURF'} {m['id']} -- „sie“, „die Mail“ meint diese.\n"
                f"An: {m['an'] or '-'}" + (f" · Cc: {m['cc']}" if m.get("cc") else "") + f"\nBetreff: {m['betreff'] or '-'}\n"
                + (f"Anhänge: {', '.join(a['name'] for a in m['daten']['anhaenge'])}\n" if m["daten"]["anhaenge"] else "")
                + f"Text:\n{mail._html_zu_text(m.get('html') or '')[:6000] or '(noch leer)'}\n\n" + mail.talk_text())
    if art == "webspace":
        from . import webspace
        return webspace.kontext_text(k.get("pfad"))
    if art == "aktionen":
        # Current Actions (17.10.2026): dieselbe Liste wie auf der Seite.
        from . import aktionen, teamchat
        from .api import GESPRAECH_LAEUFT
        a = aktionen.sammeln(GESPRAECH_LAEUFT, teamchat.wer_name)
        zeilen = [f"- {z['art_name']}: {z['titel']}" + (f" ({z['wer']})" if z.get("wer") else "")
                  + (f", {z['schritt']}" if z.get("schritt") else "") + (f", {round(z['prozent'])} %" if z.get("prozent") is not None else "")
                  + (", PAUSIERT" if z.get("stand") == "pausiert" else "") for z in a["laufend"]]
        return ("VEIKO SCHAUT AUF CURRENT ACTIONS (alles, was gerade auf dem Server läuft; pausieren und abbrechen "
                "geht dort per Knopf, nicht über Talk).\n" + ("\n".join(zeilen) if zeilen else "Gerade läuft nichts."))
    if art == "watchdog":
        from . import systeminfo
        w = systeminfo.watchdog()
        if not w.get("bekannt"):
            return "VEIKO SCHAUT AUF DEN WATCHDOG. Der WatchDog-Dienst (vve-health) meldet gerade nichts."
        nf = w.get("notfall") or {}
        karten = ", ".join(f"Karte {g.get('index', 0) + 1} {g.get('temp_c')} °C" for g in w.get("gpu_temps") or []) or "keine gemeldet"
        automatik = "ANGEHALTEN" if w.get("automatik_angehalten") else "an" if w.get("auto_an") else "aus"
        notfall = f"{_zeit(nf.get('zeit'))}: {nf.get('grund')}" if nf else "keiner"
        return ("VEIKO SCHAUT AUF DEN WATCHDOG (wacht über Temperaturen und Dienste, schaltet im Notfall ab).\n"
                f"Grafikkarten: {karten}; Notfallschwelle {w.get('schwelle_c')} °C; Automatik {automatik}; "
                f"letzte Messung vor {w.get('alter_sek')} s.\n"
                f"Letzter Notfall: {notfall}.\n"
                f"Selbst repariert: {', '.join(w.get('reparaturen') or []) or 'nichts'}.")
    if art == "vorgang":
        v = db.holen("vorgaenge", kid)
        if not v:
            return ""
        ev = db.alle("SELECT wer, art, text FROM ereignisse WHERE vorgang_id=? ORDER BY id", (kid,))
        verlauf = "\n".join(f"- {stab.rollen_name(e['wer'])} ({e['art']}): {e['text'][:700]}" for e in ev)
        return f"VEIKO SCHAUT GERADE AUF DEN VORGANG {kid}: {v['titel']} (Stand: {v['stand']})\nVerlauf:\n{verlauf}"
    if art == "projekt":
        p = db.holen("projekte", kid)
        if not p:
            return ""
        auf = db.alle("SELECT id, titel, status FROM aufgaben WHERE projekt_id=? AND archiviert=0 ORDER BY status, erstellt DESC LIMIT 30", (kid,))
        erg = db.alle("SELECT id, titel, form, erstellt, pruefung FROM ergebnisse WHERE projekt_id=? ORDER BY erstellt DESC LIMIT 8", (kid,))
        notiz = db.alle("SELECT titel, kurz, text FROM notizen WHERE projekt_id=? ORDER BY erstellt DESC LIMIT 5", (kid,))
        return (f"VEIKO SCHAUT GERADE AUF DAS PROJEKT {kid}: {p['name']}" + (f" (Kategorie {p['kategorie']})" if p.get("kategorie") else "") + (f" -- Ziel: {p['ziel']}" if p.get("ziel") else "") +
                "\nAufgaben:\n" + "\n".join(f"- {a['id']} [{a['status']}] {a['titel']}" for a in auf) +
                ("\nErgebnisse (neueste zuerst):\n" + "\n".join(f"- {e['id']}: {e['titel']} ({e['form']}) -- {ergebnis_steckbrief(e)}" for e in erg) if erg else "") +
                ("\nJüngste Notizen:\n" + "\n".join(f"- {(n['kurz'] or n['text'] or '')[:200]}" for n in notiz) if notiz else ""))
    if art == "ergebnis":
        e = db.holen("ergebnisse", kid)
        if e:
            # 20.000 statt 8.000 Zeichen (22.10.2026): "gib mir dazu eine kurze Zusammenfassung" soll
            # mehr als die erste Seite kennen; bei laengeren Werken steht dabei, dass es gekuerzt ist.
            inhalt = e["inhalt"] or ""
            return (f"VEIKO LIEST GERADE DAS ERGEBNIS „{e['titel']}“ (id {e['id']}{', Projekt ' + e['projekt_id'] if e.get('projekt_id') else ''}) "
                    f"von {stab.rollen_name(e['rolle'])}. „Daraus“, „dazu“, „davon“, „das“ meint dieses Ergebnis.\n"
                    f"STECKBRIEF: {ergebnis_steckbrief(e, lang=True)}"
                    + (f" (Du siehst die ersten 20.000 von {len(inhalt):,} Zeichen.)".replace(",", ".") if len(inhalt) > 20000 else "")
                    + f"\n{inhalt[:20000]}")
    if art == "notiz":
        n = db.holen("notizen", kid)
        if n:
            return f"VEIKO SPRICHT ÜBER DIE NOTIZ „{n.get('titel') or ''}“ vom {n.get('datum') or '?'}:\n{(n.get('text') or n.get('kurz') or '')[:12000]}"
    if art == "datei":
        d = db.holen("dateien", kid)
        if d:
            return f"VEIKO SPRICHT ÜBER DIE UNTERLAGE „{d['name']}“:\n{(d.get('text') or '(Inhalt nicht lesbar)')[:12000]}"
    if art == "aufgabe":
        a = db.holen("aufgaben", kid)
        if a:
            p = db.holen("projekte", a.get("projekt_id") or "") if a.get("projekt_id") else None
            return (aufgabe_text(kid).replace("DIESES GESPRÄCH GEHÖRT ZUR AUFGABE", "VEIKO SCHAUT GERADE AUF DIE AUFGABE")
                    + f"\n(aufgabe_id {kid}" + (f", Projekt „{p['name']}“ projekt_id {p['id']}" if p else ", ohne Projekt") + ")")
    # Seiten ohne eigenes Ding (19.10.2026: "mit allen Elementen im Cockpit per Talk sprechen"):
    # was die Seite zeigt, in wenigen Zeilen -- dieselben Quellen wie die Seite selbst.
    if art in SEITEN_KONTEXT:
        try:
            return SEITEN_KONTEXT[art]()
        except Exception as f:  # noqa: BLE001 -- der Kontext darf eine Antwort nie verhindern
            return f"VEIKO SCHAUT AUF {k.get('titel') or art} (Stand gerade nicht lesbar: {f})."
    return ""


def _team_kontext() -> str:
    t = db.alle("SELECT id, name, titel, modell, aktiv FROM team ORDER BY reihenfolge")
    zeilen = [f"- {m['name']} ({m['titel']}): {'aktiv' if m['aktiv'] else 'pausiert'}, Modell {m['modell'] or 'Vorgabe ' + llm.vorgabe('arbeit')}" for m in t]
    return ("VEIKO SCHAUT AUF DIE TEAMSEITE (Mitglieder, Externe, Besetzung mit Modellen, Optimierung, Neu bei Ollama). "
            "Chatten mit einem Mitglied: zeigen ziel chat. Umstellen von Modellen geht dort per Knopf.\n" + "\n".join(zeilen))


def _einstellungen_kontext() -> str:
    from . import folien_stil, stimme
    e = {"stab_aktiv": stab.stab_aktiv(), "talk_stimme": stimme.gewaehlte_stimme(), "praesentation_stil": folien_stil.vorgabe()}
    return ("VEIKO SCHAUT AUF DIE SETTINGS (Freigaben, Team-Pipeline, Präsentationen, Stimme, Memory, Daten, Konto). "
            f"Team-Pipeline: {'an' if e.get('stab_aktiv') else 'aus'}; Stimme: {e.get('talk_stimme') or 'Vorgabe'}; "
            f"Präsentationen: {e.get('praesentation_stil') or 'vveorg'}. Einträge ins Memory gehen mit der Aktion merken.\n"
            "MEMORY:\n" + stab.gedaechtnis_text() + "\n\n" + _versionen_text())


def _versionen_text() -> str:
    from . import versionen
    return versionen.kontext_text()


def _usage_kontext() -> str:
    from . import usage
    return usage.kontext_text()


def _stack_kontext() -> str:
    from . import systeminfo, webspace
    w = systeminfo.watchdog()
    return ("VEIKO SCHAUT AUF DEN STACK (Server, Updates, Sicherungen, Software, WatchDog und ganz unten seine Website). "
            "Die Notabschaltung gibt es nie über Talk.\n"
            + (f"WatchDog: Grafikkarten " + ", ".join(f"{g.get('temp_c')} °C" for g in w.get("gpu_temps") or []) if w.get("bekannt") else "WatchDog meldet nichts.")
            + "\n" + webspace.stack_text())


def _empfehlungen_kontext() -> str:
    from . import systeminfo
    from .api import REVISION_ZULETZT
    e = systeminfo.EMPF_ZULETZT
    stufe = {"achtung": "JETZT", "einspielen": "empfohlen", "info": "Hinweis", "nicht": "nicht einspielen"}
    zeilen = [f"- [{stufe.get(x.get('stufe'), x.get('stufe'))}] {x.get('titel')}: {str(x.get('warum') or '')[:160]}" for x in e[:14]]
    vs = REVISION_ZULETZT.get("vorschlaege") or []
    mod = [f"- {str(v.get('platz') or '').replace('rolle:', '').replace('vorgabe:', '')}: {v.get('kandidat')} statt {v.get('bisher')} ({str(v.get('warum') or '')[:120]})" for v in vs[:8]]
    return ("VEIKO SCHAUT AUF RECOMMENDATIONS (alle Empfehlungen an einem Ort: Server und Software, Modelle für das Team, neue Modelle zum Laden, "
            "Hinweise zur Website). Einspielen, Umstellen und Laden geht dort per Knopf, nicht über Talk.\n"
            + ("Server, Software, Modellkatalog:\n" + "\n".join(zeilen) if zeilen else "Server und Software: Stand noch nicht abgerufen oder nichts offen.")
            + ("\nGemessen bessere Modelle je Rolle:\n" + "\n".join(mod) if mod else "")
            + (f"\nGesamtplan der Karten: {REVISION_ZULETZT['fazit']}" if REVISION_ZULETZT.get("fazit") else ""))


def _explorer_kontext() -> str:
    from . import explorer
    return explorer.kontext_text()


SEITEN_KONTEXT = {"team": _team_kontext, "einstellungen": _einstellungen_kontext, "usage": _usage_kontext,
                  "stack": _stack_kontext, "explorer": _explorer_kontext, "empfehlungen": _empfehlungen_kontext}


def vorschlaege_aus(text: str) -> tuple[str, list[dict[str, Any]]]:
    m = re.search(r"```aktionen\s*(.*?)(```|$)", text, re.S)
    if not m:
        return text.strip(), []
    roh = llm.json_aus(m.group(1))
    sichtbar = text[:m.start()].strip()
    liste = roh if isinstance(roh, list) else ([roh] if isinstance(roh, dict) else [])
    gut = []
    for a in liste[:6]:
        if not isinstance(a, dict) or a.get("aktion") not in AKTIONEN:
            continue
        if any(not a.get(f) for f in AKTIONEN[a["aktion"]]):
            continue
        a["label"] = beschriften(a)
        if a["label"]:
            gut.append(a)
    return sichtbar, gut


DATUM = re.compile(r"\d{4}-\d{2}-\d{2}")
ZIELE = {"ueberblick": "Überblick", "aufgaben": "Aufgaben", "zeitplan": "Zeitplan", "struktur": "Struktur", "notizen": "Notizen", "ergebnisse": "Ergebnisse",
         "verlauf": "Verlauf", "dateien": "Dateien"}
# Bereiche des Cockpits, die Talk ohne Projekt oeffnen kann.
# Neu geordnet am 19.10.2026: Team = Team + Stab & Modelle (aufklappbare Abschnitte),
# eigene Seiten Usage und Explorer, "Maschine" heisst Stack (Kennung bleibt system),
# "Langläufer" heisst LongRuns (Kennung bleibt langlauf), Memory steht unter Einstellungen.
BEREICHE = {"board": "Advisory Board", "briefing": "Briefing", "inbox": "Inbox", "projects": "Projects", "team": "Team",
            "neo": "Neo", "system": "Stack", "stack": "Stack", "watchdog": "WatchDog", "brainstrom": "BrainStrom", "exo": "ExO",
            "langlauf": "LongRuns", "aktionen": "Current Actions", "webspace": "WebSpace", "modelle": "Team: Modelle", "einstellungen": "Settings",
            "usage": "Usage", "explorer": "Explorer", "memory": "Memory", "versionen": "Settings: Versionsverlauf", "empfehlungen": "Recommendations", "website_stand": "Stack: Website",
            # Reiter und Listen (18.10.2026): erreichbar wie die Bereiche.
            "uebersicht_modelle": "Team: Besetzung und Empfehlungen", "installiert": "Installierte Modelle", "optimierung": "Optimierung",
            "neue_modelle": "Neu bei Ollama", "verbrauch": "Usage", "alle_aufgaben": "Alle Aufgaben",
            "alle_notizen": "Alle Notizen", "neuer_langlaeufer": "Neuer LongRun",
            # Fehlten bis 22.10.2026 -- ein "zeigen daily" des Modells fiel deshalb still heraus.
            "daily": "Daily Tasks", "mail": "Mail"}
# Wohin ein Ziel im Browser fuehrt (Adresse hinter #/). Fehlt es hier, ist das Ziel selbst die Adresse.
BEREICH_PFAD = {"watchdog": "system/watchdog", "stack": "system", "website_stand": "system/website", "modelle": "team/besetzung",
                "uebersicht_modelle": "team/besetzung", "installiert": "team/installiert",
                "optimierung": "team/optimierung", "neue_modelle": "team/neu", "verbrauch": "usage", "memory": "einstellungen/memory", "versionen": "einstellungen/versionen",
                "alle_aufgaben": "projects/_aufgaben", "alle_notizen": "projects/_notizen", "neuer_langlaeufer": "langlauf/neu"}
WERKZEUGE = {"erfassen": "Capture", "suche": "Suche", "hell": "Helle Darstellung", "dunkel": "Dunkle Darstellung",
             "zurueck": "Eine Seite zurück", "fenster_zu": "Fenster schließen",
             # 22.10.2026: Ueberblick-Fenster und Blaettern per Sprache
             "ueberblick": "Überblick", "runter": "Weiter nach unten", "hoch": "Nach oben", "anfang": "Ganz nach oben", "ende": "Ganz nach unten"}
# "Gib mir einen aktuellen Ueberblick", "zeig mir den aktuellen Stand", "was gibt es Neues" -- das Fenster
# mit den neuesten Ergebnissen. "Ueberblick von BVE" bleibt der Projekt-Reiter, "Stand meiner Website" die Website.
_UEBERBLICK = re.compile(r"\b(aktuell\w*\s+(überblick|ueberblick|stand|lage)|(überblick|ueberblick|stand)\s+der\s+dinge|"
                         r"gesamtüberblick|gesamtueberblick|was\s+gibt\s*(es|'s)?\s+neues|was\s+ist\s+neu|neueste[nr]?\s+ergebnisse|"
                         r"letzte[nr]?\s+ergebnisse|wo\s+stehen\s+wir|(einen|den)\s+(überblick|ueberblick)\b(?!\s+(von|über|ueber|zu)\b))", re.I)
# Blaettern: "scroll runter", "weiter nach unten", "ganz nach oben", "zurück nach oben"
# 23.10.2026: "Woll bitte mal langsam weiter nach unten" (Whisper hoerte "Woll" statt "Scroll") ging ans Modell,
# das "ich blaettere" sagte und nichts tat. Ein unbekanntes erstes Wort und "langsam" sind jetzt erlaubt.
_BLAETTERN = re.compile(r"^((bitte|kannst du|mal|noch|jetzt|und|okay|ok)\s+)*(scroll\w*|roll\w*|woll\w*|blätter\w*|blaetter\w*|geh\w*|fahr\w*|spring\w*|\w{3,8})?\s*"
                        r"(mal\s+|bitte\s+|noch\s+|weiter\s+|etwas\s+|langsam\s+|ein\s+stück\s+|ein\s+bisschen\s+|ganz\s+|wieder\s+|zurück\s+)*"
                        r"(nach\s+)?(unten|runter|oben|hoch|rauf|anfang|ende)(\s+bitte)?$", re.I)

# ---------------------------------------------------------------- Bedienen per Sprache
# Veiko, 18.10.2026: "Talk soll in der Lage sein, alles zu oeffnen, ich moechte
# komplett mit dem Cockpit sprechen und es per Sprache bedienen koennen."
# Ein klarer Bedienbefehl ("oeffne den Verbrauch", "zeig mir den Zeitplan von BVE",
# "Chat mit Neal", "zurueck") geht NICHT durch das Modell: das kostete Sekunden
# Denkzeit und vergass den Block (siehe "oeffnen" unten) -- fuer "mach das auf"
# ist beides unnoetig. Erkannt wird nur, was eindeutig ist; alles andere, auch
# "oeffne X und fass es zusammen", geht wie bisher an das Modell.
# (schluessel, Muster, Satzteil fuer "Ich oeffne dir …") -- Spezielles vor Allgemeinem.
SEITEN = [
    ("neue_modelle", r"neu bei ollama|neuen? modelle", "„Neu bei Ollama“"),
    ("verbrauch", r"usage|verbrauch|kosten|token|consumption|stromverbrauch", "Usage"),
    ("optimierung", r"optimierung|revision", "die Optimierung"),
    ("installiert", r"installiert\w*( modelle)?", "die installierten Modelle"),
    ("modelle", r"stab (und|&) modelle|modelle|besetzung", "die Besetzung im Team"),
    ("empfehlungen", r"recommendations?|empfehlungen|vorschläge|vorschlaege", "die Recommendations"),
    ("explorer", r"explorer|alle inhalte|alle ergebnisse|ablage", "den Explorer"),
    ("memory", r"memory|gedächtnis|gedaechtnis", "das Memory"),
    ("versionen", r"versionsverlauf|versionen|release\w*|changelog", "den Versionsverlauf"),
    ("website_stand", r"(stand|zustand|überblick|ueberblick) (meiner|der) (website|webseite)", "den Stand deiner Website"),
    ("neuer_langlaeufer", r"neue[nrs]? (langl(ä|ae)ufer|long ?run)", "einen neuen LongRun"),
    ("langlauf", r"langl(ä|ae)ufer|long ?runs?", "die LongRuns"),
    ("alle_aufgaben", r"(alle|meine) aufgaben|aufgabenliste", "alle Aufgaben"),
    ("alle_notizen", r"(alle|meine) notizen|notizliste", "alle Notizen"),
    ("aktionen", r"current actions|aktionen|was (gerade )?läuft", "Current Actions"),
    ("webspace", r"web ?space|meine (website|webseite|homepage)|veikovoneckern", "den WebSpace"),
    ("daily", r"daily( ?tasks?)?|tägliche[nrs]? (aufgaben|aufträge|auftraege|briefings?)|tagesbriefings?", "die Daily Tasks"),
    ("mail", r"(e-?)?mails?( ?seite)?|postausgang|(mail-?)?entwürfe|adressbuch", "die Mail-Seite"),
    ("briefing", r"briefing|startseite", "das Briefing"),
    ("inbox", r"inbox|eingang|posteingang", "die Inbox"),
    ("projects", r"projekte|projects|projektliste|projektübersicht", "die Projekte"),
    ("board", r"advisory board|\bboard\b|beirat|advisors|vordenker", "das Advisory Board"),
    ("brainstrom", r"brain ?strom|brainstorm\w*", "BrainStrom"),
    ("exo", r"\bexo\b", "ExO"),
    ("einstellungen", r"einstellungen|settings", "die Settings"),
    ("system", r"\bstack\b|maschine|\bsystem\b|server|watch ?dog|updates|sicherung\w*", "den Stack"),
    ("neo", r"\bneo\b", "Neo"),
    ("team", r"\bteam\b|teamseite", "die Teamseite"),
]
_ZURUECK = re.compile(r"^(bitte\s+)?(geh\w*\s+)?(eine seite\s+)?zurück(\s+bitte)?$|vorherige seite", re.I)
# hell/dunkel nur mit Schaltwort -- "das ist mir zu dunkel" ist eine Bemerkung, kein Befehl.
_THEMA = re.compile(r"\b(schalt\w*|stell\w*|wechsel\w*|mach\w*|geh\w*)\b.{0,25}\b(hell|dunkel|light|dark)\w*"
                    r"|\b(hell|dunkel|dark|light|nacht|tag)\w*[ -]?(modus|mode|ansicht|darstellung)\b", re.I)
_VERB = re.compile(r"^((bitte|kannst du|jetzt|dann|ok|okay|so|gut|und|mal|noch|ich (will|möchte|moechte))[,]?\s+)*"
                   r"(öffne|oeffne|zeig|zeige|geh|gehe|wechsel|wechsle|spring|bring mich|navigier\w*)\b"
                   r"|\b(öffnen|oeffnen|aufmachen|anzeigen|zeigen|aufrufen|sehen|auf)\s*(bitte)?\??$", re.I)
_SCHLIESS = re.compile(r"^(bitte\s+)?(schließ|schliess)\w*\s+(das|dieses|den|die)?\s*(fenster|ergebnis|ergebnisfenster|aufgabe|notiz)\b|^fenster zu$", re.I)
# "Oeffne X und fass es zusammen", "geh die Aufgaben durch" ist mehr als Bedienen -- das bekommt das Modell.
_UND_MEHR = re.compile(r"\bund\s+(dann\s+|danach\s+|sag\s+mir\s+)?(fass|sag|erklär|erklaer|schreib|mach|erstell|lies|les|prüf|pruef|gib|schick|trag|leg|frag|such|vergleich|bewert)\w*"
                       r"|\bdurch\b|\bwarum\b|\bwie\b|\bwelche\w*\b", re.I)
_VERB_IRGENDWO = re.compile(r"\b(öffne\w*|oeffne\w*|zeig\w*|anschau\w*|anzuschauen|anseh\w*|aufmach\w*|wechsel\w*|meine die seite)\b", re.I)
_CHAT_WORT = re.compile(r"\b(chat|chatten|sprechen|reden|gespräch|gespraech|schreiben)\b", re.I)
_REITER = (("zeitplan", r"zeitplan|gantt|termine"), ("struktur", r"struktur"), ("aufgaben", r"aufgaben"),
           ("notizen", r"notizen"), ("ergebnisse", r"ergebnisse"), ("verlauf", r"verlauf"),
           ("dateien", r"dateien|unterlagen|anhänge"), ("ueberblick", r"überblick|ueberblick"))
REITER_SATZ = {"ueberblick": "den Überblick", "aufgaben": "die Aufgaben", "zeitplan": "den Zeitplan", "struktur": "die Struktur",
               "notizen": "die Notizen", "ergebnisse": "die Ergebnisse", "verlauf": "den Verlauf", "dateien": "die Dateien"}


def _mitglied_im_text(t: str) -> dict[str, Any] | None:
    for m in db.alle("SELECT id, name FROM team WHERE aktiv=1"):
        if m.get("name") and re.search(r"\b" + re.escape(m["name"]) + r"\b", t, re.I):
            return m
    return None


def oeffnen_satz(o: dict[str, Any]) -> str:
    artikel = "den " if o["art"] in ("langlauf", "vorgang", "daily") else "die " if o["art"] in ("aufgabe", "notiz", "datei") else "das "
    titel = str(o.get("titel") or "")
    if o["art"] == "datei":
        # Gesprochen klingt "FR5_MAGAZIN_AUSGABE_2026_V10.pptx" wie Buchstabensalat: Endung weg, Unterstriche zu Leerzeichen.
        titel = re.sub(r"\s+", " ", re.sub(r"\.[a-z0-9]{2,5}$", "", titel, flags=re.I).replace("_", " ")).strip()
    return f"Ich öffne dir {artikel}{OEFFNEN_NAME[o['art']]} „{titel[:90]}“."


def bedienung_erkennen(text: str, kontext: dict | None = None, gid: str | None = None) -> dict[str, Any] | None:
    """Ein reiner Bedienbefehl -> {satz, zeigen|oeffnen|werkzeug}; sonst None (dann antwortet das Modell)."""
    t = re.sub(r"[.!]+$", "", (text or "").strip()).strip()
    # Blaettern (22.10.2026): kein Satz dazu -- "Ich scrolle nach unten" vorzulesen dauerte laenger als
    # das Scrollen. VOR der Ja-Pruefung: "ganz nach unten bitte" ist kein Ja auf eine Frage.
    # Kommas ("Okay, scroll mal runter") trennen fuer das Muster nichts -- Whisper setzt sie nach Gefuehl.
    b = _BLAETTERN.search(re.sub(r"\s+", " ", re.sub(r"[,;:]", " ", t)).strip()) if t else None
    # "Okay, oeffne die Daily Task" und "Ja, aber ich will die Daily Task sehen" sind kein Ja auf eine
    # Frage, sondern Bedienung (22.10.2026: beide liefen deshalb am Bedienen vorbei ins Leere).
    oeffnen_wort = bool(_VERB_IRGENDWO.search(t)) if t else False
    if not b and (not t or len(t.split()) > 18 or _UND_MEHR.search(t) or (ist_ja(t) and not oeffnen_wort)):
        return None
    if _SCHLIESS.search(t):
        return {"satz": "Ich schließe das Fenster.", "werkzeug": "fenster_zu"}
    if b:
        w = b.group(0).lower()
        ganz = bool(re.search(r"\bganz\b|anfang|ende", w))
        runter = bool(re.search(r"unten|runter|ende", w))
        return {"satz": "", "werkzeug": ("ende" if runter else "anfang") if ganz else ("runter" if runter else "hoch")}
    # Ueberblick-Fenster (22.10.2026) -- mit gesprochener Kurzfassung, ohne Modell.
    if _UEBERBLICK.search(t) and not re.search(r"website|webseite|homepage", t, re.I) and not oeffnen_suchen(re.sub(_UEBERBLICK, " ", t), "projekt"):
        from . import ueberblick
        eintraege = ueberblick.liste()
        return {"satz": ueberblick.satz(eintraege, ueberblick.lage()), "werkzeug": "ueberblick"}
    # Im Ueberblick: "oeffne das zweite", "zeig mir Nummer drei", "das letzte"
    from . import ueberblick as _ub
    ub_id = _ub.aus_kontext(kontext, t)
    if ub_id and re.search(r"\b(öffne|oeffne|zeig\w*|mach\w*|auf|nimm|geh\w*)\b", t, re.I):
        e = db.holen("ergebnisse", ub_id)
        if e:
            from .api import kurztitel
            o = {"art": "ergebnis", "id": ub_id, "titel": kurztitel(e)}
            return {"satz": oeffnen_satz(o), "oeffnen": o}
    if _ZURUECK.search(t):
        return {"satz": "Ich gehe eine Seite zurück.", "werkzeug": "zurueck"}
    # Ein aufklappbarer Abschnitt der offenen Seite (23.10.2026: "zeig mir alle externen Teammitglieder",
    # "oeffne die Sektion Extern" -- zweimal "nichts gefunden"). Die Abschnitte schickt die Oberflaeche mit.
    abschnitte = (kontext or {}).get("abschnitte") or []
    if abschnitte and (oeffnen_wort or re.search(r"\b(sektion|abschnitt|bereich|aufklapp\w*|klapp\w*)\b", t, re.I)):
        gesucht = _woerter(re.sub(r"\b(sektion|abschnitt|bereich|aufklapp\w*|klapp\w*)\b", " ", t, flags=re.I))
        beste = None
        for a in abschnitte:
            w = _woerter(str(a.get("titel") or ""))
            # Auch Wortteile: "Teammitglieder" enthaelt "mitglied", "externen" -> "extern".
            n = len(w & gesucht) + sum(1 for x in w for y in gesucht if x != y and len(x) >= 5 and (x in y or y in x))
            if n and (not beste or n > beste[0]):
                beste = (n, a)
        if beste:
            return {"satz": f"Ich klappe dir „{beste[1]['titel']}“ auf.", "werkzeug": "abschnitt:" + str(beste[1]["id"])}
    # "Zeig mir alle (meine) offenen Aufgaben" (23.10.2026: angekuendigt, nicht geoeffnet).
    if oeffnen_wort and re.search(r"\balle\b.{0,25}\baufgaben\b", t, re.I):
        return {"satz": "Ich öffne dir alle offenen Aufgaben.", "zeigen": {"ziel": "alle_aufgaben"}}
    if oeffnen_wort and re.search(r"\balle\b.{0,25}\bnotizen\b", t, re.I):
        return {"satz": "Ich öffne dir alle Notizen.", "zeigen": {"ziel": "alle_notizen"}}
    if _THEMA.search(t) and "?" not in t:
        dunkel = re.search(r"dunkel|dark|nacht", t, re.I)
        return {"satz": "Ich schalte auf " + ("dunkel." if dunkel else "hell."), "werkzeug": "dunkel" if dunkel else "hell"}
    # "Ich will mit Clayton sprechen" -- ein Wunsch nach dem Chat, auch ohne "oeffne".
    m = _mitglied_im_text(t)
    if m and re.search(r"\bmit\s+" + re.escape(m["name"]) + r"\s+(sprechen|reden|chatten|schreiben)\b", t, re.I) and "?" not in t:
        if m["name"].lower() == "neo":
            return {"satz": "Ich öffne dir Neo.", "zeigen": {"ziel": "neo"}}
        return {"satz": f"Ich öffne dir den Chat mit {m['name']}.", "zeigen": {"ziel": f"team/chat/{m['id']}"}}
    # Das Bedienwort darf auch mitten im Satz stehen ("ich wollte mir die Daily Task anschauen").
    verb = bool(_VERB.search(t)) or oeffnen_wort
    # Ohne Bedienwort nur ganz kurze Zurufe ("Verbrauch", "die Inbox") -- und nie in
    # BrainStrom/ExO, wo ein kurzes Wort meist eine Antwort auf die Frage ist.
    if not verb and (len(t.split()) > 3 or (kontext or {}).get("art") in ("brainstrom", "exo") or "?" in t):
        return None
    if verb:
        if re.search(r"\b(capture|erfass\w*)\b", t, re.I):
            return {"satz": "Ich öffne dir Capture.", "werkzeug": "erfassen"}
        if re.search(r"\b(suche|suchfeld)\b", t, re.I):
            return {"satz": "Ich öffne dir die Suche.", "werkzeug": "suche"}
        # Chat mit einem Mitglied ("oeffne den Chat mit Neal"). Neo hat seine eigene Seite.
        m = _mitglied_im_text(t)
        if m and _CHAT_WORT.search(t):
            if m["name"].lower() == "neo":
                return {"satz": "Ich öffne dir Neo.", "zeigen": {"ziel": "neo"}}
            return {"satz": f"Ich öffne dir den Chat mit {m['name']}.", "zeigen": {"ziel": f"team/chat/{m['id']}"}}
        # Ein bestimmtes Gespraech ("oeffne das Gespraech ueber das Buch").
        if re.search(r"\b(gespräch|gespraech|unterhaltung|chat)\b", t, re.I):
            g = oeffnen_suchen(t, "gespraech", ohne=gid)
            if g:
                return {"satz": f"Ich öffne dir das Gespräch „{g['titel'][:80]}“.", "oeffnen": g}
        # Reiter eines Projekts ("zeig mir den Zeitplan von BVE", im Projekt: "zeig die Aufgaben").
        reiter = next((k for k, mu in _REITER if re.search(r"\b(" + mu + r")\b", t, re.I)), None)
        if reiter and not re.search(r"\b(alle|meine)\b", t, re.I):
            ohne = re.sub(r"\b(" + "|".join(mu for _, mu in _REITER) + r")\b", " ", t, flags=re.I)
            p = oeffnen_suchen(ohne, "projekt") if _woerter(ohne) else None
            k = kontext or {}
            pid = p["id"] if p else (k.get("id") if k.get("art") == "projekt" else None)
            if pid:
                name = p["titel"] if p else (k.get("titel") or (db.holen("projekte", pid) or {}).get("name") or "")
                return {"satz": f"Ich öffne dir {REITER_SATZ[reiter]} von {name}.", "zeigen": {"ziel": reiter, "projekt_id": pid}}
            if reiter in ("aufgaben", "notizen") and not _woerter(ohne):
                return {"satz": f"Ich öffne dir alle {ZIELE[reiter]}.", "zeigen": {"ziel": "alle_" + reiter}}
    # Ein Bereich -- es sei denn, im Satz steht noch ein Titel, der ein bestimmtes Ding meint.
    seite = next(((k, mu, s) for k, mu, s in SEITEN if re.search(r"\b(" + mu + r")", t, re.I)), None)
    rest = re.sub(seite[1], " ", t, flags=re.I) if seite else t
    art_muster = "|".join(mu for _, mu in _ART_WORT)
    rest_woerter = _woerter(re.sub(art_muster, " ", rest, flags=re.I))
    if seite and not rest_woerter:
        return {"satz": f"Ich öffne dir {seite[2]}.", "zeigen": {"ziel": seite[0]}}
    if verb and rest_woerter:
        o = oeffnen_suchen(rest)
        # Ein einzelnes Wort ohne Art ("zeig mir Kalender") trifft sonst jeden Titel,
        # in dem es vorkommt -- dann nur bei einem Titel, der genau so heisst.
        if o and (re.search(art_muster, t, re.I) or len(rest_woerter) >= 2 or _woerter(o["titel"]) == rest_woerter):
            return {"satz": oeffnen_satz(o), "oeffnen": o}
    if seite and (verb or oeffnen_wort):
        # Steckt das Seitenwort in einem Titel ("das Thema Cockpit-Gedächtnis" -- 23.10.2026 ging die
        # Memory-Seite auf statt der Aufgabe "Konzept für Cockpit-Gedächtnis"), gewinnt der Titel, sobald er
        # mindestens zwei Wörter mit dem Satz teilt.
        o2 = oeffnen_suchen(t)
        if o2 and len(_woerter(o2["titel"]) & _woerter(t)) >= 2:
            return {"satz": oeffnen_satz(o2), "oeffnen": o2}
        return {"satz": f"Ich öffne dir {seite[2]}.", "zeigen": {"ziel": seite[0]}}
    return None


# ---------------------------------------------------------------- Oeffnen
# Veiko, 17.10.2026: "Oeffnen wir mal das Ergebnis von dem Auftrag zu Mensch und
# Oekonomie" -- Talk sagte zweimal "Ich oeffne dir das Ergebnisfenster" und es
# oeffnete sich nichts. Es gab nur "zeigen" (ganze Bereiche, Projekt-Reiter),
# kein einzelnes Ergebnis; und ein Satz ohne Block fiel niemandem auf. Jetzt:
# oeffnen fuer einzelne Dinge, und das Cockpit sucht selbst ueber den Titel,
# wenn das Modell keine sichere Kennung hat.
OEFFNEN_TABELLE = {"ergebnis": ("ergebnisse", "titel"), "langlauf": ("langlaeufe", "titel"), "aufgabe": ("aufgaben", "titel"),
                   "vorgang": ("vorgaenge", "titel"), "projekt": ("projekte", "name"), "notiz": ("notizen", "titel"),
                   "gespraech": ("gespraeche", "titel"), "datei": ("dateien", "name"), "daily": ("daily", "titel")}
OEFFNEN_NAME = {"ergebnis": "Ergebnis", "langlauf": "Langläufer", "aufgabe": "Aufgabe", "vorgang": "Case", "projekt": "Projekt", "notiz": "Notiz",
                "gespraech": "Gespräch", "datei": "Unterlage", "daily": "Daily Task"}
# Gespraech zuerst: "das Gespraech ueber das Kapitel" meint das Gespraech, nicht das Kapitel.
_ART_WORT = (("gespraech", r"gespräch|gespraech|unterhaltung|\bchat\b"),
             # Daily Tasks (22.10.2026) vor "ergebnis": "oeffne das Daily-Briefing zu KI" meint den Daily Task.
             ("daily", r"\bdaily\b|tägliche[nrs]?\b|taegliche[nrs]?\b|tagesbriefing"),
             # Unterlagen (19.10.2026): "oeffne das Dossier zu Verlagen" -- vor "ergebnis", sonst griffe "Dokument".
             ("datei", r"dossier|unterlage|abschrift|anhang|\bdatei|power\s?point|\bpptx?\b|\bexcel\b|\bpdf\b|word-?datei|word-?dokument|foliensatz"), ("ergebnis", r"ergebnis|resultat|kapitel|dokument|präsentation|praesentation|video|text"),
             ("langlauf", r"langläufer|langlaeufer|langlauf"), ("aufgabe", r"aufgabe|todo"),
             ("vorgang", r"\bcase|vorgang"), ("projekt", r"projekt"), ("notiz", r"notiz"))
_FUELL = {"öffne", "öffnen", "oeffne", "oeffnen", "zeig", "zeige", "zeigen", "mal", "bitte", "dem", "den", "das", "der", "die",
          "von", "zum", "zur", "und", "mir", "wir", "uns", "ergebnis", "auftrag", "auftrags", "langläufer", "aufgabe", "projekt",
          "fenster", "doch", "noch", "einmal", "kannst", "du", "ich", "möchte", "will", "sehen", "ansehen", "auf", "mach",
          # Bedienwoerter (18.10.2026) -- sonst blieben sie als "Titelwoerter" uebrig
          "gespräch", "gespraech", "chat", "unterhaltung", "über", "ueber", "geh", "gehe", "wechsel", "wechsle", "bring",
          "mich", "anzeigen", "aufmachen", "aufrufen", "jetzt", "dann", "okay", "dir", "ein", "eine", "einen", "bitte", "gerne",
          "moechte", "spring", "navigiere", "hin", "dort", "dahin", "rein", "hinein", "neue", "neuen",
          # Gesprochene Fuellwoerter (22.10.2026): "das THEMA Video-Podcast", "ich meine die SEITE Daily Task"
          "thema", "seite", "meine", "meinte", "nochmal", "eigentlich", "wollte", "anschauen", "schauen", "sehen", "aber", "ja"}


def _stamm(w: str) -> str:
    # "Videos" soll "Video" finden, "Kapiteln" "Kapitel" -- grob, aber fuer Titel reicht es.
    for end in ("en", "es", "er", "e", "s", "n"):
        if len(w) > 4 and w.endswith(end):
            return w[: -len(end)]
    return w


def _woerter(t: str) -> set[str]:
    t = (t or "").lower().replace("&", " und ")
    return {_stamm(w) for w in re.findall(r"[a-zäöüß0-9]{3,}", t) if w not in _FUELL}


def oeffnen_suchen(text: str, art: str | None = None, ohne: str | None = None) -> dict[str, Any] | None:
    """Das Ding, dessen Titel am besten zu Veikos Worten passt. Nur bei einem
    klaren Treffer (mindestens zwei gemeinsame Woerter, bzw. alle Woerter eines
    kurzen Titels) -- lieber nichts oeffnen als das Falsche."""
    # "Version 10" heisst im Dateinamen "V10" (23.10.2026: "oeffne das FR5 Magazin Version 10"),
    # "PowerPoint" heisst dort "pptx".
    text = re.sub(r"\bversion\s*(\d{1,3})\b", lambda m: f"v{int(m.group(1))} v{int(m.group(1)):02d}", text or "", flags=re.I)
    text = re.sub(r"\bpower\s?point\b", "pptx", text, flags=re.I)
    gesucht = _woerter(text)
    if not gesucht:
        return None
    if not art:
        # Das ZUERST genannte Art-Wort zaehlt (19.10.2026): "oeffne die Aufgabe Kapitel Mensch
        # und Oekonomie" oeffnete das ERGEBNIS, weil "Kapitel" (Ergebnis-Wort, Teil des Titels)
        # in der Liste vor "Aufgabe" stand. Bei gleicher Stelle gilt die Reihenfolge der Liste.
        treffer = [(m.start(), i, a) for i, (a, mu) in enumerate(_ART_WORT) for m in [re.search(mu, text or "", re.I)] if m]
        if treffer:
            # Findet die erkannte Art nichts, ueberall suchen (22.10.2026: "das Thema Video-Podcast"
            # -- "Video" klang nach einem Video-Ergebnis, gemeint war das Projekt VIDEO PODCAST).
            return oeffnen_suchen(text, min(treffer)[2], ohne) or oeffnen_suchen(text, "_alle", ohne)
    arten = [art] if art in OEFFNEN_TABELLE else ["ergebnis", "langlauf", "projekt", "aufgabe", "vorgang", "datei", "daily"]
    bestes, punkte = None, 0.0
    for a in arten:
        tab, feld = OEFFNEN_TABELLE[a]
        ordnung = "erstellt" if tab != "projekte" else "rowid"
        # Gespraeche nach letzter Aenderung; das laufende Talk-Gespraech (ohne) findet sich nie selbst.
        sql = (f"SELECT id, {feld} AS t FROM {tab} ORDER BY {ordnung} DESC LIMIT 300" if a != "gespraech" else
               "SELECT id, titel AS t FROM gespraeche WHERE id!=? AND art IN ('talk','team','neo','board') ORDER BY geaendert DESC LIMIT 300")
        for z in db.alle(sql, (ohne or "",)) if a == "gespraech" else db.alle(sql):
            w = _woerter(z["t"])
            if not w:
                continue
            gemein = len(gesucht & w)
            if gemein >= min(2, len(gesucht)) or (gemein >= 1 and gemein == len(w)):
                p = gemein + gemein / len(w)   # bei Gleichstand der kuerzere, genauere Titel; sonst der neueste (Reihenfolge)
                if a == "datei":
                    # Unterlagen in mehreren Fassungen ("…_V01", "…_V10"): bei gleich vielen Treffern die NEUESTE,
                    # nicht die mit dem kuerzesten Namen -- das war meist die aelteste.
                    p = gemein + 0.001 * gemein / len(w)
                if p > punkte:
                    bestes, punkte = {"art": a, "id": z["id"], "titel": z["t"]}, p
    return _gespraech_ort(bestes)


def _gespraech_ort(o: dict[str, Any] | None) -> dict[str, Any] | None:
    """Ein Gespraech oeffnet an seinem Ort (zuordnung.gespraechOeffnen): dafuer Art und Mitglied."""
    if o and o["art"] == "gespraech":
        g = db.holen("gespraeche", o["id"]) or {}
        k = g.get("kontext") if isinstance(g.get("kontext"), dict) else {}
        o = {**o, "g_art": g.get("art"), "wer": k.get("wer")}
    return o


def oeffnen_aufloesen(a: dict[str, Any], text: str = "") -> dict[str, Any] | None:
    art = a.get("art")
    if art in OEFFNEN_TABELLE and a.get("id"):
        tab, feld = OEFFNEN_TABELLE[art]
        z = db.holen(tab, str(a["id"]))
        if z:
            return _gespraech_ort({"art": art, "id": z["id"], "titel": z.get(feld) or ""})
    # Keine oder falsche Kennung: ueber den Titel des Modells, sonst ueber Veikos Worte.
    return oeffnen_suchen(str(a.get("titel") or ""), art) or (oeffnen_suchen(text, art) if text else None)


# Was "ersetzen" anfasst: Felder je Tabelle, immer nur Eintraege des Projekts. Notizen
# bleiben unangetastet -- sie sind Veikos Wortlaut (die Abschrift), kein Arbeitsstand.
ERSETZEN_FELDER = {"projekte": ("name", "ziel"), "aufgaben": ("titel", "notiz"),
                   "ergebnisse": ("titel", "inhalt"), "vorgaenge": ("titel", "einordnung")}


def _ersetzen_zeilen(pid: str):
    for tab, felder in ERSETZEN_FELDER.items():
        sql = f"SELECT id,{','.join(felder)} FROM {tab} WHERE " + ("id=?" if tab == "projekte" else "projekt_id=?")
        for z in db.alle(sql, (pid,)):
            yield tab, felder, z


def _ersetzen_muster(alt: str) -> re.Pattern[str]:
    """Nur am Wortanfang (19.10.2026): "ODA-Loop" -> "CUDA-Loop" machte aus "OODA-Loop"
    ein "OCUDA-Loop", weil es mitten im Wort ersetzte. Nach hinten offen, damit
    "OODA-Loops" mitgeht."""
    return re.compile(r"(?<!\w)" + re.escape(alt))


def ersetzen_zaehlen(pid: str, alt: str) -> tuple[int, int]:
    mu = _ersetzen_muster(alt)
    n = e = 0
    for _tab, felder, z in _ersetzen_zeilen(pid):
        k = sum(len(mu.findall(str(z.get(f) or ""))) for f in felder)
        n += k
        e += 1 if k else 0
    return n, e


def ersetzen_schreibweise(pid: str, alt: str) -> str | None:
    """Steht der Begriff nur als Teil eines laengeren Wortes da (Veiko sagt "ODA-Loop",
    im Projekt steht "OODA-Loop" -- Whisper hoert das doppelte O nicht), wird die eine
    Schreibweise genommen, die es wirklich gibt. Mehrere verschiedene: lieber nichts."""
    mu = re.compile(r"(?<!\w)(\w+)" + re.escape(alt))
    formen = set()
    for _tab, felder, z in _ersetzen_zeilen(pid):
        for f in felder:
            formen.update(m.group(1) + alt for m in mu.finditer(str(z.get(f) or "")))
    return formen.pop() if len(formen) == 1 else None


_PRUEF_AUFTRAG = re.compile(r"^\s*(prüf|pruef|überprüf|ueberpruef|bewerte|begutachte|gib (ein|dein) urteil)", re.I)


def _pruef_ergebnis(a: dict[str, Any]) -> dict[str, Any] | None:
    """Das Ergebnis, das geprueft werden soll: Kennung, sonst ueber Titel oder Auftrag."""
    e = db.holen("ergebnisse", str(a.get("ergebnis_id") or "")) if a.get("ergebnis_id") else None
    if e:
        return e
    # Zuerst unter den UNGEPRUEFTEN suchen (19.10.2026): "lass Daniel das zweite Recherche-
    # Dossier pruefen" traf sonst ein schon geprueftes Ergebnis, dessen Titel zufaellig mehr
    # Woerter teilte ("Pruefe das zweite Recherche-Dossier …"). Verglichen wird ueber
    # Wortanfaenge (5 Zeichen), damit "zweite" und "Zweiter" zusammenfinden.
    offen = [e for e in db.alle("SELECT id, titel, pruefung FROM ergebnisse ORDER BY erstellt DESC LIMIT 200")
             if ((e.get("pruefung") if isinstance(e.get("pruefung"), dict) else {}) or {}).get("urteil") in (None, "", "recherche", "ungeprueft")]
    stamm = lambda s: {w[:5] for w in _woerter(s or "")}  # noqa: E731
    for t in (a.get("titel"), a.get("auftrag")):
        if not t:
            continue
        gesucht = stamm(str(t))
        wertung = sorted(((len(gesucht & stamm(e["titel"])), i, e) for i, e in enumerate(offen)), key=lambda x: (-x[0], x[1]))
        if wertung and wertung[0][0] >= 2 and (len(wertung) == 1 or wertung[0][0] > wertung[1][0]):
            return db.holen("ergebnisse", wertung[0][2]["id"])
    for t in (a.get("titel"), a.get("auftrag")):
        o = oeffnen_suchen(str(t or ""), "ergebnis") if t else None
        if o:
            return db.holen("ergebnisse", o["id"])
    # Gibt es in den letzten drei Tagen GENAU EIN ungeprueftes Ergebnis, ist es gemeint.
    neu = [e for e in offen if (db.holen("ergebnisse", e["id"]) or {}).get("erstellt", 0) > time.time() - 3 * 86400]
    return db.holen("ergebnisse", neu[0]["id"]) if len(neu) == 1 else None


def beschriften(a: dict[str, Any]) -> str | None:
    art = a["aktion"]
    # "Pruefe das Dossier …" als Ausarbeitung (gemessen am 19.10.: an Neal, Form Dokument)
    # meint eine Pruefung des Vorhandenen -- dann wird daraus die Aktion pruefen.
    if art == "ausarbeiten" and _PRUEF_AUFTRAG.search(str(a.get("auftrag") or "")):
        e = _pruef_ergebnis(a)
        if e:
            a.clear()
            a.update({"aktion": "pruefen", "ergebnis_id": e["id"]})
            art = "pruefen"
    if art == "pruefen":
        e = _pruef_ergebnis(a)
        if not e:
            return None
        a["ergebnis_id"] = e["id"]
        return f"Daniel prüft „{(e['titel'] or '')[:80]}“"
    if art == "extern_pruefen":
        from . import langlauf, teamchat
        wer = EXTERN_NAME.get(str(a.get("wer") or "").lower().strip())
        e = db.holen("ergebnisse", str(a.get("ergebnis_id") or "")) if a.get("ergebnis_id") else None
        if not e:
            o = next((x for x in (oeffnen_suchen(str(t), "ergebnis") for t in (a.get("titel"), a.get("auftrag")) if t) if x), None)
            e = db.holen("ergebnisse", o["id"]) if o else None
        l = _langlauf_zum_ergebnis(e["id"]) if e else None
        if not wer or not l:
            return None
        a.update(wer=wer, ergebnis_id=e["id"], langlauf_id=l["id"])
        try:
            s = langlauf.abschluss_schaetzen(l["id"], wer)
        except ValueError:
            return None
        return (f"{teamchat.EXTERNE[wer]['name']} prüft „{(e['titel'] or '')[:70]}“ abschließend "
                f"({s['teile']} Teil{'e' if s['teile'] != 1 else ''}, geschätzt $ {s['usd']:.2f})")
    if art == "langlauf":
        from . import langlauf
        if a.get("art") not in langlauf.ARTEN:
            a["art"] = langlauf.art_aus(str(a.get("auftrag")))
        a["pruefer"] = a.get("pruefer") if a.get("pruefer") in langlauf.PRUEFER else "dario"
        try:
            a["budget"] = max(0.0, min(50.0, float(a.get("budget") or 5)))
        except (TypeError, ValueError):
            a["budget"] = 5.0
        try:
            a["pruef_alle"] = max(0, min(10, int(a.get("pruef_alle"))))
        except (TypeError, ValueError):
            a["pruef_alle"] = 3
        if len(str(a["auftrag"]).strip()) < 20:
            return None
        p = db.holen("projekte", str(a.get("projekt_id") or "")) if a.get("projekt_id") else None
        titel = str(a.get("titel") or a["auftrag"])[:70]
        wann = "am Ende" if a["pruef_alle"] == 0 else f"alle {a['pruef_alle']}"
        return (f"LongRun starten: „{titel}“ ({langlauf.ARTEN[a['art']]['name']}{', ' + p['name'] if p else ''}; "
                f"prüft {'Demmis' if a['pruefer'] == 'demmis' else 'Dario'} {wann}, Budget {a['budget']:.0f} $)")
    if art in ("entscheiden", "antworten"):
        e = db.holen("entscheidungen", a["entscheidung_id"])
        if not e or e["stand"] != "offen":
            return None
        if art == "antworten":
            return f"Antwort geben: „{str(a['text'])[:80]}“"
        return ("Ja: " if a.get("antwort") == "ja" else "Nein: ") + e["frage"][:90]
    if art == "aufgabe_neu":
        p = db.holen("projekte", a.get("projekt_id") or "") if a.get("projekt_id") else None
        return f"Aufgabe anlegen: {a['titel'][:90]}" + (f" ({p['name']})" if p else "")
    if art == "aufgabe_erledigt":
        t = db.holen("aufgaben", a["aufgabe_id"])
        return f"Als erledigt markieren: {t['titel'][:90]}" if t else None
    if art == "aufgabe_aendern":
        t = db.holen("aufgaben", a["aufgabe_id"])
        if not t:
            return None
        was = []
        if a.get("titel") and a["titel"] != t["titel"]:
            was.append(f"Titel „{str(a['titel'])[:60]}“")
        if a.get("faellig") and DATUM.fullmatch(str(a["faellig"])):
            was.append("Termin " + time.strftime("%d.%m.%Y", time.strptime(a["faellig"], "%Y-%m-%d")))
        if a.get("status") in ("offen", "erledigt") and a["status"] != t["status"]:
            was.append("Status " + a["status"])
        return f"Aufgabe „{t['titel'][:60]}“ ändern: " + ", ".join(was) if was else None
    if art == "bild":
        return f"Bild: {(a.get('titel') or a['prompt'])[:80]}"
    if art == "visualisierung":
        return f"Visualisierung: {(a.get('titel') or a['beschreibung'])[:80]}"
    if art == "zeigen":
        if a.get("ziel") == "chat":
            return a.get("wer") and f"Zeigen: Chat mit {a['wer']}"
        name = ZIELE.get(a.get("ziel")) or BEREICHE.get(a.get("ziel"))
        return name and f"Zeigen: {name}"
    if art == "werkzeug":
        return WERKZEUGE.get(a.get("was")) and f"Bedienen: {WERKZEUGE[a['was']]}"
    if art == "oeffnen":
        # Aufgeloest wird erst in senden() (mit Veikos Worten als Rueckfall).
        return f"Öffnen: {OEFFNEN_NAME.get(a.get('art'), 'Ansicht')} {str(a.get('titel') or a.get('id') or '')[:80]}".strip()
    if art == "ausarbeiten":
        return f"{stab.rollen_name(a.get('rolle') or 'stratege')} ausarbeiten lassen: {a['auftrag'][:90]}"
    if art == "merken":
        return f"Merken: {a['begriff']} = {a['bedeutung'][:80]}"
    if art == "notiz":
        return f"Als Notiz ans Team: {a['text'][:90]}"
    if art == "projekt_neu":
        return f"Projekt anlegen: {a['name'][:60]}"
    if art == "vorgemerkt":
        v = db.holen("vorgaenge", str(a.get("vorgang_id") or ""))
        if not v or v["stand"] != "vorgemerkt" or a.get("was") not in ("freigeben", "erledigt", "verwerfen"):
            return None
        return {"freigeben": f"Freigeben: „{v['titel'][:70]}“" + (f" -- {str(a.get('anweisung'))[:90]}" if a.get("anweisung") else ""),
                "erledigt": f"Ablegen, nichts mehr tun: „{v['titel'][:70]}“",
                "verwerfen": f"Verwerfen samt Aufgaben: „{v['titel'][:70]}“"}[a["was"]]
    if art == "daily":
        from . import daily
        was = a.get("was")
        if was == "anlegen":
            if not str(a.get("titel") or "").strip() or not str(a.get("auftrag") or "").strip() \
                    or re.fullmatch(r"(?i)\s*daily[\s-]*tasks?\s*", str(a.get("titel"))):
                return None
            plan = daily.zeitplan_text({"uhrzeit": daily._uhrzeit(a.get("uhrzeit")), "tage": json.dumps(daily.tage_aus_text(a.get("tage")))})
            return f"Daily Task anlegen: „{str(a['titel'])[:60]}“ ({plan}, {stab.rollen_name(a.get('rolle') if a.get('rolle') in daily.ROLLEN else 'stratege')})"
        if was not in ("aendern", "ausfuehren", "pausieren", "fortsetzen", "loeschen"):
            return None
        d = daily.holen(str(a.get("daily_id") or ""))
        if not d and a.get("titel"):
            # Kennung vergessen, Titel genannt: ueber dieselbe Titelsuche wie "oeffne …".
            t = oeffnen_suchen(str(a["titel"]), "daily")
            d = daily.holen(t["id"]) if t else None
        if not d:
            return None
        a["daily_id"] = d["id"]
        return {"aendern": f"Daily Task „{d['titel'][:60]}“ ändern",
                "ausfuehren": f"Daily Task „{d['titel'][:60]}“ jetzt ausführen",
                "pausieren": f"Daily Task „{d['titel'][:60]}“ pausieren",
                "fortsetzen": f"Daily Task „{d['titel'][:60]}“ wieder einschalten",
                "loeschen": f"Daily Task „{d['titel'][:60]}“ löschen"}[was]
    if art == "mail":
        from . import mail
        was = a.get("was")
        if was not in ("entwurf", "aendern", "senden"):
            return None
        if was != "entwurf":
            m = mail.holen(str(a.get("mail_id") or ""))
            if not m:
                # Ohne Kennung ist der juengste Entwurf gemeint -- der, ueber den gerade gesprochen wird.
                mid = db.wert("SELECT id FROM mails WHERE stand IN ('entwurf','fehler') ORDER BY geaendert DESC LIMIT 1")
                m = mail.holen(mid) if mid else None
            if not m or m["stand"] == "gesendet":
                return None
            a["mail_id"] = m["id"]
            if was == "senden":
                an = mail.adressen(m["an"])
                if not an or mail.pruefen(an) or (not mail._html_zu_text(m.get("html") or "").strip() and not m["daten"]["anhaenge"]):
                    return None
                n = len(m["daten"]["anhaenge"])
                return f"Mail abschicken an {', '.join(an)}: „{(m['betreff'] or '(ohne Betreff)')[:70]}“" + (f" mit {n} Anhang" + ("en" if n > 1 else "") if n else "")
            return f"Mail-Entwurf „{m['betreff'][:60]}“ ändern" if m.get("betreff") else f"Mail-Entwurf an {m.get('an') or 'noch niemanden'} ändern"
        if a.get("bezug_art") in mail.BEZUG and not db.holen({"ergebnis": "ergebnisse", "aufgabe": "aufgaben", "notiz": "notizen",
                                                            "datei": "dateien", "projekt": "projekte"}[a["bezug_art"]], str(a.get("bezug_id") or "")):
            o = oeffnen_suchen(str(a.get("titel") or ""), a["bezug_art"]) if a.get("titel") else None
            a["bezug_id"] = o["id"] if o else None
        an = mail.adressen(a.get("an"))
        b = mail.bezug_lesen({"art": a.get("bezug_art"), "id": a.get("bezug_id")}) if a.get("bezug_id") else None
        return (f"Mail-Entwurf an {', '.join(an) or 'noch niemanden'}" + (f" zu „{b['titel'][:60]}“" if b else "")
                + (" (Adresse nicht im Adressbuch)" if an and mail.pruefen(an) else ""))
    if art == "neo":
        return f"Neo beauftragen: {a['auftrag'][:90]}"
    if art == "ersetzen":
        p = db.holen("projekte", str(a.get("projekt_id") or ""))
        if not p or not str(a["alt"]).strip() or str(a["alt"]) == str(a["neu"]):
            return None
        n, e = ersetzen_zaehlen(p["id"], str(a["alt"]))
        if not n:
            form = ersetzen_schreibweise(p["id"], str(a["alt"]))
            if not form:
                return None
            a["alt"] = form
            n, e = ersetzen_zaehlen(p["id"], form)
        return f"Im Projekt {p['name'][:40]} „{str(a['alt'])[:40]}“ durch „{str(a['neu'])[:40]}“ ersetzen ({n} Stellen in {e} Einträgen)"
    if art == "brainstrom":
        return f"BrainStrom: {str(a['thema'])[:90]}"
    if art == "brainstrom_antwort":
        return f"Antwort an BrainStrom: {str(a['text'])[:90]}"
    if art == "brainstrom_genug":
        return "BrainStrom: direkt zu den Wegen"
    if art == "brainstrom_weg":
        try:
            return f"BrainStrom: Weg {int(a['nummer'])} wählen"
        except (TypeError, ValueError):
            return None
    if art == "brainstrom_uebernehmen":
        return "Entwurf als Projekt mit Aufgaben übernehmen"
    if art == "exo":
        p = db.holen("projekte", a.get("projekt_id") or "") if a.get("projekt_id") else None
        return "ExO-Analyse: " + (p["name"] if p and a.get("umfang") == "projekt" else "ganzes Portfolio")
    return None


async def ausfuehren(a: dict[str, Any]) -> dict[str, Any]:
    art = a["aktion"]
    if art == "entscheiden":
        return stab.entscheiden(a["entscheidung_id"], "ja" if a.get("antwort") == "ja" else "nein", a.get("text") or "")
    if art == "antworten":
        return stab.entscheiden(a["entscheidung_id"], "ja", a["text"])
    if art == "aufgabe_neu":
        pid = stab.projekt_finden(a.get("projekt_id"))
        db.anlegen("aufgaben", {"id": db.neue_id("t"), "titel": a["titel"][:200], "projekt_id": pid,
                                "status": "offen", "prio": 2, "faellig": a.get("faellig") or "", "quelle": "du",
                                "erstellt": time.time(), "geaendert": time.time()})
        return {"ok": True}
    if art == "aufgabe_erledigt":
        db.aendern("aufgaben", a["aufgabe_id"], {"status": "erledigt", "geaendert": time.time()})
        return {"ok": True}
    if art == "aufgabe_aendern":
        # Nur diese drei Felder; alles andere im Vorschlag wird nicht angefasst.
        werte: dict[str, Any] = {}
        if a.get("titel"):
            werte["titel"] = str(a["titel"])[:200]
        if a.get("faellig") and DATUM.fullmatch(str(a["faellig"])):
            werte["faellig"] = a["faellig"]
        if a.get("status") in ("offen", "erledigt"):
            werte["status"] = a["status"]
        if not werte or not db.holen("aufgaben", a["aufgabe_id"]):
            return {"ok": False, "grund": "Nichts zu ändern oder Aufgabe nicht gefunden"}
        werte["geaendert"] = time.time()
        db.aendern("aufgaben", a["aufgabe_id"], werte)
        return {"ok": True}
    if art == "ausarbeiten":
        vid = a.get("vorgang_id") if db.holen("vorgaenge", a.get("vorgang_id") or "") else None
        if vid and (db.holen("vorgaenge", vid) or {}).get("stand") == "vorgemerkt":
            # Ein Auftrag an einen vorgemerkten Case ist seine Freigabe -- so steht es auch im Verlauf.
            db.ereignis(vid, "du", "freigabe", "Freigegeben im Gespräch.\n\n" + str(a.get("auftrag") or ""))
        grundlage =db.holen("ergebnisse", str(a.get("ergebnis_id") or "")) if a.get("ergebnis_id") else None
        if not vid:
            # Mit Ergebnis als Grundlage traegt die Notiz des Vorgangs dessen Inhalt -- dieselbe
            # Form wie teamchat.ausarbeitung_starten, damit die Rolle nicht bei null anfaengt.
            text_v = a["auftrag"] + (f"\n\nGRUNDLAGE -- das Ergebnis „{grundlage['titel']}“:\n" + (grundlage.get("inhalt") or "")[:30000] if grundlage else "")
            v = stab.aus_text(text_v, quelle="gespraech", projekt_id=stab.projekt_finden(a.get("projekt_id")),
                              titel=a["auftrag"][:80])
            vid = v["id"]
            db.ausfuehren("UPDATE vorgaenge SET stand='eingeordnet' WHERE id=?", (vid,))
        stab.auftrag_setzen(vid, {"rolle": a.get("rolle"), "form": a.get("form"), "auftrag": a["auftrag"],
                                  "recherche": a.get("recherche"),
                                  # Die Aufgabe, zu der die Ausarbeitung gehoert (bezug_erkennen, 19.10.2026):
                                  # das Aufgabenfenster listet ihre Ergebnisse darueber.
                                  "aufgabe_id": a.get("aufgabe_id") if db.holen("aufgaben", str(a.get("aufgabe_id") or "")) else None,
                                  # Praesentations-Stil (folien_stil.py): nur wenn Veiko einen genannt hat, sonst die Vorgabe.
                                  "stil": a.get("stil") if a.get("stil") in ("vveorg", "cockpit") else
                                  ({"id": "eigen", "text": str(a.get("stil_text"))[:800]} if a.get("stil") == "eigen" and a.get("stil_text") else None)})
        stab.wecken()
        return {"ok": True, "vorgang_id": vid}
    if art == "merken":
        db.anlegen("gedaechtnis", {"id": db.neue_id("g"), "art": a.get("art") or "begriff", "begriff": a["begriff"][:80],
                                   "bedeutung": a["bedeutung"][:200], "bestaetigt": 1, "quelle": "talk", "erstellt": time.time()})
        return {"ok": True}
    if art == "notiz":
        v = stab.aus_text(a["text"], quelle="gespraech", projekt_id=stab.projekt_finden(a.get("projekt_id")))
        stab.wecken()
        return {"ok": True, "vorgang_id": v["id"]}
    if art == "vorgemerkt":
        if a["was"] == "freigeben":
            stab.freigeben(a["vorgang_id"], str(a.get("anweisung") or ""))
        else:
            stab.vorgang_schliessen(a["vorgang_id"], a["was"], "Im Gespräch entschieden.")
        return {"ok": True, "vorgang_id": a["vorgang_id"]}
    if art == "daily":
        from . import daily
        was = a["was"]
        try:
            if was == "anlegen":
                d = daily.anlegen(a)
                return {"ok": True, "daily_id": d.get("id"), "titel": d.get("titel")}
            did = a["daily_id"]
            if was == "ausfuehren":
                r = daily.ausfuehren(did, von_hand=True)
                return {"ok": bool(r.get("ok", True)), "daily_id": did}
            if was == "loeschen":
                daily.loeschen(did)
                return {"ok": True}
            if was in ("pausieren", "fortsetzen"):
                daily.aendern(did, {"aktiv": was == "fortsetzen"})
                return {"ok": True, "daily_id": did}
            # aendern: nur, was im Vorschlag wirklich steht -- ein leeres Feld loescht nichts.
            daily.aendern(did, {k: a[k] for k in ("titel", "auftrag", "rolle", "uhrzeit", "tage", "projekt_id") if a.get(k)})
            return {"ok": True, "daily_id": did}
        except ValueError as f:
            return {"ok": False, "grund": str(f)}
    if art == "projekt_neu":
        pid = db.neue_id("p")
        db.anlegen("projekte", {"id": pid, "name": a["name"][:80], "farbe": "#6D4AE0", "status": "aktiv",
                                "start": time.strftime("%Y-%m-%d"), "fruehere_namen": [], "sortierung": 999,
                                "erstellt": time.time(), "geaendert": time.time(), "quelle": "du"})
        return {"ok": True, "projekt_id": pid}
    if art in SOFORT_VERFAHREN or art == "brainstrom_uebernehmen":
        from . import verfahren
        if art == "brainstrom":
            verfahren.bs_starten(str(a["thema"]), a.get("projekt_id"))
        elif art == "brainstrom_antwort":
            verfahren.bs_antworten(str(a["text"]))
        elif art == "brainstrom_genug":
            verfahren.bs_genug()
        elif art == "brainstrom_weg":
            verfahren.bs_weg(int(a["nummer"]) - 1)
        elif art == "exo":
            verfahren.exo_starten(str(a.get("umfang") or "portfolio"), a.get("projekt_id"))
        else:
            return await verfahren.bs_uebernehmen()
        return {"ok": True}
    if art == "langlauf":
        from . import langlauf
        # Was zum Projekt schon da ist, geht mit -- dieselbe Vorauswahl wie beim Anlegen von Hand
        # (langlauf.bestand): Ergebnisse, Gespraeche, lesbare Unterlagen; Notizen nicht.
        material = [{"art": m["art"], "id": m["id"]} for m in langlauf.bestand(a.get("projekt_id"), a.get("aufgabe_id"))
                    if m.get("vorgewaehlt")]
        try:
            l = langlauf.anlegen(str(a.get("titel") or ""), str(a["auftrag"]), a.get("art") or "buch", a.get("projekt_id"),
                                 a.get("pruefer") or "dario", a.get("pruef_alle", 3), float(a.get("budget") or 5), a.get("rolle"), a.get("aufgabe_id"), material)
        except ValueError as f:
            return {"ok": False, "grund": str(f)}
        return {"ok": True, "langlauf_id": l.get("id"), "titel": l.get("titel"), "material": len(material)}
    if art == "mail":
        from . import mail
        try:
            if a["was"] == "senden":
                r = await mail.senden(a["mail_id"])
                return {"ok": True, "mail_id": a["mail_id"], "mail_gesendet": True, "an": r["an"], "betreff": r.get("betreff")}
            if a["was"] == "entwurf":
                m = mail.anlegen({"an": a.get("an"), "bezug": {"art": a.get("bezug_art"), "id": a.get("bezug_id")} if a.get("bezug_id") else None}, wer="talk")
                # Ohne Inhalt und ohne Bezug wird nicht formuliert (22.10.2026: das Modell schrieb sonst
                # "ich habe deine Anweisung erhalten ..." in die Mail). Der Entwurf steht, Talk fragt nach dem Text.
                stil = "entwurf" if (str(a.get("anweisung") or "").strip() or a.get("bezug_id")) else None
                geaendert = False
            else:
                m, geaendert = mail.holen(a["mail_id"]), True
                werte: dict[str, Any] = {}
                if a.get("an"):
                    werte["an"] = ", ".join(mail.adressen(a["an"]))
                if a.get("bezug_art") in ("ergebnis", "datei") and a.get("bezug_id"):
                    neu = mail.anhang_pruefen({"art": a["bezug_art"], "id": a["bezug_id"]})
                    if neu and neu not in m["daten"]["anhaenge"]:
                        werte["anhaenge"] = m["daten"]["anhaenge"] + [neu]
                if werte:
                    m = mail.aendern(m["id"], werte)
                stil = a.get("stil") if a.get("stil") in mail.AUFTRAEGE else ("entwurf" if a.get("anweisung") else None)
            text = ""
            if stil:
                v = await mail.formulieren(m["id"], stil, str(a.get("anweisung") or ""))
                m = mail.aendern(m["id"], {"html": v["html"], "betreff": v["betreff"] or m.get("betreff") or ""})
                text = v["text"]
            an = mail.adressen(m["an"])
            return {"ok": True, "mail_id": m["id"], "an": ", ".join(an), "betreff": m.get("betreff"), "text": text,
                    "geaendert": geaendert, "adresse_fehlt": not an or bool(mail.pruefen(an)),
                    "leer": not mail._html_zu_text(m.get("html") or "").strip()}
        except (ValueError, llm.ModellFehler) as f:
            return {"ok": False, "grund": str(f)}
    if art == "extern_pruefen":
        from . import langlauf
        try:
            langlauf.abschluss_starten(a["langlauf_id"], a["wer"])
        except (KeyError, ValueError) as f:
            return {"ok": False, "grund": str(f)}
        return {"ok": True, "langlauf_id": a["langlauf_id"], "extern": a["wer"]}
    if art == "pruefen":
        e = _pruef_ergebnis(a)
        if not e:
            return {"ok": False, "grund": "Ergebnis nicht gefunden"}
        if e["id"] in stab.PRUEFT_GERADE:
            return {"ok": True, "geprueft_wird": e["id"], "lief_schon": True}
        # Im Hintergrund: Daniels Pruefung dauert ein, zwei Minuten; Talk antwortet sofort.
        # Als HINTERGRUND starten, nicht mit dem Vorrang des Gespraechs: die Aufgabe erbte sonst
        # Talks Vorrang, und Veikos naechster Satz wartete 40 s hinter Daniel (gemessen 19.10.).
        ctx = contextvars.copy_context()
        ctx.run(llm.VORRANG.set, False)
        t = asyncio.create_task(stab.ergebnis_pruefen(e["id"]), context=ctx)
        _LAUFEND.add(t)
        t.add_done_callback(_LAUFEND.discard)
        return {"ok": True, "geprueft_wird": e["id"]}
    if art == "ersetzen":
        alt, neu = str(a["alt"]), str(a["neu"])
        pid = str(a.get("projekt_id") or "")
        if not db.holen("projekte", pid) or not alt.strip():
            return {"ok": False, "grund": "Projekt nicht gefunden"}
        mu = _ersetzen_muster(alt)
        n = 0
        for tab, felder, z in list(_ersetzen_zeilen(pid)):
            werte = {f: mu.sub(lambda _m: neu, str(z.get(f) or "")) for f in felder if mu.search(str(z.get(f) or ""))}
            if werte:
                n += sum(len(mu.findall(str(z.get(f) or ""))) for f in werte)
                db.aendern(tab, z["id"], werte, wer="talk")
        return {"ok": True, "ersetzt": n}
    if art == "neo":
        from . import neo
        gid = db.neue_id("g")
        db.einfuegen("gespraeche", {"id": gid, "art": "neo", "titel": a["auftrag"][:70], "erstellt": time.time(),
                                    "geaendert": time.time()})
        jid = await neo.senden(gid, a["auftrag"], [])
        return {"ok": True, "neo_gespraech": gid, "job": jid}
    return {"ok": False, "grund": "unbekannte Aktion"}


def gespraech_holen_oder_anlegen(gid: str | None, kontext: dict | None) -> str:
    if gid and db.holen("gespraeche", gid):
        return gid
    gid = db.neue_id("g")
    db.einfuegen("gespraeche", {"id": gid, "art": "talk", "titel": "Gespräch", "kontext": kontext or {},
                                "erstellt": time.time(), "geaendert": time.time()})
    return gid


async def senden(gid: str, text: str, kontext: dict | None, anhaenge: list[str], stimme: bool,
                 schnell: bool = False, netz: bool = False) -> AsyncIterator[dict]:
    voll = text
    for did in anhaenge or []:
        d = db.holen("dateien", did)
        if d and d.get("text"):
            voll += f"\n\n[Angehängt: {d['name']}]\n{d['text'][:15000]}"
        elif d:
            voll += f"\n\n[Angehängt: {d['name']} -- Inhalt nicht lesbar]"
    # Zu welcher Aufgabe gehoert das (bezug_erkennen, 19.10.2026)? Nur, wenn das
    # Gespraech nicht ohnehin von Hand zugeordnet ist -- die Hand sticht.
    z0 = zuordnung(gid)
    bez = None if (z0.get("aufgabe_id") or z0.get("projekt_id")) else bezug_erkennen(text, gid, kontext)
    db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                  (gid, "du", voll, json.dumps({"anzeige": text, "kontext": kontext or {}, "bezug": bez}, ensure_ascii=False), time.time()))
    if db.wert("SELECT titel FROM gespraeche WHERE id=?", (gid,)) == "Gespräch":
        db.ausfuehren("UPDATE gespraeche SET titel=? WHERE id=?", (text[:60] or "Gespräch", gid))
    # Ein reiner Bedienbefehl ("oeffne den Verbrauch") braucht kein Modell (bedienung_erkennen).
    bed = None if anhaenge else bedienung_erkennen(text, kontext, gid)
    # "Was hast du (in diesem Gespraech) erledigt?" -- beantwortet das Cockpit aus dem, was es
    # festgehalten hat, nicht das Modell aus dem Gedaechtnis (19.10.2026: es zaehlte eine
    # ausgefuehrte Pruefung und eine angelegte Aufgabe als "vorgeschlagen").
    if not bed and not anhaenge and ERLEDIGT_FRAGE.search(text) and len(text.split()) <= 16:
        bed = {"satz": erledigt_satz(gid)}
    if bed:
        zeig = [zeigen_ziel(bed["zeigen"])] if bed.get("zeigen") else []
        oeff = [bed["oeffnen"]] if bed.get("oeffnen") else []
        mid = db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                            (gid, "assistent", bed["satz"], json.dumps({"vorschlaege": [], "modell": "bedienung"}, ensure_ascii=False), time.time()))
        db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), gid))
        yield {"typ": "fertig", "text": bed["satz"], "vorschlaege": [], "nachricht_id": mid, "modell": "bedienung", "medien": [],
               "zeigen": [z for z in zeig if z], "oeffnen": oeff, "werkzeug": bed.get("werkzeug")}
        return
    # "Fass das zweite zusammen" im Ueberblick (22.10.2026): das gemeinte Ergebnis wird der Bezug
    # fuer das Modell und geht zugleich auf -- Veiko sieht, worueber Talk gerade spricht.
    ueb_oeffnen = None
    from . import ueberblick
    ueb_id = ueberblick.aus_kontext(kontext, text)
    if ueb_id and db.holen("ergebnisse", ueb_id):
        from .api import kurztitel
        kontext = {"art": "ergebnis", "id": ueb_id}
        ueb_oeffnen = {"art": "ergebnis", "id": ueb_id, "titel": kurztitel(db.holen("ergebnisse", ueb_id) or {})}
    verlauf = []
    for m in reversed(db.alle("SELECT rolle, text, daten FROM nachrichten WHERE gespraech_id=? ORDER BY id DESC LIMIT 12", (gid,))):
        verlauf.append({"role": "user" if m["rolle"] == "du" else "assistant",
                        "content": m["text"] if m["rolle"] == "du" else _fuers_modell(m["text"], m.get("daten") or {})})
    # Reihenfolge mit Absicht (19.10.2026): was sich selten aendert zuerst, damit Ollama den
    # Anfang aus dem Zwischenspeicher nimmt (system_kern, auch beim Vorwaermen). Uhrzeit und
    # Vorlese-Regeln kamen frueher VOR der Lage -- jede Minute und jeder Wechsel zwischen
    # Tippen und Sprechen liess so die ganze Anweisung neu rechnen.
    system = system_kern() + f"\n\n{kontext_text(kontext)}\n\nHEUTE: {time.strftime('%A, %d.%m.%Y %H:%M')}"
    st = stand_text(gid)
    if st:
        system += "\n\n" + st
    if stimme:
        system += "\n\nDIESE ANTWORT WIRD VORGELESEN:\n" + STIMME_ZUSATZ
    # Zugeordnetes Projekt und Aufgabe (17.10.2026) -- gilt fuer jede Nachricht dieses Gespraechs.
    zt = zuordnung_text(gid, (kontext or {}).get("id") if (kontext or {}).get("art") == "projekt" else None)
    if zt:
        system += "\n\n" + zt
    if bez and (kontext or {}).get("art") != "aufgabe":   # dort steht die Aufgabe schon im KONTEXT
        system += "\n\n" + bezug_text(bez)
    if re.search(r"beirat|board|vordenker", text, re.I):
        system += "\n\n" + beirat_text()
    denken, zusatz = llm.tempo(schnell)
    from . import dossier
    system += "\n\n" + zusatz + "\n\n" + dossier.ANWEISUNG
    modell = await llm.talk_modell()
    if not modell:
        yield {"typ": "fehler", "text": "Kein lokales Modell für das Gespräch installiert."}
        return
    # Internet nur, wenn Veiko es im Talk zugeschaltet hat (16.10.: "bei Talk soll
    # zunaechst nicht das Internet befragt werden ... der soll schnell und
    # fluessig sein"). Vorher lief die Pruefung bei jedem gruendlichen Satz.
    quellen: list[dict[str, str]] = []
    if netz:
        yield {"typ": "status", "text": "prüft, ob das Internet hilft …"}
        quellen = await stab.netzwissen(modell, verlauf)
        if quellen:
            system += "\n\n" + stab.netz_system(quellen)
            yield {"typ": "status", "text": f"{len(quellen)} Quellen aus dem Netz gelesen …"}
    # Links in der Nachricht werden immer geoeffnet, auch ohne Globus (quellen.py):
    # ein Link ist ein ausdruecklicher Auftrag, keine Frage des Netz-Schalters.
    from . import quellen as verlinkt
    if verlinkt.links(text):
        yield {"typ": "status", "text": "öffnet die Links aus deiner Nachricht …"}
        k = kontext or {}
        z = zuordnung(gid)
        ltext, lstatus = await verlinkt.einbinden(text, {"projekt_id": z.get("projekt_id") or (k.get("id") if k.get("art") == "projekt" else None),
                                                         "aufgabe_id": z.get("aufgabe_id"), "gespraech_id": gid, "wer": "assistent"})
        if ltext:
            system += "\n\n" + ltext
        if lstatus:
            yield {"typ": "status", "text": "; ".join(lstatus)}
    if denken:
        yield {"typ": "status", "text": "denkt gründlich nach …"}
    gesamt = ""
    # Eine Denkschleife (llm.Denkschleife) bricht ab, bevor ein Wort Antwort steht -- dann einmal
    # ohne langes Nachdenken neu (22.10.2026: "leg einen Daily Task an …" lief in zwei von drei
    # Versuchen im Kreis; Veiko sah nur eine Fehlermeldung statt einer Antwort).
    for versuch in (denken, False) if denken else (False,):
        try:
            with llm.taetig("Talk antwortet dir" + (" (gründlich)" if versuch else "")):
                async for t in llm.strom(modell, system, verlauf, temperatur=0.4, denken=versuch, num_ctx=24576):
                    gesamt += t
                    if "```aktionen" not in gesamt:
                        yield {"typ": "text", "t": t}
            break
        except llm.Denkschleife:
            if not versuch or gesamt:
                yield {"typ": "fehler", "text": "Ich habe mich beim Nachdenken verhakt. Sag es mir bitte noch einmal, gern etwas kürzer."}
                return
            yield {"typ": "status", "text": "setzt neu an …"}
        except llm.ModellFehler as f:
            yield {"typ": "fehler", "text": str(f)}
            return
    sichtbar, vorschlaege = vorschlaege_aus(gesamt)
    # Was nach Cockpit-Vermerk aussieht, hat das Modell abgeschrieben -- nie anzeigen.
    sichtbar = VERMERK_RE.sub("", sichtbar).strip()
    # Dieselbe Aktion nicht zweimal vorschlagen (gemessen: zweimal "Ja: Kronis …" in einer Antwort).
    gesehen, eindeutig = set(), []
    for v in vorschlaege:
        schluessel = json.dumps({k: v.get(k) for k in v if k not in ("label",)}, sort_keys=True, ensure_ascii=False)
        if schluessel not in gesehen:
            gesehen.add(schluessel)
            eindeutig.append(v)
    vorschlaege = eindeutig
    # Im Projekt gehoert Neues in dieses Projekt, auch wenn das Modell die Kennung vergisst.
    if kontext and kontext.get("art") == "projekt" and db.holen("projekte", kontext.get("id") or ""):
        for v in vorschlaege:
            if (v["aktion"] in ("aufgabe_neu", "notiz", "ausarbeiten", "langlauf") or (v["aktion"] == "zeigen" and v.get("ziel") in ZIELE))                     and not v.get("projekt_id"):
                v["projekt_id"] = kontext["id"]
                v["label"] = beschriften(v) or v["label"]
    _bezug_einsetzen(vorschlaege, bez)
    _kontext_einsetzen(vorschlaege, kontext)
    # Ein grosses Vorhaben wird ein LongRun, keine einzelne Ausarbeitung (19.10.2026, Veiko:
    # "dass erkannt wird, dass es ein LongRun ist, und dann wirklich richtig intensiv gearbeitet
    # wird"). Das Modell waehlt trotz Anweisung oft "ausarbeiten" -- dann entsteht ein Buch oder
    # eine grosse Praesentation in EINER Antwort. Die Regel steht in langlauf.gross, nicht hier;
    # der LongRun braucht wie immer ein Ja (die Pruefung kostet Geld).
    from . import langlauf as _ll
    gr = _ll.gross(text)
    if gr:
        umgestellt = False
        for i, v in enumerate(vorschlaege):
            if v["aktion"] != "ausarbeiten" or _PRUEF_AUFTRAG.search(str(v.get("auftrag") or "")):
                continue
            auftrag_ll = str(v.get("auftrag") or "")
            if text.strip() and text.strip()[:200] not in auftrag_ll:
                auftrag_ll = (auftrag_ll + "\n\nVeikos Worte: " + text.strip()).strip()
            neu = {"aktion": "langlauf", "titel": str(v.get("titel") or "")[:120], "auftrag": auftrag_ll, "art": gr["art"],
                   "rolle": v.get("rolle"), "projekt_id": v.get("projekt_id"), "aufgabe_id": v.get("aufgabe_id"),
                   "pruefer": gr["pruefer"], "pruef_alle": gr["pruef_alle"], "budget": 5}
            neu["label"] = beschriften(neu) or "LongRun starten"
            vorschlaege[i] = neu
            umgestellt = True
        if umgestellt:
            sichtbar = (re.sub(r"\s*Soll ich das so machen\?\s*$", "", sichtbar).rstrip() + "\n\nDas ist ein großes Vorhaben -- dafür schlage ich einen LongRun vor: "
                        "das Team plant es in Etappen und arbeitet jede gründlich aus, Daniel prüft jede Etappe"
                        + (f", und {'Demmis' if gr['pruefer'] == 'demmis' else 'Dario'} prüft am Ende das fertige Werk"
                           if gr["pruef_alle"] == 0 else "")
                        + ". Die Prüfung kostet Geld (Budget 5 Dollar). Soll ich das so machen?").strip()
    # Schon Ausgefuehrtes nicht noch einmal vorschlagen (19.10.2026: auf "Nein, warte damit"
    # bot Talk die laengst laufende Zusammenfuehrung erneut an). Gleich = gleiche Aktion und
    # gleiches Etikett in diesem Gespraech.
    schon = {(v.get("aktion"), v.get("label")) for m in db.alle("SELECT daten FROM nachrichten WHERE gespraech_id=? AND rolle='assistent'", (gid,))
             for v in ((m.get("daten") or {}).get("vorschlaege") or []) if v.get("erledigt")}
    vorschlaege = [v for v in vorschlaege if (v.get("aktion"), v.get("label")) not in schon or v["aktion"] in ("zeigen", "oeffnen", "werkzeug")]
    # "Zeigen" aendert nichts -- das Cockpit fuehrt es sofort aus, ohne Knopf.
    zeigen = [v for v in vorschlaege if v["aktion"] == "zeigen" and (v.get("projekt_id") or v.get("ziel") in BEREICHE or v.get("ziel") == "chat")]
    oeffnen_roh = [v for v in vorschlaege if v["aktion"] == "oeffnen"]
    werkzeug = next((v["was"] for v in vorschlaege if v["aktion"] == "werkzeug" and v.get("was") in WERKZEUGE), None)
    vorschlaege = [v for v in vorschlaege if v["aktion"] not in ("zeigen", "oeffnen", "werkzeug")]
    oeffnen = [o for o in (oeffnen_aufloesen(v, text) for v in oeffnen_roh[:1]) if o]
    # Angekuendigt, aber nichts geschickt (17.10.2026: zweimal "Ich oeffne dir das
    # Ergebnisfenster", und nichts geschah). Erst gezielt den Block nachfordern,
    # dann selbst ueber den Titel suchen, sonst ehrlich sagen, dass nichts aufging.
    will_oeffnen = re.search(r"\b(öffne|oeffne|öffnen|oeffnen|zeig(e)? mir|aufmachen|mach\w* .{0,40}\bauf)\b", text, re.I)
    sagt_oeffnen = re.search(r"\b(ich )?(öffne|oeffne|zeige) (dir|ich)\b", sichtbar, re.I)
    if not zeigen and not oeffnen and not werkzeug and (sagt_oeffnen or will_oeffnen):
        if sagt_oeffnen and not oeffnen_roh:
            try:
                roh = await llm.chat(modell, system, verlauf + [{"role": "assistant", "content": gesamt}, {"role": "user", "content":
                    "Du hast angekündigt, etwas zu öffnen, aber keinen ```aktionen-Block geschickt. Antworte jetzt NUR mit dem Block "
                    "(zeigen oder oeffnen) für genau das, was Veiko sehen will, ohne weiteren Text."}], temperatur=0.1, num_ctx=24576)
                _, nach = vorschlaege_aus(roh if "```aktionen" in roh else "```aktionen\n" + roh + "\n```")
                zeigen = [v for v in nach if v["aktion"] == "zeigen" and (v.get("projekt_id") or v.get("ziel") in BEREICHE)][:1]
                oeffnen = [o for o in (oeffnen_aufloesen(v, text) for v in nach if v["aktion"] == "oeffnen") if o][:1]
            except llm.ModellFehler:
                pass
        if not zeigen and not oeffnen:
            treffer = oeffnen_suchen(text)
            if treffer:
                oeffnen = [treffer]
        if not zeigen and not oeffnen:
            # Ein Bereich mitten im Satz ("du kannst das Projekt schliessen und zeig mir die Daily Task",
            # 22.10.2026: fuenfmal "nichts gefunden", obwohl die Seite gemeint und benannt war).
            seite = next(((k, s) for k, mu, s in SEITEN if re.search(r"\b(" + mu + r")", text, re.I)), None)
            if seite:
                zeigen = [{"aktion": "zeigen", "ziel": seite[0]}]
                sichtbar = re.sub(r"[^.!?\n]*\b(nichts gefunden|nicht gefunden|finde ich nicht|öffne dir|oeffne dir)\b[^.!?\n]*[.!?]?", "", sichtbar or "", flags=re.I).strip()
                sichtbar = (f"Ich öffne dir {seite[1]}.\n\n" + sichtbar).strip()
        if not zeigen and not oeffnen and sagt_oeffnen:
            sichtbar = re.sub(r"[^.!?\n]*\b(öffne|oeffne|zeige) (dir|ich)\b[^.!?\n]*[.!?]?", "", sichtbar).strip()
            sichtbar = (sichtbar + "\n\nIch habe nichts gefunden, das ich öffnen kann. Sag mir bitte den Titel, so wie er im Cockpit steht.").strip()
    if oeffnen:
        o = oeffnen[0]
        satz = oeffnen_satz(o)
        # Den Satz des Modells durch den genauen ersetzen -- es soll dastehen, WAS aufgeht. Satzweise an echten
        # Satzenden: am Punkt in "6mrmi.jpg" geschnitten blieb am 23.10. Wortsalat stehen ("jpg, 6mrmi.jpg, …").
        saetze = re.split(r"(?<=[.!?])\s+", sichtbar or "")
        rest = " ".join(s for s in saetze if not re.search(r"\b(öffne|oeffne|zeige) (dir|ich)\b", s, re.I)
                        and not re.search(r"\.\w{2,4}\b", s) and len(s.strip()) >= 25).strip()
        sichtbar = (satz + ("\n\n" + rest if rest else "")).strip()
    # Bilder und Visualisierungen kosten nur Rechenzeit: sofort starten, Ergebnis im Gespraech.
    from . import medien
    medien_jobs = []
    for v in [v for v in vorschlaege if v["aktion"] in ("bild", "visualisierung")][:2]:
        j = (medien.bild_starten(str(v["prompt"])[:1500], str(v.get("titel") or ""), str(v.get("vorlage") or "z-image"), str(v.get("format") or "quadrat"))
             if v["aktion"] == "bild" else medien.visualisierung_starten(str(v["beschreibung"])[:4000], str(v.get("titel") or "")))
        medien_jobs.append({"id": j["id"], "art": j["art"], "titel": j["titel"]})
    vorschlaege = [v for v in vorschlaege if v["aktion"] not in ("bild", "visualisierung")]
    # BrainStrom und ExO: sofort ausfuehren und die Ansicht oeffnen. Bei BrainStrom
    # wartet das Gespraech auf die naechste Frage und haengt sie an -- so wird sie
    # beim Freisprechen gleich vorgelesen, und man kann weiter antworten.
    # Veiko hat schon bestaetigt -- dann nicht noch einmal fragen (Veiko, 01.10.: "ich
    # moechte das ja nicht noch mal bestaetigen muessen, das Cockpit soll einfach
    # losarbeiten"). Zwei Faelle:
    #   1. Er sagt kurz "ja, macht das so" auf eine Frage, und das Modell haengt den
    #      Vorschlag erst JETZT an (es hatte ihn bei der Frage vergessen).
    #   2. Er erteilt ausdruecklich einen Auftrag ans Team oder an Neo. Das erzeugt
    #      nur eine Ausarbeitung (Case in der Inbox), aendert keinen Bestand.
    # Alles andere (Entscheidungen, Projekte, Aufgaben, Merken) bleibt beim Ja-Knopf.
    vorher = db.eine("SELECT id, text, daten FROM nachrichten WHERE gespraech_id=? AND rolle='assistent' ORDER BY id DESC LIMIT 1", (gid,))
    hatte_offen = bool(vorher and any(not v.get("erledigt") for v in ((vorher.get("daten") or {}).get("vorschlaege") or [])))
    bestaetigt = bool(vorher and "?" in (vorher.get("text") or "") and not hatte_offen and ist_ja(text)
                      and not _VERB_IRGENDWO.search(text) and not re.search(r"\b(aber|sondern|stattdessen)\b", text, re.I))
    auftrag = bool(AUFTRAG_AN_TEAM.search(text))
    befehl = bool(BEFEHL.search(text)) and not _ABLEHNUNG.search(text)
    # Ja auf die offenen Vorschlaege der vorigen Antwort (19.10.2026: "Ja, das solltest du
    # vorhin schon ausführen. Führe das jetzt aus" -- zu lang fuer das kurze Ja im Browser,
    # ging ans Modell, das "Ich beauftrage Neo" schrieb, und nichts lief). Dann werden
    # genau DIESE Vorschlaege ausgefuehrt; was das Modell jetzt noch einmal anhaengt, entfaellt.
    erledigt_in = None
    vorab = []
    # "Das sieht gut aus, schick die E-Mail ab" ist das Ja auf ein angebotenes Abschicken, auch ohne
    # das Wort "ja" (22.10.2026: gemessen wurde nur erneut gefragt, und danach behauptete das Modell,
    # die Mail sei raus). Gilt NUR fuer das Abschicken -- das ist ausdruecklich genug.
    vs_vorher = ((vorher or {}).get("daten") or {}).get("vorschlaege") or [] if hatte_offen else []
    senden_offen = [i for i, v in enumerate(vs_vorher) if not v.get("erledigt") and v.get("aktion") == "mail" and v.get("was") == "senden"]
    senden_ja = bool(senden_offen) and bool(re.search(r"\b(abschick\w*|absend\w*|verschick\w*|schick\w*\b.{0,40}\bab\b|raus\s*damit|kann\s+raus|senden)\b", text, re.I)) \
        and not _ABLEHNUNG.search(text) and not re.search(r"\b(noch nicht|nicht abschick|erst|ändere|aendere|kürzer|kuerzer)\b", text, re.I) \
        and not re.search(r"\?\s*$", text) and not re.match(r"\s*(hast|ist|wurde|sind|habt|wann|ob)\b", text, re.I) \
        and not re.search(r"\bschon\b.{0,30}\b(verschickt|gesendet|abgeschickt|weggeschickt|raus)\b", text, re.I)
    # "Ja, aber ich wollte die Daily Task sehen" / "Okay, oeffne …" ist kein Ja auf die offenen Vorschlaege
    # (22.10.2026: das haette ein angebotenes Abschicken ausgeloest).
    ja_klar = ist_ja(text) and not _VERB_IRGENDWO.search(text) and not re.search(r"\b(aber|sondern|stattdessen|erst)\b", text, re.I)
    if hatte_offen and (ja_klar or senden_ja):
        vs_alt = (vorher.get("daten") or {}).get("vorschlaege") or []
        idx = senden_offen if senden_ja and not ja_klar else [i for i, v in enumerate(vs_alt) if not v.get("erledigt")]
        vorab = await vorschlaege_ausfuehren(vorher["id"], idx)
        erledigt_in = {"nachricht_id": vorher["id"], "indizes": idx}
        vorschlaege = []
        sichtbar = AENDERUNG_BEHAUPTET.sub("", TEAM_BEHAUPTET.sub("", sichtbar)).strip()
    if bestaetigt and not [v for v in vorschlaege if v["aktion"] not in SOFORT_VERFAHREN]:
        # Ja gesagt, aber das Modell liefert wieder keinen Block (gemessen am 01.10.:
        # es schrieb "Annie macht sich an die Praesentation" und loeste nichts aus).
        # Einmal gezielt nachfordern -- nur den Block, nichts sonst.
        try:
            roh = await llm.chat(modell, system, verlauf + [{"role": "assistant", "content": gesamt}, {"role": "user", "content":
                "Veiko hat deinen Vorschlag mit Ja bestätigt. Antworte jetzt NUR mit dem ```aktionen-Block für genau diesen Vorschlag, ohne weiteren Text."}],
                temperatur=0.1, num_ctx=24576)
            _, nach = vorschlaege_aus(roh if "```aktionen" in roh else "```aktionen\n" + roh + "\n```")
            for v in nach:
                if kontext and kontext.get("art") == "projekt" and v["aktion"] in ("aufgabe_neu", "notiz", "ausarbeiten") and not v.get("projekt_id"):
                    v["projekt_id"] = kontext["id"]
                    v["label"] = beschriften(v) or v["label"]
            _bezug_einsetzen(nach, bez)
            vorschlaege += [v for v in nach if v["aktion"] not in ("zeigen", "bild", "visualisierung")]
        except llm.ModellFehler:
            pass
    # "Lass Daniel … pruefen" (19.10.2026): erst ohne Modell aufloesen (Kontext, Titel in Veikos
    # Worten, das eine ungepruefte Ergebnis), sonst den Block gezielt nachfordern. Gemessen:
    # das Modell antwortete "Daniel hat das bereits geprueft" -- verwechselt mit einem
    # anderen Ergebnis, das nur den Titel "Pruefe …" trug.
    # "Lass Demmis das Buch pruefen" (22.10.2026): gemessen wurde daraus zweimal Daniel und einmal ein
    # LongRun, der ein Feedback schrieb. Nennt Veiko einen Externen -- oder sagt Ja zu einem Angebot,
    # das einen Externen nannte --, ist es extern_pruefen; Daniel und ein Pruef-LongRun entfallen.
    vorher_text = str((vorher or {}).get("text") or "") if isinstance(vorher, dict) else ""
    extern_gemeint = EXTERN_PRUEFEN.search(text) or (ist_ja(text) and EXTERN_PRUEFEN.search(vorher_text))
    if not erledigt_in and extern_gemeint and not [v for v in vorschlaege if v["aktion"] == "extern_pruefen"]:
        name = next((EXTERN_NAME[w.lower()] for w in re.findall(r"\b(dario|claude|demmis|demis|dennis|gemini|elon|grok)\b",
                     extern_gemeint.group(0), re.I)), None)
        alt = next((v for v in vorschlaege if v["aktion"] in ("pruefen", "langlauf") and (v["aktion"] == "pruefen" or _PRUEF_AUFTRAG.search(str(v.get("auftrag") or "")))), None)
        a = {"aktion": "extern_pruefen", "wer": name, "titel": (alt or {}).get("titel") or text,
             "ergebnis_id": (alt or {}).get("ergebnis_id") or ((kontext or {}).get("id") if (kontext or {}).get("art") == "ergebnis" else None)}
        lab = beschriften(a)
        if not lab:
            try:
                roh = await llm.chat(modell, system, verlauf + [{"role": "assistant", "content": gesamt},
                                                                 {"role": "user", "content": f"Veiko will, dass {name or 'ein Externer'} ein VORHANDENES Werk abschließend prüft. Antworte NUR mit "
                                                                  f"```aktionen\n[{{\"aktion\":\"extern_pruefen\",\"wer\":\"{name or 'demmis'}\",\"ergebnis_id\":\"r… aus LAGE\",\"titel\":\"Titel des Werks\"}}]\n``` ohne weiteren Text."}],
                                       temperatur=0.1, denken=False)
                _, nach = vorschlaege_aus(roh if "```aktionen" in roh else "```aktionen\n" + roh + "\n```")
                a = next((v for v in nach if v["aktion"] == "extern_pruefen"), a)
                lab = a.get("label") if a.get("label") else None
            except llm.ModellFehler:
                pass
        if lab:
            a["label"] = lab
            a.pop("zugestimmt", None)
            vorschlaege = [v for v in vorschlaege if v is not alt and v["aktion"] != "pruefen"] + [a]
            sichtbar = AENDERUNG_BEHAUPTET.sub("", TEAM_BEHAUPTET.sub("", sichtbar or "")).strip()
    # Mail (22.10.2026): gemessen schrieb das Modell "Ich erstelle den Entwurf fuer Hanna" und schickte
    # keinen Block. Will Veiko eine Mail, wird der Block gezielt nachgefordert.
    am_entwurf = (kontext or {}).get("art") == "mail" and (kontext or {}).get("id") not in (None, "alle") and bool(
        MAIL_BEFEHL.search(text) or re.search(r"kürzer|kuerzer|freundlicher|förmlicher|foermlicher|englisch|klarer|korrigier|abschick|"
                                              r"drinstehen|drin stehen|reinschreiben|\binhalt\b|\btext\b|änder|aender|betreff", text, re.I)) \
        and not re.search(r"\?\s*$", text) and not re.match(r"\s*(hast|ist|wurde|sind|habt|wann|ob|was|wie)\b", text, re.I)
    if not erledigt_in and (MAIL_ABSICHT.search(text) or am_entwurf) and not [v for v in vorschlaege if v["aktion"] == "mail"]:
        try:
            roh = await llm.chat(modell, system, verlauf + [{"role": "assistant", "content": gesamt}, {"role": "user", "content":
                "Veiko will eine E-Mail. Antworte NUR mit dem ```aktionen-Block, ohne weiteren Text, z. B. "
                "```aktionen\n[{\"aktion\":\"mail\",\"was\":\"entwurf\",\"an\":\"Name oder Adresse\",\"bezug_art\":\"ergebnis\",\"bezug_id\":\"r… aus LAGE\","
                "\"titel\":\"Titel des Dings\",\"anweisung\":\"was drinstehen soll, in Veikos Worten\"}]\n``` -- "
                "bei einem offenen Entwurf (KONTEXT) stattdessen was aendern oder senden mit dessen mail_id."}],
                temperatur=0.1, denken=False, num_ctx=24576)
            _, nach = vorschlaege_aus(roh if "```aktionen" in roh else "```aktionen\n" + roh + "\n```")
            nach = [v for v in nach if v["aktion"] == "mail"][:1]
            _kontext_einsetzen(nach, kontext)
            vorschlaege += nach
        except llm.ModellFehler:
            pass
        # Gemessen am 22.10.: "Schreibe eine E-Mail an von.eckern.web.de" -- das Modell fragte zweimal
        # zurueck, statt den Entwurf anzulegen. Steht eine Adresse im Satz, legt das Cockpit ihn selbst an.
        if not [v for v in vorschlaege if v["aktion"] == "mail"] and am_entwurf and not re.search(r"\?\s*$", text):
            # Auf dem offenen Entwurf ist Veikos Satz die Aenderung -- gemessen schrieb das Modell
            # "ich habe den Entwurf aktualisiert" und schickte trotz Nachforderung keinen Block.
            a = {"aktion": "mail", "was": "aendern", "mail_id": kontext["id"], "anweisung": text}
            a["label"] = beschriften(a)
            if a["label"]:
                vorschlaege.append(a)
        if not [v for v in vorschlaege if v["aktion"] == "mail"] and not am_entwurf:
            from . import mail as _mail
            adr = _mail.adresse_im_text(text)
            if adr:
                rest = re.sub(r"(?i)\b(bitte|schreib\w*|schick\w*|send\w*|verschick\w*|(eine|die|ne)\s+)?(e-?mail|mail)\b|\ban\s+\S+(\s+(at|ät|punkt)\s+\S+)*", " ", text)
                a = {"aktion": "mail", "was": "entwurf", "an": adr, "anweisung": text if len(_woerter(rest)) >= 3 else ""}
                a["label"] = beschriften(a)
                if a["label"]:
                    vorschlaege.append(a)
    if not erledigt_in and not extern_gemeint and DANIEL_PRUEFEN.search(text) and not [v for v in vorschlaege if v["aktion"] == "pruefen"]:
        a: dict[str, Any] = {"aktion": "pruefen", "titel": text}
        if (kontext or {}).get("art") == "ergebnis":
            a["ergebnis_id"] = kontext["id"]
        lab = beschriften(a)
        if not lab:
            try:
                roh = await llm.chat(modell, system, verlauf + [{"role": "assistant", "content": gesamt},
                                                                 {"role": "user", "content": "Veiko will, dass Daniel ein VORHANDENES Ergebnis prüft. Antworte NUR mit "
                                                                  "```aktionen\n[{\"aktion\":\"pruefen\",\"ergebnis_id\":\"r… aus LAGE\",\"titel\":\"Titel des Ergebnisses\"}]\n``` ohne weiteren Text."}],
                                       temperatur=0.1, denken=False)
                _, nach = vorschlaege_aus(roh if "```aktionen" in roh else "```aktionen\n" + roh + "\n```")
                a = next((v for v in nach if v["aktion"] == "pruefen"), a)
                lab = a.get("label")
            except llm.ModellFehler:
                pass
        if lab:
            a["label"] = lab
            vorschlaege = [v for v in vorschlaege if v["aktion"] != "ausarbeiten"] + [a]
    # Nur wenn Veiko etwas veranlassen will (Auftrag, Befehl, Ja) -- in einem Lagebericht
    # ("Neal arbeitet gerade am Kapitel") ist derselbe Satz ein Bericht, keine Behauptung
    # (19.10.2026: "Ich moechte eine Gesamtlage" endete mit "konnte nicht ans Team geben").
    will_was = auftrag or befehl or ist_ja(text)
    if not erledigt_in and not bestaetigt and will_was and not [v for v in vorschlaege if v["aktion"] in ("ausarbeiten", "neo", "pruefen", "langlauf")] and (TEAM_BEHAUPTET.search(sichtbar or "") or (auftrag and not zeigen and not oeffnen and not werkzeug)):
        try:
            roh = await llm.chat(modell, system, verlauf + [{"role": "assistant", "content": gesamt}, {"role": "user", "content":
                "Du hast gesagt, das Team (oder Neo) arbeite daran, aber keinen ```aktionen-Block geschickt -- gestartet ist nichts. "
                "Antworte jetzt NUR mit dem ```aktionen-Block (ausarbeiten oder neo) für genau diesen Auftrag, ohne weiteren Text."}],
                temperatur=0.1, denken=False, num_ctx=24576)
            _, nach = vorschlaege_aus(roh if "```aktionen" in roh else "```aktionen\n" + roh + "\n```")
            nach = [v for v in nach if v["aktion"] in ("ausarbeiten", "neo")][:1]
            _kontext_einsetzen(nach, kontext)
            _bezug_einsetzen(nach, bez)
            vorschlaege += nach
        except llm.ModellFehler:
            pass
        if not [v for v in vorschlaege if v["aktion"] in ("ausarbeiten", "neo", "langlauf")] and TEAM_BEHAUPTET.search(sichtbar or ""):
            sichtbar = TEAM_BEHAUPTET.sub("", sichtbar).strip()
            sichtbar = (sichtbar + "\n\nIch konnte den Auftrag nicht ans Team geben -- gestartet ist nichts. Sag mir bitte noch einmal, wer was machen soll.").strip()
    # Auch eine Frage "Soll ich das so machen?" OHNE Block (19.10.2026: "Ich schlage vor, die
    # Aufgabe … als erledigt zu markieren. Soll ich das so machen?" -- es gab keinen Knopf, und
    # ein Ja haette nichts ausfuehren koennen).
    frage_ohne_block = bool(re.search(r"Soll ich das so machen\?\s*$", sichtbar or ""))
    # Eine erbetene Zusammenfassung oder Erklaerung aendert nichts (22.10.2026: "Fass das zweite
    # zusammen" bekam "Geaendert ist noch nichts" angehaengt, weil die Antwort "ich lege dir ... vor" sagte).
    nur_lesen = bool(re.search(r"\b(fass\w*|zusammenfass\w*|zusammenfassung|erklär\w*|erklaer\w*|worum geht|was steht|lies|vorlesen)\b", text, re.I))
    if nur_lesen and not vorschlaege:
        # Ein angehaengtes "Ich schlage vor, ... Soll ich das so machen?" ohne Aktion faellt weg --
        # gemessen am 22.10.: nach einer fertigen Zusammenfassung bot das Modell eine an.
        sichtbar = re.sub(r"\n+[^\n]*\b(ich schlage vor|schlage ich vor|soll ich (das|dir))\b[^\n]*\s*$", "", sichtbar or "", flags=re.I).strip()
    if not erledigt_in and not bestaetigt and not vorschlaege and not nur_lesen and (AENDERUNG_BEHAUPTET.search(sichtbar or "") or frage_ohne_block):
        try:
            roh = await llm.chat(modell, system, verlauf + [{"role": "assistant", "content": gesamt}, {"role": "user", "content":
                "Du hast eine Aktion angekündigt oder vorgeschlagen, aber keinen ```aktionen-Block geschickt -- es gibt nichts zum Ausführen. "
                "Antworte jetzt NUR mit dem ```aktionen-Block für genau diese Änderung, ohne weiteren Text."}],
                temperatur=0.1, denken=False, num_ctx=24576)
            _, nach = vorschlaege_aus(roh if "```aktionen" in roh else "```aktionen\n" + roh + "\n```")
            nach = [v for v in nach if v["aktion"] not in ("zeigen", "oeffnen", "werkzeug", "bild", "visualisierung")][:2]
            _kontext_einsetzen(nach, kontext)
            _bezug_einsetzen(nach, bez)
            vorschlaege += nach
        except llm.ModellFehler:
            pass
        if not vorschlaege:
            sichtbar = AENDERUNG_BEHAUPTET.sub("", sichtbar)
            sichtbar = re.sub(r"[^.!?\n]*\b(ich schlage vor|schlage ich vor)\b[^.!?\n]*[.!?]?|\s*Soll ich das so machen\?\s*$", "", sichtbar, flags=re.I).strip()
            # Auf eine FRAGE Veikos war das nur ein Angebot des Modells, keine verlangte Aenderung -- dann
            # faellt das Angebot still weg (22.10.2026: "Was ist bei den Daily Tasks los?" endete mit
            # "Geändert ist noch nichts").
            if not re.search(r"\?\s*$", text) and not re.match(r"\s*(was|wie|wo|wer|wann|warum|welche\w*|gibt es|hast du|ist)\b", text, re.I):
                sichtbar = (sichtbar + "\n\nGeändert ist noch nichts -- ich konnte das keiner Aktion zuordnen. Sag mir bitte genau, was wo geändert werden soll.").strip()
    if bestaetigt:
        if not vorschlaege:
            sichtbar = re.sub(r"[^.!?\n]*(macht sich|arbeitet an|erscheint in der Inbox)[^.!?\n]*[.!?]?", "", sichtbar).strip()
            sichtbar = (sichtbar + "\n\nIch konnte deinem Ja keinen Auftrag zuordnen, gestartet ist noch nichts. Sag mir bitte noch einmal, was das Team tun soll.").strip()
    # Vorgemerktes freigeben (21.10.2026): gemessen schlug das Modell "freigeben" UND eine eigene
    # Ausarbeitung an Clayton vor -- die Ausarbeitung lief sofort (Auftrag ans Team) und entstand
    # ohne Bezug zur Notiz, das Konzept waere doppelt gekommen. Die Freigabe ist der Weg: eine
    # Ausarbeitung daneben faellt weg, ihr Auftrag geht in die Anweisung.
    # Und schlaegt das Modell NUR eine Ausarbeitung vor (zweite Messung am 21.10.), die erkennbar
    # zu einem vorgemerkten Case gehoert ("das Gedaechtnis-Thema"), haengt sie an genau diesen Case:
    # der Auftrag gibt ihn frei (auftrag_setzen), und es entsteht kein zweiter Case daneben.
    vm_cases = db.alle("SELECT id, titel FROM vorgaenge WHERE stand='vorgemerkt'")
    if vm_cases:
        worte = {w.lower() for w in re.findall(r"\w{5,}", text)}
        for v in vorschlaege:
            if v["aktion"] != "ausarbeiten" or v.get("vorgang_id"):
                continue
            passt = [c for c in vm_cases if worte & {w.lower() for w in re.findall(r"\w{5,}", c["titel"] or "")}]
            if len(passt) == 1:
                v["vorgang_id"] = passt[0]["id"]
    fg = [v for v in vorschlaege if v["aktion"] == "vorgemerkt" and v.get("was") == "freigeben"]
    if fg:
        for v in [v for v in vorschlaege if v["aktion"] == "ausarbeiten" and (not v.get("vorgang_id") or v.get("vorgang_id") == fg[0].get("vorgang_id"))]:
            if not fg[0].get("anweisung"):
                fg[0]["anweisung"] = f"{stab.rollen_name(v.get('rolle') or 'stratege')}: {v.get('auftrag')}"
            vorschlaege.remove(v)
        sichtbar = re.sub(r"\n*Gestartet: [^\n]*", "", sichtbar)
    vm_befehl = bool(VORGEMERKT_BEFEHL.search(text)) and not _ABLEHNUNG.search(text)
    daily_befehl = bool(DAILY_BEFEHL.search(text)) and not _ABLEHNUNG.search(text)
    mail_befehl = bool(MAIL_BEFEHL.search(text)) and not _ABLEHNUNG.search(text)
    # Ein vom Modell vorgeschlagenes Abschicken gilt nur, wenn Veiko abschicken WILL. Bittet er um eine
    # Aenderung, wird daraus die Aenderung -- danach haengt das Cockpit das Abschicken selbst an.
    # Eine FRAGE nach dem Versand ("Hast du sie schon verschickt?") ist nie ein Auftrag zu senden.
    ist_frage = bool(re.search(r"\?\s*$", text) or re.match(r"\s*(hast|ist|wurde|sind|habt|wann|ob)\b", text, re.I)
                     or re.search(r"\bschon\b.{0,30}\b(verschickt|gesendet|abgeschickt|weggeschickt|raus)\b", text, re.I))
    will_senden = not ist_frage and bool(re.search(r"\b(abschick\w*|absend\w*|raus\b|verschick\w*|schick\w*\b.{0,30}\bab\b|send\w*)", text, re.I))
    mail_befehl = mail_befehl and not ist_frage    # "Hast du sie verschickt?" ist kein Auftrag an den Entwurf
    if ist_frage:
        # Was das Modell auf eine Frage hin an einem Entwurf aendern will, faellt weg (gemessen: ein leeres "aendern").
        vorschlaege = [v for v in vorschlaege if not (v["aktion"] == "mail" and v.get("was") == "aendern" and not v.get("erledigt"))]
    for v in vorschlaege:
        # Die Inhaltsangabe muss aus Veikos JETZIGEM Satz stammen (22.10.2026: "Schreib eine Mail an …"
        # bekam den Inhalt eines alten Entwurfs aus der Lage untergeschoben -- "Film-Ärger").
        if v["aktion"] == "mail" and v.get("anweisung") and not v.get("erledigt"):
            eigene = _woerter(text)
            if len(_woerter(str(v["anweisung"])) & eigene) < 2:
                v["anweisung"] = ""
        if v["aktion"] == "mail" and v.get("was") == "senden" and not will_senden and not v.get("erledigt"):
            if MAIL_BEFEHL.search(text) or re.search(r"kürzer|kuerzer|freundlicher|förmlicher|foermlicher|englisch|klarer|neu", text, re.I):
                v.update(was="aendern", anweisung=text)
                v["label"] = beschriften(v) or v["label"]
    if any(v["aktion"] == "mail" for v in vorschlaege):
        # Den Mailtext schreibt das Cockpit, nie das Modell in seine Antwort (siehe SYSTEM).
        sichtbar = re.sub(r"\n*(Entwurf (angelegt|geändert): )[\s\S]*$", "", sichtbar or "")
        sichtbar = re.sub(r"\n*(Hallo|Hi|Liebe|Lieber|Sehr geehrte\w*|Guten Tag)\b[^\n]*,\s*\n[\s\S]*?(Grüße|Gruß|Grüßen)\s*\n[^\n]*", "", sichtbar).strip()
    im_satz = zustimmung_im_satz(text)
    # Abschicken (22.10.2026) nur als Ja auf die Frage "Soll ich sie so abschicken?" -- also erst,
    # nachdem Veiko den Entwurf gesehen oder gehoert hat. Jeder andere Weg bleibt ein Vorschlag.
    abschicken_ok = bestaetigt and "abschicken" in str((vorher or {}).get("text") or "")
    # Steht der Entwurf offen vor Veiko und sagt er "kann jetzt verschickt werden", hat er ihn gesehen --
    # das ist die Zustimmung, auch wenn das Angebot ein paar Antworten zurueckliegt (22.10.2026: dazwischen
    # lag "oeffne die Suche", und das Abschicken blieb ein Vorschlag).
    offener_entwurf = db.holen("mails", (kontext or {}).get("id") or "") if (kontext or {}).get("art") == "mail" else None
    if offener_entwurf and offener_entwurf.get("stand") != "gesendet" and will_senden and not _ABLEHNUNG.search(text) \
            and not re.search(r"\b(noch nicht|nicht abschick|ändere|aendere|kürzer|kuerzer)\b", text, re.I):
        abschicken_ok = True
        if not [v for v in vorschlaege if v["aktion"] == "mail"]:
            a = {"aktion": "mail", "was": "senden", "mail_id": offener_entwurf["id"]}
            a["label"] = beschriften(a)
            if a["label"]:
                vorschlaege.append(a)
    gleich =[v for v in vorschlaege if v["aktion"] not in SOFORT_VERFAHREN
              and not (v["aktion"] == "mail" and v.get("was") == "senden" and not abschicken_ok)
              and (bestaetigt or (auftrag and v["aktion"] in ("ausarbeiten", "neo", "pruefen"))
                   or (befehl and v["aktion"] in BEFEHL_AKTIONEN)
                   or (vm_befehl and v["aktion"] == "vorgemerkt")
                   # Loeschen nie ohne Ja -- "aendern"/"pausieren" sind umkehrbar, ein geloeschter Task nur ueber den Verlauf.
                   or (daily_befehl and v["aktion"] == "daily" and v.get("was") != "loeschen")
                   or (mail_befehl and v["aktion"] == "mail")
                   # Auf dem offenen Entwurf ist jede Inhaltsangabe die Aenderung (22.10.2026: "Da soll drinstehen,
                   # dass …" blieb ein Vorschlag). Ein Entwurf zu aendern verschickt nichts.
                   or (am_entwurf and v["aktion"] == "mail" and v.get("was") != "senden")
                   or (v.get("zugestimmt") is True and im_satz))]
    ausgefuehrt = list(vorab)
    for v in gleich[:3]:
        try:
            r = await ausfuehren(v)
        except Exception as f:  # noqa: BLE001
            r = {"ok": False, "grund": str(f)}
        v["erledigt"] = bool(r.get("ok"))
        v["ergebnis"] = r
        ausgefuehrt.append({**r, "label": v.get("label")})
    if ausgefuehrt:
        # Das Cockpit sagt selbst, WAS lief -- je Aktion eine Zeile mit ihrem Etikett
        # (19.10.2026: "Ich schlage vor, dass Daniel … prüft" stand ueber "Ist beim Team",
        # gestartet war aber Neal. Der Satz des Modells darf nie das Einzige sein, was
        # Veiko ueber eine ausgefuehrte Aktion liest).
        zeilen = []
        for r in ausgefuehrt:
            was = r.get("label") or "Aktion"
            if not r.get("ok"):
                zeilen.append(f"Ging nicht: {was} ({r.get('grund')})")
            elif r.get("neo_gespraech"):
                zeilen.append(f"Gestartet: {was}. Neo arbeitet daran.")
            elif "ersetzt" in r:
                zeilen.append(f"Erledigt: {r['ersetzt']} Stellen ersetzt.")
            elif r.get("langlauf_id"):
                zeilen.append(f"Gestartet: {was}. Er steht jetzt unter LongRuns"
                              + (f", mit {r['material']} vorhandenen Ergebnissen und Unterlagen als Grundlage" if r.get("material") else "")
                              + " -- zuerst plant das Team die Etappen.")
            elif r.get("mail_gesendet"):
                zeilen.append(f"Gesendet: an {', '.join(r.get('an') or [])} -- „{r.get('betreff') or ''}“. Sie steht unter Mail → Gesendet.")
            elif r.get("mail_id"):
                zeilen.append(f"Entwurf {'geändert' if r.get('geaendert') else 'angelegt'}: an {r.get('an') or 'noch niemanden'} " + (f" -- Betreff „{r['betreff']}“" if r.get("betreff") else " -- noch ohne Betreff")
                              + (f"\n\n{r['text']}" if r.get("text") else "")
                              + ("\n\nDie Adresse fehlt noch -- sag sie mir oder trag sie im Entwurf ein." if r.get("adresse_fehlt")
                                 else "\n\nNoch steht kein Text drin. Was soll drinstehen?" if r.get("leer") else "\n\nSoll ich sie so abschicken?"))
            elif r.get("lief_schon"):
                zeilen.append(f"Läuft schon: {was}. Sein Urteil steht in wenigen Minuten am Ergebnis.")
            elif r.get("geprueft_wird"):
                zeilen.append(f"Gestartet: {was}. Sein Urteil steht in wenigen Minuten am Ergebnis -- frag mich dann „Was sagt Daniel?“.")
            elif r.get("vorgang_id"):
                zeilen.append(f"Gestartet: {was}. Das Ergebnis erscheint in der Inbox.")
            else:
                zeilen.append(f"Erledigt: {was}.")
        hinweis = "\n".join(zeilen)
        sichtbar = re.sub(r"\s*Soll ich das so machen\?\s*$", "", sichtbar).strip()
        if any(r.get("ok") and r.get("mail_id") for r in ausgefuehrt):
            # Die Frage zum Entwurf stellt das Cockpit ("Soll ich sie so abschicken?") -- eigene Fragen des
            # Modells daneben ("Soll ich den Entwurf anzeigen?") verwirren nur, und ein Satzschnitt am Punkt
            # einer Adresse ("von.eckern@web.") liess Bruchstuecke stehen. Die Zeile des Cockpits sagt alles.
            sichtbar = ""
        sichtbar = re.sub(r"[^.!?\n]*\b(ich schlage vor|schlage ich vor|mein vorschlag)\b[^.!?\n]*[.!?]?", "", sichtbar, flags=re.I).strip()
        # Wer was tut, sagt die Zeile des Cockpits -- Saetze des Modells darueber fallen weg
        # ("Ich beauftrage Neo …" ueber "Ersetzt: 8 Stellen", "Daniel prüft" ueber Neals Auftrag).
        sichtbar = TEAM_BEHAUPTET.sub("", sichtbar)
        if any(r.get("geprueft_wird") for r in ausgefuehrt):
            # Vor Daniels Urteil kann das Modell nichts Belastbares ueber das Ergebnis sagen
            # (gemessen: "Daniel hat das bereits geprueft … du musst nichts weiter tun" neben
            # "Gestartet: Daniel prueft"). Die Zeile des Cockpits steht allein.
            sichtbar = ""
        if not any(r.get("neo_gespraech") for r in ausgefuehrt):
            sichtbar = re.sub(r"[^.!?\n]*\bNeo\b[^.!?\n]*[.!?]?", "", sichtbar)
        sichtbar = AENDERUNG_BEHAUPTET.sub("", sichtbar)
        sichtbar = re.sub(r"[^.!?\n]*(erscheint in der Inbox|Ist beim Team|arbeitet daran)[^.!?\n]*[.!?]?", "", sichtbar).strip()
        # Reste nach dem Streichen ("Oktober 2026." -- ein Datum hatte den Satz am Punkt geteilt).
        sichtbar = "\n\n".join(p.strip() for p in re.split(r"\n\s*\n", sichtbar) if len(p.strip()) >= 30)
        sichtbar = (sichtbar + "\n\n" + hinweis).strip()
        # Ein frischer Mail-Entwurf bekommt das Abschicken gleich als offenen Vorschlag: ein "Ja"
        # schickt ihn ab -- aber erst NACHDEM Veiko den Text gesehen oder gehoert hat (22.10.2026).
        entwurf = next((r for r in ausgefuehrt if r.get("ok") and r.get("mail_id") and not r.get("mail_gesendet") and not r.get("adresse_fehlt") and not r.get("leer")), None)
        if entwurf and not any(v["aktion"] == "mail" and v.get("was") == "senden" and not v.get("erledigt") for v in vorschlaege):
            nachher = {"aktion": "mail", "was": "senden", "mail_id": entwurf["mail_id"]}
            nachher["label"] = beschriften(nachher)
            if nachher["label"]:
                vorschlaege.append(nachher)
        mail_offen = next((r["mail_id"] for r in ausgefuehrt if r.get("ok") and r.get("mail_id")), None)
        if mail_offen and not oeffnen:
            oeffnen = [{"art": "mail", "id": mail_offen, "titel": ""}]
    sofort = [v for v in vorschlaege if v["aktion"] in SOFORT_VERFAHREN][:1]
    vorschlaege = [v for v in vorschlaege if v["aktion"] not in SOFORT_VERFAHREN]
    if sofort:
        from . import verfahren
        v = sofort[0]
        ziel = "exo" if v["aktion"] == "exo" else "brainstrom"
        if not any(z.get("ziel") == ziel for z in zeigen):
            zeigen = [{"aktion": "zeigen", "ziel": ziel}]
        try:
            await ausfuehren(v)
            if ziel == "brainstrom":
                yield {"typ": "text", "t": "\n\n_BrainStrom denkt nach …_"}
                await verfahren.warten("brainstrom", 150)
                naechstes = verfahren.kurz_fuer_talk()
                if naechstes:
                    sichtbar = (sichtbar + "\n\n" + naechstes).strip()
            else:
                sichtbar = (sichtbar + "\n\nDie ExO-Analyse läuft, das dauert ein bis zwei Minuten. Das Ergebnis erscheint in der Ansicht.").strip()
        except (ValueError, llm.ModellFehler) as f:
            sichtbar = (sichtbar + f"\n\nDas ging nicht: {f}").strip()
    # Liegt noch ein Vorschlag offen da, darf der Text nicht so klingen, als sei er
    # erledigt ("Ich gebe das an Jason weiter" -- und nichts passierte). Dann endet
    # die Antwort mit der Frage, damit klar ist, dass ein Ja oder der Knopf fehlt.
    offen = [v for v in vorschlaege if not v.get("erledigt") and v["aktion"] not in ("zeigen",)]
    if offen and not sichtbar.rstrip().endswith("?"):
        sichtbar = re.sub(r"[^.!?\n]*\b(gebe das (an \w+ )?weiter|leg(e|t) (es|das|ihn) an|kümmert sich|macht sich|lasse \w+)\b[^.!?\n]*[.!?]?", "", sichtbar).strip()
        sichtbar = AENDERUNG_BEHAUPTET.sub("", sichtbar).strip()
        sichtbar = (sichtbar + "\n\nNoch nicht ausgeführt: " + "; ".join(v["label"] for v in offen) + ". Soll ich das so machen?").strip()
    if llm.fremdschrift(sichtbar):
        sichtbar = llm.FREMDSCHRIFT.sub("", sichtbar)
    # Recherche-Dossier auf Zuruf (dossier.py, 17.10.2026)
    from . import dossier
    _z = zuordnung(gid)
    d_ziel = {"projekt_id": _z.get("projekt_id") or ((kontext or {}).get("id") if (kontext or {}).get("art") == "projekt" else None) or (bez or {}).get("projekt_id"),
              "aufgabe_id": _z.get("aufgabe_id") or (bez or {}).get("aufgabe_id"), "gespraech_id": gid, "wer": "assistent"}
    hatte_block = bool(dossier.BLOCK_RE.search(sichtbar or ""))
    sichtbar, recherche = await dossier.aus_antwort(sichtbar, d_ziel)
    # Angekuendigt, aber nicht gestartet (19.10.2026): auf "Führe die Recherche noch einmal
    # durch" schrieb das Modell "Recherche gestartet: …" -- abgeschrieben von der Meldung des
    # Cockpits weiter oben im Verlauf --, ohne den Block. Gestartet war nichts, und Veiko
    # wartete auf ein Dossier. Jetzt: einmal gezielt nachfordern; kommt kein Block, wird
    # die Behauptung gestrichen und ehrlich gesagt, dass nichts laeuft.
    if not hatte_block and RECHERCHE_BEHAUPTET.search(sichtbar or ""):
        try:
            roh = await llm.chat(modell, system, verlauf + [{"role": "assistant", "content": gesamt}, {"role": "user", "content":
                "Du hast eine Recherche angekündigt, aber den Block nicht geschickt -- gestartet ist nichts. Antworte jetzt NUR mit "
                "<<<RECHERCHE>>>\ndas Thema und worauf es ankommt, in ein bis drei Sätzen\n<<<ENDE>>>\nohne weiteren Text."}],
                temperatur=0.1, denken=False, num_ctx=24576)
        except llm.ModellFehler:
            roh = ""
        if dossier.BLOCK_RE.search(roh or ""):
            _, recherche = await dossier.aus_antwort(roh, d_ziel)
        sichtbar = RECHERCHE_BEHAUPTET.sub("", sichtbar).strip()
        if not recherche:
            sichtbar = (sichtbar + "\n\nIch konnte die Recherche nicht starten -- gestartet ist nichts. Sag mir bitte noch einmal das Thema.").strip()
    if recherche:
        sichtbar = (sichtbar + "\n\n" + recherche[0]).strip()
    # Eine Mail gilt erst als gesendet, wenn das Cockpit sie gesendet hat (22.10.2026: gemessen
    # stand "Ich habe die E-Mail angepasst und abgeschickt" ueber einem neuen, ungesendeten Entwurf).
    # Gemessen am 22.10.: auf "Hast du das schon weggeschickt?" antwortete das Modell zweimal "ja, erfolgreich
    # versendet" -- nichts war raus. Ob eine Mail gesendet ist, sagt deshalb das Cockpit, nicht das Modell.
    um_mail = (any(v["aktion"] == "mail" for v in vorschlaege) or (kontext or {}).get("art") == "mail"
               or re.search(r"\b(e-?mail|mail)\b", text + " " + (sichtbar or ""), re.I))
    if um_mail and not any(r.get("mail_gesendet") for r in ausgefuehrt):
        behauptet = re.search(r"\b(abgeschickt|versendet|verschickt|gesendet|rausgeschickt|weggeschickt)\b", sichtbar or "", re.I)
        frage = re.search(r"\b(abgeschickt|versendet|verschickt|gesendet|rausgeschickt|weggeschickt|raus)\b", text, re.I) and (
            "?" in text or re.search(r"^\s*(hast|ist|wurde|sind|habt)\b|\bschon\b", text, re.I))
        if behauptet or frage:
            # Satzweise -- ein Punkt IN einer Adresse ("von.eckern@web.de") ist kein Satzende.
            saetze = re.split(r"(?<=[.!?])\s+", sichtbar or "")
            sichtbar = " ".join(s for s in saetze if not re.search(r"\b(abgeschickt|versendet|verschickt|gesendet|rausgeschickt|weggeschickt)\b", s, re.I)).strip()
            if frage:
                # Die Antwort auf "Ist sie raus?" gibt das Cockpit allein.
                sichtbar = ""
            from . import mail as _mail
            sichtbar = (sichtbar + "\n\n" + _mail.stand_satz((kontext or {}).get("id") if (kontext or {}).get("art") == "mail" else None)).strip()
    # "Aus unserem Gespräch noch offen:" ohne etwas dahinter (gemessen am 22.10.2026) faellt weg.
    sichtbar = re.sub(r"\n*[^\n]*noch offen:\s*$", "", sichtbar or "").strip()
    sichtbar += stab.netz_fuss(quellen)
    # Ein gerade gestarteter LongRun geht sofort auf (19.10.2026, Veiko: "wenn einer beauftragt
    # wird, soll er sofort bei LongRuns erscheinen, damit ich sehe, dass er wirklich ausgefuehrt wird").
    neu_ll = next((r for r in ausgefuehrt if r.get("ok") and r.get("langlauf_id")), None)
    if neu_ll and not oeffnen:
        oeffnen = [{"art": "langlauf", "id": neu_ll["langlauf_id"], "titel": neu_ll.get("titel") or ""}]
    if ueb_oeffnen and not oeffnen:
        oeffnen = [ueb_oeffnen]
    mid = db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                        (gid, "assistent", sichtbar, json.dumps({"vorschlaege": vorschlaege, "modell": modell, "medien": medien_jobs,
                                                                 "bezug": bez}, ensure_ascii=False), time.time()))
    db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), gid))
    yield {"typ": "fertig", "text": sichtbar, "vorschlaege": vorschlaege, "nachricht_id": mid, "modell": modell, "medien": medien_jobs, "bezug": bez,
           "zeigen": [z for z in (zeigen_ziel(v) for v in zeigen[:1]) if z],
           "oeffnen": oeffnen[:1], "werkzeug": werkzeug, "erledigt_in": erledigt_in}


def _kontext_einsetzen(vorschlaege: list[dict[str, Any]], kontext: dict[str, Any] | None) -> None:
    """Ein offenes Ergebnis ist die Grundlage einer Ausarbeitung (19.10.2026): "lass Neal
    daraus eine Praesentation machen" im Ergebnisfenster meint genau dieses Ergebnis --
    das Modell vergisst die Kennung oft, deshalb setzt das Cockpit sie selbst."""
    if kontext and kontext.get("art") == "projekt" and db.holen("projekte", kontext.get("id") or ""):
        for v in vorschlaege:
            if v["aktion"] == "ausarbeiten" and not v.get("projekt_id"):
                v["projekt_id"] = kontext["id"]
                v["label"] = beschriften(v) or v["label"]
    # Mail (22.10.2026): "schick das an Hanna" im Ergebnisfenster meint dieses Ergebnis, und auf der
    # Mail-Seite meint "mach sie kuerzer" den offenen Entwurf.
    for v in vorschlaege:
        if v["aktion"] != "mail" or not kontext or not kontext.get("id"):
            continue
        # Auf einem offenen Entwurf ist "formulier sie neu" eine Aenderung DIESES Entwurfs -- gemessen
        # legte das Modell sonst einen zweiten an.
        offen_m = db.holen("mails", kontext["id"]) if kontext.get("art") == "mail" else None
        if v.get("was") == "entwurf" and offen_m and offen_m.get("stand") != "gesendet":
            v.update(was="aendern", mail_id=offen_m["id"])
            if not v.get("stil") and not v.get("anweisung"):
                v["anweisung"] = "neu formulieren"
            v["label"] = beschriften(v) or v["label"]
            continue
        if v.get("was") == "entwurf" and kontext.get("art") in ("ergebnis", "aufgabe", "notiz", "datei", "projekt") and not v.get("bezug_id"):
            v.update(bezug_art=kontext["art"], bezug_id=kontext["id"])
            v["label"] = beschriften(v) or v["label"]
        elif v.get("was") in ("aendern", "senden") and kontext.get("art") == "mail" and db.holen("mails", kontext["id"]):
            v["mail_id"] = kontext["id"]
            v["label"] = beschriften(v) or v["label"]
    if not kontext or kontext.get("art") != "ergebnis":
        return
    e = db.holen("ergebnisse", kontext.get("id") or "")
    if not e:
        return
    for v in vorschlaege:
        if v["aktion"] == "pruefen" and not db.holen("ergebnisse", str(v.get("ergebnis_id") or "")):
            v["ergebnis_id"] = e["id"]
            v["label"] = beschriften(v) or v["label"]
        if v["aktion"] == "ausarbeiten":
            v.setdefault("ergebnis_id", e["id"])
            if not v.get("projekt_id") and e.get("projekt_id"):
                v["projekt_id"] = e["projekt_id"]
                v["label"] = beschriften(v) or v["label"]


# Was das Cockpit selbst an eine Antwort haengt. Im Verlauf fuers Modell steht statt dessen,
# was WIRKLICH passiert ist (19.10.2026): das Modell schrieb "Noch nicht ausgeführt: …" ab,
# ohne Block -- es sah aus wie ein Vorschlag, und nichts war da. Und es wusste nicht, dass
# ein Vorschlag inzwischen per Knopf ausgefuehrt war, weil der Text das nicht sagte.
_COCKPIT_ANHANG = re.compile(r"^(Noch nicht ausgeführt: .*|Ist beim Team, das Ergebnis erscheint in der Inbox\.|Neo arbeitet daran\.|"
                             r"Ersetzt: \d+ Stellen\.|Erledigt\.|Nicht alles ging: .*|Geändert ist noch nichts.*|"
                             r"Gestartet: .*|Erledigt: .*|Ging nicht: .*|"
                             r"Ich konnte (den Auftrag|deinem Ja|die Recherche).*)$", re.M)


def _fuers_modell(text: str, daten: dict[str, Any]) -> str:
    """Eine fruehere Antwort, wie das Modell sie im Verlauf sieht: ohne alles, was das
    Cockpit selbst angehaengt hat. Was wirklich ausgefuehrt wurde, steht NICHT hier, sondern
    in stand_text() in der Anweisung -- ein Vermerk im Verlauf wurde am 19.10.2026 woertlich
    abgeschrieben ("[Vermerk des Cockpits: AUSGEFÜHRT: …]" stand in Veikos Antwort)."""
    t = _COCKPIT_ZEILE.sub("", text or "")
    # Die Entwurfsanzeige des Cockpits samt Mailtext (22.10.2026): gemessen ahmte das Modell sie nach
    # und schrieb einen Text hin, der nie im Entwurf stand -- und ein Ja haette den ALTEN verschickt.
    t = re.sub(r"\n*(Entwurf (angelegt|geändert): |Gesendet: an )[\s\S]*$", "", t)
    return _COCKPIT_ANHANG.sub("", VERMERK_RE.sub("", t)).strip() or "(siehe WAS IN DIESEM GESPRÄCH SCHON PASSIERT IST)"


VERMERK_RE = re.compile(r"\s*\[Vermerk des Cockpits[^\]]*\]?", re.I)


ERLEDIGT_FRAGE = re.compile(r"\bwas (hast du|habt ihr|wurde|ist)\b.{0,40}\b(erledigt|gemacht|ausgeführt|ausgefuehrt|gestartet|getan|angelegt|geändert|geaendert)\b", re.I)


def erledigt_satz(gid: str) -> str:
    """Die Antwort auf "Was hast du erledigt?" -- aus den gespeicherten Vorschlaegen."""
    getan, offen = [], []
    for m in db.alle("SELECT daten FROM nachrichten WHERE gespraech_id=? AND rolle='assistent' ORDER BY id", (gid,)):
        for v in (m.get("daten") or {}).get("vorschlaege") or []:
            if v.get("erledigt") and not v.get("abgelehnt"):
                getan.append(v.get("label"))
            elif not v.get("erledigt") and not v.get("abgelehnt") and not v.get("ergebnis"):
                offen.append(v.get("label"))
    getan = list(dict.fromkeys(getan))
    offen = [x for x in dict.fromkeys(offen) if x not in getan]
    if not getan and not offen:
        return "In diesem Gespräch habe ich noch nichts ausgeführt -- wir haben nur gesprochen."
    teile = []
    if getan:
        teile.append("In diesem Gespräch ausgeführt:\n" + "\n".join(f"- {x}" for x in getan[-10:]))
    if offen:
        teile.append("Vorgeschlagen, wartet noch auf dein Ja:\n" + "\n".join(f"- {x}" for x in offen[-5:]))
    return "\n\n".join(teile)


def stand_text(gid: str) -> str:
    """Was in diesem Gespraech wirklich passiert ist -- fuer die Anweisung, nicht den Verlauf."""
    zeilen = []
    for m in db.alle("SELECT text, daten FROM nachrichten WHERE gespraech_id=? AND rolle='assistent' ORDER BY id DESC LIMIT 12", (gid,)):
        for z in _COCKPIT_ZEILE.findall(m.get("text") or ""):
            zeilen.append(z[:160])
        for v in (m.get("daten") or {}).get("vorschlaege") or []:
            if v.get("abgelehnt"):
                zeilen.append(f"von Veiko abgelehnt: {v.get('label')}")
            elif v.get("erledigt"):
                zeilen.append(f"AUSGEFÜHRT (läuft oder ist fertig, NICHT noch einmal vorschlagen): {v.get('label')}")
            elif v.get("ergebnis") and not (v["ergebnis"] or {}).get("ok"):
                zeilen.append(f"fehlgeschlagen: {v.get('label')} ({(v['ergebnis'] or {}).get('grund')})")
            else:
                zeilen.append(f"vorgeschlagen, wartet auf Veikos Ja: {v.get('label')}")
    if not zeilen:
        return ""
    return ("WAS IN DIESEM GESPRÄCH SCHON PASSIERT IST (vom Cockpit festgehalten, jüngstes zuerst; schreib das nie ab, "
            "sag es in eigenen Worten, wenn Veiko fragt):\n" + "\n".join("- " + z for z in zeilen[:12]))


def zeigen_ziel(v: dict[str, Any]) -> dict[str, Any] | None:
    """Was der Browser oeffnet: Projekt-Reiter, Chat mit einem Mitglied oder eine Adresse (BEREICH_PFAD)."""
    ziel = str(v.get("ziel") or "")
    if v.get("projekt_id") and ziel in ZIELE:
        return {"ziel": ziel, "projekt_id": v["projekt_id"], "frage": None}
    if ziel == "chat":
        m = _mitglied_im_text(str(v.get("wer") or ""))
        if not m:
            return None
        ziel = "neo" if m["name"].lower() == "neo" else f"team/chat/{m['id']}"
    elif ziel in ZIELE:   # ein Projekt-Reiter ohne Projekt: die Liste ueber alle Projekte
        ziel = {"aufgaben": "alle_aufgaben", "notizen": "alle_notizen"}.get(ziel, "projects")
    return {"ziel": BEREICH_PFAD.get(ziel, ziel), "projekt_id": None, "frage": str(v.get("frage") or "")[:2000] or None}


async def vorschlaege_ausfuehren(nachricht_id: int, indizes: list[int]) -> list[dict[str, Any]]:
    m = db.eine("SELECT * FROM nachrichten WHERE id=?", (nachricht_id,))
    if not m:
        return [{"ok": False, "grund": "Nachricht nicht gefunden"}]
    daten = m.get("daten") or {}
    vs = daten.get("vorschlaege") or []
    ergebnisse = []
    for i in indizes:
        if i < 0 or i >= len(vs) or vs[i].get("erledigt"):
            continue
        try:
            r = await ausfuehren(vs[i])
        except Exception as f:  # noqa: BLE001
            r = {"ok": False, "grund": str(f)}
        vs[i]["erledigt"] = bool(r.get("ok"))
        vs[i]["ergebnis"] = r
        ergebnisse.append({**r, "label": vs[i].get("label")})
    daten["vorschlaege"] = vs
    db.ausfuehren("UPDATE nachrichten SET daten=? WHERE id=?", (json.dumps(daten, ensure_ascii=False), nachricht_id))
    return ergebnisse


# ---------------------------------------------------------------- Zuordnung
# Jedes Gespraech (Talk, Team-Chat, Neo, Board) kann einem Projekt und einer
# Aufgabe zugeordnet werden (Veiko, 17.10.2026: "einzelne Chats Projekten und
# Aufgaben zuordnen, damit mein Setup gut funktioniert"). Gespeichert wird im
# vorhandenen Feld gespraeche.kontext -- dieselbe Stelle, an der Team-Chat und
# Board ihr Projekt schon immer trugen; keine neue Tabelle, keine zweite Wahrheit.
# Wirkung: das Modell bekommt Projekt und Aufgabe als Bezug in jeder Antwort,
# und die Projektseite zeigt das Gespraech.
def zuordnung(gid: str | None) -> dict[str, Any]:
    g = db.holen("gespraeche", gid) if gid else None
    k = (g or {}).get("kontext") or {}
    return {"projekt_id": k.get("projekt_id"), "aufgabe_id": k.get("aufgabe_id")} if isinstance(k, dict) else {}


def zuordnen(gid: str, projekt_id: str | None, aufgabe_id: str | None) -> dict[str, Any]:
    g = db.holen("gespraeche", gid)
    if not g:
        raise ValueError("Gespräch nicht gefunden.")
    if aufgabe_id:
        a = db.holen("aufgaben", aufgabe_id)
        if not a:
            raise ValueError("Aufgabe nicht gefunden.")
        projekt_id = projekt_id or a.get("projekt_id")
    if projekt_id and not db.holen("projekte", projekt_id):
        raise ValueError("Projekt nicht gefunden.")
    k = g.get("kontext") if isinstance(g.get("kontext"), dict) else {}
    k = {**k, "projekt_id": projekt_id or None, "aufgabe_id": aufgabe_id or None}
    db.ausfuehren("UPDATE gespraeche SET kontext=? WHERE id=?", (json.dumps(k, ensure_ascii=False), gid))
    return beschriftung(k)


def beschriftung(k: dict[str, Any]) -> dict[str, Any]:
    p = db.holen("projekte", k["projekt_id"]) if k.get("projekt_id") else None
    a = db.holen("aufgaben", k["aufgabe_id"]) if k.get("aufgabe_id") else None
    return {"projekt_id": k.get("projekt_id"), "aufgabe_id": k.get("aufgabe_id"),
            "projekt_name": (p or {}).get("name"), "aufgabe_titel": (a or {}).get("titel")}


def aufgabe_text(aufgabe_id: str | None) -> str:
    a = db.holen("aufgaben", aufgabe_id) if aufgabe_id else None
    if not a:
        return ""
    teile = [f"DIESES GESPRÄCH GEHÖRT ZUR AUFGABE: {a['titel']} (Stand: {a.get('status')}"
             + (f", fällig {a['faellig']}" if a.get("faellig") else "") + ")"]
    if (a.get("notiz") or "").strip():
        teile.append("Informationen zur Aufgabe: " + a["notiz"].strip()[:6000])
    # Anhaenge der Aufgabe (Aufgabenfenster, 17.10.2026): wer ueber die Aufgabe
    # spricht, soll auch die Unterlagen kennen, die Veiko dort abgelegt hat.
    platz = 24000
    # Ergebnisse fuer diese Aufgabe zuerst (19.10.2026): ein Recherche-Dossier ist die
    # verdichtete Fassung der langen Abschriften daneben -- es gehoert vor sie.
    for r in db.alle("SELECT r.titel, r.inhalt FROM ergebnisse r JOIN vorgaenge v ON v.id=r.vorgang_id "
                     "WHERE json_extract(v.auftrag,'$.aufgabe_id')=? ORDER BY r.erstellt DESC LIMIT 3", (aufgabe_id,)):
        t = (r.get("inhalt") or "").strip()
        if platz > 0 and t:
            teile.append(f"ERGEBNIS ZUR AUFGABE „{r['titel']}“:\n" + t[:min(platz, 12000)])
            platz -= min(len(t), 12000)
    for f in db.alle("SELECT name, text FROM dateien WHERE aufgabe_id=? ORDER BY erstellt", (aufgabe_id,)):
        t = (f.get("text") or "").strip()
        if platz <= 0:
            teile.append(f"(Weitere Unterlage „{f['name']}“ -- aus Platzgründen nicht mitgeschickt.)")
            continue
        teile.append(f"UNTERLAGE ZUR AUFGABE „{f['name']}“:\n" + (t[:min(platz, 12000)] if t else "(Inhalt nicht lesbar.)"))
        platz -= min(len(t), 12000)
    teile.append("Richte deine Antworten auf diese Aufgabe aus, solange Veiko nichts anderes sagt.")
    return "\n".join(teile)


# ---------------------------------------------------------------- Bezug erkennen
# Veiko, 19.10.2026: "ich hatte ueber Talk einen Auftrag erteilt, ich finde die
# Ergebnisse nicht, der Chat ist einer dazu passenden, bereits existierenden
# Aufgabe nicht zugeordnet worden ... mein zentraler Punkt fuer die Arbeit sind
# die Projekte mit ihren Aufgaben." Anlass: „stoß eine Recherche an, wie ich an
# Verlage herantreten kann“ -- im BUCH PROJECT steht die Aufgabe „Verlag finden“,
# das Dossier landete trotzdem ohne Projekt unter „Anhänge“.
# Talk ist EIN langes Gespraech ueber vieles; die Zuordnung des ganzen Gespraechs
# (zuordnen) passt dafuer nicht. Erkannt wird deshalb je Nachricht, ohne Modell
# (kein Zeitverlust) und nur bei einem klaren Treffer -- lieber kein Bezug als ein
# falscher. Was aus der Nachricht entsteht (Dossier, Ausarbeitung, Aufgabe, Notiz),
# geht dorthin, und Talk zeigt den Bezug unter der Antwort.
_BEZUG_LEER = {"recherch", "such", "find", "mach", "erstell", "schreib", "anstoß", "stoß", "kann", "komm", "frag", "best",
               "heut", "morg", "doch", "also", "etwas", "alles", "welch", "dies", "dass", "oder", "aber", "schon", "auch",
               "mehr", "sehr", "wird", "werd", "sind", "habe", "hast", "will", "soll", "muss", "könnt", "könn", "mein",
               "mich", "dein", "sein", "nach", "lass", "bitt", "kurz", "klär", "klaer", "hol", "info", "informatio",
               "thema", "sach", "plan", "aufgab", "projekt", "erledig", "gerad", "einfach", "eigentlich", "vielleicht",
               # Formen und Allerweltswoerter: "erstelle eine Präsentation" meint nicht jede Aufgabe mit "Präsentation".
               "präsentatio", "praesentatio", "dokument", "video", "webseit", "website", "konzept", "text", "bild", "list",
               "entwurf", "inhalt", "erarbeit", "ausarbeit", "vorschlag", "idee", "frag", "termin", "neues", "worauf"}


def _bezug_woerter(t: str) -> set[str]:
    return {w for w in _woerter(t) if w not in _BEZUG_LEER and len(w) >= 4}


def bezug_erkennen(text: str, gid: str | None, kontext: dict | None) -> dict[str, Any] | None:
    """Zu welcher offenen Aufgabe (und welchem Projekt) Veikos Nachricht gehoert.
    {projekt_id, aufgabe_id, projekt_name, aufgabe_titel, erkannt: True} oder None."""
    k = kontext or {}
    # Aus dem Aufgabenfenster heraus ("Im Gespräch besprechen"): der Bezug ist die Aufgabe selbst.
    if k.get("art") == "aufgabe":
        a = db.holen("aufgaben", k.get("id") or "")
        if a:
            p = db.holen("projekte", a.get("projekt_id") or "") if a.get("projekt_id") else None
            return {"projekt_id": a.get("projekt_id"), "aufgabe_id": a["id"], "projekt_name": (p or {}).get("name"),
                    "aufgabe_titel": a["titel"], "erkannt": True}
    im_projekt = k.get("id") if k.get("art") == "projekt" else None
    gesucht = _bezug_woerter(text)
    projekte = db.alle("SELECT id, name FROM projekte WHERE status NOT IN ('archiviert','abgeschlossen')")
    im_satz = {p["id"] for p in projekte if _bezug_woerter(p["name"]) and _bezug_woerter(p["name"]) <= gesucht}
    treffer: list[tuple[float, dict[str, Any]]] = []
    if gesucht and not ist_ja(text):
        sql = ("SELECT a.id, a.titel, a.projekt_id, p.name FROM aufgaben a LEFT JOIN projekte p ON p.id=a.projekt_id "
               "WHERE a.status!='erledigt' AND a.archiviert=0" + (" AND a.projekt_id=?" if im_projekt else ""))
        for a in db.alle(sql, (im_projekt,) if im_projekt else ()):
            w = _bezug_woerter(a["titel"])
            if not w:
                continue
            gemein = gesucht & w
            # Klar heisst: zwei gemeinsame Woerter, oder der ganze (kurze) Aufgabentitel,
            # oder ein langes, eigenes Wort ("Verlage" ~ "Verlag finden").
            if len(gemein) >= 2 or (gemein and (gemein == w or max(len(x) for x in gemein) >= 6)):
                # Laengere Woerter sind spezifischer: "Verlag" vor "Buch" (19.10.2026: "Recherche zum Thema
                # Verlag fuer das Buch" traf "Verlag finden" und "Buch schreiben" gleich stark -- kein Bezug).
                treffer.append((len(gemein) + len(gemein) / len(w) + sum(len(x) for x in gemein) / 20
                                + (1 if a["projekt_id"] in im_satz else 0), a))
    treffer.sort(key=lambda x: -x[0])
    if treffer and (len(treffer) == 1 or treffer[0][0] > treffer[1][0]):
        a = treffer[0][1]
        return {"projekt_id": a["projekt_id"], "aufgabe_id": a["id"], "projekt_name": a.get("name"),
                "aufgabe_titel": a["titel"], "erkannt": True}
    # Gleichstand zwischen Aufgaben DESSELBEN Projekts: dann wenigstens das Projekt.
    if treffer and not im_projekt and len({x[1]["projekt_id"] for x in treffer if x[0] == treffer[0][0]}) == 1 and treffer[0][1]["projekt_id"]:
        a = treffer[0][1]
        return {"projekt_id": a["projekt_id"], "aufgabe_id": None, "projekt_name": a.get("name"), "aufgabe_titel": None, "erkannt": True}
    if im_projekt:
        return None   # das Projekt steht ohnehin im Kontext
    # Kein eindeutiger Treffer: eine kurze Folgenachricht ("ja", "und die Kosten?")
    # gehoert zum Bezug der vorigen, wenn die hoechstens 15 Minuten alt ist.
    if gid and len((text or "").split()) <= 12:
        vor = db.eine("SELECT daten, zeit FROM nachrichten WHERE gespraech_id=? AND rolle='assistent' ORDER BY id DESC LIMIT 1", (gid,))
        b = ((vor or {}).get("daten") or {}).get("bezug") if vor else None
        if b and time.time() - (vor.get("zeit") or 0) < 900 and db.holen("projekte", b.get("projekt_id") or ""):
            return b
    # Nur ein Projekt im Satz ("im Buchprojekt …"): dann gehoert es dorthin.
    if len(im_satz) == 1:
        p = next(x for x in projekte if x["id"] in im_satz)
        return {"projekt_id": p["id"], "aufgabe_id": None, "projekt_name": p["name"], "aufgabe_titel": None, "erkannt": True}
    return None


def _bezug_einsetzen(vorschlaege: list[dict[str, Any]], b: dict[str, Any] | None) -> None:
    """Was aus einer Nachricht mit erkanntem Bezug entsteht, bekommt Projekt (und bei
    einer Ausarbeitung die Aufgabe) -- auch wenn das Modell die Kennung vergisst."""
    if not b:
        return
    for v in vorschlaege:
        if v["aktion"] in ("aufgabe_neu", "notiz", "ausarbeiten", "langlauf") and not v.get("projekt_id") and b.get("projekt_id"):
            v["projekt_id"] = b["projekt_id"]
            v["label"] = beschriften(v) or v["label"]
        if v["aktion"] in ("ausarbeiten", "langlauf") and not v.get("aufgabe_id") and b.get("aufgabe_id"):
            v["aufgabe_id"] = b["aufgabe_id"]


def bezug_text(b: dict[str, Any]) -> str:
    if b.get("aufgabe_id"):
        info = (aufgabe_text(b["aufgabe_id"]).replace("DIESES GESPRÄCH GEHÖRT ZUR AUFGABE", "AUFGABE")
                .replace("Richte deine Antworten auf diese Aufgabe aus, solange Veiko nichts anderes sagt.", ""))
        return (f"BEZUG (vom Cockpit erkannt): Veikos Nachricht gehört zur bestehenden Aufgabe „{b['aufgabe_titel']}“ "
                f"(aufgabe_id {b['aufgabe_id']}) im Projekt „{b.get('projekt_name') or 'ohne Projekt'}“ (projekt_id {b.get('projekt_id')}). "
                "Alles, was daraus entsteht -- Recherche, Ausarbeitung, neue Aufgaben, Notizen -- gehört dorthin: setze diese projekt_id "
                "(und bei ausarbeiten die aufgabe_id) in den aktionen-Block. Lege KEINE zweite Aufgabe mit demselben Inhalt an. "
                f"Nenne den Bezug in einem kurzen Halbsatz („für deine Aufgabe „{b['aufgabe_titel']}““).\n" + info).strip()
    return (f"BEZUG (vom Cockpit erkannt): Veikos Nachricht gehört zum Projekt „{b.get('projekt_name')}“ (projekt_id {b.get('projekt_id')}). "
            "Was daraus entsteht, gehört in dieses Projekt.")


def zuordnung_text(gid: str | None, schon_projekt: str | None = None) -> str:
    """Bezug fuer das Modell. schon_projekt: das Projekt, das ohnehin im Kontext
    steht -- dann nicht ein zweites Mal anhaengen."""
    z = zuordnung(gid)
    teile = []
    if z.get("projekt_id") and z["projekt_id"] != schon_projekt:
        teile.append(kontext_text({"art": "projekt", "id": z["projekt_id"]}).replace(
            "VEIKO SCHAUT GERADE AUF DAS PROJEKT", "DIESES GESPRÄCH GEHÖRT ZUM PROJEKT"))
    if z.get("aufgabe_id"):
        teile.append(aufgabe_text(z["aufgabe_id"]))
    return "\n\n".join(t for t in teile if t)
