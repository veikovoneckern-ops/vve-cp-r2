// WEBSPACE -- der Editor einer Seite (19.10.2026).
//
// Veiko: "erweiter die Funktionalitäten bei WebSpace deutlich … vergleichbar
// arbeiten wie mit den Top-Tools … sehr stark auf Usability und intuitive
// Bedienoberfläche achten."
//
// Aufbau wie bei Webflow, Squarespace oder dem WordPress-Blockeditor:
//   Mitte   die Seite selbst (Rahmen mit Kopf, Menü und Fuß der echten Seite),
//           direkt beschreibbar; über jedem Abschnitt eine kleine Leiste zum
//           Verschieben, Ziehen, Duplizieren, Löschen, KI und Einfügen.
//   Rechts  Eigenschaften dessen, was angeklickt ist (Band: Bild, Deckkraft,
//           Höhe, Effekt; Bild: austauschen, Beschreibung, Größe; Knopf: Ziel …),
//           ohne Auswahl die Seiteneinstellungen mit Google-Vorschau; dazu KI und Verlauf.
//   Oben    Format-Leiste, Rückgängig/Wiederholen, Gerät (Rechner/Tablet/Handy), HTML.
//
// Gespeichert wird automatisch (1,5 s nach der letzten Änderung) in den Klon --
// öffentlich wird erst mit "Veröffentlichen". Rückgängig hält das Cockpit selbst
// (Liste der Fassungen), weil das Rückgängig des Browsers Strukturänderungen
// (Abschnitt verschoben, KI-Text) nicht kennt.
import { html, useState, useEffect, useRef, Icon, Modal, toast, fehlerMelden, zeitText } from "./ui.js";
import { api } from "./api.js";
import { BASIS, zuEditor, ausEditor, abschnittArt, kurzText, VORLAGEN, youtubeId, saeubern } from "./webspace-teile.js";

const EDITOR_CSS = `
  main[contenteditable="true"]{outline:none}
  main[contenteditable="true"] a{cursor:text}
  .ws-marke{margin:24px auto;max-width:1152px;padding:26px 20px;border:2px dashed #98A6B8;border-radius:8px;
    background:repeating-linear-gradient(45deg,#f5f7fa,#f5f7fa 10px,#eef1f5 10px,#eef1f5 20px);
    color:#32465C;font:600 15px/1.4 system-ui,sans-serif;text-align:center;user-select:none}
  .ws-marke span{margin-right:8px}
  .video iframe{pointer-events:none}
  .video:has(iframe[src$="/embed/"])::after{content:"YouTube-Link rechts unter Eigenschaften eintragen";position:absolute;inset:0;display:grid;place-items:center;color:#fff;font:600 16px system-ui}
  .abstand{background:repeating-linear-gradient(0deg,transparent,transparent 7px,rgba(59,111,216,.08) 7px,rgba(59,111,216,.08) 8px)}
  #ws-ui{position:absolute;left:0;top:0;width:0;height:0;z-index:2147483000;font:13px/1.3 system-ui,-apple-system,sans-serif}
  .ws-box{position:absolute;pointer-events:none;border-radius:3px;box-sizing:border-box}
  .ws-box.hover{border:1px dashed rgba(59,111,216,.8)}
  .ws-box.block{border:2px solid #3B6FD8}
  .ws-box.el{border:2px solid #7C3AED}
  .ws-box.blitz{border:3px solid #0b8f3e;transition:opacity 1.2s}
  .ws-leiste{position:absolute;pointer-events:auto;display:flex;align-items:center;gap:1px;background:#1B3F6B;border-radius:7px;padding:3px;box-shadow:0 4px 14px rgba(0,0,0,.25);transform:translate(-100%,0);white-space:nowrap}
  .ws-leiste button{all:unset;cursor:pointer;color:#fff;min-width:26px;height:26px;display:grid;place-items:center;border-radius:5px;font:700 14px system-ui}
  .ws-leiste button:hover{background:rgba(255,255,255,.2)}
  .ws-leiste button.weg:hover{background:#8f1d18}
  .ws-leiste .griff{cursor:grab}
  .ws-leiste .name{color:#cfe0ff;padding:0 8px 0 6px;font:700 12px system-ui}
  .ws-plus{position:absolute;pointer-events:auto;transform:translate(-50%,-50%);width:28px;height:28px;border-radius:50%;border:0;background:#3B6FD8;color:#fff;font:700 18px/28px system-ui;text-align:center;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.25)}
  .ws-plus:hover{background:#1B3F6B}
  .ws-linie{position:absolute;height:4px;background:#3B6FD8;border-radius:2px;pointer-events:none}
  .ws-ende{max-width:1152px;margin:28px auto 56px;padding:0 24px}
  .ws-ende button{width:100%;border:2px dashed #98A6B8;background:#fafbfc;padding:20px;border-radius:10px;font:600 15px system-ui;color:#32465C;cursor:pointer}
  .ws-ende button:hover{border-color:#3B6FD8;color:#1B3F6B;background:#f0f5ff}
  html.ws-zieht, html.ws-zieht *{cursor:grabbing!important;user-select:none!important}
  html.ws-nurlesen main{opacity:.96}
`;

const GERAETE = [["desktop", "Rechner", null], ["tablet", "Tablet", 820], ["handy", "Handy", 390]];
const KI_SCHNELL = [["Kürzer", "Mach den Text deutlich kürzer und knapper, ohne Inhalt zu verlieren."],
  ["Verständlicher", "Formuliere verständlicher und klarer, für Leser ohne Vorwissen."],
  ["Ausführlicher", "Arbeite den Text etwas ausführlicher aus, ohne Fakten zu erfinden."],
  ["Rechtschreibung", "Korrigiere nur Rechtschreibung, Grammatik und Zeichensetzung. Sonst nichts ändern."],
  ["Professioneller", "Formuliere professioneller und souveräner, im Ton eines Experten."],
  ["Auf Englisch", "Übersetze den Text ins Englische. Struktur und Bausteine bleiben gleich."]];

