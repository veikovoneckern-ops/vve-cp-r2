"""
NEO ÄNDERT NICHTS OHNE DARIOS FREIGABE (22.10.2026).

Veiko: "Stell bitte sicher, dass Neo keine Veränderungen vornimmt, bevor Dario das nicht überprüft
und freigegeben hat. Nicht, dass er irgendwelche Fehler macht und im Cockpit etwas zerstört."

Anlass ist belegt: am 21.10.2026 setzte Neo in cockpit/konfig.py die Adresse des alten Backends
auf leer und startete den Dienst neu -- seitdem liefen Postausgang, die Externen und das
Ollama-Update ins Leere, und niemand sah es, weil die Aenderung nie committet wurde.

So geht es jetzt:
  - LESEN und NACHSEHEN (datei_lesen, suche, rein lesende Befehle) wirkt sofort -- Neo muss den
    Code ansehen koennen, um gute Aenderungen vorzuschlagen.
  - In seine ARBEITSABLAGEN (Vorschau-Seiten, Dokumente zum Herunterladen, /tmp) schreibt er frei --
    das veraendert das Cockpit nicht, und eine Vorschau, die erst nach einer Cloud-Pruefung
    erscheint, waere keine Vorschau.
  - ALLES ANDERE wird VORGEMERKT: Dateien im Repo, Einstellungen, Kopien ausserhalb der Ablagen,
    jeder Befehl, der etwas veraendern koennte. Neo arbeitet innerhalb des Auftrags auf seinem
    Entwurf weiter (datei_lesen zeigt ihm die vorgemerkte Fassung).
  - Am Ende prueft DARIO den vollstaendigen Unterschied (alt -> neu) und die Befehle. Nur bei
    "freigegeben" spielt das Cockpit ein: Sicherung der alten Fassung, Syntaxpruefung (Python,
    JavaScript, JSON) -- scheitert sie, wird alles zurueckgerollt --, dann die Befehle, dann ein
    Commit mit Darios Begruendung und der Push nach GitHub. Ein Neustart des Cockpits laeuft
    zuletzt und verzoegert, damit die Antwort vorher gespeichert ist.
  - Ist Dario nicht erreichbar, wird NICHTS eingespielt. Es gibt keinen Weg daran vorbei --
    so hat Veiko es verlangt.
"""
from __future__ import annotations

import asyncio
import difflib
import json
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from . import llm
from .konfig import DATEN, VORSCHAU_DIR, WURZEL

EXPORT_DIR = DATEN / "exports"
FREI = (VORSCHAU_DIR, EXPORT_DIR, Path("/tmp"))
SICHERUNG = DATEN / "neo-sicherung"
NEUSTART = re.compile(r"\bsystemctl\s+(--user\s+)?(restart|reload|stop|start)\s+vve-cp-r2\b")
MAX_DIFF = 60000


def frei(p: Path) -> bool:
    s = str(p.resolve())
    return any(s == str(f.resolve()) or s.startswith(str(f.resolve()).rstrip("/") + "/") for f in FREI)


# ---------------------------------------------------------------- rein lesende Befehle
_LESEND = {"ls", "ll", "cat", "head", "tail", "less", "more", "wc", "du", "df", "free", "uptime", "ps", "pgrep", "nvidia-smi",
           "journalctl", "stat", "file", "which", "whereis", "type", "echo", "printf", "pwd", "date", "hostname", "uname", "id",
           "whoami", "lsblk", "lscpu", "ip", "ss", "sort", "uniq", "cut", "tr", "jq", "grep", "egrep", "fgrep", "rg", "tree",
           "diff", "cmp", "md5sum", "sha256sum", "realpath", "readlink", "basename", "dirname", "test", "true", "false", "sensors",
           "xxd", "nl", "column", "cd", "column", "seq", "awk", "sed", "find", "top", "git", "systemctl", "docker", "ollama",
           "curl", "pip", "pip3", "node", "python", "python3", "sqlite3", "tar", "unzip", "zipinfo", "timedatectl", "lsof", "env"}
