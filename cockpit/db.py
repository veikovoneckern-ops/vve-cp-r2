"""
DIE DATENHALTUNG -- eine SQLite-Datei statt eines ganzen Zustands als JSON.

Warum (Befund B5 im Konzept): Im alten Cockpit schickte der Browser bei jeder
Aenderung den GESAMTEN Zustand, und wer zuletzt schrieb, gewann. Daraus kamen
Konflikte zwischen Geraeten, die Positivliste in migrate(), das Verbot fuer
die Pipeline, den Zustand zu schreiben, und verlorene Gespraeche.

Hier gibt es genau einen Schreiber (dieses Backend), jede Aenderung betrifft
eine Zeile, und alles, was der Stab selbst aendert, steht im Protokoll und
laesst sich zuruecknehmen.

SQLite ist in Python eingebaut -- keine neue Abhaengigkeit. WAL-Modus, damit
Lesen nicht auf Schreiben wartet.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from typing import Any, Iterable

from .konfig import DB_DATEI

_lock = threading.RLock()
_con = sqlite3.connect(str(DB_DATEI), check_same_thread=False, isolation_level=None)
_con.row_factory = sqlite3.Row
_con.execute("PRAGMA journal_mode=WAL")
_con.execute("PRAGMA foreign_keys=OFF")
_con.execute("PRAGMA busy_timeout=5000")

SCHEMA = """
CREATE TABLE IF NOT EXISTS projekte (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, farbe TEXT, status TEXT DEFAULT 'aktiv',
  start TEXT, ende TEXT, ziel TEXT, eltern_id TEXT, leitung TEXT,
  fruehere_namen TEXT DEFAULT '[]', sortierung INTEGER DEFAULT 0,
  erstellt REAL, geaendert REAL, quelle TEXT DEFAULT 'du'
);
CREATE TABLE IF NOT EXISTS aufgaben (
  id TEXT PRIMARY KEY, titel TEXT NOT NULL, projekt_id TEXT, status TEXT DEFAULT 'offen',
  prio INTEGER DEFAULT 2, faellig TEXT, notiz TEXT DEFAULT '', quelle TEXT DEFAULT 'du',
  vorgang_id TEXT, notiz_id TEXT, erstellt REAL, geaendert REAL, archiviert INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS notizen (
  id TEXT PRIMARY KEY, titel TEXT, datum TEXT, text TEXT, kurz TEXT DEFAULT '',
  quelle TEXT DEFAULT 'eingabe', projekt_id TEXT, plaud_id TEXT, erstellt REAL
);
CREATE INDEX IF NOT EXISTS notizen_plaud ON notizen(plaud_id);
CREATE TABLE IF NOT EXISTS vorgaenge (
  id TEXT PRIMARY KEY, titel TEXT, stand TEXT DEFAULT 'neu', notiz_id TEXT, projekt_id TEXT,
  projekt_vorschlag TEXT, einordnung TEXT DEFAULT '', quelle TEXT DEFAULT 'plaud',
  erstellt REAL, geaendert REAL, alt_id TEXT, auftrag TEXT, versuche INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ereignisse (
  id INTEGER PRIMARY KEY AUTOINCREMENT, vorgang_id TEXT, zeit REAL, wer TEXT, art TEXT,
  text TEXT DEFAULT '', daten TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ereignisse_vg ON ereignisse(vorgang_id);
CREATE TABLE IF NOT EXISTS entscheidungen (
  id TEXT PRIMARY KEY, vorgang_id TEXT, art TEXT, frage TEXT, daten TEXT DEFAULT '{}',
  wer TEXT, stand TEXT DEFAULT 'offen', antwort TEXT, erstellt REAL, erledigt REAL
);
CREATE TABLE IF NOT EXISTS ergebnisse (
  id TEXT PRIMARY KEY, vorgang_id TEXT, projekt_id TEXT, titel TEXT, form TEXT, inhalt TEXT,
  rolle TEXT, modell TEXT, quellen TEXT DEFAULT '[]', pruefung TEXT DEFAULT '{}',
  ansicht INTEGER DEFAULT 0, erstellt REAL
);
CREATE TABLE IF NOT EXISTS gedaechtnis (
  id TEXT PRIMARY KEY, art TEXT, begriff TEXT, bedeutung TEXT, bestaetigt INTEGER DEFAULT 1,
  quelle TEXT, erstellt REAL
);
CREATE TABLE IF NOT EXISTS protokoll (
  id INTEGER PRIMARY KEY AUTOINCREMENT, zeit REAL, wer TEXT, aktion TEXT, tabelle TEXT,
  datensatz_id TEXT, vorher TEXT, nachher TEXT, vorgang_id TEXT, rueckgaengig INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS gespraeche (
  id TEXT PRIMARY KEY, art TEXT, titel TEXT, kontext TEXT DEFAULT '{}', erstellt REAL, geaendert REAL
);
CREATE TABLE IF NOT EXISTS nachrichten (
  id INTEGER PRIMARY KEY AUTOINCREMENT, gespraech_id TEXT, rolle TEXT, text TEXT,
  daten TEXT DEFAULT '{}', zeit REAL
);
CREATE INDEX IF NOT EXISTS nachrichten_g ON nachrichten(gespraech_id);
CREATE TABLE IF NOT EXISTS team (
  id TEXT PRIMARY KEY, name TEXT, titel TEXT, kurz TEXT, auftrag TEXT, modell TEXT,
  aktiv INTEGER DEFAULT 1, art TEXT, reihenfolge INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS dateien (
  id TEXT PRIMARY KEY, name TEXT, typ TEXT, groesse INTEGER, pfad TEXT, text TEXT,
  projekt_id TEXT, erstellt REAL
);
CREATE TABLE IF NOT EXISTS sitzungen (token TEXT PRIMARY KEY, benutzer TEXT, erstellt REAL);
CREATE TABLE IF NOT EXISTS einstellungen (schluessel TEXT PRIMARY KEY, wert TEXT);
"""

with _lock:
    _con.executescript(SCHEMA)

# Spalten, die nach dem ersten Start dazukamen. CREATE TABLE IF NOT EXISTS
# fasst eine bestehende Tabelle nicht an -- deshalb hier einzeln nachruesten.
NACHRUESTEN = [
    # Struktur und Zeitplan der Projektansicht (01.10.2026): Unteraufgaben,
    # Reihenfolge per Ziehen, Beginn fuer den Balken im Zeitplan.
    ("aufgaben", "eltern_id", "TEXT"),
    ("aufgaben", "sortierung", "INTEGER DEFAULT 0"),
    ("aufgaben", "start", "TEXT"),
]
with _lock:
    for _tab, _spalte, _typ in NACHRUESTEN:
        if _spalte not in {r[1] for r in _con.execute(f"PRAGMA table_info({_tab})")}:
            _con.execute(f"ALTER TABLE {_tab} ADD COLUMN {_spalte} {_typ}")


def jetzt() -> float:
    return time.time()


def neue_id(vorsatz: str) -> str:
    return vorsatz + secrets.token_hex(5)


def _zeile(r: sqlite3.Row | None) -> dict[str, Any] | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("fruehere_namen", "daten", "quellen", "pruefung", "kontext", "vorher", "nachher"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except (ValueError, TypeError):
                pass
    return d


def alle(sql: str, args: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with _lock:
        return [_zeile(r) for r in _con.execute(sql, tuple(args)).fetchall()]  # type: ignore[misc]


def eine(sql: str, args: Iterable[Any] = ()) -> dict[str, Any] | None:
    with _lock:
        return _zeile(_con.execute(sql, tuple(args)).fetchone())


def wert(sql: str, args: Iterable[Any] = ()) -> Any:
    with _lock:
        r = _con.execute(sql, tuple(args)).fetchone()
    return r[0] if r else None


def ausfuehren(sql: str, args: Iterable[Any] = ()) -> int:
    with _lock:
        cur = _con.execute(sql, tuple(args))
        return cur.lastrowid or cur.rowcount


def _json(v: Any) -> Any:
    return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v


def einfuegen(tabelle: str, werte: dict[str, Any], ersetzen: bool = False) -> None:
    spalten = list(werte.keys())
    sql = (f"INSERT {'OR REPLACE ' if ersetzen else ''}INTO {tabelle} ({','.join(spalten)}) "
           f"VALUES ({','.join('?' for _ in spalten)})")
    ausfuehren(sql, [_json(werte[s]) for s in spalten])


def holen(tabelle: str, did: str) -> dict[str, Any] | None:
    return eine(f"SELECT * FROM {tabelle} WHERE id=?", (did,))


def protokollieren(wer: str, aktion: str, tabelle: str, did: str, vorher: Any, nachher: Any,
                   vorgang_id: str | None = None) -> int:
    return ausfuehren(
        "INSERT INTO protokoll (zeit,wer,aktion,tabelle,datensatz_id,vorher,nachher,vorgang_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (jetzt(), wer, aktion, tabelle, did, json.dumps(vorher, ensure_ascii=False),
         json.dumps(nachher, ensure_ascii=False), vorgang_id))


def anlegen(tabelle: str, werte: dict[str, Any], wer: str = "du", vorgang_id: str | None = None,
            aktion: str = "angelegt") -> dict[str, Any]:
    """Neue Zeile + Protokolleintrag. Was der Stab anlegt, laesst sich so zuruecknehmen."""
    einfuegen(tabelle, werte)
    neu = holen(tabelle, werte["id"])
    protokollieren(wer, aktion, tabelle, werte["id"], None, neu, vorgang_id)
    return neu or werte


def aendern(tabelle: str, did: str, werte: dict[str, Any], wer: str = "du",
            vorgang_id: str | None = None, aktion: str = "geaendert") -> dict[str, Any] | None:
    vorher = holen(tabelle, did)
    if vorher is None:
        return None
    werte = {k: v for k, v in werte.items() if k != "id"}
    if not werte:
        return vorher
    sets = ",".join(f"{k}=?" for k in werte)
    ausfuehren(f"UPDATE {tabelle} SET {sets} WHERE id=?", [_json(v) for v in werte.values()] + [did])
    nachher = holen(tabelle, did)
    protokollieren(wer, aktion, tabelle, did, vorher, nachher, vorgang_id)
    return nachher


def loeschen(tabelle: str, did: str, wer: str = "du") -> bool:
    vorher = holen(tabelle, did)
    if vorher is None:
        return False
    ausfuehren(f"DELETE FROM {tabelle} WHERE id=?", (did,))
    protokollieren(wer, "geloescht", tabelle, did, vorher, None)
    return True


def rueckgaengig(protokoll_id: int) -> dict[str, Any]:
    """Nimmt EINEN Protokolleintrag zurueck. Nur fuer anlegen/aendern/loeschen
    einzelner Zeilen -- mehr braucht es nicht, und mehr waere schwer zu erklaeren."""
    p = eine("SELECT * FROM protokoll WHERE id=?", (protokoll_id,))
    if not p:
        return {"ok": False, "grund": "Eintrag nicht gefunden"}
    if p["rueckgaengig"]:
        return {"ok": False, "grund": "Schon zurueckgenommen"}
    tab, did, vorher = p["tabelle"], p["datensatz_id"], p["vorher"]
    if vorher is None:
        ausfuehren(f"DELETE FROM {tab} WHERE id=?", (did,))
    else:
        einfuegen(tab, {k: v for k, v in vorher.items()}, ersetzen=True)
    ausfuehren("UPDATE protokoll SET rueckgaengig=1 WHERE id=?", (protokoll_id,))
    return {"ok": True}


def einstellung(schluessel: str, vorgabe: Any = None) -> Any:
    r = wert("SELECT wert FROM einstellungen WHERE schluessel=?", (schluessel,))
    if r is None:
        return vorgabe
    try:
        return json.loads(r)
    except (ValueError, TypeError):
        return vorgabe


def einstellung_setzen(schluessel: str, w: Any) -> None:
    ausfuehren("INSERT OR REPLACE INTO einstellungen (schluessel,wert) VALUES (?,?)",
               (schluessel, json.dumps(w, ensure_ascii=False)))


def ereignis(vorgang_id: str, wer: str, art: str, text: str = "", daten: dict | None = None) -> None:
    ausfuehren("INSERT INTO ereignisse (vorgang_id,zeit,wer,art,text,daten) VALUES (?,?,?,?,?,?)",
               (vorgang_id, jetzt(), wer, art, text, json.dumps(daten or {}, ensure_ascii=False)))
    ausfuehren("UPDATE vorgaenge SET geaendert=? WHERE id=?", (jetzt(), vorgang_id))
