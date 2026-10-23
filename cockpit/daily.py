"""
DAILY TASKS -- was das Team jeden Tag von selbst untersucht und als Briefing liefert.

Veiko (22.10.2026): "Fuer das Team taegliche Aufgaben anlegen koennen -- irgendetwas, was sie
taeglich untersuchen sollen, wo sie mir dann ein Briefing geben, in Bezug auf den Daily Task.
Und eine komplette sprachliche Interaktion: Fragen stellen, Sachen tiefer untersuchen und gleich
weiter bearbeiten."

Kein eigener Arbeitsweg: ein Daily Task ist ein AUFTRAG MIT ZEITPLAN. Zur Uhrzeit legt die
Schleife einen Vorgang mit Auftrag an (quelle "daily"), und die gewoehnliche Pipeline arbeitet
ihn ab (stab.ausarbeiten): Recherche mit frischen Quellen (zeitraum "week"), die Rolle schreibt,
Daniel prueft, das Briefing ist ein Ergebnis wie jedes andere -- mit Vorschau, Chat, Word,
"Abschliessend pruefen", Ueberblick. Was es nur hier gibt:
  - die feste Form des Briefings (Bewertung, Das Wichtigste, Neu seit dem letzten Briefing,
    Empfehlung) und das VORIGE Briefing im Auftrag -- sonst meldet das Team jeden Tag dasselbe;
  - kurz statt gegliedert (auftrag["kurz"]): ein Tagesbriefing ist eine Seite, kein Konzept;
  - der Verlauf je Daily Task (alle Briefings, ueber auftrag.daily_id).
"""
from __future__ import annotations

import asyncio
import datetime
import json
import re
import time
import traceback
from typing import Any

from . import db, stab

TAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
BEWERTUNG_RE = re.compile(r"^\s*\**\s*Bewertung\s*:?\**\s*:?\s*\**\s*(ruhig|beachtenswert|wichtig)", re.I | re.M)
ROLLEN = ("stratege", "buch", "designer", "video", "cockpit", "pmo")

# Vorlagen fuers Anlegen -- Ideen, keine Pflicht. Was Veiko daraus macht, entscheidet er.
VORLAGEN = [
    {"titel": "KI im Personalwesen", "rolle": "stratege",
     "auftrag": "Was gibt es Neues zu KI im Personalwesen und in der HR-Transformation: Studien, Produkte, Regulierung (EU AI Act), "
                "Beispiele großer Unternehmen. Was davon ist für mich als Head of Corporate HR Transformation bei Krones relevant?"},
    {"titel": "Wettbewerb und Branche", "rolle": "stratege",
     "auftrag": "Meldungen zu Krones und den Wettbewerbern im Maschinen- und Anlagenbau für Getränke und Verpackung "
                "(z. B. KHS, Sidel, Tetra Pak): Aufträge, Personalthemen, Standorte, Strategie."},
    {"titel": "Neue KI-Modelle für mein Cockpit", "rolle": "cockpit",
     "auftrag": "Welche neuen offenen KI-Modelle (Ollama, Hugging Face) sind erschienen, die auf zwei RTX 3090 laufen und für "
                "deutsche Texte, Analyse oder Programmieren besser sein könnten als die, die ich nutze?"},
    {"titel": "Mein Buch: Debatte KI und Arbeit", "rolle": "buch",
     "auftrag": "Neue Beiträge, Studien und Stimmen zur Debatte über KI, Arbeit und Ökonomie (Abundance, Kasy, Diamandis), "
                "die für mein Buch „KI & Menschen“ eine gute Szene, ein Zitat oder ein Argument hergeben."},
]


def _tage(t: Any) -> list[int]:
    if isinstance(t, list):
        return [int(x) for x in t if str(x).isdigit() and 0 <= int(x) <= 6]
    try:
        return _tage(json.loads(t or "[]"))
    except (ValueError, TypeError):
        return [0, 1, 2, 3, 4]


def tage_aus_text(t: Any) -> list[int]:
    """'werktags', 'täglich', 'mo, mi, fr', [0,2,4] -> Wochentage (0 = Montag)."""
    if isinstance(t, list):
        return _tage(t)
    s = str(t or "").lower()
    if not s or re.search(r"werktag|wochentag|mo.{0,3}(bis|-|–).{0,3}fr", s):
        return [0, 1, 2, 3, 4]
    if re.search(r"täglich|taeglich|jeden tag|alle tage|immer", s):
        return list(range(7))
    if re.search(r"wochenende", s):
        return [5, 6]
    tage = [i for i, k in enumerate(["mo", "di", "mi", "do", "fr", "sa", "so"]) if re.search(rf"\b{k}", s)]
    return tage or [0, 1, 2, 3, 4]


