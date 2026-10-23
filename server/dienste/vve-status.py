#!/usr/bin/env python3
"""VVE-STATUS — Hardware- und Dienstetelemetrie als JSON auf 127.0.0.1:9099.

Liegt auf dem Server unter /usr/local/bin/vve-status.py und wird von der
Server-Sektion des Cockpits gelesen (Route /status in Caddy).

WARUM DIE DATEI JETZT IM REPO LIEGT: Sie tat es lange nicht. Damit
existierten 157 Zeilen, von denen die halbe Server-Ansicht abhaengt,
genau einmal — unversioniert und ausserhalb jeder Sicherung
(vvec-backup.sh erfasst /var/lib/vvec, /etc/vvec, /etc/caddy und
/srv/www, nicht /usr/local/bin). Ein Plattenschaden haette das Cockpit
laufen lassen und die Telemetrie stumm.
"""
import json, subprocess, os, re, shutil, glob, time, socket, urllib.error, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

def sh(c, t=15):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=t).stdout.strip()
    except Exception:
        return ""


COMFY_ORTE = [
    os.path.expanduser("~/comfyui-daten/ComfyUI/models"),
    os.path.expanduser("~/comfy-models"),
]
for _heim in glob.glob("/home/*"):
    for _kandidat in (os.path.join(_heim, "comfyui-daten", "ComfyUI", "models"),
                       os.path.join(_heim, "comfy-models")):
        if _kandidat not in COMFY_ORTE:
            COMFY_ORTE.append(_kandidat)
COMFY_ORDNER = ["diffusion_models", "checkpoints", "unet", "video"]


def comfy_ordner_liste():
    """Welche Unterordner es unter ComfyUI/models WIRKLICH gibt.

    Anlass (10.09.2026): Neo empfahl fuer ein neues Videomodell den Pfad
    models/videos/ (Plural) -- den gibt es nicht, das echte Videomodell
    (HunyuanVideo) liegt in diffusion_models/. Neo hatte dafuer keine
    Grundlage ausser Raten, weil comfy_modelle() nur Dateinamen samt
    Groesse zurueckgab, nie die Ordnerstruktur. Diese Liste schliesst die
    Luecke, und zwar dauerhaft: sie liest bei JEDEM /status-Abruf frisch
    vom Server, veraltet also nicht wie ein einmal aufgeschriebener Satz.
    """
    for ort in COMFY_ORTE:
        if os.path.isdir(ort):
            try:
                return sorted(n for n in os.listdir(ort)
                               if os.path.isdir(os.path.join(ort, n)))
            except OSError:
                continue
    return []


def comfy_modelle():
    raus, gesehen = [], set()
    for ort in COMFY_ORTE:
        for ordner in COMFY_ORDNER:
            muster = os.path.join(ort, ordner, "**", "*")
            try:
                for pfad in glob.glob(muster, recursive=True):
                    if not os.path.isfile(pfad):
                        continue
                    if not pfad.lower().endswith((".safetensors", ".ckpt", ".gguf", ".pt")):
                        continue
                    name = os.path.basename(pfad)
                    if name in gesehen:
                        continue
                    gesehen.add(name)
                    gb = os.path.getsize(pfad) / (1024 ** 3)
                    if gb < 1.0:
                        continue
                    raus.append("%s|%.1fGB" % (name, gb))
            except OSError:
                continue
    return sorted(raus)


ZEITGEBER = [
    "vvec-plaud-sync.timer",
    "vvec-vorgang.timer",
    "vvec-board.timer",
    "vvec-suche-index.timer",
    "vvec-sicherung-inhalt.timer",
    "vvec-sicherung-server.timer",
    "vvec-backup.timer",
]


def zeitgeber():
    roh = sh("systemctl show " + " ".join(ZEITGEBER) +
             " --timestamp=unix"
             " -p Id -p LoadState -p ActiveState -p LastTriggerUSec"
             " -p NextElapseUSecRealtime -p NextElapseUSecMonotonic", 8)
    aus = {}
    for block in roh.split("\n\n"):
        kv = {}
        for zeile in block.splitlines():
            if "=" in zeile:
                k, _, v = zeile.partition("=")
                kv[k.strip()] = v.strip()
        uid = kv.get("Id")
        if not uid:
            continue

        def zeit(name):
            v = kv.get(name, "").strip().lstrip("@")
            if not v or v in ("n/a", "0"):
                return None
            try:
                return int(v)
            except ValueError:
                return None

        mono = kv.get("NextElapseUSecMonotonic", "").strip()
        aus[uid] = {
            "geladen": kv.get("LoadState") == "loaded",
            "aktiv": kv.get("ActiveState") or None,
            "zuletzt": zeit("LastTriggerUSec"),
            "naechster": zeit("NextElapseUSecRealtime"),
            "abstand": bool(mono and mono not in ("0", "n/a")),
        }
    return aus


