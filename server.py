#!/usr/bin/env python3
"""Release 2 Iteration 2. Eigenes Backend, kein Layer. Neo arbeitet jetzt mit echten Werkzeugen
(auflisten, lesen, durchsuchen, Aenderung vorschlagen) statt eines einzelnen Textblocks --
dieselbe Arbeitsweise wie ein Werkzeug-Agent, nur serverseitig und an dieses Projekt gebunden."""
from __future__ import annotations
import hashlib, json, os, secrets, smtplib, time
from email.message import EmailMessage
from pathlib import Path
from typing import Any
import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

WURZEL = Path(__file__).resolve().parent
FRONTEND = WURZEL / "frontend"
DATEN = WURZEL / "daten"
EINSTELLUNG_DATEI = DATEN / "einstellungen.json"
JOURNAL_DATEI = DATEN / "journal.json"
BESUCH_DATEI = DATEN / "letzter-besuch.json"
BENUTZER_DATEI = DATEN / "benutzer.json"
OLLAMA = os.environ.get("VVEC_OLLAMA", "http://127.0.0.1:11434").rstrip("/")
NEO_MODELL = os.environ.get("VVEC_NEO_MODELL", "qwen3.6:27b")
STATUS_URL = os.environ.get("VVEC_STATUS_URL", "").rstrip("/")

# Neo kann wahlweise ueber den lokalen Ollama laufen (Vorgabe, digitale Souveraenitaet,
# kein Token-Preis) oder -- wenn Veiko das ausdruecklich will -- ueber die Anthropic-API,
# also ueber dasselbe Modell, das dieses Repo gebaut hat. Vorgabe bleibt lokal; Cloud ist
# nie ein stiller Rueckfall, sondern eine bewusste Einstellung per Umgebungsvariable.
NEO_ANBIETER = os.environ.get("VVEC_NEO_ANBIETER", "lokal").strip().lower()
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODELL = os.environ.get("VVEC_NEO_CLAUDE_MODELL", "").strip()
AKTIVES_MODELL_LABEL = f"claude:{CLAUDE_MODELL}" if NEO_ANBIETER == "claude" else NEO_MODELL
MAX_SCHRITTE = int(os.environ.get("VVEC_NEO_MAX_SCHRITTE", "8"))

# Anmeldung. Ein Konto (dieses Cockpit ist fuer einen Nutzer gebaut, siehe UEBERGABE.md
# von Release 1) -- Einrichten, Anmelden, Abmelden, Passwort aendern, Passwort per
# E-Mail zuruecksetzen. Sitzungen leben nur im Speicher: ein Neustart meldet ab, das ist
# fuer ein persoenliches Cockpit kein Problem und einfacher als ein Sitzungsspeicher.
SMTP_HOST = os.environ.get("VVEC_SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("VVEC_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("VVEC_SMTP_USER", "").strip()
SMTP_PASSWORT = os.environ.get("VVEC_SMTP_PASSWORT", "")
SMTP_ABSENDER = os.environ.get("VVEC_SMTP_ABSENDER", "").strip() or SMTP_USER
OEFFENTLICHE_URL = os.environ.get("VVEC_OEFFENTLICHE_URL", "").rstrip("/")
COOKIE_SICHER = os.environ.get("VVEC_COOKIE_SICHER", "false").strip().lower() == "true"
SITZUNG_COOKIE = "vvec_sitzung"
SITZUNG_DAUER_SEK = 14 * 24 * 3600
RESET_DAUER_SEK = 3600
SITZUNGEN: dict[str, dict[str, Any]] = {}

ERLAUBTE_ENDUNGEN = {".py", ".js", ".css", ".html", ".md", ".json", ".txt"}
VERBOTENE_TEILE = {".venv", "__pycache__", ".git", "node_modules"}
# Wohin Neo tatsaechlich schreiben darf -- dieselbe Liste wie in anforderungen/AUFTRAG-NEO.md
# Abschnitt 6.2. daten/ traegt Laufzeitbestand (Einstellungen, Journal) und ist bewusst nicht
# dabei: wer dort schreibt, ueberschreibt Zustand statt Code.
SCHREIB_ERLAUBT = ("server.py", "frontend/", "anforderungen/", "doku/", "tests/", "werkzeug/",
                    "systemd/", "rollen.json", "requirements.txt", "README.md", "STATUS.md",
                    ".gitignore")

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

def schreiben_erlaubt(rel: str) -> bool:
    rel = rel.replace("\\", "/").lstrip("/")
    if rel.startswith("daten/"):
        return False
    for eintrag in SCHREIB_ERLAUBT:
        if eintrag.endswith("/"):
            if rel.startswith(eintrag):
                return True
        elif rel == eintrag:
            return True
    return False

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

# ---------------------------------------------------------------------------
# Benutzerverwaltung
# ---------------------------------------------------------------------------

def _passwort_hash(passwort: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), salt, 200_000).hex()

