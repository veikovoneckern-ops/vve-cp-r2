"""
VvE Cockpit -- neue Fassung (Release 2).

Laeuft PARALLEL zum alten Cockpit und fasst es nicht an: eigener Dienst,
eigener Port, eigene Datenbank. Den alten Bestand liest es nur (siehe
cockpit/importer.py). Warum es diese Fassung gibt und wie sie gedacht ist,
steht in KONZEPT.md.

Start:  .venv/bin/python server.py      (Vorgabe 127.0.0.1:8790)
"""
from __future__ import annotations

import asyncio
import contextlib

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cockpit import anmeldung, importer, stab
from cockpit.api import router
from cockpit.konfig import FRONTEND, HOST, PORT

OFFEN = ("/api/konto/", "/static/", "/favicon")


@contextlib.asynccontextmanager
async def lebenszeit(app: FastAPI):
    try:
        importer.abgleichen()
    except Exception as e:  # noqa: BLE001 -- ohne alten Bestand soll es trotzdem starten
        print(f"Abgleich mit dem alten Cockpit gescheitert: {e}", flush=True)
    aufgabe = asyncio.create_task(stab.schleife())
    yield
    aufgabe.cancel()


app = FastAPI(title="VvE Cockpit", lifespan=lebenszeit, docs_url=None, redoc_url=None)


@app.middleware("http")
async def anmeldung_pruefen(request: Request, call_next):
    pfad = request.url.path
    if pfad.startswith("/api/") and not pfad.startswith(OFFEN):
        if not anmeldung.sitzung(request.cookies.get(anmeldung.COOKIE)):
            return JSONResponse({"detail": "Nicht angemeldet"}, status_code=401)
    antwort = await call_next(request)
    if pfad == "/" or pfad.startswith("/static/"):
        # Kein Zwischenspeichern: sonst sieht man nach einem Update tagelang die alte Oberflaeche.
        antwort.headers["Cache-Control"] = "no-store"
    return antwort


app.include_router(router)
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
async def start():
    return FileResponse(FRONTEND / "index.html")


@app.get("/status")
async def status():
    return {"dienst": "vve-cockpit-neu", "ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, proxy_headers=True, forwarded_allow_ips="*")
