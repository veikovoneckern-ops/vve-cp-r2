"""
VERSIONSVERLAUF -- was sich am Cockpit wann geaendert hat (Settings, 19.10.2026).

Veiko: "bau mir bei Settings noch eine Art Versionsverlauf fuer das Cockpit als
Releasemanagement, also einen Versionsverlauf fuer die Funktionalitaeten des
Cockpits, die wir ja staendig weiterentwickeln."

Die Quelle ist die Git-Geschichte dieses Repos -- keine zweite, von Hand gepflegte
Liste. Jede Aenderung, die auf den Server kommt, kommt als Commit; eine eigene
Liste daneben waere nach dem ersten vergessenen Eintrag falsch, und niemand
merkte es. Ein Tag mit Aenderungen ist eine Version (2.1 = erster Tag der neuen
Fassung, 03.09.2026). Die Nummern bleiben stabil, solange die Geschichte nicht
umgeschrieben wird -- das tut hier niemand.

Was dabei gerechnet und nicht gemeldet ist, steht so da:
  * Bereiche (Talk, Team, Stack …) kommen aus den geaenderten Dateien (BEREICHE).
  * "Laeuft" ist der Commit, mit dem der Dienst GESTARTET wurde (beim Import
    gemerkt). Weicht der Stand im Repo davon ab, ist etwas eingespielt, aber noch
    nicht neu gestartet -- auch das steht da.
"""
from __future__ import annotations

import re
import subprocess
import time
from typing import Any

from .konfig import WURZEL

# Datei -> Bereich. Erster Treffer gewinnt; was nirgends passt, heisst "Sonstiges".
BEREICHE: list[tuple[str, str]] = [
    (r"talk\.js|gespraech\.py|stimme\.(js|py)|composer\.js", "Talk & Sprache"),
    (r"neo\.(js|py)", "Neo"),
    (r"stab\.py|inbox\.js|importer\.py|postfach\.py|quellen\.py", "Stab & Inbox"),
    (r"team\.js|teamchat\.(js|py)|modelle\.js|revision\.py|modellkatalog\.py|ruf\.py|team_rollen", "Team & Modelle"),
    (r"projects\.js|aufgabe\.js|briefing\.js", "Projekte & Aufgaben"),
    (r"dossier\.py|langlauf\.(js|py)", "Recherche & LongRuns"),
    (r"folien|medien\.py|video|podcast|bild_vorlagen|ergebnis\.js|dokumente\.py", "Ergebnisse & Medien"),
    (r"board\.(js|py)|board_profile|verfahren\.(js|py)", "Board, BrainStrom & ExO"),
    (r"usage|explorer|datei\.js|anhang\.py", "Usage & Explorer"),
    (r"webspace", "Website"),
    (r"system|server\.js|watchdog|sicherung|kopf\.js|empfehlungen\.js|aktionen\.(js|py)", "Stack & Betrieb"),
    (r"einstellungen\.js|anmeldung|passwort|versionen", "Settings"),
    (r"\.css$|ui\.js|app\.js|leiste\.js|index\.html", "Oberfläche"),
    (r"server\.py|api\.py|db\.py|llm\.py|konfig\.py|requirements|systemd/|\.gitignore", "Kern (Server, Daten, Modelle)"),
    (r"CLAUDE\.md|README|STATUS|KONZEPT|\.md$", "Dokumentation"),
]
_BEREICH_RE = [(re.compile(m, re.I), n) for m, n in BEREICHE]
_SCHLUSS = re.compile(r"^(Co-Authored-By|Signed-off-by):.*$", re.M | re.I)


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=str(WURZEL), capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


GESTARTET = _git("rev-parse", "HEAD").strip() or None
GESTARTET_UM = time.time()
_cache: dict[str, Any] = {"kopf": None, "daten": None}


def _bereiche(dateien: list[str]) -> list[str]:
    raus: list[str] = []
    for d in dateien:
        name = next((n for m, n in _BEREICH_RE if m.search(d)), "Sonstiges")
        if name not in raus:
            raus.append(name)
    # Reine Doku zaehlt nur, wenn sonst nichts geaendert wurde.
    if len(raus) > 1 and "Dokumentation" in raus:
        raus.remove("Dokumentation")
    return raus


