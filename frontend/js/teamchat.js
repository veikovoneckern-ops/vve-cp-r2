// MIT DEM TEAM SPRECHEN -- ein Gespraech mit genau einem Mitglied (lokal oder extern).
// EINE Komponente fuer zwei Einstiege (Bauregel 2): die Gespraechsseite unter
// Team und die Spalte "Weiterarbeiten" im Ergebnisfenster. Im Ergebnisfenster
// liegt das Ergebnis im Kontext; verlangt Veiko eine Aenderung, schreibt das
// Mitglied eine neue Fassung, Daniel prueft sie, und sie laesst sich zuruecknehmen.
import { Zuordnung } from "./zuordnung.js";
import { html, useState, useEffect, useRef, Icon, Avatar, Md, Leer, toast, fehlerMelden, navigiere, zeitText, bus, kopieren, tempoSchnell, TempoSchalter, Ziehgriff } from "./ui.js";
import { api, strom } from "./api.js";
import { Composer } from "./composer.js";
import { URTEIL } from "./ergebnis.js";
import { vorlesen, vorleseStopp } from "./stimme.js";
// Kreis-Import (langlauf.js nutzt TeamChat): unbedenklich, langlaufStarten wird erst beim Klick gerufen.
import { langlaufStarten } from "./langlauf.js";

// Eine Liste aller, mit denen man sprechen kann: lokale Mitglieder zuerst, dann die Externen.
export function gespraechsPartner(d) {
  if (!d) return [];
  const lokal = d.team.filter((m) => m.aktiv && m.id !== "cockpit").map((m) => ({ id: m.id, name: m.name, titel: m.titel, extern: false }));
  const ext = (d.externe || []).map((x) => ({ id: x.id, name: x.name, titel: x.titel, extern: true, schluessel: x.schluessel }));
  return [...lokal, ...ext];
}

function Nachricht({ m, partner, beiRueckgaengig }) {
  const [liest, setLiest] = useState(false);
  if (m.rolle === "du") return html`<div class="bd-du">${m.text}${(m.dateien || []).length ? html`<div class="klein leise" style="margin-top:4px">📎 ${m.dateien.length} Anhang</div>` : ""}</div>`;
  const p = partner(m.rolle);
  async function lesen() {
    if (liest) { vorleseStopp(); setLiest(false); return; }
    setLiest(true);
    try { await vorlesen(m.text); } catch (e) { fehlerMelden(e); }
    setLiest(false);
  }
  return html`<div class="bd-beitrag">
    <${Avatar} wer=${m.rolle} name=${p.name} g=${30} />
    <div class="bd-blase"><b>${p.name}${m.modell ? html` <span class="leise klein" style="font-weight:400">· ${m.modell}</span>` : ""}</b>
      ${(m.text || "").trim() ? html`<${Md} text=${m.text} />`
        : html`<div class="leise">Keine Antwort geliefert. Bitte noch einmal senden, gern mit „Schnelle Antwort“.</div>`}
      ${m.fassung && html`<div class="tc-fassung"><span class="tc-fassung-text"><${Icon} n="check" g=${13} />Neue Fassung gespeichert${m.pruefung ? ` · ${(URTEIL[m.pruefung] || { wort: m.pruefung }).wort}` : ""}</span>
        ${m.protokoll_id && beiRueckgaengig && html`<button class="btn klein geist" onClick=${() => beiRueckgaengig(m.protokoll_id)}><${Icon} n="undo" g=${13} />Zurücknehmen</button>`}</div>`}
      <div class="tc-werkzeug">
        <button class="btn klein geist" onClick=${lesen} title="Vorlesen"><${Icon} n=${liest ? "stopp" : "play"} g=${13} />${liest ? "Stopp" : "Vorlesen"}</button>
        <button class="btn klein geist" onClick=${async () => { if (await kopieren(m.text)) toast("Kopiert."); }}><${Icon} n="kopie" g=${13} />Kopieren</button>
      </div>
    </div></div>`;
}

