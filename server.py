#!/usr/bin/env python3
"""Release 2 Iteration 1. Eigenes Backend, kein Layer."""
from __future__ import annotations
import json, os, re, time
from pathlib import Path
from typing import Any
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

WURZEL = Path(__file__).resolve().parent
FRONTEND = WURZEL / "frontend"
DATEN = WURZEL / "daten"
EINSTELLUNG_DATEI = DATEN / "einstellungen.json"
JOURNAL_DATEI = DATEN / "journal.json"
BESUCH_DATEI = DATEN / "letzter-besuch.json"
OLLAMA = os.environ.get("VVEC_OLLAMA", "http://127.0.0.1:11434").rstrip("/")
NEO_MODELL = os.environ.get("VVEC_NEO_MODELL", "qwen3.6:27b")
STATUS_URL = os.environ.get("VVEC_STATUS_URL", "").rstrip("/")
ERLAUBTE_ENDUNGEN = {".py", ".js", ".css", ".html", ".md", ".json", ".txt"}
VERBOTENE_TEILE = {".venv", "__pycache__", ".git", "node_modules"}
app = FastAPI(title="vve-cp-r2")
START = time.time()

def json_lesen(pfad: Path, fallback: Any) -> Any:
    if not pfad.exists():
        return fallback
    try:
        return json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback

def json_schreiben(pfad: Path, wert: Any) -> None:
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps(wert, ensure_ascii=False, indent=2), encoding="utf-8")

