// STAB & MODELLE (17.10.2026; vorher "Modelle" und "Verbrauch" als zwei Seiten).
//
// Vier Reiter, in dieser Reihenfolge, weil das die Fragen sind, die man hier hat:
//   Besetzung     Wer rechnet womit? Je Rolle und fuer Talk das Modell, das WIRKLICH
//                 rechnet (nicht nur das eingetragene), umstellbar; dazu alles Installierte.
//   Optimierung   Was sollte ich aendern? Vorschlaege der Modell-Revision (revision.py),
//                 jeder mit einer Messung auf dieser Maschine belegt; was sich zu laden
//                 lohnt; welche neue Rolle denkbar waere; was der Katalog empfiehlt.
//   Neu bei Ollama  Neueste Modelle und Nachfolger, je mit Einordnung.
//   Verbrauch     Token und Kosten (verbrauch.js).
//
// Veiko (17.10.2026): "das Cockpit soll selbst sehr stringent nach Optimierungen
// suchen ... und mir dann Vorschlaege machen." Gesucht und gemessen wird nachts von
// selbst; umgestellt wird nie ohne Klick hier.
import { html, useState, useEffect, Icon, toast, fehlerMelden, zeitText, navigiere } from "./ui.js";
import { api } from "./api.js";
import { Verbrauch } from "./verbrauch.js";

const tok = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1).replace(".", ",") + " Mio." : n >= 1e3 ? Math.round(n / 1e3) + " Tsd." : String(n || 0));
const zahl = (x) => (x == null ? "—" : String(Math.round(x * 10) / 10).replace(".", ","));
const TABS = [["besetzung", "Besetzung"], ["optimierung", "Optimierung"], ["neu", "Neu bei Ollama"], ["verbrauch", "Verbrauch"]];
const URTEIL_KURZ = { tragfaehig: "in Ordnung", nachbessern: "mit Einwänden", rueckfrage: "mit Rückfrage", ungeprueft: "ungeprüft" };

function LadenKnopf({ name, laden, nachher, text = "Laden" }) {
  const j = laden[name];
  if (j && j.stand === "laeuft") return html`<span class="pill lila">lädt · ${j.prozent || 0} %</span>`;
  if (j && j.stand === "fertig") return html`<span class="pill gruen">geladen</span>`;
  async function los() {
    try { await api("/system/modell-laden", { methode: "POST", daten: { name } }); toast(`${name} wird geladen. Den Fortschritt siehst du unter „Neu bei Ollama“.`); nachher(); }
    catch (e) { fehlerMelden(e); }
  }
  return html`<button class="btn klein primaer" onClick=${los} title=${"Bei Ollama laden: " + name}><${Icon} n="download" g=${13} />${text}</button>`;
}

