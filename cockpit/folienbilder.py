"""
BILDER FUER PRAESENTATIONEN -- je Folie ein Bild aus ComfyUI, in der Vorschau
UND in der PowerPoint-Datei.

Anlass (Veiko, 16.10.2026): "wenn ich eine ppt erstellen lasse und Bilder drin
haben will, funktioniert das nicht". Annies Folien trugen zwar Zeilen wie
"Bildbeschreibung: …", aber nichts machte daraus ein Bild -- sie standen als
Text auf der Folie.

Wie es laeuft:
  - Jede Folie darf EINE Zeile "Bild: <Beschreibung>" tragen (auch
    "Bildbeschreibung:", "Visual:"). Das ist die Vorgabe an Annie (stab.FORMEN)
    und zugleich alles, was hier gelesen wird.
  - Gerechnet wird mit derselben Bildvorlage wie im Gespraech (medien.py,
    Z-Image Turbo auf der zweiten Karte, ~15 s je Bild), Querformat.
  - Abgelegt wird je Bild unter einem SCHLUESSEL AUS DER BESCHREIBUNG, nicht
    unter der Foliennummer. Wird die Praesentation im Ergebnisfenster
    ueberarbeitet, bleiben unveraenderte Bilder gueltig, eine geaenderte
    Beschreibung zeigt bis zum Neurechnen kein falsches Bild -- es braucht
    dafuer keine zweite Buchfuehrung.
  - Als JPEG in 1280 Punkt Breite (Pillow kommt mit python-pptx ohnehin mit):
    die Ansicht bettet die Bilder ein (der abgeschottete Rahmen der Vorschau
    darf keine Anfragen mit Anmeldung stellen), und sieben PNG zu je 2 MB
    waeren eine 14-MB-Seite.

Kostet nur Rechenzeit auf der eigenen Hardware -- laeuft deshalb ohne Rueckfrage.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

from . import db
from .konfig import MEDIEN_DIR

BILD_ZEILE = re.compile(r"^\s*[-*•]?\s*\**\s*(bildbeschreibung|bildidee|bild|visual|image)\b[^:]{0,30}:\s*\**\s*(.+)$", re.I)
# Bis 17.10.2026 ging die DEUTSCHE Beschreibung samt "ohne Schrift" an Z-Image --
# und das Modell malte deutsche Woerter als verstuemmelte Schrift ins Bild
# ("Ein vied eet Keim", "Verbüћgt ezer Mensch" in der ExO-Praesentation).
# Jetzt: das lokale Modell schreibt fuer ALLE Bilder einer Praesentation auf
# einmal englische Bildanweisungen in EINEM Stil (_kunstregie), gerechnet wird
# mit Qwen-Image und einer Liste dessen, was NICHT ins Bild soll.
ZUSATZ = (", premium editorial illustration for a keynote presentation, cinematic lighting, clean composition, "
          "generous negative space, high detail, no text")
NEGATIV = ("text, letters, words, typography, caption, title, label, signage, watermark, logo, signature, numbers, "
           "blurry, low quality, deformed, distorted hands, extra fingers, cluttered")
VORLAGE, VORLAGE_ERSATZ = "qwen", "z-image"
LAUFEND: dict[str, asyncio.Task] = {}
MAX_BILDER = 20


def folien_roh(md: str) -> list[str]:
    """Die Folien als Rohtext -- dieselbe Aufteilung fuer Vorschau, PowerPoint
    und Bilder, sonst landet ein Bild auf der falschen Folie."""
    teile = [t for t in re.split(r"(?m)^\s*---+\s*$", md or "") if t.strip()]
    if len(teile) <= 1:
        teile = [t for t in re.split(r"(?m)^(?=#{1,2}\s)", md or "") if t.strip()]
    return teile


def bild_text(roh: str) -> str:
    """Die Beschreibung aus einer Bildzeile, ohne Markdown-Reste. EINE Stelle,
    weil der Dateischluessel daraus entsteht: weicht das Saeubern beim Rechnen
    und beim Einbauen ab, findet der Einbau das Bild nie."""
    return re.sub(r"\*\*|__", "", roh).strip().strip("*").strip()[:900]


def bild_prompt(folie: str) -> str | None:
    for z in folie.splitlines():
        m = BILD_ZEILE.match(z)
        if m and len(bild_text(m.group(2))) >= 8:
            return bild_text(m.group(2))
    return None


# Wo Bilder gerechnet werden: Folien und alles, was als Text/Word ausgegeben
# wird. Webseiten bringen ihr eigenes HTML mit, Videos haben ein Drehbuch.
MIT_BILDERN = ("praesentation", "text", "aufstellung", "konzept", "dokument")


def prompts(md: str, form: str = "praesentation") -> list[str | None]:
    """Praesentation: ein Bild je Folie (das erste der Folie). Sonst: jede
    Bildzeile im Text, an ihrer Stelle."""
    if form == "praesentation":
        return [bild_prompt(f) for f in folien_roh(md)]
    return [bild_text(m.group(2)) for z in (md or "").splitlines()
            if (m := BILD_ZEILE.match(z)) and len(bild_text(m.group(2))) >= 8]


def _schluessel(prompt: str) -> str:
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12]


def datei(eid: str, prompt: str) -> Path:
    return MEDIEN_DIR / f"{eid}-f{_schluessel(prompt)}.jpg"


def vorhanden(eid: str, prompt: str | None) -> bytes | None:
    if not prompt:
        return None
    p = datei(eid, prompt)
    return p.read_bytes() if p.is_file() else None


def daten_uri(roh: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(roh).decode("ascii")


# ------------------------------------------------------------ Stand am Ergebnis
def _stand_setzen(eid: str, **werte: Any) -> None:
    e = db.holen("ergebnisse", eid) or {}
    m = e.get("medien") if isinstance(e.get("medien"), dict) else {}
    s = dict(m.get("folienbilder") or {})
    s.update(werte, geaendert=time.time())
    m["folienbilder"] = s
    db.ausfuehren("UPDATE ergebnisse SET medien=? WHERE id=?", (json.dumps(m, ensure_ascii=False), eid))


def stand(e: dict[str, Any]) -> dict[str, Any] | None:
    """Was die Oberflaeche braucht: wie viele Bilder gewuenscht sind, wie viele
    es schon gibt, und ob gerade gerechnet wird. None bei Formen ohne Bilder."""
    if e.get("form") not in MIT_BILDERN:
        return None
    ps = [p for p in prompts(e.get("inhalt") or "", e["form"]) if p]
    s = dict(((e.get("medien") if isinstance(e.get("medien"), dict) else {}) or {}).get("folienbilder") or {})
    if s.get("stand") == "rechnet" and e["id"] not in LAUFEND:
        s["stand"] = "abgebrochen"
    s["gewuenscht"] = len(ps)
    s["vorhanden"] = sum(1 for p in ps if datei(e["id"], p).is_file())
    return s


# ------------------------------------------------------------ rechnen
def _als_jpeg(png: bytes) -> bytes:
    from PIL import Image
    b = Image.open(BytesIO(png)).convert("RGB")
    if b.width > 1280:
        b = b.resize((1280, round(b.height * 1280 / b.width)))
    out = BytesIO()
    b.save(out, "JPEG", quality=84, optimize=True)
    return out.getvalue()


async def _kunstregie(eid: str, liste: list[str]) -> list[str]:
    """Deutsche Bildbeschreibungen -> englische Bildanweisungen in EINEM Stil fuer
    die ganze Praesentation. Faellt das Modell aus, gehen die deutschen Texte mit
    englischem Zusatz raus (schlechter, aber kein Abbruch)."""
    from . import llm
    e = db.holen("ergebnisse", eid) or {}
    modell = await llm.modell_waehlen(llm.vorgabe("arbeit"), llm.vorgabe("talk"), "qwen3.6:27b")
    if not modell:
        return liste
    frage = (f"PRÄSENTATION: {e.get('titel') or ''}\n\nBILDWÜNSCHE (deutsch, in dieser Reihenfolge):\n"
             + "\n".join(f"{i + 1}. {p}" for i, p in enumerate(liste))
             + "\n\nDu bist Art Director. Lege EINEN gemeinsamen visuellen Stil für alle Bilder fest (Bildsprache, Farbpalette, "
               "Licht, Materialien -- passend zu einem eleganten, dunkelblau-warmen Business-Design) und schreibe für jeden "
               "Wunsch eine englische Bildanweisung für ein Bildmodell: konkretes Motiv, Komposition (Platz links oder rechts "
               "für Text, wo sinnvoll), Perspektive, Licht, Stil. 40 bis 80 Wörter je Bild. NIEMALS Text, Buchstaben, Zahlen, "
               "Schilder, Logos oder Bildschirme mit Schrift; keine echten, erkennbaren Personen. Antworte NUR mit JSON: "
               '{"stil": "der gemeinsame Stil auf Englisch", "bilder": ["Anweisung 1", "..."]}')
    try:
        d = llm.json_aus(await llm.chat(modell, "", [{"role": "user", "content": frage}], json_format=True,
                                        temperatur=0.4, denken=False, timeout=300)) or {}
    except llm.ModellFehler:
        return liste
    bilder = [str(b).strip() for b in (d.get("bilder") or []) if str(b).strip()]
    if len(bilder) != len(liste):
        return liste
    stil = str(d.get("stil") or "").strip()
    return [f"{b}. Style: {stil}" if stil else b for b in bilder]


async def _lauf(eid: str, liste: list[str]) -> None:
    from . import medien
    t0 = time.time()
    _stand_setzen(eid, stand="rechnet", anzahl=len(liste), fertig=0, fehler=None, start=t0, schritt="Art Direction: Bildstil festlegen")
    fehler = 0
    try:
        englisch = await _kunstregie(eid, liste)
        async with httpx.AsyncClient(timeout=60) as c:
            for i, p in enumerate(liste):
                _stand_setzen(eid, schritt=f"Bild {i + 1} von {len(liste)}", fertig=i)
                try:
                    try:
                        png = await medien.comfy_bild(c, englisch[i] + ZUSATZ, VORLAGE, 1344, 768, NEGATIV)
                    except RuntimeError as x:
                        print(f"[folienbilder] {eid} Bild {i + 1} mit {VORLAGE} gescheitert ({x}) -- nehme {VORLAGE_ERSATZ}", flush=True)
                        png = await medien.comfy_bild(c, englisch[i] + ZUSATZ, VORLAGE_ERSATZ, 1344, 768, NEGATIV)
                    # Abgelegt unter der DEUTSCHEN Beschreibung -- daran findet der Einbau das Bild.
                    datei(eid, p).write_bytes(await asyncio.to_thread(_als_jpeg, png))
                except Exception as x:  # noqa: BLE001 -- ein Bild darf scheitern, die anderen nicht
                    fehler += 1
                    print(f"[folienbilder] {eid} Bild {i + 1}: {x}", flush=True)
        _stand_setzen(eid, stand="fertig" if not fehler else "fehler", fertig=len(liste) - fehler,
                      fehler=(f"{fehler} von {len(liste)} Bildern ließen sich nicht rechnen." if fehler else None),
                      dauer_s=round(time.time() - t0))
    except Exception as x:  # noqa: BLE001
        _stand_setzen(eid, stand="fehler", fehler=f"{x.__class__.__name__}: {str(x)[:300]}")
    finally:
        LAUFEND.pop(eid, None)


def starten(eid: str, neu: bool = False) -> int:
    """Rechnet die fehlenden Bilder (mit neu=True alle). Gibt die Zahl der zu
    rechnenden Bilder zurueck; 0 = nichts zu tun oder laeuft schon."""
    if eid in LAUFEND:
        return 0
    e = db.holen("ergebnisse", eid)
    if not e or e.get("form") not in MIT_BILDERN:
        return 0
    ps = [p for p in prompts(e.get("inhalt") or "", e["form"]) if p][:MAX_BILDER]
    if neu:
        for p in ps:
            datei(eid, p).unlink(missing_ok=True)
    liste = [p for p in dict.fromkeys(ps) if not datei(eid, p).is_file()]
    if not liste:
        return 0
    # Sofort als "rechnet" vermerken: die Antwort auf das Oeffnen soll den
    # Fortschritt schon zeigen, nicht erst der naechste Abruf.
    _stand_setzen(eid, stand="rechnet", anzahl=len(liste), fertig=0, fehler=None, schritt="beginnt")
    LAUFEND[eid] = asyncio.create_task(_lauf(eid, liste))
    return len(liste)
