// TALK -- ein Gespraech, ueberall. Seitenspalte am Rechner, ganze Seite am Telefon.
// Drei Arten zu reden:
//   tippen oder diktieren     -- Composer, Enter sendet
//   Freisprechen              -- zuhoeren, antworten, vorlesen, weiter zuhoeren
//   Per Stimme durchgehen     -- die offenen Entscheidungen der Reihe nach;
//                                ja / nein / spaeter / frei antworten
// Aendern tut das Gespraech nur auf Bestaetigung (Knopf oder ein gesprochenes "ja").
import { html, useState, useEffect, useRef, Icon, Md, toast, fehlerMelden, aktualisieren, navigiere, rolleName } from "./ui.js";
import { api, strom } from "./api.js";
import { Composer } from "./composer.js";
import { aufnehmen, erkennen, vorlesen, vorleseStopp, mikrofonGrund } from "./stimme.js";

const JA = /^(ja|jo|jep|genau|klar|mach (das|es)|machen|gerne|ok(ay)?|einverstanden|passt|anlegen|merken|bitte|richtig|stimmt|ja bitte|ja,? mach)\b/i;
const NEIN = /^(nein|nee|nö|lieber nicht|nicht|ablehnen|falsch|stimmt nicht)\b/i;
const SPAETER = /^(später|spaeter|weiter|nächste|naechste|überspringen|ueberspringen|skip|egal)\b/i;
const ENDE = /^(stopp|stop|ende|beenden|aufhören|aufhoeren|das wars|das war's|danke,? das (war|wars)|tschüss|tschuess|schluss)\b/i;
const reinigen = (t) => String(t || "").trim().replace(/[.!?,]+$/, "").trim();

function Welle({ pegel }) {
  const n = [0.5, 0.8, 1, 0.8, 0.5];
  return html`<span class="welle" aria-hidden="true">${n.map((f, i) => html`<i key=${i} style=${`height:${4 + Math.round(18 * f * pegel)}px`}></i>`)}</span>`;
}

export function Talk({ zu, kontext, setKontext, start }) {
  const [gid, setGid] = useState(() => { try { return localStorage.getItem("vvec_talk_g") || null; } catch (e) { return null; } });
  const [msgs, setMsgs] = useState([]);
  const [lauf, setLauf] = useState(null); // {text}
  const [frei, setFrei] = useState(null); // {modus:"frei"|"durch", zustand, text, pegel}
  const verlaufRef = useRef(null);
  const abbruch = useRef(null);
  const freiAn = useRef(false);
  const aufn = useRef(null);
  const letzterStart = useRef(0);

  useEffect(() => { try { gid ? localStorage.setItem("vvec_talk_g", gid) : localStorage.removeItem("vvec_talk_g"); } catch (e) { /* egal */ } }, [gid]);
  useEffect(() => {
    if (!gid) { setMsgs([]); return; }
    api("/talk/" + gid).then((d) => setMsgs(d.nachrichten.map(zuAnzeige))).catch(() => { setGid(null); setMsgs([]); });
  }, []);
  useEffect(() => { const v = verlaufRef.current; if (v) v.scrollTop = v.scrollHeight; }, [msgs, lauf, frei && frei.zustand]);
  useEffect(() => {
    if (!start || start.n === letzterStart.current) return;
    letzterStart.current = start.n;
    if (start.durchgehen) durchgehen();
    else if (start.text) senden(start.text, [], false);
  }, [start]);
  useEffect(() => () => { freiAn.current = false; if (aufn.current) aufn.current.abbrechen(); vorleseStopp(); }, []);
  useEffect(() => {
    const k = (e) => { if (e.key === "Escape" && !document.querySelector(".modal-grund")) { if (frei) freiStopp(); else zu(); } };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [frei]);

  function zuAnzeige(m) {
    const d = m.daten || {};
    return { id: m.id, rolle: m.rolle === "du" ? "du" : "ck", text: m.rolle === "du" ? (d.anzeige ?? m.text) : m.text, vorschlaege: d.vorschlaege || [] };
  }

  async function senden(text, anhaenge, stimme) {
    if (lauf) return false;
    setMsgs((m) => [...m, { id: "d" + Date.now(), rolle: "du", text }]);
    setLauf({ text: "" });
    const ctl = new AbortController(); abbruch.current = ctl;
    let fertig = null, stromFehler = null;
    try {
      await strom("/talk/senden", { gespraech_id: gid, text, kontext: kontext ? { art: kontext.art, id: kontext.id } : null, anhaenge, stimme }, (e) => {
        if (e.typ === "start") setGid(e.gespraech_id);
        else if (e.typ === "text") setLauf((l) => ({ text: (l ? l.text : "") + e.t }));
        else if (e.typ === "fertig") fertig = e;
        else if (e.typ === "fehler") stromFehler = e.text;
      }, ctl.signal);
      if (stromFehler) throw new Error(stromFehler);
    } catch (e) {
      if (e.name !== "AbortError") { fehlerMelden(e); setMsgs((m) => [...m, { id: "f" + Date.now(), rolle: "ck", text: "Das hat nicht geklappt: " + e.message, vorschlaege: [] }]); }
    }
    setLauf(null);
    if (fertig) {
      setMsgs((m) => [...m, { id: fertig.nachricht_id, rolle: "ck", text: fertig.text, vorschlaege: fertig.vorschlaege }]);
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
        toast(neo ? "Neo arbeitet daran." : "Erledigt.", neo ? { aktion: { text: "Zu Neo", fn: () => navigiere("/neo/" + neo.neo_gespraech) } } : {});
      }
      aktualisieren();
      return !fehl.length;
    } catch (e) { fehlerMelden(e); return false; }
  }

  function offeneVorschlaege() {
    const letzte = [...msgs].reverse().find((m) => m.rolle === "ck");
    if (!letzte || !letzte.vorschlaege) return null;
    const idx = letzte.vorschlaege.map((v, i) => (!v.erledigt ? i : -1)).filter((i) => i >= 0);
    return idx.length ? { mid: letzte.id, idx } : null;
  }

  // ------------------------------------------------------------ Freisprechen
  async function zuhoeren() {
    setFrei((f) => f && { ...f, zustand: "hoert", pegel: 0 });
    const ctl = await aufnehmen({ stilleStopp: true, maxSek: 60, pegel: (p) => setFrei((f) => f && { ...f, pegel: p }) });
    aufn.current = ctl;
    const blob = await ctl.ende;
    aufn.current = null;
    if (!freiAn.current) return "";
    if (!ctl.gesprochen()) return "";
    setFrei((f) => f && { ...f, zustand: "erkennt" });
    const d = await erkennen(blob);
    return reinigen(d.text);
  }
  async function sprechen(text) {
    if (!freiAn.current || !text) return;
    setFrei((f) => f && { ...f, zustand: "spricht" });
    try { await vorlesen(text); } catch (e) { /* ohne Ton weiter */ }
  }

  async function freiStart() {
    const grund = mikrofonGrund();
    if (grund) { toast(grund, { fehler: true }); return; }
    freiAn.current = true;
    setFrei({ modus: "frei", zustand: "hoert", pegel: 0 });
    let leer = 0;
    while (freiAn.current) {
      let t = "";
      try { t = await zuhoeren(); } catch (e) { toast(e.message, { fehler: true }); break; }
      if (!freiAn.current) break;
      if (!t) { if (++leer >= 3) { await sprechen("Ich höre nichts mehr und beende das Freisprechen."); break; } continue; }
      leer = 0;
      if (ENDE.test(t)) { await sprechen("Gut, ich höre auf."); break; }
      const offen = offeneVorschlaege();
      if (offen && JA.test(t)) {
        const ok = await ausfuehren(offen.mid, offen.idx);
        await sprechen(ok ? "Erledigt." : "Das ging leider nicht ganz.");
        continue;
      }
      setFrei((f) => f && { ...f, zustand: "denkt" });
      const r = await senden(t, [], true);
      if (r && r.text) await sprechen(r.text + (r.vorschlaege && r.vorschlaege.length ? " Soll ich das so machen?" : ""));
    }
    freiStopp();
  }
  function freiStopp() {
    freiAn.current = false;
    if (aufn.current) aufn.current.abbrechen();
    vorleseStopp();
    setFrei(null);
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
      setFrei((f) => f && { ...f, text: `${i + 1} von ${liste.length}: ${e.frage}` });
      systemZeile(`**${i + 1} von ${liste.length}** · ${rolleName(e.wer)}: ${e.frage}`);
      await sprechen(`${rolleName(e.wer)} ${e.art === "rueckfrage" ? "fragt" : "schlägt vor"}: ${e.frage}`);
      let versuch = 0;
      while (freiAn.current) {
        let t = "";
        try { t = await zuhoeren(); } catch (x) { toast(x.message, { fehler: true }); freiAn.current = false; break; }
        if (!freiAn.current) break;
        if (!t) { if (++versuch >= 2) { await sprechen("Ich lasse das für später."); break; } await sprechen("Ich habe nichts gehört. Ja, nein oder später?"); continue; }
        setMsgs((m) => [...m, { id: "d" + Date.now(), rolle: "du", text: t }]);
        if (ENDE.test(t)) { freiAn.current = false; break; }
        let antwort = null, text = "";
        if (SPAETER.test(t)) antwort = "spaeter";
        else if (e.art === "rueckfrage") { antwort = NEIN.test(t) && t.split(" ").length <= 2 ? "nein" : "ja"; text = antwort === "ja" ? t : ""; }
        else if (JA.test(t)) antwort = "ja";
        else if (NEIN.test(t)) antwort = "nein";
        if (!antwort) { if (++versuch >= 2) { await sprechen("Ich lasse das für später."); break; } await sprechen("Bitte sag ja, nein oder später."); continue; }
        try {
          await api("/entscheidungen/" + e.id, { methode: "POST", daten: { antwort, text } });
          erledigt += antwort === "spaeter" ? 0 : 1;
          const q = { ja: e.art === "rueckfrage" ? "Antwort ist beim Stab." : "Erledigt.", nein: "Abgelehnt.", spaeter: "Später." }[antwort];
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

  function neu() { if (lauf) return; setGid(null); setMsgs([]); }

  const ZUSTAND = { hoert: "Ich höre zu …", erkennt: "Verstehe …", denkt: "Denke nach …", spricht: "Spreche …" };
  return html`<aside class="talk" aria-label="Talk">
    <div class="talk-kopf">
      <h2><${Icon} n="talk" g=${17} />Talk</h2>
      <button class=${"btn klein" + (frei && frei.modus === "frei" ? " primaer" : "")} onClick=${() => (frei ? freiStopp() : freiStart())}
        title="Freihändig sprechen: ich höre zu, antworte und lese vor" aria-pressed=${!!frei}><${Icon} n="welle" g=${14} />${frei ? "Beenden" : "Freisprechen"}</button>
      <button class="btn geist icon" onClick=${neu} title="Neues Gespräch" aria-label="Neues Gespräch"><${Icon} n="neu" g=${17} /></button>
      <button class="btn geist icon" onClick=${zu} title="Schließen (Esc)" aria-label="Talk schließen"><${Icon} n="x" /></button>
    </div>
    ${kontext && html`<div class="talk-kontext"><${Icon} n="auge" g=${14} /><span>schaut auf: ${kontext.titel || kontext.art}</span>
      <button class="btn klein geist icon" onClick=${() => setKontext(null)} aria-label="Bezug entfernen" title="Ohne Bezug weiterreden"><${Icon} n="x" g=${13} /></button></div>`}
    <div class="talk-verlauf" ref=${verlaufRef}>
      ${!msgs.length && !lauf && html`<div class="talk-start">
        <p>Frag mich etwas über deine Lage, deine Projekte oder das, was der Stab vorschlägt. Ich ändere nichts ohne deine Bestätigung.</p>
        <div class="knopfreihe">
          <button class="btn klein" onClick=${() => senden("Was liegt an?", [], false)}>Was liegt an?</button>
          <button class="btn klein" onClick=${durchgehen}><${Icon} n="play" g=${12} />Entscheidungen per Stimme</button>
          ${kontext && html`<button class="btn klein" onClick=${() => senden("Fass mir das kurz zusammen und sag, was als Nächstes zu tun ist.", [], false)}>Zusammenfassen</button>`}
        </div></div>`}
      ${msgs.map((m) => m.rolle === "du"
        ? html`<div class="talk-blase du" key=${m.id}>${m.text}</div>`
        : html`<div class="talk-blase ck" key=${m.id}>
            <${Md} text=${m.text} />
            ${m.vorschlaege && m.vorschlaege.map((v, i) => html`<div class=${"vorschlag" + (v.erledigt ? " erledigt" : "")} key=${i}>
              <span>${v.label}</span>
              ${v.erledigt ? html`<span class="pill gruen">erledigt</span>` : html`<button class="btn klein primaer" onClick=${() => ausfuehren(m.id, [i])}>Ausführen</button>`}
            </div>`)}
            ${m.vorschlaege && m.vorschlaege.filter((v) => !v.erledigt).length > 1 && html`<button class="btn klein" style="margin-top:6px"
              onClick=${() => ausfuehren(m.id, m.vorschlaege.map((v, i) => (v.erledigt ? -1 : i)).filter((i) => i >= 0))}>Alle ausführen</button>`}
            ${typeof m.id === "number" && html`<button class="btn klein geist" style="margin-top:4px" title="Vorlesen" onClick=${() => vorlesen(m.text).catch((e) => toast(e.message, { fehler: true }))}><${Icon} n="play" g=${12} />Vorlesen</button>`}
          </div>`)}
      ${lauf && html`<div class="talk-blase ck">${lauf.text ? html`<${Md} text=${lauf.text} />` : html`<span class="leise">Denke nach …</span>`}</div>`}
    </div>
    <div class="talk-eingabe">
      ${frei && html`<div class="frei-leiste" role="status">
        <${Welle} pegel=${frei.zustand === "hoert" ? frei.pegel : frei.zustand === "spricht" ? 0.6 : 0.15} />
        <div style="min-width:0"><b>${ZUSTAND[frei.zustand] || ""}</b>${frei.text && html`<div class="leise klein" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${frei.text}</div>`}</div>
        <span class="luecke"></span>
        <button class="btn klein" onClick=${freiStopp}>Beenden</button>
      </div>`}
      <${Composer} platzhalter=${kontext ? "Frag zu „" + (kontext.titel || "").slice(0, 40) + "“ …" : "Frag oder beauftrage den Stab …"}
        beimSenden=${(t, a) => senden(t || "(siehe Anhang)", a, false).then(() => true)} laeuft=${!!lauf}
        beimStoppen=${() => abbruch.current && abbruch.current.abort()} entwurfKey="talk" hinweis="" />
    </div>
  </aside>`;
}
