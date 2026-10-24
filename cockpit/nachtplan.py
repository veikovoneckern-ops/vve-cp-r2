"""
DER NACHTPLAN (23.10.2026) -- was nachts laeuft, wann und warum in dieser Reihenfolge.

Veiko: "optimiere die Dinge, die nachts laufen -- in der Regel arbeite ich zwischen 22 Uhr
und 5 Uhr nicht mit dem Cockpit." Bis dahin waren die Nachtarbeiten einzeln entstanden, jede
mit ihrem eigenen Fenster: Modelle laden ab 23 Uhr, Revision ab 2 Uhr, RSI ab 3 Uhr -- die
Stunden von 22 bis 2 Uhr blieben fast leer, und Daily Tasks liefen um 06:30, also erst, wenn
Veiko schon arbeitet.

Jetzt hintereinander, so dass sich nie zwei Modellarbeiten die Grafikkarten teilen (die
Revision misst Antwortzeiten -- ein zweites Modell daneben verfaelscht sie) und um 5 Uhr
alles fertig ist:

  22:00        Modelle laden (nachtladen.py, nur wenn eingeschaltet) -- nur Leitung, keine Karte
  00:30-03:00  Modell-Revision startet (revision.py); wartet bis 02:00 auf laufende Downloads
  03:00        RSI (rsi.py, Veikos Vorgabe 3-5 Uhr); wartet bis 03:30 auf die Revision
  03:30        Sicherung (sicherung.py): Datenbank lokal, alles verschluesselt nach OneDrive
  04:00        Daily Tasks, neue mit dieser Vorgabe (daily.py) -- die Briefings liegen um 5 bereit
  04:50        Morgens bereit (hier): Talk-Modell laden und Whisper einmal rechnen lassen,
               damit der erste Satz um 5 nicht auf das Laden wartet
  05:00        Downloads pausieren; die Leitung gehoert wieder Veiko
  05:00        Morgenbericht per Mail (tagesbericht.py) -- beschreibt die ganze Nacht

Bis zum 23.10.2026 liefen daneben noch Arbeiten des alten Cockpits (Sicherungen 03:00/03:15,
Stab-Bericht 07:00); sie enden mit dessen Abschaltung. Was davon gebraucht wird, macht diese
Fassung selbst (Sicherung samt Serverstand 03:30, Advisory Board 23:00).
"""
from __future__ import annotations

import asyncio
import datetime
import time
import traceback
from typing import Any
from zoneinfo import ZoneInfo

from . import db

BERLIN = ZoneInfo("Europe/Berlin")
BEREIT_UM = (4, 50)
HALTEN = "3h"     # so lange bleibt das Talk-Modell im Speicher, wenn Talk nicht geoeffnet wird


def _stand() -> dict[str, Any]:
    return db.einstellung("morgen_bereit", {}) or {}


async def morgens_bereit() -> dict[str, Any]:
    from . import gespraech, llm, stimme
    t0 = time.time()
    ergebnis: dict[str, Any] = {"zeit": t0}
    try:
        modell = await llm.talk_modell()
        if modell:
            ergebnis["modell"] = await llm.aufwaermen(modell, gespraech.system_kern(), halten=HALTEN)
    except Exception as e:  # noqa: BLE001
        ergebnis["fehler_modell"] = f"{e.__class__.__name__}: {str(e)[:200]}"
    try:
        ergebnis["whisper"] = await stimme.vorwaermen()
    except Exception as e:  # noqa: BLE001
        ergebnis["fehler_whisper"] = f"{e.__class__.__name__}: {str(e)[:200]}"
    ergebnis["sekunden"] = round(time.time() - t0, 1)
    return ergebnis


async def schleife() -> None:
    await asyncio.sleep(150)
    while True:
        try:
            jetzt = datetime.datetime.now(BERLIN)
            heute = jetzt.date().isoformat()
            if (jetzt.hour, jetzt.minute) >= BEREIT_UM and jetzt.hour < 6 and _stand().get("tag") != heute:
                db.einstellung_setzen("morgen_bereit", {"tag": heute, "laeuft": True})
                e = await morgens_bereit()
                db.einstellung_setzen("morgen_bereit", {"tag": heute, **e})
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(120)


def _wann(t: Any) -> str | None:
    # Deutsche Zeit -- der Server laeuft in UTC, und "00:11" fuer einen Lauf um 02:11 fuehrt in die Irre.
    return datetime.datetime.fromtimestamp(t, BERLIN).strftime("%d.%m. %H:%M") if t else None


