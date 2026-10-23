// RSI (23.10.2026) -- das Cockpit verbessert sich aus Veikos Gespraechen (cockpit/rsi.py).
// Veiko: "Das Cockpit soll sich nachts anschauen, was nicht gut funktioniert hat ... Neo soll
// Vorschlaege machen ... nichts umsetzen oder einspielen ... durch Dario geprueft ... und dann
// brauche ich einen Vorschlag, was Dario ausarbeiten soll oder ob Neo das ausarbeiten soll."
//
// Je Vorschlag eine Karte: was Veiko erlebt hat (mit den Belegen aus den Gespraechen), was Neo
// vorschlaegt, was Dario dazu sagt und WER es ausarbeiten soll -- und genau die Knoepfe, die
// dazu passen. Was Geld kostet (Dario), fragt vorher an Ort und Stelle mit dem geschaetzten Betrag.
import { html, useState, useEffect, Icon, Md, Leer, bus, toast, fehlerMelden, zeitText, useAbruf, navigiere } from "./ui.js";
import { api } from "./api.js";

const STAND = {
  neu: ["gelb", "wartet auf Dario"], geprueft: ["blau", "von Dario geprüft"], plan: ["lila", "Darios Plan liegt vor"],
  bei_neo: ["lila", "Neo arbeitet daran"], erledigt: ["gruen", "erledigt"], verworfen: ["", "verworfen"],
  in_serie: ["lila", "wird umgesetzt"], umgesetzt: ["gruen", "umgesetzt"], zurueckgenommen: ["", "zurückgenommen"],
};
const ERGEBNIS = { umgesetzt: "umgesetzt", gescheitert: "nicht umgesetzt", abgebrochen: "abgebrochen" };
const URTEIL = { sinnvoll: ["gruen", "sinnvoll"], ueberarbeiten: ["gelb", "überarbeiten"], verwerfen: ["rot", "verwerfen"], nicht_geprueft: ["", "nicht geprüft"] };
const WER = { neo: "Neo soll es ausarbeiten", dario: "Dario soll erst einen Umsetzungsplan schreiben", keiner: "Dario rät: nicht umsetzen" };
const AUFWAND = { klein: "kleiner Aufwand", mittel: "mittlerer Aufwand", gross: "großer Aufwand" };
const dollar = (x) => "$ " + Number(x || 0).toFixed(2).replace(".", ",");

function Kostenfrage({ was, rid, fertig, zu }) {
  const [s, setS] = useState(null);
  useEffect(() => { api(`/rsi/${rid}/${was}`, { methode: "POST", daten: {} }).then((d) => setS(d.schaetzung)).catch((e) => { fehlerMelden(e); zu(); }); }, [rid, was]);
  async function ja() {
    try { await api(`/rsi/${rid}/${was}`, { methode: "POST", daten: { bestaetigt: true } }); toast(was === "plan" ? "Dario schreibt den Plan." : "Dario prüft."); fertig(); }
    catch (e) { fehlerMelden(e); }
    zu();
  }
  return html`<div class="rsi-kosten hinweisbox">
    ${s == null ? "Schätze die Kosten …" : html`Dario ${was === "plan" ? "schreibt einen Umsetzungsplan" : "prüft den Vorschlag"} -- das kostet etwa <b>${dollar(s)}</b>.`}
    <span class="knopfreihe"><button class="btn klein primaer" disabled=${s == null} onClick=${ja}>Ja, ausgeben</button>
      <button class="btn klein geist" onClick=${zu}>Abbrechen</button></span></div>`;
}

