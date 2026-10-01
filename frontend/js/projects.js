// PROJECTS -- Portfolio und je Projekt: Aufgaben, Notizen, Ergebnisse,
// Dateien, Verlauf. Dazu die Uebersichten "Alle Aufgaben" und "Alle Notizen".
// Ersetzt Projekte, Aufgaben, Notizen, Artefakte und Archiv des alten Cockpits.
import { html, useState, useEffect, useRef, Icon, Avatar, Leer, Md, Modal, StandPill, bus, toast, fehlerMelden, aktualisieren,
  zeitText, datumText, useAbruf, navigiere, kopieren, rolleName } from "./ui.js";
import { api, hochladen } from "./api.js";
import { Ausarbeiten } from "./inbox.js";

const FARBEN = ["#2C6BB3", "#0E9377", "#C07C12", "#E0392B", "#7C3AED", "#D0458F", "#0E7490", "#647388"];

export function Projects({ id }) {
  if (id === "_aufgaben") return html`<${Uebersicht} art="aufgaben" />`;
  if (id === "_notizen") return html`<${Uebersicht} art="notizen" />`;
  if (id) return html`<${Projekt} key=${id} id=${id} />`;
  return html`<${Uebersicht} art="projekte" />`;
}

function Kopfwahl({ art }) {
  return html`<div class="segment" style="margin-bottom:14px">
    <button class=${art === "projekte" ? "an" : ""} onClick=${() => navigiere("/projects")}>Projekte</button>
    <button class=${art === "aufgaben" ? "an" : ""} onClick=${() => navigiere("/projects/_aufgaben")}>Alle Aufgaben</button>
    <button class=${art === "notizen" ? "an" : ""} onClick=${() => navigiere("/projects/_notizen")}>Alle Notizen</button>
  </div>`;
}

function Uebersicht({ art }) {
  useEffect(() => { bus.sende("talk-kontext", null); }, []);
  return html`<div class="seite">
    <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center"><${Kopfwahl} art=${art} /></div>
    ${art === "projekte" && html`<${ProjektListe} />`}
    ${art === "aufgaben" && html`<${AufgabenListe} />`}
    ${art === "notizen" && html`<${NotizListe} />`}
  </div>`;
}

function ProjektListe() {
  const [alle, setAlle] = useState(false);
  const [q, setQ] = useState("");
  const [d, laden] = useAbruf("/projekte?alle=" + (alle ? 1 : 0), 60000, []);
  const [neu, setNeu] = useState(false);
  const liste = d ? d.projekte.filter((p) => !q || (p.name + " " + (p.fruehere_namen || []).join(" ")).toLowerCase().includes(q.toLowerCase())) : null;
  return html`
    <div class="knopfreihe" style="margin-bottom:12px">
      <input class="eingabe" style="max-width:280px" placeholder="Projekt suchen …" value=${q} onInput=${(e) => setQ(e.target.value)} aria-label="Projekt suchen" />
      <label class="klein leise" style="display:flex;gap:6px;align-items:center"><input type="checkbox" checked=${alle} onChange=${(e) => setAlle(e.target.checked)} />archivierte zeigen</label>
      <span style="flex:1"></span>
      <button class="btn primaer" onClick=${() => setNeu(true)}><${Icon} n="plus" g=${15} />Neues Projekt</button>
    </div>
    ${!liste ? html`<div class="lade">Lade …</div>` : !liste.length ? html`<${Leer} titel="Keine Projekte gefunden." />` : html`
    <div class="proj-raster">${liste.map((p) => {
      const ges = (p.offen || 0) + (p.erledigt || 0);
      return html`<button class="proj-karte" key=${p.id} onClick=${() => navigiere("/projects/" + p.id)}>
        <h3><span class="punkt" style=${"background:" + (p.farbe || "#999")}></span><span>${p.name}</span>
          ${p.status !== "aktiv" && html`<span class="pill">${p.status}</span>`}</h3>
        ${p.ziel && html`<div class="leise klein" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.ziel}</div>`}
        <div class="fortschritt" title=${`${p.erledigt} von ${ges} Aufgaben erledigt`}><i style=${`width:${ges ? Math.round(100 * p.erledigt / ges) : 0}%`}></i></div>
        <div class="zahlen"><span><b>${p.offen}</b> offen</span><span>${p.notizen} Notizen</span>${p.ergebnisse > 0 && html`<span>${p.ergebnisse} Ergebnisse</span>`}
          ${p.bewegung && html`<span>· ${zeitText(p.bewegung)}</span>`}</div>
      </button>`;
    })}</div>`}
    ${neu && html`<${NeuesProjekt} zu=${() => setNeu(false)} fertig=${(p) => { setNeu(false); laden(); navigiere("/projects/" + p.id); }} />`}`;
}

