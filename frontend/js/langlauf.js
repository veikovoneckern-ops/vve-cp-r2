// LANGLAEUFER -- ein langes Vorhaben laeuft in Etappen durch (Veiko, 17.10.2026:
// "ein grosses Buch oder ein langes Video einfach durchlaufen lassen, mit
// automatischen Zwischenpruefungen durch Dario oder Demmis, ohne dass ich jedes
// Mal eingreifen muss"). Ablauf und Regeln: cockpit/langlauf.py.
//
// Die Seite beantwortet drei Fragen: Wie weit ist es? Was haben die Pruefer
// gesagt? Was hat es bisher gekostet? Eingreifen ist moeglich (Hinweis an das
// Team, Pause, Budget), aber nie noetig -- ausser, ein Pruefer haelt an.
import { html, useState, useEffect, useRef, Icon, toast, fehlerMelden, zeitText, Md, Modal, bus, useAbruf } from "./ui.js";
import { api } from "./api.js";
import { TeamChat, gespraechsPartner } from "./teamchat.js";
import { Textfeld } from "./composer.js";

const usd = (n) => "$ " + (n || 0).toFixed(2).replace(".", ",");
const STAND = {
  plant: ["lila", "plant die Etappen"], laeuft: ["lila", "läuft"], wartet: ["gelb", "wartet auf dich"],
  pausiert: ["", "pausiert"], fehler: ["rot", "hängt"], fertig: ["gruen", "fertig"], abgebrochen: ["", "abgebrochen"],
};
const URTEIL = { weiter: ["gruen", "trägt -- weiter"], nachbessern: ["gelb", "nachgebessert"], anhalten: ["rot", "angehalten"] };
const PRUEFER = { dario: "Dario (Claude)", demmis: "Demmis (Gemini)" };

// "Was schon dazugehoert" (17.10.2026): Ergebnisse, Gespraeche, Unterlagen und
// Notizen des Projekts zum Ankreuzen. Das Team liest beim Planen und je Etappe
// den aktuellen Inhalt des Angekreuzten (langlauf.material_text).
const MATERIAL_GRUPPEN = [["ergebnis", "Ergebnisse"], ["gespraech", "Gespräche"], ["datei", "Unterlagen"], ["notiz", "Notizen"]];
const schluessel = (m) => m.art + ":" + m.id;

function Material({ bestand, wahl, setWahl }) {
  const umschalten = (k) => { const n = new Set(wahl); n.has(k) ? n.delete(k) : n.add(k); setWahl(n); };
  const gruppe = (art, an) => { const n = new Set(wahl); bestand.filter((m) => m.art === art).forEach((m) => an ? n.add(schluessel(m)) : n.delete(schluessel(m))); setWahl(n); };
  return html`<div class="ll-material">
    ${MATERIAL_GRUPPEN.map(([art, name]) => {
      const liste = bestand.filter((m) => m.art === art);
      if (!liste.length) return "";
      const gewaehlt = liste.filter((m) => wahl.has(schluessel(m))).length;
      return html`<div class="ll-mat-gruppe" key=${art}>
        <div class="ll-mat-kopf"><b>${name}</b><span class="leise klein">${gewaehlt} von ${liste.length}</span><span class="luecke"></span>
          <button class="btn klein geist" onClick=${() => gruppe(art, gewaehlt < liste.length)}>${gewaehlt < liste.length ? "alle" : "keine"}</button></div>
        ${liste.map((m) => html`<label class="ll-mat-zeile" key=${schluessel(m)}>
          <input type="checkbox" checked=${wahl.has(schluessel(m))} onChange=${() => umschalten(schluessel(m))} />
          <span class="haupt-text"><span>${m.titel}</span><span class="leise klein">${m.unter}${m.zeit ? " · " + zeitText(m.zeit) : ""}</span></span></label>`)}
      </div>`;
    })}
  </div>`;
}

