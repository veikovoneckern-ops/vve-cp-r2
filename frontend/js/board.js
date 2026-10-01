// ADVISORY BOARD -- Veikos Runde von Advisors (aus dem alten Cockpit uebernommen,
// dort "Advisory Board"). Links der Tisch: wer sitzt, wer nicht, mit Profil.
// Rechts das Gespraech: die Antwort wird je Advisor in eine eigene Sprechblase
// geteilt (die Advisors nennen sich fett am Absatzanfang) -- lesbarer als ein
// langer Block. Einzelgespraech mit einer Person, optionaler Projektbezug,
// Gespraeche bleiben gespeichert.
import { html, useState, useEffect, useRef, Icon, Md, Modal, Leer, toast, fehlerMelden, navigiere, zeitText, bus } from "./ui.js";
import { api, strom } from "./api.js";
import { Composer } from "./composer.js";

const GRUPPEN_FARBE = { c1: "#2C6BB3", c2: "#C07C12", c3: "#0E7490", c4: "#B4322A", c5: "#7C3AED" };
const initialen = (n) => n.split(/\s+/).filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase();
const farbe = (p) => GRUPPEN_FARBE[(p.clusters || [])[0]] || "#647388";

const START = [
  ["Challenge meinen Plan", "Ich stelle euch einen Plan vor. Challenged ihn ehrlich: Was hält nicht, was fehlt, was würdet ihr anders machen? Mein Plan: "],
  ["Was übersehe ich?", "Ich stehe vor dieser Entscheidung und habe das Gefühl, etwas zu übersehen. Was seht ihr, was ich nicht sehe? Es geht um: "],
  ["Pro und Contra", "Gebt mir die stärksten Argumente dafür und dagegen, jeweils aus eurer Sicht: "],
  ["Entscheidungshilfe", "Ich muss mich zwischen diesen Optionen entscheiden. Wozu ratet ihr, und warum? Optionen: "],
];

function Avatar({ p, g = 34 }) {
  return html`<span class="bd-ava" style=${`width:${g}px;height:${g}px;font-size:${Math.round(g * 0.36)}px;background:${farbe(p)}`} aria-hidden="true">${initialen(p.name)}</span>`;
}

// Antwort in Beitraege je Advisor teilen: "**Name**" am Zeilenanfang beginnt einen Beitrag.
function teilen(text, personen) {
  const re = /^\s*\*\*([^*\n]{2,60})\*\*\s*[:–—-]?\s*/gm;
  const stuecke = [];
  let m, letzte = 0, wer = null;
  while ((m = re.exec(text))) {
    const vor = text.slice(letzte, m.index).trim();
    if (vor || wer) stuecke.push({ wer, text: vor });
    const name = m[1].trim().toLowerCase();
    wer = personen.find((p) => p.name.toLowerCase() === name || name.includes(p.name.split(" ").pop().toLowerCase())) || { name: m[1].trim() };
    letzte = re.lastIndex;
  }
  stuecke.push({ wer, text: text.slice(letzte).trim() });
  return stuecke.filter((s) => s.text);
}

function Beitraege({ text, personen, einzel }) {
  const st = einzel ? [{ wer: einzel, text }] : teilen(text, personen);
  return st.map((s, i) => html`<div class="bd-beitrag" key=${i}>
    ${s.wer ? html`<${Avatar} p=${s.wer} g=${32} />` : html`<span class="bd-ava board" aria-hidden="true"><${Icon} n="team" g=${16} /></span>`}
    <div class="bd-blase"><b>${s.wer ? s.wer.name : "Advisory Board"}</b><${Md} text=${s.text} /></div>
  </div>`);
}