function NeuesProjekt({ zu, fertig }) {
  const [name, setName] = useState("");
  const [ziel, setZiel] = useState("");
  const [farbe, setFarbe] = useState(FARBEN[0]);
  async function los() {
    try { fertig(await api("/projekte", { methode: "POST", daten: { name, ziel, farbe } })); toast("Projekt angelegt."); } catch (e) { fehlerMelden(e); }
  }
  return html`<${Modal} titel="Neues Projekt" zu=${zu} fuss=${html`<button class="btn geist" onClick=${zu}>Abbrechen</button>
      <button class="btn primaer" disabled=${!name.trim()} onClick=${los}>Anlegen</button>`}>
    <div class="feld"><label for="np-name">Name</label><input id="np-name" class="eingabe" value=${name} onInput=${(e) => setName(e.target.value)} autofocus
      onKeyDown=${(e) => { if (e.key === "Enter" && name.trim()) los(); }} /></div>
    <div class="feld" style="margin-top:10px"><label for="np-ziel">Ziel (optional, ein Satz)</label><input id="np-ziel" class="eingabe" value=${ziel} onInput=${(e) => setZiel(e.target.value)} /></div>
    <div class="feld" style="margin-top:10px"><label>Farbe</label><div class="knopfreihe">${FARBEN.map((f) => html`
      <button type="button" aria-label=${"Farbe " + f} onClick=${() => setFarbe(f)} style=${`width:28px;height:28px;border-radius:50%;border:3px solid ${farbe === f ? "var(--ink)" : "transparent"};background:${f};cursor:pointer`}></button>`)}</div></div>
  <//>`;
}

function AufgabeZeile({ t, nachher, mitProjekt }) {
  const [bearb, setBearb] = useState(false);
  const [titel, setTitel] = useState(t.titel);
  async function setzen(daten, meldung) {
    try { await api("/aufgaben/" + t.id, { methode: "PATCH", daten }); if (meldung) toast(meldung); nachher(); aktualisieren(); } catch (e) { fehlerMelden(e); }
  }
  const erledigt = t.status === "erledigt";
  return html`<div class="zeile">
    <button class=${"check" + (erledigt ? " an" : "")} onClick=${() => setzen({ status: erledigt ? "offen" : "erledigt" })} aria-label=${(erledigt ? "Wieder öffnen: " : "Erledigt: ") + t.titel}>
      ${erledigt ? html`<${Icon} n="check" g=${14} w=${3} />` : ""}</button>
    <div class="haupt-text">
      ${bearb ? html`<input class="eingabe" value=${titel} autofocus onInput=${(e) => setTitel(e.target.value)}
          onKeyDown=${(e) => { if (e.key === "Enter") { setBearb(false); if (titel.trim() && titel !== t.titel) setzen({ titel: titel.trim() }); } if (e.key === "Escape") { setBearb(false); setTitel(t.titel); } }}
          onBlur=${() => { setBearb(false); if (titel.trim() && titel !== t.titel) setzen({ titel: titel.trim() }); }} />`
        : html`<span style=${erledigt ? "text-decoration:line-through;color:var(--ink-3)" : ""} onDblClick=${() => setBearb(true)}>${t.titel}</span>`}
      <div class="leise klein">
        ${mitProjekt && (t.projekt_name ? html`<a href=${"#/projects/" + t.projekt_id} style="color:inherit">${t.projekt_name}</a>` : "ohne Projekt")}
        ${t.quelle === "stab" ? html`${mitProjekt ? " · " : ""}vom Stab${t.vorgang_id ? html` (<a href=${"#/inbox/" + t.vorgang_id} style="color:inherit">Akte</a>)` : ""}` : ""}
      </div>
    </div>
    <input type="date" class="eingabe" style="width:auto;min-height:30px;padding:2px 6px;font-size:12px" value=${t.faellig || ""} aria-label="Fällig am"
      onChange=${(e) => setzen({ faellig: e.target.value })} />
    <button class="btn klein geist icon" title="Bearbeiten" aria-label="Bearbeiten" onClick=${() => setBearb(true)}><${Icon} n="stift" g=${14} /></button>
    <button class="btn klein geist icon" title="Archivieren" aria-label="Archivieren" onClick=${async () => {
      try { await api("/aufgaben/" + t.id, { methode: "DELETE" }); toast("Archiviert.", { aktion: { text: "Rückgängig", fn: () => setzen({ archiviert: 0 }) } }); nachher(); } catch (e) { fehlerMelden(e); }
    }}><${Icon} n="archiv" g=${14} /></button>
  </div>`;
}

