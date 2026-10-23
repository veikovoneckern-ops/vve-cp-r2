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
import gzip

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from cockpit import anmeldung, daily, dossier, folienbilder, importer, langlauf, medien, nachtladen, nachtplan, revision, rsi, stab, usage, webspace
from cockpit.api import router
from cockpit.konfig import FRONTEND, HOST, PORT

OFFEN = ("/api/konto/", "/static/", "/favicon")


@contextlib.asynccontextmanager
async def lebenszeit(app: FastAPI):
    try:
        importer.abgleichen()
    except Exception as e:  # noqa: BLE001 -- ohne alten Bestand soll es trotzdem starten
        print(f"Abgleich mit dem alten Cockpit gescheitert: {e}", flush=True)
    try:
        stab.zuordnung_nachziehen()
        # Urteile fertiger Langlaeufer nach der Regel vom 21.10.2026 (Externe haben das letzte Wort).
        langlauf.urteile_nachziehen()
        # Plaud-Titel statt Dateiname, und "noch nicht bearbeiten"-Notizen vormerken (21.10.2026).
        stab.plaud_titel_nachziehen()
        stab.vorgemerkt_nachziehen()
    except Exception as e:  # noqa: BLE001 -- eine Nachpflege darf den Start nie verhindern
        print(f"Zuordnung nachziehen gescheitert: {e}", flush=True)
    aufgabe = asyncio.create_task(stab.schleife())
    # Langlaeufer (17.10.2026): eigene Schleife, teilt sich die Sperre mit der Pipeline.
    lang = asyncio.create_task(langlauf.schleife())
    # Modell-Revision (17.10.2026): nachts einmal messen, ob es bessere Modelle gibt.
    rev = asyncio.create_task(revision.schleife())
    # Nachts neue Modelle laden, wenn Veiko es eingeschaltet hat (nachtladen.py, 21.10.2026).
    laden = asyncio.create_task(nachtladen.schleife())
    # Daily Tasks (22.10.2026): taegliche Auftraege zur geplanten Zeit an die Pipeline.
    taeglich = asyncio.create_task(daily.schleife())
    # ComfyUI gibt nach Leerlauf seinen Grafikspeicher frei (medien.py, 17.10.2026).
    frei = asyncio.create_task(medien.aufraeum_schleife())
    # Fehlende Bilder in Ergebnissen von selbst nachrechnen (folienbilder.py, 18.10.2026).
    bilder = asyncio.create_task(folienbilder.nachhol_schleife())
    # Strom beider Shelly-Dosen alle fuenf Minuten mitschreiben (Usage, 19.10.2026).
    strom = asyncio.create_task(usage.strom_schleife())
    # Recherche-Dossiers, die ein Neustart unterbrochen hat, fortsetzen (19.10.2026).
    weiter = asyncio.create_task(dossier.fortsetzen())
    # RSI (23.10.2026): nachts aus den Gespraechen Verbesserungen vorschlagen (Neo) und pruefen (Dario).
    besser = asyncio.create_task(rsi.schleife())
    # Morgens um 04:50 Talk-Modell und Spracherkennung laden (nachtplan.py, 23.10.2026).
    bereit = asyncio.create_task(nachtplan.schleife())
    yield
    bereit.cancel()
    besser.cancel()
    weiter.cancel()
    strom.cancel()
    bilder.cancel()
    frei.cancel()
    aufgabe.cancel()
    lang.cancel()
    rev.cancel()
    laden.cancel()
    taeglich.cancel()


app = FastAPI(title="VvE Cockpit", lifespan=lebenszeit, docs_url=None, redoc_url=None)


