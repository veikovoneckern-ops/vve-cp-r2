// WATCHDOG -- eigene Ansicht mit eigenem Knopf links, 1:1 aus dem alten Cockpit
// (healthAnsicht, dort am 10./11.09.2026 entstanden). Veiko ist oft nicht in der
// Naehe seines Setups und will auf einen Blick sehen, ob alles normal laeuft.
//
// Gliederung wie dort:
//   Zustand        ein Satz, der die Frage beantwortet, die man hier hat
//   Maschine       GPU-Temperatur, Notabschaltung (Kill Switch, Safety
//                  Shutdown & Reboot), letzter Notfall, Selbstheilung
//   Sicherheit     Firewall, fail2ban, SSH-Fehlversuche, Auto-Updates
//                  -- unabhaengig vom WatchDog (eigener Zeitgeber vve-sicherheit)
//   Aufbau und Wartung  dasselbe wie in der Server-Sektion (Veikos Wunsch vom 11.09.)
//
// Reine Anzeige. Die Knoepfe legen nur eine Anfrage in den Briefkasten des
// WatchDog-Dienstes (vve-health); der Ablauf selbst steht nur dort. Per Talk
// laesst sich die Notabschaltung bewusst NICHT ausloesen -- ein verhoertes Wort
// darf den Server nicht ausschalten.
import { html, useState, useEffect, Icon, bus, zeitText } from "./ui.js";
import { useDetails, AufbauReihe, AufbauDetail, Auftrag, Kachel, Gruppe, Zeile, BalkenZeile, WatchDogKnoepfe } from "./server.js";

const AKTION = { "dock-strom-aus": "Dock-Strom aus", "dock-strom-an-server-steckdosenzyklus": "Dock aus/an, Server-Steckdosenzyklus",
  "kill-switch": "Kill Switch", "dock-strom-aus-automatik-gestoppt": "Dock aus, Automatik angehalten" };

function alter(sek) {
  if (sek == null) return "unbekannt";
  return sek < 90 ? Math.round(sek) + " s" : Math.round(sek / 60) + " Min";
}

// Der Satz oben -- dieselbe Rangfolge wie im alten Cockpit.
export function wdZustand(wd) {
  if (!wd || !wd.bekannt) return { st: "unbekannt", text: "WatchDog nicht aktiv" };
  const nf = wd.notfall;
  if (wd.alter_sek != null && wd.alter_sek > 90) return { st: "unbekannt", text: `WatchDog antwortet seit ${alter(wd.alter_sek)} nicht mehr -- der Stand ist alt.` };
  if (wd.automatik_angehalten) return { st: "kritisch", text: "AUTOMATIK ANGEHALTEN -- wiederholter Notfall, braucht dich. Dock-Strom bleibt aus." };
  if (nf && Date.now() / 1000 - nf.zeit < 3600) return { st: "warnung", text: "Notfall wurde vor Kurzem automatisch behoben: " + nf.grund };
  if ((wd.reparaturen || []).length) return { st: "warnung", text: `${wd.reparaturen.length} Dienst${wd.reparaturen.length === 1 ? "" : "e"} automatisch neu gestartet, weil ${wd.reparaturen.length === 1 ? "er" : "sie"} nicht antwortete${wd.reparaturen.length === 1 ? "" : "n"}.` };
  return { st: "ok", text: "Alles normal." };
}