def zeitplan_text(d: dict[str, Any]) -> str:
    t = _tage(d.get("tage"))
    wann = "täglich" if len(t) == 7 else "werktags" if t == [0, 1, 2, 3, 4] else ", ".join(TAGE[i] for i in t) or "nie"
    return f"{wann} um {d.get('uhrzeit') or '04:00'} Uhr"


def _uhrzeit(u: Any) -> str:
    m = re.match(r"^\s*(\d{1,2})(?:[:.](\d{2}))?", str(u or ""))
    if not m or int(m.group(1)) > 23:
        return "04:00"
    return f"{int(m.group(1)):02d}:{int(m.group(2) or 0):02d}"


# ---------------------------------------------------------------- Bestand
def holen(did: str) -> dict[str, Any] | None:
    d = db.holen("daily", did)
    if d:
        d["tage"] = _tage(d.get("tage"))
    return d


def verlauf(did: str, grenze: int = 30) -> list[dict[str, Any]]:
    zeilen = db.alle("SELECT r.id, r.titel, r.erstellt, r.pruefung, substr(r.inhalt,1,600) AS anfang, r.vorgang_id FROM ergebnisse r "
                     "JOIN vorgaenge v ON v.id=r.vorgang_id WHERE json_extract(v.auftrag,'$.daily_id')=? "
                     "ORDER BY r.erstellt DESC LIMIT ?", (did, grenze))
    for z in zeilen:
        m = BEWERTUNG_RE.search(z.get("anfang") or "")
        z["bewertung"] = m.group(1).lower() if m else None
        z.pop("anfang", None)
    return zeilen


def laeuft(did: str) -> dict[str, Any] | None:
    v = db.eine("SELECT id, titel, stand, versuche FROM vorgaenge WHERE quelle='daily' AND json_extract(auftrag,'$.daily_id')=? "
                "AND stand IN ('neu','in_arbeit','eingeordnet') ORDER BY erstellt DESC LIMIT 1", (did,))
    if v and stab.ZUSTAND.get("laeuft") and (stab.ZUSTAND["laeuft"] or {}).get("vorgang_id") == v["id"]:
        v["was"] = stab.ZUSTAND["laeuft"].get("was")
    return v


def liste() -> list[dict[str, Any]]:
    aus = []
    for d in db.alle("SELECT * FROM daily ORDER BY sortierung, erstellt"):
        d["tage"] = _tage(d.get("tage"))
        d["zeitplan"] = zeitplan_text(d)
        d["rolle_name"] = stab.rollen_name(d.get("rolle"))
        d["projekt_name"] = (db.holen("projekte", d.get("projekt_id") or "") or {}).get("name")
        v = verlauf(d["id"], 1)
        d["letztes"] = v[0] if v else None
        d["laeuft"] = laeuft(d["id"])
        d["naechster"] = naechster_lauf(d)
        aus.append(d)
    return aus


def anlegen(werte: dict[str, Any], wer: str = "du") -> dict[str, Any]:
    titel = stab._kurz(werte.get("titel"), 80)
    auftrag = str(werte.get("auftrag") or "").strip()[:3000]
    if not titel or not auftrag:
        raise ValueError("Ein Daily Task braucht einen Titel und einen Auftrag (was täglich untersucht werden soll).")
    did = db.neue_id("d")
    db.anlegen("daily", {"id": did, "titel": titel, "auftrag": auftrag,
                         "rolle": werte.get("rolle") if werte.get("rolle") in ROLLEN else "stratege",
                         "projekt_id": stab.projekt_finden(werte.get("projekt_id")) if werte.get("projekt_id") else None,
                         "uhrzeit": _uhrzeit(werte.get("uhrzeit")), "tage": json.dumps(tage_aus_text(werte.get("tage"))),
                         "netz": 0 if werte.get("netz") is False else 1, "aktiv": 1,
                         "sortierung": int(db.wert("SELECT COALESCE(MAX(sortierung),0)+1 FROM daily") or 1),
                         "erstellt": time.time(), "geaendert": time.time()}, wer=wer)
    return holen(did) or {}