_fassungen = {"wann": 0.0, "geholt": False, "wert": {}}
FASSUNG_TTL = 900


def _programm_stempel():
    """Aenderungszeit der Ollama-Programmdatei — billig (ein stat).

    Die Fassungen sind 15 Minuten gemerkt. Nach einem Ollama-Update aus dem
    Cockpit hiess das: die Empfehlung "Ollama ist veraltet" blieb bis zu
    15 Minuten stehen, obwohl die neue Fassung laengst lief — und wurde
    deshalb ein zweites Mal angeklickt (30.09.2026). Aendert sich die
    Datei, wird sofort neu gefragt.
    """
    try:
        return os.stat("/usr/local/bin/ollama").st_mtime
    except OSError:
        return None


def fassungen():
    stempel = _programm_stempel()
    if (_fassungen["geholt"] and time.time() - _fassungen["wann"] < FASSUNG_TTL
            and _fassungen.get("stempel") == stempel):
        return _fassungen["wert"]

    def kurz(befehl, name, muster):
        m = re.search(muster, sh(befehl, 8))
        return f"{name} {m.group(1)}" if m else ""

    w = {
        "ollama": kurz("ollama --version 2>/dev/null", "Ollama",
                       r"([0-9]+\.[0-9][0-9.]*)"),
        "docker": kurz("docker --version 2>/dev/null", "Docker",
                       r"([0-9]+\.[0-9][0-9.]*)"),
        "caddy": kurz("caddy version 2>/dev/null", "Caddy",
                      r"v?([0-9]+\.[0-9][0-9.]*)"),
        "python": kurz("python3 --version", "Python",
                       r"([0-9]+\.[0-9][0-9.]*)"),
    }
    _fassungen["wert"] = {k: v for k, v in w.items() if v}
    _fassungen["wann"] = time.time()
    _fassungen["geholt"] = True
    _fassungen["stempel"] = stempel
    return _fassungen["wert"]


_ollama_conf = {"wann": 0.0, "geholt": False, "wert": {}}


def ollama_conf():
    """Die WIRKSAMEN Einstellungen des Ollama-Dienstes.

    Nicht aus der override.conf gelesen, sondern von systemd erfragt:
    die Datei ist nur eine von mehreren moeglichen Quellen (Unit,
    Drop-ins, Umgebung des Dienstes), und wer die Datei liest, liest
    einen Wunsch — nicht das, was der laufende Dienst tatsaechlich
    bekommen hat. Genau dieser Unterschied ist hier der Punkt: das
    Cockpit soll sagen koennen, wie gross das Kontextfenster WIRKLICH
    ist, und nicht, was irgendwo eingetragen wurde.

    Aendert sich nur bei einem Neustart von ollama, deshalb dieselbe
    Viertelstunde Gedaechtnis wie bei den Fassungen — der Aufruf kostet
    einen Unterprozess, der Statustakt liegt bei 20 Sekunden.
    """
    if _ollama_conf["geholt"] and time.time() - _ollama_conf["wann"] < FASSUNG_TTL:
        return _ollama_conf["wert"]
    roh = sh("systemctl show ollama -p Environment", 8)
    aus = {}
    # "Environment=PATH=… OLLAMA_FLASH_ATTENTION=1 OLLAMA_CONTEXT_LENGTH=16384"
    for stueck in roh.partition("=")[2].split():
        k, _, v = stueck.partition("=")
        if k.startswith("OLLAMA_"):
            aus[k] = v
    _ollama_conf["wert"] = aus
    _ollama_conf["wann"] = time.time()
    _ollama_conf["geholt"] = True
    return aus


