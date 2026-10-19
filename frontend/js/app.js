// Das Grundgeruest: fuenf Bereiche plus Neo, ein Gespraech, ein Erfassen.
// Briefing · Inbox · Projects · Team · System -- dazu Neo als eigener Knopf
// (Veikos Wunsch: "einer der Hauptakteure in meinem Team"), Talk und Capture.
import { useEsc, html, render, useState, useEffect, useRef, Icon, Toasts, Modal, bus, toast, fehlerMelden, navigiere, tippsEinrichten, listenEinrichten, breitenLaden } from "./ui.js";
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
import { Logo, CockpitLeiste, ServerKaesten, SprechKnopf, TalkPille, kopfAbruf } from "./kopf.js";
import { LeisteNav, useLeiste, FENSTER } from "./leiste.js";
import { Einstellungen } from "./einstellungen.js";
import { Usage } from "./usage.js";
import { Explorer } from "./explorer.js";
import { Empfehlungen } from "./empfehlungen.js";
import { DateiFenster } from "./datei.js";
import { Langlaeufer } from "./langlauf.js";
import { BrainStrom, ExO } from "./verfahren.js";
import { Aktionen } from "./aktionen.js";
import { AufgabeFenster } from "./aufgabe.js";
import { WebSpace } from "./webspace.js";

const BEREICHE = [
  { id: "briefing", titel: "Briefing", icon: "briefing", unter: "Was jetzt zählt" },
  { id: "inbox", titel: "Inbox", icon: "inbox", unter: "Alles, was hereinkommt" },
  { id: "projects", titel: "Projects", icon: "projects", unter: "Vorhaben, Aufgaben, Ergebnisse" },
  // Lange Vorhaben in Etappen mit Zwischenpruefung durch Dario oder Demmis (17.10.).
  // Heisst seit dem 19.10.2026 "LongRuns" (Veikos Wunsch); die Kennung bleibt langlauf.
  { id: "langlauf", titel: "LongRuns", icon: "langlauf", unter: "Buch, langes Dokument, langes Video -- läuft durch" },
  // Alles, was gerade laeuft, mit Pausieren/Abbrechen (Veiko, 17.10.2026). Hinter den
  // Langlaeufern: weit oben, damit man es findet, aber nicht unter den ersten vier --
  // die stehen auf dem Telefon in der unteren Leiste und sollen dort bleiben.
  { id: "aktionen", titel: "Current Actions", kurz: "Actions", icon: "aktionen", unter: "Alles, was gerade läuft" },
  // Alle erzeugten Inhalte wie in einem Datei-Explorer (Veiko, 19.10.2026).
  { id: "explorer", titel: "Explorer", icon: "explorer", unter: "Alles, was entstanden ist -- suchen, filtern, öffnen" },
  { id: "neo", titel: "Neo", icon: "neo", unter: "Cockpit Engineer", neo: true },
  // Team = Mitglieder + das fruehere "Stab & Modelle", in aufklappbaren Abschnitten (19.10.2026).
  { id: "team", titel: "Team", icon: "team", unter: "Mitglieder, Besetzung, Modelle, Optimierung" },
  // Verbrauch als eigene Seite (19.10.2026): Token, Rechenzeit, Kosten, Strom -- nach Projekt, Aufgabe, Modell.
  { id: "usage", titel: "Usage", icon: "usage", unter: "Token, Rechenzeit, Kosten und Strom" },
  // Alle Empfehlungen an einem Ort (Veiko, 19.10.2026): Server, Software, Modelle, Website.
  { id: "empfehlungen", titel: "Recommendations", kurz: "Tipps", icon: "tipp", unter: "Was sich verbessern lässt: Server, Modelle, Website" },
  { id: "board", titel: "Advisory Board", kurz: "Board", icon: "board", unter: "Deine Advisors" },
  // Die Website veikovoneckern.org bearbeiten und veröffentlichen (Veiko, 18.10.2026).
  { id: "webspace", titel: "WebSpace", icon: "globus", unter: "Deine Website veikovoneckern.org" },
  // Aus dem alten Cockpit uebernommen (Veiko, 01.10.): zwei Verfahren auf dem
  // eigenen Modell und der WatchDog -- je mit eigenem Knopf.
  { id: "brainstrom", titel: "BrainStrom", icon: "brainstrom", unter: "Aus einer Idee ein Vorhaben" },
  { id: "exo", titel: "ExO", icon: "exo", unter: "Exponential-Organizations-Analyse" },
  // Neu geordnet am 17.10.2026 und 19.10.2026: Stack = Server + WatchDog + Website;
  // Team = Mitglieder + Besetzung, Optimierung, Neues bei Ollama; Usage und Explorer eigene Seiten;
  // Einstellungen = Freigaben, Pipeline, Stimme, Memory, Daten, Konto. Alte Adressen leitet route() um.
  // "Maschine" heisst seit dem 19.10.2026 "Stack"; die Kennung bleibt system (Kopfzeile, alte Links).
  { id: "system", titel: "Stack", icon: "stapel", unter: "Server, Updates, Sicherungen, WatchDog, Website" },
  // Heisst seit dem 19.10.2026 "Settings" (Veikos Wunsch); die Kennung bleibt einstellungen.
  { id: "einstellungen", titel: "Settings", icon: "einstellungen", unter: "Freigaben, Pipeline, Stimme, Memory, Daten, Konto" },
];