// ------------------------------------------------------------ Besetzung
function Besetzung({ rev, d, laden, neuLaden }) {
  async function umstellen(p, modell) {
    try { await api("/revision/umstellen", { methode: "POST", daten: { platz: p.platz, modell } }); toast(`${p.name} rechnet jetzt mit ${modell}.`); neuLaden(); }
    catch (e) { fehlerMelden(e); }
  }
  const gesamt = d ? d.installiert.reduce((s, m) => s + m.gb, 0) : 0;
  return html`
    <section class="karte">
      <div class="karte-kopf"><h3>Wer rechnet womit</h3><span class="leise klein">das Modell, das wirklich rechnet -- umstellen gilt sofort</span></div>
      ${!rev ? html`<div class="lade">Lade …</div>` : html`<div class="tabelle-wrap"><table class="tabelle mo-tabelle"><thead><tr>
          <th>Wer</th><th>Modell</th><th class="zahl">Aufrufe 30 T.</th><th class="zahl">Ø Dauer</th><th>Daniels Urteile</th></tr></thead>
        <tbody>${rev.bestand.plaetze.map((p) => html`<tr>
          <td><b>${p.name}</b><div class="leise klein">${p.titel}</div></td>
          <td><select class="eingabe mo-wahl" value=${p.modell || ""} onChange=${(e) => umstellen(p, e.target.value)}>
              ${!p.modell && html`<option value="">— keins installiert —</option>`}
              ${rev.installiert.map((n) => html`<option value=${n}>${n}</option>`)}</select>
            ${p.eigen_fehlt && html`<div class="mo-warn klein">Eingetragen ist <b class="mono">${p.eigen}</b> -- nicht installiert, deshalb rechnet still dieses hier.</div>`}</td>
          <td class="zahl">${p.aufrufe || html`<span class="leise">—</span>`}</td>
          <td class="zahl">${p.dauer_mittel != null ? zahl(p.dauer_mittel) + " s" : html`<span class="leise">—</span>`}</td>
          <td class="klein">${Object.keys(p.urteile || {}).length ? Object.entries(p.urteile).map(([u, n]) => `${n}× ${URTEIL_KURZ[u] || u}`).join(", ") : html`<span class="leise">—</span>`}</td></tr>`)}</tbody></table></div>
        <p class="leise klein" style="margin-top:8px">„Aufrufe“ zählt, wie oft diese Rolle mit diesem Modell gerechnet hat; „Ø Dauer“ ist die mittlere Wartezeit je Aufruf, Lesen und Laden eingeschlossen. Das reine Schreibtempo misst die Optimierung. Daniels Urteile zählen die geprüften Ergebnisse der Rolle. Mehr Zahlen stehen erst da, seit das Cockpit sie erfasst (Seite Verbrauch).</p>`}
    </section>
    <section class="karte">
      <div class="karte-kopf"><h3>Installiert</h3>${d && html`<span class="leise klein">${d.installiert.length} Modelle · ${gesamt.toFixed(0)} GB${d.frei_gb ? ` · ${Math.round(d.frei_gb)} GB frei` : ""} · ${d.vram.toFixed(0)} GB auf den Grafikkarten</span>`}</div>
      ${!d ? html`<div class="lade">Lade …</div>` : html`<div class="tabelle-wrap"><table class="tabelle mo-tabelle"><thead><tr>
        <th>Modell</th><th class="zahl">Größe</th><th>Passt</th><th>Bestes installiertes für</th><th>Team</th><th class="zahl">Aufrufe 30 T.</th><th>Zuletzt</th></tr></thead>
        <tbody>${d.installiert.map((m) => html`<tr>
          <td class="mono">${m.name}${m.geladen ? html` <span class="pill lila">im Speicher</span>` : ""}</td>
          <td class="zahl">${m.gb.toFixed(1).replace(".", ",")} GB</td>
          <td class="leise">${m.passt.replace("passt auf ", "")}</td>
          <td>${m.aufgaben.join(", ") || html`<span class="leise">—</span>`}</td>
          <td>${m.team.join(", ") || html`<span class="leise">—</span>`}</td>
          <td class="zahl">${m.aufrufe ? `${m.aufrufe} · ${tok(m.token)}` : html`<span class="leise">—</span>`}</td>
          <td class="leise klein">${m.zuletzt ? zeitText(m.zuletzt) : "—"}</td></tr>`)}</tbody></table></div>
        <p class="leise klein" style="margin-top:8px">Ein Strich bei „Aufrufe“ heißt noch nicht „wird nicht gebraucht“ -- gezählt wird erst seit ${d.erfasst_seit ? new Date(d.erfasst_seit * 1000).toLocaleDateString("de-DE") : "heute"}. Entfernt wird hier nichts.</p>`}
    </section>`;
}

// ------------------------------------------------------------ Optimierung
function Messung({ m }) {
  const [auf, setAuf] = useState(false);
  const n = m.aufgaben;
  const ergebnis = m.siege_kandidat > m.siege_bisher ? ["gruen", "neues vorn"] : m.siege_kandidat < m.siege_bisher ? ["", "bisheriges vorn"] : ["", "gleich"];
  return html`<div class="mo-messung">
    <div class="mo-messung-kopf" role="button" onClick=${() => setAuf(!auf)}>
      <span><b>${(m.daten || {}).name || m.platz}</b>: <span class="mono">${m.bisher}</span> gegen <span class="mono">${m.kandidat}</span></span>
      <span class=${"pill " + ergebnis[0]}>${ergebnis[1]} · ${m.siege_kandidat}:${m.siege_bisher}${m.gleich ? ` (${m.gleich}× gleich)` : ""} von ${n}</span>
      <span class="leise klein">${zahl(m.tps_bisher)} → ${zahl(m.tps_kandidat)} Tok/s · ${zeitText(m.zeit)}</span>
      <${Icon} n=${auf ? "runter" : "rechts"} g=${14} /></div>
    ${auf && html`<div class="mo-messung-leib klein">
      <p class="leise">Verdeckter Vergleich: ${m.richter} las beide Antworten als A und B in zufälliger Reihenfolge, ohne zu wissen, welche von welchem Modell kam. Antwortzeit ohne Laden: ${zahl(m.dauer_bisher)} s gegen ${zahl(m.dauer_kandidat)} s.</p>
      ${((m.daten || {}).einzeln || []).map((e, i) => html`<div class="mo-einzeln">
        <div><b>Aufgabe ${i + 1}:</b> ${e.aufgabe}</div>
        <div><span class=${"pill " + (e.sieger === "kandidat" ? "gruen" : "")}>${e.sieger === "kandidat" ? m.kandidat + " besser" : e.sieger === "bisher" ? m.bisher + " besser" : "gleich gut"}</span> ${e.begruendung}</div>
        <details><summary>Beide Antworten (Anfang)</summary><div class="mo-zwei"><div><b class="mono">${m.bisher}</b><p>${e.bisher_text}</p></div><div><b class="mono">${m.kandidat}</b><p>${e.kandidat_text}</p></div></div></details>
      </div>`)}</div>`}
  </div>`;
}

