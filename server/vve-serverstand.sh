#!/bin/bash
# ---------------------------------------------------------------------------
# Serverstand fuer die Sicherung des NEUEN Cockpits (23.10.2026).
#
# Bis dahin sicherte das ALTE Cockpit nachts (vvec-sicherung.sh --server) alles,
# was man zum Neuaufbau des Servers braucht und was nur root lesen kann: Caddy,
# Cloudflare-Tunnel, sudo-Regeln, systemd-Units, Firewall, Paketliste, wie die
# Container gestartet wurden. Mit dem alten Cockpit faellt diese Sicherung weg.
# Das neue Cockpit laeuft als vveadmin und kann die Dateien nicht selbst lesen.
#
# Deshalb dieses Skript, nach demselben Muster wie vve-ollama-aktualisieren:
# Veiko installiert es EINMAL root-eigen nach /usr/local/sbin/vve-serverstand
# (Befehl in cockpit/sicherung.py, SERVERSTAND_EINRICHTEN), und genau dieser
# Aufruf OHNE Argumente ist fuer vveadmin ohne Passwort freigegeben. Es LIEST nur
# und schreibt ein tar.gz auf die Standardausgabe -- keine Zwischendatei, deren
# Rechte falsch stehen koennten. Die Sicherung des Cockpits legt es in ihr
# verschluesseltes Paket (Ordner server/), Schluessel darin inklusive.
#
# Eine Aenderung an dieser Vorlage wirkt erst, wenn der Installationsbefehl
# erneut ausgefuehrt wird -- die Kopie unter /usr/local/sbin gehoert root.
# ---------------------------------------------------------------------------
set -uo pipefail
umask 077

A=$(mktemp -d /tmp/vve-serverstand.XXXXXX)
trap 'rm -rf "$A"' EXIT
S="$A/serverstand"
mkdir -p "$S"

kopie() {  # kopie <ziel-unterordner> <pfad>... -- fehlt etwas, wird es vermerkt statt abzubrechen
  local ziel="$S/$1"; shift
  mkdir -p "$ziel"
  for p in "$@"; do
    if [ -e "$p" ]; then cp -a "$p" "$ziel/" 2>/dev/null || echo "nicht kopierbar: $p" >> "$S/FEHLT.txt"
    else echo "nicht vorhanden: $p" >> "$S/FEHLT.txt"; fi
  done
}

kopie caddy /etc/caddy/Caddyfile
kopie cloudflared /etc/cloudflared
kopie sudoers.d /etc/sudoers.d
kopie systemd /etc/systemd/system/vve-*.service /etc/systemd/system/vve-*.timer /etc/systemd/system/ollama.service \
              /etc/systemd/system/ollama.service.d /etc/systemd/system/cloudflared.service
kopie etc-vve /etc/vve
kopie usr-local /usr/local/bin/vve-status.py /usr/local/bin/vve-admin.py /usr/local/bin/vve-rgb.py \
                /usr/local/bin/vve-health.py /usr/local/bin/vve-sicherheit.py /usr/local/sbin/vve-ollama-aktualisieren \
                /usr/local/sbin/vve-serverstand
kopie firewall /etc/ufw/user.rules /etc/ufw/user6.rules /etc/fail2ban/jail.d
kopie ssh /etc/ssh/sshd_config.d
kopie searxng /var/lib/docker/volumes/searxng-config/_data/settings.yml
kopie openedai-speech /var/lib/docker/volumes/openedai-config/_data

# Was sich nicht kopieren laesst, wird als Bestand festgehalten.
dpkg --get-selections > "$S/pakete.txt" 2>/dev/null
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' > "$S/docker-container.txt" 2>/dev/null
# Wie die Container gestartet wurden (Mounts, GPUs, Umgebung) -- ComfyUI wurde von Hand
# mit --gpus device=1 angelegt; ohne das hier waere es beim Neuaufbau geraten.
docker inspect $(docker ps -aq) > "$S/docker-inspect.json" 2>/dev/null
tailscale serve status --json > "$S/tailscale-serve.json" 2>/dev/null
systemctl list-timers --all --no-pager > "$S/zeitgeber.txt" 2>/dev/null
crontab -l > "$S/crontab-root.txt" 2>/dev/null
ls -la /home/vveadmin/comfy-models /home/vveadmin/comfyui-daten > "$S/comfy-ordner.txt" 2>/dev/null
{ uname -a; date -Is; } > "$S/stand.txt"

tar -czf - -C "$A" serverstand
