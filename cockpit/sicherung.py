"""
SICHERUNG DES NEUEN COCKPITS -- lokal UND nach OneDrive (23.10.2026).

Bis zum 23.10. sicherte dieses Modul nur die Datenbank, und zwar auf DIESELBE Platte
(daten/sicherungen, 30 Staende). Die OneDrive-Sicherung gehoerte dem alten Cockpit
(/opt/vvec/vvec-sicherung.sh) und erfasste nur dessen Daten. Veiko wollte das alte Cockpit
bald loeschen -- dann haette es fuer die neue Fassung keine einzige Sicherung ausserhalb des
Servers gegeben, und Unterlagen, Medien und Zugangsdaten waren nie gesichert.

Jetzt, taeglich 03:30 deutscher Zeit (vve-cp-r2-sicherung.timer, nach RSI) und von Hand:
  1. Datenbank per SQLite-Backup-API (in sich stimmig auch waehrend des Schreibens -- eine
     Dateikopie im WAL-Modus kann einen halben Stand sichern), mit integrity_check. Bleibt
     wie bisher als lokaler Stand liegen (30).
  2. Ein Paket: dieser Datenbankstand + alles unter daten/ (Unterlagen, Medien, Ergebnisse,
     WebSpace samt Entwuerfen, Einstellungen) + die Zugangsdaten der neuen Fassung
     (~/.config/vve-cp-r2.env, TLS-Zertifikat, die systemd-Units, die SSH-Schluessel fuer
     GitHub und die Website) + eine Anleitung zum Wiederherstellen.
     Nicht dabei: was sich neu rechnen laesst (cache, Vorschaubilder) und die alten lokalen
     Datenbankstaende. Der Programmcode liegt auf GitHub.
  3. VERSCHLUESSELT mit AES-256 (openssl, PBKDF2 -- dieselbe Art wie die Server-Sicherung des
     alten Cockpits; openssl ist auf jedem Rettungssystem da). Das Paket enthaelt Schluessel
     und Zugangsdaten. Der Schluessel liegt in ~/.config/vve-cp-r2-sicherung.key und MUSS
     zusaetzlich bei Veiko liegen (Passwortmanager) -- faellt die Platte aus, ist er sonst mit weg.
  4. GEGENPROBE: das verschluesselte Paket wird entschluesselt und gelesen. Eine Sicherung,
     die man nicht oeffnen kann, ist keine -- und das faellt sonst erst im Ernstfall auf.
  5. Per rclone nach OneDrive (dieselbe Anmeldung wie das alte Cockpit, einmal von Veiko
     kopiert, siehe einrichten_befehl()), Unterordner "Backup Cockpit-R2", 14 Staende.

Ohne OneDrive-Einrichtung laeuft Schritt 1 weiter, und der Stand sagt ehrlich
"nicht eingerichtet" -- kein stilles Weglassen.

Aufruf: .venv/bin/python -m cockpit.sicherung     (Zeitgeber vve-cp-r2-sicherung.timer)
"""
from __future__ import annotations

import io
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

from .konfig import DB_DATEI, DATEN

ZIEL = DATEN / "sicherungen"
BEHALTEN = 30
STAND = DATEN / "sicherung-stand.json"
HEIM = Path.home()
ENV = HEIM / ".config" / "vve-cp-r2.env"
SCHLUESSEL = HEIM / ".config" / "vve-cp-r2-sicherung.key"
RCLONE_KONF = HEIM / ".config" / "rclone" / "rclone.conf"
UNTERORDNER = "Backup Cockpit-R2"
BEHALTEN_FERN = 14
MUSTER = "vve-cp-r2-"
# Was nicht ins Paket gehoert: laesst sich neu rechnen, ist schon in der Datenbank-Kopie, oder alt.
WEG_DATEN = {"sicherungen", "cache", "explorer-vorschau", "cockpit.sqlite", "cockpit.sqlite-wal", "cockpit.sqlite-shm",
             ".sicherung-arbeit", "sicherung-stand.json", "sicherung-stand.tmp"}