@app.middleware("http")
async def anmeldung_pruefen(request: Request, call_next):
    pfad = request.url.path
    if pfad.startswith("/api/") and not pfad.startswith(OFFEN):
        if not anmeldung.sitzung(request.cookies.get(anmeldung.COOKIE)):
            return JSONResponse({"detail": "Nicht angemeldet"}, status_code=401)
    antwort = await call_next(request)
    if pfad == "/" or pfad.startswith("/static/"):
        # "no-cache" statt "no-store" (19.10.2026, Veiko am Handy: "es dauert ewig"): der Browser
        # behaelt die Datei und fragt nur nach, ob sie sich geaendert hat (ETag -> 304, ein paar
        # Byte). Ein Update ist trotzdem beim naechsten Laden da -- mit "no-store" holte das
        # Handy bei JEDEM Laden alle 36 Programmdateien (940 KB) neu.
        antwort.headers["Cache-Control"] = "no-cache"
    return antwort


class Komprimieren:
    """gzip fuer Oberflaeche und Daten (19.10.2026). Entschieden wird am INHALTSTYP der
    Antwort, nicht am Pfad: die gestreamten Antworten (Talk, Team-Chat, application/x-ndjson)
    muessen Wort fuer Wort ankommen und bleiben ungepackt, ebenso Bilder, Videos, Dateien
    und Teilantworten (Range). Gepackte Antworten werden ganz gesammelt -- das sind JSON,
    HTML, CSS und JavaScript, also hoechstens wenige hundert KB."""
    TYPEN = ("application/json", "text/html", "text/css", "text/javascript", "application/javascript", "image/svg+xml", "text/plain")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or b"gzip" not in b",".join(v for k, v in scope["headers"] if k == b"accept-encoding"):
            return await self.app(scope, receive, send)
        start: dict = {}
        teile: list[bytes] = []
        packen = False

        async def senden(msg):
            nonlocal packen
            if msg["type"] == "http.response.start":
                h = {k.lower(): v for k, v in msg.get("headers", [])}
                typ = h.get(b"content-type", b"").decode("latin-1").split(";")[0].strip()
                packen = (msg["status"] == 200 and typ in self.TYPEN and b"content-encoding" not in h
                          and b"content-range" not in h and scope.get("method") != "HEAD")
                if packen:
                    start.update(msg)
                    return
                return await send(msg)
            if msg["type"] == "http.response.body" and packen:
                teile.append(msg.get("body", b""))
                if msg.get("more_body"):
                    return
                roh = b"".join(teile)
                koerper = gzip.compress(roh, 6) if len(roh) >= 1200 else roh
                kopf = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
                kopf.append((b"content-length", str(len(koerper)).encode()))
                if koerper is not roh:
                    kopf += [(b"content-encoding", b"gzip"), (b"vary", b"Accept-Encoding")]
                await send({**start, "headers": kopf})
                return await send({"type": "http.response.body", "body": koerper})
            return await send(msg)

        await self.app(scope, receive, senden)


app.include_router(router)
# WebSpace (18.10.2026): Editor fuer die Website veikovoneckern.org, eigenes Modul.
app.include_router(webspace.router)
app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
async def start():
    # Alle Programmteile vorab ankuendigen (modulepreload, 19.10.2026): ohne das holte der
    # Browser app.js, las dort die Importe, holte die naechsten, las deren Importe ... -- eine
    # Kette von Stufen, und jede kostet am Handy im WLAN gut 100 ms. So kommen sie parallel.
    seite = (FRONTEND / "index.html").read_text(encoding="utf-8")
    module = sorted(p.relative_to(FRONTEND).as_posix() for p in (FRONTEND / "js").glob("*.js"))
    module += sorted(p.relative_to(FRONTEND).as_posix() for p in (FRONTEND / "vendor").glob("*.js"))
    vorab = "".join(f'<link rel="modulepreload" href="/static/{m}">\n' for m in module)
    return HTMLResponse(seite.replace("</head>", vorab + "</head>", 1))


@app.get("/status")
async def status():
    return {"dienst": "vve-cockpit-neu", "ok": True}


fastapi_app = app
app = Komprimieren(fastapi_app)   # ganz aussen, nach allen Routen: auch Dateien aus /static werden gepackt


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, proxy_headers=True, forwarded_allow_ips="*")
