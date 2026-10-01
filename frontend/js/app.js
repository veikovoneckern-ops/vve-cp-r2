// Das Grundgeruest: fuenf Bereiche plus Neo, ein Gespraech, ein Erfassen.
// Briefing · Inbox · Projects · Team · System -- dazu Neo als eigener Knopf
// (Veikos Wunsch: "einer der Hauptakteure in meinem Team"), Talk und Capture.
import { html, render, useState, useEffect, useRef, Icon, Toasts, Modal, bus, toast, fehlerMelden, navigiere, tippsEinrichten } from "./ui.js";
import { api } from "./api.js";
import { Composer } from "./composer.js";
import { Briefing } from "./briefing.js";
import { Inbox } from "./inbox.js";
import { Projects, ErgebnisAnsicht, NotizAnsicht } from "./projects.js";
import { Team } from "./team.js";
import { System } from "./system.js";
import { Neo } from "./neo.js";
import { Talk } from "./talk.js";
import { Board } from "./board.js";
import { Logo, CockpitLeiste, ServerKaesten, SprechKnopf, kopfAbruf } from "./kopf.js";
import { ServerSektion } from "./server.js";

const BEREICHE = [
  { id: "briefing", titel: "Briefing", icon: "briefing", unter: "Was jetzt zählt" },
  { id: "inbox", titel: "Inbox", icon: "inbox", unter: "Alles, was hereinkommt" },
  { id: "projects", titel: "Projects", icon: "projects", unter: "Vorhaben, Aufgaben, Ergebnisse" },
  { id: "neo", titel: "Neo", icon: "neo", unter: "Cockpit Engineer", neo: true },
  { id: "team", titel: "Team", icon: "team", unter: "Dein KI-Team" },
  { id: "board", titel: "Advisory Board", kurz: "Board", icon: "board", unter: "Deine Advisors" },
  { id: "system", titel: "System", icon: "system", unter: "Team-Pipeline, Daten, Einstellungen" },
];

