#!/usr/bin/env python3
"""Release 2 Iteration 2. Eigenes Backend, kein Layer. Neo arbeitet jetzt mit echten Werkzeugen
(auflisten, lesen, durchsuchen, Aenderung vorschlagen) statt eines einzelnen Textblocks --
dieselbe Arbeitsweise wie ein Werkzeug-Agent, nur serverseitig und an dieses Projekt gebunden."""
from __future__ import annotations
import asyncio, hashlib, json, os, re, secrets, smtplib, time
from email.message import EmailMessage
from pathlib import Path
from typing import Any
import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
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
MAX_SCHRITTE = int(os.environ.get("VVEC_NEO_MAX_SCHRITTE", "40"))
BEFEHL_TIMEOUT_SEK = int(os.environ.get("VVEC_NEO_BEFEHL_TIMEOUT", "120"))
# 16384 war zu knapp fuer einen Werkzeug-Kreislauf mit echten Dateiinhalten und bis zu 40
# Schritten -- der Verlauf waechst mit jedem Schritt und wird komplett neu mitgeschickt, war
# also schon nach 1-2 Dateien voll. Ollama kappt dann still von vorne, und ein denkendes Modell
# (qwen3.6 mit "thinking") kann dabei mitten im Denken abgeschnitten werden, bevor Text oder ein
# Werkzeugaufruf entsteht -- das war der 503 "Ollama lieferte weder Text noch Werkzeugaufruf".
# 65536 wurde auf dem Server geprueft (laedt auf den zwei 3090en, je ~12GB frei danach).
NEO_NUM_CTX = int(os.environ.get("VVEC_NEO_NUM_CTX", "65536"))
# 180s war zu knapp fuer einen weit fortgeschrittenen Lauf (grosser Kontext -> langsameres
# Prefill). Der Stream haelt die Verbindung selbst am Leben (siehe neo_agentenlauf), ein hohes
# Zeitlimit hier kostet also nichts mehr -- nur die tatsaechliche Antwortzeit von Ollama zaehlt.
OLLAMA_TIMEOUT_SEK = float(os.environ.get("VVEC_NEO_OLLAMA_TIMEOUT", "600"))

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

# Volle Serverreichweite (Veikos ausdruecklicher Wunsch, 9. September 2026): Neo arbeitet
# nicht mehr nur im eigenen Projektordner, sondern mit denselben Rechten wie der Nutzer
# vveadmin auf dem ganzen Server -- liest, schreibt und fuehrt Befehle sofort aus, ohne
# Rueckfrage. Eine kleine, harte Grenze bleibt trotzdem, dieselbe die auch fuer mich (Claude)
# gilt: keine Systemverzeichnisse, keine Zugangsdaten. Dazu, projektspezifisch: die
# AUSGELIEFERTEN Release-1-Dateien (/opt/vvec, /srv/www) sind vom Schreiben ausgenommen, weil
# Release 1 eine eigene geprüfte Auslieferung mit Pruefsummen und automatischem Zurueckrollen
# hat (vvec-update.sh) -- direktes Ueberschreiben ginge daran vorbei. Lesen bleibt ueberall
# erlaubt, auch dort.
GESPERRTE_SCHREIBPFADE = tuple(
    str(Path(p).expanduser()) for p in (
        "/etc", "/boot", "/sys", "/proc", "/root", "~/.ssh",
        "/etc/sudoers", "/etc/sudoers.d", "/opt/vvec", "/srv/www",
    )
)

def pfad_gesperrt(ziel: Path) -> bool:
    ziel_s = str(ziel)
    return any(ziel_s == g or ziel_s.startswith(g.rstrip("/") + "/") for g in GESPERRTE_SCHREIBPFADE)

def pfad_aufloesen(pfad: str) -> Path:
    p = Path(pfad.strip()).expanduser()
    if not p.is_absolute():
        p = WURZEL / p
    return p.resolve()

# Ein kleiner, harter Riegel gegen die wenigen Befehle, die den Server selbst lahmlegen oder
# Daten unwiederbringlich vernichten wuerden -- alles andere laeuft ungefragt, wie vereinbart.
BEFEHL_GESPERRT_MUSTER = [
    r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+/(\s|$)",   # rm -rf / (und Varianten der Flag-Reihenfolge)
    r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+/home\b",
    r"\bmkfs(\.\w+)?\b",
    r"\bdd\s+.*of=/dev/",
    r"\b(shutdown|poweroff|halt)\b",
    r"\breboot\b",
]
BEFEHL_GESPERRT_REGEX = re.compile("|".join(BEFEHL_GESPERRT_MUSTER), re.IGNORECASE)

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

