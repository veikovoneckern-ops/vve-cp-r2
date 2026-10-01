// SYSTEM -- wieder ausfuehrlich, wie die Server-Sektion des alten Cockpits:
// Empfehlungen (einspielen / nicht einspielen / Achtung), Aufbau-Schaubild,
// Updates im Einzelnen, Dienste und Zeitgeber, Modelle, Sicherungen, Sicherheit.
// Alles aus Live-Daten; was nicht abrufbar ist, steht als "nicht verfuegbar" da.
import { html, useState, useEffect, Icon, Leer, toast, fehlerMelden, aktualisieren, zeitText, useAbruf, bus, kopieren } from "./ui.js";
import { api } from "./api.js";

function Wert({ name, wert, warn }) {
  return html`<div class="messwert"><span class="leise">${name}</span><b style=${warn ? "color:var(--signal)" : ""}>${wert ?? "nicht verfügbar"}</b></div>`;
}

export function gpus(s) {
  if (!s || !s.gpu_nvidia) return [];
  return String(s.gpu_nvidia).trim().split("\n").map((z) => {
    const t = z.split(",").map((x) => x.trim());
    const mib = (x) => parseFloat(String(x || "0")) || 0;
    return { name: t[0], temp: +t[1], last: parseInt(t[2]) || 0, belegt: mib(t[3]), gesamt: mib(t[4]), watt: parseFloat(t[5]) || 0 };
  });
}

const STUFE = { einspielen: ["gruen", "einspielen"], nicht: ["", "nicht einspielen"], achtung: ["rot", "Achtung"], info: ["blau", "Hinweis"] };

function Empfehlung({ e, auftrag, starten }) {
  const [frage, setFrage] = useState(false);
  const [st, label] = STUFE[e.stufe] || ["", e.stufe];
  const laeuft = auftrag && auftrag.laeuft;
  return html`<div class=${"empf " + e.stufe}>
    <div class="empf-kopf"><span class=${"pill " + st}>${label}</span></div>
    <b>${e.titel}</b>
    <p class="leise klein empf-text" title=${e.warum}>${e.warum}</p>
    ${e.befehl && html`<div class="befehl"><pre>${e.befehl}</pre>
      <button class="btn klein geist icon" title="Befehl kopieren" aria-label="Befehl kopieren" onClick=${async () => { if (await kopieren(e.befehl)) toast("Befehl kopiert. Im Terminal auf dem Server einfügen."); }}><${Icon} n="kopie" g=${13} /></button></div>`}
    ${e.aktion && (frage
      ? html`<div class="knopfreihe"><span class="klein">${e.aktion.art === "neustart" ? "Wirklich neu starten? Alles bricht kurz ab." : "Jetzt einspielen?"}</span>
          <button class="btn klein gefahr voll" onClick=${() => { setFrage(false); starten(e.aktion.art); }}>Ja, ${e.aktion.text.toLowerCase()}</button>
          <button class="btn klein geist" onClick=${() => setFrage(false)}>Abbrechen</button></div>`
      : html`<div><button class="btn klein gefahr" disabled=${laeuft} onClick=${() => setFrage(true)}>${laeuft ? "läuft schon ein Auftrag" : e.aktion.text}</button></div>`)}
  </div>`;
}

function farbeTemp(t, warn, krit) { return t >= krit ? "var(--signal)" : t >= warn ? "var(--amber)" : "var(--sea)"; }

