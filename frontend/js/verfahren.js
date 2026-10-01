// BRAINSTROM UND ExO -- 1:1 aus dem alten Cockpit (Fenster "BrainStrom — aus
// einer Idee ein Vorhaben" und "ExO — Exponential-Organizations-Analyse"),
// hier als eigene Bereiche mit Knopf links.
//
// Der Stand liegt auf dem Server (cockpit/verfahren.py), nicht im Browser:
// Talk kann deshalb mitmachen. Wer in BrainStrom auf "Sprechen" tippt, hoert die
// offene Frage vorgelesen und antwortet einfach -- die Antwort landet in
// derselben Frage, die hier auf dem Bildschirm steht. Die Ansicht fragt den
// Stand ab, solange etwas rechnet, und zieht nach jeder Talk-Antwort nach.
//
// Es geht nichts in die Cloud: beide rechnen ausschliesslich auf Ollama.
import { html, useState, useEffect, useRef, Icon, Md, toast, fehlerMelden, bus, navigiere, dauer } from "./ui.js";
import { api } from "./api.js";
import { Composer } from "./composer.js";

function useStand(pfad, art) {
  const [s, setS] = useState(null);
  const laden = () => api(pfad).then(setS).catch(fehlerMelden);
  useEffect(() => {
    laden();
    const sicht = () => { if (!document.hidden) laden(); };
    document.addEventListener("visibilitychange", sicht);
    const aus = bus.an("verfahren-neu", laden);
    return () => { aus(); document.removeEventListener("visibilitychange", sicht); };
  }, []);
  // Solange gerechnet wird: alle 1,5 s; sonst alle 6 s (Talk kann den Stand aendern).
  useEffect(() => {
    const i = setInterval(() => { if (!document.hidden) laden(); }, s && s.laeuft ? 1500 : 6000);
    return () => clearInterval(i);
  }, [s && s.laeuft]);
  useEffect(() => {
    bus.sende("talk-kontext", { art, id: art, titel: art === "exo" ? "ExO" : "BrainStrom" });
    return () => bus.sende("talk-kontext", null);
  }, []);
  return [s, setS, laden];
}

async function tun(pfad, daten, setS) {
  try { const r = await api(pfad, { methode: "POST", daten: daten || {} }); if (r && setS && r.phase !== undefined) setS(r); return r; }
  catch (e) { fehlerMelden(e); return null; }
}

function ProjektWahl({ wert, setzen, projekte, label = "Projekt" }) {
  return html`<label class="vf-lbl">${label}
    <select class="eingabe" value=${wert || ""} onChange=${(e) => setzen(e.target.value || null)}>
      <option value="">— ohne Projekt —</option>
      ${projekte.filter((p) => p.status !== "archiviert").map((p) => html`<option value=${p.id}>${p.name}</option>`)}
    </select></label>`;
}

function Schritte({ namen, jetzt }) {
  return html`<div class="vf-schritte">${namen.map((n, i) => html`${i ? html`<span class="vf-pfeil">›</span>` : null}
    <span class=${"vf-schritt" + (i < jetzt ? " fertig" : i === jetzt ? " jetzt" : "")}><i>${i < jetzt ? "✓" : i + 1}</i>${n}</span>`)}</div>`;
}

// Ein lokales Modell braucht fuer einen Entwurf schon mal eine Minute; eine Minute
// ohne Lebenszeichen fuehlt sich an wie ein Absturz. Deshalb Uhr und Balken.
function Arbeit({ text, seit }) {
  const [jetzt, setJetzt] = useState(Date.now());
  useEffect(() => { const i = setInterval(() => setJetzt(Date.now()), 1000); return () => clearInterval(i); }, []);
  return html`<div class="vf-lauf" role="status">
    <div class="vf-lauf-kopf"><span class="vf-spin"></span><b>${text}</b><span class="leise klein">${seit ? dauer(jetzt / 1000 - seit) : ""}</span></div>
    <div class="vf-balken"><i></i></div>
    <div class="leise klein">Das Modell rechnet auf dem eigenen Server. Es läuft weiter, auch wenn du die Seite wechselst.</div>
  </div>`;
}

function Fehler({ text }) {
  if (!text) return null;
  const bild = /multimodal/i.test(text);
  return html`<div class="fehlerbox"><b>${bild ? "Das eingestellte Modell kann keine Bilder lesen." : "Das lokale Modell hat nicht geliefert."}</b><br />${text}
    ${!bild && html`<br /><span class="klein">Ein zweiter Versuch hilft bei einem Zeitablauf oft schon.</span>`}</div>`;
}

