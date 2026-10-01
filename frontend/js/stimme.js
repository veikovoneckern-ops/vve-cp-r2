// Aufnehmen, erkennen (eigener Whisper), vorlesen (eigener Piper).
// Kein Rueckfall auf die Spracherkennung des Browsers: die schickt den Ton an
// Google, und das darf nicht als Nebenwirkung eines Fehlers passieren.

function typWaehlen() {
  if (typeof MediaRecorder === "undefined") return null;
  for (const t of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) {
    try { if (MediaRecorder.isTypeSupported(t)) return t; } catch (e) { /* weiter */ }
  }
  return "";
}

export function mikrofonGrund() {
  if (!window.isSecureContext) return "Das Mikrofon geht nur über eine sichere Verbindung (https). Öffne das Cockpit über seine https-Adresse.";
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return "Dieser Browser gibt kein Mikrofon frei.";
  if (typWaehlen() === null) return "Dieser Browser kann nicht aufnehmen.";
  return "";
}

// Startet eine Aufnahme. stilleStopp: hoert nach dem Sprechen selbst auf
// (Freisprechen). pegel(0..1) wird fuer die Anzeige laufend gemeldet.
export async function aufnehmen({ stilleStopp = false, maxSek = 180, pegel } = {}) {
  const grund = mikrofonGrund();
  if (grund) throw new Error(grund);
  let strom;
  try {
    strom = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (e) {
    throw new Error(e && e.name === "NotAllowedError" ? "Das Mikrofon wurde nicht freigegeben. In den Browser-Einstellungen erlauben." : "Kein Mikrofon gefunden.");
  }
  const typ = typWaehlen();
  const rec = new MediaRecorder(strom, typ ? { mimeType: typ } : {});
  const teile = [];
  rec.ondataavailable = (e) => { if (e.data && e.data.size) teile.push(e.data); };
  let ctx, ana, rahmen, fertig;
  const ende = new Promise((ok) => { fertig = ok; });
  rec.onstop = () => {
    strom.getTracks().forEach((t) => t.stop());
    if (rahmen) cancelAnimationFrame(rahmen);
    if (ctx) ctx.close().catch(() => {});
    fertig(new Blob(teile, { type: rec.mimeType || typ || "audio/webm" }));
  };
  rec.start(250);
  const start = performance.now();
  let gesprochen = false, stilleSeit = 0;
  try {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    const quelle = ctx.createMediaStreamSource(strom);
    ana = ctx.createAnalyser(); ana.fftSize = 1024;
    quelle.connect(ana);
    const buf = new Uint8Array(ana.fftSize);
    const takt = () => {
      ana.getByteTimeDomainData(buf);
      let s = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; s += v * v; }
      const rms = Math.sqrt(s / buf.length);
      if (pegel) pegel(Math.min(1, rms * 6));
      const t = performance.now();
      if (rms > 0.035) { gesprochen = true; stilleSeit = 0; } else if (!stilleSeit) stilleSeit = t;
      if (stilleStopp && rec.state === "recording") {
        if (gesprochen && stilleSeit && t - stilleSeit > 1500) rec.stop();
        else if (!gesprochen && t - start > 9000) rec.stop();
      }
      if (t - start > maxSek * 1000 && rec.state === "recording") rec.stop();
      if (rec.state === "recording") rahmen = requestAnimationFrame(takt);
    };
    takt();
  } catch (e) { /* ohne Pegel geht es auch */ }
  return {
    stopp() { if (rec.state === "recording") rec.stop(); return ende; },
    ende,
    abbrechen() { teile.length = 0; if (rec.state === "recording") rec.stop(); },
    gesprochen: () => gesprochen,
  };
}

function dateiname(blob) {
  const t = blob.type || "";
  return "aufnahme." + (t.includes("mp4") ? "mp4" : t.includes("ogg") ? "ogg" : t.includes("wav") ? "wav" : "webm");
}

export async function erkennen(blob) {
  const fd = new FormData();
  fd.append("datei", blob, dateiname(blob));
  const r = await fetch("/api/stimme/hoeren", { method: "POST", body: fd, credentials: "same-origin" });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || "Spracherkennung fehlgeschlagen");
  return d;
}

let laufend = null;
export function vorleseStopp() {
  if (laufend) { laufend.pause(); laufend.dispatchEvent(new Event("ended")); laufend = null; }
}

export async function vorlesen(text) {
  vorleseStopp();
  const sauber = String(text || "").replace(/```[\s\S]*?```/g, " ").replace(/[#*_`>|]/g, " ").replace(/\s+/g, " ").trim();
  if (!sauber) return;
  const r = await fetch("/api/stimme/sprechen", { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: sauber.slice(0, 2500) }) });
  if (!r.ok) throw new Error("Sprachausgabe nicht erreichbar");
  const url = URL.createObjectURL(await r.blob());
  const a = new Audio(url);
  laufend = a;
  await new Promise((ok) => {
    a.addEventListener("ended", ok, { once: true });
    a.addEventListener("error", ok, { once: true });
    a.play().catch(ok);
  });
  URL.revokeObjectURL(url);
  if (laufend === a) laufend = null;
}
