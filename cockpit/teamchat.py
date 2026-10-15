"""
DIREKT MIT DEM TEAM SPRECHEN -- ein Gespraech mit genau einem Mitglied.

Zwei Einstiege, EIN Weg (Bauregel 2):
  - Team -> Mitglied -> "Chatten": freies Gespraech mit Jason, Clayton, Neal ...
    oder mit einem der drei Externen (Dario, Elon, Demmis).
  - Ergebnisfenster -> "Weiterarbeiten": dasselbe Gespraech, nur mit dem
    Ergebnis im Kontext. Verlangt Veiko eine Aenderung, liefert das Mitglied
    eine neue Fassung; sie ersetzt den Inhalt des Ergebnisses ueber
    db.aendern (also mit Protokoll und Rueckgaengig) und Daniel prueft sie.

Warum die neue Fassung zwischen festen Marken steht statt als JSON: ein
Buchkapitel in einen JSON-String zu maskieren ist genau die Fleissarbeit, an
der Modelle sich verzaehlen (im alten Cockpit zweimal gemessen bei Neo).

Die Externen laufen ueber den Cloud-Weg des ALTEN Backends (/api/cloud/...).
Die Schluessel liegen nur dort; diese Fassung bekommt keinen eigenen. Jede
Nachricht an einen Externen ist ein bezahlter Aufruf -- die Oberflaeche sagt
das an jeder Nachricht, und es gibt keinen Weg, auf dem der Stab sie von
selbst anspricht.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, AsyncIterator

import httpx

from . import db, llm, stab
from .konfig import ALT_BACKEND, ALT_TOKEN, MODELL_TALK

# Die drei Externen. Namen wie im alten Cockpit (dort Anzeige-Kennungen der
# Anbieter). Die Modellvorgabe ist eine Wunschliste: genommen wird das erste,
# das der Anbieter gerade anbietet.
EXTERNE: dict[str, dict[str, Any]] = {
    "dario": {"name": "Dario", "titel": "Claude · Anthropic", "anbieter": "claude",
              "kurz": "Zweite Meinung mit großem Kontext: Texte, Code, Argumentation",
              "wunsch": ["claude-opus-5-5", "claude-fable-5-1", "claude-opus-5", "claude-sonnet-5-5"]},
    "elon": {"name": "Elon", "titel": "Grok · xAI", "anbieter": "grok",
             "kurz": "Zweite Meinung, direkt und zugespitzt",
             "wunsch": ["grok-4.7", "grok-4.6", "grok-4.5", "grok-4.3"]},
    "demmis": {"name": "Demmis", "titel": "Gemini · Google", "anbieter": "gemini",
               "kurz": "Recherche, Faktenprüfung, lange Dokumente",
               "wunsch": ["gemini-3.1-pro-preview", "gemini-pro-latest", "gemini-2.5-pro"]},
}
# Bild-, Video- und Sprachmodelle gehoeren nicht in eine Auswahl fuer ein Gespraech.
_KEIN_TEXT = re.compile(r"imagine|image|video|tts|embed|banana|veo|imagen|audio|live|lyria|robotics|computer-use|antigravity|aqa|transcribe|customtools|deep-research|multi-agent|build", re.I)

FASSUNG_AUF, FASSUNG_ZU = "<<<FASSUNG>>>", "<<<ENDE>>>"
_cloud_cache: dict[str, Any] = {"zeit": 0.0, "modelle": {}, "schluessel": {}}

STIL = ("WIE DU ANTWORTEST: Deutsch, für Veiko (kein Entwickler, aber sattelfest in Konzepten). "
        "Zuerst das Ergebnis, dann die Begründung. Kein Fachbegriff ohne Erklärung. Eine Empfehlung statt drei Varianten. "
        "Erfinde keine Fakten, Zahlen oder Namen; was du nicht weißt, sagst du. Gründlich arbeiten ist ausdrücklich erwünscht: "
        "Rechenzeit spielt keine Rolle, kürze nicht aus Sparsamkeit.")


def ist_extern(wer: str) -> bool:
    return wer in EXTERNE


def wer_name(wer: str) -> str:
    return EXTERNE[wer]["name"] if wer in EXTERNE else stab.rollen_name(wer)


# ---------------------------------------------------------------- Cloud
async def cloud_stand(frisch: bool = False) -> dict[str, Any]:
    """Welche Externen einen Schluessel haben und welche Modelle sie anbieten.
    Zehn Minuten gemerkt -- die Team-Ansicht fragt alle 15 Sekunden."""
    if not frisch and time.time() - _cloud_cache["zeit"] < 600 and _cloud_cache["modelle"]:
        return _cloud_cache
    kopf = {"X-Cockpit-Token": ALT_TOKEN} if ALT_TOKEN else {}
    modelle: dict[str, list[str]] = {}
    schluessel: dict[str, bool] = {}
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            h = (await c.get(f"{ALT_BACKEND}/api/health")).json()
            schluessel = dict(h.get("cloud_keys") or {})
            for x in EXTERNE.values():
                p = x["anbieter"]
                if not schluessel.get(p):
                    continue
                r = await c.get(f"{ALT_BACKEND}/api/cloud/{p}", headers=kopf)
                if r.status_code == 200:
                    modelle[p] = [m["id"] for m in r.json().get("models", []) if not _KEIN_TEXT.search(m.get("id", ""))]
    except (httpx.HTTPError, ValueError):
        return _cloud_cache  # lieber den alten Stand als eine leere Liste, die nach "kein Schluessel" aussieht
    _cloud_cache.update(zeit=time.time(), modelle=modelle, schluessel=schluessel)
    return _cloud_cache


async def externe_liste() -> list[dict[str, Any]]:
    st = await cloud_stand()
    gewaehlt = db.einstellung("extern_modelle", {}) or {}
    out = []
    for xid, x in EXTERNE.items():
        angebot = st["modelle"].get(x["anbieter"], [])
        out.append({"id": xid, "name": x["name"], "titel": x["titel"], "kurz": x["kurz"], "extern": True,
                    "schluessel": st["schluessel"].get(x["anbieter"]),  # None = unbekannt
                    "modelle": angebot, "modell": gewaehlt.get(xid) or "",
                    "vorgabe": next((w for w in x["wunsch"] if w in angebot), angebot[0] if angebot else None)})
    return out


async def _extern_modell(wer: str) -> str | None:
    st = await cloud_stand()
    x = EXTERNE[wer]
    angebot = st["modelle"].get(x["anbieter"], [])
    g = (db.einstellung("extern_modelle", {}) or {}).get(wer)
    if g and (g in angebot or not angebot):
        return g
    return next((w for w in x["wunsch"] if w in angebot), angebot[0] if angebot else x["wunsch"][0])


async def _cloud_chat(wer: str, modell: str, system: str, nachrichten: list[dict[str, str]]) -> str:
    if not ALT_TOKEN:
        raise llm.ModellFehler("Für die Externen fehlt VVEC_ALT_TOKEN in ~/.config/vve-cp-r2.env.")
    p = EXTERNE[wer]["anbieter"]
    body = {"model": modell, "max_tokens": 16000, "system": system, "messages": nachrichten}
    try:
        async with httpx.AsyncClient(timeout=320) as c:
            r = await c.post(f"{ALT_BACKEND}/api/cloud/{p}", json=body, headers={"X-Cockpit-Token": ALT_TOKEN})
    except httpx.HTTPError as e:
        raise llm.ModellFehler(f"{EXTERNE[wer]['name']} nicht erreichbar: {e.__class__.__name__}") from e
    try:
        d = r.json()
    except ValueError:
        raise llm.ModellFehler(f"{EXTERNE[wer]['name']}: unlesbare Antwort ({r.status_code})")
    if r.status_code != 200:
        raise llm.ModellFehler(((d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else None)
                               or d.get("detail") or f"Fehler {r.status_code}")
    return "\n".join(b.get("text", "") for b in d.get("content") or [] if b.get("type") == "text").strip()


# ---------------------------------------------------------------- Kontext
def _stab_text() -> str:
    leute = [f"- {m['name']} ({m['titel']}): {m.get('kurz') or ''}" for m in
             db.alle("SELECT name, titel, kurz FROM team WHERE aktiv=1 ORDER BY reihenfolge")]
    leute += [f"- {x['name']} ({x['titel']}, extern, kostet Geld): {x['kurz']}" for x in EXTERNE.values()]
    return "\n".join(leute)


def _ergebnis_text(e: dict[str, Any]) -> str:
    p = e.get("pruefung") or {}
    return (f"DAS ERGEBNIS, AN DEM IHR ARBEITET: „{e['titel']}“ (Form: {e['form']}, erstellt von {stab.rollen_name(e['rolle'])})\n"
            + (f"Daniels letzte Prüfung: {p.get('urteil')} -- {p.get('begruendung') or ''}\n" if p.get("urteil") else "")
            + f"===== AKTUELLE FASSUNG =====\n{e.get('inhalt') or ''}\n===== ENDE DER FASSUNG =====\n\n"
            "ÄNDERUNGEN: Will Veiko etwas am Ergebnis ändern, erweitern, kürzen oder neu schreiben lassen, dann schreibst du "
            "zuerst ein bis zwei Sätze, was du änderst, und danach die VOLLSTÄNDIGE neue Fassung -- nicht nur die geänderten "
            f"Stellen -- zwischen einer Zeile, die nur {FASSUNG_AUF} enthält, und einer Zeile, die nur {FASSUNG_ZU} enthält. "
            "Behalte Aufbau und Form bei, sofern Veiko nichts anderes will. Stellt Veiko nur eine Frage oder will diskutieren, "
            "antwortest du ohne Fassung.")


def system_text(wer: str, kontext: dict[str, Any]) -> str:
    from .gespraech import kontext_text
    if ist_extern(wer):
        x = EXTERNE[wer]
        kopf = (f"Du bist {x['name']} ({x['titel']}), externer Berater in Veiko von Eckerns persönlichem KI-Team. "
                "Veiko ist Head of Corporate HR Transformation bei Krones und hat daneben private Vorhaben (u. a. Bücher). "
                "Das übrige Team rechnet lokal auf seinem eigenen Server; du bist die zugeschaltete zweite Meinung.")
    else:
        r = stab.rolle(wer)
        kopf = (r.get("auftrag") or f"Du bist {r.get('name')}, {r.get('titel')} in Veiko von Eckerns KI-Team.")
        kopf += f"\n\nJETZT sprichst du direkt mit Veiko, in Ich-Form, als {r.get('name')}."
    teile = [kopf, STIL, f"WER SONST IM TEAM IST:\n{_stab_text()}", f"GEDÄCHTNIS (was über Veiko bekannt ist):\n{stab.gedaechtnis_text()}"]
    if kontext.get("projekt_id"):
        pk = kontext_text({"art": "projekt", "id": kontext["projekt_id"]})
        if pk:
            teile.append(pk)
    if kontext.get("ergebnis_id"):
        e = db.holen("ergebnisse", kontext["ergebnis_id"])
        if e:
            teile.append(_ergebnis_text(e))
    return "\n\n".join(teile)


def _anhang_text(datei_ids: list[str]) -> str:
    teile = []
    for did in datei_ids[:8]:
        d = db.holen("dateien", str(did))
        if not d:
            continue
        t = (d.get("text") or "").strip()
        teile.append(f"ANHANG „{d['name']}“:\n" + (t[:60000] if t else "(Inhalt nicht lesbar -- sag Veiko das.)"))
    return "\n\n".join(teile)


def fassung_trennen(text: str) -> tuple[str, str | None]:
    """Prosa und neue Fassung trennen. Ohne schliessende Marke gilt alles nach der
    oeffnenden als Fassung -- eine abgeschnittene Marke soll die Arbeit nicht verwerfen."""
    a = text.find(FASSUNG_AUF)
    if a == -1:
        return text.strip(), None
    b = text.find(FASSUNG_ZU, a)
    fassung = text[a + len(FASSUNG_AUF): b if b != -1 else None].strip()
    prosa = (text[:a] + (text[b + len(FASSUNG_ZU):] if b != -1 else "")).strip()
    return prosa, fassung or None


# ---------------------------------------------------------------- Gespraeche
def gespraeche(wer: str | None = None, ergebnis_id: str | None = None) -> list[dict[str, Any]]:
    sql = ("SELECT g.id, g.titel, g.geaendert, g.kontext, (SELECT COUNT(*) FROM nachrichten n WHERE n.gespraech_id=g.id) AS anzahl "
           "FROM gespraeche g WHERE g.art='team'")
    args: list[Any] = []
    if wer:
        sql += " AND json_extract(g.kontext,'$.wer')=?"
        args.append(wer)
    if ergebnis_id:
        sql += " AND json_extract(g.kontext,'$.ergebnis_id')=?"
        args.append(ergebnis_id)
    return db.alle(sql + " ORDER BY g.geaendert DESC LIMIT 40", args)


async def senden(gid: str | None, wer: str, text: str, datei_ids: list[str],
                 kontext: dict[str, Any], schnell: bool = False) -> AsyncIterator[dict[str, Any]]:
    if not ist_extern(wer) and not db.holen("team", wer):
        yield {"typ": "fehler", "text": f"Unbekanntes Teammitglied: {wer}"}
        return
    kontext = {k: kontext.get(k) for k in ("projekt_id", "ergebnis_id") if kontext.get(k)}
    if kontext.get("ergebnis_id") and not kontext.get("projekt_id"):
        e0 = db.holen("ergebnisse", kontext["ergebnis_id"]) or {}
        if e0.get("projekt_id"):
            kontext["projekt_id"] = e0["projekt_id"]
    if not gid or not db.holen("gespraeche", gid):
        gid = db.neue_id("g")
        db.einfuegen("gespraeche", {"id": gid, "art": "team", "titel": (text or "Gespräch")[:70],
                                    "kontext": {**kontext, "wer": wer}, "erstellt": time.time(), "geaendert": time.time()})
    yield {"typ": "start", "gespraech_id": gid}

    anh = _anhang_text(datei_ids)
    db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                  (gid, "du", text, json.dumps({"dateien": datei_ids, "wer": wer}, ensure_ascii=False), time.time()))
    # Verlauf: nur Prosa. Die jeweils aktuelle Fassung steht im System-Text --
    # alte Fassungen noch einmal mitzuschicken hiesse, ein Buch doppelt zu zahlen.
    zeilen = list(reversed(db.alle("SELECT rolle, text, daten FROM nachrichten WHERE gespraech_id=? ORDER BY id DESC LIMIT 20", (gid,))))
    verlauf = []
    for i, m in enumerate(zeilen):
        inhalt = m["text"] or ""
        if i == len(zeilen) - 1 and anh:
            inhalt += "\n\n" + anh
        verlauf.append({"role": "user" if m["rolle"] == "du" else "assistant", "content": inhalt or "(leer)"})
    denken, zusatz = llm.tempo(schnell)
    system = system_text(wer, kontext) + "\n\n" + zusatz

    gesamt = ""
    try:
        if ist_extern(wer):
            modell = await _extern_modell(wer)
            yield {"typ": "status", "text": f"{wer_name(wer)} antwortet ({modell}) …"}
            gesamt = await _cloud_chat(wer, modell or "", system, verlauf)
            yield {"typ": "text", "t": gesamt}
        else:
            modell = await stab.modell_fuer(wer, MODELL_TALK)
            if not modell:
                yield {"typ": "fehler", "text": "Kein lokales Modell installiert."}
                return
            stab.laeuft(wer, "im Gespräch mit dir")
            if denken:
                yield {"typ": "status", "text": f"{wer_name(wer)} denkt gründlich nach …"}
            try:
                async for t in llm.strom(modell, system, verlauf, temperatur=0.6, denken=denken, num_ctx=65536):
                    gesamt += t
                    yield {"typ": "text", "t": t}
            finally:
                if (stab.ZUSTAND.get("laeuft") or {}).get("was") == "im Gespräch mit dir":
                    stab.laeuft(None)
    except llm.ModellFehler as f:
        yield {"typ": "fehler", "text": str(f)}
        return
    if llm.fremdschrift(gesamt):
        gesamt = llm.FREMDSCHRIFT.sub("", gesamt)

    prosa, fassung = fassung_trennen(gesamt)
    daten: dict[str, Any] = {"wer": wer, "modell": modell}
    if fassung and kontext.get("ergebnis_id"):
        eid = kontext["ergebnis_id"]
        e = db.holen("ergebnisse", eid) or {}
        db.aendern("ergebnisse", eid, {"inhalt": fassung, "modell": modell}, wer=wer, vorgang_id=e.get("vorgang_id"),
                   aktion="überarbeitet")
        pid = db.wert("SELECT MAX(id) FROM protokoll WHERE tabelle='ergebnisse' AND datensatz_id=?", (eid,))
        daten.update(fassung=True, zeichen=len(fassung), protokoll_id=pid)
        yield {"typ": "fassung", "zeichen": len(fassung), "protokoll_id": pid}
        # Daniel prueft auch die ueberarbeitete Fassung -- dieselbe Regel wie beim ersten Entwurf.
        yield {"typ": "status", "text": "Daniel prüft die neue Fassung …"}
        v = db.holen("vorgaenge", e.get("vorgang_id") or "") or {"id": e.get("vorgang_id") or ""}
        stab.laeuft("kritiker", "prüft eine Überarbeitung", v.get("id"))
        try:
            pruefung = await stab.pruefen(fassung, {"auftrag": f"{e.get('titel')} -- Veikos Anweisung: {text}",
                                                    "form": e.get("form")}, v)
        finally:
            stab.laeuft(None)
        db.aendern("ergebnisse", eid, {"pruefung": pruefung}, wer="kritiker", vorgang_id=e.get("vorgang_id"), aktion="geprüft")
        daten["pruefung"] = pruefung.get("urteil")
        yield {"typ": "pruefung", "pruefung": pruefung}
        if not prosa:
            prosa = "Neue Fassung geschrieben."
    elif fassung:
        # Fassung ohne Ergebnis im Kontext: einfach im Text stehen lassen.
        prosa = gesamt.replace(FASSUNG_AUF, "").replace(FASSUNG_ZU, "").strip()
    mid = db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                        (gid, wer, prosa, json.dumps(daten, ensure_ascii=False), time.time()))
    db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), gid))
    yield {"typ": "fertig", "text": prosa, "nachricht_id": mid, "modell": modell, **{k: daten[k] for k in ("fassung", "protokoll_id") if k in daten}}