function Fuss({ modell, children }) {
  return html`<div class="vf-fuss"><span>Antwortet: <b>${modell || "ein lokales Modell"}</b> auf dem eigenen Server — kein Cloud-Modell im Datenweg.</span>
    <span class="knopfreihe">${children}</span></div>`;
}

// Eine Rueckfrage direkt am Knopf -- wie ueberall in dieser Fassung.
function FrageKnopf({ text, frage, ja, tun: aktion, klasse = "" }) {
  const [auf, setAuf] = useState(false);
  if (auf) return html`<span class="knopfreihe"><span class="klein">${frage}</span>
    <button class="btn klein primaer" onClick=${() => { setAuf(false); aktion(); }}>${ja}</button>
    <button class="btn klein geist" onClick=${() => setAuf(false)}>Abbrechen</button></span>`;
  return html`<button class=${"btn klein " + klasse} onClick=${() => setAuf(true)}>${text}</button>`;
}

function useProjekte() {
  const [p, setP] = useState([]);
  useEffect(() => { api("/projekte").then((d) => setP(d.projekte)).catch(() => {}); }, []);
  return p;
}

// ================================================================ BrainStrom
export function BrainStrom() {
  const [s, setS, laden] = useStand("/brainstrom", "brainstrom");
  const projekte = useProjekte();
  const [arbeitet, setArbeitet] = useState(false);
  const bs = (pfad, daten) => tun("/brainstrom/" + pfad, daten, setS);
  if (!s) return html`<div class="lade">Lade BrainStrom …</div>`;
  const stufe = s.phase === "start" ? 0 : s.phase === "frage" ? 1 : s.phase === "wege" ? 2 : 3;

  async function uebernehmen() {
    setArbeitet(true);
    const r = await tun("/brainstrom/uebernehmen");
    setArbeitet(false);
    if (r && r.projekt_id) { toast(`${r.aufgaben} Aufgaben angelegt.`); navigiere("/projects/" + r.projekt_id + "/aufgaben"); }
    laden();
  }
  async function alsErgebnis() {
    const r = await tun("/brainstrom/ergebnis");
    if (r && r.ergebnis_id) toast("Als Ergebnis gespeichert.", { aktion: { text: "Ansehen", fn: () => bus.sende("ergebnis-zeigen", r.ergebnis_id) } });
    laden();
  }

  return html`<div class="vf">
    <div class="vf-kopf">
      <h2>BrainStrom — aus einer Idee ein Vorhaben</h2>
      <span class="leise klein vf-unter">eine Frage nach der anderen</span>
      <span class="luecke"></span>
      <${ProjektWahl} wert=${s.projekt_id} projekte=${projekte} setzen=${(pid) => bs("projekt", { projekt_id: pid })} />
    </div>
    <${Schritte} namen=${["Thema", "Fragen", "Wege", "Entwurf"]} jetzt=${stufe} />
    <div class="vf-leib">
      <${Fehler} text=${s.fehler} />
      ${s.fehler && !s.laeuft && s.letzte_art && html`<div style="margin:-4px 0 12px"><button class="btn klein" onClick=${() => bs("nochmal")}><${Icon} n="neu_laden" g=${12} />Noch einmal versuchen</button></div>`}
      ${s.verlauf.length > 0 && s.phase !== "start" && html`<div class="vf-verlauf">${s.verlauf.map((v, i) => html`<div class="vf-vz" key=${i}>
        <span class="f">${v.frage}</span><span class="a">${v.antwort}</span></div>`)}</div>`}
      ${s.laeuft || arbeitet ? html`<${Arbeit} text=${arbeitet ? "Legt Projekt und Aufgaben an …" : s.was || "Denkt nach …"} seit=${s.seit} />`
        : s.phase === "start" ? html`<div class="vf-frage">
            <span class="nr">Schritt 1</span><p>Worum geht es?</p>
            <div class="warum">Ein, zwei Sätze reichen. Die Zuspitzung passiert danach — eine Frage nach der anderen. Du kannst tippen, diktieren oder sprechen (oben auf Sprechen).</div>
            <${Composer} platzhalter="Zum Beispiel: Wie bekomme ich die Führungskräfte-Entwicklung von Präsenz auf hybrid, ohne dass die Wirkung verloren geht?"
              zeilen=${3} entwurfKey="brainstrom-thema" sendenText="Losgehen" projektId=${s.projekt_id || ""} autofokus=${true}
              beimSenden=${async (t, anh) => !!(await bs("start", { thema: t, projekt_id: s.projekt_id, anhaenge: anh }))} />
          </div>`
        : s.phase === "frage" && s.frage ? html`<div class="vf-frage">
            <span class="nr">Frage ${s.verlauf.length + 1} von höchstens 8</span>
            <p>${s.frage.text}</p>
            ${s.frage.warum && html`<div class="warum">${s.frage.warum}</div>`}
            ${(s.frage.optionen || []).length > 0 && html`<div class="vf-opt">${s.frage.optionen.map((o) => html`
              <button type="button" class="btn" onClick=${() => bs("antwort", { text: o })}>${o}</button>`)}</div>`}
            <${Composer} platzhalter="Eigene Antwort — oder oben eine auswählen" zeilen=${2} entwurfKey="brainstrom-antwort" sendenText="Weiter"
              erlaubeAnhang=${false} autofokus=${true} beimSenden=${async (t) => !!(await bs("antwort", { text: t }))} />
            <div class="vf-quelle">Genug gefragt? <button class="btn klein" onClick=${() => bs("genug")}>Direkt zu den Wegen</button></div>
          </div>`
        : s.phase === "wege" && s.wege ? html`<div class="vf-wege">${s.wege.map((w, i) => html`
            <button type="button" class="vf-weg" onClick=${() => bs("weg", { nummer: i })}>
              <b>${w.name || "Weg " + (i + 1)}</b><div class="kern">${w.kern || ""}</div>
              <div class="abw dafuer"><i>dafür:</i> ${w.dafuer || "—"}</div>
              <div class="abw dagegen"><i>dagegen:</i> ${w.dagegen || "—"}</div></button>`)}</div>
            <div class="vf-quelle">Ein Klick wählt den Weg — der Entwurf wird darauf geschrieben.</div>`
        : s.phase === "fertig" ? html`<div class="vf-dok"><${Md} text=${s.entwurf} /></div>
            ${s.funde && html`<div class="vf-pruef"><b>Selbstprüfung des Entwurfs${s.funde.length ? ` — ${s.funde.length} Punkt${s.funde.length === 1 ? "" : "e"}` : " — nichts gefunden"}</b>
              ${s.funde.length ? s.funde.map((f) => html`<div class="vf-fund"><span>${f.art || "Punkt"}</span><div><b>${f.stelle || ""}</b> ${f.text || ""}</div></div>`)
                : html`<div class="vf-fund"><div>Das Modell hat im eigenen Entwurf keine Platzhalter, Widersprüche oder offenen Mehrdeutigkeiten gefunden. Das ist ein Befund des Modells über sich selbst — kein Gütesiegel.</div></div>`}</div>`}`
        : null}
    </div>
    <${Fuss} modell=${s.modell}>
      ${s.phase !== "start" && !s.laeuft && html`<${FrageKnopf} text="Neu anfangen" frage="Die bisherigen Fragen, Antworten und der Entwurf gehen verloren." ja="Neu anfangen" tun=${() => bs("neu")} />`}
      ${s.phase === "fertig" && !s.laeuft && !arbeitet && html`
        <button class="btn klein" onClick=${() => bs("pruefen")}>Selbstprüfung</button>
        ${s.ergebnis_id ? html`<button class="btn klein" onClick=${() => bus.sende("ergebnis-zeigen", s.ergebnis_id)}><${Icon} n="auge" g=${13} />Ergebnis ansehen</button>`
          : html`<button class="btn klein" onClick=${alsErgebnis} title="Als Ergebnis speichern (ansehen, als Word herunterladen)">Als Ergebnis</button>`}
        ${s.projekt_angelegt ? html`<button class="btn klein" onClick=${() => navigiere("/projects/" + s.projekt_angelegt)}>Zum Projekt</button>`
          : html`<${FrageKnopf} klasse="primaer" text="Als Projekt mit Aufgaben" frage=${s.projekt_id ? "Die Aufgaben kommen in das gewählte Projekt." : "Ein neues Projekt mit den ersten Aufgaben anlegen?"} ja="Anlegen" tun=${uebernehmen} />`}`}
    </${Fuss}>
  </div>`;
}