def journal_anhaengen(zeile: dict[str, Any]) -> None:
    stand = json_lesen(JOURNAL_DATEI, [])
    if not isinstance(stand, list):
        stand = []
    zeile["wann"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    stand.append(zeile)
    json_schreiben(JOURNAL_DATEI, stand[-200:])

def pfad_pruefen(rel: str) -> Path:
    rel = rel.replace("\\", "/").lstrip("/")
    if ".." in Path(rel).parts:
        raise HTTPException(400, "Pfad nicht erlaubt")
    ziel = (WURZEL / rel).resolve()
    if not str(ziel).startswith(str(WURZEL)):
        raise HTTPException(400, "Pfad ausserhalb des Projekts")
    if any(teil in VERBOTENE_TEILE for teil in ziel.parts):
        raise HTTPException(400, "Pfad nicht erlaubt")
    if ziel.suffix.lower() not in ERLAUBTE_ENDUNGEN:
        raise HTTPException(400, "Dateityp nicht erlaubt")
    return ziel

def dateibaum() -> list[str]:
    liste: list[str] = []
    for p in WURZEL.rglob("*"):
        if not p.is_file():
            continue
        if any(teil in VERBOTENE_TEILE for teil in p.parts):
            continue
        if p.suffix.lower() not in ERLAUBTE_ENDUNGEN:
            continue
        liste.append(str(p.relative_to(WURZEL)).replace("\\", "/"))
    return sorted(liste)

def neo_system() -> str:
    kontext = (WURZEL / "anforderungen" / "NEO-KONTEXT.md").read_text(encoding="utf-8")
    return kontext + "\n\n## Dateibaum jetzt\n" + "\n".join(dateibaum()) + (
        "\n\nAntwortformat:\n1. Zuerst klarer Text an Veiko.\n"
        "2. Wenn Dateien geaendert werden sollen, danach genau ein JSON-Block:\n"
        "```json\n{\"dateien\":[{\"pfad\":\"frontend/stil.css\",\"inhalt\":\"...\",\"begruendung\":\"...\"}]}\n```\n"
        "Nur Pfade aus dem Dateibaum oder neue Dateien unter frontend/, daten/, anforderungen/.\n"
        "Inhalt muss die komplette Zieldatei sein.\n"
    )

def json_block_ziehen(text: str):
    dateien = []
    gesagt = text.strip()
    treffer = re.search(r"```json\\s*(\\{.*?\\})\\s*```", text, re.S)
    if treffer:
        gesagt = (text[:treffer.start()] + text[treffer.end():]).strip()
        try:
            paket = json.loads(treffer.group(1))
            roh = paket.get("dateien") or []
            if isinstance(roh, list):
                dateien = [d for d in roh if isinstance(d, dict) and "pfad" in d]
        except json.JSONDecodeError:
            dateien = []
    return gesagt, dateien

async def ollama_chat(system: str, user: str) -> str:
    url = f"{OLLAMA}/api/chat"
    body = {"model": NEO_MODELL, "stream": False, "options": {"num_ctx": 16384},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            antwort = await client.post(url, json=body)
    except httpx.HTTPError as fehler:
        raise HTTPException(503, f"Ollama nicht erreichbar unter {OLLAMA}: {fehler.__class__.__name__}") from fehler
    if antwort.status_code >= 400:
        raise HTTPException(503, f"Ollama antwortet {antwort.status_code}. Modell {NEO_MODELL}?")
    inhalt = ((antwort.json().get("message") or {}).get("content") or "")
    if not inhalt.strip():
        raise HTTPException(503, "Ollama lieferte leeren Text")
    return inhalt

async def status_lesen() -> dict[str, Any]:
    lage = {"quelle": None, "dienste": "nicht verfuegbar", "strom_server": "nicht verfuegbar",
            "strom_dock": "nicht verfuegbar", "temperatur": "nicht verfuegbar",
            "modell": "nicht verfuegbar", "jobs": "nicht verfuegbar"}
    if not STATUS_URL:
        return lage
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            antwort = await client.get(f"{STATUS_URL}/status")
        if antwort.status_code >= 400:
            return lage
        lage["quelle"] = STATUS_URL
        roh = antwort.json()
        if isinstance(roh, dict):
            for schluessel in ("dienste", "strom_server", "strom_dock", "temperatur", "modell", "jobs"):
                if schluessel in roh and roh[schluessel] not in (None, ""):
                    lage[schluessel] = roh[schluessel]
    except httpx.HTTPError:
        return lage
    return lage

class GespraechKoerper(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    an: str = "neo"
    datei: str | None = None

class EinspielKoerper(BaseModel):
    dateien: list[dict[str, Any]]

@app.get("/status")
async def status():
    return {"dienst": "vve-cp-r2", "ok": True, "seit_sekunden": int(time.time() - START),
            "ollama": OLLAMA, "neo_modell": NEO_MODELL}

@app.get("/api/einstellungen")
async def einstellungen_lesen():
    vorgabe = {"thema": "dunkel", "schrift_fluss": 18, "schrift_neben": 16, "schrift_nav": 15, "schrift_eingabe": 18}
    stand = json_lesen(EINSTELLUNG_DATEI, {})
    if not isinstance(stand, dict):
        stand = {}
    vorgabe.update({k: stand[k] for k in vorgabe if k in stand})
    return vorgabe

@app.post("/api/einstellungen")
async def einstellungen_schreiben(koerper: dict[str, Any]):
    stand = await einstellungen_lesen()
    for schluessel in ("thema", "schrift_fluss", "schrift_neben", "schrift_nav", "schrift_eingabe"):
        if schluessel in koerper:
            stand[schluessel] = koerper[schluessel]
    json_schreiben(EINSTELLUNG_DATEI, stand)
    return stand

@app.get("/api/lage")
async def lage():
    besuch = json_lesen(BESUCH_DATEI, {})
    letzter = besuch.get("wann") if isinstance(besuch, dict) else None
    json_schreiben(BESUCH_DATEI, {"wann": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return {"letzter_besuch": letzter,
            "seit_weg": "Noch keine Bewegung in diesem Release. Der neue Stab hat die vorliegenden Notizen noch nicht gesichtet.",
            "projekte": [], "in_arbeit": [], "unsicher": []}

@app.get("/api/rollen")
async def rollen():
    return json_lesen(WURZEL / "rollen.json", {})

@app.get("/api/server")
async def server_lage():
    return await status_lesen()

@app.get("/api/dateien")
async def dateien():
    return {"dateien": dateibaum()}

@app.get("/api/datei")
async def datei_lesen(pfad: str):
    ziel = pfad_pruefen(pfad)
    if not ziel.exists() or not ziel.is_file():
        raise HTTPException(404, "Datei fehlt")
    text = ziel.read_text(encoding="utf-8")
    if len(text) > 120000:
        text = text[:120000] + "\n... [gekuerzt]"
    return {"pfad": pfad, "inhalt": text}

@app.post("/api/gespraech")
async def gespraech(koerper: GespraechKoerper):
    an = koerper.an.strip().lower() or "neo"
    if an != "neo":
        journal_anhaengen({"wer": "cockpit", "was": "abgewiesen", "an": an})
        return {"wer": "cockpit", "lauf": "Cockpit nimmt keine Fachrolle ausser Neo in Iteration 1.",
                "text": f"{an.capitalize()} arbeitet in dieser Iteration noch nicht. Schreib an Neo, wenn die Loesung selbst geaendert werden soll.",
                "dateien": []}
    zusatz = ""
    if koerper.datei:
        ziel = pfad_pruefen(koerper.datei)
        if ziel.exists():
            zusatz = f"\n\n## Datei {koerper.datei}\n" + ziel.read_text(encoding="utf-8")[:80000]
    journal_anhaengen({"wer": "veiko", "was": "auftrag", "text": koerper.text[:500]})
    roh = await ollama_chat(neo_system(), koerper.text + zusatz)
    gesagt, dateien = json_block_ziehen(roh)
    journal_anhaengen({"wer": "neo", "was": "antwort", "dateien": [d.get("pfad") for d in dateien]})
    return {"wer": "neo", "lauf": f"Neo hat mit {NEO_MODELL} geantwortet.",
            "text": gesagt or roh, "dateien": dateien, "modell": NEO_MODELL}

@app.post("/api/neo/einspielen")
async def neo_einspielen(koerper: EinspielKoerper):
    geschrieben = []
    for eintrag in koerper.dateien:
        pfad = str(eintrag.get("pfad") or "")
        inhalt = eintrag.get("inhalt")
        if inhalt is None:
            continue
        ziel = pfad_pruefen(pfad)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(str(inhalt), encoding="utf-8")
        geschrieben.append(pfad)
    journal_anhaengen({"wer": "veiko", "was": "eingespielt", "dateien": geschrieben})
    return {"geschrieben": geschrieben}

@app.post("/api/sicherung")
async def sicherung_skizze():
    return JSONResponse({"ok": False, "grund": "Graph-Token haengt am Server, nicht im Repo.",
                         "soll": "POST in Microsoft Graph /me/drive, Ordner VVE-Sicherung. Nie C:."}, status_code=501)

@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")

app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8780, reload=False)
