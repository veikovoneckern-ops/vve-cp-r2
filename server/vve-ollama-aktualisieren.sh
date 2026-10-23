#!/bin/bash
# ---------------------------------------------------------------------------
# Ollama aktualisieren -- fuer das NEUE Cockpit, ohne das alte (23.10.2026).
#
# Wird EINMAL von Veiko als root installiert (Befehl in cockpit/systeminfo.py,
# OLLAMA_EINRICHTEN) nach /usr/local/sbin/vve-ollama-aktualisieren, root-eigen,
# und genau dieser eine Aufruf ist fuer vveadmin ohne Passwort freigegeben
# (/etc/sudoers.d/vve-ollama-aktualisieren). Das Cockpit startet ihn ohne jedes
# Argument -- es gibt nichts, womit es den Ablauf veraendern koennte. Die Kopie
# unter /usr/local/sbin gehoert root: weder das Cockpit noch Neo koennen sie
# umschreiben, auch wenn die Vorlage hier im Repo liegt. Eine Aenderung an dieser
# Vorlage wirkt erst, wenn Veiko den Installationsbefehl erneut ausfuehrt.
#
# Der Ablauf ist der des alten Wartungsdienstes (vvec-wartung-lauf.sh, Art
# "ollama-aktualisieren", 14.10.2026), weil er sich bewaehrt hat:
#   ERST VOLLSTAENDIG LADEN, DANN IN SEKUNDEN TAUSCHEN. Das offizielle install.sh
#   raeumt /usr/local/lib/ollama ZUERST leer und laedt danach 1,4 GB -- ueber das
#   WLAN dieses Servers gut zehn Minuten, in denen jeder Modellaufruf scheitert.
#   1. Archiv komplett in ein Staging unter /usr/local laden und entpacken.
#   2. Pruefen, ob Binary und Laufzeitbibliotheken wirklich darin liegen.
#   3. Erst dann tauschen (mv im selben Dateisystem: Sekunden), ollama neu starten.
#   4. Antwortet ollama nicht binnen 30 s, wird der alte Stand zurueckgelegt.
#
# Protokoll und Stand liegen lesbar fuer das Cockpit unter /var/lib/vve-cp-r2-wartung
# (<art>-<zeit>.log / .stand: "running", "done 0", "failed <rc>") -- dieselbe Form
# wie beim alten Dienst, damit das Cockpit sie genauso mitliest.
# ---------------------------------------------------------------------------
set -uo pipefail
umask 022

WURZEL=/var/lib/vve-cp-r2-wartung
mkdir -p "$WURZEL" && chmod 755 "$WURZEL"
STEMPEL=$(date +%Y%m%d-%H%M%S)
PROTOKOLL="$WURZEL/ollama-aktualisieren-$STEMPEL.log"
STAND="$WURZEL/ollama-aktualisieren-$STEMPEL.stand"
: > "$PROTOKOLL"
stand_setzen() { printf '%s\n' "$1" > "$STAND"; chmod 644 "$STAND" "$PROTOKOLL" 2>/dev/null || true; }
log() { printf '%s\n' "$*" >> "$PROTOKOLL"; }

# Nur ein Lauf zur Zeit -- zwei Taeusche gleichzeitig waeren genau der halbe Zustand,
# den dieser Ablauf verhindern soll.
exec 9>"$WURZEL/.sperre"
if ! flock -n 9; then
  log "Es laeuft schon ein Update. Nichts getan."
  stand_setzen "failed 75"; exit 0
fi

# Alte Protokolle aufraeumen (die letzten zehn Laeufe bleiben).
ls -1t "$WURZEL"/ollama-aktualisieren-*.log 2>/dev/null | tail -n +11 | while read -r f; do rm -f "$f" "${f%.log}.stand"; done

stand_setzen "running"
case "$(uname -m)" in
  x86_64)  oarch=amd64 ;;
  aarch64) oarch=arm64 ;;
  *) log "Unbekannte Architektur $(uname -m)."; stand_setzen "failed 1"; exit 0 ;;
esac

neu=$(mktemp -d /usr/local/.ollama-neu.XXXXXX)
alt="/usr/local/.ollama-alt.$$"
aufraeumen() { rm -rf "$neu"; }
trap 'aufraeumen; stand_setzen "failed 143"; exit 143' TERM INT

url="https://ollama.com/download/ollama-linux-${oarch}"
log "PHASE download: Lade die neue Fassung herunter (die laufende bleibt solange in Betrieb) ..."
log "Bisher: $(/usr/local/bin/ollama --version 2>/dev/null | tail -1)"
if curl -fsIL "${url}.tar.zst" >/dev/null 2>&1; then
  archiv="$neu/ollama.tar.zst"
  curl -fL -sS -o "$archiv" "${url}.tar.zst" >> "$PROTOKOLL" 2>&1 && zstd -dc "$archiv" | tar -xf - -C "$neu"
  rc=$?
else
  archiv="$neu/ollama.tgz"
  curl -fL -sS -o "$archiv" "${url}.tgz" >> "$PROTOKOLL" 2>&1 && tar -xzf "$archiv" -C "$neu"
  rc=$?
fi
rm -f "$archiv"
if [ "$rc" != "0" ]; then
  log "Download oder Entpacken fehlgeschlagen (rc $rc). Die laufende Installation ist unveraendert."
  aufraeumen; stand_setzen "failed $rc"; exit 0
fi
if [ ! -x "$neu/bin/ollama" ] || ! find "$neu/lib/ollama" -name '*.so*' 2>/dev/null | grep -q .; then
  log "Im Archiv fehlen Binary oder Laufzeitbibliotheken. Die laufende Installation ist unveraendert."
  aufraeumen; stand_setzen "failed 1"; exit 0
fi
log "PHASE einrichten: Neue Fassung vollstaendig: $("$neu/bin/ollama" --version 2>/dev/null | tail -1). Tausche aus und starte ollama neu ..."

# Ab hier keine Unterbrechung mehr: ein halber Tausch ist schlimmer als keiner.
trap '' TERM INT
mkdir -p "$alt/lib"
mv /usr/local/bin/ollama "$alt/ollama" 2>/dev/null
[ -d /usr/local/lib/ollama ] && mv /usr/local/lib/ollama "$alt/lib/ollama"
mv "$neu/bin/ollama" /usr/local/bin/ollama
mv "$neu/lib/ollama" /usr/local/lib/ollama
chmod 755 /usr/local/lib/ollama
find /usr/local/lib/ollama -type d -exec chmod 755 {} +
systemctl restart ollama
ok=0
for i in $(seq 1 30); do
  if curl -fs http://127.0.0.1:11434/api/version >/dev/null 2>&1; then ok=1; break; fi
  sleep 1
done
if [ "$ok" = "1" ]; then
  log "ollama antwortet wieder: $(curl -fs http://127.0.0.1:11434/api/version)"
  rm -rf "$alt"; aufraeumen
  stand_setzen "done 0"
else
  log "ollama antwortet nach dem Tausch nicht -- lege die alte Fassung zurueck."
  rm -rf /usr/local/lib/ollama
  mv "$alt/lib/ollama" /usr/local/lib/ollama 2>/dev/null
  mv -f "$alt/ollama" /usr/local/bin/ollama 2>/dev/null
  systemctl restart ollama
  rm -rf "$alt"; aufraeumen
  stand_setzen "failed 1"
fi
exit 0
