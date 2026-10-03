"""
DER STAB-KERN -- was mit einer Notiz passiert, ohne dass Veiko dabei sein muss.

Drei Stufen statt einer Pipeline fuer alles (Konzept, Abschnitt 8):

  1 EINORDNEN  immer        Jason: Projekt, Anliegen, Zusammenfassung, Fragen
  2 ABLEITEN   immer        Jason: Aufgaben fuer Veiko, Vorschlaege
  3 AUSARBEITEN nur auf Auftrag  Fachrolle + Recherche, Daniel prueft, eine
                            Nachbesserungsrunde, Ergebnis landet im Projekt

Warum so (Befund B3): Im alten Journal urteilte die Pruefung 25-mal
"nachbessern" und einmal "tragfaehig"; das beste Ergebnis war das
einfachste -- vier klare Aufgaben aus "Muttis Nachlasswuenschen". Kleine,
verlaessliche Dinge laufen deshalb immer, teure und fehleranfaellige nur,
wenn jemand sie verlangt.

Was der Stab selbst tun darf, regeln die Vertrauensstufen (einstellung
"vertrauen"). Alles, was er selbst anlegt oder aendert, steht im Protokoll
und laesst sich mit einem Klick zuruecknehmen.
"""
from __future__ import annotations

import asyncio
import html as htmlmod
import json
import re
import time
import traceback
from pathlib import Path
from typing import Any

import httpx

from . import db, llm
from .konfig import (ERGEBNIS_DIR, MODELL_ARBEIT, MODELL_STAB, PLAUD_DIR, SEARX,
                     STAB_TAKT_SEK)

# ---------------------------------------------------------------- Vertrauen
VERTRAUEN_VORGABE = {
    "zuordnen": "selbst",        # Notiz einem bestehenden Projekt zuordnen
    "aufgaben": "selbst",        # Aufgaben fuer Veiko anlegen
    "ausarbeiten": "selbst",     # lokal ausarbeiten, wenn die Notiz es verlangt
    "projekt_neu": "fragen",     # neues Projekt
    "gedaechtnis": "fragen",     # Gedaechtnis-Eintrag
}


def vertrauen() -> dict[str, str]:
    v = dict(VERTRAUEN_VORGABE)
    v.update(db.einstellung("vertrauen", {}) or {})
    return v


def stab_aktiv() -> bool:
    return bool(db.einstellung("stab_aktiv", True))


# Woerter, an denen man einen ausdruecklichen Auftrag erkennt. Feste Regel im
# Code, weil das Modell sich nicht verlaesslich daran haelt (gemessen am
# 30.09.: llama3.3 erfand trotz Verbot ein "Konzept fuer Projekt EVE").
AUSARBEITUNG_RE = re.compile(
    r"arbeite\w*\s.*\saus|ausarbeit|entw[ue]rf|recherch|such\w*\s.*\s(raus|heraus)|"
    r"finde\s+(heraus|raus)|mach\w*\s+(mir\s+)?(einen?|eine)\s+(vorschlag|konzept|entwurf|präsentation|praesentation|aufstellung|übersicht|uebersicht|liste)|"
    r"erstell\w*|schreib\w*\s+(mir\s+)?(einen?|eine|den|die|das)|präsentation|praesentation|webseite|landingpage|"
    r"vergleich\w*|zusammenstellung|stell\w*\s.*\szusammen",
    re.IGNORECASE)

ROLLEN_FUER_ARBEIT = ("stratege", "buch", "designer", "video", "cockpit", "pmo")
FORMEN = ("text", "aufstellung", "konzept", "dokument", "webseite", "praesentation")
FORM_ANWEISUNG = {
    "text": "Liefere einen fertigen, gut lesbaren Text in Markdown.",
    "aufstellung": "Liefere eine Aufstellung als Markdown-Tabelle oder gegliederte Liste. Jede Zeile mit Quelle, wo es eine gibt.",
    "konzept": "Liefere ein Konzept in Markdown: Ziel, Ausgangslage, Vorschlag, Schritte, offene Punkte.",
    "webseite": "Liefere eine vollstaendige, eigenstaendige HTML-Seite (inline CSS, kein externes Skript) in EINEM ```html-Block. Davor zwei Saetze, was die Seite zeigt.",
    "dokument": "Liefere ein vollständiges, gegliedertes Dokument in Markdown (Titel mit #, Abschnitte mit ##, Listen, Tabellen wo sinnvoll). Es wird als Word-Datei ausgegeben -- schreib es so, dass man es direkt weitergeben kann.",
    "praesentation": "Liefere Folien in Markdown. Trenne Folien mit einer Zeile, die nur '---' enthaelt. Jede Folie: '# Titel' und hoechstens fuenf Stichpunkte.",
}

# ---------------------------------------------------------------- Zustand
ZUSTAND: dict[str, Any] = {"laeuft": None, "letzter_lauf": None, "letzter_fehler": None,
                           "durchgaenge": 0}
_lock = asyncio.Lock()


def laeuft(wer: str | None, was: str = "", vorgang_id: str | None = None) -> None:
    ZUSTAND["laeuft"] = {"wer": wer, "was": was, "vorgang_id": vorgang_id, "seit": time.time()} if wer else None


# ---------------------------------------------------------------- Wissen
def gedaechtnis_text() -> str:
    zeilen = [f"- {g['begriff']} = {g['bedeutung']}" for g in
              db.alle("SELECT * FROM gedaechtnis WHERE bestaetigt=1 AND art!='hoerfehler' ORDER BY begriff")]
    return "\n".join(zeilen) if zeilen else "(noch nichts eingetragen)"


def hoerfehler_korrigieren(text: str) -> str:
    for g in db.alle("SELECT begriff, bedeutung FROM gedaechtnis WHERE art='hoerfehler' AND bestaetigt=1"):
        if g["begriff"]:
            text = re.sub(r"\b" + re.escape(g["begriff"]) + r"\b", g["bedeutung"], text, flags=re.IGNORECASE)
    return text


