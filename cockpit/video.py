"""
ERKLAERVIDEOS -- aus Ridleys Drehbuch wird ein echtes Video mit Sprecherstimme.

Veiko (16.10.2026): "ich hatte die Aufgabe erteilt, ein Video zu erstellen,
aber das geschieht nicht." Bis dahin schrieb Ridley nur Drehbuch und Prompts;
gerechnet wurde nichts, weil diese Fassung nur Bilder und Schaubilder kannte.

Ablauf je Szene:
  1. Sprechtext -> Piper (dieselbe Stimme wie Talk), Dauer messen
  2. Bild-Prompt -> HunyuanVideo 1.5 in ComfyUI (Vorlage aus dem alten
     Cockpit, dort aus dem echten Workflow umgerechnet und durchgelaufen)
  3. zusammenschneiden mit PyAV (liegt fuer Whisper ohnehin im venv; ffmpeg
     gibt es auf dem Server nur im ComfyUI-Container)
Ist der Sprechtext laenger als die Szene, steht das letzte Bild still, bis er
fertig ist -- lieber ein ruhiges Bild als ein abgeschnittener Satz.

Warum im Hintergrund und nicht im Durchgang des Teams: eine Minute Video sind
zwoelf Szenen zu je einigen Minuten Rechenzeit auf der zweiten Karte. Das darf
die Einordnung neuer Notizen nicht eine Stunde lang aufhalten.

Der Stand steht am Ergebnis (Spalte medien), damit er einen Neustart des
Dienstes ueberlebt: ein Lauf, der nach einem Neustart nicht mehr existiert,
heisst "abgebrochen" und laesst sich mit einem Klick neu starten.
"""
from __future__ import annotations

import asyncio
import io
import json
import random
import re
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

import httpx

from . import db, llm
from .konfig import COMFY, MEDIEN_DIR

VORLAGE = json.loads(Path(__file__).with_name("video_vorlage.json").read_text(encoding="utf-8"))
BREITE, HOEHE, FPS = 848, 480, 24          # was HunyuanVideo rechnet (Bewegtszenen)
AUS_B, AUS_H = 1280, 720                    # was das fertige Video hat (17.10.2026: vorher 848x480)
MAX_SZENEN = 16
SZENE_BILDER = 121                          # 5 s bei 24 fps; Hunyuan will 4*n+1
BEWEGT_ANTEIL = 0.34                        # hoechstens jede dritte Szene als echtes Bewegtbild
LAUFEND: dict[str, asyncio.Task] = {}
# Gestaltung wie die Folien (folien.py): Marineblau, Bernstein.
DUNKEL, AKZENT = (11, 24, 38), (201, 134, 26)
SCHRIFT, SCHRIFT_FETT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Umbau 17.10.2026 (Veiko: "jetzt auch fuer Videos pruefen und ggf. umbauen"). Befund
# am Video vom 16.10.: 848x480, unscharf, jede Szene in anderem Stil, keine einzige
# Einblendung -- und 16 Minuten Rechenzeit je 5-Sekunden-Szene. Jetzt:
#   - eine Bildregie fuer alle Szenen (folienbilder.kunstregie, wie bei den Folien),
#   - "Bildfilm" als Regel: ein scharfes Standbild (Qwen-Image, 1344x768) mit
#     langsamer Kamerafahrt, ~1,5 Minuten je Szene,
#   - echtes Bewegtbild (HunyuanVideo) nur, wo Ridley "bewegung" setzt, hoechstens
#     jede dritte Szene,
#   - Einblendung, Untertitel, Vor- und Abspann setzt das COCKPIT (Pillow), nicht
#     das Bildmodell -- das malt Schrift nur als Buchstabensalat.
DREHBUCH_ANWEISUNG = (
    "Liefere ein Drehbuch für ein Erklärvideo. Zuerst in Markdown kurz Ziel, Zielgruppe und Ablauf. "
    "Danach GENAU EINEN Block ```json mit {\"titel\": \"…\", \"szenen\": [{\"bild\": \"…\", \"text\": \"…\", "
    "\"einblendung\": \"…\", \"bewegung\": false}]}. "
    "Je Szene etwa 5 Sekunden: \"text\" ist der deutsche Sprechertext, höchstens 14 Wörter, ganze Sätze, gut vorlesbar "
    "(Abkürzungen ausschreiben, keine Klammern). \"bild\" ist eine ausführliche ENGLISCHE Bildbeschreibung: Motiv, Stil, "
    "Licht; keine Schrift im Bild, keine echten Personen, keine Logos. \"einblendung\": die Kernaussage der Szene in "
    "höchstens 6 Wörtern -- das Cockpit setzt sie als Schrift ins Bild (leer lassen, wo keine nötig ist). \"bewegung\": "
    "true nur, wo echte Bewegung die Aussage trägt (Fluss, Wachstum, Menschen in Aktion) -- höchstens jede dritte Szene; "
    "sonst false, dann wird ein Standbild mit Kamerafahrt daraus. Alle Szenen im selben Bildstil. "
    "Die Szenenzahl ergibt sich aus der gewünschten Länge (eine Minute ≈ 12 Szenen), höchstens 16. "
    "Bleib bei dem, was die Notiz verlangt, und erfinde keine Fakten.")


