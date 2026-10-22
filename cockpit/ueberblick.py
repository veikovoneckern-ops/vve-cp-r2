"""
UEBERBLICK -- "Gib mir einen aktuellen Ueberblick" als Fenster mit den letzten Ergebnissen.

Veiko (22.10.2026): "Wenn ich sage, gib mir einen aktuellen Ueberblick oder zeig mir den
aktuellen Stand, soll sich ein Fenster oeffnen, in dem wirklich die letzten Ergebnisse
praesentiert werden -- mit Vorschaubildern. Dann moechte ich sagen: oeffne mir das, gib mir
dazu eine kurze Zusammenfassung." Bis dahin las Talk eine Liste vor, und sehen konnte er nur
das Briefing.

Ein Ort fuer die Liste: liste() liefert die Ergebnisse in DER Reihenfolge, in der das Fenster
sie nummeriert -- Talk loest "das zweite" ueber dieselbe Funktion auf (gespraech.py), und die
Kennungen gehen als Fensterbezug mit (art "ueberblick", id = Kennungen mit Komma).
"""
from __future__ import annotations

import re
from typing import Any

from . import db, stab

ANZAHL = 12
NUMMERN = ["erste", "zweite", "dritte", "vierte", "fünfte", "sechste", "siebte", "achte", "neunte", "zehnte", "elfte", "zwölfte"]


def _vorschau_art(e: dict[str, Any]) -> str:
    """Womit die Kachel ihr Vorschaubild zeigt: bild (erstes gerechnetes Folien-/Textbild),
    video (Standbild aus dem Video), ansicht (verkleinerte erste Seite) oder text (Auszug)."""
    from . import folienbilder, video
    if e.get("form") == "video" and video.datei(e["id"]).is_file():
        return "video"
    if erstes_bild(e):
        return "bild"
    if e.get("form") in ("praesentation", "dokument", "webseite") or (e.get("form") in ("text", "aufstellung", "konzept")
                                                                      and stab._hat_bildzeile(e.get("inhalt") or "")):
        return "ansicht"
    return "text"


def erstes_bild(e: dict[str, Any]):
    from . import folienbilder
    if e.get("form") not in folienbilder.MIT_BILDERN:
        return None
    for p in folienbilder.prompts(e.get("inhalt") or "", e["form"]):
        if p and folienbilder.datei(e["id"], p).is_file():
            return folienbilder.datei(e["id"], p)
    return None


def _auszug(text: str, n: int = 260) -> str:
    t = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    t = re.sub(r"(?m)^\s*(#{1,6}|[-*•]|\d+[.)])\s*", "", t)
    t = re.sub(r"[*_`>|]", "", t)
    t = re.sub(r"(?mi)^\s*(typ|bild|notizen?)\s*:.*$", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:n].rsplit(" ", 1)[0] + " …" if len(t) > n else t


def liste(anzahl: int = ANZAHL) -> list[dict[str, Any]]:
    from .api import kurztitel
    aus = []
    for i, e in enumerate(stab.neu_entstanden(tage=30, anzahl=anzahl)):
        voll = db.holen("ergebnisse", e["id"]) or {}
        p = e.get("pruefung")
        aus.append({"nr": i + 1, "id": e["id"], "titel": kurztitel({**voll, "vorgang_titel": e.get("vorgang_titel")}),
                    "form": e.get("form"), "wer": e.get("wer_name"), "projekt": e.get("projekt_name"),
                    "bearbeitet": e.get("bearbeitet"), "urteil_text": e.get("urteil_text"),
                    "urteil": (p if isinstance(p, dict) else {}).get("urteil"),
                    "vorschau": _vorschau_art(voll), "auszug": _auszug(voll.get("inhalt") or ""),
                    "zeichen": len(voll.get("inhalt") or "")})
    return aus


def lage() -> dict[str, Any]:
    ents = db.wert("SELECT COUNT(*) FROM entscheidungen WHERE stand='offen'") or 0
    vm = [v["titel"] for v in db.alle("SELECT titel FROM vorgaenge WHERE stand='vorgemerkt' ORDER BY erstellt DESC LIMIT 5")]
    lauf = [v for v in db.alle("SELECT id, titel, auftrag, stand FROM vorgaenge WHERE stand IN ('neu','in_arbeit') "
                               "AND quelle!='alt' ORDER BY geaendert DESC LIMIT 5")]
    from . import langlauf
    ll = [l["titel"] for l in langlauf.liste() if l.get("stand") in ("laeuft", "plant")][:3]
    return {"entscheidungen": ents, "vorgemerkt": vm, "laeuft": [v["titel"] for v in lauf] + [f"LongRun {t}" for t in ll]}


def _wort(n: int) -> str:
    return {1: "ein", 2: "zwei", 3: "drei", 4: "vier", 5: "fünf", 6: "sechs", 7: "sieben", 8: "acht", 9: "neun",
            10: "zehn", 11: "elf", 12: "zwölf"}.get(n, str(n))


