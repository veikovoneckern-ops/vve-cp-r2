// CURRENT ACTIONS -- alles, was auf dem Server gerade laeuft (17.10.2026).
//
// Veiko: "da will ich alles sehen, was gerade laeuft, auch Downloads -- und die
// will ich pausieren oder abbrechen koennen." Die Liste kommt fertig vom Server
// (aktionen.py liest die Zustaende der Module, fuehrt keinen eigenen); hier wird
// nur gezeichnet und gesteuert. Knoepfe gibt es nur, wo der Server sie anbietet
// (steuerung) -- ein Pipeline-Schritt mitten in einer Aenderung hat keinen,
// sondern einen Link an seinen Ort.
import { html, useState, useEffect, Icon, Leer, toast, fehlerMelden, zeitText, bus } from "./ui.js";

const rest = (s) => (s < 60 ? "unter 1 Min." : s < 3600 ? Math.round(s / 60) + " Min." : Math.floor(s / 3600) + " Std. " + Math.round((s % 3600) / 60) + " Min.");
import { api } from "./api.js";

const KNOPF = {
  pausieren: ["Pausieren", "", "Pausiert."],
  fortsetzen: ["Fortsetzen", "primaer", "Läuft weiter."],
  abbrechen: ["Abbrechen", "gefahr", "Abgebrochen."],
  weg: ["Aus der Liste", "geist", null],
};
// Was ein Abbruch jeweils bedeutet -- die Rueckfrage sagt es, bevor geklickt ist.
const ABBRUCH = {
  download: "Download abbrechen? Schon Geladenes bleibt bei Ollama liegen; ein neues Laden setzt dort fort.",
  langlauf: "Langläufer abbrechen? Fertige Etappen bleiben, weiter geht es danach nicht mehr.",
  video: "Video abbrechen? Am Ergebnis steht dann „abgebrochen“ mit „Neu rechnen“.",
  folienbilder: "Bilder abbrechen? Fertige Bilder bleiben, die übrigen lassen sich neu rechnen.",
  neo: "Neos Auftrag abbrechen? Was er schon geändert hat, bleibt.",
  gespraech: "Antwort abbrechen? Die Frage bleibt im Gespräch stehen.",
  revision: "Modell-Vergleich abbrechen? Fertige Vergleiche bleiben gespeichert.",
  youtube: "YouTube-Auftrag abbrechen? Fertige Abschriften bleiben als Unterlagen, und aus den fertigen Folgen entsteht trotzdem ein Dossier.",
};

function Steuerknopf({ z, aktion, neu }) {
  const [frage, setFrage] = useState(false);
  const [text, klasse, meldung] = KNOPF[aktion] || [aktion, "", null];
  async function los() {
    setFrage(false);
    try { await api("/aktionen/steuern", { methode: "POST", daten: { id: z.id, aktion } }); if (meldung) toast(meldung); }
    catch (e) { fehlerMelden(e); }
    neu();
  }
  if (aktion === "abbrechen" && frage) return html`<span class="knopfreihe mo-frage"><span class="klein">${ABBRUCH[z.art] || "Wirklich abbrechen?"}</span>
    <button class="btn klein gefahr voll" onClick=${los}>Abbrechen</button><button class="btn klein geist" onClick=${() => setFrage(false)}>Nein</button></span>`;
  return html`<button class=${"btn klein " + klasse} onClick=${() => (aktion === "abbrechen" ? setFrage(true) : los())}>
    ${aktion === "pausieren" ? html`<${Icon} n="stopp" g=${12} />` : aktion === "fortsetzen" ? html`<${Icon} n="play" g=${12} />` : ""}${text}</button>`;
}

function Ansehen({ z }) {
  if (z.ergebnis_id) return html`<button class="btn klein geist" onClick=${() => bus.sende("ergebnis-zeigen", z.ergebnis_id)}>Ansehen</button>`;
  if (z.talk_gid) return html`<button class="btn klein geist" onClick=${() => bus.sende("talk-oeffnen", { gid: z.talk_gid })}>Ansehen</button>`;
  if (z.link) return html`<a class="btn klein geist" href=${z.link}>Ansehen</a>`;
  return null;
}

