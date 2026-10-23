"""
RSI-SERIE -- mehrere Verbesserungen auf einmal umsetzen lassen, ohne Widersprueche (23.10.2026).

Veiko: "Ich moechte bei mehreren Punkten per Klickbox auswaehlen, welche bearbeitet und welche
verworfen werden, und dann eine Art Start Bearbeitung haben. Es muss darauf geachtet werden, dass es
nicht zu Widerspruechen kommt -- wenn in einem Chatverlauf etwas aufgedeckt wird und in einem anderen
etwas Widerspruechliches, muss das vorher gut geprueft werden, damit sich nicht gegenlaeufige
Entwicklungsaufwaende ergeben. Die Ergebnisse -- wenn das Code ist, verstehe ich es eh nicht -- sollen
wirklich umgesetzt werden, und dann soll mir gesagt werden: abgeschlossen, das neue Release ist da.
Wenn etwas nicht funktioniert, muss es zurueckgenommen werden koennen. Und das alles auch ueber Talk."

Ablauf einer Serie (eine zur Zeit, Stand in der Einstellung "rsi_serie"):
  1. AUSWAHL: Veiko markiert Punkte als "umsetzen" oder "verwerfen" (Seite RSI oder Talk).
     Verworfenes ist sofort verworfen.
  2. WIDERSPRUCHSPRUEFUNG durch Dario (kostet wenige Cent; geschaetzt und genannt, bevor Veiko
     waehlt): alle ausgewaehlten Punkte ZUSAMMEN, dazu die zuletzt umgesetzten -- widersprechen sich
     zwei, ueberschneiden sie sich in denselben Stellen, haengt einer vom anderen ab? Ergebnis: eine
     Reihenfolge, je Punkt ein Hinweis fuer Neo, was er wegen der anderen beachten muss, und Punkte,
     die zurueckgestellt werden, bis Veiko entschieden hat (z. B. weil sie einem anderen widersprechen).
     Ist Dario nicht erreichbar, startet NICHTS -- ohne Pruefung keine Serie, so wollte Veiko es.
  3. START (Veikos Klick oder sein Ja in Talk): Neo setzt die Punkte NACHEINANDER um, jeder in seinem
     eigenen Gespraech, jeder mit Darios Freigabe vor dem Einspielen (neo_freigabe.py, wie immer).
     Nacheinander, weil der zweite Punkt den Code sehen soll, wie ihn der erste hinterlassen hat --
     parallel geaenderte Dateien waeren genau die gegenlaeufige Arbeit, die Veiko vermeiden will.
     Kein Neustart zwischen den Punkten (er wuerde den naechsten abbrechen), einer am Ende.
  4. RELEASE: am Ende eine Meldung (Seite RSI, Talk-Lage, Morgenbericht): was umgesetzt ist, was
     nicht und warum. Jeder umgesetzte Punkt ist ein eigener Commit.
  5. ZURUECKNEHMEN: ein ganzes Release oder ein einzelner Punkt -- git revert der Commits (neueste
     zuerst), Syntaxpruefung, Push, Neustart. Geht ein revert nicht glatt (spaetere Aenderung an
     derselben Stelle), wird NICHTS veraendert und das gesagt.

Was ein Neustart mitten in der Serie anrichtet (etwa eine Auslieferung): der laufende Punkt ist
verloren (Neo laeuft in diesem Dienst). Beim Start wird er als "unterbrochen" vermerkt, die Serie
laeuft mit dem naechsten weiter -- statt fuer immer auf "laeuft" zu stehen.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import time
import traceback
from typing import Any

from . import db, llm
from .konfig import WURZEL

ZUSTAND = "rsi_serie"
RELEASES = "rsi_releases"
MAX_JE_PUNKT = 75 * 60          # so lange darf Neo an einem Punkt arbeiten, dann wird abgebrochen
OFFEN = ("neu", "geprueft", "plan")

_task: asyncio.Task | None = None


# ---------------------------------------------------------------- Zustand
def stand() -> dict[str, Any]:
    return db.einstellung(ZUSTAND, {}) or {}


def _setzen(**w: Any) -> dict[str, Any]:
    s = stand()
    s.update(w)
    db.einstellung_setzen(ZUSTAND, s)
    return s


def releases() -> list[dict[str, Any]]:
    return db.einstellung(RELEASES, []) or []


def wann(t: float) -> str:
    """Deutsche Zeit -- der Server laeuft in UTC, und "15:52" fuer ein Release um 17:52 fuehrt in die Irre."""
    import datetime
    from zoneinfo import ZoneInfo
    return datetime.datetime.fromtimestamp(t, ZoneInfo("Europe/Berlin")).strftime("%d.%m. %H:%M")


def laeuft() -> bool:
    return stand().get("stand") in ("pruefung", "laeuft")


def _rsi(rid: str) -> dict[str, Any] | None:
    r = db.holen("rsi", rid)
    if r and not isinstance(r.get("daten"), dict):
        try:
            r["daten"] = json.loads(r["daten"] or "{}")
        except (TypeError, ValueError):
            r["daten"] = {}
    return r


def _stand_rsi(rid: str, stand_: str, **zusatz: Any) -> None:
    r = _rsi(rid)
    if not r:
        return
    d = r["daten"]
    if zusatz:
        d["serie"] = {**(d.get("serie") or {}), **zusatz}
    db.ausfuehren("UPDATE rsi SET stand=?, daten=?, geaendert=? WHERE id=?", (stand_, json.dumps(d, ensure_ascii=False), time.time(), rid))


def _git(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=WURZEL, capture_output=True, text=True, timeout=timeout)


def _kopf() -> str:
    return _git("rev-parse", "--short", "HEAD").stdout.strip()


# ---------------------------------------------------------------- 1.+2. Auswahl und Widerspruchspruefung
PRUEF_SYSTEM = (
    "Du bist Dario, unabhängiger Prüfer für das VvE Cockpit (FastAPI-Backend unter cockpit/, Preact-Frontend unter frontend/js/, "
    "Talk = Sprachdialog, Neo = lokaler Coding-Agent, der die Punkte gleich NACHEINANDER umsetzt). Veiko hat mehrere "
    "Verbesserungsvorschläge zum Umsetzen ausgewählt. Bevor Neo anfängt, prüfst du sie ZUSAMMEN:\n"
    "1. WIDERSPRÜCHE: verlangt ein Punkt etwas, das ein anderer (oder eine der ZULETZT UMGESETZTEN Änderungen) gerade "
    "anders regelt? Beispiel: einer will, dass Talk bei X nachfragt, ein anderer, dass Talk bei X sofort handelt.\n"
    "2. ÜBERSCHNEIDUNGEN: ändern zwei Punkte dieselbe Funktion oder Stelle? Dann gehören sie in eine sinnvolle Reihenfolge, "
    "und der spätere muss wissen, was der frühere geändert hat.\n"
    "3. ABHÄNGIGKEITEN: braucht ein Punkt einen anderen zuerst?\n"
    "4. DOPPELT: meinen zwei Punkte DENSELBEN Fehler (gleiches Fehlerbild, gleiche Stelle), wird nur EINER umgesetzt -- der "
    "konkretere; der andere kommt unter \"doppelt\" und NICHT in die Reihenfolge. Zwei Punkte zum selben Fehler nacheinander "
    "umzusetzen heißt, dieselbe Stelle zweimal anzufassen -- genau die gegenläufige Arbeit, die Veiko nicht will.\n"
    "Ein echter Widerspruch, den nur Veiko auflösen kann, heißt: einen der beiden ZURÜCKSTELLEN, mit einer Frage an Veiko. "
    "Bloße Überschneidungen löst du über Reihenfolge und Hinweise, nicht durch Zurückstellen.\n"
    "Antworte NUR mit JSON: {\"reihenfolge\": [\"id\", …] (alle nicht zurückgestellten und nicht doppelten), "
    "\"doppelt\": [{\"id\": \"id\", \"wie\": \"id des Punkts, der umgesetzt wird\"}], "
    "\"konflikte\": [{\"ids\": [\"id\", \"id\"], \"art\": \"widerspruch|ueberschneidung|abhaengigkeit\", \"beschreibung\": \"ein Satz für Veiko\", "
    "\"loesung\": \"ein Satz\"}], \"zurueckstellen\": [{\"id\": \"id\", \"grund\": \"ein Satz\", \"frage_an_veiko\": \"eine Frage\"}], "
    "\"hinweise\": {\"id\": \"was Neo bei diesem Punkt wegen der anderen beachten muss, oder leer\"}, "
    "\"zusammenfassung\": \"zwei bis vier Sätze für Veiko, ohne Fachjargon: was umgesetzt wird, in welcher Reihenfolge, was zurückgestellt ist\"}")


def _punkt_text(r: dict[str, Any]) -> str:
    from . import rsi
    d = r["daten"]
    da = d.get("dario") or {}
    return (f"=== PUNKT id={r['id']} ===\n" + rsi._vorschlag_text(d)
            + (f"\nDARIOS AUFTRAG DAZU: {da.get('naechster_auftrag')}" if da.get("naechster_auftrag") else "")
            + (f"\nDARIOS PLAN (Auszug): {str((d.get('plan') or {}).get('text') or '')[:1500]}" if d.get("plan") else ""))


def _zuletzt_umgesetzt() -> str:
    zeilen = [f"- {r['titel']}" for r in db.alle("SELECT titel FROM rsi WHERE stand='umgesetzt' ORDER BY geaendert DESC LIMIT 10")]
    return "\n".join(zeilen) or "(noch nichts)"


def pruef_frage(ids: list[str]) -> str:
    punkte = [r for r in (_rsi(i) for i in ids) if r]
    return ("AUSGEWÄHLT ZUM UMSETZEN:\n\n" + "\n\n".join(_punkt_text(r) for r in punkte)
            + "\n\nZULETZT UMGESETZT (darf nicht wieder zurückgedreht werden):\n" + _zuletzt_umgesetzt())


def schaetzung(ids: list[str]) -> float:
    """Widerspruchspruefung plus je Punkt ohne fertigen Plan Darios Umsetzungsplan (mit Code-Auszug).
    Darios Pruefung jeder Aenderung vor dem Einspielen kommt dazu und steht im Text daneben (je Punkt einige Cent)."""
    from . import rsi
    s = rsi.schaetzung(PRUEF_SYSTEM, pruef_frage(ids), 1500 + 300 * len(ids))
    for i in ids:
        r = _rsi(i)
        if r and not (r["daten"].get("plan") or {}).get("fuer_umsetzung"):
            s += rsi.schaetzung(rsi.DARIO_PLAN_SYSTEM, rsi._vorschlag_text(r["daten"]) + rsi.code_auszug(r["daten"]), 4000)
    return round(s, 3)


def auswahl(umsetzen: list[str], verwerfen: list[str], automatisch: bool = True) -> dict[str, Any]:
    """Verwirft sofort, was verworfen werden soll, und startet die Widerspruchspruefung fuer den Rest
    (im Hintergrund). Rueckgabe: was passiert, mit geschaetzten Kosten.

    automatisch (Vorgabe, Veiko 23.10.2026: "das, was ich auswaehle, soll dann auch, wenn nicht
    widerspruechlich, umgesetzt werden"): nach der Pruefung setzt Neo sofort um, was nicht
    zurueckgestellt ist -- ohne zweiten Klick. Zurueckgestelltes bleibt offen, mit Darios Frage."""
    if laeuft() or stand().get("stand") == "bereit":
        raise ValueError("Es läuft schon eine Serie -- warte, bis sie fertig ist.")
    # Doppelte vorher zusammenlegen; ein ausgewaehlter, der dabei aufgeht, zaehlt als sein Ziel.
    from . import rsi
    rsi.doppelte_zusammenlegen()
    ziel = {r["id"]: rsi._daten(r).get("zusammengelegt_in") for r in db.alle("SELECT id, daten FROM rsi WHERE stand='zusammengelegt'")}
    umsetzen = [ziel.get(i) or i for i in umsetzen]
    verwerfen = [i for i in verwerfen if i not in ziel]
    offen = {r["id"] for r in db.alle(f"SELECT id FROM rsi WHERE stand IN {OFFEN}")}
    umsetzen = [i for i in dict.fromkeys(umsetzen) if i in offen]
    verwerfen = [i for i in dict.fromkeys(verwerfen) if i in offen and i not in umsetzen]
    for i in verwerfen:
        db.ausfuehren("UPDATE rsi SET stand='verworfen', geaendert=? WHERE id=?", (time.time(), i))
    if not umsetzen:
        return {"ok": True, "verworfen": len(verwerfen), "umsetzen": 0}
    s = schaetzung(umsetzen)
    db.einstellung_setzen(ZUSTAND, {"id": db.neue_id("x"), "stand": "pruefung", "auswahl": umsetzen, "verworfen": verwerfen,
                                    "start": time.time(), "schaetzung": s, "ergebnisse": {}, "automatisch": automatisch})
    _starten(_pruefen())
    return {"ok": True, "verworfen": len(verwerfen), "umsetzen": len(umsetzen), "schaetzung": s, "automatisch": automatisch}


async def _pruefen() -> None:
    from . import rsi
    s = stand()
    ids = s.get("auswahl") or []
    try:
        antwort, kosten, modell = await rsi._dario(PRUEF_SYSTEM, pruef_frage(ids), 1500 + 300 * len(ids))
    except llm.ModellFehler as f:
        _setzen(stand="fehler", fehler=f"Dario war für die Widerspruchsprüfung nicht erreichbar ({f}). Ohne diese Prüfung "
                                        "startet nichts -- versuch es später noch einmal.")
        return
    j = llm.json_aus(antwort)
    if not isinstance(j, dict):
        _setzen(stand="fehler", fehler="Darios Antwort auf die Widerspruchsprüfung war nicht lesbar. Ohne Prüfung startet nichts.")
        return
    zurueck = [z for z in (j.get("zurueckstellen") or []) if isinstance(z, dict) and z.get("id") in ids]
    zurueck_ids = {z["id"] for z in zurueck}
    # Doppelte: nur einer wird umgesetzt, der andere geht in ihm auf (Belege wandern mit).
    doppelt = [x for x in (j.get("doppelt") or []) if isinstance(x, dict) and x.get("id") in ids and x.get("wie") in ids
               and x["id"] != x["wie"] and x["wie"] not in zurueck_ids]
    doppelt_ids = set()
    for x in doppelt:
        if x["wie"] in doppelt_ids:
            continue
        r = _rsi(x["id"])
        if r:
            rsi._anhaengen(x["wie"], r["daten"].get("belege") or [], "Serie", r["daten"].get("vorschlag"))
            d = r["daten"]
            d["zusammengelegt_in"] = x["wie"]
            db.ausfuehren("UPDATE rsi SET stand='zusammengelegt', daten=?, geaendert=? WHERE id=?", (json.dumps(d, ensure_ascii=False), time.time(), x["id"]))
            doppelt_ids.add(x["id"])
    zurueck_ids |= doppelt_ids
    reihe = [i for i in (j.get("reihenfolge") or []) if i in ids and i not in zurueck_ids]
    reihe += [i for i in ids if i not in reihe and i not in zurueck_ids]     # nichts geht stillschweigend verloren
    hinweise = j.get("hinweise") if isinstance(j.get("hinweise"), dict) else {}
    _setzen(stand="bereit", reihenfolge=reihe, zurueckgestellt=zurueck, doppelt=doppelt,
            konflikte=[k for k in (j.get("konflikte") or []) if isinstance(k, dict)][:12],
            hinweise={i: str(hinweise.get(i) or "")[:1500] for i in reihe},
            zusammenfassung=str(j.get("zusammenfassung") or "")[:1500], pruef_kosten=round(kosten, 4), pruef_modell=modell)
    if not s.get("automatisch"):
        return
    # Gleich weiter, ohne zweiten Klick -- Veikos Ja galt der Auswahl samt Umsetzung.
    if not reihe:
        for z in zurueck:
            _stand_rsi(z["id"], "geprueft", zurueckgestellt=z.get("grund"), frage=z.get("frage_an_veiko"))
        _setzen(stand="fertig", ende=time.time(), release_id=None, gemeldet=False,
                meldung="Umgesetzt wurde nichts: Dario hat alle ausgewählten Punkte zurückgestellt, weil sie sich widersprechen. "
                        "Seine Fragen an dich stehen an den Punkten.")
        return
    try:
        starten()
    except ValueError as e:
        _setzen(stand="fehler", fehler=f"Geprüft, aber nicht gestartet: {e}")


# ---------------------------------------------------------------- 3. Start: nacheinander umsetzen
def starten() -> dict[str, Any]:
    s = stand()
    if s.get("stand") != "bereit":
        raise ValueError("Es liegt keine geprüfte Auswahl bereit." if s.get("stand") != "laeuft" else "Die Serie läuft schon.")
    if not s.get("reihenfolge"):
        raise ValueError("Nach der Prüfung bleibt nichts zum Umsetzen übrig.")
    sauber = _git("status", "--porcelain", "--untracked-files=no").stdout.strip()
    if sauber:
        raise ValueError("Im Cockpit liegen uncommittete Änderungen -- so würde die Serie sie mit einmischen. "
                         "Erst klären (Neo oder Claude Code).")
    _setzen(stand="laeuft", gestartet=time.time(), start_commit=_kopf(), aktuell=None, ergebnisse={})
    for i in s["reihenfolge"]:
        _stand_rsi(i, "in_serie", serie_id=s["id"])
    for z in s.get("zurueckgestellt") or []:
        _stand_rsi(z["id"], "geprueft", zurueckgestellt=z.get("grund"), frage=z.get("frage_an_veiko"))
    _starten(_abarbeiten())
    return {"ok": True, "punkte": len(s["reihenfolge"])}


def _hinweis(s: dict[str, Any], rid: str) -> str:
    andere = [x for x in s["reihenfolge"] if x != rid]
    vorher = [x for x in s["reihenfolge"][: s["reihenfolge"].index(rid)]]
    teile = ["DIESER AUFTRAG IST TEIL EINER SERIE von RSI-Punkten, die nacheinander umgesetzt werden."]
    if vorher:
        teile.append("VOR DIR schon umgesetzt (der Code, den du liest, enthält es -- dreh es nicht zurück): "
                     + "; ".join(f"„{(_rsi(x) or {}).get('titel', x)}“ ({(s['ergebnisse'].get(x) or {}).get('stand', '?')})" for x in vorher))
    nachher = [x for x in andere if x not in vorher]
    if nachher:
        teile.append("NACH DIR kommen noch (nicht vorwegnehmen): " + "; ".join(f"„{(_rsi(x) or {}).get('titel', x)}“" for x in nachher))
    if s.get("hinweise", {}).get(rid):
        teile.append("DARIOS HINWEIS FÜR DIESEN PUNKT: " + s["hinweise"][rid])
    teile.append("Setz NUR diesen Punkt um. Starte das Cockpit nicht neu -- das passiert am Ende der Serie einmal.")
    return "\n".join(teile)


async def _abarbeiten() -> None:
    from . import neo, rsi
    try:
        while True:
            s = stand()
            if s.get("stand") != "laeuft":
                return
            rest = [i for i in s["reihenfolge"] if i not in s.get("ergebnisse", {})]
            if not rest:
                break
            rid = rest[0]
            _setzen(aktuell=rid, aktuell_seit=time.time(), aktuell_schritt="Dario schreibt den Umsetzungsplan")
            # 1. PLAN (23.10.2026): ohne ihn bekam Neo Darios "naechsten Auftrag" -- meist "erst untersuchen,
            # noch keinen Code" -- und Dario lehnte danach ab, weil kein Code kam bzw. der falsche. Der Plan
            # entsteht gegen den echten Code und endet zwingend in einer Aenderung.
            punkt = _rsi(rid) or {}
            if not (punkt.get("daten") or {}).get("plan", {}).get("fuer_umsetzung"):
                p = await rsi.dario_plan(rid, zum_umsetzen=True)
                if not p.get("ok"):
                    _ergebnis(rid, "gescheitert", grund=f"Darios Plan kam nicht zustande: {p.get('grund')}")
                    continue
                plan_text = str(((_rsi(rid) or {}).get("daten") or {}).get("plan", {}).get("text") or "")
                if plan_text.lstrip().upper().startswith("KEINE ÄNDERUNG"):
                    _ergebnis(rid, "gescheitert", grund="Dario: " + plan_text.strip()[:500])
                    continue
            # 2. NEO setzt den Plan um; 3. lehnt Dario ab, bessert Neo EINMAL nach (gleiches Gespraech, mit den Maengeln).
            _setzen(aktuell_schritt="Neo setzt um")
            r = await rsi.neo_beauftragen(rid, _hinweis(s, rid), kein_neustart=True)
            if not r.get("ok"):
                _ergebnis(rid, "gescheitert", grund=r.get("grund") or "Neo ließ sich nicht beauftragen.")
                continue
            _setzen(aktuell_gespraech=r["gespraech_id"])
            job = await _warten(r["job"])
            if job is None:
                _ergebnis(rid, "gescheitert", grund=f"Nach {MAX_JE_PUNKT // 60} Minuten abgebrochen.", gespraech_id=r["gespraech_id"])
                continue
            lauf = job.get("lauf") or {}
            pr = lauf.get("pruefung") or {}
            if not pr.get("eingespielt") and pr.get("urteil") != "nicht_geprueft":
                _setzen(aktuell_schritt="Neo bessert nach")
                maengel = (f"{pr.get('von', 'Dario')} hat deine Änderung abgelehnt:\n{pr.get('begruendung') or ''}"
                           + ("\nMängel:\n" + "\n".join(f"- {m}" for m in pr.get("maengel") or []) if pr.get("maengel") else "")
                           if pr else "Du hast nichts am Cockpit geändert -- es ist nichts vorgemerkt.")
                try:
                    jid2 = await neo.senden(r["gespraech_id"], "NACHBESSERN (einmal, automatisch in der RSI-Serie). " + maengel
                                            + "\n\nSetz Darios Umsetzungsplan jetzt vollständig um: erst die betroffenen Stellen mit "
                                              "datei_lesen ansehen, dann mit datei_aendern ändern. Behebe genau diese Mängel, nichts sonst.",
                                            [], kein_neustart=True)
                    job2 = await _warten(jid2)
                    if job2 is not None:
                        lauf = job2.get("lauf") or {}
                        pr = lauf.get("pruefung") or pr
                except ValueError:
                    pass
            eg = lauf.get("einspiel_ergebnis") or {}
            if pr.get("eingespielt"):
                _ergebnis(rid, "umgesetzt", commit=eg.get("commit"), dateien=[str(x).split("/vve-cp-r2/")[-1] for x in eg.get("dateien") or []],
                          neustart=bool(eg.get("neustart") or eg.get("server_teile")), gespraech_id=r["gespraech_id"],
                          bericht=str(pr.get("begruendung") or "")[:800])
            elif pr:
                _ergebnis(rid, "gescheitert", grund=f"{pr.get('von', 'Dario')}: {str(pr.get('begruendung') or '')[:600]}",
                          gespraech_id=r["gespraech_id"])
            else:
                _ergebnis(rid, "gescheitert", grund="Neo hat nichts am Cockpit geändert. " + str(lauf.get("antwort") or "")[-400:],
                          gespraech_id=r["gespraech_id"])
        _abschliessen()
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 -- nie eine Serie auf "laeuft" haengen lassen
        traceback.print_exc()
        _setzen(stand="fehler", fehler=f"{e.__class__.__name__}: {str(e)[:300]}", ende=time.time())


async def _warten(jid: str) -> dict[str, Any] | None:
    """Bis Neos Auftrag fertig ist; None nach MAX_JE_PUNKT (dann wird er abgebrochen)."""
    from . import neo
    ende = time.time() + MAX_JE_PUNKT
    while time.time() < ende:
        job = neo.JOBS.get(jid)
        if not job or job["fertig"]:
            return job or {}
        await asyncio.sleep(5)
    neo.abbrechen(jid)
    return None


def _ergebnis(rid: str, stand_: str, **w: Any) -> None:
    s = stand()
    erg = s.get("ergebnisse") or {}
    erg[rid] = {"stand": stand_, "zeit": time.time(), **w}
    _setzen(ergebnisse=erg, aktuell=None)
    _stand_rsi(rid, "umgesetzt" if stand_ == "umgesetzt" else "geprueft",
               ergebnis=stand_, grund=w.get("grund"), commit=w.get("commit"), gespraech_id=w.get("gespraech_id"))


def _abschliessen() -> None:
    from . import neo_freigabe
    s = stand()
    erg = s.get("ergebnisse") or {}
    ok = [i for i, e in erg.items() if e["stand"] == "umgesetzt"]
    commits = [erg[i]["commit"] for i in s["reihenfolge"] if i in ok and erg[i].get("commit")]
    neustart = any(erg[i].get("neustart") for i in ok)
    release = None
    if ok:
        release = {"id": s["id"], "zeit": time.time(), "start_commit": s.get("start_commit"), "ende_commit": _kopf(),
                   "commits": commits, "punkte": [{"id": i, "titel": (_rsi(i) or {}).get("titel"), "commit": erg[i].get("commit")} for i in ok],
                   "zurueckgenommen": False}
        db.einstellung_setzen(RELEASES, ([release] + releases())[:20])
    nicht = [{"id": i, "titel": (_rsi(i) or {}).get("titel"), "grund": e.get("grund")} for i, e in erg.items() if e["stand"] != "umgesetzt"]
    _setzen(stand="fertig", ende=time.time(), release_id=release["id"] if release else None, neustart=neustart,
            meldung=_meldung(ok, nicht, neustart), gemeldet=False)
    if neustart:
        neo_freigabe.neustart_spaeter()


def _meldung(ok: list[str], nicht: list[dict[str, Any]], neustart: bool) -> str:
    if not ok:
        return ("Die RSI-Serie ist durch, aber umgesetzt wurde nichts: "
                + "; ".join(f"„{n['titel']}“ -- {n.get('grund') or 'unbekannt'}" for n in nicht)[:900])
    t = (f"Das neue Release ist da: {len(ok)} Verbesserung{'en' if len(ok) != 1 else ''} umgesetzt -- "
         + ", ".join(f"„{(_rsi(i) or {}).get('titel')}“" for i in ok) + ".")
    if nicht:
        t += f" Nicht umgesetzt: " + ", ".join(f"„{n['titel']}“" for n in nicht) + " (Gründe auf der Seite RSI)."
    t += (" Das Cockpit startet einmal neu; lad danach die Seite neu und probier es aus." if neustart
          else " Lad die Seite einmal neu und probier es aus.")
    return t + " Funktioniert etwas nicht, kannst du das Release zurücknehmen."


def gemeldet() -> None:
    if stand().get("stand") == "fertig":
        _setzen(gemeldet=True)


def abbrechen() -> dict[str, Any]:
    """Bricht eine Serie VOR dem Start ab (nach der Pruefung) oder stoppt sie nach dem laufenden Punkt."""
    s = stand()
    if s.get("stand") in ("bereit", "fehler", "pruefung"):
        db.einstellung_setzen(ZUSTAND, {})
        return {"ok": True}
    if s.get("stand") == "laeuft":
        # Der laufende Punkt wird zu Ende gebracht (ein halb eingespieltes Release waere schlimmer),
        # danach keine weiteren.
        rest = [i for i in s["reihenfolge"] if i not in (s.get("ergebnisse") or {}) and i != s.get("aktuell")]
        _setzen(reihenfolge=[i for i in s["reihenfolge"] if i not in rest])
        for i in rest:
            _stand_rsi(i, "geprueft", ergebnis="abgebrochen")
        return {"ok": True, "nach_aktuellem": True}
    return {"ok": False, "grund": "Es läuft keine Serie."}


def fortsetzen_nach_neustart() -> None:
    """Beim Start des Dienstes: lief eine Serie, ist der aktuelle Punkt verloren -- vermerken, weiter."""
    s = stand()
    if s.get("stand") == "pruefung":
        _setzen(stand="fehler", fehler="Das Cockpit wurde während der Widerspruchsprüfung neu gestartet. Bitte noch einmal prüfen lassen.")
        return
    if s.get("stand") != "laeuft":
        return
    if s.get("aktuell"):
        _ergebnis(s["aktuell"], "gescheitert", grund="Unterbrochen: das Cockpit wurde neu gestartet, während Neo daran arbeitete.",
                  gespraech_id=s.get("aktuell_gespraech"))
    _starten(_abarbeiten())


def _starten(coro) -> None:
    global _task
    _task = asyncio.create_task(coro)


# ---------------------------------------------------------------- 5. Zuruecknehmen
def zuruecknehmen(release_id: str | None = None, rsi_id: str | None = None) -> dict[str, Any]:
    """git revert der Commits eines Release (oder eines Punkts), neueste zuerst. Geht es nicht glatt,
    bleibt alles, wie es war."""
    from . import neo_freigabe
    if laeuft():
        return {"ok": False, "grund": "Während eine Serie läuft, wird nichts zurückgenommen."}
    rel = next((r for r in releases() if r["id"] == release_id), None) if release_id else None
    if not release_id and not rsi_id:      # "nimm das letzte Release zurueck"
        rel = next((r for r in releases() if not r.get("zurueckgenommen")), None)
    if rsi_id:
        rel = rel or next((r for r in releases() if any(p["id"] == rsi_id for p in r["punkte"])), None)
        punkte = [p for p in (rel or {}).get("punkte", []) if p["id"] == rsi_id]
    else:
        punkte = (rel or {}).get("punkte", [])
    punkte = [p for p in punkte if p.get("commit") and not p.get("zurueckgenommen")]
    if not punkte:
        return {"ok": False, "grund": "Dazu gibt es nichts zurückzunehmen."}
    if _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        return {"ok": False, "grund": "Im Cockpit liegen uncommittete Änderungen -- erst klären, dann zurücknehmen."}
    vorher = _kopf()
    commits = [p["commit"] for p in punkte][::-1]
    # Mit eigenem Autor -- ohne bricht git revert ab, wenn das Konto keinen hinterlegt hat (im Test gefunden).
    r = _git("-c", "user.name=Cockpit (RSI)", "-c", "user.email=rsi@vve-cockpit.local", "revert", "--no-edit", *commits, timeout=120)
    if r.returncode:
        _git("revert", "--abort")
        _git("reset", "--hard", vorher)
        konflikt = "conflict" in (r.stdout + r.stderr).lower()
        return {"ok": False, "grund": ("Zurücknehmen geht nicht glatt -- an denselben Stellen wurde danach weiter geändert. "
                                       "Es ist nichts verändert. Neo kann es gezielt rückgängig machen." if konflikt else
                                       "Zurücknehmen ging nicht, es ist nichts verändert: " + (r.stderr or r.stdout).strip()[-300:])}
    geaendert = _git("diff", "--name-only", vorher, "HEAD").stdout.split()
    fehler = _pruefen_dateien(geaendert)
    if fehler:
        _git("reset", "--hard", vorher)
        return {"ok": False, "grund": "Nach dem Zurücknehmen liefe das Cockpit nicht (" + fehler[:300] + ") -- es ist nichts verändert."}
    p = _git("push", "origin", "HEAD:main")
    for x in punkte:
        x["zurueckgenommen"] = True
        _stand_rsi(x["id"], "zurueckgenommen", zurueckgenommen=time.time())
    alle = releases()
    for rr in alle:
        if rr["id"] == rel["id"]:
            rr["punkte"] = [next((x for x in punkte if x["id"] == q["id"]), q) for q in rr["punkte"]]
            rr["zurueckgenommen"] = all(q.get("zurueckgenommen") for q in rr["punkte"])
    db.einstellung_setzen(RELEASES, alle)
    neustart = any(f.endswith(".py") for f in geaendert)
    if neustart:
        neo_freigabe.neustart_spaeter()
    return {"ok": True, "punkte": [x["titel"] for x in punkte], "gepusht": p.returncode == 0, "neustart": neustart}


def _pruefen_dateien(dateien: list[str]) -> str:
    fehler = []
    for f in dateien:
        pfad = WURZEL / f
        if not pfad.is_file():
            continue
        if f.endswith(".py"):
            r = subprocess.run([str(WURZEL / ".venv" / "bin" / "python"), "-m", "py_compile", str(pfad)], capture_output=True, text=True)
        elif f.endswith(".js"):
            r = subprocess.run(["node", "--input-type=module", "--check"], stdin=open(pfad, "rb"), capture_output=True, text=True)
        else:
            continue
        if r.returncode:
            fehler.append(f"{f}: {(r.stderr or r.stdout).strip()[-200:]}")
    return "; ".join(fehler)


# ---------------------------------------------------------------- fuer Seite und Talk
def uebersicht() -> dict[str, Any]:
    s = stand()
    titel = {r["id"]: r["titel"] for r in db.alle("SELECT id, titel FROM rsi")}
    return {"serie": {**s, "titel": {i: titel.get(i) for i in (s.get("auswahl") or [])}}, "releases": releases()[:8]}


def talk_text() -> str:
    """Fuer die Lage in Talk: was mit der Serie gerade ist -- und eine ungemeldete Release-Meldung."""
    s = stand()
    titel = lambda i: (_rsi(i) or {}).get("titel") or i  # noqa: E731
    if s.get("stand") == "pruefung":
        return "RSI: Dario prüft gerade die Auswahl auf Widersprüche."
    if s.get("stand") == "bereit":
        z = (f"RSI: Die Auswahl ist geprüft und wartet auf Veikos Start. Dario: {s.get('zusammenfassung')} "
             f"Umsetzen in dieser Reihenfolge: {', '.join(titel(i) for i in s.get('reihenfolge', []))}.")
        if s.get("zurueckgestellt"):
            z += " Zurückgestellt: " + "; ".join(f"{titel(x['id'])} ({x.get('grund')}; Frage: {x.get('frage_an_veiko')})" for x in s["zurueckgestellt"])
        return z + " Start mit aktion rsi was starten."
    if s.get("stand") == "laeuft":
        fertig = len(s.get("ergebnisse") or {})
        return (f"RSI: Neo setzt gerade Punkt {fertig + 1} von {len(s.get('reihenfolge', []))} um"
                + (f" („{titel(s['aktuell'])}“)" if s.get("aktuell") else "") + ".")
    if s.get("stand") == "fertig":
        return ("RSI-RELEASE (noch nicht gemeldet -- sag es Veiko zuerst): " if not s.get("gemeldet") else "RSI, zuletzt: ") + str(s.get("meldung") or "")
    if s.get("stand") == "fehler":
        return f"RSI: Die letzte Serie ist gescheitert: {s.get('fehler')}"
    return ""