def sprech_titel(t: str) -> str:
    """Ein Titel zum Vorlesen: ohne Formvorsatz ("Dokument: "), ohne Untertitel nach dem
    Gedankenstrich, hoechstens acht Woerter -- im Fenster steht der ganze Titel."""
    t = re.sub(r"^(Dokument|Präsentation|Text|Konzept|Aufstellung|Webseite|Video|Zwischenstand|LongRun|Langläufer):\s*", "", t or "")
    t = re.sub(r"^(LongRun|Langläufer):\s*", "", t)
    t = re.split(r"\s[–—-]\s", t)[0]
    w = t.split()
    return " ".join(w[:8]) + (" …" if len(w) > 8 else "")


def satz(eintraege: list[dict[str, Any]], l: dict[str, Any]) -> str:
    """Was Talk dazu SAGT, waehrend das Fenster aufgeht -- kurz, die drei neuesten beim Namen,
    der Rest steht im Fenster. Ohne Modell: das ist eine Ansage, keine Ueberlegung (0 s statt ~10 s)."""
    teile = ["Hier ist dein Überblick."]
    if eintraege:
        n = len(eintraege)
        teile.append(f"Ich zeige dir die {_wort(n)} neuesten Ergebnisse." if n > 1 else "Ich zeige dir das neueste Ergebnis.")
        for i, e in enumerate(eintraege[:3]):
            wer = f" von {e['wer']}" if e.get("wer") and e["wer"] not in ("Recherche",) else ""
            urteil = f", {e['urteil_text']}" if e.get("urteil_text") and e.get("urteil") not in (None, "") else ""
            teile.append(f"{['Ganz oben', 'Als zweites', 'Als drittes'][i]}: {sprech_titel(e['titel'])}{wer}{urteil}.")
    else:
        teile.append("In den letzten dreißig Tagen ist kein Ergebnis entstanden.")
    if l.get("entscheidungen"):
        n = l["entscheidungen"]
        teile.append(f"{_wort(n).capitalize()} {'Entscheidung wartet' if n == 1 else 'Entscheidungen warten'} auf dich.")
    if l.get("vorgemerkt"):
        teile.append("Vorgemerkt ist: " + ", ".join(l["vorgemerkt"][:2]) + ".")
    if l.get("laeuft"):
        teile.append("Gerade läuft: " + ", ".join(l["laeuft"][:2]) + ".")
    if eintraege:
        teile.append("Sag zum Beispiel: öffne das zweite, oder: fass das erste zusammen.")
    return " ".join(teile)


def nummer_im_text(text: str) -> int | None:
    """'das zweite', 'Nummer 3', 'die 3', 'Ergebnis drei', 'das letzte' -> Position ab 1 (letzte = -1)."""
    t = (text or "").lower()
    for i, w in enumerate(NUMMERN):
        if re.search(rf"\b{w}[nmrs]?\b", t):
            return i + 1
    if re.search(r"\bletzte[nmrs]?\b|\bunterste[nmrs]?\b", t):
        return -1
    zahlen = {"eins": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6, "sieben": 7, "acht": 8, "neun": 9, "zehn": 10,
              "elf": 11, "zwölf": 12}
    m = re.search(r"\b(nummer|nr\.?|ergebnis|kachel|die|das|den)\s+(\d{1,2}|" + "|".join(zahlen) + r")\b", t)
    if m:
        z = m.group(2)
        return int(z) if z.isdigit() else zahlen[z]
    return None


def aus_kontext(kontext: dict[str, Any] | None, text: str) -> str | None:
    """Die Kennung des gemeinten Ergebnisses, wenn das Ueberblick-Fenster offen ist und der Satz eine Nummer nennt."""
    k = kontext or {}
    if k.get("art") != "ueberblick":
        return None
    ids = [x for x in str(k.get("id") or "").split(",") if x]
    nr = nummer_im_text(text)
    if not ids or nr is None:
        return None
    i = len(ids) - 1 if nr == -1 else nr - 1
    return ids[i] if 0 <= i < len(ids) else None


def kontext_text(k: dict[str, Any]) -> str:
    ids = [x for x in str(k.get("id") or "").split(",") if x]
    zeilen = []
    for e in liste():
        if not ids or e["id"] in ids:
            zeilen.append(f"{len(zeilen) + 1}. {e['titel']} (id {e['id']}, {e.get('wer') or ''}, {e.get('urteil_text') or ''}): {e['auszug']}")
    return ("VEIKO SCHAUT AUF DEN ÜBERBLICK -- die neuesten Ergebnisse, nummeriert wie im Fenster. „Das zweite“ meint Nummer 2. "
            "Zum Öffnen: aktion oeffnen mit art ergebnis und der id.\n" + "\n".join(zeilen))