function Neu({ zu, fertig, d, vorlage }) {
  const [f, setF] = useState({ titel: "", auftrag: "", art: "buch", rolle: "", projekt_id: "", aufgabe_id: "", pruefer: "dario", pruef_alle: 3, budget: 5, ...(vorlage || {}) });
  const [projekte, setProjekte] = useState([]);
  const [sendet, setSendet] = useState(false);
  const [bestand, setBestand] = useState(null);
  const [wahl, setWahl] = useState(new Set());
  const [vs, setVs] = useState(null);   // Vorschlag: null | {laeuft} | {begruendung, modell} | {fehler}
  // Was Veiko selbst getippt/gewaehlt hat, ueberschreibt kein Vorschlag.
  const angefasst = useRef(new Set((vorlage && vorlage.fest) || []));
  const vsNr = useRef(0);
  useEffect(() => { api("/projekte").then((x) => setProjekte(x.projekte || [])).catch(() => {}); }, []);
  const s = (k) => (e) => { const v = e.target.value; angefasst.current.add(k); setF((x) => ({ ...x, [k]: v })); };
  const vorgabeRolle = (d.arten[f.art] || {}).rolle;
  const material = () => (bestand || []).filter((m) => wahl.has(schluessel(m))).map((m) => ({ art: m.art, id: m.id }));

  async function vorschlagHolen(mat) {
    const nr = ++vsNr.current;
    setVs({ laeuft: true });
    try {
      const v = await api("/langlaeufe/vorschlag", { methode: "POST", daten: { projekt_id: f.projekt_id, aufgabe_id: f.aufgabe_id, material: mat } });
      if (nr !== vsNr.current) return;
      setF((x) => { const n = { ...x }; for (const k of ["art", "titel", "auftrag", "rolle", "pruef_alle"]) if (v[k] && !angefasst.current.has(k)) n[k] = v[k]; return n; });
      setVs({ begruendung: v.begruendung, modell: v.modell });
    } catch (e) { if (nr === vsNr.current) setVs({ fehler: e.message || String(e) }); }
  }

  // Bestand je Projekt laden; aus Projekt oder Aufgabe gestartet gleich einen Vorschlag holen.
  const ersterVorschlag = useRef(!!(vorlage && (vorlage.projekt_id || vorlage.aufgabe_id)));
  useEffect(() => {
    if (!f.projekt_id && !f.aufgabe_id) { setBestand([]); setWahl(new Set()); return; }
    let weg = false;
    setBestand(null);
    api(`/langlaeufe/bestand?projekt_id=${encodeURIComponent(f.projekt_id || "")}&aufgabe_id=${encodeURIComponent(f.aufgabe_id || "")}`)
      .then((x) => {
        if (weg) return;
        const b = x.bestand || [];
        const vor = new Set(b.filter((m) => m.vorgewaehlt).map(schluessel));
        // Aus dem Gespraech an einem Ergebnis gestartet: dieses Ergebnis ist die Grundlage.
        if (vorlage && vorlage.ergebnis_id && b.some((m) => m.art === "ergebnis" && m.id === vorlage.ergebnis_id)) vor.add("ergebnis:" + vorlage.ergebnis_id);
        setBestand(b); setWahl(vor);
        if (ersterVorschlag.current) { ersterVorschlag.current = false; vorschlagHolen(b.filter((m) => vor.has(schluessel(m))).map((m) => ({ art: m.art, id: m.id }))); }
      })
      .catch((e) => { if (!weg) { setBestand([]); fehlerMelden(e); } });
    return () => { weg = true; };
  }, [f.projekt_id]);

  async function los() {
    setSendet(true);
    try {
      const r = await api("/langlaeufe", { methode: "POST", daten: { ...f, rolle: f.rolle || vorgabeRolle, material: material() } });
      toast("LongRun gestartet. Er plant jetzt die Etappen.");
      fertig(r.id);
    } catch (e) { fehlerMelden(e); setSendet(false); }
  }
  return html`<${Modal} titel="Neuer LongRun" zu=${zu} breit
    fuss=${html`<button class="btn" onClick=${zu}>Abbrechen</button>
      <button class="btn primaer" disabled=${sendet || f.auftrag.trim().length < 20} onClick=${los}>${sendet ? "startet …" : "Starten"}</button>`}>
    <div class="ll-form">
      <label>Was soll entstehen?
        <select class="eingabe" value=${f.art} onChange=${s("art")}>
          ${Object.entries(d.arten).map(([k, a]) => html`<option value=${k}>${a.name}</option>`)}</select></label>
      <label>Titel<input class="eingabe" value=${f.titel} onInput=${s("titel")} placeholder="z. B. Führen in der Transformation" /></label>
      <label class="breit">Das Vorhaben -- so genau wie möglich (Inhalt, Zielgruppe, Ton, Länge)
        <${Textfeld} class="eingabe" rows="6" value=${f.auftrag} onInput=${s("auftrag")}
          placeholder=${f.art === "video" ? "z. B. Ein Erklärvideo von etwa 8 Minuten über … für …, ruhiger Ton, …" : "z. B. Ein Sachbuch mit rund 12 Kapiteln über … für …, Ton …, je Kapitel ein Praxisbeispiel …"} /></label>
      <label>Wer arbeitet
        <select class="eingabe" value=${f.rolle || vorgabeRolle} onChange=${s("rolle")}>
          ${d.rollen.map((r) => html`<option value=${r.id}>${r.name}</option>`)}</select></label>
      <label>Projekt
        <select class="eingabe" value=${f.projekt_id} onChange=${s("projekt_id")}>
          <option value="">— ohne Projekt —</option>
          ${projekte.filter((p) => p.status !== "archiviert").map((p) => html`<option value=${p.id}>${p.name}</option>`)}</select></label>
      <label>Prüfung durch
        <select class="eingabe" value=${f.pruefer} onChange=${s("pruefer")}>
          ${Object.entries(PRUEFER).map(([k, n]) => html`<option value=${k}>${n}</option>`)}</select></label>
      <label>Wann prüfen?
        <select class="eingabe" value=${String(f.pruef_alle)} onChange=${s("pruef_alle")}>
          <option value="0">nur am Ende, wenn alles fertig ist</option>
          ${[1, 2, 3, 4, 5, 6, 8, 10].map((n) => html`<option value=${n}>nach je ${n} ${n === 1 ? (d.arten[f.art] || {}).etappe || "Etappe" : (d.arten[f.art] || {}).mehrzahl || "Etappen"}</option>`)}</select></label>
      <label>Budget für die Prüfungen (US-$)
        <input class="eingabe" type="number" min="0" step="0.5" value=${f.budget} onInput=${s("budget")} /></label>
    </div>
    ${(f.projekt_id || f.aufgabe_id) && html`<div class="ll-vorschlag">
      ${vs && vs.laeuft ? html`<span class="ll-jetzt"><span class="vf-spin"></span>Das Cockpit liest das Material und schlägt die Felder vor …</span>`
        : vs && vs.fehler ? html`<span class="klein">Vorschlag nicht verfügbar: ${vs.fehler}</span>`
        : vs ? html`<span class="klein"><b>Vorschlag eingesetzt</b> (${vs.modell}) -- jedes Feld bleibt änderbar; was du selbst geändert hast, bleibt stehen.${vs.begruendung ? " " + vs.begruendung : ""}</span>`
        : html`<span class="leise klein">Das Cockpit kann Art, Titel, Vorhaben und Rolle aus Projekt und Material vorschlagen.</span>`}
      <span class="luecke"></span>
      <button class="btn klein" disabled=${!!(vs && vs.laeuft) || bestand === null} onClick=${() => vorschlagHolen(material())}>
        <${Icon} n="stift" g=${13} />${vs && !vs.laeuft ? "Neu vorschlagen" : "Vorschlag machen"}</button>
    </div>
    <section class="ll-mat-bereich">
      <h4>Was schon dazugehört <span class="leise klein">-- das Team baut darauf auf und liest den aktuellen Stand</span></h4>
      ${bestand === null ? html`<div class="lade">Lade, was zum Projekt schon da ist …</div>`
        : bestand.length ? html`<${Material} bestand=${bestand} wahl=${wahl} setWahl=${setWahl} />`
        : html`<p class="leise klein">Zu diesem Projekt gibt es noch keine Ergebnisse, Gespräche, Unterlagen oder Notizen.</p>`}
    </section>`}
    ${f.aufgabe_id && html`<p class="hinweisbox klein" style="margin-top:12px">Gehört zur Aufgabe <b>${f.aufgabe_titel || ""}</b>. Sie bekommt Start und Ergebnis als Zeile in ihre Notiz; ihr Stand bleibt deine Entscheidung.</p>`}
    <p class="leise klein ll-erkl">Das Team schreibt lokal auf deinem Server -- das kostet nichts. Geld kosten nur die Zwischenprüfungen durch
      ${f.pruefer === "dario" ? " Dario" : " Demmis"}. <b>Das Budget ist deine Zustimmung:</b> so viel dürfen sie insgesamt kosten; vor jeder Prüfung
      wird geschätzt, und reicht der Rest nicht, läuft es lokal weiter, ohne zu fragen. Angehalten wird nur, wenn der Prüfer sagt, dass es
      ohne deine Entscheidung nicht weitergeht -- dann steht eine Frage im Briefing.
      ${f.art === "video" ? " Ein langes Video rechnet am Ende viele Stunden (etwa 12 Szenen je Minute)." : ""}</p>
    ${!d.zugang_extern && html`<p class="fehlerbox klein">Für Dario und Demmis fehlt der Zugang (ihre Schlüssel -- der Befehl dafür steht unter Recommendations). Der LongRun läuft dann ohne externe Prüfung, nur mit Daniel.</p>`}
  </${Modal}>`;
}