function Maschine({ wd, notfall }) {
  if (!wd || !wd.bekannt) {
    return html`<${Kachel} titel="WatchDog nicht aktiv" klasse="sv-voll">
      <p class="leise klein">vve-health meldet sich nicht -- entweder läuft der Dienst nicht (<code>systemctl status vve-health</code> auf dem Server prüfen) oder sein Stand ist nicht lesbar. Solange das so ist, gibt es keine automatische Erkennung und keine Notfall-Reaktion.</p></${Kachel}>`;
  }
  const nf = wd.notfall;
  const temps = wd.gpu_temps || [];
  return html`
    <${Kachel} titel="GPU-Temperatur" neben=${wd.alter_sek != null ? `Messung vor ${alter(wd.alter_sek)}` : ""}>
      ${temps.length ? temps.map((g) => html`<${BalkenZeile} name=${"Karte " + (g.index + 1)} wert=${g.temp_c + " °C"} p=${g.temp_c / (wd.schwelle_c || 90) * 100} warn=${85} krit=${95} />`)
        : html`<p class="leise klein">Keine Grafikkarte gemeldet -- entweder gerade stromlos (mitten im Notfallablauf?) oder nvidia-smi antwortet nicht.</p>`}
      <p class="leise klein sv-fuss">Notfallschwelle ${wd.schwelle_c || 90} °C -- nah an der Drosselgrenze der RTX 3090 (~90–93 °C). Im Alltag bleiben die Karten weit darunter.</p>
    </${Kachel}>
    <${Kachel} titel="Notabschaltung"><${WatchDogKnoepfe} wd=${wd} notfall=${notfall} />
      <p class="leise klein sv-fuss"><b>Kill Switch</b>: Dock- und Server-Strom sofort aus, ohne Abkühlpause und ohne Wiederanlauf. <b>Safety Shutdown & Reboot</b>: derselbe sichere Ablauf wie bei einem echten Notfall, von Hand ausgelöst.</p></${Kachel}>
    <${Kachel} titel="Letzter Notfall">${nf ? html`
        <${Zeile} name="Wann" wert=${zeitText(nf.zeit)} />
        <${Zeile} name="Grund" wert=${nf.grund} />
        <${Zeile} name="Aktion" wert=${AKTION[nf.aktion] || nf.aktion} s=${nf.wiederholt ? "kritisch" : ""} />
        ${(nf.temps || []).length > 0 && html`<${Zeile} name="Temperaturen damals" wert=${nf.temps.map((x) => x[1] + " °C").join(" · ")} />`}
        ${wd.automatik_angehalten && html`<div class="fehlerbox" style="margin-top:8px">Das war der zweite Notfall binnen 15 Minuten -- vermutlich kein Lastspitzen-Problem mehr, sondern ein echter Kühlungsdefekt. Die Automatik hat angehalten, Dock-Strom bleibt AUS, bis du das geprüft hast. Zurücksetzen auf dem Server: <code>~/vve-health/health-status.json</code> löschen.</div>`}`
      : html`<p class="leise klein">Noch keiner.</p>`}</${Kachel}>
    <${Kachel} titel="Selbstheilung">${(wd.reparaturen || []).length
      ? html`<p class="leise klein">Gerade automatisch repariert:</p>${wd.reparaturen.map((r) => html`<${Zeile} name=${r} wert="" />`)}`
      : html`<p class="leise klein">Ollama, Caddy und ComfyUI antworten. Fällt einer aus, startet der WatchDog ihn von selbst neu.</p>`}</${Kachel}>`;
}

function Sicherheit({ s }) {
  const sich = (s && s.sicherheit) || { bekannt: false };
  if (!sich.bekannt) {
    return html`<${Kachel} titel="Sicherheits-Check nicht aktiv" klasse="sv-voll">
      <p class="leise klein">vve-sicherheit meldet sich nicht -- der Zeitgeber läuft nicht (<code>systemctl status vve-sicherheit.timer</code> auf dem Server prüfen).</p></${Kachel}>`;
  }
  const offen = (sich.ufw && sich.ufw.offene_regeln) || [];
  const gesperrt = (sich.fail2ban && sich.fail2ban.gesperrt) || [];
  const fehl = sich.ssh_fehlgeschlagen_24h || 0;
  const unvoll = !sich.ufw || !sich.ufw.lesbar || !sich.fail2ban || !sich.fail2ban.lesbar;
  const [st, kopf] = offen.length ? ["kritisch", `${offen.length} Firewall-Regel${offen.length === 1 ? "" : "n"} erlauben Zugriff von ÜBERALL -- das sollte nicht sein.`]
    : unvoll ? ["warnung", "Prüfung unvollständig -- die Lese-Freigabe für ufw oder fail2ban fehlt."]
    : fehl > 20 ? ["warnung", `${fehl} fehlgeschlagene SSH-Anmeldeversuche in 24 Stunden.`]
    : ["ok", "Kein Fund -- Firewall eng, keine Sperren nötig."];
  return html`
    <${Kachel} titel="Befund" neben=${sich.alter_sek != null ? `geprüft vor ${alter(sich.alter_sek)}` : ""}>
      <div class=${"wd-befund " + st}><i class=${"kopf-ampel " + st}></i><b>${kopf}</b></div>
      ${unvoll && html`<p class="leise klein">Ohne die Freigabe in <code>/etc/sudoers.d/vve-security-status</code> kann der Check die Firewall nicht wirklich einsehen.</p>`}
      <p class="leise klein sv-fuss">Seit SSH im September monatelang dem ganzen Internet offenstand, prüft vve-sicherheit alle fünf Minuten nach. Es greift nirgends ein.</p>
    </${Kachel}>
    <${Kachel} titel="Im Einzelnen">
      <${Zeile} name="Firewall (ufw)" wert=${sich.ufw && sich.ufw.aktiv ? "aktiv" : "AUS"} s=${sich.ufw && sich.ufw.aktiv ? "" : "kritisch"} />
      <${Zeile} name="fail2ban" wert=${(sich.fail2ban && sich.fail2ban.aktiv ? "aktiv" : "AUS") + (gesperrt.length ? ` · ${gesperrt.length} gesperrt` : "")} s=${sich.fail2ban && sich.fail2ban.aktiv ? "" : "kritisch"} />
      <${Zeile} name="SSH-Fehlversuche (24 h)" wert=${fehl} s=${fehl > 20 ? "warnung" : ""} />
      <${Zeile} name="Auto-Updates" wert=${sich.unattended_upgrades_aktiv ? "aktiv" : "AUS"} s=${sich.unattended_upgrades_aktiv ? "" : "warnung"} />
      ${gesperrt.length > 0 && html`<p class="leise klein">Gerade gesperrt: ${gesperrt.join(", ")}</p>`}
    </${Kachel}>
    ${offen.length > 0 && html`<${Kachel} titel="Betroffene Regeln">${offen.map((z) => html`<div class="mono klein">${z}</div>`)}</${Kachel}>`}`;
}

