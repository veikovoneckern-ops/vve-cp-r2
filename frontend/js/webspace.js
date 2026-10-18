// WEBSPACE -- die Website veikovoneckern.org im Cockpit bearbeiten (18.10.2026).
//
// Veiko: "einen Button WebSpace ... einen eigenen Editor für Webseiten, die ich mit
// meinem Cockpit erstellen und bearbeiten kann." Die Website ist ein Repo aus
// kleinen HTML-Dateien (cockpit/webspace.py arbeitet auf einem Klon davon).
//
// Drei Modi für dieselbe Seite:
//   Bearbeiten  -- die Seite so, wie sie aussieht, und man schreibt direkt hinein.
//                  Sie steht in einem Rahmen (srcdoc, gleiche Herkunft), damit Kopf,
//                  Menü und Gestaltung der echten Seite gelten und der Editor auf den
//                  Text zugreifen kann. Interaktive Bausteine erscheinen als Kasten
//                  und werden nie angefasst.
//   HTML        -- der Ausschnitt als Text, für alles, was der Bearbeiten-Modus nicht kann.
//   Seite       -- Titel, Beschreibung, beim Blog Bild/Auszug.
// Gespeichert wird in den Klon (nicht öffentlich). Öffentlich wird es erst mit
// "Veröffentlichen" -- immer ein ausdrücklicher Klick, nie automatisch.
import { html, useState, useEffect, useRef, Icon, Modal, toast, fehlerMelden, bus, zeitText } from "./ui.js";
import { api, ApiFehler } from "./api.js";

const BASIS = "/api/webspace/vorschau";
const MARKE_RE = /<!--(baustein [a-z0-9-]+|blogliste)-->/g;