def plan() -> list[dict[str, Any]]:
    """Fuer die Settings: der Plan mit dem letzten Lauf je Eintrag -- aus dem Stand, den jedes Modul ohnehin fuehrt."""
    from . import board, nachtladen, revision, rsi, sicherung, stab, tagesbericht
    nl, rv, rs, mb, sich = nachtladen.stand(), revision.stand(), rsi.stand(), _stand(), sicherung.stand()
    tb = tagesbericht.stand()
    bd = board.stand()
    dailys = db.alle("SELECT titel, uhrzeit, aktiv FROM daily ORDER BY uhrzeit")

    def zuletzt(s: dict[str, Any]) -> str:
        if s.get("laeuft"):
            return "läuft gerade"
        if s.get("fehler"):
            return f"zuletzt gescheitert: {str(s['fehler'])[:120]}"
        return f"zuletzt {_wann(s.get('ende'))}: {str(s.get('ergebnis') or '')[:140]}" if s.get("ende") else "noch nicht gelaufen"

    return [
        {"key": "modelle", "schalter": True, "jetzt": True, "zeit": "22:00", "titel": "Neue Modelle laden", "an": nachtladen.an(), "wo": "Team → Modelle",
         "warum": "Nur Leitung, keine Grafikkarte -- läuft parallel zu allem. Um 05:00 wird pausiert.", "zuletzt": zuletzt(nl)},
        {"key": "board", "schalter": False, "jetzt": True, "zeit": "23:00", "titel": "Advisory Board auffrischen", "an": True, "wo": "Advisory Board",
         "warum": "Sechs Advisors je Nacht aus öffentlichen Quellen (eigene Websuche + lokales Modell), älteste zuerst. "
                  "Um 23 Uhr rechnet sonst nichts auf den Karten.",
         "zuletzt": (f"zuletzt {_wann(bd.get('letzterLauf'))}" + (f" -- {bd['letzterFehler'][:100]}" if bd.get("letzterFehler") else ""))
                    if bd.get("letzterLauf") else "noch nicht gelaufen"},
        {"key": "revision", "schalter": False, "jetzt": True, "zeit": "00:30", "titel": "Modell-Revision", "an": stab.stab_aktiv(), "wo": "Team → Optimierung (läuft nur, wenn die Team-Pipeline an ist)",
         "warum": "Misst, ob ein anderes Modell eine Rolle besser macht. Wartet bis 02:00 auf laufende Downloads; startet spätestens 03:00.",
         "zuletzt": zuletzt(rv)},
        {"key": "rsi", "schalter": True, "jetzt": True, "zeit": "03:00", "titel": "RSI -- Verbesserungen aus deinen Gesprächen", "an": rsi.an(), "wo": "Settings → RSI",
         "warum": "Dario sucht in deinen Gesprächen, wo es gehakt hat, und schlägt Verbesserungen vor; umgesetzt wird nur, was du auswählst. Wartet bis 03:30 auf die Revision, damit sich die beiden nicht die Karten teilen.",
         "zuletzt": zuletzt(rs)},
        {"key": "sicherung", "schalter": False, "jetzt": True, "zeit": "03:30", "titel": "Sicherung des Cockpits", "an": True, "wo": "Stack → Sicherungen",
         "warum": "Datenbank lokal; dazu Datenbank, Unterlagen, Medien, Zugangsdaten und der Serverstand verschlüsselt nach OneDrive "
                  + ("(eingerichtet)." if sich.get("eingerichtet") else "-- OneDrive ist noch NICHT eingerichtet, dann nur die Datenbank lokal."),
         "zuletzt": ("läuft gerade" if sich.get("laeuft") else f"zuletzt {_wann(sich.get('zeit'))}: {sich.get('zustand')}"
                     + (f", {sich.get('groesse_mb')} MB" if sich.get("zustand") == "ok" else "") if sich.get("zeit") else "noch nicht gelaufen")},
        {"key": "daily", "schalter": False, "jetzt": False, "zeit": "04:00", "titel": "Daily Tasks", "an": bool([d for d in dailys if d["aktiv"]]), "wo": "Daily Tasks",
         "warum": "Neue Daily Tasks starten um 04:00, damit die Briefings um 5 bereitliegen. "
                  + (("Eingerichtet: " + ", ".join(f"{d['titel']} ({d['uhrzeit']})" for d in dailys)) if dailys else "Noch keiner eingerichtet."),
         "zuletzt": ""},
        {"key": "morgens", "schalter": False, "jetzt": True, "zeit": "04:50", "titel": "Morgens bereit", "an": True, "wo": "",
         "warum": f"Talk-Modell laden und {HALTEN.replace('h', ' Stunden')} halten, Spracherkennung einmal anwerfen -- der erste Satz um 5 wartet nicht aufs Laden.",
         "zuletzt": ("läuft gerade" if mb.get("laeuft") else
                     f"zuletzt {_wann(mb.get('zeit'))}, {mb.get('sekunden')} s" + (" -- mit Fehler" if mb.get("fehler_modell") or mb.get("fehler_whisper") else "")
                     if mb.get("zeit") else "noch nicht gelaufen")},
        {"key": "bericht", "schalter": True, "jetzt": True, "zeit": "05:00", "titel": "Morgenbericht per Mail", "an": tagesbericht.an(), "wo": "Settings → Morgenbericht",
         "warum": f"Was der Stab seit dem letzten Bericht getan hat, an {tagesbericht.empfaenger()}. Nichts zu berichten -- keine Mail.",
         "zuletzt": (f"zuletzt gesendet {_wann(tb.get('zeit'))}: {tb.get('betreff') or ''}" if tb.get("zeit") else "noch nicht gesendet")
                    + (f" -- zuletzt gescheitert: {tb['fehler']}" if tb.get("fehler") else "")},
    ]


