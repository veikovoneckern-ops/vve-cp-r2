"""
NACHTS NEUE MODELLE LADEN -- damit die Revision etwas zu messen hat.

Veiko (21.10.2026): "eine Funktion, die ich unter Settings an- und ausschalten
kann: ueber Nacht, von 23 bis morgens um 5 Uhr, werden neue verfuegbare Modelle
runtergeladen, durch das Cockpit getestet, ob sie besser fuer irgendetwas passen,
und mir dann noch bessere Vorschlaege gemacht."

Bis dahin mass die Revision (revision.py, 02--05 Uhr) nur, was installiert ist;
jeder Download war ein Knopf. Ein neues Modell wurde also erst gemessen, nachdem
Veiko es von Hand geladen hatte -- und dafuer musste er wissen, dass es lohnt.
Jetzt schliesst sich der Kreis ohne ihn:

  22:00  dieses Modul laedt bis zu zwei Ladevorschlaege (revision.laden_vorschlaege)
  00:30  die Revision misst sie gegen das, was heute rechnet (sie nimmt in den
         letzten 14 Tagen Geladenes zuerst) -- sie wartet auf die Downloads, bis 02:00
  morgens  stehen gemessene Vorschlaege in der Team-Uebersicht und im Briefing

Grenzen, die Absicht sind:
- **Nur geladen, nie umgestellt und nie geloescht.** Ob ein Modell eine Rolle
  uebernimmt oder weg kann, entscheidet Veiko mit einem Klick -- wie bisher.
- **Nur, was gut sein koennte:** kein Modell mit Ruf "schwach"/"durchwachsen" im
  Netz (ruf.py), keines, das nur mit Auslagerung in den Arbeitsspeicher liefe.
- **Hoechstens zwei Modelle und 50 GB je Nacht**, und immer 100 GB frei auf der
  Platte. Die Leitung des Servers schafft etwa 2 MB/s -- mehr als eine Nacht
  waere es sonst nicht.
- **Um 05:00 wird pausiert.** Ollama behaelt die geladenen Teile; die naechste
  Nacht setzt dort fort. Tagsueber gehoert die Leitung Veiko.
"""
from __future__ import annotations

import asyncio
import datetime
import shutil
import time
import traceback
from typing import Any

from . import db, llm, modellkatalog, revision, ruf

SCHALTER = "modelle_nachts_laden"
STAND = "nachtladen_stand"
VON, BIS = 22, 5                 # deutsche Zeit; ueber Mitternacht (Nachtplan 23.10.2026: Veiko arbeitet 22--05 nicht)
MAX_JE_NACHT = 2
MAX_GB_JE_NACHT = 50
PLATTE_FREI_GB = 100
ABLAGE = "/usr/share/ollama"
_lauf: asyncio.Task | None = None


def an() -> bool:
    return bool(db.einstellung(SCHALTER, False))


def stand() -> dict[str, Any]:
    return db.einstellung(STAND, {}) or {}


def _setzen(**werte: Any) -> None:
    s = stand()
    s.update(werte)
    db.einstellung_setzen(STAND, s)


def laeuft() -> bool:
    return bool(_lauf and not _lauf.done())


def im_fenster(jetzt: datetime.datetime) -> bool:
    return jetzt.hour >= VON or jetzt.hour < BIS


def nacht_von(jetzt: datetime.datetime) -> str:
    """Die Nacht vom 21. auf den 22. heisst "2026-10-21" -- auch um 03:00 am 22."""
    tag = jetzt.date() if jetzt.hour >= VON else jetzt.date() - datetime.timedelta(days=1)
    return tag.isoformat()


def _platte_frei_gb() -> float | None:
    try:
        return shutil.disk_usage(ABLAGE).free / 1e9
    except OSError:
        return None


