// EXPLORER (19.10.2026) -- alles, was im Cockpit entstanden ist, an einem Ort.
// Veiko: "eine weitere Seite Explorer. Hier moechte ich alle generierten Inhalte
// sehen koennen, filtern, suchen, etc. -- vergleichbar zu einem Windows Datei
// Explorer." Anlass war ein Recherche-Dossier aus Talk, das er nicht wiederfand.
//
// Aufbau wie im Datei-Explorer: links die Ordner (nach Art und nach Projekt mit
// seinen Aufgaben), in der Mitte die Liste oder Kacheln, rechts die Vorschau des
// gewaehlten Eintrags. Ein Klick waehlt, ein Doppelklick (oder Enter, oder auf dem
// Telefon ein Tippen) oeffnet -- in der Ansicht, die es fuer das Ding schon gibt:
// Ergebnisfenster, Unterlage, Notiz, Bild. Der Explorer fuehrt keinen eigenen
// Bestand (cockpit/explorer.py liest die Tabellen); aendern kann er nur, wohin
// eine Unterlage gehoert.
import { html, useState, useEffect, Icon, Md, fehlerMelden, zeitText, bus } from "./ui.js";
import { api } from "./api.js";
import { URTEIL } from "./ergebnis.js";
import { ZuordnungWahl } from "./datei.js";

const GRUPPEN = [["alle", "Alles", "explorer"], ["ergebnis", "Ergebnisse", "check"], ["recherche", "Recherche & Abschriften", "suche"],
  ["bild", "Bilder", "auge"], ["unterlage", "Unterlagen", "clip"], ["notiz", "Notizen", "stift"]];
const ICON = { text: "liste", aufstellung: "liste", konzept: "liste", dokument: "liste", webseite: "globus", praesentation: "voll",
  video: "play", dossier: "suche", abschrift: "welle", unterlage: "clip", bild: "auge", visualisierung: "auge", notiz: "stift" };
const ZEIT = [["", "jederzeit"], ["1", "heute"], ["7", "7 Tage"], ["30", "30 Tage"], ["365", "1 Jahr"]];
const groesse = (e) => (e.einheit === "Byte"
  ? (e.groesse >= 1048576 ? (e.groesse / 1048576).toFixed(1).replace(".", ",") + " MB" : e.groesse >= 1024 ? Math.round(e.groesse / 1024) + " KB" : e.groesse + " B")
  : (e.groesse >= 1000 ? Math.round(e.groesse / 1000) + " Tsd. Z." : (e.groesse || 0) + " Z."));
const lies = (k, v) => { try { return localStorage.getItem("ex-" + k) || v; } catch (e) { return v; } };
const merk = (k, v) => { try { localStorage.setItem("ex-" + k, v); } catch (e) { /* egal */ } };

export function oeffnen(e) {
  if (e.art === "ergebnis") bus.sende("ergebnis-zeigen", e.id);
  else if (e.art === "datei") bus.sende("datei-zeigen", e.id);
  else if (e.art === "notiz") bus.sende("notiz-zeigen", e.id);
  else if (e.art === "bild") window.open("/api/medien/datei/" + e.datei, "_blank", "noopener");
}

