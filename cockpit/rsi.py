"""
RSI -- RECURSIVE SELF-IMPROVEMENT (23.10.2026).

Veiko: "Das Cockpit soll sich nachts anschauen, aus den Dialogen, die ich gemacht habe, was da
alles nicht gut funktioniert hat, wo ich gesagt habe, nein, ich moechte dies oder das, und das
konnte dann nicht ausgefuehrt werden. Dann soll Neo Vorschlaege machen, wie das verbessert werden
kann. Er soll aber nichts schon umsetzen oder einspielen. Das soll dann durch Dario geprueft
werden. Und dann brauche ich einen Vorschlag, was Dario ausarbeiten soll im naechsten Schritt
oder ob Neo das ausarbeiten soll."

Der Ablauf, einmal je Nacht (03--05 Uhr deutscher Zeit):
  1. SAMMELN (ohne Modell, schnell): Talk- und Neo-Gespraeche seit dem letzten Lauf. Ein Befund
     ist eine Stelle, an der es hakte -- Veiko widerspricht ("nein", "du sollst", "funktioniert
     nicht"), Talk gibt auf ("nichts gefunden", "verstehe dich nicht") oder Veiko wiederholt
     seine Bitte. Mit dem Gespraech davor und danach, damit man den Fehler nachvollziehen kann.
  2. NEO ANALYSIERT -- NUR LESEND. Er bekommt die Befunde, sieht im Code nach (datei_lesen,
     suche, projektwissen -- dieselben Werkzeuge wie im Neo-Chat, aber KEINE schreibenden) und
     liefert hoechstens fuenf Vorschlaege: Problem, Ursache im Code, Loesung, Dateien, Aufwand.
     Er kann hier gar nichts aendern -- die Werkzeuge dafuer bekommt er nicht.
  3. DARIO PRUEFT jeden Vorschlag: traegt er, was sind die Risiken, und WER soll ihn
     ausarbeiten -- Neo (klein, klar umrissen, lokal und kostenlos) oder Dario selbst (gross,
     heikel, braucht einen sauberen Plan). Kostet Geld: geschaetzt wird VOR jedem Aufruf, und
     ueber das Nachtbudget (Vorgabe 1 Dollar, auf der Seite einstellbar) geht nichts hinaus.
  4. VEIKO ENTSCHEIDET auf der Seite RSI: Neo ausarbeiten lassen (normaler Neo-Auftrag -- was er
     am Cockpit aendern will, prueft Dario wie immer vor dem Einspielen, neo_freigabe.py),
     Dario einen Umsetzungsplan schreiben lassen (kostet, deshalb mit Rueckfrage), oder verwerfen.

Bewusst NICHT automatisch: das Umsetzen. Ein Cockpit, das sich nachts selbst umbaut, waere nicht
mehr Veikos -- "eigenstaendig arbeiten heisst moeglichst wenig warten, nicht alles selbst
entscheiden" (CLAUDE.md des alten Cockpits).
"""
from __future__ import annotations

import asyncio
import datetime
import json
import re
import time
import traceback
from typing import Any

from . import db, llm
from .konfig import MODELL_NEO

from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")

VON, BIS = 3, 5                  # deutsche Zeit (Veikos Vorgabe)
ERSTER_RUECKBLICK = 7 * 86400    # beim allerersten Lauf: die letzte Woche
MAX_BEFUNDE = 40
MAX_VORSCHLAEGE = 5
MAX_SCHRITTE = 18
BUDGET_VORGABE = 1.0             # Dollar je Nacht fuer Darios Pruefungen
AUS_SCHAETZUNG = 2500            # Ausgabe-Token je Pruefung (geschaetzt)

# Veiko widerspricht oder beschwert sich -- am Satzanfang, oder klare Klage irgendwo.
KORREKTUR = re.compile(
    r"^\W*(nein|nee|falsch|stopp?|halt|nicht das|nicht die|nicht den|das ist falsch|das stimmt nicht|"
    r"du sollst|ich (wollte|meinte|möchte|moechte|will) (doch|aber|eigentlich)|ich (wollte|meinte) nicht|"
    r"warum (hast|kannst|machst|tust) du|wieso (hast|kannst|machst) du)\b"
    r"|\b(funktioniert|geht|klappt) (immer noch |wieder |gar |überhaupt |ueberhaupt )?nicht\b"
    r"|\b(hast du|du hast) (es |das )?(nicht|falsch)\b|\bdas war (falsch|nicht)\b", re.I)
# Talk oder Neo gibt auf.
PANNE = re.compile(
    r"nichts gefunden|verstehe dich nicht|nicht ganz verstanden|nicht verarbeiten|kann ich (leider )?nicht|"
    r"ist (leider )?gescheitert|ging (leider )?nicht|nicht erreichbar|hat nicht geliefert|Fehler beim|"
    r"keine passende|weiß ich nicht|weiss ich nicht|nicht möglich|nicht moeglich", re.I)

_BLAETTERN_GRUND = re.compile(r"\b(scroll\w*|blätter\w*|blaetter\w*)\b|\b(nach )?(unten|oben)\b", re.I)

_lauf: asyncio.Task | None = None


# ---------------------------------------------------------------- Stand und Schalter
def stand() -> dict[str, Any]:
    return db.einstellung("rsi_stand", {}) or {}


def _setzen(**w: Any) -> None:
    s = stand()
    s.update(w)
    db.einstellung_setzen("rsi_stand", s)


def an() -> bool:
    return bool(db.einstellung("rsi_aktiv", True))


def budget() -> float:
    try:
        return max(0.0, float(db.einstellung("rsi_budget", BUDGET_VORGABE)))
    except (TypeError, ValueError):
        return BUDGET_VORGABE


def laeuft() -> bool:
    return bool(_lauf and not _lauf.done())


# ---------------------------------------------------------------- 1. Sammeln
def _woerter(t: str) -> set[str]:
    return {w for w in re.findall(r"[a-zäöüß0-9]{4,}", (t or "").lower())}


def _anzeige(n: dict[str, Any]) -> str:
    d = n.get("daten") if isinstance(n.get("daten"), dict) else {}
    return str((d or {}).get("anzeige") or n.get("text") or "").strip()


def _kurz(t: str, n: int = 400) -> str:
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    return t if len(t) <= n else t[:n].rsplit(" ", 1)[0] + " …"


