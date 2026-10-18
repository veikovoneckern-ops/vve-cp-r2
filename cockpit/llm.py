"""
EIN Weg zu den lokalen Modellen. Stab, Talk und Neo rufen alle hier an.

Ollamas eigene Schnittstelle (/api/chat) statt der OpenAI-kompatiblen: nur sie
nimmt num_ctx, think und format je Anfrage an. Im alten Backend fuehrte genau
das zu Umwegen (eigene Modellkennung nur fuer ein groesseres Fenster).
"""
from __future__ import annotations

import asyncio
import collections
import contextvars
import json
import re
import time
from typing import Any, AsyncIterator

import httpx

from .konfig import OLLAMA

_modelle_cache: dict[str, Any] = {"zeit": 0.0, "liste": []}

# Wie viele Anfragen dieses Dienstes gerade bei Ollama rechnen. Die Kopfzeile
# dreht daran das Logo. Gezaehlt wird hier, weil Stab, Talk und Neo alle
# diesen einen Weg gehen -- ein Zaehler je Aufrufer liefe auseinander.
AKTIV: dict[str, Any] = {"n": 0, "seit": None}


def _beginn() -> None:
    if AKTIV["n"] == 0:
        AKTIV["seit"] = time.time()
    AKTIV["n"] += 1


def _ende() -> None:
    AKTIV["n"] = max(0, AKTIV["n"] - 1)
    if AKTIV["n"] == 0:
        AKTIV["seit"] = None


# WER gerade rechnen laesst (Veiko, 16.10.: "aktuell laeuft etwas, aber ich sehe
# nicht, was es macht"). Der Zaehler oben sagt nur DASS; die direkten Gespraeche
# tragen sich hier mit einem Satz ein. Die Pipeline meldet sich ueber stab.laeuft().
TAETIG: dict[int, dict[str, Any]] = {}


class taetig:
    """with llm.taetig("Talk antwortet"): ... -- traegt sich fuer die Dauer ein."""
    _n = 0

    def __init__(self, was: str):
        taetig._n += 1
        self.id, self.was = taetig._n, was

    def __enter__(self):
        TAETIG[self.id] = {"was": self.was, "seit": time.time()}
        # Anfragen in diesem Block gehoeren hierher und nicht zur Pipeline, die
        # vielleicht gleichzeitig rechnet (siehe ZWECK unten).
        self._zweck = ZWECK.set(ZWECK.get() or f"taetig:{self.id}")
        WAS_ZWECK[ZWECK.get()] = self.was
        return self

    def __exit__(self, *_):
        TAETIG.pop(self.id, None)
        WAS_ZWECK.pop(f"taetig:{self.id}", None)
        ZWECK.reset(self._zweck)
        return False


# ---------------------------------------------------------------- Anfragen im Einzelnen
# Veiko, 17.10.2026: "bei Current Actions moechte ich mehr Details, was gerade
# genau gemacht wird." Die Zeilen dort sagten nur den Schritt ("schreibt Etappe 3
# von 12"), nicht welches Modell gerade fuer sie rechnet, ob es noch liest oder
# schon schreibt, wie weit es ist -- und was davor passiert ist.
#
# ZWECK ordnet eine Anfrage der Aktion zu, zu der sie gehoert ("video:<eid>",
# "dossier:<id>", "gespraech:<gid>", "neo:<job>"). Ein contextvars-Wert, weil er
# sich in jeden Task vererbt, den die Aktion startet -- ohne dass jede Funktion
# dazwischen ein Argument durchreichen muss. Die Pipeline und die Langlaeufer
# setzen ihn nicht: sie melden sich ohnehin ueber stab.laeuft() mit Vorgang an,
# und der wird beim Start der Anfrage mitgemerkt.
ZWECK: contextvars.ContextVar[str | None] = contextvars.ContextVar("llm_zweck", default=None)
ANFRAGEN: dict[int, dict[str, Any]] = {}
FERTIG: collections.deque[dict[str, Any]] = collections.deque(maxlen=300)
WAS_ZWECK: dict[str, str] = {}   # Klartext zu einem Zweck ("Talk antwortet")
_anfrage_n = 0


