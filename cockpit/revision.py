"""
MODELL-REVISION -- das Cockpit sucht selbst nach besseren Modellen und belegt
jeden Vorschlag mit einer Messung auf dieser Maschine.

Veiko (17.10.2026): "ich moechte, dass das Cockpit selbst sehr stringent nach
Optimierungen sucht: welches Modell macht aktuell was, welche neuen Modelle gibt
es, was koennte durch was ersetzt werden, welche neuen Rollen koennte das Team
brauchen -- und mir dann Vorschlaege macht."

Vier Schritte:
  1. BESTAND     wer rechnet womit (jede Rolle, Talk), wie oft, wie schnell, und
                 wie Daniel die Arbeit beurteilt hat (aus verbrauch/ergebnisse)
  2. KANDIDATEN  installierte Modelle, die fuer einen Platz in Frage kommen:
                 aus der Rangliste AUFGABEN, aus der Einordnung neuer Modelle
                 (modellkatalog.einordnen) und alles in den letzten 14 Tagen Geladene
  3. MESSEN      bisheriges und neues Modell bekommen DIESELBE echte Aufgabe der
                 Rolle (aus ihren letzten Ergebnissen). Gemessen: Tempo (Ollama
                 meldet Token und Zeit) und Qualitaet im VERDECKTEN Vergleich --
                 ein drittes Modell liest beide Antworten als A und B in
                 zufaelliger Reihenfolge, ohne zu wissen, welche woher stammt.
  4. VORSCHLAGEN "umstellen", wenn das neue im Vergleich vorn liegt oder gleich gut
                 und deutlich schneller ist; dazu "laden und messen" fuer passende
                 neue Modelle bei Ollama und "neue Rolle denkbar".

Grenzen, die Absicht sind:
- **Umgestellt wird nie ohne Veikos Klick.** Autonomie heisst hier: selbst suchen,
  selbst messen, selbst vorschlagen -- nicht: selbst entscheiden.
- **Gemessen wird nur, was installiert ist.** Ein Download dauert auf der Leitung
  des Servers Stunden; den stoesst Veiko an, gemessen wird in der Nacht danach.
- **Nachts (02--05 Uhr deutscher Zeit), hoechstens vier Vergleiche**, jeder unter
  derselben Sperre wie die Pipeline -- tagsueber gehoeren die Karten dem Team.
- **Ein Vergleich ist eine Stichprobe, kein Beweis.** Deshalb stehen Zahl der
  Aufgaben und Ergebnis ("2 von 2 vorn") beim Vorschlag, nicht nur ein Urteil.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import random
import re
import time
import traceback
from typing import Any
from zoneinfo import ZoneInfo

from . import db, llm, modellkatalog, stab

BERLIN = ZoneInfo("Europe/Berlin")
MAX_VERGLEICHE = 4
AUFGABEN_JE_VERGLEICH = 2
NEU_GEMESSEN_TAGE = 30          # ein Paar wird erst nach so vielen Tagen erneut gemessen
FRISCH_TAGE = 14                # so lange gilt ein Modell als "neu geladen"
_lauf: asyncio.Task | None = None
_weck = asyncio.Event()

# Die Art eines Platzes bestimmt, welche Kandidaten aus AUFGABEN in Frage kommen.
ART_AUFGABE = {"denken": "denken", "allgemein": "allgemein", "code": "code", "talk": "schnell"}
# Fester Ersatz, wenn eine Rolle noch nichts geliefert hat, woran man messen koennte.
ERSATZ_AUFGABEN = {
    "denken": ["Ein mittelständisches Unternehmen will in zwei Jahren 30 % seiner Verwaltungsprozesse automatisieren. "
               "Welche drei Risiken werden am häufigsten unterschätzt, und was wäre je eine Gegenmaßnahme?"],
    "allgemein": ["Schreibe eine kurze, freundliche Mail an das Führungsteam, die zu einem Workshop über "
                  "KI im Personalwesen einlädt: Ziel, Ablauf in drei Punkten, Bitte um Rückmeldung bis Freitag."],
    "code": ["Schreibe eine Python-Funktion, die aus einer Liste von Zeitstempeln (Sekunden) die längste Lücke "
             "zwischen zwei aufeinanderfolgenden Werten findet und Anfang und Ende zurückgibt. Mit kurzer Erklärung."],
    "talk": ["Was liegt heute an? Antworte knapp in höchstens fünf Punkten.",
             "Fasse in drei Sätzen zusammen, was das Team zuletzt geliefert hat."],
}
RICHTER_SYSTEM = (
    "Du bist ein strenger, unparteiischer Prüfer. Du bekommst eine Aufgabe und zwei Antworten, A und B. "
    "Bewerte, welche die Aufgabe besser erfüllt: richtig, vollständig, gut verständlich, auf Deutsch, ohne erfundene "
    "Fakten und ohne fremde Schriftzeichen. Länge ist KEIN Vorteil. Antworte AUSSCHLIESSLICH mit JSON: "
    '{"besser": "A|B|gleich", "begruendung": "ein bis zwei Sätze"}')


# ---------------------------------------------------------------- Stand
def stand() -> dict[str, Any]:
    return db.einstellung("revision_stand", {}) or {}


def _stand_setzen(**werte: Any) -> None:
    s = stand()
    s.update(werte)
    db.einstellung_setzen("revision_stand", s)


def _nicht_text(name: str) -> bool:
    return bool(re.search(r"embed|minilm|bge|whisper", name))


async def plaetze() -> list[dict[str, Any]]:
    """Jeder Platz, an dem ein Modell arbeitet, mit dem Modell, das dort WIRKLICH rechnet."""
    aus = []
    for t in db.alle("SELECT id, name, titel, art, modell FROM team WHERE aktiv=1 ORDER BY reihenfolge"):
        rueck = llm.vorgabe("stab") if t["id"] == "pmo" else llm.vorgabe("neo") if t["id"] == "cockpit" else llm.vorgabe("arbeit")
        wirksam = await stab.modell_fuer(t["id"], rueck)
        aus.append({"platz": "rolle:" + t["id"], "rolle": t["id"], "name": t["name"], "titel": t["titel"],
                    "art": t.get("art") or "allgemein", "eigen": t.get("modell") or "", "modell": wirksam,
                    # Eingetragen, aber nicht (mehr) installiert: dann rechnet still ein anderes.
                    "eigen_fehlt": bool(t.get("modell")) and t.get("modell") != wirksam})
    talk = await llm.modell_waehlen(llm.vorgabe("talk"), "qwen3.6:27b", "qwen3:30b-a3b", "llama3.3:70b")
    aus.append({"platz": "vorgabe:talk", "rolle": None, "name": "Talk", "titel": "Gespräch mit dem Cockpit, Board",
                "art": "talk", "eigen": (db.einstellung("modell_vorgaben", {}) or {}).get("talk") or "", "modell": talk, "eigen_fehlt": False})
    return aus


def _nutzung(tage: int = 30) -> dict[str, Any]:
    seit = time.time() - tage * 86400
    je_modell = {z["modell"]: z for z in db.alle(
        "SELECT modell, COUNT(*) AS aufrufe, SUM(tok_aus) AS aus, SUM(dauer_s) AS dauer FROM verbrauch "
        "WHERE art='lokal' AND zeit>? GROUP BY modell", (seit,))}
    # Je Rolle (wer) und fuer Talk je Bereich: Aufrufe und mittlere Dauer. Die Dauer
    # enthaelt Lesen und ggf. Laden -- als Schreibtempo taugt sie nicht, als
    # "so lange wartet man im Schnitt" schon. Das Schreibtempo misst die Revision.
    je_wer = {(z["wer"], z["modell"]): z for z in db.alle(
        "SELECT wer, modell, COUNT(*) AS aufrufe, AVG(dauer_s) AS dauer FROM verbrauch WHERE art='lokal' AND zeit>? AND wer IS NOT NULL "
        "GROUP BY wer, modell", (seit,))}
    je_bereich = {(z["bereich"], z["modell"]): z for z in db.alle(
        "SELECT bereich, modell, COUNT(*) AS aufrufe, AVG(dauer_s) AS dauer FROM verbrauch WHERE art='lokal' AND zeit>? "
        "GROUP BY bereich, modell", (seit,))}
    urteile: dict[str, dict[str, int]] = {}
    for e in db.alle("SELECT rolle, modell, pruefung FROM ergebnisse WHERE erstellt>?", (seit,)):
        u = (e.get("pruefung") or {}).get("urteil") if isinstance(e.get("pruefung"), dict) else None
        if u:
            d = urteile.setdefault(e["rolle"] or "?", {})
            d[u] = d.get(u, 0) + 1
    return {"je_modell": je_modell, "je_wer": je_wer, "je_bereich": je_bereich, "urteile": urteile}


async def bestand() -> dict[str, Any]:
    n = _nutzung()
    zeilen = []
    for p in await plaetze():
        w = (n["je_bereich"].get(("Talk", p["modell"])) if p["platz"] == "vorgabe:talk"
             else n["je_wer"].get((p["rolle"], p["modell"]))) or {}
        zeilen.append({**p, "aufrufe": w.get("aufrufe") or 0, "dauer_mittel": round(w["dauer"], 1) if w.get("dauer") else None,
                       "urteile": n["urteile"].get(p["rolle"] or "", {})})
    return {"plaetze": zeilen, "vorgaben": {k: llm.vorgabe(k) for k in llm.VORGABEN}, "vorgaben_text": llm.VORGABEN}


# ---------------------------------------------------------------- Kandidaten
def _frisch_geladen() -> dict[str, float]:
    """Installierte Modelle -> Zeitpunkt des Ladens (Aenderungszeit des Manifests)."""
    aus = {}
    try:
        for f in modellkatalog.MANIFESTE.glob("*/*"):
            aus[f"{f.parent.name}:{f.name}"] = f.stat().st_mtime
    except OSError:
        pass
    return aus


async def kandidaten(p: dict[str, Any], inst: dict[str, float], vram: float, neu: dict[str, Any] | None) -> list[str]:
    jetzt = time.time()
    geladen = _frisch_geladen()
    art = ART_AUFGABE.get(p["art"], "allgemein")
    liste: list[str] = []
    # 1. Frisch Geladenes zuerst -- genau das soll nach einem Download gemessen werden.
    liste += [n for n, t in sorted(geladen.items(), key=lambda x: -x[1]) if jetzt - t < FRISCH_TAGE * 86400]
    # 2. Aus der Einordnung neuer Modelle: Familien, die fuer DIESE Rolle vorgeschlagen sind.
    for f in (neu or {}).get("familien") or []:
        e = f.get("einordnung") or {}
        if any(r.startswith(p["name"] + " ") or r.startswith(p["name"] + "(") or r == p["name"] or
               (p["platz"] == "vorgabe:talk" and r.startswith("Talk")) for r in e.get("rollen") or []):
            liste += [a["name"] for a in f["ausgaben"] if a.get("installiert")]
    # 3. Die Rangliste der Aufgabenart.
    for a in modellkatalog.AUFGABEN:
        if a["id"] == art:
            liste += [modellkatalog._tag(k) for k in a["kandidaten"]]
    if p["art"] == "talk":
        liste += [n for n in inst if re.search(r"-a\d+b", n)]
    gemessen = {(m["kandidat"]) for m in db.alle("SELECT kandidat FROM messungen WHERE platz=? AND bisher=? AND zeit>?",
                                                 (p["platz"], p["modell"], jetzt - NEU_GEMESSEN_TAGE * 86400))}
    aus = []
    for n in dict.fromkeys(liste):
        if n in inst and n != p["modell"] and not _nicht_text(n) and n not in gemessen and inst[n] <= max(vram, 1) * 0.95:
            # Ein deutlich kleineres Modell ersetzt kein grosses (3B fuer Jasons 70B).
            if inst.get(p["modell"]) and inst[n] < 0.35 * inst[p["modell"]]:
                continue
            aus.append(n)
    return aus[:2]


# ---------------------------------------------------------------- Messen
def _aufgaben(p: dict[str, Any]) -> list[dict[str, str]]:
    """Echte Aufgaben der Rolle aus ihren letzten Ergebnissen; sonst feste."""
    aus: list[dict[str, str]] = []
    if p["rolle"] == "pmo":
        # Jasons eigentliche Arbeit ist das Einordnen neuer Notizen -- an einer
        # allgemeinen Frage gemessen (erster Lauf am 17.10.) sagt der Vergleich
        # wenig darueber, ob ein anderes Modell IHN ersetzen kann.
        for n in db.alle("SELECT * FROM notizen WHERE length(text)>200 ORDER BY erstellt DESC LIMIT 2"):
            aus.append({"frage": f"PROJEKTE:\n{stab.projektliste_text()[:4000]}\n\nNOTIZ:\n{stab.notiz_text(n, 5000)}\n\n"
                                 "Ordne die Notiz ein: worum geht es (zwei Sätze), zu welchem Projekt gehört sie (oder keinem), "
                                 "und welche zwei bis drei nächsten Schritte folgen daraus? Knapp."})
    elif p["rolle"] == "kritiker":
        for e in db.alle("SELECT titel, form, inhalt FROM ergebnisse WHERE length(inhalt)>800 ORDER BY erstellt DESC LIMIT 2"):
            aus.append({"system": stab.PRUEF_SYSTEM,
                        "frage": f"AUFTRAG: {e['titel']}\nFORM: {e['form']}\n\nERGEBNIS:\n{e['inhalt'][:9000]}"})
    elif p["rolle"] and p["rolle"] != "cockpit":
        for e in db.alle("SELECT e.titel, v.auftrag FROM ergebnisse e LEFT JOIN vorgaenge v ON v.id=e.vorgang_id "
                         "WHERE e.rolle=? ORDER BY e.erstellt DESC LIMIT 6", (p["rolle"],)):
            try:
                a = json.loads(e.get("auftrag") or "{}").get("auftrag")
            except (ValueError, TypeError):
                a = None
            t = (a or e["titel"] or "").strip()
            if len(t) > 15 and t not in [x["frage"][:len(t)] for x in aus]:
                aus.append({"frage": t[:3000]})
            if len(aus) >= AUFGABEN_JE_VERGLEICH:
                break
    if p["art"] == "talk":
        from .gespraech import lage_text
        lage = lage_text()[:8000]
        aus = [{"system": "Du bist das VvE Cockpit, die Stimme von Veikos KI-Team. Antworte auf Deutsch, knapp und "
                          f"nur auf Grundlage der LAGE.\n\nLAGE:\n{lage}", "frage": f} for f in ERSATZ_AUFGABEN["talk"]]
    if not aus:
        aus = [{"frage": f} for f in ERSATZ_AUFGABEN.get(p["art"], ERSATZ_AUFGABEN["allgemein"])]
    if p["rolle"] and p["rolle"] != "kritiker":
        r = stab.rolle(p["rolle"])
        for x in aus:
            x.setdefault("system", f"Du bist {r.get('name')}, {r.get('titel')} in Veiko von Eckerns KI-Team. {r.get('kurz') or ''} "
                                   "Antworte auf Deutsch. Liefere eine KOMPAKTE Fassung von höchstens 350 Wörtern -- "
                                   "es geht um einen Vergleich, nicht um das fertige Ergebnis.")
    return aus[:AUFGABEN_JE_VERGLEICH]


async def _einmal(modell: str, system: str, frage: str) -> dict[str, Any]:
    body = llm._body(modell, system, [{"role": "user", "content": frage}], json_format=False, temperatur=0.4,
                     denken=False, num_ctx=16384, stream=False)
    t0 = time.time()
    d = await llm._post(body, 1200)
    text = ((d.get("message") or {}).get("content") or "").strip()
    text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
    ev, evd = d.get("eval_count") or 0, (d.get("eval_duration") or 0) / 1e9
    netto = ((d.get("total_duration") or 0) - (d.get("load_duration") or 0)) / 1e9
    return {"text": text, "tps": ev / evd if evd else None, "dauer": netto or (time.time() - t0)}


async def _richter(bisher: str, kandidat: str) -> str | None:
    # Ein Richter, der auf EINE Karte passt: llama3.3:70b (42 GB) wurde neben dem
    # geladenen ComfyUI (zweite Karte) teils auf dem Prozessor gerechnet und machte
    # jeden Vergleich um Minuten langsamer (gemessen am 17.10.). Er bleibt letzter Ausweg.
    for w in (llm.vorgabe("arbeit"), "qwen3.8:27b", "deepseek-r1:32b", "qwen3.6:27b", "nemotron3:33b", "llama3.3:70b"):
        if w and w not in (bisher, kandidat) and await llm.modell_waehlen(w):
            return w
    return None


async def vergleichen(p: dict[str, Any], kandidat: str) -> dict[str, Any]:
    bisher = p["modell"]
    richter = await _richter(bisher, kandidat)
    if not richter:
        raise llm.ModellFehler("Kein drittes Modell für den verdeckten Vergleich installiert.")
    erg = {"siege_kandidat": 0, "siege_bisher": 0, "gleich": 0, "tps_b": [], "tps_k": [], "d_b": [], "d_k": [], "einzeln": []}
    aufgaben = _aufgaben(p)
    for i, a in enumerate(aufgaben):
        system = a.get("system") or ""
        stab.laeuft("revision", f"Modell-Revision: {p['name']} -- {bisher} gegen {kandidat}, Aufgabe {i + 1} von {len(aufgaben)}")
        b = await _einmal(bisher, system, a["frage"])
        k = await _einmal(kandidat, system, a["frage"])
        # Verdeckt: wer A ist, entscheidet der Zufall; der Richter sieht keine Modellnamen.
        k_ist_a = random.random() < 0.5
        A, B = (k, b) if k_ist_a else (b, k)
        stab.laeuft("revision", f"Modell-Revision: {richter} vergleicht verdeckt ({p['name']})")
        urteil = llm.json_aus(await llm.chat(richter, RICHTER_SYSTEM, [{"role": "user", "content":
                              f"AUFGABE:\n{a['frage'][:6000]}\n\nANTWORT A:\n{A['text'][:12000] or '(leer)'}\n\n"
                              f"ANTWORT B:\n{B['text'][:12000] or '(leer)'}"}],
                              json_format=True, temperatur=0, denken=False, num_ctx=32768, timeout=900)) or {}
        besser = urteil.get("besser") if isinstance(urteil, dict) else None
        # Eine leere oder fremdschriftliche Antwort verliert, egal was der Richter meint.
        for x in (b, k):
            x["kaputt"] = not x["text"] or llm.fremdschrift(x["text"])
        if b["kaputt"] != k["kaputt"]:
            sieger = "bisher" if k["kaputt"] else "kandidat"
        elif besser == "gleich" or besser not in ("A", "B"):
            sieger = "gleich"
        else:
            sieger = "kandidat" if (besser == "A") == k_ist_a else "bisher"
        erg["siege_" + sieger if sieger != "gleich" else "gleich"] += 1
        for x, s in ((b, "b"), (k, "k")):
            if x["tps"]:
                erg["tps_" + s].append(x["tps"])
            erg["d_" + s].append(x["dauer"])
        erg["einzeln"].append({"aufgabe": a["frage"][:300], "sieger": sieger,
                               "begruendung": stab._kurz(urteil.get("begruendung") if isinstance(urteil, dict) else "", 400),
                               "bisher_text": b["text"][:1500], "kandidat_text": k["text"][:1500]})
    mittel = lambda xs: round(sum(xs) / len(xs), 1) if xs else None  # noqa: E731
    zeile = {"id": db.neue_id("m"), "zeit": time.time(), "platz": p["platz"], "bisher": bisher, "kandidat": kandidat,
             "aufgaben": len(aufgaben), "siege_kandidat": erg["siege_kandidat"], "siege_bisher": erg["siege_bisher"],
             "gleich": erg["gleich"], "tps_bisher": mittel(erg["tps_b"]), "tps_kandidat": mittel(erg["tps_k"]),
             "dauer_bisher": mittel(erg["d_b"]), "dauer_kandidat": mittel(erg["d_k"]), "richter": richter,
             "daten": {"name": p["name"], "einzeln": erg["einzeln"]}}
    db.einfuegen("messungen", zeile)
    return zeile


async def lauf(von_hand: bool = False) -> dict[str, Any]:
    """Ein Revisionslauf: Kandidaten suchen, bis zu MAX_VERGLEICHE messen."""
    from . import systeminfo
    _stand_setzen(laeuft=True, start=time.time(), schritt="sucht Kandidaten", fehler=None, von_hand=von_hand)
    fertig = 0
    try:
        s = await systeminfo.status()
        vram = systeminfo._vram_gesamt(s)
        inst = modellkatalog.lokal_gb()
        try:
            neu = await modellkatalog.neu_bei_ollama(False, vram)
            modellkatalog.einordnen(neu, inst, db.alle("SELECT id, name, titel, art, modell FROM team WHERE aktiv=1"),
                                    {"arbeit": llm.vorgabe("arbeit"), "talk": llm.vorgabe("talk")})
        except Exception:  # noqa: BLE001 -- ohne ollama.com wird trotzdem gemessen, was installiert ist
            neu = None
        paare = []
        for p in await plaetze():
            if not p["modell"]:
                continue
            for k in await kandidaten(p, inst, vram, neu):
                paare.append((p, k))
        # Talk und die meistgenutzten Rollen zuerst -- dort bringt eine Verbesserung am meisten.
        n = _nutzung()
        paare.sort(key=lambda x: (x[0]["platz"] != "vorgabe:talk",
                                  -((n["je_wer"].get((x[0]["rolle"], x[0]["modell"])) or {}).get("aufrufe") or 0)))
        paare = paare[:MAX_VERGLEICHE]
        _stand_setzen(geplant=len(paare), fertig=0)
        for p, k in paare:
            _stand_setzen(schritt=f"{p['name']}: {p['modell']} gegen {k}")
            async with stab._lock:
                try:
                    await vergleichen(p, k)
                    fertig += 1
                    _stand_setzen(fertig=fertig)
                finally:
                    stab.laeuft(None)
        _stand_setzen(laeuft=False, ende=time.time(), schritt=None,
                      ergebnis=f"{fertig} Vergleiche" if paare else "Nichts Neues zu messen: kein installiertes Modell, "
                                                                     "das für einen Platz in Frage kommt und noch nicht gemessen wurde.")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        _stand_setzen(laeuft=False, ende=time.time(), schritt=None, fehler=f"{e.__class__.__name__}: {str(e)[:300]}")
    return stand()


def starten(von_hand: bool = True) -> bool:
    global _lauf
    if _lauf and not _lauf.done():
        return False
    _lauf = asyncio.create_task(llm.mit_zweck("revision", lauf(von_hand)))
    return True


def abbrechen() -> bool:
    """Fuer Current Actions. lauf() faengt nur Exception, ein Abbruch ist keine --
    deshalb wird der Stand hier selbst zurueckgesetzt, sonst stuende er fuer immer
    auf "prueft gerade"."""
    if not _lauf or _lauf.done():
        return False
    _lauf.cancel()
    _stand_setzen(laeuft=False, ende=time.time(), schritt=None, fehler="von dir abgebrochen")
    return True


async def schleife() -> None:
    """Nachts einmal: 02--05 Uhr deutscher Zeit, wenn das Team an ist."""
    await asyncio.sleep(60)
    while True:
        try:
            jetzt = datetime.datetime.now(BERLIN)
            heute = jetzt.strftime("%Y-%m-%d")
            if 2 <= jetzt.hour < 5 and stand().get("nacht") != heute and stab.stab_aktiv():
                _stand_setzen(nacht=heute)
                starten(von_hand=False)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(600)


# ---------------------------------------------------------------- Vorschlaege
def _bewerten(m: dict[str, Any]) -> tuple[str, str]:
    k, b, n = m["siege_kandidat"], m["siege_bisher"], m["aufgaben"]
    tk, tb = m.get("tps_kandidat"), m.get("tps_bisher")
    faktor = (tk / tb) if tk and tb else None
    tempo = (f"{faktor:.1f}× so schnell".replace(".", ",") if faktor and faktor >= 1.1 else
             f"nur {faktor:.1f}× so schnell".replace(".", ",") if faktor and faktor < 0.9 else "etwa gleich schnell") if faktor else "Tempo unbekannt"
    if k > b and (not faktor or faktor >= 0.5):
        return "umstellen", f"Im verdeckten Vergleich {k} von {n} vorn, {tempo}."
    if k > b:
        return "abwaegen", f"Im verdeckten Vergleich {k} von {n} vorn, aber {tempo} -- besser, doch deutlich langsamer."
    if k == b and faktor and faktor >= 1.4:
        return "umstellen", f"Im verdeckten Vergleich gleich gut ({m['gleich']}× gleich), dabei {tempo}."
    return "behalten", f"Im verdeckten Vergleich {k} von {n} vorn, {b} hinten, {tempo} -- das bisherige bleibt besser."


async def vorschlaege() -> list[dict[str, Any]]:
    aus = []
    jetzt = {p["platz"]: p for p in await plaetze()}
    verworfen = set(db.einstellung("revision_verworfen", []) or [])
    for m in db.alle("SELECT * FROM messungen WHERE zeit>? ORDER BY zeit DESC", (time.time() - 45 * 86400,)):
        p = jetzt.get(m["platz"])
        if not p or p["modell"] != m["bisher"] or m["id"] in verworfen or any(x.get("messung") == m["id"] for x in aus):
            continue
        if any(x.get("platz") == m["platz"] and x.get("kandidat") == m["kandidat"] for x in aus):
            continue
        art, warum = _bewerten(m)
        if art == "behalten":
            continue
        aus.append({"art": art, "platz": m["platz"], "name": p["name"], "bisher": m["bisher"], "kandidat": m["kandidat"],
                    "messung": m["id"], "zeit": m["zeit"],
                    "titel": f"{p['name']}: {m['kandidat']} statt {m['bisher']}", "warum": warum})
    return aus


def umstellen(platz: str, modell: str, messung: str | None = None) -> dict[str, Any]:
    if not modell or modell not in modellkatalog.lokal_gb():
        raise ValueError("Das Modell ist nicht installiert.")
    if platz.startswith("rolle:"):
        rid = platz.split(":", 1)[1]
        alt = (db.holen("team", rid) or {}).get("modell") or ""
        if db.aendern("team", rid, {"modell": modell}, wer="du", aktion="Modell umgestellt (Revision)") is None:
            raise ValueError("Rolle nicht gefunden.")
    elif platz.startswith("vorgabe:"):
        art = platz.split(":", 1)[1]
        if art not in llm.VORGABEN:
            raise ValueError("Unbekannte Vorgabe.")
        v = db.einstellung("modell_vorgaben", {}) or {}
        alt = v.get(art) or ""
        v[art] = modell
        db.einstellung_setzen("modell_vorgaben", v)
    else:
        raise ValueError("Unbekannter Platz.")
    verlauf = db.einstellung("revision_umgestellt", []) or []
    verlauf.insert(0, {"zeit": time.time(), "platz": platz, "vorher": alt, "nachher": modell, "messung": messung})
    db.einstellung_setzen("revision_umgestellt", verlauf[:30])
    return {"ok": True, "vorher": alt}


def zuruecknehmen(platz: str) -> dict[str, Any]:
    verlauf = db.einstellung("revision_umgestellt", []) or []
    e = next((x for x in verlauf if x["platz"] == platz and not x.get("zurueck")), None)
    if not e:
        raise ValueError("Keine Umstellung zum Zurücknehmen.")
    if platz.startswith("rolle:"):
        db.aendern("team", platz.split(":", 1)[1], {"modell": e["vorher"]}, wer="du", aktion="Modell zurückgestellt (Revision)")
    else:
        v = db.einstellung("modell_vorgaben", {}) or {}
        art = platz.split(":", 1)[1]
        if e["vorher"]:
            v[art] = e["vorher"]
        else:
            v.pop(art, None)
        db.einstellung_setzen("modell_vorgaben", v)
    e["zurueck"] = time.time()
    db.einstellung_setzen("revision_umgestellt", verlauf)
    return {"ok": True}


def verwerfen(messung: str) -> None:
    v = db.einstellung("revision_verworfen", []) or []
    if messung not in v:
        v.append(messung)
    db.einstellung_setzen("revision_verworfen", v[-200:])


def neue_rollen(neu: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Aus der Einordnung: Faehigkeiten, fuer die es keine Rolle gibt -- mit den Modellen, die sie koennten."""
    rollen: dict[str, dict[str, Any]] = {}
    for f in (neu or {}).get("familien") or []:
        r = (f.get("einordnung") or {}).get("neue_rolle")
        if not r:
            continue
        x = rollen.setdefault(r["name"], {**r, "modelle": []})
        passend = [a for a in f["ausgaben"] if "passt nicht" not in (a.get("passt") or "")]
        if passend:
            a = passend[-1]
            x["modelle"].append({"name": a["name"], "gb": a["gb"], "installiert": bool(a.get("installiert")),
                                 "familie": f["familie"], "beschreibung": (f.get("beschreibung") or "")[:160]})
    for x in rollen.values():
        x["modelle"] = sorted(x["modelle"], key=lambda m: (not m["installiert"], -m["gb"]))[:3]
    return list(rollen.values())


