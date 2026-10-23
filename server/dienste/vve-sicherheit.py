#!/usr/bin/env python3
"""VVE Sicherheits-Check — Firewall-Drift, fail2ban-Stand, fehlgeschlagene
Anmeldeversuche. Reine Beobachtung, greift nirgends ein.

ANLASS (10.09.2026): beim Bau der Notfall-Automatik fiel durch einen
direkten Test von ausserhalb auf, dass Port 22 (SSH) monatelang unbemerkt
dem gesamten Internet offenstand — ufw erlaubte "Anywhere", nicht nur
Tailscale. Die Lücke war real (SSH antwortete einer Verbindung von
draussen), nur zufällig noch nicht ausgenutzt. Genau das soll sich nicht
wiederholen, ohne dass es auffaellt: dieses Skript prueft regelmaessig
neu nach, ob wieder eine Regel "Anywhere" erlaubt, die es nicht sollte.

Läuft als Timer (nicht dauerhaft wie vve-health.py) — die Firewall
ändert sich nicht im Sekundentakt, ein Blick alle fünf Minuten reicht.

Braucht fuer die eigentliche Pruefung zwei schreibgeschuetzte sudo-Rechte
(NOPASSWD, siehe /etc/sudoers.d/vve-security-status): `ufw status` und
`fail2ban-client status` -- beides nur LESEND, keine der beiden Zeilen
kann irgendetwas veraendern. Fehlen sie (aeltere Serverstaende, vor der
Freigabe), wird das ehrlich gemeldet statt eine falsche Ruhe vorzutaeuschen.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

# Dieselbe Ablage wie vve-health.py, aus demselben Grund: vveadmin kann
# nicht nach /var/lib/vvec schreiben (gehoert vvec:vvec, 755).
DATEN_DIR = Path(os.getenv("VVEC_HEALTH_DIR", os.path.expanduser("~/vve-health")))
STATUS_DATEI = DATEN_DIR / "sicherheit-status.json"


def _sh(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _schreiben(stand):
    DATEN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DATEN_DIR, 0o755)
    except OSError:
        pass
    tmp = STATUS_DATEI.with_suffix(".tmp")
    tmp.write_text(json.dumps(stand, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATUS_DATEI)
    try:
        os.chmod(STATUS_DATEI, 0o644)
    except OSError:
        pass


def ufw_stand():
    """{'aktiv': bool, 'offene_regeln': [...], 'lesbar': bool}

    "offene_regeln" sind alle Zeilen mit "Anywhere" -- Regeln also, die
    JEDE Adresse im Internet erreicht, nicht nur Tailscale. Aktuell soll
    das KEINE sein; jede gefundene Zeile ist ein Fund, den Veiko sehen
    soll, kein normaler Zustand."""
    aktiv = _sh(["systemctl", "is-active", "ufw"]).strip() == "active"
    roh = _sh(["sudo", "-n", "ufw", "status", "numbered"])
    if not roh.strip():
        return {"aktiv": aktiv, "offene_regeln": [], "lesbar": False}
    offene = []
    for zeile in roh.splitlines():
        if "Anywhere" in zeile and "ALLOW" in zeile:
            offene.append(zeile.strip())
    return {"aktiv": aktiv, "offene_regeln": offene, "lesbar": True}


def fail2ban_stand():
    """{'aktiv': bool, 'gesperrt': [...], 'lesbar': bool}"""
    aktiv = _sh(["systemctl", "is-active", "fail2ban"]).strip() == "active"
    if not aktiv:
        return {"aktiv": False, "gesperrt": [], "lesbar": True}
    roh = _sh(["sudo", "-n", "fail2ban-client", "status", "sshd"])
    if not roh.strip():
        return {"aktiv": aktiv, "gesperrt": [], "lesbar": False}
    gesperrt = []
    for zeile in roh.splitlines():
        if "Banned IP list" in zeile:
            teil = zeile.split(":", 1)[-1].strip()
            gesperrt = [ip for ip in teil.split() if ip]
    return {"aktiv": aktiv, "gesperrt": gesperrt, "lesbar": True}


def ssh_fehlgeschlagen_24h():
    """Anzahl fehlgeschlagener SSH-Anmeldeversuche der letzten 24 Stunden.
    journalctl -u ssh ist fuer vveadmin ohne sudo lesbar (Gruppe "adm")."""
    roh = _sh(["journalctl", "-u", "ssh", "--since", "-24 hours", "--no-pager"], timeout=15)
    muster = re.compile(r"Failed password|Invalid user|Connection closed by "
                         r"(authenticating|invalid) user", re.IGNORECASE)
    return sum(1 for zeile in roh.splitlines() if muster.search(zeile))


def main():
    stand = {
        "zeit": time.time(),
        "ufw": ufw_stand(),
        "fail2ban": fail2ban_stand(),
        "ssh_fehlgeschlagen_24h": ssh_fehlgeschlagen_24h(),
        "unattended_upgrades_aktiv": _sh(
            ["systemctl", "is-active", "unattended-upgrades"]).strip() == "active",
    }
    _schreiben(stand)
    if stand["ufw"]["offene_regeln"]:
        print("[vve-sicherheit] WARNUNG: %d offene Firewall-Regel(n) mit "
              "'Anywhere' gefunden: %s" % (len(stand["ufw"]["offene_regeln"]),
                                           stand["ufw"]["offene_regeln"]), flush=True)
    else:
        print("[vve-sicherheit] Stand geschrieben, keine offenen Regeln gefunden.", flush=True)


if __name__ == "__main__":
    main()
