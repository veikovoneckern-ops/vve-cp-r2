"""
ALLE ENDPUNKTE der neuen Fassung. Gegliedert nach den Bereichen der Oberflaeche:
Briefing, Inbox, Projects, Team, System, dazu Talk, Neo, Capture.

Der Browser schickt EINZELNE Aenderungen ("Aufgabe X ist erledigt"), nie den
ganzen Zustand. Damit gibt es keine Konflikte zwischen zwei Geraeten.
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import shutil
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from . import anmeldung, db, gespraech, importer, llm, nachtladen, neo, stab, stimme, teamchat
from .konfig import (ALT_COCKPIT_URL, ALT_STATE, SEARX, STATUS_URL, UPLOADS,
                     VORSCHAU_DIR)

router = APIRouter(prefix="/api")


def _fassung() -> str:
    """Kennung der ausgelieferten Oberflaeche: juengste Aenderung einer Datei unter frontend/."""
    from .konfig import FRONTEND
    try:
        return str(int(max(p.stat().st_mtime for p in FRONTEND.rglob("*") if p.is_file())))
    except ValueError:
        return ""


FASSUNG = _fassung()

SANDBOX = {"Content-Security-Policy": "sandbox allow-scripts allow-forms allow-popups",
           "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


async def _koerper(request: Request) -> dict[str, Any]:
    try:
        d = await request.json()
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


def _pflicht(d: dict[str, Any], *felder: str) -> None:
    fehlt = [f for f in felder if not str(d.get(f) or "").strip()]
    if fehlt:
        raise HTTPException(400, "Es fehlt: " + ", ".join(fehlt))


async def _stil_aus(d: dict[str, Any]) -> dict[str, Any] | None:
    """Praesentations-Stil aus einer Anfrage (folien_stil.py). Bei eigenen Vorgaben
    leitet ein lokales Modell daraus Farben, Schriften und Footer ab -- einmal hier,
    nicht bei jedem Abruf der Ansicht. Nichts gewaehlt: None = die Vorgabe."""
    from . import folien_stil
    sid = d.get("stil")
    if sid in ("vveorg", "cockpit"):
        return {"id": sid}
    if sid == "eigen":
        text = str(d.get("stil_text") or "").strip()
        if not text:
            raise HTTPException(400, "Beschreibe bei eigenen Vorgaben, wie die Präsentation aussehen soll.")
        try:
            return {"id": "eigen", "text": text[:1500], "werte": await folien_stil.aus_text(text)}
        except llm.ModellFehler as e:
            raise HTTPException(503, f"Die Vorgaben ließen sich nicht umsetzen: {e}")
    return None


# ================================================================ Konto
@router.get("/konto/ich")
async def ich(request: Request):
    name = anmeldung.sitzung(request.cookies.get(anmeldung.COOKIE))
    return {"angemeldet": bool(name), "benutzer": name, "einrichten": not anmeldung.benutzer()}


@router.post("/konto/anmelden")
async def anmelden(request: Request, response: Response):
    d = await _koerper(request)
    name = anmeldung.pruefen(str(d.get("benutzer") or ""), str(d.get("passwort") or ""))
    if not name:
        raise HTTPException(401, "Benutzername oder Passwort stimmt nicht.")
    from .konfig import COOKIE_SICHER
    response.set_cookie(anmeldung.COOKIE, anmeldung.sitzung_anlegen(name), httponly=True, samesite="lax",
                        secure=COOKIE_SICHER and request.url.scheme == "https", max_age=anmeldung.DAUER)
    return {"benutzer": name}


@router.post("/konto/einrichten")
async def einrichten(request: Request, response: Response):
    if anmeldung.benutzer():
        raise HTTPException(403, "Es gibt schon ein Konto.")
    d = await _koerper(request)
    if len(str(d.get("passwort") or "")) < 8 or len(str(d.get("benutzer") or "")) < 2:
        raise HTTPException(400, "Name mindestens 2, Passwort mindestens 8 Zeichen.")
    anmeldung.einrichten(d["benutzer"], d["passwort"])
    response.set_cookie(anmeldung.COOKIE, anmeldung.sitzung_anlegen(d["benutzer"]), httponly=True,
                        samesite="lax", max_age=anmeldung.DAUER)
    return {"benutzer": d["benutzer"]}


@router.post("/konto/abmelden")
async def abmelden(request: Request, response: Response):
    anmeldung.abmelden(request.cookies.get(anmeldung.COOKIE))
    response.delete_cookie(anmeldung.COOKIE)
    return {"ok": True}


# ================================================================ Briefing
def _protokoll_label(p: dict[str, Any]) -> str | None:
    tab, nach, vor = p["tabelle"], p.get("nachher") or {}, p.get("vorher") or {}
    if tab == "aufgaben" and p["aktion"] == "angelegt":
        pr = db.holen("projekte", nach.get("projekt_id") or "") if nach.get("projekt_id") else None
        return f"Aufgabe angelegt: {nach.get('titel')}" + (f" ({pr['name']})" if pr else "")
    if p["aktion"] == "zugeordnet" and tab in ("notizen", "vorgaenge"):
        pr = db.holen("projekte", nach.get("projekt_id") or "") or {}
        if tab == "notizen":
            return f"Notiz „{(nach.get('titel') or '')[:50]}“ zugeordnet: {pr.get('name', '?')}"
        return None
    if tab == "gedaechtnis" and p["aktion"] == "angelegt":
        return f"Gemerkt: {nach.get('begriff')} = {nach.get('bedeutung')}"
    if tab == "ergebnisse" and p["aktion"] == "angelegt":
        return None
    return None


def _wer_ist_stab(wer: str) -> bool:
    return wer not in ("du", "system", None, "")


FORM_NAME = {"text": "Text", "aufstellung": "Aufstellung", "konzept": "Konzept", "dokument": "Dokument",
             "webseite": "Webseite", "praesentation": "Präsentation", "video": "Video"}


def kurztitel(e: dict[str, Any]) -> str:
    """Ein Ergebnis-Titel, den man ueberfliegen kann. Bis zum 16.10. war der Titel
    der abgeschnittene Auftrag ("Erstellung einer lebendigen und detaillierten
    PowerPoint-Präsentation zum Thema ExO"); dann lieber Form und Case-Titel.
    Kurze Titel bleiben, wie sie sind."""
    t = (e.get("titel") or "").strip()
    vt = e.get("vorgang_titel")
    if vt is None and e.get("vorgang_id"):
        vt = (db.holen("vorgaenge", e["vorgang_id"]) or {}).get("titel")
    if vt and (len(t) > 55 or t.endswith(("…", ")")) and len(t) > 40) and not t.startswith(("Video:", "Recherche-Dossier:")):
        return f"{FORM_NAME.get(e.get('form'), 'Ergebnis')}: {vt}"
    return t or "Ergebnis"


@router.post("/lage/gesehen")
async def lage_gesehen():
    db.einstellung_setzen("briefing_gesehen", time.time())
    return {"ok": True}


def _rsi_briefing() -> dict[str, Any] | None:
    try:
        from . import rsi_serie
        return rsi_serie.briefing()
    except Exception:  # noqa: BLE001 -- das Briefing darf nie an RSI scheitern
        return None


async def _optimierung_zahl() -> int:
    from . import revision
    try:
        return len(await revision.vorschlaege())
    except Exception:  # noqa: BLE001 -- das Briefing darf daran nicht scheitern
        return 0


def _aktionen_zahl() -> int:
    from . import aktionen
    try:
        return sum(1 for z in aktionen.sammeln(GESPRAECH_LAEUFT, teamchat.wer_name)["laufend"] if z.get("stand") != "pausiert")
    except Exception:  # noqa: BLE001 -- das Briefing darf daran nicht scheitern
        return 0


@router.get("/lage")
async def lage():
    ents = db.alle("SELECT e.*, v.titel AS vorgang_titel, v.projekt_id FROM entscheidungen e "
                   "LEFT JOIN vorgaenge v ON v.id=e.vorgang_id WHERE e.stand='offen' ORDER BY e.erstellt")
    for e in ents:
        e["wer_name"] = stab.rollen_name(e["wer"])
    grenze = time.time() - 3 * 86400
    erledigt = []
    for p in db.alle("SELECT * FROM protokoll WHERE zeit>? AND rueckgaengig=0 ORDER BY id DESC LIMIT 80", (grenze,)):
        if not _wer_ist_stab(p["wer"]):
            continue
        lab = _protokoll_label(p)
        if lab:
            erledigt.append({"protokoll_id": p["id"], "text": lab, "wer": p["wer"], "wer_name": stab.rollen_name(p["wer"]),
                             "zeit": p["zeit"], "vorgang_id": p.get("vorgang_id")})
    # Dieselbe Liste wie in Talk (stab.neu_entstanden), zuletzt bearbeitete zuerst.
    ergebnisse = stab.neu_entstanden()
    for e in ergebnisse:
        e["kurztitel"] = kurztitel(e)
    # "Seit deinem letzten Besuch" (Veiko, 16.10.: "bis ich raus habe, was wirklich
    # entstanden ist und was das Neue ist"). Auf dem Server gemerkt, nicht im
    # Browser: was am Handy schon gesehen wurde, ist am Rechner nicht mehr neu.
    gesehen = db.einstellung("briefing_gesehen") or 0
    from . import video
    videos = []
    for eid in list(video.LAUFEND):
        r = db.holen("ergebnisse", eid) or {}
        vs = video.stand(r) or {}
        videos.append({"id": eid, "titel": kurztitel(r) if r else eid, "schritt": vs.get("schritt"),
                       "fertig": vs.get("fertig") or 0, "szenen": vs.get("szenen") or 0, "start": vs.get("start")})
    laufend = [v for v in db.alle("SELECT id, titel, auftrag, geaendert, versuche, stand FROM vorgaenge "
                                  "WHERE stand IN ('neu','in_arbeit','wartet') AND quelle!='alt' ORDER BY geaendert DESC LIMIT 30")
               if v["stand"] != "wartet" or stab.auftrag_offen(v)][:6]
    for v in laufend:
        try:
            a = json.loads(v.get("auftrag") or "{}")
        except ValueError:
            a = {}
        v["wer_name"] = stab.rollen_name(a.get("rolle")) if a else "Jason"
    aufgaben = db.alle("SELECT a.*, p.name AS projekt_name, p.farbe AS projekt_farbe FROM aufgaben a "
                       "LEFT JOIN projekte p ON p.id=a.projekt_id WHERE a.status!='erledigt' AND a.archiviert=0 "
                       "ORDER BY (a.faellig='' OR a.faellig IS NULL), a.faellig, a.prio, a.erstellt DESC LIMIT 8")
    # ergebnis_id: das passende Ergebnis aus dem Case der Aufgabe -- ein Klick auf
    # den Titel fuehrt dann direkt ins Gespraech daran (Veiko, 16.10.). Nur wenn
    # der Ergebnistitel ein tragendes Wort mit der Aufgabe teilt: ein Case hat oft
    # mehrere Ergebnisse, und "E-Mail beantworten" oeffnete sonst die Recherche zu
    # Abmahnungen, nur weil beide im selben Case lagen. Ohne Treffer geht der
    # Klick nach Talk, mit der Aufgabe als Bezug.
    for t in aufgaben:
        t["ergebnis_id"] = None
        if not t.get("vorgang_id"):
            continue
        woerter = set(re.findall(r"\w{5,}", (t["titel"] or "").lower()))
        for r in db.alle("SELECT id, titel FROM ergebnisse WHERE vorgang_id=? ORDER BY erstellt DESC", (t["vorgang_id"],)):
            if woerter & set(re.findall(r"\w{5,}", (r["titel"] or "").lower())):
                t["ergebnis_id"] = r["id"]
                break
    woche = time.time() - 7 * 86400
    entschieden = db.alle("SELECT stand FROM entscheidungen WHERE erledigt>? AND art!='rueckfrage'", (woche,))
    neo_lauf = [{"gespraech_id": j["gespraech_id"], "seit": j["start"]} for j in neo.JOBS.values() if not j["fertig"]]
    return {
        # Welche Fassung der Oberflaeche der Server ausliefert (19.10.2026): ein offener Tab
        # zeigte nach einem Update weiter die alte -- die Seite vergleicht und bietet Neu laden an.
        "fassung": FASSUNG,
        "entscheidungen": ents, "erledigt": erledigt[:12], "ergebnisse": ergebnisse, "laufend": laufend,
        "gesehen": gesehen, "videos": videos,
        "neu": {"ergebnisse": sum(1 for e in ergebnisse if e["bearbeitet"] > gesehen),
                "cases": db.wert("SELECT COUNT(*) FROM vorgaenge WHERE erstellt>? AND quelle!='alt'", (gesehen,)),
                "erledigt": sum(1 for x in erledigt if x["zeit"] > gesehen)},
        "aufgaben": aufgaben, "gesundheit": stab.gesundheit(), "neo_laeuft": neo_lauf,
        # Vorgemerkt (21.10.2026): eigener Block, damit eine geparkte Notiz nicht zwischen
        # den Aufgaben verschwindet. Die Aufgaben dazu stehen mit Titel dabei.
        "vorgemerkt": [{**v, "projekt_name": (db.holen("projekte", v.get("projekt_id") or "") or {}).get("name"),
                        "aufgaben": [a["titel"] for a in db.alle("SELECT titel FROM aufgaben WHERE vorgang_id=? AND status!='erledigt' "
                                                                  "AND archiviert=0", (v["id"],))]}
                       for v in db.alle("SELECT id, titel, einordnung, projekt_id, erstellt FROM vorgaenge "
                                        "WHERE stand='vorgemerkt' ORDER BY erstellt DESC LIMIT 12")],
        # Modell-Revision: belegte Vorschlaege zum Umstellen (17.10.2026) -- das Briefing
        # sagt es, damit Veiko nicht erst die Seite Stab & Modelle oeffnen muss.
        "optimierung": await _optimierung_zahl(),
        # RSI (23.10.2026): ob das Cockpit sich zuletzt veraendert hat, was gerade umgesetzt wird, was wartet.
        "rsi": _rsi_briefing(), "nacht": _nacht_briefing(),
        # Antworten, die gerade auf dem Server entstehen -- auch wenn das Fenster zu ist.
        "gespraeche_laufen": [{"gespraech_id": g, "art": s["art"], "wer": s["wer"],
                               "wer_name": teamchat.wer_name(s["wer"]) if s["wer"] else ("Talk" if s["art"] == "talk" else "Advisory Board"),
                               "start": s["start"], "status": s["status"]} for g, s in list(GESPRAECH_LAEUFT.items())],
        # Zahl fuer den Knopf "Current Actions" in der linken Leiste.
        "aktionen": _aktionen_zahl(),
        "woche": {
            "angenommen": sum(1 for e in entschieden if e["stand"] == "ja"),
            "entschieden": len(entschieden),
            "notizen": db.wert("SELECT COUNT(*) FROM notizen WHERE erstellt>?", (woche,)),
            "projekte": db.wert("SELECT COUNT(*) FROM projekte WHERE status='aktiv'"),
            "erledigt": db.wert("SELECT COUNT(*) FROM aufgaben WHERE status='erledigt' AND geaendert>?", (woche,)),
        },
    }


# ================================================================ Inbox
STAND_GRUPPE = {"wartet": ("vorgemerkt", "wartet"), "in_arbeit": ("neu", "eingeordnet", "in_arbeit"),
                "fertig": ("fertig",), "erledigt": ("erledigt", "verworfen")}


@router.get("/vorgaenge")
async def vorgaenge(filter: str = "wartet", projekt: str = "", q: str = "", grenze: int = 200):
    sql = ("SELECT v.*, p.name AS projekt_name, p.farbe AS projekt_farbe, "
           "(SELECT COUNT(*) FROM entscheidungen e WHERE e.vorgang_id=v.id AND e.stand='offen') AS offen, "
           "(SELECT COUNT(*) FROM ergebnisse r WHERE r.vorgang_id=v.id) AS ergebnisse "
           "FROM vorgaenge v LEFT JOIN projekte p ON p.id=v.projekt_id WHERE 1=1")
    args: list[Any] = []
    if filter in STAND_GRUPPE:
        sql += f" AND v.stand IN ({','.join('?' for _ in STAND_GRUPPE[filter])})"
        args += list(STAND_GRUPPE[filter])
        # Tagesbriefings (daily.py) haben ihre eigene Seite; in den Reitern stuenden sonst jeden
        # Morgen ein paar Briefings zwischen den Notizen. Unter "Alle" bleiben sie zu finden.
        sql += " AND v.quelle!='daily'"
    if projekt:
        sql += " AND v.projekt_id=?"
        args.append(projekt)
    if q:
        sql += " AND (v.titel LIKE ? OR v.einordnung LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    # Vorgemerktes zuerst: es haengt in der Inbox, bis Veiko entscheidet (21.10.2026).
    sql += " ORDER BY (v.stand='vorgemerkt') DESC, v.geaendert DESC LIMIT ?"
    args.append(min(grenze, 500))
    zaehler = {k: db.wert(f"SELECT COUNT(*) FROM vorgaenge WHERE quelle!='daily' AND stand IN ({','.join('?' for _ in s)})", s)
               for k, s in STAND_GRUPPE.items()}
    return {"vorgaenge": db.alle(sql, args), "zaehler": zaehler}


# ================================================================ Daily Tasks (22.10.2026, daily.py)
@router.get("/daily")
async def daily_liste():
    from . import daily
    rollen = [{"id": r["id"], "name": r["name"], "titel": r.get("titel")} for r in
              db.alle("SELECT id, name, titel FROM team WHERE aktiv=1") if r["id"] in daily.ROLLEN]
    return {"daily": daily.liste(), "vorlagen": daily.VORLAGEN, "rollen": rollen}


@router.get("/daily/{did}")
async def daily_einzeln(did: str):
    from . import daily
    d = daily.holen(did)
    if not d:
        raise HTTPException(404, "Daily Task nicht gefunden")
    return {**d, "zeitplan": daily.zeitplan_text(d), "rolle_name": stab.rollen_name(d.get("rolle")),
            "verlauf": daily.verlauf(did), "laeuft": daily.laeuft(did), "naechster": daily.naechster_lauf(d)}


@router.post("/daily")
async def daily_anlegen(request: Request):
    from . import daily
    try:
        return daily.anlegen(await _koerper(request))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/daily/{did}")
async def daily_aendern(did: str, request: Request):
    from . import daily
    try:
        return daily.aendern(did, await _koerper(request))
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/daily/{did}/ausfuehren")
async def daily_ausfuehren(did: str):
    from . import daily
    try:
        return daily.ausfuehren(did, von_hand=True)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.delete("/daily/{did}")
async def daily_loeschen(did: str):
    from . import daily
    try:
        daily.loeschen(did)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True}


# ================================================================ Mail (22.10.2026, mail.py)
@router.get("/mail")
async def mail_uebersicht():
    from . import mail
    return {**mail.liste(), "kontakte": mail.kontakte(grenze=300), "postausgang": await asyncio.to_thread(mail.absender),
            "formate": mail.FORMATE, "vorschlaege": list(mail.AUFTRAEGE)}


@router.get("/mail/anhaenge")
async def mail_anhang_suche(q: str = ""):
    """Was sich anhaengen laesst: Ergebnisse (als Dokument) und Unterlagen (als Original)."""
    like = f"%{q.strip()}%"
    erg = db.alle("SELECT id, titel, form, erstellt FROM ergebnisse WHERE titel LIKE ? ORDER BY erstellt DESC LIMIT 12", (like,))
    dat = db.alle("SELECT id, name, groesse, erstellt FROM dateien WHERE name LIKE ? ORDER BY erstellt DESC LIMIT 12", (like,))
    return {"treffer": [{"art": "ergebnis", "id": e["id"], "titel": e["titel"], "unter": e.get("form"), "zeit": e["erstellt"]} for e in erg]
            + [{"art": "datei", "id": d["id"], "titel": d["name"], "unter": f"{round((d.get('groesse') or 0) / 1024)} KB", "zeit": d["erstellt"]} for d in dat]}


@router.get("/mail/kontakte")
async def mail_kontakte(q: str = ""):
    from . import mail
    return {"kontakte": mail.kontakte(q, 12)}


@router.post("/mail/kontakte")
async def mail_kontakt_speichern(request: Request):
    from . import mail
    d = await _koerper(request)
    try:
        return mail.kontakt_speichern(str(d.get("email") or ""), str(d.get("name") or ""), d.get("notiz"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/mail/kontakte/{kid}")
async def mail_kontakt_loeschen(kid: str):
    db.loeschen("kontakte", kid)
    return {"ok": True}


@router.post("/mail")
async def mail_neu(request: Request):
    from . import mail
    return mail.anlegen(await _koerper(request))


@router.get("/mail/{mid}")
async def mail_einzeln(mid: str):
    from . import mail
    m = mail.holen(mid)
    if not m:
        raise HTTPException(404, "Mail nicht gefunden")
    return m


@router.post("/mail/{mid}")
async def mail_speichern(mid: str, request: Request):
    from . import mail
    try:
        return mail.aendern(mid, await _koerper(request))
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.delete("/mail/{mid}")
async def mail_weg(mid: str):
    from . import mail
    mail.loeschen(mid)
    return {"ok": True}


@router.post("/mail/{mid}/formulieren")
async def mail_formulieren(mid: str, request: Request):
    from . import mail
    d = await _koerper(request)
    try:
        return await mail.formulieren(mid, str(d.get("art") or "entwurf"), str(d.get("anweisung") or ""))
    except (ValueError, llm.ModellFehler) as e:
        raise HTTPException(409, str(e))


@router.post("/mail/{mid}/senden")
async def mail_abschicken(mid: str):
    from . import mail
    try:
        return await mail.senden(mid)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/mail/{mid}/wiederverwenden")
async def mail_wiederverwenden(mid: str):
    from . import mail
    try:
        return mail.wiederverwenden(mid)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/vorgaenge/{vid}")
async def vorgang(vid: str):
    v = db.holen("vorgaenge", vid)
    if not v:
        raise HTTPException(404, "Vorgang nicht gefunden")
    ev = db.alle("SELECT * FROM ereignisse WHERE vorgang_id=? ORDER BY id", (vid,))
    for e in ev:
        e["wer_name"] = stab.rollen_name(e["wer"])
    ents = db.alle("SELECT * FROM entscheidungen WHERE vorgang_id=? ORDER BY erstellt", (vid,))
    for e in ents:
        e["wer_name"] = stab.rollen_name(e["wer"])
    prot = db.alle("SELECT id, wer, aktion, tabelle, datensatz_id, nachher, rueckgaengig, zeit FROM protokoll "
                   "WHERE vorgang_id=? AND wer!='du' AND aktion IN ('angelegt','zugeordnet') ORDER BY id", (vid,))
    for p in prot:
        p["label"] = _protokoll_label(p) or ""
    try:
        auftrag = json.loads(v.get("auftrag") or "null")
    except ValueError:
        auftrag = None
    return {
        "vorgang": v, "auftrag": auftrag,
        "notiz": db.holen("notizen", v["notiz_id"]) if v.get("notiz_id") else None,
        "projekt": db.holen("projekte", v["projekt_id"]) if v.get("projekt_id") else None,
        "ereignisse": ev, "entscheidungen": ents,
        "aufgaben": db.alle("SELECT * FROM aufgaben WHERE vorgang_id=? ORDER BY erstellt", (vid,)),
        "ergebnisse": [{**r, "kurztitel": kurztitel({**r, "vorgang_titel": v.get("titel")})} for r in
                       db.alle("SELECT id, titel, form, rolle, pruefung, ansicht, erstellt FROM ergebnisse WHERE vorgang_id=? ORDER BY erstellt", (vid,))],
        "protokoll": [p for p in prot if p["label"]],
        "laeuft": (stab.ZUSTAND.get("laeuft") or {}).get("vorgang_id") == vid and stab.ZUSTAND["laeuft"],
    }


@router.post("/vorgaenge/{vid}/aktion")
async def vorgang_aktion(vid: str, request: Request):
    d = await _koerper(request)
    v = db.holen("vorgaenge", vid)
    if not v:
        raise HTTPException(404, "Vorgang nicht gefunden")
    a = d.get("aktion")
    if a in ("erledigt", "verwerfen"):
        stab.vorgang_schliessen(vid, a, str(d.get("kommentar") or ""))
    elif a == "freigeben":
        # Vorgemerkt -> Jason ordnet mit Veikos Anweisung neu ein (stab.freigeben, 21.10.2026).
        try:
            stab.freigeben(vid, str(d.get("anweisung") or ""))
        except ValueError as e:
            raise HTTPException(409, str(e))
    elif a == "vormerken":
        # Von Hand parken: dasselbe wie eine Notiz mit "noch nicht bearbeiten".
        if stab.auftrag_offen(v) and v["stand"] == "in_arbeit":
            raise HTTPException(409, "Das Team arbeitet gerade daran -- erst nach dem Ergebnis vormerken.")
        db.aendern("vorgaenge", vid, {"stand": "vorgemerkt", "geaendert": time.time()})
        db.ereignis(vid, "du", "entscheidung", "Vorgemerkt: das Team arbeitet nicht daran, bis du freigibst.")
    elif a == "wieder_oeffnen":
        if v["stand"] == "verworfen":
            for t in db.alle("SELECT id FROM aufgaben WHERE vorgang_id=? AND quelle='stab' AND archiviert=1", (vid,)):
                db.aendern("aufgaben", t["id"], {"archiviert": 0, "geaendert": time.time()}, wer="du", vorgang_id=vid)
        db.aendern("vorgaenge", vid, {"stand": "fertig", "geaendert": time.time()})
        db.ereignis(vid, "du", "info", "Wieder geöffnet.")
        stab.stand_berechnen(vid)
    elif a == "neu_einordnen":
        if not v.get("notiz_id"):
            raise HTTPException(400, "Zu diesem Vorgang gibt es keine Notiz.")
        db.ausfuehren("UPDATE vorgaenge SET stand='neu', versuche=0, geaendert=? WHERE id=?", (time.time(), vid))
        db.ereignis(vid, "du", "info", "Noch einmal einordnen lassen.")
        stab.wecken()
    elif a == "projekt":
        pid = d.get("projekt_id") or None
        if pid and not db.holen("projekte", pid):
            raise HTTPException(404, "Projekt nicht gefunden")
        db.aendern("vorgaenge", vid, {"projekt_id": pid})
        if v.get("notiz_id"):
            db.aendern("notizen", v["notiz_id"], {"projekt_id": pid})
        for t in db.alle("SELECT id FROM aufgaben WHERE vorgang_id=?", (vid,)):
            db.aendern("aufgaben", t["id"], {"projekt_id": pid})
        db.ereignis(vid, "du", "info", "Projekt geändert: " + ((db.holen("projekte", pid) or {}).get("name") if pid else "ohne Projekt"))
    elif a == "nochmal":
        db.ausfuehren("UPDATE vorgaenge SET versuche=0, geaendert=? WHERE id=?", (time.time(), vid))
        stab.wecken()
    else:
        raise HTTPException(400, "Unbekannte Aktion")
    return {"ok": True, "vorgang": db.holen("vorgaenge", vid)}


@router.post("/vorgaenge/{vid}/ausarbeiten")
async def vorgang_ausarbeiten(vid: str, request: Request):
    d = await _koerper(request)
    _pflicht(d, "auftrag")
    if not db.holen("vorgaenge", vid):
        raise HTTPException(404, "Vorgang nicht gefunden")
    stab.auftrag_setzen(vid, {"rolle": d.get("rolle"), "form": d.get("form"), "auftrag": d["auftrag"],
                              "recherche": d.get("recherche") or None, "stil": await _stil_aus(d)})
    db.ausfuehren("UPDATE vorgaenge SET versuche=0 WHERE id=?", (vid,))
    stab.wecken()
    return {"ok": True}


@router.post("/entscheidungen/{eid}")
async def entscheidung(eid: str, request: Request):
    d = await _koerper(request)
    r = stab.entscheiden(eid, str(d.get("antwort") or ""), str(d.get("text") or ""))
    if not r.get("ok"):
        raise HTTPException(409, r.get("grund") or "Ging nicht")
    stab.wecken()
    return r


@router.post("/erfassen")
async def erfassen(request: Request):
    d = await _koerper(request)
    text = str(d.get("text") or "").strip()
    for did in d.get("anhaenge") or []:
        f = db.holen("dateien", did)
        if f:
            text += f"\n\n[Angehängt: {f['name']}]\n{(f.get('text') or '')[:20000]}"
            if d.get("projekt_id"):
                db.ausfuehren("UPDATE dateien SET projekt_id=? WHERE id=?", (d["projekt_id"], did))
    if not text:
        raise HTTPException(400, "Es gibt nichts zu erfassen.")
    pid = d.get("projekt_id") if db.holen("projekte", d.get("projekt_id") or "") else None
    v = stab.aus_text(text, quelle="eingabe", projekt_id=pid, titel=(d.get("text") or "Erfasst")[:80])
    stab.wecken()
    return {"ok": True, "vorgang_id": v["id"]}


@router.post("/rueckgaengig/{pid}")
async def rueckgaengig(pid: int):
    r = db.rueckgaengig(pid)
    if not r.get("ok"):
        raise HTTPException(409, r.get("grund"))
    p = db.eine("SELECT vorgang_id FROM protokoll WHERE id=?", (pid,))
    if p and p.get("vorgang_id"):
        db.ereignis(p["vorgang_id"], "du", "info", "Eine Änderung des Teams zurückgenommen.")
    return r


# ================================================================ Projects
@router.get("/projekte")
async def projekte(alle: int = 0):
    sql = ("SELECT p.*, "
           "(SELECT COUNT(*) FROM aufgaben a WHERE a.projekt_id=p.id AND a.status!='erledigt' AND a.archiviert=0) AS offen, "
           "(SELECT COUNT(*) FROM aufgaben a WHERE a.projekt_id=p.id AND a.status='erledigt') AS erledigt, "
           "(SELECT COUNT(*) FROM notizen n WHERE n.projekt_id=p.id) AS notizen, "
           "(SELECT COUNT(*) FROM ergebnisse r WHERE r.projekt_id=p.id) AS ergebnisse, "
           "(SELECT MAX(geaendert) FROM vorgaenge v WHERE v.projekt_id=p.id) AS bewegung, "
           # Etwas mehr Stand auf der Kachel (19.10.2026): naechste Faelligkeit, Ueberfaelliges, ob gerade gearbeitet wird.
           "(SELECT a.faellig || '|' || a.titel FROM aufgaben a WHERE a.projekt_id=p.id AND a.status!='erledigt' AND a.archiviert=0 "
           " AND COALESCE(a.faellig,'')!='' ORDER BY a.faellig LIMIT 1) AS naechste, "
           "(SELECT COUNT(*) FROM aufgaben a WHERE a.projekt_id=p.id AND a.status!='erledigt' AND a.archiviert=0 "
           " AND COALESCE(a.faellig,'')!='' AND a.faellig < date('now','localtime')) AS ueberfaellig, "
           "(SELECT COUNT(*) FROM vorgaenge v WHERE v.projekt_id=p.id AND v.stand IN ('eingeordnet','in_arbeit','pruefung')) "
           " + (SELECT COUNT(*) FROM langlaeufe l WHERE l.projekt_id=p.id AND l.stand NOT IN ('fertig','abgebrochen','angehalten')) AS laeuft "
           "FROM projekte p" + ("" if alle else " WHERE p.status!='archiviert'") + " ORDER BY p.sortierung, p.name")
    return {"projekte": db.alle(sql),
            "kategorien": [z["kategorie"] for z in db.alle("SELECT DISTINCT kategorie FROM projekte WHERE COALESCE(kategorie,'')!='' ORDER BY kategorie")]}


@router.post("/projekte")
async def projekt_neu(request: Request):
    d = await _koerper(request)
    _pflicht(d, "name")
    pid = db.neue_id("p")
    db.anlegen("projekte", {"id": pid, "name": d["name"].strip()[:80], "farbe": d.get("farbe") or "#2C6BB3",
                            "status": "aktiv", "start": time.strftime("%Y-%m-%d"), "ziel": d.get("ziel") or "",
                            "eltern_id": d.get("eltern_id"), "fruehere_namen": [], "kategorie": str(d.get("kategorie") or "").strip()[:40],
                            "sortierung": int(db.wert("SELECT COALESCE(MAX(sortierung),0)+1 FROM projekte") or 0),
                            "erstellt": time.time(), "geaendert": time.time()})
    return db.holen("projekte", pid)


@router.patch("/projekte/{pid}")
async def projekt_aendern(pid: str, request: Request):
    d = await _koerper(request)
    p = db.holen("projekte", pid)
    if not p:
        raise HTTPException(404, "Projekt nicht gefunden")
    erlaubt = {k: d[k] for k in ("name", "farbe", "status", "ziel", "ende", "eltern_id", "leitung", "sortierung", "kategorie") if k in d}
    if "kategorie" in erlaubt:
        erlaubt["kategorie"] = str(erlaubt["kategorie"] or "").strip()[:40]
    if "farbe" in erlaubt and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(erlaubt["farbe"] or "")):
        raise HTTPException(400, "Farbe als #RRGGBB.")
    if "name" in erlaubt and erlaubt["name"] != p["name"]:
        # Alter Name wird gemerkt -- Jason findet das Projekt auch unter dem alten Namen
        # (Veiko benannte EVE in BVE um: "dadurch darf nichts kaputtgehen").
        erlaubt["fruehere_namen"] = list(dict.fromkeys((p.get("fruehere_namen") or []) + [p["name"]]))
    erlaubt["geaendert"] = time.time()
    return db.aendern("projekte", pid, erlaubt)


@router.post("/projekte/{pid}/unterlagen")
async def projekt_unterlagen(pid: str, request: Request):
    """Unterlagen ans Team: Dateien sind schon hochgeladen (/dateien), hier wird
    daraus ein Case mit festem Auftrag -- Relevanz pruefen, Auswirkungen, Arbeitsergebnisse."""
    d = await _koerper(request)
    ids = [str(x) for x in (d.get("dateien") or [])][:10]
    if not ids:
        raise HTTPException(400, "Häng mindestens eine Datei an.")
    try:
        v = stab.unterlagen_an_team(pid, ids, str(d.get("hinweis") or "").strip()[:2000])
    except ValueError as e:
        raise HTTPException(404, str(e))
    stab.wecken()
    return {"ok": True, "vorgang_id": v["id"]}


@router.post("/projekte/reihenfolge")
async def projekt_reihenfolge(request: Request):
    d = await _koerper(request)
    for i, pid in enumerate(d.get("ids") or []):
        db.ausfuehren("UPDATE projekte SET sortierung=? WHERE id=?", (i, pid))
    return {"ok": True}


@router.get("/projekte/{pid}")
async def projekt(pid: str):
    p = db.holen("projekte", pid)
    if not p:
        raise HTTPException(404, "Projekt nicht gefunden")
    return {
        "projekt": p,
        "aufgaben": db.alle("SELECT * FROM aufgaben WHERE projekt_id=? AND archiviert=0 ORDER BY status='erledigt', "
                            "(faellig='' OR faellig IS NULL), faellig, prio, erstellt DESC", (pid,)),
        "notizen": db.alle("SELECT id, titel, datum, kurz, substr(text,1,600) AS text, quelle, erstellt FROM notizen "
                           "WHERE projekt_id=? ORDER BY erstellt DESC LIMIT 100", (pid,)),
        "ergebnisse": [{**r, "wer_name": stab.rollen_name(r["rolle"]), "kurztitel": kurztitel(r)} for r in
                       db.alle("SELECT r.id, r.titel, r.form, r.rolle, r.pruefung, r.ansicht, r.erstellt, r.vorgang_id, "
                               "v.titel AS vorgang_titel FROM ergebnisse r LEFT JOIN vorgaenge v ON v.id=r.vorgang_id "
                               "WHERE r.projekt_id=? ORDER BY r.erstellt DESC", (pid,))],
        "vorgaenge": db.alle("SELECT id, titel, stand, einordnung, geaendert FROM vorgaenge WHERE projekt_id=? "
                             "ORDER BY geaendert DESC LIMIT 60", (pid,)),
        "dateien": db.alle("SELECT id, name, typ, groesse, erstellt FROM dateien WHERE projekt_id=? ORDER BY erstellt DESC", (pid,)),
        "unterprojekte": db.alle("SELECT id, name FROM projekte WHERE eltern_id=?", (pid,)),
        # Zugeordnete Gespraeche und Langlaeufer (17.10.2026).
        "gespraeche": gespraeche_von(pid),
        "langlaeufe": _langlaeufe_von(pid),
        "auftraege": _auftraege_von(pid),
    }


# ================================================================ Aufgaben
@router.get("/aufgaben")
async def aufgaben(projekt: str = "", status: str = "offen", q: str = ""):
    sql = ("SELECT a.*, p.name AS projekt_name, p.farbe AS projekt_farbe FROM aufgaben a "
           "LEFT JOIN projekte p ON p.id=a.projekt_id WHERE a.archiviert=0")
    args: list[Any] = []
    if status == "offen":
        sql += " AND a.status!='erledigt'"
    elif status == "erledigt":
        sql += " AND a.status='erledigt'"
    if projekt == "_ohne":
        sql += " AND a.projekt_id IS NULL"
    elif projekt:
        sql += " AND a.projekt_id=?"
        args.append(projekt)
    if q:
        sql += " AND a.titel LIKE ?"
        args.append(f"%{q}%")
    sql += " ORDER BY (a.faellig='' OR a.faellig IS NULL), a.faellig, a.prio, a.erstellt DESC LIMIT 400"
    return {"aufgaben": db.alle(sql, args)}


@router.post("/aufgaben")
async def aufgabe_neu(request: Request):
    d = await _koerper(request)
    _pflicht(d, "titel")
    tid = db.neue_id("t")
    # Unteraufgabe direkt aus der Struktur-Ansicht: Eltern nur aus demselben Projekt.
    eltern = db.holen("aufgaben", d.get("eltern_id") or "") if d.get("eltern_id") else None
    if eltern and eltern["projekt_id"] != (d.get("projekt_id") or None):
        eltern = None
    sortierung = (db.wert("SELECT MAX(sortierung) FROM aufgaben WHERE eltern_id IS ? AND projekt_id IS ?",
                          (eltern["id"] if eltern else None, d.get("projekt_id") or None)) or 0) + 10
    db.anlegen("aufgaben", {"id": tid, "titel": d["titel"].strip()[:300], "projekt_id": d.get("projekt_id") or None,
                            "status": "offen", "prio": int(d.get("prio") or 2), "faellig": d.get("faellig") or "",
                            "notiz": d.get("notiz") or "", "quelle": "du", "erstellt": time.time(), "geaendert": time.time(),
                            "eltern_id": eltern["id"] if eltern else None, "sortierung": sortierung})
    return db.holen("aufgaben", tid)


# Alles zu einer Aufgabe fuer das Aufgabenfenster (17.10.2026, Veiko: "Informationen
# eingeben, zum Langlaeufer machen, Anhaenge mitgeben -- und das auch beim Klick
# auf den Titel"). Nur lesen, was es schon gibt: Unterlagen, Langlaeufer,
# zugeordnete Gespraeche und die Ergebnisse ihres Case.
@router.get("/aufgaben/{tid}")
async def aufgabe_einzeln(tid: str):
    from . import langlauf
    a = db.holen("aufgaben", tid)
    if not a:
        raise HTTPException(404, "Aufgabe nicht gefunden")
    p = db.holen("projekte", a["projekt_id"]) if a.get("projekt_id") else None
    a["projekt_name"] = (p or {}).get("name")
    a["dateien"] = db.alle("SELECT id, name, groesse, erstellt, length(text) AS zeichen FROM dateien WHERE aufgabe_id=? ORDER BY erstellt", (tid,))
    a["langlaeufe"] = [langlauf.ansicht(l) for l in db.alle("SELECT * FROM langlaeufe WHERE json_extract(daten,'$.aufgabe_id')=? "
                                                             "ORDER BY geaendert DESC", (tid,))]
    a["gespraeche"] = [{"id": g["id"], "art": g["art"], "titel": g["titel"], "geaendert": g["geaendert"],
                        "wer": (g.get("kontext") or {}).get("wer") if isinstance(g.get("kontext"), dict) else None}
                       for g in db.alle("SELECT id, art, titel, kontext, geaendert FROM gespraeche WHERE json_extract(kontext,'$.aufgabe_id')=? "
                                        "ORDER BY geaendert DESC LIMIT 20", (tid,))]
    # Ergebnisse aus dem Case der Aufgabe UND aus Ausarbeitungen, die fuer sie
    # angestossen wurden (Talk erkennt den Bezug, 19.10.2026: auftrag.aufgabe_id).
    a["ergebnisse"] = db.alle("SELECT r.id, r.titel, r.form, r.erstellt FROM ergebnisse r LEFT JOIN vorgaenge v ON v.id=r.vorgang_id "
                              "WHERE (r.vorgang_id=? AND ?!='') OR json_extract(v.auftrag,'$.aufgabe_id')=? ORDER BY r.erstellt DESC",
                              (a.get("vorgang_id") or "", a.get("vorgang_id") or "", tid))
    # Was gerade fuer die Aufgabe arbeitet (Recherche, Gespraech) -- wie beim Langlaeufer.
    from . import aktionen
    a["nebenbei"] = aktionen.fuer(aufgabe_id=tid)
    return a


@router.patch("/aufgaben/{tid}")
async def aufgabe_aendern(tid: str, request: Request):
    d = await _koerper(request)
    erlaubt = {k: d[k] for k in ("titel", "status", "prio", "faellig", "start", "notiz", "projekt_id", "archiviert") if k in d}
    erlaubt["geaendert"] = time.time()
    r = db.aendern("aufgaben", tid, erlaubt)
    if not r:
        raise HTTPException(404, "Aufgabe nicht gefunden")
    return r


@router.post("/aufgaben/{tid}/verschieben")
async def aufgabe_verschieben(tid: str, request: Request):
    """Struktur per Ziehen: wo = davor | danach | darunter (als Unteraufgabe) | oben
    (oberste Ebene, ans Ende). Die Geschwister werden neu durchnummeriert; ein Ast
    wandert mit seinen Unteraufgaben. Ein Ast kann nie unter sich selbst landen."""
    d = await _koerper(request)
    wo, ziel_id = str(d.get("wo") or ""), d.get("ziel_id")
    t = db.holen("aufgaben", tid)
    if not t:
        raise HTTPException(404, "Aufgabe nicht gefunden")
    if wo not in ("davor", "danach", "darunter", "oben"):
        raise HTTPException(400, "wo muss davor, danach, darunter oder oben sein")
    ziel = db.holen("aufgaben", ziel_id) if ziel_id else None
    if wo != "oben" and (not ziel or ziel["projekt_id"] != t["projekt_id"]):
        raise HTTPException(400, "Ziel nicht im selben Projekt")
    eltern = None if wo == "oben" else (ziel["id"] if wo == "darunter" else ziel.get("eltern_id"))
    # Zyklus: das neue Eltern-Element darf nicht die Aufgabe selbst oder einer ihrer Nachfahren sein.
    p = eltern
    while p:
        if p == tid:
            raise HTTPException(409, "Eine Aufgabe kann nicht unter sich selbst hängen.")
        p = db.wert("SELECT eltern_id FROM aufgaben WHERE id=?", (p,))
    geschwister = [g["id"] for g in db.alle(
        "SELECT id FROM aufgaben WHERE projekt_id IS ? AND eltern_id IS ? AND archiviert=0 AND id!=? "
        "ORDER BY sortierung, (faellig='' OR faellig IS NULL), faellig, erstellt", (t["projekt_id"], eltern, tid))]
    if wo in ("davor", "danach") and ziel["id"] in geschwister:
        geschwister.insert(geschwister.index(ziel["id"]) + (wo == "danach"), tid)
    else:
        geschwister.append(tid)
    if t.get("eltern_id") != eltern:
        db.aendern("aufgaben", tid, {"eltern_id": eltern, "geaendert": time.time()}, aktion="verschoben")
    for i, gid in enumerate(geschwister):
        db.ausfuehren("UPDATE aufgaben SET sortierung=? WHERE id=?", ((i + 1) * 10, gid))
    return {"ok": True}


@router.delete("/aufgaben/{tid}")
async def aufgabe_loeschen(tid: str):
    # Nicht wirklich loeschen: archivieren. Zurueckholen geht ueber das Protokoll.
    r = db.aendern("aufgaben", tid, {"archiviert": 1, "geaendert": time.time()}, aktion="archiviert")
    if not r:
        raise HTTPException(404, "Aufgabe nicht gefunden")
    return {"ok": True}


# ================================================================ Notizen, Ergebnisse
@router.get("/notizen")
async def notizen(projekt: str = "", q: str = "", ohne: int = 0, grenze: int = 100):
    sql = "SELECT n.id, n.titel, n.datum, n.kurz, substr(n.text,1,400) AS text, n.quelle, n.projekt_id, n.erstellt, p.name AS projekt_name FROM notizen n LEFT JOIN projekte p ON p.id=n.projekt_id WHERE 1=1"
    args: list[Any] = []
    if projekt:
        sql += " AND n.projekt_id=?"
        args.append(projekt)
    if ohne:
        sql += " AND n.projekt_id IS NULL"
    if q:
        sql += " AND (n.text LIKE ? OR n.titel LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY n.erstellt DESC LIMIT ?"
    args.append(min(grenze, 500))
    return {"notizen": db.alle(sql, args)}


@router.get("/notizen/{nid}")
async def notiz(nid: str):
    n = db.holen("notizen", nid)
    if not n:
        raise HTTPException(404, "Notiz nicht gefunden")
    n["vorgaenge"] = db.alle("SELECT id, titel, stand FROM vorgaenge WHERE notiz_id=?", (nid,))
    return n


@router.post("/notizen/{nid}/an-stab")
async def notiz_an_stab(nid: str):
    n = db.holen("notizen", nid)
    if not n:
        raise HTTPException(404, "Notiz nicht gefunden")
    v = stab.vorgang_anlegen(n, n.get("quelle") or "eingabe", projekt_id=n.get("projekt_id"))
    stab.wecken()
    return {"ok": True, "vorgang_id": v["id"]}


@router.patch("/notizen/{nid}")
async def notiz_aendern(nid: str, request: Request):
    d = await _koerper(request)
    r = db.aendern("notizen", nid, {k: d[k] for k in ("projekt_id", "titel") if k in d})
    if not r:
        raise HTTPException(404, "Notiz nicht gefunden")
    return r


@router.get("/ergebnisse/{rid}")
async def ergebnis(rid: str):
    e = db.holen("ergebnisse", rid)
    if not e:
        raise HTTPException(404, "Ergebnis nicht gefunden")
    e["wer_name"] = stab.rollen_name(e["rolle"])
    if e.get("form") == "praesentation":
        from . import folien_stil
        e["stil"] = folien_stil.normal(e.get("stil"))   # leer = die Vorgabe, so steht es auch in der Auswahl
    # Von wem der Stand ist, der gerade gilt: die letzte Ueberarbeitung im
    # Protokoll, sonst der erste Entwurf. Das Fenster zeigt es ueber dem Text --
    # nach drei Fassungen von Neal und Demmis war nicht mehr zu erkennen, welche
    # links steht (Veiko, 16.10.).
    from . import teamchat
    p = db.alle("SELECT wer, zeit, (SELECT COUNT(*) FROM protokoll q WHERE q.tabelle='ergebnisse' AND q.datensatz_id=? "
                "AND q.aktion='überarbeitet' AND q.rueckgaengig=0) AS anzahl FROM protokoll WHERE tabelle='ergebnisse' "
                "AND datensatz_id=? AND aktion='überarbeitet' AND rueckgaengig=0 ORDER BY id DESC LIMIT 1", (rid, rid))
    e["fassung_von"] = ({"wer": p[0]["wer"], "name": teamchat.wer_name(p[0]["wer"]), "zeit": p[0]["zeit"], "nr": p[0]["anzahl"] + 1}
                        if p else {"wer": e["rolle"], "name": e["wer_name"], "zeit": e["erstellt"], "nr": 1})
    v = db.holen("vorgaenge", e.get("vorgang_id") or "") or {}
    e["vorgang_titel"] = v.get("titel")
    e["projekt_name"] = (db.holen("projekte", e.get("projekt_id") or "") or {}).get("name")
    e["kurztitel"] = kurztitel(e)
    from . import aktionen
    e["nebenbei"] = aktionen.fuer(None, rid)   # was gerade an diesem Ergebnis arbeitet (17.10.2026)
    # Ein Langlaeufer-Ergebnis hat seine externe Endpruefung schon im Lauf, und eine
    # Gesamtfassung in einer Antwort wird dort nicht uebernommen (teamchat) -- das
    # Fenster bietet "Abschließend prüfen" deshalb nur ausserhalb von Langlaeufern an.
    from . import langlauf
    e["langlauf_id"] = langlauf.zum_ergebnis(rid)
    try:
        auftrag = json.loads(v.get("auftrag") or "{}") or {}
    except ValueError:
        auftrag = {}
    e["auftrag"] = auftrag.get("auftrag")
    # Wozu das Ergebnis gehoert (23.10.2026, Veiko: "in dieser Ansicht moechte ich auch sehen, zu welchem
    # Projekt oder welcher Aufgabe das gehoert"). Die Aufgabe steht am Case (auftrag.aufgabe_id -- dort suchen
    # sie auch Explorer, Aufgabenfenster und Talk), sonst eine Aufgabe, die der Case angelegt hat.
    pr = db.holen("projekte", e.get("projekt_id") or "") or {}
    e["projekt_farbe"] = pr.get("farbe")
    a = db.holen("aufgaben", str(auftrag.get("aufgabe_id") or "")) if auftrag.get("aufgabe_id") else None
    if not a and e.get("vorgang_id"):
        a = db.eine("SELECT id, titel, status FROM aufgaben WHERE vorgang_id=? ORDER BY erstellt LIMIT 1", (e["vorgang_id"],))
    e["aufgabe"] = {"id": a["id"], "titel": a["titel"], "status": a.get("status")} if a else None
    from . import video
    e["video"] = video.stand(e)
    if e["video"]:
        e["video"].pop("drehbuch", None)
    from . import folienbilder
    fb = folienbilder.stand(e)
    # Fehlen gewuenschte Bilder, rechnet das Oeffnen sie an -- kostet nur
    # Rechenzeit, und wer ein Bild bestellt hat, soll nicht noch klicken
    # muessen. Nach einem gescheiterten Lauf nicht erneut von selbst.
    if fb and fb["gewuenscht"] > fb["vorhanden"] and fb.get("stand") not in ("rechnet", "fehler"):
        if folienbilder.starten(rid):
            fb = folienbilder.stand(db.holen("ergebnisse", rid) or e)
    e["folienbilder"] = fb
    if fb and fb["gewuenscht"]:
        e["ansicht"] = 1
    return e


@router.post("/ergebnisse/{rid}/folienbilder")
async def ergebnis_folienbilder(rid: str, neu: int = 0):
    """Die Bilder einer Praesentation rechnen: fehlende, oder mit neu=1 alle."""
    from . import folienbilder
    e = db.holen("ergebnisse", rid)
    if not e or e.get("form") not in folienbilder.MIT_BILDERN:
        raise HTTPException(404, "Zu dieser Art Ergebnis gibt es keine Bilder")
    n = folienbilder.starten(rid, neu=bool(neu))
    if not n:
        s = folienbilder.stand(e) or {}
        if s.get("stand") == "rechnet" and rid in folienbilder.LAUFEND:
            raise HTTPException(409, "Die Bilder werden gerade gerechnet.")
        if s.get("gewuenscht"):
            return {"ok": True, "bilder": 0}
        raise HTTPException(409, "Im Ergebnis steht noch keine Zeile 'Bild: …' -- im Chat rechts um Bilder bitten.")
    return {"ok": True, "bilder": n}


@router.post("/ergebnisse/{rid}/video")
async def ergebnis_video_starten(rid: str):
    """Video (neu) rechnen -- nach einem Abbruch oder nach einem ueberarbeiteten Drehbuch."""
    from . import video
    if not db.holen("ergebnisse", rid):
        raise HTTPException(404, "Ergebnis nicht gefunden")
    if not video.starten(rid):
        raise HTTPException(409, "Läuft schon, oder im Ergebnis steht kein lesbares Drehbuch (```json mit szenen).")
    return {"ok": True}


@router.get("/ergebnisse/{rid}/video")
async def ergebnis_video(rid: str, download: int = 0):
    from . import video
    p = video.datei(rid)
    if not re.fullmatch(r"r[0-9a-f]{10}", rid) or not p.is_file():
        raise HTTPException(404, "Kein Video zu diesem Ergebnis")
    kopf = {"X-Content-Type-Options": "nosniff"}
    if download:
        e = db.holen("ergebnisse", rid) or {}
        from . import dokumente
        return FileResponse(p, media_type="video/mp4", filename=dokumente.dateiname(e.get("titel") or "Video", "mp4"), headers=kopf)
    return FileResponse(p, media_type="video/mp4", headers=kopf)


@router.get("/ergebnisse/{rid}/datei")
async def ergebnis_datei(rid: str, format: str = "docx"):
    """Jedes Ergebnis als Word, PowerPoint, Markdown oder HTML herunterladen."""
    from . import dokumente
    e = db.holen("ergebnisse", rid)
    if not e:
        raise HTTPException(404, "Ergebnis nicht gefunden")
    fmt = format if format in dokumente.FORMATE else "docx"
    text = e.get("inhalt") or ""
    if e.get("form") == "webseite" and fmt == "html" and stab.ansicht_html(e):
        roh = stab.ansicht_html(e).encode("utf-8")
    elif fmt == "docx":
        roh = dokumente.zu_docx(e["titel"], text, rid)
    elif fmt == "pptx":
        roh = dokumente.zu_pptx(e["titel"], text, rid, e.get("stil"))
    elif fmt == "html":
        roh = dokumente.zu_html(e["titel"], text, rid).encode("utf-8")
    else:
        roh = text.encode("utf-8")
    typen = {"docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
             "html": "text/html; charset=utf-8", "md": "text/markdown; charset=utf-8"}
    name = dokumente.dateiname(e["titel"], fmt)
    return Response(roh, media_type=typen[fmt], headers={"Content-Disposition": f"attachment; filename=\"{name}\"",
                                                         "X-Content-Type-Options": "nosniff"})


@router.get("/praesentation/stile")
async def praesentation_stile():
    from . import folien_stil
    return {"stile": folien_stil.liste(), "vorgabe": folien_stil.vorgabe()}


@router.post("/ergebnisse/{rid}/stil")
async def ergebnis_stil(rid: str, request: Request):
    """Den Stil einer fertigen Praesentation umschalten. Gerechnet wird nichts neu:
    Ansicht und PowerPoint entstehen bei jedem Abruf aus dem Markdown."""
    from . import folien_stil
    e = db.holen("ergebnisse", rid)
    if not e:
        raise HTTPException(404, "Ergebnis nicht gefunden")
    stil = await _stil_aus(await _koerper(request))
    if stil is None:
        raise HTTPException(400, "Unbekannter Stil")
    db.aendern("ergebnisse", rid, {"stil": stil}, wer="du")
    return {"ok": True, "stil": folien_stil.normal(stil)}


@router.get("/ueberblick")
async def ueberblick_daten():
    """Das Ueberblick-Fenster (ueberblick.py, 22.10.2026): die neuesten Ergebnisse in DER
    Reihenfolge, in der Talk sie nummeriert, dazu die Lage in Kurzform."""
    from . import ueberblick
    eintraege = ueberblick.liste()
    l = ueberblick.lage()
    return {"ergebnisse": eintraege, **l, "satz": ueberblick.satz(eintraege, l)}


@router.get("/ergebnisse/{rid}/vorschaubild")
async def ergebnis_vorschaubild(rid: str):
    """Das erste gerechnete Bild eines Ergebnisses, verkleinert -- fuer die Kacheln im Ueberblick."""
    from . import ueberblick
    e = db.holen("ergebnisse", rid) if re.fullmatch(r"r[0-9a-f]{10}", rid) else None
    p = ueberblick.erstes_bild(e) if e else None
    if not p:
        raise HTTPException(404, "Kein Bild")
    from io import BytesIO
    from PIL import Image
    b = Image.open(p).convert("RGB")
    b.thumbnail((640, 640))
    out = BytesIO()
    b.save(out, "JPEG", quality=80)
    return Response(out.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


@router.get("/ergebnisse/{rid}/ansicht")
async def ergebnis_ansicht(rid: str, kurz: int = 0):
    e = db.holen("ergebnisse", rid)
    if e and kurz:
        # Kachel im Ueberblick: nur die erste Seite bzw. Folie -- ein ganzes Buch (593.000 Zeichen)
        # in zwoelf verkleinerten Rahmen haette das iPad minutenlang beschaeftigt.
        text = e.get("inhalt") or ""
        if e.get("form") == "praesentation":
            from . import folien
            teile = folien.teilen(text)
            text = teile[0] if teile else text[:3000]
        elif e.get("form") != "webseite":
            text = text[:5000]
        e = {**e, "inhalt": text}
    h = stab.ansicht_html(e) if e else None
    if not h:
        raise HTTPException(404, "Keine Ansicht zu diesem Ergebnis")
    # Escape im Rahmen erreicht das Cockpit sonst nicht -- das Fenster blieb
    # offen, sobald man in die Vorschau geklickt hatte. Nur in der Ansicht,
    # nicht im Download: die Datei soll aussehen wie geliefert.
    h += ESC_WEITERGEBEN
    return Response(h, media_type="text/html; charset=utf-8", headers=SANDBOX)


ESC_WEITERGEBEN = ("<script>document.addEventListener('keydown',function(e){if(e.key==='Escape')"
                   "parent.postMessage({vvecEsc:1},'*')});"
                   # "Scroll runter" per Sprache (22.10.2026): der Rahmen ist abgeschottet (sandbox ohne
                   # same-origin), das Cockpit kommt nicht hinein -- es schickt eine Nachricht, die Seite scrollt selbst.
                   "window.addEventListener('message',function(e){var r=e.data&&e.data.vvecScroll;if(!r)return;"
                   "var s=document.scrollingElement||document.documentElement,h=window.innerHeight*0.8,v=s.scrollTop;"
                   "var z=r==='runter'?v+h:r==='hoch'?v-h:r==='anfang'?0:s.scrollHeight;"
                   "s.scrollTo({top:z,behavior:'smooth'});setTimeout(function(){if(s.scrollTop===v)s.scrollTop=z;},700);"
                   "});</script>")


# ================================================================ Gedaechtnis, Team, Einstellungen
@router.get("/gedaechtnis")
async def gedaechtnis():
    return {"eintraege": db.alle("SELECT * FROM gedaechtnis ORDER BY art, begriff")}


@router.post("/gedaechtnis")
async def gedaechtnis_neu(request: Request):
    d = await _koerper(request)
    _pflicht(d, "begriff", "bedeutung")
    gid = db.neue_id("g")
    db.anlegen("gedaechtnis", {"id": gid, "art": d.get("art") or "begriff", "begriff": d["begriff"].strip()[:80],
                               "bedeutung": d["bedeutung"].strip()[:300], "bestaetigt": 1, "quelle": "du",
                               "erstellt": time.time()})
    return db.holen("gedaechtnis", gid)


@router.patch("/gedaechtnis/{gid}")
async def gedaechtnis_aendern(gid: str, request: Request):
    d = await _koerper(request)
    return db.aendern("gedaechtnis", gid, {k: d[k] for k in ("art", "begriff", "bedeutung") if k in d})


@router.delete("/gedaechtnis/{gid}")
async def gedaechtnis_loeschen(gid: str):
    return {"ok": db.loeschen("gedaechtnis", gid)}


@router.get("/team")
async def team():
    heute = time.time() - 86400
    mitglieder = db.alle("SELECT * FROM team ORDER BY reihenfolge")
    for m in mitglieder:
        m["heute"] = db.wert("SELECT COUNT(DISTINCT vorgang_id) FROM ereignisse WHERE wer=? AND zeit>?", (m["id"], heute))
        m["ergebnisse"] = db.wert("SELECT COUNT(*) FROM ergebnisse WHERE rolle=?", (m["id"],))
        m["auftrag_kurz"] = (m.get("auftrag") or "")[:400]
        m.pop("auftrag", None)
    lauf = stab.ZUSTAND.get("laeuft") or {}
    return {"team": mitglieder, "laeuft": lauf, "modelle": await llm.installierte_modelle(),
            "neo_laeuft": any(not j["fertig"] for j in neo.JOBS.values()),
            "externe": await teamchat.externe_liste()}


# Eigener Praefix /teamchat statt /team/chat: GET /team/{rid} wuerde "chat"
# sonst als Mitglied nehmen.
@router.patch("/teamchat/extern/{xid}")
async def extern_modell(xid: str, request: Request):
    if xid not in teamchat.EXTERNE:
        raise HTTPException(404, "Unbekannt")
    d = await _koerper(request)
    w = db.einstellung("extern_modelle", {}) or {}
    w[xid] = str(d.get("modell") or "")[:80]
    db.einstellung_setzen("extern_modelle", w)
    return {"ok": True}


@router.get("/teamchat")
async def teamchat_liste(wer: str = "", ergebnis_id: str = "", langlauf_id: str = ""):
    return {"gespraeche": teamchat.gespraeche(wer or None, ergebnis_id or None, langlauf_id or None)}


@router.get("/teamchat/{gid}")
async def teamchat_holen(gid: str):
    g = db.holen("gespraeche", gid)
    if not g or g["art"] != "team":
        raise HTTPException(404, "Gespräch nicht gefunden")
    return {"gespraech": g, "nachrichten": db.alle("SELECT * FROM nachrichten WHERE gespraech_id=? ORDER BY id", (gid,)),
            "laeuft": _laeuft_oeffentlich(gid)}


@router.delete("/teamchat/{gid}")
async def teamchat_weg(gid: str):
    # Nicht loeschen, nur aus der Liste nehmen -- wie beim Board.
    db.ausfuehren("UPDATE gespraeche SET art='team-archiv' WHERE id=? AND art='team'", (gid,))
    return {"ok": True}


# Gespraeche, deren Antwort gerade auf dem Server entsteht: gespraech_id -> Stand.
# Gemessen am 16.10.: Veiko schrieb Annie zu ihrer Praesentation, schloss das
# Fenster, und es kam nie eine Antwort -- StreamingResponse bricht den Erzeuger
# ab, sobald der Browser die Verbindung schliesst, und mit ihm die ganze Arbeit.
# Bei gruendlichen Antworten (Minuten) ist das kein Randfall, sondern der Normalfall.
GESPRAECH_LAEUFT: dict[str, dict[str, Any]] = {}
_HINTERGRUND: set = set()


def _im_hintergrund(erzeuger, art: str, wer: str = "") -> StreamingResponse:
    """Laesst einen Antwort-Erzeuger als eigene Aufgabe laufen und reicht seine
    Ereignisse nur DURCH. Schliesst der Browser, laeuft die Aufgabe zu Ende und
    speichert ihre Antwort wie sonst auch; beim Wiederoeffnen ist sie da."""
    schlange: asyncio.Queue = asyncio.Queue()
    stand: dict[str, Any] = {"art": art, "wer": wer, "start": time.time(), "text": "", "status": ""}

    async def pumpe():
        gid = None
        # Veiko wartet auf diese Antwort: Langlaeufer und Pipeline weichen (llm.vorrang).
        # Talk und Board rechnen auf dem Talk-Modell: nur Hintergrund auf DEMSELBEN Modell weicht
        # (20.10.2026); der Team-Chat nutzt das Modell des Mitglieds und nimmt Vorrang fuer alle.
        vorrang = llm.vorrang(await llm.talk_modell() if art in ("talk", "board") else None)
        vorrang.__enter__()
        try:
            async for e in erzeuger:
                if e.get("typ") == "start" and e.get("gespraech_id"):
                    gid = e["gespraech_id"]
                    GESPRAECH_LAEUFT[gid] = stand
                    llm.ZWECK.set("gespraech:" + gid)   # Current Actions: welche Anfrage gehoert hierher
                elif e.get("typ") == "text":
                    stand["text"] += e.get("t") or ""
                elif e.get("typ") == "status":
                    stand["status"] = e.get("text") or ""
                elif e.get("typ") == "wer":
                    # Ein Externer uebernimmt im selben Gespraech (teamchat.senden mit extern).
                    stand.update(wer=e.get("wer") or wer, text="", status="")
                schlange.put_nowait(e)
        except Exception as f:  # noqa: BLE001 -- der Grund soll beim Browser ankommen, nicht nur im Journal
            schlange.put_nowait({"typ": "fehler", "text": f"{f.__class__.__name__}: {f}"})
        finally:
            vorrang.__exit__()
            if gid:
                GESPRAECH_LAEUFT.pop(gid, None)
                llm.WAS_ZWECK.pop("gespraech:" + gid, None)
            schlange.put_nowait(None)

    aufgabe = asyncio.create_task(pumpe())
    _HINTERGRUND.add(aufgabe)
    aufgabe.add_done_callback(_HINTERGRUND.discard)
    stand["_aufgabe"] = aufgabe   # fuer "Stopp"; wird beim Ausliefern herausgefiltert

    async def strom():
        while True:
            e = await schlange.get()
            if e is None:
                break
            yield json.dumps(e, ensure_ascii=False) + "\n"
    return StreamingResponse(strom(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _laeuft_oeffentlich(gid: str) -> dict[str, Any] | None:
    s = GESPRAECH_LAEUFT.get(gid)
    return {k: v for k, v in s.items() if not k.startswith("_")} if s else None


@router.post("/gespraech/{gid}/abbrechen")
async def gespraech_abbrechen(gid: str):
    """"Stopp" im Browser haelt die Arbeit wirklich an -- seit sie im Hintergrund
    weiterlaeuft, wuerde ein blosses Trennen der Verbindung nichts mehr stoppen."""
    s = GESPRAECH_LAEUFT.get(gid)
    if s and s.get("_aufgabe"):
        s["_aufgabe"].cancel()
        return {"ok": True}
    return {"ok": False}


@router.post("/teamchat/senden")
async def teamchat_senden(request: Request):
    d = await _koerper(request)
    text = str(d.get("text") or "").strip()
    dateien = [str(x) for x in (d.get("dateien") or [])][:8]
    if not text and not dateien:
        raise HTTPException(400, "Es fehlt die Nachricht.")
    kontext = {"projekt_id": d.get("projekt_id") or None, "ergebnis_id": d.get("ergebnis_id") or None,
               "langlauf_id": d.get("langlauf_id") or None}
    wer = str(d.get("wer") or "")
    # extern: die Externen, die Veiko in DIESER Nachricht dazuholt UND fuer die er im
    # Fenster die Kosten freigegeben hat. Ohne diese Liste ruft der Server keinen an.
    extern = [str(x) for x in (d.get("extern") or []) if str(x) in teamchat.EXTERNE][:3]
    return _im_hintergrund(teamchat.senden(d.get("gespraech_id"), wer, text or "(siehe Anhang)", dateien, kontext,
                                           schnell=bool(d.get("schnell")), extern=extern,
                                           extern_danach=bool(d.get("extern_danach"))), "team", wer)


@router.get("/team/{rid}")
async def team_mitglied(rid: str):
    m = db.holen("team", rid)
    if not m:
        raise HTTPException(404, "Mitglied nicht gefunden")
    m["zuletzt"] = db.alle("SELECT e.vorgang_id, e.art, e.text, e.zeit, v.titel FROM ereignisse e "
                           "LEFT JOIN vorgaenge v ON v.id=e.vorgang_id WHERE e.wer=? ORDER BY e.id DESC LIMIT 15", (rid,))
    return m


@router.patch("/team/{rid}")
async def team_aendern(rid: str, request: Request):
    d = await _koerper(request)
    r = db.aendern("team", rid, {k: d[k] for k in ("modell", "aktiv", "auftrag") if k in d})
    if not r:
        raise HTTPException(404, "Mitglied nicht gefunden")
    return r


@router.post("/postfach/abrufen")
async def postfach_abrufen():
    """'Jetzt abrufen' im Cockpit: nicht bis zum naechsten Takt warten."""
    from . import postfach
    if not postfach.eingerichtet():
        raise HTTPException(409, "Das Postfach ist noch nicht eingerichtet.")
    neu = await asyncio.to_thread(postfach.abrufen)
    if neu:
        stab.wecken()
    return {"neu": neu, **postfach.stand()}


@router.get("/einstellungen")
async def einstellungen():
    from . import folien_stil, postfach
    return {"postfach": postfach.stand(), "vertrauen": stab.vertrauen(), "stab_aktiv": stab.stab_aktiv(),
            "stab_ab": db.einstellung("stab_ab"), "letzter_abgleich": db.einstellung("letzter_abgleich"),
            "alt_cockpit": ALT_COCKPIT_URL, "leiste": db.einstellung("leiste", []),
            "talk_stimme": stimme.gewaehlte_stimme(), "stimmen": stimme.STIMMEN,
            "praesentation_stil": folien_stil.vorgabe(), "praesentation_stile": folien_stil.liste(),
            "modelle_nachts_laden": nachtladen.an(), "nachtladen": nachtladen.stand(),
            "explorer_oeffnen": db.einstellung("explorer_oeffnen", "vorschau")}


@router.post("/einstellungen")
async def einstellungen_setzen(request: Request):
    d = await _koerper(request)
    if "vertrauen" in d and isinstance(d["vertrauen"], dict):
        v = stab.vertrauen()
        for k, w in d["vertrauen"].items():
            if k in stab.VERTRAUEN_VORGABE and w in ("selbst", "fragen"):
                v[k] = w
        db.einstellung_setzen("vertrauen", v)
    if "stab_aktiv" in d:
        db.einstellung_setzen("stab_aktiv", bool(d["stab_aktiv"]))
        if d["stab_aktiv"]:
            db.einstellung_setzen("stab_ab", time.time())
    # Reihenfolge der linken Leiste: auf dem Server, damit sie auf jedem Geraet
    # gleich ist. Nur kurze Kennungen; welche es gibt, weiss der Browser --
    # Unbekanntes faellt dort beim Anzeigen heraus, Fehlendes haengt hinten an.
    if "leiste" in d and isinstance(d["leiste"], list):
        ids = [str(x) for x in d["leiste"] if isinstance(x, str) and re.fullmatch(r"[a-z0-9_-]{1,24}", x)]
        db.einstellung_setzen("leiste", list(dict.fromkeys(ids))[:40])
    if d.get("talk_stimme") in stimme.STIMMEN:
        db.einstellung_setzen("talk_stimme", d["talk_stimme"])
    if d.get("praesentation_stil") in ("vveorg", "cockpit"):
        db.einstellung_setzen("praesentation_stil", d["praesentation_stil"])
    if "modelle_nachts_laden" in d:
        db.einstellung_setzen(nachtladen.SCHALTER, bool(d["modelle_nachts_laden"]))
    # Morgenbericht (tagesbericht.py, 23.10.2026): an/aus und Empfaenger -- nur eine gueltige Adresse.
    if "bericht_aktiv" in d:
        db.einstellung_setzen("bericht_aktiv", bool(d["bericht_aktiv"]))
    if isinstance(d.get("bericht_an"), str) and re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[a-z]{2,}", d["bericht_an"].strip(), re.I):
        db.einstellung_setzen("bericht_an", d["bericht_an"].strip())
    # Explorer-Klick (23.10.2026): Vorschau im Cockpit oder gleich das Original in der App.
    if d.get("explorer_oeffnen") in ("vorschau", "app"):
        db.einstellung_setzen("explorer_oeffnen", d["explorer_oeffnen"])
    return await einstellungen()


@router.get("/stimme/probe")
async def stimme_probe(stimme_id: str = ""):
    """Hoerprobe einer Stimme -- zum Auswaehlen in den Einstellungen."""
    if stimme_id not in stimme.STIMMEN:
        raise HTTPException(404, "Unbekannte Stimme")
    try:
        roh = await stimme.sprechen(stimme.PROBE_SATZ, stimme_id)
    except (RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(503, f"Piper antwortet nicht: {e}")
    return Response(roh, media_type="audio/wav")


# ================================================================ Dateien, Stimme
@router.post("/dateien")
async def datei_hoch(datei: UploadFile = File(...), projekt_id: str = "", aufgabe_id: str = ""):
    roh = await datei.read()
    aufgabe = db.holen("aufgaben", aufgabe_id) if aufgabe_id else None
    if aufgabe_id and not aufgabe:
        raise HTTPException(404, "Aufgabe nicht gefunden")
    if aufgabe and not projekt_id:
        projekt_id = aufgabe.get("projekt_id") or ""
    if len(roh) > 50 * 1024 * 1024:
        raise HTTPException(413, "Die Datei ist größer als 50 MB.")
    did = db.neue_id("d")
    name = Path(datei.filename or "datei").name[:120]
    ziel = UPLOADS / f"{did}_{name}"
    ziel.write_bytes(roh)
    text, art, hinweis = "", "", ""
    try:
        from .anhang import _auswerten
        r = _auswerten(name, roh)
        text, art = (r.get("text") or "")[:120000], r.get("art") or ""
    except HTTPException as e:
        hinweis = str(e.detail)
    except Exception as e:  # noqa: BLE001
        hinweis = f"Konnte den Inhalt nicht lesen: {e}"
    db.einfuegen("dateien", {"id": did, "name": name, "typ": datei.content_type or mimetypes.guess_type(name)[0] or "",
                             "groesse": len(roh), "pfad": str(ziel), "text": text,
                             "projekt_id": projekt_id or None, "aufgabe_id": aufgabe_id or None, "erstellt": time.time()})
    return {"id": did, "name": name, "groesse": len(roh), "art": art, "zeichen": len(text),
            "hinweis": hinweis, "pfad": str(ziel)}


# Eine Unterlage von einer Aufgabe loesen (Aufgabenfenster). Geloescht wird
# nichts: die Datei bleibt in den Unterlagen des Projekts.
@router.patch("/dateien/{did}")
async def datei_aendern(did: str, request: Request):
    d = await _koerper(request)
    if not db.holen("dateien", did):
        raise HTTPException(404, "Datei nicht gefunden")
    if "aufgabe_id" in d:
        a = db.holen("aufgaben", d.get("aufgabe_id") or "") if d.get("aufgabe_id") else None
        if d.get("aufgabe_id") and not a:
            raise HTTPException(404, "Aufgabe nicht gefunden")
        db.ausfuehren("UPDATE dateien SET aufgabe_id=? WHERE id=?", (d.get("aufgabe_id") or None, did))
        # Eine Aufgabe bringt ihr Projekt mit (Explorer: "gehört zu …").
        if a and a.get("projekt_id") and "projekt_id" not in d:
            db.ausfuehren("UPDATE dateien SET projekt_id=? WHERE id=?", (a["projekt_id"], did))
    if "projekt_id" in d:
        if d.get("projekt_id") and not db.holen("projekte", d["projekt_id"]):
            raise HTTPException(404, "Projekt nicht gefunden")
        db.ausfuehren("UPDATE dateien SET projekt_id=? WHERE id=?", (d.get("projekt_id") or None, did))
    if "name" in d and str(d.get("name") or "").strip():
        db.ausfuehren("UPDATE dateien SET name=? WHERE id=?", (re.sub(r'[\\/:*?"<>|]', "-", str(d["name"]).strip())[:120], did))
    return {"ok": True}


# Eine Unterlage im Cockpit ansehen statt herunterladen (Explorer, Talk, Aufgabe;
# 19.10.2026): Angaben, Zuordnung und der gelesene Text.
@router.get("/dateien/{did}/info")
async def datei_info(did: str):
    d = db.holen("dateien", did)
    if not d:
        raise HTTPException(404, "Datei nicht gefunden")
    p = db.holen("projekte", d.get("projekt_id") or "") if d.get("projekt_id") else None
    a = db.holen("aufgaben", d.get("aufgabe_id") or "") if d.get("aufgabe_id") else None
    return {"id": d["id"], "name": d["name"], "typ": d.get("typ"), "groesse": d.get("groesse"), "erstellt": d.get("erstellt"),
            "projekt_id": d.get("projekt_id"), "projekt_name": (p or {}).get("name"),
            "aufgabe_id": d.get("aufgabe_id"), "aufgabe_titel": (a or {}).get("titel"),
            "vorhanden": Path(d["pfad"]).is_file(), "text": (d.get("text") or "")[:200000],
            "gekuerzt": len(d.get("text") or "") > 200000}


# Dieselbe Seitenansicht wie bei Ergebnissen (dokumente.zu_html, Seitenbild wie Word) und
# Word als Download -- fuer Unterlagen mit lesbarem Text (19.10.2026).
def _datei_text(did: str) -> tuple[str, str]:
    d = db.holen("dateien", did)
    if not d or not (d.get("text") or "").strip():
        raise HTTPException(404, "Kein lesbarer Text in dieser Unterlage")
    return re.sub(r"\.(md|txt)$", "", d["name"]), d["text"]


@router.get("/dateien/{did}/ansicht")
async def datei_ansicht(did: str):
    from . import dokumente
    titel, text = _datei_text(did)
    return Response(dokumente.zu_html(titel, text) + ESC_WEITERGEBEN, media_type="text/html; charset=utf-8", headers=SANDBOX)


# PowerPoint als Folien (23.10.2026, pptx_ansicht.py): Lage, Text und Bilder jeder Folie
# im richtigen Seitenverhaeltnis -- auch Hochformat. Gezeichnet wird in datei.js.
def _pptx_pfad(did: str) -> str:
    d = db.holen("dateien", did)
    if not d or not Path(d["pfad"]).is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    if not str(d["pfad"]).lower().endswith((".pptx", ".ppsx", ".potx", ".pptm")):
        raise HTTPException(415, "Keine PowerPoint-Datei (nur .pptx; altes .ppt kann das Cockpit nicht lesen)")
    return d["pfad"]


@router.get("/dateien/{did}/folien")
async def datei_folien(did: str):
    from . import pptx_ansicht
    pfad = _pptx_pfad(did)
    try:
        return await asyncio.to_thread(pptx_ansicht.folien, pfad)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Die Folien ließen sich nicht lesen: {e}")


@router.get("/dateien/{did}/folienmedium")
async def datei_folienmedium(did: str, n: str, b: int = 1600):
    from . import pptx_ansicht
    pfad = _pptx_pfad(did)
    try:
        roh, mime = await asyncio.to_thread(pptx_ansicht.medium, pfad, n, b)
    except KeyError:
        raise HTTPException(404, "Bild nicht in der Datei")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"Bild nicht lesbar: {e}")
    return Response(roh, media_type=mime, headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff",
                                                   "Content-Security-Policy": "sandbox"})


@router.get("/dateien/{did}/word")
async def datei_word(did: str):
    from . import dokumente
    titel, text = _datei_text(did)
    name = dokumente.dateiname(titel, "docx")
    return Response(dokumente.zu_docx(titel, text), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f"attachment; filename=\"{name}\""})


# ================================================================ Versionsverlauf (19.10.2026, versionen.py)
@router.get("/versionen")
async def versionen_liste():
    from . import versionen
    return versionen.verlauf()


# ================================================================ Explorer (19.10.2026, explorer.py)
@router.get("/explorer")
async def explorer_liste(q: str = ""):
    from . import explorer
    d = explorer.liste()
    d["im_inhalt"] = explorer.im_inhalt(q) if q else {}
    return d


@router.get("/explorer/vorschau/{art}/{eid}")
async def explorer_vorschau(art: str, eid: str, breite: int = 480):
    """Vorschaubild einer Kachel (explorer.vorschau_bild); 404 heisst: dort steht der Textauszug."""
    from . import explorer
    r = await asyncio.to_thread(explorer.vorschau_bild, art, eid, breite)
    if not r:
        raise HTTPException(404, "Keine Bildvorschau")
    return Response(r[0], media_type=r[1], headers={"Cache-Control": "private, max-age=86400", "X-Content-Type-Options": "nosniff"})


@router.get("/dateien/{did}")
async def datei_holen(did: str, anzeigen: bool = False):
    d = db.holen("dateien", did)
    if not d or not Path(d["pfad"]).is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    # anzeigen=1 (Explorer: Foto, PDF, Ton, Film): im Browser zeigen statt herunterladen -- nur fuer
    # Arten, die kein Skript tragen koennen (kein HTML, kein SVG), sonst liefe fremder Code im Cockpit.
    mime = (d.get("typ") or mimetypes.guess_type(d["name"] or "")[0] or "").lower()
    sicher = anzeigen and mime != "image/svg+xml" and mime.startswith(("image/", "audio/", "video/", "application/pdf"))
    return FileResponse(d["pfad"], filename=d["name"], headers={"X-Content-Type-Options": "nosniff"},
                        media_type=mime if sicher else None, content_disposition_type="inline" if sicher else "attachment")


# Messwerte des Ins-Wort-Fallens (22.10.2026, stimme.lauschen): je Talk-Satz Pegel, Schwelle und
# was daraus wurde. Die Schwellen lassen sich nur an echten Stimmen einstellen -- der Pruefbrowser
# hat kein Mikrofon. Die letzten 60 bleiben, und jede Zeile steht im Journal.
@router.post("/stimme/diagnose")
async def stimme_diagnose(request: Request):
    d = {k: v for k, v in (await _koerper(request)).items() if isinstance(v, (str, int, float, bool)) or v is None}
    d["zeit"] = time.time()
    d["geraet"] = (request.headers.get("user-agent") or "")[:120]
    liste = (db.einstellung("stimme_diagnose", []) or [])[-59:] + [d]
    db.einstellung_setzen("stimme_diagnose", liste)
    print(f"[stimme] einwurf={d.get('einsatz')} spitze={d.get('spitze_vorher')} schwelle={d.get('schwelle_bei_einsatz')} "
          f"mittel={d.get('mittel_ende')} boden={d.get('boden')} ctx={d.get('kontext')} -> {d.get('ergebnis')}", flush=True)
    return {"ok": True}


@router.get("/stimme/diagnose")
async def stimme_diagnose_lesen():
    return {"messungen": db.einstellung("stimme_diagnose", []) or []}


@router.post("/stimme/hoeren")
async def hoeren(datei: UploadFile = File(...)):
    roh = await datei.read()
    try:
        # Veiko hat gerade gesprochen: der Hintergrund gibt die Karte schon fuer
        # Whisper frei, nicht erst fuer die Antwort danach (llm.vorrang).
        with llm.vorrang(await llm.talk_modell()):
            return await stimme.hoeren(roh, stab.whisper_vorlage())
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.post("/stimme/sprechen")
async def sprechen(request: Request):
    d = await _koerper(request)
    llm.vorrang_anstossen(await llm.talk_modell())   # waehrend Talk vorliest, bleibt der Hintergrund (auf dem Talk-Modell) still
    try:
        return Response(await stimme.sprechen(str(d.get("text") or "")), media_type="audio/wav")
    except (RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(503, f"Sprachausgabe nicht erreichbar: {e}")


# ================================================================ Talk
@router.post("/talk/aufwaermen")
async def talk_aufwaermen(request: Request):
    """Talk ist offen (19.10.2026, Veiko: "wenn ich Talk anklicke, sollten die notwendigen
    Modelle sofort geladen und auf Touren gebracht werden"). Drei Dinge gleichzeitig:
    Sprachmodell laden und den festen Teil der Anweisung vorrechnen, Whisper laden, Piper
    einmal sprechen lassen. Der Browser fragt alle paar Minuten erneut, solange Talk offen
    ist -- das haelt das Modell im Speicher. frisch=True (Talk gerade geoeffnet) haelt den
    Hintergrund kurz zurueck, damit der erste Satz nicht hinter einem Team-Schritt ansteht."""
    d = await _koerper(request)
    if d.get("frisch"):
        llm.vorrang_anstossen(await llm.talk_modell())
    t0 = time.time()
    modell, whisper, piper = await asyncio.gather(gespraech.aufwaermen(), stimme.vorwaermen(), stimme.sprechen("Ja."),
                                                  return_exceptions=True)
    def teil(x: Any) -> dict[str, Any]:
        if isinstance(x, BaseException):
            return {"ok": False, "grund": str(x)[:200]}
        return x if isinstance(x, dict) else {"ok": True}
    return {"modell": teil(modell), "whisper": teil(whisper), "piper": teil(piper), "sekunden": round(time.time() - t0, 1)}


@router.post("/talk/senden")
async def talk_senden(request: Request):
    d = await _koerper(request)
    text = str(d.get("text") or "").strip()
    if not text and not d.get("anhaenge"):
        raise HTTPException(400, "Es fehlt der Text.")
    gid = gespraech.gespraech_holen_oder_anlegen(d.get("gespraech_id"), d.get("kontext"))

    async def mit_start():
        yield {"typ": "start", "gespraech_id": gid}
        async for e in gespraech.senden(gid, text, d.get("kontext"), d.get("anhaenge") or [], bool(d.get("stimme")),
                                        schnell=bool(d.get("schnell")), netz=bool(d.get("netz"))):
            yield e
    return _im_hintergrund(mit_start(), "talk")


# ================================================================ BrainStrom und ExO (verfahren.py)
@router.get("/brainstrom")
async def brainstrom_stand():
    from . import verfahren
    return verfahren.bs_stand()


@router.post("/brainstrom/{aktion}")
async def brainstrom_aktion(aktion: str, request: Request):
    from . import verfahren
    d = await _koerper(request)
    try:
        if aktion == "start":
            return verfahren.bs_starten(str(d.get("thema") or ""), d.get("projekt_id"), d.get("anhaenge") or [])
        if aktion == "antwort":
            return verfahren.bs_antworten(str(d.get("text") or ""))
        if aktion == "genug":
            return verfahren.bs_genug()
        if aktion == "weg":
            return verfahren.bs_weg(int(d.get("nummer") if d.get("nummer") is not None else -1))
        if aktion == "pruefen":
            return verfahren.bs_pruefen()
        if aktion == "projekt":
            return verfahren.bs_projekt_setzen(d.get("projekt_id"))
        if aktion == "neu":
            return verfahren.bs_neu()
        if aktion == "ergebnis":
            return verfahren.bs_als_ergebnis()
        if aktion == "uebernehmen":
            return await verfahren.bs_uebernehmen()
        if aktion == "nochmal":
            return verfahren.bs_nochmal()
        if aktion == "fehler-weg":
            return verfahren.fehler_weg("brainstrom")
    except (ValueError, llm.ModellFehler) as e:
        raise HTTPException(409, str(e))
    raise HTTPException(404, "Unbekannte Aktion")


@router.get("/exo")
async def exo_stand():
    from . import verfahren
    return verfahren.exo_stand()


@router.post("/exo/{aktion}")
async def exo_aktion(aktion: str, request: Request):
    from . import verfahren
    d = await _koerper(request)
    try:
        if aktion == "start":
            return verfahren.exo_starten(str(d.get("umfang") or "portfolio"), d.get("projekt_id"))
        if aktion == "neu":
            return verfahren.exo_neu()
        if aktion == "ergebnis":
            return verfahren.exo_als_ergebnis()
        if aktion == "aufgabe":
            return verfahren.exo_aufgabe(str(d.get("text") or ""))
        if aktion == "fehler-weg":
            return verfahren.fehler_weg("exo")
    except ValueError as e:
        raise HTTPException(409, str(e))
    raise HTTPException(404, "Unbekannte Aktion")


# ================================================================ Advisory Board
@router.get("/board")
async def board_uebersicht():
    from . import board
    return board.uebersicht()


@router.post("/board/auffrischen")
async def board_auffrischen(request: Request):
    """Jetzt auffrischen: alle, die aelter als zwei Tage sind (oder eine Person mit id). Laeuft im Hintergrund."""
    from . import board
    d = await _koerper(request)
    if board.LAUF["aktiv"]:
        raise HTTPException(409, "Das Board wird gerade aufgefrischt.")
    asyncio.create_task(board.auffrischen(alle=bool(d.get("alle")), nur_id=str(d.get("id") or "")))
    return {"ok": True}


@router.post("/board/tisch")
async def board_tisch(request: Request):
    from . import board
    d = await _koerper(request)
    ids = [i for i in (d.get("ids") or []) if i in board.NACH_ID]
    db.einstellung_setzen("board_tisch", ids)
    return {"tisch": ids}


@router.get("/board/gespraech/{gid}")
async def board_gespraech(gid: str):
    g = db.holen("gespraeche", gid)
    if not g or g["art"] != "board":
        raise HTTPException(404, "Gespräch nicht gefunden")
    return {"gespraech": g, "nachrichten": db.alle("SELECT * FROM nachrichten WHERE gespraech_id=? ORDER BY id", (gid,)),
            "laeuft": _laeuft_oeffentlich(gid)}


@router.delete("/board/gespraech/{gid}")
async def board_gespraech_weg(gid: str):
    # Nicht loeschen, nur aus der Liste nehmen -- wie ueberall in dieser Fassung.
    db.ausfuehren("UPDATE gespraeche SET art='board-archiv' WHERE id=? AND art='board'", (gid,))
    return {"ok": True}


@router.post("/board/senden")
async def board_senden(request: Request):
    from . import board
    d = await _koerper(request)
    text = str(d.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Es fehlt die Frage.")

    return _im_hintergrund(board.senden(d.get("gespraech_id"), text, d.get("mit") or None, d.get("projekt_id") or None,
                                        schnell=bool(d.get("schnell"))), "board")


@router.get("/talk/gespraeche")
async def talk_liste():
    return {"gespraeche": db.alle("SELECT id, titel, geaendert FROM gespraeche WHERE art='talk' ORDER BY geaendert DESC LIMIT 40")}


@router.get("/talk/{gid}")
async def talk_holen(gid: str):
    g = db.holen("gespraeche", gid)
    if not g:
        raise HTTPException(404, "Gespräch nicht gefunden")
    return {"gespraech": g, "nachrichten": db.alle("SELECT * FROM nachrichten WHERE gespraech_id=? ORDER BY id", (gid,)),
            "laeuft": _laeuft_oeffentlich(gid)}


@router.post("/talk/ausfuehren")
async def talk_ausfuehren(request: Request):
    d = await _koerper(request)
    r = await gespraech.vorschlaege_ausfuehren(int(d.get("nachricht_id") or 0), [int(i) for i in d.get("indizes") or []])
    stab.wecken()
    return {"ergebnisse": r}


# ================================================================ Neo
# ================================================================ Sicherung (23.10.2026, sicherung.py)
@router.get("/sicherung")
async def sicherung_stand():
    from . import sicherung
    s = sicherung.stand()
    s["befehl"] = None if s["eingerichtet"] else sicherung.einrichten_befehl()
    return s


@router.post("/sicherung/jetzt")
async def sicherung_jetzt():
    """Startet denselben Dienst wie der naechtliche Zeitgeber -- eigener Prozess, eigene
    Prioritaet (Nice, IO idle), und er laeuft weiter, auch wenn das Cockpit neu startet."""
    from . import sicherung
    s = sicherung.stand()
    if s.get("laeuft") and time.time() - (s.get("start") or 0) < 7200:
        raise HTTPException(409, "Die Sicherung läuft schon.")
    p = await asyncio.create_subprocess_exec("systemctl", "--user", "start", "--no-block", "vve-cp-r2-sicherung.service",
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, fehler = await p.communicate()
    if p.returncode:
        raise HTTPException(500, f"Konnte die Sicherung nicht starten: {fehler.decode(errors='replace')[:300]}")
    return {"ok": True}


@router.post("/sicherung/schluessel")
async def sicherung_schluessel(request: Request):
    """Den Schluessel zeigen -- nur auf ausdrueckliche Bitte (bestaetigt), damit er im Passwortmanager
    landet. Ohne ihn ist jede Sicherung in OneDrive wertlos, wenn die Platte ausfaellt."""
    from . import sicherung
    d = await _koerper(request)
    if d.get("gesichert"):
        sicherung.schluessel_gesichert()
        return {"ok": True}
    if not d.get("bestaetigt"):
        raise HTTPException(400, "bestaetigt fehlt")
    return {"schluessel": sicherung.schluessel()}


# ================================================================ Nachtplan (23.10.2026, nachtplan.py)
@router.get("/nachtplan")
async def nachtplan_liste():
    from . import nachtplan
    return {"plan": nachtplan.plan()}


@router.post("/nachtplan/{key}")
async def nachtplan_aktion(key: str, request: Request):
    """Von der Daily-Tasks-Seite: {"an": bool} schaltet, {"jetzt": true} startet ausserhalb der Zeit."""
    from . import nachtplan
    d = await _koerper(request)
    try:
        if "an" in d:
            nachtplan.setzen(key, bool(d["an"]))
            return {"ok": True}
        if d.get("jetzt"):
            return {"ok": True, "text": await nachtplan.jetzt(key)}
    except ValueError as e:
        raise HTTPException(409, str(e))
    raise HTTPException(400, "an oder jetzt fehlt")


def _nacht_briefing() -> dict[str, Any] | None:
    """Fuers Briefing (24.10.2026): was heute Nacht lief, und das neueste Briefing je Daily Task der letzten 24 h."""
    from . import daily, nachtplan
    try:
        grenze = time.time() - 24 * 3600
        dailys = [{"id": t["id"], "titel": t["titel"], "ergebnis_id": t["letztes"]["id"], "bewertung": t["letztes"].get("bewertung"),
                   "zeit": t["letztes"]["erstellt"]} for t in daily.liste() if t.get("letztes") and t["letztes"]["erstellt"] > grenze]
        return {"nacht": nachtplan.briefing(), "daily": dailys}
    except Exception:  # noqa: BLE001 -- das Briefing darf nie daran scheitern
        return None


# ================================================================ Morgenbericht (23.10.2026, tagesbericht.py)
@router.get("/tagesbericht")
async def tagesbericht_stand(vorschau: bool = False):
    from . import tagesbericht
    s = tagesbericht.stand()
    if vorschau:
        s["vorschau"] = tagesbericht.bauen()
    return s


@router.post("/tagesbericht/jetzt")
async def tagesbericht_jetzt():
    from . import tagesbericht
    try:
        return await tagesbericht.schicken(erzwingen=True)
    except ValueError as e:
        raise HTTPException(409, str(e))


# ================================================================ RSI (23.10.2026, rsi.py)
# Verbesserungen aus Veikos Gespraechen: Neo schlaegt vor (nur lesend), Dario prueft, Veiko entscheidet.
@router.get("/rsi")
async def rsi_liste():
    from . import rsi
    d = rsi.liste()
    for v in d["vorschlaege"]:
        n = (v.get("daten") or {}).get("neo") or {}
        v["neo_laeuft"] = bool(n.get("gespraech_id") and neo.laufender_job(n["gespraech_id"]))
    from . import neo_lektionen, rsi_serie
    d.update(rsi_serie.uebersicht())
    d["lektionen"] = neo_lektionen.liste()      # was Dario Neo beigebracht hat (24.10.2026)
    return d


@router.delete("/neo/lektionen/{lid}")
async def neo_lektion_loeschen(lid: str):
    from . import neo_lektionen
    if not neo_lektionen.loeschen(lid):
        raise HTTPException(404, "Diese Regel gibt es nicht.")
    return {"ok": True}


@router.post("/rsi/lauf")
async def rsi_lauf():
    from . import rsi
    if not rsi.starten(von_hand=True):
        raise HTTPException(409, "RSI läuft schon.")
    return {"ok": True}


@router.post("/rsi/einstellungen")
async def rsi_einstellungen(request: Request):
    from . import rsi
    d = await _koerper(request)
    if "an" in d:
        db.einstellung_setzen("rsi_aktiv", bool(d["an"]))
    if "dario_auto" in d:
        db.einstellung_setzen("rsi_dario_auto", bool(d["dario_auto"]))
    if "budget" in d:
        try:
            db.einstellung_setzen("rsi_budget", round(min(20.0, max(0.0, float(d["budget"]))), 2))
        except (TypeError, ValueError):
            raise HTTPException(400, "Budget muss eine Zahl sein.")
    return rsi.liste()


# ---- RSI-Serie (23.10.2026, rsi_serie.py): mehrere Punkte auswaehlen, auf Widersprueche pruefen,
# nacheinander umsetzen, als Release melden, zuruecknehmen. Diese Routen stehen VOR /rsi/{rid}/{was},
# sonst faenge die allgemeine Route "/rsi/serie/start" als Vorschlag "serie" ab.
@router.post("/rsi/serie/auswahl")
async def rsi_serie_auswahl(request: Request):
    """umsetzen/verwerfen: Kennungen. Ohne bestaetigt=true nur die Schaetzung der Pruefkosten (Kostensperre)."""
    from . import rsi_serie
    d = await _koerper(request)
    umsetzen = [str(x) for x in d.get("umsetzen") or []]
    verwerfen = [str(x) for x in d.get("verwerfen") or []]
    if not d.get("bestaetigt"):
        return {"ok": False, "grund": "bestaetigen", "schaetzung": rsi_serie.schaetzung(umsetzen) if umsetzen else 0}
    try:
        return rsi_serie.auswahl(umsetzen, verwerfen)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/rsi/serie/{was}")
async def rsi_serie_handeln(was: str):
    from . import rsi_serie
    try:
        if was == "start":
            return rsi_serie.starten()
        if was == "abbrechen":
            return rsi_serie.abbrechen()
        if was == "gemeldet":
            rsi_serie.gemeldet()
            return {"ok": True}
    except ValueError as e:
        raise HTTPException(409, str(e))
    raise HTTPException(400, "Unbekannte Aktion")


@router.post("/rsi/release/zuruecknehmen")
async def rsi_zuruecknehmen(request: Request):
    from . import rsi_serie
    d = await _koerper(request)
    r = rsi_serie.zuruecknehmen(d.get("release_id"), d.get("rsi_id"))
    if not r.get("ok"):
        raise HTTPException(409, r.get("grund") or "Ging nicht.")
    return r


@router.post("/rsi/{rid}/{was}")
async def rsi_handeln(rid: str, was: str, request: Request):
    """Veikos Entscheidung je Vorschlag. Was Geld kostet (Dario), braucht bestaetigt=true --
    ohne kommt nur die Schaetzung zurueck (Kostensperre)."""
    from . import rsi
    d = await _koerper(request)
    r = db.holen("rsi", rid)
    if not r:
        raise HTTPException(404, "Vorschlag nicht gefunden")
    if was == "neo":
        return await rsi.neo_beauftragen(rid)
    if was in ("pruefen", "plan"):
        daten = r["daten"] if isinstance(r["daten"], dict) else {}
        s = rsi.schaetzung(rsi.DARIO_RSI_SYSTEM if was == "pruefen" else rsi.DARIO_PLAN_SYSTEM,
                           rsi._vorschlag_text(daten), rsi.AUS_SCHAETZUNG if was == "pruefen" else 4000)
        if not d.get("bestaetigt"):
            return {"ok": False, "schaetzung": round(s, 3), "grund": "bestaetigen"}
        if not rsi.im_hintergrund(rid, was):
            raise HTTPException(409, "Dario arbeitet an diesem Vorschlag schon.")
        return {"ok": True, "laeuft": True}
    if was in ("verwerfen", "erledigt", "zurueck"):
        stand_ = {"verwerfen": "verworfen", "erledigt": "erledigt", "zurueck": "neu"}[was]
        db.ausfuehren("UPDATE rsi SET stand=?, geaendert=? WHERE id=?", (stand_, time.time(), rid))
        return {"ok": True}
    raise HTTPException(400, "Unbekannte Aktion")


@router.get("/neo/gespraeche")
async def neo_liste():
    liste = db.alle("SELECT g.id, g.titel, g.geaendert, (SELECT COUNT(*) FROM nachrichten n WHERE n.gespraech_id=g.id) AS anzahl "
                    "FROM gespraeche g WHERE g.art='neo' ORDER BY g.geaendert DESC LIMIT 100")
    for g in liste:
        g["laeuft"] = neo.laufender_job(g["id"])
    return {"gespraeche": liste}


@router.post("/neo/gespraeche")
async def neo_neu():
    gid = db.neue_id("g")
    db.einfuegen("gespraeche", {"id": gid, "art": "neo", "titel": "Neues Gespräch", "erstellt": time.time(), "geaendert": time.time()})
    return db.holen("gespraeche", gid)


@router.get("/neo/gespraeche/{gid}")
async def neo_gespraech(gid: str):
    g = db.holen("gespraeche", gid)
    if not g or g["art"] != "neo":
        raise HTTPException(404, "Gespräch nicht gefunden")
    return {"gespraech": g, "nachrichten": db.alle("SELECT * FROM nachrichten WHERE gespraech_id=? ORDER BY id", (gid,)),
            "job": neo.laufender_job(gid)}


@router.patch("/neo/gespraeche/{gid}")
async def neo_umbenennen(gid: str, request: Request):
    d = await _koerper(request)
    _pflicht(d, "titel")
    db.ausfuehren("UPDATE gespraeche SET titel=? WHERE id=? AND art='neo'", (d["titel"][:80], gid))
    return {"ok": True}


@router.delete("/neo/gespraeche/{gid}")
async def neo_loeschen(gid: str):
    if neo.laufender_job(gid):
        raise HTTPException(409, "Neo arbeitet in diesem Gespräch noch.")
    # Nicht weg, nur ins Archiv -- ein Gespraech ist eine Akte.
    db.ausfuehren("UPDATE gespraeche SET art='neo-archiv' WHERE id=? AND art='neo'", (gid,))
    return {"ok": True}


@router.post("/neo/{gid}/senden")
async def neo_senden(gid: str, request: Request):
    d = await _koerper(request)
    if not db.holen("gespraeche", gid):
        raise HTTPException(404, "Gespräch nicht gefunden")
    text = str(d.get("text") or "").strip()
    if not text and not d.get("anhaenge"):
        raise HTTPException(400, "Es fehlt der Auftrag.")
    try:
        jid = await neo.senden(gid, text, d.get("anhaenge") or [])
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"job": jid}


@router.get("/neo/job/{jid}")
async def neo_job(jid: str, ab: int = 0):
    return await neo.ereignisse(jid, ab)


@router.post("/neo/job/{jid}/abbrechen")
async def neo_abbrechen(jid: str):
    return {"ok": neo.abbrechen(jid)}


@router.get("/neo/vorschau/{pfad:path}")
async def neo_vorschau(pfad: str):
    ziel = (VORSCHAU_DIR / pfad).resolve()
    try:
        ziel.relative_to(VORSCHAU_DIR.resolve())
    except ValueError:
        raise HTTPException(404, "Nicht gefunden")
    if ziel.is_dir():
        ziel = ziel / "index.html"
    if not ziel.is_file():
        raise HTTPException(404, "Nicht gefunden")
    typ = mimetypes.guess_type(str(ziel))[0] or "text/plain"
    if typ not in ("text/html", "text/css", "application/javascript", "text/javascript", "image/png", "image/jpeg",
                   "image/svg+xml", "image/gif", "image/webp", "application/json"):
        typ = "text/plain"
    return Response(ziel.read_bytes(), media_type=typ, headers=SANDBOX)


@router.get("/neo/export/{name}")
async def neo_export(name: str):
    from .dokumente import EXPORT_DIR
    ziel = (EXPORT_DIR / name).resolve()
    try:
        ziel.relative_to(EXPORT_DIR.resolve())
    except ValueError:
        raise HTTPException(404, "Nicht gefunden")
    if not ziel.is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    return FileResponse(str(ziel), filename=ziel.name, headers={"X-Content-Type-Options": "nosniff"})


@router.get("/neo/vorschauen")
async def neo_vorschauen():
    liste = []
    for p in sorted(VORSCHAU_DIR.glob("*/index.html"), key=lambda x: -x.stat().st_mtime)[:30]:
        liste.append({"name": p.parent.name, "url": f"/api/neo/vorschau/{p.parent.name}/index.html", "zeit": p.stat().st_mtime})
    return {"vorschauen": liste}


# ================================================================ System
@router.get("/system")
async def system():
    out: dict[str, Any] = {"stab": stab.gesundheit(), "stimme": stimme.verfuegbar(), "alt_cockpit": ALT_COCKPIT_URL}
    async with httpx.AsyncClient(timeout=4) as c:
        try:
            r = await c.get(f"{STATUS_URL}/status")
            out["status"] = r.json()
        except (httpx.HTTPError, ValueError):
            out["status"] = None
        # Websuche: /healthz der eigenen SearXNG -- fragt keine Suchmaschine an.
        try:
            r = await c.get(f"{SEARX}/healthz")
            out["websuche"] = {"erreichbar": r.status_code == 200, "code": r.status_code}
        except httpx.HTTPError:
            out["websuche"] = {"erreichbar": False, "code": None}
    out["modelle"] = await llm.installierte_modelle(frisch=True)
    out["geladen"] = await llm.geladene_modelle()
    gesamt, _, frei = shutil.disk_usage("/")
    out["platte"] = {"gesamt": gesamt, "frei": frei}
    out["db"] = {t: db.wert(f"SELECT COUNT(*) FROM {t}") for t in
                 ("projekte", "aufgaben", "notizen", "vorgaenge", "ergebnisse", "gedaechtnis", "gespraeche")}
    out["einstellungen"] = await einstellungen()
    return out


@router.get("/kopf")
async def kopf():
    from . import systeminfo
    return await systeminfo.kopf()


@router.get("/system/details")
async def system_details(frisch: int = 0):
    from . import systeminfo
    d = await systeminfo.gesamt(bool(frisch))
    a = dict(d["auftrag"])
    a["log"] = a.get("log", "")[-8000:]
    d["auftrag"] = a
    return d


@router.post("/system/auftrag")
async def system_auftrag(request: Request):
    from . import systeminfo
    d = await _koerper(request)
    art = str(d.get("art") or "")
    if art == "ollama-update":
        r = await systeminfo.ollama_update_starten()
        if not r["ok"]:
            raise HTTPException(409, r["grund"])
        return r
    if art not in ("updates", "neustart", "ollama-neustart", "caddy-neustart"):
        raise HTTPException(400, "Unbekannter Auftrag")
    if not systeminfo.starten(art):
        raise HTTPException(409, "Es läuft schon ein Auftrag.")
    return {"ok": True}


@router.post("/system/notfall")
async def system_notfall(request: Request):
    """Kill Switch / Safety Shutdown & Reboot -- nur eine Anfrage an den WatchDog."""
    from . import systeminfo
    d = await _koerper(request)
    try:
        return systeminfo.notfall_anfordern(str(d.get("art") or ""))
    except ValueError:
        raise HTTPException(400, "Art muss kill oder neustart sein")
    except (RuntimeError, OSError) as e:
        raise HTTPException(503, str(e))


@router.get("/system/watchdog")
async def system_watchdog():
    from . import systeminfo
    return systeminfo.watchdog()


@router.post("/system/modell-laden")
async def system_modell_laden(request: Request):
    import re as _re
    from . import modellkatalog
    d = await _koerper(request)
    name = str(d.get("name") or "").strip().lower()
    if not _re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,39}:[a-z0-9][a-z0-9._-]{0,39}", name):
        raise HTTPException(400, "Modellname muss familie:ausgabe sein")
    return modellkatalog.laden_starten(name)


@router.get("/system/modell-laden")
async def system_modell_laden_stand():
    from . import modellkatalog
    return {"laden": modellkatalog.LADEN}


# ================================================================ Current Actions
# Alles, was gerade laeuft, an einer Stelle -- mit Pausieren/Abbrechen, wo das
# sicher geht (Veiko, 17.10.2026). Details: aktionen.py.
@router.get("/aktionen")
async def aktionen_liste():
    from . import aktionen
    return aktionen.sammeln(GESPRAECH_LAEUFT, teamchat.wer_name)


@router.post("/aktionen/steuern")
async def aktionen_steuern(request: Request):
    from . import aktionen
    d = await _koerper(request)
    try:
        return aktionen.steuern(str(d.get("id") or ""), str(d.get("aktion") or ""), GESPRAECH_LAEUFT)
    except ValueError as e:
        raise HTTPException(409, str(e))


# Ein Modell entfernen -- nur, wenn es nichts im Cockpit mehr braucht
# (revision.gebraucht_von). Der Ersatz-Weg auf Stab & Modelle: laden, umstellen,
# altes entfernen (Veiko, 17.10.2026).
@router.post("/modelle/entfernen")
async def modelle_entfernen(request: Request):
    from . import revision
    d = await _koerper(request)
    try:
        return await revision.entfernen(str(d.get("name") or ""), bool(d.get("trotzdem")))
    except ValueError as e:
        raise HTTPException(409, str(e))
    except (RuntimeError, httpx.HTTPError) as e:
        raise HTTPException(503, str(e))


# ================================================================ Bilder und Visualisierungen aus dem Gespraech
@router.get("/medien/{jid}")
async def medien_stand(jid: str):
    from . import medien
    s = medien.stand(jid)
    if not s:
        raise HTTPException(404, "Unbekannt")
    return s


@router.get("/medien/datei/{name}")
async def medien_datei(name: str, download: int = 0):
    import re as _re
    from .konfig import MEDIEN_DIR
    if not _re.fullmatch(r"m[0-9a-f]{10}\.(png|svg)", name):
        raise HTTPException(404, "Unbekannt")
    p = MEDIEN_DIR / name
    if not p.is_file():
        raise HTTPException(404, "Unbekannt")
    kopf = {"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'", "X-Content-Type-Options": "nosniff"}
    if download:
        return FileResponse(p, filename=("Bild-" if name.endswith(".png") else "Visualisierung-") + name, headers=kopf)
    return FileResponse(p, headers=kopf)


@router.get("/system/auftrag")
async def system_auftrag_stand():
    from . import systeminfo
    systeminfo.ollama_update_wiederaufnehmen()
    a = dict(systeminfo.AUFTRAG)
    a["log"] = a.get("log", "")[-8000:]
    return a


@router.post("/system/auftrag/schliessen")
async def system_auftrag_schliessen():
    # Ein beendeter Auftrag blieb bis zum naechsten Neustart dieses Dienstes
    # oben stehen -- auf jedem Geraet, auch nach dem Neuladen. Geschlossen wird
    # deshalb hier und nicht im Browser. Ein laufender Auftrag bleibt sichtbar:
    # wer ihn wegklickt, saehe nicht mehr, dass gerade etwas am System passiert.
    from . import systeminfo
    if systeminfo.AUFTRAG.get("laeuft"):
        raise HTTPException(409, "Der Auftrag läuft noch.")
    systeminfo.AUFTRAG.update(art=None, rc=None, start=None, ende=None, log="", fortschritt=None, gestoert=[])
    return {"ok": True}


@router.post("/system/abgleich")
async def abgleich():
    return {"ok": True, "neu": importer.abgleichen()}


@router.post("/system/durchgang")
async def durchgang():
    stab.wecken()
    return {"ok": True}


@router.get("/suche")
async def suche(q: str):
    q = q.strip()
    if len(q) < 2:
        return {"treffer": []}
    like = f"%{q}%"
    t = []
    t += [{"art": "projekt", "id": r["id"], "titel": r["name"]} for r in
          db.alle("SELECT id, name FROM projekte WHERE name LIKE ? OR fruehere_namen LIKE ? LIMIT 6", (like, like))]
    t += [{"art": "vorgang", "id": r["id"], "titel": r["titel"], "unter": r["stand"]} for r in
          db.alle("SELECT id, titel, stand FROM vorgaenge WHERE titel LIKE ? OR einordnung LIKE ? ORDER BY geaendert DESC LIMIT 8", (like, like))]
    t += [{"art": "aufgabe", "id": r["id"], "titel": r["titel"], "unter": r["projekt_id"]} for r in
          db.alle("SELECT id, titel, projekt_id FROM aufgaben WHERE titel LIKE ? AND archiviert=0 LIMIT 8", (like,))]
    t += [{"art": "notiz", "id": r["id"], "titel": r["titel"] or r["kurz"][:60], "unter": r["datum"]} for r in
          db.alle("SELECT id, titel, kurz, datum FROM notizen WHERE text LIKE ? OR titel LIKE ? ORDER BY erstellt DESC LIMIT 8", (like, like))]
    t += [{"art": "ergebnis", "id": r["id"], "titel": r["titel"]} for r in
          db.alle("SELECT id, titel FROM ergebnisse WHERE titel LIKE ? OR inhalt LIKE ? LIMIT 6", (like, like))]
    return {"treffer": t}


# ================================================================ Verbrauch (Token und Kosten)
# Die Seite "AI Consumption" des alten Cockpits, neu (Veiko, 16.10.2026). Dort
# waren die Token geschaetzt (Zeichen / 4) und auch lokale Aufrufe trugen einen
# Preis. Hier: lokale Zahlen exakt von Ollama, kostenlos (eigener Server);
# Cloud-Zahlen exakt vom Anbieter, die KOSTEN nach einer sichtbaren, aenderbaren
# Preistabelle -- Listenpreise aendern sich, und eine still veraltete Zahl waere
# schlimmer als eine, deren Annahme man sieht.
PREISE_VORGABE = {"claude": [5.0, 25.0], "grok": [3.0, 15.0], "gemini": [2.0, 12.0]}   # US-$ je 1 Mio. Token: [Eingabe, Ausgabe]
ANBIETER_NAME = {"ollama": "Lokal (eigener Server)", "claude": "Dario · Claude", "grok": "Elon · Grok", "gemini": "Demmis · Gemini"}


def _preise() -> dict[str, list[float]]:
    p = db.einstellung("verbrauch_preise", {}) or {}
    return {k: [float(x) for x in (p.get(k) or v)] for k, v in PREISE_VORGABE.items()}


def _kosten(anbieter: str, ein: int, aus: int, preise: dict[str, list[float]]) -> float:
    pr = preise.get(anbieter)
    return (ein / 1e6 * pr[0] + aus / 1e6 * pr[1]) if pr else 0.0


@router.get("/verbrauch")
async def verbrauch(von: float = 0, bis: float = 0, projekt: str = ""):
    bis = bis or time.time() + 60
    preise = _preise()
    sql = ("SELECT bereich, anbieter, modell, COUNT(*) AS aufrufe, SUM(tok_ein) AS ein, SUM(tok_aus) AS aus, "
           "SUM(dauer_s) AS dauer, SUM(geschaetzt) AS geschaetzt FROM verbrauch WHERE zeit>=? AND zeit<=?")
    args: list[Any] = [von, bis]
    if projekt:
        sql += " AND projekt_id=?"
        args.append(projekt)
    zeilen = db.alle(sql + " GROUP BY bereich, anbieter, modell", args)
    for z in zeilen:
        z["quelle"] = "neu"
        z["kosten"] = _kosten(z["anbieter"], z["ein"] or 0, z["aus"] or 0, preise)
    # Das alte Cockpit (nur lesen): seine Liste S.usage, Token dort geschaetzt.
    # Projekt-Kennungen des alten Cockpits passen nicht zu den neuen -- mit einem
    # Projektfilter bleibt der alte Bestand deshalb draussen, statt falsch zugeordnet.
    alt: dict[tuple[str, str], dict[str, Any]] = {}
    if not projekt:
        try:
            # Einmal in die eigene Datenbank uebernommen (23.10.2026) -- die Datei des alten Cockpits
            # wird geloescht, der Verbrauch von damals soll in dieser Ansicht bleiben.
            alt_usage = db.einstellung("alt_usage")
            if alt_usage is None and ALT_STATE.is_file():
                alt_usage = json.loads(ALT_STATE.read_text(encoding="utf-8")).get("usage") or []
                db.einstellung_setzen("alt_usage", alt_usage)
            for u in (alt_usage or []):
                ts = (u.get("ts") or 0) / 1000
                if not (von <= ts <= bis):
                    continue
                anb = "ollama" if u.get("provider") == "lokal" else str(u.get("provider") or "")
                k = (str(u.get("op") or "Sonstiges"), anb)
                a = alt.setdefault(k, {"bereich": "Altes Cockpit: " + k[0], "anbieter": anb, "modell": "",
                                       "aufrufe": 0, "ein": 0, "aus": 0, "dauer": 0.0, "geschaetzt": 0, "quelle": "alt"})
                a["aufrufe"] += 1
                a["geschaetzt"] += 1
                a["ein"] += int(u.get("inTok") or 0)
                a["aus"] += int(u.get("outTok") or 0)
        except (OSError, ValueError):
            pass
    for a in alt.values():
        a["kosten"] = _kosten(a["anbieter"], a["ein"], a["aus"], preise)
    alle = zeilen + list(alt.values())
    je_anbieter: dict[str, dict[str, Any]] = {}
    for z in alle:
        j = je_anbieter.setdefault(z["anbieter"], {"anbieter": z["anbieter"], "name": ANBIETER_NAME.get(z["anbieter"], z["anbieter"]),
                                                   "aufrufe": 0, "ein": 0, "aus": 0, "dauer": 0.0, "kosten": 0.0})
        for f in ("aufrufe", "ein", "aus", "dauer", "kosten"):
            j[f] += z[f] or 0
    seit = db.wert("SELECT MIN(zeit) FROM verbrauch")
    return {"zeilen": alle, "je_anbieter": list(je_anbieter.values()), "preise": preise,
            "preise_vorgabe": PREISE_VORGABE, "erfasst_seit": seit,
            "projekte": db.alle("SELECT id, name FROM projekte ORDER BY name")}


@router.post("/verbrauch/preise")
async def verbrauch_preise(request: Request):
    d = await _koerper(request)
    neu = {}
    for k in PREISE_VORGABE:
        v = d.get(k)
        if isinstance(v, list) and len(v) == 2:
            try:
                neu[k] = [max(0.0, float(v[0])), max(0.0, float(v[1]))]
            except (TypeError, ValueError):
                raise HTTPException(400, f"Preis für {k} ist keine Zahl.")
    db.einstellung_setzen("verbrauch_preise", neu)
    return {"preise": _preise()}


# ================================================================ Usage (19.10.2026, usage.py)
# Die Seite "Usage": dieselben Buchungen wie /verbrauch, aber nach Projekt, Aufgabe,
# Modell, Rolle, Bereich und Tag -- dazu der Strom aus den Shelly-Zaehlern.
@router.get("/usage")
async def usage_auswertung(von: float = 0, bis: float = 0, projekt: str = "", aufgabe: str = "", modell: str = "",
                           anbieter: str = "", rolle: str = "", art: str = ""):
    from . import usage
    d = usage.auswerten(von, bis, {"projekt": projekt, "aufgabe": aufgabe, "modell": modell, "anbieter": anbieter,
                                   "rolle": rolle, "art": art}, _preise())
    d["strom"] = usage.strom(von, bis or time.time() + 60)
    d["preise"] = _preise()
    d["preise_vorgabe"] = PREISE_VORGABE
    d["anbieter_name"] = ANBIETER_NAME
    return d


@router.post("/usage/strompreis")
async def usage_strompreis(request: Request):
    d = await _koerper(request)
    w = d.get("preis")
    if w in (None, ""):
        db.einstellung_setzen("strompreis", None)
        return {"preis": None}
    try:
        p = round(float(str(w).replace(",", ".")), 4)
    except ValueError:
        raise HTTPException(400, "Der Strompreis ist keine Zahl.")
    if not 0 <= p < 5:
        raise HTTPException(400, "Der Strompreis gilt je kWh in Euro, also etwa 0,30.")
    db.einstellung_setzen("strompreis", p)
    return {"preis": p}


# ================================================================ Modelle (Uebersicht und Empfehlungen)
# Wie die Seite "Modelle" im alten Cockpit (Veiko, 16.10.2026: "ich hatte doch
# im alten Cockpit eine gute Uebersicht zu den Modellen, die installiert sind,
# und ob ich welche durch neue ersetzen sollte"). Eine Seite, vier Fragen:
# was liegt hier, wer nutzt es wirklich, was sollte ich ersetzen, was ist neu.
@router.get("/modelle")
async def modelle_uebersicht(frisch: int = 0):
    from . import modellkatalog, ruf, systeminfo
    s = await systeminfo.status()
    vram = systeminfo._vram_gesamt(s)
    inst_gb = modellkatalog.lokal_gb()
    geladen = {m.get("name"): m for m in await llm.geladene_modelle()}
    team: dict[str, list[str]] = {}
    for t in db.alle("SELECT name, modell FROM team WHERE modell!=''"):
        team.setdefault(t["modell"], []).append(t["name"])
    vor30 = time.time() - 30 * 86400
    nutzung = {z["modell"]: z for z in db.alle(
        "SELECT modell, COUNT(*) AS aufrufe, SUM(tok_ein + tok_aus) AS token, SUM(dauer_s) AS dauer, MAX(zeit) AS zuletzt "
        "FROM verbrauch WHERE art='lokal' AND zeit>? GROUP BY modell", (vor30,))}
    aufgaben_von: dict[str, list[str]] = {}
    for a in modellkatalog.AUFGABEN:
        kand = [modellkatalog._tag(k) for k in a["kandidaten"]]
        bester = next((k for k in kand if k in inst_gb), None)
        if bester:
            aufgaben_von.setdefault(bester, []).append(a["name"])
    installiert = []
    for name, gb in sorted(inst_gb.items(), key=lambda x: -x[1]):
        n = nutzung.get(name) or {}
        installiert.append({"name": name, "gb": gb, "passt": modellkatalog._passt(gb, vram), "team": team.get(name, []),
                            "aufgaben": aufgaben_von.get(name, []), "geladen": name in geladen,
                            "aufrufe": n.get("aufrufe") or 0, "token": n.get("token") or 0, "zuletzt": n.get("zuletzt")})
    try:
        katalog = await modellkatalog.pruefen(bool(frisch))
    except Exception:  # noqa: BLE001
        katalog = None
    try:
        neu = await modellkatalog.neu_bei_ollama(bool(frisch), vram)
    except Exception as e:  # noqa: BLE001
        neu = {"fehler": str(e), "familien": []}
    from .konfig import MODELL_ARBEIT, MODELL_TALK
    modellkatalog.einordnen(neu, inst_gb, db.alle("SELECT id, name, titel, art, modell FROM team WHERE aktiv=1"),
                            {"arbeit": llm.vorgabe("arbeit"), "talk": llm.vorgabe("talk")})
    return {"installiert": installiert, "vram": vram, "frei_gb": ((s or {}).get("disk_gb") or {}).get("free"),
            "empfehlungen": modellkatalog.vorschlaege(katalog, vram) + modellkatalog.neu_vorschlaege(neu, 8),
            "neu": neu, "katalog_stand": katalog and katalog.get("zeit"), "laden": modellkatalog.LADEN,
            "ruf": ruf.ansicht(),
            "erfasst_seit": db.wert("SELECT MIN(zeit) FROM verbrauch WHERE art='lokal'")}


# ================================================================ Langlaeufer
# Ein langes Vorhaben in Etappen, mit Zwischenpruefung durch Dario oder Demmis
# im Rahmen eines Budgets (Veiko, 17.10.2026). Details: langlauf.py.
@router.get("/langlaeufe")
async def langlaeufe_liste(projekt_id: str = ""):
    from . import aktionen, langlauf
    # Was sonst gerade fuer jeden Langlaeufer arbeitet (Recherche, Antwort im
    # Gespraech, Video ...): hier und nicht in langlauf.ansicht, weil Current
    # Actions selbst die Liste liest -- dort waere es eine Schleife.
    liste = [{**l, "nebenbei": aktionen.fuer(l["id"], l.get("ergebnis_id"))} for l in langlauf.liste(projekt_id or None)]
    return {"langlaeufe": liste, "arten": langlauf.ARTEN,
            "rollen": [{"id": r, "name": stab.rollen_name(r)} for r in stab.ROLLEN_FUER_ARBEIT if r != "pmo"],
            "preise": _preise(), "zugang_extern": teamchat.extern_moeglich()}


@router.post("/langlaeufe")
async def langlauf_anlegen(request: Request):
    from . import langlauf
    d = await _koerper(request)
    try:
        return langlauf.anlegen(str(d.get("titel") or ""), str(d.get("auftrag") or ""), str(d.get("art") or "buch"),
                                d.get("projekt_id") or None, str(d.get("pruefer") or "dario"),
                                (3 if d.get("pruef_alle") in (None, "") else int(d.get("pruef_alle"))), float(d.get("budget") or 0), d.get("rolle"), d.get("aufgabe_id") or None,
                                d.get("material"))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))


# Was zu Projekt/Aufgabe schon da ist (zum Ankreuzen) und ein Vorschlag fuer die
# Felder (17.10.2026). Vor /langlaeufe/{lid} stehen lassen, sonst faengt die
# Kennungs-Route "bestand" ab.
@router.get("/langlaeufe/bestand")
async def langlauf_bestand(projekt_id: str = "", aufgabe_id: str = ""):
    from . import langlauf
    return {"bestand": langlauf.bestand(projekt_id or None, aufgabe_id or None)}


@router.post("/langlaeufe/erkennen")
async def langlauf_erkennen(request: Request):
    """Ist dieser Auftrag ein LongRun? Dieselbe Antwort wie fuer Talk und die Pipeline
    (langlauf.gross) -- die Oberflaeche fuehrt keine eigene Regel (19.10.2026)."""
    from . import langlauf
    d = await _koerper(request)
    t = str(d.get("text") or "")
    # Stammt das Ergebnis, an dem gesprochen wird, selbst aus einem LongRun, sagt die Antwort
    # das: dann ist "Kapitel fuer Kapitel ueberarbeiten" (der Weg im Chat) die naheliegende
    # Wahl, ein neuer LongRun die andere (19.10.2026).
    von = None
    lid = langlauf.zum_ergebnis(str(d.get("ergebnis_id"))) if d.get("ergebnis_id") else None
    if lid:
        l = langlauf.holen(lid) or {}
        von = {"id": lid, "titel": l.get("titel"), "etappen": langlauf.ARTEN.get(l.get("art"), {}).get("mehrzahl", "Etappen")}
    return {"gross": langlauf.gross(t), "nachher": bool(langlauf._NACHHER.search(t)), "langlauf_von": von}


@router.post("/langlaeufe/vorschlag")
async def langlauf_vorschlag(request: Request):
    from . import langlauf
    d = await _koerper(request)
    try:
        return await langlauf.vorschlag(d.get("projekt_id") or None, d.get("aufgabe_id") or None, d.get("material"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except llm.ModellFehler as e:
        raise HTTPException(503, f"Kein Vorschlag möglich: {e}")


@router.get("/langlaeufe/{lid}")
async def langlauf_einzeln(lid: str):
    from . import langlauf
    l = langlauf.einzeln(lid)
    if not l:
        raise HTTPException(404, "Langläufer nicht gefunden")
    from . import aktionen
    l["nebenbei"] = aktionen.fuer(l["id"], l.get("ergebnis_id"))
    return l


@router.get("/langlaeufe/{lid}/abschluss")
async def langlauf_abschluss_schaetzen(lid: str, wer: str):
    """Was eine abschliessende externe Pruefung kostet -- fuer die Rueckfrage vor dem Klick."""
    from . import langlauf
    try:
        return langlauf.abschluss_schaetzen(lid, wer)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/langlaeufe/{lid}/abschluss")
async def langlauf_abschluss(lid: str, request: Request):
    from . import langlauf
    d = await _koerper(request)
    try:
        return langlauf.abschluss_starten(lid, str(d.get("wer") or ""))
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/langlaeufe/{lid}/{aktion}")
async def langlauf_steuern(lid: str, aktion: str, request: Request):
    from . import langlauf
    d = await _koerper(request)
    try:
        return langlauf.steuern(lid, aktion, d)
    except (TypeError, ValueError) as e:
        raise HTTPException(409, str(e))


# ================================================================ Modell-Revision
# Das Cockpit sucht selbst nach besseren Modellen und belegt jeden Vorschlag mit
# einer Messung (Veiko, 17.10.2026). Details: revision.py.
REVISION_ZULETZT: dict[str, Any] = {}


@router.get("/revision")
async def revision_uebersicht():
    from . import modellkatalog, revision, ruf, systeminfo
    s = await systeminfo.status()
    vram = systeminfo._vram_gesamt(s)
    inst = modellkatalog.lokal_gb()
    try:
        neu = await modellkatalog.neu_bei_ollama(False, vram)
        modellkatalog.einordnen(neu, inst, db.alle("SELECT id, name, titel, art, modell FROM team WHERE aktiv=1"),
                                {"arbeit": llm.vorgabe("arbeit"), "talk": llm.vorgabe("talk")})
    except Exception:  # noqa: BLE001
        neu = None
    plan = await revision.gesamtplan(neu)
    vs = await revision.vorschlaege(plan)
    # Fuer Talk auf der Seite Recommendations (gespraech._empfehlungen_kontext), ohne neuen Abruf.
    REVISION_ZULETZT.update(vorschlaege=vs, fazit=(plan or {}).get("fazit"), zeit=time.time())
    return {"stand": revision.stand(), "bestand": await revision.bestand(), "vorschlaege": vs,
            "laden": revision.laden_vorschlaege(neu), "neue_rollen": revision.neue_rollen(neu),
            "messungen": db.alle("SELECT * FROM messungen ORDER BY zeit DESC LIMIT 20"),
            "umgestellt": (db.einstellung("revision_umgestellt", []) or [])[:10],
            "installiert": sorted(n for n in inst if not revision._nicht_text(n)), "vram": vram,
            "laeuft_download": modellkatalog.LADEN,
            # Fuer die Team-Uebersicht (17.10.2026): was schon geladen, aber fuer
            # einen Platz noch nicht gemessen ist, und wer welches Modell noch braucht.
            "geladen_ungemessen": revision.geladen_ungemessen(neu), "gebraucht": await revision.gebraucht_von(),
            "groessen": inst, "extern": await teamchat.externe_liste(),
            # Abgewogene Gesamtbesetzung beider Karten (17.10.2026, revision.gesamtplan).
            "gesamtplan": plan,
            # Qualitaet laut Netz und das klare Urteil je Empfehlung (18.10.2026, ruf.py).
            "ruf": ruf.ansicht(), "ruf_stand": ruf.STAND, "urteile": await revision.urteile(neu, plan)}


@router.post("/revision/{aktion}")
async def revision_aktion(aktion: str, request: Request):
    from . import revision
    d = await _koerper(request)
    try:
        if aktion == "start":
            return {"gestartet": revision.starten(True), "stand": revision.stand()}
        if aktion == "umstellen":
            return revision.umstellen(str(d.get("platz") or ""), str(d.get("modell") or ""), d.get("messung"))
        if aktion == "zurueck":
            return revision.zuruecknehmen(str(d.get("platz") or ""))
        if aktion == "plan":
            plan = await revision.gesamtplan()
            v = next((x for x in plan["varianten"] if x["name"] == d.get("variante")), None)
            if not v:
                raise ValueError("Diese Variante gibt es nicht (mehr).")
            if v.get("laden"):
                raise ValueError(f"Erst laden: {', '.join(v['laden'])}. Danach misst die nächste Nacht, und die Variante lässt sich übernehmen.")
            return {"getan": revision.plan_uebernehmen(v["zuordnung"])}
        if aktion == "verwerfen":
            revision.verwerfen(str(d.get("messung") or ""))
            return {"ok": True}
        if aktion == "ruf":
            from . import ruf
            return {"gestartet": ruf.starten(bool(d.get("alles"))), "stand": ruf.STAND}
    except ValueError as e:
        raise HTTPException(409, str(e))
    raise HTTPException(404, "Unbekannte Aktion")


# ================================================================ Gespraeche zuordnen
# Jedes Gespraech (Talk, Team-Chat, Neo, Board) laesst sich einem Projekt und
# einer Aufgabe zuordnen (Veiko, 17.10.2026). Details: gespraech.zuordnen().
@router.get("/gespraeche/{gid}/zuordnung")
async def gespraech_zuordnung(gid: str):
    g = db.holen("gespraeche", gid)
    if not g:
        raise HTTPException(404, "Gespräch nicht gefunden")
    return gespraech.beschriftung(g.get("kontext") if isinstance(g.get("kontext"), dict) else {})


@router.patch("/gespraeche/{gid}/zuordnung")
async def gespraech_zuordnen(gid: str, request: Request):
    d = await _koerper(request)
    try:
        return gespraech.zuordnen(gid, d.get("projekt_id") or None, d.get("aufgabe_id") or None)
    except ValueError as e:
        raise HTTPException(409, str(e))


def gespraeche_von(projekt_id: str) -> list[dict[str, Any]]:
    """Zugeordnete Gespraeche eines Projekts, mit dem Weg zurueck ins Gespraech."""
    aus = []
    for g in db.alle("SELECT g.id, g.art, g.titel, g.kontext, g.geaendert, (SELECT COUNT(*) FROM nachrichten n WHERE n.gespraech_id=g.id) AS anzahl "
                     "FROM gespraeche g WHERE json_extract(g.kontext,'$.projekt_id')=? AND g.art IN ('talk','team','neo','board') "
                     "ORDER BY g.geaendert DESC LIMIT 60", (projekt_id,)):
        k = g.get("kontext") if isinstance(g.get("kontext"), dict) else {}
        if not g["anzahl"]:
            continue
        a = db.holen("aufgaben", k["aufgabe_id"]) if k.get("aufgabe_id") else None
        wer = k.get("wer")
        aus.append({"id": g["id"], "art": g["art"], "titel": g["titel"], "geaendert": g["geaendert"], "anzahl": g["anzahl"],
                    "wer": wer, "wer_name": teamchat.wer_name(wer) if wer else None,
                    "aufgabe_id": k.get("aufgabe_id"), "aufgabe_titel": (a or {}).get("titel")})
    return aus


def _auftraege_von(projekt_id: str) -> list[dict[str, Any]]:
    """Ausarbeitungen des Teams zu einem Projekt, mit ihrem juengsten Ergebnis (19.10.2026).

    Veiko vermisste in "LongRuns und Gespraeche" einen Auftrag, den er per Talk gegeben hatte
    ("... als LongRun ueberarbeiten") -- Talk hatte daraus eine Ausarbeitung gemacht, und die
    Spalte kannte nur LongRuns und Gespraeche. Cases eines LongRuns fehlen hier, die zeigt der
    LongRun selbst; Cases aus Notizen ohne Auftrag ebenso (die stehen unter Verlauf)."""
    aus = []
    for v in db.alle("SELECT v.id, v.titel, v.stand, v.geaendert, json_extract(v.auftrag,'$.rolle') AS rolle, "
                     "COALESCE(json_extract(v.auftrag,'$.aufgabe_id'), (SELECT a.id FROM aufgaben a WHERE a.vorgang_id=v.id LIMIT 1)) AS aufgabe_id, "
                     "(SELECT r.id FROM ergebnisse r WHERE r.vorgang_id=v.id ORDER BY r.erstellt DESC LIMIT 1) AS ergebnis_id "
                     "FROM vorgaenge v WHERE v.projekt_id=? AND json_valid(v.auftrag) AND json_extract(v.auftrag,'$.rolle') IS NOT NULL "
                     "AND v.id NOT IN (SELECT vorgang_id FROM langlaeufe WHERE vorgang_id IS NOT NULL) "
                     "ORDER BY v.geaendert DESC LIMIT 20", (projekt_id,)):
        a = db.holen("aufgaben", v["aufgabe_id"]) if v.get("aufgabe_id") else None
        aus.append({**v, "wer_name": stab.rollen_name(v["rolle"]), "aufgabe_titel": (a or {}).get("titel")})
    return aus


def _langlaeufe_von(projekt_id: str) -> list[dict[str, Any]]:
    from . import langlauf
    return langlauf.liste(projekt_id)