# ---------------------------------------------------------------- Doppelte erkennen (23.10.2026)
# Veiko: "es werden einige Punkte doppelt bearbeitet ... schon beim Durchschauen meiner Gespraeche muss
# gut identifiziert werden, ob es sich um den gleichen Fehler handelt, der mehrfach vorkommt." Gemessen:
# zwei Laeufe am 23.10. ergaben dieselben vier Themen zweimal, eine Serie arbeitete jedes zweimal ab.
OFFEN_STAENDE = ("neu", "geprueft", "plan", "bei_neo", "in_serie")
GLEICH_AB = 0.5      # Anteil gemeinsamer Woerter in Titel + Problem, ab dem zwei Vorschlaege derselbe Fehler sind


def _daten(r: dict[str, Any]) -> dict[str, Any]:
    d = r.get("daten")
    if isinstance(d, dict):
        return d
    try:
        return json.loads(d or "{}")
    except (TypeError, ValueError):
        return {}


def _aehnlich(a: str, b: str) -> float:
    wa, wb = _woerter(a), _woerter(b)
    return len(wa & wb) / max(1, len(wa | wb))


def _stellen(d: dict[str, Any]) -> set[str]:
    """Die Code-Stellen, die ein Vorschlag als Ursache nennt -- Namen in Backticks (`oeffnen_suchen`)."""
    return {x for x in re.findall(r"`([A-Za-z_][A-Za-z0-9_]{3,})(?:\(\))?`", str(d.get("ursache") or "")) if not x.endswith(".py")}


def _gleicher_offener(v: dict[str, Any], offen: list[dict[str, Any]]) -> str | None:
    """Mechanische Gegenprobe, falls Neo ein Duplikat nicht als solches erkennt: gleicher Titel oder
    ueberwiegend dieselben Woerter in Titel und Problem."""
    text = f"{v.get('titel', '')} {v.get('problem', '')}"
    stellen_v = _stellen(v)
    beste, wert = None, 0.0
    w_titel = _woerter(v.get("titel", ""))
    for r in offen:
        # Gleicher Titel -- aber erst ab zwei sinntragenden Woertern ("Probe X"/"Probe Y" sind sonst gleich).
        if len(w_titel) >= 2 and w_titel == _woerter(r["titel"]):
            return r["id"]
        # Dieselbe Funktion als Ursache und ein aehnlicher Titel: derselbe Fehler, nur anders beschrieben
        # ("Talk oeffnet nicht das, was Veiko meint" / "... das richtige Projekt bei KI-Singularitaet",
        # beide in oeffnen_suchen).
        if stellen_v & _stellen(_daten(r)) and _aehnlich(v.get("titel", ""), r["titel"]) >= 0.25:
            return r["id"]
        a = _aehnlich(text, f"{r['titel']} {_daten(r).get('problem', '')}")
        if a > wert:
            beste, wert = r["id"], a
    return beste if wert >= GLEICH_AB else None


def _anhaengen(rid: str, belege: list[dict[str, Any]], nacht: str, vorschlag: str | None = None) -> None:
    """Ein weiteres Vorkommen desselben Fehlers: Belege dazu, Zaehler hoch -- kein neuer Vorschlag."""
    r = db.holen("rsi", rid)
    if not r:
        return
    d = _daten(r)
    schon = {(b.get("gespraech_id"), b.get("zeit")) for b in d.get("belege") or []}
    neu = [b for b in belege if (b.get("gespraech_id"), b.get("zeit")) not in schon]
    d["belege"] = (d.get("belege") or []) + neu[: max(0, 10 - len(d.get("belege") or []))]
    d["vorkommen"] = int(d.get("vorkommen") or 1) + max(1, len(neu))
    d.setdefault("auch_gesehen", []).append({"nacht": nacht, "belege": len(neu), "vorschlag": _kurz(vorschlag, 600) if vorschlag else None})
    db.ausfuehren("UPDATE rsi SET daten=?, geaendert=? WHERE id=?", (json.dumps(d, ensure_ascii=False), time.time(), rid))


def doppelte_zusammenlegen() -> list[tuple[str, str]]:
    """Fuehrt offene Vorschlaege zusammen, die derselbe Fehler sind (gleiche Probe wie beim Anlegen).
    Behalten wird der mit Darios Plan, sonst der mit mehr Belegen, sonst der aeltere; der andere
    bekommt den Stand "zusammengelegt" und verweist auf den behaltenen. Laufende (bei_neo, in_serie)
    werden nicht angefasst -- an ihnen arbeitet gerade jemand."""
    zeilen = db.alle("SELECT id, titel, stand, daten, erstellt FROM rsi WHERE stand IN ('neu','geprueft','plan') ORDER BY erstellt")
    paare: list[tuple[str, str]] = []
    weg: set[str] = set()
    for i, a in enumerate(zeilen):
        if a["id"] in weg:
            continue
        for b in zeilen[i + 1:]:
            if b["id"] in weg or _gleicher_offener({**_daten(b), "titel": b["titel"]}, [a]) != a["id"]:
                continue
            da, dbb = _daten(a), _daten(b)
            rang = lambda d: (bool(d.get("plan")), len(d.get("belege") or []))  # noqa: E731
            behalten, ab = (a, b) if rang(da) >= rang(dbb) else (b, a)
            _anhaengen(behalten["id"], _daten(ab).get("belege") or [], str(ab.get("erstellt") and
                       datetime.datetime.fromtimestamp(ab["erstellt"], BERLIN).date().isoformat()), _daten(ab).get("vorschlag"))
            d = _daten(ab)
            d["zusammengelegt_in"] = behalten["id"]
            db.ausfuehren("UPDATE rsi SET stand='zusammengelegt', daten=?, geaendert=? WHERE id=?",
                          (json.dumps(d, ensure_ascii=False), time.time(), ab["id"]))
            weg.add(ab["id"])
            paare.append((behalten["id"], ab["id"]))
            if ab is a:
                break
    return paare