export function Editor({ pfad, stand, sichernRef, geaendert: aufGeaendert, kopfLeiste, geloescht }) {
  const [seite, setSeite] = useState(null);
  const [kopf, setKopfZustand] = useState(null);
  const [fehler, setFehler] = useState(null);
  const [speicher, setSpeicher] = useState({ stand: "gespeichert", zeit: 0 });
  const [modus, setModus] = useState("visuell");
  const [geraet, setGeraet] = useState(() => { try { return localStorage.getItem("ws-geraet") || "desktop"; } catch (e) { return "desktop"; } });
  const [rechts, setRechts] = useState("eigenschaften");
  const [auswahlNr, setAuswahlNr] = useState(0);
  const [huelle, setHuelle] = useState(null);
  const [bibliothek, setBibliothek] = useState(null);   // { nach: element|null, ersetzen?: element }
  const [medien, setMedien] = useState(null);           // { waehlen(pfad) }
  const [linkPop, setLinkPop] = useState(null);
  const [fassungAnsicht, setFassungAnsicht] = useState(null);
  const [kiMeldung, setKiMeldung] = useState(null);
  const [histNr, setHistNr] = useState(0);
  const [codeText, setCodeText] = useState("");

  const rahmen = useRef(null);
  const aktuell = useRef("");          // aktueller HTML-Text der Seite
  const kopfRef = useRef(null);
  const hist = useRef({ liste: [], i: -1 });
  const ausw = useRef({ block: null, el: null });
  const hover = useRef(null);
  const timer = useRef({ eingabe: 0, speichern: 0 });
  const fn = useRef({});

  // ------------------------------------------------ Laden
  useEffect(() => {
    api("/webspace/seite?pfad=" + encodeURIComponent(pfad))
      .then((s) => { setSeite(s); kopfRef.current = s.kopf; setKopfZustand(s.kopf); aktuell.current = s.inhalt.trim(); })
      .catch((e) => setFehler(e.message));
    fetch(BASIS + "/_editor.html", { credentials: "same-origin" })
      .then((r) => { if (!r.ok) throw new Error("Der Seitenrahmen ließ sich nicht bauen (Fehler " + r.status + ")"); return r.text(); })
      .then(setHuelle).catch((e) => setFehler(e.message));
  }, [pfad]);

  const doc = () => rahmen.current && rahmen.current.contentDocument;
  const main = () => { const d = doc(); return d && d.querySelector("main"); };

  // ------------------------------------------------ Speichern
  const setKopf = (k) => { kopfRef.current = k; setKopfZustand(k); markieren(); };
  function markieren() {
    setSpeicher((s) => ({ ...s, stand: "ungespeichert" }));
    clearTimeout(timer.current.speichern);
    timer.current.speichern = setTimeout(() => speichern(), 1500);
  }
  async function speichern() {
    clearTimeout(timer.current.speichern);
    if (timer.current.eingabe) { clearTimeout(timer.current.eingabe); timer.current.eingabe = 0; uebernehmen(); }
    if (speicherStand() === "gespeichert" || speicherStand() === "speichert") return true;
    setSpeicher((s) => ({ ...s, stand: "speichert" }));
    try {
      await api("/webspace/seite", { methode: "POST", daten: { pfad, kopf: kopfRef.current, inhalt: aktuell.current } });
      setSpeicher({ stand: "gespeichert", zeit: Date.now() / 1000 });
      aufGeaendert();
      return true;
    } catch (e) { setSpeicher((s) => ({ ...s, stand: "fehler", text: e.message })); fehlerMelden(e); return false; }
  }
  const speicherRef = useRef(speicher);
  speicherRef.current = speicher;
  const speicherStand = () => speicherRef.current.stand;
  sichernRef.current = { sichern: speichern };
  useEffect(() => {
    // Beim Verlassen der Seite (Tab zu) noch schnell sichern.
    const weg = () => {
      if (speicherStand() !== "ungespeichert") return;
      fetch("/api/webspace/seite", { method: "POST", keepalive: true, credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pfad, kopf: kopfRef.current, inhalt: aktuell.current }) });
    };
    addEventListener("beforeunload", weg);
    return () => { removeEventListener("beforeunload", weg); clearTimeout(timer.current.speichern); clearTimeout(timer.current.eingabe); };
  }, [pfad]);

  // ------------------------------------------------ Fassungen (Rückgängig)
  function merken(s) {
    const h = hist.current;
    if (h.liste[h.i] === s) return;
    h.liste = h.liste.slice(0, h.i + 1);
    h.liste.push(s);
    if (h.liste.length > 300) h.liste.shift();
    h.i = h.liste.length - 1;
    setHistNr((n) => n + 1);
  }
  // Den Stand aus dem Rahmen übernehmen (nach Tippen oder einer Strukturänderung).
  function uebernehmen() {
    const m = main();
    if (!m || fassungAnsicht) return;
    const s = ausEditor(m);
    if (s === aktuell.current) return;
    aktuell.current = s;
    merken(s);
    markieren();
  }
  function setzen(s, { merkenAuch = true } = {}) {
    aktuell.current = s;
    if (merkenAuch) merken(s);
    rendern(s);
    markieren();
  }
  function rueckgaengig() {
    if (timer.current.eingabe) { clearTimeout(timer.current.eingabe); timer.current.eingabe = 0; uebernehmen(); }
    const h = hist.current;
    if (h.i <= 0) return;
    h.i--; setHistNr((n) => n + 1);
    setzen(h.liste[h.i], { merkenAuch: false });
  }
  function wiederholen() {
    const h = hist.current;
    if (h.i >= h.liste.length - 1) return;
    h.i++; setHistNr((n) => n + 1);
    setzen(h.liste[h.i], { merkenAuch: false });
  }

  // ------------------------------------------------ Rahmen
  function rendern(s, { lesen = false } = {}) {
    const m = main();
    if (!m) return;
    m.innerHTML = zuEditor(s);
    m.setAttribute("contenteditable", lesen ? "false" : "true");
    doc().documentElement.classList.toggle("ws-nurlesen", lesen);
    waehlen(null, null);
    zeichnen();
  }
  function eingerichtet() {
    const d = doc();
    const m = main();
    if (!d || !m) return;
    try { d.execCommand("defaultParagraphSeparator", false, "p"); } catch (e) { /* alt */ }
    // Unter dem Inhalt: "Abschnitt hinzufügen" (außerhalb von main, wird nie gespeichert).
    const ende = d.createElement("div");
    ende.className = "ws-ende";
    ende.innerHTML = '<button type="button">＋ Abschnitt hinzufügen</button>';
    ende.querySelector("button").addEventListener("click", () => fn.current.bibliothek(null));
    m.after(ende);
    const ui = d.createElement("div");
    ui.id = "ws-ui";
    d.body.appendChild(ui);
    rendern(aktuell.current);
    const basis = ausEditor(m);
    aktuell.current = basis;
    hist.current = { liste: [basis], i: 0 };
    setHistNr((n) => n + 1);
    rahmenEreignisse(d);
  }

  function blockVon(el) {
    const m = main();
    if (!m || !el) return null;
    let b = el.nodeType === 1 ? el : el.parentElement;
    while (b && b.parentElement !== m) b = b.parentElement;
    return b && b.parentElement === m ? b : null;
  }
  function elementVon(t) {
    if (!t || t.nodeType !== 1) return null;
    return t.closest(".ws-marke, img, .video, a, h1, h2, h3, h4, blockquote, figcaption, li, p, hr, .abstand, .karte, .band-innen, .band") || null;
  }
  function waehlen(block, el) {
    ausw.current = { block, el };
    setAuswahlNr((n) => n + 1);
    if (block) setRechts((r) => (r === "verlauf" ? "eigenschaften" : r));
    zeichnen();
  }

  // Die Rahmen um Abschnitte, die Abschnitts-Leiste und das Plus.
  function zeichnen() {
    const d = doc();
    if (!d) return;
    const ui = d.getElementById("ws-ui");
    if (!ui) return;
    const w = d.defaultView;
    const pos = (el) => { const r = el.getBoundingClientRect(); return { l: r.left + w.scrollX, t: r.top + w.scrollY, b: r.width, h: r.height }; };
    const box = (el, kl) => { const p = pos(el); return `<div class="ws-box ${kl}" style="left:${p.l}px;top:${p.t}px;width:${p.b}px;height:${p.h}px"></div>`; };
    const { block, el } = ausw.current;
    const h = hover.current;
    let s = "";
    if (h && h !== block && h.isConnected) s += box(h, "hover");
    if (block && block.isConnected) s += box(block, "block");
    if (el && el !== block && el.isConnected) s += box(el, "el");
    const leisteFuer = (h && h.isConnected) ? h : (block && block.isConnected ? block : null);
    if (leisteFuer && !d.documentElement.classList.contains("ws-nurlesen")) {
      const p = pos(leisteFuer);
      const art = abschnittArt(leisteFuer);
      const oben = Math.max(p.t + 6, w.scrollY + 6);
      s += `<div class="ws-leiste" style="left:${p.l + p.b - 8}px;top:${Math.min(oben, p.t + p.h - 34)}px">
        <button class="griff" data-a="ziehen" title="Ziehen zum Verschieben">⠿</button><span class="name">${art.name}</span>
        <button data-a="hoch" title="Nach oben">↑</button><button data-a="runter" title="Nach unten">↓</button>
        <button data-a="kopie" title="Duplizieren">⧉</button><button data-a="ki" title="Mit der KI bearbeiten">✦</button>
        <button data-a="weg" class="weg" title="Abschnitt löschen">🗑</button></div>
        <button class="ws-plus" data-a="plus" style="left:${p.l + p.b / 2}px;top:${p.t + p.h}px" title="Abschnitt darunter einfügen">＋</button>`;
      ui.dataset.fuer = "";
      ui._fuer = leisteFuer;
    } else ui._fuer = null;
    ui.innerHTML = s;
  }

  function rahmenEreignisse(d) {
    const w = d.defaultView;
    let rafAn = false;
    const neuZeichnen = () => { if (rafAn) return; rafAn = true; w.requestAnimationFrame(() => { rafAn = false; zeichnen(); }); };
    d.addEventListener("mousemove", (e) => {
      if (d.documentElement.classList.contains("ws-zieht")) return;
      if (e.target.closest && e.target.closest("#ws-ui")) return;
      const b = blockVon(e.target);
      if (b !== hover.current) { hover.current = b; neuZeichnen(); }
    });
    d.addEventListener("mouseleave", () => { hover.current = null; neuZeichnen(); });
    w.addEventListener("scroll", neuZeichnen, { passive: true });
    w.addEventListener("resize", neuZeichnen);
    // Klicks: Abschnitts-Leiste, Links im Text (nicht folgen), Auswahl.
    d.addEventListener("click", (e) => {
      const knopf = e.target.closest && e.target.closest("#ws-ui [data-a]");
      if (knopf) { e.preventDefault(); fn.current.leiste(knopf.dataset.a, d.getElementById("ws-ui")._fuer); return; }
      if (e.target.closest("a")) e.preventDefault();
      if (e.target.closest(".ws-ende, header, footer")) { if (!e.target.closest(".ws-ende")) e.preventDefault(); return; }
      const b = blockVon(e.target);
      fn.current.waehlen(b, elementVon(e.target));
    }, true);
    d.addEventListener("pointerdown", (e) => {
      const g = e.target.closest && e.target.closest("#ws-ui [data-a=ziehen]");
      if (g) { e.preventDefault(); fn.current.ziehen(e, d.getElementById("ws-ui")._fuer); }
    });
    d.addEventListener("input", () => {
      clearTimeout(timer.current.eingabe);
      timer.current.eingabe = setTimeout(() => { timer.current.eingabe = 0; fn.current.uebernehmen(); }, 450);
      setSpeicher((s) => (s.stand === "ungespeichert" ? s : { ...s, stand: "ungespeichert" }));
      neuZeichnen();
      // "/" in einer leeren Zeile öffnet die Abschnitte (wie in Notion und WordPress).
      const sel = d.getSelection();
      const n = sel && sel.anchorNode && (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement);
      const zeile = n && n.closest("p, h2, h3, h4");
      if (zeile && zeile.textContent === "/") fn.current.bibliothek(blockVon(zeile), zeile);
    });
    // Dreifachklick markiert im Browser über das Absatzende hinaus; wer dann tippt,
    // zieht den nächsten Absatz (z. B. die Quelle eines Zitats) mit hinein.
    // Deshalb: genau den Inhalt des angeklickten Absatzes markieren.
    d.addEventListener("mouseup", (e) => {
      if (e.detail < 3) return;
      const z = e.target.closest && e.target.closest("p, h1, h2, h3, h4, li, cite, figcaption");
      if (!z) return;
      const r = d.createRange();
      r.selectNodeContents(z);
      const s = d.getSelection();
      s.removeAllRanges(); s.addRange(r);
    });
    d.addEventListener("keydown", (e) => fn.current.taste(e));
    d.addEventListener("paste", (e) => fn.current.einfuegen(e));
    d.addEventListener("dragover", (e) => { if ([...(e.dataTransfer.items || [])].some((i) => i.kind === "file")) e.preventDefault(); });
    d.addEventListener("drop", (e) => {
      const dateien = [...(e.dataTransfer.files || [])].filter((f) => /^image\//.test(f.type));
      if (!dateien.length) return;
      e.preventDefault();
      fn.current.bildHochUndEinfuegen(dateien[0], blockVon(e.target));
    });
  }

  // ------------------------------------------------ Abschnitte
  function neueKnoten(htmlText) {
    const t = doc().createElement("template");
    t.innerHTML = zuEditor(htmlText);
    return [...t.content.childNodes].filter((n) => n.nodeType === 1);
  }
  function einfuegenNach(nach, htmlText) {
    const m = main();
    const knoten = neueKnoten(htmlText);
    let ref = nach;
    for (const k of knoten) {
      if (ref) ref.after(k); else m.appendChild(k);
      ref = k;
    }
    uebernehmen();
    const erster = knoten[0];
    if (erster) { erster.scrollIntoView({ block: "center", behavior: "smooth" }); blitzen(erster); waehlen(erster, erster); }
    return knoten;
  }
  function blitzen(el) {
    const d = doc(); const ui = d && d.getElementById("ws-ui");
    if (!ui || !el) return;
    setTimeout(() => {
      const r = el.getBoundingClientRect(), w = d.defaultView;
      const b = d.createElement("div");
      b.className = "ws-box blitz";
      b.style.cssText = `left:${r.left + w.scrollX}px;top:${r.top + w.scrollY}px;width:${r.width}px;height:${r.height}px`;
      ui.appendChild(b);
      setTimeout(() => { b.style.opacity = "0"; }, 400);
      setTimeout(() => b.remove(), 1700);
    }, 350);
  }
  function leiste(a, block) {
    if (!block) return;
    if (a === "hoch" && block.previousElementSibling) { block.previousElementSibling.before(block); uebernehmen(); waehlen(block, block); }
    if (a === "runter" && block.nextElementSibling) { block.nextElementSibling.after(block); uebernehmen(); waehlen(block, block); }
    if (a === "kopie") { const k = block.cloneNode(true); block.after(k); uebernehmen(); blitzen(k); waehlen(k, k); }
    if (a === "weg") {
      const art = abschnittArt(block).name;
      block.remove(); hover.current = null; uebernehmen(); waehlen(null, null);
      toast(`Abschnitt „${art}“ gelöscht.`, { dauer: 10000, aktion: { text: "Rückgängig", fn: rueckgaengig } });
    }
    if (a === "plus") setBibliothek({ nach: block });
    if (a === "ki") { waehlen(block, block); setRechts("ki"); }
  }
  // Ziehen über Pointer Events (nie natives Drag, siehe CLAUDE.md).
  function ziehen(e, block) {
    const d = doc(), m = main(), w = d.defaultView;
    if (!block) return;
    d.documentElement.classList.add("ws-zieht");
    const ui = d.getElementById("ws-ui");
    const linie = d.createElement("div");
    linie.className = "ws-linie";
    let ziel = null;
    const bewegen = (ev) => {
      const bloecke = [...m.children].filter((b) => b !== block);
      let vor = null;
      for (const b of bloecke) { const r = b.getBoundingClientRect(); if (ev.clientY < r.top + r.height / 2) { vor = b; break; } }
      ziel = { vor };
      const ref = vor ? vor.getBoundingClientRect() : (bloecke.length ? bloecke[bloecke.length - 1].getBoundingClientRect() : m.getBoundingClientRect());
      const y = vor ? ref.top : ref.bottom;
      linie.style.cssText = `left:${ref.left + w.scrollX + 20}px;width:${ref.width - 40}px;top:${y + w.scrollY - 2}px`;
      if (!linie.isConnected) ui.appendChild(linie);
      // Am Rand automatisch scrollen.
      if (ev.clientY < 60) w.scrollBy(0, -18); else if (ev.clientY > w.innerHeight - 60) w.scrollBy(0, 18);
    };
    const los = () => {
      d.removeEventListener("pointermove", bewegen);
      d.removeEventListener("pointerup", los);
      d.documentElement.classList.remove("ws-zieht");
      linie.remove();
      if (ziel) { if (ziel.vor) ziel.vor.before(block); else m.appendChild(block); uebernehmen(); blitzen(block); waehlen(block, block); }
    };
    d.addEventListener("pointermove", bewegen);
    d.addEventListener("pointerup", los);
  }

  // ------------------------------------------------ Tasten, Einfügen, Bilder
  function taste(e) {
    const strg = e.ctrlKey || e.metaKey;
    const k = e.key.toLowerCase();
    if (strg && k === "z" && !e.shiftKey) { e.preventDefault(); rueckgaengig(); return; }
    if (strg && (k === "y" || (k === "z" && e.shiftKey))) { e.preventDefault(); wiederholen(); return; }
    if (strg && k === "s") { e.preventDefault(); speichern().then((ok) => ok && toast("Gespeichert.")); return; }
    if (strg && k === "k") { e.preventDefault(); linkOeffnen(); return; }
    if (e.key === "Escape") { if (ausw.current.block) { e.preventDefault(); e.stopPropagation(); waehlen(null, null); } }
  }
  function einfuegen(e) {
    const cd = e.clipboardData;
    if (!cd) return;
    const bild = [...(cd.files || [])].find((f) => /^image\//.test(f.type));
    if (bild) { e.preventDefault(); bildHochUndEinfuegen(bild, ausw.current.block); return; }
    const h = cd.getData("text/html");
    if (h) { e.preventDefault(); doc().execCommand("insertHTML", false, saeubern(h)); return; }
    const t = cd.getData("text/plain");
    if (t && t.includes("\n")) {
      e.preventDefault();
      const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
      doc().execCommand("insertHTML", false, t.split(/\n{2,}|\r\n\r\n/).map((a) => `<p>${esc(a.trim()).replace(/\n/g, "<br>")}</p>`).join(""));
    }
  }
  async function bildHoch(datei) {
    const fd = new FormData(); fd.append("datei", datei, datei.name || "bild.png");
    const r = await fetch("/api/webspace/bild", { method: "POST", body: fd, credentials: "same-origin" });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || "Hochladen gescheitert");
    return d.pfad;
  }
  async function bildHochUndEinfuegen(datei, nach) {
    try {
      toast("Bild wird hochgeladen …");
      const p = await bildHoch(datei);
      einfuegenNach(nach || [...main().children].pop() || null, `<div class="fliess">\n<figure class="mittel"><img src="${p}" alt=""><figcaption></figcaption></figure>\n</div>`);
      toast("Bild eingefügt. Rechts eine Bildbeschreibung eintragen.");
    } catch (x) { fehlerMelden(x); }
  }

  // ------------------------------------------------ Formatieren
  function befehl(b, wert) {
    const d = doc();
    if (!d || fassungAnsicht) return;
    rahmen.current.contentWindow.focus();
    d.execCommand(b, false, wert);
    uebernehmen();
  }
  const markierung = useRef(null);
  function linkOeffnen() {
    const d = doc();
    const s = d && d.getSelection();
    markierung.current = s && s.rangeCount ? s.getRangeAt(0).cloneRange() : null;
    const a = s && s.anchorNode && (s.anchorNode.nodeType === 1 ? s.anchorNode : s.anchorNode.parentElement).closest("a");
    setLinkPop({ href: a ? a.getAttribute("href") : "" });
  }
  function linkSetzen(url) {
    const d = doc();
    rahmen.current.contentWindow.focus();
    if (markierung.current) { const s = d.getSelection(); s.removeAllRanges(); s.addRange(markierung.current); }
    if (!url) d.execCommand("unlink");
    else {
      d.execCommand("createLink", false, url);
      const s = d.getSelection();
      const n = s.anchorNode && (s.anchorNode.nodeType === 1 ? s.anchorNode : s.anchorNode.parentElement);
      const a = n && n.closest("a");
      if (a) { if (/^https?:/.test(url)) { a.target = "_blank"; a.rel = "noopener"; } else { a.removeAttribute("target"); a.removeAttribute("rel"); } }
    }
    setLinkPop(null);
    uebernehmen();
  }

  // ------------------------------------------------ KI
  async function kiAuftrag(auftrag, art) {
    const { block } = ausw.current;
    const daten = { pfad, kopf: kopfRef.current, inhalt: aktuell.current, auftrag };
    if (art === "abschnitt" && block) daten.abschnitt = ausEditor(einzeln(block));
    if (art === "neu") daten.neu = true;
    const r = await api("/webspace/assistent", { methode: "POST", daten });
    if (r.art === "abschnitt" && block && block.isConnected) {
      const knoten = neueKnoten(r.inhalt);
      if (!knoten.length) throw new Error("Die KI hat keinen Abschnitt geliefert.");
      block.replaceWith(...knoten);
      uebernehmen(); blitzen(knoten[0]); waehlen(knoten[0], knoten[0]);
    } else if (r.art === "neu") {
      einfuegenNach(block || [...main().children].pop() || null, r.inhalt);
    } else {
      setzen(r.inhalt);
    }
    setKiMeldung({ text: r.erklaerung, hinweise: r.hinweise, modell: r.modell });
  }
  function einzeln(block) {
    const wrap = doc().createElement("main");
    wrap.appendChild(block.cloneNode(true));
    return wrap;
  }

  fn.current = { leiste, ziehen, uebernehmen, taste, einfuegen, bildHochUndEinfuegen,
    waehlen: (b, el) => waehlen(b, el),
    bibliothek: (nach, ersetzen) => setBibliothek({ nach, ersetzen }) };

  // ------------------------------------------------ Tasten auch außerhalb des Rahmens
  useEffect(() => {
    const k = (e) => {
      if (e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); speichern(); }
        return;
      }
      const strg = e.ctrlKey || e.metaKey, t = e.key.toLowerCase();
      if (strg && t === "s") { e.preventDefault(); speichern().then((ok) => ok && toast("Gespeichert.")); }
      else if (strg && t === "z" && !e.shiftKey && modus === "visuell") { e.preventDefault(); rueckgaengig(); }
      else if (strg && (t === "y" || (t === "z" && e.shiftKey)) && modus === "visuell") { e.preventDefault(); wiederholen(); }
    };
    document.addEventListener("keydown", k);
    return () => document.removeEventListener("keydown", k);
  }, [modus, pfad]);

  function modusWechseln(m) {
    if (m === modus) return;
    if (m === "code") { uebernehmen(); setCodeText(aktuell.current); }
    else { if (codeText !== aktuell.current) setzen(codeText); else rendern(aktuell.current); }
    setModus(m);
  }
  function geraetWaehlen(g) { setGeraet(g); try { localStorage.setItem("ws-geraet", g); } catch (e) { /* egal */ } setTimeout(zeichnen, 60); }

  if (fehler) return html`<div class="karte" style="margin:16px"><h3>Seite lässt sich nicht laden</h3><p class="leise">${fehler}</p></div>`;
  if (!seite || !kopf) return html`<div class="leise" style="padding:20px">Seite wird geladen …</div>`;

  const srcdoc = huelle ? huelle.replace("<!--EDITOR-->", "").replace("</head>", `<style>${EDITOR_CSS}</style></head>`) : null;
  const h = hist.current;
  const breite = (GERAETE.find((g) => g[0] === geraet) || [])[2];

  return html`<div class="wse">
    <div class="wse-kopf">
      <div class="wse-titel"><b title=${kopf.titel}>${kopf.titel}</b>
        <span class="leise"><a href=${stand.live + seite.adresse} target="_blank" rel="noopener" title="Die veröffentlichte Seite öffnen">${seite.adresse}</a> · <${SpeicherStand} s=${speicher} jetzt=${() => speichern()} /></span></div>
      <div class="segment wse-geraete" role="group" aria-label="Gerät">
        ${GERAETE.map(([id, name]) => html`<button class=${geraet === id ? "an" : ""} title=${"Ansicht: " + name} aria-label=${name} onClick=${() => geraetWaehlen(id)}><span class=${"ws-ger " + id}></span></button>`)}
      </div>
      <span class="knopfreihe">
        <button class="btn geist icon" title="Rückgängig (Strg+Z)" aria-label="Rückgängig" disabled=${h.i <= 0 || modus !== "visuell"} onClick=${rueckgaengig}><${Icon} n="undo" g=${16} /></button>
        <button class="btn geist icon" title="Wiederholen (Strg+Y)" aria-label="Wiederholen" disabled=${h.i >= h.liste.length - 1 || modus !== "visuell"} onClick=${wiederholen}><span style="display:inline-block;transform:scaleX(-1)"><${Icon} n="undo" g=${16} /></span></button>
        <button class=${"btn klein" + (modus === "code" ? " primaer" : "")} title="HTML der Seite bearbeiten" onClick=${() => modusWechseln(modus === "code" ? "visuell" : "code")}>${"</>"}</button>
        <a class="btn klein" href=${BASIS + seite.adresse} target="_blank" rel="noopener" title="Vorschau mit allen Funktionen in neuem Tab (gespeicherter Stand)"><${Icon} n="auge" g=${14} />Vorschau</a>
        ${kopfLeiste}
      </span>
    </div>
    ${modus === "visuell" && !fassungAnsicht && html`<${Werkzeug} befehl=${befehl} link=${linkOeffnen} einfuegen=${() => setBibliothek({ nach: ausw.current.block })} />`}
    <div class="wse-mitte">
      <div class=${"wse-flaeche" + (breite ? " geraet" : "")}>
        ${fassungAnsicht && html`<div class="wse-banner violett"><span><b>Du siehst die Fassung vom ${new Date(fassungAnsicht.zeit).toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" })}</b> — „${fassungAnsicht.text}“. Nur zum Ansehen.</span>
          <span class="knopfreihe"><button class="btn klein primaer" onClick=${() => { const s = fassungAnsicht.inhalt; setFassungAnsicht(null); setzen(s); toast("Diese Fassung ist jetzt dein Entwurf. Veröffentlichen nicht vergessen."); }}>Diese Fassung wiederherstellen</button>
          <button class="btn klein" onClick=${() => { setFassungAnsicht(null); rendern(aktuell.current); }}>Zurück zur aktuellen</button></span></div>`}
        ${kiMeldung && html`<div class="wse-banner gruen"><span><b>KI-Änderung übernommen</b> <span class="leise">(${kiMeldung.modell})</span>${kiMeldung.text ? " — " + kiMeldung.text : ""}
            ${(kiMeldung.hinweise || []).map((x) => html`<br /><span class="leise klein">${x}</span>`)}</span>
          <span class="knopfreihe"><button class="btn klein" onClick=${() => { rueckgaengig(); setKiMeldung(null); }}>Rückgängig</button>
          <button class="btn klein geist" onClick=${() => setKiMeldung(null)}>OK</button></span></div>`}
        ${srcdoc ? html`<iframe ref=${rahmen} class="wse-rahmen" style=${(breite ? `width:${breite}px;` : "") + (modus === "code" ? "display:none" : "")} srcdoc=${srcdoc} onLoad=${eingerichtet} title="Seite bearbeiten"></iframe>`
          : html`<div class="leise" style="padding:20px">Seitenrahmen wird gebaut …</div>`}
        ${modus === "code" && html`<textarea class="wse-code" spellcheck="false" value=${codeText} aria-label="HTML der Seite"
          onInput=${(e) => { setCodeText(e.target.value); aktuell.current = e.target.value; markieren(); }}></textarea>`}
      </div>
      <aside class="wse-rechts">
        <div class="segment wse-tabs">
          ${[["eigenschaften", "Eigenschaften"], ["ki", "✦ KI"], ["verlauf", "Verlauf"]].map(([id, t]) => html`<button class=${rechts === id ? "an" : ""} onClick=${() => setRechts(id)}>${t}</button>`)}
        </div>
        <div class="wse-rechts-inhalt" key=${auswahlNr + "-" + rechts}>
          ${rechts === "eigenschaften" && (ausw.current.block && ausw.current.block.isConnected
            ? html`<${Eigenschaften} ausw=${ausw.current} stand=${stand} doc=${doc()}
                geaendert=${() => { uebernehmen(); zeichnen(); setAuswahlNr((n) => n + 1); }}
                medien=${(waehle) => setMedien({ waehlen: waehle })} abwaehlen=${() => waehlen(null, null)}
                leiste=${(a) => leiste(a, ausw.current.block)} />`
            : html`<${SeitenEinstellungen} kopf=${kopf} setKopf=${setKopf} seite=${seite} pfad=${pfad} stand=${stand}
                medien=${(waehle) => setMedien({ waehlen: waehle })} geaendert=${aufGeaendert} geloescht=${geloescht} sichern=${speichern} />`)}
          ${rechts === "ki" && html`<${KiFeld} block=${ausw.current.block && ausw.current.block.isConnected ? ausw.current.block : null} auftrag=${kiAuftrag} />`}
          ${rechts === "verlauf" && html`<${Verlauf} pfad=${pfad} ansehen=${(f) => { uebernehmen(); setFassungAnsicht(f); rendern(f.inhalt, { lesen: true }); }} />`}
        </div>
      </aside>
    </div>
    ${bibliothek && html`<${Bibliothek} zu=${() => setBibliothek(null)} stand=${stand}
      waehlen=${(v) => {
        const { nach, ersetzen } = bibliothek;
        let ziel = nach;
        if (ersetzen && ersetzen.isConnected) {
          // Die Zeile mit dem "/" verschwindet; war sie allein im Abschnitt, der ganze Abschnitt.
          // Steht danach noch Text im selben Abschnitt, wird er an dieser Stelle geteilt --
          // der neue Abschnitt landet genau dort, wo das "/" stand (wie in Notion/WordPress).
          const b = blockVon(ersetzen);
          if (b && b.textContent.trim() === "/") { ziel = b.previousElementSibling; b.remove(); }
          else if (b && ersetzen.parentElement === b && ersetzen.nextElementSibling) {
            const rest = b.cloneNode(false);
            while (ersetzen.nextSibling) rest.appendChild(ersetzen.nextSibling);
            ersetzen.remove();
            b.after(rest);
            ziel = b;
          } else ersetzen.remove();
        }
        setBibliothek(null);
        const knoten = einfuegenNach(ziel, v.html);
        if (v.medien && knoten[0]) {
          const img = knoten[0].querySelector("img");
          setMedien({ waehlen: (p) => { img.setAttribute("src", BASIS + p); uebernehmen(); setAuswahlNr((n) => n + 1); } });
        }
        if (v.id === "video") setRechts("eigenschaften");
      }}
      ki=${async (auftrag) => { setBibliothek(null); const { nach } = bibliothek; if (nach) waehlen(nach, nach); try { toast("Die KI schreibt den Abschnitt … (etwa eine halbe Minute)"); await kiAuftrag(auftrag, "neu"); } catch (e) { fehlerMelden(e); } }} />`}
    ${medien && html`<${MedienWahl} zu=${() => setMedien(null)} waehlen=${(p) => { medien.waehlen(p); setMedien(null); }} />`}
    ${linkPop && html`<${LinkFenster} wert=${linkPop.href} stand=${stand} zu=${() => setLinkPop(null)} setzen=${linkSetzen} />`}
  </div>`;
}