function NeueAufgabe({ projektId, nachher }) {
  const [t, setT] = useState("");
  async function los() {
    if (!t.trim()) return;
    try { await api("/aufgaben", { methode: "POST", daten: { titel: t.trim(), projekt_id: projektId || null } }); setT(""); nachher(); aktualisieren(); } catch (e) { fehlerMelden(e); }
  }
  return html`<div style="display:flex;gap:6px;margin-bottom:8px">
    <input class="eingabe" placeholder="Neue Aufgabe … (Enter)" value=${t} onInput=${(e) => setT(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter") los(); }} aria-label="Neue Aufgabe" />
    <button class="btn" disabled=${!t.trim()} onClick=${los}><${Icon} n="plus" g=${15} />Anlegen</button>
  </div>`;
}

function AufgabenListe() {
  const [status, setStatus] = useState("offen");
  const [q, setQ] = useState("");
  const [d, laden] = useAbruf(`/aufgaben?status=${status}&q=${encodeURIComponent(q)}`, 30000, []);
  return html`<section class="karte">
    <div class="knopfreihe" style="margin-bottom:10px">
      <div class="segment"><button class=${status === "offen" ? "an" : ""} onClick=${() => setStatus("offen")}>Offen</button>
        <button class=${status === "erledigt" ? "an" : ""} onClick=${() => setStatus("erledigt")}>Erledigt</button></div>
      <input class="eingabe" style="max-width:260px" placeholder="Aufgaben suchen …" value=${q} onInput=${(e) => setQ(e.target.value)} />
    </div>
    <${NeueAufgabe} projektId=${null} nachher=${laden} />
    ${!d ? html`<div class="lade">Lade …</div>` : !d.aufgaben.length ? html`<${Leer} titel="Keine Aufgaben." />`
      : d.aufgaben.map((t) => html`<${AufgabeZeile} key=${t.id} t=${t} nachher=${laden} mitProjekt=${true} />`)}
  </section>`;
}

function NotizListe({ projektId }) {
  const [q, setQ] = useState("");
  const [ohne, setOhne] = useState(false);
  const [d] = useAbruf(`/notizen?q=${encodeURIComponent(q)}&ohne=${ohne ? 1 : 0}${projektId ? "&projekt=" + projektId : ""}`, 60000, []);
  return html`<section class="karte">
    <div class="knopfreihe" style="margin-bottom:10px">
      <input class="eingabe" style="max-width:280px" placeholder="In Notizen suchen …" value=${q} onInput=${(e) => setQ(e.target.value)} />
      ${!projektId && html`<label class="klein leise" style="display:flex;gap:6px;align-items:center"><input type="checkbox" checked=${ohne} onChange=${(e) => setOhne(e.target.checked)} />nur ohne Projekt</label>`}
    </div>
    ${!d ? html`<div class="lade">Lade …</div>` : !d.notizen.length ? html`<${Leer} titel="Keine Notizen." />`
      : d.notizen.map((n) => {
        const text = (n.kurz || n.text || "").replace(/Transcript:[^\n]*\n|\[\d\d:\d\d - \d\d:\d\d\] Speaker \d+:/g, "").trim();
        const titelIstText = n.titel && text.startsWith(n.titel.trim());
        return html`<div class="zeile" key=${n.id} style="cursor:pointer" role="button" tabindex="0" onClick=${() => bus.sende("notiz-zeigen", n.id)}
          onKeyDown=${(e) => { if (e.key === "Enter") bus.sende("notiz-zeigen", n.id); }}>
        <div class="haupt-text">${!titelIstText && html`<b>${n.titel || "Notiz"}</b>`}
          <div class=${titelIstText ? "" : "leise klein"} style="display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">${text}</div></div>
        <span class="neben">${!projektId ? (n.projekt_name || "ohne Projekt") + " · " : ""}${n.datum ? datumText(n.datum) : zeitText(n.erstellt)}</span>
      </div>`;
      })}
  </section>`;
}

