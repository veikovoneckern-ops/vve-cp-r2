"""
ANMELDUNG -- dieselben Konten wie in Iteration 1 (daten/benutzer.json),
Sitzungen aber in der Datenbank. In Iteration 1 lagen sie im Speicher und
waren nach jedem Neustart weg; das hiess: nach jedem Update neu anmelden.

Neo hat Shell-Zugriff als vveadmin. Eine Anmeldung vor dem Cockpit ist
deshalb Pflicht, auch wenn es nur im Tailnet erreichbar ist.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any

from . import db
from .konfig import BENUTZER_DATEI

COOKIE = "vvec_neu"
DAUER = 30 * 24 * 3600


def _hash(passwort: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), salt, 200_000).hex()


def benutzer() -> list[dict[str, Any]]:
    try:
        d = json.loads(BENUTZER_DATEI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(d, dict) and d.get("benutzername"):
        return [d]
    return d.get("benutzer") or [] if isinstance(d, dict) else []


def einrichten(name: str, passwort: str) -> None:
    salt = secrets.token_bytes(16)
    liste = benutzer()
    liste.append({"benutzername": name, "email": "", "salt": salt.hex(), "hash": _hash(passwort, salt)})
    BENUTZER_DATEI.write_text(json.dumps({"benutzer": liste}, ensure_ascii=False, indent=1), encoding="utf-8")


def pruefen(name: str, passwort: str) -> str | None:
    for b in benutzer():
        if b.get("benutzername", "").lower() == name.strip().lower():
            try:
                salt = bytes.fromhex(b["salt"])
            except (KeyError, ValueError):
                return None
            if secrets.compare_digest(_hash(passwort, salt), b.get("hash", "")):
                return b["benutzername"]
    return None


def sitzung_anlegen(name: str) -> str:
    token = secrets.token_urlsafe(32)
    db.ausfuehren("INSERT INTO sitzungen (token,benutzer,erstellt) VALUES (?,?,?)", (token, name, time.time()))
    return token


def sitzung(token: str | None) -> str | None:
    if not token:
        return None
    r = db.eine("SELECT * FROM sitzungen WHERE token=?", (token,))
    if not r:
        return None
    if time.time() - r["erstellt"] > DAUER:
        db.ausfuehren("DELETE FROM sitzungen WHERE token=?", (token,))
        return None
    return r["benutzer"]


def abmelden(token: str | None) -> None:
    if token:
        db.ausfuehren("DELETE FROM sitzungen WHERE token=?", (token,))
