// NEO -- mit dem Cockpit Engineer arbeiten, so wie mit Claude Code.
// Links die Gespraeche, in der Mitte Verlauf und Eingabe, rechts die Vorschau
// (Matrix-Regen, solange nichts darin steht). Neo arbeitet mit echten
// Werkzeugen als vveadmin; jeder Schritt steht aufklappbar im Verlauf.
// Ein Auftrag laeuft auf dem Server weiter, auch wenn du die Seite wechselst.
import { Zuordnung } from "./zuordnung.js";
import { useEsc, escEigen, html, useState, useEffect, useRef, Icon, Md, Leer, toast, fehlerMelden, zeitText, dauer, navigiere, kopieren, bus, Ziehgriff } from "./ui.js";
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
  // Matrix (Veiko, 01.10.): die Vorschau zeigt nur den Regen -- auch waehrend
  // Neo arbeitet. Erst wenn er in DIESEM Auftrag ein Ergebnis zeigt
  // (vorschau-Ereignis), erscheint es von selbst. Ein frueheres Ergebnis des
  // Gespraechs wird dann beim Oeffnen nicht mehr geladen.
  const [matrix, setMatrix] = useState(() => lies("vvec_neo_matrix", false));
  const [url, setUrl] = useState(null);
  const [neuLaden, setNeuLaden] = useState(0);
  const [listeOffen, setListeOffen] = useState(false);
  const [team, setTeam] = useState(null);
  const [titelBearb, setTitelBearb] = useState(null);
  const [jetzt, setJetzt] = useState(Date.now());
  const verlaufRef = useRef(null);
  const folgt = useRef(null);
  const amBoden = useRef(true);

  // Laden mit Wiederholung (24.10.2026): ein einziger gescheiterter Abruf liess die Seite fuer immer bei
  // "Lade …" stehen -- Veiko sah beim Klick aus Current Actions nichts von dem, was Neo gerade tat.
  // Jetzt steht der Grund da, und es wird alle vier Sekunden neu versucht, solange die Seite offen ist.
  const [ladeFehler, setLadeFehler] = useState("");
  const offenRef = useRef(true);
  useEffect(() => () => { offenRef.current = false; }, []);
  const listeLaden = () => api("/neo/gespraeche").then((d) => { setListe(d.gespraeche); setLadeFehler(""); return d.gespraeche; })
    .catch((e) => { setLadeFehler(e.message || "Server nicht erreichbar"); if (offenRef.current) setTimeout(listeLaden, 4000); });
  useEffect(() => { listeLaden(); api("/team").then(setTeam).catch(() => {}); }, []);
  useEffect(() => { bus.sende("talk-kontext", null); }, []);
  useEffect(() => { if (innerWidth > 820) merk("vvec_neo_vorschau", vorschauAn); }, [vorschauAn]);
  useEffect(() => {
    merk("vvec_neo_voll", voll);
    document.documentElement.classList.toggle("neo-vollbild", voll);
    return () => document.documentElement.classList.remove("neo-vollbild");
  }, [voll]);
  useEffect(() => bus.an("vollbild", (an) => setVoll(!!an)), []);
  // Escape verlaesst erst die Gespraechsliste (Telefon), dann das Vollbild --
  // was zuletzt aufging, liegt oben auf dem Stapel (ui.js).
  useEsc(() => setVoll(false), voll);
  useEsc(() => setListeOffen(false), listeOffen);
  useEffect(() => { merk("vvec_neo_matrix", matrix); }, [matrix]);
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
    let aktuell = true;
    const laden = () => api("/neo/gespraeche/" + id).then((d) => {
      if (!aktuell) return;
      setG(d); setLadeFehler("");
      const letzteVorschau = [...d.nachrichten].reverse().find((m) => m.daten && m.daten.vorschau);
      if (letzteVorschau && !lies("vvec_neo_matrix", false)) setUrl(letzteVorschau.daten.vorschau);
      if (d.job) folgen(d.job);
    }).catch((e) => {
      if (!aktuell) return;
      // Gibt es das Gespraech nicht (404), zurueck zur Liste; sonst (Netz, Dienst startet neu) erneut versuchen.
      if (e.status === 404) { fehlerMelden(e); navigiere("/neo"); return; }
      setLadeFehler(e.message || "Server nicht erreichbar");
      setTimeout(laden, 4000);
    });
    laden();
    return () => { aktuell = false; };
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
          if (e.typ === "schritt_start") { n.aktuell = e; n.zwischenNeu = false; }
          else if (e.typ === "schritt") { n.schritte.push(e); n.aktuell = null; }
          else if (e.typ === "zwischen") { n.zwischen = e.text; n.zwischenNeu = true; }
          else if (e.typ === "datei") n.dateien = [...(n.dateien || []), e];
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
      bus.sende("ki-start");
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

  // Matrix an: Regen statt Ergebnis, Spalte auf. Noch einmal, waehrend der Regen
  // laeuft: zurueck zum letzten Ergebnis dieses Gespraechs.
  function matrixUmschalten() {
    if (matrix && !url) {
      setMatrix(false);
      const letzte = g && [...g.nachrichten].reverse().find((m) => m.daten && m.daten.vorschau);
      if (letzte) setUrl(letzte.daten.vorschau);
      return;
    }
    setMatrix(true); setUrl(null); setVorschauAn(true);
  }
  const regenAn = vorschauAn && !url;

  const neoModell = team && (team.team.find((m) => m.id === "cockpit") || {}).modell;
  const nachrichten = g ? g.nachrichten : [];
  const zeigeVorschau = vorschauAn;

  return html`<div class=${"neo" + (zeigeVorschau ? " mit-vorschau" : "") + (listeOffen ? " liste-offen" : "")}>
    <aside class="neo-liste" aria-label="Gespräche mit Neo">
      <${Ziehgriff} name="neo-liste" seite="rechts" />
      <div class="kopf"><button class="btn primaer" style="width:100%" onClick=${neuesGespraech}><${Icon} n="neu" g=${15} />Neues Gespräch</button></div>
      <div class="liste">
        ${!liste ? html`<div class="lade">${ladeFehler ? `Nicht erreichbar (${ladeFehler}) -- ich versuche es weiter …` : "Lade …"}</div>` : liste.map((x) => html`<div key=${x.id} style="display:flex;align-items:center">
          <button class=${"neo-g" + (x.id === id ? " an" : "")} onClick=${() => navigiere("/neo/" + x.id)} title=${x.titel}>
            <span>${x.titel || "Gespräch"}</span>
            <small class="leise">${zeitText(x.geaendert).replace("vor ", "")}</small></button>
          ${x.id === id && !x.laeuft && html`<button class="btn klein geist icon" title="Archivieren" aria-label="Gespräch archivieren" onClick=${() => archivieren(x.id)}><${Icon} n="archiv" g=${13} /></button>`}
        </div>`)}
      </div>
    </aside>
    <section class="neo-mitte">
      <div class="neo-kopf">
        <button class="btn geist icon neo-ersatz" onClick=${() => setListeOffen(!listeOffen)} aria-label="Gespräche zeigen" title="Gespräche zeigen"><${Icon} n="liste" /></button>
        <button class="btn geist icon neo-ersatz" onClick=${neuesGespraech} aria-label="Neues Gespräch" title="Neues Gespräch"><${Icon} n="neu" g=${15} /></button>
        <h2><${Icon} n="neo" g=${18} />
          ${titelBearb !== null ? html`<input class="eingabe" value=${titelBearb} autofocus onInput=${(e) => setTitelBearb(e.target.value)} onBlur=${titelSpeichern}
              onKeyDown=${(e) => { if (e.key === "Enter") titelSpeichern(); if (escEigen(e)) setTitelBearb(null); }} />`
            : html`<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:text" title="Doppelklick zum Umbenennen" onDblClick=${() => g && setTitelBearb(g.gespraech.titel)}>${g ? g.gespraech.titel : "Neo"}</span>`}</h2>
        <${Zuordnung} gid=${id} klein=${true} />
        ${team && html`<select class="eingabe" style="width:auto;min-height:32px;font-size:12.5px" value=${neoModell || ""} onChange=${(e) => modellSetzen(e.target.value)} aria-label="Neos Modell" title="Womit Neo rechnet">
          <option value="">Vorgabe (qwen3-coder-neo)</option>
          ${team.modelle.filter((m) => !m.includes("embed")).map((m) => html`<option value=${m}>${m}</option>`)}</select>`}
        <button class=${"btn klein" + (zeigeVorschau ? " primaer" : "")} onClick=${() => setVorschauAn(!vorschauAn)} aria-pressed=${zeigeVorschau} title="Vorschau-Spalte"><${Icon} n="auge" g=${14} /><span class="txt">Vorschau</span></button>
        <button class=${"btn klein matrix-knopf" + (matrix && regenAn ? " an" : "")} onClick=${matrixUmschalten} aria-pressed=${matrix && regenAn}
          title=${matrix && regenAn ? "Zurück zum letzten Ergebnis" : "Nur Matrix-Regen in der Vorschau, bis Neo ein neues Ergebnis zeigt"}><span class="txt">Matrix</span></button>
        <button class="btn klein" onClick=${() => setVoll(!voll)} aria-pressed=${voll} title=${voll ? "Vollbild verlassen (Esc)" : "Vollbild"}><${Icon} n=${voll ? "klein" : "voll"} g=${14} /><span class="txt">${voll ? "Verlassen" : "Vollbild"}</span></button>
      </div>
      <div class="neo-verlauf" ref=${verlaufRef} onScroll=${(e) => { const v = e.target; amBoden.current = v.scrollHeight - v.scrollTop - v.clientHeight < 60; }}>
        ${!g ? html`<div class="lade">${ladeFehler ? `Gespräch nicht erreichbar (${ladeFehler}) -- ich versuche es alle vier Sekunden neu …` : "Lade Gespräch …"}</div>` : !nachrichten.length && !job ? html`<div class="karte" style="max-width:640px">
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
    <${Md} text=${(m.text || "").replace(/\[Deine Arbeitsschritte damals:[\s\S]*?\]\s*$/, "").trim()} />
    ${!schritte.length && /\[Deine Arbeitsschritte damals:/.test(m.text || "") && html`<div class="hinweisbox klein" style="margin-top:6px">Diese Antwort beschreibt Arbeit, die nicht stattgefunden hat: Neo hat dabei kein einziges Werkzeug benutzt. Seit dem 01.10. wird das erkannt und Neo zurückgeschickt.</div>`}
    ${(d.dateien || []).some((f) => f.download) && html`<div>${d.dateien.filter((f) => f.download).map((f) => html`
      <a class="datei-chip" href=${f.download} download><${Icon} n="download" g=${14} />${f.name}</a>`)}</div>`}
    ${(d.dateien || []).some((f) => !f.download) && html`<div style="margin-top:8px" class="klein"><b>Geänderte Dateien:</b>
      <ul style="margin:2px 0 0;padding-left:18px">${d.dateien.filter((f) => !f.download).map((f) => html`<li><code>${f.pfad}</code>${f.begruendung ? " · " + f.begruendung : ""}</li>`)}</ul></div>`}
    ${d.vorschau && html`<button class="btn klein" style="margin-top:8px" onClick=${() => zeigen(d.vorschau)}><${Icon} n="auge" g=${13} />Ergebnis in der Vorschau</button>`}
    ${schritte.length > 0 && html`<details class="schritte"><summary>${schritte.length} Arbeitsschritte</summary>
      ${schritte.map((s, i) => html`<details class="schritt" key=${i}><summary><span class="name">${s.name}</span> ${s.kurz}</summary><pre>${s.ergebnis}</pre></details>`)}</details>`}
  </div>`;
}