# ---------------------------------------------------------------- Schalten und von Hand starten (24.10.2026)
# Veiko: "die hinterlegten Aufgaben fuer die Nacht sollen auch in den Daily Tasks enthalten sein, mit Optionen
# fuer Einstellungen". Die Daily-Tasks-Seite schaltet hierueber -- dieselben Schalter wie an den Stellen, die "wo"
# nennt, keine zweiten. Einen Schalter gibt es nur, wo es einen gibt: Board, Sicherung und "Morgens bereit" laufen
# immer, die Revision haengt an der Team-Pipeline (die schaltet man nicht nebenbei von hier aus ab).
SCHALTER = {"modelle": "modelle_nachts_laden", "rsi": "rsi_aktiv", "bericht": "bericht_aktiv"}


def setzen(key: str, an: bool) -> None:
    if key not in SCHALTER:
        raise ValueError("Diese Nachtaufgabe läuft immer -- sie hat keinen Schalter.")
    db.einstellung_setzen(SCHALTER[key], bool(an))


async def jetzt(key: str) -> str:
    """Startet eine Nachtaufgabe ausserhalb ihrer Zeit. Rueckgabe: ein Satz fuer die Meldung."""
    from . import board, nachtladen, revision, rsi, tagesbericht
    if key == "modelle":
        if not nachtladen.starten(True):
            raise ValueError("Das Laden läuft schon.")
        return "Neue Modelle werden geladen."
    if key == "board":
        if board.LAUF["aktiv"]:
            raise ValueError("Das Board wird gerade aufgefrischt.")
        asyncio.create_task(board.auffrischen(alle=False, nur_id=""))
        return "Das Advisory Board wird aufgefrischt."
    if key == "revision":
        if not revision.starten(True):
            raise ValueError("Die Revision läuft schon.")
        return "Die Modell-Revision misst jetzt."
    if key == "rsi":
        if not rsi.starten(von_hand=True):
            raise ValueError("RSI läuft schon.")
        return "Dario sieht deine Gespräche durch."
    if key == "sicherung":
        p = await asyncio.create_subprocess_exec("systemctl", "--user", "start", "--no-block", "vve-cp-r2-sicherung.service",
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, fehler = await p.communicate()
        if p.returncode:
            raise ValueError(f"Konnte die Sicherung nicht starten: {fehler.decode(errors='replace')[:300]}")
        return "Die Sicherung läuft."
    if key == "morgens":
        asyncio.create_task(morgens_bereit())
        return "Talk-Modell und Spracherkennung werden geladen."
    if key == "bericht":
        r = await tagesbericht.schicken(erzwingen=True)
        return "Morgenbericht verschickt." if r.get("gesendet", True) else str(r.get("grund") or "Nichts zu berichten.")
    raise ValueError("Unbekannte Nachtaufgabe.")


def briefing() -> list[dict[str, Any]]:
    """Fuers Briefing: was heute Nacht gelaufen ist, je Aufgabe eine Zeile. Was gescheitert ist, steht oben."""
    zeilen = []
    for p in plan():
        if p["key"] == "daily" or not p["an"]:
            continue
        z = p.get("zuletzt") or ""
        zeilen.append({"key": p["key"], "zeit": p["zeit"], "titel": p["titel"], "text": z,
                       "problem": "gescheitert" in z or "Fehler" in z or "NICHT eingerichtet" in p.get("warum", "")})
    return sorted(zeilen, key=lambda x: not x["problem"])