function Vorschlag({ v, neu, nr, wahl, setWahl, waehlbar }) {
  const d = v.daten || {};
  const da = d.dario || {};
  const [frage, setFrage] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const st = STAND[v.stand] || ["", v.stand];
  async function tun(was) {
    setLaeuft(true);
    try {
      const r = await api(`/rsi/${v.id}/${was}`, { methode: "POST", daten: {} });
      if (was === "neo" && r.gespraech_id) { toast("Neo arbeitet daran -- seine Änderung prüft Dario vor dem Einspielen."); navigiere("/neo/" + r.gespraech_id); }
      else toast({ verwerfen: "Verworfen.", erledigt: "Als erledigt markiert.", zurueck: "Wieder offen." }[was] || "Erledigt.");
      neu();
    } catch (e) { fehlerMelden(e); }
    setLaeuft(false);
  }
  const offen = ["neu", "geprueft", "plan"].includes(v.stand);
  const empf = da.wer_weiter;
  const sr = d.serie || {};
  // Auswahl fuer die Serie (rsi_serie.py): EINE Ankreuzbox je Kachel (Veiko, 23.10.2026) -- was
  // mit den Angekreuzten passiert (verwerfen oder pruefen und umsetzen), entscheidet die Leiste.
  return html`<section class=${"karte rsi-karte" + (offen ? "" : " ruhig") + (wahl ? " gewaehlt-umsetzen" : "")}>
    ${offen && waehlbar && html`<label class="rsi-wahlreihe"><input type="checkbox" class="rsi-haken" checked=${!!wahl}
      onChange=${(e) => setWahl(v.id, e.target.checked ? "an" : "")} /><span class="klein">${nr ? `Punkt ${nr}` : ""} ${wahl ? "-- ausgewählt" : "-- auswählen"}</span></label>`}
    ${sr.ergebnis && html`<div class=${sr.ergebnis === "umgesetzt" ? "hinweisbox" : "fehlerbox"} style="margin-bottom:8px">
      <b>Letzter Umsetzungsversuch: ${ERGEBNIS[sr.ergebnis] || sr.ergebnis}</b>${sr.grund ? " -- " + sr.grund : ""}
      ${sr.gespraech_id && html` <a href=${"#/neo/" + sr.gespraech_id}>Neos Gespräch ansehen</a>`}</div>`}
    ${sr.zurueckgestellt && offen && html`<div class="hinweisbox" style="margin-bottom:8px"><b>Zurückgestellt:</b> ${sr.zurueckgestellt}${sr.frage ? html`<br /><b>Frage an dich:</b> ${sr.frage}` : ""}</div>`}
    <div class="karte-kopf"><h3>${v.titel}</h3>
      <span class="knopfreihe"><span class=${"pill " + st[0]}>${v.arbeitet ? "Dario arbeitet …" : st[1]}</span>
        <span class="pill">${AUFWAND[d.aufwand] || d.aufwand}</span></span></div>
    <p>${d.problem}</p>
    ${(d.belege || []).length > 0 && html`<details class="rsi-belege"><summary class="klein">Aus deinen Gesprächen (${d.belege.length})</summary>
      ${d.belege.map((b) => html`<div class="rsi-beleg klein">
        <div class="leise">${zeitText(b.zeit)} · ${b.art === "neo" ? "Neo" : "Talk"} · ${(b.signale || []).join(", ")}</div>
        <div><b>Du:</b> ${b.veiko}</div><div><b>${b.art === "neo" ? "Neo" : "Talk"}:</b> ${b.antwort || "(keine Antwort)"}</div></div>`)}</details>`}
    <div class="rsi-zwei">
      <div><div class="leise klein">Neos Vorschlag</div><${Md} text=${d.vorschlag || ""} />
        ${d.ursache && html`<p class="klein"><b>Ursache:</b> ${d.ursache}</p>`}
        ${(d.dateien || []).length > 0 && html`<p class="klein leise">Dateien: ${d.dateien.join(", ")}</p>`}
        ${d.risiko && html`<p class="klein leise">Risiko laut Neo: ${d.risiko}</p>`}</div>
      <div><div class="leise klein">Darios Prüfung</div>
        ${da.urteil ? html`<p><span class=${"pill " + (URTEIL[da.urteil] || [""])[0]}>${(URTEIL[da.urteil] || ["", da.urteil])[1]}</span> ${da.begruendung}</p>
          ${(da.risiken || []).length > 0 && html`<ul class="klein">${da.risiken.map((r) => html`<li>${r}</li>`)}</ul>`}
          ${empf && html`<p class="rsi-empf"><${Icon} n="rechts" g=${13} /> <b>${WER[empf]}</b>${da.warum_wer ? " -- " + da.warum_wer : ""}</p>`}
          ${da.naechster_auftrag && html`<details><summary class="klein">Darios Auftrag für den nächsten Schritt</summary><${Md} text=${da.naechster_auftrag} /></details>`}
          ${da.kosten ? html`<p class="klein leise">Kosten der Prüfung: ${dollar(da.kosten)}</p>` : ""}`
        : html`<p class="leise klein">Noch nicht geprüft.</p>`}
        ${d.plan && d.plan.text && html`<details open=${v.stand === "plan"}><summary class="klein"><b>Darios Umsetzungsplan</b> (${dollar(d.plan.kosten)})</summary><${Md} text=${d.plan.text} /></details>`}
      </div>
    </div>
    ${v.fehler && html`<div class="fehlerbox">${v.fehler}</div>`}
    ${frage && html`<${Kostenfrage} was=${frage} rid=${v.id} fertig=${neu} zu=${() => setFrage("")} />`}
    <div class="knopfreihe karte-fuss">
      ${offen && !v.arbeitet && html`
        <button class=${"btn klein" + (empf === "neo" || v.stand === "plan" ? " primaer" : "")} disabled=${laeuft} onClick=${() => tun("neo")}
          title="Ein normaler Neo-Auftrag. Was er am Cockpit ändern will, prüft Dario vor dem Einspielen.">
          <${Icon} n="neo" g=${13} />${v.stand === "plan" ? "Neo nach Darios Plan umsetzen lassen" : "Neo ausarbeiten lassen"}</button>
        ${v.stand !== "plan" && html`<button class=${"btn klein" + (empf === "dario" ? " primaer" : "")} disabled=${laeuft} onClick=${() => setFrage("plan")}>
          <${Icon} n="stift" g=${13} />Dario einen Plan schreiben lassen</button>`}
        ${!da.urteil || da.urteil === "nicht_geprueft" ? html`<button class="btn klein" disabled=${laeuft} onClick=${() => setFrage("pruefen")}><${Icon} n="check" g=${13} />Von Dario prüfen lassen</button>` : ""}
        <button class=${"btn klein geist" + (empf === "keiner" ? " primaer" : "")} disabled=${laeuft} onClick=${() => tun("verwerfen")}>Verwerfen</button>`}
      ${v.stand === "bei_neo" && d.neo && html`
        <a class="btn klein primaer" href=${"#/neo/" + d.neo.gespraech_id}><${Icon} n="neo" g=${13} />${v.neo_laeuft ? "Neo arbeitet -- ansehen" : "Neos Ergebnis ansehen"}</a>
        <button class="btn klein" disabled=${laeuft} onClick=${() => tun("erledigt")}>Erledigt</button>`}
      ${(v.stand === "verworfen" || v.stand === "erledigt") && html`<button class="btn klein geist" disabled=${laeuft} onClick=${() => tun("zurueck")}>Wieder öffnen</button>`}
      <span class="leise klein" style="margin-left:auto">${zeitText(v.erstellt)}</span>
    </div>
  </section>`;
}