def _anmelden(body: dict[str, Any], stream: bool) -> dict[str, Any]:
    global _anfrage_n
    _anfrage_n += 1
    zweck, vid, was = ZWECK.get(), None, ""
    if zweck:
        was = WAS_ZWECK.get(zweck, "")
    else:
        # Ohne Zweck rechnet die Pipeline oder ein Langlaeufer: beide melden sich
        # ueber stab.laeuft() mit Vorgang und Schritt an.
        try:
            from . import stab
            l = stab.ZUSTAND.get("laeuft") or {}
            vid = l.get("vorgang_id")
            was = f"{stab.rollen_name(l['wer'])} {l.get('was') or ''}".strip() if l.get("wer") else ""
        except Exception:  # noqa: BLE001 -- die Anzeige darf nie einen Aufruf scheitern lassen
            pass
    e = {"id": _anfrage_n, "modell": body.get("model") or "", "start": time.time(), "zweck": zweck,
         "vorgang_id": vid, "was": was, "stream": stream,
         "tok_aus": 0, "denk_tok": 0, "erstes": None, "json": bool(body.get("format"))}
    ANFRAGEN[e["id"]] = e
    return e


def _abmelden(e: dict[str, Any], d: dict[str, Any] | None = None, fehler: str | None = None) -> None:
    ANFRAGEN.pop(e["id"], None)
    d = d or {}
    FERTIG.append({**{k: e[k] for k in ("modell", "start", "zweck", "vorgang_id", "was")}, "ende": time.time(),
                   "tok_ein": d.get("prompt_eval_count") or e.get("tok_ein"), "tok_aus": d.get("eval_count") or e["tok_aus"] or None,
                   "fehler": fehler})


def anfragen_zu(zweck: str | None = None, vorgang_id: str | None = None, verlauf: int = 3) -> dict[str, Any]:
    """Was gerade fuer diese Aktion rechnet und was zuletzt fertig wurde. Ollama
    rechnet je Modell eine Anfrage nach der anderen (n_seq_max = 1): ist fuer
    dasselbe Modell eine aeltere Anfrage offen, WARTET diese -- das wird so gesagt,
    statt "liest" zu behaupten."""
    def passt(a: dict[str, Any]) -> bool:
        return (zweck is not None and a.get("zweck") == zweck) or \
               (vorgang_id is not None and not a.get("zweck") and a.get("vorgang_id") == vorgang_id)

    jetzt = time.time()
    laufend = []
    for a in sorted(ANFRAGEN.values(), key=lambda x: x["start"]):
        if not passt(a):
            continue
        # Alle aelteren offenen Anfragen an dasselbe Modell -- auch die, die schon
        # schreiben: diese hier kommt erst dran, wenn sie ganz fertig sind
        # (gemessen 17.10.: B stand sonst auf "liest", waehrend A noch schrieb).
        vor = [b for b in ANFRAGEN.values() if b["modell"] == a["modell"] and b["start"] < a["start"]
               and not b.get("wartet_vorrang")]
        if a.get("wartet_vorrang"):
            phase, tempo = "pausiert, solange du mit dem Cockpit sprichst", None
        elif a.get("erstes"):
            dauer = jetzt - a["erstes"]
            phase = "schreibt"
            tempo = round(a["tok_aus"] / dauer, 1) if dauer > 2 and a["tok_aus"] else None
        elif a.get("denk_tok"):
            phase, tempo = "denkt nach", None
        elif vor and not a["stream"]:
            phase, tempo = "rechnet oder wartet, bis das Modell frei ist", None
        elif vor:
            phase, tempo = "wartet, bis das Modell frei ist", None
        else:
            # Ob Ollama das Modell erst laedt, sagt die Anfrage nicht; nach ein paar
            # Sekunden ohne erstes Wort ist das der haeufigste Grund (gemessen: 12 s).
            phase = "liest die Vorlage" if jetzt - a["start"] < 8 else "lädt das Modell oder liest die Vorlage"
            if not a["stream"]:
                phase += " -- die Antwort kommt am Stück"
            tempo = None
        laufend.append({"modell": a["modell"], "seit": a["start"], "phase": phase, "tok_aus": a["tok_aus"] or None,
                        "denk_tok": a["denk_tok"] or None, "tempo": tempo, "was": a["was"],
                        "vor": [b["was"] or b["modell"] for b in vor][:2]})
    fertig = [f for f in reversed(FERTIG) if passt(f)][:verlauf]
    return {"laufend": laufend,
            "verlauf": [{"was": f["was"], "modell": f["modell"], "ende": f["ende"], "dauer_s": round(f["ende"] - f["start"]),
                         "tok_aus": f["tok_aus"], "fehler": f["fehler"]} for f in fertig]}


