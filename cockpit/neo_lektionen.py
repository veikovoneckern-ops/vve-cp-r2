"""
NEOS GEDAECHTNIS -- was Dario ihm beigebracht hat (24.10.2026).

Veiko: "Wenn Dario sagt, hier sind noch Fehler drin, dann soll er Neo das beibringen. Dann muss irgendeine Art
von Gedaechtnis im Cockpit entstehen fuer Neo: da hast du einen Fehler gemacht, das musst du grundsaetzlich so
und so machen."

So entsteht eine Lektion: lehnt Dario eine Aenderung von Neo ab (neo_freigabe.pruefen), formuliert er neben den
Maengeln -- die nur fuer diesen Auftrag gelten -- eine ALLGEMEINE Regel, wenn der Fehler eine Art ist, die Neo
wieder machen koennte ("Benutze nur Namen, die im Code definiert sind -- lies vorher nach"). Die Regel landet
hier und steht ab dann in JEDEM Auftrag an Neo (neo.system_text), nicht nur in RSI.

Kein Wachsen ohne Ende: hoechstens MAX Lektionen; eine Regel, die fast wortgleich schon da ist, zaehlt nur das
bestehende "wie oft" hoch. Veiko sieht und loescht sie auf der Seite RSI ("Was Neo gelernt hat") -- ein Gedaechtnis,
das man nicht korrigieren kann, waere eines, dem man irgendwann nicht mehr traut.
"""
from __future__ import annotations

import re
import time
from typing import Any

from . import db

SCHLUESSEL = "neo_lektionen"
MAX = 40


def liste() -> list[dict[str, Any]]:
    return db.einstellung(SCHLUESSEL, []) or []


def _woerter(t: str) -> set[str]:
    return set(re.findall(r"[a-zäöüß0-9_]{4,}", (t or "").lower()))


def hinzufuegen(regel: str, anlass: str = "") -> dict[str, Any] | None:
    regel = re.sub(r"\s+", " ", str(regel or "")).strip()
    if len(regel) < 15:
        return None
    alle = liste()
    w = _woerter(regel)
    for l in alle:
        wl = _woerter(l["regel"])
        if w and len(w & wl) / max(1, len(w | wl)) >= 0.6:
            l["wie_oft"] = int(l.get("wie_oft") or 1) + 1
            l["zuletzt"] = time.time()
            db.einstellung_setzen(SCHLUESSEL, alle)
            return l
    neu = {"id": db.neue_id("l"), "regel": regel[:500], "anlass": str(anlass or "")[:300], "zeit": time.time(),
           "zuletzt": time.time(), "wie_oft": 1}
    alle = [neu] + alle
    # Uebervoll: die am seltensten bestaetigten und aeltesten fallen heraus.
    if len(alle) > MAX:
        alle = sorted(alle, key=lambda l: (int(l.get("wie_oft") or 1), l.get("zuletzt") or 0), reverse=True)[:MAX]
    db.einstellung_setzen(SCHLUESSEL, alle)
    return neu


def loeschen(lid: str) -> bool:
    alle = liste()
    rest = [l for l in alle if l["id"] != lid]
    db.einstellung_setzen(SCHLUESSEL, rest)
    return len(rest) < len(alle)


def text() -> str:
    """Fuer Neos Anweisung: die Regeln, die Dario ihm beigebracht hat -- die oefter bestaetigten zuerst."""
    alle = sorted(liste(), key=lambda l: (int(l.get("wie_oft") or 1), l.get("zuletzt") or 0), reverse=True)
    if not alle:
        return ""
    return ("WAS DARIO DIR BEIGEBRACHT HAT -- Regeln aus Fehlern, die du schon einmal gemacht hast. Halte dich IMMER daran:\n"
            + "\n".join(f"- {l['regel']}" + (f" ({l['wie_oft']}× nötig gewesen)" if int(l.get("wie_oft") or 1) > 1 else "") for l in alle))
