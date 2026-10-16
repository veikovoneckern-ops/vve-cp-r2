// VERBRAUCH -- Token und Kosten, die Seite "AI Consumption" des alten Cockpits
// neu (Veiko, 16.10.2026). Gleich geblieben: Zeitraum (Heute, Woche, Monat,
// Jahr, eigener), Projektfilter, eine Karte je Anbieter, eine sortierbare
// Tabelle nach Vorgang und Modell. Anders: die Token sind exakt (lokal meldet
// Ollama sie, in der Cloud der Anbieter), lokale Arbeit kostet nichts, und die
// Preise, mit denen die Cloud-Kosten gerechnet werden, stehen sichtbar und
// aenderbar auf der Seite -- eine stille Annahme waere eine erfundene Zahl.
import { html, useState, useEffect, Icon, toast, fehlerMelden, zeitText } from "./ui.js";
import { api } from "./api.js";

const ZEITRAUM = [["heute", "Heute"], ["woche", "Woche"], ["monat", "Monat"], ["jahr", "Jahr"], ["alles", "Alles"], ["eigen", "Eigener Zeitraum"]];
const tok = (n) => (n >= 1e6 ? (n / 1e6).toFixed(2).replace(".", ",") + " Mio." : n >= 1e3 ? (n / 1e3).toFixed(1).replace(".", ",") + " Tsd." : String(n || 0));
const usd = (n) => "$ " + (n > 0 && n < 0.01 ? n.toFixed(4) : n.toFixed(2)).replace(".", ",");
const dauer = (s) => (s >= 3600 ? (s / 3600).toFixed(1).replace(".", ",") + " Std." : s >= 60 ? Math.round(s / 60) + " Min." : Math.round(s || 0) + " s");

function fenster(art, von, bis) {
  const jetzt = Date.now() / 1000;
  if (art === "heute") { const d = new Date(); d.setHours(0, 0, 0, 0); return [d.getTime() / 1000, 0]; }
  if (art === "woche") return [jetzt - 7 * 86400, 0];
  if (art === "monat") return [jetzt - 30 * 86400, 0];
  if (art === "jahr") return [jetzt - 365 * 86400, 0];
  if (art === "eigen") return [von ? new Date(von + "T00:00:00").getTime() / 1000 : 0, bis ? new Date(bis + "T23:59:59").getTime() / 1000 : 0];
  return [0, 0];
}

function Preise({ preise, vorgabe, gespeichert }) {
  const [p, setP] = useState(preise);
  useEffect(() => setP(preise), [JSON.stringify(preise)]);
  const NAME = { claude: "Dario · Claude", grok: "Elon · Grok", gemini: "Demmis · Gemini" };
  async function speichern() {
    try { const r = await api("/verbrauch/preise", { methode: "POST", daten: p }); toast("Preise gespeichert."); gespeichert(r.preise); }
    catch (e) { fehlerMelden(e); }
  }
  const feld = (k, i) => html`<input class="eingabe vb-preis" type="number" min="0" step="0.01" value=${p[k][i]}
    onInput=${(e) => setP({ ...p, [k]: i ? [p[k][0], e.target.value] : [e.target.value, p[k][1]] })} aria-label=${NAME[k] + (i ? " Ausgabe" : " Eingabe")} />`;
  return html`<details class="karte vb-preise">
    <summary><b>Mit welchen Preisen gerechnet wird</b> <span class="leise klein">US-$ je 1 Mio. Token -- Annahme, bitte mit deiner Rechnung abgleichen</span></summary>
    <table class="tabelle"><thead><tr><th>Anbieter</th><th>Eingabe</th><th>Ausgabe</th><th class="leise">Vorgabe</th></tr></thead>
      <tbody>${Object.keys(p).map((k) => html`<tr><td>${NAME[k] || k}</td><td>${feld(k, 0)}</td><td>${feld(k, 1)}</td>
        <td class="leise klein">${vorgabe[k][0]} / ${vorgabe[k][1]}</td></tr>`)}</tbody></table>
    <div class="knopfreihe" style="margin-top:8px"><button class="btn primaer klein" onClick=${speichern}>Preise speichern</button>
      <span class="leise klein">Lokale Modelle kosten nichts: sie rechnen auf deinem eigenen Server (nur Strom).</span></div>
  </details>`;
}

