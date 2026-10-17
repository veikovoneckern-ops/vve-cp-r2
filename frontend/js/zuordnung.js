// ZUORDNUNG -- ein Gespraech einem Projekt und einer Aufgabe zuordnen (Veiko,
// 17.10.2026: "einzelne Chats Projekten und Aufgaben zuordnen koennen, damit mein
// Setup gut funktioniert"). Sitzt im Kopf jedes Chatfensters (Talk, Team-Chat,
// Neo, Board). Gespeichert wird am Gespraech (gespraech.zuordnen); das Modell
// bekommt Projekt und Aufgabe danach bei jeder Antwort mit, und die Projektseite
// listet das Gespraech.
//
// Ohne Gespraech (noch keine Nachricht) gibt es nichts zuzuordnen -- der Knopf
// steht dann ausgegraut da, statt eine Zuordnung zu versprechen, die verloren ginge.
import { html, useState, useEffect, useRef, Icon, toast, fehlerMelden, useEsc, navigiere } from "./ui.js";
import { api } from "./api.js";

let projekteCache = null;

export function Zuordnung({ gid, klein = false }) {
  const [z, setZ] = useState(null);
  const [auf, setAuf] = useState(false);
  const [projekte, setProjekte] = useState(projekteCache || []);
  const [aufgaben, setAufgaben] = useState([]);
  const [pid, setPid] = useState("");
  const [aid, setAid] = useState("");
  const kasten = useRef(null);
  useEsc(() => setAuf(false), auf);

  useEffect(() => {
    setZ(null);
    if (!gid) return;
    api(`/gespraeche/${gid}/zuordnung`).then(setZ).catch(() => setZ(null));
  }, [gid]);
  useEffect(() => {
    if (!auf) return undefined;
    setPid((z && z.projekt_id) || ""); setAid((z && z.aufgabe_id) || "");
    if (!projekteCache) api("/projekte").then((d) => { projekteCache = (d.projekte || []).filter((p) => p.status !== "archiviert"); setProjekte(projekteCache); }).catch(() => {});
    const weg = (e) => { if (kasten.current && !kasten.current.contains(e.target)) setAuf(false); };
    setTimeout(() => document.addEventListener("mousedown", weg), 0);
    return () => document.removeEventListener("mousedown", weg);
  }, [auf]);
  useEffect(() => {
    if (!pid) { setAufgaben([]); return; }
    api("/aufgaben?projekt=" + encodeURIComponent(pid) + "&status=offen").then((d) => setAufgaben(d.aufgaben || [])).catch(() => setAufgaben([]));
  }, [pid]);

  async function speichern(p, a) {
    try {
      const r = await api(`/gespraeche/${gid}/zuordnung`, { methode: "PATCH", daten: { projekt_id: p || null, aufgabe_id: a || null } });
      setZ(r); setAuf(false);
      toast(r.projekt_name ? `Zugeordnet: ${r.projekt_name}${r.aufgabe_titel ? " · " + r.aufgabe_titel : ""}. Gilt ab der nächsten Antwort.` : "Zuordnung gelöst.");
    } catch (e) { fehlerMelden(e); }
  }

  const text = z && z.projekt_name ? z.projekt_name + (z.aufgabe_titel ? " · " + z.aufgabe_titel : "") : "Zuordnen";
  return html`<span class="zu-wrap" ref=${kasten}>
    <button class=${"btn klein zu-knopf" + (z && z.projekt_id ? " an" : "") + (klein ? " geist" : "")} disabled=${!gid}
      onClick=${() => setAuf(!auf)} title=${gid ? (z && z.projekt_id ? "Zugeordnet: " + text + " -- ändern" : "Diesem Gespräch ein Projekt und eine Aufgabe geben") : "Erst nach der ersten Nachricht"}>
      <${Icon} n="projects" g=${13} /><span class="zu-text">${text}</span></button>
    ${auf && html`<div class="zu-pop" role="dialog" aria-label="Gespräch zuordnen">
      <label>Projekt<select class="eingabe" value=${pid} onChange=${(e) => { setPid(e.target.value); setAid(""); }}>
        <option value="">— kein Projekt —</option>${projekte.map((p) => html`<option value=${p.id}>${p.name}</option>`)}</select></label>
      <label>Aufgabe<select class="eingabe" value=${aid} disabled=${!pid} onChange=${(e) => setAid(e.target.value)}>
        <option value="">— keine bestimmte —</option>${aufgaben.map((a) => html`<option value=${a.id}>${a.titel}</option>`)}</select></label>
      <p class="leise klein">Das Modell bekommt Projekt und Aufgabe ab jetzt bei jeder Antwort mit; die Projektseite zeigt das Gespräch.</p>
      <div class="knopfreihe">
        <button class="btn klein primaer" onClick=${() => speichern(pid, aid)}>Speichern</button>
        ${z && z.projekt_id && html`<button class="btn klein" onClick=${() => speichern(null, null)}>Lösen</button>`}
        ${z && z.projekt_id && html`<button class="btn klein geist" onClick=${() => { setAuf(false); navigiere("/projects/" + z.projekt_id); }}>Zum Projekt</button>`}
      </div></div>`}
  </span>`;
}

// Ein zugeordnetes Gespraech wieder oeffnen -- je nach Art an seinem Ort.
export function gespraechOeffnen(g, bus) {
  if (g.art === "team" && g.wer) navigiere(`/team/chat/${g.wer}/${g.id}`);
  else if (g.art === "neo") navigiere("/neo/" + g.id);
  else if (g.art === "board") navigiere("/board/" + g.id);
  else if (g.art === "talk") bus.sende("talk-oeffnen", { gid: g.id });
}