// Wen Veiko in einer Nachricht an ein Teammitglied dazuholt ("gib Demmis die
// Fassung zum Korrekturlesen"). Die Externen antworten dann selbst im selben
// Gespraech (teamchat.senden mit extern) -- nach einmaliger Kostenfreigabe.
const EXTERN_NAMEN = [["dario", /\b(dario|claude)\b/i], ["elon", /\b(elon|grok)\b/i], ["demmis", /\b(demmis|demis|gemini)\b/i]];
// Waehrend des Schreibens: Fassung und Langlaeufer-Bloecke nicht roh zeigen.
// Was davon wirklich uebernommen wurde, steht danach unter der fertigen Antwort.
const ohneBloecke = (t) => t.replace(/<<<FASSUNG>>>[\s\S]*/, "\n\n_… schreibt die neue Fassung …_")
  .replace(/<<<(HINWEIS|UEBERARBEITEN|NEUE_ETAPPEN)>>>[\s\S]*/, "\n\n_… gibt die Anweisung an den LongRun …_")
  .replace(/<<<RECHERCHE>>>[\s\S]*/, "\n\n_… startet die Recherche …_");
function genannteExterne(text) { return EXTERN_NAMEN.filter(([, re]) => re.test(text || "")).map(([id]) => id); }
// Ist das ein grosses Vorhaben (LongRun), und soll ein genannter Externer erst DANACH pruefen?
// Beides beantwortet der Server (langlauf.gross, dieselbe Regel wie Talk und Pipeline) --
// hier steht keine eigene Regel (19.10.2026). Im Chat schreibt das Mitglied alles in EINE
// Antwort; ein komplettes Buch oder eine grosse Praesentation wird dort zwangslaeufig ein Auszug.
async function erkennen(text) {
  try { return await api("/langlaeufe/erkennen", { methode: "POST", daten: { text } }); }
  catch (e) { return { gross: null, nachher: false }; }
}

