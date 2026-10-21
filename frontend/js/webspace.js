// WEBSPACE -- die Website veikovoneckern.org im Cockpit bearbeiten (18./19.10.2026).
//
// Veiko: "einen Button WebSpace ... einen eigenen Editor für Webseiten" und am
// 19.10.: "deutlich erweitern ... vergleichbar mit den Top-Tools ... sehr stark
// auf Usability und intuitive Bedienoberfläche achten".
//
// Links: Seiten · Menü · Medien · Suchen. Mitte und rechts: der Editor
// (webspace-editor.js). Oben rechts: "Veröffentlichen" -- immer ein ausdrücklicher
// Klick mit Rückfrage; davor zeigt der Dialog, was sich auf welcher Seite ändert,
// und was vor dem Veröffentlichen auffällt (fehlende Seiten hinter Links, Bilder
// ohne Beschreibung, Platzhalter der KI ...). Gespeichert wird automatisch, aber
// nur in den Klon auf dem Server -- öffentlich ist nichts davon.
import { html, useState, useEffect, useRef, Icon, Modal, toast, fehlerMelden, bus, zeitText } from "./ui.js";
import { api } from "./api.js";
import { Editor, MedienWahl } from "./webspace-editor.js";
import { BASIS, absaetze, vergleichen } from "./webspace-teile.js";
import { Textfeld } from "./composer.js";

export function WebSpace({ pfad: pfadAusAdresse }) {
  const [stand, setStand] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [pfad, setPfad] = useState(pfadAusAdresse || "index.html");
  const [links, setLinks] = useState(() => { try { const t = localStorage.getItem("ws-links"); return t && t !== "menue" ? t : "seiten"; } catch (e) { return "seiten"; } });
  const [neu, setNeu] = useState(false);
  const [pub, setPub] = useState(false);
  const [editorNr, setEditorNr] = useState(0);
  const editorRef = useRef({ sichern: async () => true });

  const laden = () => api("/webspace/stand").then((s) => { setStand(s); setFehler(null); return s; }).catch((e) => setFehler(e.message));
  useEffect(() => { laden(); }, []);
  const laeuft = stand && stand.veroeffentlichung && stand.veroeffentlichung.stand !== "completed";
  useEffect(() => {
    const i = setInterval(() => { if (!document.hidden) laden(); }, laeuft ? 5000 : 30000);
    return () => clearInterval(i);
  }, [laeuft]);
  useEffect(() => { if (pfadAusAdresse) setPfad(pfadAusAdresse); }, [pfadAusAdresse]);
  useEffect(() => {
    if (stand && !stand.seiten.some((s) => s.pfad === pfad)) { setPfad("index.html"); history.replaceState(null, "", "#/webspace"); }
  }, [stand, pfad]);
  useEffect(() => {
    bus.sende("talk-kontext", { art: "webspace", id: "webspace", titel: "WebSpace", pfad });
    return () => bus.sende("talk-kontext", null);
  }, [pfad]);
  const linksWaehlen = (t) => { setLinks(t); try { localStorage.setItem("ws-links", t); } catch (e) { /* egal */ } };

  async function wechseln(neuerPfad, { neuLaden = false } = {}) {
    await editorRef.current.sichern();
    if (neuLaden) await laden();
    if (neuerPfad === pfad) setEditorNr((n) => n + 1);
    setPfad(neuerPfad);
    history.replaceState(null, "", "#/webspace/" + encodeURIComponent(neuerPfad));
  }
  // Nach Änderungen außerhalb des Editors (Menü, Ersetzen, Verwerfen): Editor frisch laden.
  const neuAufbauen = async () => { await laden(); setEditorNr((n) => n + 1); };

  if (fehler && !stand) return html`<div class="karte" style="margin:16px"><h3>WebSpace nicht erreichbar</h3><p class="leise">${fehler}</p>
    <button class="btn" onClick=${laden}>Noch einmal</button></div>`;
  if (!stand) return html`<div class="leise" style="padding:20px">WebSpace wird geladen …</div>`;

  const anzahl = (stand.aenderungen || []).length;
  const pubKnopf = html`<button class="btn primaer klein ws-pub-knopf" onClick=${async () => { await editorRef.current.sichern(); await laden(); setPub(true); }}
    title=${anzahl ? "Änderungen ansehen und veröffentlichen" : "Alles ist veröffentlicht"}>
    <${Icon} n="globus" g=${15} />Veröffentlichen${anzahl ? html`<span class="ws-zahl">${anzahl}</span>` : ""}</button>`;

  return html`<div class="ws2">
    <aside class="ws2-links">
      <div class="segment ws2-tabs">
        ${[["seiten", "Seiten"], ["medien", "Medien"], ["suchen", "Suchen"]].map(([id, t]) => html`<button class=${links === id ? "an" : ""} onClick=${() => linksWaehlen(id)}>${t}</button>`)}
      </div>
      <div class="ws2-links-inhalt">
        ${(links === "seiten" || links === "menue") && html`<${SeitenBaum} stand=${stand} pfad=${pfad} waehlen=${wechseln} neu=${(art) => setNeu(art || "seite")} neuLaden=${laden} menueGeaendert=${neuAufbauen} />`}
        ${links === "medien" && html`<${MedienVerwaltung} />`}
        ${links === "suchen" && html`<${SuchenErsetzen} oeffnen=${wechseln} vorher=${() => editorRef.current.sichern()} fertig=${neuAufbauen} />`}
      </div>
      <${OnlineStand} stand=${stand} />
    </aside>
    <section class="ws2-haupt">
      <${Editor} key=${pfad + "#" + editorNr} pfad=${pfad} stand=${stand} sichernRef=${editorRef} kopfLeiste=${pubKnopf}
        geaendert=${(x) => { if (x && x.wechseln) wechseln(x.wechseln, { neuLaden: true }); else laden(); }}
        geloescht=${async () => { await laden(); wechseln("index.html"); }} />
    </section>
    ${neu && html`<${NeueSeite} vorgabe=${neu} stand=${stand} zu=${() => setNeu(false)} fertig=${async (p) => { setNeu(false); await laden(); wechseln(p); }} />`}
    ${pub && html`<${VeroeffentlichenDialog} stand=${stand} zu=${() => setPub(false)} oeffnen=${(p) => { setPub(false); wechseln(p); }}
      fertig=${async () => { setPub(false); await laden(); }} verworfen=${async () => { setPub(false); await neuAufbauen(); }} />`}
  </div>`;
}