function Projekt({ id }) {
  const [tab, setTab] = useState("ueberblick");
  const [d, laden, fehler] = useAbruf("/projekte/" + id, 30000, []);
  const [nameBearb, setNameBearb] = useState(null);
  const [ausarbeiten, setAusarbeiten] = useState(false);
  const datei = useRef(null);
  useEffect(() => { if (d) bus.sende("talk-kontext", { art: "projekt", id, titel: d.projekt.name }); }, [d && d.projekt.name]);
  useEffect(() => () => bus.sende("talk-kontext", null), []);
  if (fehler) return html`<div class="seite"><div class="fehlerbox">${fehler.message}</div></div>`;
  if (!d) return html`<div class="seite"><div class="lade">Lade Projekt …</div></div>`;
  const p = d.projekt;
  const offen = d.aufgaben.filter((t) => t.status !== "erledigt");
  const erledigt = d.aufgaben.filter((t) => t.status === "erledigt");

  async function aendern(daten, meldung) {
    try { await api("/projekte/" + id, { methode: "PATCH", daten }); if (meldung) toast(meldung); laden(); aktualisieren(); } catch (e) { fehlerMelden(e); }
  }
  async function hoch(liste) {
    for (const f of liste) {
      try { await hochladen(f, { projekt_id: id }); toast("Abgelegt: " + f.name); } catch (e) { fehlerMelden(e); }
    }
    laden();
  }

  const TABS = [["ueberblick", "Überblick"], ["aufgaben", "Aufgaben", offen.length], ["notizen", "Notizen", d.notizen.length],
    ["ergebnisse", "Ergebnisse", d.ergebnisse.length], ["verlauf", "Verlauf", d.vorgaenge.length], ["dateien", "Dateien", d.dateien.length]];

  return html`<div class="seite">
    <div class="akte-kopf">
      <button class="btn geist icon" onClick=${() => navigiere("/projects")} aria-label="Zurück zu allen Projekten" title="Alle Projekte"><${Icon} n="links" /></button>
      <div class="titel">
        ${nameBearb !== null ? html`<input class="eingabe titel-gross" value=${nameBearb} autofocus onInput=${(e) => setNameBearb(e.target.value)}
            onKeyDown=${(e) => { if (e.key === "Enter" && nameBearb.trim()) { aendern({ name: nameBearb.trim() }, "Umbenannt. Der alte Name bleibt Jason bekannt."); setNameBearb(null); } if (e.key === "Escape") setNameBearb(null); }} />`
          : html`<h2 class="titel-gross" style="display:flex;align-items:center;gap:10px"><span class="punkt" style=${"width:14px;height:14px;background:" + (p.farbe || "#999")}></span>${p.name}
            <button class="btn klein geist icon" onClick=${() => setNameBearb(p.name)} title="Umbenennen" aria-label="Umbenennen"><${Icon} n="stift" g=${14} /></button></h2>`}
        <div class="leise klein" style="margin-top:3px">${p.ziel || "Kein Ziel eingetragen."}${(p.fruehere_namen || []).length ? ` · früher: ${p.fruehere_namen.join(", ")}` : ""}</div>
      </div>
      <div class="knopfreihe">
        <button class="btn" onClick=${() => bus.sende("talk-oeffnen", { kontext: { art: "projekt", id, titel: p.name } })}><${Icon} n="talk" g=${15} />Besprechen</button>
        <button class="btn" onClick=${() => setAusarbeiten(true)}><${Icon} n="stift" g=${15} />Ausarbeiten lassen</button>
        <select class="eingabe" style="width:auto" value=${p.status} aria-label="Status" onChange=${(e) => aendern({ status: e.target.value }, "Status geändert.")}>
          <option value="aktiv">aktiv</option><option value="pausiert">pausiert</option><option value="abgeschlossen">abgeschlossen</option><option value="archiviert">archiviert</option>
        </select>
      </div>
    </div>
    <div class="tabs" role="tablist">${TABS.map(([k, t, n]) => html`<button role="tab" aria-selected=${tab === k} class=${tab === k ? "an" : ""} onClick=${() => setTab(k)}>${t}${n ? html`<span class="zahl">${n}</span>` : ""}</button>`)}</div>

    ${tab === "ueberblick" && html`<div class="raster zwei">
      <section class="karte"><div class="karte-kopf"><h3>Offene Aufgaben</h3><span class="pill">${offen.length}</span></div>
        <${NeueAufgabe} projektId=${id} nachher=${laden} />
        ${offen.length ? offen.slice(0, 12).map((t) => html`<${AufgabeZeile} key=${t.id} t=${t} nachher=${laden} />`) : html`<${Leer}>Keine offenen Aufgaben.</${Leer}>`}
        ${offen.length > 12 && html`<button class="btn klein geist" onClick=${() => setTab("aufgaben")}>Alle ${offen.length} zeigen</button>`}
      </section>
      <div>
        <section class="karte"><div class="karte-kopf"><h3>Ziel</h3></div>
          <textarea class="eingabe" rows="2" placeholder="Ein Satz: Was soll mit diesem Projekt erreicht werden? Hilft dem Stab beim Einordnen." value=${p.ziel || ""}
            onBlur=${(e) => { if (e.target.value !== (p.ziel || "")) aendern({ ziel: e.target.value }, "Ziel gespeichert."); }}></textarea></section>
        <section class="karte"><div class="karte-kopf"><h3>Neueste Ergebnisse</h3></div>
          ${d.ergebnisse.length ? d.ergebnisse.slice(0, 4).map((r) => html`<${ErgebnisZeile} key=${r.id} r=${r} />`) : html`<${Leer}>Noch keine. „Ausarbeiten lassen“ gibt einer Rolle einen Auftrag.</${Leer}>`}</section>
        <section class="karte"><div class="karte-kopf"><h3>Jüngste Akten</h3></div>
          ${d.vorgaenge.length ? d.vorgaenge.slice(0, 5).map((v) => html`<div class="zeile" key=${v.id}><div class="haupt-text"><a href=${"#/inbox/" + v.id} style="color:inherit">${v.titel}</a></div><${StandPill} stand=${v.stand} /></div>`)
            : html`<${Leer}>Noch keine.</${Leer}>`}</section>
      </div>
    </div>`}
    ${tab === "aufgaben" && html`<section class="karte">
      <${NeueAufgabe} projektId=${id} nachher=${laden} />
      ${offen.map((t) => html`<${AufgabeZeile} key=${t.id} t=${t} nachher=${laden} />`)}
      ${erledigt.length > 0 && html`<details style="margin-top:10px"><summary class="leise klein" style="cursor:pointer">${erledigt.length} erledigt</summary>
        ${erledigt.map((t) => html`<${AufgabeZeile} key=${t.id} t=${t} nachher=${laden} />`)}</details>`}
      ${!d.aufgaben.length && html`<${Leer} titel="Noch keine Aufgaben." />`}
    </section>`}
    ${tab === "notizen" && html`<${NotizListe} projektId=${id} />`}
    ${tab === "ergebnisse" && html`<section class="karte">${d.ergebnisse.length ? d.ergebnisse.map((r) => html`<${ErgebnisZeile} key=${r.id} r=${r} />`)
      : html`<${Leer} titel="Noch keine Ergebnisse.">Mit „Ausarbeiten lassen“ bekommt eine Rolle einen Auftrag. Das Ergebnis landet hier, geprüft von Daniel.</${Leer}>`}</section>`}
    ${tab === "verlauf" && html`<section class="karte">${d.vorgaenge.length ? d.vorgaenge.map((v) => html`<div class="zeile" key=${v.id}>
        <div class="haupt-text"><a href=${"#/inbox/" + v.id} style="color:inherit"><b>${v.titel}</b></a><div class="leise klein">${v.einordnung || ""}</div></div>
        <${StandPill} stand=${v.stand} /><span class="neben">${zeitText(v.geaendert)}</span></div>`) : html`<${Leer} titel="Noch keine Akten zu diesem Projekt." />`}</section>`}
    ${tab === "dateien" && html`<section class="karte"
        onDragOver=${(e) => e.preventDefault()} onDrop=${(e) => { e.preventDefault(); hoch([...e.dataTransfer.files]); }}>
      <div class="karte-kopf"><h3>Dateien</h3><button class="btn klein rechts" onClick=${() => datei.current.click()}><${Icon} n="plus" g=${14} />Hochladen</button>
        <input ref=${datei} type="file" multiple hidden onChange=${(e) => { const l = [...e.target.files]; e.target.value = ""; hoch(l); }} /></div>
      ${d.dateien.length ? d.dateien.map((f) => html`<div class="zeile" key=${f.id}><${Icon} n="clip" g=${15} />
        <div class="haupt-text"><a href=${"/api/dateien/" + f.id} target="_blank" rel="noopener">${f.name}</a></div>
        <span class="neben">${Math.max(1, Math.round(f.groesse / 1024))} KB · ${zeitText(f.erstellt)}</span></div>`)
        : html`<${Leer}>Noch keine Dateien. Hierher ziehen oder „Hochladen“.</${Leer}>`}
    </section>`}
    ${ausarbeiten && html`<${Ausarbeiten} v=${null} projektId=${id} zu=${() => setAusarbeiten(false)} fertig=${() => { setAusarbeiten(false); navigiere("/inbox"); }} />`}
  </div>`;
}

