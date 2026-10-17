"""
CURRENT ACTIONS -- alles, was auf dem Server gerade laeuft, an einer Stelle.

Veiko, 17.10.2026: "einen Button 'Current Actions', da will ich alles sehen,
was gerade laeuft, auch Downloads -- und die will ich pausieren oder abbrechen
koennen." Vorher stand jede Art an ihrem eigenen Ort (Downloads unter "Neu bei
Ollama", Langlaeufer auf ihrer Seite, Videos am Ergebnis, Gespraeche nur im
Fenster), und die Frage "was rechnet da gerade?" liess sich nur durch Suchen
beantworten.

Diese Datei fuehrt KEINEN eigenen Stand. Sie liest die Zustaende, die die
Module ohnehin halten (modellkatalog.LADEN, stab.ZUSTAND, langlauf, video,
folienbilder, medien, neo.JOBS, revision, verfahren, systeminfo.AUFTRAG und die
Gespraeche aus api.py) -- ein zweiter Zaehler liefe beim naechsten Umbau
auseinander. Gesteuert wird ueber dieselben Funktionen wie an den Orten selbst.

Jede Zeile hat dieselbe Form:
  {id, art, titel, wer, schritt, start, prozent?, stand, link?, steuerung: [..]}
steuerung nennt nur, was hier wirklich geht. Was sich nicht sicher anhalten
laesst (ein Pipeline-Schritt mitten in einer Datenbankaenderung), bekommt
keinen Knopf, sondern einen Link an seinen Ort.
"""
from __future__ import annotations

import time
from typing import Any

from . import db, llm, modellkatalog, stab

ART_NAME = {"download": "Download", "pipeline": "Team-Pipeline", "langlauf": "Langläufer", "video": "Video",
            "folienbilder": "Bilder für ein Ergebnis", "medien": "Bild aus dem Gespräch", "neo": "Neo",
            "gespraech": "Antwort im Gespräch", "revision": "Modell-Revision", "verfahren": "Verfahren",
            "system": "Server-Auftrag"}


def _titel_ergebnis(eid: str) -> str:
    r = db.holen("ergebnisse", eid) or {}
    return (r.get("titel") or eid)[:120]


