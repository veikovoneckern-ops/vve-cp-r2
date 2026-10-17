// LANGLAEUFER -- ein langes Vorhaben laeuft in Etappen durch (Veiko, 17.10.2026:
// "ein grosses Buch oder ein langes Video einfach durchlaufen lassen, mit
// automatischen Zwischenpruefungen durch Dario oder Demmis, ohne dass ich jedes
// Mal eingreifen muss"). Ablauf und Regeln: cockpit/langlauf.py.
//
// Die Seite beantwortet drei Fragen: Wie weit ist es? Was haben die Pruefer
// gesagt? Was hat es bisher gekostet? Eingreifen ist moeglich (Hinweis an das
// Team, Pause, Budget), aber nie noetig -- ausser, ein Pruefer haelt an.
import { html, useState, useEffect, Icon, toast, fehlerMelden, zeitText, Md, Modal, bus, useAbruf } from "./ui.js";
import { api } from "./api.js";

const usd = (n) => "$ " + (n || 0).toFixed(2).replace(".", ",");
const STAND = {
  plant: ["lila", "plant die Etappen"], laeuft: ["lila", "läuft"], wartet: ["gelb", "wartet auf dich"],
  pausiert: ["", "pausiert"], fehler: ["rot", "hängt"], fertig: ["gruen", "fertig"], abgebrochen: ["", "abgebrochen"],
};
const URTEIL = { weiter: ["gruen", "trägt -- weiter"], nachbessern: ["gelb", "nachgebessert"], anhalten: ["rot", "angehalten"] };
const PRUEFER = { dario: "Dario (Claude)", demmis: "Demmis (Gemini)" };

function Neu({ zu, fertig, d, vorlage }) {
  const [f, setF] = useState({ titel: "", auftrag: "", art: "buch", rolle: "", projekt_id: "", aufgabe_id: "", pruefer: "dario", pruef_alle: 3, budget: 5, ...(vorlage || {}) });
  const [projekte, setProjekte] = useState([]);
  const [sendet, setSendet] = useState(false);
  useEffect(() => { api("/projekte").then((x) => setProjekte(x.projekte || [])).catch(() => {}); }, []);
  const s = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const vorgabeRolle = (d.arten[f.art] || {}).rolle;
  async function los() {
    setSendet(true);
    try {
      const r = await api("/langlaeufe", { methode: "POST", daten: { ...f, rolle: f.rolle || vorgabeRolle } });
      toast("Langläufer gestartet. Er plant jetzt die Etappen.");
      fertig(r.id);
    } catch (e) { fehlerMelden(e); setSendet(false); }
  }
  return html`<${Modal} titel="Neuer Langläufer" zu=${zu} breit
    fuss=${html`<button class="btn" onClick=${zu}>Abbrechen</button>
      <button class="btn primaer" disabled=${sendet || f.auftrag.trim().length < 20} onClick=${los}>${sendet ? "startet …" : "Starten"}</button>`}>
    <div class="ll-form">
      <label>Was soll entstehen?
        <select class="eingabe" value=${f.art} onChange=${s("art")}>
          ${Object.entries(d.arten).map(([k, a]) => html`<option value=${k}>${a.name}</option>`)}</select></label>
      <label>Titel<input class="eingabe" value=${f.titel} onInput=${s("titel")} placeholder="z. B. Führen in der Transformation" /></label>
      <label class="breit">Das Vorhaben -- so genau wie möglich (Inhalt, Zielgruppe, Ton, Länge)
        <textarea class="eingabe" rows="6" value=${f.auftrag} onInput=${s("auftrag")}
          placeholder=${f.art === "video" ? "z. B. Ein Erklärvideo von etwa 8 Minuten über … für …, ruhiger Ton, …" : "z. B. Ein Sachbuch mit rund 12 Kapiteln über … für …, Ton …, je Kapitel ein Praxisbeispiel …"}></textarea></label>
      <label>Wer arbeitet
        <select class="eingabe" value=${f.rolle || vorgabeRolle} onChange=${s("rolle")}>
          ${d.rollen.map((r) => html`<option value=${r.id}>${r.name}</option>`)}</select></label>
      <label>Projekt
        <select class="eingabe" value=${f.projekt_id} onChange=${s("projekt_id")}>
          <option value="">— ohne Projekt —</option>
          ${projekte.filter((p) => p.status !== "archiviert").map((p) => html`<option value=${p.id}>${p.name}</option>`)}</select></label>
      <label>Zwischenprüfung durch
        <select class="eingabe" value=${f.pruefer} onChange=${s("pruefer")}>
          ${Object.entries(PRUEFER).map(([k, n]) => html`<option value=${k}>${n}</option>`)}</select></label>
      <label>Prüfen nach je … ${(d.arten[f.art] || {}).mehrzahl || "Etappen"}
        <input class="eingabe" type="number" min="1" max="10" value=${f.pruef_alle} onInput=${s("pruef_alle")} /></label>
      <label>Budget für die Prüfungen (US-$)
        <input class="eingabe" type="number" min="0" step="0.5" value=${f.budget} onInput=${s("budget")} /></label>
    </div>
    ${f.aufgabe_id && html`<p class="hinweisbox klein" style="margin-top:12px">Gehört zur Aufgabe <b>${f.aufgabe_titel || ""}</b>. Sie bekommt Start und Ergebnis als Zeile in ihre Notiz; ihr Stand bleibt deine Entscheidung.</p>`}
    <p class="leise klein ll-erkl">Das Team schreibt lokal auf deinem Server -- das kostet nichts. Geld kosten nur die Zwischenprüfungen durch
      ${f.pruefer === "dario" ? " Dario" : " Demmis"}. <b>Das Budget ist deine Zustimmung:</b> so viel dürfen sie insgesamt kosten; vor jeder Prüfung
      wird geschätzt, und reicht der Rest nicht, läuft es lokal weiter, ohne zu fragen. Angehalten wird nur, wenn der Prüfer sagt, dass es
      ohne deine Entscheidung nicht weitergeht -- dann steht eine Frage im Briefing.
      ${f.art === "video" ? " Ein langes Video rechnet am Ende viele Stunden (etwa 12 Szenen je Minute)." : ""}</p>
    ${!d.zugang_extern && html`<p class="fehlerbox klein">Für Dario und Demmis fehlt der Zugang (VVEC_ALT_TOKEN). Der Langläufer läuft dann ohne externe Prüfung, nur mit Daniel.</p>`}
  </${Modal}>`;
}