def whisper_vorlage() -> str:
    """Namen fuer Whispers initial_prompt -- dann hoert es "Krones" statt "Kronis"."""
    # Whisper nimmt etwa 220 Tokens Vorlage; was dahinter steht, wird abgeschnitten.
    # Deshalb ZUERST die englischen Woerter des Cockpits und des Arbeitsalltags --
    # die erkennt ein deutsch eingestelltes Whisper am schlechtesten
    # ("Advisory Board", "Use Case"; Veiko, 01. und 03.10.).
    namen = ["Advisory Board", "Briefing", "Inbox", "Capture", "Talk", "Case", "Memory", "Projects", "Team", "Neo",
             "WatchDog", "BrainStrom", "ExO", "Kill Switch", "Dialog beenden", "Use Case", "Workshop", "Meeting",
             "Masterclass", "Feedback", "Deadline", "Update", "Slides", "Prompt", "Leadership", "Learning"]
    namen += [t["name"] for t in db.alle("SELECT name FROM team")]  # "Neo" statt "Nioh"
    namen += [g["bedeutung"] if g["art"] == "hoerfehler" else g["begriff"]
              for g in db.alle("SELECT art, begriff, bedeutung FROM gedaechtnis WHERE bestaetigt=1 AND art!='aussprache'")]
    namen += [p["name"] for p in db.alle("SELECT name FROM projekte WHERE status!='archiviert'")]
    try:
        from .board import PROFILE
        namen += [p["name"] for p in PROFILE["persons"]]
    except (ImportError, OSError, ValueError, KeyError):
        pass
    return ", ".join(dict.fromkeys(n for n in namen if n))[:900]


def projektliste_text() -> str:
    zeilen = []
    for p in db.alle("SELECT * FROM projekte WHERE status!='archiviert' ORDER BY sortierung, name"):
        frueher = p.get("fruehere_namen") or []
        z = f"- {p['id']} | {p['name']}"
        if frueher:
            z += f" (frueher: {', '.join(frueher)})"
        if p.get("ziel"):
            z += f" -- {p['ziel'][:80]}"
        zeilen.append(z)
    return "\n".join(zeilen) or "(keine Projekte)"


def rolle(rid: str) -> dict[str, Any]:
    return db.holen("team", rid) or {"id": rid, "name": rid, "titel": "", "auftrag": "", "modell": ""}


def rollen_name(rid: str | None) -> str:
    if not rid:
        return "Team"
    if rid in ("du", "veiko"):
        return "Du"
    if rid == "system":
        return "Cockpit"
    r = db.holen("team", rid)
    return r["name"] if r else rid


async def modell_fuer(rid: str, rueckfall: str) -> str | None:
    r = rolle(rid)
    return await llm.modell_waehlen(r.get("modell"), rueckfall, MODELL_ARBEIT, "qwen3.6:27b", "qwen3:30b-a3b")


def projekt_finden(wert: Any) -> str | None:
    if not wert:
        return None
    w = str(wert).strip()
    if db.holen("projekte", w):
        return w
    norm = w.lower()
    for p in db.alle("SELECT id, name, fruehere_namen FROM projekte"):
        if p["name"].lower() == norm or norm in [n.lower() for n in (p.get("fruehere_namen") or [])]:
            return p["id"]
    return None


# ---------------------------------------------------------------- Eingang
def notiz_text(n: dict[str, Any], grenze: int = 6000) -> str:
    t = (n.get("text") or "").strip() or (n.get("kurz") or "").strip()
    # Plaud-Kopfzeilen ("Transcript: ...", "[00:01 - 00:08] Speaker 1:") weg -- Rauschen.
    t = re.sub(r"^Transcript:.*\n", "", t)
    t = re.sub(r"\[\d\d:\d\d\s*-\s*\d\d:\d\d\]\s*Speaker \d+:\s*", "", t)
    t = hoerfehler_korrigieren(t.strip())
    return t[:grenze] + (" …[gekürzt]" if len(t) > grenze else "")


def vorgang_anlegen(notiz: dict[str, Any], quelle: str, titel: str | None = None,
                    projekt_id: str | None = None, auftrag: dict | None = None) -> dict[str, Any]:
    vid = db.neue_id("v")
    jetzt = time.time()
    db.einfuegen("vorgaenge", {
        "id": vid, "titel": titel or (notiz.get("titel") or "Neue Notiz")[:120], "stand": "neu",
        "notiz_id": notiz["id"], "projekt_id": projekt_id, "quelle": quelle, "erstellt": jetzt,
        "geaendert": jetzt, "auftrag": json.dumps(auftrag, ensure_ascii=False) if auftrag else None,
    })
    db.ereignis(vid, "du", "notiz", notiz_text(notiz, 4000),
                {"quelle": quelle, "notiz_id": notiz["id"], "datum": notiz.get("datum")})
    return db.holen("vorgaenge", vid)  # type: ignore[return-value]


def aus_text(text: str, quelle: str = "eingabe", projekt_id: str | None = None,
             titel: str | None = None) -> dict[str, Any]:
    """Erfassen, Talk und Neo-Auftraege: Text wird eine Notiz UND ein Vorgang."""
    nid = db.neue_id("n")
    jetzt = time.time()
    db.einfuegen("notizen", {"id": nid, "titel": titel or text[:60], "datum": time.strftime("%Y-%m-%d"),
                             "text": text, "quelle": quelle, "projekt_id": projekt_id, "erstellt": jetzt})
    return vorgang_anlegen(db.holen("notizen", nid) or {"id": nid, "text": text}, quelle,
                           titel=titel or text[:80], projekt_id=projekt_id)


def plaud_scannen() -> int:
    """Neue Plaud-Notizen aus der Ablage des alten Servers holen (nur lesen)."""
    if not PLAUD_DIR.is_dir():
        return 0
    ab = float(db.einstellung("stab_ab", time.time()) or time.time())
    neu = 0
    for f in sorted(PLAUD_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime):
        pid = f.stem
        if db.wert("SELECT 1 FROM notizen WHERE plaud_id=?", (pid,)):
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not (d.get("transcript") or d.get("summary")):
            continue
        nid = "pl" + pid[:12]
        if db.holen("notizen", nid):
            nid = db.neue_id("pl")
        angekommen = float(d.get("fetched") or f.stat().st_mtime)
        db.einfuegen("notizen", {
            "id": nid, "titel": d.get("name") or "Plaud-Notiz", "datum": str(d.get("created_at") or "")[:10],
            "text": d.get("transcript") or "", "kurz": d.get("summary") or "", "quelle": "plaud",
            "projekt_id": None, "plaud_id": pid, "erstellt": float(d.get("created_ts") or angekommen),
        })
        neu += 1
        if angekommen >= ab and stab_aktiv():
            vorgang_anlegen(db.holen("notizen", nid) or {"id": nid}, "plaud")
    return neu