def ollama_laeuft():
    """Was gerade im Speicher liegt — mit Prozessor und Kontextlaenge.

    Das bestehende Feld ollama_running bleibt unveraendert, obwohl beide
    aus derselben Zeile stammen: es wird an fuenf Stellen im Cockpit
    ausgewertet, und sein Format ("name|100%") dort umzustellen haette
    jede davon anfassen muessen. Ein zweites, ausdrueckliches Feld kostet
    nichts (dieselbe eine Ausgabe wird zweimal gelesen) und kann sagen,
    was wirklich interessiert:

      prozessor  "100% GPU" oder "1%/99% CPU/GPU". Steht ein Anteil auf
                 CPU, liegt ein Teil des Modells im RAM — das ist der
                 haeufigste Grund fuer "es antwortet ploetzlich zaeh".
      kontext    die Fenstergroesse, mit der DIESES Modell geladen wurde.
                 Die Einstellung des Dienstes ist eine Vorgabe; was
                 wirklich gilt, steht hier.
    """
    raus = []
    for zeile in sh("ollama ps | tail -n +2").splitlines():
        f = zeile.split()
        # NAME ID SIZE EINHEIT PROZESSOR[ ZUSATZ] KONTEXT UNTIL...
        if len(f) < 6:
            continue
        rest = f[4:]
        prozessor = rest[0]
        if len(rest) > 1 and not rest[1].isdigit():
            prozessor += " " + rest[1]
            rest = rest[1:]
        kontext = rest[1] if len(rest) > 1 and rest[1].isdigit() else ""
        raus.append({"name": f[0], "groesse": f[2] + " " + f[3],
                     "prozessor": prozessor,
                     "kontext": int(kontext) if kontext else None})
    return raus


def temps(sj):
    def g(chip, key, sub=None):
        try:
            v = sj[chip][key]
            if sub: return round(v[sub], 1)
            return round(list(v.values())[0], 1)
        except Exception:
            return None
    def find(prefix):
        for k in sj:
            if k.startswith(prefix): return k
        return ""
    ram = []
    for k in sj:
        if k.startswith("spd5118"):
            t = g(k, "temp1")
            if t: ram.append(t)
    return {
        "cpu": g(find("k10temp"), "Tctl"),
        "igpu": g(find("amdgpu"), "edge"),
        "nvme": g(find("nvme"), "Composite"),
        "board": g(find("acpitz"), "temp1"),
        "wifi": g(find("mt7925"), "temp1"),
        "ram_avg": round(sum(ram)/len(ram), 1) if ram else None,
    }

def igpu(sj):
    for k in sj:
        if k.startswith("amdgpu"):
            c = sj[k]
            def v(key):
                try: return round(list(c[key].values())[0], 1)
                except Exception: return None
            return {"power_w": v("PPT"), "clock_mhz": (v("sclk")/1e6 if v("sclk") else None), "temp_c": v("edge")}
    return {}


# Strom an der Steckdose. Layer liest power.server und power.dock.
# Namen wie in der Shelly-App: MINISFORUM am Mini-PC, RTXeGPU am Dock.
# RPC: http://<name>.local/rpc/Switch.GetStatus?id=0
# IP in VVEC_SHELLY_* sticht, falls .local nicht aufloest.
# Keine geschaetzten Watt.
STROM_TTL = 15
STROM_TIMEOUT = 1.2
_strom = {"wann": 0.0, "wert": None}
_vvec_env_cache = {"geholt": False, "wert": {}}


def _vvec_env():
    if _vvec_env_cache["geholt"]:
        return _vvec_env_cache["wert"]
    aus = {}
    try:
        with open("/etc/vvec/vvec.env", encoding="utf-8") as f:
            for zeile in f:
                zeile = zeile.strip()
                if not zeile or zeile.startswith("#") or "=" not in zeile:
                    continue
                k, _, v = zeile.partition("=")
                aus[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    _vvec_env_cache["wert"] = aus
    _vvec_env_cache["geholt"] = True
    return aus


def _strom_ziel(schluessel, vorgabe):
    env = os.environ.get(schluessel, "").strip()
    if env:
        return env
    datei = _vvec_env().get(schluessel, "").strip()
    return datei or vorgabe


def _ist_adresse(wert):
    if not wert:
        return False
    try:
        socket.inet_pton(socket.AF_INET, wert)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, wert)
        return True
    except OSError:
        return False


# IPs aus der Shelly-App, WLAN R-Vnet-FR. .local braucht Avahi;
# ohne das wuerde der Dienst den Namen kennen und trotzdem nichts lesen.
_SHELLY_IP = {
    "MINISFORUM": "192.168.178.159",
    "RTXeGPU": "192.168.178.161",
}