_UNTER = {
    "git": {"status", "log", "diff", "show", "branch", "remote", "rev-parse", "ls-files", "blame", "describe", "grep", "shortlog"},
    "systemctl": {"status", "show", "is-active", "is-enabled", "is-failed", "list-units", "list-timers", "cat", "list-unit-files"},
    "docker": {"ps", "logs", "images", "inspect", "stats", "version", "info"},
    "ollama": {"list", "ps", "show", "--version", "-v"},
    "pip": {"list", "show", "freeze", "--version"}, "pip3": {"list", "show", "freeze", "--version"},
    "tar": {"-tf", "-tzf", "-tvf", "-tvzf", "--list"}, "unzip": {"-l", "-v", "-t"},
}


def _segmente(befehl: str) -> list[str]:
    return [s.strip() for s in re.split(r"&&|\|\||;|\|", befehl) if s.strip()]


def nur_lesend(befehl: str) -> bool:
    """True, wenn der Befehl erkennbar nichts veraendert. Im Zweifel False -- dann prueft Dario."""
    b = befehl.strip()
    if not b or "$(" in b or "`" in b or re.search(r"\btee\b|\bxargs\b|\bsudo\b|\beval\b|\bexec\b", b):
        return False
    # Umleitungen in Dateien veraendern etwas; nur Fehlerausgabe und /dev/null sind erlaubt.
    ohne = re.sub(r"\d?>&\d|\d?>\s*/dev/null", "", b)
    if ">" in ohne:
        return False
    for seg in _segmente(b):
        try:
            t = shlex.split(seg)
        except ValueError:
            return False
        while t and re.match(r"^\w+=", t[0]):      # VAR=wert befehl
            t = t[1:]
        if not t:
            continue
        cmd = Path(t[0]).name
        rest = t[1:]
        if cmd not in _LESEND:
            return False
        if cmd == "env" and any(not re.match(r"^-|^\w+=", x) for x in rest):
            return False                             # env fuehrt sonst einen anderen Befehl aus
        if cmd in _UNTER:
            toks = list(rest)
            if cmd == "git":
                while toks and toks[0].startswith("-"):
                    toks = toks[2:] if toks[0] in ("-C", "-c") else toks[1:]
                sub = toks[0] if toks else ""
            elif cmd in ("tar", "unzip"):
                sub = toks[0] if toks else ""
            else:
                sub = next((x for x in toks if not x.startswith("-")), toks[0] if toks else "")
            if sub not in _UNTER[cmd]:
                return False
        if cmd == "curl" and any(x in ("-X", "--request", "-d", "--data", "--data-raw", "--data-binary", "-F", "--form", "-T",
                                       "--upload-file", "-o", "-O", "--output", "--remote-name") or x.startswith(("-d", "--data")) for x in rest):
            return False
        if cmd == "find" and any(x in ("-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls") for x in rest):
            return False
        if cmd == "sed":
            # Nur zum Lesen von Zeilenbereichen (sed -n '1,40p' datei) -- sed kann sonst schreiben
            # (-i, oder der Befehl w, auch ohne Leerzeichen: "w/tmp/x").
            skripte = [x for x in rest if not x.startswith("-")]
            if "-n" not in rest or not skripte or not re.fullmatch(r"(\d+|\$)(,(\d+|\$))?p", skripte[0]):
                return False
        # Befehle, die harmlos aussehen und doch schreiben oder loeschen koennen:
        if cmd == "git" and (re.search(r"\s(-d|-D|-m|-M|--delete|--move|--force|-f|--output\S*|--set-upstream\S*)\b", seg)
                             or re.search(r"\bremote\s+(add|remove|rm|rename|set-url|set-head|prune)\b", seg)):
            return False
        if cmd == "journalctl" and re.search(r"--(vacuum|rotate|flush|relinquish|sync|setup-keys)", seg):
            return False
        if cmd == "sort" and any(x in ("-o", "--output") or x.startswith(("-o", "--output=")) for x in rest):
            return False
        if cmd == "uniq" and len([x for x in rest if not x.startswith("-")]) > 1:
            return False
        if cmd == "ip" and re.search(r"\b(set|add|del|delete|flush|change|replace|append)\b", seg):
            return False
        if cmd == "curl" and any(x in ("-K", "--config") for x in rest):
            return False
        if cmd == "awk" and "system(" in seg:
            return False
        if cmd in ("python", "python3") and not (rest[:2] == ["-m", "json.tool"] or rest[:1] in (["-V"], ["--version"])):
            return False
        if cmd == "node" and not (rest[:1] in (["--check"], ["-v"], ["--version"])):
            return False
        if cmd == "sqlite3" and ("-readonly" not in rest or re.search(r"\b(insert|update|delete|drop|create|alter|replace|attach|vacuum)\b", seg, re.I)):
            return False
        if cmd == "top" and "-b" not in rest:
            return False
    return True


