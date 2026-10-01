// SYSTEM -- die Maschine, ein Stockwerk unter der taeglichen Arbeit.
// Liest dieselben Quellen wie das alte Cockpit (vve-status, Ollama), schreibt
// aber nichts am Server: Updates, Sicherungen und WatchDog bleiben vorerst im
// alten Cockpit, das dafuer gebaut und geprueft ist.
import { html, useState, Icon, Leer, toast, fehlerMelden, aktualisieren, zeitText, useAbruf, bus } from "./ui.js";
import { api } from "./api.js";
import { useEffect } from "./ui.js";

function Wert({ name, wert, warn }) {
  return html`<div class="messwert"><span class="leise">${name}</span><b style=${warn ? "color:var(--signal)" : ""}>${wert ?? "nicht verfügbar"}</b></div>`;
}

function gpus(s) {
  if (!s || !s.gpu_nvidia) return [];
  return String(s.gpu_nvidia).trim().split("\n").map((z) => {
    const t = z.split(",").map((x) => x.trim());
    return { name: t[0], temp: t[1], last: t[2], belegt: t[3], gesamt: t[4], watt: t[5] };
  });
}

export function System({ konto, thema }) {
  const [d, laden] = useAbruf("/system", 30000, []);
  const [laeuft, setLaeuft] = useState("");
  useEffect(() => { bus.sende("talk-kontext", null); }, []);
  if (!d) return html`<div class="seite"><div class="lade">Lade Systemstand …</div></div>`;
  const s = d.status || {};
  const g = d.stab || {};
  const e = d.einstellungen || {};
  async function abgleich() {
    setLaeuft("abgleich");
    try {
      const r = await api("/system/abgleich", { methode: "POST" });
      const n = r.neu; const summe = Object.values(n).reduce((a, b) => a + b, 0);
      toast(summe ? `Übernommen: ${n.projekte} Projekte, ${n.aufgaben} Aufgaben, ${n.notizen + n.plaud} Notizen, ${n.vorgaenge} Akten.` : "Nichts Neues im alten Cockpit.");
      laden(); aktualisieren();
    } catch (x) { fehlerMelden(x); }
    setLaeuft("");
  }
  async function durchgang() {
    try { await api("/system/durchgang", { methode: "POST" }); toast("Stab-Durchgang angestoßen."); setTimeout(laden, 4000); } catch (x) { fehlerMelden(x); }
  }
  const temps = s.temps_c || {};
  return html`<div class="seite">
    <div class="sys-raster">
      <section class="karte"><div class="karte-kopf"><h3>Stab-Pipeline</h3></div>
        <${Wert} name="Stab" wert=${g.stab_aktiv ? "an" : "aus"} />
        <${Wert} name="Letzter Durchgang" wert=${g.letzter_lauf ? zeitText(g.letzter_lauf) : "noch keiner"} />
        <${Wert} name="Gerade" wert=${g.laeuft ? g.laeuft.was : "nichts"} />
        <${Wert} name="Plaud-Abruf (alter Dienst)" wert=${g.sync ? zeitText(g.sync) : "unbekannt"} warn=${g.sync && Date.now() / 1000 - g.sync > 1800} />
        <${Wert} name="Letzte Notiz" wert=${g.letzte_datei ? zeitText(g.letzte_datei) : "unbekannt"} />
        ${g.letzter_fehler && html`<div class="fehlerbox" style="margin-top:8px">${g.letzter_fehler}</div>`}
        <div class="knopfreihe" style="margin-top:10px"><button class="btn klein" onClick=${durchgang}><${Icon} n="play" g=${13} />Jetzt einen Durchgang</button></div>
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Maschine</h3>${s.host && html`<span class="leise klein rechts">${s.host.uptime}</span>`}</div>
        ${d.status ? html`
          <${Wert} name="Prozessor" wert=${temps.cpu != null ? `${temps.cpu} °C · Last ${s.host ? s.host.load[0].toFixed(2) : "?"}` : null} />
          <${Wert} name="Arbeitsspeicher" wert=${s.memory_mb ? `${Math.round(s.memory_mb.used / 1024)} von ${Math.round(s.memory_mb.total / 1024)} GB` : null} />
          <${Wert} name="Platte" wert=${s.disk_gb ? `${Math.round(s.disk_gb.free)} GB frei` : null} />
          ${gpus(s).map((x, i) => html`<${Wert} name=${"Grafikkarte " + (i + 1)} wert=${`${x.temp} °C · ${x.last} · ${x.belegt} von ${x.gesamt}`} warn=${+x.temp >= 80} />`)}
          ${s.power && s.power.server && html`<${Wert} name="Strom Server / Docks" wert=${`${Math.round(s.power.server.watt)} W / ${Math.round((s.power.dock || {}).watt || 0)} W`} />`}
          <${Wert} name="Netz" wert=${s.network ? (s.network.wlan ? `WLAN ${s.network.wlan.ssid}` : "LAN") : null} />
          <${Wert} name="Updates offen" wert=${s.updates ? `${s.updates.pending}${s.updates.reboot_required ? " · Neustart fällig" : ""}` : null} />`
          : html`<${Leer}>Der Status-Dienst (vve-status) antwortet nicht.</${Leer}>`}
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Modelle</h3><span class="pill rechts">${d.modelle.length}</span></div>
        <${Wert} name="Gerade geladen" wert=${d.geladen.length ? d.geladen.map((m) => m.name).join(", ") : "keines"} />
        <div style="margin-top:6px;display:flex;flex-wrap:wrap;gap:5px">${d.modelle.map((m) => html`<span class="pill">${m}</span>`)}</div>
        <p class="leise klein" style="margin-top:8px">Welches Mitglied womit rechnet, stellst du unter Team ein.</p>
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Stimme</h3></div>
        <${Wert} name="Spracherkennung (Whisper)" wert=${d.stimme.whisper ? `bereit · Modell ${d.stimme.modell}${d.stimme.geladen.length ? " · geladen auf " + d.stimme.geladen.join(", ") : ""}` : d.stimme.grund} warn=${!d.stimme.whisper} />
        <${Wert} name="Mikrofon im Browser" wert=${window.isSecureContext ? "möglich (sichere Verbindung)" : "nicht möglich: Seite nicht über https geöffnet"} warn=${!window.isSecureContext} />
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Daten dieser Fassung</h3></div>
        ${Object.entries(d.db).map(([k, v]) => html`<${Wert} name=${k[0].toUpperCase() + k.slice(1)} wert=${v} />`)}
        <${Wert} name="Letzter Abgleich mit dem alten Cockpit" wert=${e.letzter_abgleich ? zeitText(e.letzter_abgleich) : "nie"} />
        <div class="knopfreihe" style="margin-top:10px">
          <button class="btn klein" disabled=${laeuft === "abgleich"} onClick=${abgleich} title="Holt nur, was es hier noch nicht gibt. Überschreibt nichts.">
            <${Icon} n="neu_laden" g=${13} />${laeuft === "abgleich" ? "Gleiche ab …" : "Mit altem Cockpit abgleichen"}</button></div>
        <p class="leise klein" style="margin-top:8px">Liest das alte Cockpit nur. Was du hier änderst, bleibt hier, und umgekehrt.</p>
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Pflege und Sicherheit</h3></div>
        <p class="leise klein">Updates, Sicherungen, Firmware, WatchDog und Kill Switch laufen vorerst weiter im alten Cockpit. Dort sind sie gebaut und geprüft.</p>
        ${s.sicherheit && html`<${Wert} name="Firewall" wert=${s.sicherheit.ufw && s.sicherheit.ufw.aktiv ? (s.sicherheit.ufw.offene_regeln.length ? `${s.sicherheit.ufw.offene_regeln.length} offene Regeln` : "aktiv, nichts offen") : "nicht lesbar"} warn=${s.sicherheit.ufw && s.sicherheit.ufw.offene_regeln.length} />`}
        ${s.health && html`<${Wert} name="WatchDog" wert=${s.health.automatik_angehalten ? "angehalten" : `aktiv · Schwelle ${s.health.schwelle_c} °C`} warn=${s.health.automatik_angehalten} />`}
        <a class="btn klein" style="margin-top:10px" href=${d.alt_cockpit} target="_blank" rel="noopener"><${Icon} n="extern" g=${13} />Altes Cockpit öffnen</a>
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Einstellungen</h3></div>
        <${Wert} name="Angemeldet als" wert=${konto.benutzer} />
        <div class="knopfreihe" style="margin-top:10px">
          <button class="btn klein" onClick=${thema}><${Icon} n="mond" g=${13} />Hell / Dunkel</button>
          <button class="btn klein" onClick=${() => { try { localStorage.removeItem("vvec_thema"); } catch (x) { /* egal */ } delete document.documentElement.dataset.theme; }}>Wie das System</button>
          <button class="btn klein gefahr" onClick=${() => api("/konto/abmelden", { methode: "POST" }).then(() => location.reload())}><${Icon} n="raus" g=${13} />Abmelden</button>
        </div>
      </section>
    </div>
  </div>`;
}
