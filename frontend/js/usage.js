// USAGE (19.10.2026) -- Veiko: "eine eigene Seite fuer das Thema Verbrauch mit dem
// Button Usage. Hier moechte ich wie im alten Cockpit eine Seite mit verschiedenen
// Ansichten und Filtern haben, nach Projekten, Aufgaben, Modellen etc. und auch
// Stromverbrauch." Ersetzt den Reiter "Verbrauch" (verbrauch.js) -- kein zweiter Weg.
//
// Oben die Filter in EINER Reihe, darunter die Summen, dann eine Ansicht zur Zeit.
// Ein Klick auf eine Zeile filtert danach ("nur dieses Projekt"). Alles kommt aus
// /api/usage (usage.py): exakte Token je Aufruf, Rechenzeit, Cloud-Kosten aus der
// Preistabelle unten, Strom aus den Zaehlern der beiden Shelly-Dosen. Was nicht
// gemessen ist, steht nicht da -- Strom gibt es je Tag und Dose, nicht je Projekt.
import { html, useState, useEffect, Icon, toast, fehlerMelden, bus } from "./ui.js";
import { api } from "./api.js";

const ZEITRAUM = [["heute", "Heute"], ["woche", "7 Tage"], ["monat", "30 Tage"], ["jahr", "Jahr"], ["alles", "Alles"], ["eigen", "Eigener"]];
const ANSICHTEN = [["projekt", "Projekte"], ["aufgabe", "Aufgaben"], ["modell", "Modelle"], ["rolle", "Rollen"], ["bereich", "Bereiche"], ["tag", "Verlauf"], ["strom", "Strom"]];
const MASSE = [["dauer", "Rechenzeit"], ["token", "Token"], ["kosten", "Cloud-Kosten"], ["aufrufe", "Aufrufe"]];
const ANBIETER = { ollama: "Lokal", claude: "Dario · Claude", grok: "Elon · Grok", gemini: "Demmis · Gemini" };

const tok = (n) => (n >= 1e6 ? (n / 1e6).toFixed(2).replace(".", ",") + " Mio." : n >= 1e3 ? (n / 1e3).toFixed(1).replace(".", ",") + " Tsd." : String(n || 0));
const usd = (n) => "$ " + ((n || 0) > 0 && n < 0.01 ? n.toFixed(4) : (n || 0).toFixed(2)).replace(".", ",");
const dauer = (s) => (s >= 3600 ? (s / 3600).toFixed(1).replace(".", ",") + " Std." : s >= 60 ? Math.round(s / 60) + " Min." : Math.round(s || 0) + " s");
const kwh = (x) => (x == null ? "–" : x.toFixed(x < 10 ? 2 : 1).replace(".", ",") + " kWh");
const eur = (x) => (x == null ? "–" : x.toFixed(2).replace(".", ",") + " €");
const wert = (g, mass) => (mass === "token" ? (g.ein || 0) + (g.aus || 0) : g[mass] || 0);
const zeigen = (x, mass) => (mass === "token" ? tok(x) : mass === "kosten" ? usd(x) : mass === "dauer" ? dauer(x) : String(x));
const tagKurz = (t) => { const [, m, d] = t.split("-"); return `${+d}.${+m}.`; };

function fenster(art, von, bis) {
  const jetzt = Date.now() / 1000;
  if (art === "heute") { const d = new Date(); d.setHours(0, 0, 0, 0); return [d.getTime() / 1000, 0]; }
  if (art === "woche") return [jetzt - 7 * 86400, 0];
  if (art === "monat") return [jetzt - 30 * 86400, 0];
  if (art === "jahr") return [jetzt - 365 * 86400, 0];
  if (art === "eigen") return [von ? new Date(von + "T00:00:00").getTime() / 1000 : 0, bis ? new Date(bis + "T23:59:59").getTime() / 1000 : 0];
  return [0, 0];
}
const merk = (k, v) => { try { localStorage.setItem("us-" + k, v); } catch (e) { /* egal */ } };
const lies = (k, v) => { try { return localStorage.getItem("us-" + k) || v; } catch (e) { return v; } };

