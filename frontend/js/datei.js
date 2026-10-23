// UNTERLAGE ANSEHEN (19.10.2026) -- ein Recherche-Dossier, eine Abschrift oder eine
// hochgeladene Datei im Cockpit lesen, statt sie herunterzuladen. Anlass: Veiko fand
// das Dossier aus Talk nicht; der Link fuehrte nur zu einem Download. EIN Fenster
// (bus "datei-zeigen", gezeigt von app.js) fuer Explorer, Talk, Aufgabe und Projekt.
// Hier laesst sich auch sagen, wohin die Unterlage gehoert (Projekt, Aufgabe).
//
// Der Text steht als Seite wie in Word (Veiko: "eher in einer Ansicht wie die Vorschau
// fuer ein Word-Dokument") -- dieselbe Ansicht wie bei Ergebnissen (/dateien/{id}/ansicht,
// dokumente.zu_html), abgeschottet im Rahmen; dazu Word als Download.
import { html, useState, useEffect, Icon, Modal, toast, fehlerMelden, zeitText, bus, aktualisieren, useFensterKontext } from "./ui.js";
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

// POWERPOINT ALS FOLIEN (23.10.2026) -- Veiko: eine pptx aus dem Explorer kam nur als
// Text an, die FR5-Ausgabe steht dazu im Hochformat. Der Server liest jede Folie
// (pptx_ansicht.py: Lage, Text, Farben, Bilder); hier wird sie im RICHTIGEN
// Seitenverhaeltnis gezeichnet. Eine Buehne in Punkt (1 pt = 1 px), die per transform
// auf die Breite des Fensters skaliert wird -- so stimmen Abstaende und Schriftgroessen
// zueinander, egal wie breit das Fenster ist. Text wird als TEXT gesetzt (Preact), nie
// als Markup: er stammt aus einer fremden Datei.
const PPTX = /\.(pptx|ppsx|potx|pptm)$/i;
export const istPptx = (name) => PPTX.test(name || "");

function hgStil(h, medium) {
  if (!h) return "background:#fff";
  if (h.bild) return `background:#fff url("${medium(h.bild)}") center/cover no-repeat`;
  if (h.verlauf) return `background:linear-gradient(${h.verlauf.join(",")})`;
  return `background:${h.farbe || "#fff"}`;
}

function TextBlock({ t }) {
  const skala = t.skala || 1;
  const grund = t.grund_gr || 18;
  const [l, o, r, u] = t.innen;
  const stil = `position:absolute;inset:0;display:flex;flex-direction:column;justify-content:${{ m: "center", b: "flex-end" }[t.anker] || "flex-start"};`
    + `padding:${o}px ${r}px ${u}px ${l}px;`
    + (t.senkrecht ? `writing-mode:vertical-rl;${t.senkrecht === "vert270" ? "transform:rotate(180deg);" : ""}` : "");
  return html`<div style=${stil}>${t.absaetze.map((a) => {
    const gr0 = ((a.laeufe[0] && a.laeufe[0].gr) || a.leer || grund) * skala;
    const pst = `margin:${a.vor || 0}px 0 ${a.nach || 0}px ${a.einzug || 0}px;text-indent:${a.erste || 0}px;text-align:${{ c: "center", r: "right", j: "justify" }[a.ausr] || "left"};`
      + (a.zh_pt ? `line-height:${a.zh_pt}px;` : `line-height:${(a.zh || 1) * 1.2};`) + `white-space:${t.umbruch ? "pre-wrap" : "pre"};font-size:${gr0}px;overflow-wrap:break-word`;
    if (!a.laeufe.length) return html`<div style=${pst + `;height:${gr0 * 1.2}px`}></div>`;
    return html`<div style=${pst}>${a.aufz && html`<span style="margin-right:.4em">${a.aufz}</span>`}${a.laeufe.map((x) => html`<span style=${
      `font-size:${(x.gr || grund) * skala}px;font-weight:${x.f ? 700 : 400};font-style:${x.k ? "italic" : "normal"};`
      + (x.u ? "text-decoration:underline;" : "") + (x.gross ? "text-transform:uppercase;" : "")
      + (x.spc ? `letter-spacing:${x.spc}px;` : "") + `color:${x.farbe || "#000"};`
      + `font-family:${x.schrift ? JSON.stringify(x.schrift) + "," : ""}"Segoe UI",Arial,sans-serif`}>${x.t}</span>`)}</div>`;
  })}</div>`;
}