// ---------------------------------------------------------------- Seiten (Struktur der Website)
// Veiko, 19.10.2026: "per Drag and Drop Seiten von der Position verschieben und
// Seiten zu Unterseiten und umgekehrt machen". Die Liste zeigt deshalb die Struktur
// der Website = Reihenfolge und Verschachtelung des Menüs (seiten.json). Was hier
// verschoben wird, ändert das Menü; die ADRESSE einer Seite bleibt dabei gleich
// (alte Links und Google-Einträge funktionieren weiter) -- wie bei Wix/Squarespace.
// Ziehen über Pointer Events am Griff (nie natives Drag, siehe CLAUDE.md); auf
// dem Tablet geht dasselbe über das "…"-Menü. Das Menü kennt nur EINE Unterebene.
function SeitenBaum({ stand, pfad, waehlen, neu, neuLaden, menueGeaendert }) {
  const [suche, setSuche] = useState("");
  const [menue, setMenue] = useState(null);       // offenes "…"-Menü (Schlüssel der Zeile)
  const [zug, setZug] = useState(null);           // { quelle, ziel, x, y, text }
  const [umbenennen, setUmbenennen] = useState(null);
  const liste = useRef(null);
  const zugRef = useRef(null);
  const start = useRef(null);
  const gezogen = useRef(false);

  const seiteVon = (adr) => stand.seiten.find((s) => s.adresse === adr);
  const nav = stand.menue;
  const imMenue = new Set();
  nav.forEach((p) => { imMenue.add(p.href); (p.unter || []).forEach((u) => imMenue.add(u.href)); });
  const frei = stand.seiten.filter((s) => !s.blog && !imMenue.has(s.adresse)).sort((a, b) => a.adresse.localeCompare(b.adresse));
  const blog = stand.seiten.filter((s) => s.blog).sort((a, b) => (a.blog.reihe ?? 999) - (b.blog.reihe ?? 999));
  const q = suche.trim().toLowerCase();
  const passt = (t, a) => !q || (t + " " + a).toLowerCase().includes(q);

  // ------------------------------------------------ Menü ändern (sofort gespeichert, mit Rückgängig)
  async function menueSpeichern(neuNav, meldung) {
    const vorher = JSON.parse(JSON.stringify(nav));
    try {
      await api("/webspace/menue", { methode: "POST", daten: { navigation: neuNav } });
      await menueGeaendert();
      toast(meldung + " Online erst nach dem Veröffentlichen.", { dauer: 10000, aktion: { text: "Rückgängig", fn: async () => {
        try { await api("/webspace/menue", { methode: "POST", daten: { navigation: vorher } }); await menueGeaendert(); } catch (e) { fehlerMelden(e); }
      } } });
    } catch (e) { fehlerMelden(e); }
  }
  const kopie = () => JSON.parse(JSON.stringify(nav));
  const holen = (l, weg) => (weg.length === 1 ? l[weg[0]] : l[weg[0]].unter[weg[1]]);
  function herausnehmen(l, weg) {
    if (weg.length === 1) return l.splice(weg[0], 1)[0];
    const p = l[weg[0]];
    const x = p.unter.splice(weg[1], 1)[0];
    if (!p.unter.length) delete p.unter;
    return x;
  }
  // Quelle an Ziel einsortieren. Ziel: { art: "vor"|"nach"|"in", weg } oder { art: "ende" }.
  function einsortieren(quelle, ziel) {
    const l = kopie();
    let punkt;
    let zielPunkt = ziel.weg ? holen(l, ziel.weg) : null;
    if (quelle.art === "menue") {
      if (ziel.weg && JSON.stringify(ziel.weg) === JSON.stringify(quelle.weg)) return null;
      punkt = herausnehmen(l, quelle.weg);
    } else {
      const s = stand.seiten.find((x) => x.adresse === quelle.adresse);
      punkt = { text: kurzTitel(s.titel), href: s.adresse };
    }
    if (ziel.art === "in") {
      if (punkt.unter) { toast("Eine Seite mit Unterseiten kann selbst keine Unterseite werden (das Menü hat nur eine Unterebene).", { fehler: true }); return null; }
      (zielPunkt.unter = zielPunkt.unter || []).push(punkt);
      return { l, text: `„${punkt.text}“ ist jetzt Unterseite von „${zielPunkt.text}“.` };
    }
    if (ziel.art === "ende") { l.push(punkt); return { l, text: `„${punkt.text}“ steht jetzt im Menü.` }; }
    // vor/nach: Position des Zielpunkts NACH dem Herausnehmen suchen (Objekt bleibt gleich).
    const oben = l.indexOf(zielPunkt);
    if (oben >= 0) {
      l.splice(oben + (ziel.art === "nach" ? 1 : 0), 0, punkt);
      return { l, text: `„${punkt.text}“ verschoben.` };
    }
    const eltern = l.find((p) => (p.unter || []).includes(zielPunkt));
    if (!eltern) return null;
    if (punkt.unter) { toast("Eine Seite mit Unterseiten kann selbst keine Unterseite werden (das Menü hat nur eine Unterebene).", { fehler: true }); return null; }
    eltern.unter.splice(eltern.unter.indexOf(zielPunkt) + (ziel.art === "nach" ? 1 : 0), 0, punkt);
    return { l, text: `„${punkt.text}“ ist jetzt Unterseite von „${eltern.text}“.` };
  }
  function ausDemMenue(weg) {
    const l = kopie();
    const p = holen(l, weg);
    if (p.unter && p.unter.length) { toast("Erst die Unterseiten woanders hinziehen, dann lässt sich diese Seite aus dem Menü nehmen.", { fehler: true }); return; }
    herausnehmen(l, weg);
    menueSpeichern(l, `„${p.text}“ steht nicht mehr im Menü (die Seite selbst bleibt).`);
  }
  async function blogSortieren(quellPfad, zielPfad, art) {
    const reihe = blog.map((s) => s.pfad).filter((p) => p !== quellPfad);
    const i = reihe.indexOf(zielPfad);
    reihe.splice(i + (art === "nach" ? 1 : 0), 0, quellPfad);
    if (reihe.join() === blog.map((s) => s.pfad).join()) return;
    try { await api("/webspace/blog-reihenfolge", { methode: "POST", daten: { pfade: reihe } }); await neuLaden(); toast("Reihenfolge der Artikel geändert. Online erst nach dem Veröffentlichen."); }
    catch (e) { fehlerMelden(e); }
  }

  // ------------------------------------------------ Ziehen
  function runter(e, quelle, text) {
    if (e.button !== 0) return;
    e.preventDefault();
    start.current = { quelle, text, x: e.clientX, y: e.clientY };
    addEventListener("pointermove", bewegen);
    addEventListener("pointerup", hoch);
    addEventListener("pointercancel", abbruch);
  }
  function loesen() {
    removeEventListener("pointermove", bewegen);
    removeEventListener("pointerup", hoch);
    removeEventListener("pointercancel", abbruch);
  }
  function abbruch() { loesen(); start.current = null; zugRef.current = null; setZug(null); }
  function zielBestimmen(x, y, quelle) {
    const el = document.elementFromPoint(x, y);
    const zeile = el && el.closest && el.closest("[data-wsz]");
    const gruppe = el && el.closest && el.closest("[data-wsg]");
    if (quelle.art === "blog") {
      if (!zeile || zeile.dataset.art !== "blog" || zeile.dataset.pfad === quelle.pfad) return null;
      const r = zeile.getBoundingClientRect();
      return { art: y < r.top + r.height / 2 ? "vor" : "nach", pfad: zeile.dataset.pfad };
    }
    if (zeile && zeile.dataset.art === "menue") {
      const weg = JSON.parse(zeile.dataset.weg);
      if (quelle.art === "menue" && JSON.stringify(weg) === JSON.stringify(quelle.weg)) return null;
      // Nicht in die eigenen Unterseiten ziehen.
      if (quelle.art === "menue" && quelle.weg.length === 1 && weg.length === 2 && weg[0] === quelle.weg[0]) return null;
      const r = zeile.getBoundingClientRect();
      const rel = (y - r.top) / r.height;
      // Mitte = Unterseite (nur unter Hauptseiten), Ränder = davor/danach.
      if (weg.length === 1 && rel > 0.28 && rel < 0.72) return { art: "in", weg };
      return { art: rel < 0.5 ? "vor" : "nach", weg };
    }
    if (gruppe && gruppe.dataset.wsg === "frei" && quelle.art === "menue") return { art: "frei" };
    if (gruppe && gruppe.dataset.wsg === "menue" && quelle.art === "frei") return { art: "ende" };
    return null;
  }
  function bewegen(e) {
    const s = start.current;
    if (!s) return;
    if (!zugRef.current && Math.abs(e.clientY - s.y) < 6 && Math.abs(e.clientX - s.x) < 6) return;
    const ziel = zielBestimmen(e.clientX, e.clientY, s.quelle);
    zugRef.current = { quelle: s.quelle, text: s.text, ziel, x: e.clientX, y: e.clientY };
    setZug(zugRef.current);
    // Am Rand der Liste mitscrollen.
    const r = liste.current && liste.current.getBoundingClientRect();
    if (r) { if (e.clientY < r.top + 40) liste.current.scrollTop -= 14; else if (e.clientY > r.bottom - 40) liste.current.scrollTop += 14; }
  }
  function hoch() {
    loesen();
    const z = zugRef.current;
    start.current = null; zugRef.current = null; setZug(null);
    if (!z) return;
    gezogen.current = true;
    setTimeout(() => { gezogen.current = false; }, 0);
    if (!z.ziel) return;
    if (z.quelle.art === "blog") { blogSortieren(z.quelle.pfad, z.ziel.pfad, z.ziel.art); return; }
    if (z.ziel.art === "frei") { ausDemMenue(z.quelle.weg); return; }
    const r = einsortieren(z.quelle, z.ziel);
    if (r) menueSpeichern(r.l, r.text);
  }
  useEffect(() => () => loesen(), []);
  useEffect(() => { if (!zug) return; const k = (e) => { if (e.key === "Escape") abbruch(); }; addEventListener("keydown", k); return () => removeEventListener("keydown", k); }, [!!zug]);

  // ------------------------------------------------ Aktionen im "…"-Menü
  async function aktion(a, s, weg) {
    setMenue(null);
    try {
      if (a === "kopie") { const r = await api("/webspace/duplizieren", { methode: "POST", daten: { pfad: s.pfad } }); toast(`Kopie angelegt: ${r.adresse}`); await neuLaden(); waehlen(r.pfad); }
      if (a === "weg") { await api("/webspace/loeschen", { methode: "POST", daten: { pfad: s.pfad } }); toast(`„${s.titel}“ gelöscht. Online weg ist sie erst nach dem Veröffentlichen.`); await neuLaden(); if (s.pfad === pfad) waehlen("index.html"); }
      if (a === "live") window.open(stand.live + s.adresse, "_blank", "noopener");
      if (a === "hoch" || a === "runter") {
        const geschw = weg.length === 1 ? nav : nav[weg[0]].unter;
        const i = weg[weg.length - 1] + (a === "hoch" ? -1 : 1);
        if (i < 0 || i >= geschw.length) return;
        const r = einsortieren({ art: "menue", weg }, { art: a === "hoch" ? "vor" : "nach", weg: weg.length === 1 ? [i] : [weg[0], i] });
        if (r) menueSpeichern(r.l, r.text);
      }
      if (a === "unter") { const r = einsortieren({ art: "menue", weg }, { art: "in", weg: [weg[0] - 1] }); if (r) menueSpeichern(r.l, r.text); }
      if (a === "oben") { const r = einsortieren({ art: "menue", weg }, { art: "nach", weg: [weg[0]] }); if (r) menueSpeichern(r.l, r.text); }
      if (a === "ausmenue") ausDemMenue(weg);
      if (a === "insmenue") { const r = einsortieren({ art: "frei", adresse: s.adresse }, { art: "ende" }); if (r) menueSpeichern(r.l, r.text); }
    } catch (e) { fehlerMelden(e); }
  }
  async function textSetzen(weg, text) {
    setUmbenennen(null);
    const l = kopie();
    const p = holen(l, weg);
    if (!text.trim() || text.trim() === p.text) return;
    p.text = text.trim().slice(0, 60);
    menueSpeichern(l, `Menütext geändert: „${p.text}“.`);
  }

  // ------------------------------------------------ Zeilen
  const zielKlasse = (art, schluessel) => {
    if (!zug || !zug.ziel) return "";
    const z = zug.ziel;
    if (art === "blog") return z.pfad === schluessel ? " ziel-" + z.art : "";
    return z.weg && JSON.stringify(z.weg) === schluessel ? " ziel-" + z.art : "";
  };
  const zeile = ({ art, s, punkt, weg, schluessel }) => {
    const titel = punkt ? punkt.text : s ? s.titel : "?";
    const adr = s ? s.adresse : punkt && punkt.href;
    const gezogenHier = zug && ((art === "menue" && zug.quelle.art === "menue" && JSON.stringify(zug.quelle.weg) === schluessel)
      || (art === "frei" && zug.quelle.adresse === adr) || (art === "blog" && zug.quelle.pfad === schluessel));
    const quelle = art === "menue" ? { art, weg } : art === "frei" ? { art, adresse: adr } : { art, pfad: s.pfad };
    const geschw = art === "menue" ? (weg.length === 1 ? nav : nav[weg[0]].unter) : null;
    return html`<div class=${"ws2-zeile" + (s && s.pfad === pfad ? " an" : "") + (weg && weg.length === 2 ? " kind" : "") + (gezogenHier ? " zieht" : "") + zielKlasse(art, schluessel)}
        key=${art + schluessel} data-wsz="1" data-art=${art} data-weg=${weg ? JSON.stringify(weg) : undefined} data-pfad=${s ? s.pfad : undefined}>
      <span class="ws2-griff" title="Ziehen zum Verschieben" onPointerDown=${(e) => runter(e, quelle, titel)}>⠿</span>
      ${umbenennen === schluessel ? html`<input class="eingabe ws2-umbenennen" autofocus value=${titel}
          onKeyDown=${(e) => { if (e.key === "Enter") textSetzen(weg, e.target.value); if (e.key === "Escape") { e.stopPropagation(); setUmbenennen(null); } }}
          onBlur=${(e) => textSetzen(weg, e.target.value)} />`
        : html`<button class="ws2-zeile-haupt" onClick=${() => { if (!gezogen.current && s) waehlen(s.pfad); }} title=${s ? s.titel + " · " + s.adresse : adr}>
        <span class="ws2-zeile-titel">${titel}</span><span class="ws2-zeile-adr">${s ? s.adresse : adr + " (keine eigene Seite)"}</span></button>`}
      ${s && s.geaendert && html`<span class="ws-punkt" title="Geändert, noch nicht veröffentlicht"></span>`}
      <button class="btn geist icon klein ws2-mehr" title="Weitere Aktionen" aria-label="Weitere Aktionen" onClick=${() => setMenue(menue === art + schluessel ? null : art + schluessel)}><${Icon} n="mehr" g=${15} /></button>
      ${menue === art + schluessel && html`<div class="ws2-menue" role="menu">
        ${art === "menue" && html`
          ${weg[weg.length - 1] > 0 && html`<button onClick=${() => aktion("hoch", s, weg)}>↑ Nach oben</button>`}
          ${weg[weg.length - 1] < geschw.length - 1 && html`<button onClick=${() => aktion("runter", s, weg)}>↓ Nach unten</button>`}
          ${weg.length === 1 && weg[0] > 0 && !punkt.unter && html`<button onClick=${() => aktion("unter", s, weg)}>→ Unterseite von „${nav[weg[0] - 1].text}“</button>`}
          ${weg.length === 2 && html`<button onClick=${() => aktion("oben", s, weg)}>← Auf die oberste Ebene</button>`}
          <button onClick=${() => { setMenue(null); setUmbenennen(schluessel); }}><${Icon} n="stift" g=${14} />Menütext ändern</button>
          ${adr !== "/" && html`<button onClick=${() => aktion("ausmenue", s, weg)}>Aus dem Menü nehmen</button>`}`}
        ${art === "frei" && html`<button onClick=${() => aktion("insmenue", s)}><${Icon} n="plus" g=${14} />Ins Menü aufnehmen</button>`}
        ${s && html`<button onClick=${() => aktion("live", s)}><${Icon} n="extern" g=${14} />Online ansehen</button>
          <button onClick=${() => aktion("kopie", s)}><${Icon} n="kopie" g=${14} />Duplizieren</button>
          ${s.pfad !== "index.html" && html`<${Bestaetigen} text="Seite löschen" frage=${`„${s.titel}“ löschen?`} tun=${() => aktion("weg", s)} />`}`}
      </div>`}
    </div>`;
  };

  const menueZeilen = [];
  nav.forEach((p, i) => {
    const s = seiteVon(p.href);
    const kinder = (p.unter || []).map((u, j) => ({ u, j })).filter(({ u }) => passt(u.text, u.href));
    if (passt(p.text, p.href) || kinder.length) menueZeilen.push(zeile({ art: "menue", s, punkt: p, weg: [i], schluessel: JSON.stringify([i]) }));
    kinder.forEach(({ u, j }) => menueZeilen.push(zeile({ art: "menue", s: seiteVon(u.href), punkt: u, weg: [i, j], schluessel: JSON.stringify([i, j]) })));
  });
  const freiZeilen = frei.filter((s) => passt(s.titel, s.adresse)).map((s) => zeile({ art: "frei", s, schluessel: s.adresse }));
  const blogZeilen = blog.filter((s) => passt(s.titel, s.adresse)).map((s) => zeile({ art: "blog", s, schluessel: s.pfad }));
  const freiZiel = zug && zug.ziel && zug.ziel.art === "frei";
  const endeZiel = zug && zug.ziel && zug.ziel.art === "ende";
  return html`<div class=${"ws2-seiten" + (zug ? " zieht" : "")}>
    <div class="ws2-neu-reihe">
      <button class="btn primaer" onClick=${() => neu("seite")} title="Neue Seite anlegen (mit Platz im Menü)"><${Icon} n="plus" g=${15} />Neue Seite</button>
      <button class="btn primaer" onClick=${() => neu("blog")} title="Neuen Beitrag im Blog „Inspiration“ anlegen"><${Icon} n="plus" g=${15} />Blogbeitrag</button>
    </div>
    <input class="eingabe ws2-suche" placeholder="Seite suchen …" value=${suche} onInput=${(e) => setSuche(e.target.value)} />
    <div class="ws2-liste" ref=${liste}>
      <div class=${"ws2-gruppe-box" + (endeZiel ? " ziel" : "")} data-wsg="menue">
        <div class="ws-gruppe" title="Reihenfolge und Verschachtelung wie im Menü der Website">Im Menü <span class="ws2-tipp">⠿ ziehen: Kante = davor/danach, Mitte = Unterseite</span></div>
        ${menueZeilen}
      </div>
      <div class=${"ws2-gruppe-box" + (freiZiel ? " ziel" : "")} data-wsg="frei">
        <div class="ws-gruppe">Nicht im Menü</div>
        ${freiZeilen.length ? freiZeilen : html`<div class="ws2-leer">${zug && zug.quelle.art === "menue" ? "Hierher ziehen, um eine Seite aus dem Menü zu nehmen" : "Alle Seiten stehen im Menü."}</div>`}
      </div>
      <div class="ws2-gruppe-box" data-wsg="blog">
        <div class="ws-gruppe" title="Reihenfolge in der Übersicht „Inspiration“">Blog „Inspiration“ <span class="ws2-tipp">neueste oben</span><button class="ws2-gruppe-plus" title="Neuer Blogbeitrag" onClick=${() => neu("blog")}>＋ Beitrag</button></div>
        ${blogZeilen}
      </div>
      ${q && !menueZeilen.length && !freiZeilen.length && !blogZeilen.length && html`<p class="leise klein" style="padding:8px">Nichts gefunden.</p>`}
    </div>
    ${zug && html`<div class="ws2-geist" style=${`left:${zug.x + 14}px;top:${zug.y + 8}px`}>⠿ ${zug.text}
      <span>${!zug.ziel ? "" : zug.ziel.art === "in" ? "→ als Unterseite" : zug.ziel.art === "frei" ? "aus dem Menü nehmen" : zug.ziel.art === "ende" ? "ins Menü aufnehmen" : zug.ziel.art === "vor" ? "↑ davor" : "↓ danach"}</span></div>`}
  </div>`;
}

