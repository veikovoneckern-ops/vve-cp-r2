// ZEITPLAN und STRUKTUR -- zwei Darstellungen der Aufgaben eines Projekts, wie im
// alten Cockpit (dort: Zeitplan, Ablauf, Struktur). Beide arbeiten auf denselben
// Aufgaben wie der Reiter "Aufgaben"; es gibt keinen eigenen Bestand.
//
// Ziehen ueber Pointer Events, NICHT ueber natives HTML5-Drag: im alten Cockpit
// scheiterten drei Anlaeufe mit draggable/dragstart am echten Browser (CLAUDE.md
// dort, "Rail-Reihenfolge"). Pointer Events sind gewoehnliche Ereignisse ohne
// eigenen Browser-Modus und funktionieren mit Maus und Finger gleich.
import { html, useState, useRef, Icon, Leer, fehlerMelden, aktualisieren } from "./ui.js";
import { api } from "./api.js";

const TAG = 86400000;
const iso = (d) => d.toISOString().slice(0, 10);
const zuDatum = (s) => (s ? new Date(s + "T00:00:00") : null);
const heute = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
const kurz = (s) => (s ? new Date(s + "T00:00:00").toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" }) : "");

// Baum aus eltern_id, Reihenfolge nach sortierung, dann Termin. Aufgaben, deren
// Eltern nicht sichtbar sind (archiviert, anderes Projekt), werden zur Wurzel --
// es geht nichts verloren.
export function baum(aufgaben) {
  const ids = new Set(aufgaben.map((t) => t.id));
  const ord = (a, b) => (a.sortierung || 0) - (b.sortierung || 0) || (a.faellig || "9").localeCompare(b.faellig || "9") || (a.erstellt || 0) - (b.erstellt || 0);
  const kinder = (pid) => aufgaben.filter((t) => (pid ? t.eltern_id === pid : !t.eltern_id || !ids.has(t.eltern_id))).sort(ord);
  const flach = [];
  const geh = (t, tiefe, zu) => {
    const k = kinder(t.id);
    flach.push({ t, tiefe, kinder: k.length });
    if (!zu.has(t.id)) k.forEach((c) => geh(c, tiefe + 1, zu));
  };
  return (zu = new Set()) => { flach.length = 0; kinder(null).forEach((t) => geh(t, 0, zu)); return flach.slice(); };
}

async function setzen(id, daten, nachher) {
  try { await api("/aufgaben/" + id, { methode: "PATCH", daten }); nachher(); aktualisieren(); } catch (e) { fehlerMelden(e); }
}

// ------------------------------------------------------------ Zeitplan
export function Zeitplan({ projekt, aufgaben, laden }) {
  const offenAuch = aufgaben.filter((t) => !t.archiviert);
  const zeilen = baum(offenAuch)();
  const mitTermin = zeilen.filter((z) => z.t.faellig || z.t.start);
  const ohne = zeilen.filter((z) => !z.t.faellig && !z.t.start);
  const daten = [heute()];
  [projekt.start, projekt.ende].forEach((s) => { const d = zuDatum(s); if (d) daten.push(d); });
  mitTermin.forEach(({ t }) => [t.start, t.faellig].forEach((s) => { const d = zuDatum(s); if (d) daten.push(d); }));
  const von = new Date(Math.min(...daten)); von.setDate(1);
  const bis = new Date(Math.max(...daten)); bis.setMonth(bis.getMonth() + 1, 0);
  const tage = Math.round((bis - von) / TAG) + 1;
  const pct = (d) => ((d - von) / TAG) / tage * 100;
  const monate = [];
  for (let m = new Date(von); m <= bis; m = new Date(m.getFullYear(), m.getMonth() + 1, 1)) {
    const ende = new Date(m.getFullYear(), m.getMonth() + 1, 0);
    monate.push({ name: m.toLocaleDateString("de-DE", { month: "short", year: "2-digit" }), links: pct(m), breite: pct(ende) - pct(m) + 100 / tage });
  }
  const h = pct(heute());
  // Hilfslinien genau an den Monatsanfaengen, passend zur Achse darueber.
  const linien = monate.slice(1).map((m) => html`<i class="zp-mon" style=${`left:${m.links}%`}></i>`);
  const pS = zuDatum(projekt.start), pE = zuDatum(projekt.ende);

  const Spur = ({ t }) => {
    const s = zuDatum(t.start), f = zuDatum(t.faellig);
    const erl = t.status === "erledigt", ueber = !erl && f && f < heute();
    const kl = "zp-balken" + (erl ? " erledigt" : ueber ? " ueber" : "");
    return html`<div class="zp-spur">
      ${linien}<i class="zp-heute" style=${`left:${h}%`}></i>
      ${s && f ? html`<span class=${kl} style=${`left:${pct(s)}%;width:${Math.max(pct(f) - pct(s) + 100 / tage, 0.6)}%`} title=${`${kurz(t.start)} – ${kurz(t.faellig)}`}></span>`
        : html`<span class=${"zp-marke" + (erl ? " erledigt" : ueber ? " ueber" : "")} style=${`left:${pct(f || s)}%`} title=${(f ? "fällig " : "Beginn ") + kurz(t.faellig || t.start)}></span>`}
    </div>`;
  };

  return html`<section class="karte zp">
    <div class="zp-legende"><span><i class="zp-l balken"></i>Beginn bis Fälligkeit</span><span><i class="zp-l marke"></i>nur fällig</span>
      <span><i class="zp-l ueber"></i>überfällig</span><span><i class="zp-l heute"></i>heute</span>
      <span class="leise">Beginn und Fälligkeit direkt in der Zeile ändern.</span></div>
    <div class="zp-raster">
      <div class="zp-kopf"><div class="zp-name">Aufgabe</div><div class="zp-daten">Beginn · Fällig</div>
        <div class="zp-achse">${monate.map((m) => html`<span style=${`left:${m.links}%;width:${m.breite}%`}>${m.name}</span>`)}<i class="zp-heute" style=${`left:${h}%`}></i></div></div>
      <div class="zp-zeile zp-projekt"><div class="zp-name"><b>${projekt.name}</b></div><div class="zp-daten leise klein">${pS ? kurz(projekt.start) : "?"} – ${pE ? kurz(projekt.ende) : "offen"}</div>
        <div class="zp-spur">${linien}<i class="zp-heute" style=${`left:${h}%`}></i>${pS && html`<span class="zp-balken projekt" style=${`left:${pct(pS)}%;width:${Math.max((pE ? pct(pE) : 100) - pct(pS), 0.6)}%;background:${projekt.farbe || "var(--steel)"}`}></span>`}</div></div>
      ${mitTermin.map(({ t, tiefe }) => html`<div class="zp-zeile" key=${t.id}>
        <div class="zp-name" style=${`padding-left:${tiefe * 16}px`} title=${t.titel}><span class=${t.status === "erledigt" ? "erledigt" : ""}>${t.titel}</span></div>
        <div class="zp-daten">
          <input type="date" value=${t.start || ""} aria-label=${"Beginn: " + t.titel} onChange=${(e) => setzen(t.id, { start: e.target.value || null }, laden)} />
          <input type="date" value=${t.faellig || ""} aria-label=${"Fällig: " + t.titel} onChange=${(e) => setzen(t.id, { faellig: e.target.value }, laden)} />
        </div>
        <${Spur} t=${t} /></div>`)}
    </div>
    ${ohne.length > 0 && html`<details class="zp-ohne"><summary>${ohne.length} ${ohne.length === 1 ? "Aufgabe" : "Aufgaben"} ohne Termin</summary>
      ${ohne.map(({ t }) => html`<div class="zp-ohne-zeile" key=${t.id}><span>${t.titel}</span>
        <input type="date" aria-label=${"Fällig: " + t.titel} onChange=${(e) => setzen(t.id, { faellig: e.target.value }, laden)} /></div>`)}
    </details>`}
    ${!zeilen.length && html`<${Leer} titel="Noch keine Aufgaben." />`}
  </section>`;
}

// ------------------------------------------------------------ Struktur
// Mitte einer Aufgabe = als Unteraufgabe anhaengen, oberes/unteres Viertel =
// davor/danach einsortieren, freie Flaeche darunter = oberste Ebene. Wie im
// alten Cockpit; die Pruefung auf Zyklen macht der Server.
export function Struktur({ aufgaben, laden }) {
  const [zu, setZu] = useState(() => new Set());
  const [zug, setZug] = useState(null); // { id, x, y, ziel, wo }
  const zugRef = useRef(null);
  const liste = useRef(null);
  const sichtbar = aufgaben.filter((t) => !t.archiviert);
  const zeilen = baum(sichtbar)(zu);

  function zielFinden(x, y, eigene) {
    const el = document.elementFromPoint(x, y);
    const zeile = el && el.closest("[data-st-id]");
    if (zeile && liste.current.contains(zeile)) {
      const id = zeile.dataset.stId;
      if (id === eigene) return null;
      const b = zeile.getBoundingClientRect();
      const r = (y - b.top) / b.height;
      return { ziel: id, wo: r < 0.28 ? "davor" : r > 0.72 ? "danach" : "darunter" };
    }
    if (el && el.closest(".st-frei")) return { ziel: null, wo: "oben" };
    return null;
  }

  function runter(e, t) {
    if (e.button !== undefined && e.button !== 0) return;
    const start = { x: e.clientX, y: e.clientY };
    let aktiv = false;
    const zieh = (ev) => {
      if (!aktiv && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 6) return; // Klick, kein Ziehen
      aktiv = true;
      ev.preventDefault();
      // Am Rand des sichtbaren Bereichs mitscrollen -- sonst laege bei langen
      // Listen das Ziel (oder die freie Flaeche) unerreichbar unter dem Rand.
      const rolle = liste.current && liste.current.closest(".inhalt");
      if (rolle) {
        const b = rolle.getBoundingClientRect();
        if (ev.clientY > b.bottom - 50) rolle.scrollTop += 14;
        else if (ev.clientY < b.top + 50) rolle.scrollTop -= 14;
      }
      const z ={ id: t.id, titel: t.titel, x: ev.clientX, y: ev.clientY, ...(zielFinden(ev.clientX, ev.clientY, t.id) || { ziel: undefined, wo: null }) };
      zugRef.current = z; setZug(z);
    };
    const los = async () => {
      removeEventListener("pointermove", zieh); removeEventListener("pointerup", los); removeEventListener("pointercancel", los);
      const z = zugRef.current; zugRef.current = null; setZug(null);
      if (!aktiv || !z || !z.wo) return;
      try {
        await api(`/aufgaben/${t.id}/verschieben`, { methode: "POST", daten: { ziel_id: z.ziel, wo: z.wo } });
        if (z.wo === "darunter") setZu((s) => { const n = new Set(s); n.delete(z.ziel); return n; });
        laden(); aktualisieren();
      } catch (x) { fehlerMelden(x); }
    };
    addEventListener("pointermove", zieh, { passive: false });
    addEventListener("pointerup", los); addEventListener("pointercancel", los);
  }

  const umklappen = (id) => setZu((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  return html`<section class="karte st">
    <div class="st-hinweis"><${Icon} n="liste" g=${13} /> Am Griff ziehen (Maus oder Finger): auf die <b>Mitte</b> einer Aufgabe = als Unteraufgabe ·
      an den <b>oberen oder unteren Rand</b> = davor oder danach · in die <b>freie Fläche</b> unten = oberste Ebene. Unteraufgaben wandern mit.</div>
    <div class="st-liste" ref=${liste}>
      ${zeilen.map(({ t, tiefe, kinder }) => {
        const erl = t.status === "erledigt";
        const hier = zug && zug.ziel === t.id ? " ziel-" + zug.wo : "";
        return html`<div class=${"st-zeile" + hier + (zug && zug.id === t.id ? " zieht" : "")} data-st-id=${t.id} key=${t.id} style=${`--tiefe:${tiefe}`}>
          <span class="st-griff" onPointerDown=${(e) => runter(e, t)} title="Ziehen zum Verschieben" aria-label=${"Verschieben: " + t.titel}><${Icon} n="griff" g=${14} /></span>
          ${kinder ? html`<button class=${"st-pfeil" + (zu.has(t.id) ? " zu" : "")} onClick=${() => umklappen(t.id)} aria-label=${zu.has(t.id) ? "Zweig aufklappen" : "Zweig zuklappen"}><${Icon} n="runter" g=${13} /></button>` : html`<span class="st-pfeil leer"></span>`}
          <button class=${"check" + (erl ? " an" : "")} onClick=${() => setzen(t.id, { status: erl ? "offen" : "erledigt" }, laden)} aria-label=${(erl ? "Wieder öffnen: " : "Erledigt: ") + t.titel}>
            ${erl ? html`<${Icon} n="check" g=${13} w=${3} />` : ""}</button>
          <span class=${"st-titel" + (erl ? " erledigt" : "")}>${t.titel}${zu.has(t.id) && kinder ? html` <span class="pill">+${kinder}</span>` : ""}</span>
          ${t.faellig && html`<span class="neben">${kurz(t.faellig)}</span>`}
        </div>`;
      })}
      <div class=${"st-frei" + (zug && zug.wo === "oben" ? " ziel-oben" : "")}>${zug ? "Hier loslassen: oberste Ebene" : ""}</div>
    </div>
    ${!zeilen.length && html`<${Leer} titel="Noch keine Aufgaben." />`}
    ${zug && zug.wo !== undefined && html`<div class="st-geist" style=${`left:${zug.x + 12}px;top:${zug.y + 8}px`}>${zug.titel}
      <small>${{ davor: "davor einsortieren", danach: "danach einsortieren", darunter: "als Unteraufgabe", oben: "oberste Ebene" }[zug.wo] || "…"}</small></div>`}
  </section>`;
}
