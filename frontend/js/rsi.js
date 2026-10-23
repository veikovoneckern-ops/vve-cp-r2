// RSI (23.10.2026) -- das Cockpit verbessert sich aus Veikos Gespraechen (cockpit/rsi.py, rsi_serie.py).
// Neo findet nachts, wo es hakte, Veiko waehlt aus, Neo setzt um (Dario prueft), am Ende ein Release.
//
// Aufbau seit dem 23.10.2026 abends (Veiko: "etwas einfacher von der Usability, idiotensicher im Sinne
// von: was muss ich machen und was ist gelaufen"):
//   1. Oben EIN Kasten "Was jetzt zu tun ist" -- genau ein Zustand, ein Satz, hoechstens ein Hauptknopf,
//      darueber die Schrittleiste (Neo findet -> du waehlst -> Neo setzt um -> Release).
//   2. Darunter die Vorschlaege: Ankreuzbox, was passiert ist, Darios Einschaetzung in einem Satz.
//      Alles Technische (Belege, Neos Vorschlag, Plan) hinter "Details". Die frueheren Einzelknoepfe je
//      Karte (Neo ausarbeiten, Plan bestellen, pruefen lassen) sind weg -- sie waren drei Wege zum selben Ziel.
//   3. Unten "Was gelaufen ist": letzter Durchlauf, Releases (zuruecknehmen), Erledigtes. Einstellungen zu.
import { html, useState, useEffect, Icon, Md, bus, toast, fehlerMelden, zeitText, useAbruf } from "./ui.js";
import { api } from "./api.js";

const URTEIL = { sinnvoll: ["gruen", "Dario: sinnvoll"], ueberarbeiten: ["gelb", "Dario: Richtung stimmt, noch unscharf"],
  verwerfen: ["rot", "Dario rät ab"], nicht_geprueft: ["", "noch nicht geprüft"] };
const ALT_STAND = { umgesetzt: ["gruen", "umgesetzt"], verworfen: ["", "verworfen"], erledigt: ["gruen", "erledigt"],
  zurueckgenommen: ["", "zurückgenommen"], zusammengelegt: ["", "zusammengelegt"] };
const dollar = (x) => "$ " + Number(x || 0).toFixed(2).replace(".", ",");
const WAEHLBAR = ["neu", "geprueft", "plan"];
const IN_ARBEIT = ["bei_neo", "in_serie"];

// ------------------------------------------------------------ Schrittleiste
function Schritte({ aktiv }) {
  const S = [["finden", "Neo findet Probleme"], ["waehlen", "Du wählst aus"], ["umsetzen", "Neo setzt um, Dario prüft"], ["fertig", "Neues Release"]];
  const i = S.findIndex(([k]) => k === aktiv);
  return html`<ol class="rsi-schritte">${S.map(([k, t], n) => html`<li class=${n < i ? "war" : n === i ? "jetzt" : ""}><span>${n + 1}</span>${t}</li>`)}</ol>`;
}