def befunde_sammeln(seit: float, bis: float | None = None) -> list[dict[str, Any]]:
    """Stellen, an denen es hakte -- nur aus den gespeicherten Gespraechen, ohne Modell."""
    bis = bis or time.time()
    befunde: list[dict[str, Any]] = []
    gespraeche = db.alle("SELECT id, art, titel FROM gespraeche WHERE art IN ('talk','neo') AND geaendert>=? ORDER BY geaendert DESC", (seit,))
    for g in gespraeche:
        msgs = db.alle("SELECT id, rolle, text, daten, zeit FROM nachrichten WHERE gespraech_id=? AND zeit<=? ORDER BY id", (g["id"], bis))
        letzte_meldung = -99
        for i, n in enumerate(msgs):
            if n["rolle"] != "du" or (n.get("zeit") or 0) < seit:
                continue
            t = _anzeige(n)
            if not t:
                continue
            antwort = next((m for m in msgs[i + 1:i + 3] if m["rolle"] != "du"), None)
            a_text = (antwort or {}).get("text") or ""
            vorige = next((_anzeige(m) for m in reversed(msgs[:i]) if m["rolle"] == "du"), "")
            signale = []
            if KORREKTUR.search(t):
                signale.append("Veiko widerspricht")
            if PANNE.search(a_text[:600]):
                signale.append(("Talk" if g["art"] == "talk" else "Neo") + " gibt auf")
            w1, w2 = _woerter(t), _woerter(vorige)
            # Mehrmals blaettern ist Lesen, keine Wiederholung einer gescheiterten Bitte.
            if (len(w1) >= 2 and len(w2) >= 2 and len(w1 & w2) / len(w1 | w2) >= 0.6
                    and not _BLAETTERN_GRUND.search(t)):
                signale.append("Veiko wiederholt seine Bitte")
            if not signale or i - letzte_meldung <= 1:
                # Zwei Treffer direkt hintereinander sind meist DIESELBE Panne -- einmal reicht.
                continue
            letzte_meldung = i
            davor = [m for m in msgs[max(0, i - 4):i]]
            daten = (antwort or {}).get("daten") if isinstance((antwort or {}).get("daten"), dict) else {}
            d_n = n.get("daten") if isinstance(n.get("daten"), dict) else {}
            befunde.append({
                "gespraech_id": g["id"], "art": g["art"], "zeit": n.get("zeit"), "signale": signale,
                "davor": [{"wer": "Veiko" if m["rolle"] == "du" else ("Talk" if g["art"] == "talk" else "Neo"),
                           "text": _kurz(_anzeige(m) if m["rolle"] == "du" else m.get("text"), 300)} for m in davor],
                "veiko": _kurz(t, 400), "antwort": _kurz(a_text, 500),
                # Woran man die Ursache erkennt: kam die Antwort aus der Bedienung ohne Modell, welche
                # Aktionen wurden vorgeschlagen, auf welcher Seite stand Veiko.
                "weg": (daten or {}).get("modell") or "", "kontext": (d_n or {}).get("kontext") or {},
                "aktionen": [v.get("aktion") for v in ((daten or {}).get("vorschlaege") or []) if isinstance(v, dict)],
            })
    befunde.sort(key=lambda b: b.get("zeit") or 0, reverse=True)
    return befunde[:MAX_BEFUNDE]


def schon_behoben(b: dict[str, Any]) -> bool:
    """Spielt einen Talk-Befund mit dem HEUTIGEN Code nach (nur die Bedienung, ohne Modell, ohne etwas
    auszufuehren). Antwortet Talk heute anders und ohne aufzugeben, ist die Panne inzwischen behoben.
    Gemessen am 23.10.2026: ohne diese Pruefung schlug Neo drei Dinge vor, die am selben Morgen schon
    behoben waren -- er erkennt das an den Commits allein nicht zuverlaessig."""
    if b.get("art") != "talk":
        return False
    from . import gespraech
    t = re.sub(r"\s+", " ", re.sub(r"[,;:.!]", " ", b.get("veiko") or "")).strip()
    # Was heute im Browser oder ueber eine Regel mit Gespraechsbezug laeuft, laesst sich hier nicht
    # nachspielen -- deshalb von Hand: fremde Schrift verwirft stimme.hoeren, "Dialog b…" beendet das
    # Freisprechen (talk.js istEnde), "nicht X, sondern Y" wiederholt die vorige Bitte (_KORREKTUR).
    buchst = [c for c in t if c.isalpha()]
    if buchst and sum(1 for c in buchst if ord(c) > 0x24F) / len(buchst) > 0.3:
        return True
    if len(t.split()) <= 8 and re.search(r"\bdialog\s*(b\w*|bin)\b", t, re.I):
        return True
    if gespraech._KORREKTUR.search(t):
        return True
    try:
        r = gespraech.bedienung_erkennen(b["veiko"], b.get("kontext") or None, None)
    except Exception:  # noqa: BLE001
        return False
    if not r or not (r.get("zeigen") or r.get("oeffnen") or r.get("werkzeug")):
        return False
    return (r.get("satz") or "") != (b.get("antwort") or "") and not PANNE.search(r.get("satz") or "")


def befunde_text(befunde: list[dict[str, Any]]) -> str:
    teile = []
    for i, b in enumerate(befunde, 1):
        zeit = time.strftime("%d.%m. %H:%M", time.localtime(b.get("zeit") or 0))
        vorher = "\n".join(f"   {x['wer']}: {x['text']}" for x in b["davor"][-3:])
        teile.append(f"[{i}] {zeit} · {'Talk' if b['art'] == 'talk' else 'Neo'} · {', '.join(b['signale'])}"
                     + (f" · Seite: {b['kontext'].get('art')}" if isinstance(b.get("kontext"), dict) and b["kontext"].get("art") else "")
                     + (f"\n   (vorher)\n{vorher}" if vorher else "")
                     + f"\n   VEIKO: {b['veiko']}\n   ANTWORT: {b['antwort'] or '(keine)'}"
                     + (f"\n   Weg der Antwort: {'Bedienung ohne Modell' if b['weg'] == 'bedienung' else b['weg']}" if b.get("weg") else "")
                     + (f" · vorgeschlagene Aktionen: {', '.join(a for a in b['aktionen'] if a)}" if b.get("aktionen") else ""))
    return "\n\n".join(teile)


