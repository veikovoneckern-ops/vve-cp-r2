// UEBERBLICK (22.10.2026) -- "Gib mir einen aktuellen Ueberblick" als Fenster.
// Veiko: "ein Fenster, bei dem wirklich die letzten Ergebnisse praesentiert werden, mit
// Vorschaubildern -- und dann moechte ich sagen: oeffne mir das, gib mir dazu eine kurze
// Zusammenfassung." Die Kacheln sind nummeriert wie in der Liste, die Talk kennt
// (ueberblick.py): "oeffne das zweite", "fass das dritte zusammen" treffen genau diese Kachel.
// Der Fensterbezug traegt die Kennungen in dieser Reihenfolge (id mit Komma).
import { html, useState, useEffect, Icon, Modal, Leer, bus, zeitText, useFensterKontext, fehlerMelden, navigiere } from "./ui.js";
import { api } from "./api.js";
import { URTEIL } from "./ergebnis.js";

const FORM = { praesentation: "Präsentation", dokument: "Dokument", text: "Text", konzept: "Konzept", aufstellung: "Aufstellung",
  webseite: "Webseite", video: "Video" };

function Vorschau({ e }) {
  // Womit die Kachel zeigt, was drin ist -- vom Server bestimmt (ueberblick._vorschau_art).
  if (e.vorschau === "bild") return html`<img src=${"/api/ergebnisse/" + e.id + "/vorschaubild"} alt="" loading="lazy" />`;
  if (e.vorschau === "video") return html`<video src=${"/api/ergebnisse/" + e.id + "/video#t=2"} preload="metadata" muted playsinline></video>`;
  if (e.vorschau === "ansicht") return html`<iframe class="ub-rahmen" src=${"/api/ergebnisse/" + e.id + "/ansicht?kurz=1"} loading="lazy"
    sandbox="allow-scripts" tabindex="-1" aria-hidden="true" title=""></iframe>`;
  return html`<div class="ub-seite"><b>${e.titel}</b><p>${e.auszug}</p></div>`;
}

export function UeberblickFenster({ zu }) {
  const [d, setD] = useState(null);
  useEffect(() => { api("/ueberblick").then(setD).catch((x) => { fehlerMelden(x); zu(); }); }, []);
  const liste = d ? d.ergebnisse : [];
  useFensterKontext(d && { art: "ueberblick", id: liste.map((e) => e.id).join(","), titel: "Überblick" });
  const oeffnen = (e) => bus.sende("ergebnis-zeigen", e.id);
  return html`<${Modal} titel="Überblick" zu=${zu} breit="voll" kopf=${html`<span class="leise klein ub-tipp">Sag: „öffne das zweite“ · „fass das dritte zusammen“ · „scroll runter“</span>`}>
    ${!d ? html`<div class="lade">Lade …</div>` : html`
      <div class="ub-lage">
        ${d.entscheidungen > 0 && html`<button class="pill gelb" onClick=${() => { zu(); navigiere("/briefing"); }}>${d.entscheidungen} ${d.entscheidungen === 1 ? "Entscheidung wartet" : "Entscheidungen warten"}</button>`}
        ${(d.vorgemerkt || []).length > 0 && html`<button class="pill blau" onClick=${() => { zu(); navigiere("/inbox"); }}>Vorgemerkt: ${d.vorgemerkt.join(", ")}</button>`}
        ${(d.laeuft || []).length > 0 && html`<span class="pill lila">Läuft: ${d.laeuft.join(", ")}</span>`}
        ${!d.entscheidungen && !(d.vorgemerkt || []).length && !(d.laeuft || []).length && html`<span class="leise klein">Nichts wartet auf dich, gerade läuft nichts.</span>`}
      </div>
      ${!liste.length ? html`<${Leer} titel="Noch keine Ergebnisse.">In den letzten dreißig Tagen ist nichts entstanden.</${Leer}>` : html`
      <div class="ub-raster">
        ${liste.map((e) => {
          const u = URTEIL[e.urteil] || null;
          return html`<button class="ub-kachel" key=${e.id} onClick=${() => oeffnen(e)} title=${"Öffnen: " + e.titel}>
            <div class="ub-bild"><${Vorschau} e=${e} /><span class="ub-nr">${e.nr}</span><span class="ub-form">${FORM[e.form] || e.form}</span></div>
            <div class="ub-text">
              <b class="ub-titel">${e.titel}</b>
              <div class="leise klein">${[e.wer, e.projekt, zeitText(e.bearbeitet)].filter(Boolean).join(" · ")}</div>
              ${u && html`<span class=${"pill " + u.farbe}>${u.wort}</span>`}
              ${e.vorschau !== "text" && e.auszug && html`<p class="ub-auszug">${e.auszug}</p>`}
            </div>
          </button>`;
        })}
      </div>`}`}
  <//>`;
}