// Menütexte sind kurz; aus „Veiko von Eckern – Künstliche Intelligenz …“ wird „Veiko von Eckern“.
function kurzTitel(t) { return String(t || "").split(/\s[–|-]\s/)[0].slice(0, 40); }

function Bestaetigen({ text, frage, tun, ja = "Löschen" }) {
  const [auf, setAuf] = useState(false);
  if (auf) return html`<div class="ws2-frage"><span>${frage}</span><span class="knopfreihe">
    <button class="btn klein gefahr voll" onClick=${() => { setAuf(false); tun(); }}>${ja}</button>
    <button class="btn klein geist" onClick=${() => setAuf(false)}>Abbrechen</button></span></div>`;
  return html`<button class="gefahr" onClick=${() => setAuf(true)}><${Icon} n="x" g=${14} />${text}</button>`;
}

function OnlineStand({ stand }) {
  const v = stand.veroeffentlichung;
  let lage = html`<span class="leise">Stand unbekannt</span>`;
  if (v) {
    if (v.stand !== "completed") lage = html`<span class="ws-lage gelb">● GitHub veröffentlicht gerade …</span>`;
    else if (v.ergebnis === "success") lage = html`<span class="ws-lage gruen">● Online · ${zeitText(Date.parse(v.zeit) / 1000)}</span>`;
    else lage = html`<span class="ws-lage rot">● Letzte Veröffentlichung gescheitert · <a href=${v.url} target="_blank" rel="noopener">Ansehen</a></span>`;
  }
  return html`<div class="ws2-online">${lage}<a href=${stand.live} target="_blank" rel="noopener" class="ws-live"><${Icon} n="extern" g=${13} />${stand.live.replace("https://", "")}</a></div>`;
}

