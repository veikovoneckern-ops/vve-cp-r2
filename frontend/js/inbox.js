// INBOX -- alles, was hereinkommt, als Akte mit Verlauf.
// Ersetzt Eingang, Zuordnungen, Drop, Schnellsichtung, Vorgaenge und Work in
// Progress des alten Cockpits: EIN Ort pro Notiz.
import { html, useState, useEffect, Icon, Avatar, Leer, Md, Modal, StandPill, bus, toast, fehlerMelden, aktualisieren,
  zeitText, useAbruf, navigiere, rolleName, ROLLEN_WAHL, FORM_WAHL } from "./ui.js";
import { api } from "./api.js";
import { Entscheidung } from "./entscheidung.js";

const FILTER = [["wartet", "Wartet auf dich"], ["in_arbeit", "In Arbeit"], ["fertig", "Fertig"], ["erledigt", "Erledigt"], ["alle", "Alle"]];
const ART_TEXT = { notiz: "Notiz", einordnung: "hat eingeordnet", aufgabe: "Aufgabe", rueckfrage: "fragt nach", vorschlag: "schlägt vor",
  antwort: "hat geantwortet", ergebnis: "hat geliefert", pruefung: "hat geprüft", entscheidung: "hat entschieden", fehler: "Fehler",
  info: "", auftrag: "hat beauftragt" };
const QUELLE = { plaud: "Plaud", eingabe: "Capture", gespraech: "Talk", alt: "altes Cockpit" };

export function Inbox({ id }) {
  const [filter, setFilter] = useState(() => { try { return sessionStorage.getItem("inbox_filter") || "wartet"; } catch (e) { return "wartet"; } });
  const [q, setQ] = useState("");
  const [daten, laden] = useAbruf(`/vorgaenge?filter=${filter}&q=${encodeURIComponent(q)}`, 15000, []);
  useEffect(() => { try { sessionStorage.setItem("inbox_filter", filter); } catch (e) { /* egal */ } }, [filter]);
  useEffect(() => () => bus.sende("talk-kontext", null), []);
  const liste = daten ? daten.vorgaenge : null;
  const z = daten ? daten.zaehler : {};

  // Ohne Auswahl am Rechner die erste Akte zeigen -- eine leere rechte Haelfte erklaert nichts.
  useEffect(() => {
    if (!id && liste && liste.length && innerWidth > 820) navigiere("/inbox/" + liste[0].id);
  }, [id, liste && liste.length]);

  return html`<div class=${"inbox" + (id ? " mit-akte" : "")}>
    <aside class="inbox-liste">
      <div class="kopf">
        <div class="segment" role="tablist">${FILTER.map(([k, t]) => html`<button role="tab" aria-selected=${filter === k} class=${filter === k ? "an" : ""}
          onClick=${() => setFilter(k)}>${t}${z[k] !== undefined && k !== "alle" ? html`<span class="zahl">${z[k]}</span>` : ""}</button>`)}</div>
        <input class="eingabe" placeholder="In der Inbox suchen …" value=${q} onInput=${(e) => setQ(e.target.value)} aria-label="In der Inbox suchen" />
      </div>
      <div class="liste">
        ${!liste ? html`<div class="lade">Lade …</div>`
          : !liste.length ? html`<${Leer} titel=${filter === "wartet" ? "Nichts wartet auf dich." : "Hier ist nichts."}>
              ${filter === "wartet" ? "Neue Notizen ordnet Jason von selbst ein. Mit Capture gibst du ihm etwas direkt." : ""}</${Leer}>`
          : liste.map((v) => html`<button key=${v.id} class=${"vg-eintrag" + (v.id === id ? " an" : "")} onClick=${() => navigiere("/inbox/" + v.id)}>
              <b>${v.titel}</b>
              <div class="unter">
                <${StandPill} stand=${v.stand} />
                ${v.offen > 0 && html`<span class="pill gelb">${v.offen} offen</span>`}
                ${v.projekt_name ? html`<span><span class="punkt" style=${"width:7px;height:7px;background:" + (v.projekt_farbe || "#999")}></span> ${v.projekt_name}</span>`
                  : v.projekt_vorschlag ? html`<span>neu: ${v.projekt_vorschlag}?</span>` : html`<span>ohne Projekt</span>`}
                <span>· ${QUELLE[v.quelle] || v.quelle} · ${zeitText(v.geaendert)}</span>
              </div>
            </button>`)}
      </div>
    </aside>
    ${id ? html`<${Akte} key=${id} id=${id} nachher=${laden} />`
      : html`<div class="akte"><${Leer} titel="Wähle links einen Case.">Jede Notiz, jeder Auftrag aus dem Talk und alles aus Capture landet hier, mit allem, was dein Team dazu getan hat.</${Leer}></div>`}
  </div>`;
}

