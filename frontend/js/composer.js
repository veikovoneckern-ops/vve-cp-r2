// EIN Eingabefeld fuer alles: Talk, Neo, Erfassen, Antworten an den Stab.
// Ueberall gleich: Plus = anhaengen, Mikrofon = diktieren, Enter = senden,
// Umschalt+Enter = neue Zeile. Dazu Ziehen-und-Fallenlassen und Einfuegen.
import { html, useState, useRef, useEffect, Icon, toast } from "./ui.js";
import { hochladen } from "./api.js";
import { aufnehmen, erkennen, mikrofonGrund } from "./stimme.js";

function groesse(b) { return b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(b / 1024)) + " KB"; }

export function Composer({ platzhalter = "Schreib oder sprich …", beimSenden, laeuft = false, beimStoppen,
  erlaubeAnhang = true, erlaubeMic = true, projektId = "", autofokus = false, entwurfKey = "", zeilen = 1,
  hinweis = "Enter senden · Umschalt+Enter neue Zeile", sendenText = "Senden", feldRef }) {
  const [text, setText] = useState(() => { try { return entwurfKey ? sessionStorage.getItem("entwurf:" + entwurfKey) || "" : ""; } catch (e) { return ""; } });
  const [anh, setAnh] = useState([]);
  const [aufnahme, setAufnahme] = useState(null); // {start, ctl}
  const [erkenne, setErkenne] = useState(false);
  const [ziehen, setZiehen] = useState(false);
  const [jetzt, setJetzt] = useState(Date.now());
  const ta = useRef(null);
  const datei = useRef(null);
  if (feldRef) feldRef.current = { fokus: () => ta.current && ta.current.focus(), setzen: (t) => { setText(t); setTimeout(() => ta.current && ta.current.focus(), 0); } };

  useEffect(() => { if (autofokus && ta.current && matchMedia("(pointer:fine)").matches) ta.current.focus(); }, []);
  useEffect(() => { try { if (entwurfKey) sessionStorage.setItem("entwurf:" + entwurfKey, text); } catch (e) { /* egal */ } }, [text, entwurfKey]);
  useEffect(() => {
    const t = ta.current; if (!t) return;
    t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, window.innerHeight * 0.4) + "px";
  }, [text]);
  useEffect(() => {
    if (!aufnahme) return;
    const i = setInterval(() => setJetzt(Date.now()), 500);
    return () => clearInterval(i);
  }, [aufnahme]);

  function dateienDazu(liste) {
    // liste ist schon ein eigenes Array -- input.files ist eine LEBENDE Liste,
    // die beim Zuruecksetzen von .value leer wird (die teuerste Falle des alten Cockpits).
    for (const f of liste) {
      const id = Math.random().toString(36).slice(2);
      setAnh((a) => [...a, { id, name: f.name || "einfuegen.png", groesse: f.size, stand: "laedt", anteil: 0 }]);
      hochladen(f, { projekt_id: projektId, fortschritt: (p) => setAnh((a) => a.map((x) => x.id === id ? { ...x, anteil: p } : x)) })
        .then((d) => setAnh((a) => a.map((x) => x.id === id ? { ...x, stand: "fertig", server: d.id, hinweis: d.hinweis, zeichen: d.zeichen } : x)))
        .catch((e) => setAnh((a) => a.map((x) => x.id === id ? { ...x, stand: "fehler", hinweis: e.message } : x)));
    }
  }

  const bereit = anh.filter((a) => a.stand === "fertig");
  const laedt = anh.some((a) => a.stand === "laedt");
  const kannSenden = !laeuft && !laedt && !erkenne && (text.trim() || bereit.length);

  async function senden() {
    if (!kannSenden) return;
    const t = text.trim();
    const ids = bereit.map((a) => a.server);
    const ok = await beimSenden(t, ids, bereit.map((a) => a.name));
    if (ok !== false) { setText(""); setAnh([]); }
  }

  async function mikro() {
    if (aufnahme) {
      const blob = await aufnahme.ctl.stopp();
      setAufnahme(null);
      setErkenne(true);
      try {
        const d = await erkennen(blob);
        if (d.text) {
          setText((alt) => (alt && !alt.endsWith(" ") && !alt.endsWith("\n") ? alt + " " : alt) + d.text);
          setTimeout(() => ta.current && ta.current.focus(), 0);
        } else toast(d.hinweis || "Nichts verstanden.");
      } catch (e) { toast(e.message, { fehler: true }); }
      setErkenne(false);
      return;
    }
    const grund = mikrofonGrund();
    if (grund) { toast(grund, { fehler: true }); return; }
    try {
      const ctl = await aufnehmen();
      setAufnahme({ start: Date.now(), ctl });
    } catch (e) { toast(e.message, { fehler: true }); }
  }

  const sek = aufnahme ? Math.floor((jetzt - aufnahme.start) / 1000) : 0;
  let info = "";
  if (aufnahme) info = `Aufnahme läuft · ${Math.floor(sek / 60)}:${String(sek % 60).padStart(2, "0")} · zum Beenden tippen`;
  else if (erkenne) info = "Erkenne Sprache …";
  else if (laedt) info = "Lade hoch …";

  return html`<div class=${"composer" + (ziehen ? " ziehen" : "")}
      onDragOver=${(e) => { if (erlaubeAnhang && e.dataTransfer && [...e.dataTransfer.types].includes("Files")) { e.preventDefault(); setZiehen(true); } }}
      onDragLeave=${() => setZiehen(false)}
      onDrop=${(e) => { if (!erlaubeAnhang) return; e.preventDefault(); setZiehen(false); dateienDazu([...(e.dataTransfer.files || [])]); }}>
    ${anh.length > 0 && html`<div class="composer-chips">${anh.map((a) => html`
      <span class=${"chip" + (a.stand === "fehler" ? " fehler" : a.stand === "laedt" ? " laedt" : "")} key=${a.id}
        title=${a.hinweis || (a.zeichen ? `${a.zeichen} Zeichen gelesen` : a.name)}>
        <${Icon} n="clip" g=${13} />
        <span class="name">${a.name}</span>
        ${a.stand === "laedt" ? html`<span class="balken"><i style=${`width:${Math.round((a.anteil || 0) * 100)}%`}></i></span>`
          : html`<span class="leise">${a.stand === "fehler" ? "Fehler" : groesse(a.groesse)}</span>`}
        <button type="button" aria-label="Anhang entfernen" onClick=${() => setAnh((x) => x.filter((y) => y.id !== a.id))}><${Icon} n="x" g=${13} /></button>
      </span>`)}</div>`}
    <textarea ref=${ta} rows=${zeilen} value=${text} placeholder=${platzhalter} aria-label=${platzhalter}
      onInput=${(e) => setText(e.target.value)}
      onPaste=${(e) => { const f = [...(e.clipboardData?.files || [])]; if (erlaubeAnhang && f.length) { e.preventDefault(); dateienDazu(f); } }}
      onKeyDown=${(e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); senden(); } }}></textarea>
    <div class="composer-leiste">
      ${erlaubeAnhang && html`<button type="button" class="sym" title="Datei anhängen (PDF, Word, Excel, PowerPoint, Text, Bild)" aria-label="Datei anhängen"
        onClick=${() => datei.current.click()}><${Icon} n="plus" g=${19} /></button>
        <input ref=${datei} type="file" multiple hidden onChange=${(e) => { const l = [...e.target.files]; e.target.value = ""; dateienDazu(l); }} />`}
      ${erlaubeMic && html`<button type="button" class=${"sym" + (aufnahme ? " aufnahme" : erkenne ? " denkt" : "")}
        title=${aufnahme ? "Aufnahme beenden" : "Diktieren"} aria-label=${aufnahme ? "Aufnahme beenden" : "Diktieren"} aria-pressed=${!!aufnahme}
        onClick=${mikro} disabled=${erkenne}><${Icon} n=${aufnahme ? "stopp" : "mic"} g=${18} /></button>`}
      <span class="info">${info}</span>
      ${laeuft && beimStoppen
        ? html`<button type="button" class="senden stopp" title="Abbrechen" aria-label="Abbrechen" onClick=${beimStoppen}><${Icon} n="stopp" g=${16} /></button>`
        : html`<button type="button" class="senden" title=${sendenText + " (Enter)"} aria-label=${sendenText} disabled=${!kannSenden} onClick=${senden}><${Icon} n="senden" g=${18} w=${2.2} /></button>`}
    </div>
    ${hinweis && html`<div class="composer-hinweis">${hinweis}</div>`}
  </div>`;
}