function Karte({ z, neu }) {
  const st = z.stand === "pausiert" ? "pausiert" : z.stand === "fehler" ? "fehler" : z.stand === "fertig" ? "fertig" : "";
  const dl = z.art === "download";
  return html`<div class=${"ak-karte " + st}>
    <div class="ak-kopf"><div style="min-width:0"><span class="leise klein">${z.art_name}${z.wer ? " · " + z.wer : ""}</span><br /><b class=${dl ? "mono" : ""}>${z.titel}</b></div>
      ${z.prozent != null && html`<span class="pill">${Math.round(z.prozent)} %</span>`}</div>
    ${z.prozent != null && html`<div class="video-balken"><i style=${`width:${z.prozent}%`}></i></div>`}
    <div class="ak-zeile">
      ${z.stand === "fehler" && z.fehler ? html`<span style="color:var(--signal)">${z.fehler}</span>` : z.schritt ? html`<span>${z.schritt}</span>` : ""}
      ${z.teile ? html`<span>${z.teile}</span>` : ""}
      ${dl && z.gb ? html`<span>${z.geladen_gb != null ? String(z.geladen_gb).replace(".", ",") + " von " : ""}${String(z.gb).replace(".", ",")} GB</span>` : ""}
      ${dl && z.stand === "laeuft" && (z.mb_s ? html`<span>${String(z.mb_s).replace(".", ",")} MB/s${z.rest_s ? " · noch etwa " + rest(z.rest_s) : ""}</span>` : html`<span>Tempo wird gemessen …</span>`)}
      ${z.start ? html`<span>seit ${zeitText(z.start).replace("vor ", "")}</span>` : ""}
    </div>
    <div class="knopfreihe">${(z.steuerung || []).map((a) => html`<${Steuerknopf} key=${a} z=${z} aktion=${a} neu=${neu} />`)}<${Ansehen} z=${z} /></div>
  </div>`;
}

export function Aktionen() {
  const [d, setD] = useState(null);
  const neu = () => api("/aktionen").then(setD).catch(fehlerMelden);
  useEffect(() => {
    bus.sende("talk-kontext", { art: "aktionen", id: "aktionen", titel: "Current Actions" });
    neu();
    // Alle 3 Sekunden, solange die Seite offen ist -- Downloads und Etappen
    // sollen sich sichtbar bewegen; im Hintergrund-Tab wird nicht gefragt.
    const t = setInterval(() => { if (!document.hidden) neu(); }, 3000);
    return () => { clearInterval(t); bus.sende("talk-kontext", null); };
  }, []);
  if (!d) return html`<div class="lade">Lade …</div>`;
  const o = d.ollama || {};
  return html`<div class="seite">
    <div class="karte ak-ollama">
      <b>${d.laufend.length ? `${d.laufend.length} ${d.laufend.length === 1 ? "Aktion" : "Aktionen"}` : "Gerade läuft nichts."}</b>
      <span class="leise klein">${o.anfragen ? `Ollama rechnet gerade ${o.anfragen} ${o.anfragen === 1 ? "Anfrage" : "Anfragen"}${o.seit ? " (seit " + zeitText(o.seit).replace("vor ", "") + ")" : ""}` : "Ollama rechnet gerade nichts"}${(o.taetig || []).length ? ": " + o.taetig.map((t) => t.was).join(", ") : ""}.</span>
      ${d.pipeline_wartet > 0 && html`<a class="leise klein" href="#/inbox">${d.pipeline_wartet} Cases warten auf das Team</a>`}
    </div>
    ${d.laufend.length ? html`<div class="ak-liste">${d.laufend.map((z) => html`<${Karte} key=${z.id} z=${z} neu=${neu} />`)}</div>`
      : html`<${Leer} titel="Nichts in Arbeit">Downloads, Langläufer, Videos, Bilder, Antworten in Gesprächen, Neos Aufträge und Modell-Vergleiche erscheinen hier, sobald sie laufen.<//>`}
    ${d.beendet.length > 0 && html`<section class="karte" style="margin-top:14px">
      <div class="karte-kopf"><h3>Gerade fertig geworden</h3><span class="leise klein">letzte Stunde</span></div>
      <div class="ak-liste">${d.beendet.map((z) => html`<${Karte} key=${z.id} z=${{ ...z, stand: "fertig" }} neu=${neu} />`)}</div></section>`}
  </div>`;
}