WEG_PRAEFIX = ("medien-alt-", "cockpit-vor-")
ZUGANG = [ENV, HEIM / ".config" / "vve-cp-r2-tls", HEIM / ".config" / "systemd" / "user",
          HEIM / ".ssh" / "id_ed25519", HEIM / ".ssh" / "id_ed25519.pub",
          HEIM / ".ssh" / "webspace_ed25519", HEIM / ".ssh" / "webspace_ed25519.pub"]

ANLEITUNG = """WIEDERHERSTELLEN -- VvE Cockpit (neue Fassung, vve-cp-r2)

1. Paket entschluesseln und auspacken (den Schluessel hast du im Passwortmanager):
     openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in vve-cp-r2-DATUM.tgz.enc -pass pass:'DEIN-SCHLUESSEL' | tar -xzf -
2. Code holen:   git clone git@github.com:veikovoneckern-ops/vve-cp-r2.git ~/vve-cp-r2
   und die Python-Umgebung anlegen (siehe README.md im Repo).
3. daten/ aus dem Paket nach ~/vve-cp-r2/daten kopieren; cockpit.sqlite liegt bereits drin.
4. zugang/.config/* nach ~/.config, zugang/.ssh/* nach ~/.ssh (chmod 600 auf die Schluessel).
5. systemctl --user daemon-reload && systemctl --user enable --now vve-cp-r2 vve-cp-r2-sicherung.timer
"""


# ---------------------------------------------------------------- Einstellungen
def _env_wert(name: str) -> str:
    """Erst aus der Umgebung, sonst direkt aus der env-Datei -- der laufende Dienst hat eine
    nachtraeglich ergaenzte Zeile erst nach einem Neustart in seiner Umgebung."""
    if os.environ.get(name):
        return os.environ[name].strip()
    try:
        for z in ENV.read_text(encoding="utf-8").splitlines():
            if z.startswith(name + "="):
                return z.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def ziel() -> tuple[str, str]:
    """(rclone-Fernziel, Ordner) -- dieselben Werte wie die Sicherung des alten Cockpits."""
    return _env_wert("VVEC_SICHERUNG_RCLONE_REMOTE"), _env_wert("VVEC_SICHERUNG_ZIEL_ORDNER")


def eingerichtet() -> bool:
    fern, ordner = ziel()
    return bool(fern and ordner and RCLONE_KONF.is_file() and shutil.which("rclone"))


def einrichten_befehl() -> str:
    """Einmal von Veiko (braucht sein Passwort): die OneDrive-Anmeldung des alten Cockpits fuer
    vveadmin kopieren und Fernziel/Ordner uebernehmen. Mehr Rechte bekommt dabei niemand."""
    return ("mkdir -p ~/.config/rclone && sudo cp /etc/vvec/rclone.conf ~/.config/rclone/rclone.conf "
            "&& sudo chown $USER: ~/.config/rclone/rclone.conf && chmod 600 ~/.config/rclone/rclone.conf "
            "&& sudo grep -E '^(RCLONE_REMOTE|ZIEL_ORDNER)=' /etc/vvec/sicherung.env "
            "| sed 's/^/VVEC_SICHERUNG_/' >> ~/.config/vve-cp-r2.env && echo eingerichtet")


# Der SERVERSTAND (23.10.2026): was nur root lesen kann und man zum Neuaufbau braucht (Caddy,
# Cloudflare, sudo-Regeln, Units, Firewall, Paketliste, Container-Aufrufe). Bis dahin sicherte das
# die Server-Sicherung des alten Cockpits; sie faellt mit ihm weg. Ein root-eigenes Skript
# (server/vve-serverstand.sh) liefert es als tar.gz auf die Standardausgabe; vveadmin darf genau
# diesen Aufruf ohne Argumente. Fehlt es, laeuft die Sicherung trotzdem -- und der Stand sagt das.
SERVERSTAND_SKRIPT = "/usr/local/sbin/vve-serverstand"
SERVERSTAND_EINRICHTEN = (
    "sudo install -o root -g root -m 755 ~/vve-cp-r2/server/vve-serverstand.sh " + SERVERSTAND_SKRIPT +
    " && echo 'vveadmin ALL=(root) NOPASSWD: " + SERVERSTAND_SKRIPT + " \"\"' | sudo tee /etc/sudoers.d/vve-serverstand >/dev/null"
    " && sudo chmod 440 /etc/sudoers.d/vve-serverstand && sudo visudo -c -q && echo eingerichtet")


