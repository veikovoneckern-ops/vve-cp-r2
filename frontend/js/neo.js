// NEO -- mit dem Cockpit Engineer arbeiten, so wie mit Claude Code.
// Links die Gespraeche, in der Mitte Verlauf und Eingabe, rechts die Vorschau
// (Matrix-Regen, solange nichts darin steht). Neo arbeitet mit echten
// Werkzeugen als vveadmin; jeder Schritt steht aufklappbar im Verlauf.
// Ein Auftrag laeuft auf dem Server weiter, auch wenn du die Seite wechselst.
import { html, useState, useEffect, useRef, Icon, Md, Leer, toast, fehlerMelden, zeitText, dauer, navigiere, kopieren, bus } from "./ui.js";
import { api } from "./api.js";
import { Composer } from "./composer.js";
import { MatrixRegen, MatrixZeichen } from "./matrix.js";

const lies = (k, v) => { try { const x = localStorage.getItem(k); return x === null ? v : x === "1"; } catch (e) { return v; } };
const merk = (k, v) => { try { localStorage.setItem(k, v ? "1" : "0"); } catch (e) { /* egal */ } };

const BEISPIELE = [
  "Wie ist die neue Cockpit-Fassung aufgebaut? Sieh im Repo nach und erklär es mir in fünf Sätzen.",
  "Prüf, ob alle Dienste auf dem Server laufen, und sag mir, was auffällt.",
  "Bau mir eine kleine Seite, die meine Projekte als Kacheln zeigt, und zeig sie in der Vorschau.",
];

