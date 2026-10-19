// UNTERLAGE ANSEHEN (19.10.2026) -- ein Recherche-Dossier, eine Abschrift oder eine
// hochgeladene Datei im Cockpit lesen, statt sie herunterzuladen. Anlass: Veiko fand
// das Dossier aus Talk nicht; der Link fuehrte nur zu einem Download. EIN Fenster
// (bus "datei-zeigen", gezeigt von app.js) fuer Explorer, Talk, Aufgabe und Projekt.
// Hier laesst sich auch sagen, wohin die Unterlage gehoert (Projekt, Aufgabe).
import { html, useState, useEffect, Icon, Md, Modal, toast, fehlerMelden, zeitText, bus, aktualisieren } from "./ui.js";
import { api } from "./api.js";

const groesse = (b) => (b >= 1048576 ? (b / 1048576).toFixed(1).replace(".", ",") + " MB" : b >= 1024 ? Math.round(b / 1024) + " KB" : (b || 0) + " Byte");

// Projekt und Aufgabe waehlen -- auch vom Explorer benutzt.
export function ZuordnungWahl({ projektId, aufgabeId, setzen }) {
  const [projekte, setProjekte] = useState([]);
  const [aufgaben, setAufgaben] = useState([]);
  useEffect(() => { api("/projekte").then((d) => setProjekte(d.projekte)).catch(() => {}); }, []);
  useEffect(() => {
    if (!projektId) { setAufgaben([]); return; }
    api("/aufgaben?status=offen&projekt=" + encodeURIComponent(projektId)).then((d) => setAufgaben(d.aufgaben)).catch(() => {});
  }, [projektId]);
  return html`<div class="zuordnung-wahl">
    <label class="klein leise" for="zw-projekt">Projekt</label>
    <select id="zw-projekt" class="eingabe" value=${projektId || ""} onChange=${(e) => setzen({ projekt_id: e.target.value || null, aufgabe_id: null })}>
      <option value="">ohne Projekt</option>${projekte.map((p) => html`<option value=${p.id}>${p.name}</option>`)}</select>
    <label class="klein leise" for="zw-aufgabe">Aufgabe</label>
    <select id="zw-aufgabe" class="eingabe" value=${aufgabeId || ""} disabled=${!projektId} onChange=${(e) => setzen({ projekt_id: projektId, aufgabe_id: e.target.value || null })}>
      <option value="">keine bestimmte Aufgabe</option>
      ${aufgabeId && !aufgaben.some((a) => a.id === aufgabeId) && html`<option value=${aufgabeId}>(aktuelle Aufgabe)</option>`}
      ${aufgaben.map((a) => html`<option value=${a.id}>${a.titel}</option>`)}</select>
  </div>`;
}

export function DateiFenster({ id, zu }) {
  const [d, setD] = useState(null);
  const [fehler, setFehler] = useState("");
  const holen = () => api("/dateien/" + id + "/info").then(setD).catch((e) => setFehler(e.message));
  useEffect(() => { holen(); }, [id]);
  async function zuordnen(z) {
    try {
      await api("/dateien/" + id, { methode: "PATCH", daten: z });
      toast(z.aufgabe_id ? "Hängt jetzt an der Aufgabe." : z.projekt_id ? "Gehört jetzt zum Projekt." : "Keinem Projekt mehr zugeordnet.");
      holen(); aktualisieren(); bus.sende("explorer-neu");
    } catch (e) { fehlerMelden(e); }
  }
  const md = d && /\.md$/i.test(d.name);
  return html`<${Modal} titel=${d ? d.name.replace(/\.(md|txt)$/i, "") : "Unterlage"} zu=${zu} breit=${true}
    fuss=${d && html`<span class="leise klein" style="margin-right:auto">${groesse(d.groesse)} · ${zeitText(d.erstellt)}</span>
      <button class="btn" onClick=${() => { bus.sende("talk-oeffnen", { kontext: { art: "datei", id: d.id, titel: d.name } }); zu(); }}><${Icon} n="talk" g=${14} />Mit Talk besprechen</button>
      ${d.vorhanden && html`<a class="btn primaer" href=${"/api/dateien/" + d.id} download><${Icon} n="download" g=${14} />Herunterladen</a>`}`}>
    ${fehler && html`<div class="fehlerbox">${fehler}</div>`}
    ${!d && !fehler && html`<div class="lade">Lade …</div>`}
    ${d && html`<div class="datei-fenster">
      <div class="karte datei-zuordnung">
        <div class="leise klein" style="margin-bottom:6px">${d.aufgabe_titel ? html`Hängt an der Aufgabe <b>${d.aufgabe_titel}</b>${d.projekt_name ? html` im Projekt <b>${d.projekt_name}</b>` : ""}.`
          : d.projekt_name ? html`Gehört zum Projekt <b>${d.projekt_name}</b>.` : "Gehört noch zu keinem Projekt."}
          ${d.aufgabe_id && html` <button class="btn klein geist" onClick=${() => { bus.sende("aufgabe-zeigen", d.aufgabe_id); zu(); }}>Aufgabe öffnen</button>`}</div>
        <${ZuordnungWahl} projektId=${d.projekt_id} aufgabeId=${d.aufgabe_id} setzen=${zuordnen} />
      </div>
      ${d.text ? html`<div class="datei-text">${md ? html`<${Md} text=${d.text} />` : html`<pre>${d.text}</pre>`}</div>`
        : html`<p class="leise">Den Inhalt konnte das Cockpit nicht als Text lesen. ${d.vorhanden ? "Herunterladen geht." : "Die Datei liegt nicht mehr auf dem Server."}</p>`}
      ${d.gekuerzt && html`<p class="leise klein">Gezeigt sind die ersten 200.000 Zeichen; die ganze Datei gibt es per Download.</p>`}
    </div>`}
  <//>`;
}
