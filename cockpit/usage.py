"""USAGE -- Verbrauch an Token, Rechenzeit, Geld und Strom (19.10.2026).

Veiko: "eine eigene Seite fuer das Thema Verbrauch mit dem Button Usage. Hier
moechte ich wie im alten Cockpit eine Seite mit verschiedenen Ansichten und
Filtern haben, nach Projekten, Aufgaben, Modellen etc. und auch Stromverbrauch."

Grundlage sind zwei Aufzeichnungen, sonst nichts:
- `verbrauch` -- je Modellaufruf eine Zeile (llm.buchen; exakte Token, Rechenzeit).
- `strom` -- alle fuenf Minuten der Zaehlerstand beider Shelly-Steckdosen
  (Server, Grafik-Dock), wie vve-status ihn meldet (strom_schleife).
Was daraus nicht folgt, wird nicht geschaetzt: Strom gibt es je Tag und Dose,
nicht je Projekt -- dafuer fehlt eine Messung, und eine Verteilung nach
Rechenzeit waere eine erfundene Zahl. Die Aufgabe eines Aufrufs kommt ueber
seinen Case (aufgaben.vorgang_id, auftrag.aufgabe_id, Langlaeufer).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from . import db

TAKT_S = 300
DOSEN = {"server": "Mini-PC (Server)", "dock": "Grafik-Dock (2× RTX 3090)"}
ROLLE = {"pmo": "Jason", "cockpit": "Neo", "stratege": "Clayton", "buch": "Neal", "kritiker": "Daniel",
         "designer": "Annie", "video": "Ridley", "talk": "Talk", "dario": "Dario (Claude)", "elon": "Elon (Grok)",
         "demmis": "Demmis (Gemini)", "revision": "Modell-Revision", "ruf": "Ruf im Netz"}


def tabelle_anlegen() -> None:
    db.ausfuehren("CREATE TABLE IF NOT EXISTS strom (id INTEGER PRIMARY KEY AUTOINCREMENT, zeit REAL, dose TEXT, "
                  "watt REAL, kwh REAL)")
    db.ausfuehren("CREATE INDEX IF NOT EXISTS strom_zeit ON strom(zeit)")


async def strom_schleife() -> None:
    """Alle fuenf Minuten den Zaehlerstand beider Dosen festhalten. Faellt vve-status
    aus, fehlt der Punkt -- die Luecke bleibt sichtbar, nichts wird aufgefuellt."""
    from . import systeminfo
    tabelle_anlegen()
    while True:
        try:
            s = await systeminfo.status() or {}
            p = s.get("power") or {}
            for dose in DOSEN:
                d = p.get(dose)
                if isinstance(d, dict) and (d.get("kwh") is not None or d.get("watt") is not None):
                    db.ausfuehren("INSERT INTO strom (zeit,dose,watt,kwh) VALUES (?,?,?,?)",
                                  (time.time(), dose, d.get("watt"), d.get("kwh")))
        except Exception as e:  # noqa: BLE001 -- eine verpasste Messung soll die Schleife nie beenden
            print(f"[strom] Messung ausgefallen: {e}", flush=True)
        await asyncio.sleep(TAKT_S)


def _tage_zwischen(tage: list[str]) -> list[str]:
    """Alle Tage vom ersten bis zum letzten (JJJJ-MM-TT), auch die ohne Eintrag."""
    if not tage:
        return []
    t = time.mktime(time.strptime(tage[0], "%Y-%m-%d")) + 43200
    ende, aus = tage[-1], []
    while len(aus) < 800:
        s = _tag(t)
        aus.append(s)
        if s >= ende:
            break
        t += 86400
    return aus


def _tag(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts))


def strom(von: float, bis: float) -> dict[str, Any]:
    tabelle_anlegen()
    preis = db.einstellung("strompreis", None)
    zeilen = db.alle("SELECT zeit, dose, watt, kwh FROM strom WHERE zeit>=? AND zeit<=? ORDER BY dose, zeit", (von - TAKT_S * 2, bis))
    je_tag: dict[str, dict[str, Any]] = {}
    gesamt = {d: 0.0 for d in DOSEN}
    watt: dict[str, list[float]] = {d: [] for d in DOSEN}
    vorher: dict[str, dict[str, Any]] = {}
    for z in zeilen:
        d = z["dose"]
        if d not in DOSEN:
            continue
        v = vorher.get(d)
        vorher[d] = z
        if z["zeit"] < von:
            continue
        if z.get("watt") is not None:
            watt[d].append(float(z["watt"]))
        if not v or z.get("kwh") is None or v.get("kwh") is None:
            continue
        diff = float(z["kwh"]) - float(v["kwh"])
        # Zaehler zurueckgesetzt (Dose neu gestartet): diesen Schritt nicht mitzaehlen. Eine Luecke
        # (Cockpit lief nicht) zaehlt dagegen mit -- der Zaehler hat in der Zeit ja weitergezaehlt;
        # sie landet beim Tag der naechsten Messung.
        if diff < 0:
            continue
        t = je_tag.setdefault(_tag(z["zeit"]), {"tag": _tag(z["zeit"]), **{x: 0.0 for x in DOSEN}})
        t[d] += diff
        gesamt[d] += diff
    tage = [je_tag.get(t) or {"tag": t, **{x: 0.0 for x in DOSEN}} for t in _tage_zwischen(sorted(je_tag))]
    for t in tage:
        t["summe"] = round(sum(t[x] for x in DOSEN), 3)
        t["kosten"] = round(t["summe"] * float(preis), 2) if preis else None
        for x in DOSEN:
            t[x] = round(t[x], 3)
    summe = sum(gesamt.values())
    seit = db.wert("SELECT MIN(zeit) FROM strom")
    return {"tage": tage, "gesamt": {k: round(v, 3) for k, v in gesamt.items()}, "summe": round(summe, 3),
            "kosten": round(summe * float(preis), 2) if preis else None, "preis": preis,
            "mittel_w": {d: round(sum(w) / len(w)) if w else None for d, w in watt.items()},
            "dosen": DOSEN, "seit": seit}


def _aufgaben_je_vorgang() -> dict[str, str]:
    m = {a["vorgang_id"]: a["id"] for a in db.alle("SELECT id, vorgang_id FROM aufgaben WHERE vorgang_id IS NOT NULL")}
    for v in db.alle("SELECT id, json_extract(auftrag,'$.aufgabe_id') AS aid FROM vorgaenge WHERE auftrag LIKE '%aufgabe_id%'"):
        if v.get("aid"):
            m[v["id"]] = v["aid"]
    for l in db.alle("SELECT vorgang_id AS vid, json_extract(daten,'$.aufgabe_id') AS aid FROM langlaeufe"):
        if l.get("vid") and l.get("aid"):
            m[l["vid"]] = l["aid"]
    return m


def auswerten(von: float, bis: float, filt: dict[str, str], preise: dict[str, list[float]]) -> dict[str, Any]:
    """Alle Ansichten in einem Abruf: Summen, je Anbieter, je Projekt/Aufgabe/Modell/Rolle/Bereich/Tag.
    filt: projekt, aufgabe, modell, anbieter, rolle, art (lokal|cloud) -- leer = alle."""
    bis = bis or time.time() + 60
    zuordnung = _aufgaben_je_vorgang()
    aufgaben = {a["id"]: a for a in db.alle("SELECT id, titel, projekt_id FROM aufgaben")}
    projekte = {p["id"]: p["name"] for p in db.alle("SELECT id, name FROM projekte")}
    roh = db.alle("SELECT zeit, art, anbieter, modell, bereich, wer, vorgang_id, projekt_id, tok_ein, tok_aus, dauer_s, geschaetzt "
                  "FROM verbrauch WHERE zeit>=? AND zeit<=?", (von, bis))
    gruppen: dict[str, dict[str, dict[str, Any]]] = {k: {} for k in ("projekt", "aufgabe", "modell", "rolle", "bereich", "tag", "anbieter")}
    summe = {"aufrufe": 0, "ein": 0, "aus": 0, "dauer": 0.0, "kosten": 0.0, "geschaetzt": 0}

    def zaehle(art: str, schluessel: str, name: str, z: dict[str, Any], kosten: float, **mehr: Any) -> None:
        g = gruppen[art].setdefault(schluessel, {"schluessel": schluessel, "name": name, "aufrufe": 0, "ein": 0, "aus": 0,
                                                 "dauer": 0.0, "kosten": 0.0, **mehr})
        g["aufrufe"] += 1
        g["ein"] += z.get("tok_ein") or 0
        g["aus"] += z.get("tok_aus") or 0
        g["dauer"] += z.get("dauer_s") or 0
        g["kosten"] += kosten

    for z in roh:
        aid = zuordnung.get(z.get("vorgang_id") or "")
        pid = z.get("projekt_id") or (aufgaben.get(aid) or {}).get("projekt_id")
        rolle = z.get("wer") or ("talk" if (z.get("bereich") or "").lower().startswith("talk") else "")
        if filt.get("projekt") and (pid or "_ohne") != filt["projekt"]:
            continue
        if filt.get("aufgabe") and aid != filt["aufgabe"]:
            continue
        if filt.get("modell") and z.get("modell") != filt["modell"]:
            continue
        if filt.get("anbieter") and z.get("anbieter") != filt["anbieter"]:
            continue
        if filt.get("rolle") and rolle != filt["rolle"]:
            continue
        if filt.get("art") == "lokal" and z.get("anbieter") != "ollama":
            continue
        if filt.get("art") == "cloud" and z.get("anbieter") == "ollama":
            continue
        pr = preise.get(z.get("anbieter") or "")
        kosten = ((z.get("tok_ein") or 0) / 1e6 * pr[0] + (z.get("tok_aus") or 0) / 1e6 * pr[1]) if pr else 0.0
        for f, w in (("aufrufe", 1), ("ein", z.get("tok_ein") or 0), ("aus", z.get("tok_aus") or 0), ("dauer", z.get("dauer_s") or 0),
                     ("kosten", kosten), ("geschaetzt", z.get("geschaetzt") or 0)):
            summe[f] += w
        zaehle("projekt", pid or "_ohne", projekte.get(pid or "", "ohne Projekt"), z, kosten)
        if aid:
            a = aufgaben.get(aid) or {}
            zaehle("aufgabe", aid, a.get("titel") or "Aufgabe", z, kosten, projekt=projekte.get(a.get("projekt_id") or ""))
        zaehle("modell", f"{z.get('anbieter')}|{z.get('modell') or ''}", z.get("modell") or z.get("anbieter") or "?", z, kosten,
               anbieter=z.get("anbieter"))
        zaehle("rolle", rolle or "_sonst", ROLLE.get(rolle, rolle or "Sonstiges"), z, kosten)
        zaehle("bereich", z.get("bereich") or "Sonstiges", z.get("bereich") or "Sonstiges", z, kosten)
        zaehle("tag", _tag(z["zeit"]), _tag(z["zeit"]), z, kosten)
        zaehle("anbieter", z.get("anbieter") or "?", z.get("anbieter") or "?", z, kosten)
    aus = {k: sorted(v.values(), key=lambda g: (-g["kosten"], -g["dauer"], -g["aufrufe"])) for k, v in gruppen.items()}
    # Tage ohne Arbeit stehen mit null da -- sonst rueckten die Saeulen zusammen, und die
    # Zeitachse taeuschte eine dichte Folge vor, wo Tage dazwischen leer waren.
    aus["tag"] = [gruppen["tag"].get(t) or {"schluessel": t, "name": t, "aufrufe": 0, "ein": 0, "aus": 0, "dauer": 0.0, "kosten": 0.0}
                  for t in _tage_zwischen(sorted(gruppen["tag"]))]
    for liste in aus.values():
        for g in liste:
            g["kosten"] = round(g["kosten"], 4)
            g["dauer"] = round(g["dauer"], 1)
    summe["kosten"] = round(summe["kosten"], 4)
    return {"summe": summe, "nach": aus,
            "auswahl": {"projekte": [{"id": k, "name": v} for k, v in sorted(projekte.items(), key=lambda x: x[1].lower())],
                        "modelle": sorted({z.get("modell") for z in roh if z.get("modell")}),
                        "rollen": [{"id": k, "name": v} for k, v in ROLLE.items()]},
            "erfasst_seit": db.wert("SELECT MIN(zeit) FROM verbrauch")}


def kontext_text() -> str:
    """Fuer Talk: die letzten 30 Tage in wenigen Zeilen."""
    from .api import _preise
    jetzt = time.time()
    d = auswerten(jetzt - 30 * 86400, 0, {}, _preise())
    s = d["summe"]
    st = strom(jetzt - 30 * 86400, jetzt)
    zeile = lambda g: f"{g['name']}: {g['aufrufe']} Aufrufe, {round(g['dauer'] / 60)} Min. Rechenzeit, ${g['kosten']:.2f}"  # noqa: E731
    return ("VEIKO SCHAUT AUF USAGE (Verbrauch: Token, Rechenzeit, Cloud-Kosten, Strom; Ansichten nach Projekt, Aufgabe, Modell, Rolle, Tag). "
            f"Letzte 30 Tage: {s['aufrufe']} Aufrufe, {s['ein'] + s['aus']} Token, {round(s['dauer'] / 3600, 1)} Std. lokale Rechenzeit, "
            f"Cloud-Kosten ${s['kosten']:.2f}.\nNach Projekt: " + "; ".join(zeile(g) for g in d["nach"]["projekt"][:6]) +
            "\nNach Modell: " + "; ".join(zeile(g) for g in d["nach"]["modell"][:6]) +
            (f"\nStrom (seit Beginn der Aufzeichnung im Zeitraum): {st['summe']} kWh" + (f", {st['kosten']} €" if st.get("kosten") is not None else "")
             if st["tage"] else "\nStrom: noch keine Aufzeichnung im Zeitraum."))