// Was sonst gerade fuer diesen Langlaeufer arbeitet: Recherche, Antwort im
// Gespraech, Video ... (aktionen.fuer). Veiko, 17.10.2026: "es wird gearbeitet,
// der Status steht aber auf fertig -- ich moechte immer die aktuellen Stati sehen."
export function Nebenbei({ liste }) {
  if (!liste || !liste.length) return null;
  return html`<div class="ll-nebenbei">${liste.map((n) => html`<div class="ll-jetzt" key=${n.id}><span class="vf-spin"></span>
    <span><b>${n.art_name}${n.wer ? " · " + n.wer : ""}:</b> ${n.schritt || n.titel}${n.teile ? " · " + n.teile : ""}
      ${n.jetzt ? html`<span class="leise klein"> · ${n.jetzt.modell} ${n.jetzt.phase}${n.jetzt.tok_aus ? ", " + n.jetzt.tok_aus.toLocaleString("de-DE") + " Token" : ""}</span>` : ""}
      ${" "}<a class="klein" href="#/aktionen">Current Actions</a></span></div>`)}</div>`;
}
const standAnzeige = (l) => {
  const [farbe, text] = STAND[l.stand] || ["", l.stand];
  if (l.arbeitet) return ["lila", "arbeitet"];
  if ((l.nebenbei || []).length) return ["lila", (l.stand === "fertig" ? "fertig · " : text + " · ") + "es wird weitergearbeitet"];
  return [farbe, text];
};

