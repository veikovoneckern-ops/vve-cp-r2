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


# ---------------------------------------------------------------- Teamarbeit ohne Rueckfrage
# Veiko, 18.10.2026, an Neals Antwort „Wenn du willst, dass Annie ein Cover- und
# Bildkonzept dazu macht -- sag Bescheid“: „Ich möchte nicht gefragt werden, ob
# etwas an ein anderes Teammitglied übergeben werden soll, sondern das Team soll
# eigenständig zusammenarbeiten, um das Ergebnis zu liefern.“
# Ein Mitglied gibt deshalb selbst weiter (Block unten), und das Cockpit holt das
# andere Mitglied sofort in DIESES Gespraech -- derselbe Weg, auf dem Externe
# antworten (Ereignis "wer"). Nur das lokale Team: ein Externer kostet Geld und
# kommt nie ohne Veikos Freigabe dazu.
UEBERGABE_RE = re.compile(r"<<<WEITERGEBEN\s+(?:an\s*=?\s*)?[\"„“']?([^\"„“'>\n]+?)[\"„“']?\s*>>>(.*?)(?:<<<ENDE>>>|\Z)", re.S | re.I)
MAX_UEBERGABEN = 3        # je Nachricht von Veiko -- eine Kette, kein Kreis
# Erkennt eine Rueckfrage nach einer Uebergabe, die trotz Anweisung kam (dann
# einmal gezielt nachfordern, wie bei Talk und Neo).
FRAGT_NACH_RE = re.compile(r"wenn du (das )?(willst|möchtest|magst)|sag (mir )?bescheid|soll ich|möchtest du,? dass|"
                           r"falls du (das )?(willst|möchtest)|gib mir (kurz )?bescheid", re.I)
TEAMARBEIT = (
    "TEAMARBEIT -- OHNE VEIKO ZU FRAGEN: Ihr arbeitet als Team zusammen, um Veiko ein fertiges Ergebnis zu liefern. "
    "Frag Veiko NIE, ob du etwas an ein anderes Teammitglied geben sollst, und schreib nie „wenn du willst, macht X …, "
    "sag Bescheid“. Braucht das Ergebnis die Arbeit eines anderen Mitglieds (Annie: Gestaltung, Bildkonzept, Bilder; "
    "Neal: Texte; Clayton: Strategie und Konzepte; Ridley: Video; Jason: Planung), dann gib selbst weiter: hänge am "
    "Ende deiner Antwort einen Block an\n"
    "<<<WEITERGEBEN an=\"Annie\">>>\nder konkrete Auftrag: was genau, wofür, worauf achten\n<<<ENDE>>>\n"
    "Das Cockpit holt das Mitglied dann sofort in dieses Gespräch; es arbeitet selbst weiter (bei einem Ergebnis "
    "direkt an der Fassung). Sag Veiko in einem Satz, wer sich woran macht. Daniel prüft jede neue Fassung ohnehin "
    "von selbst -- ihn musst du nicht holen. Externe (Dario, Elon, Demmis) kosten Geld: die holt nur Veiko selbst. "
    "Rückfragen an Veiko nur, wenn eine Entscheidung wirklich nur er treffen kann (Inhalt, Ziel, Geld) -- nie für eine Übergabe.")


def _ziel(name: str, von: str) -> str | None:
    """Name oder Kennung -> Kennung eines aktiven, lokalen Mitglieds (nicht man selbst)."""
    n = name.strip().lower()
    for m in db.alle("SELECT id, name FROM team WHERE aktiv=1"):
        if n in (m["id"].lower(), (m["name"] or "").lower()) and m["id"] != von:
            return m["id"]
    return None


