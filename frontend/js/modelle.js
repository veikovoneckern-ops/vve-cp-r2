// MODELLE -- die Seite "Modelle" des alten Cockpits, neu (Veiko, 16.10.2026:
// "ich hatte doch im alten Cockpit eine gute Uebersicht zu den Modellen, die
// installiert sind, und ob ich welche durch neue ersetzen sollte").
//
// Vier Fragen, in dieser Reihenfolge:
//   Was sollte ich tun?         Empfehlungen (Ersatz, Nachfolger, neue Fassung)
//   Was laedt gerade?           Fortschritt je Download
//   Was liegt hier?             installierte Modelle -- Groesse, wer sie nutzt,
//                               wie oft sie in den letzten 30 Tagen gerechnet haben
//   Was gibt es Neues?          neueste Modelle bei ollama.com, mit dem, was
//                               davon auf die beiden Karten passt
// Empfohlen ist nicht "besser": ob ein neues Modell hier besser ist, zeigt erst
// eine Messung. Deshalb steht bei allem Neuen "ungetestet".
import { html, useState, useEffect, Icon, toast, fehlerMelden, zeitText } from "./ui.js";
import { api } from "./api.js";

const tok = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1).replace(".", ",") + " Mio." : n >= 1e3 ? Math.round(n / 1e3) + " Tsd." : String(n || 0));

function LadenKnopf({ name, laden, nachher, text = "Laden" }) {
  const j = laden[name];
  if (j && j.stand === "laeuft") return html`<span class="pill lila">lädt · ${j.prozent || 0} %</span>`;
  if (j && j.stand === "fertig") return html`<span class="pill gruen">geladen</span>`;
  async function los() {
    try { await api("/system/modell-laden", { methode: "POST", daten: { name } }); toast(`${name} wird geladen. Den Fortschritt siehst du oben auf dieser Seite.`); nachher(); }
    catch (e) { fehlerMelden(e); }
  }
  return html`<button class="btn klein primaer" onClick=${los} title=${"Bei Ollama laden: " + name}><${Icon} n="download" g=${13} />${text}</button>`;
}