// ------------------------------------------------------------ Serie (rsi_serie.py, 23.10.2026)
// Veiko: "bei mehreren Punkten per Klickbox auswaehlen, welche bearbeitet und welche verworfen werden,
// dann eine Art Start Bearbeitung ... vorher auf Widersprueche pruefen ... dann soll mir gesagt werden:
// abgeschlossen, das neue Release ist da ... und zuruecknehmen koennen."
function Auswahlleiste({ wahl, titel, leeren, fertig, alle, alleWaehlen }) {
  const ids = Object.keys(wahl);
  const [frage, setFrage] = useState(null);       // {art: "umsetzen"|"verwerfen", schaetzung} -- die Zusammenfassung vor dem Ja
  const [laeuft, setLaeuft] = useState(false);
  if (!ids.length) return "";
  async function umsetzenFragen() {
    try { const r = await api("/rsi/serie/auswahl", { methode: "POST", daten: { umsetzen: ids } }); setFrage({ art: "umsetzen", schaetzung: r.schaetzung }); }
    catch (e) { fehlerMelden(e); }
  }
  async function ja() {
    setLaeuft(true);
    try {
      const daten = frage.art === "umsetzen" ? { umsetzen: ids, bestaetigt: true } : { verwerfen: ids, bestaetigt: true };
      const r = await api("/rsi/serie/auswahl", { methode: "POST", daten });
      toast(r.umsetzen ? "Dario prüft auf Widersprüche, danach setzt Neo um." : `${r.verworfen} verworfen.`);
      leeren(); setFrage(null); fertig();
    } catch (e) { fehlerMelden(e); }
    setLaeuft(false);
  }
  return html`<section class="karte rsi-leiste">
    ${!frage ? html`<div class="knopfreihe">
        <b>${ids.length} ausgewählt</b>
        <button class="btn klein primaer" onClick=${umsetzenFragen}><${Icon} n="play" g=${13} />Prüfen und umsetzen</button>
        <button class="btn klein" onClick=${() => setFrage({ art: "verwerfen" })}>Verwerfen</button>
        ${ids.length < alle && html`<button class="btn klein geist" onClick=${alleWaehlen}>Alle auswählen</button>`}
        <button class="btn klein geist" onClick=${leeren}>Auswahl aufheben</button></div>`
      : html`<div>
        <p><b>${frage.art === "umsetzen" ? `Umgesetzt werden (${ids.length}):` : `Verworfen werden (${ids.length}):`}</b></p>
        <ol class="klein">${ids.map((i) => html`<li>${titel[i]}</li>`)}</ol>
        ${frage.art === "umsetzen" && html`<p class="klein">Zuerst prüft Dario die Punkte zusammen auf Widersprüche und Überschneidungen -- auch gegen das, was zuletzt
          umgesetzt wurde -- und legt die Reihenfolge fest (etwa <b>${dollar(frage.schaetzung)}</b>). <b>Danach setzt Neo von selbst um, was nicht widersprüchlich ist</b>,
          einen Punkt nach dem anderen; Dario prüft jede Änderung vor dem Einspielen (je Punkt einige Cent). Was sich widerspricht, bleibt offen, mit Darios Frage an dich.
          Am Ende bekommst du Bescheid, dass das neue Release da ist.</p>`}
        <div class="knopfreihe"><button class=${"btn klein " + (frage.art === "umsetzen" ? "primaer" : "gefahr")} disabled=${laeuft} onClick=${ja}>
            ${frage.art === "umsetzen" ? "Ja, prüfen und umsetzen" : "Ja, verwerfen"}</button>
          <button class="btn klein geist" onClick=${() => setFrage(null)}>Zurück</button></div></div>`}
  </section>`;
}