# ---------------------------------------------------------------- Stufe 1+2
EINORDNEN_SYSTEM = """Du bist Jason, Head of PMO in Veiko von Eckerns persönlichem Stab. Veiko ist Head of Corporate HR Transformation bei Krones und hat daneben private Vorhaben. Du ordnest eine neue Notiz ein, die er gesprochen oder geschrieben hat.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau dieser Form:
{
 "titel": "kurzer Titel, höchstens 8 Wörter",
 "zusammenfassung": "ein Satz, was Veiko will",
 "art": "aufgabe | idee | information | privat",
 "projekt_id": "eine id aus der Projektliste oder null",
 "projekt_neu": "kurzer Name für ein neues Projekt oder null",
 "aufgaben": [{"titel": "konkrete Handlung für Veiko", "projekt_id": "id aus der Liste oder null"}],
 "ausarbeitung": null oder {"rolle": "stratege|buch|designer|video|cockpit", "form": "text|aufstellung|konzept|webseite|praesentation", "auftrag": "was genau erarbeitet werden soll", "recherche": "Suchanfrage oder null"},
 "rueckfrage": "eine Frage an Veiko oder null",
 "gedaechtnis": [{"art": "person|organisation|begriff", "begriff": "...", "bedeutung": "..."}]
}

Regeln:
- Erfinde nichts. Was nicht in der Notiz steht, kommt nicht vor. Keine Zahlen, Daten oder Namen dazudichten.
- projekt_id nur aus der Liste. Nutze das GEDÄCHTNIS, um Personen und Begriffe zuzuordnen.
- projekt_neu nur, wenn die Notiz ausdrücklich ein neues Projekt verlangt oder klar ein neues, eigenständiges Vorhaben beschreibt, das in kein bestehendes passt.
- aufgaben: nur Handlungen, die Veiko SELBST erledigen will ("ich muss", "ich will", "nicht vergessen"). Eine je Anliegen, kurz, im Imperativ. Höchstens 6. Jede Aufgabe bekommt ihr eigenes passendes Projekt (projekt_id), eine Notiz kann mehrere Projekte betreffen. Keine Aufgabe über das Anlegen oder Zuordnen eines Projekts.
- ausarbeitung: nur für das, worum Veiko den STAB ausdrücklich bittet ("such mir raus", "arbeite aus", "mach mir einen Entwurf", "stell zusammen", "recherchiere"). Was er selbst tun muss, ist eine Aufgabe, keine Ausarbeitung. Sonst null. stratege = Recherchen, Aufstellungen, Strategie, Konzepte; buch = Texte, Artikel, Bücher, Mails; designer = Bilder und Gestaltung; video = Video; cockpit = das Cockpit oder Software. recherche = eine knappe Suchanfrage, wenn Fakten aus dem Internet nötig sind.

BEISPIEL
Notiz: "Ich muss morgen den Quartalsbericht abgeben und Papa anrufen. Such mir raus, welche Hotels in Hamburg Tagungsräume haben."
Antwort: {"titel": "Quartalsbericht, Papa, Tagungshotels", "zusammenfassung": "Bericht abgeben, Vater anrufen, Tagungshotels in Hamburg finden lassen", "art": "aufgabe", "projekt_id": null, "projekt_neu": null,
 "aufgaben": [{"titel": "Quartalsbericht abgeben", "projekt_id": null}, {"titel": "Papa anrufen", "projekt_id": null}],
 "ausarbeitung": {"rolle": "stratege", "form": "aufstellung", "auftrag": "Hotels in Hamburg mit Tagungsräumen zusammenstellen, mit Kontakt und Quelle", "recherche": "Hotel Hamburg Tagungsräume"},
 "rueckfrage": null, "gedaechtnis": []}
(Im Beispiel gibt es keine passenden Projekte; bei dir nimmst du die ids aus der Liste.)
- rueckfrage nur, wenn ohne Antwort nichts Sinnvolles möglich ist.
- gedaechtnis: nur eindeutige Zuordnungen, die die Notiz belegt (z. B. wer mit einem Spitznamen gemeint ist). Sonst [].
- Schreibe Deutsch."""


async def einordnen(v: dict[str, Any]) -> None:
    n = db.holen("notizen", v["notiz_id"]) if v.get("notiz_id") else None
    if not n:
        db.aendern("vorgaenge", v["id"], {"stand": "fertig"}, wer="system")
        db.ereignis(v["id"], "system", "fehler", "Zum Vorgang gibt es keine Notiz mehr.")
        return
    modell = await modell_fuer("pmo", MODELL_STAB)
    if not modell:
        raise llm.ModellFehler("Kein passendes lokales Modell installiert.")
    laeuft("pmo", "ordnet ein", v["id"])
    frage = (f"GEDÄCHTNIS (was über Veiko bekannt ist):\n{gedaechtnis_text()}\n\n"
             f"PROJEKTE:\n{projektliste_text()}\n\n"
             f"NOTIZ vom {n.get('datum') or 'unbekannt'} ({n.get('quelle')}):\n{notiz_text(n)}")
    if v.get("auftrag"):
        frage += f"\n\nVORGABE AUS DEM GESPRÄCH: {v['auftrag']}"
    d = None
    for versuch in range(2):
        antwort = await llm.chat(modell, EINORDNEN_SYSTEM, [{"role": "user", "content": frage}],
                                 json_format=True, temperatur=0.2, denken=False)
        d = llm.json_aus(antwort)
        if isinstance(d, dict) and not llm.fremdschrift(json.dumps(d, ensure_ascii=False)):
            break
        d = None
    if not isinstance(d, dict):
        raise llm.ModellFehler("Jason hat keine lesbare Einordnung geliefert (zweimal versucht).")
    anwenden(v, n, d, modell)


