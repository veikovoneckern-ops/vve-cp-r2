"""
EIN Weg zu den lokalen Modellen. Stab, Talk und Neo rufen alle hier an.

Ollamas eigene Schnittstelle (/api/chat) statt der OpenAI-kompatiblen: nur sie
nimmt num_ctx, think und format je Anfrage an. Im alten Backend fuehrte genau
das zu Umwegen (eigene Modellkennung nur fuer ein groesseres Fenster).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, AsyncIterator

import httpx

from .konfig import OLLAMA

_modelle_cache: dict[str, Any] = {"zeit": 0.0, "liste": []}

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


async def _post(body: dict[str, Any], timeout: float) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=timeout) as c:
        r = await c.post(f"{OLLAMA}/api/chat", json=body)
        if r.status_code == 400 and "think" in r.text.lower() and "think" in body:
            # Modelle ohne Denkphase (z. B. llama3.3) lehnen das Feld ab.
            body = {k: v for k, v in body.items() if k != "think"}
            r = await c.post(f"{OLLAMA}/api/chat", json=body)
    if r.status_code >= 400:
        raise ModellFehler(f"Ollama antwortet {r.status_code}: {r.text[:300]}")
    return r.json()


async def chat(modell: str, system: str, nachrichten: list[dict[str, Any]], *,
               json_format: bool = False, temperatur: float | None = None,
               denken: bool | None = False, num_ctx: int | None = 16384,
               timeout: float = 600) -> str:
    body = _body(modell, system, nachrichten, json_format=json_format, temperatur=temperatur,
                 denken=denken, num_ctx=num_ctx, stream=False)
    try:
        d = await _post(body, timeout)
    except httpx.HTTPError as e:
        raise ModellFehler(f"Ollama nicht erreichbar: {e.__class__.__name__}") from e
    return ((d.get("message") or {}).get("content") or "").strip()


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
    async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10)) as c:
        async with c.stream("POST", f"{OLLAMA}/api/chat", json=body) as r:
            if r.status_code == 400 and "think" in body:
                await r.aread()
                body.pop("think", None)
                async for t in _strom_nochmal(c, body):
                    yield t
                return
            if r.status_code >= 400:
                txt = (await r.aread()).decode("utf-8", "replace")
                raise ModellFehler(f"Ollama antwortet {r.status_code}: {txt[:300]}")
            async for zeile in r.aiter_lines():
                if not zeile.strip():
                    continue
                try:
                    d = json.loads(zeile)
                except ValueError:
                    continue
                t = (d.get("message") or {}).get("content") or ""
                if t:
                    yield t


async def _strom_nochmal(c: httpx.AsyncClient, body: dict[str, Any]) -> AsyncIterator[str]:
    async with c.stream("POST", f"{OLLAMA}/api/chat", json=body) as r:
        if r.status_code >= 400:
            txt = (await r.aread()).decode("utf-8", "replace")
            raise ModellFehler(f"Ollama antwortet {r.status_code}: {txt[:300]}")
        async for zeile in r.aiter_lines():
            try:
                d = json.loads(zeile)
            except ValueError:
                continue
            t = (d.get("message") or {}).get("content") or ""
            if t:
                yield t


async def geladene_modelle() -> list[dict[str, Any]]:
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.get(f"{OLLAMA}/api/ps")
        return r.json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return []
