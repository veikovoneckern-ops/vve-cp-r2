"""
Neues Passwort fuer ein Konto setzen -- direkt auf dem Server, ohne Browser.

Aufruf (im Ordner ~/vve-cp-r2):  .venv/bin/python -m cockpit.passwort veiko
Fragt zweimal nach dem neuen Passwort (Eingabe bleibt unsichtbar) und meldet
alle bestehenden Sitzungen ab.
"""
from __future__ import annotations

import getpass
import json
import secrets
import sys

from . import db
from .anmeldung import _hash, benutzer
from .konfig import BENUTZER_DATEI


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else input("Benutzername: ").strip()
    liste = benutzer()
    konto = next((b for b in liste if b.get("benutzername", "").lower() == name.lower()), None)
    if not konto:
        raise SystemExit(f"Kein Konto „{name}“. Vorhanden: {', '.join(b.get('benutzername', '?') for b in liste) or 'keines'}")
    pw = getpass.getpass("Neues Passwort (mindestens 8 Zeichen): ")
    if len(pw) < 8:
        raise SystemExit("Zu kurz, nichts geändert.")
    if getpass.getpass("Noch einmal: ") != pw:
        raise SystemExit("Die beiden Eingaben stimmen nicht überein, nichts geändert.")
    salt = secrets.token_bytes(16)
    konto["salt"], konto["hash"] = salt.hex(), _hash(pw, salt)
    BENUTZER_DATEI.write_text(json.dumps({"benutzer": liste}, ensure_ascii=False, indent=1), encoding="utf-8")
    db.ausfuehren("DELETE FROM sitzungen WHERE lower(benutzer)=lower(?)", (konto["benutzername"],))
    print(f"Passwort für „{konto['benutzername']}“ ist neu gesetzt. Du kannst dich jetzt anmelden.")


if __name__ == "__main__":
    main()