def uebergaben_trennen(text: str, von: str) -> tuple[str, list[dict[str, str]]]:
    """Uebergabe-Bloecke aus einer Antwort: sie werden ausgefuehrt, nicht angezeigt."""
    weiter: list[dict[str, str]] = []
    for m in UEBERGABE_RE.finditer(text):
        zid = _ziel(m.group(1), von)
        auftrag = m.group(2).strip()
        if zid and auftrag and zid not in [w["wer"] for w in weiter]:
            weiter.append({"wer": zid, "auftrag": auftrag[:3000], "von": von})
    return UEBERGABE_RE.sub("", text).strip(), weiter


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
    antwort = "\n".join(b.get("text", "") for b in d.get("content") or [] if b.get("type") == "text").strip()
    # Verbrauch buchen (Seite Verbrauch): die Zaehler meldet der Anbieter selbst
    # (das alte Backend reicht "usage" durch); fehlen sie, wird geschaetzt
    # (Zeichen / 4) und das steht als geschaetzt dabei.
    u = d.get("usage") or {}
    ein, aus = u.get("input_tokens") or 0, u.get("output_tokens") or 0
    geschaetzt = not (ein or aus)
    if geschaetzt:
        ein = (len(system) + sum(len(str(n.get("content") or "")) for n in nachrichten)) // 4
        aus = len(antwort) // 4
    llm.buchen("cloud", p, modell, ein, aus, geschaetzt=geschaetzt, wer=wer)
    return antwort


# ---------------------------------------------------------------- Kontext
def _stab_text() -> str:
    leute = [f"- {m['name']} ({m['titel']}): {m.get('kurz') or ''}" for m in
             db.alle("SELECT name, titel, kurz FROM team WHERE aktiv=1 ORDER BY reihenfolge")]
    leute += [f"- {x['name']} ({x['titel']}, extern, kostet Geld): {x['kurz']}" for x in EXTERNE.values()]
    return "\n".join(leute)


def _folien_anweisung() -> str:
    from .folien import ANWEISUNG
    return ANWEISUNG


def _langlauf_ergebnis_text(e: dict[str, Any]) -> str:
    """Das Ergebnis eines Langlaeufers: ohne den vollen Text (ein Buch hat leicht
    200.000 Zeichen, das sprengt jedes Fenster) und OHNE den Weg "vollstaendige
    neue Fassung". Gemessen 17.10.2026: "arbeite Daniels Einwaende ein und schreib
    die vollstaendige neue Fassung" machte aus 193.000 Zeichen 77.000 -- ein Modell
    kann ein Buch nicht in einer Antwort neu schreiben, es kuerzt dann still.
    Aenderungen gehen deshalb ueber die Bloecke des Langlaeufers (Kapitel fuer
    Kapitel, jedes mit Daniels Pruefung); die stehen in DER LANGLÄUFER weiter unten."""
    p = e.get("pruefung") or {}
    return (f"DAS ERGEBNIS, AN DEM IHR ARBEITET: „{e['titel']}“ -- das zusammengesetzte Ergebnis des Langläufers unten "
            f"({len(e.get('inhalt') or ''):,} Zeichen; den Inhalt der einzelnen Stücke zeigt die Kurzfassung im Plan).\n".replace(",", ".")
            + (f"Daniels letzte Prüfung: {p.get('urteil')} -- {p.get('begruendung') or ''}\n"
               + "".join(f"- {x}\n" for x in (p.get("maengel") or p.get("einwaende") or [])[:12]) if p.get("urteil") else "")
            + "ÄNDERUNGEN AM ERGEBNIS: NIE eine neue Gesamtfassung schreiben, auch wenn Veiko „vollständige neue Fassung“ sagt. "
            "Dafür ist der Block <<<UEBERARBEITEN>>> da: betrifft es das ganze Werk (Ton, Daniels Einwände, durchgehende "
            "Fehler), eine Zeile „alle: …“ mit allen Punkten, die einzuarbeiten sind; betrifft es einzelne Stücke, je Zeile "
            "Nummer und Änderung. Der Langläufer schreibt dann jedes Stück einzeln neu, Daniel prüft, und das Ergebnis "
            "wird danach aktualisiert. Sag Veiko in einem Satz, dass es so läuft und dass er den Fortschritt am Langläufer sieht.")