function route() {
  const teile = (location.hash.replace(/^#\/?/, "") || "briefing").split("/");
  // Alte Adressen (vor den Neuordnungen am 17. und 19.10.2026) fuehren an die neue Stelle.
  if (teile[0] === "watchdog") { teile[0] = "system"; teile[1] = "watchdog"; }
  if (teile[0] === "verbrauch" || (teile[0] === "modelle" && teile[1] === "verbrauch")) { teile.length = 1; teile[0] = "usage"; }
  if (teile[0] === "modelle") { teile[0] = "team"; teile[1] = { uebersicht: "besetzung", installiert: "installiert", optimierung: "optimierung", neu: "neu" }[teile[1]] || "besetzung"; }
  if (teile[0] === "team" && teile[1] === "gedaechtnis") { teile[0] = "einstellungen"; teile[1] = "memory"; }
  return { bereich: BEREICHE.some((b) => b.id === teile[0]) ? teile[0] : "briefing", id: teile[1] ? decodeURIComponent(teile[1]) : null, rest: teile.slice(2) };
}

// Suche als Symbol wie im alten Cockpit; das Feld klappt darunter auf (Strg+K).
// Spart in der Kopfzeile den Platz, den die Statuskaesten brauchen.
function SucheKnopf() {
  const [auf, setAuf] = useState(false);
  useEffect(() => bus.an("suche-oeffnen", () => setAuf(true)), []);
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

// Untere Leiste auf dem Telefon. Zehn Bereiche passen nicht auf 390 Punkt --
// gemessen waren nur sechs erreichbar, System gar nicht. Auf schmalen Geraeten
// stehen deshalb die ersten vier (in Veikos Reihenfolge aus der linken Leiste)
// plus "Mehr"; dahinter alle. Ab 560 Punkt passen alle zehn nebeneinander.
const UNTEN_SICHTBAR = 4;
function UntenNav({ liste, aktiv, offen }) {
  const [mehr, setMehr] = useState(false);
  useEffect(() => { setMehr(false); }, [aktiv]);
  useEsc(() => setMehr(false), mehr);
  const zahl = (b) => (b.id === "inbox" && offen ? html`<span class="zahl">${offen}</span>` : null);
  const verborgenAktiv = liste.slice(UNTEN_SICHTBAR).some((b) => b.id === aktiv);
  return html`<nav class="unten-nav" aria-label="Bereiche">
    ${liste.map((b, i) => html`<a href=${"#/" + b.id} class=${(aktiv === b.id ? "an " : "") + (b.neo ? "neo-nav " : "") + (i >= UNTEN_SICHTBAR ? "unten-ueber" : "")}>
      <${Icon} n=${b.icon} g=${20} />${b.kurz || b.titel}${zahl(b)}</a>`)}
    <button class=${"unten-mehr" + (verborgenAktiv || mehr ? " an" : "")} onClick=${() => setMehr(!mehr)} aria-expanded=${mehr}>
      <${Icon} n="liste" g=${20} />Mehr</button>
    ${mehr && html`<div class="unten-blatt" role="menu">
      ${liste.slice(UNTEN_SICHTBAR).map((b) => html`<a role="menuitem" href=${"#/" + b.id} class=${aktiv === b.id ? "an" : ""}><${Icon} n=${b.icon} g=${18} />${b.titel}${zahl(b)}</a>`)}
    </div>`}
  </nav>`;
}

// Hell/Dunkel -- vom Knopf in der Leiste und von Talk ("schalt auf dunkel").
function themaSetzen(neu) {
  document.documentElement.dataset.theme = neu;
  try { localStorage.setItem("vvec_thema", neu); } catch (e) { /* egal */ }
}

function App() {
  const [konto, setKonto] = useState(null);
  const [r, setR] = useState(route());
  // Im eigenen Fenster startet Talk zu: dort soll nur die eine Seite stehen.
  const [talk, setTalk] = useState(() => { try { return !FENSTER && localStorage.getItem("vvec_talk") === "1" && innerWidth > 1180; } catch (e) { return false; } });
  const [talkStart, setTalkStart] = useState(null);
  const [kontext, setKontext] = useState(null);
  const [erfassen, setErfassen] = useState(false);
  const [lage, setLage] = useState(null);
  const [anzeige, setAnzeige] = useState(null);
  const [aufgabe, setAufgabe] = useState(null);
  // Neue Fassung auf dem Server (19.10.2026): ein offener Tab zeigte nach einem Update
  // weiter die alte Oberflaeche. Die erste gesehene Fassung gilt; weicht /lage ab, Hinweis.
  const fassung = useRef(null);
  const [neueFassung, setNeueFassung] = useState(false);
  const [leiste, leisteSpeichern] = useLeiste(BEREICHE, !!(konto && konto.angemeldet));

  const pruefen = () => api("/konto/ich").then(setKonto).catch(() => setKonto({ angemeldet: false, fehler: true }));
  useEffect(() => { pruefen(); }, []);
  useEffect(() => {
    const h = () => setR(route());
    addEventListener("hashchange", h);
    const ab = () => setKonto((k) => ({ ...(k || {}), angemeldet: false }));
    addEventListener("vvec-abgemeldet", ab);
    return () => { removeEventListener("hashchange", h); removeEventListener("vvec-abgemeldet", ab); };
  }, []);
  // Das eigene Fenster schreibt den Talk-Zustand nicht zurueck -- sonst
  // bestimmte das zuletzt geschlossene Fenster, ob Talk im Hauptfenster aufgeht.
  useEffect(() => { if (FENSTER) return; try { localStorage.setItem("vvec_talk", talk ? "1" : "0"); } catch (e) { /* egal */ } }, [talk]);
  useEffect(() => bus.an("talk-oeffnen", (d) => { setTalkStart({ ...(d || {}), n: Date.now() }); if (d && d.kontext) setKontext(d.kontext); setTalk(true); }), []);
  useEffect(() => bus.an("talk-kontext", (k) => setKontext(k)), []);
  // Ein offenes Fenster ueberlagert den Bezug der Seite, ohne ihn zu loeschen (ui.useFensterKontext).
  const [fensterKontext, setFensterKontext] = useState(null);
  useEffect(() => bus.an("talk-fenster", (k) => setFensterKontext(k)), []);
  useEffect(() => bus.an("erfassen", () => setErfassen(true)), []);
  useEffect(() => bus.an("thema-setzen", (neu) => themaSetzen(neu)), []);
  // Die Server-Sektion steht fest auf der Seite System; wer sie von anderswo
  // anfordert (frueher: Aufklappen), landet dort.
  useEffect(() => bus.an("server-sektion", () => navigiere("#/system")), []);
  // Sprechen oben im Kopf: Talk geht auf und hoert sofort zu.
  useEffect(() => bus.an("dialog-start", () => { setTalkStart({ frei: true, ausKopf: true, n: Date.now() }); setTalk(true); }), []);
  useEffect(() => { if (konto && konto.angemeldet) return kopfAbruf(); }, [konto && konto.angemeldet]);
  // ergebnis-zeigen: eine Kennung, oder { id, vorlage } -- dann steht die Bitte schon im Chat (Daniels Einwände einarbeiten).
  useEffect(() => bus.an("ergebnis-zeigen", (x) => setAnzeige({ art: "ergebnis", id: (x && x.id) || x, vorlage: x && x.vorlage, n: Date.now() })), []);
  useEffect(() => bus.an("notiz-zeigen", (id) => setAnzeige({ art: "notiz", id })), []);
  // Eine Unterlage im Cockpit lesen (datei.js, 19.10.2026): Explorer, Talk, Aufgabe.
  useEffect(() => bus.an("datei-zeigen", (id) => setAnzeige({ art: "datei", id, n: Date.now() })), []);
  // Das Aufgabenfenster (17.10.2026): von jeder Stelle, an der eine Aufgabe steht.
  useEffect(() => bus.an("aufgabe-zeigen", (id) => setAufgabe({ id, n: Date.now() })), []);
  useEffect(() => {
    if (!konto || !konto.angemeldet) return;
    const holen = () => api("/lage").then((d) => {
      setLage(d); bus.sende("lage", d);
      if (d.fassung) { if (fassung.current == null) fassung.current = d.fassung; else if (d.fassung !== fassung.current) setNeueFassung(true); }
    }).catch(() => {});
    holen();
    const i = setInterval(() => { if (!document.hidden) holen(); }, 25000);
    const aus = bus.an("aktualisieren", holen);
    return () => { clearInterval(i); aus(); };
  }, [konto && konto.angemeldet]);
  useEffect(() => { if (r.bereich !== "neo") document.documentElement.classList.remove("neo-vollbild"); }, [r.bereich]);

  if (!konto) return html`<div class="lade">Cockpit wird geladen …</div>`;
  if (!konto.angemeldet) return html`<${Anmelden} einrichten=${konto.einrichten} fertig=${pruefen} />`;

  const bereich = BEREICHE.find((b) => b.id === r.bereich);
  const offen = lage ? lage.entscheidungen.length : 0;
  const neoLaeuft = lage && lage.neo_laeuft && lage.neo_laeuft.length > 0;
  const akt = lage ? lage.aktionen || 0 : 0;
  const zahl = (b) => b.id === "aktionen" && akt ? html`<span class="zahl ruhig">${akt}</span>` : b.id === "inbox" && offen ? html`<span class="zahl">${offen}</span>` : b.neo && neoLaeuft ? html`<span class="zahl ruhig">arbeitet</span>` : null;
  const voll = r.bereich === "inbox" || r.bereich === "neo" || r.bereich === "board" || r.bereich === "webspace";
  // Im Projekt steht oben der Projektname (wie im alten Cockpit "BVE / Projekt-Detail").
  const imProjekt = r.bereich === "projects" && r.id && !r.id.startsWith("_") && kontext && kontext.art === "projekt";
  const titel = imProjekt ? kontext.titel : bereich.titel;
  const unter = imProjekt ? "Projekt-Detail" : bereich.unter;
  if (FENSTER) document.title = titel + " · VvE Cockpit";

  function thema() {
    const jetzt = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    themaSetzen(jetzt === "dark" ? "light" : "dark");
  }

  return html`<div class=${"schale" + (talk ? " mit-talk" : "") + (FENSTER ? " fenster" : "")}>
    ${!FENSTER && html`<nav class="rail" aria-label="Bereiche">
      <div class="marke"><${Logo} gross=${true} /></div>
      <button class="erfassen-knopf" onClick=${() => setErfassen(true)} title="Etwas ans Team geben"><${Icon} n="plus" g=${17} w=${2.4} />Capture</button>
      <${LeisteNav} liste=${leiste} aktiv=${r.bereich} zahl=${zahl} speichern=${leisteSpeichern} />
      <div class="rail-fuss">
        <button onClick=${thema} title="Hell / Dunkel" aria-label="Hell oder dunkel"><${Icon} n="mond" g=${16} /></button>
        <button onClick=${() => api("/konto/abmelden", { methode: "POST" }).then(pruefen)} title="Abmelden" aria-label="Abmelden"><${Icon} n="raus" g=${16} /></button>
      </div>
    </nav>`}
    <div class="haupt">
      <header class="topbar">
        <span class="nur-mobil kopf-logo"><${Logo} /></span>
        <div class="kopf-titel">
          <h1>${titel}</h1><span>${unter}</span>
        </div>
        ${!FENSTER && html`<${CockpitLeiste} lage=${lage} />
        <span class="kopf-trenner"></span>
        <${ServerKaesten} offen=${r.bereich === "system"} umschalten=${() => navigiere("#/system")} gesundheit=${lage && lage.gesundheit} />`}
        ${FENSTER && html`<span class="luecke"></span>`}
        <span class="kopf-knoepfe">
          <button class="kopf-icon nur-mobil" onClick=${() => setErfassen(true)} aria-label="Capture" title="Capture"><${Icon} n="plus" g=${19} /></button>
          <${SprechKnopf} />
          <${SucheKnopf} />
          <button class=${"kopf-icon talk-auf" + (talk ? " an" : "")} onClick=${() => setTalk(!talk)} aria-pressed=${talk}
            title=${talk ? "Gesprächsspalte schließen" : "Gesprächsspalte öffnen (zum Tippen)"} aria-label="Gesprächsspalte"><${Icon} n="chat" g=${18} /></button>
        </span>
      </header>
      <main class=${"inhalt" + (voll ? " voll" : "")}>
        ${r.bereich === "briefing" && html`<${Briefing} lage=${lage} />`}
        ${r.bereich === "inbox" && html`<${Inbox} id=${r.id} />`}
        ${r.bereich === "projects" && html`<${Projects} id=${r.id} rest=${r.rest} />`}
        ${r.bereich === "team" && html`<${Team} id=${r.id} rest=${r.rest} />`}
        ${r.bereich === "system" && html`<${System} gesundheit=${lage && lage.gesundheit} abschnitt=${r.id} />`}
        ${r.bereich === "einstellungen" && html`<${Einstellungen} konto=${konto} thema=${thema} abschnitt=${r.id} />`}
        ${r.bereich === "usage" && html`<${Usage} />`}
        ${r.bereich === "explorer" && html`<${Explorer} />`}
        ${r.bereich === "empfehlungen" && html`<${Empfehlungen} abschnitt=${r.id} />`}
        ${r.bereich === "neo" && html`<${Neo} id=${r.id} />`}
        ${r.bereich === "board" && html`<${Board} id=${r.id} />`}
        ${r.bereich === "brainstrom" && html`<${BrainStrom} />`}
        ${r.bereich === "exo" && html`<${ExO} />`}
        ${r.bereich === "langlauf" && html`<${Langlaeufer} id=${r.id} />`}
        ${r.bereich === "aktionen" && html`<${Aktionen} />`}
        ${r.bereich === "webspace" && html`<${WebSpace} pfad=${r.id} />`}
      </main>
    </div>
    ${talk && html`<${Talk} zu=${() => setTalk(false)} kontext=${fensterKontext || kontext} setKontext=${(k) => { setFensterKontext(null); setKontext(k); }} start=${talkStart} />`}
    ${!FENSTER && html`<${UntenNav} liste=${leiste} aktiv=${r.bereich} offen=${offen} />`}
    ${!talk && !FENSTER && html`<button class="talk-fab" onClick=${() => setTalk(true)} aria-label="Talk öffnen"><${Icon} n="talk" g=${24} /></button>`}
    ${anzeige && anzeige.art === "ergebnis" && html`<${ErgebnisAnsicht} key=${anzeige.n} id=${anzeige.id} vorlage=${anzeige.vorlage} zu=${() => setAnzeige(null)} />`}
    ${anzeige && anzeige.art === "notiz" && html`<${NotizAnsicht} id=${anzeige.id} zu=${() => setAnzeige(null)} />`}
    ${erfassen && html`<${Erfassen} zu=${() => setErfassen(false)} />`}
    ${aufgabe && html`<${AufgabeFenster} key=${aufgabe.n} id=${aufgabe.id} zu=${() => setAufgabe(null)} />`}
    ${anzeige && anzeige.art === "datei" && html`<${DateiFenster} key=${anzeige.n} id=${anzeige.id} zu=${() => setAnzeige(null)} />`}
    ${neueFassung && html`<div class="neue-fassung" role="status"><${Icon} n="neu_laden" g=${15} /><span>Das Cockpit wurde aktualisiert.</span>
      <button class="btn klein primaer" onClick=${() => location.reload()}>Neu laden</button>
      <button class="btn klein geist icon" onClick=${() => setNeueFassung(false)} aria-label="Später" title="Später"><${Icon} n="x" g=${13} /></button></div>`}
    ${talk && (anzeige || aufgabe || erfassen) && html`<${TalkPille} />`}
    <${Toasts} />
  </div>`;
}

tippsEinrichten();
breitenLaden();
listenEinrichten();
render(html`<${App} />`, document.getElementById("app"));
