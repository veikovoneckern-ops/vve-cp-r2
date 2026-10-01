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
// Wie im alten Cockpit: das Projekt links als Wurzel, die Aufgaben rechts als
// Baum mit Verbindungslinien in der Projektfarbe. Ziehen am Knoten:
//   Mitte einer Aufgabe      = als Unteraufgabe anhaengen
//   oberer / unterer Rand    = davor / danach einsortieren
//   aufs Projekt oder frei   = oberste Ebene
// Ungueltige Ziele (der Knoten selbst oder einer seiner Nachfahren) werden schon
// beim Ziehen rot; der Server prueft trotzdem noch einmal.
// Dazu, was beim Strukturieren hilft: + am Knoten legt eine Unteraufgabe an,
// + am Projekt eine Aufgabe, Doppelklick benennt um, Termin direkt am Knoten,
// Fortschritt je Ast, alles auf- oder zuklappen.
const ST = { W: 300, H: 42, GAP: 10, EIN: 28, ROOT_W: 210, ROOT_H: 66, X: 300 };

export function Struktur({ projekt, aufgaben, laden }) {
  const [zu, setZu] = useState(() => new Set());
  const [zug, setZug] = useState(null);       // { id, titel, x, y, ziel, wo }
  const [neu, setNeu] = useState(null);       // id der Eltern-Aufgabe oder "wurzel"
  const [neuText, setNeuText] = useState("");
  const [umben, setUmben] = useState(null);   // { id, text }
  const zugRef = useRef(null);
  const flaeche = useRef(null);
  const sichtbar = aufgaben.filter((t) => !t.archiviert);
  const farbe = projekt.farbe || "var(--steel)";

  const kinderVon = {};
  sichtbar.forEach((t) => { if (t.eltern_id) (kinderVon[t.eltern_id] = kinderVon[t.eltern_id] || []).push(t); });
  const nachfahren = (id) => { const s = new Set(); const geh = (x) => (kinderVon[x] || []).forEach((k) => { s.add(k.id); geh(k.id); }); geh(id); return s; };
  const fortschritt = (id) => { const n = [...nachfahren(id)].map((k) => sichtbar.find((t) => t.id === k)); return [n.filter((t) => t && t.status === "erledigt").length, n.length]; };

  const zeilen = baum(sichtbar)(zu);
  const tiefe = zeilen.reduce((m, z) => Math.max(m, z.tiefe), 0);
  // Platz fuer das Eingabefeld "neue Unteraufgabe" direkt unter seinem Eltern-Knoten.
  const pos = {}; let y = 20;
  const reihen = [];
  zeilen.forEach((z) => {
    pos[z.t.id] = { x: ST.X + z.tiefe * ST.EIN, y };
    reihen.push({ ...z, x: pos[z.t.id].x, y });
    y += ST.H + ST.GAP;
    if (neu === z.t.id) y += ST.H + ST.GAP;
  });
  const neuWurzelY = y;
  if (neu === "wurzel") y += ST.H + ST.GAP;
  const hoehe = Math.max(y + 10, ST.ROOT_H + 60);
  const breite = ST.X + tiefe * ST.EIN + ST.W + 60;
  const rootY = Math.max(20, Math.min(hoehe / 2 - ST.ROOT_H / 2, 140));
  const rootMitte = rootY + ST.ROOT_H / 2;

  const linien = reihen.map((r) => {
    const my = r.y + ST.H / 2;
    if (!r.t.eltern_id || !pos[r.t.eltern_id]) {
      const sx = 20 + ST.ROOT_W, mx = sx + (r.x - sx) / 2;
      return html`<path d=${`M${sx} ${rootMitte} H${mx} V${my} H${r.x}`} />`;
    }
    const p = pos[r.t.eltern_id];
    return html`<path d=${`M${p.x + 14} ${p.y + ST.H} V${my} H${r.x}`} />`;
  });

  function zielFinden(x, y, eigene) {
    const el = document.elementFromPoint(x, y);
    if (!el || !flaeche.current || !flaeche.current.contains(el)) return null;
    const knoten = el.closest("[data-st-id]");
    if (knoten) {
      const id = knoten.dataset.stId;
      if (id === eigene || nachfahren(eigene).has(id)) return { ziel: id, wo: "ungueltig" };
      const b = knoten.getBoundingClientRect();
      const r = (y - b.top) / b.height;
      return { ziel: id, wo: r < 0.28 ? "davor" : r > 0.72 ? "danach" : "darunter" };
    }
    return { ziel: null, wo: "oben" };
  }

  function runter(e, t) {
    if (e.button !== undefined && e.button !== 0) return;
    if (e.target.closest("button,input,.st-termin")) return; // Knoepfe bleiben Knoepfe
    const start = { x: e.clientX, y: e.clientY };
    let aktiv = false;
    const zieh = (ev) => {
      if (!aktiv && Math.hypot(ev.clientX - start.x, ev.clientY - start.y) < 6) return; // Klick, kein Ziehen
      aktiv = true;
      ev.preventDefault();
      // Am Rand mitscrollen -- sonst laege das Ziel bei grossen Baeumen unerreichbar.
      const r = flaeche.current && flaeche.current.parentElement;
      if (r) {
        const b = r.getBoundingClientRect();
        if (ev.clientY > b.bottom - 40) r.scrollTop += 14; else if (ev.clientY < b.top + 40) r.scrollTop -= 14;
        if (ev.clientX > b.right - 40) r.scrollLeft += 14; else if (ev.clientX < b.left + 40) r.scrollLeft -= 14;
      }
      const z = { id: t.id, titel: t.titel, x: ev.clientX, y: ev.clientY, ...(zielFinden(ev.clientX, ev.clientY, t.id) || { ziel: undefined, wo: null }) };
      zugRef.current = z; setZug(z);
    };
    const los = async () => {
      removeEventListener("pointermove", zieh); removeEventListener("pointerup", los); removeEventListener("pointercancel", los);
      const z = zugRef.current; zugRef.current = null; setZug(null);
      if (!aktiv || !z || !z.wo || z.wo === "ungueltig") return;
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
  const allesZu = () => setZu(new Set(Object.keys(kinderVon)));
  async function anlegen() {
    const titel = neuText.trim();
    if (!titel) { setNeu(null); return; }
    try {
      await api("/aufgaben", { methode: "POST", daten: { titel, projekt_id: projekt.id, eltern_id: neu === "wurzel" ? null : neu } });
      if (neu !== "wurzel") setZu((s) => { const n = new Set(s); n.delete(neu); return n; });
      setNeuText(""); laden(); aktualisieren();
    } catch (x) { fehlerMelden(x); }
  }
  async function umbenennen() {
    const u = umben; setUmben(null);
    const t = sichtbar.find((x) => x.id === u.id);
    if (u.text.trim() && t && u.text.trim() !== t.titel) await setzen(u.id, { titel: u.text.trim() }, laden);
  }
  const neuFeld = (x, y) => html`<div class="st-neu" style=${`left:${x}px;top:${y}px;width:${ST.W}px;height:${ST.H}px`}>
    <input autofocus value=${neuText} placeholder=${neu === "wurzel" ? "Neue Aufgabe … (Enter)" : "Neue Unteraufgabe … (Enter)"}
      onInput=${(e) => setNeuText(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter") anlegen(); if (e.key === "Escape") { setNeu(null); setNeuText(""); } }}
      onBlur=${() => { if (!neuText.trim()) setNeu(null); }} aria-label="Titel der neuen Aufgabe" /></div>`;

  const offen = sichtbar.filter((t) => t.status !== "erledigt").length;
  const hz = heute();

  return html`<section class="karte st">
    <div class="st-kopf">
      <div class="st-hinweis"><${Icon} n="griff" g=${13} /> <b>Ziehen</b> (Maus und Finger): auf die <b>Mitte</b> einer Aufgabe = als Unteraufgabe ·
        an den <b>oberen oder unteren Rand</b> = davor oder danach · aufs <b>Projekt</b> oder in die <b>freie Fläche</b> = oberste Ebene.
        Unteraufgaben wandern mit; was nicht geht, wird rot.</div>
      <div class="knopfreihe">
        <button class="btn klein geist" onClick=${() => setZu(new Set())} title="Alle Zweige aufklappen">Alles auf</button>
        <button class="btn klein geist" onClick=${allesZu} title="Alle Zweige zuklappen">Alles zu</button>
      </div>
    </div>
    <div class="st-rahmen">
      <div class=${"st-flaeche" + (zug && zug.wo === "oben" ? " ziel-oben" : "")} ref=${flaeche} style=${`width:${breite}px;height:${hoehe}px`}>
        <svg class="st-linien" width=${breite} height=${hoehe} style=${`--st-farbe:${farbe}`} aria-hidden="true">${linien}</svg>
        <div class="st-wurzel" data-st-wurzel="1" style=${`left:20px;top:${rootY}px;width:${ST.ROOT_W}px;height:${ST.ROOT_H}px;--st-farbe:${farbe}`}>
          <b>${projekt.name}</b><span>${offen} offen · ${sichtbar.length - offen} erledigt</span>
          <button class="st-akt" onClick=${() => { setNeu("wurzel"); setNeuText(""); }} title="Neue Aufgabe" aria-label="Neue Aufgabe"><${Icon} n="plus" g=${13} /></button>
        </div>
        ${reihen.map(({ t, x, y, kinder }) => {
          const erl = t.status === "erledigt";
          const ueber = !erl && t.faellig && zuDatum(t.faellig) < hz;
          const [f, n] = kinder ? fortschritt(t.id) : [0, 0];
          const ziel = zug && zug.ziel === t.id ? " ziel-" + zug.wo : "";
          return html`<div key=${t.id} data-st-id=${t.id} onPointerDown=${(e) => runter(e, t)}
              class=${"st-knoten" + (erl ? " erledigt" : "") + (ueber ? " ueber" : "") + ziel + (zug && zug.id === t.id ? " zieht" : "")}
              style=${`left:${x}px;top:${y}px;width:${ST.W}px;height:${ST.H}px;--st-farbe:${farbe}`}
              >
            ${kinder ? html`<button class=${"st-zweig" + (zu.has(t.id) ? " zu" : "")} onClick=${() => umklappen(t.id)}
              title=${zu.has(t.id) ? `Zweig aufklappen (${kinder})` : "Zweig zuklappen"} aria-label=${zu.has(t.id) ? "Zweig aufklappen" : "Zweig zuklappen"}><${Icon} n="runter" g=${11} w=${2.4} /></button>` : ""}
            <button class=${"st-ck" + (erl ? " an" : "")} onClick=${() => setzen(t.id, { status: erl ? "offen" : "erledigt" }, laden)}
              title=${erl ? "Wieder öffnen" : "Als erledigt markieren"} aria-label=${(erl ? "Wieder öffnen: " : "Erledigt: ") + t.titel}>${erl ? html`<${Icon} n="check" g=${10} w=${3} />` : ""}</button>
            ${umben && umben.id === t.id
              ? html`<input class="st-umben" autofocus value=${umben.text} onInput=${(e) => setUmben({ id: t.id, text: e.target.value })}
                  onKeyDown=${(e) => { if (e.key === "Enter") umbenennen(); if (e.key === "Escape") setUmben(null); }} onBlur=${umbenennen} aria-label="Neuer Titel" />`
              : html`<span class="st-tt" onDblClick=${() => setUmben({ id: t.id, text: t.titel })}>${t.titel}</span>`}
            ${kinder ? html`<span class=${"st-zahl" + (f === n ? " fertig" : "")} title=${`${f} von ${n} Unteraufgaben erledigt`}>${f}/${n}</span>` : ""}
            <label class=${"st-termin" + (t.faellig ? "" : " leer")} title=${t.faellig ? "Fällig am " + kurz(t.faellig) + " · ändern" : "Termin setzen"}>
              ${t.faellig ? kurz(t.faellig) : html`<${Icon} n="kalender" g=${12} />`}
              <input type="date" value=${t.faellig || ""} onChange=${(e) => setzen(t.id, { faellig: e.target.value }, laden)} aria-label=${"Fällig: " + t.titel} /></label>
            <span class="st-akte">
              <button class="st-akt" onClick=${() => { setNeu(t.id); setNeuText(""); }} title="Unteraufgabe anlegen" aria-label="Unteraufgabe anlegen"><${Icon} n="plus" g=${12} /></button>
              <button class="st-akt" onClick=${() => setUmben({ id: t.id, text: t.titel })} title="Umbenennen" aria-label="Umbenennen"><${Icon} n="stift" g=${12} /></button>
              <button class="st-akt" onClick=${async () => { try { await api("/aufgaben/" + t.id, { methode: "DELETE" }); laden(); aktualisieren(); } catch (x) { fehlerMelden(x); } }}
                title="Archivieren (lässt sich zurückholen)" aria-label="Archivieren"><${Icon} n="archiv" g=${12} /></button>
            </span>
          </div>`;
        })}
        ${neu && neu !== "wurzel" && pos[neu] && neuFeld(pos[neu].x + ST.EIN, pos[neu].y + ST.H + ST.GAP)}
        ${neu === "wurzel" && neuFeld(ST.X, neuWurzelY)}
        ${!reihen.length && neu !== "wurzel" && html`<div class="st-leer" style=${`left:${ST.X}px;top:${rootY + 12}px`}>Noch keine Aufgaben. Mit + am Projekt anlegen.</div>`}
      </div>
    </div>
    ${zug && zug.wo !== undefined && html`<div class=${"st-geist" + (zug.wo === "ungueltig" ? " ungueltig" : "")} style=${`left:${zug.x + 12}px;top:${zug.y + 8}px`}>${zug.titel}
      <small>${{ davor: "davor einsortieren", danach: "danach einsortieren", darunter: "als Unteraufgabe", oben: "oberste Ebene", ungueltig: "geht nicht: unter sich selbst" }[zug.wo] || "…"}</small></div>`}
  </section>`;
}