function Aufbau({ s }) {
  if (!s) return html`<${Leer}>Der Status-Dienst antwortet nicht.</${Leer}>`;
  const t = s.temps_c || {};
  const g = gpus(s);
  const p = s.power || {};
  const mem = s.memory_mb || {};
  const netz = s.network || {};
  const kasten = (x, y, w, h) => html`<rect x=${x} y=${y} width=${w} height=${h} rx="10" class="sb-kasten" />`;
  const zeile = (x, y, txt, cls = "sb-text") => html`<text x=${x} y=${y} class=${cls}>${txt}</text>`;
  const dose = (x, d, name) => html`<g>
    ${kasten(x, 286, 280, 50)}
    <circle cx=${x + 22} cy="311" r="8" class="sb-dose" />
    ${zeile(x + 40, 306, name, "sb-titel")}
    ${d ? zeile(x + 40, 325, `${Math.round(d.watt)} W · ${Math.round(d.volt)} V · Dose ${d.temp_c} °C · ${d.kwh?.toFixed(1)} kWh`) : zeile(x + 40, 325, "keine Messung")}
  </g>`;
  return html`<div class="sb-wrap"><svg viewBox="0 0 740 346" class="sb" role="img" aria-label="Aufbau des Servers">
    ${kasten(10, 20, 300, 236)}
    ${zeile(26, 46, "Mini-PC · MINISFORUM AI X1 Pro", "sb-titel")}
    ${zeile(26, 70, (s.cpu || {}).model ? "Ryzen AI 9 HX 370 · " + s.cpu.cores + " Kerne" : "Prozessor")}
    <text x="26" y="96" class="sb-text">Prozessor <tspan class="sb-wert" fill=${farbeTemp(t.cpu || 0, 75, 90)}>${t.cpu ?? "?"} °C</tspan> · Last ${s.host ? s.host.load[0].toFixed(2) : "?"}</text>
    ${zeile(26, 120, `Arbeitsspeicher ${Math.round((mem.used || 0) / 1024)} / ${Math.round((mem.total || 0) / 1024)} GB`)}
    <rect x="26" y="128" width="268" height="6" rx="3" class="sb-bahn" /><rect x="26" y="128" width=${268 * Math.min(1, (mem.used || 0) / (mem.total || 1))} height="6" rx="3" class="sb-fuell" />
    <text x="26" y="156" class="sb-text">NVMe <tspan class="sb-wert" fill=${farbeTemp(t.nvme || 0, 60, 70)}>${t.nvme ?? "?"} °C</tspan> · ${s.disk_gb ? Math.round(s.disk_gb.free) + " GB frei" : ""}</text>
    ${zeile(26, 180, netz.wlan ? `WLAN ${netz.wlan.ssid} · ${netz.wlan.signal_dbm} dBm · ${netz.wlan.bitrate_mbit} Mbit/s` : netz.interface ? `LAN · ${netz.interface}` : "Netz unbekannt")}
    ${zeile(26, 204, `Tailnet ${netz.tailscale_ip || "?"} · LAN ${netz.lan_ip || "?"}`)}
    ${zeile(26, 228, (s.host || {}).uptime ? "läuft seit " + s.host.uptime.replace("up ", "") : "")}
    ${g.slice(0, 2).map((k, i) => {
      const y = 20 + i * 124;
      return html`<g key=${i}>
        <path d=${`M310 ${110 + i * 40} C 370 ${110 + i * 40}, 370 ${y + 55}, 430 ${y + 55}`} class="sb-leitung" />
        ${kasten(430, y, 300, 110)}
        ${zeile(446, y + 26, `RTX 3090 · Dock ${i + 1}`, "sb-titel")}
        <text x="446" y=${y + 50} class="sb-text"><tspan class="sb-wert" fill=${farbeTemp(k.temp, 80, 90)}>${k.temp} °C</tspan> · Last ${k.last} % · ${Math.round(k.watt)} W</text>
        ${zeile(446, y + 74, `VRAM ${(k.belegt / 1024).toFixed(1)} / ${(k.gesamt / 1024).toFixed(0)} GB`)}
        <rect x="446" y=${y + 84} width="268" height="6" rx="3" class="sb-bahn" /><rect x="446" y=${y + 84} width=${268 * Math.min(1, k.belegt / (k.gesamt || 1))} height="6" rx="3" class="sb-fuell lila" />
      </g>`;
    })}
    ${g.length === 0 && zeile(446, 80, "Keine Grafikkarte gemeldet")}
    <path d="M150 286 V256" class="sb-strom" /><path d="M580 286 V266 H736 V75 H730 M736 199 H730" class="sb-strom" />
    ${dose(10, p.server, "Steckdose Server")}
    ${dose(450, p.dock, "Steckdose Docks")}
  </svg></div>`;
}

function Updates({ u }) {
  if (!u) return null;
  const ein = u.pakete.filter((p) => p.einspielbar);
  const gest = u.pakete.filter((p) => !p.einspielbar);
  const Zeile = ({ p }) => html`<div class="zeile"><div class="haupt-text"><b class="mono klein">${p.name}</b>${p.sicherheit ? html` <span class="pill rot">Sicherheit</span>` : ""}
      <div class="leise klein">${p.beschreibung || ""}</div></div><span class="neben mono">${p.von} → ${p.nach}</span></div>`;
  return html`<div class="raster zwei">
    <section class="karte"><div class="karte-kopf"><h3>Würde apt jetzt einspielen</h3><span class="pill gruen">${ein.length}</span></div>
      ${ein.length ? ein.map((p) => html`<${Zeile} p=${p} />`) : html`<${Leer}>Nichts einzuspielen.</${Leer}>`}</section>
    <section class="karte"><div class="karte-kopf"><h3>Gestaffelt zurückgehalten</h3><span class="pill">${gest.length}</span></div>
      ${gest.length ? gest.map((p) => html`<${Zeile} p=${p} />`) : html`<${Leer}>Nichts zurückgehalten.</${Leer}>`}
      <p class="leise klein" style="margin-top:8px">Ubuntu gibt diese Fassungen schrittweise frei. Nicht erzwingen; sie kommen von selbst.</p></section>
  </div>`;
}