# ---------------------------------------------------------------- 2. Neo analysiert (nur lesend)
NEO_RSI_SYSTEM = (
    "Du bist Neo, Cockpit Engineer. Heute Nacht hast du EINE Aufgabe: aus Veikos Gesprächen mit dem Cockpit herausfinden, "
    "was nicht gut funktioniert hat, und VORSCHLÄGE machen, wie man es verbessert. Du änderst NICHTS -- du hast nur Werkzeuge "
    "zum Lesen (datei_lesen, suche, projektwissen). Umgesetzt wird erst, wenn Dario geprüft und Veiko entschieden hat.\n\n"
    "So gehst du vor:\n"
    "1. Lies die Befunde. Fasse zusammen, was zusammengehört (dieselbe Ursache = ein Vorschlag). Einzelne Hörfehler der "
    "Spracherkennung, die niemand verhindern kann, und Fälle, in denen das Cockpit richtig gehandelt hat, lässt du weg.\n"
    "2. Sieh für jeden Kandidaten im Code nach, WO es hakt: Talk-Bedienung und Erkennung stehen in cockpit/gespraech.py "
    "(bedienung_erkennen, oeffnen_suchen, SEITEN, die Anweisung SYSTEM), das Ausführen von Aktionen in vorschlaege_ausfuehren, "
    "die Spracherkennung in cockpit/stimme.py, der Browser-Teil in frontend/js/talk.js, Neo in cockpit/neo.py. "
    "Hol dir mit projektwissen die Regeln des Bereichs. Behaupte keine Ursache, die du nicht im Code gesehen hast -- "
    "dann schreib „Ursache nicht sicher“.\n"
    f"3. Höchstens {MAX_VORSCHLAEGE} Vorschläge, die wichtigsten zuerst (was Veiko am häufigsten oder am meisten stört). "
    "Jeder Vorschlag hat eine EIGENE Ursache -- zwei Befunde mit derselben Ursache sind EIN Vorschlag mit beiden Belegen.\n"
    "4. KONKRET: „vorschlag“ nennt Datei, Funktion und genau, was dort anders werden soll (welches Muster, welche Regel, "
    "welcher Satz, mit einem kurzen Beispiel). „Die Erkennung verbessern“ oder „besser verstehen“ ist kein Vorschlag -- "
    "so etwas lässt du weg. Lieber zwei handfeste Vorschläge als fünf allgemeine.\n\n"
    "Am Ende antwortest du NUR mit einem JSON-Block:\n"
    "```json\n{\"vorschlaege\": [{\"titel\": \"kurz, was besser werden soll\", \"problem\": \"was Veiko erlebt hat, in seinen Worten, "
    "zwei Sätze\", \"belege\": [Nummern der Befunde], \"ursache\": \"wo im Code es hakt (Datei, Funktion) und warum\", "
    "\"vorschlag\": \"was genau geändert werden soll, konkret genug zum Umsetzen\", \"dateien\": [\"cockpit/…\"], "
    "\"aufwand\": \"klein|mittel|gross\", \"risiko\": \"was dabei kaputtgehen könnte\"}]}\n```\n"
    "Gibt es nichts Sinnvolles zu verbessern: {\"vorschlaege\": []}. Deutsch, ohne Fachjargon in titel und problem.\n\n"
    "DERSELBE FEHLER, MEHRFACH: Taucht ein Fehler in mehreren Gesprächen auf, ist das EIN Vorschlag mit allen Belegen -- "
    "nicht einer je Gespräch. Gehört ein Befund zu einem der SCHON OFFENEN VORSCHLÄGE (gleiches Fehlerbild, gleiche Stelle "
    "im Code, auch wenn Veiko andere Worte benutzt hat), schlag ihn NICHT neu vor, sondern hänge ihn an: ein Eintrag "
    "{\"gleich_wie\": \"s…\", \"belege\": [Nummern]} in derselben Liste \"vorschlaege\". Unterschiedlich ist ein Fehler nur, "
    "wenn er eine andere Ursache hat -- „Talk öffnet das falsche Projekt“ und „Talk öffnet das falsche Ergebnis“ sind "
    "derselbe Fehler, wenn beide an derselben Suche liegen.")

LESE_WERKZEUGE = ("datei_lesen", "suche", "projektwissen")


async def neo_analysieren(befunde: list[dict[str, Any]], offene: list[str]) -> tuple[list[dict[str, Any]], str]:
    from . import neo
    tools = [{"type": "function", "function": w} for w in neo.WERKZEUGE if w["name"] in LESE_WERKZEUGE]
    lauf: dict[str, Any] = {"gelesen": set(), "dateien": [], "schritte": []}
    verlauf: list[dict[str, Any]] = [{"role": "user", "content":
        "BEFUNDE AUS VEIKOS GESPRÄCHEN (neueste zuerst):\n\n" + befunde_text(befunde)
        + ("\n\nSCHON OFFENE VORSCHLÄGE (nicht noch einmal vorschlagen -- gehört ein Befund dazu, hänge ihn mit "
           "gleich_wie an):\n- " + "\n- ".join(offene) if offene else "")
        + "\n\nSieh im Code nach und liefere dann den JSON-Block."}]
    text = ""
    # Der aktuelle Stand (Landkarte, letzte Commits): viele Pannen der letzten Tage sind schon behoben --
    # Neo soll das an den Commits erkennen und sie nicht ein zweites Mal vorschlagen.
    from . import neo_stand
    system = (NEO_RSI_SYSTEM + "\n\nWICHTIG: Prüfe für jeden Befund an den letzten Commits unten (und im Code), ob er seit dem "
              "Gespräch schon behoben ist. Behobenes schlägst du NICHT vor.\n" + neo_stand.stand_text())
    for schritt in range(MAX_SCHRITTE):
        _setzen(schritt=f"Neo sieht im Code nach (Schritt {schritt + 1})")
        antwort = await llm.chat_mit_werkzeugen(MODELL_NEO, system, neo._gekuerzt(verlauf), tools, num_ctx=neo.NUM_CTX)
        text = (antwort.get("content") or "").strip()
        aufrufe = antwort.get("tool_calls") or []
        if not aufrufe and "<function=" in text:
            text, aufrufe = neo._xml_aufrufe(text)
        verlauf.append({"role": "assistant", "content": text, **({"tool_calls": aufrufe} if aufrufe else {})})
        if not aufrufe:
            break
        for a in aufrufe:
            fn = a.get("function") or {}
            name = fn.get("name") or ""
            eingabe = fn.get("arguments")
            if isinstance(eingabe, str):
                try:
                    eingabe = json.loads(eingabe)
                except ValueError:
                    eingabe = {}
            if name not in LESE_WERKZEUGE:
                # Auch wenn das Modell ein schreibendes Werkzeug erfindet: es gibt keins.
                ergebnis = "Abgewiesen: heute Nacht nur lesen. Änderungen schlägst du im JSON-Block vor."
            else:
                ergebnis = await neo.werkzeug(name, eingabe if isinstance(eingabe, dict) else {}, lauf)
            verlauf.append({"role": "tool", "content": ergebnis})
    else:
        verlauf.append({"role": "user", "content": "Die Zeit für Nachsehen ist um. Liefere JETZT den JSON-Block mit dem, was du weißt."})
        text = (await llm.chat_mit_werkzeugen(MODELL_NEO, system, neo._gekuerzt(verlauf), [], num_ctx=neo.NUM_CTX)).get("content") or ""
    d = llm.json_aus(text)
    if not isinstance(d, dict) or not isinstance(d.get("vorschlaege"), list):
        # Einmal nachfragen -- ein fehlender Block ist der haeufigste Fehler eines lokalen Modells.
        verlauf.append({"role": "user", "content": "Bitte NUR den JSON-Block mit den Vorschlägen, ohne weiteren Text."})
        text = (await llm.chat_mit_werkzeugen(MODELL_NEO, system, neo._gekuerzt(verlauf), [], num_ctx=neo.NUM_CTX)).get("content") or ""
        d = llm.json_aus(text)
    if not isinstance(d, dict) or not isinstance(d.get("vorschlaege"), list):
        raise llm.ModellFehler("Neo hat keine lesbaren Vorschläge geliefert.")
    gelesen = sorted(lauf["gelesen"])
    aus = []
    for v in d["vorschlaege"]:
        if isinstance(v, dict) and v.get("gleich_wie"):
            # Ein Befund zu einem schon offenen Vorschlag: anhaengen statt neu (lauf() fuehrt zusammen).
            nummern = [int(x) for x in (v.get("belege") or []) if str(x).isdigit() and 1 <= int(x) <= len(befunde)]
            aus.append({"gleich_wie": str(v["gleich_wie"]), "belege": [befunde[n - 1] for n in nummern][:6]})
    for v in [x for x in d["vorschlaege"] if isinstance(x, dict) and not x.get("gleich_wie")][:MAX_VORSCHLAEGE]:
        if not isinstance(v, dict) or not str(v.get("titel") or "").strip() or not str(v.get("vorschlag") or "").strip():
            continue
        nummern = [int(x) for x in (v.get("belege") or []) if str(x).isdigit() and 1 <= int(x) <= len(befunde)]
        aus.append({"titel": _kurz(v["titel"], 120), "problem": _kurz(v.get("problem"), 800), "ursache": _kurz(v.get("ursache"), 1500),
                    "vorschlag": str(v.get("vorschlag"))[:4000], "dateien": [str(x)[:120] for x in (v.get("dateien") or [])][:10],
                    "aufwand": v.get("aufwand") if v.get("aufwand") in ("klein", "mittel", "gross") else "mittel",
                    "risiko": _kurz(v.get("risiko"), 800), "belege": [befunde[n - 1] for n in nummern][:6]})
    # Doppelte zusammenlegen (gemessen am 23.10.: drei von fuenf Vorschlaegen meinten dieselbe Stelle
    # in bedienung_erkennen) -- gleiche Woerter in Titel und Ursache, die Belege wandern mit.
    zusammen: list[dict[str, Any]] = []
    for v in aus:
        if v.get("gleich_wie"):
            zusammen.append(v)
            continue
        w = _woerter(v["titel"] + " " + v["ursache"])
        gleich = next((z for z in zusammen if not z.get("gleich_wie") and len(w & _woerter(z["titel"] + " " + z["ursache"])) / max(1, len(w | _woerter(z["titel"] + " " + z["ursache"]))) >= 0.45), None)
        if gleich:
            schon = {(b.get("gespraech_id"), b.get("zeit")) for b in gleich["belege"]}
            gleich["belege"] += [b for b in v["belege"] if (b.get("gespraech_id"), b.get("zeit")) not in schon][:6 - len(gleich["belege"])]
            gleich["vorschlag"] += "\n\nDazu: " + v["vorschlag"]
        else:
            zusammen.append(v)
    return zusammen, ", ".join(p.split("/vve-cp-r2/")[-1] for p in gelesen)