async def mit_zweck(zweck: str, coro):
    """asyncio.create_task(llm.mit_zweck("video:" + eid, _lauf(...))) -- alle
    Anfragen in diesem Task zaehlen fuer diese Aktion."""
    ZWECK.set(zweck)
    return await coro


def anfragen_frei() -> list[dict[str, Any]]:
    """Anfragen, die keiner Aktion zuzuordnen sind (fuer die Kopfzeile)."""
    return [{"modell": a["modell"], "seit": a["start"], "was": a["was"]} for a in ANFRAGEN.values()
            if not a.get("zweck") and not a.get("vorgang_id")]


# ---------------------------------------------------------------- Vorrang fuer Gespraeche
# Veiko, 18.10.2026: "wenn etwas laeuft und ich parallel mit dem Cockpit sprechen
# will, dauert das Verstehen, Antworten und Ausfuehren lange. Talk soll gut und
# schnell funktionieren; ob ein Langlaeufer dadurch etwas laenger dauert, ist
# nicht so wichtig."
#
# Der Grund ist Ollama: es rechnet je Modell EINE Anfrage nach der anderen
# (n_seq_max = 1), und seit "ein Modell fuer alle" teilen sich Talk und das ganze
# Team qwen3.8. Schrieb Neal gerade ein Kapitel, stand Talk hinten in der Schlange
# -- Minuten, nicht Sekunden. Eine Warteschlange mit Vorrang hilft dagegen nicht:
# Ollama nimmt eine laufende Anfrage nicht zurueck. Also umgekehrt: beginnt ein
# Gespraech (Talk, Board, Team-Chat -- Veiko sitzt davor und wartet), werden die
# laufenden Hintergrund-Anfragen abgebrochen (Verbindung zu = Ollama hoert auf)
# und spaeter von vorn gestellt; neue warten. Der Preis ist die verworfene halbe
# Antwort des Langlaeufers -- genau der Tausch, den Veiko will.
#
# NACHLAUF: ein Gespraech ist mehr als eine Anfrage -- danach liest Piper vor,
# Veiko antwortet, Whisper schreibt ab. Startete der Hintergrund in dieser Pause
# wieder, staende der naechste Satz erneut hinten an und das halbe Kapitel waere
# umsonst angefangen. Hoeren und Sprechen frischen den Zeitpunkt deshalb auf.
VORRANG: contextvars.ContextVar[bool] = contextvars.ContextVar("llm_vorrang", default=False)
NACHLAUF_S = 45
_vorrang: dict[str, Any] = {"offen": 0, "zuletzt": 0.0}
_HINTERGRUND: dict[int, asyncio.Task] = {}   # Anfrage-ID -> der Task, der gerade bei Ollama liest


def vorrang_anstossen() -> None:
    """Hoeren/Sprechen von Talk: haelt den Hintergrund noch NACHLAUF_S zurueck."""
    _vorrang["zuletzt"] = time.time()


def vorrang_aktiv() -> bool:
    return bool(_vorrang["offen"]) or time.time() - _vorrang["zuletzt"] < NACHLAUF_S


class vorrang:
    """with llm.vorrang(): ... -- ein Gespraech laeuft; der Hintergrund weicht."""

    def __enter__(self):
        self._token = VORRANG.set(True)
        _vorrang["offen"] += 1
        _vorrang["zuletzt"] = time.time()
        for aid, t in list(_HINTERGRUND.items()):
            e = ANFRAGEN.get(aid)
            if e is not None:
                e["verdraengt"] = True
            t.cancel()
        return self

    def __exit__(self, *_):
        _vorrang["offen"] = max(0, _vorrang["offen"] - 1)
        _vorrang["zuletzt"] = time.time()
        VORRANG.reset(self._token)
        return False