export function Usage() {
  const [art, setArt] = useState(() => lies("zeitraum", "monat"));
  const [von, setVon] = useState("");
  const [bis, setBis] = useState("");
  const [f, setF] = useState({ projekt: "", aufgabe: "", modell: "", rolle: "", art: "" });
  const [namen, setNamen] = useState({});   // Anzeige der gewaehlten Aufgabe
  const [ansicht, setAnsicht] = useState(() => lies("ansicht", "projekt"));
  const [mass, setMass] = useState(() => lies("mass", "dauer"));
  const [d, setD] = useState(null);
  const laden = () => {
    const [a, b] = fenster(art, von, bis);
    const q = new URLSearchParams({ von: a, bis: b, ...f });
    api("/usage?" + q).then(setD).catch(fehlerMelden);
  };
  useEffect(() => { merk("zeitraum", art); laden(); }, [art, von, bis, JSON.stringify(f)]);
  useEffect(() => { merk("ansicht", ansicht); }, [ansicht]);
  useEffect(() => { merk("mass", mass); }, [mass]);
  useEffect(() => { bus.sende("talk-kontext", { art: "usage", id: "usage", titel: "Usage" }); return () => bus.sende("talk-kontext", null); }, []);
  if (!d) return html`<div class="seite"><div class="lade">Lade Usage …</div></div>`;
  const s = d.summe;
  const st = d.strom;
  const filtern = (g) => {
    if (ansicht === "projekt") setF({ ...f, projekt: g.schluessel });
    else if (ansicht === "aufgabe") { setF({ ...f, aufgabe: g.schluessel }); setNamen({ ...namen, aufgabe: g.name }); }
    else if (ansicht === "modell") setF({ ...f, modell: g.schluessel.split("|")[1] || "" });
    else if (ansicht === "rolle") setF({ ...f, rolle: g.schluessel === "_sonst" ? "" : g.schluessel });
  };
  const aktiv = Object.values(f).some(Boolean);
  return html`<div class="seite us">
    <div class="us-filter" role="group" aria-label="Filter">
      <div class="segment">${ZEITRAUM.map(([id, t]) => html`<button class=${art === id ? "an" : ""} onClick=${() => setArt(id)}>${t}</button>`)}</div>
      ${art === "eigen" && html`<span class="knopfreihe"><input class="eingabe" type="date" value=${von} onInput=${(e) => setVon(e.target.value)} aria-label="Von" />
        – <input class="eingabe" type="date" value=${bis} onInput=${(e) => setBis(e.target.value)} aria-label="Bis" /></span>`}
      <select class="eingabe" value=${f.projekt} onChange=${(e) => setF({ ...f, projekt: e.target.value, aufgabe: "" })} aria-label="Projekt">
        <option value="">Alle Projekte</option><option value="_ohne">ohne Projekt</option>
        ${d.auswahl.projekte.map((p) => html`<option value=${p.id}>${p.name}</option>`)}</select>
      <select class="eingabe" value=${f.modell} onChange=${(e) => setF({ ...f, modell: e.target.value })} aria-label="Modell">
        <option value="">Alle Modelle</option>${d.auswahl.modelle.map((m) => html`<option value=${m}>${m}</option>`)}</select>
      <select class="eingabe" value=${f.rolle} onChange=${(e) => setF({ ...f, rolle: e.target.value })} aria-label="Rolle">
        <option value="">Alle Rollen</option>${d.auswahl.rollen.map((r) => html`<option value=${r.id}>${r.name}</option>`)}</select>
      <div class="segment">${[["", "Lokal + Cloud"], ["lokal", "Lokal"], ["cloud", "Cloud"]].map(([k, t]) => html`<button class=${f.art === k ? "an" : ""} onClick=${() => setF({ ...f, art: k })}>${t}</button>`)}</div>
      ${f.aufgabe && html`<span class="pill lila">Aufgabe: ${namen.aufgabe || "gewählt"} <button class="us-weg" onClick=${() => setF({ ...f, aufgabe: "" })} aria-label="Aufgabenfilter entfernen">×</button></span>`}
      ${aktiv && html`<button class="btn klein geist" onClick=${() => setF({ projekt: "", aufgabe: "", modell: "", rolle: "", art: "" })}>Filter zurücksetzen</button>`}
    </div>

    <div class="us-kacheln">
      <div class="karte us-kachel"><span class="leise klein">Rechenzeit lokal</span><b>${dauer(s.dauer)}</b><span class="klein leise">${s.aufrufe} Aufrufe</span></div>
      <div class="karte us-kachel"><span class="leise klein">Token</span><b>${tok(s.ein + s.aus)}</b><span class="klein leise">${tok(s.ein)} gelesen · ${tok(s.aus)} geschrieben</span></div>
      <div class="karte us-kachel"><span class="leise klein">Cloud-Kosten</span><b>${usd(s.kosten)}</b><span class="klein leise">lokal kostet nichts außer Strom</span></div>
      <div class="karte us-kachel"><span class="leise klein">Strom</span><b>${st.tage.length ? kwh(st.summe) : "–"}</b>
        <span class="klein leise">${st.tage.length ? (st.kosten != null ? eur(st.kosten) : "Strompreis fehlt") : "noch keine Aufzeichnung"}${aktiv && st.tage.length ? " · ganzer Server, ungefiltert" : ""}</span></div>
    </div>

    <div class="us-ansicht">
      <div class="segment us-reiter" role="tablist">${ANSICHTEN.map(([k, t]) => html`<button role="tab" aria-selected=${ansicht === k} class=${ansicht === k ? "an" : ""} onClick=${() => setAnsicht(k)}>${t}</button>`)}</div>
      ${ansicht !== "strom" && html`<label class="klein leise us-mass">Maß
        <select class="eingabe" value=${mass} onChange=${(e) => setMass(e.target.value)}>${MASSE.map(([k, t]) => html`<option value=${k}>${t}</option>`)}</select></label>`}
    </div>

    ${ansicht === "strom" ? html`<${Strom} st=${st} neu=${laden} />`
      : ansicht === "tag" ? html`<${Verlauf} tage=${d.nach.tag} mass=${mass} />`
      : html`<${Liste} zeilen=${d.nach[ansicht]} mass=${mass} ansicht=${ansicht} filtern=${filtern} />`}

    <p class="leise klein us-fuss">Mitgeschrieben wird seit ${d.erfasst_seit ? new Date(d.erfasst_seit * 1000).toLocaleDateString("de-DE") : "jetzt"}. Token und Rechenzeit sind exakt (Ollama bzw. der Cloud-Anbieter meldet sie).
      Die Zuordnung zu Projekt und Aufgabe läuft über den Case, aus dem ein Aufruf kam; Gespräche ohne Bezug stehen unter „ohne Projekt“.
      Cloud-Kosten = Token × Preis aus der Tabelle unten, keine Abrechnung des Anbieters.</p>
    <${Preise} preise=${d.preise} vorgabe=${d.preise_vorgabe} gespeichert=${laden} />
  </div>`;
}