function SpeicherStand({ s, jetzt }) {
  const [, tick] = useState(0);
  useEffect(() => { const i = setInterval(() => tick((n) => n + 1), 10000); return () => clearInterval(i); }, []);
  if (s.stand === "speichert") return html`<span class="ws-speicher">Speichert …</span>`;
  if (s.stand === "ungespeichert") return html`<span class="ws-speicher gelb">Ungespeicherte Änderungen</span>`;
  if (s.stand === "fehler") return html`<button class="ws-speicher rot" onClick=${jetzt} title=${s.text}>Speichern gescheitert — erneut versuchen</button>`;
  return html`<span class="ws-speicher gruen" title="Gespeichert, aber noch nicht veröffentlicht">✓ Gespeichert${s.zeit ? " " + zeitText(s.zeit) : ""}</span>`;
}

// ---------------------------------------------------------------- Format-Leiste
function Werkzeug({ befehl, link, einfuegen }) {
  const k = (titel, inhalt, f) => html`<button class="btn geist icon klein" title=${titel} aria-label=${titel}
    onMouseDown=${(e) => { e.preventDefault(); f(); }}>${inhalt}</button>`;
  return html`<div class="wse-werkzeug" role="toolbar" aria-label="Formatieren">
    <select class="eingabe wse-format" title="Absatzformat" onMouseDown=${(e) => e.stopPropagation()}
      onChange=${(e) => { befehl("formatBlock", e.target.value); e.target.value = ""; }}>
      <option value="">Format …</option><option value="p">Absatz</option><option value="h1">Überschrift 1</option>
      <option value="h2">Überschrift 2</option><option value="h3">Überschrift 3</option><option value="blockquote">Zitat</option>
    </select>
    <span class="ws-trenner"></span>
    ${k("Fett (Strg+B)", html`<b>B</b>`, () => befehl("bold"))}
    ${k("Kursiv (Strg+I)", html`<i style="font-family:serif">I</i>`, () => befehl("italic"))}
    ${k("Unterstrichen (Strg+U)", html`<u>U</u>`, () => befehl("underline"))}
    ${k("Link (Strg+K)", html`<${Icon} n="extern" g=${15} />`, link)}
    <span class="ws-trenner"></span>
    ${k("Aufzählung", html`<${Icon} n="liste" g=${15} />`, () => befehl("insertUnorderedList"))}
    ${k("Nummerierte Liste", html`<b style="font-size:12px">1.</b>`, () => befehl("insertOrderedList"))}
    <span class="ws-trenner"></span>
    ${k("Linksbündig", html`<span class="ws-ausr l"></span>`, () => befehl("justifyLeft"))}
    ${k("Zentriert", html`<span class="ws-ausr m"></span>`, () => befehl("justifyCenter"))}
    ${k("Formatierung entfernen", html`<span style="text-decoration:line-through;font-weight:700">T</span>`, () => befehl("removeFormat"))}
    <span class="ws-trenner"></span>
    <button class="btn klein" onMouseDown=${(e) => { e.preventDefault(); einfuegen(); }} title="Abschnitt einfügen (oder „/“ in einer leeren Zeile tippen)"><${Icon} n="plus" g=${14} />Abschnitt</button>
    <span class="ws-hinweis leise">Klick in die Seite und schreib · Abschnitt anklicken für Einstellungen · „/“ für neuen Abschnitt</span>
  </div>`;
}

