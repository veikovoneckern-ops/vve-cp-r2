// SERVER-SEKTION -- klappt unter der Kopfzeile auf, wie im alten Cockpit.
// Gliederung 1:1 von dort uebernommen (Veiko, 01.10.: "damit bin ich gut
// zurechtgekommen und wusste, wo sich was befindet"):
//   Kopf: Host, seit wann, die Ampel
//   Aufbau-Schaubild | Updates, Empfehlungen und Sicherungen
//   Software: So kommen Sie herein · Verteiler · Dienste · Von selbst ·
//             Unterbau · Diese Fassung · Platte · Nach draussen
//   Womit Sie arbeiten:      Modelle · Eigener Bestand · Websuche · Stimme
//   Was die Maschine meldet: Temperaturen · Auslastung · Strom · RTX-LED
// Anders als dort: Kacheln einer Reihe sind gleich hoch und gleich breit
// (Raster statt Mehrspaltensatz -- Veikos Wunsch nach Symmetrie). Lange
// Inhalte (Modelle) scrollen in ihrer Kachel, statt die Reihe zu strecken.
//
// Alles aus Live-Daten. Was nicht gemeldet wird, steht als "nicht gemeldet"
// da -- ein grauer Punkt ist ehrlicher als ein geratener gruener.
import { html, useState, useEffect, Icon, Leer, Modal, toast, fehlerMelden, zeitText, kopieren } from "./ui.js";
import { api } from "./api.js";
import { useKopf, ampel, ledFarbe } from "./kopf.js";

export function gpus(s) {
  if (!s || !s.gpu_nvidia) return [];
  return String(s.gpu_nvidia).trim().split("\n").map((z) => {
    const t = z.split(",").map((x) => x.trim());
    const zahl = (x) => parseFloat(String(x || "0")) || 0;
    return { name: t[0], temp: zahl(t[1]), last: parseInt(t[2]) || 0, belegt: zahl(t[3]), gesamt: zahl(t[4]), watt: zahl(t[5]), luefter: t[6] };
  });
}

// ------------------------------------------------------------ Bausteine
function Kachel({ titel, neben, children, klasse = "" }) {
  return html`<section class=${"sv-kachel " + klasse}>
    <div class="sv-kachel-kopf"><h4>${titel}</h4>${neben && html`<span class="sv-neben">${neben}</span>`}</div>
    <div class="sv-kachel-leib">${children}</div>
  </section>`;
}
function Gruppe({ titel, unter, klasse = "", children }) {
  return html`<div class="sv-gruppe"><b>${titel}</b>${unter && html`<em>${unter}</em>`}</div>
    <div class=${"sv-raster " + klasse}>${children}</div>`;
}
function Zeile({ name, wert, s }) {
  return html`<div class="sv-zeile"><span>${name}</span><b class=${s || ""}>${wert ?? "nicht gemeldet"}</b></div>`;
}
function Balken({ p, warn = 80, krit = 92 }) {
  const w = Math.max(0, Math.min(100, p || 0));
  return html`<div class="sv-balken"><i class=${w >= krit ? "kritisch" : w >= warn ? "warnung" : ""} style=${`width:${w}%`}></i></div>`;
}
function BalkenZeile({ name, wert, p, warn, krit }) {
  return html`<div class="sv-bzeile"><div class="sv-zeile"><span>${name}</span><b>${wert}</b></div><${Balken} p=${p} warn=${warn} krit=${krit} /></div>`;
}
// Eine Zeile im Software-Schaubild: Punkt, Name, rechts eine Marke, darunter ein Satz.
function SwZ({ st, name, marke, satz, knopf }) {
  return html`<div class="sw-z"><i class=${"sw-punkt " + (st || "unbekannt")}></i>
    <div class="sw-z-txt"><div class="sw-z-kopf"><b>${name}</b>${marke && html`<span>${marke}</span>`}</div>
      ${satz && html`<div class="sw-z-satz">${satz}</div>`}${knopf}</div></div>`;
}
const zustand = (ok, schlecht) => (ok ? "ok" : schlecht ? "warnung" : "unbekannt");

// ------------------------------------------------------------ Aufbau
function farbeTemp(t, warn, krit) { return t >= krit ? "var(--signal)" : t >= warn ? "var(--amber)" : "var(--sea)"; }

function Aufbau({ s, beiKlick }) {
  if (!s) return html`<${Leer}>Der Status-Dienst antwortet nicht.</${Leer}>`;
  const t = s.temps_c || {};
  const g = gpus(s);
  const p = s.power || {};
  const mem = s.memory_mb || {};
  const netz = s.network || {};
  const funk = String(netz.interface || "").startsWith("wl");
  const kasten = (x, y, w, h) => html`<rect x=${x} y=${y} width=${w} height=${h} rx="10" class="sb-kasten" />`;
  const zeile = (x, y, txt, cls = "sb-text") => html`<text x=${x} y=${y} class=${cls}>${txt}</text>`;
  const dose = (x, d, name) => html`<g>
    ${kasten(x, 286, 280, 50)}
    <circle cx=${x + 22} cy="311" r="8" class="sb-dose" />
    ${zeile(x + 40, 306, name, "sb-titel")}
    ${d ? html`<text x=${x + 40} y="325" class="sb-text">${Math.round(d.watt)} W · ${Math.round(d.volt)} V · Dose <tspan class="sb-wert" fill=${farbeTemp(d.temp_c || 0, 60, 72)}>${d.temp_c} °C</tspan> · ${d.kwh != null ? d.kwh.toFixed(1) : "?"} kWh</text>` : zeile(x + 40, 325, "keine Messung")}
  </g>`;
  return html`<div class="sb-wrap"><svg viewBox="0 0 740 346" class="sb" role="img" aria-label="Aufbau des Servers">
    ${kasten(10, 20, 300, 236)}
    ${zeile(26, 46, "Mini-PC · MINISFORUM AI X1 Pro", "sb-titel")}
    ${zeile(26, 70, (s.cpu || {}).model ? "Ryzen AI 9 HX 370 · " + s.cpu.cores + " Threads" : "Prozessor")}
    <text x="26" y="96" class="sb-text">Prozessor <tspan class="sb-wert" fill=${farbeTemp(t.cpu || 0, 75, 90)}>${t.cpu ?? "?"} °C</tspan> · Last ${s.host && s.host.load ? (+s.host.load[0]).toFixed(2) : "?"}</text>
    ${zeile(26, 120, `Arbeitsspeicher ${Math.round((mem.used || 0) / 1024)} / ${Math.round((mem.total || 0) / 1024)} GB`)}
    <rect x="26" y="128" width="268" height="6" rx="3" class="sb-bahn" /><rect x="26" y="128" width=${268 * Math.min(1, (mem.used || 0) / (mem.total || 1))} height="6" rx="3" class="sb-fuell" />
    <text x="26" y="156" class="sb-text">NVMe <tspan class="sb-wert" fill=${farbeTemp(t.nvme || 0, 60, 70)}>${t.nvme ?? "?"} °C</tspan> · ${s.disk_gb ? Math.round(s.disk_gb.free) + " GB frei" : ""}</text>
    <text x="26" y="180" class="sb-text"><tspan class="sb-wert" fill=${funk ? "var(--amber)" : "var(--sea)"}>${funk ? "WLAN" : "LAN"}</tspan>${funk && netz.wlan ? ` · ${netz.wlan.ssid} · ${netz.wlan.signal_dbm} dBm · ${netz.wlan.bitrate_mbit} Mbit/s` : netz.lan_speed_mbit ? ` · ${netz.lan_speed_mbit} Mbit/s` : ""}</text>
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
    ${beiKlick && html`<g class="sb-treffer">
      <rect x="10" y="20" width="300" height="236" rx="10" role="button" tabindex="0" aria-label="Mini-PC im Einzelnen" onClick=${() => beiKlick("minipc")}><title>Mini-PC: was läuft, Messwerte</title></rect>
      ${g.slice(0, 2).map((k, i) => html`<rect x="430" y=${20 + i * 124} width="300" height="110" rx="10" role="button" tabindex="0" aria-label=${"Grafikkarte " + (i + 1) + " im Einzelnen"} onClick=${() => beiKlick("gpu:" + i)}><title>Karte ${i + 1}: was darauf läuft</title></rect>`)}
      <rect x="10" y="286" width="280" height="50" rx="10" role="button" tabindex="0" aria-label="Strom im Einzelnen" onClick=${() => beiKlick("strom")}><title>Steckdosen und Notabschaltung</title></rect>
      <rect x="450" y="286" width="280" height="50" rx="10" role="button" tabindex="0" aria-label="Strom im Einzelnen" onClick=${() => beiKlick("strom")}><title>Steckdosen und Notabschaltung</title></rect>
    </g>`}
  </svg></div>`;
}

