"""
NEO KENNT DEN AKTUELLEN STAND (22.10.2026).

Veiko: "Sorge dafuer, dass Neo immer den letzten Stand der Aenderungen am Cockpit wirklich sehr gut kennt
und nicht etwas Falsches macht. Er soll so gut werden wie du, Claude Code."

Was Claude Code hat und Neo bisher nicht hatte:
  1. DIE GANZE DOKU. CLAUDE.md (156 KB) haelt fuer jede Regel fest, WARUM es so ist und woran man frueher
     gescheitert ist. Sie passt nicht in Neos Fenster -- also bekommt er das Inhaltsverzeichnis aller
     Regeln (Ueberschriften, ~7 KB) und holt sich den vollstaendigen Abschnitt mit `projektwissen`.
  2. DEN VERLAUF. Die letzten Commits mit ihren Dateien -- was sich zuletzt wo geaendert hat.
  3. DIE LANDKARTE. Jedes Modul mit seiner ersten Doku-Zeile, AUTOMATISCH aus dem Code -- ein von Hand
     gepflegter Text (NEO-KONTEXT.md) war nach drei Wochen veraltet (kannte weder Mail noch Daily Tasks).
  4. NACHSEHEN VOR DEM AENDERN. Eine Datei, die Neo aendern will, muss er in diesem Auftrag gelesen haben.
  5. PRUEFEN VOR DEM BEHAUPTEN. Bevor Dario pruefen darf, laesst das Cockpit Neos vorgemerkte Fassung in
     einer Wegwerf-Kopie laufen (Syntax UND Import aller Module) -- ein Fehler geht an Neo zurueck,
     nicht an Dario und nie ins laufende Cockpit.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from .konfig import WURZEL

DOKU = WURZEL / "CLAUDE.md"


def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=WURZEL, capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def verlauf_text(anzahl: int = 25) -> str:
    roh = _git("log", f"-{anzahl}", "--date=format:%d.%m. %H:%M", "--pretty=format:@@%h %ad %s", "--name-only")
    if not roh:
        return "(Verlauf nicht lesbar)"
    zeilen, dateien = [], []
    for z in roh.splitlines() + ["@@"]:
        if z.startswith("@@"):
            if zeilen and dateien:
                zeilen[-1] += "  [" + ", ".join(dateien[:8]) + (" …" if len(dateien) > 8 else "") + "]"
            dateien = []
            if z[2:].strip():
                zeilen.append("- " + z[2:].strip())
        elif z.strip():
            dateien.append(z.strip())
    return "\n".join(zeilen)


def _erste_zeile_py(p: Path) -> str:
    try:
        doc = ast.get_docstring(ast.parse(p.read_text(encoding="utf-8"))) or ""
    except (SyntaxError, OSError, UnicodeDecodeError):
        return ""
    for z in doc.splitlines():
        if z.strip():
            return z.strip()
    return ""


def _erste_zeile_js(p: Path) -> str:
    try:
        for z in p.read_text(encoding="utf-8").splitlines()[:6]:
            if z.startswith("//") and len(z.strip("/ ")) > 8:
                return z.strip("/ ").strip()
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def landkarte() -> str:
    teile = ["Backend (cockpit/):"]
    for p in sorted((WURZEL / "cockpit").glob("*.py")):
        if p.name != "__init__.py":
            teile.append(f"- {p.name}: {_erste_zeile_py(p)[:150]}")
    teile.append("Oberfläche (frontend/js/):")
    for p in sorted((WURZEL / "frontend" / "js").glob("*.js")):
        teile.append(f"- {p.name}: {_erste_zeile_js(p)[:150]}")
    return "\n".join(teile)


def _doku() -> str:
    try:
        return DOKU.read_text(encoding="utf-8")
    except OSError:
        return ""


def regeln_index() -> str:
    """Die Ueberschriften aller Regeln aus CLAUDE.md -- vollstaendig ueber `projektwissen`."""
    titel = []
    for z in _doku().splitlines():
        m = re.match(r"^- \*\*(.+?)\*\*", z)
        if m:
            titel.append("- " + m.group(1)[:170])
    return "\n".join(titel)


def grundlagen() -> str:
    """Der Anfang von CLAUDE.md bis zu den festen Regeln (Was das ist, Bauregeln)."""
    t = _doku()
    i = t.find("## Feste Regeln")
    return t[:i].strip() if i > 0 else t[:4000]


def projektwissen(thema: str, grenze: int = 14000) -> str:
    """Alle Regel-Abschnitte aus CLAUDE.md, in denen das Thema vorkommt -- vollstaendig, mit Unterpunkten."""
    t = _doku()
    if not t:
        return "CLAUDE.md nicht lesbar."
    woerter = [w.lower() for w in re.findall(r"[\wäöüß.\-]{3,}", thema)]
    if not woerter:
        return "Gib ein Stichwort an (Datei, Funktion, Thema)."
    bloecke, akt = [], []
    for z in t.splitlines():
        if re.match(r"^(- \*\*|#)", z) and akt:
            bloecke.append("\n".join(akt))
            akt = []
        akt.append(z)
    if akt:
        bloecke.append("\n".join(akt))
    def punkte(b: str) -> int:
        k = b.lower()
        return sum(k.count(w) for w in woerter) + (3 if all(w in k for w in woerter) else 0)
    treffer = sorted(((punkte(b), i, b) for i, b in enumerate(bloecke) if punkte(b)), key=lambda x: (-x[0], x[1]))
    if not treffer:
        return f"Zu „{thema}“ steht nichts in CLAUDE.md. Sieh im Code nach (suche) und im Verlauf (git log -p)."
    raus, laenge = [], 0
    for _, _, b in treffer:
        if laenge + len(b) > grenze:
            break
        raus.append(b)
        laenge += len(b)
    rest = len(treffer) - len(raus)
    return "\n\n".join(raus) + (f"\n\n[{rest} weitere Abschnitte -- genaueres Stichwort angeben]" if rest else "")


def stand_text() -> str:
    status = _git("status", "--short")
    return ("\n\n## STAND DES COCKPITS (bei jedem Auftrag frisch aus dem Repo)\n"
            "### Die Grundlagen (Anfang von CLAUDE.md)\n" + grundlagen()[:6000] +
            "\n\n### Alle Regeln in CLAUDE.md (nur die Überschriften -- den vollständigen Abschnitt mit dem Warum holst du "
            "dir mit projektwissen(\"Stichwort\"), BEVOR du etwas in diesem Bereich änderst)\n" + regeln_index() +
            "\n\n### Die letzten Änderungen (git log, neueste zuerst, mit Dateien)\n" + verlauf_text() +
            ("\n\n### ACHTUNG: nicht committete Änderungen im Repo\n" + status if status else "") +
            "\n\n### Landkarte (jedes Modul mit seiner ersten Doku-Zeile)\n" + landkarte())


# ---------------------------------------------------------------- Selbsttest vor Darios Pruefung
def selbsttest(entwurf: dict[str, Any]) -> str | None:
    """Die vorgemerkte Fassung in einer Wegwerf-Kopie: Syntax und Import aller Backend-Module, node --check
    fuer geaenderte JavaScript-Dateien. Rueckgabe: Fehlertext oder None. Das laufende Cockpit bleibt unberuehrt."""
    dateien = {Path(p): d for p, d in (entwurf.get("dateien") or {}).items()}
    im_repo = {p: d for p, d in dateien.items() if str(p).startswith(str(WURZEL) + "/")}
    if not im_repo:
        return None
    tmp = Path(tempfile.mkdtemp(prefix="neo-selbsttest-"))
    try:
        for teil in ("cockpit", "frontend/js", "server.py"):
            q = WURZEL / teil
            if q.is_dir():
                shutil.copytree(q, tmp / teil, ignore=shutil.ignore_patterns("__pycache__"))
            elif q.is_file():
                (tmp / teil).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(q, tmp / teil)
        for p, d in im_repo.items():
            ziel = tmp / p.relative_to(WURZEL)
            ziel.parent.mkdir(parents=True, exist_ok=True)
            if d.get("kopie_von"):
                shutil.copyfile(d["kopie_von"], ziel)
            elif d.get("neu") is not None:
                ziel.write_text(d["neu"], encoding="utf-8")
        fehler = []
        for p in im_repo:
            z = tmp / p.relative_to(WURZEL)
            if z.suffix == ".py":
                try:
                    compile(z.read_text(encoding="utf-8"), str(p), "exec")
                except SyntaxError as f:
                    fehler.append(f"{p.relative_to(WURZEL)}, Zeile {f.lineno}: {f.msg}")
                    continue
                # Undefinierte Namen (23.10.2026): Neo benutzte "_ABLEHNUNG", ohne es zu definieren -- Syntax und
                # Import gehen durch, der Fehler kommt erst beim Aufruf. pyflakes findet das, ohne etwas auszufuehren.
                # Nur "undefined name": unbenutzte Importe u. Ae. sind kein Grund, eine Aenderung zurueckzuschicken.
                if importlib.util.find_spec("pyflakes"):
                    r = subprocess.run([sys.executable, "-m", "pyflakes", str(z)], capture_output=True, text=True, timeout=60)
                    for zeile in (r.stdout or "").splitlines():
                        if "undefined name" in zeile:
                            fehler.append(f"{p.relative_to(WURZEL)}{zeile.split(str(z), 1)[-1]}")
            elif z.suffix in (".js", ".mjs") and shutil.which("node"):
                kopie = z.with_suffix(".pruef.mjs")
                shutil.copyfile(z, kopie)
                r = subprocess.run(["node", "--check", str(kopie)], capture_output=True, text=True, timeout=30)
                if r.returncode:
                    fehler.append(f"{p.relative_to(WURZEL)}: " + " ".join((r.stderr or "").strip().splitlines()[:3]))
        if not fehler and any(p.suffix == ".py" for p in im_repo):
            # Import ALLER Module -- faengt fehlende Namen, falsche Importe, Kreisbezuege (das, woran ein
            # Neustart sonst scheitert). Eigene, leere Datenablage, damit nichts Echtes beruehrt wird.
            module = [f"cockpit.{p.stem}" for p in sorted((tmp / "cockpit").glob("*.py")) if p.name != "__init__.py"]
            umgebung = {**os.environ, "VVEC_NEU_DATEN": str(tmp / "daten"), "PYTHONDONTWRITEBYTECODE": "1"}
            r = subprocess.run([sys.executable, "-c", "import importlib,sys\nfor m in sys.argv[1:]: importlib.import_module(m)\nimport server",
                                *module], cwd=tmp, capture_output=True, text=True, timeout=90, env=umgebung)
            if r.returncode:
                zeilen = (r.stderr or r.stdout).strip().splitlines()
                fehler.append("Import scheitert:\n" + "\n".join(zeilen[-12:]))
        return "\n".join(fehler) or None
    except (OSError, subprocess.SubprocessError) as f:
        return f"Selbsttest nicht ausführbar: {f}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
