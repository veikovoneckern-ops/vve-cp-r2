// Matrix-Regen und Matrix-Zeichen fuer Neo -- uebernommen aus dem alten Layer
// (regenBild, matrixZeichen), dort am 07.09.2026 auf Veikos Wunsch entstanden.
// Halbbreite Katakana plus Ziffern: in einer dicktengleichen Schrift genau eine
// Zelle breit, die Zeile springt nicht.
import { html, useEffect, useRef, useState } from "./ui.js";

const ZEICHEN = (() => {
  let s = "0123456789";
  for (let c = 0xff66; c <= 0xff9d; c++) s += String.fromCharCode(c);
  return s;
})();
const zufall = () => ZEICHEN[Math.floor(Math.random() * ZEICHEN.length)];
const ruhig = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

// Canvas statt DOM: 40 Spalten x 45 Zeichen, 18-mal je Sekunde, waeren
// zweitausend Elemente neben einem rechnenden Modell. Das Verblassen macht das
// Bild: jedes Bild wird halbdurchsichtig uebermalt, der Schweif entsteht umsonst.
export function MatrixRegen({ children }) {
  const ref = useRef(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    let spalten = [], zelle = 16, laeuft = true, t;
    const groesse = () => {
      const r = cv.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      cv.width = Math.max(1, r.width * dpr); cv.height = Math.max(1, r.height * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      zelle = r.width < 500 ? 14 : 16;
      const n = Math.ceil(r.width / zelle);
      spalten = Array.from({ length: n }, () => Math.floor(Math.random() * -40));
      ctx.fillStyle = "#04120a"; ctx.fillRect(0, 0, r.width, r.height);
    };
    groesse();
    const ro = new ResizeObserver(groesse); ro.observe(cv);
    const bild = () => {
      if (!laeuft) return;
      const r = cv.getBoundingClientRect();
      ctx.fillStyle = "rgba(4,18,10,0.085)";
      ctx.fillRect(0, 0, r.width, r.height);
      ctx.font = `${zelle - 2}px ui-monospace, Consolas, monospace`;
      for (let i = 0; i < spalten.length; i++) {
        const y = spalten[i];
        if (y >= 0) {
          ctx.fillStyle = "#b8ffd0";
          ctx.fillText(zufall(), i * zelle, y * zelle);
          ctx.fillStyle = "#00c853";
          ctx.fillText(zufall(), i * zelle, (y - 1) * zelle);
        }
        spalten[i] = y * zelle > r.height && Math.random() > 0.975 ? Math.floor(Math.random() * -20) : y + 1;
      }
      t = setTimeout(() => requestAnimationFrame(bild), ruhig() ? 220 : 55);
    };
    bild();
    const sicht = () => { laeuft = !document.hidden; if (laeuft) bild(); };
    document.addEventListener("visibilitychange", sicht);
    return () => { laeuft = false; clearTimeout(t); ro.disconnect(); document.removeEventListener("visibilitychange", sicht); };
  }, []);
  return html`<div class="regen"><canvas ref=${ref} aria-hidden="true"></canvas>${children}</div>`;
}

// EIN Zeichen in Zeilenhoehe. Ein Band aus zwanzig Zeichen drueckte den Text
// daneben zusammen; ein pulsierendes Logo stand die halbe Zeit fast still.
export function MatrixZeichen() {
  const [z, setZ] = useState(zufall());
  useEffect(() => {
    const i = setInterval(() => setZ(zufall()), ruhig() ? 700 : 160);
    return () => clearInterval(i);
  }, []);
  return html`<span class="matrix-zeichen" aria-hidden="true">${z}</span>`;
}