# ---------------------------------------------------------------- 3. Dario prueft
DARIO_RSI_SYSTEM = (
    "Du bist Dario, unabhängiger Prüfer für das VvE Cockpit (Veikos selbst gehostetes KI-Cockpit: FastAPI-Backend unter "
    "cockpit/, Preact-Frontend unter frontend/js/, Talk = Sprachdialog, Neo = lokaler Coding-Agent). Neo hat aus Veikos "
    "Gesprächen einen VERBESSERUNGSVORSCHLAG abgeleitet. Noch ist nichts umgesetzt. Prüfe:\n"
    "1. Trägt der Vorschlag -- löst er, was Veiko in den Belegen erlebt hat? Stimmt die Ursache?\n"
    "2. Risiken: was könnte dabei kaputtgehen?\n"
    "3. WER soll ihn ausarbeiten: \"neo\" (klein und klar umrissen, eine oder zwei Stellen -- Neo arbeitet lokal und kostenlos, "
    "seine Änderung prüfst du vor dem Einspielen ohnehin noch einmal), \"dario\" (groß, mehrere Bereiche, heikel -- erst ein "
    "sauberer Umsetzungsplan von dir) oder \"keiner\" (verwerfen).\n"
    "4. Formuliere den NÄCHSTEN AUFTRAG für den Gewählten so, dass er ihn ohne Rückfrage ausführen kann.\n"
    "Antworte NUR mit JSON: {\"urteil\": \"sinnvoll|ueberarbeiten|verwerfen\", \"begruendung\": \"zwei, drei Sätze für Veiko, "
    "ohne Fachjargon\", \"risiken\": [\"…\"], \"wer_weiter\": \"neo|dario|keiner\", \"warum_wer\": \"ein Satz\", "
    "\"naechster_auftrag\": \"der konkrete Auftrag\"}")


def _vorschlag_text(v: dict[str, Any]) -> str:
    belege = "\n".join(f"- Veiko: {b['veiko']}\n  Antwort: {b['antwort'] or '(keine)'}" for b in v.get("belege") or [])
    return (f"TITEL: {v['titel']}\n\nPROBLEM: {v.get('problem')}\n\nBELEGE AUS DEN GESPRÄCHEN:\n{belege or '(keine)'}\n\n"
            f"URSACHE LAUT NEO: {v.get('ursache')}\n\nNEOS VORSCHLAG:\n{v.get('vorschlag')}\n\n"
            f"DATEIEN: {', '.join(v.get('dateien') or []) or '(nicht genannt)'} · AUFWAND: {v.get('aufwand')} · RISIKO LAUT NEO: {v.get('risiko')}")


async def _dario(system: str, frage: str, aus_tokens: int) -> tuple[str, float, str]:
    """Ein Aufruf bei Dario mit Kostenbuchung. Gibt (Antwort, Kosten in $, Modell) zurueck."""
    from . import langlauf, teamchat
    modell = await teamchat._extern_modell("dario")
    t0 = time.time()
    with llm.taetig("Dario prüft einen RSI-Vorschlag"):
        antwort = await teamchat._cloud_chat("dario", modell, system, [{"role": "user", "content": frage}])
    z = db.eine("SELECT SUM(tok_ein) AS ein, SUM(tok_aus) AS aus FROM verbrauch WHERE art='cloud' AND zeit>=? AND wer=?",
                (t0 - 1, "dario")) or {}
    kosten = langlauf._usd("claude", z.get("ein") or 0, z.get("aus") or 0) if (z.get("ein") or z.get("aus")) \
        else langlauf._usd("claude", int((len(system) + len(frage)) / 3.5), aus_tokens)
    return antwort, kosten, modell


def schaetzung(system: str, frage: str, aus_tokens: int) -> float:
    from . import langlauf
    return langlauf._usd("claude", int((len(system) + len(frage)) / 3.5), aus_tokens)