// ------------------------------------------------------------ Mini-Reihe im Briefing (23.10.2026)
// Veiko: "die tolle Uebersicht mit Vorschaubildern ... koennte doch auch in einer Mini-Kachelansicht
// noch zusaetzlich bei dem Briefing sein, damit ich das bildhaft sehen kann -- auf- und zuklappbar."
// Dieselbe Liste (/ueberblick, ueberblick.liste) und dieselben Vorschauen wie das Fenster, damit
// beide immer dasselbe zeigen. Geladen wird erst beim Aufklappen -- zugeklappt kostet sie nichts.
// Ob sie offen ist, merkt sich DIESES Geraet (am Telefon will man sie vielleicht zu, am Rechner auf).
const MERK = "vvec_briefing_kacheln";
function gemerkt() { try { return localStorage.getItem(MERK) === "1"; } catch (x) { return false; } }
function merken(auf) { try { localStorage.setItem(MERK, auf ? "1" : "0"); } catch (x) { /* egal */ } }

function MiniKacheln() {
  const [d, setD] = useState(null);
  useEffect(() => { api("/ueberblick").then(setD).catch(fehlerMelden); }, []);
  if (!d) return html`<div class="lade">Lade …</div>`;
  const liste = d.ergebnisse || [];
  if (!liste.length) return html`<div class="leise klein">In den letzten dreißig Tagen ist kein Ergebnis entstanden.</div>`;
  return html`<div class="ub-reihe">
    ${liste.map((e) => {
      const u = URTEIL[e.urteil] || null;
      return html`<button class="ub-kachel ub-mini" key=${e.id} onClick=${() => bus.sende("ergebnis-zeigen", e.id)} title=${"Öffnen: " + e.titel}>
        <div class="ub-bild"><${Vorschau} e=${e} /><span class="ub-form">${FORM[e.form] || e.form}</span></div>
        <div class="ub-text">
          <b class="ub-titel">${e.titel}</b>
          <div class="leise klein">${[e.wer, zeitText(e.bearbeitet)].filter(Boolean).join(" · ")}</div>
          ${u && html`<span class=${"pill " + u.farbe}>${u.wort}</span>`}
        </div>
      </button>`;
    })}
  </div>`;
}

export function ErgebnisReihe() {
  const [auf, setAuf] = useState(gemerkt);
  const umschalten = () => { setAuf(!auf); merken(!auf); };
  return html`<section class=${"klappe ub-klappe" + (auf ? " auf" : "")}>
    <div class="klappe-kopf">
      <button class="klappe-knopf" onClick=${umschalten} aria-expanded=${auf}>
        <span class="klappe-pfeil" aria-hidden="true"><${Icon} n="rechts" g=${16} w=${2.4} /></span>
        <span class="klappe-titel"><b>Ergebnisse in Bildern</b><small>die neuesten Ergebnisse mit Vorschau -- antippen öffnet</small></span>
        <span class="klappe-tun">${auf ? "Zuklappen" : "Aufklappen"}</span>
      </button>
      ${auf && html`<span class="klappe-rechts"><button class="btn klein geist" onClick=${() => bus.sende("ueberblick-zeigen")}
        title="Das große Überblick-Fenster -- per Sprache: „gib mir einen Überblick“"><${Icon} n="auge" g=${13} />Groß ansehen</button></span>`}
    </div>
    ${auf && html`<div class="klappe-inhalt"><${MiniKacheln} /></div>`}
  </section>`;
}