// ------------------------------------------------------------ "Was jetzt zu tun ist"
function JetztKasten({ d, waehlbare, wahl, setWahlAlle, titel, laden }) {
  const s = d.serie || {};
  const st = d.stand || {};
  const [laeuft, setLaeuft] = useState(false);
  async function tun(pfad, text) {
    setLaeuft(true);
    try { await api(pfad, { methode: "POST" }); if (text) toast(text); laden(); } catch (e) { fehlerMelden(e); }
    setLaeuft(false);
  }
  const t = (i) => titel[i] || i;
  const erg = s.ergebnisse || {};
  const reihe = s.reihenfolge || [];
  const nichtsTun = html`<p class="rsi-du">Du musst nichts tun. Du kannst die Seite verlassen.</p>`;
  const fortschritt = html`<ul class="rsi-fortschritt">${reihe.map((i) => {
    const e = erg[i];
    const zeichen = e ? (e.stand === "umgesetzt" ? "✓" : "✗") : s.aktuell === i ? "▶" : "·";
    return html`<li class=${e ? (e.stand === "umgesetzt" ? "ok" : "nein") : s.aktuell === i ? "jetzt" : ""}><span class="rsi-zeichen">${zeichen}</span> ${t(i)}
      ${s.aktuell === i && s.aktuell_schritt ? html` <span class="leise klein">-- ${s.aktuell_schritt}</span>` : ""}
      ${e && e.stand !== "umgesetzt" && e.grund ? html`<div class="leise klein">Nicht geklappt: ${e.grund}</div>` : ""}</li>`;
  })}</ul>`;

  let schritt, kopf, inhalt;
  if (d.laeuft) {
    schritt = "finden"; kopf = "Neo sieht gerade deine Gespräche durch";
    inhalt = html`<p>${st.schritt || "läuft"} …</p>${nichtsTun}`;
  } else if (s.stand === "pruefung") {
    schritt = "umsetzen"; kopf = "Dario prüft deine Auswahl";
    inhalt = html`<p>Er sucht Widersprüche und Doppel und legt die Reihenfolge fest. Danach setzt Neo von selbst um.</p>${nichtsTun}`;
  } else if (s.stand === "laeuft") {
    schritt = "umsetzen"; kopf = `Wird umgesetzt -- Punkt ${Math.min(Object.keys(erg).length + 1, reihe.length)} von ${reihe.length}`;
    inhalt = html`${fortschritt}${nichtsTun}
      <div class="knopfreihe"><button class="btn klein geist" disabled=${laeuft} onClick=${() => tun("/rsi/serie/abbrechen", "Nach dem aktuellen Punkt ist Schluss.")}>Nach diesem Punkt anhalten</button></div>`;
  } else if (s.stand === "bereit") {
    schritt = "umsetzen"; kopf = "Geprüft -- wartet auf deinen Start";
    inhalt = html`${s.zusammenfassung && html`<p>${s.zusammenfassung}</p>`}<ol class="klein">${reihe.map((i) => html`<li>${t(i)}</li>`)}</ol>
      <div class="knopfreihe"><button class="btn primaer" disabled=${laeuft} onClick=${() => tun("/rsi/serie/start", "Neo legt los.")}><${Icon} n="play" g=${14} />Jetzt umsetzen</button>
        <button class="btn klein geist" disabled=${laeuft} onClick=${() => tun("/rsi/serie/abbrechen")}>Doch nicht</button></div>`;
  } else if (s.stand === "fehler") {
    schritt = "umsetzen"; kopf = "Das Umsetzen hat nicht geklappt";
    inhalt = html`<div class="fehlerbox">${s.fehler}</div>
      <div class="knopfreihe" style="margin-top:8px"><button class="btn klein" onClick=${() => tun("/rsi/serie/abbrechen")}>Verstanden, ausblenden</button></div>`;
  } else if (s.stand === "fertig" && !s.gemeldet) {
    schritt = "fertig"; kopf = s.release_id ? "Fertig -- das neue Release ist da" : "Fertig -- umgesetzt wurde nichts";
    inhalt = html`${fortschritt}
      <p class="rsi-du">${s.release_id ? "Lad die Seite neu und probier es aus. Klappt etwas nicht, kannst du es unten unter „Was gelaufen ist“ zurücknehmen."
        : "Die Gründe stehen oben je Punkt. Die Punkte sind wieder offen und erscheinen unten."}</p>
      <div class="knopfreihe">${s.release_id && html`<button class="btn primaer" onClick=${() => location.reload()}><${Icon} n="neu_laden" g=${14} />Seite neu laden</button>`}
        <button class="btn klein geist" onClick=${() => tun("/rsi/serie/gemeldet")}>Gesehen, ausblenden</button></div>`;
  } else if (waehlbare.length) {
    schritt = "waehlen"; kopf = `${waehlbare.length} ${waehlbare.length === 1 ? "Vorschlag wartet" : "Vorschläge warten"} auf dich`;
    inhalt = html`<p class="rsi-du"><b>So geht's:</b> Kreuz unten an, was umgesetzt werden soll, und klick „Umsetzen“. Was du nicht willst: ankreuzen und „Verwerfen“.</p>
      <${Auswahlleiste} wahl=${wahl} titel=${titel} leeren=${() => setWahlAlle({})} fertig=${laden}
        alle=${waehlbare.length} alleWaehlen=${() => setWahlAlle(Object.fromEntries(waehlbare.map((v) => [v.id, "an"])))} />`;
  } else {
    schritt = "finden"; kopf = "Nichts zu tun";
    inhalt = html`<p class="rsi-du">Es liegt kein Vorschlag vor. Neo sieht jede Nacht um 3 Uhr deine Gespräche durch${d.an ? "" : " -- das ist gerade ausgeschaltet (Einstellungen unten)"}.</p>
      <div class="knopfreihe"><button class="btn klein" onClick=${() => tun("/rsi/lauf", "Neo sieht deine Gespräche durch.")}><${Icon} n="play" g=${13} />Jetzt durchsehen</button></div>`;
  }
  return html`<section class="karte rsi-jetzt">
    <${Schritte} aktiv=${schritt} />
    <h3>${kopf}</h3>
    ${inhalt}
  </section>`;
}