// wer: Kennung des Mitglieds; gid: Gespraech oder null; ergebnisId/projektId: Kontext.
// beiFassung(): das Ergebnisfenster laedt danach neu. beiGespraech(gid): neue Kennung merken.
// beiTaetig({name, status} | null): was gerade passiert -- fuer die Anzeige im Fensterkopf.
export function TeamChat({ wer, partnerListe, gid, ergebnisId = "", projektId = "", langlaufId = "", beiFassung, beiGespraech, leerText, beiTaetig, vorlage }) {
  const [msgs, setMsgs] = useState([]);
  const [lauf, setLauf] = useState(null);
  const [vorlesenAn, setVorlesenAn] = useState(() => { try { return localStorage.getItem("tc-vorlesen") === "1"; } catch (e) { return false; } });
  const [kostenOk, setKostenOk] = useState(false);   // je Gespraech einmal: Externe kosten Geld
  const [externFrei, setExternFrei] = useState([]);   // dazugeholte Externe, fuer die die Kosten freigegeben sind
  const [wartet, setWartet] = useState(null);
  const feld = useRef(null);
  const verlauf = useRef(null);
  const abbruch = useRef(null);
  const partner = (id) => partnerListe.find((p) => p.id === id) || { name: id };
  const ich = partner(wer);

  // Eine Antwort, die auf dem Server noch entsteht, OHNE dass dieses Fenster sie
  // angestossen hat (Fenster war zu, anderes Geraet). Sie wird mitgelesen, bis
  // sie fertig ist -- statt wie frueher stumm verloren zu gehen.
  const [nach, setNach] = useState(null);
  const lade = () => api("/teamchat/" + gid).then((x) => {
    setMsgs(x.nachrichten.map((m) => ({ id: m.id, rolle: m.rolle, text: m.text,
      dateien: (m.daten || {}).dateien, modell: (m.daten || {}).modell, fassung: (m.daten || {}).fassung,
      protokoll_id: (m.daten || {}).protokoll_id, pruefung: (m.daten || {}).pruefung })));
    setNach((vorher) => {
      if (vorher && !x.laeuft && beiFassung) beiFassung();   // fertig geworden: Ergebnis neu laden
      return x.laeuft || null;
    });
  }).catch(() => setMsgs([]));
  useEffect(() => {
    if (!gid) { setMsgs([]); setNach(null); return; }
    lade();
  }, [gid]);
  useEffect(() => {
    if (!nach || lauf) return;
    const t = setInterval(lade, 3000);
    return () => clearInterval(t);
  }, [!!nach, !!lauf, gid]);
  useEffect(() => { const v = verlauf.current; if (v) v.scrollTop = v.scrollHeight; }, [msgs, lauf]);
  useEffect(() => { try { localStorage.setItem("tc-vorlesen", vorlesenAn ? "1" : "0"); } catch (e) { /* egal */ } }, [vorlesenAn]);

  // Was gerade passiert, nach oben melden (Fensterkopf des Ergebnisses).
  useEffect(() => {
    if (!beiTaetig) return;
    if (lauf) { const p = partner(lauf.wer || wer); beiTaetig({ name: p.name, status: lauf.status || (lauf.text ? "schreibt …" : "denkt nach …") }); }
    else if (nach) { const p = partner(nach.wer || wer); beiTaetig({ name: p.name, status: nach.status || (nach.text ? "schreibt …" : "arbeitet …") }); }
    else beiTaetig(null);
  }, [lauf && lauf.status, lauf && lauf.wer, lauf && !!lauf.text, nach && nach.status, nach && nach.wer, !!lauf, !!nach]);
  useEffect(() => () => beiTaetig && beiTaetig(null), []);
  // Eine vorbereitete Bitte ins Feld legen (nicht senden -- Veiko liest und schickt selbst).
  useEffect(() => { if (vorlage && vorlage.text) setTimeout(() => feld.current && feld.current.setzen(vorlage.text), 80); }, [vorlage && vorlage.n]);

  async function senden(text, dateien, namen, imChat = false) {
    if (lauf) return false;
    if (ich.extern && !kostenOk) { setWartet({ text, dateien, namen }); return true; }
    const dazu = ich.extern ? [] : genannteExterne(text).filter((x) => partnerListe.some((p) => p.id === x));
    const erk = ich.extern ? { gross: null, nachher: false } : await erkennen(text);
    const nachher = dazu.length > 0 && erk.nachher;
    // In einem LongRun-Gespraech gehen Anweisungen ohnehin an den LongRun.
    if (!imChat && !langlaufId && erk.gross) { setWartet({ text, dateien, namen, dazu, nachher, langlauf: erk.gross }); return true; }
    if (dazu.length && !dazu.every((x) => externFrei.includes(x))) { setWartet({ text, dateien, namen, dazu, nachher }); return true; }
    return sendenFrei(text, dateien, dazu, nachher);
  }
  function alsLangLauf(w) {
    const g = w.langlauf;
    setWartet(null);
    langlaufStarten({ projekt_id: projektId || "", titel: "", auftrag: w.text, rolle: wer, art: g.art, pruefer: g.pruefer,
      pruef_alle: g.pruef_alle, ergebnis_id: ergebnisId || "", fest: ["auftrag", "rolle", "art", "pruefer", "pruef_alle"] });
  }

  async function sendenFrei(text, dateien, extern = [], danach = false) {
    setMsgs((m) => [...m, { id: "d" + Date.now(), rolle: "du", text: text || "(siehe Anhang)", dateien }]);
    setLauf({ text: "", status: "" });
    const ctl = new AbortController(); abbruch.current = ctl;
    let neuGid = gid, fehler = null, pruefung = null;
    const fertige = [];
    bus.sende("ki-start");
    try {
      await strom("/teamchat/senden", { gespraech_id: gid || null, wer, text, dateien, ergebnis_id: ergebnisId || null, projekt_id: projektId || null, langlauf_id: langlaufId || null,
        schnell: tempoSchnell(), extern, extern_danach: danach && extern.length > 0 }, (e) => {
        if (e.typ === "start") neuGid = e.gespraech_id;
        else if (e.typ === "wer") setLauf({ wer: e.wer, text: "", status: `${partner(e.wer).name} wird dazugeholt …` });
        else if (e.typ === "text") setLauf((l) => l && { ...l, text: l.text + e.t });
        else if (e.typ === "status") setLauf((l) => l && { ...l, status: e.text });
        else if (e.typ === "fassung") { setLauf((l) => l && { ...l, status: "Neue Fassung gespeichert." }); beiFassung && beiFassung(); }
        else if (e.typ === "pruefung") pruefung = e.pruefung;
        else if (e.typ === "fertig") {
          // Mehrere Antworten in einer Runde (Neal holt Demmis und Elon): jede sofort zeigen.
          const f = { id: e.nachricht_id, rolle: e.wer || wer, text: e.text, modell: e.modell, fassung: e.fassung,
            protokoll_id: e.protokoll_id, pruefung: pruefung && pruefung.urteil };
          pruefung = null;
          fertige.push(f);
          setMsgs((m) => [...m, f]);
          setLauf((l) => l && { ...l, text: "", status: "" });
        }
        else if (e.typ === "fehler") fehler = e.text;
      }, ctl.signal);
      if (fehler) throw new Error(fehler);
    } catch (e) { if (e.name !== "AbortError") fehlerMelden(e); }
    setLauf(null);
    if (fertige.length) {
      if (fertige.some((f) => f.fassung) && beiFassung) beiFassung();
      if (vorlesenAn) vorlesen(fertige.map((f) => f.text).join("\n\n")).catch(() => {});
    }
    if (neuGid && neuGid !== gid && beiGespraech) beiGespraech(neuGid);
    return true;
  }

  async function rueckgaengig(pid) {
    try {
      const r = await api("/rueckgaengig/" + pid, { methode: "POST" });
      if (r && r.ok === false) throw new Error(r.grund || "Ging nicht.");
      toast("Vorige Fassung wiederhergestellt."); beiFassung && beiFassung();
    } catch (e) { fehlerMelden(e); }
  }

  return html`<div class="tc">
    <div class="bd-verlauf tc-verlauf" ref=${verlauf}>
      ${!msgs.length && !lauf && html`<${Leer} titel=${`Mit ${ich.name} sprechen`}>${leerText || (ich.extern
        ? `${ich.name} ist extern und kostet Geld je Nachricht. Gut für eine zweite Meinung.`
        : `${ich.name} rechnet lokal auf deinem Server. Tippen, diktieren (Mikrofon) oder Unterlagen anhängen.`)}</${Leer}>`}
      ${msgs.map((m) => html`<${Nachricht} key=${m.id} m=${m} partner=${partner} beiRueckgaengig=${ergebnisId ? rueckgaengig : null} />`)}
      ${lauf && html`<div class="bd-beitrag"><${Avatar} wer=${lauf.wer || wer} name=${partner(lauf.wer || wer).name} g=${30} />
        <div class="bd-blase"><b>${partner(lauf.wer || wer).name}</b>${lauf.text ? html`<${Md} text=${ohneBloecke(lauf.text)} />`
          : html`<div class="bd-denkt">${lauf.status || `${partner(lauf.wer || wer).name} denkt nach …`}</div>`}
          ${lauf.text && lauf.status && html`<div class="leise klein" style="margin-top:6px">${lauf.status}</div>`}</div></div>`}
      ${!lauf && nach && html`<div class="bd-beitrag"><${Avatar} wer=${nach.wer || wer} name=${partner(nach.wer || wer).name} g=${30} />
        <div class="bd-blase"><b>${partner(nach.wer || wer).name}</b> <span class="leise klein">arbeitet noch · seit ${zeitText(nach.start).replace("vor ", "")}</span>
          ${nach.text ? html`<${Md} text=${ohneBloecke(nach.text)} />`
            : html`<div class="bd-denkt">${nach.status || `${partner(nach.wer || wer).name} denkt nach …`}</div>`}
          <div class="leise klein" style="margin-top:6px">Du kannst das Fenster schließen. Die Antwort wird fertig gerechnet und erscheint hier.</div></div></div>`}
    </div>
    ${wartet && wartet.langlauf && html`<div class="hinweisbox tc-kosten">
      <b>Das ist ein großes Vorhaben (${wartet.langlauf.art_name}) -- dafür gibt es den LongRun.</b> Hier im Chat schreibt ${ich.name} alles in eine einzige Antwort;
      ein großes Werk wird so zwangsläufig ein Auszug. Als LongRun plant ${ich.name} es in Etappen und arbeitet eine nach der anderen aus, jede gründlich
      und von Daniel geprüft, und ${wartet.langlauf.pruefer === "demmis" ? "Demmis" : "Dario"} prüft ${wartet.langlauf.pruef_alle === 0 ? "am Ende das fertige Werk" : "zwischendurch"}.
      Im nächsten Schritt siehst du alles im Formular und startest selbst -- dort steht auch das Budget für die Prüfung.
      <div class="knopfreihe" style="margin-top:8px">
        <button class="btn primaer klein" onClick=${() => alsLangLauf(wartet)}><${Icon} n="langlauf" g=${14} />Als LongRun starten</button>
        <button class="btn klein" onClick=${() => { const w = wartet; setWartet(null); setTimeout(() => senden(w.text, w.dateien, w.namen, true), 0); }}>Trotzdem hier im Chat</button>
        <button class="btn klein geist" onClick=${() => { feld.current && feld.current.setzen(wartet.text); setWartet(null); }}>Abbrechen</button></div></div>`}
    ${wartet && !wartet.langlauf && wartet.dazu && wartet.dazu.length > 0 && html`<div class="hinweisbox tc-kosten">
      <b>Du holst ${wartet.dazu.map((x) => partner(x).name).join(" und ")} dazu.</b>${" "}${wartet.dazu.map((x) => `${partner(x).name} (${partner(x).titel})`).join(", ")} ${wartet.dazu.length > 1 ? "sind bezahlte Cloud-Modelle" : "ist ein bezahltes Cloud-Modell"}:
      der Aufruf kostet Geld beim Anbieter. ${ergebnisId ? "Die vollständige aktuelle Fassung geht mit. " : ""}Die Antwort erscheint hier im Gespräch.
      <div class="knopfreihe" style="margin-top:8px">
        <button class="btn primaer klein" onClick=${() => { const w = wartet; setWartet(null); setExternFrei((f) => [...new Set([...f, ...w.dazu])]); setTimeout(() => sendenFrei(w.text, w.dateien, w.dazu, w.nachher), 0); }}>
          ${wartet.nachher ? `Erlauben: erst ${ich.name}, danach prüft ${wartet.dazu.map((x) => partner(x).name).join(" und ")}` : `Erlauben und ${wartet.dazu.map((x) => partner(x).name).join(" und ")} fragen`}</button>
        <button class="btn klein" onClick=${() => { const w = wartet; setWartet(null); setTimeout(() => sendenFrei(w.text, w.dateien, []), 0); }}>Nur ${ich.name} antworten lassen</button>
        <button class="btn klein geist" onClick=${() => { feld.current && feld.current.setzen(wartet.text); setWartet(null); }}>Abbrechen</button></div></div>`}
    ${wartet && !wartet.langlauf && !(wartet.dazu && wartet.dazu.length) && html`<div class="hinweisbox tc-kosten"><b>${ich.name} ist ein bezahltes Cloud-Modell.</b> Jede Nachricht in diesem Gespräch kostet Geld beim Anbieter.
      <div class="knopfreihe" style="margin-top:8px"><button class="btn primaer klein" onClick=${() => { const w = wartet; setWartet(null); setKostenOk(true); setTimeout(() => sendenFrei(w.text, w.dateien), 0); }}>Für dieses Gespräch erlauben und senden</button>
        <button class="btn klein geist" onClick=${() => { feld.current && feld.current.setzen(wartet.text); setWartet(null); }}>Abbrechen</button></div></div>`}
    <div class="tc-eingabe">
      <${Composer} feldRef=${feld} platzhalter=${ergebnisId ? `Sag ${ich.name}, was am Ergebnis passieren soll …` : langlaufId ? `Sag ${ich.name}, was am LongRun passieren soll …` : `Schreib ${ich.name} …`}
        beimSenden=${senden} laeuft=${!!lauf || !!nach} beimStoppen=${() => { if (lauf) { abbruch.current && abbruch.current.abort(); } else if (nach) { api("/gespraech/" + gid + "/abbrechen", { methode: "POST" }).then(lade).catch(() => {}); } }}
        projektId=${projektId} entwurfKey=${"tc:" + wer + ":" + (ergebnisId || langlaufId || gid || "")} zeilen=${2} />
      <${TempoSchalter} />
      <label class="klein leise tc-vorlesen"><input type="checkbox" checked=${vorlesenAn} onChange=${(e) => setVorlesenAn(e.target.checked)} />Antworten vorlesen</label>
    </div>
  </div>`;
}

