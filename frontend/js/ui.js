// Gemeinsame Bausteine. Preact + htm liegen als Datei im Repo (vendor/),
// werden vom eigenen Server ausgeliefert -- kein fremder Anbieter im Datenweg,
// kein Bauschritt. Preact aendert nur, was sich wirklich geaendert hat: damit
// verschwindet die Fehlerklasse "Eingabe/Scroll-Stellung nach dem Neuzeichnen
// weg", die im alten Cockpit ueber ein Dutzend Mal auftauchte.
import { html, render, useState, useEffect, useRef, useCallback, useMemo, useLayoutEffect } from "../vendor/preact-htm.js";
import { api } from "./api.js";

export { html, render, useState, useEffect, useRef, useCallback, useMemo, useLayoutEffect };

// ------------------------------------------------------------ Ereignisbus
const hoerer = {};
export const bus = {
  an(name, fn) { (hoerer[name] ||= new Set()).add(fn); return () => hoerer[name].delete(fn); },
  sende(name, daten) { (hoerer[name] || []).forEach((fn) => { try { fn(daten); } catch (e) { console.error(e); } }); },
};

// ------------------------------------------------------------ Symbole
const PFADE = {
  briefing: "M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
  inbox: "M4 13h4l2 3h4l2-3h4M4 13 6 5h12l2 8v6H4z",
  projects: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  team: "M9 11a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM3.5 20a5.5 5.5 0 0 1 11 0M17 11a2.5 2.5 0 1 0 0-5M15.5 14.5A4.5 4.5 0 0 1 21 19",
  system: "M4 5h16v10H4zM8 19h8M12 15v4",
  neo: "M4 6l6 6-6 6M12 18h8",
  talk: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7",
  plus: "M12 5v14M5 12h14",
  clip: "M21 11.5 12.6 20a5 5 0 0 1-7.1-7.1l8.5-8.5a3.3 3.3 0 0 1 4.7 4.7l-8.5 8.5a1.7 1.7 0 0 1-2.4-2.4l7.8-7.8",
  senden: "M5 12h14M13 6l6 6-6 6",
  stopp: "M7 7h10v10H7z",
  x: "M18 6 6 18M6 6l12 12",
  check: "M5 12.5l4.5 4.5L19 7",
  undo: "M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3",
  suche: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.3-4.3",
  links: "M15 18l-6-6 6-6",
  rechts: "M9 6l6 6-6 6",
  runter: "M6 9l6 6 6-6",
  voll: "M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3",
  klein: "M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3M16 21v-3a2 2 0 0 1 2-2h3",
  auge: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  neu: "M21 11.5a8.5 8.5 0 0 1-8.5 8.5c-1.5 0-3-.4-4.3-1.1L3 20l1.1-5.2A8.5 8.5 0 1 1 21 11.5zM12 8.5v6M9 11.5h6",
  sonne: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  mond: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  raus: "M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4M10 17l5-5-5-5M15 12H3",
  neu_laden: "M3 12a9 9 0 0 1 15-6.7M21 12a9 9 0 0 1-15 6.7M18 3v4h-4M6 21v-4h4",
  archiv: "M3 4h18v4H3zM5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4",
  stift: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  extern: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5",
  kopie: "M9 9h11v11H9zM5 15H4V4h11v1",
  welle: "M3 12h2l2-6 3 12 3-9 2 6 2-3h4",
  mehr: "M5 12h.01M12 12h.01M19 12h.01",
  play: "M7 5v14l11-7z",
  liste: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
};
export function Icon({ n, g = 18, w = 1.9 }) {
  return html`<svg class="ico" viewBox="0 0 24 24" width=${g} height=${g} fill="none" stroke="currentColor"
    stroke-width=${w} stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d=${PFADE[n] || ""} /></svg>`;
}

// ------------------------------------------------------------ Rollen
export const ROLLEN_FARBE = { pmo: "#2C6BB3", cockpit: "#0b8f3e", stratege: "#C07C12", buch: "#7C3AED", kritiker: "#E0392B",
  designer: "#D0458F", video: "#0E7490", du: "#1B3F6B", system: "#647388" };
export function Avatar({ wer, name, g = 28 }) {
  const n = (name || wer || "?").trim();
  return html`<span class="avatar" title=${n} style=${`background:${ROLLEN_FARBE[wer] || "#647388"};width:${g}px;height:${g}px;font-size:${Math.round(g * 0.4)}px`}>${n === "Du" ? "V" : n.slice(0, 1).toUpperCase()}</span>`;
}