// ---------------------------------------------------------------- Umsetzen Datei <-> Editor
function zuEditor(inhalt) {
  return inhalt
    .replace(/(["'(])\/bilder\//g, "$1" + BASIS + "/bilder/")
    .replace(MARKE_RE, (m, was) => {
      const text = was === "blogliste" ? "Liste der Blogartikel (baut sich von selbst)" : `Interaktiver Baustein „${was.slice(9)}“ (wird hier nicht bearbeitet)`;
      return `<div class="ws-marke" contenteditable="false" data-marke="${was}">${text}</div>`;
    });
}
function ausEditor(main) {
  const k = main.cloneNode(true);
  k.querySelectorAll(".ws-marke").forEach((m) => m.replaceWith(document.createComment(m.dataset.marke)));
  k.querySelectorAll("[contenteditable]").forEach((e) => e.removeAttribute("contenteditable"));
  k.removeAttribute("contenteditable");
  let s = k.innerHTML;
  s = s.split(BASIS + "/bilder/").join("/bilder/");
  // Schreibweise der vorhandenen Seiten halten: strong/em statt b/i, Schalter ohne ="".
  s = s.replace(/<(\/?)b>/g, "<$1strong>").replace(/<(\/?)i>/g, "<$1em>")
    .replace(/ (controls|playsinline|autoplay|muted|loop)=""/g, " $1");
  // Leere Absätze, die beim Tippen entstehen, nicht mitschleppen.
  s = s.replace(/<p>(\s|<br>)*<\/p>/g, "").replace(/\n{3,}/g, "\n\n");
  return s.trim();
}

const EDITOR_CSS = `
  main[contenteditable="true"]{outline:none}
  main[contenteditable="true"] :is(p,h1,h2,h3,h4,li,figure):hover{outline:1px dashed rgba(59,111,216,.45);outline-offset:3px}
  .ws-marke{margin:24px auto;max-width:1152px;padding:28px 20px;border:2px dashed #98A6B8;border-radius:8px;
    background:repeating-linear-gradient(45deg,#f5f7fa,#f5f7fa 10px,#eef1f5 10px,#eef1f5 20px);
    color:#32465C;font:600 15px/1.4 system-ui,sans-serif;text-align:center;user-select:none}
  .ws-vorschlag main{box-shadow:inset 0 0 0 4px #7C3AED}
`;

// ---------------------------------------------------------------- Hauptansicht
export function WebSpace({ pfad: pfadAusAdresse }) {
  const [stand, setStand] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [pfad, setPfad] = useState(pfadAusAdresse || "index.html");
  const [neu, setNeu] = useState(false);
  const editorRef = useRef(null);

  const laden = () => api("/webspace/stand").then((s) => { setStand(s); setFehler(null); }).catch((e) => setFehler(e.message));
  useEffect(() => { laden(); }, []);
  // Läuft gerade eine Veröffentlichung auf GitHub: alle 5 s nachsehen, sonst alle 30 s.
  const laeuft = stand && stand.veroeffentlichung && stand.veroeffentlichung.stand !== "completed";
  useEffect(() => {
    const i = setInterval(() => { if (!document.hidden) laden(); }, laeuft ? 5000 : 30000);
    return () => clearInterval(i);
  }, [laeuft]);
  useEffect(() => { if (pfadAusAdresse) setPfad(pfadAusAdresse); }, [pfadAusAdresse]);
  // Gibt es die geöffnete Seite nicht mehr (verworfen, gelöscht), zur Startseite.
  useEffect(() => {
    if (stand && !stand.seiten.some((s) => s.pfad === pfad)) {
      setPfad("index.html");
      history.replaceState(null, "", "#/webspace");
    }
  }, [stand, pfad]);
  useEffect(() => {
    bus.sende("talk-kontext", { art: "webspace", id: "webspace", titel: "WebSpace", pfad });
    return () => bus.sende("talk-kontext", null);
  }, [pfad]);

  async function wechseln(neuerPfad) {
    // Ungespeichertes wird beim Wechseln gesichert -- nicht gefragt, nichts geht verloren.
    if (editorRef.current) await editorRef.current.sichern();
    setPfad(neuerPfad);
    history.replaceState(null, "", "#/webspace/" + encodeURIComponent(neuerPfad));
  }

  if (fehler && !stand) return html`<div class="karte"><h3>WebSpace nicht erreichbar</h3><p class="leise">${fehler}</p>
    <button class="btn" onClick=${laden}>Noch einmal</button></div>`;
  if (!stand) return html`<div class="leise" style="padding:20px">WebSpace wird geladen …</div>`;

  return html`<div class="ws">
    <aside class="ws-seite">
      <div class="ws-knoepfe">
        <button class="btn primaer klein" onClick=${() => setNeu(true)}><${Icon} n="plus" g=${15} />Neue Seite oder Artikel</button>
      </div>
      <${SeitenListe} stand=${stand} pfad=${pfad} waehlen=${wechseln} />
      <${Veroeffentlichen} stand=${stand} neuLaden=${laden} vorher=${() => editorRef.current && editorRef.current.sichern()} />
    </aside>
    <section class="ws-haupt">
      <${Editor} key=${pfad} pfad=${pfad} stand=${stand} ref_=${editorRef} geaendert=${laden}
        geloescht=${() => { laden(); wechseln("index.html"); }} />
    </section>
    ${neu && html`<${NeueSeite} stand=${stand} zu=${() => setNeu(false)} fertig=${(p) => { setNeu(false); laden(); wechseln(p); }} />`}
  </div>`;
}

function SeitenListe({ stand, pfad, waehlen }) {
  const seiten = stand.seiten.filter((s) => !s.blog);
  const blog = stand.seiten.filter((s) => s.blog).sort((a, b) => (a.blog.reihe ?? 999) - (b.blog.reihe ?? 999));
  const zeile = (s) => html`<button class=${"ws-zeile" + (s.pfad === pfad ? " an" : "")} onClick=${() => waehlen(s.pfad)} title=${s.adresse}>
    <span class="ws-zeile-titel">${s.titel}</span>
    ${s.geaendert && html`<span class="ws-punkt" title="Geändert, noch nicht veröffentlicht"></span>`}
    <span class="ws-zeile-adr">${s.adresse}</span></button>`;
  return html`<div class="ws-liste">
    <div class="ws-gruppe">Seiten</div>${seiten.map(zeile)}
    <div class="ws-gruppe">Blog „Inspiration“</div>${blog.map(zeile)}
  </div>`;
}

function Veroeffentlichen({ stand, neuLaden, vorher }) {
  const [frage, setFrage] = useState(false);
  const [laeuft, setLaeuft] = useState(false);
  const aend = stand.aenderungen || [];
  const v = stand.veroeffentlichung;
  async function los() {
    setFrage(false); setLaeuft(true);
    try {
      await vorher();
      const r = await api("/webspace/veroeffentlichen", { methode: "POST", daten: { bestaetigt: true } });
      toast(r.nichts ? "Es gab nichts zu veröffentlichen." : `Veröffentlicht (${r.dateien} Datei${r.dateien === 1 ? "" : "en"}). GitHub baut die Seite jetzt, das dauert etwa eine Minute.`);
      neuLaden();
    } catch (e) { fehlerMelden(e); }
    setLaeuft(false);
  }
  async function allesVerwerfen() {
    try { await api("/webspace/verwerfen", { methode: "POST", daten: {} }); toast("Alle unveröffentlichten Änderungen verworfen."); neuLaden(); bus.sende("webspace-neu"); }
    catch (e) { fehlerMelden(e); }
  }
  let lage = null;
  if (v) {
    if (v.stand !== "completed") lage = html`<span class="ws-lage gelb">GitHub veröffentlicht gerade …</span>`;
    else if (v.ergebnis === "success") lage = html`<span class="ws-lage gruen">Online · Stand ${v.sha} · ${zeitText(Date.parse(v.zeit) / 1000)}</span>`;
    else lage = html`<span class="ws-lage rot">Letzte Veröffentlichung gescheitert (${v.ergebnis}). <a href=${v.url} target="_blank" rel="noopener">Ansehen</a></span>`;
  }
  return html`<div class="ws-pub karte">
    <div class="ws-pub-kopf"><b>${aend.length ? `${aend.length} unveröffentlichte Änderung${aend.length === 1 ? "" : "en"}` : "Alles veröffentlicht"}</b></div>
    ${aend.length > 0 && html`<ul class="ws-aend">${aend.slice(0, 12).map((a) => html`<li><span class=${"ws-art " + a.art}>${a.art}</span>${a.datei.replace(/^inhalt\//, "")}</li>`)}
      ${aend.length > 12 && html`<li class="leise">… und ${aend.length - 12} weitere</li>`}</ul>`}
    ${aend.length > 0 && (frage
      ? html`<div class="ws-frage">Jetzt auf veikovoneckern.org veröffentlichen? Danach sieht es jeder.
          <span class="knopfreihe"><button class="btn klein primaer" onClick=${los}>Ja, veröffentlichen</button>
          <button class="btn klein geist" onClick=${() => setFrage(false)}>Abbrechen</button></span></div>`
      : html`<span class="knopfreihe"><button class="btn primaer klein" disabled=${laeuft} onClick=${() => setFrage(true)}>
          <${Icon} n="globus" g=${15} />${laeuft ? "Wird veröffentlicht …" : "Veröffentlichen"}</button>
          <${FrageKnopf} text="Alles verwerfen" frage="Alle Änderungen seit der letzten Veröffentlichung verwerfen?" ja="Verwerfen" tun=${allesVerwerfen} /></span>`)}
    <div class="ws-pub-fuss">${lage}<a href=${stand.live} target="_blank" rel="noopener" class="ws-live"><${Icon} n="extern" g=${13} />${stand.live.replace("https://", "")}</a></div>
  </div>`;
}

function FrageKnopf({ text, frage, ja, tun, klasse = "" }) {
  const [auf, setAuf] = useState(false);
  if (auf) return html`<span class="knopfreihe"><span class="klein">${frage}</span>
    <button class="btn klein gefahr" onClick=${() => { setAuf(false); tun(); }}>${ja}</button>
    <button class="btn klein geist" onClick=${() => setAuf(false)}>Abbrechen</button></span>`;
  return html`<button class=${"btn klein " + klasse} onClick=${() => setAuf(true)}>${text}</button>`;
}

// ---------------------------------------------------------------- Editor einer Seite
function Editor({ pfad, stand, ref_, geaendert, geloescht }) {
  const [seite, setSeite] = useState(null);   // { kopf, inhalt } -- zuletzt gespeichert
  const [kopf, setKopf] = useState(null);
  const [inhalt, setInhalt] = useState("");   // aktueller Stand (aus Rahmen oder HTML-Feld)
  const [modus, setModus] = useState("bearbeiten");
  const [vorschlag, setVorschlag] = useState(null);
  const [speichert, setSpeichert] = useState(false);
  const [fehler, setFehler] = useState(null);
  const rahmen = useRef(null);
  const zustand = useRef({});
  zustand.current = { seite, kopf, inhalt, modus, vorschlag };

  useEffect(() => {
    api("/webspace/seite?pfad=" + encodeURIComponent(pfad))
      .then((s) => { setSeite(s); setKopf(s.kopf); setInhalt(s.inhalt); })
      .catch((e) => setFehler(e.message));
  }, [pfad]);
  useEffect(() => bus.an("webspace-neu", () => {
    api("/webspace/seite?pfad=" + encodeURIComponent(pfad)).then((s) => { setSeite(s); setKopf(s.kopf); setInhalt(s.inhalt); setVorschlag(null); }).catch(() => {});
  }), [pfad]);

  // Den aktuellen Text holen: im Bearbeiten-Modus aus dem Rahmen, sonst aus dem Zustand.
  function aktuell() {
    const z = zustand.current;
    if (z.modus === "bearbeiten" && !z.vorschlag && rahmen.current) {
      const main = rahmen.current.contentDocument && rahmen.current.contentDocument.querySelector("main");
      if (main && main.dataset.bereit) {
        // Der Browser schreibt HTML beim Auslesen anders zurück (Leerzeichen,
        // Anführungszeichen). Unverändert = gleich dem Stand direkt nach dem Laden;
        // dann gilt der Originaltext -- sonst wäre jede bloß geöffnete Seite "geändert".
        const s = ausEditor(main);
        return s === rahmen.current.dataset.basis ? z.inhalt : s;
      }
    }
    return z.inhalt;
  }
  function ungespeichert() {
    const z = zustand.current;
    if (!z.seite) return false;
    return aktuell() !== z.seite.inhalt.trim() || JSON.stringify(z.kopf) !== JSON.stringify(z.seite.kopf);
  }
  async function speichern(still) {
    const z = zustand.current;
    if (!z.seite || !ungespeichert()) return true;
    const neuInhalt = aktuell();
    setSpeichert(true);
    try {
      await api("/webspace/seite", { methode: "POST", daten: { pfad, kopf: z.kopf, inhalt: neuInhalt } });
      setSeite({ ...z.seite, kopf: z.kopf, inhalt: neuInhalt });
      setInhalt(neuInhalt);
      if (!still) toast("Gespeichert. Öffentlich wird es erst mit „Veröffentlichen“.");
      geaendert();
      return true;
    } catch (e) { fehlerMelden(e); return false; }
    finally { setSpeichert(false); }
  }
  // Für die Hauptansicht: vor dem Wechsel oder Veröffentlichen sichern.
  ref_.current = { sichern: () => speichern(true) };

  // Strg+S speichert.
  useEffect(() => {
    const k = (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); speichern(false); } };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [pfad]);

  function modusWechseln(m) {
    if (m === modus) return;
    const jetzt = aktuell();
    setInhalt(jetzt);
    setModus(m);
  }

  if (fehler) return html`<div class="karte"><h3>Seite lässt sich nicht laden</h3><p class="leise">${fehler}</p></div>`;
  if (!seite || !kopf) return html`<div class="leise" style="padding:20px">Seite wird geladen …</div>`;

  const info = stand.seiten.find((s) => s.pfad === pfad);
  return html`<div class="ws-editor">
    <div class="ws-kopfzeile">
      <div class="ws-titel"><b>${kopf.titel}</b><span class="leise">${seite.adresse}${info && info.geaendert ? " · geändert, nicht veröffentlicht" : ""}</span></div>
      <div class="segment">
        ${[["bearbeiten", "Bearbeiten"], ["html", "HTML"], ["seite", "Seite"]].map(([k, t]) => html`<button class=${modus === k ? "an" : ""} onClick=${() => modusWechseln(k)}>${t}</button>`)}
      </div>
      <span class="knopfreihe">
        <button class="btn primaer klein" disabled=${speichert} onClick=${() => speichern(false)} title="Speichern (Strg+S)">${speichert ? "Speichert …" : "Speichern"}</button>
        <a class="btn klein" href=${BASIS + seite.adresse} target="_blank" rel="noopener" title="Vorschau mit allen Funktionen in einem neuen Tab (gespeicherter Stand)"><${Icon} n="auge" g=${14} />Vorschau</a>
        ${info && info.geaendert && html`<${FrageKnopf} text="Verwerfen" frage="Änderungen an dieser Seite verwerfen?" ja="Verwerfen"
          tun=${async () => { try { await api("/webspace/verwerfen", { methode: "POST", daten: { pfad } }); geaendert(); bus.sende("webspace-neu"); } catch (e) { fehlerMelden(e); } }} />`}
        ${pfad !== "index.html" && html`<${FrageKnopf} text="Löschen" frage="Diese Seite löschen? Weg ist sie erst nach dem Veröffentlichen." ja="Löschen"
          tun=${async () => { try { await api("/webspace/loeschen", { methode: "POST", daten: { pfad } }); toast("Seite gelöscht (noch nicht veröffentlicht)."); geloescht(); } catch (e) { fehlerMelden(e); } }} />`}
      </span>
    </div>
    ${modus === "bearbeiten" && html`<${Bearbeiten} rahmen=${rahmen} inhalt=${vorschlag ? vorschlag.inhalt : inhalt} vorschlag=${vorschlag} />`}
    ${modus === "html" && html`<textarea class="ws-code" spellcheck="false" value=${vorschlag ? vorschlag.inhalt : inhalt}
      readOnly=${!!vorschlag} onInput=${(e) => setInhalt(e.target.value)} aria-label="HTML der Seite"></textarea>`}
    ${modus === "seite" && html`<${SeitenFelder} kopf=${kopf} setKopf=${setKopf} />`}
    <${Assistent} pfad=${pfad} kopf=${kopf} aktuell=${aktuell} vorschlag=${vorschlag} setVorschlag=${setVorschlag}
      uebernehmen=${() => { setInhalt(vorschlag.inhalt); setVorschlag(null); toast("Übernommen. Noch speichern, dann veröffentlichen."); }} />
  </div>`;
}

// Der Bearbeiten-Modus: die echte Seite in einem Rahmen, Text direkt bearbeitbar.
function Bearbeiten({ rahmen, inhalt, vorschlag }) {
  const [huelle, setHuelle] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [pop, setPop] = useState(null);       // "link" | "bild"
  const auswahl = useRef(null);
  useEffect(() => {
    fetch(BASIS + "/_editor.html", { credentials: "same-origin" })
      .then((r) => { if (!r.ok) throw new ApiFehler("Der Seitenrahmen ließ sich nicht bauen (Fehler " + r.status + ")", r.status); return r.text(); })
      .then(setHuelle).catch((e) => setFehler(e.message));
  }, []);
  const doc = huelle ? huelle.replace("<!--EDITOR-->", zuEditor(inhalt)).replace("</head>", `<style>${EDITOR_CSS}</style></head>`)
    .replace("<body>", vorschlag ? '<body class="ws-vorschlag">' : "<body>") : null;

  function eingerichtet() {
    const d = rahmen.current && rahmen.current.contentDocument;
    if (!d) return;
    const main = d.querySelector("main");
    if (!main) return;
    // Links führen im Editor nirgendwohin -- ein Klick soll Text markieren, nicht wegnavigieren.
    d.addEventListener("click", (e) => { if (e.target.closest("a")) e.preventDefault(); }, true);
    d.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); document.dispatchEvent(new KeyboardEvent("keydown", { key: "s", ctrlKey: true })); }
    });
    if (!vorschlag) {
      main.setAttribute("contenteditable", "true");
      try { d.execCommand("defaultParagraphSeparator", false, "p"); } catch (e) { /* alt */ }
    }
    rahmen.current.dataset.basis = ausEditor(main);
    main.dataset.bereit = "1";
  }
  function merken() {
    const d = rahmen.current && rahmen.current.contentDocument;
    const s = d && d.getSelection();
    auswahl.current = s && s.rangeCount ? s.getRangeAt(0).cloneRange() : null;
  }
  function zurueck() {
    const d = rahmen.current.contentDocument;
    if (!auswahl.current) return;
    const s = d.getSelection();
    s.removeAllRanges(); s.addRange(auswahl.current);
  }
  function befehl(b, wert) {
    const d = rahmen.current && rahmen.current.contentDocument;
    if (!d || vorschlag) return;
    rahmen.current.contentWindow.focus();
    d.execCommand(b, false, wert);
  }
  // Mausdruck statt Klick: ein Klick nähme dem Rahmen erst den Fokus und damit die Markierung.
  const knopf = (titel, icon, fn) => html`<button class="btn geist icon klein" title=${titel} aria-label=${titel}
    onMouseDown=${(e) => { e.preventDefault(); fn(); }}>${icon}</button>`;

  if (fehler) return html`<div class="karte"><p>${fehler}</p></div>`;
  return html`<div class="ws-bearbeiten">
    <div class="ws-werkzeug" role="toolbar" aria-label="Formatieren">
      ${knopf("Absatz", html`<b>¶</b>`, () => befehl("formatBlock", "p"))}
      ${knopf("Überschrift 2", html`<b>H2</b>`, () => befehl("formatBlock", "h2"))}
      ${knopf("Überschrift 3", html`<b>H3</b>`, () => befehl("formatBlock", "h3"))}
      <span class="ws-trenner"></span>
      ${knopf("Fett", html`<b>B</b>`, () => befehl("bold"))}
      ${knopf("Kursiv", html`<i style="font-family:serif">I</i>`, () => befehl("italic"))}
      ${knopf("Unterstrichen", html`<u>U</u>`, () => befehl("underline"))}
      <span class="ws-trenner"></span>
      ${knopf("Aufzählung", html`<${Icon} n="liste" g=${15} />`, () => befehl("insertUnorderedList"))}
      ${knopf("Nummerierte Liste", html`<b>1.</b>`, () => befehl("insertOrderedList"))}
      <span class="ws-trenner"></span>
      ${knopf("Link", html`<${Icon} n="extern" g=${15} />`, () => { merken(); setPop("link"); })}
      ${knopf("Bild einfügen", html`<${Icon} n="clip" g=${15} />`, () => { merken(); setPop("bild"); })}
      ${knopf("Formatierung entfernen", html`<span style="text-decoration:line-through">T</span>`, () => befehl("removeFormat"))}
      <span class="ws-trenner"></span>
      ${knopf("Rückgängig", html`<${Icon} n="undo" g=${15} />`, () => befehl("undo"))}
      <span class="ws-hinweis leise">${vorschlag ? "Vorschlag des Assistenten (violett umrandet) -- unten übernehmen oder verwerfen" : "Direkt in die Seite klicken und schreiben"}</span>
    </div>
    ${pop === "link" && html`<${LinkPop} zu=${() => setPop(null)} setzen=${(url) => { zurueck(); befehl(url ? "createLink" : "unlink", url || undefined);
      if (url && /^https?:/.test(url)) { const a = rahmen.current.contentDocument.getSelection().anchorNode; const el = a && (a.nodeType === 1 ? a : a.parentElement); const l = el && el.closest("a"); if (l) { l.target = "_blank"; l.rel = "noopener"; } }
      setPop(null); }} />`}
    ${pop === "bild" && html`<${BildPop} zu=${() => setPop(null)} setzen=${(src) => { zurueck(); befehl("insertHTML", `<figure><img src="${BASIS}${src}" alt="" loading="lazy"></figure><p><br></p>`); setPop(null); }} />`}
    ${doc ? html`<iframe ref=${rahmen} class="ws-rahmen" srcdoc=${doc} onLoad=${eingerichtet} title="Seite bearbeiten"></iframe>`
      : html`<div class="leise" style="padding:20px">Seitenrahmen wird gebaut …</div>`}
  </div>`;
}