function Software({ s }) {
  if (!s) return null;
  const sv = s.services || {};
  const timer = s.timers || {};
  const NAMEN = { "vvec-plaud-sync.timer": "Plaud-Abruf", "vvec-vorgang.timer": "Vorgänge (altes Cockpit)", "vvec-board.timer": "Beirat auffrischen",
    "vvec-suche-index.timer": "Suchindex", "vvec-sicherung-inhalt.timer": "Sicherung Inhalt", "vvec-sicherung-server.timer": "Sicherung Server", "vvec-backup.timer": "restic (nicht eingerichtet)" };
  return html`<div class="raster drei">
    <section class="karte"><div class="karte-kopf"><h3>Dienste</h3></div>
      ${Object.entries(sv).map(([k, v]) => html`<div class="messwert"><span>${k}</span><b style=${/active|running/i.test(v) ? "color:var(--sea)" : "color:var(--signal)"}>${v}</b></div>`)}
      ${(s.docker || []).map((c) => { const [n, z] = String(c).split("|"); return html`<div class="messwert"><span>${n} <span class="leise klein">Container</span></span><b style=${/^Up/.test(z) ? "color:var(--sea)" : "color:var(--signal)"}>${z}</b></div>`; })}
    </section>
    <section class="karte"><div class="karte-kopf"><h3>Zeitgeber</h3></div>
      ${Object.entries(timer).map(([k, t]) => html`<div class="messwert"><span>${NAMEN[k] || k}</span>
        <b style=${!t.geladen ? "color:var(--ink-4)" : t.aktiv === "active" ? "" : "color:var(--signal)"}>${!t.geladen ? "fehlt" : t.zuletzt ? zeitText(t.zuletzt) : t.aktiv}</b></div>`)}
    </section>
    <section class="karte"><div class="karte-kopf"><h3>Fassungen</h3></div>
      ${Object.entries(s.versions || {}).map(([k, v]) => html`<${Wert} name=${k} wert=${v} />`)}
      ${Object.entries(s.ollama_conf || {}).map(([k, v]) => html`<${Wert} name=${k.replace("OLLAMA_", "").toLowerCase()} wert=${v} />`)}
    </section>
  </div>`;
}

function Modelle({ liste, neueste, s }) {
  if (!liste) return null;
  const ges = gpus(s).reduce((a, k) => a + k.gesamt / 1024, 0) || 48;
  return html`<section class="karte"><div class="karte-kopf"><h3>Modelle</h3><span class="pill">${liste.length}</span>
      ${s && s.versions && html`<span class="leise klein rechts">${s.versions.ollama}${neueste ? " · neueste " + neueste : ""}</span>`}</div>
    <div class="tabelle-wrap"><table class="tabelle"><thead><tr><th>Modell</th><th>Größe</th><th>Passt auf</th><th>Im Team</th><th>Jetzt</th></tr></thead><tbody>
      ${liste.map((m) => html`<tr><td class="mono">${m.name}</td><td>${m.groesse}</td>
        <td class="leise">${m.gb === 0 ? "?" : m.gb * 1.08 < 22.5 ? "eine Karte" : m.gb * 1.08 < ges - 1.5 ? "beide Karten" : "mit Auslagerung"}</td>
        <td>${m.team.join(", ") || html`<span class="leise">—</span>`}</td>
        <td>${m.geladen ? html`<span class="pill lila">geladen${m.prozessor ? " · " + m.prozessor : ""}</span>` : ""}</td></tr>`)}
    </tbody></table></div>
  </section>`;
}

function Auftrag({ a }) {
  if (!a || (!a.laeuft && !a.ende)) return null;
  const titel = a.art === "updates" ? "Updates einspielen" : "Neustart";
  return html`<section class="karte" style="margin-bottom:14px">
    <div class="karte-kopf"><h3>${titel}</h3>
      ${a.laeuft ? html`<span class="pill lila">läuft seit ${zeitText(a.start).replace("vor ", "")}</span>`
        : a.rc === 0 ? html`<span class="pill gruen">fertig ${zeitText(a.ende)}</span>` : html`<span class="pill rot">fehlgeschlagen (rc ${a.rc})</span>`}</div>
    <pre class="log">${a.log || "…"}</pre>
  </section>`;
}