// ------------------------------------------------------------ Zeit
export function zeitText(ts) {
  if (!ts) return "";
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "gerade eben";
  if (s < 3600) return `vor ${Math.floor(s / 60)} Min.`;
  if (s < 86400) return `vor ${Math.floor(s / 3600)} Std.`;
  if (s < 7 * 86400) return `vor ${Math.floor(s / 86400)} T.`;
  return new Date(ts * 1000).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "2-digit" });
}
export function datumText(s) {
  if (!s) return "";
  const d = new Date(s + (s.length <= 10 ? "T12:00:00" : ""));
  return isNaN(d) ? s : d.toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" });
}
export function dauer(sek) {
  sek = Math.max(0, Math.round(sek));
  return sek < 60 ? `${sek} s` : `${Math.floor(sek / 60)}:${String(sek % 60).padStart(2, "0")} Min.`;
}

// ------------------------------------------------------------ Meldungen
let toastId = 0;
export function toast(text, { fehler = false, aktion, dauer: d = 4500 } = {}) {
  bus.sende("toast", { id: ++toastId, text, fehler, aktion, dauer: fehler ? 8000 : d });
}
export function Toasts() {
  const [liste, setListe] = useState([]);
  useEffect(() => bus.an("toast", (t) => {
    setListe((l) => [...l, t]);
    setTimeout(() => setListe((l) => l.filter((x) => x.id !== t.id)), t.dauer);
  }), []);
  return html`<div class="toasts" role="status" aria-live="polite">${liste.map((t) => html`
    <div class=${"toast" + (t.fehler ? " fehler" : "")} key=${t.id}>
      <span>${t.text}</span>
      ${t.aktion && html`<button onClick=${() => { t.aktion.fn(); setListe((l) => l.filter((x) => x.id !== t.id)); }}>${t.aktion.text}</button>`}
    </div>`)}</div>`;
}
export function fehlerMelden(e) { toast(e && e.message ? e.message : String(e), { fehler: true }); }