def aendern(did: str, werte: dict[str, Any], wer: str = "du") -> dict[str, Any]:
    d = holen(did)
    if not d:
        raise ValueError("Diesen Daily Task gibt es nicht.")
    neu: dict[str, Any] = {}
    if werte.get("titel"):
        neu["titel"] = stab._kurz(werte["titel"], 80)
    if werte.get("auftrag"):
        neu["auftrag"] = str(werte["auftrag"]).strip()[:3000]
    if werte.get("rolle") in ROLLEN:
        neu["rolle"] = werte["rolle"]
    if "projekt_id" in werte:
        neu["projekt_id"] = stab.projekt_finden(werte["projekt_id"]) if werte["projekt_id"] else None
    if werte.get("uhrzeit"):
        neu["uhrzeit"] = _uhrzeit(werte["uhrzeit"])
    if werte.get("tage") not in (None, ""):
        neu["tage"] = json.dumps(tage_aus_text(werte["tage"]))
    if "netz" in werte:
        neu["netz"] = 1 if werte["netz"] else 0
    if "aktiv" in werte:
        neu["aktiv"] = 1 if werte["aktiv"] else 0
    if neu:
        neu["geaendert"] = time.time()
        db.aendern("daily", did, neu, wer=wer)
    return holen(did) or {}


def loeschen(did: str, wer: str = "du") -> None:
    """Der Daily Task geht (zuruecknehmbar ueber das Protokoll); seine Briefings bleiben Ergebnisse."""
    if not db.loeschen("daily", did, wer=wer):
        raise ValueError("Diesen Daily Task gibt es nicht.")


# ---------------------------------------------------------------- Lauf
def _jetzt() -> datetime.datetime:
    from zoneinfo import ZoneInfo
    return datetime.datetime.now(ZoneInfo("Europe/Berlin"))


def naechster_lauf(d: dict[str, Any]) -> float | None:
    if not d.get("aktiv"):
        return None
    tage = _tage(d.get("tage"))
    if not tage:
        return None
    jetzt = _jetzt()
    h, m = map(int, _uhrzeit(d.get("uhrzeit")).split(":"))
    for plus in range(0, 8):
        tag = jetzt + datetime.timedelta(days=plus)
        zeit = tag.replace(hour=h, minute=m, second=0, microsecond=0)
        if tag.weekday() in tage and zeit > jetzt and not (plus == 0 and d.get("letzter_tag") == jetzt.strftime("%Y-%m-%d")):
            return zeit.timestamp()
    return None


def faellig(d: dict[str, Any], jetzt: datetime.datetime | None = None) -> bool:
    jetzt = jetzt or _jetzt()
    if not d.get("aktiv") or jetzt.weekday() not in _tage(d.get("tage")):
        return False
    if d.get("letzter_tag") == jetzt.strftime("%Y-%m-%d"):
        return False
    return jetzt.strftime("%H:%M") >= _uhrzeit(d.get("uhrzeit"))


def auftrag_text(d: dict[str, Any], heute: str) -> str:
    vorher = verlauf(d["id"], 1)
    voriges = ""
    if vorher:
        e = db.holen("ergebnisse", vorher[0]["id"]) or {}
        ohne_quellen = re.sub(r"(?s)\*\*Quellen\*\*.*$", "", e.get("inhalt") or "")[:4000]
        voriges = (f"\n\nDAS VORIGE BRIEFING vom {time.strftime('%d.%m.%Y', time.localtime(e.get('erstellt') or 0))} -- "
                   "„Neu seit dem letzten Briefing“ bezieht sich darauf; wiederhole nichts, was dort schon stand, "
                   f"außer es hat sich verändert:\n{ohne_quellen}")
    return (f"TÄGLICHES BRIEFING „{d['titel']}“ für Veiko, {heute}.\n"
            f"WAS JEDEN TAG ZU UNTERSUCHEN IST: {d['auftrag']}\n\n"
            "Liefere ein KURZES Briefing (höchstens eine Seite) in genau diesem Aufbau:\n"
            "Erste Zeile: „Bewertung: ruhig“, „Bewertung: beachtenswert“ oder „Bewertung: wichtig“ -- ob heute etwas Veikos "
            "Aufmerksamkeit braucht.\n"
            "## Das Wichtigste heute\ndrei bis fünf Punkte, je ein bis zwei Sätze, mit Verweis auf die Quelle und dem Datum der Meldung.\n"
            "## Neu seit dem letzten Briefing\nwas sich verändert hat; gibt es nichts Neues, sag das in einem Satz.\n"
            "## Was ich empfehle\nein bis drei konkrete nächste Schritte für Veiko.\n"
            "Nur, was in den Quellen steht. Ältere Meldungen nur, wenn sie für heute wichtig sind -- dann mit Datum."
            + voriges)


