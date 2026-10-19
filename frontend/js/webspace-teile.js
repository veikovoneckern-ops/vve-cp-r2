// WEBSPACE -- Abschnitts-Vorlagen und Hilfen, die Editor und Hauptansicht teilen (19.10.2026).
//
// Eine Seite ist eine Folge von ABSCHNITTEN: die obersten Elemente des Inhalts
// (Band, Text, Karten, Balken, Baustein-Marke ...). Der Editor zeigt, verschiebt,
// dupliziert und löscht genau diese Elemente; gespeichert wird weiter der HTML-Text.

export const BASIS = "/api/webspace/vorschau";
const MARKE_RE = /<!--(baustein [a-z0-9-]+|blogliste)-->/g;

// ---------------------------------------------------------------- Datei <-> Editor
// Die Blog-Liste baut sich beim Veröffentlichen aus den Artikeln. Im Editor stand dort
// bis zum 19.10. nur ein Platzhalter -- Veiko: "wieso sind auf dieser Seite keine Inhalte?".
// Jetzt zeigt der Editor die echte Liste (aus dem Stand, gleiche Reihenfolge und Markup wie
// bauen.js), nur lesend; ein Klick auf einen Beitrag öffnet ihn. Gespeichert wird weiter
// nur die Marke.
let blogArtikel = [];
export function blogSetzen(seiten) {
  blogArtikel = (seiten || []).filter((s) => s.blog).sort((a, b) => (a.blog.reihe ?? 999) - (b.blog.reihe ?? 999));
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[c]));
function blogVorschau() {
  if (!blogArtikel.length) return "<p class=\"ws-marke-leer\">Noch keine Blogartikel. Neue Artikel legst du links über „Neue Seite oder Artikel“ an.</p>";
  return "<div class=\"blogliste\">" + blogArtikel.map((a) => `<div class="blogeintrag" data-ws-pfad="${esc(a.pfad)}" title="Artikel öffnen">
    ${a.blog.bild ? `<img src="${esc(a.blog.bild.startsWith("/bilder/") ? BASIS + a.blog.bild : a.blog.bild)}" alt="" loading="lazy">` : "<span></span>"}
    <div><h2>${esc(a.titel)}</h2><p>${esc(a.blog.auszug || "")}</p></div></div>`).join("") + "</div>";
}