def sammeln(gespraeche: dict[str, dict[str, Any]], wer_name) -> dict[str, Any]:
    jetzt = time.time()
    laufend: list[dict[str, Any]] = []
    beendet: list[dict[str, Any]] = []

    # Downloads
    for j in list(modellkatalog.LADEN.values()):
        z = {"id": "download:" + j["name"], "art": "download", "titel": j["name"], "stand": j.get("stand"),
             "schritt": j.get("schritt"), "start": j.get("start"), "prozent": j.get("prozent"), "gb": j.get("gb"),
             "geladen_gb": j.get("geladen_gb"), "mb_s": j.get("mb_s"), "rest_s": j.get("rest_s"),
             "fehler": j.get("fehler"), "link": "#/modelle/uebersicht"}
        if j.get("stand") == "laeuft":
            z["steuerung"] = ["pausieren", "abbrechen"]
            laufend.append(z)
        elif j.get("stand") == "pausiert":
            z["steuerung"] = ["fortsetzen", "abbrechen"]
            laufend.append(z)
        elif j.get("stand") == "fehler":
            z["steuerung"] = ["fortsetzen", "weg"]
            laufend.append(z)
        elif j.get("ende") and jetzt - j["ende"] < 3600:
            z["steuerung"] = ["weg"]
            beendet.append(z)

    # Team-Pipeline: der Schritt, der gerade rechnet (stab.laeuft)
    l = stab.ZUSTAND.get("laeuft")
    langlauf_vids = set()
    from . import langlauf
    for x in langlauf.liste():
        if x["stand"] in ("plant", "laeuft", "wartet", "pausiert", "fehler"):
            langlauf_vids.add(x.get("vorgang_id"))
            st = x["stand"]
            laufend.append({"id": "langlauf:" + x["id"], "art": "langlauf", "titel": x["titel"], "stand": st,
                            "wer": x.get("rolle_name"),
                            "schritt": (x.get("was") if x.get("arbeitet") else
                                        {"plant": "plant die Etappen", "laeuft": "wartet auf den nächsten Schritt",
                                         "wartet": "wartet auf deine Antwort", "pausiert": "pausiert",
                                         "fehler": "angehalten nach Fehlern: " + str(x.get("fehler") or "")}.get(st, st)),
                            "prozent": round(x["fertig"] / x["etappen"] * 100) if x.get("etappen") else None,
                            "teile": f"{x['fertig']} von {x['etappen']} {x['etappen_name']}" if x.get("etappen") else None,
                            "start": x.get("erstellt"), "link": "#/langlauf/" + x["id"],
                            "steuerung": (["fortsetzen", "abbrechen"] if st in ("pausiert", "fehler", "wartet")
                                          else ["pausieren", "abbrechen"])})
    if l and l.get("vorgang_id") not in langlauf_vids:
        v = db.holen("vorgaenge", l["vorgang_id"]) if l.get("vorgang_id") else None
        laufend.append({"id": "pipeline", "art": "pipeline", "titel": (v or {}).get("titel") or "Team-Pipeline",
                        "wer": stab.rollen_name(l.get("wer")), "schritt": l.get("was"), "start": l.get("seit"), "stand": "laeuft",
                        "link": ("#/inbox/" + l["vorgang_id"]) if l.get("vorgang_id") else "#/inbox", "steuerung": []})
    warten = db.wert("SELECT COUNT(*) FROM vorgaenge WHERE stand IN ('neu','eingeordnet','in_arbeit') AND quelle NOT IN ('alt','langlauf')")

    # Videos und Bilder an Ergebnissen
    from . import folienbilder, medien, video
    for eid in list(video.LAUFEND):
        r = db.holen("ergebnisse", eid) or {}
        vs = video.stand(r) or {}
        laufend.append({"id": "video:" + eid, "art": "video", "titel": _titel_ergebnis(eid), "wer": "Ridley",
                        "schritt": vs.get("schritt"), "start": vs.get("start"), "stand": "laeuft",
                        "prozent": round((vs.get("fertig") or 0) / vs["szenen"] * 100) if vs.get("szenen") else None,
                        "teile": f"{vs.get('fertig') or 0} von {vs['szenen']} Szenen" if vs.get("szenen") else None,
                        "ergebnis_id": eid, "steuerung": ["abbrechen"]})
    for eid in list(folienbilder.LAUFEND):
        r = db.holen("ergebnisse", eid) or {}
        fs = folienbilder.stand(r) or {}
        laufend.append({"id": "folienbilder:" + eid, "art": "folienbilder", "titel": _titel_ergebnis(eid), "wer": "Annie",
                        "schritt": fs.get("schritt"), "start": fs.get("geaendert"), "stand": "laeuft",
                        "prozent": round((fs.get("fertig") or 0) / fs["anzahl"] * 100) if fs.get("anzahl") else None,
                        "ergebnis_id": eid, "steuerung": ["abbrechen"]})
    for j in list(medien.JOBS.values()):
        if j.get("stand") == "laeuft":
            laufend.append({"id": "medien:" + j["id"], "art": "medien", "titel": j.get("titel") or "Bild", "stand": "laeuft",
                            "schritt": "ComfyUI rechnet", "start": j.get("start"), "steuerung": []})

    # Neo und Antworten in Gespraechen
    from . import neo
    for jid, j in list(neo.JOBS.items()):
        if not j.get("fertig"):
            g = db.holen("gespraeche", j["gespraech_id"]) or {}
            laufend.append({"id": "neo:" + jid, "art": "neo", "titel": g.get("titel") or "Auftrag an Neo", "wer": "Neo",
                            "schritt": f"arbeitet mit {j.get('modell') or '?'}", "start": j.get("start"), "stand": "laeuft",
                            "link": "#/neo/" + j["gespraech_id"], "steuerung": ["abbrechen"]})
    for gid, s in list(gespraeche.items()):
        g = db.holen("gespraeche", gid) or {}
        wer = (wer_name(s["wer"]) if s.get("wer") else ("Talk" if s.get("art") == "talk" else "Advisory Board"))
        link = ("#/team/chat/" + s["wer"] + "/" + gid) if s.get("art") == "team" and s.get("wer") else \
               ("#/board/" + gid) if s.get("art") == "board" else None
        laufend.append({"id": "gespraech:" + gid, "art": "gespraech", "titel": g.get("titel") or "Gespräch", "wer": wer,
                        "schritt": s.get("status") or "antwortet", "start": s.get("start"), "stand": "laeuft",
                        "link": link, "talk_gid": gid if s.get("art") == "talk" else None, "steuerung": ["abbrechen"]})

    # Revision, Verfahren, Server-Auftrag
    from . import revision, systeminfo, verfahren
    rs = revision.stand()
    if rs.get("laeuft"):
        laufend.append({"id": "revision", "art": "revision", "titel": "Modelle vergleichen", "wer": "Cockpit",
                        "schritt": rs.get("schritt"), "start": rs.get("start"), "stand": "laeuft",
                        "teile": f"{rs.get('fertig') or 0} von {rs['geplant']} Vergleichen" if rs.get("geplant") else None,
                        "prozent": round((rs.get("fertig") or 0) / rs["geplant"] * 100) if rs.get("geplant") else None,
                        "link": "#/modelle/optimierung", "steuerung": ["abbrechen"]})
    for art, t in list(verfahren._TASKS.items()):
        if t and not t.done():
            laufend.append({"id": "verfahren:" + art, "art": "verfahren", "titel": {"brainstrom": "BrainStrom", "exo": "ExO"}.get(art, art),
                            "schritt": "rechnet den nächsten Schritt", "stand": "laeuft", "link": "#/" + art, "steuerung": []})
    a = systeminfo.AUFTRAG
    if a.get("laeuft"):
        laufend.append({"id": "system", "art": "system", "titel": f"Server: {a.get('art') or 'Auftrag'}", "stand": "laeuft",
                        "schritt": ((a.get("log") or "").strip().splitlines() or [""])[-1][:160], "start": a.get("start"),
                        "link": "#/system", "steuerung": []})

    for z in laufend + beendet:
        z["art_name"] = ART_NAME.get(z["art"], z["art"])
    return {"laufend": laufend, "beendet": beendet, "zeit": jetzt,
            "ollama": {"anfragen": llm.AKTIV.get("n") or 0, "seit": llm.AKTIV.get("seit"),
                       "taetig": [dict(v) for v in list(llm.TAETIG.values())]},
            "pipeline_wartet": warten or 0}