def _kurz(s: Any, n: int = 200) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def anwenden(v: dict[str, Any], n: dict[str, Any], d: dict[str, Any], modell: str) -> None:
    vt = vertrauen()
    vid = v["id"]
    titel = _kurz(d.get("titel"), 90) or v["titel"]
    zus = _kurz(d.get("zusammenfassung"), 300)
    pid = projekt_finden(d.get("projekt_id")) or projekt_finden(d.get("projekt_neu"))
    if v.get("projekt_id"):
        pid = v["projekt_id"]
    db.aendern("vorgaenge", vid, {"titel": titel, "einordnung": zus}, wer="pmo", vorgang_id=vid)

    teile = [zus] if zus else []
    if pid:
        pname = (db.holen("projekte", pid) or {}).get("name", pid)
        if vt["zuordnen"] == "selbst" or v.get("projekt_id"):
            db.aendern("vorgaenge", vid, {"projekt_id": pid}, wer="pmo", vorgang_id=vid, aktion="zugeordnet")
            if n.get("projekt_id") != pid:
                db.aendern("notizen", n["id"], {"projekt_id": pid}, wer="pmo", vorgang_id=vid, aktion="zugeordnet")
            teile.append(f"Projekt: **{pname}**")
        else:
            entscheidung_anlegen(vid, "zuordnung", f"Notiz dem Projekt „{pname}“ zuordnen?", {"projekt_id": pid})

    neues_projekt = None if pid else _kurz(d.get("projekt_neu"), 60) or None
    if neues_projekt:
        db.aendern("vorgaenge", vid, {"projekt_vorschlag": neues_projekt}, wer="pmo", vorgang_id=vid)
        if not db.wert("SELECT 1 FROM entscheidungen WHERE art='projekt_neu' AND stand='offen' AND lower(json_extract(daten,'$.name'))=lower(?)",
                       (neues_projekt,)):
            entscheidung_anlegen(vid, "projekt_neu", f"Neues Projekt „{neues_projekt}“ anlegen?",
                                 {"name": neues_projekt})

    angelegt = []
    vorhandene = {a["titel"].lower() for a in db.alle("SELECT titel FROM aufgaben WHERE vorgang_id=?", (vid,))}
    for a in (d.get("aufgaben") or [])[:6]:
        t = _kurz(a.get("titel") if isinstance(a, dict) else a, 140)
        if not t or t.lower() in vorhandene or re.search(r"projekt\s+(an)?leg|zuordn", t, re.I):
            continue
        # Eigenes Projekt je Aufgabe: eine Notiz betrifft oft mehrere Vorhaben
        # (gemessen: "Skript OTH" und "Frau Schwarz anrufen" in EINER Notiz).
        a_pid = (projekt_finden(a.get("projekt_id")) if isinstance(a, dict) and a.get("projekt_id") else None) or pid
        if vt["aufgaben"] == "selbst":
            db.anlegen("aufgaben", {"id": db.neue_id("t"), "titel": t, "projekt_id": a_pid, "status": "offen",
                                    "prio": 2, "quelle": "stab", "vorgang_id": vid, "notiz_id": n["id"],
                                    "erstellt": time.time(), "geaendert": time.time()},
                       wer="pmo", vorgang_id=vid)
            angelegt.append(t)
        else:
            entscheidung_anlegen(vid, "aufgabe", f"Aufgabe anlegen: „{t}“?", {"titel": t, "projekt_id": a_pid})
    if angelegt:
        teile.append("Für dich angelegt: " + "; ".join(angelegt))

    for g in (d.get("gedaechtnis") or [])[:3]:
        if not isinstance(g, dict) or not g.get("begriff") or not g.get("bedeutung"):
            continue
        b, bed = _kurz(g["begriff"], 60), _kurz(g["bedeutung"], 160)
        if db.wert("SELECT 1 FROM gedaechtnis WHERE lower(begriff)=lower(?)", (b,)):
            continue
        if db.wert("SELECT 1 FROM entscheidungen WHERE art='gedaechtnis' AND stand='offen' AND lower(json_extract(daten,'$.begriff'))=lower(?)", (b,)):
            continue
        art = g.get("art") if g.get("art") in ("person", "organisation", "begriff") else "begriff"
        if vt["gedaechtnis"] == "selbst":
            db.anlegen("gedaechtnis", {"id": db.neue_id("g"), "art": art, "begriff": b, "bedeutung": bed,
                                       "bestaetigt": 1, "quelle": vid, "erstellt": time.time()}, wer="pmo", vorgang_id=vid)
        else:
            entscheidung_anlegen(vid, "gedaechtnis", f"„{b}“ ist {bed}. Merken?",
                                 {"art": art, "begriff": b, "bedeutung": bed})

    if d.get("rueckfrage"):
        entscheidung_anlegen(vid, "rueckfrage", _kurz(d["rueckfrage"], 400), {})

    aus = d.get("ausarbeitung")
    if isinstance(aus, dict) and aus.get("auftrag"):
        r = aus.get("rolle") if aus.get("rolle") in ROLLEN_FUER_ARBEIT else "stratege"
        f = aus.get("form") if aus.get("form") in FORMEN else "text"
        auftrag = {"rolle": r, "form": f, "auftrag": _kurz(aus["auftrag"], 600),
                   "recherche": _kurz(aus.get("recherche"), 150) or None}
        verlangt = bool(AUSARBEITUNG_RE.search(notiz_text(n))) or v.get("quelle") == "gespraech"
        if verlangt and vt["ausarbeiten"] == "selbst":
            db.aendern("vorgaenge", vid, {"auftrag": json.dumps(auftrag, ensure_ascii=False)}, wer="pmo", vorgang_id=vid)
            teile.append(f"{rollen_name(r)} arbeitet aus: {auftrag['auftrag']}")
        else:
            entscheidung_anlegen(vid, "ausarbeitung",
                                 f"Soll {rollen_name(r)} das ausarbeiten? {auftrag['auftrag']}", auftrag)

    db.ereignis(vid, "pmo", "einordnung", "\n".join(f"- {t}" if i else t for i, t in enumerate(teile)) or "Eingeordnet.",
                {"modell": modell, "art": d.get("art")})
    stand_berechnen(vid)


def entscheidung_anlegen(vid: str | None, art: str, frage: str, daten: dict[str, Any],
                         wer: str = "pmo") -> str:
    eid = db.neue_id("e")
    db.einfuegen("entscheidungen", {"id": eid, "vorgang_id": vid, "art": art, "frage": frage,
                                    "daten": daten, "wer": wer, "stand": "offen", "erstellt": time.time()})
    if vid:
        db.ereignis(vid, wer, "rueckfrage" if art == "rueckfrage" else "vorschlag", frage,
                    {"entscheidung_id": eid, "art": art})
    return eid