async def _warten_auf_vorrang(e: dict[str, Any]) -> None:
    if VORRANG.get():
        return
    try:
        while vorrang_aktiv():
            e["wartet_vorrang"] = True
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        ANFRAGEN.pop(e["id"], None)   # abgebrochen, bevor sie bei Ollama war
        raise
    e.pop("wartet_vorrang", None)

# Tempo direkter Gespraeche (Talk, Board, Team-Chat). Vorgabe ist gruendlich:
# das Modell denkt vor der Antwort nach. "Schnelle Antwort" schaltet das ab --
# Veikos Wunsch fuer unterwegs (Handy, Tablet). Die Pipeline kennt keinen
# Schalter, sie arbeitet immer gruendlich (stab.DENKEN).
GRUENDLICH_ZUSATZ = ("TEMPO: gründlich. Denk vor der Antwort sorgfältig nach und antworte vollständig; "
                     "Rechenzeit spielt keine Rolle.")
SCHNELL_ZUSATZ = "TEMPO: schnell. Veiko will eine schnelle Antwort: knapp, direkt, das Wichtigste zuerst."


def tempo(schnell: bool) -> tuple[bool, str]:
    """(denken, Zusatz fuer den System-Text)."""
    return (False, SCHNELL_ZUSATZ) if schnell else (True, GRUENDLICH_ZUSATZ)


# Chinesische, japanische, koreanische Schriftzeichen. Gemessen im alten Journal:
# "Veiko建树作为 expert" -- solche Antworten sollen nie bei Veiko ankommen.
FREMDSCHRIFT = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯]")


class ModellFehler(Exception):
    pass


async def installierte_modelle(frisch: bool = False) -> list[str]:
    if not frisch and time.time() - _modelle_cache["zeit"] < 60 and _modelle_cache["liste"]:
        return _modelle_cache["liste"]
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{OLLAMA}/api/tags")
        namen = [m.get("name", "") for m in r.json().get("models", [])]
    except (httpx.HTTPError, ValueError):
        return _modelle_cache["liste"]
    _modelle_cache.update(zeit=time.time(), liste=namen)
    return namen


async def modell_waehlen(*wuensche: str | None) -> str | None:
    """Erstes installiertes Modell aus der Wunschliste. Nie eines, das es nicht gibt."""
    da = await installierte_modelle()
    for w in wuensche:
        if not w:
            continue
        if w in da:
            return w
        if ":" not in w and f"{w}:latest" in da:
            return f"{w}:latest"
    return None


def fremdschrift(text: str) -> bool:
    return bool(FREMDSCHRIFT.search(text or ""))