def passwort_setzen(passwort: str) -> dict[str, str]:
    salt = secrets.token_bytes(16)
    return {"salt": salt.hex(), "hash": _passwort_hash(passwort, salt)}

def passwort_pruefen(passwort: str, salt_hex: str, hash_hex: str) -> bool:
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    return secrets.compare_digest(_passwort_hash(passwort, salt), hash_hex)

def benutzer_lesen() -> dict[str, Any] | None:
    stand = json_lesen(BENUTZER_DATEI, None)
    return stand if isinstance(stand, dict) and stand.get("benutzername") else None

def benutzer_schreiben(stand: dict[str, Any]) -> None:
    json_schreiben(BENUTZER_DATEI, stand)

def sitzung_anlegen(benutzername: str) -> str:
    token = secrets.token_urlsafe(32)
    SITZUNGEN[token] = {"benutzername": benutzername, "erstellt": time.time()}
    return token

def sitzung_pruefen(token: str | None) -> str | None:
    if not token:
        return None
    eintrag = SITZUNGEN.get(token)
    if not eintrag:
        return None
    if time.time() - eintrag["erstellt"] > SITZUNG_DAUER_SEK:
        SITZUNGEN.pop(token, None)
        return None
    return eintrag["benutzername"]

def email_senden(empfaenger: str, betreff: str, text: str) -> None:
    if not SMTP_HOST:
        raise HTTPException(503, "Kein SMTP eingerichtet (VVEC_SMTP_HOST fehlt serverseitig).")
    nachricht = EmailMessage()
    nachricht["Subject"] = betreff
    nachricht["From"] = SMTP_ABSENDER
    nachricht["To"] = empfaenger
    nachricht.set_content(text)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as verbindung:
            verbindung.starttls()
            if SMTP_USER:
                verbindung.login(SMTP_USER, SMTP_PASSWORT)
            verbindung.send_message(nachricht)
    except (smtplib.SMTPException, OSError) as fehler:
        raise HTTPException(503, f"E-Mail-Versand fehlgeschlagen: {fehler.__class__.__name__}") from fehler

OEFFENTLICHE_PFADE = {"/", "/status"}
OEFFENTLICHE_VORSAETZE = ("/static/", "/api/konto/")

@app.middleware("http")
async def anmeldung_pruefen(request: Request, call_next):
    pfad = request.url.path
    if pfad in OEFFENTLICHE_PFADE or any(pfad.startswith(p) for p in OEFFENTLICHE_VORSAETZE):
        return await call_next(request)
    benutzername = sitzung_pruefen(request.cookies.get(SITZUNG_COOKIE))
    if not benutzername:
        return JSONResponse({"detail": "Nicht angemeldet"}, status_code=401)
    request.state.benutzername = benutzername
    return await call_next(request)

# ---------------------------------------------------------------------------
# Neos Werkzeuge -- eine Wahrheit fuer beide Motoren (Claude-Format als
# Innensprache, wie im Release-1-Backend: ein neuer Anbieter wird adaptiert,
# statt an vielen Stellen etwas zu aendern).
# ---------------------------------------------------------------------------

