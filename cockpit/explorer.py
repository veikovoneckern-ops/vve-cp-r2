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
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

from . import db
from .konfig import DATEN, MEDIEN_DIR

FORM_NAME = {"text": "Text", "aufstellung": "Aufstellung", "konzept": "Konzept", "dokument": "Dokument",
             "webseite": "Webseite", "praesentation": "Präsentation", "video": "Video"}
TYP_NAME = {**FORM_NAME, "dossier": "Recherche-Dossier", "abschrift": "Abschrift", "unterlage": "Unterlage",
            "bild": "Bild", "visualisierung": "Visualisierung", "notiz": "Notiz",
            "pdf": "PDF", "word": "Word", "excel": "Excel", "powerpoint": "PowerPoint", "audio": "Audio",
            "film": "Video-Datei", "webdatei": "HTML", "textdatei": "Textdatei"}
# Gruppen fuer den Baum links: was gehoert wohin.
GRUPPE = {"text": "ergebnis", "aufstellung": "ergebnis", "konzept": "ergebnis", "dokument": "ergebnis",
          "webseite": "ergebnis", "praesentation": "ergebnis", "video": "ergebnis",
          "dossier": "recherche", "abschrift": "recherche", "unterlage": "unterlage",
          "bild": "bild", "visualisierung": "bild", "notiz": "notiz",
          "pdf": "unterlage", "word": "unterlage", "excel": "unterlage", "powerpoint": "unterlage", "audio": "unterlage",
          "film": "unterlage", "webdatei": "unterlage", "textdatei": "unterlage"}
ROLLE = {"recherche": "Recherche", "pmo": "Jason", "cockpit": "Neo", "stratege": "Clayton", "buch": "Neal", "kritiker": "Daniel",
         "designer": "Annie", "video": "Ridley"}


# Art einer Unterlage aus Endung und Dateityp (19.10.2026, Veiko: "Bilder werden nicht als
# Bilder gezaehlt" -- 23 Fotos standen unter "Unterlage", weil nur Dossier und Abschrift am
# Namen erkannt wurden).
ENDUNG_TYP = {**{e: "bild" for e in ("jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff", "heic", "svg")},
              "pdf": "pdf", "doc": "word", "docx": "word", "odt": "word", "rtf": "word",
              "xls": "excel", "xlsx": "excel", "csv": "excel", "ods": "excel",
              "ppt": "powerpoint", "pptx": "powerpoint", "odp": "powerpoint",
              **{e: "audio" for e in ("mp3", "m4a", "wav", "ogg", "opus", "flac", "aac")},
              **{e: "film" for e in ("mp4", "mov", "webm", "mkv", "avi")},
              "html": "webdatei", "htm": "webdatei", "md": "textdatei", "txt": "textdatei"}