def _ist_langlauf_ergebnis(kontext: dict[str, Any]) -> bool:
    if not kontext.get("ergebnis_id") or not kontext.get("langlauf_id"):
        return False
    from . import langlauf
    return langlauf.zum_ergebnis(kontext["ergebnis_id"]) == kontext["langlauf_id"]


def _ergebnis_text(e: dict[str, Any]) -> str:
    p = e.get("pruefung") or {}
    return (f"DAS ERGEBNIS, AN DEM IHR ARBEITET: „{e['titel']}“ (Form: {e['form']}, erstellt von {stab.rollen_name(e['rolle'])})\n"
            + (f"Daniels letzte Prüfung: {p.get('urteil')} -- {p.get('begruendung') or ''}\n" if p.get("urteil") else "")
            + f"===== AKTUELLE FASSUNG =====\n{e.get('inhalt') or ''}\n===== ENDE DER FASSUNG =====\n\n"
            "ÄNDERUNGEN: Will Veiko etwas am Ergebnis ändern, erweitern, kürzen oder neu schreiben lassen, dann schreibst du "
            "zuerst ein bis zwei Sätze, was du änderst, und danach die VOLLSTÄNDIGE neue Fassung -- nicht nur die geänderten "
            f"Stellen -- zwischen einer Zeile, die nur {FASSUNG_AUF} enthält, und einer Zeile, die nur {FASSUNG_ZU} enthält. "
            "Behalte Aufbau und Form bei, sofern Veiko nichts anderes will. Stellt Veiko nur eine Frage oder will diskutieren, "
            "antwortest du ohne Fassung."
            + (" Bei dieser Präsentation wird aus einer Zeile 'Bild: <Bildbeschreibung>' am Folienende ein echtes Bild "
               "gerechnet (eine je Folie, ohne Schrift im Bild). Will Veiko Bilder, setze solche Zeilen; behalte vorhandene "
               "unverändert, wenn das Bild bleiben soll. Für jede neue Fassung gelten diese Folienregeln:\n" + _folien_anweisung()
               if e.get("form") == "praesentation" else
               " Wünscht Veiko ein Bild, setze an die Stelle eine eigene Zeile 'Bild: <Bildbeschreibung>' -- daraus wird ein "
               "echtes Bild gerechnet und in Ansicht und Word-Datei eingebaut. Beschreibe ein Bild nie nur im Text."
               if e.get("form") in ("text", "aufstellung", "konzept", "dokument") else ""))


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
    if not ist_extern(wer):
        teile.insert(3, TEAMARBEIT)
    if kontext.get("projekt_id"):
        pk = kontext_text({"art": "projekt", "id": kontext["projekt_id"]})
        if pk:
            teile.append(pk)
    if kontext.get("ergebnis_id"):
        e = db.holen("ergebnisse", kontext["ergebnis_id"])
        if e:
            teile.append(_langlauf_ergebnis_text(e) if kontext.get("langlauf_id") and _ist_langlauf_ergebnis(kontext) else _ergebnis_text(e))
    if kontext.get("langlauf_id"):
        # Gespraech ueber einen Langlaeufer (17.10.2026): Plan, Stand, Hinweise und
        # die drei Bloecke, mit denen das Mitglied etwas ausloesen kann.
        from . import langlauf
        lk = langlauf.chat_kontext(kontext["langlauf_id"])
        if lk:
            teile.append(lk)
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
def gespraeche(wer: str | None = None, ergebnis_id: str | None = None, langlauf_id: str | None = None) -> list[dict[str, Any]]:
    sql = ("SELECT g.id, g.titel, g.geaendert, g.kontext, (SELECT COUNT(*) FROM nachrichten n WHERE n.gespraech_id=g.id) AS anzahl "
           "FROM gespraeche g WHERE g.art='team'")
    args: list[Any] = []
    if wer:
        sql += " AND json_extract(g.kontext,'$.wer')=?"
        args.append(wer)
    if ergebnis_id:
        sql += " AND json_extract(g.kontext,'$.ergebnis_id')=?"
        args.append(ergebnis_id)
    if langlauf_id:
        sql += " AND json_extract(g.kontext,'$.langlauf_id')=?"
        args.append(langlauf_id)
    return db.alle(sql + " ORDER BY g.geaendert DESC LIMIT 40", args)


