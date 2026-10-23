"""
ADVISORY BOARD -- Veikos Runde von Advisors, uebernommen aus dem alten Cockpit.

Woher was kommt:
  - Die Profile (Gruppen, Kurzbiografie, Prinzipien, typische Fragen, Staerken,
    blinde Flecken) stehen in board_profile.json -- einmalig aus BOARD_DATA des
    alten Cockpits gezogen. Wer am Tisch sitzt, ist Veikos Auswahl.
  - Der aktuelle oeffentliche Stand je Person: bis zum 23.10.2026 frischte ihn das alte
    Backend nachts auf (/var/lib/vvec/board-stand.json), diese Fassung las nur. Seitdem
    frischt sie SELBST auf (auffrischen() unten, daten/board-stand.json, nachts 23 Uhr und
    per Knopf) -- portiert aus dem alten board.py, damit das alte Cockpit wegkann.

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
from .konfig import ALT_DATEN, DATEN, MODELL_TALK, SEARX

PROFILE = json.loads((Path(__file__).with_name("board_profile.json")).read_text(encoding="utf-8"))
NACH_ID = {p["id"]: p for p in PROFILE["persons"]}
GRUPPEN = {c["id"]: c["name"] for c in PROFILE["clusters"]}
STAND_DATEI = DATEN / "board-stand.json"
ALT_STAND = ALT_DATEN / "board-stand.json"


def stand() -> dict[str, Any]:
    """Der eigene Stand; solange es ihn nicht gibt, der zuletzt vom alten Cockpit geschriebene."""
    for f in (STAND_DATEI, ALT_STAND):
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


# ---------------------------------------------------------------- Auffrischen (23.10.2026)
# Portiert aus dem alten board.py -- dieselben Regeln, weil sie dort trugen:
#   - NUR aus den Treffern der eigenen SearXNG, nichts erfinden; ohne Treffer bleibt der alte Stand.
#   - Tote oder lange Ruhende werden so benannt, statt ihnen Aktuelles anzudichten.
#   - Sechs Personen je Nacht (19 sind in vier Naechten durch), aelteste zuerst; der Knopf nimmt
#     alle, die aelter als zwei Tage sind.
#   - Lokales Modell, ohne Cloud. Nachts um 23 Uhr (Nachtplan, nachtplan.py): da rechnet sonst
#     nichts auf den Karten -- das alte Cockpit tat es um 04:30, mitten in die Daily Tasks.
MAX_JE_NACHT = 6
FRISCH_S = 2 * 24 * 3600
LAUF: dict[str, Any] = {"aktiv": False, "wer": "", "getan": 0, "offen": 0, "fehler": None, "start": 0}

VERDICHTEN = (
    "Du verdichtest öffentliche Aussagen von {name} zu einem aktuellen Persönlichkeits-Stand.\n\n"
    "REGELN:\n- NUR aus den TREFFERN. Nichts erfinden. Kein Zitat, das nicht in den Treffern steht.\n"
    "- Ist die Person tot, lange ohne neue Aussage, oder die Treffer sind nur Nachrufe/Rückblicke: "
    "tot_oder_ruhend=true, stand sagt das in einem Satz, aussagen leer.\n"
    "- Keine Biografie. Nur was HEUTE gilt: Haltung, Themen, was sich verschoben hat.\n"
    "- Deutsch, kurze Sätze, keine Fachsprache.\n"
    "- 'geaendert' nur füllen, wenn die Treffer eine Verschiebung gegenüber dem LETZTEN STAND zeigen.\n\n"
    'Antworte AUSSCHLIESSLICH mit JSON: {{"stand": "zwei bis vier Sätze: wofür steht diese Person HEUTE", '
    '"themen": ["höchstens fünf aktuelle Themen"], "aussagen": [{{"text": "eng an den Treffern", "quelle": "Medium oder Titel", '
    '"wann": "JJJJ-MM oder leer"}}], "tot_oder_ruhend": false, "geaendert": ""}}')


def _stand_schreiben(d: dict[str, Any]) -> None:
    tmp = STAND_DATEI.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STAND_DATEI)


async def _suchen(frage: str) -> list[dict[str, str]]:
    import httpx
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{SEARX}/search", params={"q": frage, "format": "json", "language": "en", "safesearch": "0"})
    if r.status_code != 200:
        raise RuntimeError(f"Websuche antwortete mit {r.status_code}")
    return [{"titel": (t.get("title") or "").strip()[:200], "adresse": (t.get("url") or "")[:300],
             "auszug": (t.get("content") or "").strip()[:600]} for t in (r.json().get("results") or [])[:6]]


async def person_auffrischen(pid: str, name: str, modell: str) -> dict[str, Any]:
    jahr = time.gmtime().tm_year
    treffer, gesehen, suchfehler = [], set(), ""
    for q in (f'"{name}" {jahr} (interview OR speech OR statement OR said OR keynote)',
              f'"{name}" (interview OR podcast OR "I believe" OR opinion) {jahr - 1} OR {jahr}'):
        try:
            for t in await _suchen(q):
                k = t["adresse"] or t["titel"]
                if k and k not in gesehen:
                    gesehen.add(k)
                    treffer.append(t)
        except Exception as e:  # noqa: BLE001
            suchfehler = str(e)
        if len(treffer) >= 6:
            break
    alt = (stand().get("personen") or {}).get(pid) or {}
    e: dict[str, Any] = {"id": pid, "name": name, "stand": alt.get("stand") or "", "themen": alt.get("themen") or [],
                         "aussagen": alt.get("aussagen") or [], "quellen": alt.get("quellen") or [],
                         "tot_oder_ruhend": bool(alt.get("tot_oder_ruhend")), "geaendert": "",
                         "aktualisiert": int(time.time()), "modell": modell, "fehler": ""}
    if not treffer:
        # Lieber ehrlich alt als frei erfunden: der bisherige Stand bleibt.
        e["fehler"] = suchfehler or "Keine öffentlichen Treffer"
        return e
    e["quellen"] = [{"titel": t["titel"], "adresse": t["adresse"]} for t in treffer[:8]]
    text = "\n\n".join(f"{i}. {t['titel']}\n   {t['adresse']}\n   {t['auszug'][:500]}" for i, t in enumerate(treffer, 1))
    frage = f"PERSON: {name}\n\nLETZTER STAND:\n{alt.get('stand') or '(noch keiner)'}\n\nTREFFER:\n{text}"
    try:
        d = llm.json_aus(await llm.chat(modell, VERDICHTEN.format(name=name), [{"role": "user", "content": frage}],
                                        json_format=True, temperatur=0.2, denken=False)) or {}
    except Exception as f:  # noqa: BLE001
        e["fehler"] = f"Modell: {f}"
        return e
    if not str(d.get("stand") or "").strip() or llm.fremdschrift(json.dumps(d, ensure_ascii=False)):
        e["fehler"] = "Modell lieferte keinen lesbaren Stand"
        return e
    e.update(stand=str(d["stand"]).strip()[:800],
             themen=[str(x).strip()[:80] for x in (d.get("themen") or []) if str(x).strip()][:5],
             aussagen=[{"text": str(a.get("text"))[:400], "quelle": str(a.get("quelle") or "")[:120], "wann": str(a.get("wann") or "")[:10]}
                       for a in (d.get("aussagen") or [])[:5] if isinstance(a, dict) and str(a.get("text") or "").strip()],
             tot_oder_ruhend=bool(d.get("tot_oder_ruhend")), geaendert=str(d.get("geaendert") or "").strip()[:300])
    return e


async def auffrischen(alle: bool = False, nur_id: str = "") -> dict[str, Any]:
    if LAUF["aktiv"]:
        return {"ok": False, "grund": "Läuft schon."}
    d = stand()
    d.setdefault("personen", {})
    jetzt = time.time()
    wartend = [p for p in PROFILE["persons"] if (not nur_id or p["id"] == nur_id)
               and (alle or nur_id or jetzt - float(((d["personen"].get(p["id"]) or {}).get("aktualisiert")) or 0) >= FRISCH_S)]
    wartend.sort(key=lambda p: float(((d["personen"].get(p["id"]) or {}).get("aktualisiert")) or 0))
    if not alle and not nur_id:
        wartend = wartend[:MAX_JE_NACHT]
    if not wartend:
        return {"ok": True, "getan": 0, "hinweis": "Alle sind frisch genug."}
    modell = llm.vorgabe("arbeit")
    LAUF.update(aktiv=True, wer="", getan=0, offen=len(wartend), fehler=None, start=time.time())
    letzter_fehler = ""
    try:
        with llm.taetig("Advisory Board: frischt auf"):
            for p in wartend:
                LAUF["wer"] = p["name"]
                e = await person_auffrischen(p["id"], p["name"], modell)
                d = stand()
                d.setdefault("personen", {})[p["id"]] = e
                d["letzterLauf"] = int(time.time())
                letzter_fehler = f"{p['name']}: {e['fehler']}" if e.get("fehler") else letzter_fehler
                d["letzterFehler"] = letzter_fehler
                _stand_schreiben(d)
                LAUF.update(getan=LAUF["getan"] + 1, offen=LAUF["offen"] - 1)
    finally:
        LAUF.update(aktiv=False, wer="", fehler=letzter_fehler or None)
    return {"ok": True, "getan": LAUF["getan"], "modell": modell, "fehler": letzter_fehler or None}


async def schleife() -> None:
    """Einmal je Nacht ab 23 Uhr deutscher Zeit (Nachtplan)."""
    import asyncio
    import datetime
    import traceback
    from zoneinfo import ZoneInfo
    await asyncio.sleep(180)
    while True:
        try:
            jetzt = datetime.datetime.now(ZoneInfo("Europe/Berlin"))
            heute = jetzt.date().isoformat()
            if jetzt.hour == 23 and db.einstellung("board_nacht") != heute and not LAUF["aktiv"]:
                db.einstellung_setzen("board_nacht", heute)
                await auffrischen()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(300)


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
            "aufgefrischt": st.get("letzterLauf"), "lauf": dict(LAUF), "letzter_fehler": st.get("letzterFehler") or ""}


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


async def senden(gid: str | None, text: str, mit: list[str] | None, projekt_id: str | None,
                 schnell: bool = False) -> AsyncIterator[dict[str, Any]]:
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
    # Zugeordnetes Projekt und Aufgabe (17.10.2026): gespeichert am Gespraech.
    from .gespraech import aufgabe_text, zuordnung
    z = zuordnung(gid)
    projekt_id = projekt_id or z.get("projekt_id")
    pk = kontext_text({"art": "projekt", "id": projekt_id}) if projekt_id else ""
    if z.get("aufgabe_id"):
        pk = (pk + "\n\n" if pk else "") + aufgabe_text(z["aufgabe_id"])
    modell = await llm.talk_modell()
    if not modell:
        yield {"typ": "fehler", "text": "Kein lokales Modell installiert."}
        return
    from . import stab
    denken, zusatz = llm.tempo(schnell)
    from . import dossier
    system = system_text(ids, len(ids) == 1, pk) + "\n\n" + zusatz + "\n\n" + dossier.ANWEISUNG
    quellen: list[dict[str, str]] = []
    if denken:
        yield {"typ": "status", "text": "prüft, ob das Internet hilft …"}
        quellen = await stab.netzwissen(modell, verlauf)
        if quellen:
            system += "\n\n" + stab.netz_system(quellen)
            yield {"typ": "status", "text": f"{len(quellen)} Quellen aus dem Netz gelesen, das Board berät …"}
    # Links in der Nachricht werden immer geoeffnet (quellen.py, 17.10.2026).
    from . import quellen as verlinkt
    if verlinkt.links(text):
        yield {"typ": "status", "text": "öffnet die Links aus deiner Nachricht …"}
        ltext, lstatus = await verlinkt.einbinden(text, {"projekt_id": projekt_id or z.get("projekt_id"), "aufgabe_id": z.get("aufgabe_id"),
                                                         "gespraech_id": gid, "wer": "board"})
        if ltext:
            system += "\n\n" + ltext
        if lstatus:
            yield {"typ": "status", "text": "; ".join(lstatus)}
    gesamt = ""
    try:
        with llm.taetig("Das Advisory Board antwortet dir"):
            async for t in llm.strom(modell, system, verlauf, temperatur=0.7, denken=denken, num_ctx=32768):
                gesamt += t
                yield {"typ": "text", "t": t}
    except llm.ModellFehler as f:
        yield {"typ": "fehler", "text": str(f)}
        return
    if llm.fremdschrift(gesamt):
        gesamt = llm.FREMDSCHRIFT.sub("", gesamt)
    gesamt, recherche = await dossier.aus_antwort(gesamt, {"projekt_id": projekt_id or z.get("projekt_id"), "aufgabe_id": z.get("aufgabe_id"),
                                                          "gespraech_id": gid, "wer": "board"})
    if recherche:
        gesamt = gesamt.strip() + "\n\n" + recherche[0]
    gesamt = gesamt.strip() + stab.netz_fuss(quellen)
    mid = db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                        (gid, "board", gesamt.strip(), json.dumps({"mit": ids, "modell": modell}, ensure_ascii=False), time.time()))
    db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), gid))
    yield {"typ": "fertig", "text": gesamt.strip(), "nachricht_id": mid, "modell": modell}