// Eine Tabelle mit Balken je Zeile: lesbar auch auf dem Telefon, sortierbar.
function Liste({ zeilen, mass, ansicht, filtern }) {
  const [sort, setSort] = useState(null);
  const liste = [...zeilen].sort((a, b) => {
    if (!sort) return wert(b, mass) - wert(a, mass);
    const va = sort.feld === "name" ? a.name : wert(a, sort.feld), vb = sort.feld === "name" ? b.name : wert(b, sort.feld);
    return (typeof va === "string" ? va.localeCompare(vb, "de") : va - vb) * sort.richtung;
  });
  const max = Math.max(1e-9, ...liste.map((g) => wert(g, mass)));
  const klickbar = ["projekt", "aufgabe", "modell", "rolle"].includes(ansicht);
  const th = (feld, text, zahl) => html`<th class=${zahl ? "zahl" : ""}><button class="vb-sort" onClick=${() => setSort({ feld, richtung: sort && sort.feld === feld ? -sort.richtung : (feld === "name" ? 1 : -1) })}>
    ${text}${sort && sort.feld === feld ? (sort.richtung < 0 ? " ▾" : " ▴") : ""}</button></th>`;
  if (!liste.length) return html`<div class="karte"><p class="leise">${ansicht === "aufgabe" ? "Im Zeitraum wurde für keine Aufgabe gerechnet -- oder die Aufrufe hingen an keinem Case mit Aufgabe." : "Im gewählten Zeitraum wurde nichts gerechnet."}</p></div>`;
  return html`<section class="karte"><div class="tabelle-wrap"><table class="tabelle us-tabelle">
    <thead><tr>${th("name", { projekt: "Projekt", aufgabe: "Aufgabe", modell: "Modell", rolle: "Rolle", bereich: "Bereich" }[ansicht])}
      <th class="us-balken-kopf">${(MASSE.find((m) => m[0] === mass) || [])[1]}</th>
      ${th("aufrufe", "Aufrufe", 1)}${th("token", "Token", 1)}${th("dauer", "Rechenzeit", 1)}${th("kosten", "Kosten", 1)}</tr></thead>
    <tbody>${liste.map((g) => html`<tr class=${klickbar ? "klickbar" : ""} onClick=${klickbar ? () => filtern(g) : null}
        title=${klickbar ? "Klicken: nur das zeigen" : ""}>
      <td><b>${g.name}</b>${g.projekt ? html`<div class="leise klein">${g.projekt}</div>` : ""}${g.anbieter && g.anbieter !== "ollama" ? html` <span class="pill">${ANBIETER[g.anbieter] || g.anbieter}</span>` : ""}</td>
      <td class="us-balken-zelle"><span class="us-balken" style=${`width:${Math.max(2, wert(g, mass) / max * 100)}%`} aria-hidden="true"></span>
        <span class="klein">${zeigen(wert(g, mass), mass)}</span></td>
      <td class="zahl">${g.aufrufe}</td><td class="zahl">${tok(g.ein + g.aus)}</td><td class="zahl">${g.dauer ? dauer(g.dauer) : "–"}</td>
      <td class="zahl">${g.kosten ? usd(g.kosten) : "–"}</td></tr>`)}</tbody>
  </table></div></section>`;
}