function SerieKasten({ serie, titel, neu }) {
  const [laeuft, setLaeuft] = useState(false);
  const [startFrage, setStartFrage] = useState(false);
  const s = serie || {};
  if (!s.stand) return "";
  async function tun(was, text) {
    setLaeuft(true);
    try { await api("/rsi/serie/" + was, { methode: "POST" }); if (text) toast(text); neu(); } catch (e) { fehlerMelden(e); }
    setLaeuft(false); setStartFrage(false);
  }
  const t = (i) => titel[i] || i;
  const erg = s.ergebnisse || {};
  if (s.stand === "pruefung") return html`<section class="karte rsi-serie"><div class="lade">Dario prüft die Auswahl auf Widersprüche (${(s.auswahl || []).length} Punkte) -- danach setzt Neo von selbst um, was nicht widersprüchlich ist …</div></section>`;
  if (s.stand === "fehler") return html`<section class="karte rsi-serie"><div class="fehlerbox">${s.fehler}</div>
    <div class="knopfreihe karte-fuss"><button class="btn klein" onClick=${() => tun("abbrechen")}>Schließen</button></div></section>`;
  if (s.stand === "bereit") return html`<section class="karte rsi-serie">
    <div class="karte-kopf"><h3>Geprüft -- bereit zum Umsetzen</h3>${s.pruef_kosten ? html`<span class="leise klein">Prüfung: ${dollar(s.pruef_kosten)}</span>` : ""}</div>
    ${s.zusammenfassung && html`<p>${s.zusammenfassung}</p>`}
    <p class="klein"><b>Reihenfolge:</b></p>
    <ol class="klein">${(s.reihenfolge || []).map((i) => html`<li>${t(i)}${s.hinweise && s.hinweise[i] ? html`<div class="leise">${s.hinweise[i]}</div>` : ""}</li>`)}</ol>
    ${(s.konflikte || []).length > 0 && html`<p class="klein"><b>Was Dario gefunden hat:</b></p><ul class="klein">${s.konflikte.map((k) => html`<li>
      <b>${{ widerspruch: "Widerspruch", ueberschneidung: "Überschneidung", abhaengigkeit: "Abhängigkeit" }[k.art] || k.art}:</b> ${k.beschreibung} ${k.loesung ? "-- " + k.loesung : ""}</li>`)}</ul>`}
    ${(s.zurueckgestellt || []).length > 0 && html`<div class="hinweisbox klein"><b>Zurückgestellt (wird nicht umgesetzt):</b>
      <ul>${s.zurueckgestellt.map((z) => html`<li>${t(z.id)} -- ${z.grund}${z.frage_an_veiko ? html`<br /><i>Frage an dich: ${z.frage_an_veiko}</i>` : ""}</li>`)}</ul></div>`}
    ${startFrage ? html`<div class="hinweisbox">Neo setzt jetzt ${(s.reihenfolge || []).length} Punkte nacheinander um. Jede Änderung prüft Dario vor dem Einspielen
        (je Punkt einige Cent). Am Ende startet das Cockpit einmal neu, und du bekommst Bescheid. Starten?
        <div class="knopfreihe" style="margin-top:8px"><button class="btn klein primaer" disabled=${laeuft} onClick=${() => tun("start", "Neo legt los.")}>Ja, starten</button>
          <button class="btn klein geist" onClick=${() => setStartFrage(false)}>Noch nicht</button></div></div>`
      : html`<div class="knopfreihe karte-fuss">
        <button class="btn primaer" disabled=${laeuft || !(s.reihenfolge || []).length} onClick=${() => setStartFrage(true)}><${Icon} n="play" g=${14} />Bearbeitung starten</button>
        <button class="btn klein geist" disabled=${laeuft} onClick=${() => tun("abbrechen", "Auswahl verworfen -- die Punkte sind wieder offen.")}>Auswahl verwerfen</button></div>`}
  </section>`;
  const reihe = s.reihenfolge || [];
  const zeile = (i) => {
    const e = erg[i];
    const zeichen = e ? (e.stand === "umgesetzt" ? "✓" : "✗") : s.aktuell === i ? "▶" : "·";
    return html`<li class=${e ? (e.stand === "umgesetzt" ? "ok" : "nein") : s.aktuell === i ? "jetzt" : ""}><span class="rsi-zeichen">${zeichen}</span> ${t(i)}
      ${e && e.stand !== "umgesetzt" && e.grund ? html`<div class="leise klein">${e.grund}</div>` : ""}
      ${s.aktuell === i && s.aktuell_gespraech ? html` <a class="klein" href=${"#/neo/" + s.aktuell_gespraech}>Neo zusehen</a>` : ""}
      ${e && e.gespraech_id ? html` <a class="klein leise" href=${"#/neo/" + e.gespraech_id}>Gespräch</a>` : ""}</li>`;
  };
  if (s.stand === "laeuft") return html`<section class="karte rsi-serie">
    <div class="karte-kopf"><h3>Wird umgesetzt -- Punkt ${Math.min(Object.keys(erg).length + 1, reihe.length)} von ${reihe.length}</h3></div>
    <ul class="rsi-fortschritt">${reihe.map(zeile)}</ul>
    <p class="leise klein">Neo arbeitet die Punkte nacheinander ab; Dario prüft jede Änderung vor dem Einspielen. Du kannst die Seite verlassen -- Talk sagt dir Bescheid, wenn das Release da ist.</p>
    <div class="knopfreihe karte-fuss"><button class="btn klein geist" disabled=${laeuft} onClick=${() => tun("abbrechen", "Nach dem aktuellen Punkt ist Schluss.")}>Nach diesem Punkt anhalten</button></div>
  </section>`;
  if (s.stand === "fertig") return html`<section class=${"karte rsi-serie" + (s.release_id ? " fertig" : "")}>
    <div class="karte-kopf"><h3>${s.release_id ? "Das neue Release ist da" : "Serie beendet"}</h3><span class="leise klein">${zeitText(s.ende)}</span></div>
    <p>${s.meldung}</p>
    <ul class="rsi-fortschritt">${reihe.map(zeile)}</ul>
    <div class="knopfreihe karte-fuss">
      ${s.release_id && html`<button class="btn klein primaer" onClick=${() => location.reload()}><${Icon} n="neu_laden" g=${13} />Seite neu laden</button>`}
      ${!s.gemeldet && html`<button class="btn klein geist" onClick=${() => tun("gemeldet")}>Gesehen</button>`}</div>
  </section>`;
  return "";
}