def _punkte(rumpf: str) -> list[str]:
    """Commit-Text -> Punkte. Mit Aufzaehlung: jeder "- …" ein Punkt, umbrochene Zeilen
    gehoeren zum vorigen. Ohne: jeder Absatz ein Punkt (Git bricht bei 72 Zeichen um,
    zeilenweise waeren das halbe Saetze)."""
    zeilen = _SCHLUSS.sub("", rumpf or "").strip().splitlines()
    ist_punkt = re.compile(r"^\s*[-*]\s+")
    raus: list[str] = []
    if any(ist_punkt.match(z) for z in zeilen):
        for z in zeilen:
            if not z.strip():
                continue
            if ist_punkt.match(z) or not raus:
                raus.append(ist_punkt.sub("", z).strip())
            else:
                raus[-1] += " " + z.strip()
        return raus
    absatz: list[str] = []
    for z in zeilen + [""]:
        if z.strip():
            absatz.append(z.strip())
        elif absatz:
            raus.append(" ".join(absatz))
            absatz = []
    return raus


def _commits() -> list[dict[str, Any]]:
    roh = _git("log", "--date=unix", "--name-only", "--format=\x1e%H\x1f%ad\x1f%s\x1f%b\x1f")
    raus = []
    for block in roh.split("\x1e"):
        if not block.strip():
            continue
        teile = block.split("\x1f")
        if len(teile) < 5:
            continue
        sha, zeit, betreff, rumpf, dateien = teile[0].strip(), teile[1], teile[2].strip(), teile[3], teile[4]
        dateiliste = [z.strip() for z in dateien.splitlines() if z.strip()]
        raus.append({"sha": sha, "kurz": sha[:7], "zeit": float(zeit or 0), "titel": betreff, "punkte": _punkte(rumpf),
                     "dateien": len(dateiliste), "bereiche": _bereiche(dateiliste)})
    return raus


def verlauf() -> dict[str, Any]:
    kopf = _git("rev-parse", "HEAD").strip() or None
    if _cache["kopf"] != kopf or _cache["daten"] is None:
        commits = _commits()
        tage: dict[str, list[dict[str, Any]]] = {}
        for c in commits:
            tage.setdefault(time.strftime("%Y-%m-%d", time.localtime(c["zeit"])), []).append(c)
        reihe = sorted(tage)            # aelteste zuerst -> Nummer
        versionen = []
        for i, tag in enumerate(reihe, start=1):
            liste = tage[tag]
            bereiche: dict[str, int] = {}
            for c in liste:
                for b in c["bereiche"]:
                    bereiche[b] = bereiche.get(b, 0) + 1
            versionen.append({"version": f"2.{i}", "tag": tag, "aenderungen": liste,
                              "bereiche": sorted(bereiche, key=lambda b: -bereiche[b]),
                              "von": min(c["zeit"] for c in liste), "bis": max(c["zeit"] for c in liste)})
        versionen.reverse()             # neueste zuerst
        _cache.update(kopf=kopf, daten=versionen)
    versionen = _cache["daten"] or []
    laeuft = next((v for v in versionen if any(c["sha"] == GESTARTET for c in v["aenderungen"])), None)
    return {"versionen": versionen,
            "laeuft": {"sha": GESTARTET, "kurz": (GESTARTET or "")[:7] or None, "version": laeuft["version"] if laeuft else None,
                       "seit": GESTARTET_UM},
            "im_repo": {"sha": kopf, "kurz": (kopf or "")[:7] or None},
            "neustart_offen": bool(kopf and GESTARTET and kopf != GESTARTET),
            "bereiche": [n for _m, n in BEREICHE] + ["Sonstiges"],
            "quelle_fehlt": not versionen}


def kontext_text(n: int = 4) -> str:
    """Fuer Talk: die juengsten Versionen in Kurzform ("Was ist neu im Cockpit?")."""
    d = verlauf()
    if not d["versionen"]:
        return "VERSIONSVERLAUF: nicht abrufbar (keine Git-Geschichte gefunden)."
    zeilen = [f"VERSIONSVERLAUF DES COCKPITS (läuft: Version {d['laeuft']['version'] or '?'}"
              + (", eine neuere ist eingespielt, aber noch nicht neu gestartet" if d["neustart_offen"] else "") + "):"]
    heute = time.strftime("%Y-%m-%d")
    gestern = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    for v in d["versionen"][:n]:
        wann = {heute: " (HEUTE)", gestern: " (gestern)"}.get(v["tag"], "")
        zeilen.append(f"Version {v['version']} vom {time.strftime('%d.%m.%Y', time.strptime(v['tag'], '%Y-%m-%d'))}{wann}, "
                      f"{len(v['aenderungen'])} Änderungen:")
        zeilen += [f"- {c['titel']}" for c in v["aenderungen"][:10]]
    return "\n".join(zeilen)
