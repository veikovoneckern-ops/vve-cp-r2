// TALK -- ein Gespraech, ueberall. Seitenspalte am Rechner, ganze Seite am Telefon.
// Drei Arten zu reden:
//   tippen oder diktieren     -- Composer, Enter sendet
//   Freisprechen              -- zuhoeren, antworten, vorlesen, weiter zuhoeren
//   Per Stimme durchgehen     -- die offenen Entscheidungen der Reihe nach
// Aendern tut das Gespraech nur auf Bestaetigung: Knopf, oder ein "ja" auf den
// letzten Vorschlag (gesprochen oder getippt).
//
// Die Endlosschleife vom 01.10.2026: die Freisprech-Schleife ist EINE lange
// laufende Funktion und sah deshalb immer den Stand von ihrem Start --
// Gespraechskennung null (jeder Satz ein neues Gespraech) und keine offenen
// Vorschlaege (ein "ja" fuehrte nie etwas aus). Kennung und Verlauf liegen
// deshalb zusaetzlich in Refs, die die Schleife immer aktuell liest.
import { html, useState, useEffect, useRef, Icon, Md, toast, fehlerMelden, aktualisieren, navigiere, rolleName, bus } from "./ui.js";
import { api, strom } from "./api.js";
import { Composer } from "./composer.js";
import { boardFrageMerken } from "./board.js";
import { aufnehmen, erkennen, vorlesen, vorleseStopp, mikrofonGrund } from "./stimme.js";