async def senden(gid: str | None, wer: str, text: str, datei_ids: list[str],
                 kontext: dict[str, Any], schnell: bool = False,
                 extern: list[str] | None = None) -> AsyncIterator[dict[str, Any]]:
    """extern: Externe, die Veiko in dieser Nachricht dazuholt und fuer die er im
    Fenster die Kosten freigegeben hat. Sie antworten dann SELBST in diesem
    Gespraech, statt dass das Mitglied nur einen Auftrag an sie formuliert --
    gemessen am 16.10.: "gib Demmis die Fassung zum Korrekturlesen" brachte von
    Neal einen fertigen Pruefauftrag "zum Weiterschicken", aber keinen Demmis."""
    if not ist_extern(wer) and not db.holen("team", wer):
        yield {"typ": "fehler", "text": f"Unbekanntes Teammitglied: {wer}"}
        return
    kontext = {k: kontext.get(k) for k in ("projekt_id", "ergebnis_id", "langlauf_id") if kontext.get(k)}
    if kontext.get("ergebnis_id") and not kontext.get("langlauf_id"):
        # Das Ergebnis eines Langlaeufers: Aenderungen laufen ueber seine Etappen
        # (_langlauf_ergebnis_text), und der Langlaeufer zeigt, dass gearbeitet wird.
        from . import langlauf
        lid = langlauf.zum_ergebnis(kontext["ergebnis_id"])
        if lid:
            kontext["langlauf_id"] = lid
    if kontext.get("langlauf_id") and not kontext.get("projekt_id"):
        l0 = db.holen("langlaeufe", kontext["langlauf_id"]) or {}
        if l0.get("projekt_id"):
            kontext["projekt_id"] = l0["projekt_id"]
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
        # Hat ein anderes Mitglied hier geantwortet (Uebergabe), steht sein Name davor --
        # sonst hielte das Modell Annies Beitrag fuer seinen eigenen.
        if m["rolle"] not in ("du", wer):
            inhalt = f"[{wer_name(m['rolle'])}]: {inhalt}"
        verlauf.append({"role": "user" if m["rolle"] == "du" else "assistant", "content": inhalt or "(leer)"})
    denken, zusatz = llm.tempo(schnell)
    # Zugeordnetes Projekt/Aufgabe (17.10.2026): gespeichert am Gespraech, gilt
    # auch, wenn das Fenster selbst keinen Projektbezug mitschickt.
    from .gespraech import aufgabe_text, zuordnung
    z = zuordnung(gid)
    if z.get("projekt_id") and not kontext.get("projekt_id"):
        kontext["projekt_id"] = z["projekt_id"]
    from . import dossier
    system = system_text(wer, kontext) + "\n\n" + zusatz + "\n\n" + dossier.ANWEISUNG
    if z.get("aufgabe_id"):
        system += "\n\n" + aufgabe_text(z["aufgabe_id"])

    # Internet im gruendlichen Modus -- auch fuer die Externen: die Suche plant
    # ein LOKALES Modell, es kostet also nichts extra, und die Cloud-Anbieter
    # bekommen ueber den Proxy kein eigenes Suchwerkzeug.
    quellen: list[dict[str, str]] = []
    if denken:
        planer = await llm.modell_waehlen(llm.vorgabe("talk"), "qwen3.6:27b", "qwen3:30b-a3b")
        if planer:
            yield {"typ": "status", "text": "prüft, ob das Internet hilft …"}
            quellen = await stab.netzwissen(planer, verlauf)
            if quellen:
                system += "\n\n" + stab.netz_system(quellen)
                yield {"typ": "status", "text": f"{len(quellen)} Quellen aus dem Netz gelesen …"}

    # Links in Veikos Nachricht werden IMMER geoeffnet (quellen.py, 17.10.2026) --
    # auch bei "Schnelle Antwort": ein Link ist ein ausdruecklicher Auftrag.
    from . import quellen as verlinkt
    ltext = ""
    if verlinkt.links(text):
        yield {"typ": "status", "text": "öffnet die Links aus deiner Nachricht …"}
        ltext, lstatus = await verlinkt.einbinden(text, {"projekt_id": kontext.get("projekt_id"), "aufgabe_id": z.get("aufgabe_id"),
                                                         "langlauf_id": kontext.get("langlauf_id"), "gespraech_id": gid, "wer": wer})
        if ltext:
            system += "\n\n" + ltext
        if lstatus:
            yield {"typ": "status", "text": "; ".join(lstatus)}

    sprecher = [x for x in (extern or []) if x in EXTERNE] if not ist_extern(wer) else []
    netz = ("\n\n" + stab.netz_system(quellen)) if quellen else ""
    if not sprecher:
        weiter: list[dict[str, str]] = []
        async for e in _antwort(gid, wer, system, verlauf, kontext, text, quellen, denken):
            if e.get("typ") == "fertig":
                weiter += e.get("weitergeben") or []
            yield e
        # Das Team arbeitet selbst weiter, ohne Veiko zu fragen (TEAMARBEIT oben).
        dazu = zusatz + netz + (("\n\n" + ltext) if ltext else "") + \
            ("\n\n" + aufgabe_text(z["aufgabe_id"]) if z.get("aufgabe_id") else "")
        async for e in _uebergaben(gid, weiter, kontext, text, dazu, quellen, denken):
            yield e
        return
    for xid in sprecher:
        yield {"typ": "wer", "wer": xid}
        xsys = (system_text(xid, kontext) + "\n\n" + zusatz + netz + (("\n\n" + ltext) if ltext else "") +
                ("\n\n" + aufgabe_text(z["aufgabe_id"]) if z.get("aufgabe_id") else "") +
                f"\n\nDICH HAT {wer_name(wer).upper()} AUS VEIKOS TEAM AUF VEIKOS WUNSCH IN DIESES GESPRÄCH GEHOLT. "
                "Erledige Veikos letzte Nachricht selbst und vollständig hier im Gespräch -- nicht als Vorschlag, "
                "was jemand anderes tun könnte. Bei einer Korrektur: nenne jede Fundstelle mit Zitat und Verbesserung.")
        async for e in _antwort(gid, xid, xsys, verlauf, kontext, text, quellen, denken):
            yield e