async def dario_pruefen(rid: str, rest_budget: float | None = None) -> dict[str, Any]:
    r = db.holen("rsi", rid)
    if not r:
        return {"ok": False, "grund": "Vorschlag nicht gefunden"}
    d = r["daten"] if isinstance(r["daten"], dict) else {}
    frage = _vorschlag_text(d)
    s = schaetzung(DARIO_RSI_SYSTEM, frage, AUS_SCHAETZUNG)
    if rest_budget is not None and s > rest_budget:
        d["dario"] = {"urteil": "nicht_geprueft", "begruendung": f"Das Nachtbudget reichte nicht mehr (geschätzt $ {s:.2f}, übrig "
                      f"$ {max(rest_budget, 0):.2f}). Auf der Seite lässt sich die Prüfung von Hand anstoßen.", "kosten": 0}
        _speichern(rid, d, "neu")
        return {"ok": False, "kosten": 0, "grund": "Budget"}
    try:
        antwort, kosten, modell = await _dario(DARIO_RSI_SYSTEM, frage, AUS_SCHAETZUNG)
    except llm.ModellFehler as f:
        d["dario"] = {"urteil": "nicht_geprueft", "begruendung": f"Hat nicht geklappt: {f}", "kosten": 0}
        _speichern(rid, d, "neu")
        return {"ok": False, "kosten": 0, "grund": str(f)}
    j = llm.json_aus(antwort)
    if not isinstance(j, dict) or j.get("urteil") not in ("sinnvoll", "ueberarbeiten", "verwerfen"):
        j = {"urteil": "nicht_geprueft", "begruendung": "Darios Antwort war nicht lesbar.", "risiken": [], "wer_weiter": "keiner"}
    wer = j.get("wer_weiter") if j.get("wer_weiter") in ("neo", "dario", "keiner") else "keiner"
    d["dario"] = {"urteil": j["urteil"], "begruendung": _kurz(j.get("begruendung"), 1500),
                  "risiken": [_kurz(x, 400) for x in (j.get("risiken") or [])][:6], "wer_weiter": wer,
                  "warum_wer": _kurz(j.get("warum_wer"), 500), "naechster_auftrag": str(j.get("naechster_auftrag") or "")[:4000],
                  "modell": modell, "kosten": round(kosten, 4), "zeit": time.time()}
    _speichern(rid, d, "geprueft" if j["urteil"] != "nicht_geprueft" else "neu")
    return {"ok": True, "kosten": kosten}


def _speichern(rid: str, d: dict[str, Any], stand_: str | None = None) -> None:
    if stand_:
        db.ausfuehren("UPDATE rsi SET daten=?, stand=?, geaendert=? WHERE id=?", (json.dumps(d, ensure_ascii=False), stand_, time.time(), rid))
    else:
        db.ausfuehren("UPDATE rsi SET daten=?, geaendert=? WHERE id=?", (json.dumps(d, ensure_ascii=False), time.time(), rid))


# ---------------------------------------------------------------- Der naechtliche Lauf
async def lauf(von_hand: bool = False) -> dict[str, Any]:
    start = time.time()
    seit = float(db.einstellung("rsi_bis", 0) or 0) or (start - ERSTER_RUECKBLICK)
    _setzen(laeuft=True, start=start, ende=None, fehler=None, schritt="Sammle, wo es in den Gesprächen hakte",
            von_hand=von_hand, kosten=0)
    neu: list[str] = []
    kosten = 0.0
    try:
        alle = befunde_sammeln(seit, start)
        befunde = [b for b in alle if not schon_behoben(b)]
        behoben = len(alle) - len(befunde)
        _setzen(befunde=len(befunde), behoben=behoben)
        if not befunde:
            db.einstellung_setzen("rsi_bis", start)
            _setzen(laeuft=False, ende=time.time(), schritt=None, neu=0,
                    ergebnis=(f"{behoben} Stellen gefunden, an denen es hakte -- alle sind inzwischen behoben." if behoben
                              else "Keine Stelle gefunden, an der es hakte -- nichts vorzuschlagen."))
            return stand()
        # Mit Kennung und Problem, nicht nur dem Titel (23.10.2026: zwei Laeufe ergaben dieselben vier
        # Vorschlaege doppelt -- Neo kannte von den offenen nur die Titel).
        offen_zeilen = db.alle(f"SELECT id, titel, daten FROM rsi WHERE stand IN {OFFEN_STAENDE}")
        offene = [f"{r['id']}: {r['titel']} -- {_kurz(_daten(r).get('problem'), 220)}" for r in offen_zeilen]
        with llm.taetig("RSI: Neo sucht Verbesserungen"):
            vorschlaege, gelesen = await neo_analysieren(befunde, offene)
        nacht = datetime.datetime.now(BERLIN).date().isoformat()
        angehaengt = 0
        for v in vorschlaege:
            # Derselbe Fehler wie ein offener Vorschlag: Neo sagt es (gleich_wie), sonst die Wortprobe.
            ziel = v.get("gleich_wie") if v.get("gleich_wie") in {r["id"] for r in offen_zeilen} else None
            ziel = ziel or (None if v.get("gleich_wie") else _gleicher_offener(v, offen_zeilen))
            if ziel or v.get("gleich_wie"):
                if ziel:
                    _anhaengen(ziel, v.get("belege") or [], nacht, v.get("vorschlag"))
                    angehaengt += 1
                continue
            rid = db.neue_id("s")
            db.einfuegen("rsi", {"id": rid, "nacht": nacht, "stand": "neu", "titel": v["titel"],
                                 "daten": {**v, "neo_gelesen": gelesen, "befunde_gesamt": len(befunde)},
                                 "erstellt": time.time(), "geaendert": time.time()})
            neu.append(rid)
        # Erst jetzt weiterruecken: scheitert Neo, kommen dieselben Gespraeche naechste Nacht wieder dran.
        db.einstellung_setzen("rsi_bis", start)
        # Zweiter Riegel: was trotzdem doppelt angelegt wurde, gleich zusammenlegen -- Dario prueft dann nur einen.
        weg = {ab for _, ab in doppelte_zusammenlegen()}
        neu = [r for r in neu if r not in weg]
        angehaengt += len(weg)
        for i, rid in enumerate(neu, 1):
            if not db.einstellung("rsi_dario_auto", True):
                break
            _setzen(schritt=f"Dario prüft Vorschlag {i} von {len(neu)}")
            r = await dario_pruefen(rid, budget() - kosten)
            kosten += r.get("kosten") or 0
            _setzen(kosten=round(kosten, 4))
        _setzen(laeuft=False, ende=time.time(), schritt=None, neu=len(neu),
                ergebnis=(f"{len(befunde)} Stellen gefunden, an denen es hakte; daraus {len(neu)} neue Vorschläge."
                          if neu else f"{len(befunde)} Stellen gefunden, aber kein neuer Vorschlag.")
                + (f" {angehaengt}× war es ein Fehler, der schon als Vorschlag offen ist -- dort als weiteres Vorkommen angehängt." if angehaengt else "")
                + (f" {behoben} weitere sind inzwischen behoben." if behoben else ""))
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        _setzen(laeuft=False, ende=time.time(), schritt=None, neu=len(neu), fehler=f"{e.__class__.__name__}: {str(e)[:300]}")
    return stand()


