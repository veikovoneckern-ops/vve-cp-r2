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

Dazu Dinge des alten Cockpits auf demselben Server (systemd, nicht in diesem Repo):
03:00/03:15 die Sicherungen nach OneDrive (Platte und Leitung), 04:30 das Auffrischen des
Advisory Boards (lokales Modell -- deshalb liegen RSI und Daily Tasks davor), 07:00 der
Stab-Bericht per Mail.
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
    from . import nachtladen, revision, rsi, sicherung, stab
    nl, rv, rs, mb, sich = nachtladen.stand(), revision.stand(), rsi.stand(), _stand(), sicherung.stand()
    dailys = db.alle("SELECT titel, uhrzeit, aktiv FROM daily ORDER BY uhrzeit")

    def zuletzt(s: dict[str, Any]) -> str:
        if s.get("laeuft"):
            return "läuft gerade"
        if s.get("fehler"):
            return f"zuletzt gescheitert: {str(s['fehler'])[:120]}"
        return f"zuletzt {_wann(s.get('ende'))}: {str(s.get('ergebnis') or '')[:140]}" if s.get("ende") else "noch nicht gelaufen"

    return [
        {"zeit": "22:00", "titel": "Neue Modelle laden", "an": nachtladen.an(), "wo": "Team → Modelle",
         "warum": "Nur Leitung, keine Grafikkarte -- läuft parallel zu allem. Um 05:00 wird pausiert.", "zuletzt": zuletzt(nl)},
        {"zeit": "00:30", "titel": "Modell-Revision", "an": stab.stab_aktiv(), "wo": "Team → Optimierung (läuft nur, wenn die Team-Pipeline an ist)",
         "warum": "Misst, ob ein anderes Modell eine Rolle besser macht. Wartet bis 02:00 auf laufende Downloads; startet spätestens 03:00.",
         "zuletzt": zuletzt(rv)},
        {"zeit": "03:00", "titel": "RSI -- Verbesserungen aus deinen Gesprächen", "an": rsi.an(), "wo": "RSI",
         "warum": "Neo schlägt vor, Dario prüft. Wartet bis 03:30 auf die Revision, damit sich die beiden nicht die Karten teilen.",
         "zuletzt": zuletzt(rs)},
        {"zeit": "03:30", "titel": "Sicherung des Cockpits", "an": True, "wo": "Stack → Sicherungen",
         "warum": "Datenbank lokal; dazu Datenbank, Unterlagen, Medien und Zugangsdaten verschlüsselt nach OneDrive "
                  + ("(eingerichtet)." if sich.get("eingerichtet") else "-- OneDrive ist noch NICHT eingerichtet, dann nur die Datenbank lokal."),
         "zuletzt": ("läuft gerade" if sich.get("laeuft") else f"zuletzt {_wann(sich.get('zeit'))}: {sich.get('zustand')}"
                     + (f", {sich.get('groesse_mb')} MB" if sich.get("zustand") == "ok" else "") if sich.get("zeit") else "noch nicht gelaufen")},
        {"zeit": "04:00", "titel": "Daily Tasks", "an": bool([d for d in dailys if d["aktiv"]]), "wo": "Daily Tasks",
         "warum": "Neue Daily Tasks starten um 04:00, damit die Briefings um 5 bereitliegen. "
                  + (("Eingerichtet: " + ", ".join(f"{d['titel']} ({d['uhrzeit']})" for d in dailys)) if dailys else "Noch keiner eingerichtet."),
         "zuletzt": ""},
        {"zeit": "04:50", "titel": "Morgens bereit", "an": True, "wo": "",
         "warum": f"Talk-Modell laden und {HALTEN.replace('h', ' Stunden')} halten, Spracherkennung einmal anwerfen -- der erste Satz um 5 wartet nicht aufs Laden.",
         "zuletzt": ("läuft gerade" if mb.get("laeuft") else
                     f"zuletzt {_wann(mb.get('zeit'))}, {mb.get('sekunden')} s" + (" -- mit Fehler" if mb.get("fehler_modell") or mb.get("fehler_whisper") else "")
                     if mb.get("zeit") else "noch nicht gelaufen")},
        {"zeit": "03:00 · 03:15 · 04:30 · 07:00", "titel": "Altes Cockpit auf demselben Server", "an": True, "wo": "",
         "warum": "Sicherungen nach OneDrive (03:00, 03:15), Advisory Board auffrischen (04:30, lokales Modell -- deshalb liegt "
                  "alles Rechnende davor), Stab-Bericht per Mail (07:00).", "zuletzt": ""},
    ]
