// Aufnehmen, erkennen (eigener Whisper), vorlesen (eigener Piper).
// Kein Rueckfall auf die Spracherkennung des Browsers: die schickt den Ton an
// Google, und das darf nicht als Nebenwirkung eines Fehlers passieren.
import { toast } from "./ui.js";

function typWaehlen() {
  if (typeof MediaRecorder === "undefined") return null;
  for (const t of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) {
    try { if (MediaRecorder.isTypeSupported(t)) return t; } catch (e) { /* weiter */ }
  }
  return "";
}

export function mikrofonGrund() {
  if (!window.isSecureContext) return "Das Mikrofon geht nur über https. Wie du das einmalig einrichtest, steht unter System → Stimme.";
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
    if (rahmen) clearInterval(rahmen);
    if (ctx) ctx.close().catch(() => {});
    fertig(new Blob(teile, { type: rec.mimeType || typ || "audio/webm" }));
  };
  rec.start(250);
  const start = performance.now();
  let gesprochen = false, stilleSeit = 0;
  try {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    // Ohne vorherigen Klick auf genau diesem Weg startet der Kontext angehalten -- dann bliebe der Pegel bei null.
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
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
      if (rec.state !== "recording" && rahmen) { clearInterval(rahmen); rahmen = null; }
    };
    // Zeitgeber statt requestAnimationFrame: das pausiert der Browser, sobald der
    // Tab nicht sichtbar ist -- wer beim Freisprechen in ein anderes Fenster
    // wechselt, haette nie ein Satzende erkannt bekommen. Im Hintergrund drosselt
    // der Browser auf etwa eine Abfrage je Sekunde; das reicht fuers Satzende.
    rahmen = setInterval(takt, 60);
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