export function Explorer() {
  const [d, setD] = useState(null);
  const [q, setQ] = useState("");
  const [inhalt, setInhalt] = useState(() => lies("inhalt", "0") === "1");
  const [treffer, setTreffer] = useState({});
  const [ordner, setOrdner] = useState(() => lies("ordner", "alle"));   // alle | gruppe | p:<id> | a:<id> | p:_ohne
  const [zeit, setZeit] = useState(() => lies("zeit", ""));
  const [wer, setWer] = useState("");
  const [ansicht, setAnsicht] = useState(() => lies("ansicht", "liste"));
  const [sort, setSort] = useState({ feld: "zeit", richtung: -1 });
  const [wahl, setWahl] = useState(null);
  const [offen, setOffen] = useState({});   // aufgeklappte Projekte im Baum
  const [schmal, setSchmal] = useState(() => matchMedia("(max-width:900px)").matches);
  const laden = () => api("/explorer").then(setD).catch(fehlerMelden);
  useEffect(() => { laden(); return bus.an("explorer-neu", laden); }, []);
  useEffect(() => { const m = matchMedia("(max-width:900px)"); const h = () => setSchmal(m.matches); m.addEventListener("change", h); return () => m.removeEventListener("change", h); }, []);
  useEffect(() => { bus.sende("talk-kontext", { art: "explorer", id: "explorer", titel: "Explorer" }); return () => bus.sende("talk-kontext", null); }, []);
  useEffect(() => { merk("ordner", ordner); merk("zeit", zeit); merk("ansicht", ansicht); merk("inhalt", inhalt ? "1" : "0"); }, [ordner, zeit, ansicht, inhalt]);
  // Im Inhalt suchen: auf dem Server, nach einer kurzen Pause im Tippen.
  useEffect(() => {
    if (!inhalt || q.trim().length < 3) { setTreffer({}); return undefined; }
    const t = setTimeout(() => api("/explorer?q=" + encodeURIComponent(q.trim())).then((x) => setTreffer(x.im_inhalt || {})).catch(() => {}), 350);
    return () => clearTimeout(t);
  }, [q, inhalt]);

  if (!d) return html`<div class="seite"><div class="lade">Lade den Explorer …</div></div>`;
  const alle = d.eintraege;
  const zaehl = (fn) => alle.filter(fn).length;
  const imOrdner = (e) => ordner === "alle" ? true
    : ordner.startsWith("p:") ? (ordner === "p:_ohne" ? !e.projekt_id : e.projekt_id === ordner.slice(2))
    : ordner.startsWith("a:") ? e.aufgabe_id === ordner.slice(2) : e.gruppe === ordner;
  const qn = q.trim().toLowerCase();
  const grenze = zeit ? Date.now() / 1000 - Number(zeit) * 86400 : 0;
  const liste = alle.filter((e) => imOrdner(e) && (!grenze || (e.zeit || 0) >= grenze) && (!wer || e.wer === wer)
      && (!qn || (e.titel || "").toLowerCase().includes(qn) || (e.projekt_name || "").toLowerCase().includes(qn) || (e.aufgabe_titel || "").toLowerCase().includes(qn) || treffer[e.id]))
    .sort((a, b) => {
      const va = a[sort.feld] ?? "", vb = b[sort.feld] ?? "";
      return (typeof va === "string" ? String(va).localeCompare(String(vb), "de") : va - vb) * sort.richtung;
    });
  const werListe = [...new Set(alle.map((e) => e.wer).filter(Boolean))].sort();
  const ordnerName = ordner === "alle" ? "Alles" : ordner === "p:_ohne" ? "Ohne Projekt"
    : ordner.startsWith("p:") ? (d.projekte.find((p) => p.id === ordner.slice(2)) || {}).name || "Projekt"
    : ordner.startsWith("a:") ? (alle.find((e) => e.aufgabe_id === ordner.slice(2)) || {}).aufgabe_titel || "Aufgabe"
    : (GRUPPEN.find((g) => g[0] === ordner) || [0, ordner])[1];
  const gewaehlt = wahl && alle.find((e) => e.id === wahl);
  const klick = (e) => { if (schmal) oeffnen(e); else setWahl(e.id); };
  const th = (feld, text, klasse = "") => html`<th class=${klasse}><button class="vb-sort" onClick=${() => setSort({ feld, richtung: sort.feld === feld ? -sort.richtung : (feld === "titel" ? 1 : -1) })}>
    ${text}${sort.feld === feld ? (sort.richtung < 0 ? " ▾" : " ▴") : ""}</button></th>`;
  // Aufgaben je Projekt, die Eintraege haben -- fuer den Baum.
  const aufgabenVon = (pid) => {
    const m = new Map();
    alle.forEach((e) => { if (e.projekt_id === pid && e.aufgabe_id) m.set(e.aufgabe_id, (m.get(e.aufgabe_id) || { titel: e.aufgabe_titel, n: 0 })); });
    alle.forEach((e) => { if (e.projekt_id === pid && e.aufgabe_id) m.get(e.aufgabe_id).n++; });
    return [...m.entries()];
  };
  const projekteMit = d.projekte.filter((p) => alle.some((e) => e.projekt_id === p.id));

  const baum = html`<nav class="ex-baum" aria-label="Ordner">
    <div class="ex-baum-titel leise klein">Nach Art</div>
    ${GRUPPEN.map(([k, t, ic]) => html`<button class=${"ex-ordner" + (ordner === k ? " an" : "")} onClick=${() => setOrdner(k)}>
      <${Icon} n=${ic} g=${15} /><span>${t}</span><small>${k === "alle" ? alle.length : zaehl((e) => e.gruppe === k)}</small></button>`)}
    <div class="ex-baum-titel leise klein">Nach Projekt</div>
    ${projekteMit.map((p) => {
      const auf = aufgabenVon(p.id);
      return html`<div>
        <div class=${"ex-ordner-zeile" + (ordner === "p:" + p.id ? " an" : "")}>
          <button class="ex-pfeil" disabled=${!auf.length} aria-expanded=${!!offen[p.id]} aria-label=${(offen[p.id] ? "Aufgaben zuklappen: " : "Aufgaben aufklappen: ") + p.name}
            onClick=${() => setOffen({ ...offen, [p.id]: !offen[p.id] })}>${auf.length ? html`<${Icon} n=${offen[p.id] ? "runter" : "rechts"} g=${13} w=${2.4} />` : ""}</button>
          <button class="ex-ordner" onClick=${() => setOrdner("p:" + p.id)}><${Icon} n="projects" g=${15} /><span>${p.name}</span><small>${zaehl((e) => e.projekt_id === p.id)}</small></button>
        </div>
        ${offen[p.id] && auf.map(([aid, a]) => html`<button class=${"ex-ordner ex-aufgabe" + (ordner === "a:" + aid ? " an" : "")} onClick=${() => setOrdner("a:" + aid)}>
          <${Icon} n="check" g=${13} /><span>${a.titel}</span><small>${a.n}</small></button>`)}
      </div>`;
    })}
    <button class=${"ex-ordner" + (ordner === "p:_ohne" ? " an" : "")} onClick=${() => setOrdner("p:_ohne")}><${Icon} n="projects" g=${15} /><span>Ohne Projekt</span><small>${zaehl((e) => !e.projekt_id)}</small></button>
  </nav>`;

  return html`<div class="seite ex">
    <div class="ex-kopf" role="group" aria-label="Suchen und filtern">
      <div class="ex-suche"><${Icon} n="suche" g=${15} />
        <input class="eingabe" type="search" value=${q} placeholder="Suchen: Titel, Projekt, Aufgabe …" aria-label="Im Explorer suchen" onInput=${(e) => setQ(e.target.value)} /></div>
      <label class="klein ex-inhalt" title="Auch im Text von Ergebnissen, Unterlagen und Notizen suchen"><input type="checkbox" checked=${inhalt} onChange=${(e) => setInhalt(e.target.checked)} />auch im Inhalt</label>
      ${schmal && html`<select class="eingabe" value=${ordner} onChange=${(e) => setOrdner(e.target.value)} aria-label="Ordner">
        ${GRUPPEN.map(([k, t]) => html`<option value=${k}>${t}</option>`)}
        <optgroup label="Projekte">${projekteMit.map((p) => html`<option value=${"p:" + p.id}>${p.name}</option>`)}<option value="p:_ohne">Ohne Projekt</option></optgroup>
        ${ordner.startsWith("a:") && html`<option value=${ordner}>Aufgabe: ${ordnerName}</option>`}</select>`}
      <select class="eingabe" value=${zeit} onChange=${(e) => setZeit(e.target.value)} aria-label="Zeitraum">${ZEIT.map(([k, t]) => html`<option value=${k}>${t}</option>`)}</select>
      <select class="eingabe" value=${wer} onChange=${(e) => setWer(e.target.value)} aria-label="Von wem"><option value="">von allen</option>${werListe.map((w) => html`<option value=${w}>${w}</option>`)}</select>
      <div class="segment" role="group" aria-label="Darstellung">
        <button class=${ansicht === "liste" ? "an" : ""} onClick=${() => setAnsicht("liste")} title="Liste"><${Icon} n="liste" g=${14} /> Liste</button>
        <button class=${ansicht === "kacheln" ? "an" : ""} onClick=${() => setAnsicht("kacheln")} title="Kacheln"><${Icon} n="voll" g=${14} /> Kacheln</button></div>
      <button class="btn klein geist icon" onClick=${laden} title="Neu laden" aria-label="Neu laden"><${Icon} n="neu_laden" g=${15} /></button>
    </div>
    <div class=${"ex-rumpf" + (gewaehlt && !schmal ? " mit-vorschau" : "")}>
      ${!schmal && baum}
      <div class="ex-mitte">
        <div class="ex-pfad"><b>${ordnerName}</b><span class="leise klein">${liste.length} ${liste.length === 1 ? "Eintrag" : "Einträge"}${qn ? ` für „${q.trim()}“` : ""}</span></div>
        ${!liste.length ? html`<div class="karte"><p class="leise">Hier ist nichts${qn || zeit || wer ? " für diese Filter" : ""}.</p></div>`
          : ansicht === "kacheln" ? html`<div class="ex-kacheln">${liste.slice(0, 400).map((e) => html`<button key=${e.id}
              class=${"karte ex-kachel" + (wahl === e.id ? " an" : "")} onClick=${() => klick(e)} onDblClick=${() => oeffnen(e)}
              onKeyDown=${(k) => { if (k.key === "Enter") { k.preventDefault(); oeffnen(e); } }}>
              ${e.art === "bild" ? html`<img src=${"/api/medien/datei/" + e.datei} alt="" loading="lazy" />` : html`<span class="ex-kachel-ic"><${Icon} n=${ICON[e.typ] || "clip"} g=${28} /></span>`}
              <b>${e.titel}</b><span class="leise klein">${e.typ_name}${e.projekt_name ? " · " + e.projekt_name : ""}</span>
              <span class="leise klein">${zeitText(e.zeit)}${e.wer ? " · " + e.wer : ""}</span></button>`)}</div>`
          : html`<div class="tabelle-wrap ex-liste"><table class="tabelle">
              <thead><tr>${th("titel", "Name")}${th("typ_name", "Art", "ex-sp-art")}${th("projekt_name", "Projekt / Aufgabe", "ex-sp-projekt")}${th("wer", "Von", "ex-sp-wer")}${th("zeit", "Geändert")}${th("groesse", "Größe", "zahl ex-sp-groesse")}</tr></thead>
              <tbody>${liste.slice(0, 600).map((e) => html`<tr key=${e.id} tabindex="0" class=${"klickbar" + (wahl === e.id ? " an" : "")}
                  onClick=${() => klick(e)} onDblClick=${() => oeffnen(e)}
                  onKeyDown=${(k) => { if (k.key === "Enter") oeffnen(e); }}>
                <td><span class="ex-name"><${Icon} n=${ICON[e.typ] || "clip"} g=${15} /><span><b>${e.titel}</b>
                  ${treffer[e.id] && html`<span class="leise klein ex-treffer">${treffer[e.id]}</span>`}
                  <span class="leise klein ex-nur-schmal">${e.typ_name}${e.projekt_name ? " · " + e.projekt_name : ""} · ${zeitText(e.zeit)}</span></span></span></td>
                <td class="ex-sp-art"><span class="leise">${e.typ_name}</span>${e.urteil && URTEIL[e.urteil] ? html` <span class=${"pill " + URTEIL[e.urteil].farbe} title=${URTEIL[e.urteil].wort}>${e.urteil === "tragfaehig" ? "✓" : "!"}</span>` : ""}</td>
                <td class="ex-sp-projekt klein">${e.projekt_name || html`<span class="leise">–</span>`}${e.aufgabe_titel ? html`<div class="leise">${e.aufgabe_titel}</div>` : ""}</td>
                <td class="ex-sp-wer klein">${e.wer || "–"}</td>
                <td class="klein">${zeitText(e.zeit)}</td>
                <td class="zahl klein ex-sp-groesse">${groesse(e)}</td></tr>`)}</tbody></table></div>`}
        ${liste.length > 600 && html`<p class="leise klein">Gezeigt sind die ersten 600 -- grenz die Suche ein.</p>`}
      </div>
      ${gewaehlt && !schmal && html`<${Vorschau} e=${gewaehlt} zu=${() => setWahl(null)} neu=${laden} />`}
    </div>
  </div>`;
}