function Optimierung({ rev, d, laden, neuLaden }) {
  if (!rev) return html`<div class="lade">Lade …</div>`;
  const st = rev.stand || {};
  const tun = async (pfad, daten, text) => {
    try { const r = await api("/revision/" + pfad, { methode: "POST", daten: daten || {} }); if (text) toast(text); neuLaden(); return r; }
    catch (e) { fehlerMelden(e); }
  };
  const zurueckBar = new Set();
  const umgestellt = (rev.umgestellt || []).filter((u) => { if (u.zurueck || zurueckBar.has(u.platz)) return false; zurueckBar.add(u.platz); return true; });
  return html`
    <div class="mo-rev-kopf karte">
      <div class="haupt-text">
        ${st.laeuft ? html`<b><span class="vf-spin"></span> Prüft gerade${st.geplant ? ` (${st.fertig || 0} von ${st.geplant} Vergleichen)` : ""}</b>
            <div class="leise klein">${st.schritt || ""} -- das dauert je Vergleich einige Minuten.</div>`
          : html`<b>Modell-Revision</b>
            <div class="leise klein">Sucht jede Nacht (2--5 Uhr) selbst nach besseren Modellen und misst sie mit echten Aufgaben des Teams.
              ${st.ende ? ` Zuletzt ${zeitText(st.ende)}: ${st.fehler ? "gescheitert -- " + st.fehler : st.ergebnis || ""}` : " Noch kein Lauf."}</div>`}
      </div>
      <button class="btn klein" disabled=${st.laeuft} onClick=${() => tun("start", null, "Die Revision misst jetzt. Das dauert je Vergleich einige Minuten.")}>
        <${Icon} n="play" g=${13} />Jetzt prüfen</button>
    </div>

    <section class="karte">
      <div class="karte-kopf"><h3>Vorschläge zum Umstellen</h3><span class="leise klein">jeder mit einer Messung auf deinem Server belegt</span></div>
      ${rev.vorschlaege.length ? rev.vorschlaege.map((v) => html`<div class="zeile mo-empf">
          <div class="haupt-text"><b>${v.titel}</b>${v.art === "abwaegen" ? html` <span class="pill gelb">abwägen</span>` : ""}
            <div class="leise klein">${v.warum} Gemessen ${zeitText(v.zeit)}.</div></div>
          <span class="knopfreihe">
            <button class="btn klein primaer" onClick=${() => tun("umstellen", { platz: v.platz, modell: v.kandidat, messung: v.messung }, `${v.name} rechnet jetzt mit ${v.kandidat}.`)}>Umstellen</button>
            <button class="btn klein geist" onClick=${() => tun("verwerfen", { messung: v.messung }, "Verworfen.")}>Verwerfen</button></span></div>`)
        : html`<p class="leise">Kein Modell hat in einer Messung besser abgeschnitten als das, was gerade rechnet.${rev.messungen.length ? "" : " Gemessen wurde noch nichts -- die erste Revision läuft heute Nacht, oder „Jetzt prüfen“."}</p>`}
      ${umgestellt.length > 0 && html`<div class="mo-umgestellt">${umgestellt.slice(0, 5).map((u) => html`<div class="zeile klein">
          <div class="haupt-text">Umgestellt ${zeitText(u.zeit)}: <b>${u.platz.replace("rolle:", "").replace("vorgabe:", "")}</b> von <span class="mono">${u.vorher || "Vorgabe"}</span> auf <span class="mono">${u.nachher}</span></div>
          <button class="btn klein geist" onClick=${() => tun("zurueck", { platz: u.platz }, "Zurückgestellt.")}>Zurück</button></div>`)}</div>`}
    </section>

    ${rev.laden.length > 0 && html`<section class="karte">
      <div class="karte-kopf"><h3>Lohnt sich zu laden</h3><span class="leise klein">neu bei Ollama und passend für dein Team -- nach dem Laden misst die nächste Nacht</span></div>
      ${rev.laden.map((x) => html`<div class="zeile mo-empf"><div class="haupt-text"><b class="mono">${x.name}</b> ${x.neuer ? html`<span class="pill lila">Nachfolger</span>` : ""}
          <div class="leise klein">${x.gb} GB, ${x.passt}. Geeignet für ${x.rollen.join(", ")}.${x.ersetzt.length ? ` Könnte ${x.ersetzt.join(", ")} ersetzen.` : ""}</div></div>
        <${LadenKnopf} name=${x.name} laden=${laden} nachher=${neuLaden} /></div>`)}
    </section>`}

    ${rev.neue_rollen.length > 0 && html`<section class="karte">
      <div class="karte-kopf"><h3>Neue Rollen, die das Team brauchen könnte</h3><span class="leise klein">Fähigkeiten, für die heute niemand zuständig ist</span></div>
      ${rev.neue_rollen.map((r) => html`<div class="zeile mo-empf"><div class="haupt-text"><b>${r.name}</b>
          <div class="leise klein">${r.wofuer}.</div>
          <div class="mo-rollen-modelle">${r.modelle.map((m) => html`<span class="mo-rollen-modell"><span class="mono klein">${m.name}</span> <span class="leise klein">${m.gb} GB</span>
            ${m.installiert ? html`<span class="pill gruen">installiert</span>` : html`<${LadenKnopf} name=${m.name} laden=${laden} nachher=${neuLaden} />`}</span>`)}</div></div></div>`)}
      <p class="leise klein">Eine neue Rolle braucht deine Entscheidung, welche Aufgaben sie übernimmt. Sag mir oder Neo, welche du willst -- dann richten wir sie ein.</p>
    </section>`}

    ${d && d.empfehlungen.length > 0 && html`<section class="karte">
      <div class="karte-kopf"><h3>Aus dem Modellkatalog</h3><span class="leise klein">ungeprüft -- erst laden, dann misst die Revision</span></div>
      ${d.empfehlungen.map((e) => html`<div class="zeile mo-empf"><div class="haupt-text"><b>${e.titel}</b><div class="leise klein">${e.warum}</div></div>
        ${e.aktion && e.aktion.art === "modell" && html`<${LadenKnopf} name=${e.aktion.name} laden=${laden} nachher=${neuLaden} text=${e.aktion.text} />`}</div>`)}
    </section>`}

    <section class="karte">
      <div class="karte-kopf"><h3>Messungen</h3><span class="leise klein">die letzten 20 -- anklicken für Aufgaben und Begründungen</span></div>
      ${rev.messungen.length ? rev.messungen.map((m) => html`<${Messung} key=${m.id} m=${m} />`) : html`<p class="leise">Noch keine.</p>`}
    </section>`;
}