// Saeulen je Tag, ein Mass, eine Farbe. Hover zeigt den genauen Wert.
function Verlauf({ tage, mass }) {
  const [an, setAn] = useState(null);
  if (!tage.length) return html`<div class="karte"><p class="leise">Im gewählten Zeitraum wurde nichts gerechnet.</p></div>`;
  const max = Math.max(1e-9, ...tage.map((t) => wert(t, mass)));
  const g = an != null ? tage[an] : null;
  return html`<section class="karte"><div class="karte-kopf"><h3>${(MASSE.find((m) => m[0] === mass) || [])[1]} je Tag</h3>
      <span class="leise klein">${g ? `${tagKurz(g.schluessel)}: ${zeigen(wert(g, mass), mass)} · ${g.aufrufe} Aufrufe` : "Zeig auf eine Säule für den genauen Wert"}</span></div>
    <div class="us-saeulen" role="img" aria-label=${"Verlauf je Tag: " + tage.map((t) => `${tagKurz(t.schluessel)} ${zeigen(wert(t, mass), mass)}`).join(", ")}
      onMouseLeave=${() => setAn(null)}>
      ${tage.map((t, i) => html`<div class=${"us-saeule-feld" + (an === i ? " an" : "")} onMouseEnter=${() => setAn(i)} onClick=${() => setAn(i)} title=${`${tagKurz(t.schluessel)}: ${zeigen(wert(t, mass), mass)}`}>
        <span class="us-saeule" style=${`height:${Math.max(1, wert(t, mass) / max * 100)}%`}></span>
        ${(tage.length <= 14 || i % Math.ceil(tage.length / 10) === 0) && html`<span class="us-tag">${tagKurz(t.schluessel)}</span>`}</div>`)}
    </div></section>`;
}

