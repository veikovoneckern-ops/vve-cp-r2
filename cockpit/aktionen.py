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

ART_NAME = {"download": "Download", "pipeline": "Team-Pipeline", "langlauf": "LongRun", "video": "Video",
            "folienbilder": "Bilder für ein Ergebnis", "medien": "Bild aus dem Gespräch", "neo": "Neo",
            "gespraech": "Antwort im Gespräch", "revision": "Modell-Revision", "ruf": "Ruf im Netz", "verfahren": "Verfahren",
            "system": "Server-Auftrag", "dossier": "Recherche-Dossier", "rsi": "RSI"}


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
             "fehler": j.get("fehler"), "link": "#/empfehlungen/modelle"}
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
                            "start": x.get("erstellt"), "link": "#/langlauf/" + x["id"], "_vid": x.get("vorgang_id"),
                            "steuerung": (["fortsetzen", "abbrechen"] if st in ("pausiert", "fehler", "wartet")
                                          else ["pausieren", "abbrechen"])})
    if l and l.get("vorgang_id") not in langlauf_vids:
        v = db.holen("vorgaenge", l["vorgang_id"]) if l.get("vorgang_id") else None
        laufend.append({"id": "pipeline", "art": "pipeline", "titel": (v or {}).get("titel") or "Team-Pipeline",
                        "wer": stab.rollen_name(l.get("wer")), "schritt": l.get("was"), "start": l.get("seit"), "stand": "laeuft", "_vid": l.get("vorgang_id"),
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
            n_schritte = sum(1 for e in j.get("ereignisse") or [] if e.get("typ") == "schritt")
            # Was Neo GERADE tut, in Klartext (24.10.2026) -- vorher stand hier nur "arbeitet mit <Modell>".
            laufend.append({"id": "neo:" + jid, "art": "neo", "titel": g.get("titel") or "Auftrag an Neo", "wer": "Neo",
                            "schritt": neo.job_stand(j), "teile": f"{n_schritte} Schritte · {j.get('modell') or ''}".strip(" ·"),
                            "start": j.get("start"), "stand": "laeuft",
                            "link": "#/neo/" + j["gespraech_id"], "steuerung": ["abbrechen"]})
    # RSI (24.10.2026): das Durchsehen und eine laufende Serie stehen hier mit, je mit dem Schritt, der gerade laeuft.
    from . import rsi, rsi_serie
    if rsi.laeuft():
        rs = rsi.stand()
        laufend.append({"id": "rsi", "art": "rsi", "titel": "RSI: Gespräche durchsehen", "wer": "Neo · Dario", "stand": "laeuft",
                        "schritt": rs.get("schritt") or "läuft", "start": rs.get("start"), "link": "#/rsi", "steuerung": []})
    se = rsi_serie.stand()
    if se.get("stand") in ("pruefung", "laeuft"):
        reihe = se.get("reihenfolge") or []
        fertig_n = len(se.get("ergebnisse") or {})
        akt = (db.holen("rsi", se.get("aktuell") or "") or {}).get("titel")
        laufend.append({"id": "rsi-serie", "art": "rsi", "titel": "RSI: Verbesserungen umsetzen", "wer": "Neo · Dario", "stand": "laeuft",
                        "schritt": ("Dario prüft die Auswahl auf Widersprüche" if se["stand"] == "pruefung"
                                    else f"{akt or 'nächster Punkt'} -- {se.get('aktuell_schritt') or 'läuft'}"),
                        "teile": f"Punkt {min(fertig_n + 1, len(reihe))} von {len(reihe)}" if reihe else None,
                        "prozent": round(fertig_n / len(reihe) * 100) if reihe else None,
                        "start": se.get("gestartet") or se.get("start"), "link": "#/rsi", "steuerung": []})
    for gid, s in list(gespraeche.items()):
        g = db.holen("gespraeche", gid) or {}
        wer = (wer_name(s["wer"]) if s.get("wer") else ("Talk" if s.get("art") == "talk" else "Advisory Board"))
        link = ("#/team/chat/" + s["wer"] + "/" + gid) if s.get("art") == "team" and s.get("wer") else \
               ("#/board/" + gid) if s.get("art") == "board" else None
        laufend.append({"id": "gespraech:" + gid, "art": "gespraech", "titel": g.get("titel") or "Gespräch", "wer": wer,
                        "schritt": s.get("status") or "antwortet", "start": s.get("start"), "stand": "laeuft",
                        "link": link, "talk_gid": gid if s.get("art") == "talk" else None, "steuerung": ["abbrechen"]})

    # Recherche-Dossiers (dossier.py: YouTube, Podcasts, Webseiten; 17.10.2026)
    from . import dossier
    for y in list(dossier.JOBS.values()):
        z = {"id": "dossier:" + y["id"], "art": "dossier", "titel": y["dossier_titel"], "wer": "Cockpit", "stand": y["stand"],
             "schritt": y["schritt"] + (f" · {y['ohne']} nicht lesbar" if y.get("ohne") else ""), "start": y["start"],
             # Fertig ist fertig: 17 von 18 Quellen (eine nicht lesbar) zeigte sonst 94 % an einem fertigen Dossier.
             "prozent": 100 if y["stand"] == "fertig" else round(y["fertig"] / y["anzahl"] * 100) if y["anzahl"] else None,
             "teile": f"{y['fertig']} von {y['anzahl']} Quellen" if y["anzahl"] else None, "fehler": y.get("fehler"),
             "ergebnis_id": y.get("ergebnis_id")}
        if y["stand"] == "laeuft":
            z["steuerung"] = ["abbrechen"]
            laufend.append(z)
        elif y.get("ende") and jetzt - y["ende"] < 3600:
            z["steuerung"] = []
            beendet.append(z)

    # Revision, Verfahren, Server-Auftrag
    from . import revision, systeminfo, verfahren
    rs = revision.stand()
    if rs.get("laeuft"):
        laufend.append({"id": "revision", "art": "revision", "titel": "Modelle vergleichen", "wer": "Cockpit",
                        "schritt": rs.get("schritt"), "start": rs.get("start"), "stand": "laeuft",
                        "teile": f"{rs.get('fertig') or 0} von {rs['geplant']} Vergleichen" if rs.get("geplant") else None,
                        "prozent": round((rs.get("fertig") or 0) / rs["geplant"] * 100) if rs.get("geplant") else None,
                        "link": "#/team/optimierung", "steuerung": ["abbrechen"]})
    from . import ruf
    if ruf.STAND.get("laeuft") and not rs.get("laeuft"):
        g = ruf.STAND.get("geplant") or 0
        laufend.append({"id": "ruf", "art": "ruf", "titel": "Modelle im Netz prüfen", "wer": "Cockpit",
                        "schritt": ruf.STAND.get("schritt"), "start": ruf.STAND.get("start"), "stand": "laeuft",
                        "teile": f"{ruf.STAND.get('fertig') or 0} von {g} Modellen" if g else None,
                        "prozent": round((ruf.STAND.get("fertig") or 0) / g * 100) if g else None,
                        "link": "#/empfehlungen/modelle", "steuerung": ["abbrechen"]})
    for art, t in list(verfahren._TASKS.items()):
        if t and not t.done():
            laufend.append({"id": "verfahren:" + art, "art": "verfahren", "titel": {"brainstrom": "BrainStrom", "exo": "ExO"}.get(art, art),
                            "schritt": "rechnet den nächsten Schritt", "stand": "laeuft", "link": "#/" + art, "steuerung": []})
    a = systeminfo.AUFTRAG
    if a.get("laeuft"):
        laufend.append({"id": "system", "art": "system", "titel": f"Server: {a.get('art') or 'Auftrag'}", "stand": "laeuft",
                        "schritt": ((a.get("log") or "").strip().splitlines() or [""])[-1][:160], "start": a.get("start"),
                        "link": "#/system", "steuerung": []})

    # Was gerade genau fuer jede Zeile rechnet und was zuletzt fertig wurde
    # (Veiko, 17.10.2026: "mehr Details, was gerade genau gemacht wird").
    # Zugeordnet wird ueber den Zweck der Anfrage (llm.ZWECK = die Zeilen-ID)
    # bzw. bei Pipeline und Langlaeufern ueber den Vorgang.
    for z in laufend:
        vid = z.pop("_vid", None)
        if z["art"] in ("pipeline", "langlauf"):
            z["detail"] = llm.anfragen_zu(vorgang_id=vid) if vid else None
        elif z["art"] in ("video", "folienbilder", "neo", "gespraech", "dossier", "revision"):
            z["detail"] = llm.anfragen_zu(zweck=z["id"])
    for z in laufend + beendet:
        z.pop("_vid", None)
        z["art_name"] = ART_NAME.get(z["art"], z["art"])
        z["bezug"] = _bezug(z)
    return {"laufend": laufend, "beendet": beendet, "zeit": jetzt,
            "ollama": {"anfragen": llm.AKTIV.get("n") or 0, "seit": llm.AKTIV.get("seit"),
                       "taetig": [dict(v) for v in list(llm.TAETIG.values())],
                       "ohne_zuordnung": llm.anfragen_frei()},
            "pipeline_wartet": warten or 0}


def _json(w: Any) -> dict[str, Any]:
    if isinstance(w, dict):
        return w
    try:
        import json
        d = json.loads(w or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def _bezug(z: dict[str, Any]) -> dict[str, Any]:
    """Wofuer eine Aktion arbeitet: Langlaeufer, Ergebnis, Projekt.

    Veiko, 17.10.2026: "ich gebe ueber den Chat etwas ein und es wird gearbeitet,
    der Status vom Langlaeufer steht aber auf fertig. Ich moechte immer wirklich
    die aktuellen Stati zu allen Sachen sehen." Eine Recherche oder eine Antwort
    im Langlaeufer-Gespraech gehoert zum Langlaeufer, auch wenn sie nicht seine
    Etappen veraendert -- also muss der Langlaeufer sie zeigen."""
    art, _, ref = z["id"].partition(":")
    if art == "langlauf":
        d = _json((db.holen("langlaeufe", ref) or {}).get("daten"))
        return {"langlauf_id": ref, "ergebnis_id": d.get("ergebnis_id")}
    if art in ("video", "folienbilder"):
        r = db.holen("ergebnisse", ref) or {}
        return {"ergebnis_id": ref, "projekt_id": r.get("projekt_id")}
    if art == "gespraech":
        k = _json((db.holen("gespraeche", ref) or {}).get("kontext"))
        return {"langlauf_id": k.get("langlauf_id"), "ergebnis_id": k.get("ergebnis_id"), "projekt_id": k.get("projekt_id"),
                "aufgabe_id": k.get("aufgabe_id")}
    if art == "dossier":
        from . import dossier
        zi = (dossier.JOBS.get(ref) or {}).get("ziel") or {}
        return {"langlauf_id": zi.get("langlauf_id"), "projekt_id": zi.get("projekt_id"), "aufgabe_id": zi.get("aufgabe_id"),
                "ergebnis_id": (dossier.JOBS.get(ref) or {}).get("ergebnis_id")}
    return {}


_ZWISCHEN: dict[str, Any] = {"zeit": 0.0, "liste": []}


def fuer(langlauf_id: str | None = None, ergebnis_id: str | None = None, aufgabe_id: str | None = None) -> list[dict[str, Any]]:
    """Was gerade fuer diesen Langlaeufer bzw. dieses Ergebnis laeuft -- ohne den
    Langlaeufer selbst. Zwei Sekunden gemerkt: die Langlaeufer-Liste fragt je Zeile."""
    import time as _t
    if _t.time() - _ZWISCHEN["zeit"] > 2:
        from .api import GESPRAECH_LAEUFT
        from .teamchat import wer_name
        _ZWISCHEN.update(zeit=_t.time(), liste=sammeln(GESPRAECH_LAEUFT, wer_name)["laufend"])
    aus = []
    for z in _ZWISCHEN["liste"]:
        b = z.get("bezug") or {}
        if z["id"] == f"langlauf:{langlauf_id}":
            continue
        if ((langlauf_id and b.get("langlauf_id") == langlauf_id) or (ergebnis_id and b.get("ergebnis_id") == ergebnis_id)
                or (aufgabe_id and b.get("aufgabe_id") == aufgabe_id)):
            jetzt = ((z.get("detail") or {}).get("laufend") or [None])[0]
            aus.append({"id": z["id"], "art_name": z["art_name"], "wer": z.get("wer"), "titel": z["titel"],
                        "schritt": z.get("schritt"), "teile": z.get("teile"), "prozent": z.get("prozent"), "start": z.get("start"),
                        "jetzt": jetzt and {"modell": jetzt["modell"], "phase": jetzt["phase"], "tok_aus": jetzt.get("tok_aus")}})
    return aus


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
    if art == "dossier":
        from . import dossier
        if not dossier.abbrechen(ref):
            raise ValueError("Läuft schon nicht mehr.")
        return {"ok": True}
    if art == "ruf":
        from . import ruf
        if not ruf.abbrechen():
            raise ValueError("Läuft schon nicht mehr.")
        return {"ok": True}
    if art == "revision":
        from . import revision
        if not revision.abbrechen():
            raise ValueError("Läuft schon nicht mehr.")
        return {"ok": True}
    raise ValueError("Das lässt sich hier nicht anhalten.")