export function Modelle() {
  const [d, setD] = useState(null);
  const [laden, setLaden] = useState({});
  const [prueft, setPrueft] = useState(false);
  const holen = (frisch) => {
    setPrueft(!!frisch);
    return api("/modelle" + (frisch ? "?frisch=1" : "")).then((x) => { setD(x); setLaden(x.laden || {}); })
      .catch(fehlerMelden).finally(() => setPrueft(false));
  };
  useEffect(() => { holen(false); }, []);
  // Laeuft ein Download, alle 5 Sekunden den Stand holen.
  const laeuft = Object.values(laden).some((j) => j.stand === "laeuft");
  useEffect(() => {
    if (!laeuft) return;
    const t = setInterval(() => api("/system/modell-laden").then((x) => {
      setLaden(x.laden || {});
      if (!Object.values(x.laden || {}).some((j) => j.stand === "laeuft")) holen(false);
    }).catch(() => {}), 5000);
    return () => clearInterval(t);
  }, [laeuft]);
  if (!d) return html`<div class="seite"><div class="lade">Lade Modelle …</div></div>`;

  const gesamt = d.installiert.reduce((s, m) => s + m.gb, 0);
  const downloads = Object.values(laden).filter((j) => j.stand === "laeuft" || (j.stand === "fehler"));
  const familien = (d.neu && d.neu.familien) || [];
  const art = (f) => f.neuer ? ["lila", "Nachfolger"] : f.groesser ? ["gelb", "größere Ausgabe"] : f.verwandt ? ["", "aus deiner Familie"] : ["", "neu, andere Familie"];

  return html`<div class="seite mo">
    <div class="mo-kopf">
      <div><b>${d.installiert.length} Modelle installiert</b> <span class="leise">· ${gesamt.toFixed(0)} GB${d.frei_gb ? ` · ${Math.round(d.frei_gb)} GB frei auf der Platte` : ""} · ${d.vram.toFixed(0)} GB auf den Grafikkarten</span></div>
      <span class="leise klein">${d.neu && d.neu.zeit ? `ollama.com zuletzt geprüft ${zeitText(d.neu.zeit)}` : ""}</span>
      <button class="btn klein" onClick=${() => holen(true)} disabled=${prueft}><${Icon} n="neu" g=${14} />${prueft ? "prüft …" : "Jetzt neu prüfen"}</button>
    </div>

    ${downloads.length > 0 && html`<section class="karte">
      <div class="karte-kopf"><h3>Wird geladen</h3></div>
      ${downloads.map((j) => html`<div class="zeile"><div class="haupt-text"><b class="mono">${j.name}</b>
        <div class="leise klein">${j.stand === "fehler" ? "Abgebrochen: " + (j.fehler || "") : `${j.schritt || ""}${j.gb ? ` · ${j.gb} GB` : ""} · seit ${zeitText(j.start)}`}</div>
        ${j.stand === "laeuft" && html`<div class="video-balken"><i style=${`width:${j.prozent || 0}%`}></i></div>`}</div>
        ${j.stand === "fehler" ? html`<${LadenKnopf} name=${j.name} laden=${{}} nachher=${() => holen(false)} text="Neu versuchen" />` : html`<span class="neben">${j.prozent || 0} %</span>`}</div>`)}
      <p class="leise klein">Die Leitung des Servers ist langsam (unter 1 MB/s); große Modelle brauchen Stunden. Ein abgebrochener Download setzt beim nächsten Versuch fort.</p>
    </section>`}

    <section class="karte">
      <div class="karte-kopf"><h3>Empfehlungen</h3><span class="leise klein">Neu und ungetestet: erst laden, dann im Team messen, dann ersetzen</span></div>
      ${d.empfehlungen.length ? d.empfehlungen.map((e) => html`<div class="zeile mo-empf"><div class="haupt-text"><b>${e.titel}</b>
          <div class="leise klein">${e.warum}</div></div>
          ${e.aktion && e.aktion.art === "modell" && html`<${LadenKnopf} name=${e.aktion.name} laden=${laden} nachher=${() => holen(false)} text=${e.aktion.text} />`}</div>`)
        : html`<p class="leise">Nichts zu empfehlen: für jede Aufgabe läuft das beste bekannte Modell, und bei ollama.com gibt es keinen neueren Nachfolger einer Familie, die du nutzt.${d.neu && d.neu.fehler ? " (ollama.com war nicht erreichbar: " + d.neu.fehler + ")" : ""}</p>`}
    </section>

    <section class="karte">
      <div class="karte-kopf"><h3>Installiert</h3></div>
      <div class="tabelle-wrap"><table class="tabelle mo-tabelle"><thead><tr>
        <th>Modell</th><th class="zahl">Größe</th><th>Passt</th><th>Wofür (bestes installiertes)</th><th>Team</th><th class="zahl">Aufrufe 30 T.</th><th>Zuletzt</th></tr></thead>
        <tbody>${d.installiert.map((m) => html`<tr>
          <td class="mono">${m.name}${m.geladen ? html` <span class="pill lila">im Speicher</span>` : ""}</td>
          <td class="zahl">${m.gb.toFixed(1).replace(".", ",")} GB</td>
          <td class="leise">${m.passt.replace("passt auf ", "")}</td>
          <td>${m.aufgaben.join(", ") || html`<span class="leise">—</span>`}</td>
          <td>${m.team.join(", ") || html`<span class="leise">—</span>`}</td>
          <td class="zahl">${m.aufrufe ? `${m.aufrufe} · ${tok(m.token)}` : html`<span class="leise">—</span>`}</td>
          <td class="leise klein">${m.zuletzt ? zeitText(m.zuletzt) : "—"}</td></tr>`)}</tbody></table></div>
      <p class="leise klein" style="margin-top:8px">„Aufrufe“ zählt erst seit ${d.erfasst_seit ? new Date(d.erfasst_seit * 1000).toLocaleDateString("de-DE") : "heute"} (Seite Verbrauch). Ein Strich heißt deshalb noch nicht „wird nicht gebraucht“ -- entfernt wird hier nichts.</p>
    </section>

    <section class="karte">
      <div class="karte-kopf"><h3>Neu bei Ollama</h3><span class="leise klein">Neueste Modelle und Nachfolger deiner Familien -- je Modell die Ausgaben, die auf deine Karten passen</span></div>
      ${familien.length ? html`<div class="mo-neu">${familien.map((f) => { const [farbe, label] = art(f); return html`<div class="mo-familie">
          <div class="mo-familie-kopf"><b class="mono">${f.familie}</b> <span class=${"pill " + farbe}>${label}</span>
            ${(f.faehigkeiten || []).map((x) => html` <span class="pill">${{ vision: "Bilder", tools: "Werkzeuge", thinking: "denkt", decision: "Entscheidungen", audio: "Ton" }[x] || x}</span>`)}</div>
          <div class="leise klein">${f.beschreibung}</div>
          ${f.einordnung && html`<div class="mo-einordnung klein">
            ${f.einordnung.aufgaben.length > 0 && html`<div><span class="leise">Taugt für:</span> ${f.einordnung.aufgaben.join(", ")}</div>`}
            <div><span class="leise">Könnte ersetzen:</span> ${f.einordnung.ersetzt.length ? html`<span class="mono">${f.einordnung.ersetzt.join(", ")}</span>` : f.einordnung.aelter ? "nichts -- du hast schon eine neuere Fassung dieser Familie" : "nichts Installiertes -- käme dazu"}</div>
            ${f.einordnung.rollen.length > 0 && html`<div><span class="leise">Im Team geeignet für:</span> ${f.einordnung.rollen.join(", ")}</div>`}
            ${f.einordnung.neue_rolle && html`<div><span class="leise">Neue Rolle denkbar:</span> <b>${f.einordnung.neue_rolle.name}</b> -- ${f.einordnung.neue_rolle.wofuer}</div>`}
          </div>`}
          ${f.ausgaben.map((a) => html`<div class="mo-ausgabe"><span class="mono klein">${a.name}</span><span class="leise klein">${a.gb} GB · ${a.passt}</span>
            ${a.installiert ? html`<span class="pill gruen">installiert</span>` : html`<${LadenKnopf} name=${a.name} laden=${laden} nachher=${() => holen(false)} />`}</div>`)}
        </div>`; })}</div>`
        : html`<p class="leise">${d.neu && d.neu.fehler ? "ollama.com war nicht erreichbar: " + d.neu.fehler : "Noch nicht geprüft."}</p>`}
    </section>
  </div>`;
}