function LinkPop({ zu, setzen }) {
  const [url, setUrl] = useState("");
  return html`<div class="ws-pop">
    <input class="eingabe" autofocus placeholder="https://… oder /seite (leer = Link entfernen)" value=${url}
      onInput=${(e) => setUrl(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter") setzen(url.trim()); if (e.key === "Escape") { e.stopPropagation(); zu(); } }} />
    <button class="btn klein primaer" onClick=${() => setzen(url.trim())}>Setzen</button>
    <button class="btn klein geist" onClick=${zu}>Abbrechen</button>
  </div>`;
}

function BildPop({ zu, setzen }) {
  const [bilder, setBilder] = useState(null);
  const [laedt, setLaedt] = useState(false);
  const feld = useRef(null);
  useEffect(() => { api("/webspace/bilder").then((d) => setBilder(d.bilder)).catch(fehlerMelden); }, []);
  async function hoch(e) {
    // Erst kopieren, dann zurücksetzen: input.files ist eine lebende Liste (FileList-Falle aus dem alten Cockpit).
    const dateien = [...e.target.files];
    e.target.value = "";
    if (!dateien.length) return;
    setLaedt(true);
    try {
      const fd = new FormData(); fd.append("datei", dateien[0], dateien[0].name);
      const r = await fetch("/api/webspace/bild", { method: "POST", body: fd, credentials: "same-origin" });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "Hochladen gescheitert");
      setzen(d.pfad);
    } catch (x) { fehlerMelden(x); }
    setLaedt(false);
  }
  return html`<div class="ws-pop ws-bilder">
    <div class="ws-bilder-kopf"><b>Bild einfügen</b>
      <button class="btn klein" disabled=${laedt} onClick=${() => feld.current.click()}><${Icon} n="plus" g=${14} />${laedt ? "Lädt hoch …" : "Neues Bild hochladen"}</button>
      <input ref=${feld} type="file" accept="image/*" hidden onChange=${hoch} />
      <button class="btn klein geist" onClick=${zu}>Schließen</button></div>
    <div class="ws-bilder-raster">${(bilder || []).filter((b) => !/\.mp4$/.test(b)).map((b) => html`<button onClick=${() => setzen(b)} title=${b}>
      <img src=${BASIS + b} alt="" loading="lazy" /></button>`)}</div>
  </div>`;
}