def stand_berechnen(vid: str) -> str:
    v = db.holen("vorgaenge", vid)
    if not v or v["stand"] in ("erledigt", "verworfen"):
        return v["stand"] if v else ""
    offen = db.wert("SELECT COUNT(*) FROM entscheidungen WHERE vorgang_id=? AND stand='offen'", (vid,))
    hat_auftrag = auftrag_offen(v) is not None
    if offen:
        neu = "wartet"
    elif hat_auftrag:
        neu = "in_arbeit"
    else:
        neu = "fertig"
    if neu != v["stand"]:
        db.ausfuehren("UPDATE vorgaenge SET stand=?, geaendert=? WHERE id=?", (neu, time.time(), vid))
    return neu


def auftrag_offen(v: dict[str, Any]) -> dict[str, Any] | None:
    """Ein Auftrag ist offen, bis sein Ergebnis da ist ("erledigt" gesetzt).
    Unabhaengig davon, ob daneben eine Frage offen ist -- eine Recherche soll
    nicht warten, bis Veiko eine Gedaechtnis-Frage beantwortet hat."""
    try:
        a = json.loads(v.get("auftrag") or "null")
    except (ValueError, TypeError):
        return None
    return a if isinstance(a, dict) and a.get("auftrag") and not a.get("erledigt") else None


def _auftrag_erledigt(vid: str) -> None:
    v = db.holen("vorgaenge", vid) or {}
    a = auftrag_offen(v)
    if a:
        a["erledigt"] = time.time()
        db.ausfuehren("UPDATE vorgaenge SET auftrag=? WHERE id=?", (json.dumps(a, ensure_ascii=False), vid))


def auftrag_setzen(vid: str, auftrag: dict[str, Any]) -> None:
    auftrag = dict(auftrag)
    auftrag["zeit"] = time.time()
    if auftrag.get("rolle") not in ROLLEN_FUER_ARBEIT:
        auftrag["rolle"] = "stratege"
    if auftrag.get("form") not in FORMEN:
        auftrag["form"] = "text"
    db.ausfuehren("UPDATE vorgaenge SET auftrag=?, stand='in_arbeit', geaendert=? WHERE id=?",
                  (json.dumps(auftrag, ensure_ascii=False), time.time(), vid))
    db.ereignis(vid, "du", "auftrag", f"{rollen_name(auftrag['rolle'])} soll ausarbeiten: {auftrag.get('auftrag', '')}",
                {"form": auftrag["form"]})
    stand_berechnen(vid)


# ---------------------------------------------------------------- Entscheiden
def entscheiden(eid: str, antwort: str, text: str = "") -> dict[str, Any]:
    e = db.holen("entscheidungen", eid)
    if not e:
        return {"ok": False, "grund": "Entscheidung nicht gefunden"}
    if e["stand"] != "offen":
        return {"ok": False, "grund": "Schon entschieden"}
    vid = e.get("vorgang_id")
    daten = e.get("daten") or {}
    ergebnis: dict[str, Any] = {"ok": True}
    if antwort == "spaeter":
        db.ausfuehren("UPDATE entscheidungen SET erstellt=? WHERE id=?", (time.time(), eid))
        return {"ok": True, "spaeter": True}

    if e["art"] == "rueckfrage":
        if not text.strip() and antwort != "nein":
            return {"ok": False, "grund": "Zur Rückfrage fehlt die Antwort"}
        if antwort == "nein":
            text = text or "(nicht beantwortet, verworfen)"
        if vid:
            db.ereignis(vid, "du", "antwort", text)
            v = db.holen("vorgaenge", vid) or {}
            if v.get("auftrag"):
                a = json.loads(v["auftrag"])
                a["antworten"] = (a.get("antworten") or []) + [{"frage": e["frage"], "antwort": text}]
                db.ausfuehren("UPDATE vorgaenge SET auftrag=? WHERE id=?", (json.dumps(a, ensure_ascii=False), vid))
    elif antwort == "ja":
        if e["art"] == "projekt_neu":
            name = (text or daten.get("name") or "Neues Projekt").strip()[:80]
            pid = db.neue_id("p")
            db.anlegen("projekte", {"id": pid, "name": name, "farbe": "#6D4AE0", "status": "aktiv",
                                    "start": time.strftime("%Y-%m-%d"), "fruehere_namen": [],
                                    "sortierung": int(db.wert("SELECT COALESCE(MAX(sortierung),0)+1 FROM projekte") or 0),
                                    "erstellt": time.time(), "geaendert": time.time(), "quelle": "stab"},
                       wer="du", vorgang_id=vid)
            # Alle Vorgaenge mit demselben Vorschlag bekommen das Projekt -- samt Notiz und Aufgaben.
            alt_name = daten.get("name") or name
            for vv in db.alle("SELECT * FROM vorgaenge WHERE lower(projekt_vorschlag)=lower(?) AND projekt_id IS NULL", (alt_name,)):
                _projekt_zuordnen(vv, pid)
            ergebnis["projekt_id"] = pid
        elif e["art"] == "gedaechtnis":
            db.anlegen("gedaechtnis", {"id": db.neue_id("g"), "art": daten.get("art") or "begriff",
                                       "begriff": daten.get("begriff"), "bedeutung": text or daten.get("bedeutung"),
                                       "bestaetigt": 1, "quelle": vid or "vorschlag", "erstellt": time.time()},
                       wer="du", vorgang_id=vid)
        elif e["art"] == "ausarbeitung" and vid:
            a = dict(daten)
            if text:
                a["auftrag"] = (a.get("auftrag") or "") + " -- Veiko ergänzt: " + text
            auftrag_setzen(vid, a)
        elif e["art"] == "zuordnung" and vid:
            v = db.holen("vorgaenge", vid)
            if v:
                _projekt_zuordnen(v, daten.get("projekt_id"))
        elif e["art"] == "aufgabe":
            db.anlegen("aufgaben", {"id": db.neue_id("t"), "titel": text or daten.get("titel"),
                                    "projekt_id": daten.get("projekt_id"), "status": "offen", "prio": 2,
                                    "quelle": "stab", "vorgang_id": vid, "erstellt": time.time(),
                                    "geaendert": time.time()}, wer="du", vorgang_id=vid)

    db.ausfuehren("UPDATE entscheidungen SET stand=?, antwort=?, erledigt=? WHERE id=?",
                  ("ja" if antwort == "ja" or e["art"] == "rueckfrage" else "nein", text, time.time(), eid))
    if vid and e["art"] != "rueckfrage":
        db.ereignis(vid, "du", "entscheidung",
                    ("Ja" if antwort == "ja" else "Nein") + f" — {e['frage']}" + (f" ({text})" if text else ""))
    if vid:
        stand_berechnen(vid)
    return ergebnis


