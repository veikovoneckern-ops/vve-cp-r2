"""
UEBERNAHME AUS DEM ALTEN COCKPIT -- nur lesend, nur hinzufuegend.

Waehrend beide Fassungen parallel laufen, gilt: der alte Stand wird nie
geschrieben. Die neue Fassung holt sich beim ersten Start alles, was sie
braucht, und kann das jederzeit wiederholen ("Neu abgleichen"). Dabei kommt
nur dazu, was es hier noch NICHT gibt -- eine Aenderung, die du in der
neuen Fassung gemacht hast, wird nie von einem alten Wert ueberschrieben.

Die Plaud-Ablage wird nicht kopiert, sondern laufend gelesen (stab.py).
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from . import db
from .konfig import ALT_ROLLEN, ALT_STATE, ALT_VORGAENGE, PLAUD_DIR

KATALOG_DATEI = Path(__file__).with_name("team_rollen.json")

STATUS_ALT = {"erledigt": "erledigt", "wartet": "wartet", "neu": "offen", "offen": "offen",
              "in_arbeit": "offen", "laeuft": "offen"}
STAND_ALT = {"uebernommen": "erledigt", "geschlossen": "verworfen", "abgelegt": "verworfen",
             "fertig": "fertig", "rueckfrage": "fertig"}


def _lesen(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _datum_ts(s: Any) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:19]).timestamp()
    except ValueError:
        return None


def katalog() -> list[dict[str, Any]]:
    """Rollenkatalog: der ausgelieferte des alten Cockpits, sonst die Kopie hier."""
    d = _lesen(ALT_ROLLEN) or _lesen(KATALOG_DATEI) or {}
    return d.get("rollen") or []


def team_einrichten(state: dict[str, Any] | None) -> int:
    alt_team = {m.get("rolleId"): m for m in ((state or {}).get("team") or [])}
    n = 0
    for i, r in enumerate(katalog()):
        if db.holen("team", r["id"]):
            continue
        m = alt_team.get(r["id"]) or {}
        db.einfuegen("team", {
            "id": r["id"], "name": r.get("name"), "titel": r.get("titel"), "kurz": r.get("kurz"),
            "auftrag": r.get("auftrag") or "", "modell": m.get("modell") or r.get("vorgabeModell") or "",
            "aktiv": 0 if m.get("aktiv") is False else 1, "art": r.get("aufgabeArt") or "",
            "reihenfolge": i,
        })
        n += 1
    return n


def abgleichen() -> dict[str, int]:
    zaehler = {"projekte": 0, "aufgaben": 0, "notizen": 0, "plaud": 0, "vorgaenge": 0, "team": 0}
    state = _lesen(ALT_STATE) or {}
    zaehler["team"] = team_einrichten(state)

    for i, p in enumerate(state.get("projects") or []):
        if not p.get("id") or db.holen("projekte", p["id"]):
            continue
        db.einfuegen("projekte", {
            "id": p["id"], "name": p.get("name") or "Ohne Namen", "farbe": p.get("color") or "#2C6BB3",
            "status": p.get("status") or "aktiv", "start": p.get("start") or "", "ende": p.get("end") or "",
            "ziel": p.get("goal") or "", "eltern_id": p.get("parentId"), "leitung": p.get("teamLeadId"),
            "fruehere_namen": p.get("fruehereNamen") or [], "sortierung": i,
            "erstellt": _datum_ts(p.get("start")) or time.time(), "geaendert": time.time(), "quelle": "alt",
        })
        zaehler["projekte"] += 1

    for t in state.get("todos") or []:
        if not t.get("id") or db.holen("aufgaben", t["id"]):
            continue
        try:
            prio = int(t.get("prio") or 2)
        except (TypeError, ValueError):
            prio = 2
        db.einfuegen("aufgaben", {
            "id": t["id"], "titel": t.get("title") or "Ohne Titel", "projekt_id": t.get("projectId"),
            "status": STATUS_ALT.get(str(t.get("status")), "offen"), "prio": prio,
            "faellig": t.get("due") or "", "notiz": t.get("notes") or "",
            "quelle": "stab" if t.get("vomTeam") else "du", "notiz_id": t.get("noteId"),
            "erstellt": _datum_ts(t.get("created")) or time.time(),
            "geaendert": _datum_ts(t.get("updated")) or time.time(),
            "archiviert": 1 if t.get("archived") else 0,
            "eltern_id": t.get("parentId"), "start": t.get("start") or None,
        })
        zaehler["aufgaben"] += 1

    # Einmalig: Unteraufgaben und Beginn fuer Aufgaben, die vor dem 01.10.2026
    # (als es die Spalten noch nicht gab) uebernommen wurden. Nur einmal, damit
    # ein spaeter hier geloester Ast nicht beim naechsten Abgleich zurueckkommt.
    if not db.einstellung("struktur_nachgezogen"):
        for t in state.get("todos") or []:
            if t.get("id") and (t.get("parentId") or t.get("start")):
                db.ausfuehren("UPDATE aufgaben SET eltern_id=COALESCE(eltern_id, ?), start=COALESCE(start, ?) WHERE id=?",
                              (t.get("parentId"), t.get("start") or None, t["id"]))
        db.einstellung_setzen("struktur_nachgezogen", time.time())

    bekannte_plaud: set[str] = set()
    for n in state.get("notes") or []:
        if not n.get("id"):
            continue
        plaud_id = n.get("driveId") if str(n.get("source", "")).lower() == "plaud" else None
        if plaud_id:
            bekannte_plaud.add(plaud_id)
        if db.holen("notizen", n["id"]):
            continue
        db.einfuegen("notizen", {
            "id": n["id"], "titel": n.get("title") or "", "datum": n.get("date") or "",
            "text": n.get("transcript") or n.get("original") or n.get("summary") or "",
            "kurz": n.get("kurz") or n.get("summary") or "",
            "quelle": "plaud" if plaud_id else "eingabe", "projekt_id": n.get("projectId"),
            "plaud_id": plaud_id,
            "erstellt": _datum_ts(n.get("date")) or _datum_ts(n.get("importedAt")) or ALT_STATE.stat().st_mtime,
        })
        zaehler["notizen"] += 1

    # Plaud-Notizen, die das alte Cockpit nie uebernommen hat: als Notiz ohne
    # Projekt. Einen Vorgang bekommen sie NICHT -- sonst arbeitet der Stab
    # monatealten Rueckstand ab (dieselbe Ueberlegung wie MAX_ALTER_TAGE alt).
    if PLAUD_DIR.is_dir():
        for f in PLAUD_DIR.glob("*.json"):
            pid = f.stem
            if pid in bekannte_plaud or db.wert("SELECT 1 FROM notizen WHERE plaud_id=?", (pid,)):
                continue
            d = _lesen(f) or {}
            if not d:
                continue
            db.einfuegen("notizen", {
                "id": "pl" + pid[:12], "titel": d.get("name") or "", "datum": str(d.get("created_at") or "")[:10],
                "text": d.get("transcript") or "", "kurz": d.get("summary") or "", "quelle": "plaud",
                "projekt_id": None, "plaud_id": pid,
                "erstellt": float(d.get("created_ts") or d.get("fetched") or f.stat().st_mtime),
            })
            zaehler["plaud"] += 1

    for v in _lesen(ALT_VORGAENGE) or []:
        vid = "alt" + str(v.get("id", ""))[-10:]
        if not v.get("id") or db.holen("vorgaenge", vid):
            continue
        notiz_id = v.get("notizId")
        if notiz_id and not db.holen("notizen", notiz_id):
            alt_n = db.eine("SELECT id FROM notizen WHERE plaud_id=?", (notiz_id,))
            notiz_id = alt_n["id"] if alt_n else None
        erstellt = float(v.get("erstellt") or time.time())
        db.einfuegen("vorgaenge", {
            "id": vid, "titel": v.get("titel") or "Vorgang", "stand": STAND_ALT.get(v.get("stand"), "fertig"),
            "notiz_id": notiz_id, "projekt_id": v.get("projektId"), "projekt_vorschlag": v.get("projektVorschlag"),
            "einordnung": v.get("einordnung") or "", "quelle": "alt", "erstellt": erstellt,
            "geaendert": float(v.get("geaendert") or erstellt), "alt_id": v.get("id"),
        })
        db.ereignis(vid, "system", "info", "Aus dem alten Cockpit übernommen. Bearbeitet hat ihn die alte Pipeline.")
        for t in v.get("todos") or []:
            titel = t if isinstance(t, str) else (t or {}).get("titel")
            if titel:
                db.ereignis(vid, "pmo", "aufgabe", titel)
        for a in v.get("aufgaben") or []:
            txt = a.get("ergebnisText") or a.get("ergebnis") or ""
            if txt:
                db.ereignis(vid, a.get("rolle") or "stab", "ergebnis", txt[:6000], {"titel": a.get("titel")})
        pr = v.get("pruefung") or {}
        if pr.get("urteil"):
            db.ereignis(vid, "kritiker", "pruefung", pr.get("begruendung") or pr.get("text") or "",
                        {"urteil": pr.get("urteil")})
        if v.get("geschlossenKommentar"):
            db.ereignis(vid, "du", "entscheidung", "Beendet: " + v["geschlossenKommentar"])
        db.ausfuehren("UPDATE vorgaenge SET geaendert=? WHERE id=?", (float(v.get("geaendert") or erstellt), vid))
        zaehler["vorgaenge"] += 1

    if db.einstellung("stab_ab") is None:
        # Ab JETZT bekommt jede neue Plaud-Notiz einen Vorgang in der neuen Fassung.
        db.einstellung_setzen("stab_ab", time.time())
        _startvorschlaege()
    db.einstellung_setzen("letzter_abgleich", time.time())
    return zaehler


def _startvorschlaege() -> None:
    """Zwei Gedaechtnis-Vorschlaege, die sich aus deinen Daten belegen lassen:
    Whisper hoerte 'Kronis' (KI-Assistent der Uebersicht), und deine
    Arbeitsadresse ist bei krones.com. Bestaetigen musst du sie trotzdem."""
    for frage, daten in (
        ("„Kronis“ ist ein Hörfehler für „Krones“. Soll ich das korrigieren, wann immer es auftaucht?",
         {"art": "hoerfehler", "begriff": "Kronis", "bedeutung": "Krones"}),
        ("Krones ist dein Arbeitgeber. Merken?",
         {"art": "organisation", "begriff": "Krones", "bedeutung": "Veikos Arbeitgeber"}),
    ):
        db.einfuegen("entscheidungen", {
            "id": db.neue_id("e"), "vorgang_id": None, "art": "gedaechtnis", "frage": frage,
            "daten": daten, "wer": "pmo", "stand": "offen", "erstellt": time.time(),
        })