// ================================================================ ExO
const SCALE = [["S", "Staff on Demand", "Arbeit von außen statt fester Kopfzahl"], ["C", "Community & Crowd", "ein Kreis von Beteiligten außerhalb der Organisation"],
  ["A", "Algorithms", "Entscheidungen, die auf Daten laufen statt auf Bauchgefühl"], ["L", "Leveraged Assets", "geliehene statt besessene Mittel"],
  ["E", "Engagement", "Bindung durch Rückmeldung, Wettbewerb, Anerkennung"]];
const IDEAS = [["I", "Interfaces", "die Übergabe zwischen außen und innen"], ["D", "Dashboards", "wenige Kennzahlen, die alle sehen"],
  ["E", "Experimentation", "Versuche mit erlaubtem Scheitern"], ["A", "Autonomy", "Entscheidungen dort, wo die Arbeit liegt"],
  ["S", "Social Technologies", "der Fluss von Wissen ohne Umweg über Hierarchie"]];

function ExoKarte({ v, w, angelegt, aufgabe }) {
  w = w || {};
  const stand = ["stark", "ansatz", "fehlt"].includes(w.stand) ? w.stand : "fehlt";
  const fertig = (angelegt || []).includes(w.schritt);
  return html`<div class="vf-exo-karte" data-stand=${stand}>
    <div class="kopf"><span class="kuerzel">${v[0]}</span><span class="name">${w.name || v[1]}</span>
      <span class="stand">${stand === "stark" ? "trägt" : stand === "ansatz" ? "im Ansatz" : "fehlt"}</span></div>
    <div class="befund">${w.befund || v[2]}</div>
    ${w.schritt && html`<div class="vf-exo-schritt"><span class="txt">${w.schritt}</span>
      <button class="btn klein" disabled=${fertig} onClick=${() => aufgabe(w.schritt)}>${fertig ? "angelegt" : "Als Aufgabe"}</button></div>`}
  </div>`;
}