def _projekt_zuordnen(v: dict[str, Any], pid: str | None) -> None:
    if not pid:
        return
    db.aendern("vorgaenge", v["id"], {"projekt_id": pid}, wer="du", vorgang_id=v["id"], aktion="zugeordnet")
    if v.get("notiz_id"):
        db.aendern("notizen", v["notiz_id"], {"projekt_id": pid}, wer="du", vorgang_id=v["id"], aktion="zugeordnet")
    for a in db.alle("SELECT id FROM aufgaben WHERE vorgang_id=? AND projekt_id IS NULL", (v["id"],)):
        db.aendern("aufgaben", a["id"], {"projekt_id": pid}, wer="du", vorgang_id=v["id"], aktion="zugeordnet")


# ---------------------------------------------------------------- Stufe 3
def _html_zu_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>", " ", h)
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", htmlmod.unescape(h)).strip()


async def recherche(anfrage: str, seiten: int = 3) -> list[dict[str, str]]:
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 VvE-Cockpit"}) as c:
            r = await c.get(f"{SEARX}/search", params={"q": anfrage, "format": "json", "language": "de"})
            treffer = (r.json().get("results") or [])[:8]
            out = []
            for t in treffer:
                eintrag = {"titel": t.get("title") or "", "url": t.get("url") or "", "text": t.get("content") or ""}
                if len([o for o in out if o.get("voll")]) < seiten and eintrag["url"].startswith("http"):
                    try:
                        s = await c.get(eintrag["url"], timeout=8)
                        if "html" in s.headers.get("content-type", ""):
                            eintrag["text"] = _html_zu_text(s.text)[:3500]
                            eintrag["voll"] = "1"
                    except httpx.HTTPError:
                        pass
                out.append(eintrag)
            return out
    except (httpx.HTTPError, ValueError):
        return []


def _vorgang_kontext(v: dict[str, Any]) -> str:
    teile = []
    if v.get("notiz_id"):
        n = db.holen("notizen", v["notiz_id"])
        if n:
            teile.append(f"VEIKOS NOTIZ:\n{notiz_text(n, 5000)}")
    if v.get("projekt_id"):
        p = db.holen("projekte", v["projekt_id"]) or {}
        offen = db.alle("SELECT titel FROM aufgaben WHERE projekt_id=? AND status!='erledigt' LIMIT 15", (v["projekt_id"],))
        teile.append(f"PROJEKT: {p.get('name')}" + (f" -- Ziel: {p['ziel']}" if p.get("ziel") else "") +
                     ("\nOffene Aufgaben: " + "; ".join(a["titel"] for a in offen) if offen else ""))
    antworten = db.alle("SELECT text FROM ereignisse WHERE vorgang_id=? AND art='antwort'", (v["id"],))
    if antworten:
        teile.append("VEIKOS ANTWORTEN AUF RÜCKFRAGEN:\n" + "\n".join("- " + a["text"] for a in antworten))
    return "\n\n".join(teile)


PRUEF_SYSTEM = """Du bist Daniel, Red Team Lead in Veikos Stab. Du prüfst ein Arbeitsergebnis, bevor es Veiko sieht.
Antworte AUSSCHLIESSLICH mit JSON: {"urteil": "tragfaehig|nachbessern|rueckfrage", "begruendung": "zwei Sätze", "maengel": ["..."], "frage": "nur bei rueckfrage: die Frage an Veiko"}
Mängel sind: erfundene Fakten, Zahlen oder Namen ohne Quelle; Platzhalter wie [Name]; fremde Schriftzeichen; Auftrag verfehlt; unvollständig abgebrochen.
Kein Mangel: Angaben, die es nirgends gibt und die das Ergebnis offen als fehlend markiert.
Prüfe Fakten NUR gegen die mitgelieferten QUELLEN und die Notiz. Behaupte nichts aus eigenem Wissen: was in den Quellen steht, ist belegt; was dort nicht steht und trotzdem als Tatsache dasteht, ist ein Mangel.
Die Quellenliste mit Adressen hängt das Cockpit selbst an das Ergebnis an; fehlende Adressen im Text sind kein Mangel.
rueckfrage nur, wenn das Ergebnis ohne eine Auskunft von Veiko nicht sinnvoll werden kann."""