function SeitenFelder({ kopf, setKopf }) {
  const setze = (k, v) => setKopf({ ...kopf, [k]: v });
  const blog = kopf.blog;
  return html`<div class="ws-felder">
    <div class="feld"><label>Titel (Browser-Tab, Suchmaschinen${blog ? ", Überschrift des Artikels" : ""})</label>
      <input class="eingabe" value=${kopf.titel || ""} onInput=${(e) => setze("titel", e.target.value)} /></div>
    <div class="feld"><label>Beschreibung (ein bis zwei Sätze für Suchmaschinen)</label>
      <textarea class="eingabe" rows="3" value=${kopf.beschreibung || ""} onInput=${(e) => setze("beschreibung", e.target.value)}></textarea></div>
    ${blog && html`<div class="feld"><label>Auszug in der Blog-Übersicht</label>
        <textarea class="eingabe" rows="3" value=${blog.auszug || ""} onInput=${(e) => setze("blog", { ...blog, auszug: e.target.value })}></textarea></div>
      <div class="feld"><label>Titelbild in der Übersicht</label>
        <${BildWahl} wert=${blog.bild} setzen=${(b) => setze("blog", { ...blog, bild: b })} /></div>
      <div class="feld"><label>Reihenfolge (kleinere Zahl = weiter oben)</label>
        <input class="eingabe" type="number" style="max-width:120px" value=${blog.reihe ?? ""} onInput=${(e) => setze("blog", { ...blog, reihe: Number(e.target.value) })} /></div>`}
    <p class="leise klein">Änderungen hier gelten erst nach „Speichern“ und sind öffentlich erst nach „Veröffentlichen“.</p>
  </div>`;
}