def _datei_typ(name: str, mime: str | None = None) -> str:
    n = (name or "").lower()
    if n.startswith(("recherche-dossier", "dossier")):
        return "dossier"
    if n.startswith(("youtube ", "podcast ", "abschrift")):
        return "abschrift"
    endung = n.rsplit(".", 1)[-1] if "." in n[-6:] else ""
    if endung in ENDUNG_TYP:
        return ENDUNG_TYP[endung]
    m = (mime or "").lower()
    for anfang, typ in (("image/", "bild"), ("audio/", "audio"), ("video/", "film"), ("application/pdf", "pdf"), ("text/", "textdatei")):
        if m.startswith(anfang):
            return typ
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

    for r in db.alle("SELECT id, vorgang_id, projekt_id, titel, form, rolle, pruefung, erstellt, length(inhalt) AS laenge, substr(inhalt, 1, 600) AS anfang FROM ergebnisse"):
        # Ein Recherche-Dossier ist ein Ergebnis (dossier._als_ergebnis), steht aber bei den Recherchen.
        eintrag(id=r["id"], art="ergebnis", typ="dossier" if r.get("rolle") == "recherche" else (r.get("form") or "text"), titel=r.get("titel") or "Ergebnis",
                projekt_id=r.get("projekt_id"), aufgabe_id=vg_aufgabe.get(r.get("vorgang_id") or ""),
                wer=ROLLE.get(r.get("rolle") or "", r.get("rolle")), zeit=max(r.get("erstellt") or 0, bearbeitet.get(r["id"]) or 0),
                erstellt=r.get("erstellt"), groesse=r.get("laenge") or 0, einheit="Zeichen", urteil=_urteil(r.get("pruefung")),
                vorgang_id=r.get("vorgang_id"), auszug=_auszug(r.get("anfang")),
                vorschau=bool(r.get("form") == "praesentation" and _folienbild(r["id"])))
    for d in db.alle("SELECT id, name, typ, groesse, projekt_id, aufgabe_id, erstellt, pfad, substr(text, 1, 600) AS anfang FROM dateien"):
        t = _datei_typ(d.get("name") or "", d.get("typ"))
        eintrag(id=d["id"], art="datei", typ=t, titel=re.sub(r"\.(md|txt)$", "", d.get("name") or "Datei"), name=d.get("name"),
                mime=d.get("typ"), projekt_id=d.get("projekt_id"), aufgabe_id=d.get("aufgabe_id"),
                wer="Cockpit" if t in ("dossier", "abschrift") else "Du", zeit=d.get("erstellt"), erstellt=d.get("erstellt"),
                groesse=d.get("groesse") or 0, einheit="Byte", auszug=_auszug(d.get("anfang")),
                vorschau=_datei_hat_bild(d.get("pfad") or "", t))
    for n in db.alle("SELECT id, titel, quelle, projekt_id, erstellt, length(text) AS laenge, substr(text, 1, 600) AS anfang FROM notizen"):
        eintrag(id=n["id"], art="notiz", typ="notiz", titel=n.get("titel") or "Notiz", projekt_id=n.get("projekt_id"),
                wer={"plaud": "Plaud", "mail": "Mail", "gespraech": "Talk"}.get(n.get("quelle") or "", "Du"),
                zeit=n.get("erstellt"), erstellt=n.get("erstellt"), groesse=n.get("laenge") or 0, einheit="Zeichen",
                quelle=n.get("quelle"), auszug=_auszug(n.get("anfang")))
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
                erstellt=t.get("zeit") or st.st_mtime, groesse=st.st_size, einheit="Byte", gespraech_id=t.get("gid"),
                vorschau=True)
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


# ---------------------------------------------------------------- Vorschau in den Kacheln
# Veiko (19.10.2026): "die Vorschau funktioniert nicht -- sauberes Zaehlen und Vorschau in den
# Kacheln muss fuer alle Arten von Dokumenten funktionieren." Ein Bild, wo es eines gibt:
# Fotos verkleinert, PDF die erste Seite (pdftoppm), PowerPoint/Word das Vorschaubild, das
# Office selbst hineinschreibt -- sonst das erste Bild der ersten Folie bzw. des Dokuments --,
# Praesentationen des Teams ihr erstes Folienbild. Wo es keins gibt (Texte, Notizen, Dossiers),
# zeigt die Kachel den Anfang des Inhalts (auszug). LibreOffice gibt es hier nicht; eine Folie
# selbst zu zeichnen hiesse raten, wie sie aussieht.
VORSCHAU_CACHE = DATEN / "explorer-vorschau"
_BILD_PIL = ("jpg", "jpeg", "png", "gif", "webp", "bmp", "tif", "tiff")
_zip_bild: dict[str, str | None] = {}   # Pfad + Zeitstempel -> Name des Bildes im Office-Archiv


def _auszug(t: str | None) -> str:
    """Die ersten Zeilen als Klartext -- ohne Markdown-Zeichen, Abschrift-Zeitmarken und Quellenzeilen."""
    t = re.sub(r"\[\d\d:\d\d(:\d\d)? - \d\d:\d\d(:\d\d)?\][^:\n]*:\s*", "", t or "")
    t = re.sub(r"(?m)^\s*(#+|[-*>]|\d+\.)\s*", "", t)
    t = re.sub(r"[*_`|]+", "", t)
    return re.sub(r"\s+", " ", t).strip()[:280]


def _folienbild(eid: str) -> Path | None:
    bilder = sorted(MEDIEN_DIR.glob(f"{eid}-f*.jpg"), key=lambda p: p.stat().st_mtime)
    return bilder[0] if bilder else None