def frei_schreibend(befehl: str) -> bool:
    """mkdir/cp/mv/touch/rm, deren Ziele ALLE in den Arbeitsablagen liegen (Vorschau-Ordner anlegen und befuellen)."""
    if "$(" in befehl or "`" in befehl or ">" in re.sub(r"\d?>&\d|\d?>\s*/dev/null", "", befehl):
        return False                                 # versteckte Befehle und Umleitungen prueft Dario
    for seg in _segmente(befehl):
        try:
            t = shlex.split(seg)
        except ValueError:
            return False
        if not t or Path(t[0]).name not in ("mkdir", "cp", "mv", "touch", "rm", "cd", "ls"):
            return False
        if Path(t[0]).name in ("cd", "ls"):
            continue
        pfade = [x for x in t[1:] if not x.startswith("-")]
        if not pfade:
            return False
        ziele = pfade if Path(t[0]).name in ("mkdir", "touch", "rm") else pfade[-1:]
        if not all(frei(Path(x).expanduser() if Path(x).expanduser().is_absolute() else WURZEL / x) for x in ziele):
            return False
        if Path(t[0]).name == "mv" and not all(frei(Path(x).expanduser() if Path(x).expanduser().is_absolute() else WURZEL / x) for x in pfade):
            return False
    return True


# ---------------------------------------------------------------- vormerken
def entwurf(lauf: dict[str, Any]) -> dict[str, Any]:
    return lauf.setdefault("entwurf", {"dateien": {}, "befehle": []})


def gelesen(lauf: dict[str, Any], pfad: Path) -> str | None:
    """Die vorgemerkte Fassung, falls Neo die Datei in diesem Auftrag schon geaendert hat."""
    d = entwurf(lauf)["dateien"].get(str(pfad))
    return d.get("neu") if d and d.get("neu") is not None else None


def vormerken_text(lauf: dict[str, Any], pfad: Path, neu: str, begruendung: str) -> None:
    d = entwurf(lauf)["dateien"]
    if str(pfad) not in d:
        try:
            alt = pfad.read_text(encoding="utf-8") if pfad.is_file() else None
        except (OSError, UnicodeDecodeError):
            alt = None
        d[str(pfad)] = {"alt": alt, "neu": neu, "begruendung": []}
    else:
        d[str(pfad)]["neu"] = neu
    if begruendung:
        d[str(pfad)]["begruendung"].append(begruendung)


def vormerken_kopie(lauf: dict[str, Any], von: Path, nach: Path) -> None:
    entwurf(lauf)["dateien"][str(nach)] = {"kopie_von": str(von), "alt": None, "neu": None, "begruendung": ["Kopie"]}


def vormerken_befehl(lauf: dict[str, Any], befehl: str, cwd: str) -> None:
    entwurf(lauf)["befehle"].append({"befehl": befehl, "cwd": cwd})


def leer(lauf: dict[str, Any]) -> bool:
    e = lauf.get("entwurf") or {}
    return not e.get("dateien") and not e.get("befehle")


# ---------------------------------------------------------------- Darios Pruefung
def _unterschied(lauf: dict[str, Any]) -> str:
    teile = []
    for pfad, d in entwurf(lauf)["dateien"].items():
        grund = "; ".join(dict.fromkeys(d.get("begruendung") or []))
        if d.get("kopie_von"):
            groesse = Path(d["kopie_von"]).stat().st_size if Path(d["kopie_von"]).exists() else 0
            teile.append(f"### KOPIE: {d['kopie_von']} -> {pfad} ({groesse // 1024 + 1} KB)")
            continue
        alt = d.get("alt")
        diff = "".join(difflib.unified_diff((alt or "").splitlines(keepends=True), (d["neu"] or "").splitlines(keepends=True),
                                            fromfile=pfad + (" (neu angelegt)" if alt is None else ""), tofile=pfad, n=4))
        if len(diff) > 20000:
            diff = diff[:20000] + f"\n... [Unterschied gekürzt, insgesamt {len(diff)} Zeichen]"
        teile.append(f"### DATEI: {pfad}" + (f"\nBegründung von Neo: {grund}" if grund else "") + f"\n```diff\n{diff or '(keine Änderung)'}\n```")
    for b in entwurf(lauf)["befehle"]:
        teile.append(f"### BEFEHL (in {b['cwd']}):\n```\n{b['befehl']}\n```")
    text = "\n\n".join(teile)
    return text if len(text) <= MAX_DIFF else text[:MAX_DIFF] + "\n\n... [GEKÜRZT -- die Änderung ist zu groß, um sie vollständig zu zeigen]"


