// DIE LINKE LEISTE -- Knoepfe umsortieren und als eigenes Fenster abloesen.
//
// Ziehen ueber Pointer Events, nie ueber natives HTML5-Drag: das ist im alten
// Cockpit an <a>/<button> dreimal am echten Browser gescheitert (der Browser
// entscheidet selbst, ob er eine Drag-Sitzung beginnt). Hier gibt es keinen
// verborgenen Browsermodus -- nur pointerdown/move/up und eigener Code.
//
// Zwei Gesten, ein Griff:
//   - ziehen und innerhalb der Leiste loslassen  -> neue Reihenfolge
//   - ganz nach oben an den Fensterrand ziehen    -> die Seite oeffnet sich
//     in einem eigenen Browserfenster (?fenster=1), ohne Leiste
// Die Reihenfolge liegt auf dem Server (/einstellungen, "leiste"), damit sie
// auf jedem Geraet gleich ist.
import { html, useState, useEffect, useRef, Icon, toast, fehlerMelden } from "./ui.js";
import { api } from "./api.js";

// Eigenes Fenster: dieselbe Seite, nur der Inhalt.
export const FENSTER = new URLSearchParams(location.search).has("fenster");

const SCHWELLE = 6;      // Punkt Bewegung, ab der aus einem Klick ein Ziehen wird
const OBEN = 48;         // so nah am oberen Rand gilt "abloesen"

export function fensterOeffnen(b) {
  const w = window.open(location.pathname + "?fenster=1#/" + b.id, "vvec-" + b.id,
    "popup,width=" + Math.min(1280, screen.availWidth - 80) + ",height=" + Math.min(900, screen.availHeight - 80));
  if (!w) toast("Der Browser hat das Fenster blockiert. Pop-ups für das Cockpit erlauben.");
  else w.focus();
}

// Gespeicherte Reihenfolge auf die bekannten Bereiche anwenden: Unbekanntes
// faellt heraus, Neues (nach einem Update) haengt hinten an.
export function ordnen(bereiche, ids) {
  const nachId = new Map(bereiche.map((b) => [b.id, b]));
  const vorn = (ids || []).filter((id) => nachId.has(id)).map((id) => nachId.get(id));
  return [...vorn, ...bereiche.filter((b) => !vorn.includes(b))];
}

export function useLeiste(bereiche, angemeldet) {
  // Der Server ist die Wahrheit; die letzte bekannte Reihenfolge liegt nur
  // als Spiegel im Geraet, damit die Leiste beim Laden nicht erst in der
  // Grundordnung erscheint und dann umspringt.
  const merken = (x) => { try { localStorage.setItem("vvec_leiste", JSON.stringify(x)); } catch (f) { /* egal */ } };
  const [ids, setIds] = useState(() => { try { return JSON.parse(localStorage.getItem("vvec_leiste") || "null"); } catch (f) { return null; } });
  useEffect(() => {
    if (angemeldet) api("/einstellungen").then((e) => { setIds(e.leiste || []); merken(e.leiste || []); }).catch(() => {});
  }, [angemeldet]);
  async function speichern(neu) {
    const vorher = ids;
    setIds(neu);
    merken(neu);
    try { await api("/einstellungen", { methode: "POST", daten: { leiste: neu } }); }
    catch (e) { setIds(vorher); merken(vorher || []); fehlerMelden(e); }
  }
  return [ordnen(bereiche, ids), speichern];
}