function Zeile({ l, an, waehlen }) {
  const [farbe, text] = STAND[l.stand] || ["", l.stand];
  const pz = l.etappen ? Math.round(100 * l.fertig / l.etappen) : 0;
  return html`<button class=${"ll-zeile" + (an ? " an" : "")} onClick=${() => waehlen(l.id)}>
    <div class="ll-zeile-kopf"><b>${l.titel}</b><span class=${"pill " + farbe}>${l.arbeitet ? "arbeitet" : text}</span></div>
    <div class="leise klein">${l.art_name} · ${l.rolle_name} · ${l.etappen ? `${l.fertig} von ${l.etappen} ${l.etappen_name}` : "noch kein Plan"} · ${usd(l.kosten)} von ${usd(l.budget)}</div>
    <div class="video-balken"><i style=${`width:${pz}%`}></i></div>
  </button>`;
}

function Etappe({ e, name }) {
  const [auf, setAuf] = useState(false);
  const fertig = e.stand === "fertig";
  const ex = URTEIL[e.extern];
  return html`<div class=${"ll-etappe" + (fertig ? " fertig" : "")}>
    <div class="ll-etappe-kopf" onClick=${() => fertig && setAuf(!auf)} role=${fertig ? "button" : null}>
      <span class="ll-nr">${e.nr}</span>
      <div class="haupt-text"><b>${e.titel}</b>
        <div class="leise klein">${fertig ? (e.kurz || "") : (e.inhalt || "")}</div></div>
      <span class="ll-marken">
        ${fertig ? html`<span class="pill">${(e.text || "").split(/\s+/).length} Wörter</span>` : html`<span class="pill">offen</span>`}
        ${e.daniel && html`<span class="pill" title=${e.daniel.begruendung || ""}>Daniel: ${e.daniel.urteil === "tragfaehig" ? "trägt" : e.ueberarbeitet ? "überarbeitet" : e.daniel.urteil}</span>`}
        ${ex && html`<span class=${"pill " + ex[0]}>${ex[1]}</span>`}
        ${fertig && html`<${Icon} n=${auf ? "runter" : "rechts"} g=${14} />`}</span>
    </div>
    ${auf && html`<div class="ll-etappe-text"><${Md} text=${e.text || ""} /></div>`}
  </div>`;
}

