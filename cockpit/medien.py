"""
BILDER UND VISUALISIERUNGEN aus dem Gespraech ("erstell mir dazu ein Bild",
"mach mir dazu eine Visualisierung"). Ergebnis erscheint als Vorschau im Talk
und laesst sich herunterladen.

  - BILD: ComfyUI auf der zweiten Karte, mit den Vorlagen aus dem alten
    Cockpit (bild_vorlagen.json -- dort aus den echten Workflows dieser
    Maschine umgerechnet und je einmal durchgelaufen). Geaendert werden nur
    Prompt, Groesse und Seed; alles andere bleibt, wie es in ComfyUI steht.
  - VISUALISIERUNG: ein lokales Modell schreibt ein eigenstaendiges SVG
    (Schaubild, Ablauf, Diagramm, Mindmap). Kein Skript darin -- ein SVG mit
    Skript waere eine Webseite, die im Cockpit liefe. Was sich nicht als SVG
    lesen laesst, gilt als gescheitert und wird einmal neu angefordert.

Beides kostet nur Rechenzeit auf der eigenen Hardware; deshalb laeuft es ohne
Rueckfrage los (Freigaben-Logik: "kostet nur Rechenzeit").
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import httpx

from . import db, llm
from .konfig import COMFY, MEDIEN_DIR, MODELL_NEO

VORLAGEN = {v["id"]: v for v in json.loads((Path(__file__).with_name("bild_vorlagen.json")).read_text(encoding="utf-8"))}
JOBS: dict[str, dict[str, Any]] = {}
FORMATE = {"quadrat": (1024, 1024), "quer": (1344, 768), "hoch": (768, 1344)}


def _job(art: str, titel: str) -> dict[str, Any]:
    jid = db.neue_id("m")
    JOBS[jid] = {"id": jid, "art": art, "titel": titel[:120], "stand": "laeuft", "start": time.time(), "datei": None}
    return JOBS[jid]


def stand(jid: str) -> dict[str, Any] | None:
    if jid in JOBS:
        return JOBS[jid]
    # Nach einem Neustart des Dienstes: das Ergebnis liegt noch auf der Platte.
    for f in MEDIEN_DIR.glob(f"{jid}.*"):
        if f.suffix in (".png", ".svg"):
            return {"id": jid, "stand": "fertig", "datei": f.name, "art": "bild" if f.suffix == ".png" else "visualisierung"}
    return None


# ------------------------------------------------------------ Bild (ComfyUI)
async def _bild(j: dict[str, Any], prompt: str, vorlage: str, format_: str) -> None:
    v = VORLAGEN.get(vorlage) or VORLAGEN["z-image"]
    graph = json.loads(json.dumps(v["graph"]))
    k = v["knoten"]
    graph[k["prompt"]]["inputs"]["text"] = prompt
    breite, hoehe = FORMATE.get(format_, FORMATE["quadrat"])
    for knoten in [k["groesse"], *v.get("groesseAuch", [])]:
        graph[knoten]["inputs"]["width"], graph[knoten]["inputs"]["height"] = breite, hoehe
    graph[k["seed"]]["inputs"][k["seedFeld"]] = random.randint(1, 2**48)
    try:
        async with httpx.AsyncClient(timeout=30) as cl:
            r = await cl.post(f"{COMFY}/prompt", json={"prompt": graph, "client_id": "vve-cockpit-r2"})
            if r.status_code >= 400:
                j.update(stand="fehler", fehler=f"ComfyUI lehnt ab: {r.text[:200]}")
                return
            pid = r.json()["prompt_id"]
            j["schritt"] = "ComfyUI rechnet"
            for _ in range(600):                      # bis zu 10 Minuten
                await asyncio.sleep(1)
                h = (await cl.get(f"{COMFY}/history/{pid}")).json().get(pid)
                if not h:
                    continue
                st = (h.get("status") or {}).get("status_str")
                if st == "error":
                    j.update(stand="fehler", fehler="ComfyUI meldet einen Fehler beim Rechnen.")
                    return
                bilder = [b for o in (h.get("outputs") or {}).values() for b in o.get("images", [])]
                if bilder:
                    b = bilder[0]
                    roh = (await cl.get(f"{COMFY}/view", params={"filename": b["filename"], "subfolder": b.get("subfolder", ""),
                                                                 "type": b.get("type", "output")})).content
                    (MEDIEN_DIR / f"{j['id']}.png").write_bytes(roh)
                    j.update(stand="fertig", datei=f"{j['id']}.png", ende=time.time(), modell=v["name"])
                    return
            j.update(stand="fehler", fehler="ComfyUI hat nach 10 Minuten nichts geliefert.")
    except (httpx.HTTPError, KeyError, ValueError) as e:
        j.update(stand="fehler", fehler=f"ComfyUI nicht erreichbar: {e.__class__.__name__}")


def bild_starten(prompt: str, titel: str, vorlage: str = "z-image", format_: str = "quadrat") -> dict[str, Any]:
    j = _job("bild", titel or prompt)
    j["prompt"] = prompt
    asyncio.create_task(_bild(j, prompt, vorlage, format_))
    return j


# ------------------------------------------------------------ Visualisierung (SVG)
SVG_AUFTRAG = """Du zeichnest ein Schaubild als EIN eigenständiges SVG. Antworte NUR mit dem SVG-Code, beginnend mit <svg und endend mit </svg>, ohne Erklärung, ohne Markdown-Zaun.
Regeln:
- viewBox setzen (z. B. 0 0 1200 800), xmlns="http://www.w3.org/2000/svg", KEIN <script>, keine externen Bilder oder Schriften.
- Weißer Hintergrund (ein <rect> über die ganze Fläche), gut lesbare Schrift (font-family="Segoe UI, Arial, sans-serif", mind. 16px, Text #1E2A36).
- Modern und ruhig, wie das Cockpit: abgerundete Kästen (rx="14"), dünne Ränder, sanfte Flächen im Wechsel (#E1EEEF, #F1EBFE, #E3F3EC, #FBF0DC), Akzent #6A4BD6 für das Wichtigste, Pfeile und Linien #647388. Überschrift oben links fett. Großzügige Abstände.
- Deutsch beschriften. Text darf nicht über Kästen hinauslaufen: kurze Beschriftungen, bei Bedarf mehrere <tspan>-Zeilen.
- Passende Form wählen: Ablauf -> Pfeile von links nach rechts; Hierarchie -> Baum; Vergleich -> Spalten oder Balken; Zusammenhänge -> Mindmap.
- Nur Inhalte aus der Beschreibung, nichts erfinden."""


def _svg_pruefen(text: str) -> str | None:
    m = re.search(r"<svg[\s\S]*</svg>", text)
    if not m:
        return None
    svg = m.group(0)
    if re.search(r"<script|javascript:|on\w+\s*=", svg, re.I):
        return None
    try:
        ET.fromstring(svg)
    except ET.ParseError:
        return None
    return svg


async def _visualisierung(j: dict[str, Any], beschreibung: str) -> None:
    modell = await llm.modell_waehlen(MODELL_NEO, "qwen3-coder:30b", "qwen3.8:27b")
    if not modell:
        j.update(stand="fehler", fehler="Kein lokales Modell installiert.")
        return
    nachrichten = [{"role": "user", "content": beschreibung}]
    for versuch in range(2):
        try:
            text = await llm.chat(modell, SVG_AUFTRAG, nachrichten, temperatur=0.3, num_ctx=16384, timeout=300)
        except llm.ModellFehler as e:
            j.update(stand="fehler", fehler=str(e))
            return
        svg = _svg_pruefen(text)
        if svg:
            (MEDIEN_DIR / f"{j['id']}.svg").write_text(svg, encoding="utf-8")
            j.update(stand="fertig", datei=f"{j['id']}.svg", ende=time.time(), modell=modell)
            return
        nachrichten += [{"role": "assistant", "content": text[:4000]},
                        {"role": "user", "content": "Das war kein gültiges SVG (oder es enthielt Skript). Schick NUR das vollständige, wohlgeformte SVG."}]
    j.update(stand="fehler", fehler="Das Modell hat kein gültiges SVG geliefert.")


def visualisierung_starten(beschreibung: str, titel: str) -> dict[str, Any]:
    j = _job("visualisierung", titel or beschreibung)
    asyncio.create_task(_visualisierung(j, beschreibung))
    return j