export function Verbrauch() {
  const [art, setArt] = useState(() => { try { return localStorage.getItem("vb-zeitraum") || "monat"; } catch (e) { return "monat"; } });
  const [von, setVon] = useState("");
  const [bis, setBis] = useState("");
  const [projekt, setProjekt] = useState("");
  const [d, setD] = useState(null);
  const [sort, setSort] = useState({ feld: "kosten", richtung: -1 });
  const laden = () => {
    const [a, b] = fenster(art, von, bis);
    api(`/verbrauch?von=${a}&bis=${b}&projekt=${encodeURIComponent(projekt)}`).then(setD).catch(fehlerMelden);
  };
  useEffect(() => { try { localStorage.setItem("vb-zeitraum", art); } catch (e) { /* egal */ } laden(); }, [art, von, bis, projekt]);
  if (!d) return html`<div class="seite"><div class="lade">Lade Verbrauch …</div></div>`;

  const ges = d.je_anbieter.reduce((s, a) => ({ kosten: s.kosten + a.kosten, aufrufe: s.aufrufe + a.aufrufe, tok: s.tok + a.ein + a.aus }), { kosten: 0, aufrufe: 0, tok: 0 });
  const karten = ["ollama", "claude", "grok", "gemini"].map((k) => d.je_anbieter.find((a) => a.anbieter === k)
    || { anbieter: k, name: { ollama: "Lokal (eigener Server)", claude: "Dario · Claude", grok: "Elon · Grok", gemini: "Demmis · Gemini" }[k], aufrufe: 0, ein: 0, aus: 0, dauer: 0, kosten: 0 });
  const zeilen = [...d.zeilen].sort((a, b) => {
    const va = sort.feld === "tok" ? a.ein + a.aus : a[sort.feld], vb = sort.feld === "tok" ? b.ein + b.aus : b[sort.feld];
    return (typeof va === "string" ? String(va).localeCompare(String(vb), "de") : (va || 0) - (vb || 0)) * sort.richtung;
  });
  const th = (feld, text, zahl) => html`<th class=${zahl ? "zahl" : ""}><button class="vb-sort" onClick=${() => setSort({ feld, richtung: sort.feld === feld ? -sort.richtung : -1 })}>
    ${text}${sort.feld === feld ? (sort.richtung < 0 ? " ▾" : " ▴") : ""}</button></th>`;

  return html`<div class="seite vb">
    <div class="vb-filter">
      <div class="segment">${ZEITRAUM.map(([id, t]) => html`<button class=${art === id ? "an" : ""} onClick=${() => setArt(id)}>${t}</button>`)}</div>
      ${art === "eigen" && html`<span class="knopfreihe"><input class="eingabe" type="date" value=${von} onInput=${(e) => setVon(e.target.value)} aria-label="Von" />
        – <input class="eingabe" type="date" value=${bis} onInput=${(e) => setBis(e.target.value)} aria-label="Bis" /></span>`}
      <select class="eingabe" value=${projekt} onChange=${(e) => setProjekt(e.target.value)} aria-label="Projekt">
        <option value="">Alle Projekte</option>${d.projekte.map((p) => html`<option value=${p.id}>${p.name}</option>`)}</select>
      <button class="btn klein geist" onClick=${laden} title="Neu laden"><${Icon} n="neu" g=${14} /></button>
    </div>

    <div class="vb-karten">
      ${karten.map((a) => html`<div class=${"karte vb-karte " + a.anbieter}>
        <div class="leise klein">${a.name}</div>
        <div class="vb-betrag">${a.anbieter === "ollama" ? "kostenlos" : usd(a.kosten)}</div>
        <div class="klein">${a.aufrufe} Aufrufe · ${tok(a.ein + a.aus)} Token${a.anbieter === "ollama" && a.dauer ? ` · ${dauer(a.dauer)} Rechenzeit` : ""}</div></div>`)}
      <div class="karte vb-karte gesamt"><div class="leise klein">Gesamt</div><div class="vb-betrag">${usd(ges.kosten)}</div>
        <div class="klein">${ges.aufrufe} Aufrufe · ${tok(ges.tok)} Token</div></div>
    </div>

    <section class="karte">
      <div class="karte-kopf"><h3>Aufschlüsselung nach Vorgang und Modell</h3></div>
      ${zeilen.length ? html`<div class="tabelle-wrap"><table class="tabelle vb-tabelle">
        <thead><tr>${th("bereich", "Wofür")}${th("modell", "Modell")}${th("aufrufe", "Aufrufe", 1)}${th("ein", "Eingabe", 1)}${th("aus", "Ausgabe", 1)}${th("dauer", "Rechenzeit", 1)}${th("kosten", "Kosten", 1)}</tr></thead>
        <tbody>${zeilen.map((z) => html`<tr class=${z.quelle === "alt" ? "alt" : ""}>
          <td>${z.bereich}${z.geschaetzt ? html` <span class="pill" title="Token geschätzt (Zeichen ÷ 4) -- dort wurden keine Zähler gemeldet">geschätzt</span>` : ""}</td>
          <td>${z.anbieter === "ollama" ? (z.modell || "lokal") : `${{ claude: "Dario", grok: "Elon", gemini: "Demmis" }[z.anbieter] || z.anbieter}${z.modell ? " · " + z.modell : ""}`}</td>
          <td class="zahl">${z.aufrufe}</td><td class="zahl">${tok(z.ein)}</td><td class="zahl">${tok(z.aus)}</td>
          <td class="zahl">${z.dauer ? dauer(z.dauer) : "–"}</td>
          <td class="zahl"><b>${z.anbieter === "ollama" ? "–" : usd(z.kosten)}</b></td></tr>`)}</tbody>
        <tfoot><tr><td colspan="2">Gesamt</td><td class="zahl">${ges.aufrufe}</td><td class="zahl" colspan="3">${tok(ges.tok)} Token</td><td class="zahl"><b>${usd(ges.kosten)}</b></td></tr></tfoot>
      </table></div>` : html`<p class="leise">Im gewählten Zeitraum wurde nichts gerechnet${projekt ? " (für dieses Projekt)" : ""}.</p>`}
      <p class="leise klein" style="margin-top:10px">
        Mitgeschrieben wird ${d.erfasst_seit ? `seit ${new Date(d.erfasst_seit * 1000).toLocaleDateString("de-DE")} ${new Date(d.erfasst_seit * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}` : "ab jetzt"}; davor zählt nur, was das alte Cockpit notiert hat (grau, Token dort geschätzt).
        „Wofür“ richtet sich nach dem, was gerade lief -- liefen zwei Dinge gleichzeitig, kann ein Aufruf dem falschen zugeordnet sein. Die Token selbst sind exakt.
        Cloud-Kosten = Token × Preis aus der Tabelle unten, keine Abrechnung des Anbieters.</p>
    </section>

    <${Preise} preise=${d.preise} vorgabe=${d.preise_vorgabe} gespeichert=${() => laden()} />
  </div>`;
}