export function Neo({ id }) {
  const [liste, setListe] = useState(null);
  const [g, setG] = useState(null); // {gespraech, nachrichten}
  const [job, setJob] = useState(null); // {jid, ab, schritte, aktuell, zwischen, start, modell}
  // Auf dem Telefon liegt die Vorschau UEBER dem Gespraech -- dort startet sie
  // deshalb immer zu, egal was am Rechner eingestellt ist.
  const [vorschauAn, setVorschauAn] = useState(() => innerWidth > 820 && lies("vvec_neo_vorschau", innerWidth > 1100));
  const [voll, setVoll] = useState(() => lies("vvec_neo_voll", false));
  const [url, setUrl] = useState(null);
  const [neuLaden, setNeuLaden] = useState(0);
  const [listeOffen, setListeOffen] = useState(false);
  const [team, setTeam] = useState(null);
  const [titelBearb, setTitelBearb] = useState(null);
  const [jetzt, setJetzt] = useState(Date.now());
  const verlaufRef = useRef(null);
  const folgt = useRef(null);
  const amBoden = useRef(true);

  const listeLaden = () => api("/neo/gespraeche").then((d) => { setListe(d.gespraeche); return d.gespraeche; }).catch(fehlerMelden);
  useEffect(() => { listeLaden(); api("/team").then(setTeam).catch(() => {}); }, []);
  useEffect(() => { bus.sende("talk-kontext", null); }, []);
  useEffect(() => { if (innerWidth > 820) merk("vvec_neo_vorschau", vorschauAn); }, [vorschauAn]);
  useEffect(() => {
    merk("vvec_neo_voll", voll);
    document.documentElement.classList.toggle("neo-vollbild", voll);
    return () => document.documentElement.classList.remove("neo-vollbild");
  }, [voll]);
  useEffect(() => bus.an("vollbild", (an) => setVoll(!!an)), []);
  useEffect(() => { if (!job) return; const i = setInterval(() => setJetzt(Date.now()), 1000); return () => clearInterval(i); }, [!!job]);

  // Ohne Kennung: das juengste Gespraech oeffnen, sonst ein neues anlegen.
  useEffect(() => {
    if (id || !liste) return;
    if (liste.length) navigiere("/neo/" + liste[0].id);
    else neuesGespraech();
  }, [id, liste]);

  useEffect(() => {
    if (!id) return;
    folgt.current = null; setJob(null); setG(null); setUrl(null); setListeOffen(false);
    api("/neo/gespraeche/" + id).then((d) => {
      setG(d);
      const letzteVorschau = [...d.nachrichten].reverse().find((m) => m.daten && m.daten.vorschau);
      if (letzteVorschau) setUrl(letzteVorschau.daten.vorschau);
      if (d.job) folgen(d.job);
    }).catch((e) => { fehlerMelden(e); navigiere("/neo"); });
  }, [id]);

  useEffect(() => {
    const v = verlaufRef.current;
    if (v && amBoden.current) v.scrollTop = v.scrollHeight;
  }, [g, job]);

  async function neuesGespraech() {
    try { const n = await api("/neo/gespraeche", { methode: "POST" }); await listeLaden(); navigiere("/neo/" + n.id); } catch (e) { fehlerMelden(e); }
  }

  async function folgen(jid) {
    folgt.current = jid;
    let ab = 0;
    setJob({ jid, schritte: [], aktuell: null, zwischen: "", start: Date.now() / 1000, modell: "" });
    while (folgt.current === jid) {
      let d;
      try { d = await api(`/neo/job/${jid}?ab=${ab}`); } catch (e) { await new Promise((r) => setTimeout(r, 3000)); continue; }
      if (folgt.current !== jid) return;
      ab = d.naechste;
      setJob((j) => {
        if (!j) return j;
        const n = { ...j, start: d.start || j.start, modell: d.modell || j.modell, schritte: [...j.schritte] };
        for (const e of d.ereignisse || []) {
          if (e.typ === "schritt_start") n.aktuell = e;
          else if (e.typ === "schritt") { n.schritte.push(e); n.aktuell = null; }
          else if (e.typ === "zwischen") n.zwischen = e.text;
          else if (e.typ === "vorschau") { setUrl(e.url); setVorschauAn(true); setNeuLaden((x) => x + 1); }
        }
        return n;
      });
      if (d.fertig) break;
    }
    if (folgt.current !== jid) return;
    folgt.current = null;
    try { setG(await api("/neo/gespraeche/" + id)); } catch (e) { /* egal */ }
    setJob(null);
    listeLaden();
  }

  async function senden(text, anhaenge, namen) {
    if (!g) return false;
    const gid = g.gespraech.id;
    setG((x) => ({ ...x, nachrichten: [...x.nachrichten, { id: "d" + Date.now(), rolle: "du", text, daten: { anzeige: text, anhaenge: namen }, zeit: Date.now() / 1000 }] }));
    amBoden.current = true;
    try {
      const r = await api(`/neo/${gid}/senden`, { methode: "POST", daten: { text, anhaenge } });
      folgen(r.job);
      return true;
    } catch (e) { fehlerMelden(e); return false; }
  }

  async function abbrechen() {
    if (!job) return;
    try { await api(`/neo/job/${job.jid}/abbrechen`, { methode: "POST" }); toast("Neo hört auf. Was er bis hierhin getan hat, bleibt stehen."); } catch (e) { fehlerMelden(e); }
  }

  async function modellSetzen(m) {
    try { await api("/team/cockpit", { methode: "PATCH", daten: { modell: m } }); toast(`Neo rechnet ab dem nächsten Auftrag mit ${m}.`); setTeam(await api("/team")); } catch (e) { fehlerMelden(e); }
  }
  async function titelSpeichern() {
    const t = (titelBearb || "").trim(); setTitelBearb(null);
    if (!t || !g || t === g.gespraech.titel) return;
    try { await api("/neo/gespraeche/" + g.gespraech.id, { methode: "PATCH", daten: { titel: t } }); setG((x) => ({ ...x, gespraech: { ...x.gespraech, titel: t } })); listeLaden(); } catch (e) { fehlerMelden(e); }
  }
  async function archivieren(gid) {
    try { await api("/neo/gespraeche/" + gid, { methode: "DELETE" }); toast("Gespräch archiviert."); const l = await listeLaden(); if (gid === id) navigiere(l && l.length ? "/neo/" + l[0].id : "/neo"); } catch (e) { fehlerMelden(e); }
  }

  const neoModell = team && (team.team.find((m) => m.id === "cockpit") || {}).modell;
  const nachrichten = g ? g.nachrichten : [];
  const zeigeVorschau = vorschauAn;

  return html`<div class=${"neo" + (zeigeVorschau ? " mit-vorschau" : "") + (listeOffen ? " liste-offen" : "")}>
    <aside class="neo-liste" aria-label="Gespräche mit Neo">
      <div class="kopf"><button class="btn primaer" style="width:100%" onClick=${neuesGespraech}><${Icon} n="neu" g=${15} />Neues Gespräch</button></div>
      <div class="liste">
        ${!liste ? html`<div class="lade">Lade …</div>` : liste.map((x) => html`<div key=${x.id} style="display:flex;align-items:center">
          <button class=${"neo-g" + (x.id === id ? " an" : "")} onClick=${() => navigiere("/neo/" + x.id)} title=${x.titel}>
            ${x.laeuft && html`<span class="punkt" style="background:var(--matrix)"></span>`}<span>${x.titel || "Gespräch"}</span>
            <small class="leise">${zeitText(x.geaendert).replace("vor ", "")}</small></button>
          ${x.id === id && !x.laeuft && html`<button class="btn klein geist icon" title="Archivieren" aria-label="Gespräch archivieren" onClick=${() => archivieren(x.id)}><${Icon} n="archiv" g=${13} /></button>`}
        </div>`)}
      </div>
    </aside>
    <section class="neo-mitte">
      <div class="neo-kopf">
        <button class="btn geist icon nur-mobil" onClick=${() => setListeOffen(!listeOffen)} aria-label="Gespräche zeigen"><${Icon} n="liste" /></button>
        <h2><${Icon} n="neo" g=${18} />
          ${titelBearb !== null ? html`<input class="eingabe" value=${titelBearb} autofocus onInput=${(e) => setTitelBearb(e.target.value)} onBlur=${titelSpeichern}
              onKeyDown=${(e) => { if (e.key === "Enter") titelSpeichern(); if (e.key === "Escape") setTitelBearb(null); }} />`
            : html`<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:text" title="Doppelklick zum Umbenennen" onDblClick=${() => g && setTitelBearb(g.gespraech.titel)}>${g ? g.gespraech.titel : "Neo"}</span>`}</h2>
        ${team && html`<select class="eingabe" style="width:auto;min-height:32px;font-size:12.5px" value=${neoModell || ""} onChange=${(e) => modellSetzen(e.target.value)} aria-label="Neos Modell" title="Womit Neo rechnet">
          <option value="">Vorgabe (qwen3-coder-neo)</option>
          ${team.modelle.filter((m) => !m.includes("embed")).map((m) => html`<option value=${m}>${m}</option>`)}</select>`}
        <button class=${"btn klein" + (zeigeVorschau ? " primaer" : "")} onClick=${() => setVorschauAn(!vorschauAn)} aria-pressed=${zeigeVorschau} title="Vorschau-Spalte"><${Icon} n="auge" g=${14} />Vorschau</button>
        <button class="btn klein" onClick=${() => setVoll(!voll)} aria-pressed=${voll} title=${voll ? "Vollbild verlassen (Esc)" : "Vollbild"}><${Icon} n=${voll ? "klein" : "voll"} g=${14} />${voll ? "Verlassen" : "Vollbild"}</button>
      </div>
      <div class="neo-verlauf" ref=${verlaufRef} onScroll=${(e) => { const v = e.target; amBoden.current = v.scrollHeight - v.scrollTop - v.clientHeight < 60; }}>
        ${!g ? html`<div class="lade">Lade Gespräch …</div>` : !nachrichten.length && !job ? html`<div class="karte" style="max-width:640px">
            <h3 style="margin-bottom:6px">Mit Neo arbeiten</h3>
            <p class="leise">Neo ist dein Cockpit Engineer. Er liest und schreibt Dateien und führt Befehle auf dem Server aus, mit denselben Rechten wie du über SSH (ohne sudo). Jeder Schritt steht hier aufklappbar. Er arbeitet weiter, auch wenn du die Seite wechselst.</p>
            <div style="display:flex;flex-direction:column;gap:6px;margin-top:10px">${BEISPIELE.map((b) => html`<button class="btn" style="justify-content:flex-start;white-space:normal;text-align:left" onClick=${() => senden(b, [], [])}>${b}</button>`)}</div>
          </div>`
          : nachrichten.map((m) => html`<${Beitrag} key=${m.id} m=${m} zeigen=${(u) => { setUrl(u); setVorschauAn(true); setNeuLaden((x) => x + 1); }} />`)}
        ${job && html`<${Laeuft} job=${job} jetzt=${jetzt} abbrechen=${abbrechen} />`}
      </div>
      <div class="neo-eingabe">
        <${Composer} platzhalter=${job ? "Neo arbeitet … mit dem roten Knopf brichst du ab" : "Auftrag an Neo … (Enter senden, Umschalt+Enter neue Zeile)"}
          beimSenden=${senden} laeuft=${!!job} beimStoppen=${abbrechen} entwurfKey=${"neo:" + (id || "")} zeilen=${2} autofocus=${true}
          hinweis="Anhänge legt Neo auf dem Server ab und liest sie. Er führt Befehle sofort aus." sendenText="An Neo" />
      </div>
    </section>
    ${zeigeVorschau && html`<${Vorschau} url=${url} neuLaden=${neuLaden} zu=${() => setVorschauAn(false)} setUrl=${setUrl} beispiel=${() => senden(BEISPIELE[2], [], [])} />`}
  </div>`;
}

function Beitrag({ m, zeigen }) {
  const d = m.daten || {};
  if (m.rolle === "du") {
    return html`<div class="neo-beitrag du">
      <div class="kopfzeile"><b>Du</b><span>${zeitText(m.zeit)}</span>
        ${(d.anhaenge || []).map((a) => html`<span class="pill"><${Icon} n="clip" g=${11} />${a}</span>`)}</div>
      <div class="text">${d.anzeige ?? m.text}</div></div>`;
  }
  const schritte = d.schritte || [];
  return html`<div class="neo-beitrag">
    <div class="kopfzeile"><b>Neo</b><span>${zeitText(m.zeit)}</span>${d.dauer != null && html`<span>${dauer(d.dauer)}</span>`}
      ${d.modell && html`<span class="mono klein">${d.modell}</span>`}${d.abgebrochen && html`<span class="pill gelb">abgebrochen</span>`}
      <button class="btn klein geist" style="margin-left:auto" onClick=${async () => { if (await kopieren(m.text)) toast("Kopiert."); }} title="Antwort kopieren"><${Icon} n="kopie" g=${13} /></button></div>
    <${Md} text=${m.text} />
    ${(d.dateien || []).length > 0 && html`<div style="margin-top:8px" class="klein"><b>Geänderte Dateien:</b>
      <ul style="margin:2px 0 0;padding-left:18px">${d.dateien.map((f) => html`<li><code>${f.pfad}</code>${f.begruendung ? " · " + f.begruendung : ""}</li>`)}</ul></div>`}
    ${d.vorschau && html`<button class="btn klein" style="margin-top:8px" onClick=${() => zeigen(d.vorschau)}><${Icon} n="auge" g=${13} />Ergebnis in der Vorschau</button>`}
    ${schritte.length > 0 && html`<details class="schritte"><summary>${schritte.length} Arbeitsschritte</summary>
      ${schritte.map((s, i) => html`<details class="schritt" key=${i}><summary><span class="name">${s.name}</span> ${s.kurz}</summary><pre>${s.ergebnis}</pre></details>`)}</details>`}
  </div>`;
}

function Laeuft({ job, jetzt, abbrechen }) {
  const sek = jetzt / 1000 - job.start;
  const akt = job.aktuell ? `${job.aktuell.name}(${job.aktuell.kurz})` : job.schritte.length ? "denkt über das Ergebnis nach" : "liest den Auftrag";
  return html`<div>
    <div class="laeuft-zeile" role="status">
      <${MatrixZeichen} />
      <div class="text"><b>Neo arbeitet …</b><small>${dauer(sek)} · ${job.schritte.length} Schritte · ${akt}${job.modell ? " · " + job.modell : ""}</small></div>
      <button class="btn klein gefahr" onClick=${abbrechen}><${Icon} n="stopp" g=${12} />Abbrechen</button>
    </div>
    ${job.zwischen && html`<div class="neo-beitrag" style="margin-top:8px;opacity:.85"><${Md} text=${job.zwischen} /></div>`}
    ${job.schritte.length > 0 && html`<details class="schritte" open style="margin-top:6px"><summary>Schritte bisher</summary>
      ${job.schritte.slice(-12).map((s, i) => html`<details class="schritt" key=${i}><summary><span class="name">${s.name}</span> ${s.kurz}</summary><pre>${s.ergebnis}</pre></details>`)}</details>`}
  </div>`;
}

function Vorschau({ url, neuLaden, zu, setUrl, beispiel }) {
  const [frueher, setFrueher] = useState([]);
  useEffect(() => { if (!url) api("/neo/vorschauen").then((d) => setFrueher(d.vorschauen)).catch(() => {}); }, [url]);
  return html`<aside class="neo-vorschau" aria-label="Vorschau">
    ${url ? html`
      <div class="adresse">
        <code title=${url}>${url}</code>
        <button class="btn klein geist icon" onClick=${() => setUrl(url + (url.includes("?") ? "&" : "?") + "r=" + Date.now())} title="Neu laden" aria-label="Neu laden"><${Icon} n="neu_laden" g=${14} /></button>
        <a class="btn klein geist icon" href=${url} target="_blank" rel="noopener" title="In neuem Tab" aria-label="In neuem Tab öffnen"><${Icon} n="extern" g=${14} /></a>
        <button class="btn klein geist icon" onClick=${() => setUrl(null)} title="Leeren" aria-label="Vorschau leeren"><${Icon} n="x" g=${14} /></button>
        <button class="btn klein geist icon" onClick=${zu} title="Vorschau-Spalte schließen" aria-label="Vorschau schließen"><${Icon} n="rechts" g=${14} /></button>
      </div>
      <iframe key=${url + neuLaden} src=${url} sandbox="allow-scripts allow-forms allow-popups" title="Vorschau von Neos Ergebnis"></iframe>`
    : html`<${MatrixRegen}>
        <div class="tafel">
          <b>&gt; vorschau_bereit_</b>
          Hier erscheint, was Neo baut. Bitte ihn zum Beispiel, eine Seite zu bauen und in der Vorschau zu zeigen. Er legt sie auf deinem Server ab, abgeschottet vom Cockpit.
          <div><button onClick=${beispiel}>Beispiel ausprobieren</button> <button onClick=${zu}>Vorschau schließen</button></div>
          ${frueher.length > 0 && html`<div style="margin-top:10px">Frühere Vorschauen:
            ${frueher.slice(0, 5).map((f) => html`<div><button style="margin-top:4px" onClick=${() => setUrl(f.url)}>${f.name}</button></div>`)}</div>`}
        </div>
      <//>`}
  </aside>`;
}