const NEIN_WORT = /\b(nein|nee|nö|nicht|lieber nicht|ablehnen|falsch|stopp)\b/i;
const JA_WORT = /\b(ja|jawohl|jep|genau|klar|gerne|ok|okay|einverstanden|passt|richtig|bitte|mach(e)? (das|es)|tu (das|es)|(kannst|sollst|darfst) du (so )?(machen|tun)|so machen|so tun|anlegen|merken|ausführen)\b/i;
const SPAETER = /^(später|spaeter|weiter|nächste|naechste|überspringen|ueberspringen|skip|egal)\b/i;
const ENDE = /^(stopp|stop|ende|beenden|aufhören|aufhoeren|das wars|das war's|danke,? das (war|wars)|tschüss|tschuess|schluss)\b/i;
// "Dialog beenden", "wir beenden das Gespräch", "beende die Unterhaltung" ...
// -- irgendwo im Satz, aber nur in kurzen Saetzen: ein langer Satz, der das
// Wort Gespraech enthaelt, ist eine Frage und kein Abschied.
const ENDE_SATZ = /\b(dialog|gespräch|gespraech|unterhaltung|freisprechen|talk)\b.{0,20}\b(beenden|beende|beendet|ende|schließen|schliessen|aus|vorbei)\b|\b(beende|beenden|schließ|schliess|schließe)\w*\b.{0,20}\b(dialog|gespräch|gespraech|unterhaltung)\b/i;
const istEnde = (t) => ENDE.test(t) || (t.split(/\s+/).length <= 10 && ENDE_SATZ.test(t));
const reinigen = (t) => String(t || "").trim().replace(/[.!?,]+$/, "").trim();
// Ein kurzes Ja ohne Nein -- laengere Saetze sind eine neue Frage, kein Ja.
const istJa = (t) => t.split(/\s+/).length <= 10 && JA_WORT.test(t) && !NEIN_WORT.test(t);
const istNein = (t) => t.split(/\s+/).length <= 5 && NEIN_WORT.test(t) && !JA_WORT.test(t.replace(/\bnein\b/i, ""));

// Bild oder Visualisierung aus dem Gespraech: Fortschritt, dann Vorschau mit
// Grossansicht und Download. Fragt den Stand ab, bis es fertig ist -- auch nach
// einem Neuladen, denn das Ergebnis liegt auf dem Server (medien.py).
function MedienKarte({ m }) {
  const [s, setS] = useState({ stand: "laeuft" });
  const [jetzt, setJetzt] = useState(Date.now());
  useEffect(() => {
    let aus = false;
    const holen = async () => {
      try { const d = await api("/medien/" + m.id); if (aus) return; setS(d); if (d.stand === "laeuft") setTimeout(holen, 1500); }
      catch (e) { if (!aus) setS({ stand: "fehler", fehler: "Nicht mehr vorhanden (der Dienst wurde neu gestartet, bevor es fertig war)." }); }
    };
    holen();
    const i = setInterval(() => setJetzt(Date.now()), 1000);
    return () => { aus = true; clearInterval(i); };
  }, [m.id]);
  const was = m.art === "bild" ? "Bild" : "Visualisierung";
  if (s.stand === "laeuft") {
    const sek = s.start ? Math.round(jetzt / 1000 - s.start) : null;
    return html`<div class="medien-karte laeuft"><div class="medien-platz"><span class="medien-dreh"></span></div>
      <div class="medien-fuss"><b>${m.titel}</b><span class="leise klein">${was} entsteht${sek != null ? " · " + sek + " s" : ""} …</span></div></div>`;
  }
  if (s.stand === "fehler") return html`<div class="medien-karte"><div class="fehlerbox">${was} ging nicht: ${s.fehler}</div></div>`;
  const url = "/api/medien/datei/" + s.datei;
  return html`<div class="medien-karte">
    <a href=${url} target="_blank" rel="noopener" title="Groß ansehen"><img src=${url} alt=${m.titel} loading="lazy" /></a>
    <div class="medien-fuss"><b>${m.titel}</b>
      <span class="knopfreihe">
        <a class="btn klein" href=${url} target="_blank" rel="noopener" title="In neuem Tab groß ansehen"><${Icon} n="voll" g=${13} />Groß</a>
        <a class="btn klein primaer" href=${url + "?download=1"} download title=${"Herunterladen (" + (s.datei.endsWith(".svg") ? "SVG" : "PNG") + ")"}><${Icon} n="download" g=${13} />Download</a>
      </span></div>
  </div>`;
}

function StimmeKreis({ zustand, pegel, text, beiKlick }) {
  const TXT = { bereit: "Antippen und sprechen", hoert: "Ich höre zu …", erkennt: "Verstehe …", denkt: "Denke nach …", spricht: "Spreche …" };
  // Kompakt (Veiko, 01.10.: der grosse Kreis war zu gross und seine Wellen
  // strahlten ueber die Nachbarn). Die Wellen laufen jetzt INNERHALB eines
  // festen Feldes um den Kreis aus; die Lautstaerke hebt ihn nur leicht an.
  const s = zustand === "hoert" ? 1 + Math.min(0.12, pegel * 0.18) : 1;
  return html`<div class=${"stimme-kreis " + zustand} role="status">
    <span class="kreis-feld"><button class="kreis" style=${`transform:scale(${s})`} onClick=${beiKlick}
      aria-label=${zustand === "bereit" ? "Freisprechen starten" : zustand === "hoert" ? "Fertig gesprochen" : "Freisprechen beenden"}
      title=${zustand === "bereit" ? "Freisprechen starten" : zustand === "hoert" ? "Antippen, wenn du fertig bist" : "Antippen zum Beenden"}>
      <${Icon} n=${zustand === "denkt" || zustand === "erkennt" ? "mehr" : zustand === "spricht" ? "welle" : "mic"} g=${19} w=${2.1} />
    </button></span>
    <span class="kreis-text"><span class="zustand">${TXT[zustand] || ""}</span>
    ${text ? html`<span class="unter">${text}</span>` : zustand === "hoert" ? html`<span class="unter">Sag „Dialog beenden“, wenn du fertig bist.</span>` : null}</span>
  </div>`;
}

export function Talk({ zu, kontext, setKontext, start }) {
  const [gid, setGidState] = useState(() => { try { return localStorage.getItem("vvec_talk_g") || null; } catch (e) { return null; } });
  const [msgs, setMsgsState] = useState([]);
  const [lauf, setLauf] = useState(null); // {text}
  const [frei, setFrei] = useState(null); // {modus:"frei"|"durch", zustand, text, pegel}
  const gidRef = useRef(gid);
  const msgsRef = useRef([]);
  const laufRef = useRef(false);
  const kontextRef = useRef(kontext);
  const verlaufRef = useRef(null);
  const abbruch = useRef(null);
  const freiAn = useRef(false);
  const aufn = useRef(null);
  const letzterStart = useRef(0);
  const ausKopf = useRef(false);
  kontextRef.current = kontext;

  const setGid = (g) => { gidRef.current = g; setGidState(g); };
  const setMsgs = (f) => setMsgsState((alt) => { const neu = typeof f === "function" ? f(alt) : f; msgsRef.current = neu; return neu; });

  useEffect(() => { try { gid ? localStorage.setItem("vvec_talk_g", gid) : localStorage.removeItem("vvec_talk_g"); } catch (e) { /* egal */ } }, [gid]);
  useEffect(() => {
    if (!gid) { setMsgs([]); return; }
    api("/talk/" + gid).then((d) => setMsgs(d.nachrichten.map(zuAnzeige))).catch(() => { setGid(null); setMsgs([]); });
  }, []);
  useEffect(() => { const v = verlaufRef.current; if (v) v.scrollTop = v.scrollHeight; }, [msgs, lauf, frei && frei.zustand]);
  useEffect(() => {
    if (!start || start.n === letzterStart.current) return;
    letzterStart.current = start.n;
    if (start.frei) { ausKopf.current = !!start.ausKopf; if (!freiAn.current) freiStart(); }
    else if (start.durchgehen) durchgehen();
    else if (start.text) senden(start.text, [], false);
  }, [start]);
  useEffect(() => () => { freiAn.current = false; if (aufn.current) aufn.current.abbrechen(); vorleseStopp(); bus.sende("dialog-zustand", null); }, []);
  // Der Sprechen-Knopf im Kopf zeigt, was gerade passiert, und kann beenden.
  useEffect(() => { bus.sende("dialog-zustand", frei ? frei.zustand : null); }, [frei && frei.zustand]);
  useEffect(() => bus.an("dialog-ende", () => { ausKopf.current = false; freiStopp(); }), []);
  useEffect(() => {
    const k = (e) => { if (e.key === "Escape" && !document.querySelector(".modal-grund")) { if (freiAn.current) freiStopp(); else zu(); } };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, []);

  function zuAnzeige(m) {
    const d = m.daten || {};
    return { id: m.id, rolle: m.rolle === "du" ? "du" : "ck", text: m.rolle === "du" ? (d.anzeige ?? m.text) : m.text, vorschlaege: d.vorschlaege || [], medien: d.medien || [] };
  }

  async function senden(text, anhaenge, stimme) {
    if (laufRef.current) return false;
    laufRef.current = true;
    bus.sende("ki-start");
    setMsgs((m) => [...m, { id: "d" + Date.now(), rolle: "du", text }]);
    setLauf({ text: "" });
    const ctl = new AbortController(); abbruch.current = ctl;
    let fertig = null, stromFehler = null;
    const k = kontextRef.current;
    try {
      await strom("/talk/senden", { gespraech_id: gidRef.current, text, kontext: k ? { art: k.art, id: k.id } : null, anhaenge, stimme }, (e) => {
        if (e.typ === "start") setGid(e.gespraech_id);
        else if (e.typ === "text") setLauf((l) => ({ text: (l ? l.text : "") + e.t }));
        else if (e.typ === "fertig") fertig = e;
        else if (e.typ === "fehler") stromFehler = e.text;
      }, ctl.signal);
      if (stromFehler) throw new Error(stromFehler);
    } catch (e) {
      if (e.name !== "AbortError") { fehlerMelden(e); setMsgs((m) => [...m, { id: "f" + Date.now(), rolle: "ck", text: "Das hat nicht geklappt: " + e.message, vorschlaege: [] }]); }
    }
    laufRef.current = false;
    setLauf(null);
    if (fertig) {
      setMsgs((m) => [...m, { id: fertig.nachricht_id, rolle: "ck", text: fertig.text, vorschlaege: fertig.vorschlaege, medien: fertig.medien || [] }]);
      // "Zeig mir …": aendert nichts, deshalb sofort und ohne Knopf.
      const z = (fertig.zeigen || [])[0];
      if (z && z.projekt_id) navigiere("/projects/" + z.projekt_id + (z.ziel && z.ziel !== "ueberblick" ? "/" + z.ziel : ""));
      else if (z && z.ziel) {
        // Ein Bereich des Cockpits; eine mitgegebene Frage ans Board stellt das Board selbst.
        if (z.ziel === "board" && z.frage) boardFrageMerken(z.frage);
        navigiere("/" + z.ziel);
      }
      // BrainStrom/ExO haben ihren Stand auf dem Server geaendert: Ansicht sofort nachziehen.
      bus.sende("verfahren-neu");
      // Nach Veikos Ja hat der Server schon ausgefuehrt (gespraech.senden) -- Lage nachziehen.
      if ((fertig.vorschlaege || []).some((v) => v.erledigt)) aktualisieren();
      return fertig;
    }
    return true;
  }

  async function ausfuehren(mid, indizes) {
    try {
      const r = await api("/talk/ausfuehren", { methode: "POST", daten: { nachricht_id: mid, indizes } });
      setMsgs((m) => m.map((x) => x.id === mid ? { ...x, vorschlaege: x.vorschlaege.map((v, i) => indizes.includes(i) ? { ...v, erledigt: true } : v) } : x));
      const fehl = r.ergebnisse.filter((x) => !x.ok);
      if (fehl.length) toast("Nicht alles ging: " + fehl.map((f) => f.grund).join("; "), { fehler: true });
      else {
        const neo = r.ergebnisse.find((x) => x.neo_gespraech);
        const vg = r.ergebnisse.find((x) => x.vorgang_id);
        toast(neo ? "Neo arbeitet daran." : vg ? "Ist beim Team. Das Ergebnis erscheint in der Inbox." : "Erledigt.",
          neo ? { aktion: { text: "Zu Neo", fn: () => navigiere("/neo/" + neo.neo_gespraech) } }
            : vg ? { aktion: { text: "Ansehen", fn: () => navigiere("/inbox/" + vg.vorgang_id) } } : {});
      }
      aktualisieren();
      return !fehl.length;
    } catch (e) { fehlerMelden(e); return false; }
  }

  function offeneVorschlaege() {
    const letzte = [...msgsRef.current].reverse().find((m) => m.rolle === "ck");
    if (!letzte || !letzte.vorschlaege || typeof letzte.id !== "number") return null;
    const idx = letzte.vorschlaege.map((v, i) => (!v.erledigt ? i : -1)).filter((i) => i >= 0);
    return idx.length ? { mid: letzte.id, idx } : null;
  }

  // Getippt oder gesprochen: ein Ja auf offene Vorschlaege fuehrt sie aus,
  // ein Nein verwirft sie -- statt die KI dasselbe noch einmal fragen zu lassen.
  async function eingabe(text, anhaenge, stimme) {
    const t = reinigen(text);
    const offen = offeneVorschlaege();
    if (offen && t && !(anhaenge || []).length) {
      if (istJa(t)) {
        setMsgs((m) => [...m, { id: "d" + Date.now(), rolle: "du", text }]);
        const ok = await ausfuehren(offen.mid, offen.idx);
        const antwort = ok ? "Erledigt." : "Das ging leider nicht ganz. Details stehen in der Meldung.";
        setMsgs((m) => [...m, { id: "s" + Date.now(), rolle: "ck", text: antwort, vorschlaege: [] }]);
        return { text: antwort, vorschlaege: [] };
      }
      if (istNein(t)) {
        setMsgs((m) => m.map((x) => x.id === offen.mid ? { ...x, vorschlaege: x.vorschlaege.map((v) => v.erledigt ? v : { ...v, erledigt: true, abgelehnt: true }) } : x));
        setMsgs((m) => [...m, { id: "d" + Date.now(), rolle: "du", text }, { id: "s" + Date.now() + 1, rolle: "ck", text: "Gut, dann nicht.", vorschlaege: [] }]);
        return { text: "Gut, dann nicht.", vorschlaege: [] };
      }
    }
    return senden(text || "(siehe Anhang)", anhaenge, stimme);
  }

  // ------------------------------------------------------------ Freisprechen
  async function zuhoeren() {
    setFrei((f) => f && { ...f, zustand: "hoert", pegel: 0 });
    const ctl = await aufnehmen({ stilleStopp: true, maxSek: 60, pegel: (p) => setFrei((f) => f && { ...f, pegel: p }) });
    aufn.current = ctl;
    const blob = await ctl.ende;
    aufn.current = null;
    if (!freiAn.current || !ctl.gesprochen()) return "";
    setFrei((f) => f && { ...f, zustand: "erkennt" });
    const d = await erkennen(blob);
    return reinigen(d.text);
  }
  async function sprechen(text) {
    if (!freiAn.current || !text) return;
    setFrei((f) => f && { ...f, zustand: "spricht", text: "" });
    try { await vorlesen(text); } catch (e) { /* ohne Ton weiter */ }
  }

  async function freiStart() {
    const grund = mikrofonGrund();
    if (grund) { toast(grund, { fehler: true }); return; }
    freiAn.current = true;
    setFrei({ modus: "frei", zustand: "hoert", pegel: 0, text: "" });
    // Im Projekt (oder an einer Akte) ist der Rahmen sofort gesetzt -- und das
    // Cockpit sagt ihn an, damit klar ist, worueber gesprochen wird.
    const k = kontextRef.current;
    if (k && k.art === "brainstrom") {
      // In BrainStrom gleich die offene Frage vorlesen -- dann kann Veiko einfach antworten.
      let s = null;
      try { s = await api("/brainstrom"); } catch (e) { /* ohne Stand weiter */ }
      if (s && s.phase === "frage" && s.frage && !s.laeuft) {
        const opt = (s.frage.optionen || []).map((o, i) => `${i + 1}. ${o}`).join("; ");
        await sprechen(`Wir sind bei BrainStrom. Frage ${s.verlauf.length + 1}: ${s.frage.text}${opt ? " Zur Auswahl: " + opt + "." : ""}`);
      } else if (s && s.phase === "wege" && s.wege) {
        await sprechen("Wir sind bei BrainStrom. Zur Wahl stehen: " + s.wege.map((w, i) => `${i + 1}. ${w.name}`).join("; ") + ". Welchen Weg nehmen wir?");
      } else if (s && s.phase === "start") {
        await sprechen("Wir sind bei BrainStrom. Worum geht es? Ein, zwei Sätze reichen.");
      } else {
        await sprechen("Wir sind bei BrainStrom. Was möchtest du tun?");
      }
    } else if (k && k.titel) {
      const was = { projekt: "das Projekt", vorgang: "den Vorgang", ergebnis: "das Ergebnis", exo: "", watchdog: "den" }[k.art] || "";
      await sprechen(`Wir sprechen über ${was} ${k.titel}. Was möchtest du wissen oder tun?`.replace("über  ", "über "));
    }
    let leer = 0;
    while (freiAn.current) {
      let t = "";
      try { t = await zuhoeren(); } catch (e) { toast(e.message, { fehler: true }); break; }
      if (!freiAn.current) break;
      if (!t) { if (++leer >= 3) { await sprechen("Ich höre nichts mehr und beende das Freisprechen."); break; } continue; }
      leer = 0;
      if (istEnde(t)) {
        setMsgs((m) => [...m, { id: "d" + Date.now(), rolle: "du", text: t }]);
        await sprechen("Gut, ich beende unser Gespräch.");
        // Ueber den Kopf begonnen: dann auch ohne weiteren Klick wieder zu.
        if (ausKopf.current) { ausKopf.current = false; freiStopp(); zu(); return; }
        break;
      }
      setFrei((f) => f && { ...f, zustand: "denkt", text: t });
      const r = await eingabe(t, [], true);
      if (r && r.text) await sprechen(r.text);
    }
    freiStopp();
  }
  function freiStopp() {
    freiAn.current = false;
    if (aufn.current) aufn.current.abbrechen();
    vorleseStopp();
    setFrei(null);
  }
  function kreisKlick() {
    if (!frei) return freiStart();
    if (frei.zustand === "hoert" && aufn.current) aufn.current.stopp();
    else freiStopp();
  }

  // ------------------------------------------------------------ Durchgehen
  function systemZeile(text) { setMsgs((m) => [...m, { id: "s" + Date.now() + Math.random(), rolle: "ck", text, vorschlaege: [] }]); }

  async function durchgehen() {
    const grund = mikrofonGrund();
    let lage;
    try { lage = await api("/lage"); } catch (e) { fehlerMelden(e); return; }
    const liste = lage.entscheidungen || [];
    if (!liste.length) { systemZeile("Es wartet keine Entscheidung auf dich."); return; }
    if (grund) { toast(grund, { fehler: true }); return; }
    freiAn.current = true;
    setFrei({ modus: "durch", zustand: "spricht", pegel: 0, text: "" });
    await sprechen(`Es ${liste.length === 1 ? "wartet eine Entscheidung" : `warten ${liste.length} Entscheidungen`}. Sag ja, nein, später, oder antworte frei. Mit Stopp hörst du auf.`);
    let erledigt = 0;
    for (let i = 0; i < liste.length && freiAn.current; i++) {
      const e = liste[i];
      systemZeile(`**${i + 1} von ${liste.length}** · ${rolleName(e.wer)}: ${e.frage}`);
      await sprechen(`${rolleName(e.wer)} ${e.art === "rueckfrage" ? "fragt" : "schlägt vor"}: ${e.frage}`);
      setFrei((f) => f && { ...f, text: `${i + 1} von ${liste.length}` });
      let versuch = 0;
      while (freiAn.current) {
        let t = "";
        try { t = await zuhoeren(); } catch (x) { toast(x.message, { fehler: true }); freiAn.current = false; break; }
        if (!freiAn.current) break;
        if (!t) { if (++versuch >= 2) { await sprechen("Ich lasse das für später."); break; } await sprechen("Ich habe nichts gehört. Ja, nein oder später?"); continue; }
        setMsgs((m) => [...m, { id: "d" + Date.now(), rolle: "du", text: t }]);
        if (istEnde(t)) { freiAn.current = false; break; }
        let antwort = null, text = "";
        if (SPAETER.test(t)) antwort = "spaeter";
        else if (e.art === "rueckfrage") { antwort = istNein(t) ? "nein" : "ja"; text = antwort === "ja" ? t : ""; }
        else if (istJa(t)) antwort = "ja";
        else if (istNein(t)) antwort = "nein";
        if (!antwort) { if (++versuch >= 2) { await sprechen("Ich lasse das für später."); break; } await sprechen("Bitte sag ja, nein oder später."); continue; }
        try {
          await api("/entscheidungen/" + e.id, { methode: "POST", daten: { antwort, text } });
          erledigt += antwort === "spaeter" ? 0 : 1;
          const q = { ja: e.art === "rueckfrage" ? "Antwort ist beim Team." : "Erledigt.", nein: "Abgelehnt.", spaeter: "Später." }[antwort];
          systemZeile(q);
          await sprechen(q);
        } catch (x) { systemZeile("Ging nicht: " + x.message); await sprechen("Das ging leider nicht."); }
        break;
      }
    }
    if (freiAn.current) await sprechen(erledigt ? `Das waren alle. ${erledigt} erledigt.` : "Das waren alle.");
    aktualisieren();
    freiStopp();
  }

  function neu() { if (laufRef.current) return; setGid(null); setMsgs([]); }

  return html`<aside class="talk" aria-label="Talk">
    <div class="talk-kopf">
      <h2><${Icon} n="talk" g=${17} />Talk</h2>
      ${frei && html`<button class="btn klein" onClick=${() => { ausKopf.current = false; freiStopp(); }} title="Gespräch beenden (oder sag „Dialog beenden“)"><${Icon} n="stopp" g=${12} />Beenden</button>`}
      <button class="btn geist icon" onClick=${neu} title="Neues Gespräch" aria-label="Neues Gespräch"><${Icon} n="neu" g=${17} /></button>
      <button class="btn geist icon" onClick=${zu} title="Schließen (Esc)" aria-label="Talk schließen"><${Icon} n="x" /></button>
    </div>
    ${kontext && html`<div class="talk-kontext"><${Icon} n="auge" g=${14} /><span>schaut auf: ${kontext.titel || kontext.art}</span>
      <button class="btn klein geist icon" onClick=${() => setKontext(null)} aria-label="Bezug entfernen" title="Ohne Bezug weiterreden"><${Icon} n="x" g=${13} /></button></div>`}
    ${frei && html`<${StimmeKreis} zustand=${frei.zustand} pegel=${frei.pegel || 0} text=${frei.text} beiKlick=${kreisKlick} />`}
    <div class="talk-verlauf" ref=${verlaufRef}>
      ${!msgs.length && !lauf && !frei && html`<div class="talk-start">
        <p style="text-align:center">Schreib mir hier, oder tipp oben auf <b>Sprechen</b> und rede einfach los. Ich ändere nichts ohne dein Ja. Zum Schluss genügt „Dialog beenden“.</p>
        <div class="knopfreihe" style="justify-content:center">
          <button class="btn klein" onClick=${() => senden("Was liegt an?", [], false)}>Was liegt an?</button>
          <button class="btn klein" onClick=${durchgehen}><${Icon} n="play" g=${12} />Entscheidungen per Stimme</button>
          ${kontext && html`<button class="btn klein" onClick=${() => senden("Fass mir das kurz zusammen und sag, was als Nächstes zu tun ist.", [], false)}>Zusammenfassen</button>`}
        </div></div>`}
      ${msgs.map((m) => m.rolle === "du"
        ? html`<div class="talk-blase du" key=${m.id}>${m.text}</div>`
        : html`<div class="talk-blase ck" key=${m.id}>
            <${Md} text=${m.text} />
            ${m.vorschlaege && m.vorschlaege.map((v, i) => html`<div class=${"vorschlag" + (v.erledigt && !v.abgelehnt ? " erledigt" : "")} key=${i}>
              <span style=${v.abgelehnt ? "text-decoration:line-through;color:var(--ink-3)" : ""}>${v.label}</span>
              ${v.abgelehnt ? html`<span class="pill">abgelehnt</span>` : v.erledigt ? html`<span class="pill gruen">erledigt</span>`
                : html`<button class="btn klein primaer" onClick=${() => ausfuehren(m.id, [i])}>Ausführen</button>`}
            </div>`)}
            ${m.vorschlaege && m.vorschlaege.filter((v) => !v.erledigt).length > 1 && html`<button class="btn klein" style="margin-top:6px"
              onClick=${() => ausfuehren(m.id, m.vorschlaege.map((v, i) => (v.erledigt ? -1 : i)).filter((i) => i >= 0))}>Alle ausführen</button>`}
            ${(m.medien || []).map((x) => html`<${MedienKarte} key=${x.id} m=${x} />`)}
            ${typeof m.id === "number" && html`<button class="btn klein geist" style="margin-top:4px" title="Vorlesen" onClick=${() => vorlesen(m.text).catch((e) => toast(e.message, { fehler: true }))}><${Icon} n="play" g=${12} />Vorlesen</button>`}
          </div>`)}
      ${lauf && html`<div class="talk-blase ck">${lauf.text ? html`<${Md} text=${lauf.text} />` : html`<span class="leise">Denke nach …</span>`}</div>`}
    </div>
    <div class="talk-eingabe">
      <${Composer} platzhalter=${kontext ? "Frag zu „" + (kontext.titel || "").slice(0, 40) + "“ …" : "Frag oder beauftrage dein Team … („ja“ bestätigt den letzten Vorschlag)"}
        beimSenden=${(t, a) => eingabe(t, a, false).then(() => true)} laeuft=${!!lauf}
        beimStoppen=${() => abbruch.current && abbruch.current.abort()} entwurfKey="talk" hinweis="" />
    </div>
  </aside>`;
}