def _office_bild(pfad: str) -> str | None:
    """Name des besten Bildes in einer pptx/docx/xlsx: eingebettete Vorschau, sonst das erste
    Bild der ersten Folie (pptx) bzw. das erste Bild im Dokument."""
    p = Path(pfad)
    try:
        schluessel = f"{pfad}:{p.stat().st_mtime}"
    except OSError:
        return None
    if schluessel in _zip_bild:
        return _zip_bild[schluessel]
    name = None
    try:
        with zipfile.ZipFile(p) as z:
            namen = z.namelist()
            name = next((n for n in namen if n.lower() == "docprops/thumbnail.jpeg"), None)
            if not name and "ppt/slides/_rels/slide1.xml.rels" in namen:
                rels = z.read("ppt/slides/_rels/slide1.xml.rels").decode("utf-8", "replace")
                for ziel in re.findall(r'Target="\.\./media/([^"]+)"', rels):
                    if ziel.lower().rsplit(".", 1)[-1] in _BILD_PIL:
                        name = "ppt/media/" + ziel
                        break
            if not name:
                medien = [n for n in namen if re.match(r"(ppt|word|xl)/media/", n) and n.lower().rsplit(".", 1)[-1] in _BILD_PIL]
                name = medien[0] if medien else None
    except (OSError, zipfile.BadZipFile, KeyError):
        name = None
    _zip_bild[schluessel] = name
    return name


def _datei_hat_bild(pfad: str, typ: str) -> bool:
    endung = pfad.lower().rsplit(".", 1)[-1] if "." in pfad else ""
    if typ == "bild":
        return endung in _BILD_PIL or endung == "svg"
    if typ == "pdf":
        return bool(shutil.which("pdftoppm"))
    if typ in ("powerpoint", "word", "excel") and endung in ("pptx", "docx", "xlsx"):
        return bool(_office_bild(pfad))
    return False


def _verkleinern(roh: bytes, breite: int) -> bytes:
    from io import BytesIO
    from PIL import Image, ImageOps
    with Image.open(BytesIO(roh)) as b:
        b = ImageOps.exif_transpose(b)   # Handyfotos stehen sonst quer
        b.thumbnail((breite, breite))
        if b.mode not in ("RGB", "L"):
            hinten = Image.new("RGB", b.size, (255, 255, 255))
            hinten.paste(b, mask=b.convert("RGBA").split()[-1])
            b = hinten
        aus = BytesIO()
        b.convert("RGB").save(aus, "JPEG", quality=82, optimize=True)
        return aus.getvalue()


def vorschau_bild(art: str, eid: str, breite: int = 480) -> tuple[bytes, str] | None:
    """(Bilddaten, Medientyp) fuer eine Kachel -- oder None, dann zeigt die Kachel den Auszug."""
    breite = max(120, min(1200, int(breite or 480)))
    quelle: Path | None = None
    if art == "datei":
        d = db.holen("dateien", eid)
        if not d or not Path(d.get("pfad") or "").is_file():
            return None
        quelle = Path(d["pfad"])
        typ = _datei_typ(d.get("name") or "", d.get("typ"))
    elif art == "ergebnis":
        quelle, typ = _folienbild(eid), "bild"
    elif art == "bild":
        if not re.fullmatch(r"m[0-9a-f]{10}\.(png|svg)", eid):
            return None
        quelle, typ = MEDIEN_DIR / eid, "bild"
    else:
        return None
    if not quelle or not quelle.is_file():
        return None
    if quelle.suffix.lower() == ".svg":
        return quelle.read_bytes(), "image/svg+xml"   # SVG skaliert selbst
    VORSCHAU_CACHE.mkdir(parents=True, exist_ok=True)
    ziel = VORSCHAU_CACHE / f"{art}-{re.sub(r'[^A-Za-z0-9._-]', '_', eid)}-{breite}-{int(quelle.stat().st_mtime)}.jpg"
    if ziel.is_file():
        return ziel.read_bytes(), "image/jpeg"
    roh: bytes | None = None
    try:
        if typ == "pdf":
            r = subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-scale-to", str(breite), "-jpeg", str(quelle), "-"],
                               capture_output=True, timeout=30)
            roh = r.stdout if r.returncode == 0 and r.stdout else None
        elif typ in ("powerpoint", "word", "excel"):
            name = _office_bild(str(quelle))
            if name:
                with zipfile.ZipFile(quelle) as z:
                    roh = z.read(name)
        else:
            roh = quelle.read_bytes()
        if not roh:
            return None
        daten = _verkleinern(roh, breite)
    except Exception:  # noqa: BLE001 -- kaputte oder fremde Datei: dann eben der Auszug
        return None
    ziel.write_bytes(daten)
    return daten, "image/jpeg"
