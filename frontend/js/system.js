// SYSTEM -- was zu DIESER Fassung gehoert: Stab-Pipeline, Daten, Einstellungen.
// Alles ueber die Maschine (Aufbau, Updates, Dienste, Modelle, Messwerte) steht
// in der Server-Sektion, die ueber die Kaestchen in der Kopfzeile aufklappt --
// wie im alten Cockpit. Es gibt sie nur dort, nicht ein zweites Mal hier.
import { html, useState, useEffect, Icon, toast, fehlerMelden, aktualisieren, zeitText, useAbruf, bus } from "./ui.js";
import { api } from "./api.js";

function Wert({ name, wert, warn }) {
  return html`<div class="messwert"><span class="leise">${name}</span><b style=${warn ? "color:var(--signal)" : ""}>${wert ?? "nicht verfügbar"}</b></div>`;
}

export function System({ konto, thema }) {
  const [d, laden] = useAbruf("/system", 30000, []);
  const [laeuft, setLaeuft] = useState("");
  useEffect(() => { bus.sende("talk-kontext", null); }, []);

  async function abgleich() {
    setLaeuft("abgleich");
    try {
      const r = await api("/system/abgleich", { methode: "POST" });
      const n = r.neu; const summe = Object.values(n).reduce((a, b) => a + b, 0);
      toast(summe ? `Übernommen: ${n.projekte} Projekte, ${n.aufgaben} Aufgaben, ${n.notizen + n.plaud} Notizen, ${n.vorgaenge} Cases.` : "Nichts Neues im alten Cockpit.");
      laden(); aktualisieren();
    } catch (x) { fehlerMelden(x); }
    setLaeuft("");
  }
  const g = d ? d.stab || {} : {};
  const e = d ? d.einstellungen || {} : {};

  return html`<div class="seite">
    <div class="infobox" style="margin-bottom:14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <span>Alles über die Maschine (Aufbau, Updates, Dienste, Modelle, Messwerte) steht in der <b>Server-Sektion</b>.</span>
      <button class="btn klein" onClick=${() => bus.sende("server-sektion", true)}><${Icon} n="runter" g=${12} />Aufklappen</button>
    </div>
    ${d && html`<div class="raster-gleich drei">
      <section class="karte"><div class="karte-kopf"><h3>Team-Pipeline</h3></div>
        <${Wert} name="Team" wert=${g.stab_aktiv ? "an" : "aus"} />
        <${Wert} name="Letzter Durchgang" wert=${g.letzter_lauf ? zeitText(g.letzter_lauf) : "noch keiner"} />
        <${Wert} name="Gerade" wert=${g.laeuft ? g.laeuft.was : "nichts"} />
        <${Wert} name="Plaud-Abruf" wert=${g.sync ? zeitText(g.sync) : "unbekannt"} warn=${g.sync && Date.now() / 1000 - g.sync > 1800} />
        <${Wert} name="Letzte Notiz" wert=${g.letzte_datei ? zeitText(g.letzte_datei) : "unbekannt"} />
        ${g.letzter_fehler && html`<div class="fehlerbox" style="margin-top:8px">${g.letzter_fehler}</div>`}
        <div class="knopfreihe karte-fuss"><button class="btn klein" onClick=${async () => { await api("/system/durchgang", { methode: "POST" }); toast("Team-Durchgang angestoßen."); }}><${Icon} n="play" g=${13} />Jetzt einen Durchgang</button></div>
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Daten</h3></div>
        ${Object.entries(d.db).map(([k, v]) => html`<${Wert} name=${k[0].toUpperCase() + k.slice(1)} wert=${v} />`)}
        <${Wert} name="Abgleich mit altem Cockpit" wert=${e.letzter_abgleich ? zeitText(e.letzter_abgleich) : "nie"} />
        <div class="knopfreihe karte-fuss"><button class="btn klein" disabled=${laeuft === "abgleich"} onClick=${abgleich} title="Holt nur, was es hier noch nicht gibt.">
          <${Icon} n="neu_laden" g=${13} />${laeuft === "abgleich" ? "Gleiche ab …" : "Mit altem Cockpit abgleichen"}</button></div>
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Einstellungen</h3></div>
        <${Wert} name="Angemeldet als" wert=${konto.benutzer} />
        <${Wert} name="Mikrofon im Browser" wert=${window.isSecureContext ? "möglich" : "nur über https"} warn=${!window.isSecureContext} />
        ${!window.isSecureContext && html`<div class="hinweisbox" style="margin-top:8px">Öffne das Cockpit über <b>https://vveorgxais.tail4ca1ab.ts.net:8443</b>.</div>`}
        <div class="knopfreihe karte-fuss">
          <button class="btn klein" onClick=${thema}><${Icon} n="mond" g=${13} />Hell / Dunkel</button>
          <button class="btn klein" onClick=${() => { try { localStorage.removeItem("vvec_thema"); } catch (x) { /* egal */ } delete document.documentElement.dataset.theme; }}>Wie das System</button>
          <button class="btn klein gefahr" onClick=${() => api("/konto/abmelden", { methode: "POST" }).then(() => location.reload())}><${Icon} n="raus" g=${13} />Abmelden</button>
        </div>
      </section>
    </div>`}
  </div>`;
}