function Form({ f, medium, s }) {
  const tr = [f.dreh ? `rotate(${f.dreh}deg)` : "", f.spiegelH ? "scaleX(-1)" : "", f.spiegelV ? "scaleY(-1)" : ""].join(" ").trim();
  let stil = `position:absolute;left:${f.x}px;top:${f.y}px;width:${Math.max(f.b, 0.5)}px;height:${Math.max(f.h, 0.5)}px;` + (tr ? `transform:${tr};` : "");
  if (f.art === "bild") {
    if (f.fehlt) return html`<div class="folie-fehlt" style=${stil} title=${f.fehlt}>Grafik nicht darstellbar</div>`;
    const [l, t, r, b] = f.schnitt || [0, 0, 0, 0];
    const bw = f.b / Math.max(0.01, 1 - l - r), bh = f.h / Math.max(0.01, 1 - t - b);
    return html`<div style=${stil + "overflow:hidden"}><img src=${medium(f.medium, Math.max(bw, bh) * s)} alt="" loading="lazy" draggable="false"
      style=${`position:absolute;left:${-l * bw}px;top:${-t * bh}px;width:${bw}px;height:${bh}px;max-width:none`} /></div>`;
  }
  if (f.art === "platzhalter") return html`<div class="folie-fehlt" style=${stil} title=${f.fehlt}>${f.fehlt}</div>`;
  if (f.art === "tabelle") {
    return html`<div style=${stil}><table class="folie-tabelle"><colgroup>${f.spalten.map((w) => html`<col style=${`width:${w}px`} />`)}</colgroup>
      ${f.zeilen.map((z) => html`<tr style=${`height:${z.h}px`}>${z.zellen.filter((c) => !c.verbunden).map((c) => html`<td colspan=${c.spanne || 1}
        style=${`position:relative;${c.grund ? "background:" + c.grund : ""}`}>${c.text && html`<${TextBlock} t=${c.text} />`}</td>`)}</tr>`)}</table></div>`;
  }
  if (f.art === "linie") {
    const r = f.rand || { farbe: "#000", breite: 1 };
    const waag = f.h < 1;
    return html`<div style=${stil + (waag ? `height:0;border-top:${r.breite}px solid ${r.farbe}` : f.b < 1 ? `width:0;border-left:${r.breite}px solid ${r.farbe}`
      : `background:linear-gradient(to bottom right,transparent calc(50% - ${r.breite / 2}px),${r.farbe} 50%,transparent calc(50% + ${r.breite / 2}px))`)}></div>`;
  }
  if (f.fuellung) stil += `background:${f.fuellung};`;
  if (f.verlauf) stil += `background:linear-gradient(${f.verlauf.join(",")});`;
  if (f.bildfuellung) stil += `background:url("${medium(f.bildfuellung, Math.max(f.b, f.h) * s)}") center/cover no-repeat;`;
  if (f.rand) stil += `outline:${f.rand.breite}px solid ${f.rand.farbe};outline-offset:-${f.rand.breite}px;`;
  if (f.rund) stil += `border-radius:${f.rund};`;
  return html`<div style=${stil}>${f.text && html`<${TextBlock} t=${f.text} />`}</div>`;
}

export function FolienAnsicht({ id }) {
  const [d, setD] = useState(null);
  const [fehler, setFehler] = useState("");
  const [breite, setBreite] = useState(0);
  const [box, setBox] = useState(null);
  useEffect(() => { setD(null); setFehler(""); api("/dateien/" + id + "/folien").then(setD).catch((e) => setFehler(e.message)); }, [id]);
  useEffect(() => {
    if (!box) return;
    const ro = new ResizeObserver(() => setBreite(box.clientWidth));
    ro.observe(box); setBreite(box.clientWidth);
    return () => ro.disconnect();
  }, [box]);
  if (fehler) return html`<div class="fehlerbox">${fehler}</div>`;
  if (!d) return html`<div class="lade">Lese die Folien …</div>`;
  const hoch = d.hoehe > d.breite;
  // Jede Folie passt ganz auf den Bildschirm -- im Hochformat waere sie sonst 1,5 Bildschirme hoch.
  const maxB = Math.min(breite, 1280, (window.innerHeight * 0.8) * d.breite / d.hoehe);
  const s = maxB > 0 ? maxB / d.breite : 0;
  // Jedes Bild in der Groesse, in der es wirklich zu sehen ist -- ein stark zugeschnittenes
  // Bild braucht mehr Punkte als die Folie breit ist. In 200er-Stufen, damit der Zwischenspeicher trifft.
  const medium = (n, px) => "/api/dateien/" + id + "/folienmedium?n=" + encodeURIComponent(n) + "&b="
    + Math.round(Math.min(2400, Math.max(400, (px || maxB) * (window.devicePixelRatio || 1))) / 200) * 200;
  return html`<div class="folien" ref=${setBox}>
    <p class="leise klein folien-kopf">${d.folien.length} ${d.folien.length === 1 ? "Folie" : "Folien"} · ${hoch ? "Hochformat" : "Querformat"}
      ${d.hinweise.length ? html` · <span title=${d.hinweise.join("\n")}>${d.hinweise.join(" ")}</span>` : ""}</p>
    ${s > 0 && d.folien.map((f) => html`<figure class=${"folie-rahmen" + (f.ausgeblendet ? " ausgeblendet" : "")} style=${`width:${d.breite * s}px`}>
      <div class="folie-flaeche" style=${`width:${d.breite * s}px;height:${d.hoehe * s}px`}>
        <div class="folie-buehne" style=${`width:${d.breite}px;height:${d.hoehe}px;transform:scale(${s});${hgStil(f.hintergrund, medium)}`}>
          ${f.formen.map((fo) => html`<${Form} f=${fo} medium=${medium} s=${s} />`)}
        </div>
      </div>
      <figcaption class="leise klein">Folie ${f.nr}${f.ausgeblendet ? " · ausgeblendet" : ""}
        ${f.notiz && html`<details><summary>Notizen</summary><div style="white-space:pre-wrap">${f.notiz}</div></details>`}</figcaption>
    </figure>`)}
  </div>`;
}