def drehbuch_aus(text: str, grenze: int = MAX_SZENEN) -> dict[str, Any] | None:
    m = re.search(r"```json\s*(\{[\s\S]*?\})\s*```", text or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
    except ValueError:
        return None
    szenen = [s for s in (d.get("szenen") or []) if isinstance(s, dict) and str(s.get("bild") or "").strip()
              and str(s.get("text") or "").strip()][:grenze]
    if not szenen:
        return None
    return {"titel": str(d.get("titel") or "Erklärvideo")[:120],
            "szenen": [{"bild": str(s["bild"])[:1500], "text": str(s["text"])[:300],
                        "einblendung": str(s.get("einblendung") or "")[:60],
                        "bewegung": s.get("bewegung") is True or str(s.get("bewegung")).lower() == "true"} for s in szenen]}


# ------------------------------------------------------------ Stand am Ergebnis
def _stand_setzen(eid: str, **werte: Any) -> None:
    e = db.holen("ergebnisse", eid) or {}
    m = e.get("medien") if isinstance(e.get("medien"), dict) else {}
    v = dict(m.get("video") or {})
    v.update(werte, geaendert=time.time())
    m["video"] = v
    db.ausfuehren("UPDATE ergebnisse SET medien=? WHERE id=?", (json.dumps(m, ensure_ascii=False), eid))


def stand(e: dict[str, Any]) -> dict[str, Any] | None:
    """Der Video-Stand eines Ergebnisses, mit "abgebrochen" fuer einen Lauf,
    den es nach einem Neustart nicht mehr gibt."""
    v = ((e.get("medien") if isinstance(e.get("medien"), dict) else {}) or {}).get("video")
    if not v:
        return None
    v = dict(v)
    if v.get("stand") == "rechnet" and e["id"] not in LAUFEND:
        v["stand"] = "abgebrochen"
    return v


def datei(eid: str) -> Path:
    return MEDIEN_DIR / f"{eid}.mp4"


# ------------------------------------------------------------ eine Szene
async def _szene(c: httpx.AsyncClient, prompt: str) -> bytes:
    g = json.loads(json.dumps(VORLAGE["graph"]))
    k = VORLAGE["knoten"]
    g[k["prompt"]]["inputs"]["text"] = prompt
    if k.get("negativ"):
        g[k["negativ"]]["inputs"]["text"] = "text, letters, watermark, logo, blurry, distorted faces, low quality"
    g[k["groesse"]]["inputs"].update(width=BREITE, height=HOEHE, length=SZENE_BILDER)
    g[k["seed"]]["inputs"][k["seedFeld"]] = random.randint(1, 2**48)
    from . import medien
    medien.comfy_benutzt()
    r = await c.post(f"{COMFY}/prompt", json={"prompt": g, "client_id": "vve-cockpit-r2-video"})
    if r.status_code >= 400:
        raise RuntimeError(f"ComfyUI lehnt ab: {r.text[:200]}")
    pid = r.json()["prompt_id"]
    for _ in range(2400):                               # bis zu 40 Minuten je Szene
        await asyncio.sleep(2)
        h = (await c.get(f"{COMFY}/history/{pid}")).json().get(pid)
        if not h:
            continue
        if (h.get("status") or {}).get("status_str") == "error":
            raise RuntimeError("ComfyUI meldet einen Fehler beim Rechnen.")
        for o in (h.get("outputs") or {}).values():
            for x in (o.get("videos") or []) + (o.get("images") or []) + (o.get("gifs") or []):
                if str(x.get("filename", "")).lower().endswith((".mp4", ".webm", ".mov")):
                    return (await c.get(f"{COMFY}/view", params={"filename": x["filename"], "subfolder": x.get("subfolder", ""),
                                                                 "type": x.get("type", "output")})).content
        if (h.get("status") or {}).get("completed"):
            raise RuntimeError("ComfyUI ist fertig, hat aber kein Video abgelegt.")
    raise RuntimeError("Eine Szene hat nach 40 Minuten nichts geliefert.")


# ------------------------------------------------------------ Gestaltung (Pillow)
def _schrift(fett: bool, groesse: int):
    from PIL import ImageFont
    try:
        return ImageFont.truetype(SCHRIFT_FETT if fett else SCHRIFT, groesse)
    except OSError:
        return ImageFont.load_default()


def _umbrechen(draw, text: str, font, breite: int) -> list[str]:
    zeilen, z = [], ""
    for w in text.split():
        probe = (z + " " + w).strip()
        if draw.textlength(probe, font=font) <= breite or not z:
            z = probe
        else:
            zeilen.append(z)
            z = w
    if z:
        zeilen.append(z)
    return zeilen


def _ebene(einblendung: str, untertitel: str):
    """Die Schrift einer Szene als durchsichtige Ebene -- einmal je Szene gerechnet,
    dann auf jedes Bild gelegt. Einblendung unten links (Bernstein-Strich, Marine-
    Kasten), Untertitel unten mittig."""
    from PIL import Image, ImageDraw
    e = Image.new("RGBA", (AUS_B, AUS_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(e)
    if einblendung:
        f = _schrift(True, 38)
        zeilen = _umbrechen(d, einblendung, f, 640)[:2]
        h = 22 + 48 * len(zeilen)
        y0 = 70
        d.rectangle([60, y0, 60 + 30 + max(d.textlength(z, font=f) for z in zeilen) + 30, y0 + h], fill=DUNKEL + (215,))
        d.rectangle([60, y0, 66, y0 + h], fill=AKZENT + (255,))
        for i, z in enumerate(zeilen):
            d.text((90, y0 + 12 + 48 * i), z, font=f, fill=(255, 255, 255, 255))
    if untertitel:
        f = _schrift(False, 28)
        zeilen = _umbrechen(d, untertitel, f, 1040)[:2]
        for i, z in enumerate(reversed(zeilen)):
            w = d.textlength(z, font=f)
            y = AUS_H - 64 - i * 40
            d.rectangle([(AUS_B - w) / 2 - 14, y - 6, (AUS_B + w) / 2 + 14, y + 34], fill=(0, 0, 0, 150))
            d.text(((AUS_B - w) / 2, y - 2), z, font=f, fill=(255, 255, 255, 255))
    return e


def _karte(titel: str, unter: str):
    """Vor- und Abspann im Design der Folien."""
    from PIL import Image, ImageDraw
    b = Image.new("RGB", (AUS_B, AUS_H), DUNKEL)
    d = ImageDraw.Draw(b)
    f = _schrift(True, 60)
    zeilen = _umbrechen(d, titel, f, 1050)[:3]
    y = AUS_H / 2 - (len(zeilen) * 72) / 2 - 20
    d.rectangle([110, y - 34, 190, y - 28], fill=AKZENT)
    for i, z in enumerate(zeilen):
        d.text((110, y + i * 72), z, font=f, fill=(255, 255, 255))
    if unter:
        d.text((110, y + len(zeilen) * 72 + 24), unter, font=_schrift(False, 28), fill=(232, 194, 122))
    return b


def _fahrt(bild, n: int, richtung: int):
    """Kamerafahrt ueber ein Standbild: langsamer Zoom (100 -> 112 %) mit leichtem
    Schwenk, weich beschleunigt und gebremst. richtung wechselt je Szene, damit
    nicht jede Szene gleich wirkt."""
    from PIL import Image
    b = bild.convert("RGB")
    q = AUS_B / AUS_H
    if b.width / b.height > q:
        w0, h0 = int(b.height * q), b.height
    else:
        w0, h0 = b.width, int(b.width / q)
    for i in range(n):
        t = i / max(1, n - 1)
        t = t * t * (3 - 2 * t)                       # weich
        z = 1 + 0.12 * (t if richtung % 2 == 0 else 1 - t)
        w, h = w0 / z, h0 / z
        dx = (b.width - w) * (0.5 + 0.35 * (t - 0.5) * (1 if richtung % 4 < 2 else -1))
        dy = (b.height - h) * 0.5
        yield b.crop((dx, dy, dx + w, dy + h)).resize((AUS_B, AUS_H), Image.BILINEAR)


# ------------------------------------------------------------ zusammenschneiden
def _zusammensetzen(szenen: list[dict[str, Any]], ziel: Path, titel: str = "") -> float:
    """[{art: bild|clip, roh, ton, einblendung, text}] -> ein mp4 mit Ton, 1280x720.
    Vorspann und Abspann kommen dazu. Gibt die Laenge zurueck."""
    import av
    import numpy as np
    from PIL import Image
    rate = 24000
    aus = av.open(str(ziel.with_suffix(".tmp.mp4")), "w")
    vs = aus.add_stream("libx264", rate=FPS)
    vs.width, vs.height, vs.pix_fmt = AUS_B, AUS_H, "yuv420p"
    vs.options = {"crf": "19", "preset": "medium"}
    ast = aus.add_stream("aac", rate=rate)
    ast.layout = "mono"
    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    zaehler = {"bild": 0, "ton": 0}

    def bild_schreiben(img) -> None:
        f = av.VideoFrame.from_image(img.convert("RGB")).reformat(format="yuv420p")
        f.pts, f.time_base = zaehler["bild"], Fraction(1, FPS)
        zaehler["bild"] += 1
        for p in vs.encode(f):
            aus.mux(p)

    def ton_schreiben(ton) -> None:
        for start in range(0, len(ton), 1024):
            stueck = ton[start:start + 1024].reshape(1, -1)
            af = av.AudioFrame.from_ndarray(stueck, format="s16", layout="mono")
            af.sample_rate, af.pts, af.time_base = rate, zaehler["ton"], Fraction(1, rate)
            zaehler["ton"] += stueck.shape[1]
            for p in ast.encode(af):
                aus.mux(p)

    def karte(img, sek: float) -> None:
        n = int(sek * FPS)
        for i in range(n):
            a = min(1.0, i / 12, (n - 1 - i) / 12)     # ein- und ausblenden
            bild_schreiben(Image.blend(Image.new("RGB", img.size, (0, 0, 0)), img, max(0.0, a)))
        ton_schreiben(np.zeros(int(n / FPS * rate), dtype=np.int16))

    karte(_karte(titel or "Erklärvideo", time.strftime("%d.%m.%Y")), 3.0)
    for nr, s in enumerate(szenen):
        proben = []
        with av.open(io.BytesIO(s["ton"])) as ein:
            for f in ein.decode(audio=0):
                for r in resampler.resample(f):
                    proben.append(r.to_ndarray().reshape(-1))
        ton = np.concatenate(proben) if proben else np.zeros(0, dtype=np.int16)
        ton = np.concatenate([np.zeros(int(rate * 0.3), dtype=np.int16), ton, np.zeros(int(rate * 0.45), dtype=np.int16)])
        ebene = _ebene(s.get("einblendung") or "", s.get("text") or "")
        if s["art"] == "clip":
            bilder = []
            with av.open(io.BytesIO(s["roh"])) as ein:
                for f in ein.decode(video=0):
                    bilder.append(f.to_image().resize((AUS_B, AUS_H), Image.BICUBIC))
            n = int(round(max(len(bilder) / FPS, len(ton) / rate) * FPS))
            folge = (bilder[min(i, len(bilder) - 1)] for i in range(n)) if bilder else iter(())
        else:
            n = int(round(max(4.0, len(ton) / rate) * FPS))
            folge = _fahrt(Image.open(io.BytesIO(s["roh"])), n, nr)
        for i, img in enumerate(folge):
            a = min(1.0, i / 8, (n - 1 - i) / 8)       # weiche Uebergaenge zwischen Szenen
            img = Image.alpha_composite(img.convert("RGBA"), ebene).convert("RGB")
            if a < 1:
                img = Image.blend(Image.new("RGB", img.size, (0, 0, 0)), img, max(0.0, a))
            bild_schreiben(img)
        ton = np.concatenate([ton, np.zeros(max(0, int(n / FPS * rate) - len(ton)), dtype=np.int16)])[:int(n / FPS * rate)]
        ton_schreiben(ton)
    karte(_karte(titel or "", "Erstellt im VvE Cockpit"), 2.5)
    for p in vs.encode():
        aus.mux(p)
    for p in ast.encode():
        aus.mux(p)
    aus.close()
    ziel.with_suffix(".tmp.mp4").replace(ziel)
    return zaehler["bild"] / FPS


# ------------------------------------------------------------ der ganze Lauf
async def _lauf(eid: str, drehbuch: dict[str, Any]) -> None:
    from . import folienbilder, medien, stimme
    szenen = drehbuch["szenen"]
    t0 = time.time()
    _stand_setzen(eid, stand="rechnet", schritt="Bildregie: ein Stil für alle Szenen", szenen=len(szenen), fertig=0,
                  fehler=None, start=t0, datei=None)
    teile: list[dict[str, Any]] = []
    try:
        regie = await folienbilder.kunstregie(drehbuch.get("titel") or "", [s["bild"] for s in szenen], "ERKLÄRVIDEO",
                                              "Die Bilder werden zu Videoszenen; halte Motive und Farben über alle Szenen zusammenhängend. ")
        bewegt_frei = max(1, int(len(szenen) * BEWEGT_ANTEIL)) if any(s.get("bewegung") for s in szenen) else 0
        async with httpx.AsyncClient(timeout=60) as c:
            for i, s in enumerate(szenen):
                _stand_setzen(eid, schritt=f"Szene {i + 1} von {len(szenen)}: Sprecher", fertig=i)
                ton = await stimme.sprechen(s["text"])
                prompt = regie[i] if i < len(regie) else s["bild"]
                if s.get("bewegung") and bewegt_frei > 0:
                    bewegt_frei -= 1
                    _stand_setzen(eid, schritt=f"Szene {i + 1} von {len(szenen)}: Bewegtbild wird gerechnet (dauert)")
                    teile.append({"art": "clip", "roh": await _szene(c, prompt), "ton": ton, **s})
                else:
                    _stand_setzen(eid, schritt=f"Szene {i + 1} von {len(szenen)}: Bild wird gerechnet")
                    try:
                        roh = await medien.comfy_bild(c, prompt + folienbilder.ZUSATZ, folienbilder.VORLAGE, 1344, 768, folienbilder.NEGATIV)
                    except RuntimeError:
                        roh = await medien.comfy_bild(c, prompt + folienbilder.ZUSATZ, folienbilder.VORLAGE_ERSATZ, 1344, 768, folienbilder.NEGATIV)
                    teile.append({"art": "bild", "roh": roh, "ton": ton, **s})
        _stand_setzen(eid, schritt="schneidet zusammen", fertig=len(szenen))
        laenge = await asyncio.to_thread(_zusammensetzen, teile, datei(eid), drehbuch.get("titel") or "")
        _stand_setzen(eid, stand="fertig", schritt="fertig", datei=datei(eid).name, laenge_s=round(laenge, 1),
                      dauer_s=round(time.time() - t0))
    except Exception as e:  # noqa: BLE001 -- jeder Abbruch soll am Ergebnis stehen, nicht nur im Journal
        _stand_setzen(eid, stand="fehler", fehler=f"{e.__class__.__name__}: {str(e)[:300]}")
        print(f"[video] {eid} gescheitert: {e}", flush=True)
    finally:
        LAUFEND.pop(eid, None)


def starten(eid: str, drehbuch: dict[str, Any] | None = None) -> bool:
    """Startet (oder wiederholt) das Rechnen. Ohne Drehbuch nimmt es das gemerkte."""
    if eid in LAUFEND:
        return False
    e = db.holen("ergebnisse", eid)
    if not e:
        return False
    if drehbuch is None:
        # Zuerst der AKTUELLE Inhalt: wurde das Drehbuch im Ergebnisfenster
        # ueberarbeitet, soll "neu rechnen" die neue Fassung nehmen.
        # Grenze hoch: ein Langlaeufer-Video (langlauf.py) hat weit mehr als 16 Szenen.
        drehbuch = drehbuch_aus(e.get("inhalt") or "", 400) or ((e.get("medien") or {}).get("video") or {}).get("drehbuch")
    if not drehbuch:
        return False
    _stand_setzen(eid, drehbuch=drehbuch, stand="rechnet", schritt="wartet auf den Start")
    LAUFEND[eid] = asyncio.create_task(llm.mit_zweck("video:" + eid, _lauf(eid, drehbuch)))
    return True