// ------------------------------------------------------------ Auswahl -> Umsetzen oder Verwerfen
function Auswahlleiste({ wahl, titel, leeren, fertig, alle, alleWaehlen }) {
  const ids = Object.keys(wahl);
  const [frage, setFrage] = useState(null);       // {art: "umsetzen"|"verwerfen", schaetzung} -- die Zusammenfassung vor dem Ja
  const [laeuft, setLaeuft] = useState(false);
  async function umsetzenFragen() {
    try { const r = await api("/rsi/serie/auswahl", { methode: "POST", daten: { umsetzen: ids } }); setFrage({ art: "umsetzen", schaetzung: r.schaetzung }); }
    catch (e) { fehlerMelden(e); }
  }
  async function ja() {
    setLaeuft(true);
    try {
      const daten = frage.art === "umsetzen" ? { umsetzen: ids, bestaetigt: true } : { verwerfen: ids, bestaetigt: true };
      const r = await api("/rsi/serie/auswahl", { methode: "POST", daten });
      toast(r.umsetzen ? "Gestartet -- Dario prüft, danach setzt Neo um." : `${r.verworfen} verworfen.`);
      leeren(); setFrage(null); fertig();
    } catch (e) { fehlerMelden(e); }
    setLaeuft(false);
  }
  if (frage) return html`<div class="rsi-frage">
    <p><b>${frage.art === "umsetzen" ? `Diese ${ids.length} umsetzen?` : `Diese ${ids.length} verwerfen?`}</b></p>
    <ol class="klein">${ids.map((i) => html`<li>${titel[i]}</li>`)}</ol>
    ${frage.art === "umsetzen" && html`<p class="klein">Dario prüft zuerst auf Widersprüche und Doppel und schreibt je Punkt einen Plan (zusammen etwa <b>${dollar(frage.schaetzung)}</b>).
      Dann setzt Neo einen Punkt nach dem anderen um, Dario prüft jede Änderung (je Punkt einige Cent). Was sich widerspricht, bleibt offen.
      Am Ende bekommst du Bescheid -- hier, in Talk und im Morgenbericht.</p>`}
    <div class="knopfreihe"><button class=${"btn " + (frage.art === "umsetzen" ? "primaer" : "gefahr")} disabled=${laeuft} onClick=${ja}>
        ${frage.art === "umsetzen" ? "Ja, umsetzen" : "Ja, verwerfen"}</button>
      <button class="btn klein geist" onClick=${() => setFrage(null)}>Zurück</button></div></div>`;
  return html`<div class="knopfreihe rsi-leiste-knoepfe">
    <span class="rsi-zahl">${ids.length ? `${ids.length} angekreuzt` : "Noch nichts angekreuzt"}</span>
    <button class="btn primaer" disabled=${!ids.length} onClick=${umsetzenFragen}><${Icon} n="play" g=${14} />Umsetzen</button>
    <button class="btn" disabled=${!ids.length} onClick=${() => setFrage({ art: "verwerfen" })}>Verwerfen</button>
    ${ids.length < alle && html`<button class="btn klein geist" onClick=${alleWaehlen}>Alle ankreuzen</button>`}
    ${ids.length > 0 && html`<button class="btn klein geist" onClick=${leeren}>Keine</button>`}
  </div>`;
}