// ---------------------------------------------------------------- Abschnitt einfügen
function Bibliothek({ zu, waehlen, ki, stand }) {
  const [suche, setSuche] = useState("");
  const [auftrag, setAuftrag] = useState("");
  const [bausteine, setBausteine] = useState([]);
  useEffect(() => { api("/webspace/bausteine").then((d) => setBausteine(d.bausteine || [])).catch(() => {}); }, []);
  const q = suche.trim().toLowerCase();
  const liste = VORLAGEN.filter((v) => !q || (v.name + " " + v.text + " " + v.gruppe).toLowerCase().includes(q));
  const gruppen = [...new Set(liste.map((v) => v.gruppe))];
  return html`<${Modal} titel="Abschnitt einfügen" zu=${zu} breit=${true}>
    <div class="wsb-ki">
      <b>✦ Von der KI schreiben lassen</b>
      <div class="wsb-ki-zeile"><input class="eingabe" placeholder="z. B. „Ein Abschnitt über meine Vorträge mit drei Stichpunkten“"
        value=${auftrag} onInput=${(e) => setAuftrag(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter" && auftrag.trim()) ki(auftrag.trim()); }} />
      <button class="btn primaer" disabled=${!auftrag.trim()} onClick=${() => ki(auftrag.trim())}>Schreiben lassen</button></div>
    </div>
    <input class="eingabe wsb-suche" autofocus placeholder="Abschnitt suchen … (Text, Bild, Karten, Video …)" value=${suche} onInput=${(e) => setSuche(e.target.value)}
      onKeyDown=${(e) => { if (e.key === "Enter" && liste[0]) waehlen(liste[0]); }} />
    ${gruppen.map((g) => html`<div class="wsb-gruppe">${g}</div>
      <div class="wsb-raster">${liste.filter((v) => v.gruppe === g).map((v) => html`<button class="wsb-kachel" onClick=${() => waehlen(v)}>
        <span class=${"wsb-vorschau wsb-v-" + v.id}></span><b>${v.name}</b><span class="leise">${v.text}</span></button>`)}</div>`)}
    ${!q && bausteine.length > 0 && html`<div class="wsb-gruppe">Interaktive Bausteine (bereits gebaut)</div>
      <div class="wsb-raster">${bausteine.map((b) => html`<button class="wsb-kachel" onClick=${() => waehlen({ id: "baustein", html: `<!--baustein ${b}-->` })}>
        <span class="wsb-vorschau wsb-v-baustein"></span><b>${b}</b><span class="leise">fertig programmiert, wird eingesetzt</span></button>`)}</div>`}
  <//>`;
}

