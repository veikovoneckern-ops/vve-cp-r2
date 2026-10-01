"""
BRAINSTROM UND ExO -- zwei Verfahren auf dem EIGENEN Modell, 1:1 aus dem alten
Cockpit (server-status.html, "BRAINSTROM UND ExO", 05.09.2026) uebernommen.

  BrainStrom  sokratisches Zuspitzen einer Idee. Kern: EINE FRAGE PRO SCHRITT
              -- wer drei Fragen auf einmal sieht, beantwortet alle drei ungenau.
              Danach zwei bis drei Wege mit Abwaegung, dann ein Entwurf, dann
              eine Pruefung des Entwurfs gegen sich selbst.
              (Vorbild: obra/superpowers, Skill "brainstorming")
  ExO         Bewertung eines Projekts oder des ganzen Portfolios gegen den
              VEROEFFENTLICHTEN Rahmen der Exponential Organizations: MTP, SCALE,
              IDEAS, ExO Sprint. OpenExOs eigenes Material liegt nicht vor und wird
              nicht nachempfunden.

Anders als im alten Cockpit liegt der Stand auf dem SERVER (Einstellung
"brainstrom" bzw. "exo"), nicht im Browser:
  - Talk kann mitmachen: eine gesprochene Antwort geht an dieselbe Frage, die
    auf dem Bildschirm steht, und die naechste Frage wird vorgelesen.
  - Das Gespraech ueberlebt das Neuladen und den Wechsel des Geraets.
Es geht NICHTS in die Cloud -- beide rufen ausschliesslich Ollama auf.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from . import db, llm, stab
from .konfig import MODELL_ARBEIT

BS_MAX_FRAGEN = 8
_TASKS: dict[str, asyncio.Task] = {}


async def modell() -> str | None:
    return await llm.modell_waehlen(MODELL_ARBEIT, "qwen3.6:27b", "qwen3:30b-a3b", "llama3.3:70b")


def _stand_text() -> str:
    from .gespraech import lage_text
    try:
        return lage_text()
    except Exception:  # noqa: BLE001 -- ohne Stand geht es auch, nur ungenauer
        return ""


def _projekt_name(pid: str | None) -> str:
    p = db.holen("projekte", pid) if pid else None
    return p["name"] if p else ""


def _laeuft_noch(art: str) -> bool:
    t = _TASKS.get(art)
    return bool(t and not t.done())


def _im_hintergrund(art: str, coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _TASKS[art] = t
    return t


async def warten(art: str, sek: float = 120) -> None:
    """Fuer Talk: bis der laufende Schritt fertig ist (oder die Frist um)."""
    t = _TASKS.get(art)
    if t and not t.done():
        try:
            await asyncio.wait_for(asyncio.shield(t), timeout=sek)
        except asyncio.TimeoutError:
            pass


# ================================================================ BrainStrom
def bs_leer() -> dict[str, Any]:
    return {"thema": "", "projekt_id": None, "phase": "start", "verlauf": [], "frage": None,
            "wege": None, "weg": None, "entwurf": "", "funde": None, "laeuft": False,
            "was": "", "seit": None, "fehler": None, "genug": False, "runde": 0, "modell": None,
            "ergebnis_id": None, "projekt_angelegt": None}


def bs_stand() -> dict[str, Any]:
    s = {**bs_leer(), **(db.einstellung("brainstrom") or {})}
    if s["laeuft"] and not _laeuft_noch("brainstrom"):
        # Der Dienst wurde mitten im Schritt neu gestartet -- ehrlich sagen statt ewig "denkt nach".
        s.update(laeuft=False, fehler="Der Schritt wurde unterbrochen (Dienst neu gestartet). Bitte noch einmal.")
        db.einstellung_setzen("brainstrom", s)
    return s


def _bs_speichern(s: dict[str, Any]) -> None:
    db.einstellung_setzen("brainstrom", s)


def _bs_system() -> str:
    return ("Du führst ein sokratisches Zuspitzungsgespräch im persönlichen Projekt-Cockpit von Veiko von Eckern "
            "(Head of Corporate HR Transformation bei Krones). Antworte auf Deutsch.\n\n"
            "REGELN, die du NIE brichst:\n"
            "1. Du stellst IMMER genau EINE Frage. Nie zwei, nie eine mit Unterpunkten.\n"
            "2. Die Frage zielt auf Zweck, Rahmenbedingung oder Erfolgskriterium -- nicht auf Ausschmückung.\n"
            "3. Du bietest 2 bis 4 knappe Antwortmöglichkeiten an, wenn sich welche sinnvoll benennen lassen. Freitext bleibt immer möglich.\n"
            "4. Du fragst nichts, was schon beantwortet ist.\n"
            "5. Enthält das Thema mehrere voneinander unabhängige Vorhaben, zerlegst du es zuerst und fragst, welches zuerst bearbeitet wird.\n"
            "6. Du erfindest keine Tatsachen über den Cockpit-Bestand. Was du nicht weißt, fragst du.\n\n"
            "AKTUELLER COCKPIT-STAND:\n" + _stand_text())


def _bs_verlauf_text(s: dict[str, Any]) -> str:
    if not s["verlauf"]:
        return "(noch nichts beantwortet)"
    return "\n".join(f"{i + 1}. FRAGE: {v['frage']}\n   ANTWORT: {v['antwort']}" for i, v in enumerate(s["verlauf"]))


async def _bs_schritt(art: str) -> None:
    """Ein Rechenschritt im Hintergrund: naechste Frage, Entwurf oder Pruefung."""
    s = bs_stand()
    m = await modell()
    try:
        if not m:
            raise llm.ModellFehler("Kein lokales Modell installiert.")
        s["modell"] = m
        if art == "frage":
            genug = s["genug"] or len(s["verlauf"]) >= BS_MAX_FRAGEN
            anweisung = (_bs_system() + f"\n\nTHEMA: {s['thema']}" +
                         (f"\nGEHÖRT ZU PROJEKT: {_projekt_name(s['projekt_id'])}" if s["projekt_id"] else "") +
                         f"\n\nBISHERIGES GESPRÄCH:\n{_bs_verlauf_text(s)}\n\n"
                         "Entscheide, was jetzt dran ist, und antworte NUR mit JSON:\n"
                         '{"phase":"zerlegen"|"frage"|"wege",\n'
                         ' "zerlegen":["Vorhaben 1","Vorhaben 2"],\n'
                         ' "frage":"die eine Frage",\n'
                         ' "warum":"ein Satz, warum diese Frage jetzt zählt",\n'
                         ' "optionen":["Antwort A","Antwort B"],\n'
                         ' "wege":[{"name":"","kern":"","dafuer":"","dagegen":""}]}\n\n' +
                         ("Es sind genug Fragen beantwortet. Wähle phase=\"wege\" und schlage 2 bis 3 wirklich verschiedene Wege vor."
                          if genug else
                          "Nur wenn Zweck, Rahmen und Erfolgskriterium schon klar sind, wähle phase=\"wege\". Sonst phase=\"frage\"."))
            d = llm.json_aus(await llm.chat(m, "", [{"role": "user", "content": anweisung}], json_format=True, temperatur=0.4))
            if not isinstance(d, dict):
                raise llm.ModellFehler("Keine verwertbare Antwort erhalten.")
            if d.get("phase") == "wege" and isinstance(d.get("wege"), list) and d["wege"]:
                s.update(wege=[w for w in d["wege"] if isinstance(w, dict)][:3], phase="wege", frage=None)
            elif d.get("phase") == "zerlegen" and isinstance(d.get("zerlegen"), list) and len(d["zerlegen"]) > 1:
                s.update(phase="frage", frage={"text": d.get("frage") or "Das Thema enthält mehrere Vorhaben. Welches zuerst?",
                                               "warum": d.get("warum") or "Getrennt gedacht wird jedes davon konkreter.",
                                               "optionen": [str(x) for x in d["zerlegen"]][:4]})
            else:
                s.update(phase="frage", frage={"text": d.get("frage") or "Was genau soll am Ende anders sein?",
                                               "warum": d.get("warum") or "",
                                               "optionen": [str(x) for x in (d.get("optionen") or [])][:4] if isinstance(d.get("optionen"), list) else []})
            s["runde"] += 1
        elif art == "entwurf":
            anweisung = (_bs_system() + "\n\nDas Gespräch ist abgeschlossen. Schreibe jetzt den Entwurf.\n\n"
                         f"THEMA: {s['thema']}" + (f"\nPROJEKT: {_projekt_name(s['projekt_id'])}" if s["projekt_id"] else "") +
                         f"\n\nGESPRÄCH:\n{_bs_verlauf_text(s)}" +
                         (f"\n\nGEWÄHLTER WEG: {s['weg'].get('name')} — {s['weg'].get('kern')}" if s.get("weg") else "") +
                         "\n\nSchreibe ein Dokument in Markdown mit GENAU diesen Überschriften, in dieser Reihenfolge:\n"
                         "## Worum es geht\n## Ziel und Erfolgskriterium\n## Der gewählte Weg\n"
                         "## Vorgehen in Schritten\n## Was noch offen ist\n## Erste Aufgaben\n\n"
                         "Keine Platzhalter, keine eckigen Klammern, keine Sätze wie „hier könnte “. Was nicht besprochen wurde, "
                         "gehört unter „Was noch offen ist“ — nicht erfunden. Unter „Erste Aufgaben“ stehen 3 bis 6 Aufgaben als Liste, "
                         "jede beginnt mit einem Verb.")
            text = await llm.chat(m, "", [{"role": "user", "content": anweisung}], temperatur=0.5, num_ctx=24576)
            if not text.strip():
                raise llm.ModellFehler("Das Modell hat keinen Entwurf geliefert.")
            s.update(entwurf=llm.FREMDSCHRIFT.sub("", text), phase="fertig", funde=None)
        elif art == "pruefen":
            # Bewusst ein ZWEITER Aufruf mit dem Entwurf als Gegenstand: im selben Zug
            # bekommt man eine Pruefung, die den Text verteidigt.
            d = llm.json_aus(await llm.chat(m, "", [{"role": "user", "content":
                "Prüfe den folgenden Entwurf streng gegen sich selbst. Antworte auf Deutsch und NUR mit JSON:\n"
                '{"funde":[{"art":"Platzhalter"|"Widerspruch"|"Unklar"|"Zu weit","stelle":"Überschrift oder Zitat","text":"was daran nicht trägt"}]}\n\n'
                "Suche nach: Platzhaltern und Füllsätzen, inneren Widersprüchen, Aussagen ohne Grundlage, Punkten die mehrdeutig "
                "bleiben, und einem Umfang der für einen Schritt zu groß ist. Findest du nichts, gib eine leere Liste zurück — "
                "erfinde keine Funde.\n\nENTWURF:\n" + s["entwurf"]}], json_format=True, temperatur=0.2))
            s["funde"] = [f for f in (d.get("funde") if isinstance(d, dict) else []) or [] if isinstance(f, dict)]
        s["fehler"] = None
    except Exception as f:  # noqa: BLE001 -- ein Fehlschlag soll angezeigt werden, nicht den Dienst stoeren
        s["fehler"] = str(f) or f.__class__.__name__
        if art == "entwurf":
            s["phase"] = "wege"   # die Wege bleiben waehlbar, statt in einem leeren Schritt zu haengen
    # Zwischendurch "Neu anfangen"? Dann nichts ueberschreiben.
    aktuell = db.einstellung("brainstrom") or {}
    if aktuell.get("seit") != s.get("seit"):
        return
    s.update(laeuft=False, was="")
    _bs_speichern(s)


def _bs_los(s: dict[str, Any], art: str, was: str) -> dict[str, Any]:
    if _laeuft_noch("brainstrom"):
        raise ValueError("BrainStrom rechnet gerade noch. Einen Moment.")
    s.update(laeuft=True, was=was, seit=time.time(), fehler=None, letzte_art=art, letzte_was=was)
    _bs_speichern(s)
    _im_hintergrund("brainstrom", _bs_schritt(art))
    return s


def bs_nochmal() -> dict[str, Any]:
    """Nach einem Fehlschlag denselben Schritt noch einmal -- ohne neu zu tippen."""
    s = bs_stand()
    art = s.get("letzte_art")
    if not art or not s.get("thema"):
        raise ValueError("Es gibt keinen Schritt zum Wiederholen.")
    if art == "entwurf" and s.get("weg"):
        s["phase"] = "entwurf"
    return _bs_los(s, art, s.get("letzte_was") or "Noch einmal …")


def bs_starten(thema: str, projekt_id: str | None = None, anhaenge: list[str] | None = None) -> dict[str, Any]:
    thema = (thema or "").strip()
    for did in anhaenge or []:
        d = db.holen("dateien", did)
        if d and d.get("text"):
            thema += f"\n\n[Unterlage: {d['name']}]\n{d['text'][:12000]}"
    if not thema:
        raise ValueError("Erst ein Thema nennen.")
    s = bs_leer()
    s.update(thema=thema[:20000], projekt_id=stab.projekt_finden(projekt_id))
    return _bs_los(s, "frage", "Denkt über die erste Frage nach …")


def bs_antworten(text: str) -> dict[str, Any]:
    s = bs_stand()
    if s["phase"] != "frage" or not s.get("frage"):
        raise ValueError("Gerade steht keine Frage offen.")
    if not (text or "").strip():
        raise ValueError("Eine Antwort wählen oder hineinschreiben.")
    s["verlauf"].append({"frage": s["frage"]["text"], "antwort": text.strip()[:2000]})
    return _bs_los(s, "frage", "Denkt über die nächste Frage nach …")


def bs_genug() -> dict[str, Any]:
    s = bs_stand()
    if s["phase"] not in ("frage",):
        raise ValueError("Die Wege gibt es erst, wenn das Gespräch läuft.")
    s["genug"] = True
    return _bs_los(s, "frage", "Wägt Wege ab …")


def bs_weg(nummer: int) -> dict[str, Any]:
    s = bs_stand()
    wege = s.get("wege") or []
    if s["phase"] != "wege" or not (0 <= nummer < len(wege)):
        raise ValueError("Diesen Weg gibt es nicht.")
    s.update(weg=wege[nummer], phase="entwurf")
    return _bs_los(s, "entwurf", "Schreibt den Entwurf …")


def bs_pruefen() -> dict[str, Any]:
    s = bs_stand()
    if s["phase"] != "fertig":
        raise ValueError("Es gibt noch keinen Entwurf.")
    return _bs_los(s, "pruefen", "Prüft den Entwurf gegen sich selbst …")


def bs_projekt_setzen(projekt_id: str | None) -> dict[str, Any]:
    s = bs_stand()
    s["projekt_id"] = stab.projekt_finden(projekt_id)
    _bs_speichern(s)
    return s


def bs_neu() -> dict[str, Any]:
    s = bs_leer()
    _bs_speichern(s)
    return s


def _ergebnis(titel: str, text: str, projekt_id: str | None, modell_name: str | None) -> str:
    eid = db.neue_id("r")
    db.anlegen("ergebnisse", {"id": eid, "vorgang_id": None, "projekt_id": projekt_id, "titel": titel[:120], "form": "text",
                              "inhalt": text, "rolle": "system", "modell": modell_name or "", "quellen": [], "pruefung": {},
                              "ansicht": 0, "erstellt": time.time()})
    return eid


def bs_als_ergebnis() -> dict[str, Any]:
    s = bs_stand()
    if not s.get("entwurf"):
        raise ValueError("Es gibt noch keinen Entwurf.")
    eid = _ergebnis("BrainStrom: " + s["thema"].splitlines()[0][:70], s["entwurf"], s["projekt_id"], s.get("modell"))
    s["ergebnis_id"] = eid
    _bs_speichern(s)
    return {"ok": True, "ergebnis_id": eid}


async def bs_uebernehmen() -> dict[str, Any]:
    """Der Entwurf wird ein Projekt mit Aufgaben. Aendert den Bestand -- deshalb
    nur auf Klick oder ein gesprochenes Ja, nie von selbst."""
    s = bs_stand()
    if not s.get("entwurf"):
        raise ValueError("Es gibt noch keinen Entwurf.")
    m = await modell()
    if not m:
        raise ValueError("Kein lokales Modell installiert.")
    d = llm.json_aus(await llm.chat(m, "", [{"role": "user", "content":
        "Lies den Entwurf und gib NUR JSON zurück:\n"
        '{"projekt":"kurzer Projektname","ziel":"ein Satz","aufgaben":[{"titel":"beginnt mit einem Verb","warum":"ein Satz"}]}\n\n'
        "Nimm die Aufgaben aus dem Abschnitt „Erste Aufgaben“, höchstens acht. Erfinde keine dazu.\n\nENTWURF:\n" + s["entwurf"]}],
        json_format=True, temperatur=0.2))
    if not isinstance(d, dict):
        raise ValueError("Das Modell hat keine verwertbare Liste geliefert. Bitte noch einmal.")
    pid = s.get("projekt_id") if db.holen("projekte", s.get("projekt_id") or "") else None
    if not pid:
        pid = db.neue_id("p")
        db.anlegen("projekte", {"id": pid, "name": str(d.get("projekt") or s["thema"][:60] or "Neues Vorhaben")[:80],
                                "farbe": "#6D4AE0", "status": "aktiv", "ziel": str(d.get("ziel") or "")[:300],
                                "start": time.strftime("%Y-%m-%d"), "fruehere_namen": [], "sortierung": 999,
                                "erstellt": time.time(), "geaendert": time.time(), "quelle": "du"})
        s["projekt_angelegt"] = pid
    n = 0
    for i, a in enumerate((d.get("aufgaben") or [])[:8]):
        if not isinstance(a, dict) or not str(a.get("titel") or "").strip():
            continue
        db.anlegen("aufgaben", {"id": db.neue_id("t"), "titel": str(a["titel"])[:200], "projekt_id": pid, "status": "offen",
                                "prio": 2, "faellig": "", "notiz": str(a.get("warum") or "")[:500], "quelle": "du",
                                "erstellt": time.time(), "geaendert": time.time(), "sortierung": (i + 1) * 10})
        n += 1
    s["projekt_id"] = pid
    s["ergebnis_id"] = _ergebnis("BrainStrom: " + s["thema"].splitlines()[0][:70], s["entwurf"], pid, m)
    _bs_speichern(s)
    return {"ok": True, "projekt_id": pid, "aufgaben": n}


# ================================================================ ExO
SCALE = [("S", "Staff on Demand", "Arbeit von außen statt fester Kopfzahl"),
         ("C", "Community & Crowd", "ein Kreis von Beteiligten außerhalb der Organisation"),
         ("A", "Algorithms", "Entscheidungen, die auf Daten laufen statt auf Bauchgefühl"),
         ("L", "Leveraged Assets", "geliehene statt besessene Mittel"),
         ("E", "Engagement", "Bindung durch Rückmeldung, Wettbewerb, Anerkennung")]
IDEAS = [("I", "Interfaces", "die Übergabe zwischen außen und innen"),
         ("D", "Dashboards", "wenige Kennzahlen, die alle sehen"),
         ("E", "Experimentation", "Versuche mit erlaubtem Scheitern"),
         ("A", "Autonomy", "Entscheidungen dort, wo die Arbeit liegt"),
         ("S", "Social Technologies", "der Fluss von Wissen ohne Umweg über Hierarchie")]


def exo_leer() -> dict[str, Any]:
    return {"umfang": "portfolio", "projekt_id": None, "stand": None, "laeuft": False, "seit": None,
            "fehler": None, "modell": None, "angelegt": [], "ergebnis_id": None}


def exo_stand() -> dict[str, Any]:
    s = {**exo_leer(), **(db.einstellung("exo") or {})}
    if s["laeuft"] and not _laeuft_noch("exo"):
        s.update(laeuft=False, fehler="Die Analyse wurde unterbrochen (Dienst neu gestartet). Bitte noch einmal.")
        db.einstellung_setzen("exo", s)
    return s


def _exo_anweisung(s: dict[str, Any]) -> str:
    pid = s.get("projekt_id") if s["umfang"] == "projekt" else None
    p = db.holen("projekte", pid) if pid else None
    if p:
        gegenstand = f"das Projekt „{p['name']}“"
        ts = db.alle("SELECT titel, status FROM aufgaben WHERE projekt_id=? AND archiviert=0 ORDER BY erstellt", (pid,))
        ns = db.alle("SELECT titel, kurz, text FROM notizen WHERE projekt_id=? ORDER BY erstellt DESC LIMIT 30", (pid,))
        stoff = (f"PROJEKT: {p['name']}\nZIEL: {p.get('ziel') or '— keines hinterlegt —'}\nSTATUS: {p.get('status')}\nAUFGABEN:\n" +
                 ("\n".join(f"• {t['titel']} ({t['status']})" for t in ts) or "(keine)") + "\n\nNOTIZEN:\n" +
                 ("\n".join(f"• {n['titel'] or ''}: {(n['kurz'] or n['text'] or '')[:400]}" for n in ns) or "(keine)"))
    else:
        gegenstand = "das gesamte Portfolio"
        stoff = _stand_text()
    return (f"Du bewertest {gegenstand} gegen den veröffentlichten Rahmen der Exponential Organizations (Salim Ismail u. a.). "
            "Antworte auf Deutsch.\n\nRAHMEN:\n"
            "MTP — Massive Transformative Purpose: ein Zweck, der größer ist als das Vorhaben selbst.\n"
            f"SCALE (nach außen): {', '.join(x[1] for x in SCALE)}.\n"
            f"IDEAS (nach innen): {', '.join(x[1] for x in IDEAS)}.\n"
            "ExO Sprint: ein Core-Strang verbessert das Bestehende, ein Edge-Strang baut daneben etwas Neues auf.\n\n"
            "STRENGE REGEL: Du bewertest NUR, was im Material unten wirklich steht. Was sich daraus nicht beurteilen lässt, kommt "
            "in das Feld „luecke“ — nicht in eine Bewertung. Ein erfundener Befund ist schlimmer als eine Lücke.\n\n"
            f"MATERIAL:\n{stoff}\n\n"
            "Antworte NUR mit JSON:\n"
            '{"mtp":{"vorhanden":true,"befund":"","vorschlag":"ein Satz, als MTP formuliert"},\n'
            ' "scale":[{"kuerzel":"S","name":"Staff on Demand","stand":"stark|ansatz|fehlt","befund":"","schritt":"eine konkrete nächste Handlung"}],\n'
            ' "ideas":[{"kuerzel":"I","name":"Interfaces","stand":"stark|ansatz|fehlt","befund":"","schritt":""}],\n'
            ' "sprint":{"core":["",""],"edge":["",""]},\n'
            ' "luecke":"was sich aus dem Material nicht beurteilen ließ"}\n\n'
            "scale und ideas haben GENAU fünf Einträge, in der Reihenfolge der Kürzel.")


async def _exo_lauf() -> None:
    s = exo_stand()
    seit = s.get("seit")
    try:
        m = await modell()
        if not m:
            raise llm.ModellFehler("Kein lokales Modell installiert.")
        d = llm.json_aus(await llm.chat(m, "", [{"role": "user", "content": _exo_anweisung(s)}], json_format=True,
                                        temperatur=0.3, num_ctx=24576))
        if not isinstance(d, dict):
            raise llm.ModellFehler("Keine verwertbare Antwort erhalten.")
        s.update(stand=d, modell=m, fehler=None, angelegt=[], ergebnis_id=None)
    except Exception as f:  # noqa: BLE001
        s["fehler"] = str(f)
    if (db.einstellung("exo") or {}).get("seit") != seit:
        return
    s["laeuft"] = False
    db.einstellung_setzen("exo", s)


def exo_starten(umfang: str = "portfolio", projekt_id: str | None = None) -> dict[str, Any]:
    if _laeuft_noch("exo"):
        raise ValueError("Die ExO-Analyse läuft schon.")
    pid = stab.projekt_finden(projekt_id)
    umfang = "projekt" if umfang == "projekt" and pid else "portfolio"
    s = exo_leer()
    s.update(umfang=umfang, projekt_id=pid, laeuft=True, seit=time.time())
    db.einstellung_setzen("exo", s)
    _im_hintergrund("exo", _exo_lauf())
    return s


def exo_neu() -> dict[str, Any]:
    s = exo_stand()
    if s["laeuft"]:
        raise ValueError("Die ExO-Analyse läuft noch.")
    s.update(stand=None, fehler=None, angelegt=[], ergebnis_id=None)
    db.einstellung_setzen("exo", s)
    return s


def exo_text(s: dict[str, Any]) -> str:
    st = s.get("stand") or {}
    m = st.get("mtp") or {}

    def teil(titel: str, vorgaben, werte) -> str:
        zeilen = []
        for i, v in enumerate(vorgaben):
            w = (werte or [])[i] if i < len(werte or []) and isinstance((werte or [])[i], dict) else {}
            zeilen.append(f"### {v[0]} — {w.get('name') or v[1]} ({w.get('stand') or 'fehlt'})\n{w.get('befund') or ''}" +
                          (f"\n\nNächster Schritt: {w['schritt']}" if w.get("schritt") else ""))
        return f"\n\n## {titel}\n" + "\n\n".join(zeilen)
    sp = st.get("sprint") or {}
    name = _projekt_name(s.get("projekt_id")) if s["umfang"] == "projekt" else "Portfolio"
    return (f"# ExO-Analyse — {name}\n\n## MTP\n{m.get('vorschlag') or ''}\n\n{m.get('befund') or ''}" +
            teil("SCALE — nach außen", SCALE, st.get("scale")) + teil("IDEAS — nach innen", IDEAS, st.get("ideas")) +
            "\n\n## ExO Sprint\n### Core\n" + "\n".join(f"- {x}" for x in sp.get("core") or []) +
            "\n\n### Edge\n" + "\n".join(f"- {x}" for x in sp.get("edge") or []) +
            (f"\n\n## Was sich nicht beurteilen ließ\n{st['luecke']}" if st.get("luecke") else "") +
            f"\n\n---\nBewertet gegen den veröffentlichten ExO-Rahmen, gerechnet auf {s.get('modell') or 'einem lokalen Modell'} auf dem eigenen Server.")


def exo_als_ergebnis() -> dict[str, Any]:
    s = exo_stand()
    if not s.get("stand"):
        raise ValueError("Es gibt noch keine Analyse.")
    name = _projekt_name(s.get("projekt_id")) if s["umfang"] == "projekt" else "Portfolio"
    eid = _ergebnis(f"ExO-Analyse — {name}", exo_text(s), s.get("projekt_id") if s["umfang"] == "projekt" else None, s.get("modell"))
    s["ergebnis_id"] = eid
    db.einstellung_setzen("exo", s)
    return {"ok": True, "ergebnis_id": eid}


def exo_aufgabe(text: str) -> dict[str, Any]:
    """Ein naechster Schritt aus der Analyse wird eine Aufgabe -- auf Klick."""
    s = exo_stand()
    text = (text or "").strip()
    if not text:
        raise ValueError("Leerer Schritt.")
    tid = db.neue_id("t")
    db.anlegen("aufgaben", {"id": tid, "titel": text[:200], "projekt_id": s.get("projekt_id") if s["umfang"] == "projekt" else None,
                            "status": "offen", "prio": 2, "faellig": "", "notiz": "Aus der ExO-Analyse übernommen.", "quelle": "du",
                            "erstellt": time.time(), "geaendert": time.time()})
    s["angelegt"] = list(dict.fromkeys((s.get("angelegt") or []) + [text]))
    db.einstellung_setzen("exo", s)
    return {"ok": True, "aufgabe_id": tid}


# ================================================================ Fuer Talk
def kontext_text(art: str) -> str:
    if art == "brainstrom":
        s = bs_stand()
        if s["phase"] == "start":
            return "VEIKO IST IN BRAINSTROM (eine Idee Frage für Frage zuspitzen). Es läuft noch kein Gespräch; das Thema fehlt."
        t = [f"VEIKO IST IN BRAINSTROM. THEMA: {s['thema'][:1500]}",
             f"PROJEKT: {_projekt_name(s['projekt_id']) or '— keines —'}", "BISHER:\n" + _bs_verlauf_text(s)]
        if s["laeuft"]:
            t.append("GERADE: " + (s.get("was") or "rechnet"))
        elif s["phase"] == "frage" and s.get("frage"):
            f = s["frage"]
            t.append(f"AKTUELLE FRAGE (Nr. {len(s['verlauf']) + 1}): {f['text']}" +
                     (("\nANTWORTMÖGLICHKEITEN: " + " | ".join(f"{i + 1}) {o}" for i, o in enumerate(f.get('optionen') or []))) if f.get("optionen") else ""))
        elif s["phase"] == "wege" and s.get("wege"):
            t.append("WEGE ZUR WAHL:\n" + "\n".join(f"{i + 1}) {w.get('name')}: {w.get('kern')} (dafür: {w.get('dafuer')}; dagegen: {w.get('dagegen')})"
                                                    for i, w in enumerate(s["wege"])))
        elif s["phase"] == "fertig":
            t.append("ENTWURF LIEGT VOR:\n" + s["entwurf"][:5000])
        if s.get("fehler"):
            t.append("LETZTER FEHLER: " + s["fehler"])
        return "\n".join(t)
    if art == "exo":
        s = exo_stand()
        name = _projekt_name(s.get("projekt_id")) if s["umfang"] == "projekt" else "das ganze Portfolio"
        if s["laeuft"]:
            return f"VEIKO IST IN DER ExO-ANALYSE. Gerade wird {name} bewertet."
        if not s.get("stand"):
            return "VEIKO IST IN DER ExO-ANALYSE (Bewertung gegen MTP, SCALE, IDEAS). Noch keine Analyse."
        return f"VEIKO SIEHT DIE ExO-ANALYSE FÜR {name}:\n" + exo_text(s)[:6000]
    return ""


def kurz_fuer_talk() -> str:
    """Was BrainStrom gerade fragt -- zum Vorlesen nach einer gesprochenen Antwort."""
    s = bs_stand()
    if s.get("fehler"):
        return "BrainStrom kam nicht weiter: " + s["fehler"]
    if s["laeuft"]:
        return "BrainStrom rechnet noch, die nächste Frage erscheint gleich auf dem Bildschirm."
    if s["phase"] == "frage" and s.get("frage"):
        f = s["frage"]
        opt = f.get("optionen") or []
        return (f"Frage {len(s['verlauf']) + 1}: {f['text']}" +
                (" Zur Auswahl: " + "; ".join(f"{i + 1}. {o}" for i, o in enumerate(opt)) + "." if opt else ""))
    if s["phase"] == "wege" and s.get("wege"):
        return "Ich sehe diese Wege: " + "; ".join(f"{i + 1}. {w.get('name')}" for i, w in enumerate(s["wege"])) + ". Welchen nehmen wir?"
    if s["phase"] == "fertig":
        return "Der Entwurf steht auf dem Bildschirm. Soll ich ihn prüfen lassen oder als Projekt mit Aufgaben übernehmen?"
    return ""