// ---------------------------------------------------------------- Medien
function MedienVerwaltung() {
  const [liste, setListe] = useState(null);
  const [laedt, setLaedt] = useState(false);
  const [suche, setSuche] = useState("");
  const [ziel, setZiel] = useState(false);
  const feld = useRef(null);
  const laden = () => api("/webspace/medien").then((d) => setListe(d.medien)).catch(fehlerMelden);
  useEffect(() => { laden(); }, []);
  async function hoch(dateien) {
    if (!dateien.length) return;
    setLaedt(true);
    try {
      for (const f of dateien) {
        const fd = new FormData(); fd.append("datei", f, f.name);
        const r = await fetch("/api/webspace/bild", { method: "POST", body: fd, credentials: "same-origin" });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "Hochladen gescheitert");
      }
      toast(dateien.length === 1 ? "Bild hochgeladen." : `${dateien.length} Bilder hochgeladen.`);
      laden();
    } catch (x) { fehlerMelden(x); }
    setLaedt(false);
  }
  async function weg(m) {
    try { await api("/webspace/medien/loeschen", { methode: "POST", daten: { pfad: m.pfad } }); toast("Gelöscht."); laden(); }
    catch (e) { fehlerMelden(e); }
  }
  const q = suche.trim().toLowerCase();
  const sichtbar = (liste || []).filter((m) => !q || m.pfad.includes(q));
  const mb = (b) => b > 1048576 ? (b / 1048576).toFixed(1) + " MB" : Math.round(b / 1024) + " KB";
  return html`<div class=${"ws2-medien" + (ziel ? " ziel" : "")} onDragOver=${(e) => { e.preventDefault(); setZiel(true); }} onDragLeave=${() => setZiel(false)}
    onDrop=${(e) => { e.preventDefault(); setZiel(false); hoch([...e.dataTransfer.files].filter((f) => /^(image|video)\//.test(f.type))); }}>
    <button class="btn primaer ws2-neu" disabled=${laedt} onClick=${() => feld.current.click()}><${Icon} n="plus" g=${15} />${laedt ? "Lädt hoch …" : "Bilder hochladen"}</button>
    <input ref=${feld} type="file" accept="image/*,video/mp4" multiple hidden onChange=${(e) => { const d = [...e.target.files]; e.target.value = ""; hoch(d); }} />
    <p class="leise klein">Oder Bilder hierher ziehen. Im Editor kannst du Bilder auch einfach in die Seite ziehen oder einfügen (Strg+V).</p>
    <input class="eingabe ws2-suche" placeholder="Suchen …" value=${suche} onInput=${(e) => setSuche(e.target.value)} />
    ${!liste ? html`<p class="leise">Lädt …</p>` : html`<div class="ws2-medienraster">${sichtbar.map((m) => html`<div class="ws2-medium" title=${m.pfad}>
      ${m.video ? html`<div class="ws2-video">▶ Video</div>` : html`<img src=${BASIS + m.pfad} alt="" loading="lazy" />`}
      <div class="ws2-medium-text"><span>${m.pfad.slice(8)}</span><span class="leise">${mb(m.groesse)} · ${m.nutzung ? `${m.nutzung}× verwendet` : "unbenutzt"}</span></div>
      ${!m.nutzung && html`<button class="btn geist icon klein ws2-medium-weg" title="Löschen (wird nirgends verwendet)" onClick=${() => weg(m)}><${Icon} n="x" g=${13} /></button>`}
    </div>`)}</div>`}
  </div>`;
}