function Akte({ id, nachher }) {
  const [takt, setTakt] = useState(8000);
  const [d, laden, fehler] = useAbruf("/vorgaenge/" + id, takt, []);
  const [verwerfen, setVerwerfen] = useState(null);
  const [ausarbeiten, setAusarbeiten] = useState(false);
  const [projekte, setProjekte] = useState([]);
  const [notizAuf, setNotizAuf] = useState(false);
  useEffect(() => { api("/projekte").then((x) => setProjekte(x.projekte)).catch(() => {}); }, []);
  useEffect(() => {
    if (!d) return;
    setTakt(["neu", "eingeordnet", "in_arbeit"].includes(d.vorgang.stand) ? 5000 : 30000);
    bus.sende("talk-kontext", { art: "vorgang", id, titel: d.vorgang.titel });
  }, [d && d.vorgang.stand, d && d.vorgang.titel]);

  if (fehler) return html`<div class="akte"><div class="fehlerbox">${fehler.message}</div></div>`;
  if (!d) return html`<div class="akte"><div class="lade">Lade Case …</div></div>`;
  const v = d.vorgang;
  const offen = d.entscheidungen.filter((e) => e.stand === "offen");

  async function aktion(a, extra = {}) {
    try {
      await api(`/vorgaenge/${id}/aktion`, { methode: "POST", daten: { aktion: a, ...extra } });
      const t = { erledigt: "Abgelegt.", verwerfen: "Verworfen.", wieder_oeffnen: "Wieder geöffnet.", neu_einordnen: "Jason ordnet neu ein.", projekt: "Projekt geändert.", nochmal: "Wird noch einmal versucht." }[a];
      toast(t || "Erledigt.", a === "erledigt" || a === "verwerfen" ? { aktion: { text: "Rückgängig", fn: () => aktion("wieder_oeffnen") } } : {});
      setVerwerfen(null); laden(); nachher && nachher(); aktualisieren();
    } catch (e) { fehlerMelden(e); }
  }
  async function rueckgaengig(pid) {
    try { await api("/rueckgaengig/" + pid, { methode: "POST" }); toast("Zurückgenommen."); laden(); aktualisieren(); } catch (e) { fehlerMelden(e); }
  }
  async function aufgabeUmschalten(t) {
    try { await api("/aufgaben/" + t.id, { methode: "PATCH", daten: { status: t.status === "erledigt" ? "offen" : "erledigt" } }); laden(); aktualisieren(); } catch (e) { fehlerMelden(e); }
  }

  const abgeschlossen = v.stand === "erledigt" || v.stand === "verworfen";
  const notizText = d.notiz ? (d.notiz.text || d.notiz.kurz || "") : "";

  return html`<div class="akte">
    <div class="akte-kopf">
      <button class="btn geist icon zurueck-knopf" onClick=${() => navigiere("/inbox")} aria-label="Zurück zur Liste"><${Icon} n="links" /></button>
      <div class="titel">
        <h2>${v.titel}</h2>
        <div class="knopfreihe" style="margin-top:6px">
          <${StandPill} stand=${v.stand} />
          <span class="leise klein">${QUELLE[v.quelle] || v.quelle} · angelegt ${zeitText(v.erstellt)}</span>
          <select class="eingabe" style="width:auto;min-height:30px;padding:3px 8px;font-size:12.5px" value=${v.projekt_id || ""} aria-label="Projekt"
            onChange=${(e) => aktion("projekt", { projekt_id: e.target.value || null })}>
            <option value="">ohne Projekt</option>
            ${projekte.map((p) => html`<option value=${p.id}>${p.name}</option>`)}
          </select>
        </div>
      </div>
      <div class="knopfreihe">
        <button class="btn" onClick=${() => bus.sende("talk-oeffnen", { kontext: { art: "vorgang", id, titel: v.titel } })}><${Icon} n="talk" g=${15} />Besprechen</button>
        ${!abgeschlossen && html`<button class="btn" onClick=${() => setAusarbeiten(true)} title="Eine Rolle etwas ausarbeiten lassen"><${Icon} n="stift" g=${15} />Ausarbeiten lassen</button>`}
        ${!abgeschlossen ? html`
          <button class="btn ja" onClick=${() => aktion("erledigt")}><${Icon} n="check" g=${15} />Erledigt</button>
          <button class="btn gefahr" onClick=${() => setVerwerfen(verwerfen === null ? "" : null)}>Verwerfen</button>`
          : html`<button class="btn" onClick=${() => aktion("wieder_oeffnen")}><${Icon} n="undo" g=${15} />Wieder öffnen</button>`}
      </div>
    </div>
    ${verwerfen !== null && html`<div class="karte" style="margin-bottom:12px">
      <div class="feld"><label for="verw">Warum? (optional, hilft später beim Nachsehen)</label>
        <div class="antwortfeld" style="display:flex;gap:6px">
          <input id="verw" class="eingabe" value=${verwerfen} onInput=${(e) => setVerwerfen(e.target.value)} autofocus
            onKeyDown=${(e) => { if (e.key === "Enter") aktion("verwerfen", { kommentar: verwerfen }); if (e.key === "Escape") setVerwerfen(null); }} />
          <button class="btn gefahr voll" onClick=${() => aktion("verwerfen", { kommentar: verwerfen })}>Verwerfen</button>
          <button class="btn geist" onClick=${() => setVerwerfen(null)}>Abbrechen</button>
        </div></div></div>`}
    ${d.laeuft && html`<div class="hinweisbox" style="margin-bottom:12px;background:var(--violett-soft);border-color:transparent">
      <b>${rolleName(d.laeuft.wer)}</b> ${d.laeuft.was} … (seit ${zeitText(d.laeuft.seit).replace("vor ", "")})</div>`}
    ${v.versuche >= 3 && !abgeschlossen && html`<div class="fehlerbox" style="margin-bottom:12px;display:flex;gap:10px;align-items:center">
      <span style="flex:1">Das Team ist hier dreimal gescheitert. Den Grund siehst du unten im Verlauf.</span>
      <button class="btn klein" onClick=${() => aktion("nochmal")}>Noch einmal versuchen</button></div>`}

    ${offen.length > 0 && html`<section class="karte" style="margin-bottom:12px">
      <div class="karte-kopf"><h3>Wartet auf dich</h3><span class="pill gelb">${offen.length}</span></div>
      ${offen.map((e) => html`<${Entscheidung} key=${e.id} e=${e} mitVorgang=${false} nachher=${() => { laden(); nachher && nachher(); }} />`)}
    </section>`}

    <div class="raster zwei">
      <section>
        <div class="karte-kopf"><h3>Verlauf</h3></div>
        <div class="verlauf">
          ${d.ereignisse.map((e) => html`<${Ereignis} key=${e.id} e=${e} notizText=${e.art === "notiz" ? notizText : ""} notizAuf=${notizAuf} setNotizAuf=${setNotizAuf} />`)}
        </div>
      </section>
      <aside>
        ${d.protokoll.length > 0 && html`<section class="karte">
          <div class="karte-kopf"><h3>Vom Team eingetragen</h3></div>
          ${d.protokoll.map((p) => html`<div class="zeile" key=${p.id}>
            <div class="haupt-text" style=${p.rueckgaengig ? "text-decoration:line-through;color:var(--ink-4)" : ""}>${p.label}</div>
            ${!p.rueckgaengig && html`<button class="btn klein geist" onClick=${() => rueckgaengig(p.id)} title="Zurücknehmen"><${Icon} n="undo" g=${14} /></button>`}
          </div>`)}
        </section>`}
        ${d.aufgaben.length > 0 && html`<section class="karte">
          <div class="karte-kopf"><h3>Aufgaben aus diesem Case</h3></div>
          ${d.aufgaben.filter((t) => !t.archiviert).map((t) => html`<div class="zeile" key=${t.id}>
            <button class=${"check" + (t.status === "erledigt" ? " an" : "")} onClick=${() => aufgabeUmschalten(t)} aria-label="Erledigt umschalten">${t.status === "erledigt" ? html`<${Icon} n="check" g=${14} w=${3} />` : ""}</button>
            <div class="haupt-text" style=${t.status === "erledigt" ? "text-decoration:line-through;color:var(--ink-3)" : ""}>${t.titel}</div>
          </div>`)}
        </section>`}
        ${d.ergebnisse.length > 0 && html`<section class="karte">
          <div class="karte-kopf"><h3>Ergebnisse</h3></div>
          ${d.ergebnisse.map((r) => html`<div class="zeile" key=${r.id}>
            <div class="haupt-text"><b>${r.titel}</b><div class="leise klein">${r.form} · ${zeitText(r.erstellt)}</div></div>
            <button class="btn klein" onClick=${() => bus.sende("ergebnis-zeigen", r.id)}>Ansehen</button></div>`)}
        </section>`}
        <section class="karte">
          <div class="karte-kopf"><h3>Weitere Schritte</h3></div>
          <div class="knopfreihe">
            ${d.notiz && html`<button class="btn klein" onClick=${() => aktion("neu_einordnen")} title="Jason ordnet die Notiz noch einmal ein, mit dem aktuellen Memory">
              <${Icon} n="neu_laden" g=${14} />Neu einordnen</button>`}
            ${v.projekt_id && html`<a class="btn klein" href=${"#/projects/" + v.projekt_id}><${Icon} n="projects" g=${14} />Zum Projekt</a>`}
          </div>
        </section>
      </aside>
    </div>
    ${ausarbeiten && html`<${Ausarbeiten} v=${v} zu=${() => setAusarbeiten(false)} fertig=${() => { setAusarbeiten(false); laden(); }} />`}
  </div>`;
}