// Ein Arbeitsschritt in einem Satz -- dieselbe Uebersetzung wie neo.klartext im Backend (24.10.2026, Veiko:
// "bei Neo moechte ich deutlich mehr sehen, was gerade passiert"; "datei_lesen(pfad=…)" sagte ihm nichts).
function klartext(name, kurz) {
  const w = {};
  for (const m of String(kurz || "").matchAll(/(\w+)=([^,]*)/g)) w[m[1]] = m[2].trim();
  const pfad = (w.pfad || w.nach || "").replace(/^.*\/vve-cp-r2\//, "").replace(/^~\/vve-cp-r2\//, "");
  return ({ datei_lesen: `liest ${pfad}${w.ab_zeile ? " ab Zeile " + w.ab_zeile : ""}`, suche: `sucht nach „${w.text || ""}“`,
    projektwissen: `schlägt in der Doku nach: ${w.thema || ""}`, datei_aendern: `ändert ${pfad}`, datei_schreiben: `schreibt ${pfad}`,
    datei_kopieren: `kopiert nach ${pfad}`, befehl_ausfuehren: `führt aus: ${(w.befehl || "").slice(0, 80)}`,
    vorschau_zeigen: "zeigt das Ergebnis in der Vorschau", dokument_erstellen: "erstellt ein Dokument" })[name] || `${name} ${kurz || ""}`;
}

function Laeuft({ job, jetzt, abbrechen }) {
  const sek = jetzt / 1000 - job.start;
  // Was gerade passiert, als ganzer Satz: ein Werkzeug, eine Meldung des Cockpits (z. B. "Dario prüft …")
  // oder das Nachdenken zwischen zwei Schritten.
  const akt = job.aktuell ? klartext(job.aktuell.name, job.aktuell.kurz)
    : job.zwischen && job.zwischenNeu ? job.zwischen.replace(/^\(|\)$/g, "")
    : job.schritte.length ? "denkt über das Ergebnis nach" : "liest den Auftrag";
  const aendert = job.schritte.filter((s) => s.name === "datei_aendern" || s.name === "datei_schreiben").length;
  return html`<div>
    <div class="laeuft-zeile" role="status">
      <${MatrixZeichen} />
      <div class="text"><b>${!job.aktuell && job.zwischen && job.zwischenNeu ? akt : "Neo " + akt}</b><small>seit ${dauer(sek)} · ${job.schritte.length} Schritte${aendert ? ` · ${aendert} Änderungen vorgemerkt` : ""}${job.modell ? " · " + job.modell : ""}</small></div>
      <button class="btn klein gefahr" onClick=${abbrechen}><${Icon} n="stopp" g=${12} />Abbrechen</button>
    </div>
    ${job.zwischen && html`<div class="neo-beitrag" style="margin-top:8px;opacity:.85"><${Md} text=${job.zwischen} /></div>`}
    ${(job.dateien || []).length > 0 && html`<div>${job.dateien.map((f) => html`<a class="datei-chip" href=${f.url} download><${Icon} n="download" g=${14} />${f.name}</a>`)}</div>`}
    ${job.schritte.length > 0 && html`<div class="neo-protokoll" aria-label="Was Neo bisher getan hat">
      ${job.schritte.slice(-15).map((s, i) => html`<details class="neo-protokoll-zeile" key=${i}>
        <summary><span class="neo-haken">✓</span>${klartext(s.name, s.kurz)}</summary><pre>${s.ergebnis}</pre></details>`)}
      ${job.aktuell && html`<div class="neo-protokoll-zeile jetzt"><span class="neo-haken">▶</span>${klartext(job.aktuell.name, job.aktuell.kurz)} …</div>`}
    </div>`}
  </div>`;
}

function Vorschau({ url, neuLaden, zu, setUrl, beispiel }) {
  const [frueher, setFrueher] = useState([]);
  useEffect(() => { if (!url) api("/neo/vorschauen").then((d) => setFrueher(d.vorschauen)).catch(() => {}); }, [url]);
  return html`<aside class="neo-vorschau" aria-label="Vorschau">
    <${Ziehgriff} name="neo-vorschau" seite="links" />
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
        <div class="hinweis-unten">
          <span>› Hier erscheint das Ergebnis, sobald es vorliegt.</span>
          ${frueher.length > 0 && html`<span style="margin-left:auto">${frueher.slice(0, 3).map((f) => html`<button onClick=${() => setUrl(f.url)} title="Frühere Vorschau öffnen">${f.name}</button> `)}</span>`}
          <button onClick=${zu} title="Vorschau-Spalte schließen" aria-label="Vorschau schließen">×</button>
        </div>
      <//>`}
  </aside>`;
}
