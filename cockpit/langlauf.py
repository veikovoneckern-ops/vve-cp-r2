"""
LANGLAEUFER -- ein langes Vorhaben laeuft durch, ohne dass Veiko jedes Mal eingreift.

Veiko (17.10.2026): "wie schaffe ich es, ein langes aufwendiges Projekt wie ein
grosses Buch oder ein langes Video einfach durchlaufen zu lassen? Also dass
automatisch Zwischenpruefungen durch Dario oder Demmis stattfinden, ohne dass
ich jedes Mal eingreifen muss?"

Die normale Pipeline (stab.ausarbeiten) liefert EIN Ergebnis aus einem Auftrag;
fuer ein Buch mit zwanzig Kapiteln reicht das nicht -- das Modell verliert den
Faden, und niemand Unabhaengiges sieht zwischendurch drauf. Ein Langlaeufer
zerlegt das Vorhaben deshalb in Etappen und arbeitet sie nacheinander ab:

  1. PLANEN      die ausfuehrende Rolle (Neal, Ridley, Clayton) plant die Etappen
  2. ETAPPE      sie schreibt eine Etappe mit Plan, Kurzfassungen und Hinweisen
  3. DANIEL      prueft lokal; "nachbessern" -> genau eine Ueberarbeitung
  4. EXTERN      alle N Etappen (und nach der letzten) liest Dario oder Demmis
                 die juengsten Etappen: weiter / nachbessern / anhalten.
                 Hinweise gelten fuer alle folgenden Etappen.
  5. FERTIG      ein Ergebnis aus allen Etappen (Buch/Dokument als Word-faehiges
                 Markdown; beim Video ein Drehbuch, aus dem video.py rechnet)

Drei Regeln halten es im Zaum:
- **Das Budget ist die Zustimmung.** Mit dem Start legt Veiko fest, wie viel die
  Externen kosten duerfen (US-$, dieselben Preise wie die Seite Verbrauch). Reicht
  der Rest fuer eine Pruefung nicht mehr, laeuft es LOKAL weiter und das steht im
  Verlauf -- eine Pruefung, die das Budget sprengt, geht nie raus.
- **Angehalten wird nur, wenn es ohne Veiko nicht weitergeht**: wenn der Externe
  "anhalten" sagt (Richtung grundlegend falsch oder eine Entscheidung, die nur
  Veiko treffen kann). Dann steht eine Rueckfrage im Briefing; nach seiner
  Antwort geht es von selbst weiter. Daniels Rueckfragen halten NICHT an -- sie
  stehen als Mangel an der Etappe.
- **Ein Neustart verliert hoechstens die laufende Etappe**: der Stand steht nach
  jeder Etappe in der Datenbank.

Ein Langlaeufer ist zugleich ein Vorgang (quelle "langlauf"): Verlauf, Ergebnis,
Kostenbuchung und die Anzeige "arbeitet gerade" funktionieren damit wie ueberall.
Die Pipeline (stab.durchgang) ueberspringt ihn, weil sein Auftrag "langlauf" traegt.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import traceback
from typing import Any

from . import db, llm, stab, video
from .konfig import MODELL_ARBEIT

ARTEN = {
    "buch": {"name": "Buch", "rolle": "buch", "etappe": "Kapitel", "mehrzahl": "Kapitel"},
    "dokument": {"name": "Langes Dokument", "rolle": "stratege", "etappe": "Teil", "mehrzahl": "Teile"},
    "video": {"name": "Langes Video", "rolle": "video", "etappe": "Akt", "mehrzahl": "Akte"},
}
PRUEFER = ("dario", "demmis")
MAX_ETAPPEN = 40
SZENEN_JE_AKT = 12           # ein Akt ~ eine Minute Video
TAKT_SEK = 30
FEHLER_MAX = 3
AUS_TOKEN_SCHAETZUNG = 5000  # so viel schreibt eine Pruefung hoechstens etwa
_weck = asyncio.Event()


def wecken() -> None:
    _weck.set()


# ---------------------------------------------------------------- Stand
def holen(lid: str) -> dict[str, Any] | None:
    return db.holen("langlaeufe", lid)


def _speichern(l: dict[str, Any], **spalten: Any) -> None:
    werte = {"daten": l["daten"], "geaendert": time.time(), **spalten}
    sets = ",".join(f"{k}=?" for k in werte)
    db.ausfuehren(f"UPDATE langlaeufe SET {sets} WHERE id=?",
                  [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in werte.values()] + [l["id"]])
    l.update(spalten)


def liste(projekt_id: str | None = None) -> list[dict[str, Any]]:
    sql, args = "SELECT * FROM langlaeufe", []
    if projekt_id:
        sql += " WHERE projekt_id=?"
        args.append(projekt_id)
    return [ansicht(l) for l in db.alle(sql + " ORDER BY geaendert DESC", args)]


def ansicht(l: dict[str, Any]) -> dict[str, Any]:
    """Fuer die Oberflaeche: ohne die vollen Etappentexte (die holt die Einzelansicht)."""
    d = l.get("daten") or {}
    et = d.get("etappen") or []
    jetzt = stab.ZUSTAND.get("laeuft") or {}
    return {**{k: l[k] for k in ("id", "vorgang_id", "projekt_id", "titel", "art", "stand", "budget", "erstellt", "geaendert")},
            "art_name": ARTEN.get(l["art"], {}).get("name", l["art"]),
            "etappe_name": ARTEN.get(l["art"], {}).get("etappe", "Etappe"),
            "etappen_name": ARTEN.get(l["art"], {}).get("mehrzahl", "Etappen"),
            "etappen": len(et), "fertig": sum(1 for e in et if e.get("stand") == "fertig"),
            "kosten": round(d.get("kosten") or 0, 4), "pruefer": d.get("pruefer"), "pruef_alle": d.get("pruef_alle"),
            "rolle": d.get("rolle"), "rolle_name": stab.rollen_name(d.get("rolle")),
            "grund": d.get("grund"), "fehler": d.get("fehler"), "ergebnis_id": d.get("ergebnis_id"),
            "pruefungen": len(d.get("pruefungen") or []),
            "arbeitet": bool(jetzt.get("vorgang_id") and jetzt.get("vorgang_id") == l.get("vorgang_id")),
            "was": jetzt.get("was") if jetzt.get("vorgang_id") == l.get("vorgang_id") else None}


def einzeln(lid: str) -> dict[str, Any] | None:
    l = holen(lid)
    if not l:
        return None
    d = l.get("daten") or {}
    return {**ansicht(l), "auftrag": d.get("auftrag"), "etappenliste": d.get("etappen") or [],
            "pruefungsliste": d.get("pruefungen") or [], "hinweise": d.get("hinweise") or [],
            "extern_aus": d.get("extern_aus")}


# ---------------------------------------------------------------- Anlegen und Steuern
def anlegen(titel: str, auftrag: str, art: str, projekt_id: str | None, pruefer: str, pruef_alle: int,
            budget: float, rolle: str | None = None) -> dict[str, Any]:
    titel, auftrag = (titel or "").strip()[:120], (auftrag or "").strip()
    if len(auftrag) < 20:
        raise ValueError("Beschreib das Vorhaben in ein paar Sätzen -- daraus plant das Team die Etappen.")
    if art not in ARTEN:
        raise ValueError("Unbekannte Art.")
    if pruefer not in PRUEFER:
        raise ValueError("Zwischenprüfung durch Dario oder Demmis.")
    rolle = rolle if rolle in stab.ROLLEN_FUER_ARBEIT else ARTEN[art]["rolle"]
    titel = titel or auftrag[:80]
    # Der Vorgang traegt den Langlaeufer im Briefing, im Verlauf und am Ergebnis.
    v = stab.aus_text(f"Langläufer „{titel}“: {auftrag}", quelle="langlauf", projekt_id=projekt_id)
    vid = v["id"] if isinstance(v, dict) else v
    db.ausfuehren("UPDATE vorgaenge SET titel=?, stand='in_arbeit', auftrag=?, einordnung=? WHERE id=?",
                  (f"Langläufer: {titel}"[:120],
                   json.dumps({"auftrag": auftrag, "langlauf": True, "rolle": rolle, "form": "dokument"}, ensure_ascii=False),
                   "Langläufer -- arbeitet in Etappen, mit Zwischenprüfung", vid))
    lid = db.neue_id("l")
    db.einfuegen("langlaeufe", {
        "id": lid, "vorgang_id": vid, "projekt_id": projekt_id, "titel": titel, "art": art, "stand": "plant",
        "budget": max(0.0, float(budget or 0)), "erstellt": time.time(), "geaendert": time.time(),
        "daten": {"auftrag": auftrag, "rolle": rolle, "pruefer": pruefer, "pruef_alle": max(1, min(10, int(pruef_alle or 3))),
                  "etappen": [], "hinweise": [], "pruefungen": [], "kosten": 0.0, "fehlversuche": 0}})
    db.ereignis(vid, "du", "auftrag",
                f"Langläufer gestartet: {ARTEN[art]['name']}, {stab.rollen_name(rolle)} arbeitet, "
                f"{'Dario' if pruefer == 'dario' else 'Demmis'} prüft nach je {pruef_alle} {ARTEN[art]['mehrzahl']}, "
                f"Budget $ {float(budget or 0):.2f}.")
    wecken()
    return einzeln(lid) or {}


def steuern(lid: str, aktion: str, d: dict[str, Any]) -> dict[str, Any]:
    l = holen(lid)
    if not l:
        raise ValueError("Langläufer nicht gefunden.")
    daten = l["daten"]
    vid = l["vorgang_id"]
    if aktion == "pausieren":
        if l["stand"] in ("fertig", "abgebrochen"):
            raise ValueError("Der Langläufer ist schon beendet.")
        daten["stand_vorher"] = l["stand"]
        _speichern(l, stand="pausiert")
        db.ereignis(vid, "du", "info", "Langläufer pausiert.")
    elif aktion == "fortsetzen":
        if l["stand"] not in ("pausiert", "fehler", "wartet"):
            raise ValueError("Der Langläufer läuft schon.")
        daten["fehlversuche"] = 0
        daten["fehler"] = None
        neu = daten.pop("stand_vorher", None) or ("laeuft" if daten.get("etappen") else "plant")
        if l["stand"] == "wartet":
            # Fortsetzen ohne Antwort: die offene Rueckfrage gilt als uebergangen.
            for e in db.alle("SELECT id FROM entscheidungen WHERE vorgang_id=? AND stand='offen'", (vid,)):
                db.ausfuehren("UPDATE entscheidungen SET stand='nein', antwort=?, erledigt=? WHERE id=?",
                              ("(ohne Antwort fortgesetzt)", time.time(), e["id"]))
            neu = "laeuft"
        _speichern(l, stand=neu if neu != "wartet" else "laeuft")
        db.ereignis(vid, "du", "info", "Langläufer fortgesetzt.")
        wecken()
    elif aktion == "budget":
        b = max(0.0, float(d.get("budget") or 0))
        daten["extern_aus"] = None
        _speichern(l, budget=b)
        db.ereignis(vid, "du", "info", f"Budget für Zwischenprüfungen: $ {b:.2f}.")
    elif aktion == "hinweis":
        t = str(d.get("text") or "").strip()
        if not t:
            raise ValueError("Der Hinweis ist leer.")
        daten.setdefault("hinweise", []).append({"zeit": time.time(), "von": "Veiko", "text": t[:2000]})
        _speichern(l)
        db.ereignis(vid, "du", "antwort", f"Hinweis für die nächsten Etappen: {t}")
    elif aktion == "abbrechen":
        _speichern(l, stand="abgebrochen")
        db.ereignis(vid, "du", "info", "Langläufer abgebrochen. Die fertigen Etappen bleiben erhalten.")
        stab._auftrag_erledigt(vid)
        stab.stand_berechnen(vid)
    elif aktion == "zusammenfassen":
        # Vorzeitig ein Ergebnis aus dem bisher Fertigen -- ohne den Lauf zu beenden.
        return {"ergebnis_id": _abschliessen(l, vorlaeufig=True)}
    else:
        raise ValueError("Unbekannte Aktion.")
    return einzeln(lid) or {}


# ---------------------------------------------------------------- Bausteine
def _system(rid: str, art: str) -> str:
    r = stab.rolle(rid)
    form = stab.FORM_ANWEISUNG["dokument"] if art != "video" else ""
    return (f"Du bist {r.get('name')}, {r.get('titel')} in Veiko von Eckerns KI-Team. {r.get('kurz') or ''}\n\n"
            "Du arbeitest an einem LANGEN Vorhaben, Etappe für Etappe. Keine Vorrede, keine Meta-Kommentare. "
            f"{form}\nREGELN: Schreibe Deutsch. Erfinde keine Fakten über reale Personen, Firmen oder Zahlen. "
            "Halte Figuren, Begriffe, Ton und Zeitform über alle Etappen gleich. Beachte die HINWEISE der Prüfer -- "
            "sie gelten ab jetzt für jede Etappe.\n\nGEDÄCHTNIS (nur zum Verstehen von Namen):\n" + stab.gedaechtnis_text())


def _hinweise_text(d: dict[str, Any]) -> str:
    h = d.get("hinweise") or []
    return ("HINWEISE DER PRÜFER UND VON VEIKO (gelten weiter):\n" + "\n".join(f"- ({x['von']}) {x['text']}" for x in h[-15:])) if h else ""


def _plan_text(d: dict[str, Any], art: str) -> str:
    n = ARTEN[art]["etappe"]
    return "\n".join(f"{n} {e['nr']}: {e['titel']} -- {e.get('inhalt') or ''}" for e in d.get("etappen") or [])


async def _planen(l: dict[str, Any]) -> None:
    d, art, vid = l["daten"], l["art"], l["vorgang_id"]
    rid = d["rolle"]
    modell = await stab.modell_fuer(rid, MODELL_ARBEIT)
    if not modell:
        raise llm.ModellFehler("Kein passendes lokales Modell installiert.")
    stab.laeuft(rid, f"plant den Langläufer „{l['titel']}“", vid)
    n = ARTEN[art]["etappe"]
    extra = (f" Jeder {n} ist etwa eine Minute Video (rund {SZENEN_JE_AKT} Szenen zu je 5 Sekunden)." if art == "video" else
             " Jede Etappe wird 1.500 bis 5.000 Wörter lang.")
    frage = (f"VORHABEN: {d['auftrag']}\n\n{stab._vorgang_kontext(db.holen('vorgaenge', vid) or {'id': vid})[:20000]}\n\n"
             f"PLANE das Vorhaben in Etappen ({n}). Antworte AUSSCHLIESSLICH mit JSON: "
             '{"titel": "...", "etappen": [{"titel": "...", "inhalt": "was hineingehört, drei bis fünf Sätze"}]}. '
             f"Zwischen 3 und {MAX_ETAPPEN} Etappen, so viele, wie das Vorhaben wirklich braucht.{extra} "
             "Wenn das Vorhaben eine Länge nennt (Seiten, Minuten, Kapitel), halte dich daran.")
    plan = llm.json_aus(await stab._chat_robust(modell, _system(rid, art), [{"role": "user", "content": frage}],
                                                json_format=True, temperatur=0.3, denken=stab.DENKEN,
                                                num_ctx=65536, timeout=stab.LANGE_FRIST))
    etappen = [x for x in ((plan or {}).get("etappen") if isinstance(plan, dict) else None) or []
               if isinstance(x, dict) and str(x.get("titel") or "").strip()][:MAX_ETAPPEN]
    if len(etappen) < 2:
        raise llm.ModellFehler("Der Plan enthielt keine lesbaren Etappen.")
    d["etappen"] = [{"nr": i + 1, "titel": stab._kurz(x["titel"], 120), "inhalt": stab._kurz(x.get("inhalt"), 800),
                     "stand": "offen"} for i, x in enumerate(etappen)]
    if isinstance(plan, dict) and plan.get("titel"):
        d["werk_titel"] = stab._kurz(plan["titel"], 120)
    _speichern(l, stand="laeuft")
    db.ereignis(vid, rid, "info", f"Plan mit {len(etappen)} Etappen ({n}):\n" + _plan_text(d, art))


def _etappen_kontext(d: dict[str, Any], e: dict[str, Any], art: str) -> str:
    fertig = [x for x in d["etappen"] if x.get("stand") == "fertig" and x["nr"] < e["nr"]]
    kurz = "\n".join(f"{x['nr']}. {x['titel']}: {x.get('kurz') or ''}" for x in fertig)
    vorige = fertig[-1].get("text", "")[-6000:] if fertig else ""
    teile = [f"VORHABEN: {d['auftrag']}", "GESAMTPLAN:\n" + _plan_text(d, art)]
    if kurz:
        teile.append("BISHER GESCHRIEBEN (Kurzfassungen):\n" + kurz)
    if vorige:
        teile.append("ENDE DER VORIGEN ETAPPE (daran schließt du an):\n…" + vorige)
    h = _hinweise_text(d)
    if h:
        teile.append(h)
    return "\n\n".join(teile)


async def _etappe(l: dict[str, Any], e: dict[str, Any]) -> None:
    d, art, vid = l["daten"], l["art"], l["vorgang_id"]
    rid = d["rolle"]
    modell = await stab.modell_fuer(rid, MODELL_ARBEIT)
    if not modell:
        raise llm.ModellFehler("Kein passendes lokales Modell installiert.")
    n, gesamt = ARTEN[art]["etappe"], len(d["etappen"])
    system = _system(rid, art)
    v = db.holen("vorgaenge", vid) or {"id": vid}
    grund = _etappen_kontext(d, e, art) + "\n\n" + stab._vorgang_kontext(v)[:15000]
    stab.laeuft(rid, f"Langläufer: schreibt {n} {e['nr']} von {gesamt}", vid)
    if art == "video":
        frage = (grund + f"\n\nSchreibe JETZT NUR {n} {e['nr']}: „{e['titel']}“ -- {e.get('inhalt') or ''}\n"
                 + video.DREHBUCH_ANWEISUNG.replace("höchstens 16", f"höchstens {SZENEN_JE_AKT}")
                 + f" Dies ist ein Teil eines längeren Videos: kein Vorspann, kein Abspann, außer im ersten bzw. letzten {n}.")
        text = await stab._chat_robust(modell, system, [{"role": "user", "content": frage}], temperatur=0.6,
                                       denken=stab.DENKEN_SCHREIBEN, num_ctx=65536, timeout=stab.LANGE_FRIST)
        if not video.drehbuch_aus(text, SZENEN_JE_AKT):
            raise llm.ModellFehler(f"{n} {e['nr']}: kein lesbarer Szenen-Block.")
    else:
        frage = (grund + f"\n\nSchreibe JETZT NUR {n} {e['nr']} von {gesamt}: „{e['titel']}“ -- {e.get('inhalt') or ''}\n"
                 f"Beginne mit der Zeile „## {e['titel']}“. Ausführlich und vollständig; keine Wiederholung früherer Etappen, "
                 "kein Vorgriff auf spätere.")
        text = (await stab.abschnittsweise(modell, system, frage, "dokument", rid, vid)
                or await stab._chat_robust(modell, system, [{"role": "user", "content": frage}], temperatur=0.6,
                                           denken=stab.DENKEN_SCHREIBEN, num_ctx=65536, timeout=stab.LANGE_FRIST))
        text = _ueberschriften_eine_ebene_tiefer(text, e["titel"])
    if not text.strip():
        raise llm.ModellFehler(f"{n} {e['nr']}: leer.")
    # Daniel prueft lokal; "nachbessern" -> genau eine Ueberarbeitung. Eine
    # Rueckfrage haelt den Lauf NICHT an -- sie steht als Mangel an der Etappe.
    stab.laeuft("kritiker", f"Langläufer: prüft {n} {e['nr']}", vid)
    a = {"auftrag": f"{d['auftrag']} -- {n} {e['nr']}: {e['titel']}: {e.get('inhalt') or ''}", "form": "video" if art == "video" else "dokument"}
    p = await stab.pruefen(text, a, v)
    if p.get("urteil") in ("nachbessern", "rueckfrage") and (p.get("maengel") or p.get("frage")):
        stab.laeuft(rid, f"Langläufer: überarbeitet {n} {e['nr']}", vid)
        kritik = (p.get("begruendung") or "") + "\n" + "\n".join("- " + m for m in p.get("maengel") or [])
        if p.get("frage"):
            kritik += f"\n- Offene Frage (nicht raten, als „fehlt:“ markieren): {p['frage']}"
        neu = await stab._chat_robust(modell, system, [{"role": "user", "content":
                                      grund + f"\n\nDEIN ENTWURF FÜR {n} {e['nr']}:\n{text[:60000]}\n\nKRITIK VON DANIEL:\n{kritik}\n\n"
                                      "Überarbeite und liefere die vollständige Etappe."
                                      + (" Behalte den ```json-Szenenblock bei." if art == "video" else "")}],
                                      temperatur=0.5, denken=stab.DENKEN_SCHREIBEN, num_ctx=65536, timeout=stab.LANGE_FRIST)
        if neu.strip() and (art != "video" or video.drehbuch_aus(neu, SZENEN_JE_AKT)):
            text = neu if art == "video" else _ueberschriften_eine_ebene_tiefer(neu, e["titel"])
            e["ueberarbeitet"] = "Daniel"
    e["daniel"] = {"urteil": p.get("urteil"), "begruendung": p.get("begruendung"), "maengel": p.get("maengel") or []}
    e["text"] = text
    e["kurz"] = await _kurzfassung(modell, text)
    d["modell"] = modell
    e["stand"] = "fertig"
    e["zeit"] = time.time()
    _speichern(l)
    db.ereignis(vid, rid, "info", f"{n} {e['nr']} von {gesamt} fertig: {e['titel']} "
                                  f"({len(text.split())} Wörter, Daniel: {stab.urteil_klartext(p)}).")


def _ueberschriften_eine_ebene_tiefer(text: str, titel: str) -> str:
    """Aus "# Kapitel / ## Abschnitt" der Etappe wird "## / ###" -- die oberste
    Ebene gehoert dem ganzen Werk."""
    t = text.strip()
    if re.match(r"^#\s", t):
        t = re.sub(r"(?m)^(#{1,5})\s", lambda m: "#" + m.group(1) + " ", t)
    if not t.startswith("## "):
        t = f"## {titel}\n\n{t}"
    return t


async def _kurzfassung(modell: str, text: str) -> str:
    try:
        k = await llm.chat(modell, "Fasse zusammen. Deutsch, höchstens vier Sätze, nur Inhalt: was passiert, "
                                   "welche Figuren/Begriffe/Fakten eingeführt wurden.",
                           [{"role": "user", "content": text[:40000]}], temperatur=0.2, denken=False,
                           num_ctx=32768, timeout=600)
        return stab._kurz(k, 900)
    except llm.ModellFehler:
        return stab._kurz(re.sub(r"\s+", " ", text), 400)


# ---------------------------------------------------------------- Externe Pruefung
def _preise() -> dict[str, list[float]]:
    from .api import _preise as p
    return p()


def _usd(anbieter: str, ein: int, aus: int) -> float:
    pr = _preise().get(anbieter)
    return (ein / 1e6 * pr[0] + aus / 1e6 * pr[1]) if pr else 0.0


PRUEF_EXTERN = """Du bist {name} und prüfst als unabhängige Zwischeninstanz ein langes Vorhaben, das ein lokales KI-Team für Veiko von Eckern Etappe für Etappe schreibt. Veiko greift nicht ein; deine Hinweise steuern die folgenden Etappen.
Antworte AUSSCHLIESSLICH mit JSON:
{{"urteil": "weiter|nachbessern|anhalten", "begruendung": "zwei bis vier Sätze für Veiko", "hinweise": ["konkrete Anweisung für alle folgenden Etappen", "..."], "nachbessern": [{{"nr": 3, "was": "was genau an dieser Etappe zu ändern ist"}}], "frage": "nur bei anhalten: die eine Frage an Veiko"}}
- weiter: trägt; Hinweise optional.
- nachbessern: einzelne der GELIEFERTEN Etappen haben Mängel (Widersprüche, Faktenfehler, Ton, Wiederholungen, Plan verfehlt) -- nenne sie in "nachbessern".
- anhalten: NUR wenn die Richtung grundlegend falsch ist oder etwas fehlt, das nur Veiko entscheiden kann. Das hält die Arbeit an.
Höchstens fünf Hinweise, je ein Satz, umsetzbar. Deutsch."""


async def _extern_pruefen(l: dict[str, Any], letzte: list[dict[str, Any]], schluss: bool) -> None:
    from . import teamchat
    from .konfig import ALT_TOKEN
    d, art, vid = l["daten"], l["art"], l["vorgang_id"]
    wer = d["pruefer"]
    x = teamchat.EXTERNE[wer]
    if not ALT_TOKEN:
        _extern_aus(l, "Für Dario und Demmis fehlt der Zugang zum alten Backend (VVEC_ALT_TOKEN) -- es läuft lokal weiter.")
        return
    n = ARTEN[art]["etappe"]
    fertig = [e for e in d["etappen"] if e.get("stand") == "fertig"]
    frueher = "\n".join(f"{e['nr']}. {e['titel']}: {e.get('kurz') or ''}" for e in fertig if e not in letzte)
    block = "\n\n".join(f"===== {n} {e['nr']}: {e['titel']} =====\n{e.get('text', '')[:60000]}" for e in letzte)
    frage = (f"VORHABEN: {d['auftrag']}\n\nGESAMTPLAN:\n{_plan_text(d, art)}\n\n"
             + (f"FRÜHERE ETAPPEN (Kurzfassungen):\n{frueher}\n\n" if frueher else "")
             + (_hinweise_text(d) + "\n\n" if d.get("hinweise") else "")
             + f"ZU PRÜFEN ({'letzte Etappen -- danach ist das Werk fertig' if schluss else 'die jüngsten Etappen'}):\n{block[:160000]}")
    system = PRUEF_EXTERN.format(name=x["name"])
    # Kostensperre: geschaetzt wird VOR dem Aufruf (Zeichen/3,5 ein, 5.000 aus).
    schaetzung = _usd(x["anbieter"], int((len(system) + len(frage)) / 3.5), AUS_TOKEN_SCHAETZUNG)
    rest = (l.get("budget") or 0) - (d.get("kosten") or 0)
    if schaetzung > rest:
        _extern_aus(l, f"Budget reicht nicht für die nächste Prüfung durch {x['name']} (geschätzt $ {schaetzung:.2f}, "
                       f"übrig $ {max(rest, 0):.2f}) -- es läuft lokal weiter. Mit mehr Budget prüft {x['name']} wieder.")
        return
    modell = await teamchat._extern_modell(wer)
    stab.laeuft(wer, f"Langläufer: prüft {n} {letzte[0]['nr']}–{letzte[-1]['nr']}", vid)
    t0 = time.time()
    antwort = await teamchat._cloud_chat(wer, modell, system, [{"role": "user", "content": frage}])
    # Tatsaechliche Kosten aus der Buchung, die _cloud_chat gerade geschrieben hat.
    z = db.eine("SELECT SUM(tok_ein) AS ein, SUM(tok_aus) AS aus FROM verbrauch WHERE art='cloud' AND zeit>=? AND wer=?",
                (t0 - 1, wer)) or {}
    kosten = _usd(x["anbieter"], z.get("ein") or 0, z.get("aus") or 0) if (z.get("ein") or z.get("aus")) else schaetzung
    d["kosten"] = (d.get("kosten") or 0) + kosten
    j = llm.json_aus(antwort)
    if not isinstance(j, dict) or j.get("urteil") not in ("weiter", "nachbessern", "anhalten"):
        j = {"urteil": "weiter", "begruendung": f"{x['name']}s Antwort war nicht lesbar; es geht ohne Hinweise weiter.",
             "hinweise": []}
    hinweise = [stab._kurz(h, 400) for h in (j.get("hinweise") or []) if str(h).strip()][:5]
    for h in hinweise:
        d.setdefault("hinweise", []).append({"zeit": time.time(), "von": x["name"], "text": h})
    pr = {"zeit": time.time(), "wer": wer, "name": x["name"], "modell": modell, "von": letzte[0]["nr"], "bis": letzte[-1]["nr"],
          "urteil": j["urteil"], "begruendung": stab._kurz(j.get("begruendung"), 800), "hinweise": hinweise,
          "nachbessern": [], "kosten": round(kosten, 4)}
    for e in letzte:
        e["extern"] = j["urteil"]
    d.setdefault("pruefungen", []).append(pr)
    _speichern(l)
    db.ereignis(vid, wer, "pruefung", f"{x['name']} zu {n} {pr['von']}–{pr['bis']}: {pr['begruendung']}"
                + ("\nHinweise:\n" + "\n".join("- " + h for h in hinweise) if hinweise else ""),
                {"urteil": j["urteil"], "kosten": pr["kosten"]})
    if j["urteil"] == "anhalten":
        frage_v = stab._kurz(j.get("frage") or j.get("begruendung") or "Wie soll es weitergehen?", 600)
        stab.entscheidung_anlegen(vid, "rueckfrage", f"{x['name']} hat den Langläufer „{l['titel']}“ angehalten: {frage_v}",
                                  {"langlauf": l["id"]}, wer=wer)
        d["grund"] = f"{x['name']} hat angehalten: {frage_v}"
        _speichern(l, stand="wartet")
        return
    if j["urteil"] == "nachbessern":
        nummern = {int(nb.get("nr")): str(nb.get("was") or "") for nb in (j.get("nachbessern") or [])
                   if isinstance(nb, dict) and str(nb.get("nr") or "").isdigit()}
        for e in letzte:
            if e["nr"] in nummern:
                await _nachbessern(l, e, f"{x['name']}: {nummern[e['nr']]}")
                pr["nachbessern"].append(e["nr"])
        _speichern(l)


async def _nachbessern(l: dict[str, Any], e: dict[str, Any], kritik: str) -> None:
    d, art, vid = l["daten"], l["art"], l["vorgang_id"]
    rid = d["rolle"]
    modell = await stab.modell_fuer(rid, MODELL_ARBEIT)
    n = ARTEN[art]["etappe"]
    stab.laeuft(rid, f"Langläufer: bessert {n} {e['nr']} nach", vid)
    neu = await stab._chat_robust(modell, _system(rid, art), [{"role": "user", "content":
                                  _etappen_kontext(d, e, art) + f"\n\nDEINE FASSUNG VON {n} {e['nr']} („{e['titel']}“):\n"
                                  f"{e.get('text', '')[:60000]}\n\nKRITIK:\n{kritik}\n\nÜberarbeite und liefere die vollständige Etappe."
                                  + (" Behalte den ```json-Szenenblock bei." if art == "video" else "")}],
                                  temperatur=0.5, denken=stab.DENKEN_SCHREIBEN, num_ctx=65536, timeout=stab.LANGE_FRIST)
    if neu.strip() and (art != "video" or video.drehbuch_aus(neu, SZENEN_JE_AKT)):
        e["text"] = neu if art == "video" else _ueberschriften_eine_ebene_tiefer(neu, e["titel"])
        e["ueberarbeitet"] = kritik.split(":")[0]
        e["kurz"] = await _kurzfassung(modell, e["text"])
        db.ereignis(vid, rid, "info", f"{n} {e['nr']} nachgebessert ({kritik[:200]}).")


def _extern_aus(l: dict[str, Any], grund: str) -> None:
    d = l["daten"]
    if d.get("extern_aus") != grund:
        d["extern_aus"] = grund
        db.ereignis(l["vorgang_id"], "system", "info", grund)
    _speichern(l)


# ---------------------------------------------------------------- Abschluss
def _abschliessen(l: dict[str, Any], vorlaeufig: bool = False) -> str | None:
    d, art, vid = l["daten"], l["art"], l["vorgang_id"]
    fertig = [e for e in d.get("etappen") or [] if e.get("stand") == "fertig"]
    if not fertig:
        raise ValueError("Noch keine Etappe fertig.")
    titel = d.get("werk_titel") or l["titel"]
    v = db.holen("vorgaenge", vid) or {"id": vid, "projekt_id": l.get("projekt_id")}
    letzte = (d.get("pruefungen") or [{}])[-1]
    pruefung = {"urteil": "tragfaehig" if letzte.get("urteil") in ("weiter", None) else "nachbessern",
                "begruendung": (f"{len(fertig)} Etappen, jede von Daniel geprüft"
                                + (f", {len(d.get('pruefungen') or [])} Zwischenprüfungen durch "
                                   f"{letzte.get('name')} ($ {d.get('kosten', 0):.2f})" if d.get("pruefungen") else ", ohne externe Prüfung")
                                + (f". Letztes Wort von {letzte.get('name')}: {letzte.get('begruendung')}" if letzte.get("begruendung") else "")
                                + (" VORLÄUFIG -- der Lauf ist noch nicht fertig." if vorlaeufig else "")),
                "maengel": [m for e in fertig for m in ((e.get("daniel") or {}).get("maengel") or [])][:6]}
    a = {"titel": ("Zwischenstand: " if vorlaeufig else "") + titel, "form": "video" if art == "video" else "dokument"}
    if art == "video":
        szenen = []
        for e in fertig:
            db_ = video.drehbuch_aus(e.get("text", ""), SZENEN_JE_AKT)
            szenen += (db_ or {}).get("szenen") or []
        drehbuch = {"titel": titel, "szenen": szenen}
        text = (f"# {titel}\n\n" + "\n".join(f"- **{ARTEN[art]['etappe']} {e['nr']}: {e['titel']}** -- {e.get('kurz') or ''}" for e in fertig)
                + f"\n\n{len(szenen)} Szenen, etwa {round(len(szenen) * 5 / 60, 1)} Minuten.\n\n```json\n"
                + json.dumps(drehbuch, ensure_ascii=False, indent=1) + "\n```")
    else:
        text = f"# {titel}\n\n" + "\n\n".join(e.get("text", "") for e in fertig)
    eid = stab.ergebnis_speichern(v, a, text, d["rolle"], d.get("modell") or "lokal", [], pruefung)
    if art == "video" and not vorlaeufig:
        if video.starten(eid, drehbuch):
            db.ereignis(vid, d["rolle"], "info", f"Video wird gerechnet: {len(drehbuch['szenen'])} Szenen -- das dauert Stunden. "
                                                 "Es erscheint am Ergebnis, sobald es fertig ist.")
    else:
        from . import folienbilder
        if "dokument" in folienbilder.MIT_BILDERN:
            folienbilder.starten(eid)
    if not vorlaeufig:
        d["ergebnis_id"] = eid
        d["grund"] = None
        _speichern(l, stand="fertig")
        stab._auftrag_erledigt(vid)
        stab.stand_berechnen(vid)
    return eid


# ---------------------------------------------------------------- Schritt und Schleife
async def schritt(l: dict[str, Any]) -> None:
    """Genau EIN Arbeitsschritt: planen, eine Etappe, oder eine Pruefung, oder Abschluss."""
    d = l["daten"]
    if l["stand"] == "plant" or not d.get("etappen"):
        await _planen(l)
        return
    offen = [e for e in d["etappen"] if e.get("stand") != "fertig"]
    fertig = [e for e in d["etappen"] if e.get("stand") == "fertig"]
    # Pruefung faellig? Nach je pruef_alle fertigen Etappen seit der letzten Pruefung, und vor dem Abschluss.
    geprueft_bis = max([p["bis"] for p in d.get("pruefungen") or []] or [0])
    neu_seit = [e for e in fertig if e["nr"] > geprueft_bis]
    # Ist das Budget erschoepft (extern_aus), wird nicht mehr geprueft, bis Veiko
    # es erhoeht -- dann holt die naechste Pruefung alles seit der letzten nach.
    if neu_seit and (len(neu_seit) >= d.get("pruef_alle", 3) or not offen) and not d.get("extern_aus"):
        await _extern_pruefen(l, neu_seit, schluss=not offen)
        return
    if offen:
        await _etappe(l, offen[0])
        return
    _abschliessen(l)


def _naechster() -> dict[str, Any] | None:
    for l in db.alle("SELECT * FROM langlaeufe WHERE stand IN ('plant','laeuft','wartet') ORDER BY geaendert"):
        if l["stand"] == "wartet":
            # Weiter, sobald Veiko die Rueckfrage beantwortet hat; seine Antwort
            # steht dann im Vorgang und geht ueber _vorgang_kontext in jede Etappe.
            if db.wert("SELECT COUNT(*) FROM entscheidungen WHERE vorgang_id=? AND stand='offen'", (l["vorgang_id"],)):
                continue
            antwort = db.eine("SELECT text FROM ereignisse WHERE vorgang_id=? AND art='antwort' ORDER BY zeit DESC LIMIT 1",
                              (l["vorgang_id"],))
            if antwort:
                l["daten"].setdefault("hinweise", []).append({"zeit": time.time(), "von": "Veiko", "text": stab._kurz(antwort["text"], 2000)})
            l["daten"]["grund"] = None
            _speichern(l, stand="laeuft")
            db.ereignis(l["vorgang_id"], "system", "info", "Rückfrage beantwortet -- der Langläufer arbeitet weiter.")
        return l
    return None


async def schleife() -> None:
    await asyncio.sleep(20)
    while True:
        try:
            if stab.stab_aktiv():
                l = _naechster()
                if l:
                    # Dieselbe Sperre wie die Pipeline: Langlaeufer und neue Notizen
                    # wechseln sich ab, statt gleichzeitig um die Karten zu streiten.
                    async with stab._lock:
                        try:
                            await schritt(l)
                            l["daten"]["fehlversuche"] = 0
                            l["daten"]["fehler"] = None
                            _speichern(l)
                        except Exception as e:  # noqa: BLE001 -- ein Fehler stoppt nur diesen Langlaeufer
                            traceback.print_exc()
                            l["daten"]["fehlversuche"] = (l["daten"].get("fehlversuche") or 0) + 1
                            l["daten"]["fehler"] = f"{e.__class__.__name__}: {str(e)[:300]}"
                            stand = "fehler" if l["daten"]["fehlversuche"] >= FEHLER_MAX else l["stand"]
                            _speichern(l, stand=stand)
                            db.ereignis(l["vorgang_id"], "system", "fehler",
                                        f"Langläufer-Schritt gescheitert ({l['daten']['fehlversuche']}. Mal): {e}"
                                        + (" -- angehalten, bitte im Langläufer fortsetzen." if stand == "fehler" else ""))
                        finally:
                            stab.laeuft(None)
                    await asyncio.sleep(2)   # der Pipeline eine Luecke lassen
                    continue
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        _weck.clear()
        try:
            await asyncio.wait_for(_weck.wait(), timeout=TAKT_SEK)
        except asyncio.TimeoutError:
            pass