export function DateiFenster({ id, zu }) {
  const [d, setD] = useState(null);
  const [fehler, setFehler] = useState("");
  const [zeigText, setZeigText] = useState(false);
  const holen = () => api("/dateien/" + id + "/info").then(setD).catch((e) => setFehler(e.message));
  useEffect(() => { holen(); }, [id]);
  useFensterKontext(d && { art: "datei", id: d.id, titel: d.name });
  async function zuordnen(z) {
    try {
      await api("/dateien/" + id, { methode: "PATCH", daten: z });
      toast(z.aufgabe_id ? "Hängt jetzt an der Aufgabe." : z.projekt_id ? "Gehört jetzt zum Projekt." : "Keinem Projekt mehr zugeordnet.");
      holen(); aktualisieren(); bus.sende("explorer-neu");
    } catch (e) { fehlerMelden(e); }
  }
  const ort = d && (d.aufgabe_titel ? html`Hängt an der Aufgabe <b>${d.aufgabe_titel}</b>${d.projekt_name ? html` im Projekt <b>${d.projekt_name}</b>` : ""}`
    : d.projekt_name ? html`Gehört zum Projekt <b>${d.projekt_name}</b>` : "Gehört noch zu keinem Projekt");
  return html`<${Modal} titel=${d ? d.name.replace(/\.(md|txt)$/i, "") : "Unterlage"} zu=${zu} breit="voll"
    fuss=${d && html`<span class="leise klein" style="margin-right:auto">${groesse(d.groesse)} · ${zeitText(d.erstellt)}</span>
      <button class="btn" onClick=${() => { bus.sende("talk-oeffnen", { kontext: { art: "datei", id: d.id, titel: d.name } }); zu(); }}><${Icon} n="talk" g=${14} />Mit Talk besprechen</button>
      ${d.text && html`<a class="btn primaer" href=${"/api/dateien/" + d.id + "/word"} download><${Icon} n="download" g=${14} />Word</a>`}
      ${d.vorhanden && html`<a class="btn" href=${"/api/dateien/" + d.id} download title="Die Datei, wie sie abgelegt ist"><${Icon} n="download" g=${14} />Original</a>`}`}>
    ${fehler && html`<div class="fehlerbox">${fehler}</div>`}
    ${!d && !fehler && html`<div class="lade">Lade …</div>`}
    ${d && html`<div class="datei-fenster">
      <details class="karte datei-zuordnung">
        <summary class="klein">${ort}<span class="leise"> · ändern</span></summary>
        ${d.aufgabe_id && html`<button class="btn klein geist" style="margin-top:6px" onClick=${() => { bus.sende("aufgabe-zeigen", d.aufgabe_id); zu(); }}>Aufgabe öffnen</button>`}
        <${ZuordnungWahl} projektId=${d.projekt_id} aufgabeId=${d.aufgabe_id} setzen=${zuordnen} />
      </details>
      ${d.vorhanden && istPptx(d.name) && html`<div class="folien-umschalter">
        <button class=${"btn klein" + (zeigText ? " geist" : " primaer")} onClick=${() => setZeigText(false)}>Folien</button>
        <button class=${"btn klein" + (zeigText ? " primaer" : " geist")} disabled=${!d.text} onClick=${() => setZeigText(true)}>Nur Text</button></div>`}
      ${d.vorhanden && istPptx(d.name) && !zeigText ? html`<${FolienAnsicht} id=${d.id} />`
        : d.text ? html`<iframe class="datei-seite" src=${"/api/dateien/" + d.id + "/ansicht"} sandbox="allow-scripts allow-popups" title=${d.name}></iframe>`
        : html`<p class="leise">Den Inhalt konnte das Cockpit nicht als Text lesen. ${d.vorhanden ? "Das Original lässt sich herunterladen." : "Die Datei liegt nicht mehr auf dem Server."}</p>`}
    </div>`}
  <//>`;
}