def starten(von_hand: bool = True) -> bool:
    global _lauf
    if laeuft():
        return False
    _lauf = asyncio.create_task(lauf(von_hand))
    return True


async def schleife() -> None:
    """Einmal je Nacht, 03--05 Uhr deutscher Zeit (Veikos Vorgabe, 23.10.2026; Nachtplan in nachtplan.py).
    Die Modell-Revision startet spaetestens um 03:00 und misst Antwortzeiten; laeuft sie noch, wartet
    RSI auf sie -- zwei Modelle gleichzeitig verfaelschten ihre Messung. Aber hoechstens bis 03:30,
    sonst fiele RSI in einer Nacht mit langer Revision ganz aus."""
    await asyncio.sleep(120)
    while True:
        try:
            jetzt = datetime.datetime.now(BERLIN)
            heute = jetzt.date().isoformat()
            from . import revision
            spaet = jetzt.hour * 60 + jetzt.minute >= 3 * 60 + 30
            if an() and VON <= jetzt.hour < BIS and stand().get("nacht") != heute and not laeuft() \
                    and (spaet or not (revision.stand() or {}).get("laeuft")):
                _setzen(nacht=heute)
                starten(von_hand=False)
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(300)


# ---------------------------------------------------------------- 4. Veiko entscheidet
def neo_auftrag_text(r: dict[str, Any]) -> str:
    d = r["daten"] if isinstance(r["daten"], dict) else {}
    dario = d.get("dario") or {}
    plan = d.get("plan") or {}
    return ("RSI-AUFTRAG (Verbesserung aus Veikos Gesprächen, von Veiko freigegeben)\n\n"
            + _vorschlag_text(d)
            + (f"\n\nDARIOS URTEIL: {dario.get('urteil')} -- {dario.get('begruendung')}" if dario.get("urteil") else "")
            + (f"\nDARIOS RISIKEN: {'; '.join(dario.get('risiken') or [])}" if dario.get("risiken") else "")
            + (f"\n\nDARIOS AUFTRAG AN DICH:\n{dario.get('naechster_auftrag')}" if dario.get("naechster_auftrag") and not plan else "")
            + (f"\n\nDARIOS UMSETZUNGSPLAN -- setz genau diesen um:\n{plan.get('text')}" if plan.get("text") else "")
            + "\n\nArbeite wie immer: erst lesen, dann klein ändern, vormerken. Dario prüft vor dem Einspielen."
            + ("\nAm Ende MUSS eine vorgemerkte Code-Änderung stehen (datei_aendern) -- ein Bericht oder eine Untersuchung "
               "allein erfüllt diesen Auftrag nicht. Nutze nur Namen, die es im Code gibt oder die du selbst definierst."
               if plan.get("fuer_umsetzung") else ""))


async def neo_beauftragen(rid: str, hinweis: str = "", kein_neustart: bool = False) -> dict[str, Any]:
    """Ein normaler Neo-Auftrag in einem eigenen Gespraech -- mit Darios Freigabe vor dem Einspielen
    (neo_freigabe.py). Veiko sieht Neo dort arbeiten und kann eingreifen wie in jedem Neo-Gespraech.
    hinweis/kein_neustart: aus einer RSI-Serie (rsi_serie.py) -- was die uebrigen Punkte der Serie
    betrifft, und kein Neustart zwischen den Punkten."""
    from . import neo
    r = db.holen("rsi", rid)
    if not r:
        return {"ok": False, "grund": "Vorschlag nicht gefunden"}
    gid = db.neue_id("g")
    db.einfuegen("gespraeche", {"id": gid, "art": "neo", "titel": f"RSI: {r['titel']}"[:80], "erstellt": time.time(), "geaendert": time.time()})
    text = neo_auftrag_text(r) + (f"\n\n{hinweis}" if hinweis else "")
    jid = await neo.senden(gid, text, [], kein_neustart=kein_neustart)
    d = r["daten"] if isinstance(r["daten"], dict) else {}
    d["neo"] = {"gespraech_id": gid, "job": jid, "zeit": time.time()}
    _speichern(rid, d, "bei_neo")
    return {"ok": True, "gespraech_id": gid, "job": jid}


DARIO_PLAN_SYSTEM = (
    "Du bist Dario und schreibst für das VvE Cockpit (FastAPI-Backend unter cockpit/, Preact-Frontend ohne Build-Schritt unter "
    "frontend/js/, deutsche Bezeichner und Kommentare, die das WARUM erklären) einen UMSETZUNGSPLAN für einen "
    "Verbesserungsvorschlag. Neo, ein lokales Coding-Modell, setzt ihn danach um -- schreib ihn also so, dass ein "
    "weniger starkes Modell ihn Schritt für Schritt ausführen kann: welche Datei, welche Funktion, was genau ändern "
    "(mit kurzen Code-Ausschnitten, wo es hilft), was NICHT anfassen, woran man prüft, dass es geklappt hat. "
    "Markdown, Deutsch. Höchstens etwa 1.200 Wörter.")


