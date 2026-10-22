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
import { Zuordnung, gespraechOeffnen } from "./zuordnung.js";
import { escFensterZu, useEsc, html, useState, useEffect, useRef, Icon, Md, toast, fehlerMelden, aktualisieren, navigiere, rolleName, bus, talkSchalter, TalkSchalter, GlobusKnopf, Ziehgriff } from "./ui.js";
import { api, strom } from "./api.js";
import { Composer } from "./composer.js";
import { boardFrageMerken } from "./board.js";
import { aufnehmen, lauschen, erkennen, vorlesen, vorleseStopp, mikrofonGrund, mikroAnfordern, mikroFreigeben } from "./stimme.js";

const NEIN_WORT = /\b(nein|nee|nö|nicht|lieber nicht|ablehnen|falsch|stopp)\b/i;
const JA_WORT = /\b(ja|jawohl|jep|genau|klar|gerne|ok|okay|einverstanden|passt|richtig|bitte|mach(e)? (das|es)|tu (das|es)|(kannst|sollst|darfst) du (so )?(machen|tun)|so machen|so tun|anlegen|merken|ausführen)\b/i;
const SPAETER = /^(später|spaeter|weiter|nächste|naechste|überspringen|ueberspringen|skip|egal)\b/i;
const ENDE = /^(stopp|stop|ende|beenden|aufhören|aufhoeren|das wars|das war's|danke,? das (war|wars)|tschüss|tschuess|schluss)\b/i;
// "Dialog beenden", "wir beenden das Gespräch", "beende die Unterhaltung" ...
// -- irgendwo im Satz, aber nur in kurzen Saetzen: ein langer Satz, der das
// Wort Gespraech enthaelt, ist eine Frage und kein Abschied.
const ENDE_SATZ = /\b(dialog|gespräch|gespraech|unterhaltung|freisprechen|talk)\b.{0,20}\b(beenden|beende|beendet|ende|schließen|schliessen|aus|vorbei)\b|\b(beende|beenden|schließ|schliess|schließe)\w*\b.{0,20}\b(dialog|gespräch|gespraech|unterhaltung)\b/i;
// Whisper hoert "Dialog beenden" auch als "Dialogbein" (19.10.2026) -- in einem ganz
// kurzen Satz reicht "Dialog" plus "be…" oder "bin".
const ENDE_HOERFEHLER = /\bdialog\s*(be\w*|bin)\b/i;
const istEnde = (t) => ENDE.test(t) || (t.split(/\s+/).length <= 10 && ENDE_SATZ.test(t))
  || (t.split(/\s+/).length <= 4 && ENDE_HOERFEHLER.test(t));
const reinigen = (t) => String(t || "").trim().replace(/[.!?,]+$/, "").trim();
// Ein kurzes Ja ohne Nein -- laengere Saetze sind eine neue Frage, kein Ja. Beginnt der
// Satz mit Ja, darf er laenger sein ("Ja, das solltest du vorhin schon ausführen. Führe
// das jetzt aus" ging am 19.10.2026 als neue Frage ans Modell, und nichts lief).
const JA_ANFANG = /^(ja|jawohl|genau|okay|ok|gerne|klar|einverstanden)\b/i;
const istJa = (t) => !NEIN_WORT.test(t) && ((t.split(/\s+/).length <= 10 && JA_WORT.test(t)) || (t.split(/\s+/).length <= 18 && JA_ANFANG.test(t)));
// "bitte" zaehlt hier nicht als Ja: "Nein, warte damit bitte" war sonst kein Nein (19.10.2026).
const istNein = (t) => t.split(/\s+/).length <= 5 && NEIN_WORT.test(t) && !JA_WORT.test(t.replace(/\b(nein|bitte)\b/gi, ""));

// Was eine ausgefuehrte Aktion angelegt hat, ist einen Klick entfernt (19.10.2026, Veiko:
// "wenn ich ueber Talk Aktionen definiert habe, sollen sie so schnell wie moeglich im Cockpit
// sichtbar sein").
// Blaettern per Sprache (22.10.2026, Veiko: "scroll mal weiter nach unten"). Gemeint ist das
// oberste offene Fenster, sonst die Seite -- nie Talk selbst. In einer Ergebnisansicht (ein
// abgeschotteter Rahmen, das Cockpit kommt nicht hinein) bekommt der Rahmen eine Nachricht
// und scrollt selbst (api.ESC_WEITERGEBEN).
function blaettern(richtung) {
  const sichtbar = (el) => el && el.offsetParent !== null && el.getBoundingClientRect().height > 40;
  const modale = [...document.querySelectorAll(".modal")].filter(sichtbar);
  const bereich = modale[modale.length - 1] || document.querySelector("main") || document.body;
  const rahmen = [...bereich.querySelectorAll("iframe")].filter((f) => sichtbar(f) && !f.closest(".ub-bild"))
    .sort((a, b) => b.getBoundingClientRect().height - a.getBoundingClientRect().height)[0];
  if (rahmen && rahmen.getBoundingClientRect().height > bereich.getBoundingClientRect().height * 0.5) {
    try { rahmen.contentWindow.postMessage({ vvecScroll: richtung }, "*"); return; } catch (e) { /* weiter mit dem Fenster */ }
  }
  // Der groesste scrollbare Bereich im Fenster bzw. auf der Seite.
  const kandidaten = [bereich, ...bereich.querySelectorAll("*")].filter((el) => {
    if (el.closest && el.closest(".talk")) return false;
    const s = getComputedStyle(el);
    return /(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight + 20 && sichtbar(el);
  }).sort((a, b) => b.clientHeight - a.clientHeight);
  const ziel = kandidaten[0] || document.scrollingElement;
  const h = Math.round((ziel === document.scrollingElement ? innerHeight : ziel.clientHeight) * 0.8);
  const vorher = ziel.scrollTop;
  const wohin = richtung === "runter" ? vorher + h : richtung === "hoch" ? vorher - h : richtung === "anfang" ? 0 : ziel.scrollHeight;
  ziel.scrollTo({ top: wohin, behavior: "smooth" });
  // Weiches Scrollen laeuft nicht ueberall (gemessen: ohne Bildwiederholung bewegte sich nichts) --
  // steht es nach einem Moment noch, springt die Seite direkt.
  setTimeout(() => { if (ziel.scrollTop === vorher) ziel.scrollTop = wohin; }, 700);
}

function ansehenKnopf(r) {
  if (!r || !r.ok) return null;
  const ziel = r.mail_id ? () => navigiere("/mail/" + r.mail_id)
    : r.daily_id ? () => navigiere("/daily/" + r.daily_id)
    : r.langlauf_id ? () => navigiere("/langlauf/" + r.langlauf_id)
    : r.vorgang_id ? () => navigiere("/inbox/" + r.vorgang_id)
    : r.neo_gespraech ? () => navigiere("/neo/" + r.neo_gespraech)
    : r.geprueft_wird ? () => bus.sende("ergebnis-zeigen", r.geprueft_wird)
    : r.projekt_id ? () => navigiere("/projects/" + r.projekt_id) : null;
  return ziel && html`<button class="btn klein" onClick=${ziel}>Ansehen</button>`;
}

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

// Wozu eine Antwort gehoert (gespraech.bezug_erkennen, 19.10.2026): Talk ordnet eine
// Nachricht von selbst einer passenden Aufgabe zu -- was daraus entsteht (Dossier,
// Ausarbeitung), landet dort. Die Zeile macht das sichtbar und fuehrt hin.
function BezugZeile({ b }) {
  const hin = () => (b.aufgabe_id ? bus.sende("aufgabe-zeigen", b.aufgabe_id) : navigiere("/projects/" + b.projekt_id));
  return html`<button class="talk-bezug" onClick=${hin} title=${b.aufgabe_id ? "Aufgabe öffnen" : "Projekt öffnen"}>
    <${Icon} n="projects" g=${12} /><span>Gehört zu ${b.aufgabe_titel ? html`<b>${b.aufgabe_titel}</b>${b.projekt_name ? " · " + b.projekt_name : ""}` : html`<b>${b.projekt_name}</b>`}</span></button>`;
}

function StimmeKreis({ zustand, pegel, text, beiKlick }) {
  const TXT = { bereit: "Antippen und sprechen", hoert: "Ich höre zu …", erkennt: "Verstehe …", denkt: "Denke nach …", spricht: "Spreche …", pausiert: "Pausiert" };
  // Kompakt (Veiko, 01.10.: der grosse Kreis war zu gross und seine Wellen
  // strahlten ueber die Nachbarn). Die Wellen laufen jetzt INNERHALB eines
  // festen Feldes um den Kreis aus; die Lautstaerke hebt ihn nur leicht an.
  const s = zustand === "hoert" ? 1 + Math.min(0.12, pegel * 0.18) : 1;
  return html`<div class=${"stimme-kreis " + zustand} role="status">
    <span class="kreis-feld"><button class="kreis" style=${`transform:scale(${s})`} onClick=${beiKlick}
      aria-label=${zustand === "bereit" ? "Freisprechen starten" : zustand === "pausiert" ? "Weiter zuhören" : zustand === "spricht" ? "Unterbrechen und selbst sprechen" : "Gespräch beenden und Talk schließen"}
      title=${zustand === "bereit" ? "Freisprechen starten" : zustand === "pausiert" ? "Antippen: Talk hört wieder zu" : zustand === "spricht" ? "Antippen oder einfach reinsprechen: Talk hört auf und hört dir zu" : "Antippen: Gespräch beenden und Talk schließen"}>
      <${Icon} n=${zustand === "denkt" || zustand === "erkennt" ? "mehr" : zustand === "spricht" ? "welle" : zustand === "pausiert" ? "play" : "mic"} g=${19} w=${2.1} />
    </button></span>
    <span class="kreis-text"><span class="zustand">${TXT[zustand] || ""}</span>
    ${text ? html`<span class="unter">${text}</span>` : zustand === "hoert" ? html`<span class="unter">Zum Beenden antippen oder „Dialog beenden“ sagen.</span>` : zustand === "spricht" ? html`<span class="unter">Unterbrechen: einfach reinsprechen oder antippen.</span>` : null}</span>
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
  const talkFeld = useRef(null);
  const abbruch = useRef(null);
  const freiAn = useRef(false);
  const vorgriff = useRef(null);
  const letzterSatz = useRef(null);   // was eine per Ja ausgefuehrte Aktion sagt ("Gesendet an …")      // was Veiko Talk ins Wort gesagt hat (sprechen -> zuhoeren)
  const lauschRef = useRef(null);     // das Mithoeren, waehrend Talk spricht
  const pausiertRef = useRef(null);   // Grund, warum Talk gerade nicht zuhoert (Vorfahrt am Mikrofon)
  const runde = useRef(0);             // jede Freisprech-Schleife hat ihre Nummer: eine alte, die noch auf eine Antwort wartet, laeuft nach dem Weiter nicht zweimal mit
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
    // Ein zugeordnetes Gespraech von der Projektseite aus wieder oeffnen (17.10.2026).
    if (start.gid) { setGid(start.gid); return; }
    if (start.frei) { ausKopf.current = !!start.ausKopf; if (!freiAn.current) freiStart(); }
    else if (start.durchgehen) durchgehen();
    else if (start.text) senden(start.text, [], false);
    // Vorlage ins Feld statt gleich zu senden (Klick auf eine Aufgabe im Briefing):
    // Veiko sagt selbst, was mit der Aufgabe passieren soll.
    else if (start.vorlage) setTimeout(() => talkFeld.current && talkFeld.current.setzen(start.vorlage), 60);
  }, [start]);
  useEffect(() => () => { freiAn.current = false; pausiertRef.current = null; if (aufn.current) aufn.current.abbrechen(); if (lauschRef.current) lauschRef.current.abbrechen(); vorleseStopp(); mikroFreigeben("talk"); bus.sende("dialog-zustand", null); }, []);
  // Der Sprechen-Knopf im Kopf zeigt, was gerade passiert, und kann beenden.
  useEffect(() => { bus.sende("dialog-zustand", frei ? frei.zustand : null); }, [frei && frei.zustand]);
  useEffect(() => bus.an("dialog-ende", () => { ausKopf.current = false; freiBeenden(); zu(); }), []);
  useEffect(() => bus.an("dialog-weiter", () => { if (pausiertRef.current) freiStart(); }), []);
  useEsc(() => { if (freiAn.current || pausiertRef.current) freiBeenden(); else zu(); }, true, "talk");
  // Vorwaermen (19.10.2026): sobald Talk aufgeht, laedt der Server Sprachmodell, Whisper und
  // Piper; alle 4 Minuten erneut, solange Talk offen ist -- das haelt das Modell im Speicher.
  const [warm, setWarm] = useState("laedt");      // laedt | bereit | fehler
  useEffect(() => {
    let weg = false;
    const los = (frisch) => api("/talk/aufwaermen", { methode: "POST", daten: { frisch } })
      .then((r) => { if (!weg) setWarm(r.modell && r.modell.ok === false ? "fehler" : "bereit"); })
      .catch(() => { if (!weg) setWarm("fehler"); });
    los(true);
    const t = setInterval(() => los(false), 4 * 60 * 1000);
    return () => { weg = true; clearInterval(t); };
  }, []);

  function zuAnzeige(m) {
    const d = m.daten || {};
    return { id: m.id, rolle: m.rolle === "du" ? "du" : "ck", text: m.rolle === "du" ? (d.anzeige ?? m.text) : m.text, vorschlaege: d.vorschlaege || [], medien: d.medien || [],
      bezug: m.rolle === "du" ? null : d.bezug || null, datei: d.datei_id || null, ergebnis: d.ergebnis_id || null };
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
      await strom("/talk/senden", { gespraech_id: gidRef.current, text, kontext: k ? { art: k.art, id: k.id } : null, anhaenge, stimme, schnell: !talkSchalter("gruendlich"), netz: talkSchalter("netz") }, (e) => {
        if (e.typ === "start") setGid(e.gespraech_id);
        else if (e.typ === "text") setLauf((l) => ({ ...(l || {}), text: (l ? l.text : "") + e.t }));
        else if (e.typ === "status") setLauf((l) => ({ ...(l || { text: "" }), status: e.text }));
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
      // Ein Ja hat die offenen Vorschlaege der vorigen Antwort ausgefuehrt (gespraech.senden, erledigt_in).
      const ei = fertig.erledigt_in;
      // Blaettern ("scroll runter") hat keinen Satz -- dann auch keine leere Sprechblase.
      setMsgs((m) => [...(ei ? m.map((x) => x.id === ei.nachricht_id ? { ...x, vorschlaege: x.vorschlaege.map((v, i) => ei.indizes.includes(i) ? { ...v, erledigt: true } : v) } : x) : m),
        ...(fertig.text ? [{ id: fertig.nachricht_id, rolle: "ck", text: fertig.text, vorschlaege: fertig.vorschlaege, medien: fertig.medien || [], bezug: fertig.bezug || null }] : [])]);
      if (ei) aktualisieren();
      // "Zeig mir …": aendert nichts, deshalb sofort und ohne Knopf.
      const z = (fertig.zeigen || [])[0];
      // "Oeffne das Ergebnis zu …": genau dieses eine Ding (gespraech.oeffnen_aufloesen).
      const o = (fertig.oeffnen || [])[0];
      // Werkzeuge (18.10.2026): das Cockpit selbst bedienen, nicht nur Seiten oeffnen.
      const w = fertig.werkzeug;
      if (w === "erfassen") bus.sende("erfassen");
      else if (w === "suche") bus.sende("suche-oeffnen");
      else if (w === "hell" || w === "dunkel") bus.sende("thema-setzen", w === "dunkel" ? "dark" : "light");
      else if (w === "zurueck") history.back();
      else if (w === "fenster_zu" && !escFensterZu("talk")) toast("Es ist kein Fenster offen.");
      else if (w === "ueberblick") bus.sende("ueberblick-zeigen");
      else if (["runter", "hoch", "anfang", "ende"].includes(w)) blaettern(w);
      // Auf dem Telefon liegt Talk ueber der ganzen Seite: nach dem Oeffnen zur Seite
      // gehen -- ausser beim Freisprechen, das liefe sonst mitten im Satz aus.
      const wegTreten = () => { if (!freiAn.current && matchMedia("(max-width:820px)").matches) setTimeout(zu, 400); };
      if ((o && !(o.art === "gespraech" && o.g_art === "talk")) || z || w === "erfassen" || w === "suche" || w === "ueberblick") wegTreten();
      if (o) {
        if (o.art === "gespraech") gespraechOeffnen({ art: o.g_art, id: o.id, wer: o.wer }, bus);
        else if (o.art === "ergebnis") bus.sende("ergebnis-zeigen", o.id);
        else if (o.art === "aufgabe") bus.sende("aufgabe-zeigen", o.id);
        else if (o.art === "notiz") bus.sende("notiz-zeigen", o.id);
        else if (o.art === "datei") bus.sende("datei-zeigen", o.id);
        else navigiere({ langlauf: "/langlauf/", vorgang: "/inbox/", projekt: "/projects/", daily: "/daily/", mail: "/mail/" }[o.art] + o.id);
        if (o.art === "mail") setTimeout(() => bus.sende("mail-neu-laden", o.id), 300);
      } else if (z && z.projekt_id) navigiere("/projects/" + z.projekt_id + (z.ziel && z.ziel !== "ueberblick" ? "/" + z.ziel : ""));
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
      setMsgs((m) => m.map((x) => x.id === mid ? { ...x, vorschlaege: x.vorschlaege.map((v, i) => indizes.includes(i) ? { ...v, erledigt: true, ergebnis: r.ergebnisse[indizes.indexOf(i)] || v.ergebnis } : v) } : x));
      const fehl = r.ergebnisse.filter((x) => !x.ok);
      const ll = r.ergebnisse.find((x) => x.ok && x.langlauf_id);
      if (fehl.length) toast("Nicht alles ging: " + fehl.map((f) => f.grund).join("; "), { fehler: true });
      else if (ll) { toast(ll.extern ? "Die abschließende Prüfung läuft." : "LongRun gestartet."); navigiere("/langlauf/" + ll.langlauf_id); }
      else if (r.ergebnisse.some((x) => x.ok && x.mail_id)) {
        const ml = r.ergebnisse.find((x) => x.mail_id);
        letzterSatz.current = ml.mail_gesendet ? "Gesendet an " + (ml.an || []).join(", ") + "." : "Der Entwurf ist geändert.";
        toast(letzterSatz.current); navigiere("/mail/" + ml.mail_id); setTimeout(() => bus.sende("mail-neu-laden", ml.mail_id), 300);
      }
      else if (r.ergebnisse.some((x) => x.ok && x.daily_id)) { toast("Daily Task erledigt."); navigiere("/daily/" + r.ergebnisse.find((x) => x.daily_id).daily_id); }
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
    // Getippt, waehrend Talk noch vorliest: die neue Eingabe hat Vorrang (22.10.2026).
    if (!stimme) vorleseStopp();
    const t = reinigen(text);
    const offen = offeneVorschlaege();
    if (offen && t && !(anhaenge || []).length) {
      if (istJa(t)) {
        setMsgs((m) => [...m, { id: "d" + Date.now(), rolle: "du", text }]);
        const ok = await ausfuehren(offen.mid, offen.idx);
        const antwort = ok ? (letzterSatz.current || "Erledigt.") : "Das ging leider nicht ganz. Details stehen in der Meldung.";
        letzterSatz.current = null;
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
    // Was Veiko Talk ins Wort gesagt hat (sprechen), ist die naechste Eingabe -- an jeder Stelle,
    // an der Talk danach zuhoeren wuerde (Gespraech, Entscheidungen durchgehen, BrainStrom).
    if (vorgriff.current) { const t = vorgriff.current; vorgriff.current = null; return t; }
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
    // Ins Wort fallen (22.10.2026): waehrend Talk spricht, hoert das Mikrofon mit. Spricht Veiko,
    // verstummt Talk sofort, und sein Satz wird die naechste Eingabe (vorgriff -> zuhoeren).
    let lausch = null;
    try {
      lausch = await lauschen({ beiEinsatz: () => { vorleseStopp(); setFrei((f) => f && { ...f, zustand: "hoert", pegel: 0, text: "" }); },
                                pegel: (p) => setFrei((f) => f && { ...f, pegel: p }) });
    } catch (e) { lausch = null; }
    lauschRef.current = lausch;
    const melden = (ergebnis) => { if (lausch) api("/stimme/diagnose", { methode: "POST", daten: { ...lausch.bericht(), ergebnis, zeichen: text.length } }).catch(() => {}); };
    try { await vorlesen(text, { vonTalk: true }); } catch (e) { /* ohne Ton weiter */ }
    if (!lausch) return;
    // Wer genau am Satzende einsetzt, soll nicht in die Luecke bis zum naechsten Zuhoeren fallen.
    for (let i = 0; i < 8 && !lausch.eingesetzt() && freiAn.current; i++) await new Promise((ok) => setTimeout(ok, 100));
    if (!lausch.eingesetzt()) { lausch.loslassen(); lauschRef.current = null; melden("kein Einwurf"); return; }
    const blob = await lausch.ende;
    lauschRef.current = null;
    if (!freiAn.current || !blob) { melden("abgebrochen"); return; }
    setFrei((f) => f && { ...f, zustand: "erkennt" });
    try {
      const t = reinigen((await erkennen(blob)).text);
      // Was nur Talks eigene Worte wiederholt, war Echo und kein Einwurf.
      const w = (s) => (String(s).toLowerCase().match(/[a-zäöüß]{3,}/g) || []);
      const eigen = new Set(w(text));
      const seine = w(t);
      const echo = seine.length && seine.filter((x) => eigen.has(x)).length / seine.length > 0.8;
      const nurStopp = /^(stopp?|halt|ruhe|sei still|still|warte|moment|okay|ok|danke)\W*$/i.test(t);
      if (t && !nurStopp && !echo) vorgriff.current = t;
      melden(!t ? "nichts verstanden" : echo ? "Echo: " + t.slice(0, 80) : nurStopp ? "nur Stopp" : "Einwurf: " + t.slice(0, 80));
    } catch (e) { melden("Erkennung gescheitert: " + e.message); }
  }

  // Vorfahrt am Mikrofon (stimme.mikroAnfordern, 19.10.2026): Talk meldet sich an; drueckt
  // Veiko woanders Diktieren oder liest etwas vor, HAELT Talk AN -- sichtbar, und erst
  // auf seinen Klick hoert es wieder zu. Vorher hoerte Talk das Diktat mit und machte
  // daraus einen eigenen Auftrag.
  function pausieren(wer) {
    pausiertRef.current = String(wer || "").startsWith("diktat")
      ? "Du diktierst gerade -- das Diktat hat Vorfahrt. Antippen, wenn Talk wieder zuhören soll."
      : "Gerade wird etwas vorgelesen. Antippen, wenn Talk wieder zuhören soll.";
    freiAn.current = false;
    if (aufn.current) aufn.current.abbrechen();
    if (lauschRef.current) lauschRef.current.abbrechen();
    vorgriff.current = null;
    vorleseStopp();
    setFrei((f) => f && { ...f, zustand: "pausiert", pegel: 0, text: pausiertRef.current });
  }
  function mikroNehmen() { pausiertRef.current = null; mikroAnfordern("talk", pausieren); return ++runde.current; }

  async function freiStart() {
    const grund = mikrofonGrund();
    if (grund) { toast(grund, { fehler: true }); return; }
    const nr = mikroNehmen();
    const an = () => freiAn.current && runde.current === nr;
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
    while (an()) {
      let t = "";
      try { t = await zuhoeren(); } catch (e) { toast(e.message, { fehler: true }); break; }
      if (!an()) return;
      if (!t) { if (++leer >= 3) { await sprechen("Ich höre nichts mehr und beende das Freisprechen."); break; } continue; }
      leer = 0;
      if (istEnde(t)) {
        setMsgs((m) => [...m, { id: "d" + Date.now(), rolle: "du", text: t }]);
        await sprechen("Gut, ich beende unser Gespräch.");
        // Beenden heisst auch: Talk geht zu (Veiko, 19.10.2026).
        ausKopf.current = false; freiBeenden(); zu(); return;
      }
      setFrei((f) => f && { ...f, zustand: "denkt", text: t });
      const r = await eingabe(t, [], true);
      if (!an()) return;
      if (r && r.text) await sprechen(r.text);
    }
    if (runde.current === nr) freiStopp();
  }
  // freiStopp: die Schleife ist zu Ende. Ist Talk nur pausiert, bleibt der Kreis mit
  // "Pausiert" stehen; beenden tut erst freiBeenden (Knopf, "Dialog beenden", Escape).
  function freiStopp() {
    freiAn.current = false;
    if (aufn.current) aufn.current.abbrechen();
    if (lauschRef.current) lauschRef.current.abbrechen();
    vorgriff.current = null;
    vorleseStopp();
    if (pausiertRef.current) return;
    setFrei(null);
    mikroFreigeben("talk");
  }
  function freiBeenden() { pausiertRef.current = null; freiStopp(); }
  // Ein Klick auf den Kreis oder das Mikrofon oben beendet das Gespraech und schliesst Talk --
  // in jedem Zustand (Veiko, 19.10.2026: "da moechte ich einfach draufklicken koennen, dann
  // soll der Dialog beendet werden und sich das Fenster schliessen"). Vorher hiess ein Klick
  // beim Zuhoeren "fertig gesprochen"; das erledigt die Stille-Erkennung von selbst. Nur
  // "pausiert" (Diktat hat Vorfahrt) setzt fort -- dort steht das Play-Zeichen.
  function kreisKlick() {
    if (!frei || frei.zustand === "pausiert") return freiStart();
    // Waehrend Talk spricht heisst Antippen: "lass mich reden" (22.10.2026) -- vorher beendete es
    // das ganze Gespraech, und genau das tut man reflexhaft, wenn man unterbrechen will.
    if (frei.zustand === "spricht") {
      vorleseStopp();
      if (lauschRef.current) lauschRef.current.jetzt();
      setFrei((f) => f && { ...f, zustand: "hoert", pegel: 0, text: "" });
      return;
    }
    ausKopf.current = false; freiBeenden(); zu();
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
    const nr = mikroNehmen();
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
    if (runde.current === nr) freiStopp();
  }

  function neu() { if (laufRef.current) return; setGid(null); setMsgs([]); }

  return html`<aside class="talk" aria-label="Talk">
    <${Ziehgriff} name="talk" seite="links" />
    <div class="talk-kopf">
      <h2><${Icon} n="talk" g=${17} />Talk</h2>
      <${Zuordnung} gid=${gid} klein=${true} />
      ${frei && html`<button class="btn klein" onClick=${() => { ausKopf.current = false; freiBeenden(); zu(); }} title="Gespräch beenden und Talk schließen (oder sag „Dialog beenden“)"><${Icon} n="stopp" g=${12} />Beenden</button>`}
      <button class="btn geist icon" onClick=${neu} title="Neues Gespräch" aria-label="Neues Gespräch"><${Icon} n="neu" g=${17} /></button>
      <button class="btn geist icon" onClick=${zu} title="Schließen (Esc)" aria-label="Talk schließen"><${Icon} n="x" /></button>
    </div>
    ${warm === "laedt" && html`<div class="talk-warm" role="status"><span class="talk-warm-punkt" aria-hidden="true"></span>Talk wird vorbereitet: Sprachmodell und Spracherkennung laden …</div>`}
    ${kontext && html`<div class="talk-kontext"><${Icon} n="auge" g=${14} /><span>schaut auf: ${kontext.titel || kontext.art}</span>
      <button class="btn klein geist icon" onClick=${() => setKontext(null)} aria-label="Bezug entfernen" title="Ohne Bezug weiterreden"><${Icon} n="x" g=${13} /></button></div>`}
    ${frei && html`<${StimmeKreis} zustand=${frei.zustand} pegel=${frei.pegel || 0} text=${frei.text} beiKlick=${kreisKlick} />`}
    <div class="talk-verlauf" ref=${verlaufRef}>
      ${!msgs.length && !lauf && !frei && html`<div class="talk-start">
        <p style="text-align:center">Schreib mir hier, oder tipp oben auf <b>Sprechen</b> und rede einfach los. Ich ändere nichts ohne dein Ja. Bedienen kannst du alles mit Worten: „öffne den Verbrauch“, „zeig mir den Zeitplan von BVE“, „Chat mit Neal“, „zurück“. Zum Schluss genügt „Dialog beenden“.</p>
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
              ${v.abgelehnt ? html`<span class="pill">abgelehnt</span>` : v.erledigt ? html`<span class="pill gruen">erledigt</span>${ansehenKnopf(v.ergebnis)}`
                : html`<button class="btn klein primaer" onClick=${() => ausfuehren(m.id, [i])}>Ausführen</button>`}
            </div>`)}
            ${m.vorschlaege && m.vorschlaege.filter((v) => !v.erledigt).length > 1 && html`<button class="btn klein" style="margin-top:6px"
              onClick=${() => ausfuehren(m.id, m.vorschlaege.map((v, i) => (v.erledigt ? -1 : i)).filter((i) => i >= 0))}>Alle ausführen</button>`}
            ${(m.medien || []).map((x) => html`<${MedienKarte} key=${x.id} m=${x} />`)}
            ${m.ergebnis ? html`<button class="btn klein primaer" style="margin-top:6px" onClick=${() => bus.sende("ergebnis-zeigen", m.ergebnis)}><${Icon} n="voll" g=${12} />Dossier öffnen</button>`
              : m.datei && html`<button class="btn klein primaer" style="margin-top:6px" onClick=${() => bus.sende("datei-zeigen", m.datei)}><${Icon} n="voll" g=${12} />Dossier öffnen</button>`}
            ${m.bezug && html`<${BezugZeile} b=${m.bezug} />`}
            ${typeof m.id === "number" && html`<button class="btn klein geist" style="margin-top:4px" title="Vorlesen" onClick=${() => vorlesen(m.text).catch((e) => toast(e.message, { fehler: true }))}><${Icon} n="play" g=${12} />Vorlesen</button>`}
          </div>`)}
      ${lauf && html`<div class="talk-blase ck">${lauf.text ? html`<${Md} text=${lauf.text} />` : html`<span class="leise">${lauf.status ? lauf.status.charAt(0).toUpperCase() + lauf.status.slice(1) : "Denke nach …"}</span>`}</div>`}
    </div>
    <div class="talk-eingabe">
      <${Composer} feldRef=${talkFeld} platzhalter=${kontext ? "Frag zu „" + (kontext.titel || "").slice(0, 40) + "“ …" : "Frag oder beauftrage dein Team … („ja“ bestätigt den letzten Vorschlag)"}
        beimSenden=${(t, a) => eingabe(t, a, false).then(() => true)} laeuft=${!!lauf}
        beimStoppen=${() => abbruch.current && abbruch.current.abort()} entwurfKey="talk" hinweis="" extra=${html`<${GlobusKnopf} />`} />
      <div class="talk-schalter">
        <${TalkSchalter} name="gruendlich" text="Gründlich" titel="An: das Cockpit denkt vor der Antwort nach (dauert deutlich länger). Aus: schnelle, flüssige Antwort. Gilt auf diesem Gerät." />
      </div>
    </div>
  </aside>`;
}