// ------------------------------------------------------------ Modal
export function Modal({ titel, zu, children, fuss, breit }) {
  useEffect(() => {
    const k = (e) => { if (e.key === "Escape") zu(); };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [zu]);
  return html`<div class="modal-grund" onMouseDown=${(e) => { if (e.target === e.currentTarget) zu(); }}>
    <div class=${"modal" + (breit ? " breit" : "")} role="dialog" aria-modal="true" aria-label=${titel}>
      <div class="modal-kopf"><h2>${titel}</h2><button class="btn geist icon" onClick=${zu} title="Schließen (Esc)"><${Icon} n="x" /></button></div>
      <div class="modal-inhalt">${children}</div>
      ${fuss && html`<div class="modal-fuss">${fuss}</div>`}
    </div></div>`;
}

// ------------------------------------------------------------ Markdown
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function inline(s) {
  return s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|\s)(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
}
export function mdZuHtml(text) {
  // Erst ALLES escapen, dann formatieren: so kommt aus einer Modellantwort nie
  // ausfuehrbares HTML in die Oberflaeche. Links nur http/https.
  const zeilen = esc(text || "").split("\n");
  const out = [];
  let i = 0;
  while (i < zeilen.length) {
    const z = zeilen[i];
    const zaun = z.match(/^```(\w*)/);
    if (zaun) {
      const block = [];
      i++;
      while (i < zeilen.length && !/^```\s*$/.test(zeilen[i])) block.push(zeilen[i++]);
      i++;
      out.push(`<pre><code>${block.join("\n")}</code></pre>`);
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(z) && i + 1 < zeilen.length && /^\s*\|[\s:|-]+\|\s*$/.test(zeilen[i + 1])) {
      const kopf = z.trim().slice(1, -1).split("|").map((c) => `<th>${inline(c.trim())}</th>`).join("");
      i += 2;
      const reihen = [];
      while (i < zeilen.length && /^\s*\|.*\|\s*$/.test(zeilen[i])) {
        reihen.push("<tr>" + zeilen[i].trim().slice(1, -1).split("|").map((c) => `<td>${inline(c.trim())}</td>`).join("") + "</tr>");
        i++;
      }
      out.push(`<table><thead><tr>${kopf}</tr></thead><tbody>${reihen.join("")}</tbody></table>`);
      continue;
    }
    const h = z.match(/^(#{1,4})\s+(.*)/);
    if (h) { out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
    if (/^\s*[-*•]\s+/.test(z)) {
      const li = [];
      while (i < zeilen.length && /^\s*[-*•]\s+/.test(zeilen[i])) li.push(`<li>${inline(zeilen[i++].replace(/^\s*[-*•]\s+/, ""))}</li>`);
      out.push(`<ul>${li.join("")}</ul>`);
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(z)) {
      const li = [];
      while (i < zeilen.length && /^\s*\d+[.)]\s+/.test(zeilen[i])) li.push(`<li>${inline(zeilen[i++].replace(/^\s*\d+[.)]\s+/, ""))}</li>`);
      out.push(`<ol>${li.join("")}</ol>`);
      continue;
    }
    if (/^&gt;\s?/.test(z)) { out.push(`<blockquote>${inline(z.replace(/^&gt;\s?/, ""))}</blockquote>`); i++; continue; }
    if (!z.trim()) { i++; continue; }
    const absatz = [];
    while (i < zeilen.length && zeilen[i].trim() && !/^(#{1,4}\s|```|\s*[-*•]\s|\s*\d+[.)]\s|\s*\|)/.test(zeilen[i])) absatz.push(zeilen[i++]);
    if (!absatz.length) { absatz.push(zeilen[i++]); }
    out.push(`<p>${inline(absatz.join("<br>"))}</p>`);
  }
  return out.join("");
}
export function Md({ text, klasse = "" }) {
  return html`<div class=${"md " + klasse} dangerouslySetInnerHTML=${{ __html: mdZuHtml(text) }}></div>`;
}

// ------------------------------------------------------------ Daten holen
// Holt einmal und dann im Takt nach; lebt nur, solange die Ansicht steht.
export function useAbruf(pfad, takt = 0, abh = []) {
  const [daten, setDaten] = useState(null);
  const [fehler, setFehler] = useState(null);
  const lauf = useRef(0);
  const letzterPfad = useRef(null);
  const laden = useCallback(async () => {
    if (!pfad) return;
    const nr = ++lauf.current;
    try {
      const d = await api(pfad);
      if (nr === lauf.current) { setDaten(d); setFehler(null); }
    } catch (e) { if (nr === lauf.current) setFehler(e); }
  }, [pfad]);
  useEffect(() => {
    // Nur bei einem ANDEREN Pfad leeren -- ein geaenderter Takt soll nicht flackern.
    if (letzterPfad.current !== pfad) { setDaten(null); letzterPfad.current = pfad; }
    laden();
    const aus = bus.an("aktualisieren", laden);
    let t;
    if (takt) t = setInterval(() => { if (!document.hidden) laden(); }, takt);
    return () => { aus(); if (t) clearInterval(t); };
  }, [pfad, takt, ...abh]);
  return [daten, laden, fehler];
}

export function aktualisieren() { bus.sende("aktualisieren"); }

export function navigiere(ziel) { location.hash = ziel; }

export async function kopieren(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) {
    const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select();
    let ok = false; try { ok = document.execCommand("copy"); } catch (x) { /* nichts */ }
    t.remove(); return ok;
  }
}

export function Leer({ titel, children }) {
  return html`<div class="leer">${titel && html`<b>${titel}</b>`}${children}</div>`;
}

export function StandPill({ stand }) {
  const k = { neu: ["gelb", "neu"], eingeordnet: ["lila", "läuft"], wartet: ["gelb", "wartet auf dich"],
    in_arbeit: ["lila", "in Arbeit"], fertig: ["gruen", "fertig"], erledigt: ["", "erledigt"], verworfen: ["", "verworfen"] }[stand] || ["", stand];
  return html`<span class=${"pill " + k[0]}>${k[1]}</span>`;
}

export const ROLLEN_NAME = { pmo: "Jason", cockpit: "Neo", stratege: "Clayton", buch: "Neal", kritiker: "Daniel",
  designer: "Annie", video: "Ridley", du: "Du", system: "Cockpit" };
export const rolleName = (id) => ROLLEN_NAME[id] || id || "Stab";

export const ROLLEN_WAHL =[["stratege", "Clayton · Strategie, Konzepte"], ["buch", "Neal · Texte, Artikel, Bücher"],
  ["designer", "Annie · Gestaltung, Bild-Prompts"], ["video", "Ridley · Video, Storyboard"], ["pmo", "Jason · Planung, Überblick"]];
export const FORM_WAHL = [["text", "Text"], ["aufstellung", "Aufstellung / Liste"], ["konzept", "Konzept"],
  ["praesentation", "Präsentation"], ["webseite", "Webseite"]];