async def ausarbeiten(v: dict[str, Any]) -> None:
    a = json.loads(v.get("auftrag") or "{}")
    rid = a.get("rolle") or "stratege"
    form = a.get("form") or "text"
    r = rolle(rid)
    modell = await modell_fuer(rid, MODELL_ARBEIT)
    if not modell:
        raise llm.ModellFehler("Kein passendes lokales Modell installiert.")
    vid = v["id"]
    quellen: list[dict[str, str]] = []
    if a.get("recherche"):
        laeuft(rid, f"recherchiert: {a['recherche']}", vid)
        quellen = await recherche(a["recherche"])
        db.ereignis(vid, rid, "info", f"Recherche „{a['recherche']}“: {len(quellen)} Treffer.",
                    {"quellen": [{"titel": q["titel"], "url": q["url"]} for q in quellen]})
    quellen_text = "\n\n".join(f"[{i + 1}] {q['titel']} — {q['url']}\n{q['text'][:3000]}"
                               for i, q in enumerate(quellen))
    # Nur der Kern des Rollenauftrags: der volle Text (Clayton: "Zielbild,
    # Geschaeftsmodell, Wege") faerbte jede Arbeit -- eine Anbieterliste kam mit
    # vorangestelltem "Business-Check". Die Aufgabe bestimmt die Form, nicht die Rolle.
    system = (f"Du bist {r.get('name')}, {r.get('titel')} in Veiko von Eckerns KI-Team. {r.get('kurz') or ''}\n\n"
              "JETZT: deine konkrete Arbeitsaufgabe. Keine Vorrede, keine Lagebesprechung, keine Einordnung "
              "als Geschäftsmodell, keine Meta-Kommentare. Liefere direkt das fertige Ergebnis in der verlangten Form.\n"
              f"FORM: {FORM_ANWEISUNG[form]}\n"
              "REGELN: Schreibe Deutsch. Erfinde keine Fakten, Zahlen oder Namen. Stütze dich auf die Notiz, "
              "das Gedächtnis und die QUELLEN; zitiere Quellen als [1], [2]. Was fehlt, markierst du mit „fehlt:“ statt es zu raten. "
              "Keine Platzhalter in eckigen Klammern.\n\n"
              "Das GEDÄCHTNIS hilft dir nur, Namen und Begriffe im Auftrag richtig zu verstehen. Bring es NICHT von dir aus "
              "ins Ergebnis: was dort steht, gehört nur hinein, wenn der Auftrag es betrifft.\n\n"
              f"GEDÄCHTNIS:\n{gedaechtnis_text()}")
    frage = (f"AUFTRAG: {a.get('auftrag')}\n\n{_vorgang_kontext(v)}" +
             (f"\n\nQUELLEN:\n{quellen_text}" if quellen_text else "\n\n(keine Internetquellen)"))
    entwurf = ""
    pruefung: dict[str, Any] = {}
    for runde in range(2):
        laeuft(rid, ("überarbeitet" if runde else "arbeitet aus") + f" ({form})", vid)
        nachricht = frage
        if runde and pruefung:
            nachricht += ("\n\nDEIN ERSTER ENTWURF:\n" + entwurf[:9000] +
                          "\n\nKRITIK VON DANIEL:\n" + pruefung.get("begruendung", "") + "\n" +
                          "\n".join("- " + m for m in pruefung.get("maengel") or []) +
                          "\n\nÜberarbeite den Entwurf und behebe die Mängel. Liefere das vollständige Ergebnis.")
        entwurf = await llm.chat(modell, system, [{"role": "user", "content": nachricht}],
                                 temperatur=0.5, denken=False, num_ctx=32768)
        if llm.fremdschrift(entwurf):
            entwurf = await llm.chat(modell, system + "\n\nWICHTIG: Ausschließlich deutsche Sprache und lateinische Schrift.",
                                     [{"role": "user", "content": nachricht}], temperatur=0.3, denken=False, num_ctx=32768)
        if not entwurf.strip():
            raise llm.ModellFehler(f"{r.get('name')} hat nichts geliefert.")
        laeuft("kritiker", "prüft", vid)
        pruefung = await pruefen(entwurf, a, v, quellen_text)
        db.ereignis(vid, "kritiker", "pruefung", pruefung.get("begruendung", ""),
                    {"urteil": pruefung.get("urteil"), "maengel": pruefung.get("maengel") or [], "runde": runde + 1})
        if pruefung.get("urteil") != "nachbessern":
            break
    if llm.fremdschrift(entwurf):
        pruefung.setdefault("maengel", []).append("Enthält fremde Schriftzeichen.")
    ergebnis_speichern(v, a, entwurf, rid, modell, quellen, pruefung)
    _auftrag_erledigt(vid)
    if pruefung.get("urteil") == "rueckfrage" and pruefung.get("frage"):
        entscheidung_anlegen(vid, "rueckfrage", _kurz(pruefung["frage"], 400), {}, wer="kritiker")
    stand_berechnen(vid)


async def pruefen(entwurf: str, a: dict[str, Any], v: dict[str, Any], quellen_text: str = "") -> dict[str, Any]:
    modell = await modell_fuer("kritiker", MODELL_ARBEIT)
    if not modell:
        return {"urteil": "ungeprueft", "begruendung": "Kein Modell für die Prüfung installiert."}
    # Daniel bekommt DIESELBEN Quellen wie der Bearbeiter. Ohne sie pruefte er
    # aus eigenem Gedaechtnis -- und das kann genauso daneben liegen.
    frage = (f"AUFTRAG: {a.get('auftrag')}\nFORM: {a.get('form')}\n\n{_vorgang_kontext(v)[:4000]}\n\n"
             + (f"QUELLEN, die der Bearbeiter hatte:\n{quellen_text[:12000]}\n\n" if quellen_text else
                "(Der Bearbeiter hatte keine Internetquellen.)\n\n")
             + f"ERGEBNIS:\n{entwurf[:9000]}")
    for _ in range(2):
        antwort = await llm.chat(modell, PRUEF_SYSTEM, [{"role": "user", "content": frage}],
                                 json_format=True, temperatur=0.2, denken=False, num_ctx=24576)
        d = llm.json_aus(antwort)
        if isinstance(d, dict) and d.get("urteil") in ("tragfaehig", "nachbessern", "rueckfrage"):
            d["maengel"] = [str(m)[:200] for m in (d.get("maengel") or [])][:6]
            d["begruendung"] = _kurz(d.get("begruendung"), 500)
            d["modell"] = modell
            return d
    # Eine unlesbare Pruefung ist KEINE Zustimmung (Lehre vom 30.09.).
    return {"urteil": "ungeprueft", "begruendung": "Die Prüfung hat keine lesbare Antwort geliefert.", "maengel": []}


def _folien_html(text: str, titel: str) -> str:
    folien = [f.strip() for f in re.split(r"(?m)^---\s*$", text) if f.strip()]
    teile = []
    for f in folien:
        zeilen = f.splitlines()
        kopf = next((z.lstrip("# ").strip() for z in zeilen if z.startswith("#")), "")
        punkte = [z.lstrip("-*• ").strip() for z in zeilen if z.strip().startswith(("-", "*", "•"))]
        rest = [z for z in zeilen if z.strip() and not z.startswith("#") and not z.strip().startswith(("-", "*", "•"))]
        teile.append("<section><h2>" + htmlmod.escape(kopf) + "</h2>" +
                     ("<ul>" + "".join(f"<li>{htmlmod.escape(p)}</li>" for p in punkte) + "</ul>" if punkte else "") +
                     "".join(f"<p>{htmlmod.escape(z)}</p>" for z in rest[:4]) + "</section>")
    return ("<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>{htmlmod.escape(titel)}</title><style>body{{margin:0;font:18px system-ui;background:#EEF1F5;color:#0B1826}}"
            "section{background:#fff;max-width:900px;aspect-ratio:16/9;margin:24px auto;padding:48px 56px;box-sizing:border-box;"
            "border-radius:12px;box-shadow:0 4px 18px rgba(12,26,46,.1);overflow:auto}h2{font-size:34px;margin:0 0 20px;color:#2C6BB3}"
            "li{margin:10px 0}</style>" + "".join(teile))


