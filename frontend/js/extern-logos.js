// Die Zeichen der Externen, animiert (24.10.2026). Veiko: "wenn Externe arbeiten, sollen sich die Logos der
// Externen oben animiert anzeigen -- so, wie sie in einem Chat direkt mit Claude, Gemini oder Grok animiert
// gezeigt werden, wenn sie arbeiten." Nachgezeichnet als schlichtes SVG statt eingebundener Bilddateien, damit
// sie in hell und dunkel funktionieren und die Animation (CSS, app.css: .ext-*) am Zeichen selbst sitzt:
//   Claude -- der orange Strahlenkranz dreht sich langsam, die Strahlen atmen versetzt (wie beim Schreiben in claude.ai);
//   Gemini -- der Vierstern im Blau-Violett-Verlauf dreht und pulsiert, der Verlauf wandert;
//   Grok   -- das Zeichen aus Kreis und Schraegstrich, der Kreis laeuft um, das Ganze pulsiert.
// Wer gerade rechnet, meldet /kopf in ki.extern (cloud.LAEUFT) -- nichts wird hier vermutet.
import { html } from "./ui.js";

export const EXTERN_NAME = { claude: "Dario (Claude)", gemini: "Demmis (Gemini)", grok: "Elon (Grok)" };

function Claude() {
  // Zwoelf Strahlen ungleicher Laenge, wie der Kranz bei Claude.
  const laengen = [10, 7.5, 9, 6.5, 10, 8, 9.5, 7, 10, 7.5, 8.5, 6.5];
  return html`<svg class="ext-logo ext-claude" viewBox="0 0 24 24" aria-hidden="true">
    <g class="ext-claude-kranz">${laengen.map((l, i) => html`<line class="ext-claude-strahl" style=${"animation-delay:" + (i * 0.11).toFixed(2) + "s"}
      x1="12" y1="12" x2="12" y2=${12 - l} transform=${`rotate(${i * 30} 12 12)`} />`)}</g></svg>`;
}

function Gemini() {
  return html`<svg class="ext-logo ext-gemini" viewBox="0 0 24 24" aria-hidden="true">
    <defs><linearGradient id="ext-gemini-verlauf" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#4285F4" /><stop offset="0.5" stop-color="#9B72CB" /><stop offset="1" stop-color="#D96570" />
      <animateTransform attributeName="gradientTransform" type="rotate" from="0 0.5 0.5" to="360 0.5 0.5" dur="3s" repeatCount="indefinite" />
    </linearGradient></defs>
    <path class="ext-gemini-stern" fill="url(#ext-gemini-verlauf)"
      d="M12 1C12.6 7 17 11.4 23 12C17 12.6 12.6 17 12 23C11.4 17 7 12.6 1 12C7 11.4 11.4 7 12 1Z" /></svg>`;
}

function Grok() {
  return html`<svg class="ext-logo ext-grok" viewBox="0 0 24 24" aria-hidden="true">
    <circle class="ext-grok-kreis" cx="12" cy="12" r="8.5" />
    <line class="ext-grok-strich" x1="4" y1="20" x2="20.5" y2="3.5" /></svg>`;
}

const ZEICHEN = { claude: Claude, gemini: Gemini, grok: Grok };

export function ExternLogos({ wer }) {
  return html`<span class="ext-logos">${(wer || []).filter((p) => ZEICHEN[p]).map((p) => {
    const Z = ZEICHEN[p];
    return html`<span key=${p} class="ext-logo-platz" title=${EXTERN_NAME[p] + " arbeitet"}><${Z} /></span>`;
  })}</span>`;
}
