# server/ — was als root bzw. systemweit auf vveorgxais läuft

Alles hier liegt **nicht** im Benutzerdienst `vve-cp-r2`, sondern systemweit auf
dem Server. Bis zum 23.10.2026 lag der Quelltext nur im alten Repo (`vve-cp`,
Ordner `dienste/` und `systemd/`) — mit dem Löschen des alten Cockpits wäre er
weg gewesen, und die Dienste liefen danach als unversionierte Einzelstücke unter
`/usr/local/bin`. Deshalb liegen sie jetzt hier.

**Es gibt keine automatische Auslieferung.** `git pull` auf dem Server ändert an
diesen Diensten nichts; die laufenden Kopien gehören root und werden nur durch
den Installationsbefehl unten ersetzt. Das ist Absicht und derselbe Gedanke wie
beim Ollama-Update-Skript: weder das Cockpit noch Neo sollen Code umschreiben
können, der mit root-Rechten oder an der Stromversorgung arbeitet.

Stand der Kopien: **identisch mit dem, was am 23.10.2026 auf dem Server lief**
(vom Server geholt, nicht aus dem alten Repo — dort fehlten die Units von
`vve-status` und `vve-admin`).

## Die Dienste

| Dienst | läuft als | was er tut | wer ihn braucht |
|---|---|---|---|
| `vve-status` | vveadmin | Telemetrie als JSON auf 127.0.0.1:9099 (`/status`): CPU, RAM, GPUs, Ollama, Docker, Strom der Shelly-Dosen, Firmware, Zeitgeber | **neues Cockpit** (`konfig.STATUS_URL`), Server-Ansicht, Strom, Empfehlungen |
| `vve-health` | vveadmin | Watchdog: Dienste neu starten, Notabschaltung bei GPU-Temperatur, Kill Switch / Safety Reboot auf Anfrage | **neues Cockpit** (Briefkasten `~/vve-health/notfall-anfrage.json`, Stand `health-status.json`) |
| `vve-sicherheit` (+ `.timer`, 5 Min.) | vveadmin | ufw, fail2ban, SSH-Fehlversuche, unattended-upgrades → `~/vve-health/sicherheit-status.json` | neues Cockpit über `vve-status` |
| `vve-rgb` | **root** (braucht `/dev/i2c-*`) | RGB-Leisten der Karten nach Auslastung | niemand — läuft für sich |
| `vve-admin` | vveadmin | schreibende Aktionen auf 127.0.0.1:9098 mit Token (`/apt/*`, `/model/*`, `/system/reboot`, `/rgb/on|off`) | **nur das alte Cockpit**. Das neue ruft apt und reboot selbst über `sudo -n` auf |

## Installieren bzw. eine geänderte Fassung einspielen

Auf dem Server, im Klon `~/vve-cp-r2` (fragt einmal nach dem Passwort):

```bash
cd ~/vve-cp-r2 && sudo install -m 755 -o root -g root server/dienste/vve-*.py /usr/local/bin/ && sudo install -m 644 -o root -g root server/systemd/vve-* /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart vve-status vve-health vve-rgb && sudo systemctl restart vve-sicherheit.timer
```

Geklappt hat es, wenn `systemctl is-active vve-status vve-health vve-rgb vve-sicherheit.timer`
viermal `active` meldet. `vve-admin` steht bewusst nicht in der Neustart-Liste —
siehe unten.

## Was vor dem Löschen des alten Cockpits noch geändert werden muss

Geprüft am 23.10.2026. Diese Stellen hängen noch an `/etc/vvec` bzw. `/var/lib/vvec`:

1. **`vve-status` liest die Shelly-Adressen aus `/etc/vvec/vvec.env`**
   (`VVEC_SHELLY_SERVER`, `VVEC_SHELLY_DOCK`, `_strom_ziel()`). Ist die Datei weg,
   fällt er auf die Gerätenamen `MINISFORUM`/`RTXeGPU` zurück, und ob die im Netz
   auflösen, ist nicht geprüft — die Stromwerte könnten still fehlen. Die beiden
   Werte gehören vorher als `Environment=` in `vve-status.service`.
2. **`vve-status` fragt die Zeitgeber des alten Cockpits ab** (`ZEITGEBER`,
   `vvec-*.timer`). Das neue Cockpit meldet jeden davon, der geladen, aber nicht
   aktiv ist, als „Zeitgeber läuft nicht" — wer die alten Timer nur *abschaltet*
   statt sie zu entfernen, bekommt also Warnungen. Die Liste gehört auf die
   Zeitgeber, die dann noch zählen (`vve-sicherheit.timer`).
3. **`vve-health` liest zusätzlich den alten Briefkasten**
   `/var/lib/vvec/health-notfall-anfrage.json`. Fehlt er, passiert nichts
   Schlimmes (es gibt dann nur keine Anfrage von dort); aufräumen kann man ihn
   trotzdem.
4. **`vve-status` sieht nach Firmware-Läufen in `/var/lib/vvec/wartung/lauf/`.**
   Fehlt der Ordner, wird nur nicht sofort neu geprüft, sondern nach sechs Stunden.
5. **`vve-admin`** wird mit dem alten Cockpit überflüssig. Einzige Funktion, die
   es sonst nirgends gibt: RGB an/aus (`/etc/vve/rgb.state`). Abschalten mit
   `sudo systemctl disable --now vve-admin`, Datei liegt hier zum Nachlesen.
