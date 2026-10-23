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
};
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

function Vorschlag({ v, neu }) {
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
  return html`<section class=${"karte rsi-karte" + (offen ? "" : " ruhig")}>
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

export function Rsi() {
  useEffect(() => { bus.sende("talk-kontext", { art: "rsi", id: "rsi", titel: "RSI" }); return () => bus.sende("talk-kontext", null); }, []);
  const [d, laden] = useAbruf("/rsi", 0, []);
  const [zeigeAlle, setZeigeAlle] = useState(false);
  // Waehrend etwas arbeitet (Nachtlauf von Hand, Dario), alle 5 s nachsehen -- sonst steht "laeuft" fuer immer da.
  const arbeitet = d && (d.laeuft || d.vorschlaege.some((v) => v.arbeitet));
  useEffect(() => { if (!arbeitet) return; const t = setInterval(laden, 5000); return () => clearInterval(t); }, [arbeitet]);
  if (!d) return html`<div class="lade">Lade …</div>`;
  async function setzen(x) { try { await api("/rsi/einstellungen", { methode: "POST", daten: x }); laden(); } catch (e) { fehlerMelden(e); } }
  async function jetzt() { try { await api("/rsi/lauf", { methode: "POST" }); toast("RSI läuft -- Neo sieht deine Gespräche durch."); setTimeout(laden, 800); } catch (e) { fehlerMelden(e); } }
  const s = d.stand || {};
  const offen = d.vorschlaege.filter((v) => ["neu", "geprueft", "plan", "bei_neo"].includes(v.stand));
  const alt = d.vorschlaege.filter((v) => !["neu", "geprueft", "plan", "bei_neo"].includes(v.stand));
  return html`<div class="seite rsi">
    <section class="karte rsi-kopf">
      <div class="karte-kopf"><h3>Das Cockpit verbessert sich selbst</h3>
        <span class="knopfreihe"><button class="btn klein primaer" disabled=${d.laeuft} onClick=${jetzt}><${Icon} n="play" g=${13} />${d.laeuft ? "Läuft …" : "Jetzt durchsehen"}</button></span></div>
      <p class="klein">Jede Nacht zwischen 5 und 7 Uhr liest Neo deine Gespräche mit Talk und Neo seit dem letzten Lauf: wo du widersprochen hast, wo das Cockpit
        aufgegeben hat, wo du etwas wiederholen musstest. Er sieht im Code nach, woran es lag, und schlägt Verbesserungen vor. <b>Er ändert dabei nichts.</b>${" "}
        Dario prüft jeden Vorschlag und sagt, wer ihn ausarbeiten soll. Du entscheidest hier.</p>
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
    ${!offen.length && html`<${Leer} titel=${d.laeuft ? "Neo sieht gerade nach …" : "Keine offenen Vorschläge."} />`}
    ${offen.map((v) => html`<${Vorschlag} key=${v.id} v=${v} neu=${laden} />`)}
    ${alt.length > 0 && html`<button class="btn klein geist" style="margin-top:12px" onClick=${() => setZeigeAlle(!zeigeAlle)}>
      ${zeigeAlle ? "Erledigte und verworfene ausblenden" : `Erledigte und verworfene zeigen (${alt.length})`}</button>`}
    ${zeigeAlle && alt.map((v) => html`<${Vorschlag} key=${v.id} v=${v} neu=${laden} />`)}
  </div>`;
}