async def _uebergaben(gid: str, weiter: list[dict[str, str]], kontext: dict[str, Any], text: str, dazu: str,
                      quellen: list[dict[str, str]], denken: bool) -> AsyncIterator[dict[str, Any]]:
    """Weitergegebene Auftraege nacheinander abarbeiten: das Mitglied kommt ins
    Gespraech, sieht den Verlauf (auch die Antwort dessen, der weitergab) und
    bekommt den Auftrag als letzte Nachricht. Gibt es selbst weiter, reiht sich
    das hinten an -- hoechstens MAX_UEBERGABEN je Nachricht von Veiko."""
    schon = 0
    while weiter and schon < MAX_UEBERGABEN:
        w = weiter.pop(0)
        schon += 1
        yield {"typ": "wer", "wer": w["wer"]}
        zeilen = list(reversed(db.alle("SELECT rolle, text FROM nachrichten WHERE gespraech_id=? ORDER BY id DESC LIMIT 20", (gid,))))
        verlauf = [{"role": "user" if m["rolle"] == "du" else "assistant",
                    "content": (m["text"] or "(leer)") if m["rolle"] == "du" else f"[{wer_name(m['rolle'])}]: {m['text'] or ''}"}
                   for m in zeilen]
        verlauf.append({"role": "user", "content": f"[Übergabe von {wer_name(w['von'])} an dich] {w['auftrag']}"})
        system = (system_text(w["wer"], kontext) + "\n\n" + dazu +
                  f"\n\nDICH HAT {wer_name(w['von']).upper()} AUS DEM TEAM IN DIESES GESPRÄCH GEHOLT, damit Veiko ein fertiges "
                  "Ergebnis bekommt. Erledige den Auftrag selbst und vollständig hier im Gespräch -- nicht als Vorschlag oder "
                  "Briefing für jemand anderen, und ohne Veiko zu fragen, ob du anfangen sollst. Gibt es ein Ergebnis im Kontext "
                  "und ändert dein Beitrag es, liefere die vollständige neue Fassung zwischen den Marken.")
        async for e in _antwort(gid, w["wer"], system, verlauf, kontext, f"{text} -- Auftrag von {wer_name(w['von'])}: {w['auftrag']}",
                                quellen, denken):
            if e.get("typ") == "fertig":
                weiter += [x for x in (e.get("weitergeben") or []) if x["wer"] not in (y["wer"] for y in weiter)]
            yield e
    if weiter:
        yield {"typ": "status", "text": f"Weitere Übergaben ({', '.join(wer_name(x['wer']) for x in weiter)}) zurückgestellt -- "
                                        f"höchstens {MAX_UEBERGABEN} je Nachricht."}