// DIKTIEREN MIT MITLESEN (Veiko, 01.10.: "so wie hier, gleich mitlesen, was ich
// diktiere"). Der eigene Whisper kann keinen Strom, also wird die Aufnahme an
// Sprechpausen in kurze Stuecke geteilt:
//   - ein fertiges Stueck wird erkannt und gilt als fest (final),
//   - das Stueck, das gerade gesprochen wird, wird etwa alle 1,5 s vorlaeufig
//     erkannt (vorlaeufig) -- Whisper auf der Karte braucht dafuer Zehntelsekunden.
// Kein Rueckfall auf die Browser-Erkennung: die schickt den Ton an Google.
// beiText(final, vorlaeufig) meldet jeden Stand; stopp() liefert den Endtext.
export async function diktieren({ beiText, pegel } = {}) {
  const grund = mikrofonGrund();
  if (grund) throw new Error(grund);
  let strom;
  try {
    strom = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (e) {
    throw new Error(e && e.name === "NotAllowedError" ? "Das Mikrofon wurde nicht freigegeben. In den Browser-Einstellungen erlauben." : "Kein Mikrofon gefunden.");
  }
  const typ = typWaehlen();
  let final = "", vorlaeufig = "", aus = false;
  let kette = Promise.resolve();                 // feste Stuecke der Reihe nach
  let seg = null;                                // { rec, teile, nr, gesprochen, start, stille }
  let nr = 0, zwischenLaeuft = false;
  // Nach abbrechen() meldet nichts mehr -- Stuecke, die noch beim Erkennen sind, schrieben
  // sonst den Text in ein Feld zurueck, das gerade gesendet und geleert wurde (19.10.2026).
  let verworfen = false;
  const melden = () => !verworfen && beiText && beiText(final, vorlaeufig);
  const anhaengen = (t) => { t = (t || "").trim(); if (t) final = final ? final + " " + t : t; };

  function neuesStueck() {
    const rec = new MediaRecorder(strom, typ ? { mimeType: typ } : {});
    const s = { rec, teile: [], nr: ++nr, gesprochen: false, start: performance.now(), stille: 0 };
    rec.ondataavailable = (e) => { if (e.data && e.data.size) s.teile.push(e.data); };
    rec.start(250);
    seg = s;
  }
  function stueckAbschliessen() {
    const s = seg; seg = null;
    if (!s) return kette;
    const fertig = new Promise((ok) => { s.rec.onstop = ok; });
    if (s.rec.state === "recording") s.rec.stop();
    kette = kette.then(async () => {
      await fertig;
      if (!s.gesprochen) return;
      try { const d = await erkennen(new Blob(s.teile, { type: s.rec.mimeType || typ || "audio/webm" })); anhaengen(d.text); }
      catch (e) { /* ein verlorenes Stueck soll das Diktat nicht beenden */ }
      vorlaeufig = ""; melden();
    });
    return kette;
  }

  let ctx, ana, takt, zwischen;
  try {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    ana = ctx.createAnalyser(); ana.fftSize = 1024;
    ctx.createMediaStreamSource(strom).connect(ana);
  } catch (e) { ana = null; }
  const buf = new Uint8Array(1024);
  neuesStueck();
  // Zeitgeber statt requestAnimationFrame: laeuft auch, wenn der Tab nicht vorn ist.
  takt = setInterval(() => {
    if (!seg || !ana) return;
    ana.getByteTimeDomainData(buf);
    let q = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; q += v * v; }
    const rms = Math.sqrt(q / buf.length);
    if (pegel) pegel(Math.min(1, rms * 6));
    const t = performance.now();
    if (rms > 0.035) { seg.gesprochen = true; seg.stille = 0; } else if (!seg.stille) seg.stille = t;
    // Satzende: 0,8 s Pause nach Gesprochenem, oder spaetestens nach 25 s.
    if (seg.gesprochen && ((seg.stille && t - seg.stille > 800) || t - seg.start > 25000)) {
      stueckAbschliessen(); if (!aus) neuesStueck();
    }
  }, 60);
  zwischen = setInterval(async () => {
    const s = seg;
    if (!s || !s.gesprochen || zwischenLaeuft || !s.teile.length) return;
    zwischenLaeuft = true;
    try {
      const d = await erkennen(new Blob(s.teile.slice(), { type: s.rec.mimeType || typ || "audio/webm" }));
      if (seg === s && !aus) { vorlaeufig = (d.text || "").trim(); melden(); }
    } catch (e) { /* vorlaeufig ist verzichtbar */ }
    zwischenLaeuft = false;
  }, 1500);

  return {
    async stopp() {
      aus = true;
      clearInterval(takt); clearInterval(zwischen);
      await stueckAbschliessen();
      strom.getTracks().forEach((x) => x.stop());
      if (ctx) ctx.close().catch(() => {});
      vorlaeufig = ""; melden();
      return final;
    },
    abbrechen() {
      aus = true; verworfen = true; clearInterval(takt); clearInterval(zwischen);
      if (seg && seg.rec.state === "recording") { seg.teile.length = 0; seg.gesprochen = false; seg.rec.stop(); }
      strom.getTracks().forEach((x) => x.stop());
      if (ctx) ctx.close().catch(() => {});
    },
  };
}

// ------------------------------------------------------------ EINE Vorfahrt fuers Mikrofon
// Veiko, 19.10.2026: "ich hatte ueber Talk ein Thema oeffnen lassen und parallel die
// Diktierfunktion gedrueckt, um einen Auftrag zu erteilen. Dann hat Talk das Diktierte
// mitgehoert und einen Auftrag ausgeloest ... ich muesste sehen koennen, was gerade
// Vorfahrt hat." Bis dahin konnten Talk-Freisprechen, ein Diktat im Composer und ein
// Vorlesen gleichzeitig laufen -- Talk hoerte das Diktat (und jedes Vorlesen) mit.
// Jetzt gilt: wer zuletzt anfaengt, hat das Mikrofon; wer es hatte, gibt es ab und
// zeigt das (Talk pausiert sichtbar, ein Diktat endet mit dem Text, der schon da ist).
// Der Stand geht als Ereignis "vvec-mikro" an alle, die ihn zeigen (app.js).
let halter = null;   // { wer, abgeben }
function mikroMelden() { window.dispatchEvent(new CustomEvent("vvec-mikro", { detail: halter ? halter.wer : null })); }
export function mikroAnfordern(wer, abgeben) {
  if (halter && halter.wer !== wer) {
    const alt = halter;
    halter = null;
    try { alt.abgeben(wer); } catch (e) { /* der alte Halter darf das Anfordern nie verhindern */ }
  }
  halter = { wer, abgeben: abgeben || (() => {}) };
  mikroMelden();
}
export function mikroFreigeben(wer) {
  if (halter && halter.wer === wer) { halter = null; mikroMelden(); }
}
export function mikroHalter() { return halter ? halter.wer : null; }

