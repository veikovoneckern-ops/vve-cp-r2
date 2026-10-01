"""
MODELLE AKTUELL HALTEN -- welches Modell fuer welche Aufgabe, und ob es Besseres
oder Neueres gibt. Uebernommen aus dem alten Cockpit (AUFGABEN, NEO_AUSSCHAU,
/api/modelle/neuheiten), dazu eine Pruefung, die es dort nicht gab:

  1. AKTUALISIERUNG: Ollama tauscht Gewichte manchmal unter DEMSELBEN Namen
     aus. Verglichen wird die Modelldatei (digest) des installierten Modells
     mit der aktuellen bei Ollama -- am 01.10.2026 fand das sofort gemma4:e4b.
  2. ERSATZ: Je Aufgabe ist der Katalog eine Rangfolge. Gibt es ein Modell,
     das VOR dem besten installierten steht, bei Ollama existiert und auf die
     Karten passt, wird es vorgeschlagen.
  3. AUSSCHAU: Namen kommender Generationen (qwen4, gemma5 ...). Ein 404 ist
     die belastbare Antwort "noch nicht da"; ein 200 steht sofort im Cockpit.

Die Rangfolge ist von Hand gepflegt und begruendet (Messungen im alten Repo,
CLAUDE.md "Leistung und Optimierung"); die Registry sagt nur, OB es etwas
gibt, nicht ob es besser ist. Abgefragt wird je Modell genau EIN Manifest --
die Tag-Liste der Registry antwortet seit September mit 404.
Geladen wird ueber Ollamas eigene Schnittstelle; das braucht kein sudo.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from .konfig import DATEN, OLLAMA

AUFGABEN = [
    {"id": "code", "name": "Programmieren", "kandidaten": ["qwen3-coder:30b", "qwen3.8:27b", "qwen3.6:27b", "devstral:24b"]},
    {"id": "allgemein", "name": "Allgemeine Textarbeit", "kandidaten": ["qwen3.8:27b", "gemma4:12b", "gemma4:e4b", "llama3.3:70b", "qwen3:32b"]},
    {"id": "denken", "name": "Analyse und langes Denken", "kandidaten": ["qwen3.8:27b", "deepseek-r1:32b", "qwen3:32b"]},
    {"id": "schnell", "name": "Schnelle Antworten", "kandidaten": ["gemma4:e4b", "qwen3:30b-a3b", "glm-4.7-flash:latest", "qwen3:8b"]},
    {"id": "werkzeuge", "name": "Werkzeug-Aufrufe", "kandidaten": ["qwen3.8:27b", "gpt-oss:20b", "qwen3:32b"]},
    {"id": "bilder", "name": "Bilder lesen", "kandidaten": ["nemotron3:33b", "qwen3.8:27b", "llava:13b"]},
    {"id": "suche", "name": "Suche über Dokumente", "kandidaten": ["nomic-embed-text:latest", "mxbai-embed-large:latest"]},
]
AUSSCHAU = ["qwen4:27b", "qwen3.9:27b", "gemma5:12b", "llama5:70b", "deepseek-r2:32b", "devstral2:24b", "qwen4-coder:30b"]

DATEI = DATEN / "modell-neuheiten.json"
FRISCH_SEK = 6 * 3600
ACCEPT = "application/vnd.docker.distribution.manifest.v2+json"
MANIFESTE = Path("/usr/share/ollama/.ollama/models/manifests/registry.ollama.ai/library")
LADEN: dict[str, dict[str, Any]] = {}


def _tag(n: str) -> str:
    return n if ":" in n else n + ":latest"


def lokal() -> dict[str, str]:
    """Installierte Modelle -> digest ihrer Modelldatei (aus Ollamas Manifesten)."""
    aus = {}
    try:
        for f in MANIFESTE.glob("*/*"):
            try:
                for l in json.loads(f.read_text(encoding="utf-8")).get("layers") or []:
                    if str(l.get("mediaType", "")).endswith(".model"):
                        aus[f"{f.parent.name}:{f.name}"] = l["digest"]
            except (OSError, ValueError, KeyError):
                continue
    except OSError:
        pass
    return aus


async def _eins(cl: httpx.AsyncClient, tag: str) -> dict[str, Any]:
    familie, _, ausgabe = tag.partition(":")
    try:
        r = await cl.get(f"https://registry.ollama.ai/v2/library/{familie}/manifests/{ausgabe}", headers={"Accept": ACCEPT})
    except httpx.HTTPError as e:
        return {"fehler": e.__class__.__name__}
    if r.status_code == 404:
        return {"da": False}
    if r.status_code >= 400:
        return {"fehler": f"HTTP {r.status_code}"}
    try:
        schichten = r.json().get("layers") or []
    except ValueError:
        return {"da": True}
    modell = next((s.get("digest") for s in schichten if str(s.get("mediaType", "")).endswith(".model")), None)
    groesse = sum(int(s.get("size") or 0) for s in schichten)
    return {"da": True, "gb": round(groesse / 1e9, 1) if groesse else None, "digest": modell}


async def pruefen(frisch: bool = False) -> dict[str, Any]:
    if not frisch:
        try:
            d = json.loads(DATEI.read_text(encoding="utf-8"))
            if time.time() - d.get("zeit", 0) < FRISCH_SEK:
                return d
        except (OSError, ValueError):
            pass
    tags = sorted({_tag(k) for a in AUFGABEN for k in a["kandidaten"]} | set(AUSSCHAU) | set(lokal()))
    ergebnis: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "vve-cockpit-r2"}) as cl:
        for i in range(0, len(tags), 6):
            teil = tags[i:i + 6]
            ergebnis.update(dict(zip(teil, await asyncio.gather(*[_eins(cl, t) for t in teil]))))
    d = {"zeit": time.time(), "ergebnis": ergebnis}
    try:
        DATEI.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass
    return d


def _passt(gb: float | None, vram_gesamt: float) -> str:
    if not gb:
        return "Größe unbekannt"
    g = gb * 1.08
    return "passt auf eine Karte" if g < 22.5 else "passt auf beide Karten" if g < vram_gesamt - 1.5 else "nur mit Auslagerung (langsam)"


def vorschlaege(stand: dict[str, Any] | None, vram_gesamt: float = 48.0) -> list[dict[str, Any]]:
    """Empfehlungen in derselben Form wie systeminfo.empfehlungen()."""
    if not stand:
        return []
    erg = stand.get("ergebnis") or {}
    inst = lokal()
    aus: list[dict[str, Any]] = []
    # 1. gleicher Name, neue Gewichte
    for name, digest in sorted(inst.items()):
        r = erg.get(name) or {}
        if r.get("da") and r.get("digest") and r["digest"] != digest:
            aus.append({"stufe": "einspielen", "titel": f"{name}: neuere Fassung bei Ollama",
                        "warum": f"Unter demselben Namen liegen bei Ollama neue Gewichte ({r.get('gb') or '?'} GB). "
                                 "Laden ersetzt die installierte Fassung; Team-Zuordnungen bleiben.",
                        "aktion": {"art": "modell", "name": name, "text": "Aktualisieren"}})
    # 2. besser eingestuft als das beste installierte
    gesehen = set()
    for a in AUFGABEN:
        kand = [_tag(k) for k in a["kandidaten"]]
        bester = next((i for i, k in enumerate(kand) if k in inst), None)
        grenze = bester if bester is not None else len(kand)
        for k in kand[:grenze]:
            r = erg.get(k) or {}
            if not r.get("da") or k in gesehen:
                continue
            passt = _passt(r.get("gb"), vram_gesamt)
            if "Auslagerung" in passt:
                continue
            gesehen.add(k)
            aus.append({"stufe": "einspielen", "titel": f"{a['name']}: {k} verfügbar",
                        "warum": (f"Steht im Katalog vor dem installierten {kand[bester]}" if bester is not None else "Für diese Aufgabe ist noch kein Modell installiert")
                                 + f". {r.get('gb') or '?'} GB, {passt}. Danach im Team der Rolle zuweisen.",
                        "aktion": {"art": "modell", "name": k, "text": "Laden"}})
            break
    # 3. neue Generation
    for k in AUSSCHAU:
        r = erg.get(k) or {}
        if r.get("da") and k not in inst:
            aus.append({"stufe": "einspielen", "titel": f"Neue Modellgeneration: {k}",
                        "warum": f"Erstmals bei Ollama verfügbar ({r.get('gb') or '?'} GB, {_passt(r.get('gb'), vram_gesamt)}). "
                                 "Noch nicht auf dieser Maschine gemessen -- vor dem Einsatz testen.",
                        "aktion": {"art": "modell", "name": k, "text": "Laden"}})
    return aus


async def _laden(name: str) -> None:
    j = LADEN[name]
    schichten: dict[str, list[int]] = {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10)) as cl:
            async with cl.stream("POST", f"{OLLAMA}/api/pull", json={"model": name, "stream": True}) as r:
                async for zeile in r.aiter_lines():
                    if not zeile.strip():
                        continue
                    try:
                        d = json.loads(zeile)
                    except ValueError:
                        continue
                    if d.get("error"):
                        j.update(stand="fehler", fehler=d["error"])
                        return
                    if d.get("digest") and d.get("total"):
                        schichten[d["digest"]] = [int(d.get("completed") or 0), int(d["total"])]
                        fertig, ges = sum(v[0] for v in schichten.values()), sum(v[1] for v in schichten.values())
                        j.update(prozent=round(fertig / ges * 100, 1), gb=round(ges / 1e9, 1))
                    j["schritt"] = d.get("status") or j.get("schritt")
        j.update(stand="fertig", prozent=100, ende=time.time())
        try:
            DATEI.unlink()   # naechste Pruefung frisch: das Geladene ist jetzt installiert
        except OSError:
            pass
    except httpx.HTTPError as e:
        j.update(stand="fehler", fehler=f"Ollama nicht erreichbar: {e.__class__.__name__}")


def laden_starten(name: str) -> dict[str, Any]:
    if name in LADEN and LADEN[name].get("stand") == "laeuft":
        return LADEN[name]
    LADEN[name] = {"name": name, "stand": "laeuft", "prozent": 0, "start": time.time(), "schritt": "beginne"}
    asyncio.create_task(_laden(name))
    return LADEN[name]