async def _uebergabe_nachfordern(wer: str, modell: str, system: str, verlauf: list[dict[str, str]],
                                 antwort: str) -> list[dict[str, str]]:
    """Die Antwort fragt Veiko, ob jemand anderes etwas uebernehmen soll -- trotz
    Anweisung. Einmal gezielt nachfordern: entscheide selbst, nur der Block."""
    namen = [m["name"] for m in db.alle("SELECT id, name FROM team WHERE aktiv=1") if m["id"] != wer]
    if not FRAGT_NACH_RE.search(antwort) or not any(re.search(rf"\b{re.escape(n)}\b", antwort) for n in namen if n):
        return []
    # Gemessen am 18.10.: mit "entscheide selbst, sonst: keine" antwortete qwen3.8 auf
    # Neals eigenen Vorschlag (Annie macht das Bildkonzept) mit "keine". Was ein
    # Mitglied selbst vorgeschlagen hat, wird deshalb ausgefuehrt, nicht neu abgewogen.
    frage = ("Du hast Veiko vorgeschlagen, dass ein anderes Teammitglied etwas übernimmt, und ihn gefragt, ob er das will. "
             "Veiko will nicht gefragt werden -- das Team soll selbst zusammenarbeiten. Gib es deshalb JETZT weiter. "
             "Antworte NUR mit dem Block <<<WEITERGEBEN an=\"Name\">>> konkreter Auftrag: was, wofür, worauf achten <<<ENDE>>> "
             "(einer je Mitglied, das du vorgeschlagen hast). Nur wenn dein Vorschlag nichts mit Veikos Auftrag zu tun hatte, "
             "antworte: keine")
    try:
        roh = await llm.chat(modell, system, verlauf + [{"role": "assistant", "content": antwort}, {"role": "user", "content": frage}],
                             temperatur=0.3, denken=False, num_ctx=65536, timeout=300)
    except llm.ModellFehler:
        return []
    return uebergaben_trennen(roh, wer)[1]