function Zeile({ l, an, waehlen }) {
  const [farbe, text] = standAnzeige(l);
  const pz = l.etappen ? Math.round(100 * l.fertig / l.etappen) : 0;
  return html`<button class=${"ll-zeile" + (an ? " an" : "")} onClick=${() => waehlen(l.id)}>
    <div class="ll-zeile-kopf"><b>${l.titel}</b><span class=${"pill " + farbe}>${text}</span></div>
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
        ${e.daniel && html`<span class="pill" title=${e.daniel.begruendung || ""}>Daniel: ${e.daniel.urteil === "tragfaehig" ? "trägt" : e.daniel.urteil === "eingearbeitet" || e.ueberarbeitet ? "eingearbeitet" : e.daniel.urteil}</span>`}
        ${ex && html`<span class=${"pill " + ex[0]}>${ex[1]}</span>`}
        ${fertig && html`<${Icon} n=${auf ? "runter" : "rechts"} g=${14} />`}</span>
    </div>
    ${auf && html`<div class="ll-etappe-text"><${Md} text=${e.text || ""} /></div>`}
  </div>`;
}

function Detail({ id, neuLaden }) {
  const [l, laden] = useAbruf("/langlaeufe/" + id, 5000, [id]);
  const [budget, setBudget] = useState(null);
  if (!l) return html`<div class="lade">Lade …</div>`;
  const tun = async (aktion, daten, text) => {
    try { const r = await api(`/langlaeufe/${id}/${aktion}`, { methode: "POST", daten: daten || {} }); if (text) toast(text); laden(); neuLaden(); return r; }
    catch (e) { fehlerMelden(e); }
  };
  const [farbe, standText] = standAnzeige(l);
  const aktiv = ["plant", "laeuft", "wartet"].includes(l.stand);
  // Kennzahlen als EINE Zeile statt vier grosser Kacheln, die drei Aufklapper
  // nebeneinander (Veiko, 17.10.2026: "mehr Platz fuer die wesentlichen Inhalte").
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
      <${Nebenbei} liste=${l.nebenbei} />
      ${l.grund && l.stand === "wartet" && html`<div class="fehlerbox"><b>Wartet auf dich.</b> ${l.grund}<br /><span class="klein">Beantworte die Frage im Briefing -- danach arbeitet er von selbst weiter. Oder „Fortsetzen“, um ohne Antwort weiterzumachen.</span></div>`}
      ${l.fehler && html`<div class="fehlerbox"><b>${l.stand === "fehler" ? "Angehalten nach drei Fehlversuchen." : "Letzter Schritt gescheitert, wird wiederholt."}</b> ${l.fehler}</div>`}
      ${l.extern_aus && html`<div class="hinweisbox klein">${l.extern_aus}</div>`}
      <div class="ll-zahlen">
        <span><b>${l.fertig} von ${l.etappen || "?"}</b> ${l.etappen_name}</span>
        <span>schreibt <b>${l.rolle_name}</b></span>
        <span>prüft <b>${PRUEFER[l.pruefer] || l.pruefer}</b> ${l.pruef_alle == 0 ? "am Ende das fertige Werk" : "nach je " + l.pruef_alle + " " + (l.pruef_alle == 1 ? l.etappe_name : l.etappen_name)}</span>
        <span><b>${usd(l.kosten)}</b> von ${usd(l.budget)}
          ${budget === null ? html`<button class="btn klein geist" onClick=${() => setBudget(l.budget)}>Budget ändern</button>`
            : html`<span class="ll-budget"><input class="eingabe" type="number" min="0" step="0.5" value=${budget} onInput=${(e) => setBudget(e.target.value)} />
              <button class="btn klein primaer" onClick=${() => { tun("budget", { budget }, "Budget gespeichert."); setBudget(null); }}>OK</button></span>`}</span>
      </div>
      <div class="ll-aufklapper">
        <details class="klein ll-auftrag"><summary>Das Vorhaben</summary><p>${l.auftrag}</p></details>
        ${(l.material || []).length > 0 && html`<details class="klein ll-auftrag"><summary>${l.material.length} ${l.material.length === 1 ? "Stück" : "Stücke"} Material</summary>
          <ul>${l.material.map((m) => html`<li key=${m.art + m.id}>${m.titel}</li>`)}</ul></details>`}
        ${(l.hinweise || []).length > 0 && html`<details class="klein ll-auftrag"><summary>${l.hinweise.length} Hinweise für die weiteren ${l.etappen_name}</summary>
          <ul>${l.hinweise.slice().reverse().map((h, i) => html`<li key=${i}><b>${h.von}:</b> ${h.text}</li>`)}</ul></details>`}
      </div>
    </div>

    <${LanglaufChat} l=${l} neuLaden=${() => { laden(); neuLaden(); }} />

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

// Das Gespraech zum Langlaeufer (17.10.2026, Veiko: "ueber den Zwischenpruefungen
// ein vollfunktionsfaehiges Chatfenster fuer weitere Anweisungen und Dialog").
// Es ist der Team-Chat (teamchat.js) mit dem Langlaeufer als Bezug -- derselbe
// Weg wie im Ergebnisfenster: Anhaenge, Diktat, Externe dazuholen, Vorlesen.
// Ersetzt die fruehere einfache Hinweis-Zeile (Bauregel 2). Eine Anweisung wird
// Hinweis fuer die weiteren Etappen, Ueberarbeitung fertiger Etappen oder neue
// Etappen (langlauf.chat_anweisungen); was uebernommen wurde, steht unter der Antwort.
function LanglaufChat({ l, neuLaden }) {
  const [team, setTeam] = useState(null);
  const [wer, setWer] = useState(l.rolle || "buch");
  const [gid, setGid] = useState(undefined);
  useEffect(() => { api("/team").then(setTeam).catch(() => setTeam({ team: [], externe: [] })); }, []);
  useEffect(() => { setWer(l.rolle || "buch"); }, [l.id]);
  useEffect(() => {
    setGid(undefined);
    api(`/teamchat?wer=${encodeURIComponent(wer)}&langlauf_id=${encodeURIComponent(l.id)}`)
      .then((x) => setGid(x.gespraeche[0] ? x.gespraeche[0].id : null)).catch(() => setGid(null));
  }, [wer, l.id]);
  // Die Hoehe des Gespraechs folgt dem freien Platz bis zum unteren Bildschirmrand
  // (Veiko, 17.10.2026: erst "das Eingabefeld ist nicht vollstaendig zu sehen",
  // dann -- mit einem am Rand festgehaltenen Feld -- "jetzt liegt es ueber dem
  // scrollbaren Text"). So endet der Verlauf genau ueber dem Feld und das Feld am
  // Rand; zwischen 250 und 640 Punkt, damit es weder winzig noch endlos wird.
  const ref = useRef(null);
  useEffect(() => {
    let wartet = false;
    const passen = () => {
      wartet = false;
      const tc = ref.current && ref.current.querySelector(".tc");
      if (!tc) return;
      const nav = document.querySelector(".unten-nav");
      const unten = nav && getComputedStyle(nav).display !== "none" ? nav.getBoundingClientRect().top : window.innerHeight;
      // Auf schmalen Geraeten scrollt die ganze Seite: feste Hoehe, gut drei Viertel des
      // Bildschirms. Nach dem freien Platz gerechnet blieben dort 250 Punkt, davon 98 fuer
      // den Verlauf (gemessen am 18.10.2026 bei 390 Punkt Breite).
      if (window.matchMedia("(max-width:820px)").matches) { tc.style.maxHeight = Math.round(Math.max(420, unten * 0.78)) + "px"; return; }
      const oben = tc.getBoundingClientRect().top;
      // Ausserhalb des Bildschirms nichts aendern -- sonst schoebe das Wachsen beim
      // Vorbeiscrollen alles darunter (Zwischenpruefungen, Etappen) mit.
      if (oben < 0 || oben > unten - 120) return;
      tc.style.maxHeight = Math.round(Math.max(250, Math.min(640, unten - oben - 12))) + "px";
    };
    const anstossen = () => { if (!wartet) { wartet = true; requestAnimationFrame(passen); } };
    passen();
    document.addEventListener("scroll", anstossen, true);   // die Seite scrollt in einem inneren Bereich
    window.addEventListener("resize", anstossen);
    const t = setInterval(passen, 1500);   // der Chat laedt nach und kann darueber die Lage verschieben
    return () => { document.removeEventListener("scroll", anstossen, true); window.removeEventListener("resize", anstossen); clearInterval(t); };
  }, []);
  const partner = gespraechsPartner(team);
  const n = l.etappen_name;
  return html`<section class="karte ll-chat" ref=${ref}>
    <div class="karte-kopf"><h3>Gespräch zum LongRun</h3>
      <select class="eingabe bd-auswahl" value=${wer} onChange=${(e) => setWer(e.target.value)} aria-label="Mit wem sprechen">
        ${partner.length ? partner.map((m) => html`<option value=${m.id}>${m.name} · ${m.extern ? "extern, kostet Geld" : m.id === l.rolle ? "schreibt diesen LongRun" : m.titel}</option>`)
          : html`<option value=${wer}>${l.rolle_name}</option>`}</select>
      ${gid && html`<button class="btn klein geist" onClick=${() => setGid(null)} title="Neues Gespräch zu diesem LongRun"><${Icon} n="neu" g=${13} />Neu</button>`}
      ${(l.nacharbeit || []).length > 0 && html`<span class="pill lila">${l.nacharbeit.length} zur Überarbeitung vorgemerkt</span>`}</div>
    ${team && gid !== undefined ? html`<${TeamChat} key=${wer + ":" + (gid || "neu")} wer=${wer} partnerListe=${partner} gid=${gid} langlaufId=${l.id}
        projektId=${l.projekt_id || ""} beiGespraech=${setGid}
        leerText=${`Frag nach dem Stand, gib Anweisungen für die weiteren ${n}, lass fertige ${n} überarbeiten oder weitere anhängen. Unterlagen über das Plus. Was davon im LongRun ankommt, steht jeweils unter der Antwort.`} />`
      : html`<div class="lade">Lade …</div>`}
  </section>`;
}

export function Langlaeufer({ id }) {
  const [d, laden] = useAbruf("/langlaeufe", 15000);
  // Aus Projekt oder Aufgabe gestartet (langlaufStarten): Formular gleich offen und vorbelegt.
  const [neu, setNeu] = useState(() => id === "neu" && !!naechsteVorlage);
  const [vorlage] = useState(() => { const v = naechsteVorlage; naechsteVorlage = null; return v; });
  const [wahl, setWahl] = useState(id && id !== "neu" ? id : null);
  useEffect(() => { if (id && id !== "neu") setWahl(id); }, [id]);
  if (!d) return html`<div class="seite"><div class="lade">Lade LongRuns …</div></div>`;
  const aktuell = wahl || (d.langlaeufe[0] && d.langlaeufe[0].id);
  return html`<div class="seite ll">
    <div class="ll-kopf">
      <details class="ll-info klein"><summary>So arbeitet ein LongRun</summary>
        <p class="leise">Ein langes Vorhaben -- ein Buch, ein langes Dokument, ein langes Video -- läuft hier in Etappen durch. Das Team schreibt lokal,
        Daniel prüft jede Etappe, und alle paar Etappen liest Dario oder Demmis mit und gibt Hinweise für den Rest. Du musst nicht eingreifen;
        angehalten wird nur, wenn ein Prüfer deine Entscheidung braucht.</p></details>
      <button class="btn primaer klein" onClick=${() => setNeu(true)}><${Icon} n="plus" g=${14} />Neuer LongRun</button>
    </div>
    ${d.langlaeufe.length ? html`<div class="ll-raster">
        <div class="ll-liste">${d.langlaeufe.map((l) => html`<${Zeile} key=${l.id} l=${l} an=${l.id === aktuell} waehlen=${setWahl} />`)}</div>
        ${aktuell && html`<${Detail} id=${aktuell} neuLaden=${laden} />`}
      </div>`
      : html`<div class="karte"><p class="leise">Noch kein LongRun. „Neuer LongRun“ startet einen -- zum Beispiel ein Buch mit zwölf Kapiteln.</p></div>`}
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
  bus.sende("fenster-alle-zu");
  location.hash = "#/langlauf/neu";
}
