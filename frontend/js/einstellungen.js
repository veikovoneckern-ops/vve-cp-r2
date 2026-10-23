// EINSTELLUNGEN (17.10.2026) -- was Veiko am Cockpit selbst einstellt, an einem
// Ort: was das Team ohne Nachfrage darf, ob es neue Notizen bearbeitet, Stimme, Memory,
// Postfach, Daten und Konto. Vorher verteilt auf Team (Tab "Freigaben") und
// System (Kasten "Diese Fassung"). Welches Modell wofuer rechnet, steht unter
// Team -- das ist keine Einstellung, sondern Besetzung. Memory kam am 19.10.2026
// von der Teamseite hierher (Veiko: "da macht er mehr Sinn fuer mich").
import { html, useState, useEffect, Icon, toast, fehlerMelden, aktualisieren, zeitText, useAbruf, bus, Klappe, useAbschnitt } from "./ui.js";
import { api } from "./api.js";
import { Vertrauen, Gedaechtnis } from "./team.js";

function Wert({ name, wert, warn }) {
  return html`<div class="messwert"><span class="leise">${name}</span><b style=${warn ? "color:var(--signal)" : ""}>${wert ?? "nicht verfügbar"}</b></div>`;
}

// Vorgabe fuer neue Praesentationen (folien_stil.py, 18.10.2026). "Eigene Vorgaben" ist
// keine Vorgabe: die beschreibt Veiko je Praesentation, im Auftrag oder am Ergebnis.
function PraesentationStil() {
  const [d, setD] = useState(null);
  useEffect(() => { api("/einstellungen").then(setD).catch(fehlerMelden); }, []);
  if (!d || !d.praesentation_stile) return "";
  async function setzen(id) {
    try { setD(await api("/einstellungen", { methode: "POST", daten: { praesentation_stil: id } })); toast("Gespeichert."); }
    catch (x) { fehlerMelden(x); }
  }
  const vorgabe = d.praesentation_stile.find((s) => s.id === d.praesentation_stil);
  return html`<section class="karte" style="margin-top:14px"><div class="karte-kopf"><h3>Präsentationen</h3></div>
    <div class="knopfreihe"><span class="leise">Neue Präsentationen sehen so aus:</span>
      <div class="segment">${d.praesentation_stile.filter((s) => s.id !== "eigen").map((s) => html`<button class=${d.praesentation_stil === s.id ? "an" : ""}
        onClick=${() => setzen(s.id)}>${s.name}</button>`)}</div></div>
    ${vorgabe && html`<p class="leise klein" style="margin-top:8px">${vorgabe.beschreibung}</p>`}
    <p class="leise klein">Beim Auftrag und an jeder fertigen Präsentation lässt sich das Aussehen umstellen, auch auf eigene Vorgaben. Neu gerechnet wird dafür nichts.</p>
  </section>`;
}

