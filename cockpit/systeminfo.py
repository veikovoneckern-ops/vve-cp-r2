"""
SYSTEM IM DETAIL -- Updates, Empfehlungen, Sicherungen. Ersetzt die
ausfuehrliche Server-Sektion des alten Cockpits fuer die neue Fassung.

Woher die Werte kommen:
  - /status von vve-status (Telemetrie, wie im alten Cockpit)
  - apt selbst: `apt-get -s upgrade` (Simulation, braucht kein root) und
    `apt list --upgradable`. Was upgradebar ist, aber in der Simulation nicht
    eingespielt wuerde, haelt Ubuntu GESTAFFELT zurueck -- das ist die Antwort
    auf "was einspielen, was nicht".
  - GitHub fuer die neueste Ollama-Fassung (6 Stunden gemerkt).
  - /var/lib/vvec/sicherung-status.json fuer die OneDrive-Sicherungen.

Was eingespielt werden darf, entscheidet die sudo-Regel fuer vveadmin, nicht
dieser Code: genau `apt-get update`, `apt-get -y upgrade` und `reboot` gehen
ohne Passwort. Alles andere (Ollama-Update, Firmware) steht als Befehl da.

ischroot: Im alten Backend log apt wegen des gehaerteten Namensraums ueber die
Staffelung. Dieser Dienst laeuft ungehaertet; die Simulation bekommt trotzdem
`Dir::Bin::ischroot=/bin/false` -- dieselbe Wirklichkeit wie der echte Lauf.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx

from . import db
from .konfig import ALT_DATEN, STATUS_URL

_cache: dict[str, Any] = {}
APT_SIM = ["apt-get", "-s", "-o", "Debug::NoLocking=1", "-o", "Dir::Bin::ischroot=/bin/false", "upgrade"]


def _gemerkt(schluessel: str, sek: float):
    e = _cache.get(schluessel)
    return e["wert"] if e and time.time() - e["zeit"] < sek else None


def _merken(schluessel: str, wert: Any) -> Any:
    _cache[schluessel] = {"zeit": time.time(), "wert": wert}
    return wert


def _lauf(befehl: list[str], timeout: int = 60) -> str:
    try:
        r = subprocess.run(befehl, capture_output=True, text=True, timeout=timeout,
                           env={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
        return r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def updates(frisch: bool = False) -> dict[str, Any]:
    if not frisch:
        g = _gemerkt("updates", 600)
        if g is not None:
            return g
    sim = _lauf(APT_SIM)
    einspielbar = {}
    for z in sim.splitlines():
        m = re.match(r"^Inst (\S+) (?:\[(\S+)\] )?\((\S+)", z)
        if m:
            einspielbar[m.group(1)] = {"name": m.group(1), "von": m.group(2) or "", "nach": m.group(3)}
    alle = {}
    for z in _lauf(["apt", "list", "--upgradable"]).splitlines():
        m = re.match(r"^([^/\s]+)/(\S+) (\S+) \S+ \[(?:upgradable from|aktualisierbar von): ([^\]]+)\]", z)
        if m:
            alle[m.group(1)] = {"name": m.group(1), "quelle": m.group(2), "nach": m.group(3), "von": m.group(4)}
    pakete = []
    for name, p in sorted(alle.items()):
        pakete.append({**p, "einspielbar": name in einspielbar,
                       "sicherheit": "security" in p.get("quelle", "")})
    for name, p in einspielbar.items():
        if name not in alle:
            pakete.append({**p, "quelle": "", "einspielbar": True, "sicherheit": False})
    # Kurzbeschreibungen in EINEM apt-cache-Aufruf
    if pakete:
        beschr, aktuell = {}, None
        for z in _lauf(["apt-cache", "show", "--no-all-versions"] + [p["name"] for p in pakete]).splitlines():
            if z.startswith("Package: "):
                aktuell = z[9:].strip()
            elif aktuell and (z.startswith("Description-en: ") or z.startswith("Description: ")) and aktuell not in beschr:
                beschr[aktuell] = z.split(": ", 1)[1].strip()
        for p in pakete:
            p["beschreibung"] = beschr.get(p["name"], "")
    return _merken("updates", {"pakete": pakete, "zeit": time.time(),
                               "einspielbar": sum(1 for p in pakete if p["einspielbar"]),
                               "gestaffelt": sum(1 for p in pakete if not p["einspielbar"])})


async def ollama_neueste() -> str | None:
    g = _gemerkt("ollama_neu", 6 * 3600)
    if g is not None:
        return g
    try:
        async with httpx.AsyncClient(timeout=6, headers={"User-Agent": "VvE-Cockpit"}) as c:
            r = await c.get("https://api.github.com/repos/ollama/ollama/releases/latest")
        tag = str(r.json().get("tag_name") or "").lstrip("v") or None
    except (httpx.HTTPError, ValueError):
        tag = None
    return _merken("ollama_neu", tag) if tag else None


def _fassung(s: str | None) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", s or "")[:3])


def sicherungen() -> dict[str, Any] | None:
    try:
        s = json.loads((ALT_DATEN / "sicherung-status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    # Die neue Fassung (sicherung.py, 23.10.2026) unter "neu" -- dieselbe Form wie die alten
    # (zeit, zustand), damit Kopfzeile, Kachel und Empfehlungen sie ohne Sonderweg lesen.
    from . import sicherung
    n = sicherung.stand()
    s["neu"] = {"zeit": n.get("zeit"), "zustand": n.get("zustand") if n.get("eingerichtet") else "nicht_eingerichtet",
                "groesse_mb": n.get("groesse_mb"), "laeuft": n.get("laeuft"), "fehler": n.get("fehler")}
    return s


async def status() -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            return (await c.get(f"{STATUS_URL}/status")).json()
    except (httpx.HTTPError, ValueError):
        return None


def _gb(s: str) -> float:
    m = re.match(r"([\d.]+)\s*(GB|MB)", s or "")
    if not m:
        return 0.0
    return float(m.group(1)) / (1024 if m.group(2) == "MB" else 1)


def modelle(s: dict[str, Any] | None) -> list[dict[str, Any]]:
    s = s or {}
    team = {}
    for t in db.alle("SELECT name, modell FROM team WHERE modell!=''"):
        team.setdefault(t["modell"], []).append(t["name"])
    geladen = {}
    for m in s.get("ollama_laeuft") or []:
        if isinstance(m, dict):
            geladen[m.get("name")] = m
    out = []
    for z in s.get("ollama_models") or []:
        name, _, groesse = str(z).partition("|")
        out.append({"name": name, "groesse": groesse, "gb": _gb(groesse), "team": team.get(name, []),
                    "geladen": name in geladen, "prozessor": (geladen.get(name) or {}).get("prozessor")})
    return out


def empfehlungen(s: dict[str, Any] | None, upd: dict[str, Any], ollama_neu: str | None,
                 sich: dict[str, Any] | None, stab_ges: dict[str, Any]) -> list[dict[str, Any]]:
    """Jede Empfehlung wird aus Live-Daten gerechnet und verschwindet von selbst,
    sobald sie erledigt ist -- dieselbe Regel wie im alten Cockpit."""
    s = s or {}
    e: list[dict[str, Any]] = []
    jetzt = time.time()
    ein = [p for p in upd.get("pakete", []) if p["einspielbar"]]
    gest = [p for p in upd.get("pakete", []) if not p["einspielbar"]]
    if ein:
        sich_n = sum(1 for p in ein if p["sicherheit"])
        e.append({"stufe": "einspielen", "titel": f"{len(ein)} Update{'s' if len(ein) != 1 else ''} einspielen" + (f", davon {sich_n} Sicherheit" if sich_n else ""),
                  "warum": "Diese Pakete würde apt jetzt einspielen: " + ", ".join(p["name"] for p in ein[:8]) + ("…" if len(ein) > 8 else "") + ".",
                  "aktion": {"art": "updates", "text": "Einspielen"}})
    if gest:
        e.append({"stufe": "nicht", "titel": f"{len(gest)} gestaffelt zurückgehalten, nicht einspielen",
                  "warum": "Ubuntu verteilt diese Fassungen schrittweise und hält sie hier noch zurück: " + ", ".join(p["name"] for p in gest[:8]) +
                           ". Das ist Absicht; sie kommen von selbst, sobald Ubuntu sie freigibt."})
    upd_s = s.get("updates") or {}
    if upd_s.get("reboot_required"):
        e.append({"stufe": "achtung", "titel": "Neustart fällig", "warum": "Ein Update (meist Kernel oder Firmware) wird erst nach einem Neustart wirksam. Laufende Arbeit des Stabs und von Neo bricht dabei ab.",
                  "aktion": {"art": "neustart", "text": "Server neu starten"}})
    laufend = (s.get("versions") or {}).get("ollama", "")
    if ollama_neu and laufend and _fassung(ollama_neu) > _fassung(laufend):
        from .konfig import ALT_TOKEN
        titel = f"Ollama {ollama_neu} verfügbar (läuft: {laufend.replace('Ollama ', '')})"
        if AUFTRAG.get("art") == "ollama-update" and AUFTRAG.get("laeuft"):
            e.append({"stufe": "info", "titel": titel, "warum": "Das Update läuft gerade -- den Fortschritt siehst du oben im Auftrag."})
        elif ollama_eigen() or ALT_TOKEN:
            e.append({"stufe": "einspielen", "titel": titel,
                      "warum": "Neuere Modelle lassen sich mit einer alten Fassung oft nicht laden. Die neue Fassung wird erst vollständig geladen, "
                               "dann in Sekunden getauscht; antwortet Ollama danach nicht, kommt die alte zurück. "
                               + ("Läuft über das eigene Update-Skript des Cockpits." if ollama_eigen() else "Läuft noch über den Wartungsdienst des alten Cockpits."),
                      "aktion": {"art": "ollama-update", "text": "Einspielen"}})
        else:
            # Ohne eigenes Skript und ohne Token gibt es keinen Weg ohne Passwort -- dann steht hier
            # der EINMALIGE Schritt, nach dem es fuer immer per Knopf geht.
            e.append({"stufe": "einspielen", "titel": titel,
                      "warum": "Für den Knopf braucht das Cockpit einmal sein Update-Skript (fragt dein Passwort), danach steht hier „Einspielen“.",
                      "befehl": OLLAMA_EINRICHTEN})
    if not ollama_eigen():
        e.append({"stufe": "achtung", "titel": "Hängt noch am alten Cockpit: Ollama-Update",
                  "warum": "Ollama zu aktualisieren braucht Administratorrechte; bisher läuft das über den Wartungsdienst des alten Cockpits. "
                           "Einmal das eigene Update-Skript einrichten (fragt dein Passwort). Es gehört root, das Cockpit darf genau dieses eine "
                           "Skript ohne Argumente starten -- sonst nichts.",
                  "befehl": OLLAMA_EINRICHTEN})
    # Externe und Postausgang (cloud.py, mail.py, 23.10.2026): solange die Schluessel nicht hier liegen, laufen
    # Dario, Elon, Demmis und jede Mail ueber das alte Cockpit -- und fielen mit ihm aus.
    from . import cloud, mail
    fehlt = [n for n, da in (("Dario (Claude)", cloud.schluessel("claude")), ("Demmis (Gemini)", cloud.schluessel("gemini")),
                             ("Elon (Grok)", cloud.schluessel("grok")), ("Postausgang", mail.smtp_stand()["ok"])) if not da]
    if fehlt:
        e.append({"stufe": "achtung", "titel": "Hängt noch am alten Cockpit: " + ", ".join(fehlt),
                  "warum": "Die Schlüssel liegen bisher nur im alten Cockpit. Einmal übernehmen (fragt dein Passwort) -- danach spricht "
                           "das neue Cockpit die Externen und den Mailserver selbst an, und das alte kann weg.",
                  "befehl": cloud.einrichten_befehl()})
    fw = ((s.get("firmware") or {}).get("fwupd") or {})
    for u in fw.get("updates") or []:
        sb_db = u.get("secure_boot_db")
        if sb_db and s.get("firmware", {}).get("secure_boot") is False or (sb_db and u.get("gescheitert")):
            e.append({"stufe": "nicht", "titel": f"Firmware {u.get('name')}: nicht einspielen",
                      "warum": "Secure Boot ist auf diesem Server aus; das Update der Secure-Boot-Datenbank wirkt dann nicht (zuletzt: eingespielt, aber nach dem Neustart wieder fällig)."})
        else:
            e.append({"stufe": "einspielen", "titel": f"Firmware {u.get('name')} {u.get('version')} → {u.get('neu')}",
                      "warum": f"{u.get('was') or 'Firmware-Update'} von {u.get('hersteller') or 'Hersteller'}. Braucht dein Passwort.",
                      "befehl": "sudo fwupdmgr update"})
    for art, name in (("inhalt", "Inhalt"), ("server", "Server")):
        x = (sich or {}).get(art) or {}
        if not x:
            continue
        alter = jetzt - float(x.get("zeit") or 0)
        if x.get("zustand") != "ok" or alter > 48 * 3600:
            e.append({"stufe": "achtung", "titel": f"Sicherung {name}: {'fehlgeschlagen' if x.get('zustand') != 'ok' else 'älter als zwei Tage'}",
                      "warum": f"Letzter Lauf {time.strftime('%d.%m. %H:%M', time.localtime(float(x.get('zeit') or 0)))}: {x.get('text') or x.get('zustand')}. Läuft täglich um 03:00/03:15; zwei Ausfälle in Folge sind kein Zufall."})
    # Die neue Fassung (sicherung.py, 23.10.2026): ohne OneDrive liegt alles nur auf dieser einen Platte.
    from . import sicherung
    n = sicherung.stand()
    if not n.get("eingerichtet"):
        e.append({"stufe": "achtung", "titel": "Neues Cockpit: keine Sicherung außerhalb des Servers",
                  "warum": "Datenbank, Unterlagen, Medien und Zugangsdaten liegen nur auf dieser Platte. Einmal einrichten "
                           "(braucht dein Passwort) -- danach sichert es jede Nacht um 03:30 verschlüsselt nach OneDrive.",
                  "befehl": sicherung.einrichten_befehl()})
    elif n.get("zustand") == "fehler" or (n.get("zeit") and jetzt - float(n["zeit"]) > 48 * 3600):
        e.append({"stufe": "achtung", "titel": "Neues Cockpit: Sicherung " + ("fehlgeschlagen" if n.get("zustand") == "fehler" else "älter als zwei Tage"),
                  "warum": str(n.get("fehler") or "Läuft täglich um 03:30.")[:300]})
    if n.get("zustand") == "ok" and not n.get("schluessel_bestaetigt"):
        e.append({"stufe": "achtung", "titel": "Schlüssel der Sicherung in deinen Passwortmanager",
                  "warum": "Die Sicherung in OneDrive ist verschlüsselt. Fällt die Platte des Servers aus, ist der Schlüssel mit weg -- "
                           "und die Sicherung wertlos. Im Stack unter Sicherungen: „Schlüssel anzeigen“."})
    platte = s.get("disk_gb") or {}
    if platte.get("total") and platte.get("free", 0) / platte["total"] < 0.1:
        e.append({"stufe": "achtung", "titel": f"Platte fast voll ({round(platte['free'])} GB frei)", "warum": "Unter zehn Prozent frei. Große Modelle oder ComfyUI-Ausgaben aufräumen."})
    for i, z in enumerate(str(s.get("gpu_nvidia") or "").strip().splitlines()):
        teile = [t.strip() for t in z.split(",")]
        if len(teile) > 1 and teile[1].isdigit() and int(teile[1]) >= 80:
            e.append({"stufe": "achtung", "titel": f"Grafikkarte {i + 1} heiß: {teile[1]} °C", "warum": "Ab 90 °C greift der WatchDog mit dem Notfallablauf. Lüftung und Docks prüfen."})
    # Advisory Board (board.py, 23.10.2026): frischt die neue Fassung selbst auf; laeuft der Zeitgeber des alten
    # Cockpits noch, rechnet er um 04:30 doppelt -- mitten in die Daily Tasks und "Morgens bereit".
    try:
        alt_board = subprocess.run(["systemctl", "is-enabled", "vvec-board.timer"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        alt_board = ""
    if alt_board == "enabled":
        e.append({"stufe": "achtung", "titel": "Altes Cockpit frischt das Advisory Board noch zusätzlich auf",
                  "warum": "Das neue Cockpit macht das seit dem 23.10. selbst (nachts 23 Uhr). Der alte Zeitgeber rechnet um 04:30 "
                           "doppelt auf den Grafikkarten. Abschalten (fragt dein Passwort):",
                  "befehl": "sudo systemctl disable --now vvec-board.timer && echo abgeschaltet"})
    # Plaud (plaud.py, 23.10.2026): eigener Abruf, sobald eingerichtet -- bis dahin der des alten Cockpits.
    from . import plaud
    pl = plaud.stand()
    if not pl.get("laeuft_selbst"):
        e.append({"stufe": "achtung", "titel": "Hängt noch am alten Cockpit: Plaud-Notizen",
                  "warum": "Die Sprachnotizen holt bisher das alte Cockpit. Einmal übernehmen (fragt dein Passwort) -- danach holt das "
                           "neue sie selbst jede Minute, der Abruf des alten wird dabei abgeschaltet. Bisherige Notizen kommen nicht doppelt."
                           + (f" (Der eigene Abruf scheitert gerade: {str(pl['fehler'])[:160]})" if pl.get("fehler") else ""),
                  "befehl": plaud.einrichten_befehl()})
    elif pl.get("ok") is False:
        e.append({"stufe": "achtung", "titel": "Plaud-Abruf gescheitert", "warum": str(pl.get("fehler") or "")[:300]})
    if stab_ges.get("sync") and jetzt - stab_ges["sync"] > 1800:
        e.append({"stufe": "achtung", "titel": "Plaud-Abruf hängt", "warum": "Seit über einer halben Stunde kein erfolgreicher Abruf. Häufigste Ursache: "
                  "Anmeldung bei Plaud abgelaufen -- auf dem Laptop „plaud login“, dann ~/.plaud/tokens.json auf den Server nach ~/.plaud/ kopieren."})
    sicher = s.get("sicherheit") or {}
    if (sicher.get("ufw") or {}).get("offene_regeln"):
        e.append({"stufe": "achtung", "titel": "Firewall: Regel für alle offen", "warum": "Eine ufw-Regel erlaubt Zugriff aus dem ganzen Internet statt nur aus dem Tailnet: " + ", ".join(map(str, sicher["ufw"]["offene_regeln"]))})
    for name, t in (s.get("timers") or {}).items():
        if name.startswith("vvec-backup"):
            continue
        if t.get("geladen") and t.get("aktiv") != "active":
            e.append({"stufe": "achtung", "titel": f"Zeitgeber {name} läuft nicht", "warum": f"Stand: {t.get('aktiv')}. Was er anstößt, passiert gerade nicht."})
    # Neustart als Empfehlung nur, wenn der Dienst wirklich steht. Die Knoepfe
    # an Ollama und Caddy im Software-Schaubild sind Werkzeuge fuer den Fall,
    # dass etwas haengt, obwohl es "active" meldet -- keine Aufforderung.
    for dienst, folge in (("ollama", "Lokale Modelle, Team und Neo antworten nicht."),
                          ("caddy", "Das alte Cockpit ist nicht erreichbar.")):
        stand = (s.get("services") or {}).get(dienst)
        if stand and stand != "active":
            e.append({"stufe": "achtung", "titel": f"{dienst.capitalize()} läuft nicht",
                      "warum": f"Stand: {stand}. {folge}",
                      "aktion": {"art": f"{dienst}-neustart", "text": f"{dienst.capitalize()} neu starten"}})
    for c in s.get("docker") or []:
        name, _, zustand = str(c).partition("|")
        if not zustand.startswith("Up"):
            e.append({"stufe": "achtung", "titel": f"Container {name} läuft nicht", "warum": f"Stand: {zustand}.", "befehl": f"docker start {name}"})
    reihen = {"achtung": 0, "einspielen": 1, "nicht": 2, "info": 3}
    return sorted(e, key=lambda x: reihen.get(x["stufe"], 9))


# ------------------------------------------------------------ Auftraege (apt, Neustart)
AUFTRAG: dict[str, Any] = {"art": None, "laeuft": False, "log": "", "rc": None, "start": None, "ende": None}
# Die zuletzt gerechneten Empfehlungen -- fuer Talk auf der Seite Recommendations, ohne neuen Abruf.
EMPF_ZULETZT: list[dict[str, Any]] = []


async def _ausfuehren(befehle: list[list[str]]) -> None:
    AUFTRAG.update(laeuft=True, log="", rc=None, start=time.time(), ende=None)
    rc = 0
    gestoert: list[str] = []
    for b in befehle:
        anfang = len(AUFTRAG["log"])
        AUFTRAG["log"] += f"$ {' '.join(b)}\n"
        try:
            p = await asyncio.create_subprocess_exec(*b, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                                                     env={"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                                                          "DEBIAN_FRONTEND": "noninteractive"})
            assert p.stdout
            async for zeile in p.stdout:
                AUFTRAG["log"] = (AUFTRAG["log"] + zeile.decode("utf-8", "replace"))[-40000:]
            rc = await p.wait()
        except OSError as f:
            AUFTRAG["log"] += f"Fehler: {f}\n"
            rc = 1
        # apt-get update endet mit 100, sobald EINE Paketquelle nicht antwortet
        # (09.10.2026: Cloudsmith, wo Caddy seine Pakete ablegt, meldete
        # "402 Payment Required"). Die uebrigen Quellen sind dann trotzdem
        # frisch; deswegen das ganze Einspielen abzubrechen hiesse, dass eine
        # fremde Stoerung jedes Ubuntu-Update blockiert. Weiter geht es nur,
        # wenn wirklich einzelne Quellen ("Err:") die Ursache sind -- ein
        # Passwortproblem oder ein kaputtes apt bricht weiterhin ab.
        teil = AUFTRAG["log"][anfang:]
        if rc != 0 and b[-1] == "update" and "a password is required" not in teil:
            gestoert = [z.split()[1] for z in teil.splitlines() if z.startswith("Err:") and len(z.split()) > 1]
            if gestoert:
                AUFTRAG["log"] += ("\nNicht erreichbar: " + ", ".join(gestoert) +
                                   ". Die übrigen Quellen sind aktuell, eingespielt wird trotzdem.\n\n")
                rc = 0
                continue
        if rc != 0:
            if "a password is required" in AUFTRAG["log"]:
                AUFTRAG["log"] += "\nsudo verlangt ein Passwort: dieser Befehl ist für vveadmin nicht ohne Passwort freigegeben.\n"
            break
    if rc == 0 and gestoert:
        AUFTRAG["log"] += ("\nEingespielt. Hinweis: " + ", ".join(gestoert) + " war nicht erreichbar; "
                           "Pakete aus dieser Quelle kommen beim nächsten Lauf, sobald sie wieder antwortet.\n")
    AUFTRAG.update(laeuft=False, rc=rc, ende=time.time(), gestoert=gestoert)
    _cache.pop("updates", None)


def starten(art: str) -> bool:
    if AUFTRAG["laeuft"]:
        return False
    AUFTRAG["art"] = art
    if art == "updates":
        befehle = [["sudo", "-n", "/usr/bin/apt-get", "update"], ["sudo", "-n", "/usr/bin/apt-get", "-y", "upgrade"]]
    elif art == "neustart":
        befehle = [["sudo", "-n", "/usr/sbin/reboot"]]
    elif art in ("ollama-neustart", "caddy-neustart"):
        # Genau diese beiden Neustarts sind fuer vveadmin ohne Passwort
        # freigegeben -- dieselben Knoepfe wie im Software-Schaubild des alten Cockpits.
        befehle = [["sudo", "-n", "/usr/bin/systemctl", "restart", art.split("-")[0]]]
    else:
        return False
    asyncio.create_task(_ausfuehren(befehle))
    return True


# ------------------------------------------------------------ Ollama-Update (ueber das alte Cockpit)
# Das Installationsskript braucht root. Es gibt dafuer schon EINEN erprobten Weg:
# den Wartungsdienst des alten Cockpits (vvec-wartung.service, Art
# "ollama-aktualisieren", seit 30.09. zweimal sauber gelaufen). Einen zweiten
# root-Weg hier zu bauen waere eine zweite Stelle, an der Rechte falsch stehen
# koennen. Diese Fassung stoesst ihn nur an (Token) und liest das Protokoll mit,
# das der Lauf ohnehin lesbar ablegt (/var/lib/vvec/wartung/lauf, 644) -- sie
# schreibt im alten Bestand nichts.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def _protokoll_lesbar(roh: str) -> str:
    # Das Skript malt Fortschrittsbalken mit \r -- je Zeile zaehlt nur der letzte Stand.
    zeilen = [z.split("\r")[-1] for z in _ANSI.sub("", roh).split("\n")]
    return "\n".join(z for z in zeilen if z.strip())[-8000:]


# EIGENER WEG (23.10.2026): ein root-eigenes Skript (server/vve-ollama-aktualisieren.sh, von Veiko einmal
# nach /usr/local/sbin installiert), das vveadmin per sudo OHNE Argumente starten darf. Gestartet als eigene
# systemd-Benutzereinheit, damit ein Neustart des Cockpits das Update nicht abbricht. Protokoll und Stand
# liegen in derselben Form wie beim alten Wartungsdienst -- _ollama_folgen liest beide gleich.
OLLAMA_SKRIPT = "/usr/local/sbin/vve-ollama-aktualisieren"
EIGEN_LAUF = Path(os.environ.get("VVEC_WARTUNG_LAUF", "/var/lib/vve-cp-r2-wartung"))
OLLAMA_EINRICHTEN = ("sudo install -o root -g root -m 755 ~/vve-cp-r2/server/vve-ollama-aktualisieren.sh " + OLLAMA_SKRIPT +
                     " && echo 'vveadmin ALL=(root) NOPASSWD: " + OLLAMA_SKRIPT + "' | sudo tee /etc/sudoers.d/vve-ollama-aktualisieren >/dev/null"
                     " && sudo chmod 440 /etc/sudoers.d/vve-ollama-aktualisieren && sudo visudo -c -q && echo eingerichtet")


def ollama_eigen() -> bool:
    """Ist der eigene Weg eingerichtet? sudo -l mit genau diesem Befehl sagt es, ohne etwas auszufuehren."""
    g = _gemerkt("ollama_eigen", 300)
    if g is not None:
        return g
    befehl = os.environ.get("VVEC_OLLAMA_UPDATE_TEST")  # nur Pruefung: ein nachgestelltes Skript ohne sudo
    if befehl:
        return _merken("ollama_eigen", True)
    try:
        r = subprocess.run(["sudo", "-n", "-l", OLLAMA_SKRIPT], capture_output=True, timeout=5)
        return _merken("ollama_eigen", r.returncode == 0 and Path(OLLAMA_SKRIPT).is_file())
    except (OSError, subprocess.TimeoutExpired):
        return False


async def ollama_update_starten() -> dict[str, Any]:
    from .konfig import ALT_BACKEND, ALT_TOKEN
    if AUFTRAG["laeuft"]:
        return {"ok": False, "grund": "Es läuft schon ein Auftrag."}
    if ollama_eigen():
        start = time.time()
        befehl = os.environ.get("VVEC_OLLAMA_UPDATE_TEST")
        aufruf = ([befehl] if befehl else
                  ["systemd-run", "--user", "--collect", f"--unit=vve-cp-r2-ollama-{int(start)}", "sudo", "-n", OLLAMA_SKRIPT])
        p = await asyncio.create_subprocess_exec(*aufruf, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        if befehl:
            asyncio.create_task(p.wait())
        else:
            _, fehler = await p.communicate()
            if p.returncode:
                return {"ok": False, "grund": f"Update ließ sich nicht starten: {fehler.decode(errors='replace')[:300]}"}
        ziel = await _ollama_paketgroesse()
        plan = {"start": start, "netz_start": _netz_rx(), "ziel": ziel, "eigen": True}
        try:
            _OLLAMA_PLAN.write_text(json.dumps(plan), encoding="utf-8")
        except OSError:
            pass
        AUFTRAG.update(art="ollama-update", laeuft=True, rc=None, start=start, ende=None, fortschritt={"phase": "wartet"},
                       log="Update gestartet …\n")
        asyncio.create_task(_ollama_folgen(start - 10, plan, EIGEN_LAUF))
        return {"ok": True}
    if not ALT_TOKEN:
        return {"ok": False, "grund": "Dafür fehlt einmalig der Cockpit-Token des alten Backends (siehe Befehl in der Empfehlung)."}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{ALT_BACKEND}/api/wartung/ollama", headers={"X-Cockpit-Token": ALT_TOKEN})
    except httpx.HTTPError as f:
        return {"ok": False, "grund": f"Das Backend des alten Cockpits antwortet nicht ({f.__class__.__name__})."}
    if r.status_code == 401:
        return {"ok": False, "grund": "Das alte Backend lehnt den Token ab. Steht in ~/.config/vve-cp-r2.env der aktuelle COCKPIT_TOKEN?"}
    try:
        d = r.json()
    except ValueError:
        d = {}
    if d.get("darf_nicht"):
        return {"ok": False, "grund": "Der Wartungsdienst des alten Cockpits ist nicht eingerichtet."}
    start = time.time()
    # Fortschritt (Veiko, 03.10.: "ich brauche eine klare Anzeige, Prozent oder Balken"):
    # Das Skript schreibt waehrend des Downloads NICHTS ins Protokoll -- der Balken
    # von curl kommt erst am Ende -- und der Zielordner ist beim Entpacken root-only.
    # Messbar ist der Netzverkehr des Servers; verglichen mit der Dateigroesse bei
    # GitHub ergibt das eine ehrliche Schaetzung. Startwerte liegen in einer Datei,
    # damit ein Neustart dieses Dienstes die Anzeige nicht verliert.
    ziel = await _ollama_paketgroesse()
    plan = {"start": start, "netz_start": _netz_rx(), "ziel": ziel}
    try:
        _OLLAMA_PLAN.write_text(json.dumps(plan), encoding="utf-8")
    except OSError:
        pass
    AUFTRAG.update(art="ollama-update", laeuft=True, rc=None, start=start, ende=None, fortschritt={"phase": "wartet"},
                   log="Auftrag an den Wartungsdienst übergeben" + (" (lief schon)" if d.get("laeuft_bereits") else "") + " …\n")
    asyncio.create_task(_ollama_folgen(start - (3600 if d.get("laeuft_bereits") else 10), plan))
    return {"ok": True}


def _ollama_plan_pfad():
    from .konfig import DATEN
    return DATEN / "ollama-update.json"


_OLLAMA_PLAN = _ollama_plan_pfad()
OLLAMA_PAKET = "https://ollama.com/download/ollama-linux-amd64.tar.zst"


async def _ollama_paketgroesse() -> int | None:
    """Groesse des Pakets, das install.sh laedt -- per Ein-Byte-Anfrage (Content-Range)."""
    g = _gemerkt("ollama_groesse", 3600)
    if g:
        return g
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"Range": "bytes=0-0", "User-Agent": "VvE-Cockpit"}) as c:
            r = await c.get(OLLAMA_PAKET)
        m = re.search(r"/(\d+)\s*$", r.headers.get("content-range", ""))
        return _merken("ollama_groesse", int(m.group(1))) if m else None
    except httpx.HTTPError:
        return None


def _netz_rx() -> int:
    """Empfangene Bytes aller echten Netzanschluesse (LAN/WLAN, nicht Tailscale, Docker, lo)."""
    summe = 0
    try:
        for z in Path("/proc/net/dev").read_text().splitlines()[2:]:
            name, _, werte = z.partition(":")
            if re.match(r"\s*(en|eth|wl)", name):
                summe += int(werte.split()[0])
    except (OSError, ValueError, IndexError):
        pass
    return summe


def ollama_update_wiederaufnehmen() -> None:
    """Nach einem Neustart dieses Dienstes: laeuft das Update noch, wieder mitlesen."""
    if AUFTRAG["laeuft"]:
        return
    try:
        plan = json.loads(_OLLAMA_PLAN.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    lauf_dir = EIGEN_LAUF if plan.get("eigen") else ALT_DATEN / "wartung" / "lauf"
    try:
        neueste = max(lauf_dir.glob("ollama-aktualisieren-*.stand"), key=lambda p: p.stat().st_mtime)
        if not neueste.read_text().startswith("running") or neueste.stat().st_mtime < plan["start"] - 60:
            return
    except (OSError, ValueError, KeyError):
        return
    AUFTRAG.update(art="ollama-update", laeuft=True, rc=None, start=plan["start"], ende=None, fortschritt={"phase": "download"}, log="")
    asyncio.create_task(_ollama_folgen(plan["start"] - 10, plan, lauf_dir))


def _phase(log: str) -> str:
    # Eigenes Skript (23.10.2026): schreibt seine Phase ausdruecklich.
    if "PHASE einrichten" in log:
        return "einrichten"
    if "PHASE download" in log:
        return "download"
    zeilen = [z for z in log.splitlines() if z.startswith(">>>")]
    letzte = zeilen[-1] if zeilen else ""
    if "Downloading" in letzte:
        return "download"
    # Nach dem Download kommen diese Zeilen. Auf "Downloading" weiter oben ist kein
    # Verlass: das Protokoll wird auf sein Ende gekuerzt, die Zeile faellt heraus.
    if any(w in z for z in zeilen for w in ("Downloading", "Adding", "Creating", "Enabling", "GPU", "complete")):
        return "einrichten"
    return "vorbereiten"


async def _ollama_folgen(ab: float, plan: dict[str, Any] | None = None, lauf_dir: Path | None = None) -> None:
    lauf_dir = lauf_dir or (ALT_DATEN / "wartung" / "lauf")
    ende = time.time() + 3700
    gefunden = None
    plan = plan or {}
    letzte_probe: tuple[float, int] | None = None
    langsam_seit: float | None = None
    while time.time() < ende:
        await asyncio.sleep(3)
        if not gefunden:
            kandidaten = sorted((p for p in lauf_dir.glob("ollama-aktualisieren-*.stand") if p.stat().st_mtime >= ab),
                                key=lambda p: p.stat().st_mtime)
            if kandidaten:
                gefunden = kandidaten[-1]
            elif time.time() - ab > 90:
                AUFTRAG.update(laeuft=False, rc=1, ende=time.time(),
                               log=AUFTRAG["log"] + "Der Wartungsdienst hat den Auftrag nach 90 Sekunden noch nicht aufgegriffen.\n")
                return
            continue
        try:
            stand = gefunden.read_text(encoding="utf-8").strip()
            AUFTRAG["log"] = _protokoll_lesbar(gefunden.with_suffix(".log").read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if stand.startswith(("done", "failed")):
            teile = stand.split()
            rc = int(teile[1]) if len(teile) > 1 and teile[1].lstrip("-").isdigit() else (0 if stand.startswith("done") else 1)
            AUFTRAG.update(laeuft=False, rc=rc, ende=time.time(),
                           fortschritt={"phase": "fertig" if rc == 0 else "fehler", "prozent": 100 if rc == 0 else None})
            _cache.pop("ollama_neu", None)
            try:
                _OLLAMA_PLAN.unlink()
            except OSError:
                pass
            return
        # Fortschritt aus dem Netzverkehr (siehe ollama_update_starten).
        jetzt, rx = time.time(), _netz_rx()
        kbs = None
        if letzte_probe and jetzt > letzte_probe[0]:
            kbs = max(0, (rx - letzte_probe[1]) / (jetzt - letzte_probe[0]) / 1024)
        letzte_probe = (jetzt, rx)
        phase = _phase(AUFTRAG["log"])
        f: dict[str, Any] = {"phase": phase, "kbs": round(kbs) if kbs is not None else None}
        if phase == "download":
            geladen = max(0, rx - int(plan.get("netz_start") or rx))
            f["mb"] = round(geladen / 1048576)
            if plan.get("ziel"):
                f["gesamt_mb"] = round(plan["ziel"] / 1048576)
                f["prozent"] = min(99, int(geladen * 100 / plan["ziel"]))
            if kbs is not None and kbs < 20:
                langsam_seit = langsam_seit or jetzt
                f["steht_seit"] = round(jetzt - langsam_seit)
            else:
                langsam_seit = None
        elif phase == "einrichten":
            f["prozent"] = 99 if plan.get("ziel") else None
        AUFTRAG["fortschritt"] = f
    AUFTRAG.update(laeuft=False, rc=1, ende=time.time(), log=AUFTRAG["log"] + "\nKein Abschluss nach einer Stunde -- Stand unbekannt.\n")


async def gesamt(frisch: bool = False) -> dict[str, Any]:
    from . import stab
    ollama_update_wiederaufnehmen()
    s = await status()
    upd = await asyncio.to_thread(updates, frisch)
    neu = await ollama_neueste()
    sich = sicherungen()
    from . import modellkatalog
    try:
        katalog = await modellkatalog.pruefen(frisch)
    except Exception:  # noqa: BLE001 -- ohne Netz zur Registry bleibt der Rest der Seite heil
        katalog = None
    try:   # neue Modelle bei ollama.com (Nachfolger der Familien, die hier laufen), 24 h gemerkt
        neu_ollama = await modellkatalog.neu_bei_ollama(frisch, _vram_gesamt(s))
    except Exception:  # noqa: BLE001
        neu_ollama = None
    e = (empfehlungen(s, upd, neu, sich, stab.gesundheit()) + modellkatalog.vorschlaege(katalog, _vram_gesamt(s))
         + modellkatalog.neu_vorschlaege(neu_ollama))
    EMPF_ZULETZT[:] = e
    return {"status": s, "updates": upd, "ollama_neueste": neu, "sicherungen": sich, "modelle": modelle(s),
            "empfehlungen": e, "auftrag": AUFTRAG, "laden": modellkatalog.LADEN,
            "katalog_stand": katalog and katalog.get("zeit"), "karten": await asyncio.to_thread(karten),
            "watchdog": watchdog()}


def _vram_gesamt(s: dict[str, Any] | None) -> float:
    gb = 0.0
    for z in str((s or {}).get("gpu_nvidia") or "").strip().splitlines():
        t = [x.strip() for x in z.split(",")]
        if len(t) > 4:
            gb += (float(re.sub(r"[^\d.]", "", t[4]) or 0)) / 1024
    return gb or 48.0


# ------------------------------------------------------------ Kopfzeile
# Die wichtigsten Werte fuer die Kopfzeile, knapp und fertig gerechnet --
# dieselbe Auswahl wie die Kaestchen in der Topbar des alten Cockpits (Netz,
# CPU, RAM, Last, Updates, Neustart, Sicherungen, Empfehlungen), dazu die
# Grafikkarten und der Strom. Der Browser fragt alle paar Sekunden, weil sich
# daran auch das Logo dreht; deshalb wird /status kurz gemerkt und die
# apt-Simulation NIE hier angestossen, sondern nur ihr letzter Stand gelesen.
_upd_task: asyncio.Task | None = None
_im_hintergrund: dict[str, asyncio.Task] = {}


async def _frisch_oder_alt(schluessel: str, sek: float, rechnen) -> Any:
    """Gemerkter Stand, sonst der zuletzt gemerkte (bis 2 Minuten alt) -- und im Hintergrund
    neu rechnen (19.10.2026, Veiko am Handy: "es dauert ewig"). Die Kopfzeile wird alle 3 bis
    6 s abgefragt; vorher wartete fast jeder Abruf auf den Statusdienst (0,7-1,5 s) oder auf
    die Prozessormessung (top, 0,7 s). Nur wenn es noch gar keinen Stand gibt, wird gewartet.
    rechnen: eine Funktion ohne Argumente, die einen Coroutine liefert und selbst merkt."""
    w = _gemerkt(schluessel, sek)
    if w is not None:
        return w
    e = _cache.get(schluessel)
    if e and time.time() - e["zeit"] < 120:
        t = _im_hintergrund.get(schluessel)
        if t is None or t.done():
            _im_hintergrund[schluessel] = asyncio.create_task(rechnen())
        return e["wert"]
    return await rechnen()


async def _status_kopf_rechnen() -> dict[str, Any] | None:
    return _merken("status_kopf", await status())


def _gpu_zeilen(s: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for z in str(s.get("gpu_nvidia") or "").strip().splitlines():
        t = [x.strip() for x in z.split(",")]
        if len(t) < 5:
            continue
        zahl = lambda x: float(re.sub(r"[^\d.]", "", x) or 0)  # noqa: E731
        out.append({"temp": int(zahl(t[1])), "last": int(zahl(t[2])),
                    "belegt_gb": round(zahl(t[3]) / 1024, 1), "gesamt_gb": round(zahl(t[4]) / 1024)})
    return out


def _dauer(seit: float | None) -> str:
    if not seit:
        return ""
    s = int(time.time() - seit)
    return f"seit {s} s" if s < 90 else f"seit {s // 60} Min."


_NAMEN = {"llama-server": "Ollama (Modell)", "ollama": "Ollama", "python3": "Python", "python": "Python",
          "apt": "Paketverwaltung", "apt-get": "Paketverwaltung", "dpkg": "Paketverwaltung", "rclone": "Sicherung (rclone)",
          "tar": "Sicherung (tar)", "docker": "Docker", "node": "Node"}


async def _prozessor_spitze() -> list[dict[str, Any]]:
    return await _frisch_oder_alt("prozessor_spitze", 10, _prozessor_spitze_rechnen)


async def _fremd_taetig() -> list[str]:
    return await _frisch_oder_alt("fremd_taetig", 15, _fremd_taetig_rechnen)


async def _prozessor_spitze_rechnen() -> list[dict[str, Any]]:
    """Die groessten Prozessorverbraucher JETZT (Veiko, 16.10.: "der Minisforum
    laeuft laut, aber die Anzeige sagt, es laeuft nichts" -- sie sah nur die
    Grafikkarten). top misst im ZWEITEN Durchgang ueber ein halbe Sekunde; der
    erste Durchgang zeigt Durchschnitte seit Prozessstart und luegt. 10 s gemerkt."""
    gemerkt = _gemerkt("prozessor_spitze", 10)
    if gemerkt is not None:
        return gemerkt
    try:
        p = await asyncio.create_subprocess_exec("top", "-b", "-n", "2", "-d", "0.5", "-o", "%CPU", "-w", "200",
                                                 stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        aus = (await asyncio.wait_for(p.communicate(), 8))[0].decode("utf-8", "replace")
    except (OSError, asyncio.TimeoutError):
        return _merken("prozessor_spitze", [])
    letzte = aus.split("PID USER")[-1].splitlines()[1:8]
    out = []
    for z in letzte:
        t = z.split()
        if len(t) >= 12:
            try:
                cpu = float(t[8].replace(",", "."))
            except ValueError:
                continue
            if cpu >= 50 and t[11] != "top":
                out.append({"name": _NAMEN.get(t[11], t[11]), "prog": t[11], "cpu": round(cpu)})
    return _merken("prozessor_spitze", out)


async def _fremd_taetig_rechnen() -> list[str]:
    """Was AUSSERHALB dieser Fassung auf denselben Karten rechnet: das alte
    Cockpit (eigene Pipeline) und ComfyUI. 15 Sekunden gemerkt -- die Kopfzeile
    fragt alle 3 bis 6 Sekunden, und beide Antworten aendern sich langsamer."""
    gemerkt = _gemerkt("fremd_taetig", 15)
    if gemerkt is not None:
        return gemerkt
    from .konfig import ALT_BACKEND, ALT_TOKEN
    zeilen: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            kopf_alt = {"X-Cockpit-Token": ALT_TOKEN} if ALT_TOKEN else {}
            st = (await c.get(f"{ALT_BACKEND}/api/vorgang/status", headers=kopf_alt)).json()
            if st.get("laeuft"):
                v = (await c.get(f"{ALT_BACKEND}/api/vorgang", headers=kopf_alt)).json()
                wer, was = v.get("laeuftWer") or "", v.get("laeuftWas") or ""
                zeilen.append("Altes Cockpit: " + (f"{wer} {was}".strip() or "die Vorgänge-Pipeline arbeitet"))
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            q = (await c.get("http://127.0.0.1:8188/queue")).json()
        n_lauf, n_warte = len(q.get("queue_running") or []), len(q.get("queue_pending") or [])
        if n_lauf:
            zeilen.append("ComfyUI erzeugt ein Bild oder Video" + (f", {n_warte} warten" if n_warte else ""))
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    return _merken("fremd_taetig", zeilen)


async def taetigkeit(gpu_last: float, geladen: list[str]) -> dict[str, Any]:
    """Zwei, drei Saetze: was das Cockpit gerade tut (Veiko, 16.10.: "aktuell
    laeuft etwas, aber ich sehe nicht, was es macht"). Nur Angaben, die es
    wirklich gibt; rechnen die Karten, ohne dass jemand bekannt ist, steht genau
    das da -- nicht geraten, wer es sein koennte."""
    from . import llm, medien, neo, stab
    zeilen: list[str] = []
    la = stab.ZUSTAND.get("laeuft")
    if la:
        v = db.holen("vorgaenge", la.get("vorgang_id") or "") if la.get("vorgang_id") else None
        zeilen.append(f"{stab.rollen_name(la['wer'])} {la.get('was') or 'arbeitet'}"
                      + (f" · Case „{v['titel']}“" if v else "") + f" · {_dauer(la.get('seit'))}")
    for t in list(llm.TAETIG.values()):
        zeilen.append(f"{t['was']} · {_dauer(t['seit'])}")
    for j in list(neo.JOBS.values()):
        if not j.get("fertig"):
            g = db.holen("gespraeche", j.get("gid") or "") or {}
            zeilen.append(f"Neo arbeitet" + (f" an „{g.get('titel')}“" if g.get("titel") else "") + f" · {_dauer(j.get('start'))}")
    for j in list(medien.JOBS.values()):
        if j.get("stand") == "laeuft":
            zeilen.append(f"Bild/Visualisierung „{j.get('titel') or ''}“ entsteht · {_dauer(j.get('start'))}")
    from . import video
    for eid in list(video.LAUFEND):
        e = db.holen("ergebnisse", eid) or {}
        vs = video.stand(e) or {}
        zeilen.append(f"Video „{e.get('titel') or eid}“: {vs.get('schritt') or 'rechnet'} · {_dauer(vs.get('start'))}")
    fremd = await _fremd_taetig()
    zeilen += fremd
    cpu = await _prozessor_spitze()
    eigene = bool(la or llm.TAETIG or llm.AKTIV["n"])
    for c in cpu[:2]:
        if c["prog"] == "llama-server" and not eigene and not fremd and gpu_last < 20:
            zeilen.append(f"Achtung: Ollama rechnet auf dem Prozessor ({c['cpu']} %), ohne dass ein Auftrag läuft -- "
                          "vermutlich hängt es. Abhilfe: unter System bei Ollama „Neu starten“.")
        elif not (c["prog"] == "llama-server" and (eigene or fremd)):
            zeilen.append(f"Prozessor des Mini-PCs: {c['name']} braucht gerade {c['cpu']} %"
                          + (" (mehrere Kerne)" if c["cpu"] > 100 else ""))
    if not zeilen and (llm.AKTIV["n"] or gpu_last >= 20):
        zeilen.append(f"Die Grafikkarten rechnen ({round(gpu_last)} %), aber nicht für einen bekannten Auftrag dieses Cockpits"
                      " (zum Beispiel ein Test oder ein Programm direkt auf dem Server).")
    if not zeilen:
        letzt = stab.ZUSTAND.get("letzter_lauf")
        zeilen.append("Ruht gerade." + (f" Letzter Durchgang des Teams {_dauer(letzt).replace('seit', 'vor')}." if letzt else ""))
    if geladen:
        zeilen.append("Im Grafikspeicher: " + ", ".join(geladen))
    return {"zeilen": zeilen[:4], "arbeitet": bool(la or llm.TAETIG or llm.AKTIV["n"] or fremd or cpu or gpu_last >= 20)}


async def kopf() -> dict[str, Any]:
    global _upd_task
    from . import llm, stab
    # Sofort mit dem letzten Stand, aufgefrischt im Hintergrund (_frisch_oder_alt, 19.10.2026).
    s = await _frisch_oder_alt("status_kopf", 4, _status_kopf_rechnen)
    upd = _gemerkt("updates", 600)
    if upd is None and (_upd_task is None or _upd_task.done()):
        # Beim ersten Mal im Hintergrund rechnen; der naechste Abruf hat es.
        _upd_task = asyncio.create_task(asyncio.to_thread(updates))
    jetzt = time.time()
    gpus = _gpu_zeilen(s or {})
    gpu_last = max((g["last"] for g in gpus), default=0)
    ki = {"aufrufe": llm.AKTIV["n"], "seit": llm.AKTIV["seit"], "gpu_last": gpu_last,
          # Auch das alte Cockpit und ComfyUI rechnen auf denselben Karten --
          # deshalb zaehlt die Kartenlast mit, nicht nur die eigenen Aufrufe.
          "arbeitet": llm.AKTIV["n"] > 0 or gpu_last >= 20}
    out: dict[str, Any] = {"zeit": jetzt, "status_da": bool(s), "ki": ki}
    out["taetigkeit"] = await taetigkeit(gpu_last, [str(x).split("|")[0] for x in ((s or {}).get("ollama_running") or [])])
    sich = sicherungen() or {}
    out["sicherungen"] = {k: {"alter_h": round((jetzt - float(x.get("zeit") or 0)) / 3600, 1) if x.get("zeit") else None,
                              "zustand": x.get("zustand")} for k, x in sich.items() if k in ("inhalt", "server", "neu") and isinstance(x, dict)}
    ges = stab.gesundheit()
    if upd is not None:
        e = empfehlungen(s, upd, _gemerkt("ollama_neu", 6 * 3600), sich or None, ges)
        try:   # nur der gemerkte Katalogstand -- die Kopfzeile fragt nie selbst die Registry
            from . import modellkatalog
            e += modellkatalog.vorschlaege(json.loads(modellkatalog.DATEI.read_text(encoding="utf-8")), _vram_gesamt(s))
        except (OSError, ValueError):
            pass
        try:
            from . import modellkatalog
            e += modellkatalog.neu_vorschlaege(json.loads(modellkatalog.NEU_DATEI.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        out["empfehlungen"] = {"achtung": sum(1 for x in e if x["stufe"] == "achtung"),
                               "einspielen": sum(1 for x in e if x["stufe"] == "einspielen"),
                               "titel": [x["titel"] for x in e if x["stufe"] in ("achtung", "einspielen")][:5]}
    if not s:
        return out
    h, n, m = s.get("host") or {}, s.get("network") or {}, s.get("memory_mb") or {}
    u, p = s.get("updates") or {}, s.get("power") or {}
    funk = str(n.get("interface") or "").startswith("wl")
    tempo = None
    if funk and (n.get("wlan") or {}).get("bitrate_mbit") is not None:
        tempo = f"{round(n['wlan']['bitrate_mbit'])} Mbit/s"
    elif not funk and n.get("lan_speed_mbit") is not None:
        mb = n["lan_speed_mbit"]
        tempo = f"{mb / 1000:g} GBit/s" if mb >= 1000 else f"{mb} Mbit/s"
    watt = [d.get("watt") for d in (p.get("server"), p.get("dock")) if isinstance(d, dict) and d.get("watt") is not None]
    out.update({
        "host": h.get("hostname"), "uptime": str(h.get("uptime") or "").replace("up ", "") or None,
        "netz": {"art": "WLAN" if funk else "LAN", "tempo": tempo} if n.get("interface") else None,
        "cpu_c": (s.get("temps_c") or {}).get("cpu"),
        "ram_p": round(m["used"] / m["total"] * 100) if m.get("total") else None,
        "last": round(float(h["load"][0]), 2) if h.get("load") else None,
        "kerne": (s.get("cpu") or {}).get("cores"),
        "gpus": gpus,
        "watt": round(sum(watt)) if watt else None,
        "updates": {"offen": u.get("pending"), "sicherheit": u.get("security"), "neustart": bool(u.get("reboot_required"))},
        "geladen": [str(x).split("|")[0] for x in (s.get("ollama_running") or [])],
    })
    return out


# ------------------------------------------------------------ Was laeuft auf welcher Karte
# vve-status meldet die Prozesse nur fuer beide Karten zusammen (das alte Cockpit
# sagte deshalb ehrlich "nicht nach Karte getrennt"). nvidia-smi kann es je Karte;
# ueber die Kommandozeile des Prozesses erkennen wir, WAS es ist: ein
# llama-server traegt die Modelldatei (-> Ollama-Modell ueber die Manifeste),
# ComfyUI startet main.py mit Port 8188, Whisper laeuft in einem der Cockpits.
OLLAMA_MANIFESTE = Path("/usr/share/ollama/.ollama/models/manifests/registry.ollama.ai/library")


def _blob_namen() -> dict[str, str]:
    g = _gemerkt("blob_namen", 600)
    if g is not None:
        return g
    namen: dict[str, str] = {}
    try:
        for f in OLLAMA_MANIFESTE.glob("*/*"):
            try:
                for l in json.loads(f.read_text(encoding="utf-8")).get("layers") or []:
                    if str(l.get("mediaType", "")).endswith(".model"):
                        namen[l["digest"].replace(":", "-")] = f"{f.parent.name}:{f.name}"
            except (OSError, ValueError, KeyError):
                continue
    except OSError:
        pass
    return _merken("blob_namen", namen)


def _was_ist(pid: int, name: str) -> dict[str, Any]:
    import os
    try:
        cmd = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        cmd = name
    if "llama-server" in cmd or "ollama" in cmd:
        m = re.search(r"blobs/(sha256-[0-9a-f]+)", cmd)
        ctx = re.search(r"\s-c\s+(\d+)", cmd)
        modell = _blob_namen().get(m.group(1)) if m else None
        return {"art": "ollama", "was": f"Ollama · {modell}" if modell else "Ollama (Modell unbekannt)", "modell": modell,
                "kontext": int(ctx.group(1)) if ctx else None}
    if "8188" in cmd or "ComfyUI" in cmd or "main.py" in cmd:
        return {"art": "comfy", "was": "ComfyUI (Bilder und Video)"}
    try:
        cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError:
        cwd = ""
    # Whisper rechnet im Prozess des jeweiligen Cockpits (faster-whisper auf der Karte).
    if pid == os.getpid() or ("server.py" in cmd and "vve-cp-r2" in (cwd + cmd)):
        return {"art": "whisper", "was": "Spracherkennung (Whisper) · neues Cockpit"}
    if "vvec_backend" in cmd or "uvicorn" in cmd or "/opt/vvec" in (cwd + cmd):
        return {"art": "whisper", "was": "Spracherkennung (Whisper) · altes Cockpit"}
    return {"art": "anderes", "was": name.rsplit("/", 1)[-1]}


def karten() -> list[dict[str, Any]]:
    busse = {}
    for z in _lauf(["nvidia-smi", "--query-gpu=index,pci.bus_id,name", "--format=csv,noheader"]).splitlines():
        t = [x.strip() for x in z.split(",")]
        if len(t) >= 2:
            busse[t[1]] = {"index": int(t[0]), "name": t[2] if len(t) > 2 else "", "prozesse": []}
    for z in _lauf(["nvidia-smi", "--query-compute-apps=gpu_bus_id,pid,process_name,used_memory",
                    "--format=csv,noheader,nounits"]).splitlines():
        t = [x.strip() for x in z.split(",")]
        if len(t) < 4 or t[0] not in busse:
            continue
        try:
            pid, mib = int(t[1]), int(float(t[3]))
        except ValueError:
            continue
        busse[t[0]]["prozesse"].append({"pid": pid, "mib": mib, **_was_ist(pid, t[2])})
    return sorted(busse.values(), key=lambda k: k["index"])


# ------------------------------------------------------------ Notabschaltung (ueber den WatchDog)
# Es gibt genau EINE Notabschaltung: den WatchDog-Dienst vve-health (Repo vve-cp,
# dienste/vve-health.py). Diese Fassung legt nur eine Anfrage in seinen
# Briefkasten -- eine ART, nie einen Befehl. Der Ablauf (Kill Switch: Dock und
# Server sofort aus, ohne Wiederanlauf; Safety Shutdown & Reboot: Dock aus,
# 90 s abkuehlen, Dock an, Server-Steckdose mit selbsttaetigem Wiederanlauf)
# steht nur dort. Eine zweite Kopie hier waere die gefaehrlichste Doppelung
# dieses ganzen Systems.
NOTFALL_ARTEN = ("kill", "neustart")


def notfall_anfordern(art: str) -> dict[str, Any]:
    from .konfig import HEALTH_DIR
    if art not in NOTFALL_ARTEN:
        raise ValueError("Unbekannte Art")
    if not HEALTH_DIR.is_dir():
        raise RuntimeError(f"WatchDog-Ordner {HEALTH_DIR} fehlt -- laeuft vve-health?")
    ziel = HEALTH_DIR / "notfall-anfrage.json"
    tmp = ziel.with_suffix(".tmp")
    jetzt = time.time()
    tmp.write_text(json.dumps({"angefordert_um": jetzt, "art": art}), encoding="utf-8")
    tmp.replace(ziel)
    return {"ok": True, "angefordert_um": jetzt}


def watchdog() -> dict[str, Any]:
    from .konfig import HEALTH_DIR
    try:
        st = json.loads((HEALTH_DIR / "health-status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"bekannt": False}
    try:
        anfrage = json.loads((HEALTH_DIR / "notfall-anfrage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        anfrage = None
    offen = bool(anfrage and float(anfrage.get("angefordert_um") or 0) > float(st.get("letzte_anfrage_verarbeitet") or 0))
    return {"bekannt": True, **st, "alter_sek": round(time.time() - float(st.get("zeit") or 0)),
            "anfrage_offen": offen, "anfrage": anfrage}
