"""EXPLORER -- alles, was im Cockpit entstanden ist, an einem Ort (19.10.2026).

Veiko: "eine weitere Seite Explorer. Hier moechte ich alle generierten Inhalte
sehen koennen, filtern, suchen, etc. -- vergleichbar zu einem Windows Datei
Explorer." Anlass war ein Recherche-Dossier, das er nicht wiederfand.

Der Explorer fuehrt KEINEN eigenen Bestand: er liest die Tabellen, in denen die
Dinge ohnehin liegen (ergebnisse, dateien, notizen) und den Ordner der Bilder aus
Talk (MEDIEN_DIR). Aendern kann er nur die Zuordnung einer Unterlage zu Projekt
und Aufgabe -- alles andere oeffnet die Ansicht, die es schon gibt.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import db
from .konfig import MEDIEN_DIR

FORM_NAME = {"text": "Text", "aufstellung": "Aufstellung", "konzept": "Konzept", "dokument": "Dokument",
             "webseite": "Webseite", "praesentation": "Präsentation", "video": "Video"}
TYP_NAME = {**FORM_NAME, "dossier": "Recherche-Dossier", "abschrift": "Abschrift", "unterlage": "Unterlage",
            "bild": "Bild", "visualisierung": "Visualisierung", "notiz": "Notiz"}
# Gruppen fuer den Baum links: was gehoert wohin.
GRUPPE = {"text": "ergebnis", "aufstellung": "ergebnis", "konzept": "ergebnis", "dokument": "ergebnis",
          "webseite": "ergebnis", "praesentation": "ergebnis", "video": "ergebnis",
          "dossier": "recherche", "abschrift": "recherche", "unterlage": "unterlage",
          "bild": "bild", "visualisierung": "bild", "notiz": "notiz"}
ROLLE = {"recherche": "Recherche", "pmo": "Jason", "cockpit": "Neo", "stratege": "Clayton", "buch": "Neal", "kritiker": "Daniel",
         "designer": "Annie", "video": "Ridley"}


def _datei_typ(name: str) -> str:
    n = (name or "").lower()
    if n.startswith(("recherche-dossier", "dossier")):
        return "dossier"
    if n.startswith(("youtube ", "podcast ", "abschrift")):
        return "abschrift"
    return "unterlage"


def _urteil(p: Any) -> str | None:
    if isinstance(p, str):
        try:
            p = json.loads(p or "{}")
        except ValueError:
            p = {}
    # Der Schluessel (tragfaehig, nachbessern, rueckfrage, ungeprueft) -- in Worte fasst ihn ergebnis.URTEIL.
    return (p or {}).get("urteil") if isinstance(p, dict) else None


def liste() -> dict[str, Any]:
    projekte = {p["id"]: p["name"] for p in db.alle("SELECT id, name FROM projekte")}
    aufgaben = {a["id"]: a for a in db.alle("SELECT id, titel, projekt_id, vorgang_id FROM aufgaben")}
    # Ergebnis -> Aufgabe: ueber den Case der Aufgabe oder den Auftrag (auftrag.aufgabe_id, Talk-Bezug).
    vg_aufgabe = {a["vorgang_id"]: a["id"] for a in aufgaben.values() if a.get("vorgang_id")}
    for v in db.alle("SELECT id, json_extract(auftrag,'$.aufgabe_id') AS aid FROM vorgaenge WHERE auftrag LIKE '%aufgabe_id%'"):
        if v.get("aid"):
            vg_aufgabe[v["id"]] = v["aid"]
    bearbeitet = {z["datensatz_id"]: z["t"] for z in db.alle(
        "SELECT datensatz_id, MAX(zeit) AS t FROM protokoll WHERE tabelle='ergebnisse' GROUP BY datensatz_id")}
    aus: list[dict[str, Any]] = []

    def eintrag(**e: Any) -> None:
        a = aufgaben.get(e.get("aufgabe_id") or "")
        if a and not e.get("projekt_id"):
            e["projekt_id"] = a.get("projekt_id")
        e["projekt_name"] = projekte.get(e.get("projekt_id") or "")
        e["aufgabe_titel"] = (a or {}).get("titel")
        e["typ_name"] = TYP_NAME.get(e["typ"], e["typ"])
        e["gruppe"] = GRUPPE.get(e["typ"], "unterlage")
        aus.append(e)

    for r in db.alle("SELECT id, vorgang_id, projekt_id, titel, form, rolle, pruefung, erstellt, length(inhalt) AS laenge FROM ergebnisse"):
        # Ein Recherche-Dossier ist ein Ergebnis (dossier._als_ergebnis), steht aber bei den Recherchen.
        eintrag(id=r["id"], art="ergebnis", typ="dossier" if r.get("rolle") == "recherche" else (r.get("form") or "text"), titel=r.get("titel") or "Ergebnis",
                projekt_id=r.get("projekt_id"), aufgabe_id=vg_aufgabe.get(r.get("vorgang_id") or ""),
                wer=ROLLE.get(r.get("rolle") or "", r.get("rolle")), zeit=max(r.get("erstellt") or 0, bearbeitet.get(r["id"]) or 0),
                erstellt=r.get("erstellt"), groesse=r.get("laenge") or 0, einheit="Zeichen", urteil=_urteil(r.get("pruefung")),
                vorgang_id=r.get("vorgang_id"))
    for d in db.alle("SELECT id, name, typ, groesse, projekt_id, aufgabe_id, erstellt FROM dateien"):
        t = _datei_typ(d.get("name") or "")
        eintrag(id=d["id"], art="datei", typ=t, titel=re.sub(r"\.(md|txt)$", "", d.get("name") or "Datei"), name=d.get("name"),
                mime=d.get("typ"), projekt_id=d.get("projekt_id"), aufgabe_id=d.get("aufgabe_id"),
                wer="Cockpit" if t != "unterlage" else "Du", zeit=d.get("erstellt"), erstellt=d.get("erstellt"),
                groesse=d.get("groesse") or 0, einheit="Byte")
    for n in db.alle("SELECT id, titel, quelle, projekt_id, erstellt, length(text) AS laenge FROM notizen"):
        eintrag(id=n["id"], art="notiz", typ="notiz", titel=n.get("titel") or "Notiz", projekt_id=n.get("projekt_id"),
                wer={"plaud": "Plaud", "mail": "Mail", "gespraech": "Talk"}.get(n.get("quelle") or "", "Du"),
                zeit=n.get("erstellt"), erstellt=n.get("erstellt"), groesse=n.get("laenge") or 0, einheit="Zeichen",
                quelle=n.get("quelle"))
    # Bilder und Visualisierungen aus Talk: die Titel stehen in den Nachrichten, die Datei im Medienordner.
    titel: dict[str, dict[str, Any]] = {}
    for m in db.alle("SELECT gespraech_id, daten, zeit FROM nachrichten WHERE daten LIKE '%\"medien\": [{%'"):
        for x in ((m.get("daten") or {}).get("medien") or []):
            if isinstance(x, dict) and x.get("id"):
                titel[x["id"]] = {"titel": x.get("titel"), "art": x.get("art"), "gid": m["gespraech_id"], "zeit": m.get("zeit")}
    for f in sorted(MEDIEN_DIR.glob("*.*")):
        if not re.fullmatch(r"m[0-9a-f]{10}\.(png|svg)", f.name):   # dasselbe Muster wie /api/medien/datei
            continue
        t = titel.get(f.stem) or {}
        st = f.stat()
        eintrag(id=f.stem, art="bild", typ="visualisierung" if f.suffix.lower() == ".svg" else "bild",
                titel=t.get("titel") or f.name, datei=f.name, wer="Talk", zeit=t.get("zeit") or st.st_mtime,
                erstellt=t.get("zeit") or st.st_mtime, groesse=st.st_size, einheit="Byte", gespraech_id=t.get("gid"))
    aus.sort(key=lambda e: -(e.get("zeit") or 0))
    return {"eintraege": aus, "typen": TYP_NAME,
            "projekte": [{"id": p["id"], "name": p["name"], "status": p.get("status")}
                         for p in db.alle("SELECT id, name, status FROM projekte ORDER BY sortierung, name")]}


def im_inhalt(q: str) -> dict[str, str]:
    """Volltext: Kennung -> kurzer Ausschnitt um die Fundstelle (Ergebnisse, Unterlagen, Notizen)."""
    q = (q or "").strip()
    if len(q) < 3:
        return {}
    muster = f"%{q}%"
    aus: dict[str, str] = {}
    for tab, feld in (("ergebnisse", "inhalt"), ("dateien", "text"), ("notizen", "text")):
        for z in db.alle(f"SELECT id, {feld} AS t FROM {tab} WHERE {feld} LIKE ? LIMIT 200", (muster,)):
            t = z.get("t") or ""
            i = t.lower().find(q.lower())
            aus[z["id"]] = ("…" if i > 60 else "") + re.sub(r"\s+", " ", t[max(0, i - 60): i + len(q) + 90]).strip() + "…"
    return aus


def kontext_text(filter_: dict[str, Any] | None = None) -> str:
    """Fuer Talk: was im Explorer liegt, kurz -- die neuesten Eintraege und die Mengen je Art."""
    d = liste()["eintraege"]
    zahl: dict[str, int] = {}
    for e in d:
        zahl[e["typ_name"]] = zahl.get(e["typ_name"], 0) + 1
    neu = [e for e in d if e["art"] != "notiz"][:15]
    return ("VEIKO SCHAUT AUF DEN EXPLORER (alle erzeugten Inhalte: Ergebnisse, Recherche-Dossiers, Abschriften, Bilder, Unterlagen, Notizen). "
            "Öffnen geht mit der Aktion oeffnen (art ergebnis|notiz|datei) über den Titel.\n"
            "Mengen: " + ", ".join(f"{k} {v}" for k, v in sorted(zahl.items(), key=lambda x: -x[1])) +
            "\nZuletzt entstanden:\n" + "\n".join(
                f"- {e['typ_name']}: {e['titel'][:90]}" + (f" [{e['projekt_name']}" + (f" / {e['aufgabe_titel']}" if e.get('aufgabe_titel') else "") + "]" if e.get("projekt_name") else " [ohne Projekt]")
                for e in neu))