function BildWahl({ wert, setzen }) {
  const [auf, setAuf] = useState(false);
  return html`<div class="ws-bildwahl">
    ${wert ? html`<img src=${BASIS + wert} alt="" />` : html`<span class="leise">kein Bild</span>`}
    <button class="btn klein" onClick=${() => setAuf(!auf)}>${wert ? "Ändern" : "Bild wählen"}</button>
    ${auf && html`<${BildPop} zu=${() => setAuf(false)} setzen=${(b) => { setzen(b); setAuf(false); }} />`}
  </div>`;
}

// ---------------------------------------------------------------- KI-Assistent
function Assistent({ pfad, kopf, aktuell, vorschlag, setVorschlag, uebernehmen }) {
  const [auftrag, setAuftrag] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const [seit, setSeit] = useState(0);
  const [jetzt, setJetzt] = useState(Date.now());
  useEffect(() => { if (!laeuft) return; const i = setInterval(() => setJetzt(Date.now()), 1000); return () => clearInterval(i); }, [laeuft]);
  async function los() {
    if (!auftrag.trim() || laeuft) return;
    setLaeuft(true); setSeit(Date.now());
    try {
      const r = await api("/webspace/assistent", { methode: "POST", daten: { pfad, kopf, inhalt: aktuell(), auftrag } });
      setVorschlag(r);
    } catch (e) { fehlerMelden(e); }
    setLaeuft(false);
  }
  return html`<div class="ws-assistent">
    ${vorschlag ? html`<div class="ws-vorschlag-leiste">
        <div><b>Vorschlag des Assistenten</b> <span class="leise">(${vorschlag.modell})</span>
          ${vorschlag.erklaerung && html`<div class="klein">${vorschlag.erklaerung}</div>`}
          ${(vorschlag.hinweise || []).map((h) => html`<div class="klein leise">${h}</div>`)}</div>
        <span class="knopfreihe"><button class="btn primaer klein" onClick=${uebernehmen}><${Icon} n="check" g=${14} />Übernehmen</button>
          <button class="btn klein" onClick=${() => setVorschlag(null)}>Verwerfen</button></span></div>`
      : html`<div class="ws-auftrag">
        <textarea class="eingabe" rows="2" placeholder="KI-Assistent: z. B. „Schreib die Einleitung kürzer und klarer“, „Füge einen Abschnitt zu Alignment mit drei Punkten hinzu“, „Mach daraus zwei Spalten“"
          value=${auftrag} disabled=${laeuft} onInput=${(e) => setAuftrag(e.target.value)}
          onKeyDown=${(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); los(); } }}></textarea>
        <button class="btn primaer" disabled=${laeuft || !auftrag.trim()} onClick=${los}>
          ${laeuft ? `Schreibt … ${Math.round((jetzt - seit) / 1000)} s` : html`<${Icon} n="senden" g=${15} />Ändern lassen`}</button>
      </div>`}
  </div>`;
}