function Ereignis({ e, notizText, notizAuf, setNotizAuf }) {
  const dt = e.daten || {};
  const lang = notizText && notizText.length > 600;
  return html`<div class=${"ev " + e.art}>
    <${Avatar} wer=${e.wer} name=${e.wer_name} />
    <div class="blase">
      <div class="kopfzeile"><b>${e.wer_name}</b><span>${ART_TEXT[e.art] ?? e.art}</span>
        ${dt.urteil && html`<span class=${"pill " + (dt.urteil === "tragfaehig" ? "gruen" : dt.urteil === "nachbessern" ? "gelb" : "")}>${dt.urteil === "tragfaehig" ? "trägt" : dt.urteil}</span>`}
        <span style="margin-left:auto">${zeitText(e.zeit)}</span></div>
      ${e.art === "notiz" ? html`
        <div class=${"zitat" + (lang ? " einklappbar" + (notizAuf ? " auf" : "") : "")}>${notizText || e.text}</div>
        ${lang && html`<button class="btn klein geist" style="margin-top:4px" onClick=${() => setNotizAuf(!notizAuf)}>${notizAuf ? "Weniger" : "Ganze Notiz"}</button>`}`
      : e.art === "ergebnis" ? html`<${Md} text=${e.text} />
        ${dt.ergebnis_id && html`<button class="btn klein" style="margin-top:6px" onClick=${() => bus.sende("ergebnis-zeigen", dt.ergebnis_id)}><${Icon} n="auge" g=${14} />Ganzes Ergebnis</button>`}`
      : html`<${Md} text=${e.text} />`}
      ${dt.maengel && dt.maengel.length > 0 && html`<ul class="klein" style="margin:6px 0 0;padding-left:18px">${dt.maengel.map((m) => html`<li>${m}</li>`)}</ul>`}
      ${dt.quellen && dt.quellen.length > 0 && html`<details class="klein" style="margin-top:6px"><summary>${dt.quellen.length} Quellen</summary>
        <ol style="margin:4px 0 0;padding-left:18px">${dt.quellen.map((q) => html`<li><a href=${q.url} target="_blank" rel="noopener">${q.titel || q.url}</a></li>`)}</ol></details>`}
    </div>
  </div>`;
}

