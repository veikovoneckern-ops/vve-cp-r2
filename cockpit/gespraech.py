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


def ist_ja(text: str) -> bool:
    t = (text or "").strip()
    return len(t.split()) <= 10 and bool(_JA.search(t)) and not _NEIN.search(t)

SYSTEM = """Du bist das VvE Cockpit: die Stimme von Veikos persönlichem KI-Team. Veiko von Eckern ist Head of Corporate HR Transformation bei Krones. Sein Team: Jason (Head of PMO, ordnet ein), Neo (Cockpit Engineer), Clayton (Strategie), Neal (Texte, Bücher), Daniel (Red Team, prüft), Annie (Gestaltung), Ridley (Video).

So antwortest du:
- Deutsch, direkt, freundlich, ohne Vorrede. Zuerst die Antwort, dann wenn nötig die Begründung.
- Erfinde nichts. Du kennst nur, was unten in LAGE und KONTEXT steht. Wenn etwas fehlt, sag es.
- Nenne, wer gearbeitet hat, aber nur, wenn es in LAGE oder KONTEXT steht. Schreib niemandem eine Arbeit zu, die dort nicht vorkommt.
- Nenne im Text NIE interne Kennungen (e…, t…, p…, v…). Die gehören nur in den aktionen-Block. Im Text sagst du den Titel.
- Auf "Was liegt an?" antwortest du knapp: höchstens fünf Punkte, das Wichtigste zuerst (offene Entscheidungen, Überfälliges, was läuft). Keine vollständigen Listen.
- Kein Fachjargon ohne Erklärung.
- Wortwahl wie im Cockpit: „Team“ (nicht „Stab“), „Case“ (nicht „Akte“), „Memory“ (nicht „Gedächtnis“), „Advisory Board“ (nicht „Beirat“).
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
- {"aktion":"zeigen","ziel":"board|briefing|inbox|projects|team|neo|system|watchdog|brainstrom|exo"} -- öffnet einen Bereich des Cockpits sofort. Will Veiko „mit dem Advisory Board sprechen“: ziel board. Stellt er dabei schon eine Frage ans Board, gib sie als "frage" mit -- das Board antwortet dann selbst, du antwortest nicht an seiner Stelle.
- {"aktion":"ausarbeiten","rolle":"stratege|buch|designer|video","form":"text|aufstellung|konzept|dokument|webseite|praesentation","auftrag":"…","recherche":"Suchanfrage oder null","vorgang_id":"v… oder null","projekt_id":"p… oder null"}
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
AUSNAHME bild und visualisierung: die laufen sofort los, das Ergebnis erscheint gleich im Gespräch zum Ansehen und Herunterladen. Sag nur kurz „Ich erstelle dir das Bild, es erscheint gleich hier.“ bzw. „… die Visualisierung …“ -- keine Frage. Beziehen sie sich auf das Gespräch oder KONTEXT, nimm dessen Inhalte in prompt bzw. beschreibung auf.
AUSNAHME BrainStrom und ExO (brainstrom, brainstrom_antwort, brainstrom_genug, brainstrom_weg, exo): laufen sofort. Sag nur kurz, was passiert („Ich gebe deine Antwort an BrainStrom.“) -- KEINE Frage und nicht selbst die nächste BrainStrom-Frage erfinden; die stellt BrainStrom, das Cockpit liest sie vor. Ist Veiko in BrainStrom und antwortet auf die aktuelle Frage, ist das IMMER brainstrom_antwort.
DIE NOTABSCHALTUNG (Kill Switch, Safety Shutdown) gibt es NIE über das Gespräch, auch nicht auf ausdrücklichen Wunsch: sag, dass sie nur über die Knöpfe im WatchDog geht, und biete an, den WatchDog zu öffnen.
AUSNAHME zeigen: das öffnet nur eine Ansicht und passiert sofort. Dann KEINE Frage, sondern ein kurzer Satz wie „Ich öffne dir das Advisory Board.“ Reichst du eine Frage ans Board weiter, sag „Ich gebe deine Frage ans Advisory Board weiter.“ und antworte nicht selbst an seiner Stelle.
Wenn Veiko eine offene Entscheidung bestätigt oder ablehnt, gehört genau EINE passende entscheiden-Aktion in den Block, nicht mehr.
aufgabe_erledigt nur, wenn Veiko sagt, dass er etwas erledigt hat. Überfällig heißt nicht erledigt.
Schaut Veiko auf ein PROJEKT (siehe KONTEXT), dann geht es um dieses Projekt, solange er nichts anderes sagt: neue Aufgaben, Notizen und Ausarbeitungen gehören dorthin. Will er etwas sehen („zeig mir die Aufgaben“), nimm zeigen.
Wünscht Veiko ein Dokument, eine Präsentation, eine Recherche oder einen Entwurf: ausarbeiten (form dokument für Word, praesentation für Folien). Geht es um das Cockpit, den Server oder Software: neo.

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
    lauf = db.alle("SELECT id, titel, auftrag FROM vorgaenge WHERE stand='in_arbeit' LIMIT 5")
    if lauf:
        teile.append("IN ARBEIT:\n" + "\n".join(f"- {v['id']}: {v['titel']}" for v in lauf))
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
    return ""


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
BEREICHE = {"board": "Advisory Board", "briefing": "Briefing", "inbox": "Inbox", "projects": "Projects", "team": "Team",
            "neo": "Neo", "system": "System", "watchdog": "WatchDog", "brainstrom": "BrainStrom", "exo": "ExO"}


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
        name = ZIELE.get(a.get("ziel")) or BEREICHE.get(a.get("ziel"))
        return name and f"Zeigen: {name}"
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
                                  "recherche": a.get("recherche")})
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


async def senden(gid: str, text: str, kontext: dict | None, anhaenge: list[str], stimme: bool) -> AsyncIterator[dict]:
    voll = text
    for did in anhaenge or []:
        d = db.holen("dateien", did)
        if d and d.get("text"):
            voll += f"\n\n[Angehängt: {d['name']}]\n{d['text'][:15000]}"
        elif d:
            voll += f"\n\n[Angehängt: {d['name']} -- Inhalt nicht lesbar]"
    db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                  (gid, "du", voll, json.dumps({"anzeige": text, "kontext": kontext or {}}, ensure_ascii=False), time.time()))
    if db.wert("SELECT titel FROM gespraeche WHERE id=?", (gid,)) == "Gespräch":
        db.ausfuehren("UPDATE gespraeche SET titel=? WHERE id=?", (text[:60] or "Gespräch", gid))
    verlauf = []
    for m in reversed(db.alle("SELECT rolle, text FROM nachrichten WHERE gespraech_id=? ORDER BY id DESC LIMIT 12", (gid,))):
        verlauf.append({"role": "user" if m["rolle"] == "du" else "assistant", "content": m["text"]})
    system = (SYSTEM.replace("{STIMME}", STIMME_ZUSATZ if stimme else "") +
              f"\n\nHEUTE: {time.strftime('%A, %d.%m.%Y %H:%M')}\n\nLAGE:\n{lage_text()}\n\n{kontext_text(kontext)}")
    if re.search(r"beirat|board|vordenker", text, re.I):
        system += "\n\n" + beirat_text()
    modell = await llm.modell_waehlen(MODELL_TALK, "qwen3.6:27b", "qwen3:30b-a3b", "llama3.3:70b")
    if not modell:
        yield {"typ": "fehler", "text": "Kein lokales Modell für das Gespräch installiert."}
        return
    gesamt = ""
    try:
        async for t in llm.strom(modell, system, verlauf, temperatur=0.4, denken=False, num_ctx=24576):
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
    # "Zeigen" aendert nichts -- das Cockpit fuehrt es sofort aus, ohne Knopf.
    zeigen = [v for v in vorschlaege if v["aktion"] == "zeigen" and (v.get("projekt_id") or v.get("ziel") in BEREICHE)]
    vorschlaege = [v for v in vorschlaege if v["aktion"] != "zeigen"]
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
            vorschlaege += [v for v in nach if v["aktion"] not in ("zeigen", "bild", "visualisierung")]
        except llm.ModellFehler:
            pass
        if not vorschlaege:
            sichtbar = re.sub(r"[^.!?\n]*(macht sich|arbeitet an|erscheint in der Inbox)[^.!?\n]*[.!?]?", "", sichtbar).strip()
            sichtbar = (sichtbar + "\n\nIch konnte deinem Ja keinen Auftrag zuordnen, gestartet ist noch nichts. Sag mir bitte noch einmal, was das Team tun soll.").strip()
    gleich = [v for v in vorschlaege if v["aktion"] not in SOFORT_VERFAHREN
              and (bestaetigt or (auftrag and v["aktion"] in ("ausarbeiten", "neo")))]
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
    if llm.fremdschrift(sichtbar):
        sichtbar = llm.FREMDSCHRIFT.sub("", sichtbar)
    mid = db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                        (gid, "assistent", sichtbar, json.dumps({"vorschlaege": vorschlaege, "modell": modell, "medien": medien_jobs}, ensure_ascii=False), time.time()))
    db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), gid))
    yield {"typ": "fertig", "text": sichtbar, "vorschlaege": vorschlaege, "nachricht_id": mid, "modell": modell, "medien": medien_jobs,
           "zeigen": [{"ziel": v["ziel"], "projekt_id": v.get("projekt_id") if v.get("ziel") in ZIELE else None,
                       "frage": str(v.get("frage") or "")[:2000] or None} for v in zeigen[:1]]}


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
