#!/usr/bin/env python3
"""
VVEC-ANHANG — aus einer hochgeladenen Unterlage lesbaren Text machen.

Das Cockpit konnte Dateien schon an ein Projekt heften (dateien.py). Was
fehlte, war der andere Weg: eine Unterlage in ein GESPRAECH geben. Der
Plus-Knopf in den Chatfeldern las bis hierher ausschliesslich Textdateien
und schob deren Inhalt sichtbar in die Eingabe. Bei allem, was ein Mensch
tatsaechlich vor sich hat — PDF, Word, Excel, Praesentation — kam wortlos
"uebersprungen".

Eingehaengt in vvec_backend.py:
    from anhang import router as anhang_router
    app.include_router(anhang_router)

Endpunkte:
    POST /api/anhang/lesen     Datei rein (multipart), Text raus
    GET  /api/anhang/status    Modul erreichbar + was der Server kann

WARUM KEINE BIBLIOTHEKEN: pypdf, python-docx und openpyxl waeren der
bequeme Weg. Sie waeren aber drei weitere Abhaengigkeiten in einem venv,
das ueber vvec-update.sh gepflegt wird, und ein fehlendes Paket laesst
einen Router hier STILL ausfallen (siehe CLAUDE.md, "Ein fehlendes Modul
laesst den Rest weiterlaufen"). Fuer die Office-Formate braucht es sie
auch nicht: .docx, .xlsx und .pptx sind ZIP-Archive mit XML darin, und
zipfile plus xml.etree stehen in jeder Python-Standardinstallation.

PDF ist der einzige Fall, der von aussen etwas braucht. Genommen wird
pdftotext aus poppler-utils — ein Systemwerkzeug, kein Python-Paket,
haeufig ohnehin vorhanden. Fehlt es, sagt der Endpunkt das im Klartext
mitsamt Installationsbefehl. KEINE Notloesung, die aus den rohen Bytes
Buchstabenreste herausklaubt: ein halb gelesenes Dokument, das aussieht
wie ein gelesenes, ist schlimmer als eine ehrliche Fehlmeldung — dann
antwortet ein Modell zuversichtlich auf Grundlage von Bruchstuecken.

BILDER WERDEN HIER NICHT ANGEFASST. Sie gehen als Bildblock direkt an
das Modell (siehe _nach_openai in vvec_backend.py). Sie durch eine
Texterkennung zu schicken, waere der Umweg — die Modelle sehen selbst.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

router = APIRouter(prefix="/api/anhang", tags=["anhang"])

# 25 MB. Kleiner als die 50 MB von dateien.py, und das mit Absicht: dort
# wird abgelegt, hier wird GELESEN und der Text wandert anschliessend in
# ein Modellfenster. Eine 50-MB-PDF ergibt mehr Text, als jedes Fenster
# fasst; die Grenze ehrlich vorne zu ziehen ist besser, als hinten
# stillschweigend abzuschneiden.
MAX_BYTES = int(os.getenv("VVEC_ANHANG_MAX_MB", "25")) * 1024 * 1024

# Was ans Modell geht, wird begrenzt. 120 000 Zeichen sind grob 30 000
# Token — viel, aber bei 128k Kontextfenster tragbar. Wird gekuerzt, steht
# das IM Text, nicht nur in einem Feld daneben: das Modell soll wissen,
# dass es einen Ausschnitt liest.
MAX_ZEICHEN = int(os.getenv("VVEC_ANHANG_MAX_ZEICHEN", "120000"))

COCKPIT_TOKEN = os.getenv("COCKPIT_TOKEN", "")


def check_token(request: Request) -> None:
    """Eigene Kopie, damit das Modul einzeln lauffaehig bleibt — dieselbe
    Regel wie in suche.py, onedrive.py, dialog.py und dateien.py."""
    if not COCKPIT_TOKEN:
        return
    supplied = (
        request.headers.get("x-cockpit-token")
        or request.query_params.get("token")
        or ""
    )
    if supplied != COCKPIT_TOKEN:
        raise HTTPException(status_code=401, detail="Ungueltiger COCKPIT_TOKEN")


def _endung(name: str) -> str:
    m = re.search(r"\.([A-Za-z0-9]{1,8})$", name or "")
    return m.group(1).lower() if m else ""


def _aufraeumen(text: str) -> str:
    """Leerraum baendigen. PDF-Auszuege und Tabellen bringen viele leere
    Zeilen mit; sie kosten Token und tragen nichts."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Reine Textdateien