export function LeisteNav({ liste, aktiv, zahl, speichern }) {
  const [zug, setZugZustand] = useState(null);   // { id, ordnung, oben } -- fuers Zeichnen
  // Dasselbe als Ref fuer die Ereignisse: kommen letzte Bewegung und Loslassen
  // schneller, als neu gezeichnet wird, saehe hoch() sonst einen veralteten
  // Stand (null) und taete nichts -- das Abloesen ging so beim Pruefen verloren.
  const zugRef = useRef(null);
  const setZug = (z) => { zugRef.current = z; setZugZustand(z); };
  const start = useRef(null);
  const geradeGezogen = useRef(false);
  const nav = useRef(null);
  const lauscher = useRef(null);

  function runter(e, b) {
    // Nur Maus und Stift: auf einem Tablet ist Wischen in der Leiste Scrollen.
    if (e.button !== 0 || e.pointerType === "touch") return;
    start.current = { id: b.id, x: e.clientX, y: e.clientY, pid: e.pointerId };
    // Am FENSTER zuhoeren, nicht an der Knopfspalte: bei einer schnellen
    // Bewegung kommt schon das erste pointermove neben der Spalte an (beim
    // Pruefen: ueber der Leiste, dann ueber der Kopfzeile), und der Zug ging
    // verloren, bevor er begann.
    // Genau diese Funktionen merken: nach einem Neuzeichnen gaebe es neue mit
    // gleichem Namen, und removeEventListener traefe die alten nicht.
    lauscher.current = [["pointermove", bewegen], ["pointerup", hoch], ["pointercancel", abbrechen]];
    lauscher.current.forEach(([t, f]) => addEventListener(t, f));
  }
  function loesen() {
    (lauscher.current || []).forEach(([t, f]) => removeEventListener(t, f));
    lauscher.current = null;
  }
  function abbrechen() { loesen(); start.current = null; setZug(null); }
  function bewegen(e) {
    const s = start.current;
    if (!s) return;
    const zz = zugRef.current;
    if (!zz) {
      if (Math.abs(e.clientX - s.x) < SCHWELLE && Math.abs(e.clientY - s.y) < SCHWELLE) return;
      // Am LEISTENKASTEN festhalten, nicht am Knopf: der Knopf wird beim
      // Umsortieren im DOM verschoben, und ein verschobenes Element verliert
      // die Bindung -- dann kaemen keine Bewegungen mehr an. Die Bindung sorgt
      // auch dafuer, dass das Loslassen ankommt, wenn der Zeiger ueber den
      // oberen Fensterrand hinaus gezogen wurde.
      try { nav.current.setPointerCapture(s.pid); } catch (x) { /* egal */ }
    }
    const ordnung = (zz ? zz.ordnung : liste.map((b) => b.id)).filter((id) => id !== s.id);
    // Einfuegestelle aus der Hoehe: vor dem ersten Knopf, dessen Mitte unter dem Zeiger liegt.
    const knoepfe = [...nav.current.querySelectorAll("a[data-id]")].filter((a) => a.dataset.id !== s.id);
    let i = knoepfe.findIndex((a) => { const r = a.getBoundingClientRect(); return e.clientY < r.top + r.height / 2; });
    if (i < 0) i = knoepfe.length;
    const vorId = knoepfe[i] && knoepfe[i].dataset.id;
    const pos = vorId ? ordnung.indexOf(vorId) : ordnung.length;
    ordnung.splice(pos, 0, s.id);
    setZug({ id: s.id, ordnung, oben: e.clientY < OBEN });
  }
  function hoch() {
    loesen();
    const s = start.current;
    start.current = null;
    const z = zugRef.current;
    if (!s || !z) return;
    geradeGezogen.current = true;
    // Der Nachklick kommt sofort nach dem Loslassen -- oder gar nicht, wenn
    // Start und Ende auf verschiedenen Knoepfen lagen (dann trifft er die
    // Leiste). Die Sperre darf deshalb nicht auf ihn warten, sonst schluckt
    // sie den naechsten echten Klick.
    setTimeout(() => { geradeGezogen.current = false; }, 0);
    setZug(null);
    if (z.oben) { fensterOeffnen(liste.find((b) => b.id === z.id)); return; }
    if (z.ordnung.join() !== liste.map((b) => b.id).join()) speichern(z.ordnung);
  }
  // Der Browser schickt nach einem Ziehen trotzdem noch einen Klick -- genau
  // den einen fangen, sonst navigiert ein Umsortieren nebenbei.
  function klick(e) { if (geradeGezogen.current) e.preventDefault(); }

  useEffect(() => {
    const esc = (e) => { if (e.key === "Escape" && start.current) abbrechen(); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, []);

  const sicht = zug ? zug.ordnung.map((id) => liste.find((b) => b.id === id)) : liste;
  const gezogen = zug && liste.find((b) => b.id === zug.id);
  return html`<div class="nav" ref=${nav}>
    ${sicht.map((b) => html`<a key=${b.id} data-id=${b.id} href=${"#/" + b.id}
        class=${(aktiv === b.id ? "an " : "") + (b.neo ? "neo-nav " : "") + (zug && zug.id === b.id ? "zieht" + (zug.oben ? " abloesen" : "") : "")}
        onPointerDown=${(e) => runter(e, b)} onClick=${klick} draggable="false"
        title=${b.titel + " · ziehen zum Umsortieren, nach oben an den Rand ziehen für ein eigenes Fenster"}>
      <${Icon} n=${b.icon} />${b.titel}${zahl(b)}</a>`)}
    ${gezogen && html`<div class=${"leiste-oben" + (zug.oben ? " an" : "")} aria-live="polite">
      <${Icon} n="extern" g=${15} />${zug.oben ? `Loslassen: „${gezogen.titel}“ im eigenen Fenster` : "Hierher ziehen für ein eigenes Fenster"}</div>`}
  </div>`;
}
