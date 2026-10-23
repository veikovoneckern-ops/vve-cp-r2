"""
DIE EXTERNEN DIREKT -- Claude, Gemini, Grok ohne das alte Backend (23.10.2026).

Bis dahin ging jeder Aufruf an Dario, Elon oder Demmis ueber das alte Backend
(/api/cloud/<anbieter>), weil nur dort die Schluessel lagen (/etc/vvec/secrets.env).
Veiko will das alte Cockpit loeschen -- dann waeren RSI, Neos Freigabe durch Dario und
die externe Pruefung der LongRuns still ausgefallen.

Jetzt traegt das neue Cockpit die Schluessel selbst (~/.config/vve-cp-r2.env, einmal von
Veiko kopiert, siehe einrichten_befehl()) und spricht die Anbieter direkt an. Die Uebersetzer
sind dieselben wie im alten Backend: das Cockpit spricht innen Anthropic ({system, messages}
rein, {content:[{type:text}], usage} raus); Grok spricht OpenAI, Gemini ein eigenes Format mit
dem Modell im Pfad. Ehrlich bleibt, was dort ehrlich war: ein Abbruch mitten im Satz oder
ein Sicherheitsfilter steht im Text, statt als leere Antwort durchzugehen.

Fehlt hier ein Schluessel, nimmt teamchat._cloud_chat weiter den alten Weg -- der Umzug soll
nichts unterbrechen.
"""
from __future__ import annotations

import re
from typing import Any

import httpx

from .konfig import env_wert

ANBIETER: dict[str, dict[str, Any]] = {
    "claude": {"base": "https://api.anthropic.com/v1", "art": "anthropic", "key": "ANTHROPIC_API_KEY",
               "auth": lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}},
    "gemini": {"base": "https://generativelanguage.googleapis.com/v1beta", "art": "gemini", "key": "GEMINI_API_KEY",
               "auth": lambda k: {"x-goog-api-key": k}},
    "grok": {"base": "https://api.x.ai/v1", "art": "openai", "key": "XAI_API_KEY",
             "auth": lambda k: {"Authorization": f"Bearer {k}"}},
}


class CloudFehler(Exception):
    pass


def schluessel(p: str) -> str:
    return env_wert(ANBIETER[p]["key"]) if p in ANBIETER else ""


def alle_da() -> bool:
    return all(schluessel(p) for p in ANBIETER)


def einrichten_befehl() -> str:
    """Einmal von Veiko (Passwort): Cloud-Schluessel UND Postausgang aus dem alten Cockpit
    uebernehmen -- genau diese acht Zeilen, nichts sonst aus secrets.env."""
    return ("sudo grep -E '^(ANTHROPIC_API_KEY|GEMINI_API_KEY|XAI_API_KEY|VVEC_SMTP_HOST|VVEC_SMTP_PORT|VVEC_SMTP_USER|"
            "VVEC_SMTP_PASS|VVEC_SMTP_FROM)=' /etc/vvec/secrets.env >> ~/.config/vve-cp-r2.env "
            "&& chmod 600 ~/.config/vve-cp-r2.env && echo uebernommen")


async def modelle(p: str) -> list[str]:
    cfg = ANBIETER[p]
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{cfg['base']}/models", headers=cfg["auth"](schluessel(p)))
    r.raise_for_status()
    raw = r.json()
    items = raw.get("data") or raw.get("models") or []
    return [str(m.get("id") or m.get("name", "")).replace("models/", "") for m in items]


def _text(inhalt: Any) -> str:
    if isinstance(inhalt, list):
        return "\n".join(b.get("text", "") for b in inhalt if isinstance(b, dict) and b.get("type") == "text")
    return inhalt or ""