// ------------------------------------------------------------ Updates, Empfehlungen, Sicherungen
const STUFE = { einspielen: ["gruen", "einspielen"], nicht: ["", "nicht einspielen"], achtung: ["rot", "Achtung"], info: ["blau", "Hinweis"] };

function Empfehlung({ e, auftrag, starten, laden, modellLaden }) {
  const [frage, setFrage] = useState(false);
  if (e.aktion && e.aktion.art === "modell") return html`<${ModellEmpfehlung} e=${e} l=${(laden || {})[e.aktion.name]} modellLaden=${modellLaden} />`;
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

// Modell laden: kein Eingriff ins System (nur ein Download ueber Ollama), deshalb
// ohne Rueckfrage und nicht rot -- aber mit sichtbarem Fortschritt, denn 20 GB
// sind eine halbe Stunde Stille.
function ModellEmpfehlung({ e, l, modellLaden }) {
  return html`<div class="empf einspielen">
    <div class="empf-kopf"><span class="pill gruen">Modell</span></div>
    <b>${e.titel}</b>
    <p class="leise klein empf-text" title=${e.warum}>${e.warum}</p>
    ${l && l.stand === "laeuft" ? html`<div class="sv-bzeile"><div class="sv-zeile"><span>${l.schritt || "lädt"}</span><b>${l.prozent || 0} %${l.gb ? " von " + l.gb + " GB" : ""}</b></div><${Balken} p=${l.prozent || 0} warn=${101} krit=${101} /></div>`
      : l && l.stand === "fertig" ? html`<div class="leise klein">Geladen. Im Team kannst du es jetzt einer Rolle zuweisen.</div>`
      : html`<div>${l && l.stand === "fehler" ? html`<div class="fehlerbox" style="margin-bottom:6px">${l.fehler}</div>` : ""}
          <button class="btn klein primaer" onClick=${() => modellLaden(e.aktion.name)}><${Icon} n="download" g=${13} />${e.aktion.text}</button></div>`}
  </div>`;
}

// Ein roter Knopf mit Rueckfrage direkt daneben -- fuer alles, was das System veraendert.
function GefahrKnopf({ text, frage, art, starten, auftrag }) {
  const [auf, setAuf] = useState(false);
  if (auf) return html`<span class="knopfreihe"><span class="klein">${frage}</span>
    <button class="btn klein gefahr voll" onClick=${() => { setAuf(false); starten(art); }}>Ja</button>
    <button class="btn klein geist" onClick=${() => setAuf(false)}>Abbrechen</button></span>`;
  return html`<button class="btn klein gefahr" disabled=${auftrag && auftrag.laeuft} onClick=${() => setAuf(true)}>${text}</button>`;
}

function UpdatesBlock({ u, s, auftrag, starten, neuPruefen }) {
  const ein = u ? u.pakete.filter((p) => p.einspielbar) : [];
  const gest = u ? u.pakete.filter((p) => !p.einspielbar) : [];
  const neustart = s && s.updates && s.updates.reboot_required;
  const Paket = ({ p }) => html`<div class="sv-paket"><span class="mono">${p.name}</span>${p.sicherheit ? html` <span class="pill rot">Sicherheit</span>` : ""}
    <span class="leise">${p.beschreibung || ""}</span></div>`;
  return html`<div class="sv-teil">
    <h5>Updates</h5>
    ${!u ? html`<div class="leise klein">apt wird gefragt …</div>` : html`
      <${Zeile} name="Würde apt jetzt einspielen" wert=${ein.length} s=${ein.length ? "warnung" : ""} />
      <${Zeile} name="Gestaffelt zurückgehalten" wert=${gest.length} />
      <${Zeile} name="Neustart fällig" wert=${neustart ? "ja" : "nein"} s=${neustart ? "warnung" : ""} />
      ${u.pakete.length > 0 && html`<details class="sv-pakete"><summary>Pakete im Einzelnen</summary>
        ${ein.map((p) => html`<${Paket} p=${p} />`)}
        ${gest.length > 0 && html`<div class="leise klein" style="margin:6px 0 2px">Gestaffelt (kommt von selbst, nicht erzwingen):</div>${gest.map((p) => html`<${Paket} p=${p} />`)}`}
      </details>`}`}
    <div class="knopfreihe sv-aktionen">
      <button class="btn klein" onClick=${neuPruefen}><${Icon} n="neu_laden" g=${12} />Neu prüfen</button>
      ${ein.length > 0 && html`<${GefahrKnopf} text="Einspielen" frage="Jetzt einspielen?" art="updates" starten=${starten} auftrag=${auftrag} />`}
      <${GefahrKnopf} text="Server neu starten" frage="Alles bricht kurz ab. Neu starten?" art="neustart" starten=${starten} auftrag=${auftrag} />
    </div>
  </div>`;
}

function SicherungenBlock({ sich }) {
  const jetzt = Date.now() / 1000;
  return html`<div class="sv-teil">
    <h5>Sicherungen</h5>
    ${sich ? ["inhalt", "server"].map((k) => {
      const x = sich[k] || {};
      const alt = x.zeit && jetzt - x.zeit > 48 * 3600;
      return html`<${Zeile} name=${k === "inhalt" ? "Inhalt → OneDrive" : "Server → OneDrive"}
        wert=${x.zeit ? `${x.zustand === "ok" ? "ok" : x.zustand} · ${zeitText(x.zeit)}` : "unbekannt"} s=${x.zustand !== "ok" ? "kritisch" : alt ? "warnung" : ""} />`;
    }) : html`<${Zeile} name="OneDrive" wert="Stand nicht lesbar" s="warnung" />`}
    <${Zeile} name="Neue Fassung, lokal" wert="täglich 03:30" />
    <p class="leise klein" style="margin:6px 0 0">Beide OneDrive-Läufe täglich früh um 3. Gewarnt wird ab 48 Stunden.</p>
  </div>`;
}

function Auftrag({ a }) {
  if (!a || (!a.laeuft && !a.ende)) return null;
  const titel = { updates: "Updates einspielen", neustart: "Neustart", "ollama-neustart": "Ollama neu starten", "caddy-neustart": "Caddy neu starten" }[a.art] || "Auftrag";
  return html`<section class="sv-kachel sv-voll" style="margin-bottom:12px">
    <div class="sv-kachel-kopf"><h4>${titel}</h4>
      ${a.laeuft ? html`<span class="pill lila">läuft seit ${zeitText(a.start).replace("vor ", "")}</span>`
        : a.rc === 0 ? html`<span class="pill gruen">fertig ${zeitText(a.ende)}</span>` : html`<span class="pill rot">fehlgeschlagen (rc ${a.rc})</span>`}</div>
    <pre class="log">${a.log || "…"}</pre>
  </section>`;
}

// ------------------------------------------------------------ Software-Schaubild
const ZEITGEBER = { "vvec-plaud-sync.timer": "holt Plaud-Notizen", "vvec-vorgang.timer": "Vorgänge des alten Cockpits",
  "vvec-board.timer": "frischt das Advisory Board auf", "vvec-suche-index.timer": "Suchindex des alten Cockpits",
  "vvec-sicherung-inhalt.timer": "sichert den Inhalt nach OneDrive", "vvec-sicherung-server.timer": "sichert den Server nach OneDrive",
  "vvec-backup.timer": "restic, bewusst nicht eingerichtet" };

function container(s, muster) {
  const c = (s.docker || []).map((x) => { const [name, st] = String(x).split("|"); return { name, st: st || "", laeuft: /^Up/.test(st || "") }; });
  return c.find((x) => muster.test(x.name));
}

function Software({ s, sys, auftrag, starten }) {
  if (!s) return html`<${Kachel} titel="Software"><${Leer}>Der Status-Dienst antwortet nicht.</${Leer}></${Kachel}>`;
  const sv = s.services || {}, n = s.network || {}, v = s.versions || {}, h = s.host || {}, u = s.updates || {}, sich = s.sicherheit || {};
  const hier = location.host;
  const ts = String(sv.tailscale || "");
  const c = { comfy: container(s, /comfy/i), owui: container(s, /open.?webui/i), searx: container(s, /searx/i), tts: container(s, /speech|piper/i) };
  const altOk = sys && sys.alt_backend && !sys.alt_backend.code;
  const neustartKnopf = (dienst) => html`<div class="sw-z-knopf"><${GefahrKnopfKlein} dienst=${dienst} starten=${starten} auftrag=${auftrag} /></div>`;
  const karten = [
    [ "So kommen Sie herein", "zwei Wege, ein Ziel", html`
      <${SwZ} st="ok" name="Diese Fassung" marke="gerade hier" satz=${hier} />
      <${SwZ} st=${zustand(n.tailscale_ip, false)} name="Tailnet (altes Cockpit)" satz="vveorgxais.tail4ca1ab.ts.net · nur eigene Geräte" />
      <${SwZ} st="unbekannt" name="Cloudflare (altes Cockpit)" satz="cockpit.vveorgxais.org · für fremde Geräte, mit Access-MFA" />
      <${SwZ} st=${zustand(/running/i.test(ts), ts && !/running/i.test(ts))} name="tailscaled" marke=${n.tailscale_ip || ""} satz="hält den Direktdraht offen" />` ],
    [ "Was Ihre Anfragen verteilt", "", html`
      <${SwZ} st=${zustand(sv.caddy === "active", sv.caddy && sv.caddy !== "active")} name="Caddy" marke="Port 8000" satz="verteilt alles des alten Cockpits nach Pfad an die Dienste" knopf=${neustartKnopf("caddy")} />
      ${v.caddy && html`<${SwZ} st="ok" name="Fassung" marke=${v.caddy} />`}
      <${SwZ} st="ok" name="Diese Fassung" marke="Port 8790" satz="läuft direkt, nicht über Caddy" />` ],
    [ "Dienste dahinter", "", html`
      <${SwZ} st=${zustand(sv.ollama === "active", sv.ollama && sv.ollama !== "active")} name="Ollama" marke="11434" satz=${`${(s.ollama_models || []).length} Modelle, ${(s.ollama_running || []).length} im Speicher`} knopf=${neustartKnopf("ollama")} />
      <${SwZ} st=${zustand(c.comfy && c.comfy.laeuft, c.comfy)} name="ComfyUI" marke="8188" satz=${c.comfy ? `${(s.comfy_models || []).length} Bild-/Videomodelle · ${c.comfy.st}` : "Container nicht gefunden"} />
      <${SwZ} st=${zustand(c.owui && c.owui.laeuft, c.owui)} name="Open WebUI" marke="8080" satz=${c.owui ? c.owui.st : "Container nicht gefunden"} />
      <${SwZ} st=${zustand(c.searx && c.searx.laeuft, c.searx)} name="SearXNG" marke="8888" satz=${c.searx ? "Websuche · " + c.searx.st : "Container nicht gefunden"} />
      <${SwZ} st=${zustand(c.tts && c.tts.laeuft, c.tts)} name="openedai-speech" marke="5050" satz=${c.tts ? "Piper · " + c.tts.st : "Container nicht gefunden"} />
      <${SwZ} st="ok" name="vve-status" marke="9099" satz="misst die Maschine, liefert dieses Bild" />
      <${SwZ} st=${zustand(altOk, sys && !altOk)} name="Backend altes Cockpit" marke="8770" satz=${sys ? (altOk ? "antwortet" : "antwortet nicht") : "nicht gemeldet"} />` ],
    [ "Was von selbst läuft", "", Object.entries(s.timers || {}).map(([k, t]) => html`<${SwZ}
        st=${!t.geladen ? "warnung" : t.aktiv === "active" ? "ok" : t.aktiv === "failed" ? "warnung" : "unbekannt"}
        name=${k.replace(/\.timer$/, "")} marke=${!t.geladen ? "fehlt" : t.naechster ? "nächster " + new Date(t.naechster * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) : t.abstand ? "läuft ständig" : ""}
        satz=${(ZEITGEBER[k] || "") + (t.zuletzt ? " · zuletzt " + zeitText(t.zuletzt) : "")} />`) ],
    [ "Unterbau", "", html`
      <${SwZ} st=${zustand(h.os)} name=${h.os || "System nicht gemeldet"} marke=${h.kernel ? "Kernel " + h.kernel : ""} satz=${(h.hostname || "") + (h.uptime ? " · " + h.uptime : "")} />
      <${SwZ} st=${u.pending == null ? "unbekannt" : u.security ? "warnung" : u.pending ? "hinweis" : "ok"} name="Paketstand" marke=${u.pending != null ? u.pending + " offen" : "?"} satz=${u.pending ? `${u.pending} Updates verfügbar${u.security ? `, davon ${u.security} Sicherheit` : ""}` : "alles eingespielt"} />
      <${SwZ} st=${String(n.interface || "").startsWith("wl") ? "warnung" : "ok"} name="Netz" marke=${n.interface || "?"} satz=${`LAN ${n.lan_ip || "?"} · Tailnet ${n.tailscale_ip || "?"}`} />
      <${SwZ} st=${sich.ufw ? (sich.ufw.aktiv && !(sich.ufw.offene_regeln || []).length ? "ok" : "warnung") : "unbekannt"} name="Firewall" marke=${sich.ufw ? (sich.ufw.aktiv ? "aktiv" : "aus") : "?"} satz=${sich.ufw ? ((sich.ufw.offene_regeln || []).length ? (sich.ufw.offene_regeln.length + " Regeln für das ganze Internet offen") : "nur Tailnet offen") : "nicht lesbar"} />
      <${SwZ} st=${sich.fail2ban ? (sich.fail2ban.aktiv ? "ok" : "warnung") : "unbekannt"} name="fail2ban" marke=${sich.fail2ban ? (sich.fail2ban.gesperrt || []).length + " gesperrt" : "?"} satz=${`SSH-Fehlversuche 24 h: ${sich.ssh_fehlgeschlagen_24h ?? "?"}`} />
      <${SwZ} st=${s.health ? (s.health.automatik_angehalten ? "warnung" : "ok") : "unbekannt"} name="WatchDog" marke=${s.health ? `Notfall ab ${s.health.schwelle_c} °C` : "?"} satz=${s.health ? (s.health.automatik_angehalten ? "angehalten: ein Mensch muss hinsehen" : "wacht über die Grafikkarten") : "nicht gemeldet"} />` ],
    [ "Diese Fassung", "", sys ? html`
      <${SwZ} st=${sys.stab.stab_aktiv ? "ok" : "warnung"} name="Team" marke=${sys.stab.stab_aktiv ? "an" : "aus"} satz=${sys.stab.letzter_lauf ? "letzter Durchgang " + zeitText(sys.stab.letzter_lauf) : "noch kein Durchgang"} />
      <${SwZ} st=${sys.stab.sync && Date.now() / 1000 - sys.stab.sync > 1800 ? "warnung" : "ok"} name="Plaud-Abruf" marke=${sys.stab.sync ? zeitText(sys.stab.sync) : "?"} satz=${sys.stab.letzte_datei ? "letzte Notiz " + zeitText(sys.stab.letzte_datei) : ""} />
      <${SwZ} st=${sys.stab.letzter_fehler ? "warnung" : "ok"} name="Letzter Fehler" satz=${sys.stab.letzter_fehler || "keiner"} />` : html`<div class="leise klein">wird geholt …</div>` ],
    [ "Was auf der Platte liegt", s.disk_gb ? Math.round(s.disk_gb.free) + " GB frei" : "", html`
      <${SwZ} st="ok" name="daten/cockpit.sqlite" satz="der Bestand dieser Fassung, ein Schreiber" />
      <${SwZ} st="ok" name="daten/sicherungen" satz="tägliche Sicherung der Datenbank, 30 Stände" />
      <${SwZ} st="ok" name="/var/lib/vvec" satz="Bestand des alten Cockpits, hier nur gelesen" />
      <${SwZ} st="ok" name="/var/lib/vvec/plaud" satz="die Plaud-Notizen, beide Fassungen lesen sie" />` ],
    [ "Nach draußen", "zuschaltbar, nie zwingend", html`
      <${SwZ} st="unbekannt" name="Cloud-Modelle" marke="nicht eingerichtet" satz="Dario, Elon, Demmis gibt es nur im alten Cockpit" />
      <${SwZ} st="unbekannt" name="Mail-Versand" marke="nicht eingerichtet" satz="die Zugangsdaten liegen nur beim alten Backend" />
      <${SwZ} st=${zustand(sys && sys.websuche && sys.websuche.erreichbar, sys && sys.websuche && !sys.websuche.erreichbar)} name="Websuche" marke="SearXNG" satz="eigene Suchmaschine, kein Google" />` ],
  ];
  return karten.map(([t, neben, inhalt]) => html`<${Kachel} titel=${t} neben=${neben}>${inhalt}</${Kachel}>`);
}

function GefahrKnopfKlein({ dienst, starten, auftrag }) {
  const [auf, setAuf] = useState(false);
  if (auf) return html`<span class="knopfreihe"><span class="klein">${dienst === "ollama" ? "Laufende Antworten brechen ab." : "Das alte Cockpit ist kurz weg."}</span>
    <button class="btn klein gefahr voll" onClick=${() => { setAuf(false); starten(dienst + "-neustart"); }}>Ja, neu starten</button>
    <button class="btn klein geist" onClick=${() => setAuf(false)}>Abbrechen</button></span>`;
  return html`<button class="btn klein gefahr" disabled=${auftrag && auftrag.laeuft} onClick=${() => setAuf(true)}>Neu starten</button>`;
}

// ------------------------------------------------------------ Womit Sie arbeiten
function Modelle({ liste, neueste, s }) {
  const ges = gpus(s).reduce((a, k) => a + k.gesamt / 1024, 0) || 48;
  if (!liste) return html`<div class="leise klein">wird geholt …</div>`;
  return html`<div class="sv-scroll"><table class="tabelle sv-tabelle"><thead><tr><th>Modell</th><th>Größe</th><th>Passt</th><th>Team</th></tr></thead><tbody>
    ${liste.map((m) => html`<tr><td class="mono">${m.name}${m.geladen ? html` <span class="pill lila">geladen</span>` : ""}</td><td>${m.groesse}</td>
      <td class="leise">${m.gb === 0 ? "?" : m.gb * 1.08 < 22.5 ? "1 Karte" : m.gb * 1.08 < ges - 1.5 ? "2 Karten" : "Auslagerung"}</td>
      <td>${m.team.join(", ") || html`<span class="leise">—</span>`}</td></tr>`)}
  </tbody></table></div>
  <div class="leise klein sv-fuss">${s && s.versions ? s.versions.ollama : ""}${neueste ? " · neueste " + neueste : ""}</div>`;
}

// ------------------------------------------------------------ Was die Maschine meldet
function Temperaturen({ s }) {
  const t = s.temps_c || {};
  const reihen = [["CPU", t.cpu, 80, 88], ["iGPU", t.igpu, 80, 90], ["NVMe", t.nvme, 60, 75], ["Board", t.board, 70, 85], ["WLAN-Modul", t.wifi, 75, 90], ["RAM", t.ram_avg, 65, 80]];
  return html`${reihen.filter((r) => r[1] != null).map(([n, w, warn, krit]) => html`<${BalkenZeile} name=${n} wert=${w + " °C"} p=${w / krit * 100} warn=${warn / krit * 100} krit=${95} />`)}
    ${s.fans && s.fans.available === false && html`<p class="leise klein sv-fuss">Lüfterdrehzahl: nicht verfügbar. Der Mini-PC meldet sie nicht.</p>`}`;
}
function Auslastung({ s }) {
  const c = s.cpu || {}, h = s.host || {}, m = s.memory_mb || {}, d = s.disk_gb || {}, ig = s.igpu || {};
  return html`
    ${c.model && html`<${Zeile} name=${String(c.model).replace(/\s*w\/.*$/, "")} wert=${(c.cores || "?") + " Threads"} />`}
    ${h.load && html`<${Zeile} name="Last 1 / 5 / 15 min" wert=${h.load.map((x) => (+x).toFixed(2)).join(" · ")} />`}
    ${m.total && html`<${BalkenZeile} name="Arbeitsspeicher" wert=${`${Math.round(m.used / 1024)} / ${Math.round(m.total / 1024)} GB`} p=${m.used / m.total * 100} />`}
    ${d.total && html`<${BalkenZeile} name="Platte" wert=${Math.round(d.free) + " GB frei"} p=${d.used / d.total * 100} warn=${80} krit=${92} />`}
    ${ig.power_w != null && html`<${Zeile} name="iGPU 890M" wert=${`${ig.power_w} W · ${ig.clock_mhz || "?"} MHz`} />`}
    ${c.governor && html`<${Zeile} name="Governor" wert=${c.governor + (c.power_profile ? " · " + c.power_profile : "")} />`}`;
}
function Strom({ s }) {
  const p = s.power || {};
  const dosen = [["Server", p.server], ["Docks", p.dock]];
  if (!p.server && !p.dock) return html`<p class="leise klein">Keine Messwerte von den Steckdosen.</p>`;
  const summe = dosen.reduce((a, [, d]) => a + (d && d.watt ? d.watt : 0), 0);
  return html`<div class="sv-gross">${Math.round(summe)} W<span>zusammen</span></div>
    ${dosen.map(([n, d]) => d ? html`<${Zeile} name=${n} wert=${`${Math.round(d.watt)} W · ${Math.round(d.volt)} V · ${d.temp_c} °C`} s=${d.temp_c >= 72 ? "kritisch" : d.temp_c >= 60 ? "warnung" : ""} />` : html`<${Zeile} name=${n} wert="keine Messung" />`)}
    ${dosen.map(([n, d]) => d && d.kwh != null ? html`<${Zeile} name=${"Zähler " + n} wert=${d.kwh.toFixed(1) + " kWh"} />` : null)}`;
}
function RtxLed({ s }) {
  const g = gpus(s);
  if (!g.length) return html`<p class="leise klein">Keine Grafikkarte gemeldet.</p>`;
  return html`${g.map((k, i) => { const f = ledFarbe(k.last); return html`<div class="sv-led">
      <i style=${`background:${f.hex}`} title=${f.ruhe ? "Leerlauf: drei Segmente blau" : "ganze Leiste, Weiß → Rot mit der Last"}></i>
      <div><b>Karte ${i + 1}</b><span class="leise klein"> · ${f.ruhe ? "Leerlauf" : `Last ${k.last} %`} · ${k.temp} °C</span>
        <${Balken} p=${k.belegt / (k.gesamt || 1) * 100} warn=${85} krit=${95} /></div></div>`; })}
    <p class="leise klein sv-fuss">Dieselbe Farbe trägt das Logo oben links, solange lokal gerechnet wird.</p>`;
}


// ------------------------------------------------------------ Aufbau im Einzelnen
// Klick auf den Mini-PC, eine Karte oder eine Steckdose im Schaubild (wie im
// alten Cockpit). Liest denselben Stand wie das Schaubild -- keine zweite
// Abfrage. Anders als dort steht je Karte, WAS auf ihr laeuft: nvidia-smi je
// Karte plus Kommandozeile des Prozesses (systeminfo.karten()).
function Vital({ name, wert, s }) {
  return html`<div class=${"det-vital " + (s || "")}><b>${wert ?? "—"}</b><span>${name}</span></div>`;
}
const stufeWert = (w, warn, krit) => (w == null ? "" : w >= krit ? "kritisch" : w >= warn ? "warnung" : "");

function DetailMinipc({ s, karten }) {
  const t = s.temps_c || {}, m = s.memory_mb || {}, d = s.disk_gb || {}, c = s.cpu || {}, n = s.network || {}, h = s.host || {};
  const funk = String(n.interface || "").startsWith("wl");
  return html`
    <div class="det-vitals">
      <${Vital} name="CPU" wert=${t.cpu != null ? t.cpu + " °C" : null} s=${stufeWert(t.cpu, 80, 88)} />
      <${Vital} name="Arbeitsspeicher" wert=${m.total ? Math.round(m.used / m.total * 100) + " %" : null} s=${m.total ? stufeWert(m.used / m.total * 100, 80, 92) : ""} />
      <${Vital} name="NVMe frei" wert=${d.total ? Math.round(d.free) + " GB" : null} s=${d.total ? stufeWert(d.used / d.total * 100, 80, 92) : ""} />
      <${Vital} name="Last (1 min)" wert=${h.load ? (+h.load[0]).toFixed(2) : null} />
    </div>
    <h5 class="det-abschnitt">System</h5>
    <${Zeile} name="Prozessor" wert=${(c.model || "?") + (c.cores ? " · " + c.cores + " Threads" : "")} />
    <${Zeile} name="Taktregelung · Energieprofil" wert=${[c.governor, c.power_profile].filter(Boolean).join(" · ") || null} />
    <${Zeile} name="Arbeitsspeicher" wert=${m.total ? `${(m.used / 1024).toFixed(1)} / ${(m.total / 1024).toFixed(0)} GB` : null} />
    <${Zeile} name="NVMe" wert=${d.total ? `${Math.round(d.free)} von ${Math.round(d.total)} GB frei${t.nvme != null ? " · " + t.nvme + " °C" : ""}` : null} />
    <${Zeile} name="Netz" wert=${n.interface ? `${funk ? "WLAN" : "LAN"} · ${n.interface}${funk && n.wlan ? ` · ${n.wlan.ssid} · ${n.wlan.signal_dbm} dBm · ${n.wlan.bitrate_mbit} Mbit/s` : ""}` : null} s=${funk ? "warnung" : ""} />
    <${Zeile} name="Adressen" wert=${`LAN ${n.lan_ip || "?"} · Tailnet ${n.tailscale_ip || "?"}`} />
    <${Zeile} name="Läuft seit" wert=${h.uptime ? h.uptime.replace("up ", "") : null} />
    <${Zeile} name="Lüfterdrehzahl" wert=${(s.fans && s.fans.note) ? "nicht verfügbar (der Mini-PC meldet sie nicht)" : null} />
    <h5 class="det-abschnitt">Was gerade läuft</h5>
    ${Object.entries(s.services || {}).map(([k, v]) => html`<${Zeile} name=${k} wert=${v} s=${/active|running/i.test(v) ? "" : "kritisch"} />`)}
    ${(s.docker || []).map((x) => { const [nm, st] = String(x).split("|"); return html`<${Zeile} name=${nm + " (Container)"} wert=${st} s=${/^Up/.test(st || "") ? "" : "kritisch"} />`; })}
    <h5 class="det-abschnitt">Geladene Sprachmodelle</h5>
    ${(s.ollama_laeuft || []).length ? s.ollama_laeuft.map((x) => html`<${Zeile} name=${x.name} wert=${`${x.groesse} · ${x.prozessor}${x.kontext ? " · Kontext " + x.kontext : ""}`} />`)
      : html`<p class="leise klein">Gerade ist kein Modell geladen.</p>`}
    <p class="leise klein" style="margin-top:6px">Auf welcher Karte sie liegen, steht im Fenster der jeweiligen Karte.</p>`;
}

function DetailKarte({ s, i, karten }) {
  const k = gpus(s)[i];
  const kk = (karten || []).find((x) => x.index === i);
  if (!k) return html`<div class="fehlerbox">Diese Karte lässt sich gerade nicht auslesen.</div>`;
  const vp = k.belegt / (k.gesamt || 1) * 100;
  return html`
    <div class="det-vitals">
      <${Vital} name="Temperatur" wert=${k.temp + " °C"} s=${stufeWert(k.temp, 75, 85)} />
      <${Vital} name="Auslastung" wert=${k.last + " %"} />
      <${Vital} name="Leistung" wert=${Math.round(k.watt) + " W"} />
      <${Vital} name="Lüfter" wert=${k.luefter || null} />
    </div>
    <h5 class="det-abschnitt">Grafikspeicher</h5>
    <${BalkenZeile} name="Belegt" wert=${`${(k.belegt / 1024).toFixed(1)} / ${(k.gesamt / 1024).toFixed(0)} GB (${Math.round(vp)} %)`} p=${vp} warn=${75} krit=${90} />
    <h5 class="det-abschnitt">Was auf dieser Karte läuft</h5>
    ${!kk ? html`<p class="leise klein">nvidia-smi meldet gerade keine Prozessliste.</p>`
      : kk.prozesse.length ? kk.prozesse.map((p) => html`<${Zeile} name=${p.was + (p.kontext ? " · Kontext " + p.kontext : "")} wert=${(p.mib / 1024).toFixed(1) + " GB"} />`)
      : html`<p class="leise klein">Nichts. Die Karte ist frei.</p>`}
    ${kk && kk.prozesse.some((p) => p.art === "ollama") && html`<p class="leise klein" style="margin-top:6px">Ein großes Modell verteilt Ollama auf beide Karten; dann steht es in beiden Fenstern mit seinem jeweiligen Anteil.</p>`}
    <h5 class="det-abschnitt">Verbindung</h5>
    <${Zeile} name="Gehäuse" wert=${"MINISFORUM DEG1 · Dock " + (i + 1)} />
    <${Zeile} name="Anschluss" wert=${i === 0 ? "OCuLink" : "SSD-Steckplatz (M.2)"} />`;
}

function DetailStrom({ s, wd, notfall }) {
  const p = s.power || {};
  return html`
    ${[["Server", p.server], ["Docks", p.dock]].map(([n, d]) => html`<h5 class="det-abschnitt">Steckdose ${n}</h5>
      ${d ? html`<div class="det-vitals">
          <${Vital} name="Leistung" wert=${Math.round(d.watt) + " W"} />
          <${Vital} name="Spannung" wert=${Math.round(d.volt) + " V"} s=${d.volt < 210 || d.volt > 250 ? "warnung" : ""} />
          <${Vital} name="Dose" wert=${d.temp_c + " °C"} s=${stufeWert(d.temp_c, 60, 72)} />
          <${Vital} name="Zähler" wert=${d.kwh != null ? d.kwh.toFixed(1) + " kWh" : null} />
        </div><${Zeile} name="Adresse" wert=${d.host} />` : html`<p class="leise klein">Keine Messung.</p>`}`)}
    <p class="leise klein" style="margin-top:6px">Der Shelly regelt ab 70 °C ab und schaltet bei 80 °C aus; gewarnt wird ab 60 °C.</p>
    <h5 class="det-abschnitt">Notabschaltung</h5>
    <${WatchDogKnoepfe} wd=${wd} notfall=${notfall} />`;
}

function AufbauDetail({ teil, s, karten, wd, notfall, zu }) {
  const i = teil.startsWith("gpu:") ? +teil.split(":")[1] : null;
  const titel = teil === "minipc" ? "Mini-PC · MINISFORUM AI X1 Pro" : teil === "strom" ? "Strom und Notabschaltung"
    : `Grafikkarte ${i + 1}${gpus(s)[i] ? " · " + gpus(s)[i].name.replace("NVIDIA GeForce ", "") : ""}`;
  return html`<${Modal} titel=${titel} zu=${zu} breit=${true}>
    ${teil === "minipc" && html`<${DetailMinipc} s=${s} karten=${karten} />`}
    ${i != null && html`<${DetailKarte} s=${s} i=${i} karten=${karten} />`}
    ${teil === "strom" && html`<${DetailStrom} s=${s} wd=${wd} notfall=${notfall} />`}
  <//>`;
}

// ------------------------------------------------------------ WatchDog
// Die Knoepfe stoßen den WatchDog-Dienst an (systeminfo.notfall_anfordern); der
// Ablauf selbst steht nur dort. Texte der Rueckfragen wie im alten Cockpit.
const NOTFALL = {
  kill: { knopf: "Kill Switch", frage: "Wirklich sofort ALLES ausschalten?",
    text: "Dock- UND Server-Steckdose gehen sofort aus, ohne Abkühlpause. Es gibt KEINEN automatischen Wiederanlauf: der Server bleibt aus, bis du die Steckdosen von Hand (Shelly-App) wieder einschaltest. Das Cockpit ist danach nicht mehr erreichbar.",
    ja: "Ja, sofort alles ausschalten" },
  neustart: { knopf: "Safety Shutdown & Reboot", frage: "Safety Shutdown & Reboot jetzt starten?",
    text: "Schaltet die Stromversorgung der Grafikkarten ab, kühlt 90 Sekunden ab, schaltet sie wieder ein und trennt danach kurz die Server-Steckdose selbst (automatischer Wiederanlauf nach 15 Sekunden). Derselbe Ablauf wie bei einem echten automatischen Notfall. Einige Minuten sind ComfyUI, die lokalen Modelle und das Cockpit nicht erreichbar. Klappt der Wiederanlauf nicht, hilft nur die Shelly-App.",
    ja: "Ja, Ablauf starten" },
};

function WatchDogKnoepfe({ wd, notfall }) {
  const [frage, setFrage] = useState(null);
  const offen = wd && wd.anfrage_offen;
  const seit = offen && wd.anfrage ? Math.round(Date.now() / 1000 - wd.anfrage.angefordert_um) : 0;
  return html`<div class="det-notfall">
    <p class="leise klein">Automatische Notfall-Erkennung: <b>${!wd || !wd.bekannt ? "Stand unbekannt" : wd.automatik_angehalten ? "AUS, angehalten nach wiederholtem Notfall" : wd.auto_an ? "an" : "aus (nur Beobachtung)"}</b>${wd && wd.schwelle_c ? ` · Notfallschwelle ${wd.schwelle_c} °C` : ""}.</p>
    ${offen && html`<div class=${seit > 40 ? "fehlerbox" : "hinweisbox"}>${seit > 40
      ? `Die Anfrage liegt seit ${seit} s, der WatchDog hat sie nicht übernommen. Läuft vve-health in der aktuellen Fassung (mit dem Briefkasten für dieses Cockpit)?`
      : "Anfrage gestellt. Der WatchDog übernimmt innerhalb von 15 Sekunden."}</div>`}
    ${frage ? html`<div class="det-frage"><b>${NOTFALL[frage].frage}</b><p>${NOTFALL[frage].text}</p>
        <div class="knopfreihe"><button class="btn gefahr voll" onClick=${() => { const a = frage; setFrage(null); notfall(a); }}>${NOTFALL[frage].ja}</button>
          <button class="btn geist" onClick=${() => setFrage(null)}>Abbrechen</button></div></div>`
      : html`<div class="knopfreihe">
          <button class="btn gefahr" onClick=${() => setFrage("kill")} title="Dock und Server sofort aus, kein Wiederanlauf">${NOTFALL.kill.knopf}</button>
          <button class="btn gefahr" onClick=${() => setFrage("neustart")} title="Sicherer Ablauf wie bei einem Notfall, mit Wiederanlauf">${NOTFALL.neustart.knopf}</button></div>`}
  </div>`;
}

function WatchDogGruppe({ wd, notfall, s }) {
  if (!wd) return null;
  const nf = wd.notfall;
  return html`
    <${Kachel} titel="Grafikkarten-Temperatur" neben=${wd.bekannt && wd.alter_sek != null ? `Messung vor ${wd.alter_sek} s` : ""}>
      ${wd.bekannt ? (wd.gpu_temps || []).map((g) => html`<${BalkenZeile} name=${"Karte " + (g.index + 1)} wert=${g.temp_c + " °C"} p=${g.temp_c / (wd.schwelle_c || 90) * 100} warn=${85} krit=${95} />`)
        : html`<div class="fehlerbox">Der WatchDog meldet nichts. Läuft vve-health?</div>`}
      <p class="leise klein sv-fuss">Ab ${wd.schwelle_c || 90} °C greift der Notfallablauf von selbst.</p>
    </${Kachel}>
    <${Kachel} titel="Notabschaltung"><${WatchDogKnoepfe} wd=${wd} notfall=${notfall} /></${Kachel}>
    <${Kachel} titel="Letzter Notfall">${nf ? html`
        <${Zeile} name="Wann" wert=${zeitText(nf.zeit)} />
        <${Zeile} name="Grund" wert=${nf.grund} />
        <${Zeile} name="Aktion" wert=${{ "dock-strom-aus": "Dock-Strom aus", "dock-strom-an-server-steckdosenzyklus": "Dock aus/an, Server-Steckdosenzyklus", "kill-switch": "Kill Switch", "dock-strom-aus-automatik-gestoppt": "Dock aus, Automatik angehalten" }[nf.aktion] || nf.aktion} s=${nf.wiederholt ? "kritisch" : ""} />
        ${(nf.temps || []).length > 0 && html`<${Zeile} name="Temperaturen damals" wert=${nf.temps.map((x) => x[1] + " °C").join(" · ")} />`}`
      : html`<p class="leise klein">Noch keiner.</p>`}</${Kachel}>
    <${Kachel} titel="Selbstheilung">${(wd.reparaturen || []).length ? wd.reparaturen.map((r) => html`<${Zeile} name=${r} wert="" />`)
      : html`<p class="leise klein">Ollama, Caddy und ComfyUI antworten. Fällt einer aus, startet der WatchDog ihn von selbst neu.</p>`}</${Kachel}>`;
}

// ------------------------------------------------------------ Die Sektion
export function ServerSektion({ zu, gesundheit }) {
  const [det, setDet] = useState(null);
  const [sys, setSys] = useState(null);
  const [teil, setTeil] = useState(null);          // Detailfenster: minipc | gpu:0 | gpu:1 | strom
  const k = useKopf();
  const detLaden = (frisch) => api("/system/details" + (frisch ? "?frisch=1" : "")).then(setDet).catch(fehlerMelden);
  const sysLaden = () => api("/system").then(setSys).catch(() => {});
  useEffect(() => {
    detLaden(false); sysLaden();
    const i = setInterval(() => { if (!document.hidden) { detLaden(false); sysLaden(); } }, 20000);
    const esc = (e) => { if (e.key === "Escape" && !document.querySelector(".modal-grund")) zu(); };
    document.addEventListener("keydown", esc);
    return () => { clearInterval(i); document.removeEventListener("keydown", esc); };
  }, []);
  useEffect(() => {
    if (!det || !det.auftrag || !det.auftrag.laeuft) return;
    const i = setInterval(async () => {
      try { const a = await api("/system/auftrag"); setDet((x) => ({ ...x, auftrag: a })); if (!a.laeuft) { clearInterval(i); detLaden(true); } } catch (e) { /* Neustart: Server weg */ }
    }, 2500);
    return () => clearInterval(i);
  }, [det && det.auftrag && det.auftrag.laeuft]);
  // Modell laden: Fortschritt alle 2 s, solange etwas laeuft.
  async function modellLaden(name) {
    try {
      const l = await api("/system/modell-laden", { methode: "POST", daten: { name } });
      setDet((x) => ({ ...x, laden: { ...(x.laden || {}), [name]: l } }));
      toast(name + " wird geladen. Den Fortschritt siehst du in der Empfehlung.");
    } catch (e) { fehlerMelden(e); }
  }
  useEffect(() => {
    const laeuft = det && Object.values(det.laden || {}).some((l) => l.stand === "laeuft");
    if (!laeuft) return;
    const i = setInterval(async () => {
      try { const r = await api("/system/modell-laden"); setDet((x) => ({ ...x, laden: r.laden })); if (!Object.values(r.laden).some((l) => l.stand === "laeuft")) detLaden(false); } catch (e) { /* weiter */ }
    }, 2000);
    return () => clearInterval(i);
  }, [det && Object.values(det.laden || {}).some((l) => l.stand === "laeuft")]);
  async function notfall(art) {
    try {
      await api("/system/notfall", { methode: "POST", daten: { art } });
      toast(art === "kill" ? "Kill Switch angefordert. Der WatchDog greift innerhalb von 15 Sekunden ein." : "Safety Shutdown & Reboot angefordert. Der WatchDog greift innerhalb von 15 Sekunden ein.");
      const holen = async () => { try { const w = await api("/system/watchdog"); setDet((x) => ({ ...x, watchdog: w })); } catch (e) { /* Server geht gerade aus */ } };
      holen(); setTimeout(holen, 5000); setTimeout(holen, 20000); setTimeout(holen, 45000);
    } catch (e) { fehlerMelden(e); }
  }

  async function starten(art) {
    const MELDUNG = { neustart: "Server startet neu. In ein bis zwei Minuten ist er wieder da.", updates: "Updates werden eingespielt. Den Fortschritt siehst du oben.",
      "ollama-neustart": "Ollama startet neu.", "caddy-neustart": "Caddy startet neu." };
    try { await api("/system/auftrag", { methode: "POST", daten: { art } }); toast(MELDUNG[art] || "Gestartet."); detLaden(false); } catch (e) { fehlerMelden(e); }
  }
  const s = det ? det.status : null;
  const [st, satz] = ampel(k, gesundheit);
  return html`<div class="server-sektion" role="region" aria-label="Server">
    <div class="sv-innen">
      <div class="sv-kopf"><i class=${"kopf-ampel " + st}></i>
        <b>${k && k.host ? k.host : "Server"}</b><span>${k && k.uptime ? "läuft seit " + k.uptime : ""}</span><span>· ${satz}</span>
        <span class="luecke"></span>
        <button class="btn klein" onClick=${() => detLaden(true)} title="apt und Fassungen frisch abfragen"><${Icon} n="neu_laden" g=${12} />Neu prüfen</button>
        <button class="btn klein geist icon" onClick=${zu} aria-label="Server-Sektion zuklappen" title="Zuklappen (Esc)"><${Icon} n="x" g=${15} /></button>
      </div>
      <${Auftrag} a=${det && det.auftrag} />
      <div class="sv-reihe">
        <${Kachel} titel="Aufbau" neben="Bauteil anklicken für Einzelheiten"><${Aufbau} s=${s} beiKlick=${setTeil} /></${Kachel}>
        <${Kachel} titel="Updates, Empfehlungen und Sicherungen">
          <div class="sv-zwei"><${UpdatesBlock} u=${det && det.updates} s=${s} auftrag=${det && det.auftrag} starten=${starten} neuPruefen=${() => detLaden(true)} />
            <${SicherungenBlock} sich=${det && det.sicherungen} /></div>
          <h5 class="sv-empf-titel">Empfehlungen</h5>
          ${!det ? html`<div class="leise klein">Prüfe …</div>` : det.empfehlungen.length
            ? html`<div class="empf-raster">${det.empfehlungen.map((x, i) => html`<${Empfehlung} key=${i} e=${x} auftrag=${det.auftrag} starten=${starten} laden=${det.laden} modellLaden=${modellLaden} />`)}</div>`
            : html`<div class="leise klein">Nichts zu tun: keine Updates offen, alle Dienste laufen, Sicherungen frisch.</div>`}
        </${Kachel}>
      </div>
      <${Gruppe} titel="Software" unter="was darauf läuft und wie es zusammenhängt" klasse="sw"><${Software} s=${s} sys=${sys} auftrag=${det && det.auftrag} starten=${starten} /></${Gruppe}>
      <${Gruppe} titel="Womit Sie arbeiten" unter="Modelle, Bestand, Suche und Stimme">
        <${Kachel} titel="Modelle" neben=${det && det.modelle ? det.modelle.length + "" : ""}><${Modelle} liste=${det && det.modelle} neueste=${det && det.ollama_neueste} s=${s} /></${Kachel}>
        <${Kachel} titel="Eigener Bestand">${sys ? Object.entries(sys.db).map(([n, w]) => html`<${Zeile} name=${n[0].toUpperCase() + n.slice(1)} wert=${w} />`) : html`<div class="leise klein">…</div>`}</${Kachel}>
        <${Kachel} titel="Websuche">${sys ? html`<${Zeile} name="SearXNG" wert=${sys.websuche && sys.websuche.erreichbar ? "erreichbar" : "nicht erreichbar"} s=${sys.websuche && sys.websuche.erreichbar ? "" : "kritisch"} />
          <p class="leise klein sv-fuss">Die eigene Suchmaschine. Dein Team recherchiert darüber; Google sieht davon nichts.</p>` : html`<div class="leise klein">…</div>`}</${Kachel}>
        <${Kachel} titel="Stimme">${sys ? html`<${Zeile} name="Spracherkennung (Whisper)" wert=${sys.stimme.whisper ? "bereit" : sys.stimme.grund} s=${sys.stimme.whisper ? "" : "kritisch"} />
          ${sys.stimme.whisper && html`<${Zeile} name="Modell" wert=${sys.stimme.modell + (sys.stimme.geladen.length ? " · " + sys.stimme.geladen.join(", ") : "")} />`}
          <${Zeile} name="Mikrofon im Browser" wert=${window.isSecureContext ? "möglich" : "nur über https"} s=${window.isSecureContext ? "" : "warnung"} />` : html`<div class="leise klein">…</div>`}</${Kachel}>
      </${Gruppe}>
      ${det && det.watchdog && html`<${Gruppe} titel="WatchDog" unter="Wacht über Temperaturen und Dienste, schaltet im Notfall ab">
        <${WatchDogGruppe} wd=${det.watchdog} notfall=${notfall} s=${s} /></${Gruppe}>`}
      <${Gruppe} titel="Was die Maschine meldet" unter="Messwerte, hier ist nichts zu tun, solange nichts rot ist">
        <${Kachel} titel="Temperaturen" neben=${s && s.temps_c && s.temps_c.cpu != null ? Math.round(s.temps_c.cpu) + " °C CPU" : ""}>${s ? html`<${Temperaturen} s=${s} />` : "…"}</${Kachel}>
        <${Kachel} titel="Auslastung" neben=${s && s.host && s.host.uptime ? "seit " + s.host.uptime.replace("up ", "") : ""}>${s ? html`<${Auslastung} s=${s} />` : "…"}</${Kachel}>
        <${Kachel} titel="Strom">${s ? html`<${Strom} s=${s} />` : "…"}</${Kachel}>
        <${Kachel} titel="RTX-LED">${s ? html`<${RtxLed} s=${s} />` : "…"}</${Kachel}>
      </${Gruppe}>
    </div>
    ${teil && s && html`<${AufbauDetail} teil=${teil} s=${s} karten=${det && det.karten} wd=${det && det.watchdog} notfall=${notfall} zu=${() => setTeil(null)} />`}
  </div>`;
}