DARIO_SYSTEM = (
    "Du bist Dario, der unabhängige Prüfer für Änderungen am VvE Cockpit (Python/FastAPI-Backend unter ~/vve-cp-r2/cockpit, "
    "Preact-Frontend unter ~/vve-cp-r2/frontend, läuft als Dienst vve-cp-r2 auf Veikos eigenem Server). Neo, ein lokales "
    "Sprachmodell, hat Änderungen VORGEMERKT. Sie werden NUR eingespielt, wenn du sie freigibst. Prüfe streng: "
    "Erfüllt die Änderung Veikos Auftrag? Kann sie etwas kaputt machen (Syntax, fehlende Importe, entfernte Funktionen, die "
    "anderswo gebraucht werden, abgeschaltete Verbindungen, gelöschte Daten, Sicherheit, Geheimnisse im Code)? Ist sie "
    "vollständig, oder fehlen Teile? Ein Befehl, der Daten löscht, Dienste umbaut oder Pakete installiert, braucht einen klaren "
    "Grund im Auftrag. Im Zweifel: abgelehnt -- mit genauem Grund, damit Neo nachbessern kann. "
    "Lehnst du ab, bring Neo etwas bei (24.10.2026, Veiko: Neo soll aus seinen Fehlern lernen): steckt hinter den Mängeln "
    "eine ART von Fehler, die Neo bei anderen Aufträgen wieder machen könnte, formuliere sie als allgemeine Regel in einem "
    "Satz, in der Du-Form, ohne Bezug auf diesen Auftrag -- z. B. „Benutze nur Namen, die im Code definiert sind; lies die "
    "Stelle vorher mit datei_lesen nach.“ Ist es ein Einzelfall, lass \"lektion\" leer. "
    "Antworte NUR mit JSON: {\"urteil\": \"freigegeben\" oder \"abgelehnt\", \"begruendung\": \"zwei, drei Sätze auf Deutsch\", "
    "\"maengel\": [\"konkreter Mangel\", …], \"lektion\": \"allgemeine Regel oder leer\"}")


async def pruefen(lauf: dict[str, Any], auftrag: str, neo_text: str) -> dict[str, Any]:
    from . import teamchat
    unterschied = _unterschied(lauf)
    if "[GEKÜRZT" in unterschied:
        return {"urteil": "abgelehnt", "von": "Cockpit", "begruendung": "Die Änderung ist zu groß, um sie vollständig prüfen zu lassen. "
                "Neo soll sie in kleinere Schritte teilen.", "maengel": []}
    frage = (f"VEIKOS AUFTRAG AN NEO:\n{auftrag[:6000]}\n\nWAS NEO DAZU SAGT:\n{neo_text[:3000] or '(nichts)'}\n\n"
             f"DIE VORGEMERKTEN ÄNDERUNGEN:\n\n{unterschied}")
    try:
        modell = await teamchat._extern_modell("dario")
        with llm.taetig("Dario prüft Neos Änderung"):
            roh = await teamchat._cloud_chat("dario", modell, DARIO_SYSTEM, [{"role": "user", "content": frage}])
    except llm.ModellFehler as f:
        return {"urteil": "nicht_geprueft", "von": "Dario", "begruendung": f"Dario war nicht erreichbar ({f}). Eingespielt wird ohne seine Prüfung nichts.", "maengel": []}
    d = llm.json_aus(roh) or {}
    u = str(d.get("urteil") or "").lower()
    urteil = "freigegeben" if u.startswith("freigeg") else "abgelehnt"
    if not d:
        urteil = "abgelehnt"
        d = {"begruendung": "Darios Antwort war nicht lesbar -- sicherheitshalber nicht eingespielt.", "maengel": []}
    lektion = None
    if urteil == "abgelehnt" and str(d.get("lektion") or "").strip():
        # Neos Gedaechtnis (neo_lektionen.py): die Regel steht ab jetzt in jedem Auftrag an Neo.
        from . import neo_lektionen
        lektion = neo_lektionen.hinzufuegen(str(d["lektion"]), anlass=auftrag.strip().splitlines()[0][:200] if auftrag.strip() else "")
    return {"urteil": urteil, "von": "Dario", "modell": modell, "begruendung": str(d.get("begruendung") or "")[:1500],
            "maengel": [str(m)[:400] for m in (d.get("maengel") or [])][:10], "lektion": (lektion or {}).get("regel")}