def laden_vorschlaege(neu: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Neue Modelle bei Ollama, die fuer eine bestehende Rolle in Frage kommen: laden, dann misst die naechste Nacht."""
    aus = []
    for f in (neu or {}).get("familien") or []:
        e = f.get("einordnung") or {}
        if not e.get("rollen") or e.get("aelter"):
            continue
        offen = [a for a in f["ausgaben"] if not a.get("installiert") and "passt nicht" not in (a.get("passt") or "")]
        if not offen:
            continue
        a = offen[-1]
        aus.append({"name": a["name"], "gb": a["gb"], "passt": a["passt"], "rollen": e["rollen"], "plaetze": e.get("plaetze") or [],
                    "ersetzt": e.get("ersetzt") or [],
                    "familie": f["familie"], "neuer": f.get("neuer"), "beschreibung": (f.get("beschreibung") or "")[:200]})
    aus.sort(key=lambda x: (not x["neuer"], -len(x["rollen"])))
    # Zehn statt sechs, seit die Vorschlaege je Rolle im Team-Schaubild stehen:
    # bei sechs fiel fuer die hinteren Rollen nie etwas ab.
    return aus[:10]


# ---------------------------------------------------------------- Team-Uebersicht
# Veiko, 17.10.2026: "eine Uebersicht vom Team mit den Vorschlaegen, welche Rolle
# welches Modell, ob ich es laden will und ob das vorherige dann ueberhaupt noch
# gebraucht wird und ich es ersetzen kann." Diese beiden Funktionen liefern die
# zwei Fragen, die die Oberflaeche dafuer nicht selbst beantworten kann.
def geladen_ungemessen(neu: dict[str, Any] | None) -> dict[str, list[str]]:
    """Platz -> installierte Modelle, die laut Einordnung fuer ihn taugen, fuer
    diesen Platz aber noch nicht gemessen sind ("geladen, misst heute Nacht")."""
    gemessen = {(m["platz"], m["kandidat"]) for m in db.alle("SELECT platz, kandidat FROM messungen")}
    aus: dict[str, list[str]] = {}
    for f in (neu or {}).get("familien") or []:
        e = f.get("einordnung") or {}
        if e.get("aelter"):
            continue
        for a in f["ausgaben"]:
            if not a.get("installiert"):
                continue
            for p in e.get("plaetze") or []:
                if (p, a["name"]) not in gemessen and a["name"] not in aus.get(p, []):
                    aus.setdefault(p, []).append(a["name"])
    return aus


async def gebraucht_von() -> dict[str, list[dict[str, str]]]:
    """Installiertes Modell -> wer es braucht. art "fest": wird gerade benutzt,
    Entfernen ist gesperrt. art "hinweis": zuletzt benutzt, Entfernen geht mit
    Rueckfrage. Was hier fehlt, wird von nichts im Cockpit gebraucht."""
    aus: dict[str, list[dict[str, str]]] = {}

    def dazu(name: str, art: str, text: str) -> None:
        if name and not any(x["text"] == text for x in aus.get(name, [])):
            aus.setdefault(name, []).append({"art": art, "text": text})

    pl = await plaetze()
    for p in pl:
        dazu(p["modell"], "fest", f"rechnet für {p['name']}")
        if p.get("eigen") and p["eigen"] != p["modell"]:
            dazu(p["eigen"], "fest", f"bei {p['name']} eingetragen")
    jason = next((p for p in pl if p["rolle"] == "pmo"), None)
    for k, text in llm.VORGABEN.items():
        # Die Vorgabe "stab" greift NUR, wenn Jason kein eigenes Modell hat
        # (stab.py: modell_fuer("pmo", vorgabe("stab"))). Hat er eines, ist sie ein
        # blosser Rueckfall -- und fehlt sie, springt modell_waehlen auf die
        # Arbeits-Vorgabe. Als "fest" haette sie llama3.3:70b (42 GB) fuer immer
        # gesperrt, obwohl seit dem 17.10. niemand mehr damit rechnet.
        if k == "stab" and jason and jason.get("eigen") and not jason.get("eigen_fehlt"):
            dazu(llm.vorgabe(k), "hinweis", "nur Rückfall für Jason -- er hat ein eigenes Modell")
            continue
        dazu(llm.vorgabe(k), "fest", f"Vorgabe: {text}")
    for name in modellkatalog.lokal_gb():
        if _nicht_text(name):
            dazu(name, "fest", "Suche über Dokumente (Einbettung)")
    # Zwei Namen, dieselben Gewichte (qwen3-coder-neo:30b ist qwen3-coder:30b mit
    # groesserem Fenster). Wird der eine gebraucht, spart Entfernen des anderen
    # keinen Platz -- Ollama loescht geteilte Dateien nicht. Also gesperrt.
    digests = modellkatalog.lokal()
    for name, dg in digests.items():
        for anderer, dg2 in digests.items():
            if anderer != name and dg == dg2 and any(g["art"] == "fest" for g in aus.get(anderer, [])):
                dazu(name, "fest", f"dieselben Gewichte wie {anderer} -- Entfernen spart keinen Platz")
    for z in db.alle("SELECT modell, MAX(zeit) AS zuletzt, COUNT(*) AS n FROM verbrauch WHERE art='lokal' AND zeit>? GROUP BY modell",
                     (time.time() - 14 * 86400,)):
        dazu(z["modell"], "hinweis", f"in den letzten 14 Tagen {z['n']}× benutzt")
    return aus


async def entfernen(name: str, trotzdem: bool = False) -> dict[str, Any]:
    if name not in modellkatalog.lokal_gb():
        raise ValueError("Das Modell ist nicht installiert.")
    gruende = (await gebraucht_von()).get(name, [])
    fest = [g["text"] for g in gruende if g["art"] == "fest"]
    if fest:
        raise ValueError("Wird noch gebraucht: " + "; ".join(fest) + ". Erst umstellen, dann entfernen.")
    if gruende and not trotzdem:
        raise ValueError("Zuletzt noch benutzt: " + "; ".join(g["text"] for g in gruende) + ".")
    gb = modellkatalog.lokal_gb().get(name)
    await modellkatalog.entfernen(name)
    print(f"[revision] Modell entfernt: {name} ({gb} GB)", flush=True)
    return {"ok": True, "gb": gb}


# ---------------------------------------------------------------- Gesamtplan
# Veiko, 17.10.2026: "Die Empfehlungen sollen klar gegeneinander abgewogen sein,
# ich suche das Gesamtoptimum fuer mein Setup." Einzelvorschlaege je Rolle sagen
# nicht, was das GANZE Team auf zwei Karten zu je 24 GB am besten macht. Dieser
# Plan rechnet Varianten fuer die ganze Besetzung durch und waegt sie ab:
#   - Passt jedes Modell auf EINE Karte? (Bedarf = Datei x 1,08 + 1,4 GB
#     Gespraechsspeicher bei 65.536 Token; gemessen 17.10.: qwen3.8:27b 17,7 GB
#     Datei -> 20,3 GB geladen.) Passt es nicht, belegt es beide Karten.
#   - Liegen die Modelle gleichzeitig im Speicher, oder wird bei jedem Wechsel
#     umgeladen? (Ollama haelt hoechstens zwei, OLLAMA_MAX_LOADED_MODELS=2.)
#   - Kann Talk antworten, waehrend das Team schreibt? (Ollama rechnet je Modell
#     nur EINE Anfrage gleichzeitig.)
#   - Bleibt Platz fuer Bilder und Video (ComfyUI braucht ~20 GB auf einer Karte)?
#   - Qualitaet: Messungen der Revision, sonst der Rang im Katalog (AUFGABEN) --
#     und das steht dann so da ("nicht gemessen").
# Nichts wird ohne Klick umgestellt; "Plan uebernehmen" macht die Umstellungen,
# jede einzeln zuruecknehmbar.
KARTE_GB = 23.0


def bedarf_gb(name: str, inst: dict[str, float], geladen: dict[str, float]) -> float:
    if name in geladen:
        return geladen[name]
    return round(inst.get(name, 0) * 1.08 + 1.4, 1)


def _katalog_rang(name: str, aufgabe: str) -> int | None:
    for a in modellkatalog.AUFGABEN:
        if a["id"] == aufgabe:
            kand = [modellkatalog._tag(k) for k in a["kandidaten"]]
            return kand.index(name) if name in kand else None
    return None


def _alltagstempo() -> dict[str, float]:
    """Token je Sekunde im Alltag (aus verbrauch, Lesen eingeschlossen -- deshalb
    niedriger als das reine Schreibtempo; als Vergleich zwischen Modellen taugt es)."""
    aus = {}
    for z in db.alle("SELECT modell, SUM(tok_aus) AS t, SUM(dauer_s) AS d, COUNT(*) AS n FROM verbrauch WHERE art='lokal' "
                     "AND zeit>? AND dauer_s>0 GROUP BY modell", (time.time() - 30 * 86400,)):
        if z["n"] >= 3 and z["d"]:
            aus[z["modell"]] = round(z["t"] / z["d"], 1)
    return aus


def _qualitaet(name: str, aufgabe: str, mess: list[dict[str, Any]]) -> tuple[float, str]:
    """(Punkte, Beleg). Messungen wiegen schwerer als der Katalog."""
    siege = sum((m["siege_kandidat"] - m["siege_bisher"]) for m in mess if m["kandidat"] == name) + \
        sum((m["siege_bisher"] - m["siege_kandidat"]) for m in mess if m["bisher"] == name)
    n = sum(1 for m in mess if name in (m["kandidat"], m["bisher"]))
    rang = _katalog_rang(name, aufgabe)
    punkte = (10 - rang if rang is not None else 2) + 3 * siege
    beleg = (f"{n} Messung{'en' if n != 1 else ''}, Saldo {siege:+d}" if n else "nicht gemessen") + \
            (f", Katalog Rang {rang + 1} für „{aufgabe}“" if rang is not None else f", nicht im Katalog für „{aufgabe}“")
    return punkte, beleg


async def gesamtplan() -> dict[str, Any]:
    inst = {n: g for n, g in modellkatalog.lokal_gb().items() if not _nicht_text(n)}
    geladen = {m["name"]: round(m["size"] / 1e9, 1) for m in await llm.geladene_modelle() if m.get("size")}
    pl = await plaetze()
    mess = db.alle("SELECT * FROM messungen WHERE zeit>?", (time.time() - 60 * 86400,))
    tempo = _alltagstempo()
    arbeit = [p for p in pl if p["rolle"] and p["rolle"] != "cockpit"]
    talk = next((p for p in pl if p["platz"] == "vorgabe:talk"), None)
    neo = next((p for p in pl if p["rolle"] == "cockpit"), None)
    neo_m = neo["modell"] if neo else None
    code = {n for n in inst if "coder" in n or "devstral" in n}
    eine_karte = {n for n in inst if bedarf_gb(n, inst, geladen) <= KARTE_GB}

    def wert(name: str, aufgabe: str) -> tuple[float, str]:
        q, beleg = _qualitaet(name, aufgabe, mess)
        if tempo.get(name):
            beleg += f", im Alltag {tempo[name]:.0f} Token/s"
        return q, beleg

    def bestes(kandidaten: set[str], aufgabe: str, ohne: set[str] = frozenset()) -> str | None:
        k = sorted((n for n in kandidaten if n not in ohne and n not in code),
                   key=lambda n: (-wert(n, aufgabe)[0], -tempo.get(n, 0)))
        return k[0] if k else None

    def variante(name: str, kurz: str, zuordnung: dict[str, str], vorteile: list[str], nachteile: list[str]) -> dict[str, Any]:
        modelle = sorted(set(zuordnung.values()))
        gesamt = round(sum(bedarf_gb(m, inst, geladen) for m in modelle), 1)
        return {"name": name, "kurz": kurz, "zuordnung": zuordnung,
                "modelle": [{"name": m, "gb": bedarf_gb(m, inst, geladen), "eine_karte": m in eine_karte,
                             "wer": [p["name"] for p in pl if zuordnung.get(p["platz"]) == m]} for m in modelle],
                "speicher_gb": gesamt, "gleichzeitig": len(modelle) <= 2 and gesamt <= 2 * KARTE_GB,
                "vorteile": vorteile, "nachteile": nachteile}

    varianten: list[dict[str, Any]] = []
    w = bestes(eine_karte, "denken") or bestes(set(inst), "denken")
    if w:
        _, bw = wert(w, "denken")
        z = {p["platz"]: w for p in arbeit}
        if talk:
            z[talk["platz"]] = w
        varianten.append(variante(
            "Ein Modell für das ganze Team", "einfach, nichts wird zwischen den Rollen umgeladen", z,
            [f"{w} rechnet für alle -- kein Umladen zwischen Rollen ({bw})",
             f"belegt eine Karte ({bedarf_gb(w, inst, geladen)} GB); die zweite bleibt frei für Bilder, Video und Neo"],
            ["Talk wartet, solange das Team schreibt -- ein Modell rechnet eine Anfrage nach der anderen"]))
        partner = {n for n in eine_karte if bedarf_gb(n, inst, geladen) + bedarf_gb(w, inst, geladen) <= 2 * KARTE_GB}
        t = bestes(partner, "schnell", {w})
        if talk and t:
            z = {p["platz"]: w for p in arbeit}
            z[talk["platz"]] = t
            qt, bt = wert(t, "schnell")
            qw, bws = wert(w, "schnell")
            varianten.append(variante(
                "Zwei Modelle, je eine Karte", "Talk antwortet auch, während das Team schreibt", z,
                [f"Talk rechnet auf {t} und wartet nie auf einen Langläufer oder die Pipeline",
                 f"beide passen gleichzeitig in den Speicher ({bedarf_gb(w, inst, geladen)} + {bedarf_gb(t, inst, geladen)} GB)"],
                ["Bilder und Video verdrängen eines der beiden (ComfyUI braucht ~20 GB), danach wird neu geladen",
                 f"Talk: {t} ({bt}) statt {w} ({bws})" + (" -- schwächer eingestuft" if qt < qw else "")]))
        heute = {p["platz"]: p["modell"] for p in arbeit + ([talk] if talk else []) if p["modell"]}
        if heute and all(set(heute.items()) != set(v["zuordnung"].items()) for v in varianten):
            nachteile = []
            mh = set(heute.values())
            for m in sorted(mh):
                if m not in eine_karte:
                    wer = ", ".join(p["name"] for p in pl if heute.get(p["platz"]) == m)
                    nachteile.append(f"{m} ({wer}) braucht {bedarf_gb(m, inst, geladen)} GB und passt auf keine einzelne Karte")
            if len(mh) > 2 or sum(bedarf_gb(m, inst, geladen) for m in mh) > 2 * KARTE_GB:
                nachteile.append("die Modelle passen nicht gleichzeitig in den Speicher: bei jedem Wechsel zwischen den Rollen "
                                 "wird umgeladen (10 bis 30 Sekunden), und Bilder haben keinen Platz")
            varianten.append(variante("Heutige Besetzung", "so, wie es gerade eingestellt ist", heute,
                                      ["läuft heute so, nichts muss umgestellt werden"], nachteile))

    def kosten(v: dict[str, Any]) -> float:
        k = (3.0 if not v["gleichzeitig"] else 0.0) + sum(2.0 for m in v["modelle"] if not m["eine_karte"])
        if v["name"].startswith("Zwei"):
            k += -1.5 + (2.5 if any("schwächer" in n for n in v["nachteile"]) else 0)
        return k

    empfohlen = min(varianten, key=kosten)["name"] if varianten else None
    frei: list[dict[str, Any]] = []
    if empfohlen:
        v = next(x for x in varianten if x["name"] == empfohlen)
        bleibt = set(v["zuordnung"].values()) | ({neo_m} if neo_m else set())
        digests = modellkatalog.lokal()
        bleibt_dg = {digests.get(m) for m in bleibt}
        frei = [{"name": n, "gb": g} for n, g in sorted(inst.items(), key=lambda x: -x[1])
                if n not in bleibt and digests.get(n) not in bleibt_dg]
    return {"varianten": varianten, "empfohlen": empfohlen, "neo": neo_m, "frei": frei, "gemessen": bool(mess),
            "hinweis": None if mess else ("Noch keine Messung der Revision auf diesem Server -- die Abwägung stützt sich auf "
                                          "Katalog, Größe und Alltagstempo. Die nächste Nachtrevision liefert echte Vergleiche.")}


def plan_uebernehmen(zuordnung: dict[str, str]) -> list[str]:
    getan = []
    for platz, modell in zuordnung.items():
        try:
            r = umstellen(platz, modell, None)
            if r.get("vorher") != modell:
                getan.append(f"{platz.split(':', 1)[1]}: {r.get('vorher') or 'Vorgabe'} → {modell}")
        except ValueError as e:
            getan.append(f"{platz}: nicht umgestellt ({e})")
    return getan
