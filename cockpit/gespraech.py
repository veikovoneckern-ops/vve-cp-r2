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

import json
import re
import time
from typing import Any, AsyncIterator

from . import db, llm, stab
from .konfig import MODELL_TALK

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
    # BrainStrom und ExO (verfahren.py) -- Veiko, 01.10.: "wenn ich mit dem Cockpit
    # spreche, muss das auch fuer diese Elemente funktionieren".
    "brainstrom": ("thema",),
    "brainstrom_antwort": ("text",),
    "brainstrom_weg": ("nummer",),
    "brainstrom_genug": (),
    "brainstrom_uebernehmen": (),
    "exo": (),
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
    return len(t.split()) <= 10 and bool(_JA.search(t)) and not _NEIN.search(t)

SYSTEM = """Du bist das VvE Cockpit: die Stimme von Veikos persönlichem KI-Team. Veiko von Eckern ist Head of Corporate HR Transformation bei Krones. Sein Team: Jason (Head of PMO, ordnet ein), Neo (Cockpit Engineer), Clayton (Strategie), Neal (Texte, Bücher), Daniel (Red Team, prüft), Annie (Gestaltung), Ridley (Video).

So antwortest du:
- Deutsch, direkt, freundlich, ohne Vorrede. Zuerst die Antwort, dann wenn nötig die Begründung.
- Erfinde nichts. Du kennst nur, was unten in LAGE und KONTEXT steht. Wenn etwas fehlt, sag es.
- Nenne, wer gearbeitet hat, aber nur, wenn es in LAGE oder KONTEXT steht. Schreib niemandem eine Arbeit zu, die dort nicht vorkommt.
- Nenne im Text NIE interne Kennungen (e…, t…, p…, v…). Die gehören nur in den aktionen-Block. Im Text sagst du den Titel.
- Auf "Was liegt an?" antwortest du knapp: höchstens fünf Punkte, in DIESER Reihenfolge -- wie das Briefing, das Veiko daneben sieht: 1. OFFENE ENTSCHEIDUNGEN (stehen dort „keine“, sag genau das), 2. NEU ENTSTANDEN (zuletzt bearbeitete zuerst, mit Daniels Urteil in einfachen Worten), 3. WAS GERADE LÄUFT (steht dort „nichts“, sag genau das), 4. OFFENE AUFGABEN (die ersten drei, in der Reihenfolge der Liste). Nur, was in LAGE steht. Einen eigenen, noch nicht ausgeführten Vorschlag aus diesem Gespräch nennst du getrennt am Ende („Aus unserem Gespräch noch offen: …“) -- er ist keine Entscheidung des Teams. Keine vollständigen Listen.
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
- {"aktion":"zeigen","ziel":"board|briefing|inbox|projects|team|neo|system|watchdog|website_stand|brainstrom|exo|langlauf|aktionen|modelle|einstellungen|memory|usage|explorer|empfehlungen|uebersicht_modelle|installiert|optimierung|neue_modelle|alle_aufgaben|alle_notizen|neuer_langlaeufer"} -- öffnet einen Bereich oder Abschnitt des Cockpits sofort (system = Stack: Server, Updates, WatchDog, ganz unten website_stand = Stand der Website; langlauf = LongRuns; usage = Verbrauch an Token, Kosten und Strom nach Projekt, Aufgabe, Modell; explorer = alle erzeugten Inhalte zum Suchen und Filtern; memory = was das Team über Veiko weiß, unter Settings; empfehlungen = Recommendations, alle Empfehlungen zu Server, Software, Modellen und Website; optimierung = Modell-Revision, neue_modelle = Neu bei Ollama).
- {"aktion":"zeigen","ziel":"chat","wer":"Name des Teammitglieds"} -- öffnet den Chat mit diesem Mitglied (Neo: ziel neo).
- {"aktion":"werkzeug","was":"erfassen|suche|hell|dunkel|zurueck|fenster_zu"} -- Capture öffnen, Suche öffnen, helle oder dunkle Darstellung, eine Seite zurück, oberstes Fenster schließen. Sofort, ohne Rückfrage. Will Veiko „mit dem Advisory Board sprechen“: ziel board. Stellt er dabei schon eine Frage ans Board, gib sie als "frage" mit -- das Board antwortet dann selbst, du antwortest nicht an seiner Stelle.
- {"aktion":"ausarbeiten","rolle":"stratege|buch|designer|video","form":"text|aufstellung|konzept|dokument|webseite|praesentation|video","auftrag":"…","recherche":"Suchanfrage oder null","vorgang_id":"v… oder null","projekt_id":"p… oder null","aufgabe_id":"t… oder null (die Aufgabe, zu der das gehört)","stil":"vveorg|cockpit|eigen oder null","stil_text":"…"} -- stil nur bei einer Präsentation und nur, wenn Veiko das Aussehen nennt: „im VVEORG-Look“/„in meiner Vorlage“ = vveorg, „im Cockpit-Design“ = cockpit, eigene Gestaltungswünsche (Farben, Schrift, Footer) = eigen mit stil_text in seinen Worten. Sonst weglassen (dann gilt die Vorgabe, die VVEORG-Vorlage).
- {"aktion":"merken","art":"person|organisation|begriff|hoerfehler|aussprache","begriff":"…","bedeutung":"…"} -- aussprache: wie das Cockpit ein (meist englisches) Wort VORLESEN soll, in deutscher Lautschrift, z. B. begriff "Slides", bedeutung "Slaids".
- {"aktion":"notiz","text":"…","projekt_id":"p… oder null"}
- {"aktion":"projekt_neu","name":"…"}
- {"aktion":"neo","auftrag":"was Neo am Cockpit oder Server tun soll"}
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

STIMME_ZUSATZ = ("- Die Antwort wird VORGELESEN: höchstens vier kurze Sätze, keine Tabellen, keine Aufzählungszeichen, keine Markdown-Zeichen.\n"
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
    neu = stab.neu_entstanden()
    if neu:
        teile.append("NEU ENTSTANDEN (letzte sieben Tage, zuletzt bearbeitete zuerst -- so steht es auch im Briefing):\n" + "\n".join(
            f"- {e['id']}: {e['titel'][:90]} (von {e['wer_name']}, bearbeitet {_zeit(e['bearbeitet'])}"
            + (f", Projekt {e['projekt_name']}" if e.get("projekt_name") else "") + f"): {e['urteil_text']}" for e in neu))
    # Dieselbe Auswahl wie "Läuft gerade" im Briefing. Ist sie leer, steht das da --
    # ohne den Satz nannte Talk am 16.10. Erledigtes als "läuft gerade".
    lauf = [v for v in db.alle("SELECT id, titel, auftrag, stand FROM vorgaenge WHERE stand IN ('neu','in_arbeit','wartet') "
                               "AND quelle!='alt' ORDER BY geaendert DESC LIMIT 30")
            if v["stand"] != "wartet" or stab.auftrag_offen(v)][:6]
    teile.append("WAS GERADE LÄUFT:\n" + ("\n".join(f"- {v['id']}: {v['titel']}" for v in lauf) if lauf
                                         else "nichts -- das Team arbeitet gerade an keinem Case"))
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
        erg = db.alle("SELECT id, titel, form FROM ergebnisse WHERE projekt_id=? ORDER BY erstellt DESC LIMIT 8", (kid,))
        notiz = db.alle("SELECT titel, kurz, text FROM notizen WHERE projekt_id=? ORDER BY erstellt DESC LIMIT 5", (kid,))
        return (f"VEIKO SCHAUT GERADE AUF DAS PROJEKT {kid}: {p['name']}" + (f" -- Ziel: {p['ziel']}" if p.get("ziel") else "") +
                "\nAufgaben:\n" + "\n".join(f"- {a['id']} [{a['status']}] {a['titel']}" for a in auf) +
                ("\nErgebnisse:\n" + "\n".join(f"- {e['titel']} ({e['form']})" for e in erg) if erg else "") +
                ("\nJüngste Notizen:\n" + "\n".join(f"- {(n['kurz'] or n['text'] or '')[:200]}" for n in notiz) if notiz else ""))
    if art == "ergebnis":
        e = db.holen("ergebnisse", kid)
        if e:
            return f"VEIKO LIEST GERADE DAS ERGEBNIS „{e['titel']}“ von {stab.rollen_name(e['rolle'])}:\n{(e['inhalt'] or '')[:8000]}"
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
            "MEMORY:\n" + stab.gedaechtnis_text())


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
            "usage": "Usage", "explorer": "Explorer", "memory": "Memory", "empfehlungen": "Recommendations", "website_stand": "Stack: Website",
            # Reiter und Listen (18.10.2026): erreichbar wie die Bereiche.
            "uebersicht_modelle": "Team: Besetzung und Empfehlungen", "installiert": "Installierte Modelle", "optimierung": "Optimierung",
            "neue_modelle": "Neu bei Ollama", "verbrauch": "Usage", "alle_aufgaben": "Alle Aufgaben",
            "alle_notizen": "Alle Notizen", "neuer_langlaeufer": "Neuer LongRun"}
# Wohin ein Ziel im Browser fuehrt (Adresse hinter #/). Fehlt es hier, ist das Ziel selbst die Adresse.
BEREICH_PFAD = {"watchdog": "system/watchdog", "stack": "system", "website_stand": "system/website", "modelle": "team/besetzung",
                "uebersicht_modelle": "team/besetzung", "installiert": "team/installiert",
                "optimierung": "team/optimierung", "neue_modelle": "team/neu", "verbrauch": "usage", "memory": "einstellungen/memory",
                "alle_aufgaben": "projects/_aufgaben", "alle_notizen": "projects/_notizen", "neuer_langlaeufer": "langlauf/neu"}
WERKZEUGE = {"erfassen": "Capture", "suche": "Suche", "hell": "Helle Darstellung", "dunkel": "Dunkle Darstellung",
             "zurueck": "Eine Seite zurück", "fenster_zu": "Fenster schließen"}

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
    ("website_stand", r"(stand|zustand|überblick|ueberblick) (meiner|der) (website|webseite)", "den Stand deiner Website"),
    ("neuer_langlaeufer", r"neue[nrs]? (langl(ä|ae)ufer|long ?run)", "einen neuen LongRun"),
    ("langlauf", r"langl(ä|ae)ufer|long ?runs?", "die LongRuns"),
    ("alle_aufgaben", r"(alle|meine) aufgaben|aufgabenliste", "alle Aufgaben"),
    ("alle_notizen", r"(alle|meine) notizen|notizliste", "alle Notizen"),
    ("aktionen", r"current actions|aktionen|was (gerade )?läuft", "Current Actions"),
    ("webspace", r"web ?space|meine (website|webseite|homepage)|veikovoneckern", "den WebSpace"),
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
    artikel = "den " if o["art"] in ("langlauf", "vorgang") else "die " if o["art"] in ("aufgabe", "notiz", "datei") else "das "
    return f"Ich öffne dir {artikel}{OEFFNEN_NAME[o['art']]} „{str(o.get('titel') or '')[:90]}“."


def bedienung_erkennen(text: str, kontext: dict | None = None, gid: str | None = None) -> dict[str, Any] | None:
    """Ein reiner Bedienbefehl -> {satz, zeigen|oeffnen|werkzeug}; sonst None (dann antwortet das Modell)."""
    t = re.sub(r"[.!]+$", "", (text or "").strip()).strip()
    if not t or len(t.split()) > 14 or _UND_MEHR.search(t) or ist_ja(t):
        return None
    if _SCHLIESS.search(t):
        return {"satz": "Ich schließe das Fenster.", "werkzeug": "fenster_zu"}
    if _ZURUECK.search(t):
        return {"satz": "Ich gehe eine Seite zurück.", "werkzeug": "zurueck"}
    if _THEMA.search(t) and "?" not in t:
        dunkel = re.search(r"dunkel|dark|nacht", t, re.I)
        return {"satz": "Ich schalte auf " + ("dunkel." if dunkel else "hell."), "werkzeug": "dunkel" if dunkel else "hell"}
    # "Ich will mit Clayton sprechen" -- ein Wunsch nach dem Chat, auch ohne "oeffne".
    m = _mitglied_im_text(t)
    if m and re.search(r"\bmit\s+" + re.escape(m["name"]) + r"\s+(sprechen|reden|chatten|schreiben)\b", t, re.I) and "?" not in t:
        if m["name"].lower() == "neo":
            return {"satz": "Ich öffne dir Neo.", "zeigen": {"ziel": "neo"}}
        return {"satz": f"Ich öffne dir den Chat mit {m['name']}.", "zeigen": {"ziel": f"team/chat/{m['id']}"}}
    verb = bool(_VERB.search(t))
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
    if seite and verb:
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
                   "gespraech": ("gespraeche", "titel"), "datei": ("dateien", "name")}
OEFFNEN_NAME = {"ergebnis": "Ergebnis", "langlauf": "Langläufer", "aufgabe": "Aufgabe", "vorgang": "Case", "projekt": "Projekt", "notiz": "Notiz",
                "gespraech": "Gespräch", "datei": "Unterlage"}
# Gespraech zuerst: "das Gespraech ueber das Kapitel" meint das Gespraech, nicht das Kapitel.
_ART_WORT = (("gespraech", r"gespräch|gespraech|unterhaltung|\bchat\b"),
             # Unterlagen (19.10.2026): "oeffne das Dossier zu Verlagen" -- vor "ergebnis", sonst griffe "Dokument".
             ("datei", r"dossier|unterlage|abschrift|anhang|\bdatei"), ("ergebnis", r"ergebnis|resultat|kapitel|dokument|präsentation|praesentation|video|text"),
             ("langlauf", r"langläufer|langlaeufer|langlauf"), ("aufgabe", r"aufgabe|todo"),
             ("vorgang", r"\bcase|vorgang"), ("projekt", r"projekt"), ("notiz", r"notiz"))
_FUELL = {"öffne", "öffnen", "oeffne", "oeffnen", "zeig", "zeige", "zeigen", "mal", "bitte", "dem", "den", "das", "der", "die",
          "von", "zum", "zur", "und", "mir", "wir", "uns", "ergebnis", "auftrag", "auftrags", "langläufer", "aufgabe", "projekt",
          "fenster", "doch", "noch", "einmal", "kannst", "du", "ich", "möchte", "will", "sehen", "ansehen", "auf", "mach",
          # Bedienwoerter (18.10.2026) -- sonst blieben sie als "Titelwoerter" uebrig
          "gespräch", "gespraech", "chat", "unterhaltung", "über", "ueber", "geh", "gehe", "wechsel", "wechsle", "bring",
          "mich", "anzeigen", "aufmachen", "aufrufen", "jetzt", "dann", "okay", "dir", "ein", "eine", "einen", "bitte", "gerne",
          "moechte", "spring", "navigiere", "hin", "dort", "dahin", "rein", "hinein", "neue", "neuen"}


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
    gesucht = _woerter(text)
    if not gesucht:
        return None
    if not art:
        for a, muster in _ART_WORT:
            if re.search(muster, text or "", re.I):
                art = a
                break
    arten = [art] if art in OEFFNEN_TABELLE else ["ergebnis", "langlauf", "projekt", "aufgabe", "vorgang", "datei"]
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


def beschriften(a: dict[str, Any]) -> str | None:
    art = a["aktion"]
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
    if art == "neo":
        return f"Neo beauftragen: {a['auftrag'][:90]}"
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
        if not vid:
            v = stab.aus_text(a["auftrag"], quelle="gespraech", projekt_id=stab.projekt_finden(a.get("projekt_id")),
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
    if bed:
        zeig = [zeigen_ziel(bed["zeigen"])] if bed.get("zeigen") else []
        oeff = [bed["oeffnen"]] if bed.get("oeffnen") else []
        mid = db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                            (gid, "assistent", bed["satz"], json.dumps({"vorschlaege": [], "modell": "bedienung"}, ensure_ascii=False), time.time()))
        db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), gid))
        yield {"typ": "fertig", "text": bed["satz"], "vorschlaege": [], "nachricht_id": mid, "modell": "bedienung", "medien": [],
               "zeigen": [z for z in zeig if z], "oeffnen": oeff, "werkzeug": bed.get("werkzeug")}
        return
    verlauf = []
    for m in reversed(db.alle("SELECT rolle, text FROM nachrichten WHERE gespraech_id=? ORDER BY id DESC LIMIT 12", (gid,))):
        verlauf.append({"role": "user" if m["rolle"] == "du" else "assistant",
                        "content": m["text"] if m["rolle"] == "du" else _COCKPIT_ZEILE.sub("[Vermerk des Cockpits: hier wurde eine Recherche gestartet.]", m["text"])})
    system = (SYSTEM.replace("{STIMME}", STIMME_ZUSATZ if stimme else "") +
              f"\n\nHEUTE: {time.strftime('%A, %d.%m.%Y %H:%M')}\n\nLAGE:\n{lage_text()}\n\n{kontext_text(kontext)}")
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
    modell = await llm.modell_waehlen(llm.vorgabe("talk"), "qwen3.6:27b", "qwen3:30b-a3b", "llama3.3:70b")
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
    try:
        with llm.taetig("Talk antwortet dir" + (" (gründlich)" if denken else "")):
            async for t in llm.strom(modell, system, verlauf, temperatur=0.4, denken=denken, num_ctx=24576):
                gesamt += t
                if "```aktionen" not in gesamt:
                    yield {"typ": "text", "t": t}
    except llm.ModellFehler as f:
        yield {"typ": "fehler", "text": str(f)}
        return
    sichtbar, vorschlaege = vorschlaege_aus(gesamt)
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
            if (v["aktion"] in ("aufgabe_neu", "notiz", "ausarbeiten") or (v["aktion"] == "zeigen" and v.get("ziel") in ZIELE))                     and not v.get("projekt_id"):
                v["projekt_id"] = kontext["id"]
                v["label"] = beschriften(v) or v["label"]
    _bezug_einsetzen(vorschlaege, bez)
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
        if not zeigen and not oeffnen and sagt_oeffnen:
            sichtbar = re.sub(r"[^.!?\n]*\b(öffne|oeffne|zeige) (dir|ich)\b[^.!?\n]*[.!?]?", "", sichtbar).strip()
            sichtbar = (sichtbar + "\n\nIch habe nichts gefunden, das ich öffnen kann. Sag mir bitte den Titel, so wie er im Cockpit steht.").strip()
    if oeffnen:
        o = oeffnen[0]
        satz = f"Ich öffne dir {('den ' if o['art'] in ('langlauf', 'vorgang') else 'die ' if o['art'] in ('aufgabe', 'notiz') else 'das ')}{OEFFNEN_NAME[o['art']]} „{o['titel'][:90]}“."
        # Den Satz des Modells durch den genauen ersetzen -- es soll dastehen, WAS aufgeht.
        rest = re.sub(r"[^.!?\n]*\b(öffne|oeffne|zeige) (dir|ich)\b[^.!?\n]*[.!?]?", "", sichtbar).strip()
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
    vorher = db.eine("SELECT text, daten FROM nachrichten WHERE gespraech_id=? AND rolle='assistent' ORDER BY id DESC LIMIT 1", (gid,))
    hatte_offen = bool(vorher and any(not v.get("erledigt") for v in ((vorher.get("daten") or {}).get("vorschlaege") or [])))
    bestaetigt = bool(vorher and "?" in (vorher.get("text") or "") and not hatte_offen and ist_ja(text))
    auftrag = bool(AUFTRAG_AN_TEAM.search(text))
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
        if not vorschlaege:
            sichtbar = re.sub(r"[^.!?\n]*(macht sich|arbeitet an|erscheint in der Inbox)[^.!?\n]*[.!?]?", "", sichtbar).strip()
            sichtbar = (sichtbar + "\n\nIch konnte deinem Ja keinen Auftrag zuordnen, gestartet ist noch nichts. Sag mir bitte noch einmal, was das Team tun soll.").strip()
    im_satz = zustimmung_im_satz(text)
    gleich = [v for v in vorschlaege if v["aktion"] not in SOFORT_VERFAHREN
              and (bestaetigt or (auftrag and v["aktion"] in ("ausarbeiten", "neo"))
                   or (v.get("zugestimmt") is True and im_satz))]
    ausgefuehrt = []
    for v in gleich[:3]:
        try:
            r = await ausfuehren(v)
        except Exception as f:  # noqa: BLE001
            r = {"ok": False, "grund": str(f)}
        v["erledigt"] = bool(r.get("ok"))
        v["ergebnis"] = r
        ausgefuehrt.append(r)
    if ausgefuehrt:
        if all(r.get("ok") for r in ausgefuehrt):
            hinweis = ("Neo arbeitet daran." if any(r.get("neo_gespraech") for r in ausgefuehrt)
                       else "Ist beim Team, das Ergebnis erscheint in der Inbox." if any(r.get("vorgang_id") for r in ausgefuehrt) else "Erledigt.")
        else:
            hinweis = "Nicht alles ging: " + "; ".join(str(r.get("grund")) for r in ausgefuehrt if not r.get("ok"))
        sichtbar = re.sub(r"\s*Soll ich das so machen\?\s*$", "", sichtbar).strip()
        schon_gesagt = all(r.get("ok") for r in ausgefuehrt) and re.search(r"Inbox|arbeite|macht sich|kümmer|erledigt", sichtbar, re.I)
        if not schon_gesagt:
            sichtbar = (sichtbar + "\n\n" + hinweis).strip()
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
        sichtbar = re.sub(r"[^.!?\n]*\b(gebe das (an \w+ )?weiter|leg(e|t) (es|das|ihn) an|kümmert sich|macht sich)\b[^.!?\n]*[.!?]?", "", sichtbar).strip()
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
    sichtbar += stab.netz_fuss(quellen)
    mid = db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                        (gid, "assistent", sichtbar, json.dumps({"vorschlaege": vorschlaege, "modell": modell, "medien": medien_jobs,
                                                                 "bezug": bez}, ensure_ascii=False), time.time()))
    db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), gid))
    yield {"typ": "fertig", "text": sichtbar, "vorschlaege": vorschlaege, "nachricht_id": mid, "modell": modell, "medien": medien_jobs, "bezug": bez,
           "zeigen": [z for z in (zeigen_ziel(v) for v in zeigen[:1]) if z],
           "oeffnen": oeffnen[:1], "werkzeug": werkzeug}


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
        ergebnisse.append(r)
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
        if v["aktion"] in ("aufgabe_neu", "notiz", "ausarbeiten") and not v.get("projekt_id") and b.get("projekt_id"):
            v["projekt_id"] = b["projekt_id"]
            v["label"] = beschriften(v) or v["label"]
        if v["aktion"] == "ausarbeiten" and not v.get("aufgabe_id") and b.get("aufgabe_id"):
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