// Ins Wort fallen (22.10.2026, Veiko: "bei Talk soll die Sprachausgabe auch unterbrochen werden
// koennen durch andere Aussagen oder Fragen oder Anweisungen"). Laeuft WAEHREND Talk spricht:
// das Mikrofon hoert mit (Echo-Unterdrueckung des Browsers an), und erst wenn der Pegel deutlich
// ueber dem liegt, was von Talks eigener Stimme durchkommt, und das eine Viertelsekunde lang,
// gilt es als Einsatz. Die Schwelle folgt dem gleitenden Mittel des Pegels -- ein fester Wert
// war entweder taub (laute Lautsprecher) oder fiel auf Talks eigene Stimme herein.
// Beim Einsatz beginnt eine FRISCHE Aufnahme ab genau diesem Moment: die bis dahin mitgelaufene
// enthielte Talks Stimme, und Whisper schriebe sie mit ab.
export async function lauschen({ beiEinsatz, pegel } = {}) {
  if (mikrofonGrund()) return null;
  let strom;
  try {
    strom = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
  } catch (e) { return null; }
  const typ = typWaehlen();
  let ctx, rahmen, rec = null, fertig, aus = false;
  const teile = [];
  const ende = new Promise((ok) => { fertig = ok; });
  const schluss = (blob) => {
    if (aus) return;
    aus = true;
    if (rahmen) clearInterval(rahmen);
    strom.getTracks().forEach((t) => t.stop());
    if (ctx) ctx.close().catch(() => {});
    fertig(blob);
  };
  let mittel = 0.02, ueber = 0, stilleSeit = 0, einsatz = 0;
  const start = performance.now();
  try {
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") ctx.resume().catch(() => {});
    const ana = ctx.createAnalyser(); ana.fftSize = 1024;
    ctx.createMediaStreamSource(strom).connect(ana);
    const buf = new Uint8Array(ana.fftSize);
    rahmen = setInterval(() => {
      ana.getByteTimeDomainData(buf);
      let s = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; s += v * v; }
      const rms = Math.sqrt(s / buf.length);
      const t = performance.now();
      if (!rec) {
        // Die ersten 400 ms nur messen: so laut kommt Talk selbst im Mikrofon an.
        const schwelle = Math.max(0.06, mittel * 2.6);
        if (t - start > 400 && rms > schwelle) ueber++; else ueber = 0;
        mittel = mittel * 0.95 + Math.min(rms, schwelle) * 0.05;
        if (ueber >= 4) {
          rec = new MediaRecorder(strom, typ ? { mimeType: typ } : {});
          rec.ondataavailable = (e) => { if (e.data && e.data.size) teile.push(e.data); };
          rec.onstop = () => schluss(teile.length ? new Blob(teile, { type: rec.mimeType || typ || "audio/webm" }) : null);
          rec.start(250);
          einsatz = t;
          if (beiEinsatz) beiEinsatz();
        }
        return;
      }
      if (pegel) pegel(Math.min(1, rms * 6));
      if (rms > 0.035) stilleSeit = 0; else if (!stilleSeit) stilleSeit = t;
      if (rec.state === "recording" && ((stilleSeit && t - stilleSeit > 1500) || t - einsatz > 60000)) rec.stop();
    }, 60);
  } catch (e) { schluss(null); }
  return {
    ende,
    eingesetzt: () => !!rec,
    // Talk ist fertig mit Sprechen: ohne Einsatz ist nichts aufzuheben.
    loslassen() { if (!rec) schluss(null); },
    abbrechen() { teile.length = 0; if (rec && rec.state === "recording") rec.stop(); else schluss(null); },
  };
}