// ------------------------------------------------------------ Neu bei Ollama
function NeuBeiOllama({ d, laden, neuLaden, prueft, frisch }) {
  if (!d) return html`<div class="lade">Lade …</div>`;
  const downloads = Object.values(laden).filter((j) => j.stand === "laeuft" || j.stand === "fehler");
  const familien = (d.neu && d.neu.familien) || [];
  const art = (f) => f.neuer ? ["lila", "Nachfolger"] : f.groesser ? ["gelb", "größere Ausgabe"] : f.verwandt ? ["", "aus deiner Familie"] : ["", "neu, andere Familie"];
  return html`
    ${downloads.length > 0 && html`<section class="karte">
      <div class="karte-kopf"><h3>Wird geladen</h3></div>
      ${downloads.map((j) => html`<div class="zeile"><div class="haupt-text"><b class="mono">${j.name}</b>
        <div class="leise klein">${j.stand === "fehler" ? "Abgebrochen: " + (j.fehler || "") : `${j.schritt || ""}${j.gb ? ` · ${j.gb} GB` : ""} · seit ${zeitText(j.start)}`}</div>
        ${j.stand === "laeuft" && html`<div class="video-balken"><i style=${`width:${j.prozent || 0}%`}></i></div>`}</div>
        ${j.stand === "fehler" ? html`<${LadenKnopf} name=${j.name} laden=${{}} nachher=${neuLaden} text="Neu versuchen" />` : html`<span class="neben">${j.prozent || 0} %</span>`}</div>`)}
      <p class="leise klein">Die Leitung des Servers ist langsam (unter 1 MB/s); große Modelle brauchen Stunden. Ein abgebrochener Download setzt beim nächsten Versuch fort.</p>
    </section>`}
    <section class="karte">
      <div class="karte-kopf"><h3>Neu bei Ollama</h3><span class="leise klein">${d.neu && d.neu.zeit ? `zuletzt geprüft ${zeitText(d.neu.zeit)}` : ""}</span><span class="luecke"></span>
        <button class="btn klein" onClick=${frisch} disabled=${prueft}><${Icon} n="neu" g=${14} />${prueft ? "prüft …" : "Jetzt neu prüfen"}</button></div>
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
            ${a.installiert ? html`<span class="pill gruen">installiert</span>` : html`<${LadenKnopf} name=${a.name} laden=${laden} nachher=${neuLaden} />`}</div>`)}
        </div>`; })}</div>`
        : html`<p class="leise">${d.neu && d.neu.fehler ? "ollama.com war nicht erreichbar: " + d.neu.fehler : "Noch nicht geprüft."}</p>`}
    </section>`;
}

// ------------------------------------------------------------ Seite
export function Modelle({ tab }) {
  const reiter = TABS.some((t) => t[0] === tab) ? tab : "besetzung";
  const [d, setD] = useState(null);
  const [rev, setRev] = useState(null);
  const [laden, setLaden] = useState({});
  const [prueft, setPrueft] = useState(false);
  const holen = (frisch) => {
    setPrueft(!!frisch);
    return api("/modelle" + (frisch ? "?frisch=1" : "")).then((x) => { setD(x); setLaden(x.laden || {}); })
      .catch(fehlerMelden).finally(() => setPrueft(false));
  };
  const revHolen = () => api("/revision").then(setRev).catch(fehlerMelden);
  const alles = () => { holen(false); revHolen(); };
  useEffect(() => { holen(false); revHolen(); }, []);
  // Laeuft ein Download oder eine Revision, alle paar Sekunden den Stand holen.
  const laedt = Object.values(laden).some((j) => j.stand === "laeuft");
  const prueftRev = !!(rev && rev.stand && rev.stand.laeuft);
  useEffect(() => {
    if (!laedt) return undefined;
    const t = setInterval(() => api("/system/modell-laden").then((x) => {
      setLaden(x.laden || {});
      if (!Object.values(x.laden || {}).some((j) => j.stand === "laeuft")) holen(false);
    }).catch(() => {}), 5000);
    return () => clearInterval(t);
  }, [laedt]);
  useEffect(() => {
    if (!prueftRev) return undefined;
    const t = setInterval(revHolen, 10000);
    return () => clearInterval(t);
  }, [prueftRev]);
  const anzahl = rev ? rev.vorschlaege.length : 0;
  return html`<div class="seite mo">
    <div class="tabs" role="tablist">${TABS.map(([k, t]) => html`<button role="tab" aria-selected=${reiter === k} class=${reiter === k ? "an" : ""}
      onClick=${() => navigiere("/modelle/" + k)}>${t}${k === "optimierung" && anzahl ? html` <span class="pill gruen">${anzahl}</span>` : ""}</button>`)}</div>
    ${reiter === "besetzung" && html`<${Besetzung} rev=${rev} d=${d} laden=${laden} neuLaden=${alles} />`}
    ${reiter === "optimierung" && html`<${Optimierung} rev=${rev} d=${d} laden=${laden} neuLaden=${alles} />`}
    ${reiter === "neu" && html`<${NeuBeiOllama} d=${d} laden=${laden} neuLaden=${alles} prueft=${prueft} frisch=${() => holen(true)} />`}
    ${reiter === "verbrauch" && html`<${Verbrauch} />`}
  </div>`;
}