function ExoGruppe({ titel, was, vorgaben, werte, angelegt, aufgabe }) {
  const w = Array.isArray(werte) ? werte : [];
  return html`<div class="vf-exo-gruppe"><h4>${titel}</h4><p class="leise klein">${was}</p>
    <div class="vf-exo-raster">${vorgaben.map((v, i) => html`<${ExoKarte} key=${i} v=${v} w=${w[i]} angelegt=${angelegt} aufgabe=${aufgabe} />`)}</div></div>`;
}

export function ExO() {
  const [s, setS, laden] = useStand("/exo", "exo");
  const projekte = useProjekte();
  const [umfang, setUmfang] = useState(null);
  const [pid, setPid] = useState(null);
  if (!s) return html`<div class="lade">Lade ExO …</div>`;
  const u = umfang || s.umfang || "portfolio";
  const p = pid !== null ? pid : s.projekt_id;
  const st = s.stand;
  const m = (st && st.mtp) || {};
  const sp = (st && st.sprint) || {};
  const ex = (pfad, daten) => tun("/exo/" + pfad, daten).then((r) => { laden(); return r; });
  async function aufgabe(text) { const r = await ex("aufgabe", { text }); if (r && r.ok) toast("Als Aufgabe angelegt."); }
  async function alsErgebnis() {
    const r = await ex("ergebnis");
    if (r && r.ergebnis_id) toast("Als Ergebnis gespeichert.", { aktion: { text: "Ansehen", fn: () => bus.sende("ergebnis-zeigen", r.ergebnis_id) } });
  }
  return html`<div class="vf">
    <div class="vf-kopf">
      <h2>ExO — Exponential-Organizations-Analyse</h2>
      <span class="luecke"></span>
      <label class="vf-lbl">Gegenstand
        <select class="eingabe" value=${u} disabled=${s.laeuft} onChange=${(e) => setUmfang(e.target.value)}>
          <option value="portfolio">Ganzes Portfolio</option><option value="projekt">Ein Projekt</option></select></label>
      ${u === "projekt" && html`<${ProjektWahl} wert=${p} projekte=${projekte} setzen=${setPid} />`}
    </div>
    <div class="vf-leib">
      <${Fehler} text=${s.fehler} />
      ${s.laeuft ? html`<${Arbeit} text="Das lokale Modell liest den Bestand und bewertet elf Punkte — das dauert eine Weile." seit=${s.seit} />`
        : !st ? html`<div class="vf-dok">
            <h3>ExO — der Rahmen in Kürze</h3>
            <p><b>MTP</b> — ein Zweck, der größer ist als das Vorhaben. Ohne ihn bleiben die zehn Merkmale darunter Technik.</p>
            <p><b>SCALE</b>, die fünf nach außen: ${SCALE.map((x, i) => html`${i ? " · " : ""}<b>${x[0]}</b> ${x[1]}`)}</p>
            <p><b>IDEAS</b>, die fünf nach innen: ${IDEAS.map((x, i) => html`${i ? " · " : ""}<b>${x[0]}</b> ${x[1]}`)}</p>
            <p>Oben wählen, was bewertet werden soll, dann <b>Analyse starten</b>. Bewertet wird ausschließlich, was im Cockpit steht — Ziele, Aufgaben, Notizen. Was daraus nicht hervorgeht, wird am Ende als Lücke benannt und nicht geraten.</p></div>`
        : html`
          <div class="vf-exo-mtp"><span class="vf-lbl">MTP — Massive Transformative Purpose</span>
            <div class="satz">${m.vorschlag || "— kein Vorschlag —"}</div>
            <div class="leise">${m.befund || ""}${m.vorhanden === false ? html` <b>Im Bestand ist kein solcher Zweck formuliert</b> — der Satz oben ist ein Vorschlag, keine Feststellung.` : ""}</div></div>
          <${ExoGruppe} titel="SCALE — die fünf nach außen" was="Wie die Organisation Kraft von außerhalb ihrer eigenen Grenzen bezieht." vorgaben=${SCALE} werte=${st.scale} angelegt=${s.angelegt} aufgabe=${aufgabe} />
          <${ExoGruppe} titel="IDEAS — die fünf nach innen" was="Wie sie das im Inneren aushält, ohne auseinanderzufallen." vorgaben=${IDEAS} werte=${st.ideas} angelegt=${s.angelegt} aufgabe=${aufgabe} />
          <div class="vf-exo-gruppe"><h4>ExO Sprint — zwei Stränge</h4>
            <p class="leise klein">Der Core-Strang verbessert das Bestehende, der Edge-Strang baut daneben etwas Neues. Getrennt, weil das Bestehende das Neue sonst erdrückt.</p>
            <div class="vf-exo-sprint">
              <div class="vf-exo-strom"><b>Core — am Bestehenden</b><div class="leise klein">Ohne das Geschäftsmodell anzufassen.</div>
                <ul>${(sp.core || []).length ? sp.core.map((x) => html`<li>${x}</li>`) : html`<li>— kein Vorschlag —</li>`}</ul></div>
              <div class="vf-exo-strom"><b>Edge — daneben neu</b><div class="leise klein">Mit eigener Freiheit, außerhalb der bestehenden Regeln.</div>
                <ul>${(sp.edge || []).length ? sp.edge.map((x) => html`<li>${x}</li>`) : html`<li>— kein Vorschlag —</li>`}</ul></div>
            </div></div>
          ${st.luecke && html`<div class="hinweisbox"><b>Was sich nicht beurteilen ließ</b><br />${st.luecke}</div>`}`}
      <div class="vf-quelle">Grundlage ist der <b>veröffentlichte</b> ExO-Rahmen (MTP, SCALE, IDEAS, ExO Sprint). Das eigene Material von OpenExO — REWRITE-Playbook, OS Outline — liegt hier nicht vor und wird auch nicht nachempfunden.</div>
    </div>
    <${Fuss} modell=${s.modell}>
      ${st && !s.laeuft ? html`
        ${s.ergebnis_id ? html`<button class="btn klein" onClick=${() => bus.sende("ergebnis-zeigen", s.ergebnis_id)}><${Icon} n="auge" g=${13} />Ergebnis ansehen</button>`
          : html`<button class="btn klein" onClick=${alsErgebnis}>Als Ergebnis</button>`}
        <button class="btn klein" onClick=${() => ex("neu")}>Noch einmal</button>`
        : !s.laeuft && html`<button class="btn primaer" onClick=${() => { if (u === "projekt" && !p) { toast("Erst ein Projekt wählen.", { fehler: true }); return; } ex("start", { umfang: u, projekt_id: u === "projekt" ? p : null }); }}>Analyse starten</button>`}
    </${Fuss}>
  </div>`;
}