// ---------------------------------------------------------------- Suchen und Ersetzen
function SuchenErsetzen({ oeffnen, vorher, fertig }) {
  const [q, setQ] = useState("");
  const [ersatz, setErsatz] = useState("");
  const [treffer, setTreffer] = useState(null);
  const [frage, setFrage] = useState(false);
  useEffect(() => {
    if (q.trim().length < 2) { setTreffer(null); return; }
    const t = setTimeout(async () => { await vorher(); api("/webspace/suchen?q=" + encodeURIComponent(q.trim())).then((d) => setTreffer(d.treffer)).catch(fehlerMelden); }, 300);
    return () => clearTimeout(t);
  }, [q]);
  const summe = (treffer || []).reduce((a, t) => a + t.anzahl, 0);
  async function ersetzen() {
    setFrage(false);
    try { await vorher(); const r = await api("/webspace/ersetzen", { methode: "POST", daten: { suche: q.trim(), ersatz } }); toast(`${r.ersetzt}× ersetzt (noch nicht veröffentlicht).`); setQ(""); setTreffer(null); fertig(); }
    catch (e) { fehlerMelden(e); }
  }
  return html`<div class="ws2-suchen">
    <div class="feld"><label>Suchen auf allen Seiten</label><input class="eingabe" autofocus value=${q} onInput=${(e) => setQ(e.target.value)} placeholder="Wort oder Satz …" /></div>
    <div class="feld"><label>Ersetzen durch (optional)</label><input class="eingabe" value=${ersatz} onInput=${(e) => setErsatz(e.target.value)} placeholder="neuer Text" /></div>
    ${treffer && html`<p class="klein">${summe ? `${summe} Treffer auf ${treffer.length} Seite${treffer.length === 1 ? "" : "n"}` : "Nichts gefunden."} <span class="leise">(nur im sichtbaren Text, Groß-/Kleinschreibung zählt)</span></p>`}
    ${treffer && summe > 0 && (frage
      ? html`<div class="ws2-frage"><span>Alle ${summe} Stellen ersetzen?</span><span class="knopfreihe">
          <button class="btn klein primaer" onClick=${ersetzen}>Ja, ersetzen</button><button class="btn klein geist" onClick=${() => setFrage(false)}>Abbrechen</button></span></div>`
      : html`<button class="btn klein" onClick=${() => setFrage(true)}>Alle ersetzen</button>`)}
    <div class="ws2-treffer">${(treffer || []).map((t) => html`<button onClick=${() => oeffnen(t.pfad)}><b>${t.titel}</b><span class="leise klein">${t.anzahl}× · ${t.ausschnitt}</span></button>`)}</div>
  </div>`;
}

