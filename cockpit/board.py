"""
ADVISORY BOARD -- Veikos Runde von Advisors, uebernommen aus dem alten Cockpit.

Woher was kommt:
  - Die Profile (Gruppen, Kurzbiografie, Prinzipien, typische Fragen, Staerken,
    blinde Flecken) stehen in board_profile.json -- einmalig aus BOARD_DATA des
    alten Cockpits gezogen. Wer am Tisch sitzt, ist Veikos Auswahl.
  - Der aktuelle oeffentliche Stand je Person wird nachts vom alten Backend
    aufgefrischt (board.py dort, SearXNG + lokales Modell) und liegt in
    /var/lib/vvec/board-stand.json. Diese Fassung LIEST ihn nur.

Anders als im alten Cockpit:
  - Gespraeche bleiben gespeichert (gespraeche.art = 'board'), mehrere nebeneinander.
  - Einzelgespraech mit einer Person oder die Runde am Tisch.
  - Optional mit Projektbezug (derselbe Kontext wie im Talk).
  - Die Antwort nennt jeden Sprecher fett am Absatzanfang; das Cockpit teilt
    sie daran in einzelne Sprechblasen auf.
Nur lokale Modelle, wie ueberall in dieser Fassung.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, AsyncIterator

from . import db, llm
from .konfig import ALT_DATEN, MODELL_TALK

PROFILE = json.loads((Path(__file__).with_name("board_profile.json")).read_text(encoding="utf-8"))
NACH_ID = {p["id"]: p for p in PROFILE["persons"]}
GRUPPEN = {c["id"]: c["name"] for c in PROFILE["clusters"]}


def stand() -> dict[str, Any]:
    try:
        return json.loads((ALT_DATEN / "board-stand.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def tisch() -> list[str]:
    """Wer am Tisch sitzt. Beim ersten Mal die Auswahl aus dem alten Cockpit."""
    t = db.einstellung("board_tisch")
    if t is None:
        try:
            alt = json.loads((ALT_DATEN / "cockpit-state.json").read_text(encoding="utf-8"))
            t = [i for i in ((alt.get("board") or {}).get("persons") or []) if i in NACH_ID]
        except (OSError, ValueError):
            t = []
        t = t or [p["id"] for p in PROFILE["persons"][:8]]
        db.einstellung_setzen("board_tisch", t)
    return [i for i in t if i in NACH_ID]


def uebersicht() -> dict[str, Any]:
    st = stand()
    personen = []
    for p in PROFILE["persons"]:
        s = (st.get("personen") or {}).get(p["id"]) or {}
        personen.append({**p, "gruppen": [GRUPPEN.get(c, c) for c in p.get("clusters", [])],
                         "aktuell": s.get("stand") or "", "quellen": (s.get("quellen") or [])[:6],
                         "aktualisiert": s.get("aktualisiert"), "ruhend": bool(s.get("tot_oder_ruhend"))})
    gespraeche = db.alle("SELECT g.id, g.titel, g.geaendert, (SELECT COUNT(*) FROM nachrichten n WHERE n.gespraech_id=g.id) AS anzahl "
                         "FROM gespraeche g WHERE g.art='board' ORDER BY g.geaendert DESC LIMIT 40")
    return {"gruppen": PROFILE["clusters"], "personen": personen, "tisch": tisch(), "gespraeche": gespraeche,
            "aufgefrischt": st.get("letzterLauf")}


def _profil(p: dict[str, Any], aktuell: str) -> str:
    s = f"### {p['name']} ({', '.join(GRUPPEN.get(c, c) for c in p.get('clusters', []))})"
    if p.get("bio"):
        s += f"\nProfil: {p['bio']}"
    if p.get("principles"):
        s += "\nPrinzipien: " + " | ".join(p["principles"])
    if p.get("challenges"):
        s += "\nTypische Fragen: " + " | ".join(p["challenges"])
    if p.get("strengths"):
        s += f"\nStärken: {p['strengths']}"
    if p.get("blind"):
        s += f"\nBlinde Flecken: {p['blind']}"
    if aktuell:
        s += f"\nJüngster öffentlicher Stand: {aktuell}"
    return s


def system_text(ids: list[str], einzeln: bool, projekt_kontext: str) -> str:
    st = (stand().get("personen") or {})
    leute = [NACH_ID[i] for i in ids if i in NACH_ID]
    profile = "\n\n".join(_profil(p, (st.get(p["id"]) or {}).get("stand") or "") for p in leute)
    namen = ", ".join(p["name"] for p in leute)
    if einzeln:
        form = (f"Du bist {leute[0]['name']} und sprichst allein mit Veiko, in Ich-Form, in deiner Denkweise (Profil unten). "
                "Keine Namenszeile voranstellen.")
    else:
        form = (f"Am Tisch sitzen: {namen}. Es müssen NICHT alle sprechen -- nur wer wirklich etwas beiträgt (meist zwei bis vier). "
                "JEDER Beitrag beginnt in einer eigenen Zeile mit dem Namen fett, genau so: **Vorname Nachname** -- danach der Beitrag "
                "in Ich-Form. Widersprecht euch, wo es angebracht ist; macht Spannungen sichtbar. Kein Moderator, keine Zusammenfassung, "
                "außer Veiko verlangt sie.")
    return (f"Du bist das persönliche Advisory Board von Veiko von Eckern (Head of Corporate HR Transformation bei Krones; "
            f"Themen u. a. KI, HR-Transformation, Leadership).\n\n{form}\n\n"
            "So sprecht ihr: Deutsch, wie in einem echten Gespräch kluger Sparringspartner. Länge nach der Frage: kurz bei kurzen, "
            "tief bei schweren Entscheidungen. Stellt Rückfragen, wenn etwas unklar ist. Ehrlich und substanziell, kein Lob um des "
            "Lobes willen, keine Floskeln. Erfindet keine Zitate und keine aktuellen Ereignisse -- was ihr nicht wisst, sagt ihr.\n\n"
            + (f"{projekt_kontext}\n\n" if projekt_kontext else "")
            + f"===== PROFILE =====\n{profile}\n===== ENDE =====")


async def senden(gid: str | None, text: str, mit: list[str] | None, projekt_id: str | None) -> AsyncIterator[dict[str, Any]]:
    from .gespraech import kontext_text
    ids = [i for i in (mit or []) if i in NACH_ID] or tisch()
    if not ids:
        yield {"typ": "fehler", "text": "Am Tisch sitzt niemand. Hol links mindestens eine Person dazu."}
        return
    if not gid or not db.holen("gespraeche", gid):
        gid = db.neue_id("g")
        db.einfuegen("gespraeche", {"id": gid, "art": "board", "titel": text[:70] or "Gespräch", "kontext": {"projekt_id": projekt_id},
                                    "erstellt": time.time(), "geaendert": time.time()})
    yield {"typ": "start", "gespraech_id": gid}
    db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                  (gid, "du", text, json.dumps({"mit": ids, "projekt_id": projekt_id}, ensure_ascii=False), time.time()))
    verlauf = [{"role": "user" if m["rolle"] == "du" else "assistant", "content": m["text"]}
               for m in reversed(db.alle("SELECT rolle, text FROM nachrichten WHERE gespraech_id=? ORDER BY id DESC LIMIT 14", (gid,)))]
    pk = kontext_text({"art": "projekt", "id": projekt_id}) if projekt_id else ""
    modell = await llm.modell_waehlen(MODELL_TALK, "qwen3.6:27b", "qwen3:30b-a3b", "llama3.3:70b")
    if not modell:
        yield {"typ": "fehler", "text": "Kein lokales Modell installiert."}
        return
    gesamt = ""
    try:
        async for t in llm.strom(modell, system_text(ids, len(ids) == 1, pk), verlauf, temperatur=0.7, denken=False, num_ctx=24576):
            gesamt += t
            yield {"typ": "text", "t": t}
    except llm.ModellFehler as f:
        yield {"typ": "fehler", "text": str(f)}
        return
    if llm.fremdschrift(gesamt):
        gesamt = llm.FREMDSCHRIFT.sub("", gesamt)
    mid = db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                        (gid, "board", gesamt.strip(), json.dumps({"mit": ids, "modell": modell}, ensure_ascii=False), time.time()))
    db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), gid))
    yield {"typ": "fertig", "text": gesamt.strip(), "nachricht_id": mid, "modell": modell}