def _hosts_fuer(eintrag):
    eintrag = (eintrag or "").strip()
    if not eintrag:
        return []
    if _ist_adresse(eintrag):
        return [eintrag]
    if "." in eintrag:
        return [eintrag]
    aus = [eintrag + ".local", eintrag]
    ip = _SHELLY_IP.get(eintrag)
    if ip and ip not in aus:
        aus.append(ip)
    return aus


def _zahl(wert):
    if wert is None or wert == "":
        return None
    try:
        return round(float(wert), 1)
    except (TypeError, ValueError):
        return None


def _shelly_lesen(host):
    url = "http://%s/rpc/Switch.GetStatus?id=0" % host
    try:
        with urllib.request.urlopen(url, timeout=STROM_TIMEOUT) as ant:
            roh = json.loads(ant.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return None, "%s antwortet HTTP %s" % (host, e.code)
    except urllib.error.URLError as e:
        grund = e.reason if e.reason else e
        return None, "%s nicht erreichbar (%s)" % (host, grund)
    except (TimeoutError, socket.timeout):
        return None, "%s antwortet nicht (Zeit)" % host
    except (ValueError, json.JSONDecodeError):
        return None, "%s liefert kein JSON" % host
    except OSError as e:
        return None, "%s nicht erreichbar (%s)" % (host, e)
    if not isinstance(roh, dict):
        return None, "%s liefert kein Objekt" % host
    watt = _zahl(roh.get("apower"))
    if watt is None:
        return None, "%s ohne apower" % host
    aenergy = roh.get("aenergy") or {}
    wh = _zahl(aenergy.get("total") if isinstance(aenergy, dict) else None)
    temp = roh.get("temperature") or {}
    tc = _zahl(temp.get("tC") if isinstance(temp, dict) else None)
    aus = {"watt": watt, "host": host}
    if wh is not None:
        aus["kwh"] = round(wh / 1000.0, 3)
    volt = _zahl(roh.get("voltage"))
    if volt is not None:
        aus["volt"] = volt
    if tc is not None:
        aus["temp_c"] = tc
    return aus, None


def _stecker(name):
    letzte = None
    for host in _hosts_fuer(name):
        wert, grund = _shelly_lesen(host)
        if wert:
            wert["name"] = name
            return wert
        letzte = grund
    return {"name": name, "grund": letzte or ("%s nicht gesetzt" % name)}


# Netzwerk: welche Verbindung gerade traegt und mit welcher Geschwindigkeit.
# "interface" ist die Karte auf dem Weg der Default-Route — bei einem
# Server, der zwischen Kabel und WLAN wechselt, ist immer nur eine davon
# tatsaechlich aktiv, die andere zeigt NO-CARRIER. Deshalb wird nur diese
# eine genauer nachgefragt statt aller vorhandenen Interfaces.
def netzwerk():
    interface = sh("ip route get 1.1.1.1 | awk '{print $5; exit}'")
    aus = {
        "lan_ip": sh("hostname -I | awk '{print $1}'"),
        "tailscale_ip": sh("tailscale ip -4 2>/dev/null | head -1"),
        "interface": interface,
    }
    # Name kommt vom Kernel (ip route), nicht von aussen — die Pruefung ist
    # trotzdem billig zu haben und verhindert, dass ein unerwartetes
    # Zeichen in einem Shell-Kommando landet.
    if not re.fullmatch(r"[A-Za-z0-9_.@-]+", interface or ""):
        return aus
    if interface.startswith("wl"):
        iwout = sh("iw dev " + interface + " link 2>/dev/null")
        ssid = re.search(r"SSID:\s*(.+)", iwout)
        signal = re.search(r"signal:\s*(-?\d+)", iwout)
        bitrate = re.search(r"tx bitrate:\s*([\d.]+)", iwout, re.IGNORECASE)
        aus["wlan"] = {
            "ssid": ssid.group(1).strip() if ssid else None,
            "signal_dbm": int(signal.group(1)) if signal else None,
            "bitrate_mbit": float(bitrate.group(1)) if bitrate else None,
        }
    else:
        speed = sh("cat /sys/class/net/" + interface + "/speed 2>/dev/null")
        try:
            aus["lan_speed_mbit"] = int(speed)
        except ValueError:
            aus["lan_speed_mbit"] = None
    return aus


def power():
    jetzt = time.time()
    if _strom["wert"] is not None and jetzt - _strom["wann"] < STROM_TTL:
        return _strom["wert"]
    wert = {
        "server": _stecker(_strom_ziel("VVEC_SHELLY_SERVER", "MINISFORUM")),
        "dock": _stecker(_strom_ziel("VVEC_SHELLY_DOCK", "RTXeGPU")),
    }
    _strom["wert"] = wert
    _strom["wann"] = jetzt
    return wert


# ---------------------------------------------------------------------------
# FIRMWARE — gibt es Firmware- oder BIOS-Updates fuer die Bauteile?
#
# Veikos Wunsch (28.09.2026): die Empfehlungen sollen auch das pruefen,
# nicht nur apt. Drei Quellen, weil es keine gibt, die alles kennt:
#
# 1. fwupd (LVFS) — Ubuntus Firmware-Dienst. Kennt hier: System-Firmware
#    (BIOS), die Kingston-NVMe, die Secure-Boot-Datenbanken (dbx, KEK …).
#    `get-updates` braucht KEIN root; es liest die Metadaten, die
#    fwupd-refresh.timer ohnehin taeglich holt.
# 2. Die Shelly-Steckdosen (Shelly.CheckForUpdate, eigenes Netz, keine
#    Cloud) — sie sind Bauteile des Aufbaus wie jedes andere.
# 3. Was sich NICHT pruefen laesst, wird mit dem Ist-Stand gemeldet statt
#    verschwiegen: das VBIOS der RTX 3090 (NVIDIA/Kartenhersteller, kein
#    LVFS) und das BIOS, falls MINISFORUM eine Fassung nur auf der eigenen
#    Website veroeffentlicht. "Keine Updates" waere dort eine Behauptung,
#    die dieser Dienst gar nicht belegen kann.
#
# Im HINTERGRUND gerechnet, nicht im Anfragepfad: fwupdmgr braucht einige
# Sekunden, und /status wird alle 20 s von jedem offenen Cockpit gefragt.
# Gemerkt wird sechs Stunden — Firmware erscheint nicht im Minutentakt.
# ---------------------------------------------------------------------------
FIRMWARE_TTL = 6 * 3600
_firmware = {"wann": 0.0, "wert": None, "laeuft": False}


def _fw_rechnen():
    aus = {"zeit": time.time(), "fwupd": {}, "shelly": [], "bios": {}, "gpu_vbios": []}

    # Secure Boot an oder aus? Entscheidet, ob Updates der Secure-Boot-
    # Datenbanken (dbx, KEK, db, PK) ueberhaupt etwas bewirken. Gefunden am
    # 28.09.2026: das dbx-Update lief "erfolgreich", nach dem Neustart meldete
    # fwupd "expected 20260707 and got 20230501" — die Firmware uebernimmt es
    # nicht, und bei ausgeschaltetem Secure Boot liest die Sperrliste ohnehin
    # niemand. Die Empfehlung kam nach jedem Neustart wieder.
    sb = sh("mokutil --sb-state 2>/dev/null", 10).lower()
    aus["secure_boot"] = ("an" if "enabled" in sb else
                          "aus" if "disabled" in sb else None)

    # Letzter gescheiterter Versuch je Geraet aus dem fwupd-Verlauf.
    verlauf = {}
    try:
        r = subprocess.run(["fwupdmgr", "get-history", "--json"],
                           capture_output=True, text=True, timeout=60)
        roh = r.stdout
        anfang = roh.find("{")
        if anfang >= 0:
            # raw_decode statt loads: fwupdmgr haengt je nach Fassung nach
            # dem JSON noch Text an ("Extra data" beim ersten Versuch).
            daten, _ = json.JSONDecoder().raw_decode(roh[anfang:])
            for g in daten.get("Devices", []) or []:
                gid = str(g.get("DeviceId") or "")
                rel = (g.get("Releases") or [{}])[0]
                fehler = g.get("UpdateError") or ""
                zustand = g.get("UpdateState")
                if gid and (fehler or zustand in (3, 5, "failed", "failed-transient")):
                    verlauf[gid] = {"fehler": str(fehler)[:300],
                                    "fassung": rel.get("Version") or ""}
    except Exception:
        pass

    # 1. fwupd
    try:
        r = subprocess.run(
            ["fwupdmgr", "get-updates", "--json", "--no-unreported-check",
             "--no-metadata-check"],
            capture_output=True, text=True, timeout=120)
        roh = r.stdout.strip()
        # rc 2 ohne Ausgabe heisst bei fwupdmgr "nichts zu tun", kein Fehler.
        daten = json.loads(roh) if roh.startswith("{") else {"Devices": []}
        updates = []
        for g in daten.get("Devices", []) or []:
            rel = (g.get("Releases") or [])
            if not rel:
                continue
            neu = rel[0]            # fwupd sortiert die neueste nach vorn
            flags = g.get("Flags") or []
            gid = str(g.get("DeviceId") or "")
            if not re.fullmatch(r"[0-9a-f]{40}", gid):
                continue
            plugin = g.get("Plugin") or ""
            eintrag = {
                "id": gid,
                "name": g.get("Name") or "?",
                "hersteller": g.get("Vendor") or "",
                "version": g.get("Version") or "",
                "neu": neu.get("Version") or "",
                "was": neu.get("Summary") or "",
                "dringlichkeit": neu.get("Urgency") or "",
                "neustart": "needs-reboot" in flags,
                "plugin": plugin,
                # uefi_capsule ist das BIOS selbst und gehoert NICHT dazu.
                "secure_boot_db": plugin in ("uefi_dbx", "uefi_kek", "uefi_db", "uefi_pk"),
            }
            v = verlauf.get(gid)
            if v and (not v["fassung"] or v["fassung"] == eintrag["neu"]):
                eintrag["gescheitert"] = v
            updates.append(eintrag)
        aus["fwupd"] = {"ok": True, "updates": updates}
    except FileNotFoundError:
        aus["fwupd"] = {"ok": False, "grund": "fwupdmgr ist nicht installiert"}
    except Exception as e:
        aus["fwupd"] = {"ok": False, "grund": str(e)[:200]}

    # 2. Shelly-Steckdosen — initial_state gleich mit, weil er darueber
    # entscheidet, ob ein Update der Dose den Strom dahinter abschaltet.
    for schluessel, vorgabe, rolle in (("VVEC_SHELLY_SERVER", "MINISFORUM", "server"),
                                       ("VVEC_SHELLY_DOCK", "RTXeGPU", "dock")):
        name = _strom_ziel(schluessel, vorgabe)
        eintrag = {"rolle": rolle, "name": name}
        for host in _hosts_fuer(name):
            try:
                with urllib.request.urlopen("http://%s/rpc/Shelly.GetDeviceInfo" % host,
                                            timeout=3) as a:
                    info = json.loads(a.read().decode("utf-8", "replace"))
                with urllib.request.urlopen("http://%s/rpc/Shelly.CheckForUpdate" % host,
                                            timeout=8) as a:
                    upd = json.loads(a.read().decode("utf-8", "replace"))
                try:
                    with urllib.request.urlopen(
                            "http://%s/rpc/Switch.GetConfig?id=0" % host, timeout=3) as a:
                        cfg = json.loads(a.read().decode("utf-8", "replace"))
                except Exception:
                    cfg = {}
                eintrag.update({
                    "host": host,
                    "modell": info.get("model") or "",
                    "version": info.get("ver") or "",
                    "neu": ((upd.get("stable") or {}).get("version") or ""),
                    "einschalten_nach_neustart": cfg.get("initial_state"),
                })
                eintrag.pop("grund", None)
                break
            except Exception as e:
                eintrag["grund"] = "%s: %s" % (host, str(e)[:120])
        aus["shelly"].append(eintrag)

    # 3. Ist-Staende ohne Update-Quelle
    def dmi(n):
        try:
            with open("/sys/class/dmi/id/" + n, encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return ""
    aus["bios"] = {"version": dmi("bios_version"), "datum": dmi("bios_date"),
                   "board": dmi("board_name"), "hersteller": dmi("sys_vendor")}
    for z in sh("nvidia-smi --query-gpu=name,vbios_version --format=csv,noheader "
                "2>/dev/null", 10).splitlines():
        teile = [t.strip() for t in z.split(",")]
        if len(teile) >= 2:
            aus["gpu_vbios"].append({"name": teile[0], "vbios": teile[1]})
    return aus


def _fw_hintergrund():
    try:
        _firmware["wert"] = _fw_rechnen()
        _firmware["wann"] = time.time()
    finally:
        _firmware["laeuft"] = False


def firmware():
    """Letzter Firmware-Stand; stoesst bei Bedarf eine Neuberechnung an.
    Solange noch keine fertig ist, steht das ausdruecklich da ("pruefe")."""
    import threading
    # Nach einem Firmware-Lauf aus dem Cockpit SOFORT neu pruefen, nicht erst
    # nach sechs Stunden. Gefunden am 28.09.2026: das dbx-Update lief sauber
    # durch, die Empfehlung stand aber weiter da — Veiko klickte erneut, und
    # der zweite Lauf meldete "fehlgeschlagen", weil es nichts mehr zu tun gab.
    # Der alte Stand wird dabei verworfen statt weiter angezeigt: bis die
    # neue Pruefung fertig ist (eine halbe Minute), steht "wird geprueft" da
    # — ehrlicher als ein Knopf fuer ein Update, das schon eingespielt ist.
    try:
        laeufe = glob.glob("/var/lib/vvec/wartung/lauf/firmware-*.stand")
        juengster = max((os.path.getmtime(p) for p in laeufe), default=0)
    except OSError:
        juengster = 0
    if juengster > _firmware["wann"] and not _firmware["laeuft"]:
        _firmware["wann"] = 0.0
        _firmware["wert"] = None
    if (not _firmware["laeuft"] and
            time.time() - _firmware["wann"] > FIRMWARE_TTL):
        _firmware["laeuft"] = True
        threading.Thread(target=_fw_hintergrund, daemon=True).start()
    if _firmware["wert"] is None:
        return {"pruefe": True}
    return dict(_firmware["wert"], pruefe=_firmware["laeuft"])


def gesundheit():
    """Stand des Health-Watchdogs (vve-health.py) — reine Anzeige, dieser
    Dienst hier schreibt nichts hinein, nur der Watchdog selbst. Fehlt die
    Datei (Watchdog laeuft nicht oder ist auf einem aelteren Serverstand
    noch nicht ausgeliefert), wird das ehrlich als "unbekannt" gemeldet
    statt "alles in Ordnung" vorzutaeuschen."""
    # Nicht /var/lib/vvec — derselbe Grund wie in vve-health.py: der
    # Watchdog laeuft als vveadmin und hat dort keinen Schreibzugriff
    # (755, vvec:vvec). Beide Dienste laufen zufaellig als derselbe
    # Nutzer (auch dieser hier: User=vveadmin), das Home-Verzeichnis
    # reicht also fuer beide Seiten.
    try:
        pfad = os.path.join(os.getenv("VVEC_HEALTH_DIR", os.path.expanduser("~/vve-health")),
                             "health-status.json")
        with open(pfad, encoding="utf-8") as f:
            stand = json.load(f)
    except (OSError, ValueError):
        return {"bekannt": False}
    stand["bekannt"] = True
    stand["alter_sek"] = round(time.time() - stand.get("zeit", 0), 1) if stand.get("zeit") else None
    return stand


def sicherheit():
    """Stand von vve-sicherheit.py (Firewall-Drift, fail2ban, fehlgeschlagene
    Anmeldungen) — dieselbe Ablage und dasselbe "ehrlich unbekannt statt
    falsch beruhigt"-Prinzip wie gesundheit()."""
    try:
        pfad = os.path.join(os.getenv("VVEC_HEALTH_DIR", os.path.expanduser("~/vve-health")),
                             "sicherheit-status.json")
        with open(pfad, encoding="utf-8") as f:
            stand = json.load(f)
    except (OSError, ValueError):
        return {"bekannt": False}
    stand["bekannt"] = True
    stand["alter_sek"] = round(time.time() - stand.get("zeit", 0), 1) if stand.get("zeit") else None
    return stand


def status():
    la = os.getloadavg()
    du = shutil.disk_usage("/")
    d = {
        "host": {
            "hostname": sh("hostname"),
            "os": sh("lsb_release -ds"),
            "kernel": sh("uname -r"),
            "uptime": sh("uptime -p"),
            "load": [round(la[0],2), round(la[1],2), round(la[2],2)], "load_named": {"1m": la[0], "5m": la[1], "15m": la[2]},
        },
        "cpu": {
            "model": sh("lscpu | grep 'Model name' | cut -d: -f2 | xargs"),
            "cores": os.cpu_count(),
            "governor": sh("cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
            "power_profile": sh("powerprofilesctl get"),
        },
        "memory_mb": {
            "total": int(sh("free -m | awk '/^Mem:/{print $2}'") or 0),
            "used": int(sh("free -m | awk '/^Mem:/{print $3}'") or 0),
        },
        "disk_gb": {
            "total": round(du.total/1e9, 1),
            "used": round(du.used/1e9, 1),
            "free": round(du.free/1e9, 1),
        },
        "sensors_raw": json.loads(sh("sensors -j") or "{}"),
        # fan.speed dazu (09.09.2026): Veiko wollte im Aufbau-Schaubild auf
        # eine Karte klicken und sehen, ob der Luefter laeuft — bisher stand
        # dazu nur "GPU-Luefter erst mit dedizierter Karte via nvidia-smi"
        # in d["fans"]["note"], eine reine Ankuendigung ohne Wert. nvidia-smi
        # liefert die Drehzahl als Prozent der maximalen Drehzahl (kein U/min
        # ohne separate Werkzeuge), aber genau das reicht fuer "laeuft der
        # Luefter gerade" — ein zusaetzliches Feld in derselben Zeile, keine
        # zweite Abfrage.
        "gpu_nvidia": sh("nvidia-smi --query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total,power.draw,fan.speed --format=csv,noheader 2>/dev/null"),
        # Was gerade VRAM belegt — die Antwort auf "warum ist der Speicher
        # halb voll". nvidia-smi trennt das hier NICHT nach Karte (dafuer
        # braeuchte es eine zweite, per gpu_uuid korrelierte Abfrage); bei
        # zwei Karten zeigt das Cockpit die Liste deshalb als "ueber beide
        # Karten zusammen" an, statt eine Zuordnung vorzutaeuschen, die
        # dieser Aufruf gar nicht hergibt.
        "gpu_prozesse": [l for l in sh(
            "nvidia-smi --query-compute-apps=process_name,used_memory "
            "--format=csv,noheader 2>/dev/null").splitlines() if l.strip()],
        "health": gesundheit(),
        "sicherheit": sicherheit(),
        "updates": {
            "pending": len([l for l in sh("apt list --upgradable 2>/dev/null").splitlines() if "/" in l]),
            "security": len([l for l in sh("apt list --upgradable 2>/dev/null").splitlines() if "security" in l]),
            "reboot_required": os.path.exists("/var/run/reboot-required"),
        },
        "security": {
            "ufw": sh("sudo -n ufw status 2>/dev/null | head -1") or "n/a",
            "unattended_upgrades": sh("systemctl is-active unattended-upgrades"),
        },
        "services": {
            "ollama": sh("systemctl is-active ollama"),
            "caddy": sh("systemctl is-active caddy"),
            "tailscale": sh("tailscale status --json 2>/dev/null | jq -r .BackendState"),
        },
        "docker": [l for l in sh("docker ps --format '{{.Names}}|{{.Status}}'").splitlines()],
        "ollama_models": [l for l in sh("ollama list | tail -n +2 | awk '{print $1\"|\"$3$4}'").splitlines()],
        "comfy_models": comfy_modelle(),
        "comfy_ordner": comfy_ordner_liste(),
        "ollama_running": [l for l in sh("ollama ps | tail -n +2 | awk '{print $1\"|\"$5}'").splitlines()],
        "network": netzwerk(),
        "timers": zeitgeber(),
        "versions": fassungen(),
        "ollama_conf": ollama_conf(),
        "ollama_laeuft": ollama_laeuft(),
    }
    sj = d["sensors_raw"]
    d["temps_c"] = temps(sj)
    d["igpu"] = igpu(sj)
    # Der Mini-PC selbst meldet weiterhin keine Luefterdrehzahl ueber
    # lm-sensors (unveraendert) — die GPU-Drehzahl kommt seit 09.09.2026 als
    # eigenes Feld in jeder gpu_nvidia-Zeile mit (fan.speed, Prozent der
    # maximalen Drehzahl), nicht mehr ueber dieses Sammelfeld hier.
    d["fans"] = {"available": False, "note": "Mini-PC meldet keine Luefterdrehzahlen ueber lm-sensors; GPU-Luefterdrehzahl steht je Karte in gpu_nvidia (fan.speed)"}
    d["power"] = power()
    d["firmware"] = firmware()
    return d

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(status(), indent=2).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 9099), H).serve_forever()