def ergebnis_speichern(v: dict[str, Any], a: dict[str, Any], text: str, rid: str, modell: str,
                       quellen: list[dict[str, str]], pruefung: dict[str, Any]) -> str:
    eid = db.neue_id("r")
    form = a.get("form") or "text"
    if quellen and form not in ("webseite",):
        # Das Ergebnis traegt seine Quellen selbst -- auch wenn es kopiert oder gemailt wird.
        text = text.rstrip() + "\n\n**Quellen**\n" + "\n".join(
            f"{i + 1}. [{(q.get('titel') or q.get('url'))[:90]}]({q.get('url')})" for i, q in enumerate(quellen))
    titel = _kurz(a.get("auftrag"), 90) or v.get("titel") or "Ergebnis"
    ansicht = 0
    if form == "webseite":
        m = re.search(r"```html\s*(.*?)```", text, re.S | re.I)
        if m:
            (ERGEBNIS_DIR / f"{eid}.html").write_text(m.group(1), encoding="utf-8")
            ansicht = 1
    elif form == "praesentation":
        (ERGEBNIS_DIR / f"{eid}.html").write_text(_folien_html(text, titel), encoding="utf-8")
        ansicht = 1
    elif form == "dokument":
        from . import dokumente
        (ERGEBNIS_DIR / f"{eid}.html").write_text(dokumente.zu_html(titel, text), encoding="utf-8")
        ansicht = 1
    db.anlegen("ergebnisse", {
        "id": eid, "vorgang_id": v["id"], "projekt_id": v.get("projekt_id"), "titel": titel, "form": form,
        "inhalt": text, "rolle": rid, "modell": modell,
        "quellen": [{"titel": q["titel"], "url": q["url"]} for q in quellen],
        "pruefung": pruefung, "ansicht": ansicht, "erstellt": time.time(),
    }, wer=rid, vorgang_id=v["id"])
    db.ereignis(v["id"], rid, "ergebnis", text[:600] + ("…" if len(text) > 600 else ""),
                {"ergebnis_id": eid, "form": form, "urteil": pruefung.get("urteil")})
    return eid


# ---------------------------------------------------------------- Schleife
async def durchgang() -> dict[str, Any]:
    if _lock.locked():
        return {"ok": False, "grund": "läuft schon"}
    async with _lock:
        bericht = {"plaud_neu": 0, "eingeordnet": 0, "ausgearbeitet": 0, "fehler": []}
        try:
            bericht["plaud_neu"] = plaud_scannen()
        except Exception as e:  # noqa: BLE001 -- ein kaputter Abruf darf den Rest nicht stoppen
            bericht["fehler"].append(f"Plaud: {e}")
        for v in db.alle("SELECT * FROM vorgaenge WHERE stand='neu' AND versuche<3 ORDER BY erstellt LIMIT 4"):
            try:
                await einordnen(v)
                bericht["eingeordnet"] += 1
            except Exception as e:  # noqa: BLE001
                db.ausfuehren("UPDATE vorgaenge SET versuche=versuche+1 WHERE id=?", (v["id"],))
                db.ereignis(v["id"], "system", "fehler", f"Einordnen gescheitert: {e}")
                bericht["fehler"].append(str(e))
            finally:
                laeuft(None)
        offene = [v for v in db.alle("SELECT * FROM vorgaenge WHERE stand IN ('in_arbeit','wartet') AND auftrag IS NOT NULL "
                                     "AND versuche<3 ORDER BY geaendert") if auftrag_offen(v)]
        for v in offene[:1]:
            try:
                await ausarbeiten(v)
                bericht["ausgearbeitet"] += 1
            except Exception as e:  # noqa: BLE001
                db.ausfuehren("UPDATE vorgaenge SET versuche=versuche+1 WHERE id=?", (v["id"],))
                db.ereignis(v["id"], "system", "fehler", f"Ausarbeitung gescheitert: {e}")
                bericht["fehler"].append(str(e))
                traceback.print_exc()
            finally:
                laeuft(None)
        ZUSTAND["letzter_lauf"] = time.time()
        ZUSTAND["durchgaenge"] += 1
        ZUSTAND["letzter_fehler"] = bericht["fehler"][-1] if bericht["fehler"] else None
        return bericht


_weck = asyncio.Event()


def wecken() -> None:
    """Nach Erfassen oder einem Auftrag nicht bis zum naechsten Takt warten."""
    _weck.set()


async def schleife() -> None:
    await asyncio.sleep(5)
    while True:
        try:
            await durchgang()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        _weck.clear()
        try:
            await asyncio.wait_for(_weck.wait(), timeout=STAB_TAKT_SEK)
        except asyncio.TimeoutError:
            pass


_ges_cache: dict[str, Any] = {"zeit": 0.0, "letzte": None}


def _letzte_plaud_ankunft() -> float | None:
    # index.json zaehlt NICHT -- der Abruf schreibt sie jede Minute neu, auch
    # wenn keine Notiz kam. Sie mitzuzaehlen hiesse, einen Stillstand als
    # "gerade eben" zu melden (genau der Fehler von September).
    if time.time() - _ges_cache["zeit"] < 60:
        return _ges_cache["letzte"]
    letzte = None
    if PLAUD_DIR.is_dir():
        for f in PLAUD_DIR.glob("*.json"):
            if f.name == "index.json":
                continue
            m = f.stat().st_mtime
            if letzte is None or m > letzte:
                letzte = m
    _ges_cache.update(zeit=time.time(), letzte=letzte)
    return letzte


def gesundheit() -> dict[str, Any]:
    """Unterscheidet 'keine neue Notiz' von 'Abruf gescheitert' (Befund B4)."""
    letzter_abruf = _letzte_plaud_ankunft()
    letzte_notiz = letzter_abruf
    sync = None
    try:
        sync = json.loads((PLAUD_DIR / "index.json").read_text(encoding="utf-8")).get("synced")
    except (OSError, ValueError):
        pass
    return {"letzte_notiz": letzte_notiz, "letzte_datei": letzter_abruf, "sync": sync,
            "stab_aktiv": stab_aktiv(), "letzter_lauf": ZUSTAND["letzter_lauf"],
            "laeuft": ZUSTAND["laeuft"], "letzter_fehler": ZUSTAND["letzter_fehler"]}