# ---------------------------------------------------------------- einspielen
def _syntax(pfad: Path) -> str | None:
    if pfad.suffix == ".py":
        try:
            compile(pfad.read_text(encoding="utf-8"), str(pfad), "exec")
        except SyntaxError as f:
            return f"{pfad.name}, Zeile {f.lineno}: {f.msg}"
    elif pfad.suffix in (".js", ".mjs"):
        if shutil.which("node"):
            r = subprocess.run(["node", "--check", str(pfad)], capture_output=True, text=True, timeout=30)
            if r.returncode:
                return f"{pfad.name}: {(r.stderr or r.stdout).strip().splitlines()[0] if (r.stderr or r.stdout).strip() else 'Syntaxfehler'}"
    elif pfad.suffix == ".json":
        try:
            json.loads(pfad.read_text(encoding="utf-8"))
        except ValueError as f:
            return f"{pfad.name}: {f}"
    return None


async def einspielen(lauf: dict[str, Any], auftrag: str, pruefung: dict[str, Any], jid: str) -> dict[str, Any]:
    """Schreibt die freigegebenen Dateien, prueft sie, fuehrt die Befehle aus, committet und pusht."""
    e = entwurf(lauf)
    ordner = SICHERUNG / f"{time.strftime('%Y%m%d-%H%M%S')}-{jid}"
    geschrieben: list[tuple[Path, Path | None]] = []        # (Ziel, Sicherung oder None = war neu)
    try:
        for pfad, d in e["dateien"].items():
            z = Path(pfad)
            sich = None
            if z.exists():
                sich = ordner / z.relative_to("/")
                sich.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(z, sich)
            z.parent.mkdir(parents=True, exist_ok=True)
            if d.get("kopie_von"):
                shutil.copyfile(d["kopie_von"], z)
            else:
                z.write_text(d["neu"], encoding="utf-8")
            geschrieben.append((z, sich))
        fehler = [f for f in (_syntax(z) for z, _ in geschrieben) if f]
    except OSError as f:
        fehler = [f"Schreiben gescheitert: {f}"]
    if fehler:
        for z, sich in geschrieben:
            if sich:
                shutil.copy2(sich, z)
            else:
                z.unlink(missing_ok=True)
        return {"ok": False, "grund": "Die Prüfung des Cockpits nach dem Einspielen schlug fehl -- alles ist zurückgerollt: " + "; ".join(fehler)}
    ausgaben, neustart = [], []
    for b in e["befehle"]:
        if NEUSTART.search(b["befehl"]):
            neustart.append(b)
            continue
        p = await asyncio.create_subprocess_shell(b["befehl"], cwd=b["cwd"], stdout=asyncio.subprocess.PIPE,
                                                  stderr=asyncio.subprocess.STDOUT, executable="/bin/bash")
        try:
            out, _ = await asyncio.wait_for(p.communicate(), timeout=300)
        except asyncio.TimeoutError:
            p.kill()
            out = b"(nach 300 s abgebrochen)"
        ausgaben.append(f"`{b['befehl'][:120]}` -> Exit {p.returncode}: {out.decode('utf-8', 'replace').strip()[-400:]}")
    # Commit im Repo, damit die Aenderung sichtbar und nachvollziehbar ist (21.10.: Neos Aenderung lag
    # uncommittet im Server-Klon und fiel niemandem auf).
    commit = None
    im_repo = [str(z.relative_to(WURZEL)) for z, _ in geschrieben if str(z).startswith(str(WURZEL) + "/")]
    if im_repo:
        nachricht = (f"Neo: {auftrag.strip().splitlines()[0][:70] if auftrag.strip() else 'Änderung'}\n\n"
                     f"Geprüft und freigegeben von Dario: {pruefung.get('begruendung', '')[:600]}")
        r = subprocess.run(["git", "add", "--", *im_repo], cwd=WURZEL, capture_output=True, text=True)
        r = subprocess.run(["git", "-c", "user.name=Neo (Cockpit Engineer)", "-c", "user.email=neo@vve-cockpit.local",
                            "commit", "-m", nachricht, "--", *im_repo], cwd=WURZEL, capture_output=True, text=True)
        if r.returncode == 0:
            commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=WURZEL, capture_output=True, text=True).stdout.strip()
            p = subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=WURZEL, capture_output=True, text=True, timeout=60)
            gepusht = p.returncode == 0
        else:
            gepusht = False
    else:
        gepusht = False
    print(f"[neo] Änderung eingespielt (Dario: freigegeben): {', '.join(str(z) for z, _ in geschrieben)}"
          + (f"; Commit {commit}" if commit else ""), flush=True)
    return {"ok": True, "dateien": [str(z) for z, _ in geschrieben], "befehle": ausgaben, "commit": commit, "gepusht": gepusht,
            "sicherung": str(ordner) if any(s for _, s in geschrieben) else None, "neustart": bool(neustart),
            "server_teile": any(z.suffix == ".py" for z, _ in geschrieben)}