def steuern(aid: str, aktion: str, gespraeche: dict[str, dict[str, Any]]) -> dict[str, Any]:
    art, _, ref = aid.partition(":")
    if art == "download":
        return modellkatalog.laden_steuern(ref, aktion)
    if art == "langlauf":
        from . import langlauf
        return langlauf.steuern(ref, aktion, {})
    if aktion != "abbrechen":
        raise ValueError("Hier geht nur Abbrechen.")
    if art in ("video", "folienbilder"):
        from . import folienbilder, video
        t = (video.LAUFEND if art == "video" else folienbilder.LAUFEND).get(ref)
        if not t:
            raise ValueError("Läuft schon nicht mehr.")
        t.cancel()   # das Ergebnis zeigt danach "abgebrochen" mit "Neu rechnen"
        return {"ok": True}
    if art == "neo":
        from . import neo
        if not neo.abbrechen(ref):
            raise ValueError("Läuft schon nicht mehr.")
        return {"ok": True}
    if art == "gespraech":
        s = gespraeche.get(ref)
        if not s or not s.get("_aufgabe"):
            raise ValueError("Läuft schon nicht mehr.")
        s["_aufgabe"].cancel()
        return {"ok": True}
    if art == "revision":
        from . import revision
        if not revision.abbrechen():
            raise ValueError("Läuft schon nicht mehr.")
        return {"ok": True}
    raise ValueError("Das lässt sich hier nicht anhalten.")