def code_auszug(d: dict[str, Any], grenze: int = 16000) -> str:
    """Die Funktionen, um die es geht, im Wortlaut -- damit Dario einen Plan gegen den ECHTEN Code schreibt
    und nicht gegen Neos Beschreibung davon (23.10.2026: Plaene ohne Code fuehrten zu Aenderungen, die Dario
    danach selbst ablehnte). Gesucht wird in den genannten Dateien nach Namen, die in Ursache und Vorschlag stehen."""
    import ast
    from .konfig import WURZEL
    text = " ".join(str(d.get(k) or "") for k in ("ursache", "vorschlag", "problem")) + " " + \
        str((d.get("dario") or {}).get("naechster_auftrag") or "")
    namen = set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]{3,})\b", text))
    teile, laenge = [], 0
    for rel in (d.get("dateien") or [])[:6]:
        pfad = (WURZEL / str(rel).lstrip("/")).resolve()
        if not str(pfad).startswith(str(WURZEL)) or not pfad.is_file():
            continue
        quelle = pfad.read_text(encoding="utf-8", errors="replace")
        zeilen = quelle.splitlines()
        stuecke = []
        if pfad.suffix == ".py":
            try:
                baum = ast.parse(quelle)
            except SyntaxError:
                continue
            funktionen = [k for k in ast.walk(baum) if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for k in funktionen:
                if k.name in namen:
                    stuecke.append((k.lineno, "\n".join(zeilen[k.lineno - 1:k.end_lineno])))
            for k in ast.walk(baum):
                if isinstance(k, ast.Assign) and any(isinstance(t, ast.Name) and t.id in namen for t in k.targets) and k.col_offset == 0:
                    stuecke.append((k.lineno, "\n".join(zeilen[k.lineno - 1:k.end_lineno])))
            if not stuecke:
                # Keine Funktion genannt ("Talk erkennt den Befehl nicht"): die Funktionen, in denen Veikos
                # zitierte Woerter vorkommen -- dort steht die Erkennung, die fehlt oder falsch greift.
                zitiert = {z.lower() for z in re.findall(r"[„\"“]([^“\"”]{3,40})[“\"”]", text)}
                zitiert |= {str(b.get("veiko") or "").lower()[:40] for b in d.get("belege") or [] if b.get("veiko")}
                stich = {w for z in zitiert for w in re.findall(r"[a-zäöüß]{5,}", z)}
                bewertet = []
                for k in funktionen:
                    rumpf = "\n".join(zeilen[k.lineno - 1:k.end_lineno]).lower()
                    treffer = sum(1 for w in stich if w in rumpf)
                    if treffer and k.end_lineno - k.lineno < 250:
                        bewertet.append((treffer, k))
                for _, k in sorted(bewertet, key=lambda x: -x[0])[:3]:
                    stuecke.append((k.lineno, "\n".join(zeilen[k.lineno - 1:k.end_lineno])))
        else:
            for i, z in enumerate(zeilen):
                m = re.match(r"\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)", z)
                if m and m.group(1) in namen:
                    stuecke.append((i + 1, "\n".join(zeilen[i:i + 60])))
        for zeile, s in sorted(stuecke):
            s = s[:6000]
            if laenge + len(s) > grenze:
                break
            teile.append(f"--- {rel}, ab Zeile {zeile} ---\n{s}")
            laenge += len(s)
    return "\n\n".join(teile)


async def dario_plan(rid: str, zum_umsetzen: bool = False) -> dict[str, Any]:
    """zum_umsetzen (RSI-Serie): Veiko hat entschieden, dass es JETZT umgesetzt wird -- der Plan muss in einer
    Code-Aenderung enden, auch wenn Darios frueherer Auftrag "erst untersuchen" lautete (23.10.2026: genau das
    liess Neo scheitern -- er sollte Code liefern, sein Auftrag verlangte einen Bericht)."""
    r = db.holen("rsi", rid)
    if not r:
        return {"ok": False, "grund": "Vorschlag nicht gefunden"}
    d = r["daten"] if isinstance(r["daten"], dict) else {}
    code = code_auszug(d)
    frage = _vorschlag_text(d) + (f"\n\nDEINE PRÜFUNG VON VORHIN: {d['dario'].get('begruendung')}\nDEIN AUFTRAG DAZU: "
                                  f"{d['dario'].get('naechster_auftrag')}" if d.get("dario") else "")
    if code:
        frage += "\n\nDER BETROFFENE CODE IM WORTLAUT (aktueller Stand):\n" + code
    if zum_umsetzen:
        frage += ("\n\nWICHTIG: Veiko hat entschieden, dass das JETZT umgesetzt wird. Neo setzt deinen Plan direkt um, und du prüfst "
                  "danach seine Änderung. Der Plan muss deshalb in einer CODE-ÄNDERUNG enden -- kein Bericht, keine Untersuchung als "
                  "Ergebnis. Muss Neo vorher etwas nachsehen, schreib es als ersten Schritt (welche Datei, wonach suchen). Nenne die "
                  "genauen Stellen mit dem Code davor und danach, so knapp wie möglich. Ist eine Änderung nicht sinnvoll begründbar, "
                  "beginne deine Antwort mit „KEINE ÄNDERUNG:“ und dem Grund in einem Satz.")
    try:
        antwort, kosten, modell = await _dario(DARIO_PLAN_SYSTEM, frage, 4000)
    except llm.ModellFehler as f:
        return {"ok": False, "grund": f"Hat nicht geklappt: {f}"}
    d["plan"] = {"text": antwort.strip()[:20000], "kosten": round(kosten, 4), "modell": modell, "zeit": time.time(),
                 "fuer_umsetzung": zum_umsetzen, "mit_code": bool(code)}
    _speichern(rid, d, "plan")
    return {"ok": True, "kosten": kosten}


# Von Hand angestossene Dario-Aufrufe laufen im Hintergrund (eine Pruefung dauert eine halbe bis
# zwei Minuten -- so lange soll kein Knopf haengen). Die Seite fragt nach, bis er fertig ist.
ARBEITET: dict[str, str] = {}
FEHLER: dict[str, str] = {}


def im_hintergrund(rid: str, art: str) -> bool:
    if rid in ARBEITET:
        return False

    async def _los() -> None:
        try:
            r = await (dario_pruefen(rid) if art == "pruefen" else dario_plan(rid))
            if not r.get("ok") and r.get("grund"):
                FEHLER[rid] = str(r["grund"])
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            FEHLER[rid] = f"{e.__class__.__name__}: {e}"
        finally:
            ARBEITET.pop(rid, None)

    FEHLER.pop(rid, None)
    ARBEITET[rid] = art
    asyncio.create_task(_los())
    return True


def liste() -> dict[str, Any]:
    zeilen = db.alle("SELECT * FROM rsi ORDER BY CASE stand WHEN 'geprueft' THEN 0 WHEN 'neu' THEN 1 WHEN 'plan' THEN 2 "
                     "WHEN 'in_serie' THEN 3 WHEN 'bei_neo' THEN 3 WHEN 'umgesetzt' THEN 5 ELSE 6 END, erstellt DESC LIMIT 200")
    s = stand()
    for z in zeilen:
        z["arbeitet"] = ARBEITET.get(z["id"])
        z["fehler"] = FEHLER.get(z["id"])
    return {"vorschlaege": zeilen, "stand": s, "laeuft": laeuft(), "an": an(), "budget": budget(),
            "dario_auto": bool(db.einstellung("rsi_dario_auto", True)), "bis": db.einstellung("rsi_bis", 0) or 0,
            "plan_schaetzung": round(schaetzung(DARIO_PLAN_SYSTEM, "x" * 6000, 4000), 2)}