# ---------------------------------------------------------------------------

TEXT_ENDUNGEN = {
    "txt", "md", "markdown", "csv", "tsv", "json", "log", "xml", "yml",
    "yaml", "html", "htm", "js", "ts", "css", "php", "py", "sh", "sql",
    "ini", "conf", "env", "rst", "tex", "srt", "vtt",
}


def _text_lesen(roh: bytes) -> str:
    """UTF-8 zuerst, dann Windows-1252. Letzteres kommt haeufiger vor, als
    einem lieb ist — alles, was einmal durch Excel gelaufen ist."""
    for kodierung in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return roh.decode(kodierung)
        except UnicodeDecodeError:
            continue
    return roh.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# PDF — ueber pdftotext aus poppler-utils
# ---------------------------------------------------------------------------

def _pdftotext_da() -> Optional[str]:
    return shutil.which("pdftotext")


def _pdf_lesen(roh: bytes) -> str:
    werkzeug = _pdftotext_da()
    if not werkzeug:
        raise HTTPException(
            status_code=503,
            detail="PDF kann auf diesem Server nicht gelesen werden: "
                   "pdftotext fehlt. Einmalig nachruesten mit "
                   "'sudo apt install poppler-utils' — danach geht es ohne "
                   "Neustart des Backends.",
        )
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(roh)
        pfad = f.name
    try:
        # -layout haelt Spalten und Tabellen zusammen. Ohne das laufen
        # zweispaltige Seiten zeilenweise ineinander und ergeben Kauderwelsch.
        r = subprocess.run(
            [werkzeug, "-layout", "-enc", "UTF-8", pfad, "-"],
            capture_output=True, timeout=120,
        )
        if r.returncode != 0:
            fehler = (r.stderr or b"").decode("utf-8", "replace")[:300]
            raise HTTPException(
                status_code=422,
                detail=f"PDF nicht lesbar: {fehler or 'pdftotext brach ab'}",
            )
        return r.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504,
                            detail="PDF-Auswertung dauerte laenger als 120 s "
                                   "und wurde abgebrochen.")
    finally:
        try:
            os.unlink(pfad)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Office — ZIP mit XML darin, gelesen mit Bordmitteln
# ---------------------------------------------------------------------------