// Explorer-Klick (23.10.2026) -- Veiko: "ob ich beim Klick im Explorer das als Vorschau
// grundsaetzlich oeffne oder sofort in einer der Apps, also PowerPoint, WinWord, Excel,
// oder Bilder". "In der App" heisst: der Browser laedt das Original, und Windows oeffnet es
// mit dem Programm, das fuer die Endung eingetragen ist. Ein direkter Sprung nach
// PowerPoint (ms-powerpoint:) braucht eine Adresse, die Office OHNE Anmeldung abrufen
// kann -- das waere ein offener Link auf Veikos Dateien, und das Cockpit baut keinen.
function ExplorerOeffnen() {
  const [d, setD] = useState(null);
  useEffect(() => { api("/einstellungen").then(setD).catch(fehlerMelden); }, []);
  if (!d) return "";
  async function setzen(w) {
    try { setD(await api("/einstellungen", { methode: "POST", daten: { explorer_oeffnen: w } })); bus.sende("explorer-oeffnen", w); toast("Gespeichert."); }
    catch (x) { fehlerMelden(x); }
  }
  const w = d.explorer_oeffnen || "vorschau";
  return html`<section class="karte" style="margin-top:14px"><div class="karte-kopf"><h3>Dateien im Explorer öffnen</h3></div>
    <div class="knopfreihe"><span class="leise">Ein Doppelklick im Explorer öffnet</span>
      <div class="segment"><button class=${w === "vorschau" ? "an" : ""} onClick=${() => setzen("vorschau")}>die Vorschau im Cockpit</button>
        <button class=${w === "app" ? "an" : ""} onClick=${() => setzen("app")}>gleich die App</button></div></div>
    <p class="leise klein" style="margin-top:8px">${w === "app"
      ? "PowerPoint, Word, Excel, PDF, Bilder, Ton und Film kommen als Original auf diesen Rechner und öffnen sich im Programm, das Windows dafür kennt. Fertige Präsentationen des Teams kommen als PowerPoint, Texte als Word. Alles andere (Notizen, Webseiten, Videos des Teams) zeigt weiter die Vorschau."
      : "PowerPoint als Folien, Word und Texte als Seite, Fotos und PDF im Browser. Das Original lässt sich in jeder Vorschau herunterladen."}</p>
    ${w === "app" && html`<p class="leise klein">Damit sich die Datei <b>ohne weiteren Klick</b> öffnet: beim ersten Mal in der Download-Leiste von Edge oder Chrome auf die drei Punkte neben der Datei und <b>„Dateien dieses Typs immer öffnen"</b> wählen — einmal je Dateityp (pptx, docx, xlsx …). Auf iPad und Telefon gibt es das nicht; dort landet die Datei bei den Downloads.</p>`}
  </section>`;
}

export function Einstellungen({ konto, thema, abschnitt }) {
  const [d, laden] = useAbruf("/system", 30000, []);
  const [laeuft, setLaeuft] = useState("");
  useEffect(() => { bus.sende("talk-kontext", { art: "einstellungen", id: "einstellungen", titel: "Settings" }); return () => bus.sende("talk-kontext", null); }, []);
  useAbschnitt(abschnitt);

  async function abgleich() {
    setLaeuft("abgleich");
    try {
      const r = await api("/system/abgleich", { methode: "POST" });
      const n = r.neu; const summe = Object.values(n).reduce((a, b) => a + b, 0);
      toast(summe ? `Übernommen: ${n.projekte} Projekte, ${n.aufgaben} Aufgaben, ${n.notizen + n.plaud} Notizen, ${n.vorgaenge} Cases.` : "Nichts Neues im alten Cockpit.");
      laden(); aktualisieren();
    } catch (x) { fehlerMelden(x); }
    setLaeuft("");
  }
  const g = d ? d.stab || {} : {};
  const e = d ? d.einstellungen || {} : {};

  return html`<div class="seite">
    <${Vertrauen} />
    <${PraesentationStil} />
    <${ExplorerOeffnen} />
    <div style="margin-top:14px"><${Klappe} id="memory" titel="Memory" unter="Was dein Team über dich weiß: Personen, Begriffe, Hörfehler, Aussprache" vorgabe=${true}>
      <${Gedaechtnis} /></${Klappe}></div>
    <div style="margin-top:14px"><${Klappe} id="versionen" titel="Versionsverlauf" unter="Was sich am Cockpit wann geändert hat -- jede Auslieferung, nach Tagen und Bereichen">
      <${Versionen} /></${Klappe}></div>
    ${d && html`<div class="raster-gleich drei" style="margin-top:14px">
      <section class="karte"><div class="karte-kopf"><h3>Team-Pipeline</h3></div>
        <${Wert} name="Team" wert=${g.stab_aktiv ? "an" : "aus"} />
        <${Wert} name="Letzter Durchgang" wert=${g.letzter_lauf ? zeitText(g.letzter_lauf) : "noch keiner"} />
        <${Wert} name="Gerade" wert=${g.laeuft ? g.laeuft.was : "nichts"} />
        <${Wert} name="Plaud-Abruf" wert=${g.sync ? zeitText(g.sync) : "unbekannt"} warn=${g.sync && Date.now() / 1000 - g.sync > 1800} />
        <${Wert} name="Letzte Notiz" wert=${g.letzte_datei ? zeitText(g.letzte_datei) : "unbekannt"} />
        ${g.letzter_fehler && html`<div class="fehlerbox" style="margin-top:8px">${g.letzter_fehler}</div>`}
        <div class="knopfreihe karte-fuss"><button class="btn klein" onClick=${async () => { await api("/system/durchgang", { methode: "POST" }); toast("Team-Durchgang angestoßen."); }}><${Icon} n="play" g=${13} />Jetzt einen Durchgang</button></div>
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Daten</h3></div>
        ${Object.entries(d.db).map(([k, v]) => html`<${Wert} name=${k[0].toUpperCase() + k.slice(1)} wert=${v} />`)}
        <${Wert} name="Abgleich mit altem Cockpit" wert=${e.letzter_abgleich ? zeitText(e.letzter_abgleich) : "nie"} />
        <div class="knopfreihe karte-fuss"><button class="btn klein" disabled=${laeuft === "abgleich"} onClick=${abgleich} title="Holt nur, was es hier noch nicht gibt.">
          <${Icon} n="neu_laden" g=${13} />${laeuft === "abgleich" ? "Gleiche ab …" : "Mit altem Cockpit abgleichen"}</button></div>
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Konto und Darstellung</h3></div>
        <${Wert} name="Angemeldet als" wert=${konto.benutzer} />
        <${Wert} name="Mikrofon im Browser" wert=${window.isSecureContext ? "möglich" : "nur über https"} warn=${!window.isSecureContext} />
        ${!window.isSecureContext && html`<div class="hinweisbox" style="margin-top:8px">Öffne das Cockpit über <b>https://vveorgxais.tail4ca1ab.ts.net:8443</b>.</div>`}
        <div class="knopfreihe karte-fuss">
          <button class="btn klein" onClick=${thema}><${Icon} n="mond" g=${13} />Hell / Dunkel</button>
          <button class="btn klein" onClick=${() => { try { localStorage.removeItem("vvec_thema"); } catch (x) { /* egal */ } delete document.documentElement.dataset.theme; }}>Wie das System</button>
          <button class="btn klein gefahr" onClick=${() => api("/konto/abmelden", { methode: "POST" }).then(() => location.reload())}><${Icon} n="raus" g=${13} />Abmelden</button>
        </div>
      </section>
    </div>`}
  </div>`;
}

// ------------------------------------------------------------ Versionsverlauf (19.10.2026)
// Quelle ist die Git-Geschichte (cockpit/versionen.py) -- keine eigene Liste, die man
// pflegen muesste. Ein Tag mit Aenderungen ist eine Version; die neueste steht oben auf.
function Versionen() {
  const [d] = useAbruf("/versionen", 0, []);
  const [q, setQ] = useState("");
  const [bereich, setBereich] = useState("");
  const [auf, setAuf] = useState("");            // aufgeklappte Version -- anfangs keine (alles zu, wie jede Sektion)
  const [mehr, setMehr] = useState(8);
  if (!d) return html`<div class="lade">Lade …</div>`;
  if (d.quelle_fehlt) return html`<div class="hinweisbox">Der Versionsverlauf ist hier nicht abrufbar: das Cockpit findet seine Git-Geschichte nicht.</div>`;
  const such = q.trim().toLowerCase();
  const passt = (c) => (!bereich || c.bereiche.includes(bereich))
    && (!such || (c.titel + " " + c.punkte.join(" ")).toLowerCase().includes(such));
  const liste = d.versionen.map((v) => ({ ...v, treffer: v.aenderungen.filter(passt) })).filter((v) => v.treffer.length);
  const gefiltert = !!(such || bereich);
  const offen = auf;
  const datum = (tag) => { const [j, m, t] = tag.split("-"); return `${t}.${m}.${j}`; };
  const uhr = (s) => new Date(s * 1000).toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  const lf = d.laeuft || {};
  return html`<div class="vv">
    <div class="vv-stand">
      <span class="pill gruen">Läuft: Version ${lf.version || "?"}</span>
      <span class="unter-text">Commit ${lf.kurz || "unbekannt"} · gestartet ${lf.seit ? zeitText(lf.seit) : "unbekannt"} · ${d.versionen.length} Versionen seit ${datum(d.versionen[d.versionen.length - 1].tag)}</span>
      ${d.neustart_offen && html`<span class="pill gelb" title=${"Im Repo liegt " + d.im_repo.kurz + ", der Dienst läuft noch mit " + lf.kurz}>Neuer Stand eingespielt, noch nicht neu gestartet</span>`}
    </div>
    <div class="us-filter">
      <input class="eingabe vv-suche" type="search" placeholder="Suchen, z. B. Talk, Diktat, Präsentation" value=${q} onInput=${(e) => setQ(e.target.value)} aria-label="Im Versionsverlauf suchen" />
      <select class="eingabe" value=${bereich} onChange=${(e) => setBereich(e.target.value)} aria-label="Bereich">
        <option value="">Alle Bereiche</option>${d.bereiche.map((b) => html`<option value=${b}>${b}</option>`)}</select>
      ${gefiltert && html`<span class="unter-text">${liste.reduce((n, v) => n + v.treffer.length, 0)} Änderungen in ${liste.length} Versionen</span>`}
    </div>
    ${!liste.length && html`<div class="leer">Nichts gefunden.</div>`}
    ${liste.slice(0, gefiltert ? 999 : mehr).map((v) => {
      const zeigen = gefiltert || offen === v.version;
      return html`<section class=${"vv-version" + (zeigen ? " auf" : "")} key=${v.version}>
        <button class="vv-kopf" onClick=${() => setAuf(offen === v.version ? "" : v.version)} aria-expanded=${zeigen}>
          <span class="vv-pfeil" aria-hidden="true"><${Icon} n="rechts" g=${14} w=${2.4} /></span>
          <b>Version ${v.version}</b><span class="vv-datum">${datum(v.tag)}</span>
          ${lf.version === v.version && html`<span class="pill gruen">läuft</span>`}
          <span class="vv-zahl">${v.treffer.length} ${v.treffer.length === 1 ? "Änderung" : "Änderungen"}</span>
          <span class="vv-bereiche">${v.bereiche.slice(0, 4).map((b) => html`<span class="pill">${b}</span>`)}</span>
        </button>
        ${zeigen && html`<ul class="vv-liste">${v.treffer.map((c) => html`<li key=${c.sha}>
          <div class="vv-titel"><span>${c.titel}</span><span class="vv-meta">${uhr(c.zeit)} · ${c.kurz}</span></div>
          <div class="vv-tags">${c.bereiche.map((b) => html`<button class="pill vv-tag" onClick=${() => setBereich(b)} title="Nur diesen Bereich zeigen">${b}</button>`)}</div>
          ${c.punkte.length > 0 && html`<ul class="vv-punkte">${c.punkte.map((p, i) => html`<li key=${i}>${p}</li>`)}</ul>`}
        </li>`)}</ul>`}
      </section>`;
    })}
    ${!gefiltert && liste.length > mehr && html`<button class="btn klein" style="margin-top:8px" onClick=${() => setMehr(mehr + 15)}>Ältere Versionen zeigen</button>`}
    <p class="unter-text" style="margin-top:10px">Eine Version ist ein Tag mit Auslieferungen. Die Bereiche ergeben sich aus den geänderten Dateien. Die Änderungen stammen aus der Git-Geschichte der neuen Fassung (vve-cp-r2) -- die alte Fassung ist hier nicht enthalten.</p>
  </div>`;
}