// ---------------------------------------------------------------- Veröffentlichen
function VeroeffentlichenDialog({ stand, zu, oeffnen, fertig, verworfen }) {
  const [daten, setDaten] = useState(null);
  const [warn, setWarn] = useState(null);
  const [offen, setOffen] = useState(null);
  const [nachricht, setNachricht] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const [verwerfenFrage, setVerwerfenFrage] = useState(false);
  // Hat die Prüfung durch Externe etwas im Text korrigiert, muss der Editor danach
  // frisch laden -- sonst schriebe sein nächstes automatisches Speichern den alten Text zurück.
  const [korrigiert, setKorrigiert] = useState(false);
  const holen = () => {
    api("/webspace/vergleich").then(setDaten).catch(fehlerMelden);
    api("/webspace/pruefen").then((d) => setWarn(d.warnungen)).catch(() => setWarn([]));
  };
  useEffect(holen, []);
  const schliessen = () => (korrigiert ? verworfen() : zu());
  const aend = daten ? daten.aenderungen : [];
  const fehlerAnzahl = (warn || []).filter((w) => w.stufe === "fehler").length;
  async function los() {
    setLaeuft(true);
    try {
      const r = await api("/webspace/veroeffentlichen", { methode: "POST", daten: { bestaetigt: true, nachricht } });
      toast(r.nichts ? "Es gab nichts zu veröffentlichen." : "Veröffentlicht. In etwa einer Minute ist es auf veikovoneckern.org zu sehen.");
      if (korrigiert) verworfen(); else fertig();
    } catch (e) { fehlerMelden(e); setLaeuft(false); }
  }
  async function allesVerwerfen() {
    try { await api("/webspace/verwerfen", { methode: "POST", daten: {} }); toast("Alle Änderungen seit der letzten Veröffentlichung verworfen."); verworfen(); }
    catch (e) { fehlerMelden(e); }
  }
  const titelVon = (a) => (a.neu && a.neu.kopf && a.neu.kopf.titel) || (a.alt && a.alt.kopf && a.alt.kopf.titel) || a.datei;
  return html`<${Modal} titel="Veröffentlichen" zu=${schliessen} breit=${true}
    fuss=${aend.length ? html`${verwerfenFrage
        ? html`<span class="klein">Wirklich alles verwerfen?</span><button class="btn gefahr voll klein" onClick=${allesVerwerfen}>Ja, verwerfen</button><button class="btn geist klein" onClick=${() => setVerwerfenFrage(false)}>Nein</button>`
        : html`<button class="btn geist" onClick=${() => setVerwerfenFrage(true)}>Alles verwerfen</button>`}
      <span class="luecke"></span><button class="btn geist" onClick=${schliessen}>Abbrechen</button>
      <button class="btn primaer" disabled=${laeuft || !daten} onClick=${los}><${Icon} n="globus" g=${15} />${laeuft ? "Wird veröffentlicht …" : fehlerAnzahl ? "Trotzdem veröffentlichen" : "Jetzt veröffentlichen"}</button>`
      : html`<span class="luecke"></span><button class="btn" onClick=${schliessen}>Schließen</button>`}>
    ${!daten ? html`<p class="leise">Änderungen werden zusammengestellt …</p>` : !aend.length ? html`<p>Alles ist veröffentlicht. Es gibt nichts Neues.</p>` : html`
      <p class="leise">Danach ist es für alle auf <b>veikovoneckern.org</b> zu sehen (etwa eine Minute später). Jede Veröffentlichung lässt sich später im Verlauf der Seite zurückholen.</p>
      ${warn && warn.length > 0 && html`<div class=${"wpd-warn" + (fehlerAnzahl ? " rot" : "")}>
        <b>${fehlerAnzahl ? `${fehlerAnzahl} Problem${fehlerAnzahl === 1 ? "" : "e"} vor dem Veröffentlichen` : "Hinweise"}</b>
        <ul>${warn.map((w) => html`<li class=${w.stufe}><span>${w.stufe === "fehler" ? "✖" : "ⓘ"}</span>${w.text}
          ${w.pfad.endsWith(".html") && html` <button class="btn klein geist" onClick=${() => oeffnen(w.pfad)}>Seite öffnen</button>`}</li>`)}</ul></div>`}
      ${warn && !warn.length && html`<div class="wpd-ok">✓ Keine Probleme gefunden: alle Links führen zu vorhandenen Seiten, Bilder sind beschrieben.</div>`}
      <div class="wpd-liste">${aend.map((a, i) => html`<div class="wpd-seite">
        <button class="wpd-kopf" onClick=${() => setOffen(offen === i ? null : i)}>
          <span class=${"ws-art " + a.art}>${a.art}</span><b>${a.pfad ? titelVon(a) : a.datei}</b><span class="leise klein">${a.pfad ? "/" + a.pfad.replace(/(index)?\.html$/, "") : a.datei}</span>
          ${a.pfad && html`<span class="wpd-auf">${offen === i ? "▾" : "▸"} Änderungen</span>`}</button>
        ${offen === i && a.pfad && html`<${Unterschied} a=${a} />`}
      </div>`)}</div>
      <${ExternePruefung} oeffnen=${oeffnen} titelVon=${(p) => { const a = aend.find((x) => x.pfad === p); return a ? titelVon(a) : p; }}
        korrigiert=${() => { setKorrigiert(true); holen(); }} />
      <div class="feld"><label>Was hast du geändert? (optional, steht dann im Verlauf)</label>
        <input class="eingabe" value=${nachricht} onInput=${(e) => setNachricht(e.target.value)} placeholder="z. B. Neuer Artikel über Davos" /></div>`}
  <//>`;
}