export function zuEditor(inhalt) {
  return inhalt
    .replace(/(["'(])\/bilder\//g, "$1" + BASIS + "/bilder/")
    .replace(MARKE_RE, (m, was) => {
      if (was === "blogliste") {
        return `<div class="ws-marke ws-marke-blog" contenteditable="false" data-marke="blogliste"><div class="ws-marke-kopf"><span>⚙</span>Liste der Blogartikel (${blogArtikel.length}) — baut sich von selbst aus den Artikeln · Klick auf einen Beitrag öffnet ihn</div>${blogVorschau()}</div>`;
      }
      const text = `Interaktiver Baustein „${was.slice(9)}“ — wird von Neo gepflegt, hier nur verschiebbar`;
      return `<div class="ws-marke" contenteditable="false" data-marke="${was}"><span>⚙</span>${text}</div>`;
    });
}

export function ausEditor(main) {
  const k = main.cloneNode(true);
  k.querySelectorAll(".ws-marke").forEach((m) => m.replaceWith(main.ownerDocument.createComment(m.dataset.marke)));
  k.querySelectorAll("[contenteditable]").forEach((e) => e.removeAttribute("contenteditable"));
  k.querySelectorAll("[data-ws]").forEach((e) => e.removeAttribute("data-ws"));
  let s = k.innerHTML;
  s = s.split(BASIS + "/bilder/").join("/bilder/");
  // Schreibweise der vorhandenen Seiten halten.
  s = s.replace(/<(\/?)b>/g, "<$1strong>").replace(/<(\/?)i>/g, "<$1em>")
    .replace(/ (controls|playsinline|autoplay|muted|loop|allowfullscreen)=""/g, " $1")
    .replace(/ style=""/g, "").replace(/ class=""/g, "")
    .replace(/<p>(\s|<br>)*<\/p>/g, "").replace(/\n{3,}/g, "\n\n");
  return s.trim();
}

// ---------------------------------------------------------------- Abschnittsarten
// Wofür ein oberstes Element steht -- für Beschriftung, Eigenschaften und KI.
export function abschnittArt(el) {
  if (!el || el.nodeType !== 1) return { art: "?", name: "Abschnitt" };
  const c = el.classList;
  if (c.contains("ws-marke")) return el.dataset.marke === "blogliste" ? { art: "blogliste", name: "Blog-Liste" } : { art: "baustein", name: "Interaktiver Baustein" };
  if (el.tagName === "SECTION" && c.contains("band")) return { art: "band", name: "Band" };
  if (c.contains("karten")) return { art: "karten", name: "Karten" };
  if (c.contains("balken")) return { art: "balken", name: "Balken-Überschrift" };
  if (el.tagName === "HR") return { art: "trenner", name: "Trennlinie" };
  if (c.contains("abstand")) return { art: "abstand", name: "Abstand" };
  if (c.contains("fliess")) {
    if (el.querySelector(":scope > .video")) return { art: "video", name: "Video" };
    if (el.querySelector(":scope > .spalten")) return { art: "spalten", name: "Zwei Spalten" };
    if (el.querySelector(":scope > blockquote")) return { art: "zitat", name: "Zitat" };
    return { art: "text", name: "Text" };
  }
  return { art: "html", name: el.tagName.toLowerCase() };
}

export function kurzText(el, n = 60) {
  const t = (el && el.textContent || "").replace(/\s+/g, " ").trim();
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
}

// ---------------------------------------------------------------- Vorlagen ("Abschnitt einfügen")
export const VORLAGEN = [
  { id: "titelband", gruppe: "Bänder", name: "Titelband", text: "Großes Bild mit Überschrift und Untertitel",
    html: `<section class="band" data-effekt="aufdecken" style="--h:400px">
  <div class="band-bild" style="background-image:url('/bilder/banner-black-hole-new-lowres.png');opacity:0.7"></div>
  <div class="band-innen">
    <h1>Überschrift</h1>
    <p style="font-size:26px;line-height:1.6">Ein Satz, der neugierig macht.</p>
  </div>
</section>` },
  { id: "bandknopf", gruppe: "Bänder", name: "Band mit Knopf", text: "Dunkles Band, Überschrift und Verweis",
    html: `<section class="band" style="--h:260px">
  <div class="band-bild" style="background-image:url('/bilder/unsplash-xjt4q7wrrju.jpg');opacity:0.3"></div>
  <div class="band-innen">
    <h2 style="font-size:50px;line-height:1.2">ÜBERSCHRIFT</h2>
    <p class="knopfzeile"><a class="knopf" href="/">MEHR ERFAHREN</a></p>
  </div>
</section>` },
  { id: "balken", gruppe: "Bänder", name: "Balken-Überschrift", text: "Schmaler dunkler Balken, z. B. über Karten",
    html: `<div class="balken"><h3>ÜBERSCHRIFT</h3></div>` },
  { id: "text", gruppe: "Text", name: "Überschrift und Text", text: "Der Normalfall: Zwischenüberschrift mit Absatz",
    html: `<div class="fliess">
<h2>Zwischenüberschrift</h2>
<p>Hier steht dein Text. Klick hinein und schreib los.</p>
</div>` },
  { id: "absatz", gruppe: "Text", name: "Nur Text", text: "Ein Absatz ohne Überschrift",
    html: `<div class="fliess">
<p>Hier steht dein Text.</p>
</div>` },
  { id: "spalten", gruppe: "Text", name: "Zwei Spalten", text: "Zwei Textblöcke nebeneinander",
    html: `<div class="fliess">
<div class="spalten">
<div>
<h3>Links</h3>
<p>Text der linken Spalte.</p>
</div>
<div>
<h3>Rechts</h3>
<p>Text der rechten Spalte.</p>
</div>
</div>
</div>` },
  { id: "liste", gruppe: "Text", name: "Aufzählung", text: "Überschrift mit Stichpunkten",
    html: `<div class="fliess">
<h3>Überschrift</h3>
<ul>
  <li>Erster Punkt</li>
  <li>Zweiter Punkt</li>
  <li>Dritter Punkt</li>
</ul>
</div>` },
  { id: "zitat", gruppe: "Text", name: "Zitat", text: "Hervorgehobenes Zitat mit Quelle",
    html: `<div class="fliess">
<blockquote class="zitat"><p>Ein wörtliches Zitat.</p><cite>Name, Quelle</cite></blockquote>
</div>` },
  { id: "bild", gruppe: "Medien", name: "Bild mit Unterschrift", text: "Ein Bild aus deinen Medien", medien: true,
    html: `<div class="fliess">
<figure class="mittel"><img src="/bilder/hr-breit-lowres.png" alt=""><figcaption>Bildunterschrift</figcaption></figure>
</div>` },
  { id: "karten", gruppe: "Medien", name: "Drei Karten", text: "Bild, Titel und Text nebeneinander",
    html: `<div class="karten">
  <div class="karte">
    <img src="/bilder/hr-strategy-quadrat-lowres.png" alt="" loading="lazy">
    <h4>Titel</h4>
    <p>Kurzer Text.</p>
  </div>
  <div class="karte">
    <img src="/bilder/wef.png" alt="" loading="lazy">
    <h4>Titel</h4>
    <p>Kurzer Text.</p>
  </div>
  <div class="karte">
    <img src="/bilder/bpm-fg-strategy.jpg" alt="" loading="lazy">
    <h4>Titel</h4>
    <p>Kurzer Text.</p>
  </div>
</div>` },
  { id: "video", gruppe: "Medien", name: "YouTube-Video", text: "Video einbetten (Link danach rechts eintragen)",
    html: `<div class="fliess">
<div class="video"><iframe src="https://www.youtube-nocookie.com/embed/" title="Video" loading="lazy" allowfullscreen></iframe></div>
</div>` },
  { id: "knopf", gruppe: "Weiteres", name: "Knopf", text: "Ein Verweis als Knopf, mittig",
    html: `<div class="fliess mitte">
<p class="knopfzeile"><a class="knopf" href="/">MEHR ERFAHREN</a></p>
</div>` },
  { id: "trenner", gruppe: "Weiteres", name: "Trennlinie", text: "Feine Linie zwischen zwei Teilen",
    html: `<hr class="trenner">` },
  { id: "abstand", gruppe: "Weiteres", name: "Abstand", text: "Leerraum, Höhe einstellbar",
    html: `<div class="abstand" style="--abstand:48px"></div>` },
];

// ---------------------------------------------------------------- YouTube
export function youtubeId(url) {
  const m = String(url || "").match(/(?:youtu\.be\/|v=|embed\/|shorts\/)([A-Za-z0-9_-]{11})/);
  return m ? m[1] : null;
}

// ---------------------------------------------------------------- Einfügen aus Word/Web säubern
const ERLAUBT = new Set(["P", "H2", "H3", "H4", "UL", "OL", "LI", "A", "STRONG", "B", "EM", "I", "BR", "BLOCKQUOTE"]);
export function saeubern(html) {
  const d = new DOMParser().parseFromString(html, "text/html");
  function rek(n) {
    if (n.nodeType === 3) return n.textContent.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));
    if (n.nodeType !== 1) return "";
    const innen = [...n.childNodes].map(rek).join("");
    let t = n.tagName;
    if (t === "H1") t = "H2";
    if (t === "DIV" || t === "SECTION" || t === "ARTICLE") return innen ? `<p>${innen}</p>` : "";
    if (!ERLAUBT.has(t)) return innen;
    if (t === "BR") return "<br>";
    if (t === "B") t = "STRONG";
    if (t === "I") t = "EM";
    if (t === "A") {
      const h = n.getAttribute("href") || "";
      if (!/^(https?:|\/|mailto:)/.test(h)) return innen;
      return `<a href="${h.replace(/"/g, "&quot;")}"${/^https?:/.test(h) ? ' target="_blank" rel="noopener"' : ""}>${innen}</a>`;
    }
    return `<${t.toLowerCase()}>${innen}</${t.toLowerCase()}>`;
  }
  return [...d.body.childNodes].map(rek).join("").replace(/<p>\s*<\/p>/g, "");
}

// ---------------------------------------------------------------- Vergleich (Veröffentlichen-Dialog)
// Sichtbarer Text je Absatz, damit Veiko sieht, was sich INHALTLICH ändert --
// nicht, welche Anführungszeichen der Browser anders setzt.
export function absaetze(html) {
  const d = new DOMParser().parseFromString(`<div>${html.replace(MARKE_RE, (m, w) => `<p>[${w === "blogliste" ? "Blog-Liste" : "Baustein " + w.slice(9)}]</p>`)}</div>`, "text/html");
  const out = [];
  d.querySelectorAll("h1,h2,h3,h4,p,li,figcaption,cite,img").forEach((e) => {
    if (e.tagName === "IMG") { out.push("[Bild: " + (e.getAttribute("src") || "").split("/").pop() + "]"); return; }
    if (e.closest("li") && e.tagName === "P") return;
    const t = e.textContent.replace(/\s+/g, " ").trim();
    if (t) out.push((/^H/.test(e.tagName) ? "§ " : "") + t);
  });
  return out;
}

function lcs(a, b) {
  const n = a.length, m = b.length;
  const t = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) t[i][j] = a[i] === b[j] ? t[i + 1][j + 1] + 1 : Math.max(t[i + 1][j], t[i][j + 1]);
  const ops = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) { ops.push(["=", a[i]]); i++; j++; }
    else if (t[i + 1][j] >= t[i][j + 1]) { ops.push(["-", a[i]]); i++; }
    else { ops.push(["+", b[j]]); j++; }
  }
  while (i < n) ops.push(["-", a[i++]]);
  while (j < m) ops.push(["+", b[j++]]);
  return ops;
}

// Ergebnis: Liste von { art: "=", "-", "+", "~", text | teile }
export function vergleichen(alt, neu) {
  if (alt.length > 1500 || neu.length > 1500) return [{ art: "~", teile: [["-", "(zu lang für einen Vergleich)"]] }];
  const ops = lcs(alt, neu);
  const aus = [];
  for (let k = 0; k < ops.length; k++) {
    const [o, t] = ops[k];
    // Ein entfernter Absatz direkt gefolgt von einem neuen: Wort für Wort vergleichen.
    if (o === "-" && ops[k + 1] && ops[k + 1][0] === "+") {
      const w = lcs(t.split(/(\s+)/), ops[k + 1][1].split(/(\s+)/));
      aus.push({ art: "~", teile: w });
      k++;
    } else aus.push({ art: o, text: t });
  }
  return aus;
}