_sst_gemerkt: dict[str, Any] = {"zeit": 0.0, "wert": False}


def serverstand_eingerichtet() -> bool:
    # Fuenf Minuten gemerkt -- stand() wird von der Kopfzeile alle paar Sekunden gelesen.
    if time.time() - _sst_gemerkt["zeit"] < 300:
        return _sst_gemerkt["wert"]
    try:
        r = subprocess.run(["sudo", "-n", "-l", SERVERSTAND_SKRIPT], capture_output=True, timeout=5)
        wert = r.returncode == 0 and Path(SERVERSTAND_SKRIPT).is_file()
    except (OSError, subprocess.TimeoutExpired):
        wert = False
    _sst_gemerkt.update(zeit=time.time(), wert=wert)
    return wert


def serverstand_holen(arbeit: Path) -> Path | None:
    """Das tar.gz des Skripts in den Arbeitsordner; None, wenn es nicht eingerichtet ist."""
    if not serverstand_eingerichtet():
        return None
    ziel_ = arbeit / "serverstand.tgz"
    with open(ziel_, "wb") as f:
        r = subprocess.run(["sudo", "-n", SERVERSTAND_SKRIPT], stdout=f, stderr=subprocess.PIPE, timeout=600)
    if r.returncode or ziel_.stat().st_size < 1000:
        raise RuntimeError(f"Serverstand gescheitert: {r.stderr.decode(errors='replace')[:300] or 'leer'}")
    with tarfile.open(ziel_, "r:gz") as t:  # lesbar?
        t.getmembers()
    return ziel_


def schluessel() -> str:
    """Der Schluessel -- beim ersten Mal erzeugt (48 Zeichen Zufall), nur fuer vveadmin lesbar."""
    if not SCHLUESSEL.is_file():
        SCHLUESSEL.parent.mkdir(parents=True, exist_ok=True)
        SCHLUESSEL.write_text(secrets.token_urlsafe(36), encoding="utf-8")
        SCHLUESSEL.chmod(0o600)
    return SCHLUESSEL.read_text(encoding="utf-8").strip()