function ErgebnisZeile({ r }) {
  const u = r.pruefung && r.pruefung.urteil;
  return html`<div class="zeile">
    <${Avatar} wer=${r.rolle} name=${rolleName(r.rolle)} g=${22} />
    <div class="haupt-text"><b>${r.titel}</b><div class="leise klein">${rolleName(r.rolle)} · ${r.form} · ${zeitText(r.erstellt)}</div></div>
    ${u && html`<span class=${"pill " + (u === "tragfaehig" ? "gruen" : "gelb")}>${u === "tragfaehig" ? "geprüft" : u === "nachbessern" ? "mit Mängeln" : u}</span>`}
    <button class="btn klein" onClick=${() => bus.sende("ergebnis-zeigen", r.id)}>Ansehen</button>
  </div>`;
}

export function ErgebnisAnsicht({ id, zu }) {
  const [e, setE] = useState(null);
  const [ansicht, setAnsicht] = useState(false);
  useEffect(() => { api("/ergebnisse/" + id).then((x) => { setE(x); setAnsicht(!!x.ansicht); }).catch((x) => { fehlerMelden(x); zu(); }); }, [id]);
  if (!e) return html`<${Modal} titel="Ergebnis" zu=${zu}><div class="lade">Lade …</div><//>`;
  const p = e.pruefung || {};
  return html`<${Modal} titel=${e.titel} zu=${zu} breit=${true} fuss=${html`
      <button class="btn" onClick=${async () => { if (await kopieren(e.inhalt)) toast("Kopiert."); }}><${Icon} n="kopie" g=${15} />Kopieren</button>
      <button class="btn" onClick=${() => { zu(); bus.sende("talk-oeffnen", { kontext: { art: "ergebnis", id: e.id, titel: e.titel } }); }}><${Icon} n="talk" g=${15} />Besprechen</button>
      ${e.vorgang_id && html`<a class="btn" href=${"#/inbox/" + e.vorgang_id} onClick=${zu}>Zur Akte</a>`}
      <button class="btn primaer" onClick=${zu}>Schließen</button>`}>
    <div class="knopfreihe" style="margin-bottom:10px">
      <${Avatar} wer=${e.rolle} name=${e.wer_name} g=${24} /><b>${e.wer_name}</b><span class="leise klein">${e.form} · ${e.modell} · ${zeitText(e.erstellt)}</span>
      ${p.urteil && html`<span class=${"pill " + (p.urteil === "tragfaehig" ? "gruen" : "gelb")}>Daniel: ${p.urteil === "tragfaehig" ? "trägt" : p.urteil}</span>`}
      ${e.ansicht ? html`<div class="segment" style="margin-left:auto"><button class=${ansicht ? "an" : ""} onClick=${() => setAnsicht(true)}>Ansicht</button>
        <button class=${!ansicht ? "an" : ""} onClick=${() => setAnsicht(false)}>Text</button></div>` : ""}
    </div>
    ${p.begruendung && html`<div class="hinweisbox" style="margin-bottom:12px"><b>Prüfung:</b> ${p.begruendung}
      ${(p.maengel || []).length > 0 && html`<ul style="margin:4px 0 0;padding-left:18px">${p.maengel.map((m) => html`<li>${m}</li>`)}</ul>`}</div>`}
    ${ansicht ? html`<div class="ergebnis-ansicht"><iframe src=${"/api/ergebnisse/" + e.id + "/ansicht"} sandbox="allow-scripts allow-forms allow-popups" title=${e.titel}></iframe>
        <a class="btn klein" style="margin-top:6px" href=${"/api/ergebnisse/" + e.id + "/ansicht"} target="_blank" rel="noopener"><${Icon} n="extern" g=${14} />In neuem Tab öffnen</a></div>`
      : html`<${Md} text=${e.inhalt} />`}
    ${(e.quellen || []).length > 0 && html`<details style="margin-top:14px"><summary class="klein" style="cursor:pointer">${e.quellen.length} Quellen</summary>
      <ol class="klein">${e.quellen.map((q) => html`<li><a href=${q.url} target="_blank" rel="noopener">${q.titel || q.url}</a></li>`)}</ol></details>`}
  <//>`;
}