export function WatchDog() {
  const d = useDetails({ mitSystem: false });
  const { det, notfall, wdLaden } = d;
  const [teil, setTeil] = useState(null);
  const wd = det && det.watchdog;
  const s = det ? det.status : null;
  // Temperaturen im 8-Sekunden-Takt wie im alten Cockpit; der Rest im 20-Sekunden-Takt von useDetails.
  useEffect(() => { const i = setInterval(() => { if (!document.hidden) wdLaden(); }, 8000); return () => clearInterval(i); }, []);
  const z = wdZustand(wd);
  // Talk weiss, dass Veiko auf den WatchDog schaut (gespraech.kontext_text).
  useEffect(() => { bus.sende("talk-kontext", { art: "watchdog", id: "watchdog", titel: "WatchDog" }); return () => bus.sende("talk-kontext", null); }, []);
  return html`<div class="sv-innen wd">
    <div class=${"wd-kopf " + z.st}>
      <i class=${"kopf-ampel " + (z.st === "unbekannt" ? "" : z.st)}></i>
      <div><b>${det ? z.text : "Stand wird geholt …"}</b>
        ${wd && wd.bekannt && html`<span class="leise klein">Letzter Durchlauf vor ${alter(wd.alter_sek)} · Automatik ${wd.automatik_angehalten ? "ANGEHALTEN" : wd.auto_an ? "an" : "AUS (nur Beobachtung)"}</span>`}</div>
      <span class="luecke"></span>
      <button class="btn klein" onClick=${() => { d.detLaden(true); wdLaden(); }}><${Icon} n="neu_laden" g=${12} />Neu prüfen</button>
    </div>
    ${!det ? html`<div class="lade">WatchDog und Sicherheits-Check werden gefragt …</div>` : html`
      <${Gruppe} titel="Maschine" unter="GPU-Temperatur und Notfall-Automatik"><${Maschine} wd=${wd} notfall=${notfall} /></${Gruppe}>
      <${Gruppe} titel="Sicherheit" unter="Firewall, Anmeldeversuche, Auto-Updates"><${Sicherheit} s=${s} /></${Gruppe}>`}
    <div class="sv-gruppe"><b>Aufbau und Wartung</b><em>dasselbe wie in der Server-Sektion oben</em></div>
    <${Auftrag} a=${det && det.auftrag} />
    <${AufbauReihe} d=${d} beiKlick=${setTeil} />
    ${teil && s && html`<${AufbauDetail} teil=${teil} s=${s} karten=${det && det.karten} wd=${wd} notfall=${notfall} zu=${() => setTeil(null)} />`}
  </div>`;
}