function Strom({ st, neu }) {
  const [preis, setPreis] = useState(st.preis != null ? String(st.preis).replace(".", ",") : "");
  const [an, setAn] = useState(null);
  async function speichern() {
    try { await api("/usage/strompreis", { methode: "POST", daten: { preis } }); toast("Strompreis gespeichert."); neu(); } catch (e) { fehlerMelden(e); }
  }
  const tage = st.tage;
  const max = Math.max(1e-9, ...tage.map((t) => t.summe));
  const g = an != null ? tage[an] : null;
  return html`<section class="karte">
    <div class="karte-kopf"><h3>Strom je Tag</h3>
      <span class="us-legende"><i class="us-a"></i>${st.dosen.server}<i class="us-b"></i>${st.dosen.dock}</span></div>
    ${tage.length ? html`
      <div class="leise klein us-wert">${g ? `${tagKurz(g.tag)}: ${kwh(g.summe)} (Server ${kwh(g.server)}, Dock ${kwh(g.dock)})${g.kosten != null ? " · " + eur(g.kosten) : ""}` : "Zeig auf eine Säule für den genauen Wert"}</div>
      <div class="us-saeulen" role="img" aria-label=${"Strom je Tag: " + tage.map((t) => `${tagKurz(t.tag)} ${kwh(t.summe)}`).join(", ")} onMouseLeave=${() => setAn(null)}>
        ${tage.map((t, i) => html`<div class=${"us-saeule-feld" + (an === i ? " an" : "")} onMouseEnter=${() => setAn(i)} onClick=${() => setAn(i)} title=${`${tagKurz(t.tag)}: ${kwh(t.summe)}`}>
          <span class="us-stapel" style=${`height:${Math.max(1, t.summe / max * 100)}%`}>
            <span class="us-b" style=${`flex:${t.dock || 0}`}></span><span class="us-a" style=${`flex:${t.server || 0}`}></span></span>
          ${(tage.length <= 14 || i % Math.ceil(tage.length / 10) === 0) && html`<span class="us-tag">${tagKurz(t.tag)}</span>`}</div>`)}
      </div>
      <div class="tabelle-wrap" style="margin-top:12px"><table class="tabelle">
        <thead><tr><th>Dose</th><th class="zahl">Verbrauch</th><th class="zahl">Ø Leistung</th><th class="zahl">Kosten</th></tr></thead>
        <tbody>${Object.entries(st.dosen).map(([k, n]) => html`<tr><td>${n}</td><td class="zahl">${kwh(st.gesamt[k])}</td>
          <td class="zahl">${st.mittel_w[k] != null ? st.mittel_w[k] + " W" : "–"}</td><td class="zahl">${st.preis != null ? eur(st.gesamt[k] * st.preis) : "–"}</td></tr>`)}</tbody>
        <tfoot><tr><td>Zusammen</td><td class="zahl"><b>${kwh(st.summe)}</b></td><td></td><td class="zahl"><b>${eur(st.kosten)}</b></td></tr></tfoot>
      </table></div>`
      : html`<p class="leise">Für diesen Zeitraum gibt es noch keine Messung. Das Cockpit schreibt seit diesem Update alle fünf Minuten die Zähler beider Shelly-Steckdosen mit; der erste Tag steht morgen hier.</p>`}
    <div class="knopfreihe" style="margin-top:12px">
      <label class="klein" for="us-preis">Strompreis (€ je kWh)</label>
      <input id="us-preis" class="eingabe us-preis" inputmode="decimal" placeholder="z. B. 0,32" value=${preis} onInput=${(e) => setPreis(e.target.value)}
        onKeyDown=${(e) => { if (e.key === "Enter") speichern(); }} />
      <button class="btn klein primaer" onClick=${speichern}>Speichern</button>
    </div>
    <p class="leise klein" style="margin-top:8px">Gemessen an den beiden Steckdosen (Shelly) vor Mini-PC und Grafik-Dock -- also der ganze Server, nicht einzelne Projekte. Je Projekt lässt sich Strom nicht messen; dafür steht dort die Rechenzeit.
      ${st.seit ? ` Aufzeichnung seit ${new Date(st.seit * 1000).toLocaleDateString("de-DE")}.` : ""}</p>
  </section>`;
}

// Mit welchen Preisen Cloud-Kosten gerechnet werden (vorher verbrauch.js): sichtbar
// und aenderbar -- eine stille Annahme waere eine erfundene Zahl.
function Preise({ preise, vorgabe, gespeichert }) {
  const [p, setP] = useState(preise);
  useEffect(() => setP(preise), [JSON.stringify(preise)]);
  const NAME = { claude: "Dario · Claude", grok: "Elon · Grok", gemini: "Demmis · Gemini" };
  async function speichern() {
    try { await api("/verbrauch/preise", { methode: "POST", daten: p }); toast("Preise gespeichert."); gespeichert(); }
    catch (e) { fehlerMelden(e); }
  }
  const feld = (k, i) => html`<input class="eingabe vb-preis" type="number" min="0" step="0.01" value=${p[k][i]}
    onInput=${(e) => setP({ ...p, [k]: i ? [p[k][0], e.target.value] : [e.target.value, p[k][1]] })} aria-label=${NAME[k] + (i ? " Ausgabe" : " Eingabe")} />`;
  return html`<details class="karte vb-preise">
    <summary><b>Mit welchen Preisen gerechnet wird</b> <span class="leise klein">US-$ je 1 Mio. Token -- Annahme, bitte mit deiner Rechnung abgleichen</span></summary>
    <div class="tabelle-wrap"><table class="tabelle"><thead><tr><th>Anbieter</th><th>Eingabe</th><th>Ausgabe</th><th class="leise">Vorgabe</th></tr></thead>
      <tbody>${Object.keys(p).map((k) => html`<tr><td>${NAME[k] || k}</td><td>${feld(k, 0)}</td><td>${feld(k, 1)}</td>
        <td class="leise klein">${vorgabe[k][0]} / ${vorgabe[k][1]}</td></tr>`)}</tbody></table></div>
    <div class="knopfreihe" style="margin-top:8px"><button class="btn primaer klein" onClick=${speichern}>Preise speichern</button>
      <span class="leise klein">Lokale Modelle kosten nichts: sie rechnen auf deinem eigenen Server (nur Strom).</span></div>
  </details>`;
}