export function NotizAnsicht({ id, zu }) {
  const [n, setN] = useState(null);
  const [projekte, setProjekte] = useState([]);
  useEffect(() => {
    api("/notizen/" + id).then(setN).catch((x) => { fehlerMelden(x); zu(); });
    api("/projekte").then((d) => setProjekte(d.projekte)).catch(() => {});
  }, [id]);
  if (!n) return html`<${Modal} titel="Notiz" zu=${zu}><div class="lade">Lade …</div><//>`;
  const text = (n.text || n.kurz || "").replace(/Transcript:[^\n]*\n/, "").replace(/\[\d\d:\d\d - \d\d:\d\d\] Speaker \d+:\s*/g, "");
  async function anStab() {
    try { const r = await api(`/notizen/${id}/an-stab`, { methode: "POST" }); toast("Jason ordnet die Notiz ein."); zu(); navigiere("/inbox/" + r.vorgang_id); } catch (e) { fehlerMelden(e); }
  }
  return html`<${Modal} titel=${n.titel || "Notiz"} zu=${zu} fuss=${html`
      ${n.vorgaenge && n.vorgaenge.length ? html`<a class="btn" href=${"#/inbox/" + n.vorgaenge[0].id} onClick=${zu}>Zur Akte</a>`
        : html`<button class="btn" onClick=${anStab}><${Icon} n="team" g=${15} />Vom Stab bearbeiten lassen</button>`}
      <button class="btn primaer" onClick=${zu}>Schließen</button>`}>
    <div class="knopfreihe" style="margin-bottom:10px">
      <span class="leise klein">${n.quelle === "plaud" ? "Plaud" : "Notiz"} · ${n.datum || zeitText(n.erstellt)}</span>
      <select class="eingabe" style="width:auto;margin-left:auto" value=${n.projekt_id || ""} aria-label="Projekt"
        onChange=${async (e) => { try { await api("/notizen/" + id, { methode: "PATCH", daten: { projekt_id: e.target.value || null } }); toast("Zugeordnet."); aktualisieren(); } catch (x) { fehlerMelden(x); } }}>
        <option value="">ohne Projekt</option>${projekte.map((p) => html`<option value=${p.id}>${p.name}</option>`)}</select>
    </div>
    <div class="zitat">${text}</div>
  <//>`;
}