function Detail({ id, neuLaden }) {
  const [l, laden] = useAbruf("/langlaeufe/" + id, 10000, [id]);
  const [hinweis, setHinweis] = useState("");
  const [budget, setBudget] = useState(null);
  if (!l) return html`<div class="lade">Lade …</div>`;
  const tun = async (aktion, daten, text) => {
    try { const r = await api(`/langlaeufe/${id}/${aktion}`, { methode: "POST", daten: daten || {} }); if (text) toast(text); laden(); neuLaden(); return r; }
    catch (e) { fehlerMelden(e); }
  };
  const [farbe, standText] = STAND[l.stand] || ["", l.stand];
  const aktiv = ["plant", "laeuft", "wartet"].includes(l.stand);
  return html`<div class="ll-detail">
    <div class="karte">
      <div class="karte-kopf"><h3>${l.titel}</h3><span class=${"pill " + farbe}>${standText}</span>
        <span class="luecke"></span>
        ${aktiv && html`<button class="btn klein" onClick=${() => tun("pausieren", null, "Pausiert.")}>Pausieren</button>`}
        ${["pausiert", "fehler", "wartet"].includes(l.stand) && html`<button class="btn klein primaer" onClick=${() => tun("fortsetzen", null, "Läuft weiter.")}>Fortsetzen</button>`}
        ${l.fertig > 0 && !l.ergebnis_id && html`<button class="btn klein" title="Ein Ergebnis aus allem, was bisher fertig ist -- der Lauf geht weiter"
          onClick=${async () => { const r = await tun("zusammenfassen"); if (r && r.ergebnis_id) bus.sende("ergebnis-zeigen", r.ergebnis_id); }}>Zwischenstand ansehen</button>`}
        ${l.ergebnis_id && html`<button class="btn klein primaer" onClick=${() => bus.sende("ergebnis-zeigen", l.ergebnis_id)}>Ergebnis ansehen</button>`}
        ${aktiv || l.stand === "pausiert" || l.stand === "fehler" ? html`<${FrageKnopf} text="Abbrechen" frage="Wirklich abbrechen? Fertige Etappen bleiben." ja="Abbrechen" tun=${() => tun("abbrechen", null, "Abgebrochen.")} />` : ""}
      </div>
      ${l.arbeitet && html`<div class="ll-jetzt"><span class="vf-spin"></span>${l.was || "arbeitet"}</div>`}
      ${l.grund && l.stand === "wartet" && html`<div class="fehlerbox"><b>Wartet auf dich.</b> ${l.grund}<br /><span class="klein">Beantworte die Frage im Briefing -- danach arbeitet er von selbst weiter. Oder „Fortsetzen“, um ohne Antwort weiterzumachen.</span></div>`}
      ${l.fehler && html`<div class="fehlerbox"><b>${l.stand === "fehler" ? "Angehalten nach drei Fehlversuchen." : "Letzter Schritt gescheitert, wird wiederholt."}</b> ${l.fehler}</div>`}
      ${l.extern_aus && html`<div class="hinweisbox klein">${l.extern_aus}</div>`}
      <div class="ll-zahlen">
        <div><span class="leise klein">Fortschritt</span><b>${l.fertig} von ${l.etappen || "?"} ${l.etappen_name}</b></div>
        <div><span class="leise klein">Arbeitet</span><b>${l.rolle_name}</b></div>
        <div><span class="leise klein">Prüft nach je ${l.pruef_alle} ${l.pruef_alle == 1 ? l.etappe_name : l.etappen_name}</span><b>${PRUEFER[l.pruefer] || l.pruefer}</b></div>
        <div><span class="leise klein">Kosten / Budget</span><b>${usd(l.kosten)} / ${usd(l.budget)}</b>
          ${budget === null ? html`<button class="btn klein" onClick=${() => setBudget(l.budget)}>ändern</button>`
            : html`<span class="ll-budget"><input class="eingabe" type="number" min="0" step="0.5" value=${budget} onInput=${(e) => setBudget(e.target.value)} />
              <button class="btn klein primaer" onClick=${() => { tun("budget", { budget }, "Budget gespeichert."); setBudget(null); }}>OK</button></span>`}</div>
      </div>
      ${aktiv || l.stand === "pausiert" ? html`<div class="ll-hinweis">
        <input class="eingabe" value=${hinweis} placeholder="Hinweis an das Team für die nächsten Etappen (optional) …" onInput=${(e) => setHinweis(e.target.value)}
          onKeyDown=${(e) => { if (e.key === "Enter" && hinweis.trim()) { tun("hinweis", { text: hinweis }, "Hinweis gilt ab der nächsten Etappe."); setHinweis(""); } }} />
        <button class="btn klein" disabled=${!hinweis.trim()} onClick=${() => { tun("hinweis", { text: hinweis }, "Hinweis gilt ab der nächsten Etappe."); setHinweis(""); }}>Mitgeben</button></div>` : ""}
      <details class="klein ll-auftrag"><summary>Das Vorhaben</summary><p>${l.auftrag}</p></details>
    </div>

    ${l.pruefungsliste.length > 0 && html`<section class="karte">
      <div class="karte-kopf"><h3>Zwischenprüfungen</h3><span class="leise klein">${l.pruefungsliste.length} · zusammen ${usd(l.kosten)}</span></div>
      ${l.pruefungsliste.slice().reverse().map((p) => { const u = URTEIL[p.urteil] || ["", p.urteil]; return html`<div class="ll-pruefung">
        <div><b>${p.name}</b> zu ${l.etappe_name} ${p.von}–${p.bis} <span class=${"pill " + u[0]}>${u[1]}</span>
          <span class="leise klein"> · ${zeitText(p.zeit)} · ${usd(p.kosten)}</span></div>
        <div class="klein">${p.begruendung}</div>
        ${p.hinweise.length > 0 && html`<ul class="klein">${p.hinweise.map((h) => html`<li>${h}</li>`)}</ul>`}
        ${p.nachbessern.length > 0 && html`<div class="leise klein">Nachgebessert: ${l.etappe_name} ${p.nachbessern.join(", ")}</div>`}
      </div>`; })}
    </section>`}

    <section class="karte">
      <div class="karte-kopf"><h3>${l.etappen_name}</h3><span class="leise klein">Klick auf einen fertigen Eintrag zeigt den Text</span></div>
      ${l.etappenliste.length ? l.etappenliste.map((e) => html`<${Etappe} key=${e.nr} e=${e} name=${l.etappe_name} />`)
        : html`<p class="leise">${l.stand === "plant" ? "Der Plan entsteht gerade …" : "Noch kein Plan."}</p>`}
    </section>
  </div>`;
}