// Die Gespraechsseite unter Team: links alle, mit denen man sprechen kann, rechts das Gespraech.
export function TeamGespraeche({ wer, gid }) {
  const [d, setD] = useState(null);
  const [liste, setListe] = useState([]);
  useEffect(() => { api("/team").then(setD).catch(fehlerMelden); bus.sende("talk-kontext", null); }, []);
  const laden = () => wer && api("/teamchat?wer=" + encodeURIComponent(wer)).then((x) => setListe(x.gespraeche)).catch(() => {});
  useEffect(() => { laden(); }, [wer, gid]);
  if (!d) return html`<div class="seite"><div class="lade">Lade …</div></div>`;
  const partner = gespraechsPartner(d);
  const aktiv = partner.find((p) => p.id === wer);
  const ziel = (w, g) => navigiere("/team/chat/" + w + (g ? "/" + g : ""));
  return html`<div class="bd">
    <aside class="bd-tisch">
      <${Ziehgriff} name="bd-liste" seite="rechts" />
      <div class="bd-tisch-kopf"><h3>Mit wem sprechen?</h3><span class="leise klein">Lokal rechnet auf deinem Server. Extern kostet Geld je Nachricht.</span></div>
      <div class="bd-personen">
        ${partner.map((p) => html`<div class=${"bd-person am" + (p.id === wer ? " einzel" : "")} key=${p.id}>
          <button class="bd-person-haupt" onClick=${() => ziel(p.id)}><${Avatar} wer=${p.id} name=${p.name} g=${32} />
            <span class="bd-name"><b>${p.name}</b><small>${p.titel}${p.extern ? " · extern" : ""}</small></span></button></div>`)}
        <div class="bd-person am"><a class="bd-person-haupt" href="#/neo"><${Avatar} wer="cockpit" name="Neo" g=${32} />
          <span class="bd-name"><b>Neo</b><small>Cockpit Engineer · eigene Seite</small></span></a></div>
      </div>
    </aside>
    <section class="bd-gespraech">
      ${!aktiv ? html`<div class="bd-verlauf"><${Leer} titel="Wähle links, mit wem du sprechen willst." /></div>` : html`
        <div class="bd-kopf">
          <span class="bd-modus"><${Avatar} wer=${aktiv.id} name=${aktiv.name} g=${26} />Gespräch mit <b>${aktiv.name}</b>
            ${aktiv.extern && html`<span class="pill gelb">kostet Geld</span>`}${aktiv.extern && aktiv.schluessel === false && html`<span class="pill rot">kein Schlüssel</span>`}</span>
          <span class="luecke"></span>
          <${Zuordnung} gid=${gid} />
          <select class="eingabe bd-auswahl" value=${gid || ""} onChange=${(e) => ziel(wer, e.target.value)} title="Frühere Gespräche">
            <option value="">Neues Gespräch</option>${liste.map((g) => html`<option value=${g.id}>${g.titel} · ${zeitText(g.geaendert)}</option>`)}</select>
          ${gid && html`<button class="btn klein geist icon" title="Gespräch aus der Liste nehmen" onClick=${async () => {
            try { await api("/teamchat/" + gid, { methode: "DELETE" }); toast("Aus der Liste genommen."); ziel(wer); } catch (e) { fehlerMelden(e); } }}><${Icon} n="archiv" g=${15} /></button>`}
          <button class="btn klein" onClick=${() => ziel(wer)}><${Icon} n="neu" g=${14} />Neu</button>
        </div>
        <${TeamChat} key=${wer + ":" + (gid || "")} wer=${wer} partnerListe=${partner} gid=${gid}
          beiGespraech=${(g) => { ziel(wer, g); laden(); }} />`}
    </section>
  </div>`;
}