// ---------------------------------------------------------------- Link setzen
function LinkFenster({ wert, stand, zu, setzen }) {
  const [url, setUrl] = useState(wert || "");
  const vorschlaege = stand.seiten.filter((s) => !url || (s.titel + " " + s.adresse).toLowerCase().includes(url.toLowerCase())).slice(0, 8);
  return html`<${Modal} titel="Link setzen" zu=${zu}
    fuss=${html`${wert ? html`<button class="btn gefahr" onClick=${() => setzen("")}>Link entfernen</button>` : ""}<span class="luecke"></span>
      <button class="btn geist" onClick=${zu}>Abbrechen</button><button class="btn primaer" disabled=${!url.trim()} onClick=${() => setzen(url.trim())}>Übernehmen</button>`}>
    <div class="feld"><label>Adresse — eine deiner Seiten oder eine Web-Adresse (https://…)</label>
      <input class="eingabe" autofocus value=${url} placeholder="Seite suchen oder https://… eintragen" onInput=${(e) => setUrl(e.target.value)}
        onKeyDown=${(e) => { if (e.key === "Enter" && url.trim()) setzen(url.trim()); }} /></div>
    <div class="wsl-liste">${vorschlaege.map((s) => html`<button onClick=${() => setzen(s.adresse)}><b>${s.titel}</b><span class="leise">${s.adresse}</span></button>`)}</div>
    <p class="leise klein">Links auf fremde Seiten öffnen sich automatisch in einem neuen Tab.</p>
  <//>`;
}

