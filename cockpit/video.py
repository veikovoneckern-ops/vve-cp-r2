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

from . import db
from .konfig import COMFY, MEDIEN_DIR

VORLAGE = json.loads(Path(__file__).with_name("video_vorlage.json").read_text(encoding="utf-8"))
BREITE, HOEHE, FPS = 848, 480, 24          # Querformat; die Vorlage kann beides
MAX_SZENEN = 16
SZENE_BILDER = 121                          # 5 s bei 24 fps; Hunyuan will 4*n+1
LAUFEND: dict[str, asyncio.Task] = {}

DREHBUCH_ANWEISUNG = (
    "Liefere ein Drehbuch für ein Erklärvideo. Zuerst in Markdown kurz Ziel, Zielgruppe und Ablauf. "
    "Danach GENAU EINEN Block ```json mit {\"titel\": \"…\", \"szenen\": [{\"bild\": \"…\", \"text\": \"…\"}]}. "
    "Je Szene etwa 5 Sekunden: \"text\" ist der deutsche Sprechertext, höchstens 14 Wörter, ganze Sätze, gut vorlesbar "
    "(Abkürzungen ausschreiben, keine Klammern). \"bild\" ist eine ausführliche ENGLISCHE Bildbeschreibung für ein "
    "Videomodell: Motiv, Stil, Licht, Kamerabewegung; keine Schrift im Bild, keine echten Personen, keine Logos. "
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
            "szenen": [{"bild": str(s["bild"])[:1500], "text": str(s["text"])[:300]} for s in szenen]}


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


# ------------------------------------------------------------ zusammenschneiden
def _zusammensetzen(szenen: list[tuple[bytes, bytes]], ziel: Path) -> float:
    """[(mp4 der Szene, mp3 des Sprechtexts)] -> ein mp4 mit Ton. Gibt die Laenge zurueck."""
    import av
    import numpy as np
    rate = 24000
    aus = av.open(str(ziel.with_suffix(".tmp.mp4")), "w")
    vs = aus.add_stream("libx264", rate=FPS)
    vs.width, vs.height, vs.pix_fmt = BREITE, HOEHE, "yuv420p"
    vs.options = {"crf": "20", "preset": "medium"}
    ast = aus.add_stream("aac", rate=rate)
    ast.layout = "mono"
    resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
    bild_nr, ton_proben = 0, 0
    for clip, sprache in szenen:
        bilder = []
        with av.open(io.BytesIO(clip)) as ein:
            for f in ein.decode(video=0):
                bilder.append(f.reformat(width=BREITE, height=HOEHE, format="yuv420p"))
        proben = []
        with av.open(io.BytesIO(sprache)) as ein:
            for f in ein.decode(audio=0):
                for r in resampler.resample(f):
                    proben.append(r.to_ndarray().reshape(-1))
        ton = np.concatenate(proben) if proben else np.zeros(0, dtype=np.int16)
        ton = np.concatenate([np.zeros(int(rate * 0.25), dtype=np.int16), ton, np.zeros(int(rate * 0.35), dtype=np.int16)])
        dauer = max(len(bilder) / FPS, len(ton) / rate)
        n_bilder = int(round(dauer * FPS))
        for i in range(n_bilder):
            f = bilder[min(i, len(bilder) - 1)] if bilder else None
            if f is None:
                continue
            neu = av.VideoFrame.from_ndarray(f.to_ndarray(format="rgb24"), format="rgb24").reformat(format="yuv420p")
            neu.pts, neu.time_base = bild_nr, Fraction(1, FPS)
            bild_nr += 1
            for p in vs.encode(neu):
                aus.mux(p)
        ton = np.concatenate([ton, np.zeros(max(0, int(dauer * rate) - len(ton)), dtype=np.int16)])
        for start in range(0, len(ton), 1024):
            stueck = ton[start:start + 1024].reshape(1, -1)
            af = av.AudioFrame.from_ndarray(stueck, format="s16", layout="mono")
            af.sample_rate, af.pts, af.time_base = rate, ton_proben, Fraction(1, rate)
            ton_proben += stueck.shape[1]
            for p in ast.encode(af):
                aus.mux(p)
    for p in vs.encode():
        aus.mux(p)
    for p in ast.encode():
        aus.mux(p)
    aus.close()
    ziel.with_suffix(".tmp.mp4").replace(ziel)
    return bild_nr / FPS


# ------------------------------------------------------------ der ganze Lauf
async def _lauf(eid: str, drehbuch: dict[str, Any]) -> None:
    from . import stimme
    szenen = drehbuch["szenen"]
    t0 = time.time()
    _stand_setzen(eid, stand="rechnet", schritt="beginnt", szenen=len(szenen), fertig=0, fehler=None, start=t0, datei=None)
    teile: list[tuple[bytes, bytes]] = []
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            for i, s in enumerate(szenen):
                _stand_setzen(eid, schritt=f"Szene {i + 1} von {len(szenen)}: Sprecher", fertig=i)
                ton = await stimme.sprechen(s["text"])
                _stand_setzen(eid, schritt=f"Szene {i + 1} von {len(szenen)}: Video wird gerechnet")
                clip = await _szene(c, s["bild"])
                teile.append((clip, ton))
        _stand_setzen(eid, schritt="schneidet zusammen", fertig=len(szenen))
        laenge = await asyncio.to_thread(_zusammensetzen, teile, datei(eid))
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
    LAUFEND[eid] = asyncio.create_task(_lauf(eid, drehbuch))
    return True