WERKZEUGE: list[dict[str, Any]] = [
    {
        "name": "dateien_auflisten",
        "description": "Listet Dateien im Projekt vve-cp-r2. Optional nach Pfad-Anfang gefiltert, z. B. 'frontend/'.",
        "input_schema": {"type": "object", "properties": {"anfang": {"type": "string"}}},
    },
    {
        "name": "datei_lesen",
        "description": "Liest den vollstaendigen Inhalt einer Datei aus dem Projekt.",
        "input_schema": {"type": "object", "properties": {"pfad": {"type": "string"}}, "required": ["pfad"]},
    },
    {
        "name": "suche",
        "description": "Durchsucht alle lesbaren Dateien im Projekt nach einer Zeichenkette (Gross-Klein wird ignoriert).",
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    },
    {
        "name": "datei_schreiben",
        "description": (
            "Schlaegt die vollstaendige neue Fassung einer Datei vor. Schreibt NICHT sofort -- "
            "Veiko sieht den Vorschlag im Cockpit und entscheidet mit dem Knopf 'Einspielen'. "
            "'inhalt' muss die komplette Zieldatei sein, kein Ausschnitt und kein '...'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pfad": {"type": "string"},
                "inhalt": {"type": "string"},
                "begruendung": {"type": "string"},
            },
            "required": ["pfad", "inhalt"],
        },
    },
]

def _ollama_werkzeuge() -> list[dict[str, Any]]:
    return [{"type": "function",
             "function": {"name": w["name"], "description": w["description"], "parameters": w["input_schema"]}}
            for w in WERKZEUGE]

def _kurzfassung(eingabe: dict[str, Any]) -> str:
    teile = []
    for schluessel, wert in eingabe.items():
        text = str(wert)
        if len(text) > 60:
            text = text[:60] + "…"
        teile.append(f"{schluessel}={text}")
    return ", ".join(teile)

def werkzeug_ausfuehren(name: str, eingabe: dict[str, Any], vorschlaege: list[dict[str, Any]]) -> str:
    if name == "dateien_auflisten":
        anfang = str(eingabe.get("anfang") or "").replace("\\", "/").lstrip("/")
        treffer = [p for p in dateibaum() if p.startswith(anfang)] if anfang else dateibaum()
        return "\n".join(treffer) if treffer else "Keine Dateien gefunden."
    if name == "datei_lesen":
        pfad = str(eingabe.get("pfad") or "")
        try:
            ziel = pfad_pruefen(pfad)
        except HTTPException as fehler:
            return f"Fehler: {fehler.detail}"
        if not ziel.exists() or not ziel.is_file():
            return f"Datei '{pfad}' existiert nicht."
        text = ziel.read_text(encoding="utf-8", errors="replace")
        if len(text) > 8000:
            text = text[:8000] + "\n... [gekuerzt, Datei ist laenger -- gezielt in Abschnitten lesen]"
        return text
    if name == "suche":
        begriff = str(eingabe.get("text") or "").strip().lower()
        if not begriff:
            return "Fehler: 'text' fehlt."
        treffer: list[str] = []
        for pfad in dateibaum():
            try:
                zeilen = (WURZEL / pfad).read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for nr, zeile in enumerate(zeilen, 1):
                if begriff in zeile.lower():
                    kurz = zeile.strip()
                    if len(kurz) > 160:
                        kurz = kurz[:160] + "…"
                    treffer.append(f"{pfad}:{nr}: {kurz}")
                    if len(treffer) >= 50:
                        break
            if len(treffer) >= 50:
                break
        return "\n".join(treffer) if treffer else "Keine Treffer."
    if name == "datei_schreiben":
        pfad = str(eingabe.get("pfad") or "").replace("\\", "/").lstrip("/")
        inhalt = eingabe.get("inhalt")
        begruendung = str(eingabe.get("begruendung") or "")
        if not pfad:
            return "Fehler: 'pfad' fehlt."
        if inhalt is None:
            return "Fehler: 'inhalt' fehlt. Schick die vollstaendige Zieldatei."
        if not schreiben_erlaubt(pfad):
            return f"Fehler: '{pfad}' liegt ausserhalb der erlaubten Pfade. Erlaubt: " + ", ".join(SCHREIB_ERLAUBT)
        vorhanden = next((v for v in vorschlaege if v["pfad"] == pfad), None)
        if vorhanden:
            vorhanden["inhalt"] = str(inhalt)
            vorhanden["begruendung"] = begruendung
        else:
            if len(vorschlaege) >= 20:
                return "Fehler: Limit von 20 vorgeschlagenen Dateien je Lauf erreicht."
            vorschlaege.append({"pfad": pfad, "inhalt": str(inhalt), "begruendung": begruendung})
        return f"Vorschlag fuer '{pfad}' gemerkt ({len(str(inhalt))} Zeichen). Wird erst nach Klick auf 'Einspielen' geschrieben."
    return f"Fehler: unbekanntes Werkzeug '{name}'."