def json_aus(text: str) -> Any:
    """JSON aus einer Modellantwort holen -- auch wenn drumherum Text oder ein
    Codezaun steht."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        pass
    for auf, zu in (("{", "}"), ("[", "]")):
        a, b = t.find(auf), t.rfind(zu)
        if a != -1 and b > a:
            try:
                return json.loads(t[a:b + 1])
            except ValueError:
                continue
    return None


def _body(modell: str, system: str, nachrichten: list[dict[str, Any]], *, json_format: bool,
          temperatur: float | None, denken: bool | None, num_ctx: int | None,
          stream: bool, tools: list | None = None) -> dict[str, Any]:
    msgs = ([{"role": "system", "content": system}] if system else []) + nachrichten
    opts: dict[str, Any] = {}
    if temperatur is not None:
        opts["temperature"] = temperatur
    if num_ctx:
        opts["num_ctx"] = num_ctx
    body: dict[str, Any] = {"model": modell, "messages": msgs, "stream": stream, "options": opts}
    if json_format:
        body["format"] = "json"
    if denken is not None:
        body["think"] = denken
    if tools:
        body["tools"] = tools
    return body


# ---------------------------------------------------------------- Verbrauch
# Jeder Modellaufruf bucht eine Zeile in die Tabelle "verbrauch" (Seite
# Verbrauch). Wofuer gerechnet wurde, steht nicht im Aufruf -- es wird aus dem
# genommen, was sich gerade angemeldet hat (taetig() fuer Talk, Team-Chat,
# Board; stab.laeuft() fuer die Pipeline). Laufen zwei Dinge gleichzeitig,
# gilt das zuletzt angemeldete; das ist eine Naeherung, die Token selbst sind exakt.
def _bereich(was: str) -> str:
    for wort, b in (("Talk", "Talk"), ("Team-Chat", "Team-Chat"), ("Advisory Board", "Advisory Board"), ("Neo", "Neo")):
        if wort in was:
            return b
    return "Sonstiges"


def wofuer() -> dict[str, Any]:
    if TAETIG:
        was = TAETIG[max(TAETIG)]["was"]
        return {"bereich": _bereich(was), "was": was, "wer": None, "vorgang_id": None}
    try:
        from . import stab
        l = stab.ZUSTAND.get("laeuft")
        if l:
            return {"bereich": "Team (Pipeline)", "was": f"{stab.rollen_name(l['wer'])} {l.get('was') or ''}".strip(),
                    "wer": l["wer"], "vorgang_id": l.get("vorgang_id")}
    except Exception:  # noqa: BLE001 -- Buchen darf nie einen Aufruf scheitern lassen
        pass
    return {"bereich": "Sonstiges", "was": "", "wer": None, "vorgang_id": None}


def buchen(art: str, anbieter: str, modell: str, tok_ein: int, tok_aus: int, dauer_s: float = 0.0,
           geschaetzt: bool = False, **dazu: Any) -> None:
    try:
        from . import db
        w = {**wofuer(), **{k: v for k, v in dazu.items() if v}}
        pid = w.get("projekt_id")
        if not pid and w.get("vorgang_id"):
            pid = (db.holen("vorgaenge", w["vorgang_id"]) or {}).get("projekt_id")
        db.ausfuehren("INSERT INTO verbrauch (zeit,art,anbieter,modell,bereich,was,wer,vorgang_id,projekt_id,tok_ein,tok_aus,dauer_s,geschaetzt) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (time.time(), art, anbieter, modell, w.get("bereich"), (w.get("was") or "")[:160], w.get("wer"),
                       w.get("vorgang_id"), pid, int(tok_ein or 0), int(tok_aus or 0), round(float(dauer_s or 0), 2), int(geschaetzt)))
    except Exception as e:  # noqa: BLE001
        print(f"[verbrauch] nicht gebucht: {e}", flush=True)


def _ollama_buchen(body: dict[str, Any], d: dict[str, Any]) -> None:
    buchen("lokal", "ollama", body.get("model") or "", d.get("prompt_eval_count") or 0, d.get("eval_count") or 0,
           (d.get("total_duration") or 0) / 1e9)


async def _post(body: dict[str, Any], timeout: float, warten: bool = False) -> dict[str, Any]:
    e = _anmelden(body, False)
    if warten:   # Revision: Hintergrund, nicht abbrechbar (am Stueck geholt), wartet aber auf Gespraeche
        await _warten_auf_vorrang(e)
    _beginn()
    d: dict[str, Any] | None = None
    grund = "abgebrochen"
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(f"{OLLAMA}/api/chat", json=body)
            if r.status_code == 400 and "think" in r.text.lower() and "think" in body:
                # Modelle ohne Denkphase (z. B. llama3.3) lehnen das Feld ab.
                body = {k: v for k, v in body.items() if k != "think"}
                r = await c.post(f"{OLLAMA}/api/chat", json=body)
        if r.status_code >= 400:
            grund = f"Ollama {r.status_code}"
            raise ModellFehler(f"Ollama antwortet {r.status_code}: {r.text[:300]}")
        d = r.json()
        grund = None
    except httpx.HTTPError as f:
        grund = f.__class__.__name__
        raise
    finally:
        _ende()
        _abmelden(e, d, grund)
    _ollama_buchen(body, d)
    return d


async def chat(modell: str, system: str, nachrichten: list[dict[str, Any]], *,
               json_format: bool = False, temperatur: float | None = None,
               denken: bool | None = False, num_ctx: int | None = 16384,
               timeout: float = 600) -> str:
    # Intern als Strom gelesen, nach aussen eine fertige Antwort wie bisher: nur
    # so sieht Current Actions, dass und wie schnell eine Antwort waechst
    # (17.10.2026). Am Stueck geholt hiess es zehn Minuten lang nur "rechnet".
    body = _body(modell, system, nachrichten, json_format=json_format, temperatur=temperatur,
                 denken=denken, num_ctx=num_ctx, stream=True)
    teile: list[str] = []
    e = _anmelden(body, True)
    grund = "abgebrochen"

    async def sammeln() -> None:
        async with asyncio.timeout(timeout):
            async for t in _strom_lauf(body, e):
                teile.append(t)

    try:
        while True:
            # Ausserhalb der Zeitgrenze: das Warten auf ein Gespraech ist keine Rechenzeit.
            await _warten_auf_vorrang(e)
            teile.clear()
            e.update(tok_aus=0, denk_tok=0, erstes=None, verdraengt=False)
            _beginn()
            # Ein eigener Task, damit vorrang() genau DIESE Anfrage abbrechen kann,
            # ohne den Aufrufer (Pipeline, Langlaeufer) mit abzubrechen.
            innen = asyncio.create_task(sammeln())
            if not VORRANG.get():
                _HINTERGRUND[e["id"]] = innen
            try:
                await innen
            except asyncio.CancelledError:
                if e.get("verdraengt") and not asyncio.current_task().cancelling():
                    print(f"[llm] {e['was'] or body.get('model')}: weicht einem Gespräch, wird danach neu gestellt",
                          flush=True)
                    continue
                raise
            finally:
                _HINTERGRUND.pop(e["id"], None)
                _ende()
            break
        grund = None
    except TimeoutError as f:
        grund = "Zeitgrenze"
        raise ModellFehler(f"Ollama antwortet nicht binnen {round(timeout)} s") from f
    except httpx.HTTPError as f:
        grund = f.__class__.__name__
        raise ModellFehler(f"Ollama nicht erreichbar: {f.__class__.__name__}") from f
    except ModellFehler:
        grund = "Fehler"
        raise
    finally:
        _abmelden(e, e.get("_fertig"), grund)
    return "".join(teile).strip()


async def chat_mit_werkzeugen(modell: str, system: str, nachrichten: list[dict[str, Any]],
                              tools: list[dict[str, Any]], *, num_ctx: int = 65536,
                              timeout: float = 600) -> dict[str, Any]:
    body = _body(modell, system, nachrichten, json_format=False, temperatur=None, denken=None,
                 num_ctx=num_ctx, stream=False, tools=tools)
    try:
        d = await _post(body, timeout)
    except httpx.HTTPError as e:
        raise ModellFehler(f"Ollama nicht erreichbar: {e.__class__.__name__}") from e
    return d.get("message") or {}


async def strom(modell: str, system: str, nachrichten: list[dict[str, Any]], *,
                temperatur: float | None = 0.4, denken: bool | None = False,
                num_ctx: int | None = 16384) -> AsyncIterator[str]:
    body = _body(modell, system, nachrichten, json_format=False, temperatur=temperatur,
                 denken=denken, num_ctx=num_ctx, stream=True)
    e = _anmelden(body, True)
    await _warten_auf_vorrang(e)   # ohne Gespraech drumherum (heute niemand) wie der Hintergrund
    _beginn()
    grund = "abgebrochen"
    try:
        async for t in _strom_lauf(body, e):
            yield t
        grund = None
    except (httpx.HTTPError, ModellFehler) as f:
        grund = f.__class__.__name__
        raise
    finally:
        _ende()
        _abmelden(e, e.get("_fertig"), grund)


def _zeile(body: dict[str, Any], e: dict[str, Any], zeile: str) -> str:
    """Eine Zeile aus Ollamas Strom: zaehlt mit (Current Actions) und gibt den Text."""
    if not zeile.strip():
        return ""
    try:
        d = json.loads(zeile)
    except ValueError:
        return ""
    if d.get("done"):   # die letzte Zeile traegt die Zaehler
        e["_fertig"] = d
        _ollama_buchen(body, d)
    m = d.get("message") or {}
    if m.get("thinking"):
        e["denk_tok"] += 1   # ein Stueck je Zeile -- bei Ollama ein Token
    t = m.get("content") or ""
    if t:
        e["tok_aus"] += 1
        if not e["erstes"]:
            e["erstes"] = time.time()
    return t


# Speichermangel auf einer Grafikkarte ist meist voruebergehend: ComfyUI rechnet gerade
# ein Bild auf Karte 2 (18.10.2026: ein Langlaeufer brach dreimal in 20 s mit
# "cudaMalloc failed: out of memory ... CUDA1" ab, waehrend Folienbilder liefen, und hielt an).
# Dann warten, bis ComfyUI fertig ist, es seinen Speicher freigeben lassen und erneut
# versuchen -- statt den Fehler an Langlaeufer, Pipeline oder Gespraech weiterzureichen.
SPEICHERMANGEL = re.compile(r"out of memory|cudaMalloc failed|failed to allocate CUDA", re.I)
SPEICHER_VERSUCHE = 3


async def _platz_schaffen() -> None:
    from . import medien
    ende = time.time() + 240
    while time.time() < ende:
        if await medien.comfy_freigeben() or not await medien.comfy_beschaeftigt():
            break
        await asyncio.sleep(10)
    await asyncio.sleep(5)


async def _strom_lauf(body: dict[str, Any], e: dict[str, Any]) -> AsyncIterator[str]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10)) as c:
        for versuch in range(SPEICHER_VERSUCHE + 1):
            async with c.stream("POST", f"{OLLAMA}/api/chat", json=body) as r:
                if r.status_code == 400 and "think" in body:
                    await r.aread()
                    body.pop("think", None)
                    async for t in _strom_nochmal(c, body, e):
                        yield t
                    return
                if r.status_code >= 400:
                    txt = (await r.aread()).decode("utf-8", "replace")
                    # Noch nichts geliefert -- ein zweiter Anlauf ist also sicher, auch im Strom von Talk.
                    if SPEICHERMANGEL.search(txt) and versuch < SPEICHER_VERSUCHE:
                        print(f"[llm] Speichermangel bei {body.get('model')}, warte auf freien Grafikspeicher "
                              f"(Versuch {versuch + 1} von {SPEICHER_VERSUCHE})", flush=True)
                        await _platz_schaffen()
                        continue
                    raise ModellFehler(f"Ollama antwortet {r.status_code}: {txt[:300]}")
                async for zeile in r.aiter_lines():
                    t = _zeile(body, e, zeile)
                    if t:
                        yield t
                return


async def _strom_nochmal(c: httpx.AsyncClient, body: dict[str, Any], e: dict[str, Any]) -> AsyncIterator[str]:
    async with c.stream("POST", f"{OLLAMA}/api/chat", json=body) as r:
        if r.status_code >= 400:
            txt = (await r.aread()).decode("utf-8", "replace")
            raise ModellFehler(f"Ollama antwortet {r.status_code}: {txt[:300]}")
        async for zeile in r.aiter_lines():
            t = _zeile(body, e, zeile)
            if t:
                yield t


async def geladene_modelle() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.get(f"{OLLAMA}/api/ps")
        return r.json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return []


# ---------------------------------------------------------------- Vorgaben
# Welche Modelle ohne eigene Wahl rechnen (17.10.2026, Modell-Revision): Talk,
# die Rollen ohne eigenes Modell, Jason beim Einordnen, Neo. Bis dahin standen
# sie fest in der Konfiguration -- ein Knopf "Umstellen" haette nichts gehabt,
# das er aendern kann. Die Konfiguration bleibt die Vorgabe; was Veiko auf der
# Seite "Stab & Modelle" waehlt, sticht sie.
VORGABEN = {"talk": "Talk, Board und Gesprächsplanung", "arbeit": "Rollen ohne eigenes Modell (Clayton, Daniel …)",
            "stab": "Jason beim Einordnen, falls ohne eigenes Modell", "neo": "Neo, falls ohne eigenes Modell"}


def vorgabe(art: str) -> str:
    from . import db, konfig
    w = (db.einstellung("modell_vorgaben", {}) or {}).get(art)
    return w or {"talk": konfig.MODELL_TALK, "arbeit": konfig.MODELL_ARBEIT,
                 "stab": konfig.MODELL_STAB, "neo": konfig.MODELL_NEO}[art]