export function System({ konto, thema }) {
  const [d, laden] = useAbruf("/system", 30000, []);
  const [det, setDet] = useState(null);
  const [laeuft, setLaeuft] = useState("");
  useEffect(() => { bus.sende("talk-kontext", null); }, []);
  const detLaden = (frisch) => api("/system/details" + (frisch ? "?frisch=1" : "")).then(setDet).catch(fehlerMelden);
  useEffect(() => { detLaden(false); const i = setInterval(() => { if (!document.hidden) detLaden(false); }, 20000); return () => clearInterval(i); }, []);
  useEffect(() => {
    if (!det || !det.auftrag || !det.auftrag.laeuft) return;
    const i = setInterval(async () => {
      try { const a = await api("/system/auftrag"); setDet((x) => ({ ...x, auftrag: a })); if (!a.laeuft) { clearInterval(i); detLaden(true); } } catch (e) { /* Neustart: Server weg */ }
    }, 2500);
    return () => clearInterval(i);
  }, [det && det.auftrag && det.auftrag.laeuft]);

  async function starten(art) {
    try { await api("/system/auftrag", { methode: "POST", daten: { art } }); toast(art === "neustart" ? "Server startet neu. In ein bis zwei Minuten ist er wieder da." : "Updates werden eingespielt. Den Fortschritt siehst du oben."); detLaden(false); } catch (e) { fehlerMelden(e); }
  }
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
  const s = det ? det.status : d && d.status;
  const g = d ? d.stab || {} : {};
  const e = d ? d.einstellungen || {} : {};
  const sich = det && det.sicherungen;

  return html`<div class="seite">
    <${Auftrag} a=${det && det.auftrag} />
    <h2 class="abschnitt">Empfehlungen ${det && html`<button class="btn klein geist" onClick=${() => detLaden(true)} title="apt und Fassungen frisch abfragen"><${Icon} n="neu_laden" g=${13} />Neu prüfen</button>`}</h2>
    ${!det ? html`<div class="lade">Prüfe Updates und Zustand …</div>`
      : det.empfehlungen.length ? html`<div class="empf-raster">${det.empfehlungen.map((x, i) => html`<${Empfehlung} key=${i} e=${x} auftrag=${det.auftrag} starten=${starten} />`)}</div>`
      : html`<div class="karte"><${Leer} titel="Nichts zu tun.">Keine Updates offen, alle Dienste laufen, Sicherungen sind frisch.</${Leer}></div>`}

    <h2 class="abschnitt">Aufbau</h2>
    <div class="raster zwei">
      <section class="karte"><${Aufbau} s=${s} /></section>
      <div>
        <section class="karte"><div class="karte-kopf"><h3>Sicherungen</h3></div>
          ${sich ? ["inhalt", "server"].map((k) => { const x = sich[k] || {}; return html`<${Wert} name=${k === "inhalt" ? "Inhalt (OneDrive)" : "Server (OneDrive)"}
            wert=${x.zeit ? `${x.zustand === "ok" ? "ok" : x.zustand} · ${zeitText(x.zeit)}` : "unbekannt"} warn=${x.zustand !== "ok" || (Date.now() / 1000 - (x.zeit || 0)) > 172800} />`; })
            : html`<${Wert} name="OneDrive" wert="Stand nicht lesbar" />`}
          <${Wert} name="Neue Fassung (lokal, täglich 03:30)" wert="daten/sicherungen" />
        </section>
        <section class="karte"><div class="karte-kopf"><h3>Sicherheit und WatchDog</h3></div>
          ${s && s.sicherheit ? html`
            <${Wert} name="Firewall" wert=${s.sicherheit.ufw && s.sicherheit.ufw.aktiv ? (s.sicherheit.ufw.offene_regeln.length ? s.sicherheit.ufw.offene_regeln.length + " offene Regeln" : "aktiv, nichts offen") : "nicht lesbar"} warn=${s.sicherheit.ufw && s.sicherheit.ufw.offene_regeln.length} />
            <${Wert} name="fail2ban" wert=${s.sicherheit.fail2ban && s.sicherheit.fail2ban.aktiv ? `aktiv · ${s.sicherheit.fail2ban.gesperrt.length} gesperrt` : "nicht aktiv"} />
            <${Wert} name="SSH-Fehlversuche (24 h)" wert=${s.sicherheit.ssh_fehlgeschlagen_24h} />
            <${Wert} name="Automatische Sicherheitsupdates" wert=${s.sicherheit.unattended_upgrades_aktiv ? "an" : "aus"} warn=${!s.sicherheit.unattended_upgrades_aktiv} />` : html`<${Wert} name="Sicherheit" wert="nicht gemeldet" />`}
          ${s && s.health && html`<${Wert} name="WatchDog" wert=${s.health.automatik_angehalten ? "angehalten" : `aktiv · Notfall ab ${s.health.schwelle_c} °C`} warn=${s.health.automatik_angehalten} />`}
          <p class="leise klein" style="margin-top:8px">Kill Switch und Notfall-Neustart bleiben im alten Cockpit.</p>
          <a class="btn klein" href=${(d && d.alt_cockpit) || "https://vveorgxais.tail4ca1ab.ts.net/"} target="_blank" rel="noopener"><${Icon} n="extern" g=${13} />Altes Cockpit</a>
        </section>
      </div>
    </div>

    <h2 class="abschnitt">Updates im Einzelnen</h2>
    ${det ? html`<${Updates} u=${det.updates} />` : html`<div class="lade">…</div>`}

    <h2 class="abschnitt">Software</h2>
    <${Software} s=${s} />

    <h2 class="abschnitt">Modelle</h2>
    ${det ? html`<${Modelle} liste=${det.modelle} neueste=${det.ollama_neueste} s=${s} />` : html`<div class="lade">…</div>`}

    <h2 class="abschnitt">Diese Fassung</h2>
    ${d && html`<div class="sys-raster">
      <section class="karte"><div class="karte-kopf"><h3>Stab-Pipeline</h3></div>
        <${Wert} name="Stab" wert=${g.stab_aktiv ? "an" : "aus"} />
        <${Wert} name="Letzter Durchgang" wert=${g.letzter_lauf ? zeitText(g.letzter_lauf) : "noch keiner"} />
        <${Wert} name="Gerade" wert=${g.laeuft ? g.laeuft.was : "nichts"} />
        <${Wert} name="Plaud-Abruf" wert=${g.sync ? zeitText(g.sync) : "unbekannt"} warn=${g.sync && Date.now() / 1000 - g.sync > 1800} />
        <${Wert} name="Letzte Notiz" wert=${g.letzte_datei ? zeitText(g.letzte_datei) : "unbekannt"} />
        ${g.letzter_fehler && html`<div class="fehlerbox" style="margin-top:8px">${g.letzter_fehler}</div>`}
        <div class="knopfreihe" style="margin-top:10px"><button class="btn klein" onClick=${async () => { await api("/system/durchgang", { methode: "POST" }); toast("Stab-Durchgang angestoßen."); }}><${Icon} n="play" g=${13} />Jetzt einen Durchgang</button></div>
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Stimme</h3></div>
        <${Wert} name="Spracherkennung" wert=${d.stimme.whisper ? `bereit · ${d.stimme.modell}${d.stimme.geladen.length ? " · " + d.stimme.geladen.join(", ") : ""}` : d.stimme.grund} warn=${!d.stimme.whisper} />
        <${Wert} name="Mikrofon im Browser" wert=${window.isSecureContext ? "möglich" : "nur über https"} warn=${!window.isSecureContext} />
        ${!window.isSecureContext && html`<div class="hinweisbox" style="margin-top:8px">Öffne das Cockpit über <b>https://vveorgxais.tail4ca1ab.ts.net:8443</b>.</div>`}
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Daten</h3></div>
        ${Object.entries(d.db).map(([k, v]) => html`<${Wert} name=${k[0].toUpperCase() + k.slice(1)} wert=${v} />`)}
        <${Wert} name="Abgleich mit altem Cockpit" wert=${e.letzter_abgleich ? zeitText(e.letzter_abgleich) : "nie"} />
        <div class="knopfreihe" style="margin-top:10px"><button class="btn klein" disabled=${laeuft === "abgleich"} onClick=${abgleich} title="Holt nur, was es hier noch nicht gibt.">
          <${Icon} n="neu_laden" g=${13} />${laeuft === "abgleich" ? "Gleiche ab …" : "Mit altem Cockpit abgleichen"}</button></div>
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Einstellungen</h3></div>
        <${Wert} name="Angemeldet als" wert=${konto.benutzer} />
        <div class="knopfreihe" style="margin-top:10px">
          <button class="btn klein" onClick=${thema}><${Icon} n="mond" g=${13} />Hell / Dunkel</button>
          <button class="btn klein" onClick=${() => { try { localStorage.removeItem("vvec_thema"); } catch (x) { /* egal */ } delete document.documentElement.dataset.theme; }}>Wie das System</button>
          <button class="btn klein gefahr" onClick=${() => api("/konto/abmelden", { methode: "POST" }).then(() => location.reload())}><${Icon} n="raus" g=${13} />Abmelden</button>
        </div>
      </section>
    </div>`}
  </div>`;
}