// ---------------------------------------------------------------- Medien wählen
export function MedienWahl({ zu, waehlen }) {
  const [liste, setListe] = useState(null);
  const [laedt, setLaedt] = useState(false);
  const [suche, setSuche] = useState("");
  const feld = useRef(null);
  const laden = () => api("/webspace/medien").then((d) => setListe(d.medien)).catch(fehlerMelden);
  useEffect(() => { laden(); }, []);
  async function hoch(dateien) {
    if (!dateien.length) return;
    setLaedt(true);
    try {
      let letzter = null;
      for (const f of dateien) {
        const fd = new FormData(); fd.append("datei", f, f.name);
        const r = await fetch("/api/webspace/bild", { method: "POST", body: fd, credentials: "same-origin" });
        const d = await r.json();
        if (!r.ok) throw new Error(d.detail || "Hochladen gescheitert");
        letzter = d.pfad;
      }
      if (dateien.length === 1 && letzter) { waehlen(letzter); return; }
      laden();
    } catch (x) { fehlerMelden(x); }
    setLaedt(false);
  }
  const q = suche.trim().toLowerCase();
  const sichtbar = (liste || []).filter((m) => !m.video && (!q || m.pfad.includes(q)));
  return html`<${Modal} titel="Bild wählen" zu=${zu} breit=${true}>
    <div class="wsm-kopf" onDragOver=${(e) => e.preventDefault()} onDrop=${(e) => { e.preventDefault(); hoch([...e.dataTransfer.files].filter((f) => /^image\//.test(f.type))); }}>
      <button class="btn primaer" disabled=${laedt} onClick=${() => feld.current.click()}><${Icon} n="plus" g=${15} />${laedt ? "Lädt hoch …" : "Bild hochladen"}</button>
      <span class="leise">oder Bild hierher ziehen</span>
      <input ref=${feld} type="file" accept="image/*" multiple hidden onChange=${(e) => { const d = [...e.target.files]; e.target.value = ""; hoch(d); }} />
      <input class="eingabe wsm-suche" placeholder="Suchen …" value=${suche} onInput=${(e) => setSuche(e.target.value)} />
    </div>
    ${!liste ? html`<p class="leise">Lädt …</p>` : html`<div class="wsm-raster">${sichtbar.map((m) => html`<button class="wsm-bild" onClick=${() => waehlen(m.pfad)} title=${m.pfad}>
      <img src=${BASIS + m.pfad} alt="" loading="lazy" /><span>${m.pfad.slice(8)}</span></button>`)}</div>`}
  <//>`;
}

// ---------------------------------------------------------------- Eigenschaften
function Eigenschaften({ ausw, stand, doc, geaendert, medien, abwaehlen, leiste }) {
  const { block, el } = ausw;
  const art = abschnittArt(block);
  const tun = (f) => { f(); geaendert(); };
  const bild = el && el.tagName === "IMG" ? el : null;
  const link = el && el.closest && el.closest("a");
  const ueberschrift = el && /^H[1-4]$/.test(el.tagName) ? el : null;
  const absatz = el && (el.tagName === "P" || el.tagName === "LI" || el.tagName === "BLOCKQUOTE") && !link ? el : null;
  return html`<div class="wsp">
    <div class="wsp-kopf"><div><b>${art.name}</b><div class="leise klein">${kurzText(block, 70)}</div></div>
      <button class="btn geist icon klein" title="Auswahl aufheben (Esc)" onClick=${abwaehlen}><${Icon} n="x" g=${14} /></button></div>
    ${bild && html`<${BildEigenschaften} bild=${bild} tun=${tun} medien=${medien} stand=${stand} />`}
    ${link && html`<${LinkEigenschaften} a=${link} tun=${tun} stand=${stand} />`}
    ${ueberschrift && html`<${TextEigenschaften} el=${ueberschrift} tun=${tun} doc=${doc} ueber=${true} />`}
    ${absatz && html`<${TextEigenschaften} el=${absatz} tun=${tun} doc=${doc} />`}
    ${art.art === "band" && html`<${BandEigenschaften} band=${block} tun=${tun} medien=${medien} />`}
    ${art.art === "video" && html`<${VideoEigenschaften} block=${block} tun=${tun} />`}
    ${art.art === "abstand" && html`<${Gruppe} titel="Abstand"><${Regler} name="Höhe" min=${8} max=${240} einheit="px"
      wert=${parseInt(block.style.getPropertyValue("--abstand")) || 48} setzen=${(v) => tun(() => block.style.setProperty("--abstand", v + "px"))} /><//>`}
    ${art.art === "karten" && html`<${KartenEigenschaften} block=${block} el=${el} tun=${tun} />`}
    ${art.art === "spalten" && html`<${Gruppe} titel="Zwei Spalten"><button class="btn klein" onClick=${() => tun(() => { const s = block.querySelector(".spalten"); s.appendChild(s.firstElementChild); })}>Spalten tauschen</button><//>`}
    ${(art.art === "text" || art.art === "zitat" || art.art === "spalten" || art.art === "video") && html`<${Gruppe} titel="Ausrichtung des Abschnitts">
      <div class="segment">${[["", "Links"], ["mitte", "Zentriert"]].map(([k, t]) => html`<button class=${(k === "mitte") === block.classList.contains("mitte") ? "an" : ""}
        onClick=${() => tun(() => block.classList.toggle("mitte", k === "mitte"))}>${t}</button>`)}</div><//>`}
    ${(art.art === "baustein" || art.art === "blogliste") && html`<${Gruppe} titel="Fest eingebaut">
      <p class="klein">${art.art === "blogliste" ? "Hier erscheinen automatisch alle Blogartikel. Reihenfolge, Bild und Auszug stellst du am jeweiligen Artikel unter „Eigenschaften“ ein." : "Dieser Teil ist ein fertig programmierter, interaktiver Baustein. Du kannst ihn verschieben oder entfernen; inhaltlich ändern lässt er sich über Neo."}</p><//>`}
    <${Gruppe} titel="Abschnitt">
      <div class="wsp-aktionen">
        <button class="btn klein" onClick=${() => leiste("hoch")}>↑ Nach oben</button>
        <button class="btn klein" onClick=${() => leiste("runter")}>↓ Nach unten</button>
        <button class="btn klein" onClick=${() => leiste("kopie")}>⧉ Duplizieren</button>
        <button class="btn klein" onClick=${() => leiste("plus")}>＋ Darunter einfügen</button>
        <button class="btn klein gefahr" onClick=${() => leiste("weg")}>Löschen</button>
      </div>
    <//>
  </div>`;
}

function Gruppe({ titel, children }) {
  return html`<div class="wsp-gruppe"><div class="wsp-titel">${titel}</div>${children}</div>`;
}

function Regler({ name, wert, min, max, schritt = 1, einheit = "", setzen }) {
  const [w, setW] = useState(wert);
  return html`<label class="wsp-regler"><span>${name}</span>
    <input type="range" min=${min} max=${max} step=${schritt} value=${w} onInput=${(e) => { setW(Number(e.target.value)); setzen(Number(e.target.value)); }} />
    <span class="wsp-wert">${einheit === "%" ? Math.round(w * 100) + " %" : w + " " + einheit}</span></label>`;
}

function BildEigenschaften({ bild, tun, medien }) {
  const fig = bild.closest("figure");
  const [alt, setAlt] = useState(bild.getAttribute("alt") || "");
  const groesse = fig ? (["klein", "mittel", "voll"].find((k) => fig.classList.contains(k)) || "") : null;
  const unterschrift = fig && fig.querySelector("figcaption");
  return html`<${Gruppe} titel="Bild">
    <div class="wsp-bild"><img src=${bild.getAttribute("src")} alt="" />
      <button class="btn klein" onClick=${() => medien((p) => tun(() => bild.setAttribute("src", BASIS + p)))}>Bild austauschen</button></div>
    <div class="feld"><label>Bildbeschreibung (für Barrierefreiheit und Google)</label>
      <input class="eingabe" value=${alt} placeholder="Was ist auf dem Bild zu sehen?" onInput=${(e) => setAlt(e.target.value)}
        onChange=${(e) => tun(() => bild.setAttribute("alt", e.target.value))} /></div>
    ${fig && html`<div class="feld"><label>Größe</label><div class="segment">
      ${[["klein", "Klein"], ["mittel", "Mittel"], ["voll", "Volle Breite"], ["", "Original"]].map(([k, t]) => html`<button class=${groesse === k ? "an" : ""}
        onClick=${() => tun(() => { fig.classList.remove("klein", "mittel", "voll"); if (k) fig.classList.add(k); })}>${t}</button>`)}</div></div>
      <label class="wsp-haken"><input type="checkbox" checked=${!!unterschrift}
        onChange=${(e) => tun(() => { if (e.target.checked) { const c = fig.ownerDocument.createElement("figcaption"); c.textContent = "Bildunterschrift"; fig.appendChild(c); } else if (unterschrift) unterschrift.remove(); })} />
        Bildunterschrift anzeigen</label>`}
  <//>`;
}

