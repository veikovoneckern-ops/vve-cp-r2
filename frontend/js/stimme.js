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
        if (gesprochen && stilleSeit && t - stilleSeit > 1100) rec.stop();
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
//
// Zweite Fassung (22.10.2026, Veiko: "das Unterbrechen funktioniert noch nicht gut"). Drei Fehler
// der ersten, alle aus dem Aufbau abgeleitet (mit echter Stimme ist es hier nicht pruefbar):
//  1. Die Aufnahme begann erst NACH der Erkennung -- die erste Viertelsekunde des Satzes fehlte,
//     Whisper bekam "…arte mal, mach …" und verstand Unsinn. Jetzt laeuft das Mikrofon roh (PCM) in
//     einen Ringpuffer, und beim Einsatz gehen 0,8 s VOR dem Einsatz mit (als WAV).
//  2. Die Schwelle (mindestens 0,06 auf dem ganzen Frequenzband) war zu hoch: waehrend Talk spricht,
//     daempft die Echo-Unterdrueckung des Browsers auch die eigene Stimme. Jetzt nach einem
//     Hochpass (Brummen, Tisch, Lueftung zaehlen nicht) und relativ zum Echo, mindestens 0,02.
//  3. Auf dem iPad startet ein AudioContext ohne Tippen angehalten -- dann lief gar keine Messung.
//     Der Kontext wird jetzt beim ersten Tippen ins Cockpit freigeschaltet und wiederverwendet.
// Jeder Lauf meldet seine Pegel (bericht) -- Talk schickt sie an den Server, damit sich die
// Schwellen an echten Messungen statt an Vermutungen einstellen lassen.
let tonKontext = null;
function tonKontextHolen() {
  if (!tonKontext || tonKontext.state === "closed") {
    try { tonKontext = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { tonKontext = null; }
  }
  if (tonKontext && tonKontext.state === "suspended") tonKontext.resume().catch(() => {});
  return tonKontext;
}
if (typeof window !== "undefined") {
  const freigeben = () => { const k = tonKontextHolen(); if (k && k.state === "running") ["pointerdown", "touchend", "keydown"].forEach((ev) => window.removeEventListener(ev, freigeben, true)); };
  ["pointerdown", "touchend", "keydown"].forEach((ev) => window.addEventListener(ev, freigeben, { capture: true, passive: true }));
}

function wavAus(stuecke, rate) {
  // Auf 16 kHz Mono -- mehr braucht Whisper nicht, und die Datei bleibt klein.
  const n = stuecke.reduce((s, x) => s + x.length, 0);
  const alle = new Float32Array(n);
  let o = 0; for (const x of stuecke) { alle.set(x, o); o += x.length; }
  const ziel = 16000, f = rate / ziel, m = Math.floor(n / f);
  const buf = new ArrayBuffer(44 + m * 2), v = new DataView(buf);
  const s = (p, t) => { for (let i = 0; i < t.length; i++) v.setUint8(p + i, t.charCodeAt(i)); };
  s(0, "RIFF"); v.setUint32(4, 36 + m * 2, true); s(8, "WAVE"); s(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
  v.setUint16(22, 1, true); v.setUint32(24, ziel, true); v.setUint32(28, ziel * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  s(36, "data"); v.setUint32(40, m * 2, true);
  for (let i = 0; i < m; i++) {
    const p = i * f, a = Math.floor(p), b = Math.min(n - 1, a + 1), w = p - a;
    const x = Math.max(-1, Math.min(1, alle[a] * (1 - w) + alle[b] * w));
    v.setInt16(44 + i * 2, x < 0 ? x * 0x8000 : x * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

export async function lauschen({ beiEinsatz, pegel } = {}) {
  if (mikrofonGrund()) return null;
  const ctx = tonKontextHolen();
  if (!ctx) return null;
  let strom;
  try {
    // autoGainControl aus: die automatische Verstaerkung hob Talks Echo in den Pausen an und
    // machte die Schwelle unruhig.
    strom = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false } });
  } catch (e) { return null; }
  let fertig, aus = false, einsatz = 0, stilleSeit = 0;
  const ende = new Promise((ok) => { fertig = ok; });
  const rate = ctx.sampleRate;
  const VOR = Math.ceil(0.8 * rate);            // so viel geht vor dem Einsatz mit
  let ring = [], ringLaenge = 0, aufnahme = null;
  // Hochpass ~200 Hz (erste Ordnung) gegen Brummen und Tischgeraeusche.
  const a = 1 / (1 + 2 * Math.PI * 200 / rate);
  let hx = 0, hy = 0;
  let mittel = 0.01, boden = 0.01, ueber = 0, spitze = 0, echoSpitze = 0, rahmen = 0, kopplung = null, sMik = 0, sWied = 0, wiedRahmen = 0;
  const diag = { mitKurve: 0, ohneKurve: 0, still: 0 };
  const start = performance.now();
  const quelle = ctx.createMediaStreamSource(strom);
  const proz = ctx.createScriptProcessor(2048, 1, 1);
  const stumm = ctx.createGain(); stumm.gain.value = 0;
  const bericht = { rate, einsatz: false, mittel_bei_einsatz: null, schwelle_bei_einsatz: null, spitze_vorher: 0, rahmen_ueber: 0, dauer_ms: 0, kontext: ctx.state };
  const schluss = (blob) => {
    if (aus) return;
    aus = true;
    try { proz.disconnect(); quelle.disconnect(); stumm.disconnect(); } catch (e) { /* schon getrennt */ }
    strom.getTracks().forEach((t) => t.stop());
    bericht.dauer_ms = Math.round(performance.now() - start);
    fertig(blob);
  };
  proz.onaudioprocess = (ev) => {
    if (aus) return;
    const ein = ev.inputBuffer.getChannelData(0);
    const kopie = new Float32Array(ein);
    let s = 0;
    for (let i = 0; i < ein.length; i++) { hy = a * (hy + ein[i] - hx); hx = ein[i]; s += hy * hy; }
    const rms = Math.sqrt(s / ein.length);
    const t = performance.now();
    rahmen++;
    if (!einsatz) {
      ring.push(kopie); ringLaenge += kopie.length;
      while (ringLaenge - ring[0].length > VOR) ringLaenge -= ring.shift().length;
      // Die Schwelle folgt dem Mittel UND den Spitzen von Talks eigener Stimme (Silben): gemessen
      // mit einem kuenstlichen, silbenartig schwankenden Echo loeste das Mittel allein falsch aus.
      // Gelernt werden nur Spitzen UNTER der Schwelle (und alles in den ersten 300 ms) -- sonst
      // wuerde Veikos eigener Einsatz die Schwelle mit nach oben ziehen.
      // Dritte Fassung (22.10.2026, abends): mit laufendem Film blieb Veiko mit Spitzen von 0,026-0,039
      // unter der Schwelle, weil die Echo-Spitze den GANZEN Satz ueber galt. Jetzt zaehlt, wie laut Talk
      // in DIESEM Augenblick klingt (wiedergabePegel aus der Lautstaerkekurve des laufenden Satzes) mal
      // dem gemessenen Uebertragungsfaktor Lautsprecher -> Mikrofon (kopplung). In Talks Sprechpausen
      // faellt die Schwelle damit fast auf das Grundrauschen -- dort reicht schon leises Reden.
      const pw = wiedergabePegel();
      let schwelle;
      if (pw === null || kopplung === null) {
        schwelle = Math.max(0.02, mittel * 2.2, echoSpitze * 1.4);
      } else {
        schwelle = Math.max(0.014, boden * 3, kopplung * pw * 1.6 + 0.006);
        diag.mitKurve++;
      }
      if (pw === null) diag.ohneKurve++;
      if (pw !== null && pw === 0) diag.still++;
      if (window.__lauschVerlauf) window.__lauschVerlauf.push([Math.round(t - start), +rms.toFixed(4), pw === null ? null : +pw.toFixed(3), +schwelle.toFixed(4)]);
      // Einlaufzeit: die ersten 300 ms UND der Beginn der Wiedergabe, bis die Kopplung gelernt ist -- die
      // Stimme kommt erst nach dem Laden, und die ersten Echo-Rahmen trafen sonst eine ungelernte Schwelle.
      // Kopplung Lautsprecher -> Mikrofon lernen (Summen ueber viele Rahmen: Mikrofon gegen MITTELWERT der
      // Wiedergabe -- das gleicht Silbenluecken und die Verzoegerung des Echos aus). Gemessen an einem
      // kuenstlichen Echo in vier Staerken:
      //  - Augenblick gegen Fenster-Spitze verglichen lag die Kopplung mal 4x zu tief (Fehlalarm), mal zu hoch.
      //  - Alles unter der Schwelle gelernt, kletterte sie waehrend Veikos Einwurf mit (0,07 -> 0,5).
      //  - Zu frueh festgelegt, war sie zu tief: das Echo kommt erst nach dem Laden und mit Verzoegerung an.
      // Deshalb: Einlernzeit von ~0,7 s Wiedergabe (die ersten 3 Rahmen ausgelassen), danach nur Rahmen,
      // die nicht ueber der Schwelle liegen.
      if (pw !== null && pw > 0) wiedRahmen++;
      const einlernen = pw !== null && wiedRahmen > 0 && wiedRahmen <= 17;
      const warm = t - start <= 300 || einlernen || (pw !== null && pw > 0 && kopplung === null);
      if (!warm) { if (rms > schwelle) ueber++; else ueber = 0; }
      if (warm || rms <= schwelle) {
        echoSpitze = Math.max(echoSpitze * 0.995, rms);
        const pm = wiedergabePegel(true);
        if (pm !== null && pm > 0.02 && wiedRahmen > 3) {
          sMik = sMik * 0.97 + rms; sWied = sWied * 0.97 + pm;
          if (wiedRahmen >= 17) kopplung = Math.min(3, sMik / Math.max(sWied, 1e-6));
        }
      }
      spitze = Math.max(spitze, rms);
      mittel = mittel * 0.92 + Math.min(rms, schwelle) * 0.08;
      // Grundrauschen als langsam steigendes MINIMUM (verdoppelt sich ohne leise Stelle in ~3 s): ein Mittel
      // der leisen Rahmen zaehlte Echo-Reste mit, und leises Reden in Talks Sprechpausen blieb darunter.
      boden = rms < boden ? Math.max(rms, 0.0005) : boden * 1.01;
      if (ueber >= 5) {            // ~210 ms bei 48 kHz
        einsatz = t;
        aufnahme = ring; ring = [];
        Object.assign(bericht, { einsatz: true, mittel_bei_einsatz: +mittel.toFixed(4), schwelle_bei_einsatz: +schwelle.toFixed(4), spitze_vorher: +spitze.toFixed(4), rahmen_ueber: ueber });
        if (beiEinsatz) beiEinsatz();
      }
      return;
    }
    aufnahme.push(kopie);
    if (pegel) pegel(Math.min(1, rms * 10));
    // Talk schweigt jetzt -- Stille heisst: zurueck in die Naehe des Grundrauschens.
    if (rms > Math.max(0.012, boden * 2.5)) stilleSeit = 0; else if (!stilleSeit) stilleSeit = t;
    if ((stilleSeit && t - stilleSeit > 1000) || t - einsatz > 60000) schluss(wavAus(aufnahme, rate));
  };
  quelle.connect(proz); proz.connect(stumm); stumm.connect(ctx.destination);
  bericht.spitze_vorher = 0;
  return {
    ende,
    eingesetzt: () => !!einsatz,
    bericht: () => ({ ...bericht, ...diag, echo_spitze: +echoSpitze.toFixed(4), kopplung: kopplung === null ? null : +kopplung.toFixed(3), spitze_vorher: bericht.einsatz ? bericht.spitze_vorher : +spitze.toFixed(4), mittel_ende: +mittel.toFixed(4), boden: +boden.toFixed(4) }),
    // Talk ist fertig mit Sprechen: ohne Einsatz ist nichts aufzuheben.
    loslassen() { if (!einsatz) schluss(null); },
    // Von Hand unterbrochen (Kreis angetippt): sofort als Einsatz werten -- was davor gesagt
    // wurde, geht aus dem Puffer mit.
    jetzt() { if (!einsatz && !aus) { einsatz = performance.now(); aufnahme = ring; ring = []; bericht.einsatz = "hand"; } },
    abbrechen() { schluss(null); },
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
// Was gerade klingt: die Lautstaerkekurve des laufenden Stuecks (huelle, je 50 ms) -- damit das Mithoeren
// weiss, wie laut Talk in DIESEM Augenblick ist (lauschen), und was nach einem Abbruch noch zu sagen waere.
let klingt = null, klangEnde = 0, klangLetzter = 0, vorleseRest = "";
export function vorleseStopp() {
  vorleseNr++;   // auch ein noch ladendes Vorlesen spielt danach nicht mehr ab
  if (laufend) { laufend.pause(); laufend.dispatchEvent(new Event("ended")); laufend = null; }
}
// Der Teil einer Antwort, der nach einem Ins-Wort-Fallen noch nicht gesagt war (ab dem unterbrochenen Satz).
export function rest() { return vorleseRest; }

// Wie laut Talk gerade klingt (0..1, Spitze im Fenster der letzten 200 ms -- laenger haengt das Echo selten
// nach, und ein laengeres Fenster ueberdeckte die Luecken zwischen Talks Silben, in denen Veiko einsetzen kann).
// null = unbekannt (Kurve noch nicht berechnet); 0 = Talk schweigt.
// mittel=true: Mittelwert im selben Fenster -- fuer das Lernen der Kopplung (siehe lauschen).
export function wiedergabePegel(mittel = false) {
  const jetzt = performance.now();
  if (!klingt || !laufend) return jetzt - klangEnde < 300 ? (mittel ? klangLetzter / 2 : klangLetzter) : 0;
  if (!klingt.huelle) return null;
  const t = laufend.currentTime, h = klingt.huelle;
  const von = Math.max(0, Math.floor((t - 0.2) / 0.05)), bis = Math.min(h.length - 1, Math.ceil((t + 0.05) / 0.05));
  let m = 0, s = 0; for (let i = von; i <= bis; i++) { m = Math.max(m, h[i]); s += h[i]; }
  if (mittel) return s / Math.max(1, bis - von + 1);
  klangLetzter = m;
  return m;
}
async function huelleBerechnen(blob, ziel) {
  try {
    const ctx = tonKontextHolen();
    if (!ctx) return;
    const buf = await ctx.decodeAudioData(await blob.arrayBuffer());
    const d = buf.getChannelData(0), n = Math.max(1, Math.round(buf.sampleRate * 0.05));
    const h = new Float32Array(Math.ceil(d.length / n));
    for (let i = 0; i < h.length; i++) {
      let s = 0; const a = i * n, b = Math.min(d.length, a + n);
      for (let j = a; j < b; j++) s += d[j] * d[j];
      h[i] = Math.sqrt(s / Math.max(1, b - a));
    }
    ziel.huelle = h;
  } catch (e) { /* ohne Kurve gilt die alte Schwelle */ }
}

// Satzweise statt am Stueck (22.10.2026, Veiko: "der Dialog ist immer noch mit vielen Pausen"): eine
// Antwort von 300 Zeichen brauchte gemessen 2,9 s Vertonung, bevor das erste Wort kam; ein Satz 0,8 s.
// Jetzt erklingt der erste Satz, waehrend der Rest schon vertont wird. Getrennt wird nur an einem
// echten Satzende -- "20. Oktober" und "z. B." bleiben zusammen.
function saetze(text) {
  const teile = [];
  let start = 0;
  const re = /[.!?…:]["“”]?\s+/g;
  let m;
  while ((m = re.exec(text))) {
    const vor = text.slice(start, m.index).split(/\s+/).pop() || "";
    const nach = text.charAt(m.index + m[0].length);
    if (vor.length >= 3 && !/^\d+$/.test(vor) && !/^(bzw|usw|ggf|inkl|evtl|ca|Nr|Dr|vgl)$/i.test(vor) && /[A-ZÄÖÜ„"0-9]/.test(nach)) {
      teile.push(text.slice(start, m.index + m[0].length).trim());
      start = m.index + m[0].length;
    }
  }
  if (start < text.length) teile.push(text.slice(start).trim());
  // Kurze Saetze zusammenlegen (jeder Abruf kostet ~0,8 s Grundzeit); der ERSTE bleibt kurz.
  const stuecke = [];
  for (const s of teile.filter(Boolean)) {
    const l = stuecke[stuecke.length - 1];
    if (l !== undefined && stuecke.length > 1 && (l + " " + s).length < 280) stuecke[stuecke.length - 1] = l + " " + s;
    else if (l !== undefined && stuecke.length === 1 && l.length < 40) stuecke[0] = l + " " + s;
    else stuecke.push(s);
  }
  return stuecke;
}
function stimmeHolen(t) {
  return fetch("/api/stimme/sprechen", { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: t.slice(0, 2500) }) })
    .then((r) => { if (!r.ok) throw new Error("Sprachausgabe nicht erreichbar"); return r.blob(); });
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
    const stuecke = saetze(sauber.slice(0, 2500));
    vorleseRest = stuecke.join(" ");
    let naechstes = stimmeHolen(stuecke[0]);
    for (let i = 0; i < stuecke.length; i++) {
      const daten = await naechstes;
      if (nr !== vorleseNr) return;
      // Das naechste Stueck wird vertont, waehrend dieses klingt.
      if (i + 1 < stuecke.length) { naechstes = stimmeHolen(stuecke[i + 1]); naechstes.catch(() => {}); }
      vorleseRest = stuecke.slice(i).join(" ");
      const url = URL.createObjectURL(daten);
      const a = abspieler();
      const stueck = { huelle: null };
      huelleBerechnen(daten, stueck);
      a.src = url;
      laufend = a; klingt = stueck;
      const fertig = await new Promise((ok) => {
        a.addEventListener("ended", () => ok(true), { once: true });
        a.addEventListener("error", () => ok(true), { once: true });
        a.play().catch((e) => {
          // Nicht mehr still: wer nichts hoert, soll wissen warum und was hilft (einmal je Seite).
          if (e && e.name === "NotAllowedError" && !blockiertGemeldet) {
            blockiertGemeldet = true;
            toast("Der Browser hat den Ton blockiert. Tippe einmal irgendwo ins Cockpit -- danach liest es vor.", { fehler: true, dauer: 8000 });
          }
          ok(false);
        });
      });
      URL.revokeObjectURL(url);
      klangEnde = performance.now(); klingt = null;
      if (laufend === a) laufend = null;
      if (!fertig || nr !== vorleseNr) return;
    }
    vorleseRest = "";
  } finally {
    if (!vonTalk) mikroFreigeben("vorlesen");
  }
}
