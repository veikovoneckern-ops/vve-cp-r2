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

export function WebSpace({ pfad: pfadAusAdresse }) {
  const [stand, setStand] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [pfad, setPfad] = useState(pfadAusAdresse || "index.html");
  const [links, setLinks] = useState(() => { try { return localStorage.getItem("ws-links") || "seiten"; } catch (e) { return "seiten"; } });
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
        ${[["seiten", "Seiten"], ["menue", "Menü"], ["medien", "Medien"], ["suchen", "Suchen"]].map(([id, t]) => html`<button class=${links === id ? "an" : ""} onClick=${() => linksWaehlen(id)}>${t}</button>`)}
      </div>
      <div class="ws2-links-inhalt">
        ${links === "seiten" && html`<${SeitenListe} stand=${stand} pfad=${pfad} waehlen=${wechseln} neu=${() => setNeu(true)} neuLaden=${laden} />`}
        ${links === "menue" && html`<${MenueEditor} stand=${stand} gespeichert=${neuAufbauen} />`}
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
    ${neu && html`<${NeueSeite} stand=${stand} zu=${() => setNeu(false)} fertig=${async (p) => { setNeu(false); await laden(); wechseln(p); }} />`}
    ${pub && html`<${VeroeffentlichenDialog} stand=${stand} zu=${() => setPub(false)} oeffnen=${(p) => { setPub(false); wechseln(p); }}
      fertig=${async () => { setPub(false); await laden(); }} verworfen=${async () => { setPub(false); await neuAufbauen(); }} />`}
  </div>`;
}

// ---------------------------------------------------------------- Seiten
function SeitenListe({ stand, pfad, waehlen, neu, neuLaden }) {
  const [suche, setSuche] = useState("");
  const [menue, setMenue] = useState(null);
  const q = suche.trim().toLowerCase();
  const passt = (s) => !q || (s.titel + " " + s.adresse).toLowerCase().includes(q);
  const seiten = stand.seiten.filter((s) => !s.blog && passt(s)).sort((a, b) => a.adresse.localeCompare(b.adresse));
  const blog = stand.seiten.filter((s) => s.blog && passt(s)).sort((a, b) => (a.blog.reihe ?? 999) - (b.blog.reihe ?? 999));
  async function aktion(a, s) {
    setMenue(null);
    try {
      if (a === "kopie") { const r = await api("/webspace/duplizieren", { methode: "POST", daten: { pfad: s.pfad } }); toast(`Kopie angelegt: ${r.adresse}`); await neuLaden(); waehlen(r.pfad); }
      if (a === "weg") { await api("/webspace/loeschen", { methode: "POST", daten: { pfad: s.pfad } }); toast(`„${s.titel}“ gelöscht. Online weg ist sie erst nach dem Veröffentlichen.`); await neuLaden(); if (s.pfad === pfad) waehlen("index.html"); }
      if (a === "live") window.open(stand.live + s.adresse, "_blank", "noopener");
    } catch (e) { fehlerMelden(e); }
  }
  const zeile = (s) => html`<div class=${"ws2-zeile" + (s.pfad === pfad ? " an" : "")} key=${s.pfad}>
    <button class="ws2-zeile-haupt" onClick=${() => waehlen(s.pfad)} title=${s.adresse}>
      <span class="ws2-zeile-titel">${s.titel}</span>
      <span class="ws2-zeile-adr">${s.adresse}</span></button>
    ${s.geaendert && html`<span class="ws-punkt" title="Geändert, noch nicht veröffentlicht"></span>`}
    <button class="btn geist icon klein ws2-mehr" title="Weitere Aktionen" aria-label="Weitere Aktionen" onClick=${() => setMenue(menue === s.pfad ? null : s.pfad)}><${Icon} n="mehr" g=${15} /></button>
    ${menue === s.pfad && html`<div class="ws2-menue" role="menu">
      <button onClick=${() => aktion("live", s)}><${Icon} n="extern" g=${14} />Online ansehen</button>
      <button onClick=${() => aktion("kopie", s)}><${Icon} n="kopie" g=${14} />Duplizieren</button>
      ${s.pfad !== "index.html" && html`<${Bestaetigen} text="Löschen" frage=${`„${s.titel}“ löschen?`} tun=${() => aktion("weg", s)} />`}
    </div>`}
  </div>`;
  return html`<div class="ws2-seiten">
    <button class="btn primaer ws2-neu" onClick=${neu}><${Icon} n="plus" g=${15} />Neue Seite oder Artikel</button>
    <input class="eingabe ws2-suche" placeholder="Seite suchen …" value=${suche} onInput=${(e) => setSuche(e.target.value)} />
    <div class="ws2-liste">
      <div class="ws-gruppe">Seiten</div>${seiten.map(zeile)}
      <div class="ws-gruppe">Blog „Inspiration“</div>${blog.map(zeile)}
      ${!seiten.length && !blog.length && html`<p class="leise klein" style="padding:8px">Nichts gefunden.</p>`}
    </div>
  </div>`;
}

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

// ---------------------------------------------------------------- Menü
function MenueEditor({ stand, gespeichert }) {
  const [liste, setListe] = useState(() => JSON.parse(JSON.stringify(stand.menue)));
  const [geaendert, setGeaendert] = useState(false);
  const [speichert, setSpeichert] = useState(false);
  const [hinzu, setHinzu] = useState("");
  const neu = (l) => { setListe(l); setGeaendert(true); };
  const kopie = () => JSON.parse(JSON.stringify(liste));
  // Ein Punkt wird über seinen Weg angesprochen: [i] oder [i, j] (Unterpunkt).
  function holen(l, weg) { return weg.length === 1 ? [l, weg[0]] : [l[weg[0]].unter, weg[1]]; }
  function bewegen(weg, d) { const l = kopie(); const [arr, i] = holen(l, weg); const j = i + d; if (j < 0 || j >= arr.length) return; [arr[i], arr[j]] = [arr[j], arr[i]]; neu(l); }
  function entfernen(weg) { const l = kopie(); const [arr, i] = holen(l, weg); arr.splice(i, 1); if (weg.length === 2 && !l[weg[0]].unter.length) delete l[weg[0]].unter; neu(l); }
  function einruecken(weg) {
    const l = kopie();
    if (weg.length !== 1 || weg[0] === 0) return;
    const [p] = l.splice(weg[0], 1);
    const eltern = l[weg[0] - 1];
    if (p.unter) { toast("Ein Punkt mit Unterpunkten kann nicht eingerückt werden.", { fehler: true }); return; }
    (eltern.unter = eltern.unter || []).push(p);
    neu(l);
  }
  function ausruecken(weg) {
    const l = kopie();
    if (weg.length !== 2) return;
    const [p] = l[weg[0]].unter.splice(weg[1], 1);
    if (!l[weg[0]].unter.length) delete l[weg[0]].unter;
    l.splice(weg[0] + 1, 0, p);
    neu(l);
  }
  function text(weg, t) { const l = kopie(); const [arr, i] = holen(l, weg); arr[i].text = t; neu(l); }
  async function speichern() {
    setSpeichert(true);
    try { await api("/webspace/menue", { methode: "POST", daten: { navigation: liste } }); setGeaendert(false); toast("Menü gespeichert (noch nicht veröffentlicht)."); gespeichert(); }
    catch (e) { fehlerMelden(e); }
    setSpeichert(false);
  }
  const zeile = (p, weg) => html`<div class=${"ws2-menuezeile" + (weg.length === 2 ? " unter" : "")}>
    <input class="eingabe" value=${p.text} onInput=${(e) => text(weg, e.target.value)} aria-label="Text des Menüpunkts" />
    <span class="ws2-menueziel leise" title=${p.href}>${p.href}</span>
    <span class="ws2-menueknoepfe">
      <button class="btn geist icon klein" title="Nach oben" onClick=${() => bewegen(weg, -1)}>↑</button>
      <button class="btn geist icon klein" title="Nach unten" onClick=${() => bewegen(weg, 1)}>↓</button>
      ${weg.length === 1 ? html`<button class="btn geist icon klein" title="Unter den Punkt darüber einrücken" disabled=${weg[0] === 0} onClick=${() => einruecken(weg)}>→</button>`
        : html`<button class="btn geist icon klein" title="Auf die oberste Ebene holen" onClick=${() => ausruecken(weg)}>←</button>`}
      <button class="btn geist icon klein" title="Aus dem Menü nehmen (die Seite bleibt)" onClick=${() => entfernen(weg)}><${Icon} n="x" g=${13} /></button>
    </span></div>`;
  const imMenue = new Set(); liste.forEach((p) => { imMenue.add(p.href); (p.unter || []).forEach((u) => imMenue.add(u.href)); });
  const frei = stand.seiten.filter((s) => !imMenue.has(s.adresse) && !s.blog);
  return html`<div class="ws2-menueed">
    <p class="leise klein">So sieht das Menü oben auf deiner Website aus. Mit → wird ein Punkt zum Unterpunkt des darüberliegenden.</p>
    ${liste.map((p, i) => html`${zeile(p, [i])}${(p.unter || []).map((u, j) => zeile(u, [i, j]))}`)}
    <div class="ws2-hinzu"><select class="eingabe" value=${hinzu} onChange=${(e) => setHinzu(e.target.value)}>
      <option value="">Seite ins Menü aufnehmen …</option>${frei.map((s) => html`<option value=${s.adresse}>${s.titel}</option>`)}</select>
      <button class="btn klein" disabled=${!hinzu} onClick=${() => { const s = stand.seiten.find((x) => x.adresse === hinzu); neu([...kopie(), { text: s.titel, href: s.adresse }]); setHinzu(""); }}>Hinzufügen</button></div>
    <div class="knopfreihe ws2-menuefuss">
      <button class="btn primaer klein" disabled=${!geaendert || speichert} onClick=${speichern}>${speichert ? "Speichert …" : "Menü speichern"}</button>
      ${geaendert && html`<button class="btn klein geist" onClick=${() => { setListe(JSON.parse(JSON.stringify(stand.menue))); setGeaendert(false); }}>Zurücksetzen</button>`}
    </div>
  </div>`;
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
  useEffect(() => {
    api("/webspace/vergleich").then(setDaten).catch(fehlerMelden);
    api("/webspace/pruefen").then((d) => setWarn(d.warnungen)).catch(() => setWarn([]));
  }, []);
  const aend = daten ? daten.aenderungen : [];
  const fehlerAnzahl = (warn || []).filter((w) => w.stufe === "fehler").length;
  async function los() {
    setLaeuft(true);
    try {
      const r = await api("/webspace/veroeffentlichen", { methode: "POST", daten: { bestaetigt: true, nachricht } });
      toast(r.nichts ? "Es gab nichts zu veröffentlichen." : "Veröffentlicht. In etwa einer Minute ist es auf veikovoneckern.org zu sehen.");
      fertig();
    } catch (e) { fehlerMelden(e); setLaeuft(false); }
  }
  async function allesVerwerfen() {
    try { await api("/webspace/verwerfen", { methode: "POST", daten: {} }); toast("Alle Änderungen seit der letzten Veröffentlichung verworfen."); verworfen(); }
    catch (e) { fehlerMelden(e); }
  }
  const titelVon = (a) => (a.neu && a.neu.kopf && a.neu.kopf.titel) || (a.alt && a.alt.kopf && a.alt.kopf.titel) || a.datei;
  return html`<${Modal} titel="Veröffentlichen" zu=${zu} breit=${true}
    fuss=${aend.length ? html`${verwerfenFrage
        ? html`<span class="klein">Wirklich alles verwerfen?</span><button class="btn gefahr voll klein" onClick=${allesVerwerfen}>Ja, verwerfen</button><button class="btn geist klein" onClick=${() => setVerwerfenFrage(false)}>Nein</button>`
        : html`<button class="btn geist" onClick=${() => setVerwerfenFrage(true)}>Alles verwerfen</button>`}
      <span class="luecke"></span><button class="btn geist" onClick=${zu}>Abbrechen</button>
      <button class="btn primaer" disabled=${laeuft || !daten} onClick=${los}><${Icon} n="globus" g=${15} />${laeuft ? "Wird veröffentlicht …" : fehlerAnzahl ? "Trotzdem veröffentlichen" : "Jetzt veröffentlichen"}</button>`
      : html`<span class="luecke"></span><button class="btn" onClick=${zu}>Schließen</button>`}>
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
      <div class="feld"><label>Was hast du geändert? (optional, steht dann im Verlauf)</label>
        <input class="eingabe" value=${nachricht} onInput=${(e) => setNachricht(e.target.value)} placeholder="z. B. Neuer Artikel über Davos" /></div>`}
  <//>`;
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
function NeueSeite({ stand, zu, fertig }) {
  const [art, setArt] = useState("seite");
  const [titel, setTitel] = useState("");
  const [menue, setMenue] = useState("");
  const [ordner, setOrdner] = useState("");
  const [entwurf, setEntwurf] = useState("");
  const [laeuft, setLaeuft] = useState("");
  const ordnerWahl = [["", "oberste Ebene (/name)"], ...stand.menue.filter((m) => m.href.endsWith("/") && m.href !== "/").map((m) => [m.href.replace(/^\/|\/$/g, ""), `unter ${m.href} (${m.text})`])];
  async function los() {
    setLaeuft("Seite wird angelegt …");
    try {
      const r = await api("/webspace/neu", { methode: "POST", daten: { art, titel, ordner: art === "seite" ? ordner : undefined, menue: art === "seite" && menue !== "-" ? menue : null } });
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
  return html`<${Modal} titel="Neue Seite oder Artikel" zu=${zu}
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
    <div class="feld"><label>✦ Ersten Entwurf von der KI schreiben lassen (optional)</label>
      <textarea class="eingabe" rows="4" value=${entwurf} onInput=${(e) => setEntwurf(e.target.value)}
        placeholder="Worum soll es gehen? Stichpunkte reichen. Leer lassen = leere Seite zum selbst Schreiben."></textarea></div>
    ${laeuft && html`<p class="leise">${laeuft}</p>`}
  <//>`;
}