def benutzer_liste() -> list[dict[str, Any]]:
    stand = json_lesen(BENUTZER_DATEI, {"benutzer": []})
    if isinstance(stand, dict) and stand.get("benutzername"):
        # Altes Format von vor der Mehrbenutzer-Unterstuetzung: ein einzelnes Konto
        # als Wurzel-Objekt statt einer Liste. Wird beim naechsten Schreiben ins neue
        # Format ueberfuehrt, der Bestand bleibt dabei unveraendert erhalten.
        return [stand]
    if not isinstance(stand, dict):
        return []
    liste = stand.get("benutzer")
    return liste if isinstance(liste, list) else []

def benutzer_liste_schreiben(liste: list[dict[str, Any]]) -> None:
    json_schreiben(BENUTZER_DATEI, {"benutzer": liste})

def benutzer_finden(benutzername: str) -> dict[str, Any] | None:
    for b in benutzer_liste():
        if b.get("benutzername") == benutzername:
            return b
    return None

def benutzer_email_finden(email: str) -> dict[str, Any] | None:
    email = email.strip().lower()
    for b in benutzer_liste():
        if str(b.get("email", "")).strip().lower() == email:
            return b
    return None

def benutzer_reset_finden(token_hash: str) -> dict[str, Any] | None:
    for b in benutzer_liste():
        if b.get("reset_hash") and secrets.compare_digest(str(b["reset_hash"]), token_hash):
            return b
    return None