export function Ausarbeiten({ v, projektId, zu, fertig }) {
  const [rolle, setRolle] = useState("stratege");
  const [form, setForm] = useState("dokument");
  const [auftrag, setAuftrag] = useState(v ? (v.einordnung || v.titel || "") : "");
  const [recherche, setRecherche] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  async function los() {
    setLaeuft(true);
    try {
      if (v) await api(`/vorgaenge/${v.id}/ausarbeiten`, { methode: "POST", daten: { rolle, form, auftrag, recherche } });
      else {
        const r = await api("/erfassen", { methode: "POST", daten: { text: auftrag, projekt_id: projektId } });
        await api(`/vorgaenge/${r.vorgang_id}/ausarbeiten`, { methode: "POST", daten: { rolle, form, auftrag, recherche } });
      }
      toast("Auftrag ist raus. Das Ergebnis erscheint im Case, Daniel prüft es vorher.");
      aktualisieren(); fertig && fertig();
    } catch (e) { fehlerMelden(e); setLaeuft(false); }
  }
  return html`<${Modal} titel="Ausarbeiten lassen" zu=${zu} fuss=${html`
      <button class="btn geist" onClick=${zu}>Abbrechen</button>
      <button class="btn primaer" disabled=${laeuft || !auftrag.trim()} onClick=${los}>${laeuft ? "Einen Moment …" : "Auftrag geben"}</button>`}>
    <div class="raster" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">
      <div class="feld"><label for="aa-rolle">Wer</label><select id="aa-rolle" class="eingabe" value=${rolle} onChange=${(e) => setRolle(e.target.value)}>
        ${ROLLEN_WAHL.map(([k, t]) => html`<option value=${k}>${t}</option>`)}</select></div>
      <div class="feld"><label for="aa-form">Was soll herauskommen</label><select id="aa-form" class="eingabe" value=${form} onChange=${(e) => setForm(e.target.value)}>
        ${FORM_WAHL.map(([k, t]) => html`<option value=${k}>${t}</option>`)}</select></div>
    </div>
    <div class="feld" style="margin-top:10px"><label for="aa-auftrag">Auftrag</label>
      <textarea id="aa-auftrag" class="eingabe" rows="4" value=${auftrag} onInput=${(e) => setAuftrag(e.target.value)}></textarea></div>
    <div class="feld" style="margin-top:10px"><label for="aa-rech">Im Internet recherchieren (optional: Suchbegriffe)</label>
      <input id="aa-rech" class="eingabe" value=${recherche} placeholder="z. B. Anbieter Seebestattung Sassnitz" onInput=${(e) => setRecherche(e.target.value)} /></div>
    <p class="leise klein" style="margin-top:10px">Läuft lokal auf deinem Server. Gesucht wird über deine eigene Suchmaschine. Daniel prüft das Ergebnis vor der Vorlage, bei Mängeln wird einmal nachgebessert.</p>
  <//>`;
}