export function Langlaeufer({ id }) {
  const [d, laden] = useAbruf("/langlaeufe", 15000);
  // Aus Projekt oder Aufgabe gestartet (langlaufStarten): Formular gleich offen und vorbelegt.
  const [neu, setNeu] = useState(() => id === "neu" && !!naechsteVorlage);
  const [vorlage] = useState(() => { const v = naechsteVorlage; naechsteVorlage = null; return v; });
  const [wahl, setWahl] = useState(id && id !== "neu" ? id : null);
  useEffect(() => { if (id && id !== "neu") setWahl(id); }, [id]);
  if (!d) return html`<div class="seite"><div class="lade">Lade Langläufer …</div></div>`;
  const aktuell = wahl || (d.langlaeufe[0] && d.langlaeufe[0].id);
  return html`<div class="seite ll">
    <div class="ll-kopf">
      <p class="leise">Ein langes Vorhaben -- ein Buch, ein langes Dokument, ein langes Video -- läuft hier in Etappen durch. Das Team schreibt lokal,
        Daniel prüft jede Etappe, und alle paar Etappen liest Dario oder Demmis mit und gibt Hinweise für den Rest. Du musst nicht eingreifen;
        angehalten wird nur, wenn ein Prüfer deine Entscheidung braucht.</p>
      <button class="btn primaer" onClick=${() => setNeu(true)}><${Icon} n="plus" g=${15} />Neuer Langläufer</button>
    </div>
    ${d.langlaeufe.length ? html`<div class="ll-raster">
        <div class="ll-liste">${d.langlaeufe.map((l) => html`<${Zeile} key=${l.id} l=${l} an=${l.id === aktuell} waehlen=${setWahl} />`)}</div>
        ${aktuell && html`<${Detail} id=${aktuell} neuLaden=${laden} />`}
      </div>`
      : html`<div class="karte"><p class="leise">Noch kein Langläufer. „Neuer Langläufer“ startet einen -- zum Beispiel ein Buch mit zwölf Kapiteln.</p></div>`}
    ${neu && html`<${Neu} d=${d} vorlage=${vorlage} zu=${() => setNeu(false)} fertig=${(nid) => { setNeu(false); setWahl(nid); laden(); }} />`}
  </div>`;
}

// Eine Rueckfrage direkt am Knopf -- wie ueberall in dieser Fassung (verfahren.js).
function FrageKnopf({ text, frage, ja, tun: aktion }) {
  const [auf, setAuf] = useState(false);
  if (auf) return html`<span class="knopfreihe"><span class="klein">${frage}</span>
    <button class="btn klein primaer" onClick=${() => { setAuf(false); aktion(); }}>${ja}</button>
    <button class="btn klein geist" onClick=${() => setAuf(false)}>Nein</button></span>`;
  return html`<button class="btn klein" onClick=${() => setAuf(true)}>${text}</button>`;
}

// Aus einem Projekt oder einer Aufgabe heraus starten (17.10.2026): Projekt,
// Aufgabe, Titel und Auftrag stehen schon im Formular. Gemerkt in einer
// Modulvariablen statt in der Adresse -- ein langer Auftragstext gehoert nicht in die URL.
let naechsteVorlage = null;
export function langlaufStarten(vorlage) {
  naechsteVorlage = vorlage || {};
  location.hash = "#/langlauf/neu";
}