def benutzer_aktualisieren(benutzername: str, aenderungen: dict[str, Any]) -> None:
    liste = benutzer_liste()
    for b in liste:
        if b.get("benutzername") == benutzername:
            b.update(aenderungen)
            break
    benutzer_liste_schreiben(liste)

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
        antwort = await call_next(request)
        # Kein Zwischenspeichern -- weder im Browser noch bei Cloudflare. Sonst bekommt
        # jemand nach einem Update noch tagelang die alte app.js/stil.css ausgeliefert,
        # ohne dass ein Fehler zu sehen waere -- genau das ist einmal passiert.
        antwort.headers["Cache-Control"] = "no-store"
        return antwort
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
            "Schreibt sofort die vollstaendige neue Fassung einer Datei -- irgendwo auf dem "
            "Server, nicht nur im r2-Projekt (absoluter Pfad, oder relativ zum r2-Ordner). "
            "Keine Rueckfrage, keine Bestaetigung. 'inhalt' muss die komplette Zieldatei sein, "
            "kein Ausschnitt und kein '...'. Eine kleine Sperrliste bleibt: Systemverzeichnisse "
            "und die ausgelieferten Release-1-Dateien unter /opt/vvec und /srv/www."
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
    {
        "name": "befehl_ausfuehren",
        "description": (
            "Fuehrt einen Shell-Befehl auf dem Server aus, mit denselben Rechten wie der Nutzer "
            "vveadmin (kein sudo-Passwort verfuegbar). Laeuft sofort, ohne Rueckfrage. "
            "Zeitlimit 120 Sekunden. Arbeitsverzeichnis per 'arbeitsverzeichnis' waehlbar, sonst "
            "der r2-Projektordner. Fuer git, Tests, Pakete, Dienste neu starten, Server-Erkundung."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "befehl": {"type": "string"},
                "arbeitsverzeichnis": {"type": "string"},
            },
            "required": ["befehl"],
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

async def werkzeug_ausfuehren(name: str, eingabe: dict[str, Any], geaendert: list[dict[str, Any]]) -> str:
    if name == "dateien_auflisten":
        anfang = str(eingabe.get("anfang") or "").replace("\\", "/").lstrip("/")
        treffer = [p for p in dateibaum() if p.startswith(anfang)] if anfang else dateibaum()
        return "\n".join(treffer) if treffer else "Keine Dateien gefunden."
    if name == "datei_lesen":
        pfad = str(eingabe.get("pfad") or "")
        if not pfad:
            return "Fehler: 'pfad' fehlt."
        try:
            ziel = pfad_aufloesen(pfad)
        except OSError as fehler:
            return f"Fehler: {fehler}"
        if not ziel.exists() or not ziel.is_file():
            return f"Datei '{ziel}' existiert nicht."
        try:
            text = ziel.read_text(encoding="utf-8", errors="replace")
        except OSError as fehler:
            return f"Fehler beim Lesen von '{ziel}': {fehler}"
        if len(text) > 12000:
            text = text[:12000] + "\n... [gekuerzt, Datei ist laenger -- gezielt in Abschnitten lesen]"
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
        return "\n".join(treffer) if treffer else "Keine Treffer. (Nur der r2-Projektordner -- fuer den Rest des Servers befehl_ausfuehren mit grep/find nutzen.)"
    if name == "datei_schreiben":
        pfad = str(eingabe.get("pfad") or "")
        inhalt = eingabe.get("inhalt")
        begruendung = str(eingabe.get("begruendung") or "")
        if not pfad:
            return "Fehler: 'pfad' fehlt."
        if inhalt is None:
            return "Fehler: 'inhalt' fehlt. Schick die vollstaendige Zieldatei."
        try:
            ziel = pfad_aufloesen(pfad)
        except OSError as fehler:
            return f"Fehler: {fehler}"
        if pfad_gesperrt(ziel):
            return (f"Fehler: '{ziel}' ist gesperrt (Systempfad oder ausgelieferte Release-1-Dateien -- "
                     "dort direkt zu schreiben wuerde an der geprueften Auslieferung vorbei gehen).")
        try:
            ziel.parent.mkdir(parents=True, exist_ok=True)
            ziel.write_text(str(inhalt), encoding="utf-8")
        except OSError as fehler:
            return f"Fehler beim Schreiben von '{ziel}': {fehler}"
        geaendert.append({"pfad": str(ziel), "begruendung": begruendung})
        return f"Geschrieben: '{ziel}' ({len(str(inhalt))} Zeichen)."
    if name == "befehl_ausfuehren":
        befehl = str(eingabe.get("befehl") or "").strip()
        if not befehl:
            return "Fehler: 'befehl' fehlt."
        if BEFEHL_GESPERRT_REGEX.search(befehl):
            return ("Fehler: dieser Befehl ist gesperrt (Server-Neustart/-Abschaltung, Formatieren, "
                     "rekursives Loeschen auf Systemebene).")
        arbeitsverzeichnis = str(eingabe.get("arbeitsverzeichnis") or "").strip()
        try:
            cwd = pfad_aufloesen(arbeitsverzeichnis) if arbeitsverzeichnis else WURZEL
        except OSError as fehler:
            return f"Fehler: {fehler}"
        if not cwd.exists() or not cwd.is_dir():
            return f"Fehler: Arbeitsverzeichnis '{cwd}' existiert nicht."
        try:
            prozess = await asyncio.create_subprocess_shell(
                befehl, cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as fehler:
            return f"Fehler beim Starten: {fehler}"
        try:
            ausgabe_bytes, _ = await asyncio.wait_for(prozess.communicate(), timeout=BEFEHL_TIMEOUT_SEK)
        except asyncio.TimeoutError:
            prozess.kill()
            return f"Fehler: Befehl lief laenger als {BEFEHL_TIMEOUT_SEK}s und wurde abgebrochen."
        ausgabe = ausgabe_bytes.decode("utf-8", errors="replace")
        if len(ausgabe) > 6000:
            ausgabe = ausgabe[:6000] + "\n... [gekuerzt]"
        return f"Exit-Code {prozess.returncode}\n{ausgabe}".strip()
    return f"Fehler: unbekanntes Werkzeug '{name}'."

def neo_system() -> str:
    kontext = (WURZEL / "anforderungen" / "NEO-KONTEXT.md").read_text(encoding="utf-8")
    baum = "\n".join(dateibaum())
    return (
        kontext
        + "\n\n## Dateibaum des r2-Projekts jetzt\n" + baum
        + "\n\n## Wie du arbeitest\n"
        "Du hast Werkzeuge: dateien_auflisten, datei_lesen, suche (alle drei fuer das r2-Projekt), "
        "datei_schreiben und befehl_ausfuehren (beide fuer den GANZEN Server, mit denselben Rechten "
        "wie der Nutzer vveadmin). Sieh nach, was du brauchst, bevor du etwas ueber eine Datei oder "
        "den Server behauptest -- nicht raten. datei_schreiben und befehl_ausfuehren wirken SOFORT, "
        "ohne Rueckfrage -- das ist Absicht, arbeite entsprechend sorgfaeltig: lies eine Datei, "
        "bevor du sie ersetzt, sonst wirfst du weg, was schon funktioniert. Eine kleine Sperrliste "
        "bleibt: Systemverzeichnisse, Zugangsdaten, und die AUSGELIEFERTEN Release-1-Dateien unter "
        "/opt/vvec und /srv/www (lesen ja, schreiben nein -- Release 1 hat eine eigene geprüfte "
        "Auslieferung mit Ruecksprung bei Fehlern; wer daran etwas aendern will, aendert die Quelle "
        "im Repo, nicht die laufende Auslieferung). Du hast kein sudo-Passwort. Bis zu " + str(MAX_SCHRITTE) +
        " Werkzeugaufrufe je Antwort. Wenn du fertig bist, schreib eine klare Antwort an Veiko in "
        "normalem Text, die sagt, was du tatsaechlich getan hast.\n\n"
        "## Effizient arbeiten\n"
        "Jeder Werkzeugaufruf verlaengert den Kontext, den du bei jedem weiteren Schritt komplett "
        "erneut liest -- viele kleine Schritte machen dich langsamer, nicht gruendlicher. "
        "befehl_ausfuehren fuehrt einen kompletten Shell-Befehl aus: verkette mit && oder | statt "
        "vieler einzelner Aufrufe (z. B. eine Kette aus mehreren grep/find/sed in einem Aufruf statt "
        "sechs einzelnen). Lies eine Datei einmal ganz (datei_lesen, notfalls mehrfach fuer sehr "
        "grosse Dateien) statt sie in vielen kleinen sed-Ausschnitten abzutasten. Merk dir, was du "
        "in diesem Lauf schon gesehen hast -- nicht zweimal dasselbe pruefen. Wenn eine Aenderung "
        "verlangt ist: nach dem noetigsten Verstehen zuegig zu datei_schreiben/befehl_ausfuehren "
        "uebergehen, nicht endlos weiter erkunden. Nur die letzten " + str(VOLLE_SCHRITTE) + " Werkzeug-"
        "ergebnisse bleiben dir in voller Laenge sichtbar, aeltere werden gekuerzt zusammengefasst."
    )

# ---------------------------------------------------------------------------
# Die beiden Motoren. Intern wird immer im Claude-Format gedacht (Liste aus
# {role, content:[Bloecke]}); jeder Motor uebersetzt nur beim Senden/Empfangen.
# ---------------------------------------------------------------------------

VOLLE_SCHRITTE = int(os.environ.get("VVEC_NEO_VOLLE_SCHRITTE", "10"))

def _verlauf_gekuerzt(verlauf: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Werkzeugergebnisse aus AELTEREN Schritten werden gekuerzt, nicht geloescht -- sonst wird
    der Kontext bei einem langen Auftrag (viele Schritte, grosse Shell-/Datei-Ausgaben) trotz
    NEO_NUM_CTX irgendwann wieder voll, UND jede Anfrage braucht laenger, weil das Prefill mit der
    Kontextgroesse waechst -- am Ende ein ReadTimeout, wie am 8. September nach 34 Schritten
    passiert. Die letzten VOLLE_SCHRITTE Werkzeugrunden bleiben unangetastet, alles Aeltere wird
    auf eine kurze Zusammenfassung eingedampft (bei Bedarf liest/durchsucht Neo einfach erneut)."""
    tool_runden = [i for i, e in enumerate(verlauf)
                   if e.get("role") == "user" and any(b.get("type") == "tool_result" for b in (e.get("content") or []))]
    alte_runden = set(tool_runden[:-VOLLE_SCHRITTE]) if len(tool_runden) > VOLLE_SCHRITTE else set()
    if not alte_runden:
        return verlauf
    ausgabe: list[dict[str, Any]] = []
    for i, eintrag in enumerate(verlauf):
        if i not in alte_runden:
            ausgabe.append(eintrag)
            continue
        neue_bloecke = []
        for block in eintrag.get("content") or []:
            if block.get("type") != "tool_result":
                neue_bloecke.append(block)
                continue
            inhalt = str(block.get("content", ""))
            if len(inhalt) > 500:
                inhalt = inhalt[:500] + f"\n... [gekuerzt, {len(inhalt) - 500} weitere Zeichen aus einem aelteren Schritt -- bei Bedarf erneut abrufen]"
            neue_bloecke.append({**block, "content": inhalt})
        ausgabe.append({**eintrag, "content": neue_bloecke})
    return ausgabe

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

class NeoSchrittLeer(Exception):
    """Ollama hat weder Text noch Werkzeugaufruf geliefert, auch nicht im zweiten Versuch."""

async def _ollama_anfrage(system: str, verlauf: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nachrichten = [{"role": "system", "content": system}] + _verlauf_zu_ollama(_verlauf_gekuerzt(verlauf))
    body = {"model": NEO_MODELL, "stream": False, "options": {"num_ctx": NEO_NUM_CTX},
            "tools": _ollama_werkzeuge(), "messages": nachrichten}
    try:
        # 180s war bei einem grossen, weit fortgeschrittenen Kontext (Prefill skaliert mit der
        # Kontextgroesse) zu knapp und lief in ein ReadTimeout, nachdem Neo schon 34 echte
        # Schritte gemacht hatte -- die Arbeit war also nicht das Problem, nur das Zeitlimit
        # dafuer. Kein Cloudflare-Risiko mehr dadurch: der Stream haelt sich per eigenem
        # Pulsschlag (neo_agentenlauf) unabhaengig davon am Leben.
        async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT_SEK) as client:
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
    return bloecke

async def _ollama_schritt(system: str, verlauf: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Ein leerer Ruecklauf (weder Text noch Werkzeugaufruf) kommt vor allem vor, wenn das
    # denkende Modell mitten im Denken abgeschnitten wird -- meist ein einmaliger Ausrutscher.
    # Ein zweiter Versuch mit derselben Anfrage behebt das haeufig, ohne den ganzen Lauf
    # (und schon geschriebene Dateien darin) wegzuwerfen.
    bloecke = await _ollama_anfrage(system, verlauf)
    if bloecke:
        return bloecke
    bloecke = await _ollama_anfrage(system, verlauf)
    if not bloecke:
        raise NeoSchrittLeer()
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

async def _neo_agentenlauf_kern(system: str, erste_anfrage: str, warteschlange: asyncio.Queue) -> None:
    verlauf: list[dict[str, Any]] = [{"role": "user", "content": [{"type": "text", "text": erste_anfrage}]}]
    geaendert: list[dict[str, Any]] = []
    schritte: list[str] = []
    letzter_text = ""
    for _ in range(MAX_SCHRITTE):
        try:
            bloecke = await neo_motor_schritt(system, verlauf)
        except (NeoSchrittLeer, HTTPException) as fehler:
            # Nicht den ganzen Lauf mit einem nackten Fehler wegwerfen -- was Neo bis hierhin
            # schon getan (und geschrieben!) hat, bleibt sichtbar, mit einer ehrlichen Notiz
            # statt einer erfundenen Antwort. Nur wenn noch gar nichts geschah, ist es ein
            # echter Fehlschlag ohne etwas zu zeigen.
            hinweis = ("Ollama hat auf diesen Schritt weder Text noch Werkzeugaufruf geliefert "
                       "(auch im zweiten Versuch nicht).") if isinstance(fehler, NeoSchrittLeer) else str(fehler.detail)
            if not schritte:
                await warteschlange.put({"typ": "fehler", "text": hinweis})
                return
            letzter_text = (letzter_text + "\n\n" if letzter_text else "") + hinweis
            await warteschlange.put({"typ": "fertig", "text": letzter_text, "dateien": geaendert, "schritte": schritte})
            return
        verlauf.append({"role": "assistant", "content": bloecke})
        werkzeug_aufrufe = [b for b in bloecke if b.get("type") == "tool_use"]
        text_teile = [b.get("text", "") for b in bloecke if b.get("type") == "text"]
        neuer_text = "\n".join(t for t in text_teile if t).strip()
        if neuer_text:
            letzter_text = neuer_text
        if not werkzeug_aufrufe:
            await warteschlange.put({"typ": "fertig", "text": letzter_text, "dateien": geaendert, "schritte": schritte})
            return
        ergebnisse: list[dict[str, Any]] = []
        for aufruf in werkzeug_aufrufe:
            name = aufruf.get("name") or ""
            eingabe = aufruf.get("input") or {}
            ergebnis = await werkzeug_ausfuehren(name, eingabe, geaendert)
            schritt = f"{name}({_kurzfassung(eingabe)})"
            schritte.append(schritt)
            await warteschlange.put({"typ": "schritt", "schritt": schritt})
            ergebnisse.append({"type": "tool_result", "tool_use_id": aufruf.get("id", ""), "content": ergebnis})
        verlauf.append({"role": "user", "content": ergebnisse})
    letzter_text = (letzter_text + "\n\n" if letzter_text else "") + (
        f"Neo hat das Limit von {MAX_SCHRITTE} Arbeitsschritten erreicht, ohne fertig zu werden. "
        "Frag genauer oder in kleineren Schritten."
    )
    await warteschlange.put({"typ": "fertig", "text": letzter_text, "dateien": geaendert, "schritte": schritte})

_PULS_SEK = 20.0

async def neo_agentenlauf(system: str, erste_anfrage: str):
    """Async-Generator statt einer einzelnen Antwort am Ende: ein Auftrag mit vielen
    Werkzeugaufrufen (bis zu VVEC_NEO_MAX_SCHRITTE) und einem denkenden Modell kann mehrere
    Minuten dauern. Cloudflare (Edge-Proxy vor cockpit-v1-r2.vveorgxais.org) bricht eine HTTP-
    Antwort, die laenger als rund 100s KEIN Byte sendet, mit einer HTML-Fehlerseite ab -- das
    Frontend bekam dann statt JSON ein '<html>...' und `response.json()` scheiterte mit
    'Unexpected token <'. Deshalb laeuft die eigentliche Arbeit in einem Hintergrund-Task, der
    Ereignisse in eine Queue schreibt; hier kommt spaetestens alle _PULS_SEK Sekunden ein
    Lebenszeichen heraus, auch wenn ein einzelner Schritt (grosses Denken, langsamer Befehl)
    laenger braucht."""
    warteschlange: asyncio.Queue = asyncio.Queue()
    SENTINEL = object()

    async def _lauf():
        try:
            await _neo_agentenlauf_kern(system, erste_anfrage, warteschlange)
        finally:
            await warteschlange.put(SENTINEL)

    aufgabe = asyncio.create_task(_lauf())
    try:
        while True:
            try:
                ereignis = await asyncio.wait_for(warteschlange.get(), timeout=_PULS_SEK)
            except asyncio.TimeoutError:
                yield {"typ": "puls"}
                continue
            if ereignis is SENTINEL:
                break
            yield ereignis
    finally:
        if not aufgabe.done():
            aufgabe.cancel()

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

class NutzerHinzufuegenKoerper(BaseModel):
    benutzername: str = Field(min_length=2, max_length=60)
    email: str = Field(min_length=3, max_length=200)
    passwort: str = Field(min_length=8, max_length=200)

class NutzerEntfernenKoerper(BaseModel):
    benutzername: str

class GespraechKoerper(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    an: str = "neo"
    datei: str | None = None

@app.get("/status")
async def status():
    return {"dienst": "vve-cp-r2", "ok": True, "seit_sekunden": int(time.time() - START),
            "ollama": OLLAMA, "neo_modell": NEO_MODELL,
            "neo_anbieter": NEO_ANBIETER, "neo_aktives_modell": AKTIVES_MODELL_LABEL}

@app.get("/api/konto/ich")
async def konto_ich(request: Request):
    liste = benutzer_liste()
    benutzername = sitzung_pruefen(request.cookies.get(SITZUNG_COOKIE))
    benutzer = benutzer_finden(benutzername) if benutzername else None
    return {"eingerichtet": len(liste) > 0, "angemeldet": benutzername is not None,
            "benutzername": benutzername, "email": benutzer.get("email") if benutzer else None}

@app.post("/api/konto/einrichten")
async def konto_einrichten(koerper: EinrichtenKoerper, response: Response):
    # Nur erlaubt, solange noch gar kein Konto existiert -- das Anlegen weiterer
    # Konten laeuft danach ausschliesslich ueber /api/konto/nutzer-hinzufuegen und
    # verlangt eine Sitzung. Sonst koennte sich ueber das oeffentliche Internet
    # jeder ein zweites Konto anlegen.
    if benutzer_liste():
        raise HTTPException(409, "Es gibt schon ein Konto. Weitere Konten legt ein angemeldeter Nutzer an.")
    neu = {"benutzername": koerper.benutzername, "email": koerper.email,
           **passwort_setzen(koerper.passwort), "reset_hash": None, "reset_ablauf": None}
    benutzer_liste_schreiben([neu])
    token = sitzung_anlegen(koerper.benutzername)
    response.set_cookie(SITZUNG_COOKIE, token, httponly=True, samesite="lax",
                         secure=COOKIE_SICHER, max_age=SITZUNG_DAUER_SEK)
    journal_anhaengen({"wer": "veiko", "was": "konto-eingerichtet"})
    return {"benutzername": koerper.benutzername}

@app.post("/api/konto/anmelden")
async def konto_anmelden(koerper: AnmeldenKoerper, response: Response):
    benutzer = benutzer_finden(koerper.benutzername)
    if not benutzer or not passwort_pruefen(koerper.passwort, benutzer["salt"], benutzer["hash"]):
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
    benutzer = benutzer_finden(benutzername)
    if not benutzer or not passwort_pruefen(koerper.aktuelles_passwort, benutzer["salt"], benutzer["hash"]):
        raise HTTPException(401, "Aktuelles Passwort falsch.")
    benutzer_aktualisieren(benutzername, passwort_setzen(koerper.neues_passwort))
    journal_anhaengen({"wer": benutzername, "was": "passwort-geaendert"})
    return {"ok": True}

@app.post("/api/konto/passwort-vergessen")
async def konto_passwort_vergessen(koerper: PasswortVergessenKoerper):
    # Immer dieselbe Antwort, ob die E-Mail zu einem Konto passt oder nicht -- sonst
    # liesse sich ausprobieren, welche Adressen es als Konto gibt.
    antwort = {"ok": True, "hinweis": "Wenn die Adresse zu einem Konto passt, ist eine E-Mail unterwegs."}
    benutzer = benutzer_email_finden(koerper.email)
    if not benutzer:
        return antwort
    if not OEFFENTLICHE_URL:
        raise HTTPException(503, "VVEC_OEFFENTLICHE_URL ist nicht gesetzt -- der Reset-Link im Cockpit "
                                   "haette kein Ziel. Trag die Adresse ein, unter der das Cockpit von "
                                   "aussen erreichbar ist.")
    roh_token = secrets.token_urlsafe(32)
    benutzer_aktualisieren(benutzer["benutzername"], {
        "reset_hash": hashlib.sha256(roh_token.encode("utf-8")).hexdigest(),
        "reset_ablauf": time.time() + RESET_DAUER_SEK,
    })
    link = f"{OEFFENTLICHE_URL}/?reset={roh_token}"
    email_senden(benutzer["email"],
                 "VVE Cockpit -- Passwort zuruecksetzen",
                 f"Neues Passwort setzen (eine Stunde gueltig): {link}\n\n"
                 "Wenn das nicht du warst: nichts tun, der Link verfaellt von selbst.")
    journal_anhaengen({"wer": "cockpit", "was": "reset-mail-verschickt"})
    return antwort

@app.post("/api/konto/passwort-zuruecksetzen")
async def konto_passwort_zuruecksetzen(koerper: PasswortZuruecksetzenKoerper):
    pruef_hash = hashlib.sha256(koerper.token.encode("utf-8")).hexdigest()
    benutzer = benutzer_reset_finden(pruef_hash)
    if not benutzer:
        raise HTTPException(400, "Der Link ist ungueltig.")
    if time.time() > float(benutzer.get("reset_ablauf") or 0):
        raise HTTPException(400, "Der Link ist abgelaufen. Neu anfordern.")
    benutzer_aktualisieren(benutzer["benutzername"],
                            {**passwort_setzen(koerper.neues_passwort), "reset_hash": None, "reset_ablauf": None})
    journal_anhaengen({"wer": benutzer["benutzername"], "was": "passwort-zurueckgesetzt"})
    return {"ok": True}

@app.get("/api/konto/nutzer")
async def konto_nutzer_liste(request: Request):
    if not sitzung_pruefen(request.cookies.get(SITZUNG_COOKIE)):
        raise HTTPException(401, "Nicht angemeldet.")
    return {"nutzer": [{"benutzername": b["benutzername"], "email": b.get("email")} for b in benutzer_liste()]}

@app.post("/api/konto/nutzer-hinzufuegen")
async def konto_nutzer_hinzufuegen(koerper: NutzerHinzufuegenKoerper, request: Request):
    if not sitzung_pruefen(request.cookies.get(SITZUNG_COOKIE)):
        raise HTTPException(401, "Nicht angemeldet.")
    if benutzer_finden(koerper.benutzername):
        raise HTTPException(409, "Diesen Benutzernamen gibt es schon.")
    liste = benutzer_liste()
    liste.append({"benutzername": koerper.benutzername, "email": koerper.email,
                  **passwort_setzen(koerper.passwort), "reset_hash": None, "reset_ablauf": None})
    benutzer_liste_schreiben(liste)
    journal_anhaengen({"wer": "veiko", "was": "nutzer-hinzugefuegt", "benutzername": koerper.benutzername})
    return {"benutzername": koerper.benutzername}

@app.post("/api/konto/nutzer-entfernen")
async def konto_nutzer_entfernen(koerper: NutzerEntfernenKoerper, request: Request):
    if not sitzung_pruefen(request.cookies.get(SITZUNG_COOKIE)):
        raise HTTPException(401, "Nicht angemeldet.")
    liste = benutzer_liste()
    if len(liste) <= 1:
        raise HTTPException(400, "Das letzte Konto kann nicht entfernt werden -- sonst kommt niemand mehr rein.")
    neue_liste = [b for b in liste if b.get("benutzername") != koerper.benutzername]
    if len(neue_liste) == len(liste):
        raise HTTPException(404, "Diesen Benutzernamen gibt es nicht.")
    benutzer_liste_schreiben(neue_liste)
    for token, eintrag in list(SITZUNGEN.items()):
        if eintrag.get("benutzername") == koerper.benutzername:
            SITZUNGEN.pop(token, None)
    journal_anhaengen({"wer": "veiko", "was": "nutzer-entfernt", "benutzername": koerper.benutzername})
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

def _ndjson(ereignis: dict[str, Any]) -> str:
    return json.dumps(ereignis, ensure_ascii=False) + "\n"

@app.post("/api/gespraech")
async def gespraech(koerper: GespraechKoerper):
    an = koerper.an.strip().lower() or "neo"
    if an != "neo":
        journal_anhaengen({"wer": "cockpit", "was": "abgewiesen", "an": an})
        async def abgewiesen():
            yield _ndjson({"typ": "fertig", "wer": "cockpit",
                "lauf": "Cockpit nimmt keine Fachrolle ausser Neo in Iteration 1.",
                "text": f"{an.capitalize()} arbeitet in dieser Iteration noch nicht. Schreib an Neo, wenn die Loesung selbst geaendert werden soll.",
                "dateien": [], "schritte": []})
        return StreamingResponse(abgewiesen(), media_type="application/x-ndjson")
    anfrage = koerper.text
    if koerper.datei:
        ziel = pfad_pruefen(koerper.datei)
        if ziel.exists():
            anfrage += f"\n\n## Angehaengte Datei {koerper.datei}\n" + ziel.read_text(encoding="utf-8")[:8000]
    journal_anhaengen({"wer": "veiko", "was": "auftrag", "text": koerper.text[:500]})

    async def strom():
        # NDJSON: ein Ereignis pro Zeile. "puls" haelt die Verbindung durch Cloudflare am Leben
        # (siehe neo_agentenlauf), "schritt" zeigt live einen Werkzeugaufruf, "fertig"/"fehler"
        # schliesst den Lauf ab -- siehe app.js fuer die Gegenseite.
        text, geaenderte_dateien, schritte = "", [], []
        async for ereignis in neo_agentenlauf(neo_system(), anfrage):
            typ = ereignis["typ"]
            if typ == "puls" or typ == "schritt":
                yield _ndjson(ereignis)
                continue
            text = ereignis.get("text", "")
            geaenderte_dateien = ereignis.get("dateien", [])
            schritte = ereignis.get("schritte", [])
            if typ == "fehler":
                journal_anhaengen({"wer": "neo", "was": "fehler", "text": text[:500]})
                yield _ndjson({"typ": "fehler", "text": text})
                return
        journal_anhaengen({"wer": "neo", "was": "antwort",
                            "dateien": [d["pfad"] for d in geaenderte_dateien], "schritte": schritte})
        if schritte:
            lauf = f"Neo hat {len(schritte)} Arbeitsschritt(e) gemacht"
            lauf += f" und {len(geaenderte_dateien)} Datei(en) geaendert." if geaenderte_dateien else "."
        else:
            lauf = f"Neo hat mit {AKTIVES_MODELL_LABEL} geantwortet, ohne nachzusehen."
        yield _ndjson({"typ": "fertig", "wer": "neo", "lauf": lauf, "text": text or "Neo hat nichts geantwortet.",
                       "dateien": geaenderte_dateien, "schritte": schritte, "modell": AKTIVES_MODELL_LABEL})
    return StreamingResponse(strom(), media_type="application/x-ndjson")

@app.post("/api/sicherung")
async def sicherung_skizze():
    return JSONResponse({"ok": False, "grund": "Graph-Token haengt am Server, nicht im Repo.",
                         "soll": "POST in Microsoft Graph /me/drive, Ordner VVE-Sicherung. Nie C:."}, status_code=501)

@app.get("/")
async def index():
    # Versionsstempel aus der Aenderungszeit von app.js: erzwingt bei jedem Deploy eine
    # neue URL fuer die Datei, damit ein zwischengespeicherter alter Stand (Cloudflare-Rand,
    # Browser) nicht stillschweigend weiterhin ausgeliefert wird.
    stempel = str(int((FRONTEND / "app.js").stat().st_mtime))
    inhalt = (FRONTEND / "index.html").read_text(encoding="utf-8")
    inhalt = inhalt.replace("/static/app.js", f"/static/app.js?v={stempel}")
    inhalt = inhalt.replace("/static/stil.css", f"/static/stil.css?v={stempel}")
    return HTMLResponse(inhalt)

app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

if __name__ == "__main__":
    import uvicorn
    # Vorgabe bleibt localhost. Auf dem Server ueber VVEC_HOST auf die Tailscale-Adresse
    # gebunden -- nicht 0.0.0.0, damit nichts ausserhalb des Tailnets erreichbar wird,
    # ohne dass dieses Repo die Caddy-Konfiguration anfassen muss.
    HOST = os.environ.get("VVEC_HOST", "127.0.0.1")
    uvicorn.run("server:app", host=HOST, port=8780, reload=False)