function Profil({ p, amTisch, umschalten, einzeln, zu }) {
  return html`<${Modal} titel=${p.name} zu=${zu} breit=${true}>
    <div class="bd-profil-kopf"><${Avatar} p=${p} g=${52} />
      <div><div class="leise klein">${p.gruppen.join(" · ")}</div><p style="margin:4px 0 0">${p.bio}</p></div></div>
    <div class="raster-gleich zwei" style="margin-top:14px">
      <section class="karte"><div class="karte-kopf"><h3>Prinzipien</h3></div><ul class="bd-liste">${p.principles.map((x) => html`<li>${x}</li>`)}</ul></section>
      <section class="karte"><div class="karte-kopf"><h3>Typische Fragen</h3></div><ul class="bd-liste">${p.challenges.map((x) => html`<li>${x}</li>`)}</ul></section>
      <section class="karte"><div class="karte-kopf"><h3>Stärken</h3></div><p>${p.strengths}</p></section>
      <section class="karte"><div class="karte-kopf"><h3>Blinde Flecken</h3></div><p>${p.blind}</p></section>
    </div>
    <section class="karte" style="margin-top:12px"><div class="karte-kopf"><h3>Aktueller Stand</h3>
        <span class="leise klein">${p.aktualisiert ? "aufgefrischt " + zeitText(p.aktualisiert) : "noch nicht aufgefrischt"}</span></div>
      ${p.aktuell ? html`<p>${p.aktuell}</p>` : html`<p class="leise">Kein öffentlicher Stand gefunden. Das Board arbeitet dann nur mit dem Profil.</p>`}
      ${p.quellen.length > 0 && html`<div class="bd-quellen">${p.quellen.map((q) => html`<a href=${q.adresse} target="_blank" rel="noopener">${q.titel}</a>`)}</div>`}
    </section>
    <div class="knopfreihe" style="margin-top:14px">
      <button class=${"btn" + (amTisch ? "" : " primaer")} onClick=${umschalten}>${amTisch ? "Vom Tisch nehmen" : "An den Tisch holen"}</button>
      <button class="btn" onClick=${() => { einzeln(); zu(); }}><${Icon} n="talk" g=${14} />Einzelgespräch</button>
    </div>
  <//>`;
}