function Releases({ releases, neu }) {
  const [frage, setFrage] = useState(null);      // {release_id, rsi_id, text}
  const [laeuft, setLaeuft] = useState(false);
  if (!releases || !releases.length) return "";
  async function zurueck() {
    setLaeuft(true);
    try {
      const r = await api("/rsi/release/zuruecknehmen", { methode: "POST", daten: { release_id: frage.release_id, rsi_id: frage.rsi_id } });
      toast("Zurückgenommen: " + r.punkte.join(", ") + (r.neustart ? " -- das Cockpit startet kurz neu." : ""));
      setFrage(null); neu();
      if (r.neustart) setTimeout(() => location.reload(), 9000);
    } catch (e) { fehlerMelden(e); }
    setLaeuft(false);
  }
  return html`<section class="karte rsi-releases" style="margin-top:14px">
    <div class="karte-kopf"><h3>Releases aus RSI</h3></div>
    ${releases.map((r) => html`<div class="rsi-release">
      <div class="knopfreihe"><b>${zeitText(r.zeit)}</b>${r.zurueckgenommen ? html`<span class="pill">zurückgenommen</span>`
        : html`<button class="btn klein geist" onClick=${() => setFrage({ release_id: r.id, text: "das ganze Release vom " + zeitText(r.zeit) })}>Ganz zurücknehmen</button>`}</div>
      <ul class="klein">${r.punkte.map((p) => html`<li>${p.titel} ${p.zurueckgenommen ? html`<span class="leise">(zurückgenommen)</span>`
        : p.commit ? html`<button class="btn klein geist" onClick=${() => setFrage({ release_id: r.id, rsi_id: p.id, text: "„" + p.titel + "“" })}>zurücknehmen</button>`
        : html`<span class="leise">(nichts im Code -- nicht zurücknehmbar)</span>`}</li>`)}</ul></div>`)}
    ${frage && html`<div class="hinweisbox">${frage.text} zurücknehmen? Die Änderungen am Code werden rückgängig gemacht, geprüft und eingespielt;
      ändert es Server-Teile, startet das Cockpit kurz neu.
      <div class="knopfreihe" style="margin-top:8px"><button class="btn klein gefahr" disabled=${laeuft} onClick=${zurueck}>Ja, zurücknehmen</button>
        <button class="btn klein geist" onClick=${() => setFrage(null)}>Abbrechen</button></div></div>`}
  </section>`;
}