function LinkEigenschaften({ a, tun, stand }) {
  const [href, setHref] = useState(a.getAttribute("href") || "");
  const [text, setText] = useState(a.textContent);
  const knopf = a.classList.contains("knopf");
  const neuesFenster = a.getAttribute("target") === "_blank";
  const setzeZiel = (v) => tun(() => { a.setAttribute("href", v); if (/^https?:/.test(v)) { a.target = "_blank"; a.rel = "noopener"; } });
  return html`<${Gruppe} titel=${knopf ? "Knopf" : "Link"}>
    <div class="feld"><label>Text</label><input class="eingabe" value=${text} onInput=${(e) => setText(e.target.value)} onChange=${(e) => tun(() => { a.textContent = e.target.value; })} /></div>
    <div class="feld"><label>Ziel</label>
      <select class="eingabe" value=${stand.seiten.some((s) => s.adresse === href) ? href : "_eigen"} onChange=${(e) => { if (e.target.value !== "_eigen") { setHref(e.target.value); setzeZiel(e.target.value); } }}>
        ${stand.seiten.map((s) => html`<option value=${s.adresse}>${s.titel} (${s.adresse})</option>`)}
        <option value="_eigen">Andere Adresse …</option>
      </select>
      <input class="eingabe" value=${href} placeholder="https://…" onInput=${(e) => setHref(e.target.value)} onChange=${(e) => setzeZiel(e.target.value.trim())} /></div>
    <label class="wsp-haken"><input type="checkbox" checked=${neuesFenster} onChange=${(e) => tun(() => { if (e.target.checked) { a.target = "_blank"; a.rel = "noopener"; } else { a.removeAttribute("target"); a.removeAttribute("rel"); } })} /> In neuem Tab öffnen</label>
    ${!knopf && html`<button class="btn klein" onClick=${() => tun(() => a.replaceWith(...a.childNodes))}>Link entfernen</button>`}
  <//>`;
}

function TextEigenschaften({ el, tun, doc, ueber }) {
  const groesse = parseInt(el.style.fontSize) || 0;
  const ausr = el.style.textAlign || "";
  const ebenen = [["H1", "Ü1"], ["H2", "Ü2"], ["H3", "Ü3"], ["P", "Text"]];
  function ebene(tag) {
    tun(() => {
      const n = doc.createElement(tag);
      [...el.attributes].forEach((x) => n.setAttribute(x.name, x.value));
      while (el.firstChild) n.appendChild(el.firstChild);
      el.replaceWith(n);
    });
  }
  return html`<${Gruppe} titel=${ueber ? "Überschrift" : "Text"}>
    ${(ueber || el.tagName === "P") && html`<div class="feld"><label>Art</label><div class="segment">${ebenen.map(([t, n]) => html`<button class=${el.tagName === t ? "an" : ""} onClick=${() => ebene(t)}>${n}</button>`)}</div></div>`}
    <div class="feld"><label>Schriftgröße</label><div class="wsp-zeile">
      <div class="segment"><button class=${!groesse ? "an" : ""} onClick=${() => tun(() => { el.style.fontSize = ""; el.style.lineHeight = ""; })}>Standard</button></div>
      <${Regler} name="" min=${12} max=${80} einheit="px" wert=${groesse || (ueber ? 42 : 18)} setzen=${(v) => tun(() => { el.style.fontSize = v + "px"; el.style.lineHeight = v > 30 ? "1.2" : "1.6"; })} /></div></div>
    <div class="feld"><label>Ausrichtung</label><div class="segment">
      ${[["", "Standard"], ["left", "Links"], ["center", "Mitte"], ["right", "Rechts"]].map(([k, t]) => html`<button class=${ausr === k ? "an" : ""} onClick=${() => tun(() => { el.style.textAlign = k; })}>${t}</button>`)}</div></div>
  <//>`;
}