export function Board({ id }) {
  const [d, setD] = useState(null);
  const [gruppe, setGruppe] = useState("");
  const [profil, setProfil] = useState(null);
  const [msgs, setMsgs] = useState([]);
  const [lauf, setLauf] = useState(null);
  const [einzel, setEinzel] = useState(null);   // id einer Person oder null = Runde
  const [projekt, setProjekt] = useState("");
  const [projekte, setProjekte] = useState([]);
  const feld = useRef(null);
  const verlauf = useRef(null);
  const abbruch = useRef(null);

  const laden = () => api("/board").then(setD).catch(fehlerMelden);
  useEffect(() => { laden(); api("/projekte").then((x) => setProjekte(x.projekte)).catch(() => {}); bus.sende("talk-kontext", null); }, []);
  useEffect(() => {
    if (!id) { setMsgs([]); return; }
    api("/board/gespraech/" + id).then((x) => {
      setMsgs(x.nachrichten.map((m) => ({ id: m.id, rolle: m.rolle, text: m.text, mit: (m.daten || {}).mit })));
      const k = x.gespraech.kontext || {};
      setProjekt(k.projekt_id || "");
      const letzte = [...x.nachrichten].reverse().find((m) => (m.daten || {}).mit);
      setEinzel(letzte && letzte.daten.mit.length === 1 ? letzte.daten.mit[0] : null);
    }).catch(() => navigiere("/board"));
  }, [id]);
  useEffect(() => { const v = verlauf.current; if (v) v.scrollTop = v.scrollHeight; }, [msgs, lauf]);

  if (!d) return html`<div class="seite"><div class="lade">Lade Advisory Board …</div></div>`;
  const nach = Object.fromEntries(d.personen.map((p) => [p.id, p]));
  const tisch = new Set(d.tisch);
  const sichtbar = d.personen.filter((p) => !gruppe || p.clusters.includes(gruppe));
  const einzelP = einzel ? nach[einzel] : null;

  async function tischSetzen(ids) {
    setD((x) => ({ ...x, tisch: ids }));
    try { await api("/board/tisch", { methode: "POST", daten: { ids } }); } catch (e) { fehlerMelden(e); laden(); }
  }
  const umschalten = (pid) => tischSetzen(tisch.has(pid) ? d.tisch.filter((x) => x !== pid) : [...d.tisch, pid]);

  async function senden(text) {
    if (lauf) return false;
    const mit = einzel ? [einzel] : null;
    if (!einzel && !d.tisch.length) { toast("Am Tisch sitzt niemand. Hol links jemanden dazu.", { fehler: true }); return false; }
    setMsgs((m) => [...m, { id: "d" + Date.now(), rolle: "du", text }]);
    setLauf({ text: "", mit: mit || d.tisch });
    const ctl = new AbortController(); abbruch.current = ctl;
    let gid = id, fertig = null, fehler = null;
    bus.sende("ki-start");
    try {
      await strom("/board/senden", { gespraech_id: id || null, text, mit, projekt_id: projekt || null }, (e) => {
        if (e.typ === "start") gid = e.gespraech_id;
        else if (e.typ === "text") setLauf((l) => l && { ...l, text: l.text + e.t });
        else if (e.typ === "fertig") fertig = e;
        else if (e.typ === "fehler") fehler = e.text;
      }, ctl.signal);
      if (fehler) throw new Error(fehler);
    } catch (e) { if (e.name !== "AbortError") fehlerMelden(e); }
    setLauf(null);
    if (fertig) setMsgs((m) => [...m, { id: fertig.nachricht_id, rolle: "board", text: fertig.text, mit: mit || d.tisch }]);
    if (gid && gid !== id) { navigiere("/board/" + gid); laden(); }
    return true;
  }

  const gespraechWeg = async () => {
    if (!id) return;
    try { await api("/board/gespraech/" + id, { methode: "DELETE" }); toast("Aus der Liste genommen."); navigiere("/board"); laden(); } catch (e) { fehlerMelden(e); }
  };

  return html`<div class="bd">
    <aside class="bd-tisch">
      <div class="bd-tisch-kopf"><h3>Am Tisch <span class="pill">${d.tisch.length}</span></h3>
        <span class="leise klein">${d.aufgefrischt ? "Stand aufgefrischt " + zeitText(d.aufgefrischt) : ""}</span></div>
      <div class="bd-filter">
        <button class=${gruppe ? "" : "an"} onClick=${() => setGruppe("")}>Alle</button>
        ${d.gruppen.map((g) => html`<button class=${gruppe === g.id ? "an" : ""} onClick=${() => setGruppe(g.id)} title=${g.name}>
          <i style=${`background:${GRUPPEN_FARBE[g.id]}`}></i>${g.name.split(/[ ,&]/)[0]}</button>`)}
      </div>
      <div class="bd-personen">
        ${sichtbar.map((p) => html`<div class=${"bd-person" + (tisch.has(p.id) ? " am" : "") + (einzel === p.id ? " einzel" : "")} key=${p.id}>
          <button class="bd-person-haupt" onClick=${() => setProfil(p)} title="Profil ansehen">
            <${Avatar} p=${p} /><span><b>${p.name}</b><small>${p.gruppen[0]}</small></span></button>
          <button class=${"bd-sitz" + (tisch.has(p.id) ? " an" : "")} onClick=${() => umschalten(p.id)}
            title=${tisch.has(p.id) ? "Vom Tisch nehmen" : "An den Tisch holen"} aria-pressed=${tisch.has(p.id)}><${Icon} n=${tisch.has(p.id) ? "check" : "plus"} g=${14} w=${2.4} /></button>
          <button class="bd-1zu1" onClick=${() => { setEinzel(p.id); navigiere("/board"); }} title=${"Einzelgespräch mit " + p.name}><${Icon} n="talk" g=${14} /></button>
        </div>`)}
      </div>
    </aside>
    <section class="bd-gespraech">
      <div class="bd-kopf">
        ${einzelP ? html`<span class="bd-modus"><${Avatar} p=${einzelP} g=${26} />Einzelgespräch mit <b>${einzelP.name}</b>
            <button class="btn klein geist icon" onClick=${() => setEinzel(null)} title="Zurück zur Runde am Tisch"><${Icon} n="x" g=${13} /></button></span>`
          : html`<span class="bd-modus"><span class="bd-stapel">${d.tisch.slice(0, 5).map((i) => nach[i] && html`<${Avatar} p=${nach[i]} g=${26} />`)}</span>
              Runde mit <b>${d.tisch.length}</b> am Tisch</span>`}
        <span class="luecke"></span>
        <select class="eingabe bd-auswahl" value=${projekt} onChange=${(e) => setProjekt(e.target.value)} title="Optional: ein Projekt, über das gesprochen wird">
          <option value="">Ohne Projektbezug</option>${projekte.map((p) => html`<option value=${p.id}>${p.name}</option>`)}</select>
        <select class="eingabe bd-auswahl" value=${id || ""} onChange=${(e) => navigiere(e.target.value ? "/board/" + e.target.value : "/board")} title="Frühere Gespräche">
          <option value="">Neues Gespräch</option>${d.gespraeche.map((g) => html`<option value=${g.id}>${g.titel} · ${zeitText(g.geaendert)}</option>`)}</select>
        ${id && html`<button class="btn klein geist icon" onClick=${gespraechWeg} title="Gespräch aus der Liste nehmen"><${Icon} n="archiv" g=${15} /></button>`}
        <button class="btn klein" onClick=${() => navigiere("/board")} title="Neues Gespräch beginnen"><${Icon} n="neu" g=${14} />Neu</button>
      </div>
      <div class="bd-verlauf" ref=${verlauf}>
        ${!msgs.length && !lauf && html`<div class="bd-start">
          <div class="bd-stapel gross">${(einzelP ? [einzelP] : d.tisch.map((i) => nach[i]).filter(Boolean)).slice(0, 8).map((p) => html`<${Avatar} p=${p} g=${44} />`)}</div>
          <p>${einzelP ? `Frag ${einzelP.name} direkt.` : "Stell deine Frage an die Runde. Es sprechen die, deren Sicht etwas beiträgt."}</p>
          <div class="bd-starter">${START.map(([t, vorlage]) => html`<button class="btn" onClick=${() => feld.current && feld.current.setzen(vorlage)}>${t}</button>`)}</div>
        </div>`}
        ${msgs.map((m) => m.rolle === "du"
          ? html`<div class="bd-du" key=${m.id}>${m.text}</div>`
          : html`<div class="bd-antwort" key=${m.id}><${Beitraege} text=${m.text} personen=${d.personen}
              einzel=${m.mit && m.mit.length === 1 ? nach[m.mit[0]] : null} /></div>`)}
        ${lauf && html`<div class="bd-antwort">${lauf.text
          ? html`<${Beitraege} text=${lauf.text} personen=${d.personen} einzel=${lauf.mit.length === 1 ? nach[lauf.mit[0]] : null} />`
          : html`<div class="bd-denkt"><span class="bd-stapel">${lauf.mit.slice(0, 5).map((i) => nach[i] && html`<${Avatar} p=${nach[i]} g=${26} />`)}</span>
              ${lauf.mit.length === 1 ? (nach[lauf.mit[0]] || {}).name + " denkt nach …" : "Das Board berät …"}</div>`}</div>`}
      </div>
      <div class="bd-eingabe">
        <${Composer} feldRef=${feld} platzhalter=${einzelP ? `Frag ${einzelP.name} …` : "Frag das Board …"} beimSenden=${(t) => senden(t)}
          laeuft=${!!lauf} beimStoppen=${() => abbruch.current && abbruch.current.abort()} entwurfKey=${"board:" + (id || "")} erlaubeAnhang=${false} zeilen=${2} />
      </div>
    </section>
    ${profil && html`<${Profil} p=${profil} amTisch=${tisch.has(profil.id)} umschalten=${() => umschalten(profil.id)}
      einzeln=${() => { setEinzel(profil.id); navigiere("/board"); }} zu=${() => setProfil(null)} />`}
  </div>`;
}