async def _antwort(gid: str, wer: str, system: str, verlauf: list[dict[str, str]], kontext: dict[str, Any],
                   text: str, quellen: list[dict[str, str]], denken: bool) -> AsyncIterator[dict[str, Any]]:
    """Eine Antwort eines Mitglieds oder Externen: rechnen, Fassung uebernehmen,
    Daniel pruefen lassen, speichern. Ein Weg fuer beide, damit eine Fassung von
    Demmis genauso zuruecknehmbar ist wie eine von Neal."""
    gesamt = ""
    try:
        if ist_extern(wer):
            modell = await _extern_modell(wer)
            yield {"typ": "status", "text": f"{wer_name(wer)} antwortet ({modell}) …"}
            with llm.taetig(f"{wer_name(wer)} (Cloud, {modell}) antwortet dir im Team-Chat"):
                gesamt = await _cloud_chat(wer, modell or "", system, verlauf)
            yield {"typ": "text", "t": gesamt}
        else:
            modell = await stab.modell_fuer(wer, llm.vorgabe("talk"))
            if not modell:
                yield {"typ": "fehler", "text": "Kein lokales Modell installiert."}
                return
            if denken:
                yield {"typ": "status", "text": f"{wer_name(wer)} denkt gründlich nach …"}
            with llm.taetig(f"{wer_name(wer)} antwortet dir im Team-Chat" + (" (überarbeitet ein Ergebnis)" if kontext.get("ergebnis_id") else "")):
                async for t in llm.strom(modell, system, verlauf, temperatur=0.6, denken=denken, num_ctx=65536):
                    gesamt += t
                    yield {"typ": "text", "t": t}
                if not gesamt.strip() and denken:
                    # Gemessen am 16.10.: qwen3.8 dachte 2:41 Min. (rund 11.000 Token) und
                    # schrieb dann keinen Satz -- gespeichert wurde eine leere Nachricht.
                    # Ein zweiter Anlauf ohne Denkphase schreibt direkt.
                    yield {"typ": "status", "text": f"{wer_name(wer)} hat nur nachgedacht und nichts geschrieben -- zweiter Anlauf, diesmal direkt …"}
                    async for t in llm.strom(modell, system, verlauf, temperatur=0.6, denken=False, num_ctx=65536):
                        gesamt += t
                        yield {"typ": "text", "t": t}
    except llm.ModellFehler as f:
        yield {"typ": "fehler", "text": str(f)}
        return
    if not gesamt.strip():
        # Eine leere Antwort ist ein Fehler, keine Nachricht -- sonst steht eine
        # leere Blase im Chat und man weiss nicht, ob noch etwas kommt.
        yield {"typ": "fehler", "text": f"{wer_name(wer)} hat keine Antwort geliefert. Bitte noch einmal senden, "
                                        "gern mit „Schnelle Antwort“ oder in kleineren Schritten."}
        return
    if llm.fremdschrift(gesamt):
        gesamt = llm.FREMDSCHRIFT.sub("", gesamt)
    # Im Verlauf steht vor fremden Beitraegen "[Name]: " -- das Modell ahmt es gern
    # nach (18.10.: Annies Antwort begann mit "[Annie]:"). Der Name steht ohnehin am Beitrag.
    gesamt = re.sub(r"^\s*\[[^\]\n]{2,30}\]:\s*", "", gesamt)

    # Uebergaben an andere Mitglieder (TEAMARBEIT): ausfuehren statt fragen.
    weiter: list[dict[str, str]] = []
    if not ist_extern(wer):
        gesamt, weiter = uebergaben_trennen(gesamt, wer)
        if not weiter:
            weiter = await _uebergabe_nachfordern(wer, modell, system, verlauf, gesamt)
            if weiter:
                # Die Rueckfrage selbst ist damit beantwortet -- der Absatz faellt weg.
                ziele = [wer_name(w["wer"]) for w in weiter]
                gesamt = "\n\n".join(a for a in re.split(r"\n\s*\n", gesamt)
                                     if not (FRAGT_NACH_RE.search(a) and any(z in a for z in ziele))).strip()

    getan: list[str] = []
    if kontext.get("langlauf_id"):
        from . import langlauf
        gesamt, getan = langlauf.chat_anweisungen(kontext["langlauf_id"], gesamt, wer)
        if getan:
            yield {"typ": "status", "text": "Übernommen: " + "; ".join(getan)}
    # Recherche-Dossier auf Zuruf (dossier.py, 17.10.2026)
    from . import dossier
    from .gespraech import zuordnung as _zuordnung
    gesamt, recherche = await dossier.aus_antwort(gesamt, {"projekt_id": kontext.get("projekt_id"), "aufgabe_id": _zuordnung(gid).get("aufgabe_id"),
                                                           "langlauf_id": kontext.get("langlauf_id"), "gespraech_id": gid, "wer": wer})
    if recherche:
        getan = getan + recherche
        yield {"typ": "status", "text": recherche[0]}
    prosa, fassung = fassung_trennen(gesamt)
    if fassung and quellen:
        fassung += stab.netz_fuss(quellen)   # die Fassung traegt ihre Quellen selbst, wie in der Pipeline
    daten: dict[str, Any] = {"wer": wer, "modell": modell}
    if fassung and _ist_langlauf_ergebnis(kontext):
        # Trotz Anweisung eine Gesamtfassung fuer ein Langlaeufer-Ergebnis: NICHT
        # uebernehmen (sie waere gekuerzt und passte nicht mehr zu den Etappen),
        # sondern Veikos Wunsch an jedes fertige Stueck geben.
        from . import langlauf
        _, mehr = langlauf.chat_anweisungen(kontext["langlauf_id"], f"<<<UEBERARBEITEN>>>\nalle: {text}\n<<<ENDE>>>", wer)
        getan = getan + mehr
        if mehr:
            yield {"typ": "status", "text": "Übernommen: " + "; ".join(mehr)}
        prosa = (prosa + "\n\n" if prosa else "") + ("Eine komplette neue Fassung in einer Antwort würde das Buch kürzen. "
                                                     "Deshalb geht dein Wunsch an jedes Kapitel einzeln; Daniel prüft jedes.")
        fassung = None
    if fassung and kontext.get("ergebnis_id"):
        eid = kontext["ergebnis_id"]
        e = db.holen("ergebnisse", eid) or {}
        db.aendern("ergebnisse", eid, {"inhalt": fassung, "modell": modell}, wer=wer, vorgang_id=e.get("vorgang_id"),
                   aktion="überarbeitet")
        pid = db.wert("SELECT MAX(id) FROM protokoll WHERE tabelle='ergebnisse' AND datensatz_id=?", (eid,))
        daten.update(fassung=True, zeichen=len(fassung), protokoll_id=pid)
        from . import folienbilder
        if e.get("form") in folienbilder.MIT_BILDERN:
            # Neue oder geaenderte Bildzeilen gleich rechnen; unveraenderte Bilder bleiben.
            folienbilder.starten(eid)
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
    if getan:
        # Was wirklich ausgeloest wurde, steht unter der Antwort -- vom Code
        # geschrieben, nicht vom Modell behauptet.
        prosa = (prosa or "Erledigt.") + ("\n\n**Im Langläufer übernommen:**\n" if kontext.get("langlauf_id") else "\n\n**Ausgelöst:**\n") \
            + "\n".join("- " + g for g in getan)
        daten["langlauf"] = getan
    if weiter:
        # Vom Code geschrieben: wer jetzt woran arbeitet -- und es passiert gleich danach.
        prosa = (prosa or "Ich gebe weiter.") + "\n\n**Weitergegeben:**\n" + "\n".join(
            f"- {wer_name(w['wer'])}: {w['auftrag'][:200]}{'…' if len(w['auftrag']) > 200 else ''}" for w in weiter)
        daten["weitergeben"] = weiter
    prosa += stab.netz_fuss(quellen)
    mid = db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                        (gid, wer, prosa, json.dumps(daten, ensure_ascii=False), time.time()))
    db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), gid))
    yield {"typ": "fertig", "text": prosa, "nachricht_id": mid, "modell": modell, "wer": wer,
           **{k: daten[k] for k in ("fassung", "protokoll_id", "weitergeben") if k in daten}}