// ------------------------------------------------------------ eine Vorschlags-Kachel
function Vorschlag({ v, nr, wahl, setWahl, waehlbar }) {
  const d = v.daten || {};
  const da = d.dario || {};
  const sr = d.serie || {};
  const u = URTEIL[da.urteil];
  const inArbeit = IN_ARBEIT.includes(v.stand);
  return html`<section class=${"karte rsi-karte" + (wahl ? " gewaehlt" : "")}>
    <div class="rsi-karte-kopf">
      ${waehlbar ? html`<input type="checkbox" class="rsi-haken" checked=${!!wahl} aria-label=${"Ankreuzen: " + v.titel}
        onChange=${(e) => setWahl(v.id, e.target.checked ? "an" : "")} />` : html`<span class="rsi-haken-platz"></span>`}
      <div class="rsi-karte-titel" onClick=${() => waehlbar && setWahl(v.id, wahl ? "" : "an")}>
        <b>${nr}. ${v.titel}</b>
        <div class="knopfreihe">
          ${inArbeit && html`<span class="pill lila">wird gerade umgesetzt</span>`}
          ${(d.vorkommen || 1) > 1 && html`<span class="pill gelb" title="Derselbe Fehler in mehreren Gesprächen -- als ein Vorschlag zusammengefasst">${d.vorkommen}× aufgetreten</span>`}
          ${u && html`<span class=${"pill " + u[0]}>${u[1]}</span>`}
        </div>
      </div>
    </div>
    <p>${d.problem}</p>
    ${da.begruendung && html`<p class="klein leise"><b>Dario:</b> ${da.begruendung}</p>`}
    ${sr.ergebnis && sr.ergebnis !== "umgesetzt" && html`<div class="fehlerbox klein">Letzter Versuch hat nicht geklappt: ${sr.grund || sr.ergebnis}</div>`}
    ${sr.zurueckgestellt && html`<div class="hinweisbox klein"><b>Zurückgestellt:</b> ${sr.zurueckgestellt}${sr.frage ? html` <b>Frage an dich:</b> ${sr.frage}` : ""}</div>`}
    <details class="rsi-details"><summary class="klein">Details</summary>
      ${(d.belege || []).length > 0 && html`<p class="klein"><b>Aus deinen Gesprächen:</b></p>${d.belege.map((b) => html`<div class="rsi-beleg klein">
        <div class="leise">${zeitText(b.zeit)} · ${b.art === "neo" ? "Neo" : "Talk"}</div>
        <div><b>Du:</b> ${b.veiko}</div><div><b>${b.art === "neo" ? "Neo" : "Talk"}:</b> ${b.antwort || "(keine Antwort)"}</div></div>`)}`}
      <p class="klein"><b>Neos Vorschlag:</b></p><${Md} text=${d.vorschlag || ""} />
      ${d.ursache && html`<p class="klein"><b>Ursache laut Neo:</b> ${d.ursache}</p>`}
      ${da.naechster_auftrag && html`<p class="klein"><b>Darios Hinweis zur Umsetzung:</b></p><${Md} text=${da.naechster_auftrag} />`}
      ${d.plan && d.plan.text && html`<p class="klein"><b>Darios Umsetzungsplan:</b></p><${Md} text=${d.plan.text} />`}
      ${sr.gespraech_id && html`<p class="klein"><a href=${"#/neo/" + sr.gespraech_id}>Neos Arbeit an diesem Punkt ansehen</a></p>`}
    </details>
  </section>`;
}