def ausfuehren(did: str, von_hand: bool = False) -> dict[str, Any]:
    d = holen(did)
    if not d:
        raise ValueError("Diesen Daily Task gibt es nicht.")
    if laeuft(did):
        raise ValueError("Das Briefing wird gerade erarbeitet.")
    jetzt = _jetzt()
    heute = jetzt.strftime("%d.%m.%Y")
    text = auftrag_text(d, heute)
    v = stab.aus_text(text, quelle="daily", projekt_id=d.get("projekt_id"), titel=f"Daily: {d['titel']} – {jetzt.strftime('%d.%m.')}")
    stab.auftrag_setzen(v["id"], {"rolle": d.get("rolle") or "stratege", "form": "text", "auftrag": text,
                                  "titel": f"Daily: {d['titel']} – {jetzt.strftime('%d.%m.')}",
                                  "recherche": d["titel"] if d.get("netz") else None,
                                  "daily_id": did, "kurz": True, "zeitraum": "week" if d.get("netz") else None,
                                  "ohne_netz": not d.get("netz")})
    db.ausfuehren("UPDATE daily SET letzter_tag=?, letzter_lauf=? WHERE id=?", (jetzt.strftime("%Y-%m-%d"), time.time(), did))
    db.ereignis(v["id"], "du" if von_hand else "system", "info",
                f"Daily Task „{d['titel']}“ {'von Hand gestartet' if von_hand else 'zur geplanten Zeit gestartet'}.")
    stab.wecken()
    return {"ok": True, "vorgang_id": v["id"]}


async def schleife() -> None:
    """Alle fuenf Minuten: was heute faellig ist und noch nicht lief, geht an die Pipeline.
    Ein verpasster Termin (Server aus) holt sich am selben Tag nach -- am naechsten Tag nicht mehr,
    ein Briefing von gestern braucht morgens niemand."""
    await asyncio.sleep(45)
    while True:
        try:
            jetzt = _jetzt()
            for d in db.alle("SELECT * FROM daily WHERE aktiv=1"):
                if faellig(d, jetzt) and not laeuft(d["id"]):
                    ausfuehren(d["id"])
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(300)


# ---------------------------------------------------------------- Talk
def heute_text() -> str:
    """Fuer die Lage in Talk: die Briefings von heute in einer Zeile je Daily Task."""
    beginn = _jetzt().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    zeilen = []
    for d in liste():
        l = d.get("letztes")
        if l and (l.get("erstellt") or 0) >= beginn:
            zeilen.append(f"- {d['titel']} ({d['id']}): Bewertung {l.get('bewertung') or 'unbekannt'}, Briefing {l['id']}")
        elif d.get("laeuft"):
            zeilen.append(f"- {d['titel']} ({d['id']}): wird gerade erarbeitet")
    return "\n".join(zeilen)


def kontext_text(did: str | None) -> str:
    if did:
        d = holen(did)
        if d:
            v = verlauf(did, 4)
            teile = [f"VEIKO SCHAUT AUF DEN DAILY TASK „{d['titel']}“ (id {did}): {zeitplan_text(d)}, bearbeitet von "
                     f"{stab.rollen_name(d.get('rolle'))}{'' if d.get('aktiv') else ', PAUSIERT'}. Auftrag: {d['auftrag']}"]
            if v:
                e = db.holen("ergebnisse", v[0]["id"]) or {}
                teile.append(f"DAS NEUESTE BRIEFING (Ergebnis {e.get('id')}, {time.strftime('%d.%m. %H:%M', time.localtime(e.get('erstellt') or 0))}) "
                             f"-- „das Briefing“, „daraus“, „Punkt zwei“ meint dieses:\n{(e.get('inhalt') or '')[:12000]}")
                if len(v) > 1:
                    teile.append("FRÜHERE BRIEFINGS: " + "; ".join(
                        f"{time.strftime('%d.%m.', time.localtime(x['erstellt']))} ({x.get('bewertung') or '?'}, {x['id']})" for x in v[1:]))
                teile.append("Will Veiko etwas TIEFER untersucht haben, ist das eine ausarbeiten-Aktion mit ergebnis_id dieses Briefings "
                             f"und projekt_id {d.get('projekt_id') or 'null'}; die Rolle ist {d.get('rolle')}.")
            else:
                teile.append("Es gibt noch kein Briefing -- „führ ihn jetzt aus“ startet das erste.")
            return "\n\n".join(teile)
    zeilen = [f"- {d['titel']} (id {d['id']}): {d['zeitplan']}, {d['rolle_name']}{'' if d.get('aktiv') else ', pausiert'}; "
              + (f"letztes Briefing {time.strftime('%d.%m.', time.localtime(d['letztes']['erstellt']))}, Bewertung "
                 f"{d['letztes'].get('bewertung') or '?'} (Ergebnis {d['letztes']['id']})" if d.get("letztes") else "noch kein Briefing")
              for d in liste()]
    return ("VEIKO IST AUF DER SEITE DAILY TASKS -- tägliche Aufträge, aus denen jeden Tag ein Briefing entsteht.\n"
            + ("\n".join(zeilen) if zeilen else "Noch kein Daily Task angelegt."))