def neo_system() -> str:
    kontext = (WURZEL / "anforderungen" / "NEO-KONTEXT.md").read_text(encoding="utf-8")
    baum = "\n".join(dateibaum())
    return (
        kontext
        + "\n\n## Dateibaum jetzt\n" + baum
        + "\n\n## Wie du arbeitest\n"
        "Du hast Werkzeuge: dateien_auflisten, datei_lesen, suche, datei_schreiben. Sieh nach, "
        "was du brauchst, bevor du etwas ueber eine Datei behauptest oder aenderst -- nicht raten. "
        "datei_schreiben legt nur einen Vorschlag an; geschrieben wird erst, wenn Veiko im Cockpit "
        "auf 'Einspielen' klickt. Ruf datei_schreiben erst auf, nachdem du die Datei (falls vorhanden) "
        "wirklich gelesen hast -- sonst ersetzt du unbekannten Bestand durch ein Geruest. Wenn du "
        "fertig bist, schreib eine klare Antwort an Veiko in normalem Text, keine Code-Bloecke fuer "
        "Dateien mehr -- dafuer gibt es jetzt das Werkzeug."
    )

# ---------------------------------------------------------------------------
# Die beiden Motoren. Intern wird immer im Claude-Format gedacht (Liste aus
# {role, content:[Bloecke]}); jeder Motor uebersetzt nur beim Senden/Empfangen.
# ---------------------------------------------------------------------------