// ------------------------------------------------------------ Was gelaufen ist
function Verlauf({ d, alt, laden }) {
  const st = d.stand || {};
  const [frage, setFrage] = useState(null);      // {release_id, rsi_id, text}
  const [laeuft, setLaeuft] = useState(false);
  const [zeigeAlt, setZeigeAlt] = useState(false);
  async function zurueck() {
    setLaeuft(true);
    try {
      const r = await api("/rsi/release/zuruecknehmen", { methode: "POST", daten: { release_id: frage.release_id, rsi_id: frage.rsi_id } });
      toast("Zurückgenommen: " + r.punkte.join(", ") + (r.neustart ? " -- das Cockpit startet kurz neu." : ""));
      setFrage(null); laden();
      if (r.neustart) setTimeout(() => location.reload(), 9000);
    } catch (e) { fehlerMelden(e); }
    setLaeuft(false);
  }
  async function wiederOeffnen(id) { try { await api(`/rsi/${id}/zurueck`, { methode: "POST", daten: {} }); toast("Wieder offen."); laden(); } catch (e) { fehlerMelden(e); } }
  const releases = d.releases || [];
  return html`<section class="karte rsi-verlauf">
    <div class="karte-kopf"><h3>Was gelaufen ist</h3></div>
    <div class="rsi-verlauf-zeile"><span class="leise klein">Letztes Durchsehen</span>
      <span>${st.fehler ? html`<span style="color:var(--signal)">gescheitert: ${st.fehler}</span>`
        : st.ende ? html`${zeitText(st.ende)} -- ${st.ergebnis || ""}${st.kosten ? ` (Dario: ${dollar(st.kosten)})` : ""}` : "noch keins"}</span></div>
    ${releases.length === 0 && html`<div class="rsi-verlauf-zeile"><span class="leise klein">Releases</span><span>noch keins</span></div>`}
    ${releases.map((r) => html`<div class="rsi-release">
      <div class="knopfreihe"><b>Release ${zeitText(r.zeit)}</b>${r.zurueckgenommen ? html`<span class="pill">zurückgenommen</span>`
        : html`<button class="btn klein geist" onClick=${() => setFrage({ release_id: r.id, text: "das ganze Release vom " + zeitText(r.zeit) })}>Zurücknehmen</button>`}</div>
      <ul class="klein">${r.punkte.map((p) => html`<li>${p.titel} ${p.zurueckgenommen ? html`<span class="leise">(zurückgenommen)</span>`
        : p.commit && r.punkte.length > 1 ? html`<button class="btn klein geist" onClick=${() => setFrage({ release_id: r.id, rsi_id: p.id, text: "„" + p.titel + "“" })}>nur diesen zurücknehmen</button>` : ""}</li>`)}</ul></div>`)}
    ${frage && html`<div class="hinweisbox">${frage.text} zurücknehmen? Die Änderungen werden rückgängig gemacht, geprüft und eingespielt;
      betrifft es Server-Teile, startet das Cockpit kurz neu.
      <div class="knopfreihe" style="margin-top:8px"><button class="btn klein gefahr" disabled=${laeuft} onClick=${zurueck}>Ja, zurücknehmen</button>
        <button class="btn klein geist" onClick=${() => setFrage(null)}>Abbrechen</button></div></div>`}
    ${alt.length > 0 && html`<button class="btn klein geist" style="margin-top:10px" onClick=${() => setZeigeAlt(!zeigeAlt)}>
      ${zeigeAlt ? "Erledigte ausblenden" : `Erledigte, verworfene und zusammengelegte (${alt.length})`}</button>`}
    ${zeigeAlt && html`<ul class="rsi-alt">${alt.map((v) => {
      const a = ALT_STAND[v.stand] || ["", v.stand];
      return html`<li><span class=${"pill " + a[0]}>${a[1]}</span> ${v.titel} <span class="leise klein">${zeitText(v.geaendert || v.erstellt)}</span>
        ${["verworfen", "erledigt"].includes(v.stand) && html` <button class="btn klein geist" onClick=${() => wiederOeffnen(v.id)}>wieder öffnen</button>`}</li>`;
    })}</ul>`}
  </section>`;
}