// ---------------------------------------------------------------- Neue Seite / neuer Artikel
function NeueSeite({ stand, zu, fertig }) {
  const [art, setArt] = useState("seite");
  const [titel, setTitel] = useState("");
  const [menue, setMenue] = useState("");          // "" = Hauptmenü, href = darunter, "-" = nicht im Menü
  const [ordner, setOrdner] = useState("");
  const [entwurf, setEntwurf] = useState("");
  const [laeuft, setLaeuft] = useState("");
  const ordnerWahl = [["", "oberste Ebene (/name)"], ...stand.menue.filter((m) => m.href.endsWith("/") && m.href !== "/").map((m) => [m.href.replace(/^\/|\/$/g, ""), `unter ${m.href} (${m.text})`])];
  async function los() {
    setLaeuft("Seite wird angelegt …");
    try {
      const r = await api("/webspace/neu", { methode: "POST", daten: { art, titel, ordner: art === "seite" ? ordner : undefined, menue: art === "seite" && menue !== "-" ? menue : null } });
      if (entwurf.trim()) {
        setLaeuft("Der Assistent schreibt den ersten Entwurf … (das kann eine Minute dauern)");
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
    fuss=${html`<button class="btn geist" onClick=${zu}>Abbrechen</button><button class="btn primaer" disabled=${!titel.trim() || !!laeuft} onClick=${los}>${laeuft ? "Einen Moment …" : "Anlegen"}</button>`}>
    <div class="segment" style="margin-bottom:12px">
      <button class=${art === "seite" ? "an" : ""} onClick=${() => setArt("seite")}>Seite</button>
      <button class=${art === "blog" ? "an" : ""} onClick=${() => setArt("blog")}>Blogartikel (Inspiration)</button>
    </div>
    <div class="feld"><label>Titel</label><input class="eingabe" autofocus value=${titel} onInput=${(e) => setTitel(e.target.value)} placeholder=${art === "blog" ? "z. B. Was Davos 2027 über KI sagt" : "z. B. Vorträge"} /></div>
    ${art === "seite" && html`
      <div class="feld"><label>Wo liegt die Seite?</label>
        <select class="eingabe" value=${ordner} onChange=${(e) => setOrdner(e.target.value)}>${ordnerWahl.map(([w, t]) => html`<option value=${w}>${t}</option>`)}</select></div>
      <div class="feld"><label>Im Menü</label>
        <select class="eingabe" value=${menue} onChange=${(e) => setMenue(e.target.value)}>
          <option value="">als eigener Punkt im Hauptmenü</option>
          ${stand.menue.filter((m) => m.href !== "/").map((m) => html`<option value=${m.href}>unter „${m.text}“</option>`)}
          <option value="-">nicht im Menü (nur über Links erreichbar)</option>
        </select></div>`}
    <div class="feld"><label>Erster Entwurf vom KI-Assistenten (optional)</label>
      <textarea class="eingabe" rows="4" value=${entwurf} onInput=${(e) => setEntwurf(e.target.value)}
        placeholder="Worum soll es gehen? Stichpunkte reichen. Leer lassen = leere Seite zum selbst Schreiben."></textarea></div>
    ${laeuft && html`<p class="leise">${laeuft}</p>`}
  <//>`;
}