def stand() -> dict[str, Any]:
    try:
        s = json.loads(STAND.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    fern, ordner = ziel()
    s["eingerichtet"] = eingerichtet()
    s["ziel"] = f"{fern}:{ordner}/{UNTERORDNER}" if fern and ordner else None
    s["schluessel_da"] = SCHLUESSEL.is_file()
    s["lokal"] = len(list(ZIEL.glob("cockpit-*.sqlite"))) if ZIEL.is_dir() else 0
    s["serverstand_eingerichtet"] = serverstand_eingerichtet()
    return s


def _stand_setzen(**w: Any) -> None:
    try:
        s = json.loads(STAND.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    s.update(w)
    tmp = STAND.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STAND)


def schluessel_gesichert() -> None:
    _stand_setzen(schluessel_bestaetigt=time.time())


# ---------------------------------------------------------------- 1. Datenbank lokal
def sichern() -> Path:
    ZIEL.mkdir(parents=True, exist_ok=True)
    datei = ZIEL / f"cockpit-{time.strftime('%Y%m%d-%H%M%S')}.sqlite"
    quelle = sqlite3.connect(str(DB_DATEI))
    ziel_ = sqlite3.connect(str(datei))
    with ziel_:
        quelle.backup(ziel_)
    ziel_.close()
    quelle.close()
    # Gegenprobe: eine Sicherung, die sich nicht oeffnen laesst, ist keine.
    pruef = sqlite3.connect(str(datei))
    ok = pruef.execute("PRAGMA integrity_check").fetchone()[0]
    pruef.close()
    if ok != "ok":
        raise SystemExit(f"Sicherung {datei} ist beschaedigt: {ok}")
    alle = sorted(ZIEL.glob("cockpit-*.sqlite"))
    for alt in alle[:-BEHALTEN]:
        alt.unlink()
    return datei


# ---------------------------------------------------------------- 2.-5. Paket nach OneDrive
def _filter(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
    teile = Path(ti.name).parts
    # daten/<oberster Eintrag> -- was neu rechenbar oder schon in der DB-Kopie ist, fliegt raus.
    if len(teile) >= 2 and teile[0] == "daten" and (teile[1] in WEG_DATEN or teile[1].startswith(WEG_PRAEFIX)):
        return None
    if "_vorschau" in teile or "__pycache__" in teile:
        return None
    return ti


def paket_bauen(db_kopie: Path, arbeit: Path, serverstand: Path | None = None) -> tuple[Path, int]:
    """Baut das unverschluesselte .tgz und gibt (Pfad, Anzahl Eintraege) zurueck."""
    roh = arbeit / "paket.tgz"
    with tarfile.open(roh, "w:gz", compresslevel=6) as tar:
        tar.add(str(DATEN), arcname="daten", filter=_filter)
        tar.add(str(db_kopie), arcname="daten/cockpit.sqlite")
        if serverstand:
            tar.add(str(serverstand), arcname="server/serverstand.tgz")
        for p in ZUGANG:
            if p.exists():
                tar.add(str(p), arcname="zugang/" + str(p.relative_to(HEIM)))
        text = ANLEITUNG.encode("utf-8")
        info = tarfile.TarInfo("WIEDERHERSTELLEN.txt")
        info.size, info.mtime = len(text), int(time.time())
        tar.addfile(info, io.BytesIO(text))
        n = len(tar.getmembers())
    return roh, n


def _openssl(*args: str, eingabe: Path, ausgabe: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["openssl", "enc", *args, "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
                           "-pass", f"file:{SCHLUESSEL}", "-in", str(eingabe), "-out", str(ausgabe)],
                          capture_output=True, timeout=1800)


def verschluesseln_und_pruefen(roh: Path, n: int) -> Path:
    schluessel()
    enc = roh.with_name(f"{MUSTER}{time.strftime('%Y%m%d-%H%M%S')}.tgz.enc")
    r = _openssl("-salt", eingabe=roh, ausgabe=enc)
    if r.returncode:
        raise RuntimeError(f"Verschlüsseln gescheitert: {r.stderr.decode(errors='replace')[:300]}")
    # Gegenprobe: entschluesseln und als Archiv lesen -- gleiche Zahl Eintraege wie beim Packen.
    probe = roh.with_name("probe.tgz")
    r = _openssl("-d", eingabe=enc, ausgabe=probe)
    if r.returncode:
        raise RuntimeError("Das verschlüsselte Paket lässt sich nicht wieder öffnen.")
    with tarfile.open(probe, "r:gz") as t:
        m = len(t.getmembers())
    probe.unlink()
    if m != n:
        raise RuntimeError(f"Gegenprobe: {m} statt {n} Einträge im Paket.")
    return enc


def _rclone(*args: str, timeout: int = 3600) -> subprocess.CompletedProcess:
    return subprocess.run(["rclone", "--config", str(RCLONE_KONF), *args], capture_output=True, timeout=timeout)


def hochladen(enc: Path) -> tuple[str, int]:
    fern, ordner = ziel()
    pfad = f"{fern}:{ordner}/{UNTERORDNER}"
    r = _rclone("copyto", str(enc), f"{pfad}/{enc.name}", "--retries", "3")
    if r.returncode:
        raise RuntimeError(f"Hochladen gescheitert: {r.stderr.decode(errors='replace').strip()[-400:]}")
    # Ist es wirklich da, und so gross wie hier?
    r = _rclone("lsjson", f"{pfad}/{enc.name}", timeout=120)
    try:
        groesse = json.loads(r.stdout or b"[]")[0]["Size"]
    except (ValueError, IndexError, KeyError):
        raise RuntimeError("Nach dem Hochladen ist das Paket in OneDrive nicht zu finden.")
    if groesse != enc.stat().st_size:
        raise RuntimeError(f"In OneDrive liegen {groesse} Byte statt {enc.stat().st_size}.")
    # Alte Staende abraeumen -- nur eigene Pakete (Muster), die neuesten BEHALTEN_FERN bleiben.
    r = _rclone("lsf", pfad, "--include", MUSTER + "*.tgz.enc", timeout=120)
    alle = sorted(x for x in r.stdout.decode().split() if x.startswith(MUSTER))
    weg = alle[:-BEHALTEN_FERN]
    for f in weg:
        _rclone("deletefile", f"{pfad}/{f}", timeout=120)
    return pfad, len(alle) - len(weg)


def voll(probe: bool = False) -> dict[str, Any]:
    """probe=True: alles ausser dem Hochladen -- zum Pruefen ohne OneDrive."""
    t0 = time.time()
    _stand_setzen(laeuft=True, start=t0, schritt="Datenbank sichern", fehler=None)
    arbeit = DATEN / ".sicherung-arbeit"
    try:
        db_kopie = sichern()
        if not eingerichtet() and not probe:
            _stand_setzen(laeuft=False, zeit=time.time(), zustand="nicht_eingerichtet", schritt=None,
                          db=db_kopie.name, fehler="OneDrive ist für die neue Fassung noch nicht eingerichtet -- "
                          "gesichert wurde nur die Datenbank, auf derselben Platte.")
            return stand()
        shutil.rmtree(arbeit, ignore_errors=True)
        arbeit.mkdir(parents=True)
        _stand_setzen(schritt="Serverstand holen")
        try:
            sst = serverstand_holen(arbeit)
            sst_zustand = "ok" if sst else "nicht_eingerichtet"
        except Exception as e:  # noqa: BLE001 -- ohne Serverstand ist das Paket immer noch viel wert
            sst, sst_zustand = None, f"fehler: {e}"[:300]
        _stand_setzen(schritt="Paket packen", serverstand=sst_zustand)
        roh, n = paket_bauen(db_kopie, arbeit, sst)
        _stand_setzen(schritt="Verschlüsseln und gegenprüfen")
        enc = verschluesseln_und_pruefen(roh, n)
        roh.unlink()
        mb = round(enc.stat().st_size / 1e6, 1)
        if probe:
            _stand_setzen(laeuft=False, schritt=None, probe={"zeit": time.time(), "groesse_mb": mb, "eintraege": n,
                                                              "dauer_s": round(time.time() - t0)})
            return stand()
        _stand_setzen(schritt="Nach OneDrive hochladen")
        pfad, behalten = hochladen(enc)
        _stand_setzen(laeuft=False, zeit=time.time(), zustand="ok", schritt=None, fehler=None, datei=enc.name,
                      groesse_mb=mb, eintraege=n, dauer_s=round(time.time() - t0), in_onedrive=behalten, db=db_kopie.name)
    except Exception as e:  # noqa: BLE001 -- der Stand sagt, was schiefging; die Kachel zeigt es
        _stand_setzen(laeuft=False, zeit=time.time(), zustand="fehler", schritt=None, fehler=f"{e}"[:600])
        raise
    finally:
        shutil.rmtree(arbeit, ignore_errors=True)
    return stand()


if __name__ == "__main__":
    if "--nur-db" in sys.argv:
        print(f"Gesichert: {sichern()}")
    else:
        try:
            s = voll(probe="--probe" in sys.argv)
        except Exception as e:  # noqa: BLE001
            print(f"FEHLER: {e}", file=sys.stderr)
            sys.exit(1)
        print(json.dumps(s, ensure_ascii=False, indent=1))