function Einstellungen({ d, laden }) {
  async function setzen(x) { try { await api("/rsi/einstellungen", { methode: "POST", daten: x }); laden(); } catch (e) { fehlerMelden(e); } }
  async function jetzt() { try { await api("/rsi/lauf", { methode: "POST" }); toast("Neo sieht deine Gespräche durch."); setTimeout(laden, 800); } catch (e) { fehlerMelden(e); } }
  return html`<details class="karte rsi-einst"><summary><b>Einstellungen</b> <span class="leise klein">-- nachts durchsehen, Budget</span></summary>
    <div class="knopfreihe rsi-schalter">
      <label class="klein"><input type="checkbox" checked=${d.an} onChange=${(e) => setzen({ an: e.target.checked })} /> jede Nacht um 3 Uhr durchsehen</label>
      <label class="klein"><input type="checkbox" checked=${d.dario_auto} onChange=${(e) => setzen({ dario_auto: e.target.checked })} /> Dario prüft die Vorschläge nachts gleich</label>
      <label class="klein">Budget dafür je Nacht <input class="eingabe rsi-budget" type="number" min="0" max="20" step="0.5" value=${d.budget}
        onChange=${(e) => setzen({ budget: e.target.value })} /> $</label>
      <button class="btn klein" disabled=${d.laeuft} onClick=${jetzt}><${Icon} n="play" g=${13} />Jetzt durchsehen</button>
    </div>
    <p class="klein leise">Neo liest deine Gespräche mit Talk und Neo seit dem letzten Durchsehen${d.bis ? ` (zuletzt bis ${zeitText(d.bis)})` : ""}: wo du widersprochen hast,
      wo das Cockpit aufgegeben hat, wo du etwas wiederholen musstest. Derselbe Fehler in mehreren Gesprächen wird ein Vorschlag. Er ändert dabei nichts.</p>
  </details>`;
}

export function Rsi() {
  useEffect(() => { bus.sende("talk-kontext", { art: "rsi", id: "rsi", titel: "RSI" }); return () => bus.sende("talk-kontext", null); }, []);
  const [d, laden] = useAbruf("/rsi", 0, []);
  const [wahl, setWahlAlle] = useState({});
  const setWahl = (id, art) => setWahlAlle((w) => { const n = { ...w }; if (art) n[id] = art; else delete n[id]; return n; });
  const serie = d && d.serie;
  // Waehrend etwas arbeitet (Durchsehen, eine Serie), alle 5 s nachsehen -- sonst steht "laeuft" fuer immer da.
  const arbeitet = d && (d.laeuft || (serie && ["pruefung", "laeuft"].includes(serie.stand)));
  useEffect(() => { if (!arbeitet) return; const t = setInterval(laden, 5000); return () => clearInterval(t); }, [arbeitet]);
  if (!d) return html`<div class="lade">Lade …</div>`;
  const offen = d.vorschlaege.filter((v) => WAEHLBAR.includes(v.stand) || IN_ARBEIT.includes(v.stand));
  const alt = d.vorschlaege.filter((v) => !WAEHLBAR.includes(v.stand) && !IN_ARBEIT.includes(v.stand));
  const titel = Object.fromEntries(d.vorschlaege.map((v) => [v.id, v.titel]));
  // Ankreuzen geht nur, solange nichts umgesetzt wird (rsi_serie.auswahl lehnt sonst ab).
  const waehlbarJetzt = !(serie && ["pruefung", "laeuft", "bereit"].includes(serie.stand)) && !d.laeuft;
  const waehlbare = waehlbarJetzt ? offen.filter((v) => WAEHLBAR.includes(v.stand)) : [];
  return html`<div class="seite rsi">
    <div class="rsi-titel"><h2>RSI -- das Cockpit verbessert sich selbst</h2>
      <p class="leise">Neo findet in deinen Gesprächen, wo es gehakt hat. Du wählst aus, was besser werden soll. Neo setzt es um, Dario prüft jede Änderung.</p></div>
    <${JetztKasten} d=${d} waehlbare=${waehlbare} wahl=${wahl} setWahlAlle=${setWahlAlle} titel=${titel} laden=${laden} />
    ${offen.length > 0 && html`<h3 class="rsi-abschnitt">Vorschläge</h3>`}
    ${offen.map((v, i) => html`<${Vorschlag} key=${v.id} v=${v} nr=${i + 1} wahl=${wahl[v.id] || ""} setWahl=${setWahl}
      waehlbar=${waehlbarJetzt && WAEHLBAR.includes(v.stand)} />`)}
    <${Verlauf} d=${d} alt=${alt} laden=${laden} />
    <${Einstellungen} d=${d} laden=${laden} />
  </div>`;
}