def neustart_spaeter() -> None:
    """Der Dienst startet sich neu, nachdem die Antwort gespeichert ist -- Neo laeuft IN diesem Dienst."""
    subprocess.Popen(["bash", "-c", "sleep 4; systemctl --user restart vve-cp-r2"], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def bericht(pruefung: dict[str, Any], ergebnis: dict[str, Any] | None, lauf: dict[str, Any]) -> str:
    e = entwurf(lauf)
    n_d, n_b = len(e["dateien"]), len(e["befehle"])
    was = " und ".join(x for x in (f"{n_d} Datei{'en' if n_d != 1 else ''}" if n_d else "", f"{n_b} Befehl{'e' if n_b != 1 else ''}" if n_b else "") if x)
    if pruefung["urteil"] != "freigegeben":
        kopf = ("**Nicht eingespielt -- Dario war nicht erreichbar.**" if pruefung["urteil"] == "nicht_geprueft"
                else f"**Nicht eingespielt -- {pruefung.get('von', 'Dario')} hat die Änderung abgelehnt.**")
        return (f"{kopf} Vorgemerkt waren {was}; am Cockpit hat sich nichts geändert.\n\n{pruefung.get('begruendung', '')}"
                + ("\n\nMängel:\n" + "\n".join(f"- {m}" for m in pruefung["maengel"]) if pruefung.get("maengel") else "")
                + ("\n\nSag Neo „noch einmal“, sobald Dario wieder erreichbar ist." if pruefung["urteil"] == "nicht_geprueft"
                   else "\n\nSag Neo „bessere nach“, dann arbeitet er die Mängel ein, und Dario prüft erneut."))
    if not ergebnis or not ergebnis.get("ok"):
        return (f"**Dario hat freigegeben, eingespielt ist trotzdem nichts.** {(ergebnis or {}).get('grund', '')}\n\n"
                f"Darios Begründung: {pruefung.get('begruendung', '')}")
    teile = [f"**Von Dario geprüft und freigegeben, eingespielt:** {was}.", pruefung.get("begruendung", "")]
    if ergebnis.get("commit"):
        teile.append(f"Commit {ergebnis['commit']}" + (" (auch auf GitHub)." if ergebnis.get("gepusht") else " -- der Push nach GitHub ging nicht, er liegt nur auf dem Server."))
    if ergebnis.get("befehle"):
        teile.append("Ausgeführt:\n" + "\n".join(f"- {b}" for b in ergebnis["befehle"]))
    if ergebnis.get("sicherung"):
        teile.append(f"Die alten Fassungen liegen gesichert unter {ergebnis['sicherung']}.")
    if ergebnis.get("neustart"):
        teile.append("Das Cockpit startet in wenigen Sekunden neu -- danach einmal die Seite neu laden.")
    elif ergebnis.get("server_teile"):
        teile.append("Server-Teile (Python) wirken erst nach dem nächsten Neustart des Cockpits.")
    return "\n\n".join(t for t in teile if t)