# Die Namensraeume sind lang und stehen in jedem Tag. Statt sie zu
# registrieren wird auf den lokalen Namen geprueft — das ist unempfindlich
# dagegen, dass Word je nach Fassung andere Praefixe schreibt.
def _lokal(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _docx_lesen(roh: bytes) -> str:
    """Word. Absaetze sind <w:p>, Text steht in <w:t>, ein <w:tab> oder
    <w:br> dazwischen gehoert erhalten — sonst kleben Tabellenzellen
    aneinander."""
    with zipfile.ZipFile(io.BytesIO(roh)) as z:
        teile = ["word/document.xml"]
        # Kopf- und Fusszeilen tragen bei Vorlagen den halben Inhalt.
        teile += sorted(n for n in z.namelist()
                        if re.match(r"word/(header|footer)\d*\.xml$", n))
        absaetze: List[str] = []
        for name in teile:
            try:
                wurzel = ET.fromstring(z.read(name))
            except (KeyError, ET.ParseError):
                continue
            for p in wurzel.iter():
                if _lokal(p.tag) != "p":
                    continue
                stuecke: List[str] = []
                for k in p.iter():
                    lok = _lokal(k.tag)
                    if lok == "t":
                        stuecke.append(k.text or "")
                    elif lok == "tab":
                        stuecke.append("\t")
                    elif lok in ("br", "cr"):
                        stuecke.append("\n")
                zeile = "".join(stuecke).strip()
                if zeile:
                    absaetze.append(zeile)
    return "\n".join(absaetze)


def _xlsx_lesen(roh: bytes) -> str:
    """Excel. Zeichenketten liegen zentral in sharedStrings.xml, die Zellen
    verweisen nur mit einer Nummer darauf (t="s"). Wer das uebersieht,
    bekommt eine Tabelle voller Zahlen ohne Beschriftung."""
    with zipfile.ZipFile(io.BytesIO(roh)) as z:
        gemeinsam: List[str] = []
        try:
            wurzel = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in wurzel:
                gemeinsam.append("".join(
                    (t.text or "") for t in si.iter() if _lokal(t.tag) == "t"))
        except (KeyError, ET.ParseError):
            pass

        # Blattnamen aus der Arbeitsmappe, damit ueber der Tabelle steht,
        # welches Blatt man liest.
        namen: List[str] = []
        try:
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            namen = [s.get("name", "") for s in wb.iter()
                     if _lokal(s.tag) == "sheet"]
        except (KeyError, ET.ParseError):
            pass

        blaetter = sorted(n for n in z.namelist()
                          if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        raus: List[str] = []
        for i, name in enumerate(blaetter):
            try:
                wurzel = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            titel = namen[i] if i < len(namen) else f"Blatt {i + 1}"
            zeilen: List[str] = []
            for row in wurzel.iter():
                if _lokal(row.tag) != "row":
                    continue
                zellen: List[str] = []
                for c in row:
                    if _lokal(c.tag) != "c":
                        continue
                    art = c.get("t", "")
                    wert = ""
                    for k in c:
                        lok = _lokal(k.tag)
                        if lok == "v":
                            wert = k.text or ""
                        elif lok == "is":
                            wert = "".join(
                                (t.text or "") for t in k.iter()
                                if _lokal(t.tag) == "t")
                    if art == "s" and wert.isdigit():
                        idx = int(wert)
                        wert = gemeinsam[idx] if idx < len(gemeinsam) else ""
                    zellen.append(wert.strip())
                while zellen and not zellen[-1]:
                    zellen.pop()
                if zellen:
                    zeilen.append(" | ".join(zellen))
            if zeilen:
                raus.append(f"### {titel}\n" + "\n".join(zeilen))
        return "\n\n".join(raus)


def _pptx_lesen(roh: bytes) -> str:
    """PowerPoint. Je Folie eine Ueberschrift, damit sich hinterher sagen
    laesst, worauf sich etwas bezieht. Notizen kommen mit — in ihnen steht
    oft, was auf der Folie bewusst NICHT steht."""
    with zipfile.ZipFile(io.BytesIO(roh)) as z:
        vorhanden = set(z.namelist())
        folien = sorted(
            (n for n in vorhanden
             if re.match(r"ppt/slides/slide\d+\.xml$", n)),
            key=lambda n: int(re.search(r"(\d+)", n).group(1)),
        )
        raus: List[str] = []
        for n, name in enumerate(folien, 1):
            try:
                wurzel = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            texte = [(t.text or "").strip() for t in wurzel.iter()
                     if _lokal(t.tag) == "t"]
            texte = [t for t in texte if t]
            notiz_name = f"ppt/notesSlides/notesSlide{n}.xml"
            notizen: List[str] = []
            if notiz_name in vorhanden:
                try:
                    nw = ET.fromstring(z.read(notiz_name))
                    notizen = [(t.text or "").strip() for t in nw.iter()
                               if _lokal(t.tag) == "t"]
                    notizen = [t for t in notizen if t]
                except ET.ParseError:
                    pass
            if texte or notizen:
                block = f"### Folie {n}\n" + "\n".join(texte)
                if notizen:
                    block += "\n[Notizen] " + " ".join(notizen)
                raus.append(block)
        return "\n\n".join(raus)


# ---------------------------------------------------------------------------
# Verteiler
# ---------------------------------------------------------------------------

BILD_ENDUNGEN = {"png", "jpg", "jpeg", "gif", "webp", "bmp", "svg", "heic"}


def _auswerten(name: str, roh: bytes) -> Dict[str, Any]:
    endung = _endung(name)

    if endung in BILD_ENDUNGEN:
        # Kein Fehler, aber auch keine Arbeit: Bilder gehen als Bildblock
        # direkt ans Modell. Das Cockpit soll sie gar nicht erst hierher
        # schicken; kommt doch eines, wird gesagt warum nichts passiert.
        raise HTTPException(
            status_code=415,
            detail="Bilder werden nicht in Text umgewandelt — sie gehen "
                   "direkt an ein Modell, das sehen kann.")

    if endung == "pdf":
        return {"art": "PDF", "text": _pdf_lesen(roh)}
    if endung in ("docx", "dotx", "docm"):
        return {"art": "Word", "text": _docx_lesen(roh)}
    if endung in ("xlsx", "xlsm", "xltx"):
        return {"art": "Excel", "text": _xlsx_lesen(roh)}
    if endung in ("pptx", "potx", "pptm"):
        return {"art": "PowerPoint", "text": _pptx_lesen(roh)}
    if endung in TEXT_ENDUNGEN or not endung:
        return {"art": "Text", "text": _text_lesen(roh)}

    # Die alten Binaerformate (.doc, .xls, .ppt) sind KEIN ZIP und werden
    # bewusst nicht versucht. Sie zu raten hiesse, Bruchstuecke zu liefern.
    if endung in ("doc", "xls", "ppt"):
        raise HTTPException(
            status_code=415,
            detail=f"Das alte Format .{endung} kann nicht gelesen werden. "
                   "In Word/Excel/PowerPoint einmal als .docx/.xlsx/.pptx "
                   "speichern — dann geht es.")

    raise HTTPException(
        status_code=415,
        detail=f"Dateityp .{endung} wird nicht unterstuetzt. Moeglich sind "
               "PDF, Word, Excel, PowerPoint und Textdateien.")


@router.post("/lesen")
async def lesen(request: Request, datei: UploadFile = File(...)) -> Dict[str, Any]:
    check_token(request)

    roh = await datei.read()
    if len(roh) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Die Datei ist {len(roh) // 1024 // 1024} MB gross, "
                   f"erlaubt sind {MAX_BYTES // 1024 // 1024} MB.")
    if not roh:
        raise HTTPException(status_code=400, detail="Die Datei ist leer.")

    name = datei.filename or "unbenannt"
    ergebnis = _auswerten(name, roh)
    text = _aufraeumen(ergebnis["text"])

    if not text:
        # Der haeufigste Fall dahinter ist ein Scan ohne Texterkennung.
        # Das gehoert gesagt, sonst haelt man eine leere Antwort fuer
        # einen Fehler des Cockpits.
        raise HTTPException(
            status_code=422,
            detail=f"Aus „{name}“ liess sich kein Text gewinnen. Bei einer "
                   "PDF ist das meist ein Scan ohne Texterkennung — dort "
                   "stehen Bilder, keine Buchstaben.")

    gekuerzt = False
    if len(text) > MAX_ZEICHEN:
        text = text[:MAX_ZEICHEN] + (
            "\n\n[… hier abgeschnitten. Das Dokument ist laenger; gelesen "
            f"wurden die ersten {MAX_ZEICHEN} Zeichen.]")
        gekuerzt = True

    return {
        "name": name,
        "art": ergebnis["art"],
        "text": text,
        "zeichen": len(text),
        "bytes": len(roh),
        "gekuerzt": gekuerzt,
    }


@router.get("/status")
async def status(request: Request) -> Dict[str, Any]:
    """Prueft vvec-update.sh nach dem Neustart. Sagt zusaetzlich, was
    dieser Server kann — das Cockpit blendet den PDF-Hinweis danach ein
    oder aus, statt es beim ersten Versuch herauszufinden."""
    check_token(request)
    pdf = bool(_pdftotext_da())
    return {
        "ok": True,
        "modul": "anhang",
        "pdf": pdf,
        "pdf_hinweis": ("" if pdf else
                        "pdftotext fehlt — 'sudo apt install poppler-utils'"),
        "office": True,
        "max_mb": MAX_BYTES // 1024 // 1024,
        "max_zeichen": MAX_ZEICHEN,
        "formate": ["pdf", "docx", "xlsx", "pptx"] + sorted(TEXT_ENDUNGEN),
    }
