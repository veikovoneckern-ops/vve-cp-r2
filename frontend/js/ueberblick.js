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