// ---------------------------------------------------------------- Prüfung durch Externe
// Veiko: "die externen in meinem Setup auch vor Veröffentlichung prüfen lassen".
// Der Assistent im Editor rechnet weiter lokal; hier gehen die GEÄNDERTEN Seiten
// als lesbarer Text an Dario, Elon und/oder Demmis. Das kostet Geld, deshalb
// zwei Schritte: erst auswählen (mit geschätztem Preis), dann ausdrücklich erlauben.
// Ein Vorschlag wird nur übernommen, wenn die genannte Stelle wörtlich im Text steht --
// geraten wird nichts.
function ExternePruefung({ oeffnen, titelVon, korrigiert }) {
  const [liste, setListe] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [wahl, setWahl] = useState([]);
  const [frage, setFrage] = useState(false);
  const [laeuft, setLaeuft] = useState(0);
  const [ergebnisse, setErgebnisse] = useState(null);
  const [erledigt, setErledigt] = useState({});
  useEffect(() => {
    api("/webspace/externe").then((d) => {
      setListe(d);
      const da = d.externe.filter((x) => x.schluessel !== false);
      setWahl(da.length ? [da[0].id] : []);
    }).catch((e) => setFehler(e.message));
  }, []);
  useEffect(() => {
    if (!laeuft) return;
    const t = setInterval(() => setLaeuft((s) => (s ? s + 1 : 0)), 1000);
    return () => clearInterval(t);
  }, [laeuft > 0]);
  if (fehler) return html`<div class="wpx"><b>Von Externen prüfen lassen</b><p class="leise klein">Nicht verfügbar: ${fehler}</p></div>`;
  if (!liste) return html`<div class="wpx"><b>Von Externen prüfen lassen</b><p class="leise klein">Lädt …</p></div>`;
  if (!liste.seiten.length) return null;
  const gewaehlt = liste.externe.filter((x) => wahl.includes(x.id));
  const summe = gewaehlt.reduce((a, x) => a + (x.kosten || 0), 0);
  const usd = (v) => "$" + (v < 0.01 ? "<0,01" : v.toFixed(2).replace(".", ","));
  const umschalten = (id) => setWahl((w) => (w.includes(id) ? w.filter((x) => x !== id) : [...w, id]));
  async function pruefen() {
    setFrage(false); setLaeuft(1); setErgebnisse(null); setErledigt({});
    try {
      const r = await api("/webspace/extern-pruefen", { methode: "POST", daten: { wer: wahl, freigabe: true } });
      setErgebnisse(r.ergebnisse);
    } catch (e) { fehlerMelden(e); }
    setLaeuft(0);
  }
  async function uebernehmen(schl, p) {
    try {
      await api("/webspace/stelle-ersetzen", { methode: "POST", daten: { pfad: p.seite, alt: p.stelle, neu: p.vorschlag } });
      setErledigt((e) => ({ ...e, [schl]: "ok" }));
      toast("Übernommen (noch nicht veröffentlicht).");
      korrigiert();
    } catch (e) { setErledigt((x) => ({ ...x, [schl]: e.message })); }
  }
  const n = liste.seiten.length;
  return html`<div class="wpx">
    <div class="wpx-kopf"><b>Von Externen prüfen lassen</b><span class="leise klein">${n} geänderte Seite${n === 1 ? "" : "n"} · ca. ${Math.round(liste.zeichen / 1000)} Tsd. Zeichen</span></div>
    <p class="leise klein">Der KI-Assistent im Editor rechnet auf deinem eigenen Server. Hier kannst du die Änderungen zusätzlich von einem Cloud-Modell gegenlesen lassen: Rechtschreibung, Ton, Verständlichkeit, Fakten, Google-Beschreibung. Die Kosten werden unter „Verbrauch“ gebucht.</p>
    <div class="wpx-wahl">${liste.externe.map((x) => html`<label class=${"wpx-person" + (x.schluessel === false ? " aus" : "")} title=${x.schluessel === false ? "Kein Schlüssel hinterlegt" : x.modell}>
      <input type="checkbox" disabled=${x.schluessel === false || laeuft} checked=${wahl.includes(x.id)} onChange=${() => umschalten(x.id)} />
      <span><b>${x.name}</b> <span class="leise klein">${x.titel}</span><br /><span class="leise klein">${x.schluessel === false ? "kein Schlüssel hinterlegt" : `${x.modell} · ca. ${usd(x.kosten)}`}</span></span></label>`)}</div>
    ${laeuft ? html`<div class="wpx-laeuft"><div class="wpx-balken"><i></i></div><span class="klein">${gewaehlt.map((x) => x.name).join(", ")} ${gewaehlt.length === 1 ? "liest" : "lesen"} gegen … ${laeuft} s</span></div>`
      : frage ? html`<div class="ws2-frage"><span>Das schickt ${n} Seite${n === 1 ? "" : "n"} an ${gewaehlt.map((x) => x.name).join(" und ")} und kostet etwa <b>${usd(summe)}</b>. Erlauben?</span>
          <span class="knopfreihe"><button class="btn klein primaer" onClick=${pruefen}>Erlauben und prüfen lassen</button><button class="btn klein geist" onClick=${() => setFrage(false)}>Abbrechen</button></span></div>`
      : html`<button class="btn klein" disabled=${!wahl.length} onClick=${() => setFrage(true)}><${Icon} n="check" g=${14} />${ergebnisse ? "Noch einmal prüfen lassen" : "Prüfen lassen"}${wahl.length ? ` (ca. ${usd(summe)})` : ""}</button>`}
    ${(ergebnisse || []).map((e) => html`<div class=${"wpx-erg" + (e.fehler ? " fehler" : e.urteil === "veroeffentlichen" ? " gut" : " nach")}>
      <div class="wpx-erg-kopf"><b>${e.name}</b><span class="leise klein">${e.modell}</span>
        <span class="wpx-urteil">${e.fehler ? "Fehler" : e.urteil === "veroeffentlichen" ? "✓ kann raus" : "⚠ nachbessern"}</span></div>
      ${e.fehler ? html`<p class="klein">${e.fehler}</p>` : html`
        ${e.zusammenfassung && html`<p class="klein">${e.zusammenfassung}</p>`}
        ${!e.punkte.length && html`<p class="leise klein">Keine Einzelpunkte.</p>`}
        <ul class="wpx-punkte">${e.punkte.map((p, i) => {
          const schl = e.wer + ":" + i, st = erledigt[schl];
          return html`<li class=${p.gewicht}>
            <div class="wpx-p-kopf"><span class=${"wpx-gewicht " + p.gewicht}>${p.gewicht}</span>${p.art && html`<span class="leise klein">${p.art}</span>`}
              <span class="leise klein">· ${titelVon(p.seite)}</span></div>
            <div class="klein">${p.problem}</div>
            ${p.stelle && html`<div class="wpx-stelle klein"><del>${p.stelle}</del>${p.vorschlag && html` → <ins>${p.vorschlag}</ins>`}</div>`}
            ${!p.stelle && p.vorschlag && html`<div class="wpx-stelle klein"><ins>${p.vorschlag}</ins></div>`}
            <div class="knopfreihe">
              ${st === "ok" ? html`<span class="wpx-ok klein">✓ übernommen</span>`
                : p.uebernehmbar ? html`<button class="btn klein primaer" onClick=${() => uebernehmen(schl, p)}>Übernehmen</button>` : ""}
              ${st && st !== "ok" && html`<span class="wpx-nein klein">${st}</span>`}
              ${p.seite && p.seite.endsWith(".html") && html`<button class="btn klein geist" onClick=${() => oeffnen(p.seite)}>Seite öffnen</button>`}
            </div></li>`;
        })}</ul>`}
    </div>`)}
  </div>`;
}