async def auswahl() -> tuple[list[dict[str, Any]], list[str]]:
    """Was diese Nacht geladen wird, und warum anderes nicht (fuer den Stand)."""
    from . import systeminfo
    s = await systeminfo.status()
    vram = systeminfo._vram_gesamt(s)
    inst = modellkatalog.lokal_gb()
    neu = await modellkatalog.neu_bei_ollama(False, vram)
    modellkatalog.einordnen(neu, inst, db.alle("SELECT id, name, titel, art, modell FROM team WHERE aktiv=1"),
                            {"arbeit": llm.vorgabe("arbeit"), "talk": llm.vorgabe("talk")})
    gescheitert = set(stand().get("gescheitert") or [])
    offen_vorher = list(stand().get("offen") or [])
    ausgelassen: list[str] = []
    kandidaten: list[dict[str, Any]] = []
    for v in revision.laden_vorschlaege(neu):
        name = v["name"]
        if name in inst:
            continue
        if name in gescheitert:
            ausgelassen.append(f"{name}: ist schon einmal gescheitert")
            continue
        r = ruf.holen(name) or {}
        if r.get("urteil") in ("schwach", "durchwachsen"):
            ausgelassen.append(f"{name}: im Netz „{r['urteil']}“")
            continue
        if "auslager" in (v.get("passt") or "").lower():
            ausgelassen.append(f"{name}: liefe nur mit Auslagerung in den Arbeitsspeicher")
            continue
        kandidaten.append({**v, "ruf": r.get("urteil")})
    # Angefangenes zuerst, dann was im Netz gut dasteht, dann Nachfolger.
    rang = {"sehr gut": 0, "gut": 1}
    kandidaten.sort(key=lambda v: (v["name"] not in offen_vorher, rang.get(v.get("ruf") or "", 2), not v.get("neuer")))
    frei = _platte_frei_gb()
    gewaehlt, summe = [], 0.0
    for v in kandidaten:
        gb = float(v.get("gb") or 0)
        if len(gewaehlt) >= MAX_JE_NACHT:
            break
        if summe + gb > MAX_GB_JE_NACHT:
            ausgelassen.append(f"{v['name']}: zu groß für eine Nacht ({gb:.0f} GB)")
            continue
        if frei is not None and frei - summe - gb < PLATTE_FREI_GB:
            ausgelassen.append(f"{v['name']}: zu wenig Platz auf der Platte")
            continue
        gewaehlt.append(v)
        summe += gb
    return gewaehlt, ausgelassen


async def lauf(von_hand: bool = False) -> dict[str, Any]:
    _setzen(laeuft=True, start=time.time(), ende=None, fehler=None, von_hand=von_hand, modelle=[], schritt="sucht neue Modelle")
    try:
        gewaehlt, ausgelassen = await auswahl()
        _setzen(geplant=[v["name"] for v in gewaehlt], ausgelassen=ausgelassen[:8])
        if not gewaehlt:
            _setzen(laeuft=False, ende=time.time(), schritt=None,
                    ergebnis="Nichts Neues, das sich zu laden lohnt." + (f" ({len(ausgelassen)} ausgelassen)" if ausgelassen else ""))
            return stand()
        fertig, offen = [], []
        for v in gewaehlt:
            name = v["name"]
            _setzen(schritt=f"lädt {name} ({v.get('gb')} GB)")
            modellkatalog.laden_starten(name)
            while (modellkatalog.LADEN.get(name) or {}).get("stand") == "laeuft":
                await asyncio.sleep(30)
                if not von_hand and not im_fenster(datetime.datetime.now(revision.BERLIN)):
                    modellkatalog.laden_steuern(name, "pausieren")
                    break
            j = modellkatalog.LADEN.get(name) or {}
            if j.get("stand") == "fertig":
                fertig.append(name)
                modellkatalog.LADEN.pop(name, None)   # Current Actions zeigt sonst einen erledigten Download
            elif j.get("stand") == "pausiert":
                offen.append(name)
                break
            else:
                _setzen(gescheitert=list(dict.fromkeys((stand().get("gescheitert") or []) + [name]))[-20:])
        _setzen(laeuft=False, ende=time.time(), schritt=None, modelle=fertig, offen=offen,
                ergebnis=(f"Geladen: {', '.join(fertig)}. Die Revision misst sie heute Nacht." if fertig else "Nichts fertig geladen.")
                + (f" Um 5 Uhr pausiert: {', '.join(offen)} -- geht nächste Nacht weiter." if offen else ""))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        _setzen(laeuft=False, ende=time.time(), schritt=None, fehler=f"{e.__class__.__name__}: {str(e)[:300]}")
    return stand()


def starten(von_hand: bool = True) -> bool:
    global _lauf
    if laeuft():
        return False
    _lauf = asyncio.create_task(lauf(von_hand))
    return True


async def schleife() -> None:
    """Einmal je Nacht, 22--05 Uhr deutscher Zeit, wenn der Schalter an ist."""
    await asyncio.sleep(90)
    while True:
        try:
            jetzt = datetime.datetime.now(revision.BERLIN)
            nacht = nacht_von(jetzt)
            if an() and im_fenster(jetzt) and stand().get("nacht") != nacht and not laeuft():
                _setzen(nacht=nacht)
                starten(von_hand=False)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(300)