export function Rsi() {
  useEffect(() => { bus.sende("talk-kontext", { art: "rsi", id: "rsi", titel: "RSI" }); return () => bus.sende("talk-kontext", null); }, []);
  const [d, laden] = useAbruf("/rsi", 0, []);
  const [zeigeAlle, setZeigeAlle] = useState(false);
  const [wahl, setWahlAlle] = useState({});
  const setWahl = (id, art) => setWahlAlle((w) => { const n = { ...w }; if (art) n[id] = art; else delete n[id]; return n; });
  const serie = d && d.serie;
  // Waehrend etwas arbeitet (Nachtlauf, Dario, eine Serie), alle 5 s nachsehen -- sonst steht "laeuft" fuer immer da.
  const arbeitet = d && (d.laeuft || d.vorschlaege.some((v) => v.arbeitet) || (serie && ["pruefung", "laeuft"].includes(serie.stand)));
  useEffect(() => { if (!arbeitet) return; const t = setInterval(laden, 5000); return () => clearInterval(t); }, [arbeitet]);
  if (!d) return html`<div class="lade">Lade …</div>`;
  async function setzen(x) { try { await api("/rsi/einstellungen", { methode: "POST", daten: x }); laden(); } catch (e) { fehlerMelden(e); } }
  async function jetzt() { try { await api("/rsi/lauf", { methode: "POST" }); toast("RSI läuft -- Neo sieht deine Gespräche durch."); setTimeout(laden, 800); } catch (e) { fehlerMelden(e); } }
  const s = d.stand || {};
  const OFFEN = ["neu", "geprueft", "plan", "bei_neo", "in_serie"];
  const offen = d.vorschlaege.filter((v) => OFFEN.includes(v.stand));
  const alt = d.vorschlaege.filter((v) => !OFFEN.includes(v.stand));
  const titel = Object.fromEntries(d.vorschlaege.map((v) => [v.id, v.titel]));
  // Waehlen geht nur, solange keine Serie geprueft wird oder laeuft (rsi_serie.auswahl lehnt sonst ab).
  const waehlbar = !(serie && ["pruefung", "laeuft", "bereit"].includes(serie.stand));
  const waehlbare = offen.filter((v) => ["neu", "geprueft", "plan"].includes(v.stand));
  const alleWaehlen = () => setWahlAlle(Object.fromEntries(waehlbare.map((v) => [v.id, "an"])));
  return html`<div class="seite rsi">
    <section class="karte rsi-kopf">
      <div class="karte-kopf"><h3>Das Cockpit verbessert sich selbst</h3>
        <span class="knopfreihe"><button class="btn klein primaer" disabled=${d.laeuft} onClick=${jetzt}><${Icon} n="play" g=${13} />${d.laeuft ? "Läuft …" : "Jetzt durchsehen"}</button></span></div>
      <p class="klein">Jede Nacht zwischen 3 und 5 Uhr liest Neo deine Gespräche mit Talk und Neo seit dem letzten Lauf: wo du widersprochen hast, wo das Cockpit
        aufgegeben hat, wo du etwas wiederholen musstest. Er sieht im Code nach, woran es lag, und schlägt Verbesserungen vor. Dario prüft jeden Vorschlag.${" "}
        <b>Du kreuzt an, was umgesetzt oder verworfen wird</b> -- hier oder in Talk („setz Punkt 1 und 3 um, verwirf 2“). Dario prüft die Auswahl auf Widersprüche,
        danach setzt Neo von selbst um, was nicht widersprüchlich ist, und du bekommst ein neues Release, das sich zurücknehmen lässt.</p>
      <p class="klein ${s.fehler ? "" : "leise"}">${d.laeuft ? html`<b>Gerade:</b> ${s.schritt || "läuft"}`
        : s.fehler ? html`<span style="color:var(--signal)">Letzter Lauf gescheitert: ${s.fehler}</span>`
        : s.ende ? html`Letzter Lauf ${zeitText(s.ende)}: ${s.ergebnis || ""}${s.kosten ? ` Darios Prüfungen: ${dollar(s.kosten)}.` : ""}` : "Noch kein Lauf."}
        ${d.bis ? html` Durchgesehen bis: ${zeitText(d.bis)}` : ""}</p>
      <div class="knopfreihe rsi-schalter">
        <label class="klein"><input type="checkbox" checked=${d.an} onChange=${(e) => setzen({ an: e.target.checked })} /> jede Nacht</label>
        <label class="klein"><input type="checkbox" checked=${d.dario_auto} onChange=${(e) => setzen({ dario_auto: e.target.checked })} /> Dario prüft nachts gleich mit</label>
        <label class="klein">Budget je Nacht <input class="eingabe rsi-budget" type="number" min="0" max="20" step="0.5" value=${d.budget}
          onChange=${(e) => setzen({ budget: e.target.value })} /> $</label>
      </div>
    </section>
    <${SerieKasten} serie=${serie} titel=${titel} neu=${laden} />
    ${waehlbar && waehlbare.length > 0 && !Object.keys(wahl).length && html`<div class="knopfreihe" style="margin:10px 0">
      <span class="leise klein">Kreuz die Punkte an, die du umsetzen oder verwerfen willst -- dann erscheint die Leiste dafür.</span>
      ${waehlbare.length > 1 && html`<button class="btn klein" onClick=${alleWaehlen}>Alle auswählen</button>`}</div>`}
    ${waehlbar && html`<${Auswahlleiste} wahl=${wahl} titel=${titel} leeren=${() => setWahlAlle({})} fertig=${laden}
      alle=${waehlbare.length} alleWaehlen=${alleWaehlen} />`}
    ${!offen.length && html`<${Leer} titel=${d.laeuft ? "Neo sieht gerade nach …" : "Keine offenen Vorschläge."} />`}
    ${offen.map((v, i) => html`<${Vorschlag} key=${v.id} v=${v} neu=${laden} nr=${i + 1} wahl=${wahl[v.id] || ""} setWahl=${setWahl} waehlbar=${waehlbar} />`)}
    <${Releases} releases=${d.releases} neu=${laden} />
    ${alt.length > 0 && html`<button class="btn klein geist" style="margin-top:12px" onClick=${() => setZeigeAlle(!zeigeAlle)}>
      ${zeigeAlle ? "Erledigte und verworfene ausblenden" : `Erledigte und verworfene zeigen (${alt.length})`}</button>`}
    ${zeigeAlle && alt.map((v) => html`<${Vorschlag} key=${v.id} v=${v} neu=${laden} />`)}
  </div>`;
}
