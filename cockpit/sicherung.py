"""
Taegliche Sicherung der Datenbank -- per SQLite-Backup-API, nicht per Dateikopie.

Eine Kopie der Datei waehrend des Schreibens (WAL-Modus!) kann einen halben
Stand sichern; die Backup-API liefert immer einen in sich stimmigen.

Liegt auf DERSELBEN Platte: schuetzt vor Fehlbedienung und kaputten Dateien,
NICHT vor einem Plattenausfall. Fuer die OneDrive-Sicherung des alten Cockpits
muss dieses Verzeichnis dort eingetragen werden (braucht root, siehe STATUS.md).

Aufruf: .venv/bin/python -m cockpit.sicherung     (Zeitgeber vve-cp-r2-sicherung.timer)
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .konfig import DB_DATEI, DATEN

ZIEL = DATEN / "sicherungen"
BEHALTEN = 30


def sichern() -> Path:
    ZIEL.mkdir(parents=True, exist_ok=True)
    datei = ZIEL / f"cockpit-{time.strftime('%Y%m%d-%H%M%S')}.sqlite"
    quelle = sqlite3.connect(str(DB_DATEI))
    ziel = sqlite3.connect(str(datei))
    with ziel:
        quelle.backup(ziel)
    ziel.close()
    quelle.close()
    # Gegenprobe: eine Sicherung, die sich nicht oeffnen laesst, ist keine.
    pruef = sqlite3.connect(str(datei))
    ok = pruef.execute("PRAGMA integrity_check").fetchone()[0]
    pruef.close()
    if ok != "ok":
        raise SystemExit(f"Sicherung {datei} ist beschaedigt: {ok}")
    alle = sorted(ZIEL.glob("cockpit-*.sqlite"))
    for alt in alle[:-BEHALTEN]:
        alt.unlink()
    return datei


if __name__ == "__main__":
    print(f"Gesichert: {sichern()}")