function Unterschied({ a }) {
  const kopfAend = [];
  const ka = a.alt.kopf || {}, kn = a.neu.kopf || {};
  if ((ka.titel || "") !== (kn.titel || "")) kopfAend.push(["Titel", ka.titel, kn.titel]);
  if ((ka.beschreibung || "") !== (kn.beschreibung || "")) kopfAend.push(["Beschreibung", ka.beschreibung, kn.beschreibung]);
  if (JSON.stringify(ka.blog || null) !== JSON.stringify(kn.blog || null)) kopfAend.push(["Blog-Angaben", ka.blog ? "geändert" : "", kn.blog ? "neu" : ""]);
  const teile = vergleichen(absaetze(a.alt.inhalt || ""), absaetze(a.neu.inhalt || ""));
  // Unveränderte Absätze zusammenfassen, damit nur das Geänderte ins Auge fällt.
  const zeilen = [];
  let gleich = 0;
  teile.forEach((t, i) => {
    const naechsteAnders = teile.slice(i + 1, i + 2).some((x) => x.art !== "=");
    const vorigeAnders = i > 0 && teile[i - 1].art !== "=";
    if (t.art === "=" && !naechsteAnders && !vorigeAnders) { gleich++; return; }
    if (gleich) { zeilen.push(html`<div class="wpd-gleich">… ${gleich} unveränderte${gleich === 1 ? "r Absatz" : " Absätze"}</div>`); gleich = 0; }
    if (t.art === "=") zeilen.push(html`<div class="wpd-z">${t.text}</div>`);
    else if (t.art === "-") zeilen.push(html`<div class="wpd-z weg">${t.text}</div>`);
    else if (t.art === "+") zeilen.push(html`<div class="wpd-z dazu">${t.text}</div>`);
    else zeilen.push(html`<div class="wpd-z">${t.teile.map(([o, w]) => o === "=" ? w : html`<span class=${o === "-" ? "weg" : "dazu"}>${w}</span>`)}</div>`);
  });
  if (gleich) zeilen.push(html`<div class="wpd-gleich">… ${gleich} unveränderte${gleich === 1 ? "r Absatz" : " Absätze"}</div>`);
  const nurForm = !kopfAend.length && teile.every((t) => t.art === "=");
  return html`<div class="wpd-diff">
    ${kopfAend.map(([n, alt, neu]) => html`<div class="wpd-z"><b>${n}:</b> ${alt ? html`<span class="weg">${alt}</span> ` : ""}<span class="dazu">${neu || "(leer)"}</span></div>`)}
    ${nurForm ? html`<p class="leise klein">Der Text ist gleich geblieben — geändert haben sich Gestaltung, Bilder, Reihenfolge oder Einstellungen.</p>` : zeilen}
  </div>`;
}

// ---------------------------------------------------------------- Neue Seite oder Artikel
function NeueSeite({ vorgabe, stand, zu, fertig }) {
  const [art, setArt] = useState(vorgabe === "blog" ? "blog" : "seite");
  // Nur beim Blogbeitrag: Bild und Auszug für die Übersicht „Inspiration“ gleich hier,
  // statt sie danach unter „Eigenschaften“ suchen zu müssen.
  const [bild, setBild] = useState("");
  const [auszug, setAuszug] = useState("");
  const [bildWahl, setBildWahl] = useState(false);
  const [titel, setTitel] = useState("");
  const [menue, setMenue] = useState("");
  const [ordner, setOrdner] = useState("");
  const [entwurf, setEntwurf] = useState("");
  const [laeuft, setLaeuft] = useState("");
  const ordnerWahl = [["", "oberste Ebene (/name)"], ...stand.menue.filter((m) => m.href.endsWith("/") && m.href !== "/").map((m) => [m.href.replace(/^\/|\/$/g, ""), `unter ${m.href} (${m.text})`])];
  async function los() {
    setLaeuft("Seite wird angelegt …");
    try {
      const r = await api("/webspace/neu", { methode: "POST", daten: { art, titel, bild: art === "blog" ? bild : undefined, auszug: art === "blog" ? auszug.trim() : undefined, ordner: art === "seite" ? ordner : undefined, menue: art === "seite" && menue !== "-" ? menue : null } });
      if (entwurf.trim()) {
        setLaeuft("Die KI schreibt den ersten Entwurf … (meist eine halbe bis eine Minute)");
        const s = await api("/webspace/seite?pfad=" + encodeURIComponent(r.pfad));
        const v = await api("/webspace/assistent", { methode: "POST", daten: { pfad: r.pfad, kopf: s.kopf, inhalt: s.inhalt,
          auftrag: `Das ist eine neue, noch leere ${art === "blog" ? "Blogartikel-Seite" : "Seite"} mit dem Titel „${titel}“. Schreibe ihren vollständigen Inhalt. Vorgaben von Veiko: ${entwurf}` } });
        await api("/webspace/seite", { methode: "POST", daten: { pfad: r.pfad, kopf: s.kopf, inhalt: v.inhalt } });
      }
      toast(`„${titel}“ angelegt (noch nicht veröffentlicht).`);
      fertig(r.pfad);
    } catch (e) { fehlerMelden(e); setLaeuft(""); }
  }
  return html`<${Modal} titel=${art === "blog" ? "Neuer Blogbeitrag" : "Neue Seite"} zu=${zu}
    fuss=${html`<span class="luecke"></span><button class="btn geist" onClick=${zu}>Abbrechen</button><button class="btn primaer" disabled=${!titel.trim() || !!laeuft} onClick=${los}>${laeuft ? "Einen Moment …" : "Anlegen"}</button>`}>
    <div class="ws2-artwahl">
      <button class=${art === "seite" ? "an" : ""} onClick=${() => setArt("seite")}><b>Seite</b><span class="leise klein">z. B. Vorträge, Über mich — mit Platz im Menü</span></button>
      <button class=${art === "blog" ? "an" : ""} onClick=${() => setArt("blog")}><b>Blogartikel</b><span class="leise klein">erscheint unter „Inspiration“, neueste oben</span></button>
    </div>
    <div class="feld"><label>Titel</label><input class="eingabe" autofocus value=${titel} onInput=${(e) => setTitel(e.target.value)} placeholder=${art === "blog" ? "z. B. Was Davos 2027 über KI sagt" : "z. B. Vorträge"} /></div>
    ${art === "seite" && html`<div class="ws2-zwei">
      <div class="feld"><label>Wo liegt die Seite?</label>
        <select class="eingabe" value=${ordner} onChange=${(e) => setOrdner(e.target.value)}>${ordnerWahl.map(([w, t]) => html`<option value=${w}>${t}</option>`)}</select></div>
      <div class="feld"><label>Im Menü</label>
        <select class="eingabe" value=${menue} onChange=${(e) => setMenue(e.target.value)}>
          <option value="">als eigener Punkt</option>
          ${stand.menue.filter((m) => m.href !== "/").map((m) => html`<option value=${m.href}>unter „${m.text}“</option>`)}
          <option value="-">nicht im Menü</option>
        </select></div></div>`}
    ${art === "blog" && html`<div class="ws2-blogneu">
      <button class="ws2-blogbild" onClick=${() => setBildWahl(true)} title="Bild für die Übersicht wählen">
        ${bild ? html`<img src=${BASIS + bild} alt="" />` : html`<span>＋ Titelbild<br /><span class="leise klein">optional</span></span>`}</button>
      <div class="feld"><label>Kurzer Auszug für die Übersicht (optional)</label>
        <${Textfeld} class="eingabe" rows="3" value=${auszug} onInput=${(e) => setAuszug(e.target.value)} placeholder="Ein, zwei Sätze, die unter dem Titel in der Liste stehen." /></div></div>`}
    <div class="feld"><label>✦ Ersten Entwurf von der KI schreiben lassen (optional)</label>
      <${Textfeld} class="eingabe" rows="4" value=${entwurf} onInput=${(e) => setEntwurf(e.target.value)}
        placeholder="Worum soll es gehen? Stichpunkte reichen. Leer lassen = leere Seite zum selbst Schreiben." /></div>
    ${laeuft && html`<p class="leise">${laeuft}</p>`}
    ${bildWahl && html`<${MedienWahl} zu=${() => setBildWahl(false)} waehlen=${(p) => { setBild(p); setBildWahl(false); }} />`}
  <//>`;
}