// Rechts: was es ist, wohin es gehoert, ein Blick hinein -- und die Knoepfe.
function Vorschau({ e, zu, neu }) {
  const [text, setText] = useState(null);
  useEffect(() => {
    setText(null);
    const p = e.art === "ergebnis" ? api("/ergebnisse/" + e.id).then((x) => x.inhalt)
      : e.art === "notiz" ? api("/notizen/" + e.id).then((x) => x.text || x.kurz)
      : e.art === "datei" ? api("/dateien/" + e.id + "/info").then((x) => x.text) : Promise.resolve("");
    p.then((t) => setText(String(t || "").replace(/^\s*Bild:.*$/gm, "").slice(0, 1600))).catch(() => setText(""));
  }, [e.id]);
  async function zuordnen(z) {
    try { await api("/dateien/" + e.id, { methode: "PATCH", daten: z }); neu(); } catch (x) { fehlerMelden(x); }
  }
  const u = e.urteil && URTEIL[e.urteil];
  return html`<aside class="karte ex-vorschau" aria-label="Vorschau">
    <div class="ex-vorschau-kopf"><b>${e.titel}</b><button class="btn klein geist icon" onClick=${zu} aria-label="Vorschau schließen"><${Icon} n="x" g=${14} /></button></div>
    <div class="leise klein">${e.typ_name}${e.wer ? " · von " + e.wer : ""} · ${zeitText(e.zeit)} · ${groesse(e)}</div>
    ${u && html`<div style="margin-top:6px"><span class=${"pill " + u.farbe}>${u.wort}</span></div>`}
    <div class="ex-vorschau-ort klein">${e.projekt_name ? html`Projekt <b>${e.projekt_name}</b>` : "ohne Projekt"}${e.aufgabe_titel ? html` · Aufgabe <a href="#" onClick=${(x) => { x.preventDefault(); bus.sende("aufgabe-zeigen", e.aufgabe_id); }}>${e.aufgabe_titel}</a>` : ""}</div>
    ${e.art === "datei" && html`<details class="klein"><summary>Zuordnung ändern</summary><${ZuordnungWahl} projektId=${e.projekt_id} aufgabeId=${e.aufgabe_id} setzen=${zuordnen} /></details>`}
    <div class="ex-vorschau-blick">${e.art === "bild" ? html`<img src=${"/api/medien/datei/" + e.datei} alt=${e.titel} />`
      : text == null ? html`<div class="lade">Lade …</div>` : text ? html`<${Md} text=${text + (text.length >= 1600 ? " …" : "")} />` : html`<span class="leise">Keine Textvorschau.</span>`}</div>
    <div class="knopfreihe">
      <button class="btn primaer klein" onClick=${() => oeffnen(e)}><${Icon} n="voll" g=${13} />Öffnen</button>
      ${e.art !== "bild" && html`<button class="btn klein" onClick=${() => bus.sende("talk-oeffnen", { kontext: { art: e.art === "datei" ? "datei" : e.art === "notiz" ? "notiz" : "ergebnis", id: e.id, titel: e.titel } })}>
        <${Icon} n="talk" g=${13} />Mit Talk besprechen</button>`}
      ${e.art === "datei" && html`<a class="btn klein geist" href=${"/api/dateien/" + e.id} download><${Icon} n="download" g=${13} />Herunterladen</a>`}
      ${e.art === "bild" && html`<a class="btn klein geist" href=${"/api/medien/datei/" + e.datei + "?download=1"} download><${Icon} n="download" g=${13} />Herunterladen</a>`}
      ${e.vorgang_id && html`<a class="btn klein geist" href=${"#/inbox/" + e.vorgang_id}>Herkunft</a>`}
    </div>
  </aside>`;
}