function route() {
  const teile = (location.hash.replace(/^#\/?/, "") || "briefing").split("/");
  return { bereich: BEREICHE.some((b) => b.id === teile[0]) ? teile[0] : "briefing", id: teile[1] ? decodeURIComponent(teile[1]) : null, rest: teile.slice(2) };
}

// Suche als Symbol wie im alten Cockpit; das Feld klappt darunter auf (Strg+K).
// Spart in der Kopfzeile den Platz, den die Statuskaesten brauchen.
function SucheKnopf() {
  const [auf, setAuf] = useState(false);
  useEffect(() => {
    const k = (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setAuf(true); } };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, []);
  return html`<div class="suche-wrap">
    <button class=${"kopf-icon" + (auf ? " an" : "")} onClick=${() => setAuf(!auf)} aria-label="Suchen" title="Suchen (Strg+K)"><${Icon} n="suche" g=${17} /></button>
    ${auf && html`<div class="suche-pop"><${Suche} zu=${() => setAuf(false)} /></div>`}
  </div>`;
}

function Suche({ zu }) {
  const [q, setQ] = useState("");
  const [treffer, setTreffer] = useState([]);
  const [offen, setOffen] = useState(false);
  const [an, setAn] = useState(0);
  const feld = useRef(null);
  useEffect(() => { feld.current && feld.current.focus(); }, []);
  useEffect(() => {
    if (q.trim().length < 2) { setTreffer([]); return; }
    const t = setTimeout(() => api("/suche?q=" + encodeURIComponent(q)).then((d) => { setTreffer(d.treffer); setAn(0); }).catch(() => {}), 200);
    return () => clearTimeout(t);
  }, [q]);
  const oeffnen = (t) => {
    setOffen(false); setQ(""); zu();
    if (t.art === "projekt") navigiere("/projects/" + t.id);
    else if (t.art === "vorgang") navigiere("/inbox/" + t.id);
    else if (t.art === "aufgabe") navigiere(t.unter ? "/projects/" + t.unter : "/projects/_aufgaben");
    else if (t.art === "notiz") bus.sende("notiz-zeigen", t.id);
    else if (t.art === "ergebnis") bus.sende("ergebnis-zeigen", t.id);
  };
  const ART = { projekt: "Projekt", vorgang: "Vorgang", aufgabe: "Aufgabe", notiz: "Notiz", ergebnis: "Ergebnis" };
  return html`<div class="suche-feld">
    <${Icon} n="suche" g=${15} />
    <input ref=${feld} value=${q} placeholder="Suchen … (Strg+K)" aria-label="Im Cockpit suchen"
      onInput=${(e) => { setQ(e.target.value); setOffen(true); }} onFocus=${() => setOffen(true)}
      onBlur=${() => setTimeout(() => { setOffen(false); zu(); }, 180)}
      onKeyDown=${(e) => {
        if (e.key === "ArrowDown") { e.preventDefault(); setAn((a) => Math.min(a + 1, treffer.length - 1)); }
        if (e.key === "ArrowUp") { e.preventDefault(); setAn((a) => Math.max(a - 1, 0)); }
        if (e.key === "Enter" && treffer[an]) oeffnen(treffer[an]);
        if (e.key === "Escape") { e.stopPropagation(); setQ(""); zu(); }
      }} />
    ${offen && q.trim().length >= 2 && html`<div class="suche-treffer">
      ${treffer.length ? treffer.map((t, i) => html`<button class=${i === an ? "an" : ""} onMouseDown=${() => oeffnen(t)}>
        <span class="art">${ART[t.art]}</span><span>${t.titel}</span></button>`) : html`<div class="leer">Nichts gefunden.</div>`}
    </div>`}
  </div>`;
}

function Erfassen({ zu }) {
  const [projekte, setProjekte] = useState([]);
  const [projekt, setProjekt] = useState("");
  useEffect(() => { api("/projekte").then((d) => setProjekte(d.projekte)).catch(() => {}); }, []);
  async function senden(text, anhaenge) {
    try {
      const r = await api("/erfassen", { methode: "POST", daten: { text, anhaenge, projekt_id: projekt || null } });
      toast("Ans Team übergeben. Jason ordnet es gleich ein.", { aktion: { text: "Ansehen", fn: () => navigiere("/inbox/" + r.vorgang_id) } });
      bus.sende("aktualisieren");
      zu();
      return true;
    } catch (e) { fehlerMelden(e); return false; }
  }
  return html`<${Modal} titel="Capture: etwas ans Team geben" zu=${zu}>
    <p class="leise" style="margin-bottom:12px">Wie eine Plaud-Notiz: Jason ordnet ein, legt Aufgaben an und fragt nach, wenn etwas unklar ist. Du kannst tippen, diktieren oder Dateien anhängen.</p>
    <div class="feld" style="margin-bottom:10px"><label for="erf-projekt">Projekt (optional, sonst entscheidet Jason)</label>
      <select id="erf-projekt" class="eingabe" value=${projekt} onChange=${(e) => setProjekt(e.target.value)}>
        <option value="">Jason soll zuordnen</option>
        ${projekte.map((p) => html`<option value=${p.id}>${p.name}</option>`)}
      </select></div>
    <${Composer} platzhalter="Was soll dein Team wissen oder tun?" beimSenden=${senden} autofokus=${true} zeilen=${4}
      projektId=${projekt} entwurfKey="erfassen" sendenText="Ans Team" />
  <//>`;
}

function Anmelden({ fertig, einrichten }) {
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [fehler, setFehler] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  async function los(e) {
    e.preventDefault(); setLaeuft(true); setFehler("");
    try {
      await api(einrichten ? "/konto/einrichten" : "/konto/anmelden", { methode: "POST", daten: { benutzer: name, passwort: pw } });
      fertig();
    } catch (x) { setFehler(x.message); }
    setLaeuft(false);
  }
  return html`<div class="anmelden"><form onSubmit=${los}>
    <div class="anmelde-logo"><span class="logo" aria-hidden="true"></span></div>
    <h1>${einrichten ? "Konto einrichten" : "Anmelden"}</h1>
    ${einrichten ? html`<p class="leise">Noch gibt es kein Konto. Lege jetzt deins an.</p>`
      : html`<p class="leise">Dieselben Zugangsdaten wie bisher in Release 2.</p>`}
    <div class="feld"><label for="an-name">Benutzername</label><input id="an-name" class="eingabe" autocomplete="username" value=${name} onInput=${(e) => setName(e.target.value)} /></div>
    <div class="feld"><label for="an-pw">Passwort</label><input id="an-pw" class="eingabe" type="password" autocomplete=${einrichten ? "new-password" : "current-password"} value=${pw} onInput=${(e) => setPw(e.target.value)} /></div>
    ${fehler && html`<div class="fehlerbox">${fehler}</div>`}
    <button class="btn primaer" type="submit" disabled=${laeuft || !name || !pw}>${laeuft ? "Einen Moment …" : einrichten ? "Einrichten" : "Anmelden"}</button>
  </form></div>`;
}

function App() {
  const [konto, setKonto] = useState(null);
  const [r, setR] = useState(route());
  const [talk, setTalk] = useState(() => { try { return localStorage.getItem("vvec_talk") === "1" && innerWidth > 1180; } catch (e) { return false; } });
  const [talkStart, setTalkStart] = useState(null);
  const [kontext, setKontext] = useState(null);
  const [erfassen, setErfassen] = useState(false);
  const [lage, setLage] = useState(null);
  const [anzeige, setAnzeige] = useState(null);
  // Server-Sektion: klappt unter der Kopfzeile auf, wie im alten Cockpit.
  const [server, setServer] = useState(false);

  const pruefen = () => api("/konto/ich").then(setKonto).catch(() => setKonto({ angemeldet: false, fehler: true }));
  useEffect(() => { pruefen(); }, []);
  useEffect(() => {
    const h = () => setR(route());
    addEventListener("hashchange", h);
    const ab = () => setKonto((k) => ({ ...(k || {}), angemeldet: false }));
    addEventListener("vvec-abgemeldet", ab);
    return () => { removeEventListener("hashchange", h); removeEventListener("vvec-abgemeldet", ab); };
  }, []);
  useEffect(() => { try { localStorage.setItem("vvec_talk", talk ? "1" : "0"); } catch (e) { /* egal */ } }, [talk]);
  useEffect(() => bus.an("talk-oeffnen", (d) => { setTalkStart({ ...(d || {}), n: Date.now() }); if (d && d.kontext) setKontext(d.kontext); setTalk(true); }), []);
  useEffect(() => bus.an("talk-kontext", (k) => setKontext(k)), []);
  useEffect(() => bus.an("erfassen", () => setErfassen(true)), []);
  useEffect(() => bus.an("server-sektion", (an) => setServer(!!an)), []);
  // Ein Wechsel der Ansicht klappt sie zu -- sonst laege sie ueber der neuen Ansicht.
  useEffect(() => { setServer(false); }, [r.bereich, r.id]);
  // Sprechen oben im Kopf: Talk geht auf und hoert sofort zu.
  useEffect(() => bus.an("dialog-start", () => { setTalkStart({ frei: true, ausKopf: true, n: Date.now() }); setTalk(true); }), []);
  useEffect(() => { if (konto && konto.angemeldet) return kopfAbruf(); }, [konto && konto.angemeldet]);
  useEffect(() => bus.an("ergebnis-zeigen", (id) => setAnzeige({ art: "ergebnis", id })), []);
  useEffect(() => bus.an("notiz-zeigen", (id) => setAnzeige({ art: "notiz", id })), []);
  useEffect(() => {
    if (!konto || !konto.angemeldet) return;
    const holen = () => api("/lage").then((d) => { setLage(d); bus.sende("lage", d); }).catch(() => {});
    holen();
    const i = setInterval(() => { if (!document.hidden) holen(); }, 25000);
    const aus = bus.an("aktualisieren", holen);
    return () => { clearInterval(i); aus(); };
  }, [konto && konto.angemeldet]);
  useEffect(() => {
    const k = (e) => {
      if (e.key === "Escape" && document.documentElement.classList.contains("neo-vollbild") && !document.querySelector(".modal-grund")) {
        document.documentElement.classList.remove("neo-vollbild"); bus.sende("vollbild", false);
      }
    };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, []);
  useEffect(() => { if (r.bereich !== "neo") document.documentElement.classList.remove("neo-vollbild"); }, [r.bereich]);

  if (!konto) return html`<div class="lade">Cockpit wird geladen …</div>`;
  if (!konto.angemeldet) return html`<${Anmelden} einrichten=${konto.einrichten} fertig=${pruefen} />`;

  const bereich = BEREICHE.find((b) => b.id === r.bereich);
  const offen = lage ? lage.entscheidungen.length : 0;
  const neoLaeuft = lage && lage.neo_laeuft && lage.neo_laeuft.length > 0;
  const zahl = (b) => b.id === "inbox" && offen ? html`<span class="zahl">${offen}</span>` : b.neo && neoLaeuft ? html`<span class="zahl ruhig">arbeitet</span>` : null;
  const voll = r.bereich === "inbox" || r.bereich === "neo" || r.bereich === "board";
  // Im Projekt steht oben der Projektname (wie im alten Cockpit "BVE / Projekt-Detail").
  const imProjekt = r.bereich === "projects" && r.id && !r.id.startsWith("_") && kontext && kontext.art === "projekt";
  const titel = imProjekt ? kontext.titel : bereich.titel;
  const unter = imProjekt ? "Projekt-Detail" : bereich.unter;

  function thema() {
    const jetzt = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const neu = jetzt === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = neu;
    try { localStorage.setItem("vvec_thema", neu); } catch (e) { /* egal */ }
  }

  return html`<div class=${"schale" + (talk ? " mit-talk" : "")}>
    <nav class="rail" aria-label="Bereiche">
      <div class="marke"><${Logo} gross=${true} /></div>
      <button class="erfassen-knopf" onClick=${() => setErfassen(true)} title="Etwas ans Team geben"><${Icon} n="plus" g=${17} w=${2.4} />Capture</button>
      <div class="nav">
        ${BEREICHE.slice(0, 3).map((b) => html`<a href=${"#/" + b.id} class=${r.bereich === b.id ? "an" : ""}><${Icon} n=${b.icon} />${b.titel}${zahl(b)}</a>`)}
        <div class="nav-trenner"></div>
        ${BEREICHE.slice(3).map((b) => html`<a href=${"#/" + b.id} class=${(r.bereich === b.id ? "an " : "") + (b.neo ? "neo-nav" : "")}><${Icon} n=${b.icon} />${b.titel}${zahl(b)}</a>`)}
      </div>
      <div class="rail-fuss">
        <button onClick=${thema} title="Hell / Dunkel" aria-label="Hell oder dunkel"><${Icon} n="mond" g=${16} /></button>
        <button onClick=${() => api("/konto/abmelden", { methode: "POST" }).then(pruefen)} title="Abmelden" aria-label="Abmelden"><${Icon} n="raus" g=${16} /></button>
      </div>
    </nav>
    <div class="haupt">
      <header class="topbar">
        <span class="nur-mobil kopf-logo"><${Logo} /></span>
        <div class="kopf-titel">
          <h1>${titel}</h1><span>${unter}</span>
        </div>
        <${CockpitLeiste} lage=${lage} />
        <span class="kopf-trenner"></span>
        <${ServerKaesten} offen=${server} umschalten=${() => setServer(!server)} gesundheit=${lage && lage.gesundheit} />
        <span class="kopf-knoepfe">
          <button class="kopf-icon nur-mobil" onClick=${() => setErfassen(true)} aria-label="Capture" title="Capture"><${Icon} n="plus" g=${19} /></button>
          <${SprechKnopf} />
          <${SucheKnopf} />
          <button class=${"kopf-icon talk-auf" + (talk ? " an" : "")} onClick=${() => setTalk(!talk)} aria-pressed=${talk}
            title=${talk ? "Gesprächsspalte schließen" : "Gesprächsspalte öffnen (zum Tippen)"} aria-label="Gesprächsspalte"><${Icon} n="chat" g=${18} /></button>
        </span>
      </header>
      ${server && html`<${ServerSektion} zu=${() => setServer(false)} gesundheit=${lage && lage.gesundheit} />`}
      <main class=${"inhalt" + (voll ? " voll" : "")}>
        ${r.bereich === "briefing" && html`<${Briefing} lage=${lage} />`}
        ${r.bereich === "inbox" && html`<${Inbox} id=${r.id} />`}
        ${r.bereich === "projects" && html`<${Projects} id=${r.id} rest=${r.rest} />`}
        ${r.bereich === "team" && html`<${Team} id=${r.id} />`}
        ${r.bereich === "system" && html`<${System} konto=${konto} thema=${thema} />`}
        ${r.bereich === "neo" && html`<${Neo} id=${r.id} />`}
        ${r.bereich === "board" && html`<${Board} id=${r.id} />`}
      </main>
    </div>
    ${talk && html`<${Talk} zu=${() => setTalk(false)} kontext=${kontext} setKontext=${setKontext} start=${talkStart} />`}
    <nav class="unten-nav" aria-label="Bereiche">
      ${BEREICHE.filter((b) => b.id !== "system").map((b) => html`<a href=${"#/" + b.id} class=${(r.bereich === b.id ? "an " : "") + (b.neo ? "neo-nav" : "")}>
        <${Icon} n=${b.icon} g=${20} />${b.kurz || b.titel}${b.id === "inbox" && offen ? html`<span class="zahl">${offen}</span>` : null}</a>`)}
      <a href="#/system" class=${r.bereich === "system" ? "an" : ""}><${Icon} n="system" g=${20} />System</a>
    </nav>
    ${!talk && html`<button class="talk-fab" onClick=${() => setTalk(true)} aria-label="Talk öffnen"><${Icon} n="talk" g=${24} /></button>`}
    ${anzeige && anzeige.art === "ergebnis" && html`<${ErgebnisAnsicht} id=${anzeige.id} zu=${() => setAnzeige(null)} />`}
    ${anzeige && anzeige.art === "notiz" && html`<${NotizAnsicht} id=${anzeige.id} zu=${() => setAnzeige(null)} />`}
    ${erfassen && html`<${Erfassen} zu=${() => setErfassen(false)} />`}
    <${Toasts} />
  </div>`;
}

tippsEinrichten();
render(html`<${App} />`, document.getElementById("app"));