def _nach_openai(modell: str, system: str, nachrichten: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
    msgs = ([{"role": "system", "content": system}] if system else []) + \
           [{"role": m.get("role", "user"), "content": _text(m.get("content"))} for m in nachrichten]
    return {"model": modell, "messages": msgs, "stream": False, "max_tokens": min(max_tokens, 32000)}


def _von_openai(j: dict[str, Any]) -> tuple[str, int, int]:
    text, grund = "", ""
    try:
        text = j["choices"][0]["message"].get("content") or ""
        grund = j["choices"][0].get("finish_reason") or ""
    except (KeyError, IndexError, TypeError):
        pass
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    u = j.get("usage") or {}
    if grund == "length":
        text = (text + "\n\n[Hier bricht die Antwort ab -- kein Platz mehr, nicht fertig.]").strip()
    return text, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def _nach_gemini(system: str, nachrichten: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
    # Gemini kennt keine Systemrolle in contents und sagt "model" statt "assistant".
    body: dict[str, Any] = {"contents": [{"role": "model" if m.get("role") == "assistant" else "user",
                                          "parts": [{"text": _text(m.get("content"))}]} for m in nachrichten],
                            "generationConfig": {"maxOutputTokens": min(max_tokens, 32000)}}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return body


def _von_gemini(j: dict[str, Any]) -> tuple[str, int, int]:
    text, grund = "", ""
    try:
        k = (j.get("candidates") or [{}])[0]
        grund = k.get("finishReason") or ""
        text = "".join(t.get("text", "") for t in (k.get("content") or {}).get("parts", []) if isinstance(t, dict))
    except (KeyError, IndexError, TypeError):
        pass
    if not text.strip() and grund and grund not in ("STOP", "MAX_TOKENS"):
        # Gemini schweigt vor allem, wenn sein Sicherheitsfilter greift -- das ehrlich benennen.
        text = f"[Gemini hat abgebrochen. Grund: {grund}]"
    elif grund == "MAX_TOKENS":
        text = (text + "\n\n[Hier bricht die Antwort ab -- kein Platz mehr, nicht fertig.]").strip()
    u = j.get("usageMetadata") or {}
    return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)


async def chat(p: str, modell: str, system: str, nachrichten: list[dict[str, Any]],
               max_tokens: int = 16000, timeout: float = 320) -> dict[str, Any]:
    """Ein Aufruf in der Innensprache: {"text", "ein", "aus"} zurueck. Wirft CloudFehler mit Klartext."""
    cfg = ANBIETER[p]
    k = schluessel(p)
    if not k:
        raise CloudFehler(f"{cfg['key']} fehlt in ~/.config/vve-cp-r2.env")
    kopf = {"content-type": "application/json", **cfg["auth"](k)}
    if cfg["art"] == "gemini":
        ziel, body = f"{cfg['base']}/models/{modell}:generateContent", _nach_gemini(system, nachrichten, max_tokens)
    elif cfg["art"] == "openai":
        ziel, body = f"{cfg['base']}/chat/completions", _nach_openai(modell, system, nachrichten, max_tokens)
    else:
        ziel, body = f"{cfg['base']}/messages", {"model": modell, "max_tokens": max_tokens, "system": system, "messages": nachrichten}
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(ziel, json=body, headers=kopf)
    except httpx.HTTPError as e:
        raise CloudFehler(f"{p} nicht erreichbar: {e.__class__.__name__}") from e
    if r.status_code != 200:
        try:
            f = r.json()
            grund = (f.get("error") or {}).get("message") if isinstance(f.get("error"), dict) else (f.get("error") or str(f)[:400])
        except ValueError:
            grund = r.text[:400]
        raise CloudFehler(f"{p}: {grund} ({r.status_code})")
    j = r.json()
    if cfg["art"] == "gemini":
        return dict(zip(("text", "ein", "aus"), _von_gemini(j)))
    if cfg["art"] == "openai":
        return dict(zip(("text", "ein", "aus"), _von_openai(j)))
    u = j.get("usage") or {}
    text = _text(j.get("content")).strip()
    if j.get("stop_reason") == "max_tokens":
        text = (text + "\n\n[Hier bricht die Antwort ab -- kein Platz mehr, nicht fertig.]").strip()
    return {"text": text, "ein": u.get("input_tokens", 0), "aus": u.get("output_tokens", 0)}