// EIN Abspieler fuer alles Vorlesen, beim ersten Tippen freigeschaltet (21.10.2026, Veiko am
// iPad: "bei Talk funktioniert die Ausgabe nicht, ich höre nichts"). Auf dem iPad laeuft jeder
// Browser mit Safaris Technik, und Safari spielt Ton nur ab, wenn er an einem Tippen haengt.
// Talk holt die Stimme aber erst NACH der Antwort vom Server -- ein dann neu angelegtes Audio
// wurde still abgelehnt (play() scheiterte, und der Fehler wurde verschluckt). Ein Element, das
// einmal waehrend eines Tippens gespielt hat, darf danach jederzeit spielen.
const STILLE = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
let spieler = null, freigeschaltet = false, blockiertGemeldet = false;
function abspieler() {
  if (!spieler) { spieler = new Audio(); spieler.preload = "auto"; spieler.setAttribute("playsinline", ""); }
  return spieler;
}
function freischalten() {
  if (freigeschaltet || laufend) return;
  const a = abspieler();
  a.src = STILLE;
  const p = a.play();
  if (p && p.then) p.then(() => { freigeschaltet = true; a.pause(); }).catch(() => {});
}
if (typeof window !== "undefined") {
  for (const ev of ["pointerdown", "touchend", "keydown"]) window.addEventListener(ev, freischalten, { capture: true, passive: true });
}

let laufend = null, vorleseNr = 0;
export function vorleseStopp() {
  vorleseNr++;   // auch ein noch ladendes Vorlesen spielt danach nicht mehr ab
  if (laufend) { laufend.pause(); laufend.dispatchEvent(new Event("ended")); laufend = null; }
}

// vonTalk: Talk liest seine eigene Antwort vor -- dann hoert Talk gerade ohnehin nicht zu.
// Jedes andere Vorlesen (Team-Chat, Board, "Vorlesen"-Knopf) nimmt sich die Vorfahrt,
// sonst hoerte ein freisprechendes Talk die Stimme mit und nahm sie fuer Veikos Satz.
export async function vorlesen(text, { vonTalk = false } = {}) {
  vorleseStopp();
  const nr = vorleseNr;
  if (!vonTalk) mikroAnfordern("vorlesen", () => vorleseStopp());
  try {
    const sauber = String(text || "").replace(/```[\s\S]*?```/g, " ").replace(/[#*_`>|]/g, " ").replace(/\s+/g, " ").trim();
    if (!sauber) return;
    const r = await fetch("/api/stimme/sprechen", { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: sauber.slice(0, 2500) }) });
    if (!r.ok) throw new Error("Sprachausgabe nicht erreichbar");
    const daten = await r.blob();
    if (nr !== vorleseNr) return;
    const url = URL.createObjectURL(daten);
    const a = abspieler();
    a.src = url;
    laufend = a;
    await new Promise((ok) => {
      a.addEventListener("ended", ok, { once: true });
      a.addEventListener("error", ok, { once: true });
      a.play().catch((e) => {
        // Nicht mehr still: wer nichts hoert, soll wissen warum und was hilft (einmal je Seite).
        if (e && e.name === "NotAllowedError" && !blockiertGemeldet) {
          blockiertGemeldet = true;
          toast("Der Browser hat den Ton blockiert. Tippe einmal irgendwo ins Cockpit -- danach liest es vor.", { fehler: true, dauer: 8000 });
        }
        ok();
      });
    });
    URL.revokeObjectURL(url);
    if (laufend === a) laufend = null;
  } finally {
    if (!vonTalk) mikroFreigeben("vorlesen");
  }
}