def _verlauf_zu_ollama(verlauf: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ausgabe: list[dict[str, Any]] = []
    for eintrag in verlauf:
        rolle = eintrag.get("role")
        bloecke = eintrag.get("content") or []
        if rolle == "assistant":
            text_teile = [b.get("text", "") for b in bloecke if b.get("type") == "text"]
            aufrufe = [{"function": {"name": b.get("name"), "arguments": b.get("input") or {}}}
                       for b in bloecke if b.get("type") == "tool_use"]
            eintrag_ol: dict[str, Any] = {"role": "assistant", "content": "\n".join(t for t in text_teile if t)}
            if aufrufe:
                eintrag_ol["tool_calls"] = aufrufe
            ausgabe.append(eintrag_ol)
        else:
            for block in bloecke:
                if block.get("type") == "tool_result":
                    ausgabe.append({"role": "tool", "content": str(block.get("content", ""))})
                elif block.get("type") == "text":
                    ausgabe.append({"role": "user", "content": block.get("text", "")})
    return ausgabe

async def _ollama_schritt(system: str, verlauf: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nachrichten = [{"role": "system", "content": system}] + _verlauf_zu_ollama(verlauf)
    body = {"model": NEO_MODELL, "stream": False, "options": {"num_ctx": 16384},
            "tools": _ollama_werkzeuge(), "messages": nachrichten}
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            antwort = await client.post(f"{OLLAMA}/api/chat", json=body)
    except httpx.HTTPError as fehler:
        raise HTTPException(503, f"Ollama nicht erreichbar unter {OLLAMA}: {fehler.__class__.__name__}") from fehler
    if antwort.status_code >= 400:
        raise HTTPException(503, f"Ollama antwortet {antwort.status_code}. Kann {NEO_MODELL} Werkzeuge?")
    nachricht = antwort.json().get("message") or {}
    bloecke: list[dict[str, Any]] = []
    text = (nachricht.get("content") or "").strip()
    if text:
        bloecke.append({"type": "text", "text": text})
    for i, aufruf in enumerate(nachricht.get("tool_calls") or []):
        fn = aufruf.get("function") or {}
        eingabe = fn.get("arguments")
        if isinstance(eingabe, str):
            try:
                eingabe = json.loads(eingabe)
            except json.JSONDecodeError:
                eingabe = {}
        if not isinstance(eingabe, dict):
            eingabe = {}
        bloecke.append({"type": "tool_use", "id": f"lok_{i}", "name": fn.get("name", ""), "input": eingabe})
    if not bloecke:
        raise HTTPException(503, "Ollama lieferte weder Text noch Werkzeugaufruf")
    return bloecke

async def _claude_schritt(system: str, verlauf: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not ANTHROPIC_API_KEY:
        raise HTTPException(503, "ANTHROPIC_API_KEY fehlt serverseitig -- ohne Schluessel kann Neo nicht als Claude laufen.")
    if not CLAUDE_MODELL:
        raise HTTPException(503, "VVEC_NEO_CLAUDE_MODELL ist nicht gesetzt. Trag die genaue Modell-ID ein.")
    body = {"model": CLAUDE_MODELL, "max_tokens": 4096, "system": system, "tools": WERKZEUGE, "messages": verlauf}
    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            antwort = await client.post("https://api.anthropic.com/v1/messages", json=body, headers=headers)
    except httpx.HTTPError as fehler:
        raise HTTPException(503, f"Claude nicht erreichbar: {fehler.__class__.__name__}") from fehler
    if antwort.status_code >= 400:
        raise HTTPException(503, f"Claude antwortet {antwort.status_code}: {antwort.text[:300]}")
    inhalt = antwort.json().get("content") or []
    if not inhalt:
        raise HTTPException(503, "Claude lieferte leeren Inhalt")
    return inhalt

async def neo_motor_schritt(system: str, verlauf: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if NEO_ANBIETER == "claude":
        return await _claude_schritt(system, verlauf)
    return await _ollama_schritt(system, verlauf)

async def neo_agentenlauf(system: str, erste_anfrage: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    verlauf: list[dict[str, Any]] = [{"role": "user", "content": [{"type": "text", "text": erste_anfrage}]}]
    vorschlaege: list[dict[str, Any]] = []
    schritte: list[str] = []
    letzter_text = ""
    for _ in range(MAX_SCHRITTE):
        bloecke = await neo_motor_schritt(system, verlauf)
        verlauf.append({"role": "assistant", "content": bloecke})
        werkzeug_aufrufe = [b for b in bloecke if b.get("type") == "tool_use"]
        text_teile = [b.get("text", "") for b in bloecke if b.get("type") == "text"]
        neuer_text = "\n".join(t for t in text_teile if t).strip()
        if neuer_text:
            letzter_text = neuer_text
        if not werkzeug_aufrufe:
            return letzter_text, vorschlaege, schritte
        ergebnisse: list[dict[str, Any]] = []
        for aufruf in werkzeug_aufrufe:
            name = aufruf.get("name") or ""
            eingabe = aufruf.get("input") or {}
            ergebnis = werkzeug_ausfuehren(name, eingabe, vorschlaege)
            schritte.append(f"{name}({_kurzfassung(eingabe)})")
            ergebnisse.append({"type": "tool_result", "tool_use_id": aufruf.get("id", ""), "content": ergebnis})
        verlauf.append({"role": "user", "content": ergebnisse})
    letzter_text = (letzter_text + "\n\n" if letzter_text else "") + (
        f"Neo hat das Limit von {MAX_SCHRITTE} Arbeitsschritten erreicht, ohne fertig zu werden. "
        "Frag genauer oder in kleineren Schritten."
    )
    return letzter_text, vorschlaege, schritte

class EinrichtenKoerper(BaseModel):
    benutzername: str = Field(min_length=2, max_length=60)
    email: str = Field(min_length=3, max_length=200)
    passwort: str = Field(min_length=8, max_length=200)

class AnmeldenKoerper(BaseModel):
    benutzername: str
    passwort: str

class PasswortAendernKoerper(BaseModel):
    aktuelles_passwort: str
    neues_passwort: str = Field(min_length=8, max_length=200)

class PasswortVergessenKoerper(BaseModel):
    email: str

class PasswortZuruecksetzenKoerper(BaseModel):
    token: str
    neues_passwort: str = Field(min_length=8, max_length=200)

class GespraechKoerper(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    an: str = "neo"
    datei: str | None = None

class EinspielKoerper(BaseModel):
    dateien: list[dict[str, Any]]

@app.get("/status")
async def status():
    return {"dienst": "vve-cp-r2", "ok": True, "seit_sekunden": int(time.time() - START),
            "ollama": OLLAMA, "neo_modell": NEO_MODELL,
            "neo_anbieter": NEO_ANBIETER, "neo_aktives_modell": AKTIVES_MODELL_LABEL}

@app.get("/api/konto/ich")
async def konto_ich(request: Request):
    benutzer = benutzer_lesen()
    benutzername = sitzung_pruefen(request.cookies.get(SITZUNG_COOKIE))
    return {"eingerichtet": benutzer is not None, "angemeldet": benutzername is not None,
            "benutzername": benutzername, "email": benutzer.get("email") if (benutzer and benutzername) else None}

@app.post("/api/konto/einrichten")
async def konto_einrichten(koerper: EinrichtenKoerper, response: Response):
    if benutzer_lesen() is not None:
        raise HTTPException(409, "Es gibt schon ein Konto. Einrichten geht nur einmal.")
    stand = {"benutzername": koerper.benutzername, "email": koerper.email,
              **passwort_setzen(koerper.passwort), "reset_hash": None, "reset_ablauf": None}
    benutzer_schreiben(stand)
    token = sitzung_anlegen(koerper.benutzername)
    response.set_cookie(SITZUNG_COOKIE, token, httponly=True, samesite="lax",
                         secure=COOKIE_SICHER, max_age=SITZUNG_DAUER_SEK)
    journal_anhaengen({"wer": "veiko", "was": "konto-eingerichtet"})
    return {"benutzername": koerper.benutzername}

@app.post("/api/konto/anmelden")
async def konto_anmelden(koerper: AnmeldenKoerper, response: Response):
    benutzer = benutzer_lesen()
    if not benutzer or not passwort_pruefen(koerper.passwort, benutzer["salt"], benutzer["hash"]) \
            or koerper.benutzername != benutzer["benutzername"]:
        raise HTTPException(401, "Benutzername oder Passwort falsch.")
    token = sitzung_anlegen(benutzer["benutzername"])
    response.set_cookie(SITZUNG_COOKIE, token, httponly=True, samesite="lax",
                         secure=COOKIE_SICHER, max_age=SITZUNG_DAUER_SEK)
    return {"benutzername": benutzer["benutzername"]}

@app.post("/api/konto/abmelden")
async def konto_abmelden(request: Request, response: Response):
    token = request.cookies.get(SITZUNG_COOKIE)
    if token:
        SITZUNGEN.pop(token, None)
    response.delete_cookie(SITZUNG_COOKIE)
    return {"ok": True}

@app.post("/api/konto/passwort-aendern")
async def konto_passwort_aendern(koerper: PasswortAendernKoerper, request: Request):
    benutzername = sitzung_pruefen(request.cookies.get(SITZUNG_COOKIE))
    if not benutzername:
        raise HTTPException(401, "Nicht angemeldet.")
    benutzer = benutzer_lesen()
    if not benutzer or not passwort_pruefen(koerper.aktuelles_passwort, benutzer["salt"], benutzer["hash"]):
        raise HTTPException(401, "Aktuelles Passwort falsch.")
    benutzer.update(passwort_setzen(koerper.neues_passwort))
    benutzer_schreiben(benutzer)
    journal_anhaengen({"wer": "veiko", "was": "passwort-geaendert"})
    return {"ok": True}

@app.post("/api/konto/passwort-vergessen")
async def konto_passwort_vergessen(koerper: PasswortVergessenKoerper):
    # Immer dieselbe Antwort, ob die E-Mail passt oder nicht -- sonst liesse sich
    # ausprobieren, welche Adresse das eine Konto hat.
    antwort = {"ok": True, "hinweis": "Wenn die Adresse zum Konto passt, ist eine E-Mail unterwegs."}
    benutzer = benutzer_lesen()
    if not benutzer or benutzer.get("email", "").strip().lower() != koerper.email.strip().lower():
        return antwort
    if not OEFFENTLICHE_URL:
        raise HTTPException(503, "VVEC_OEFFENTLICHE_URL ist nicht gesetzt -- der Reset-Link im Cockpit "
                                   "haette kein Ziel. Trag die Adresse ein, unter der das Cockpit von "
                                   "aussen erreichbar ist.")
    roh_token = secrets.token_urlsafe(32)
    benutzer["reset_hash"] = hashlib.sha256(roh_token.encode("utf-8")).hexdigest()
    benutzer["reset_ablauf"] = time.time() + RESET_DAUER_SEK
    benutzer_schreiben(benutzer)
    link = f"{OEFFENTLICHE_URL}/?reset={roh_token}"
    email_senden(benutzer["email"],
                 "VVE Cockpit -- Passwort zuruecksetzen",
                 f"Neues Passwort setzen (eine Stunde gueltig): {link}\n\n"
                 "Wenn das nicht du warst: nichts tun, der Link verfaellt von selbst.")
    journal_anhaengen({"wer": "cockpit", "was": "reset-mail-verschickt"})
    return antwort

@app.post("/api/konto/passwort-zuruecksetzen")
async def konto_passwort_zuruecksetzen(koerper: PasswortZuruecksetzenKoerper):
    benutzer = benutzer_lesen()
    if not benutzer or not benutzer.get("reset_hash"):
        raise HTTPException(400, "Kein Reset angefordert oder Konto fehlt.")
    if time.time() > float(benutzer.get("reset_ablauf") or 0):
        raise HTTPException(400, "Der Link ist abgelaufen. Neu anfordern.")
    pruef_hash = hashlib.sha256(koerper.token.encode("utf-8")).hexdigest()
    if not secrets.compare_digest(pruef_hash, benutzer["reset_hash"]):
        raise HTTPException(400, "Der Link ist ungueltig.")
    benutzer.update(passwort_setzen(koerper.neues_passwort))
    benutzer["reset_hash"] = None
    benutzer["reset_ablauf"] = None
    benutzer_schreiben(benutzer)
    journal_anhaengen({"wer": "veiko", "was": "passwort-zurueckgesetzt"})
    return {"ok": True}

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
                "dateien": [], "schritte": []}
    anfrage = koerper.text
    if koerper.datei:
        ziel = pfad_pruefen(koerper.datei)
        if ziel.exists():
            anfrage += f"\n\n## Angehaengte Datei {koerper.datei}\n" + ziel.read_text(encoding="utf-8")[:8000]
    journal_anhaengen({"wer": "veiko", "was": "auftrag", "text": koerper.text[:500]})
    text, dateien_vorschlag, schritte = await neo_agentenlauf(neo_system(), anfrage)
    journal_anhaengen({"wer": "neo", "was": "antwort",
                        "dateien": [d["pfad"] for d in dateien_vorschlag], "schritte": schritte})
    if schritte:
        lauf = f"Neo hat {len(schritte)} Arbeitsschritt(e) gemacht"
        lauf += f" und schlaegt {len(dateien_vorschlag)} Datei(en) vor." if dateien_vorschlag else "."
    else:
        lauf = f"Neo hat mit {AKTIVES_MODELL_LABEL} geantwortet, ohne nachzusehen."
    return {"wer": "neo", "lauf": lauf, "text": text or "Neo hat nichts geantwortet.",
            "dateien": dateien_vorschlag, "schritte": schritte, "modell": AKTIVES_MODELL_LABEL}

@app.post("/api/neo/einspielen")
async def neo_einspielen(koerper: EinspielKoerper):
    geschrieben = []
    abgelehnt = []
    for eintrag in koerper.dateien:
        pfad = str(eintrag.get("pfad") or "").replace("\\", "/").lstrip("/")
        inhalt = eintrag.get("inhalt")
        if inhalt is None:
            abgelehnt.append({"pfad": pfad, "grund": "kein Inhalt"})
            continue
        if not schreiben_erlaubt(pfad):
            abgelehnt.append({"pfad": pfad, "grund": "Pfad nicht in der erlaubten Liste"})
            continue
        try:
            ziel = pfad_pruefen(pfad)
        except HTTPException as fehler:
            abgelehnt.append({"pfad": pfad, "grund": str(fehler.detail)})
            continue
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(str(inhalt), encoding="utf-8")
        geschrieben.append(pfad)
    journal_anhaengen({"wer": "veiko", "was": "eingespielt", "dateien": geschrieben, "abgelehnt": abgelehnt})
    return {"geschrieben": geschrieben, "abgelehnt": abgelehnt}

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
    # Vorgabe bleibt localhost. Auf dem Server ueber VVEC_HOST auf die Tailscale-Adresse
    # gebunden -- nicht 0.0.0.0, damit nichts ausserhalb des Tailnets erreichbar wird,
    # ohne dass dieses Repo die Caddy-Konfiguration anfassen muss.
    HOST = os.environ.get("VVEC_HOST", "127.0.0.1")
    uvicorn.run("server:app", host=HOST, port=8780, reload=False)