function BandEigenschaften({ band, tun, medien }) {
  const bildEl = band.querySelector(":scope > .band-bild");
  const url = bildEl ? (bildEl.style.backgroundImage.match(/url\(["']?([^"')]+)/) || [])[1] : null;
  const deck = bildEl ? (parseFloat(bildEl.style.opacity) || 1) : 1;
  const hoehe = parseInt(band.style.getPropertyValue("--h")) || 260;
  const effekt = band.dataset.effekt || "";
  const innen = band.querySelector(".band-innen");
  const mitte = innen && innen.style.textAlign === "center";
  function bildSetzen(p) {
    tun(() => {
      let b = band.querySelector(":scope > .band-bild");
      if (!b) { b = band.ownerDocument.createElement("div"); b.className = "band-bild"; band.prepend(b); }
      b.style.backgroundImage = `url('${BASIS + p}')`;
    });
  }
  return html`<${Gruppe} titel="Band">
    <div class="wsp-bild">${url ? html`<img src=${url} alt="" style=${"opacity:" + deck} />` : html`<span class="leise">kein Hintergrundbild</span>`}
      <span class="knopfreihe"><button class="btn klein" onClick=${() => medien(bildSetzen)}>${url ? "Bild austauschen" : "Bild wählen"}</button>
      ${url && html`<button class="btn klein geist" onClick=${() => tun(() => bildEl.remove())}>Entfernen</button>`}</span></div>
    ${url && html`<${Regler} name="Deckkraft des Bildes" min=${0.1} max=${1} schritt=${0.05} einheit="%" wert=${deck} setzen=${(v) => tun(() => { bildEl.style.opacity = v >= 1 ? "" : String(v); })} />`}
    <${Regler} name="Höhe" min=${120} max=${800} schritt=${10} einheit="px" wert=${hoehe} setzen=${(v) => tun(() => band.style.setProperty("--h", v + "px"))} />
    ${url && html`<div class="feld"><label>Bewegung beim Scrollen (nur am Rechner)</label><div class="segment">
      ${[["", "Keine"], ["aufdecken", "Bild steht still"], ["parallax", "Parallax"]].map(([k, t]) => html`<button class=${effekt === k ? "an" : ""}
        onClick=${() => tun(() => { if (k) band.dataset.effekt = k; else delete band.dataset.effekt; })}>${t}</button>`)}</div></div>`}
    ${innen && html`<div class="feld"><label>Text im Band</label><div class="segment">
      ${[[false, "Linksbündig"], [true, "Zentriert"]].map(([k, t]) => html`<button class=${mitte === k ? "an" : ""} onClick=${() => tun(() => { innen.style.textAlign = k ? "center" : ""; })}>${t}</button>`)}</div></div>`}
  <//>`;
}

function VideoEigenschaften({ block, tun }) {
  const f = block.querySelector(".video iframe");
  const id = f ? youtubeId(f.getAttribute("src")) : null;
  const [url, setUrl] = useState(id ? "https://www.youtube.com/watch?v=" + id : "");
  const neu = (v) => { const i = youtubeId(v); if (!i) { toast("Das sieht nicht nach einem YouTube-Link aus.", { fehler: true }); return; } tun(() => f.setAttribute("src", "https://www.youtube-nocookie.com/embed/" + i)); };
  return html`<${Gruppe} titel="YouTube-Video">
    <div class="feld"><label>Link zum Video</label><input class="eingabe" value=${url} placeholder="https://www.youtube.com/watch?v=…"
      onInput=${(e) => setUrl(e.target.value)} onChange=${(e) => neu(e.target.value)} onKeyDown=${(e) => { if (e.key === "Enter") neu(url); }} /></div>
    <p class="leise klein">Eingebettet über youtube-nocookie.com: YouTube setzt erst beim Abspielen Cookies.</p>
  <//>`;
}

function KartenEigenschaften({ block, el, tun }) {
  const karte = el && el.closest && el.closest(".karte");
  return html`<${Gruppe} titel="Karten">
    <div class="wsp-aktionen">
      <button class="btn klein" onClick=${() => tun(() => { const k = (karte || block.querySelector(".karte")).cloneNode(true); (karte || block.lastElementChild).after(k); })}>＋ Karte hinzufügen</button>
      ${karte && html`<button class="btn klein" onClick=${() => tun(() => karte.previousElementSibling && karte.previousElementSibling.before(karte))}>← Nach links</button>
        <button class="btn klein" onClick=${() => tun(() => karte.nextElementSibling && karte.nextElementSibling.after(karte))}>Nach rechts →</button>
        <button class="btn klein gefahr" onClick=${() => tun(() => karte.remove())}>Diese Karte löschen</button>`}
    </div>
    ${!karte && html`<p class="leise klein">Eine Karte anklicken, um sie zu verschieben oder zu löschen. Bild austauschen: auf das Bild klicken.</p>`}
  <//>`;
}

// ---------------------------------------------------------------- Seiteneinstellungen (nichts ausgewählt)
function SeitenEinstellungen({ kopf, setKopf, seite, pfad, stand, medien, geaendert, geloescht, sichern }) {
  const setze = (k, v) => setKopf({ ...kopf, [k]: v });
  const blog = kopf.blog;
  const b = kopf.beschreibung || "";
  const [name, setName] = useState(pfad.split("/").pop().replace(/\.html$/, ""));
  const uebersicht = pfad === "index.html" || pfad.endsWith("/index.html");
  async function umbenennen() {
    await sichern();
    try {
      const r = await api("/webspace/umbenennen", { methode: "POST", daten: { pfad, name } });
      toast(`Neue Adresse ${r.adresse}${r.links ? ` · ${r.links} Link${r.links === 1 ? "" : "s"} auf anderen Seiten nachgezogen` : ""}.`);
      geaendert({ wechseln: r.pfad });
    } catch (e) { fehlerMelden(e); }
  }
  return html`<div class="wsp">
    <div class="wsp-kopf"><div><b>Seite</b><div class="leise klein">Nichts ausgewählt — Einstellungen der ganzen Seite. Klick auf einen Abschnitt, um ihn einzustellen.</div></div></div>
    <${Gruppe} titel="Suchmaschinen und Teilen">
      <div class="feld"><label>Titel <span class="leise">(${(kopf.titel || "").length} Zeichen, ideal bis 60)</span></label>
        <input class="eingabe" value=${kopf.titel || ""} onInput=${(e) => setze("titel", e.target.value)} /></div>
      <div class="feld"><label>Beschreibung <span class=${b.length > 160 ? "rot" : "leise"}>(${b.length} Zeichen, ideal 120–155)</span></label>
        <textarea class="eingabe" rows="3" value=${b} onInput=${(e) => setze("beschreibung", e.target.value)} placeholder="Ein bis zwei Sätze: Worum geht es auf dieser Seite?"></textarea></div>
      <div class="wsp-google" title="So ungefähr erscheint die Seite bei Google">
        <div class="g-adr">veikovoneckern.org${seite.adresse === "/" ? "" : " › " + seite.adresse.replace(/^\/|\/$/g, "").split("/").join(" › ")}</div>
        <div class="g-titel">${(kopf.titel || "Ohne Titel") + (seite.adresse === "/" ? "" : " | Veiko von Eckern")}</div>
        <div class="g-text">${b ? (b.length > 158 ? b.slice(0, 155) + " …" : b) : html`<i class="leise">Ohne Beschreibung nimmt Google irgendeinen Text von der Seite.</i>`}</div>
      </div>
    <//>
    ${blog && html`<${Gruppe} titel="Blogartikel">
      <div class="feld"><label>Titelbild in der Übersicht</label>
        <div class="wsp-bild">${blog.bild ? html`<img src=${BASIS + blog.bild} alt="" />` : html`<span class="leise">kein Bild</span>`}
          <button class="btn klein" onClick=${() => medien((p) => setze("blog", { ...blog, bild: p }))}>${blog.bild ? "Austauschen" : "Bild wählen"}</button></div></div>
      <div class="feld"><label>Auszug in der Übersicht</label>
        <textarea class="eingabe" rows="3" value=${blog.auszug || ""} onInput=${(e) => setze("blog", { ...blog, auszug: e.target.value })}></textarea></div>
      <div class="feld"><label>Position in der Übersicht <span class="leise">(kleinere Zahl = weiter oben)</span></label>
        <input class="eingabe" type="number" style="max-width:120px" value=${blog.reihe ?? ""} onInput=${(e) => setze("blog", { ...blog, reihe: Number(e.target.value) })} /></div>
    <//>`}
    <${Gruppe} titel="Adresse">
      ${uebersicht ? html`<p class="klein">${seite.adresse} <span class="leise">— die Adresse einer Übersichtsseite bleibt fest.</span></p>` : html`
        <div class="wsp-zeile"><span class="leise klein">${seite.adresse.replace(/[^/]+$/, "")}</span>
          <input class="eingabe" value=${name} onInput=${(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))} /></div>
        ${name !== pfad.split("/").pop().replace(/\.html$/, "") && html`<button class="btn klein primaer" onClick=${umbenennen}>Adresse ändern</button>
          <p class="leise klein">Menü und Links auf anderen Seiten werden automatisch nachgezogen. Wer die alte Adresse gespeichert hat, landet nach dem Veröffentlichen auf „Seite nicht gefunden“.</p>`}`}
    <//>
  </div>`;
}

// ---------------------------------------------------------------- KI
function KiFeld({ block, auftrag }) {
  const [text, setText] = useState("");
  const [laeuft, setLaeuft] = useState(null);
  const [jetzt, setJetzt] = useState(Date.now());
  useEffect(() => { if (!laeuft) return; const i = setInterval(() => setJetzt(Date.now()), 1000); return () => clearInterval(i); }, [laeuft]);
  async function los(t, art) {
    if (!t || laeuft) return;
    setLaeuft({ seit: Date.now(), was: t });
    try { await auftrag(t, art); setText(""); } catch (e) { fehlerMelden(e); }
    setLaeuft(null);
  }
  const art = block ? "abschnitt" : "seite";
  const ziel = block ? `den Abschnitt „${abschnittArt(block).name}“` : "die ganze Seite";
  return html`<div class="wsp">
    <div class="wsp-kopf"><div><b>✦ KI-Assistent</b><div class="leise klein">Bearbeitet ${ziel}${block ? "" : " — klick einen Abschnitt an, um nur ihn zu ändern"}. Das Ergebnis steht sofort in der Seite und lässt sich rückgängig machen.</div></div></div>
    ${laeuft ? html`<div class="wsk-laeuft"><div class="wsk-balken"></div><b>Die KI schreibt … ${Math.round((jetzt - laeuft.seit) / 1000)} s</b>
        <span class="leise klein">„${laeuft.was.slice(0, 80)}“ · meist 20–60 Sekunden, du kannst währenddessen weiterlesen.</span></div>`
      : html`<div class="wsk-schnell">${KI_SCHNELL.map(([n, t]) => html`<button class="btn klein" onClick=${() => los(t, art)}>${n}</button>`)}</div>
      <div class="feld"><label>Eigener Auftrag</label>
        <textarea class="eingabe" rows="4" value=${text} onInput=${(e) => setText(e.target.value)}
          placeholder=${block ? "z. B. „Mach aus dem Text drei Stichpunkte“ oder „Ergänze einen Satz zu …“" : "z. B. „Füge nach der Einleitung einen Abschnitt zu … hinzu“"}
          onKeyDown=${(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); los(text.trim(), art); } }}></textarea></div>
      <button class="btn primaer" disabled=${!text.trim()} onClick=${() => los(text.trim(), art)}>Ausführen</button>
      <div class="wsp-gruppe"><div class="wsp-titel">Neuen Abschnitt schreiben lassen</div>
        <p class="leise klein">Schreib oben, worum es gehen soll, und klick hier. Er erscheint ${block ? "unter dem gewählten Abschnitt" : "am Ende der Seite"}.</p>
        <button class="btn klein" disabled=${!text.trim()} onClick=${() => los(text.trim(), "neu")}>＋ Als neuen Abschnitt</button></div>`}
  </div>`;
}

// ---------------------------------------------------------------- Verlauf
function Verlauf({ pfad, ansehen }) {
  const [liste, setListe] = useState(null);
  useEffect(() => { api("/webspace/verlauf?pfad=" + encodeURIComponent(pfad)).then((d) => setListe(d.fassungen)).catch(fehlerMelden); }, [pfad]);
  async function oeffnen(f) {
    try { const d = await api(`/webspace/fassung?pfad=${encodeURIComponent(pfad)}&sha=${f.sha}`); ansehen({ ...f, inhalt: d.inhalt }); }
    catch (e) { fehlerMelden(e); }
  }
  return html`<div class="wsp">
    <div class="wsp-kopf"><div><b>Veröffentlichte Fassungen</b><div class="leise klein">Jede Veröffentlichung ist hier gespeichert. Ansehen, und bei Bedarf wiederherstellen.</div></div></div>
    ${!liste ? html`<p class="leise">Lädt …</p>` : !liste.length ? html`<p class="leise">Diese Seite wurde noch nie veröffentlicht.</p>`
      : html`<div class="wsv-liste">${liste.map((f, i) => html`<button class="wsv-zeile" onClick=${() => oeffnen(f)}>
        <b>${new Date(f.zeit).toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" })}${i === 0 ? html` <span class="ws-art neu">aktuell online</span>` : ""}</b>
        <span class="leise klein">${f.text.replace(/\n.*$/s, "").slice(0, 90)}</span></button>`)}</div>`}
  </div>`;
}
