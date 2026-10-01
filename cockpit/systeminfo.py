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
        return json.loads((ALT_DATEN / "sicherung-status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


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
        e.append({"stufe": "einspielen", "titel": f"Ollama {ollama_neu} verfügbar (läuft: {laufend.replace('Ollama ', '')})",
                  "warum": "Neuere Modelle lassen sich mit einer alten Fassung oft nicht laden. Lokale Modelle sind während des Updates einige Minuten nicht erreichbar. Braucht dein Passwort, deshalb als Befehl; am besten in tmux, damit ein Verbindungsabbruch nichts zerreißt.",
                  "befehl": "tmux new -s ollama\ncurl -fsSL https://ollama.com/install.sh -o /tmp/ollama-install.sh && sudo sh /tmp/ollama-install.sh"})
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
    platte = s.get("disk_gb") or {}
    if platte.get("total") and platte.get("free", 0) / platte["total"] < 0.1:
        e.append({"stufe": "achtung", "titel": f"Platte fast voll ({round(platte['free'])} GB frei)", "warum": "Unter zehn Prozent frei. Große Modelle oder ComfyUI-Ausgaben aufräumen."})
    for i, z in enumerate(str(s.get("gpu_nvidia") or "").strip().splitlines()):
        teile = [t.strip() for t in z.split(",")]
        if len(teile) > 1 and teile[1].isdigit() and int(teile[1]) >= 80:
            e.append({"stufe": "achtung", "titel": f"Grafikkarte {i + 1} heiß: {teile[1]} °C", "warum": "Ab 90 °C greift der WatchDog mit dem Notfallablauf. Lüftung und Docks prüfen."})
    if stab_ges.get("sync") and jetzt - stab_ges["sync"] > 1800:
        e.append({"stufe": "achtung", "titel": "Plaud-Abruf hängt", "warum": "Seit über einer halben Stunde kein erfolgreicher Abruf. Häufigste Ursache: Anmeldung bei Plaud abgelaufen (Anleitung im alten Repo, ANLEITUNG.md)."})
    sicher = s.get("sicherheit") or {}
    if (sicher.get("ufw") or {}).get("offene_regeln"):
        e.append({"stufe": "achtung", "titel": "Firewall: Regel für alle offen", "warum": "Eine ufw-Regel erlaubt Zugriff aus dem ganzen Internet statt nur aus dem Tailnet: " + ", ".join(map(str, sicher["ufw"]["offene_regeln"]))})
    for name, t in (s.get("timers") or {}).items():
        if name.startswith("vvec-backup"):
            continue
        if t.get("geladen") and t.get("aktiv") != "active":
            e.append({"stufe": "achtung", "titel": f"Zeitgeber {name} läuft nicht", "warum": f"Stand: {t.get('aktiv')}. Was er anstößt, passiert gerade nicht."})
    for c in s.get("docker") or []:
        name, _, zustand = str(c).partition("|")
        if not zustand.startswith("Up"):
            e.append({"stufe": "achtung", "titel": f"Container {name} läuft nicht", "warum": f"Stand: {zustand}.", "befehl": f"docker start {name}"})
    reihen = {"achtung": 0, "einspielen": 1, "nicht": 2, "info": 3}
    return sorted(e, key=lambda x: reihen.get(x["stufe"], 9))


# ------------------------------------------------------------ Auftraege (apt, Neustart)
AUFTRAG: dict[str, Any] = {"art": None, "laeuft": False, "log": "", "rc": None, "start": None, "ende": None}


async def _ausfuehren(befehle: list[list[str]]) -> None:
    AUFTRAG.update(laeuft=True, log="", rc=None, start=time.time(), ende=None)
    rc = 0
    for b in befehle:
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
        if rc != 0:
            if "a password is required" in AUFTRAG["log"]:
                AUFTRAG["log"] += "\nsudo verlangt ein Passwort: dieser Befehl ist für vveadmin nicht ohne Passwort freigegeben.\n"
            break
    AUFTRAG.update(laeuft=False, rc=rc, ende=time.time())
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


async def gesamt(frisch: bool = False) -> dict[str, Any]:
    from . import stab
    s = await status()
    upd = await asyncio.to_thread(updates, frisch)
    neu = await ollama_neueste()
    sich = sicherungen()
    from . import modellkatalog
    try:
        katalog = await modellkatalog.pruefen(frisch)
    except Exception:  # noqa: BLE001 -- ohne Netz zur Registry bleibt der Rest der Seite heil
        katalog = None
    e = empfehlungen(s, upd, neu, sich, stab.gesundheit()) + modellkatalog.vorschlaege(katalog, _vram_gesamt(s))
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


async def kopf() -> dict[str, Any]:
    global _upd_task
    from . import llm, stab
    s = _gemerkt("status_kopf", 4)
    if s is None:
        s = _merken("status_kopf", await status())
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
    sich = sicherungen() or {}
    out["sicherungen"] = {k: {"alter_h": round((jetzt - float(x.get("zeit") or 0)) / 3600, 1) if x.get("zeit") else None,
                              "zustand": x.get("zustand")} for k, x in sich.items() if k in ("inhalt", "server") and isinstance(x, dict)}
    ges = stab.gesundheit()
    if upd is not None:
        e = empfehlungen(s, upd, _gemerkt("ollama_neu", 6 * 3600), sich or None, ges)
        try:   # nur der gemerkte Katalogstand -- die Kopfzeile fragt nie selbst die Registry
            from . import modellkatalog
            e += modellkatalog.vorschlaege(json.loads(modellkatalog.DATEI.read_text(encoding="utf-8")), _vram_gesamt(s))
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
