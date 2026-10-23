// KOPFZEILE -- Logo, Lage, Sprechen. Aufbau wie im alten Cockpit (Veiko, 01.10.:
// "damit bin ich gut zurechtgekommen"): links der Titel der Ansicht, dann die
// Cockpit-Werte als eine Leiste, dann die Server-Kaestchen (Wert oben, Bezeichnung
// darunter). Ein Klick auf die Server-Kaestchen klappt die Server-Sektion auf.
//
// Symmetrie: alle Kaesten sind gleich hoch und sitzen auf derselben Mittellinie
// wie der Titel. Die Hostzeile, die im alten Cockpit unter den Kaesten hing und
// die Reihe aus der Mitte schob, steht jetzt im Kopf der Server-Sektion.
//
// Das Logo ist Veikos eigenes, als MASKE gezeichnet (nimmt jede Farbe an). Es
// dreht sich, solange eine lokale KI rechnet, und traegt dann die Farbe der
// LED-Leiste auf den Grafikkarten: weiss bei wenig Last, rot unter Volllast --
// dieselbe Rechnung wie vve-rgb.py und ledFarbe() im alten Layer.
import { html, useEffect, useState, Icon, bus, zeitText, toast } from "./ui.js";
import { api } from "./api.js";

let letzterKopf = null;

export function useKopf() {
  const [k, setK] = useState(letzterKopf);
  useEffect(() => bus.an("kopf", setK), []);
  return k;
}

// Wie vve-rgb.py: wert = 255 * (1 - last/100), Farbe FF<wert><wert>. ohneRuhe:
// das Logo leuchtet nur WAEHREND gerechnet wird und darf dann nicht das Blau
// fuer "Karte tut nichts" tragen (zwischen zwei Antwortschritten meldet
// nvidia-smi kurz 0 %). Wer die Regel aendert, aendert sie dort mit.
export function ledFarbe(last, ohneRuhe) {
  const l = Math.max(0, Math.min(100, Number(last) || 0));
  if (l <= 5 && !ohneRuhe) return { hex: "#0000ff", ruhe: true, last: l };
  const h = Math.round(255 * (1 - l / 100)).toString(16).padStart(2, "0");
  return { hex: "#ff" + h + h, ruhe: false, last: l };
}

function logoSetzen(k) {
  const an = !!(k && k.ki && k.ki.arbeitet);
  const r = document.documentElement;
  r.classList.toggle("ki-arbeitet", an);
  if (an) r.style.setProperty("--logo-last", ledFarbe(k.ki.gpu_last, true).hex);
  else r.style.removeProperty("--logo-last");
}

export function kopfAbruf() {
  let aus = false, timer = null;
  const holen = async () => {
    if (aus) return;
    // Der erste Abruf laeuft immer, auch in einem verdeckten Tab -- sonst
    // stuende die Kopfzeile leer, bis jemand hinsieht.
    if (!document.hidden || !letzterKopf) {
      try {
        letzterKopf = await api("/kopf");
        bus.sende("kopf", letzterKopf);
        logoSetzen(letzterKopf);
      } catch (e) { /* Kopfzeile bleibt beim letzten Stand */ }
    }
    timer = setTimeout(holen, letzterKopf && letzterKopf.ki && letzterKopf.ki.arbeitet ? 3000 : 6000);
  };
  holen();
  const sofort = bus.an("ki-start", () => {
    clearTimeout(timer);
    document.documentElement.classList.add("ki-arbeitet");
    timer = setTimeout(holen, 2500);
  });
  return () => { aus = true; clearTimeout(timer); sofort(); };
}

// beiKlick (23.10.2026, Veiko: "wenn ich oben links auf das Logo klicke, soll sich die Menüleiste links
// ausblenden, damit ich die volle Breite nutzen kann"): dann ist das Logo ein Knopf statt ein Link
// zum Briefing. Auf dem Telefon bleibt es der Link -- dort gibt es keine linke Leiste.
export function Logo({ gross = false, beiKlick = null, zweck = "" }) {
  const k = useKopf();
  const ki = k && k.ki;
  const rechnet = ki && ki.arbeitet
    ? `Lokale KI rechnet · Grafikkarten ${ki.gpu_last} %` + (ki.aufrufe ? ` · ${ki.aufrufe} ${ki.aufrufe === 1 ? "Anfrage" : "Anfragen"}` : "")
    : "";
  if (beiKlick) {
    const titel = (rechnet ? rechnet + " · " : "") + zweck;
    return html`<button class=${"logo-knopf" + (gross ? " gross" : "")} onClick=${beiKlick} title=${titel} aria-label=${zweck}>
      <span class="logo" aria-hidden="true"></span></button>`;
  }
  const titel = rechnet || "Zum Briefing";
  return html`<a class=${"logo-knopf" + (gross ? " gross" : "")} href="#/briefing" title=${titel} aria-label=${titel}>
    <span class="logo" aria-hidden="true"></span></a>`;
}

// Vollbild (23.10.2026, Veiko: "dass gar nicht mehr der Rahmen vom Browser und die einzelnen Tabs zu sehen
// sind, sondern das Cockpit wirklich den gesamten Screen ausfüllt"). Die Vollbild-Schnittstelle des
// Browsers; Escape beendet es wie gewohnt. Wo der Browser sie nicht anbietet (Safari auf dem iPhone),
// erscheint der Knopf gar nicht -- ein Knopf, der nichts tut, waere schlimmer als keiner.
export function VollbildKnopf() {
  const geht = !!(document.fullscreenEnabled || document.webkitFullscreenEnabled);
  const [an, setAn] = useState(() => !!(document.fullscreenElement || document.webkitFullscreenElement));
  useEffect(() => {
    const f = () => setAn(!!(document.fullscreenElement || document.webkitFullscreenElement));
    document.addEventListener("fullscreenchange", f);
    document.addEventListener("webkitfullscreenchange", f);
    return () => { document.removeEventListener("fullscreenchange", f); document.removeEventListener("webkitfullscreenchange", f); };
  }, []);
  if (!geht) return null;
  function umschalten() {
    const d = document, e = d.documentElement;
    try {
      const p = (d.fullscreenElement || d.webkitFullscreenElement)
        ? (d.exitFullscreen || d.webkitExitFullscreen).call(d)
        : (e.requestFullscreen || e.webkitRequestFullscreen).call(e);
      if (p && p.catch) p.catch(abgelehnt);
    } catch (x) { abgelehnt(); }
  }
  // Lehnt der Browser ab (eingebettete Ansicht, Richtlinie), wird das gesagt statt still nichts zu tun.
  function abgelehnt() {
    toast("Der Browser lässt hier kein Vollbild zu. Taste F11 schaltet es am Rechner ebenfalls um.");
  }
  const titel = an ? "Vollbild beenden (Esc)" : "Vollbild: Browserrahmen und Tabs ausblenden";
  return html`<button class=${"kopf-icon vollbild" + (an ? " an" : "")} onClick=${umschalten} aria-pressed=${an} title=${titel} aria-label=${titel}>
    <${Icon} n=${an ? "klein" : "voll"} g=${17} /></button>`;
}

const STUFE = (wert, warn, krit) => (wert == null ? "" : wert >= krit ? "kritisch" : wert >= warn ? "warnung" : "");

// Die Server-Kaestchen. Reihenfolge und Auswahl wie im alten Cockpit; dazu die
// Grafikkarten, die es dort nur in der Sektion gab (seit zwei Karten wichtig).
export function serverKaesten(k) {
  const v = [];
  if (!k) return v;
  const e = k.empfehlungen;
  if (e && (e.achtung || e.einspielen)) {
    v.push({ b: "Empfehlungen", w: e.achtung ? `${e.achtung} jetzt` : `${e.einspielen} offen`, s: e.achtung ? "kritisch" : "warnung", p: 1,
      t: e.titel.join("\n") });
  }
  if (!k.status_da) { v.push({ b: "Status", w: "fehlt", s: "kritisch", p: 1, t: "Der Status-Dienst antwortet nicht" }); return v; }
  if (k.netz) v.push({ b: "Netz", w: k.netz.art + (k.netz.tempo ? " · " + k.netz.tempo : ""), s: k.netz.art === "WLAN" ? "warnung" : "", p: 2,
    t: k.netz.art === "WLAN" ? "Der Server hängt am WLAN statt am Kabel" : "Per Kabel verbunden" });
  if (k.cpu_c != null) v.push({ b: "CPU", w: Math.round(k.cpu_c) + " °C", s: STUFE(k.cpu_c, 80, 88), p: 1, t: "Prozessortemperatur" });
  if (k.gpus && k.gpus.length) {
    const heiss = Math.max(...k.gpus.map((g) => g.temp));
    v.push({ b: "GPU", w: k.gpus.map((g) => g.temp + "°").join(" · "), s: STUFE(heiss, 80, 88), p: 1,
      t: k.gpus.map((g, i) => `Karte ${i + 1}: ${g.temp} °C, Last ${g.last} %, ${g.belegt_gb} von ${g.gesamt_gb} GB`).join("\n") });
  }
  if (k.ram_p != null) v.push({ b: "RAM", w: k.ram_p + " %", s: STUFE(k.ram_p, 80, 92), p: 2, t: "Arbeitsspeicher belegt" });
  if (k.last != null) v.push({ b: "Last", w: k.last.toFixed(2), s: STUFE(k.last / (k.kerne || 24) * 100, 80, 95), p: 3, t: "Systemlast der letzten Minute" });
  if (k.updates && k.updates.offen != null) v.push({ b: "Updates", w: String(k.updates.offen), s: k.updates.sicherheit ? "kritisch" : k.updates.offen ? "warnung" : "", p: 2,
    t: k.updates.sicherheit ? `davon ${k.updates.sicherheit} Sicherheit` : "aktualisierbare Pakete, gestaffelte mitgezählt" });
  if (k.updates && k.updates.neustart) v.push({ b: "Neustart", w: "fällig", s: "warnung", p: 1, t: "Ein Update wird erst nach einem Neustart wirksam" });
  // "neu" = die neue Fassung (sicherung.py, 23.10.2026); "inhalt" ist seitdem das ALTE Cockpit.
  [["neu", "Cockpit", 2], ["inhalt", "alt", 2], ["server", "Server", 9]].forEach(([art, name, grenze]) => {
    const x = k.sicherungen && k.sicherungen[art];
    if (!x) return;
    const fehlt = x.zustand === "nicht_eingerichtet";
    const fehler = x.zustand && x.zustand !== "ok" && !fehlt;
    const tage = x.alter_h == null ? null : Math.floor(x.alter_h / 24);
    v.push({ b: "Backup " + name, w: fehlt ? "fehlt" : fehler ? "Fehler" : x.alter_h == null ? "nie" : x.alter_h < 24 ? "heute" : tage + " T",
      s: fehler || fehlt ? "kritisch" : x.alter_h == null || tage > grenze ? "warnung" : "", p: 3,
      t: fehlt ? "Das neue Cockpit wird noch nicht nach OneDrive gesichert -- Stack → Sicherungen" : art === "inhalt" ? "Sicherung des alten Cockpits nach OneDrive" : "Sicherung nach OneDrive" });
  });
  return v;
}

// Die Ampel fuer die Kopfzeile der Server-Sektion und das Telefon.
export function ampel(k, gesundheit) {
  if (!k) return ["", "Stand wird geholt …"];
  if (!k.status_da) return ["kritisch", "Status-Dienst antwortet nicht"];
  const e = k.empfehlungen;
  if (e && e.achtung) return ["kritisch", e.titel[0] || "Etwas braucht Aufmerksamkeit"];
  if (gesundheit && gesundheit.sync && Date.now() / 1000 - gesundheit.sync > 1800) return ["kritisch", "Plaud-Abruf hängt"];
  if (k.updates && k.updates.neustart) return ["warnung", "Neustart fällig"];
  if (e && e.einspielen) return ["warnung", e.titel[0] || "Updates bereit"];
  return ["ok", "alles ruhig"];
}

// Die Cockpit-Leiste links neben den Server-Kaestchen (im alten Cockpit
// "Letzter Import · Zuletzt gesichert · Import Notes").
export function CockpitLeiste({ lage }) {
  const g = lage && lage.gesundheit;
  const offen = lage ? lage.entscheidungen.length : 0;
  // Vorgemerktes zaehlt mit (21.10.2026): am iPad stand hier "leer", waehrend die Gedaechtnis-
  // Notiz in der Inbox hing und das Symbol links rot war -- zwei Anzeigen, zwei Aussagen.
  const vm = lage ? (lage.vorgemerkt || []).length : 0;
  const alt = g && g.sync && Date.now() / 1000 - g.sync > 1800;
  const inboxTitel = [offen ? `${offen} ${offen === 1 ? "Entscheidung wartet" : "Entscheidungen warten"} auf dich` : "",
    vm ? `${vm} vorgemerkt, wartet auf deine Freigabe` : ""].filter(Boolean).join(" · ") || "Nichts wartet auf dich";
  return html`<div class="kopf-leiste" role="group" aria-label="Stand des Cockpits">
    <div class=${alt ? "kritisch" : ""} title="Letzter erfolgreicher Abruf der Plaud-Notizen"><b>${g && g.sync ? zeitText(g.sync).replace("vor ", "") : "—"}</b><span>Letzter Abruf</span></div>
    <div title="Wann zuletzt eine neue Notiz hereinkam"><b>${g && g.letzte_datei ? zeitText(g.letzte_datei).replace("vor ", "") : "—"}</b><span>Letzte Notiz</span></div>
    <a href="#/inbox" class=${offen || vm ? "kritisch" : ""} title=${inboxTitel}>
      <b>${offen ? offen + " offen" : vm ? vm + " vorgemerkt" : "leer"} <${Icon} n="rechts" g=${11} w=${2.4} /></b><span>Inbox</span></a>
  </div>`;
}

export function ServerKaesten({ offen, umschalten, gesundheit }) {
  const k = useKopf();
  const v = serverKaesten(k);
  const [s, satz] = ampel(k, gesundheit);
  return html`<button class=${"kopf-server" + (offen ? " offen" : "")} onClick=${umschalten} aria-current=${offen ? "page" : null}
      title=${(k && k.host ? `${k.host}${k.uptime ? " · läuft seit " + k.uptime : ""} · ` : "") + satz + "\nKlicken: alles zum Server (Seite System)"}>
    <i class=${"kopf-ampel " + s} aria-hidden="true"></i>
    <span class="kopf-kaesten">${v.map((x) => html`<span class=${"p" + x.p + " " + x.s} title=${x.t}><b>${x.w}</b><span>${x.b}</span></span>`)}</span>
    <span class="kopf-pfeil"><${Icon} n="runter" g=${16} w=${2.2} /></span>
  </button>`;
}

const TALK_TXT = { hoert: "Talk hört zu", erkennt: "Talk versteht …", denkt: "Talk denkt nach …", spricht: "Talk spricht …", pausiert: "Talk pausiert · dein Diktat hat Vorfahrt" };

// Talk bleibt sichtbar, auch wenn ein Fenster darueber liegt (19.10.2026): Veiko sah
// nicht, ob Talk noch zuhoert, waehrend er im Fenster diktierte -- und beide nahmen
// dasselbe Mikrofon. Die Pille sagt, wer gerade Vorfahrt hat, und laesst Talk
// weiterlaufen oder beenden. Auf breiten Bildschirmen liegt das Fenster ohnehin
// neben Talk (CSS), dort blendet sie sich aus.
// Der Zustand wird hier mitgefuehrt: die Pille entsteht erst, wenn ein Fenster aufgeht --
// Talk hat seinen Zustand da laengst gemeldet, und ohne Gedaechtnis stuende sie leer da.
let talkZustand = null;
bus.an("dialog-zustand", (z) => { talkZustand = z; });

export function TalkPille() {
  const [zustand, setZustand] = useState(() => talkZustand);
  useEffect(() => bus.an("dialog-zustand", setZustand), []);
  if (!zustand) return null;
  const pause = zustand === "pausiert";
  return html`<div class=${"talk-pille " + zustand} role="status" aria-live="polite">
    <span class="talk-pille-punkt" aria-hidden="true"><${Icon} n=${pause ? "play" : "mic"} g=${13} w=${2.2} /></span>
    <span class="talk-pille-text">${TALK_TXT[zustand] || "Talk läuft"}</span>
    ${pause && html`<button class="btn klein primaer" onClick=${() => bus.sende("dialog-weiter")}>Weiter zuhören</button>`}
    <button class="btn klein" onClick=${() => bus.sende("dialog-ende")}>Beenden</button>
  </div>`;
}

// Der zentrale Knopf: ein Klick, und das Gespraech laeuft. Der Zustand kommt vom Talk.
// Nur das Mikrofon, ohne Beschriftung (Veiko: "es reicht das Mikrofonsymbol");
// was er tut, steht im Hinweis beim Ueberfahren.
export function SprechKnopf() {
  const [zustand, setZustand] = useState(null);
  useEffect(() => bus.an("dialog-zustand", setZustand), []);
  const an = !!zustand;
  const pause = zustand === "pausiert";
  return html`<button class=${"sprech-knopf" + (an ? " an " + zustand : "")} aria-pressed=${an}
    onClick=${() => bus.sende(pause ? "dialog-weiter" : an ? "dialog-ende" : "dialog-start")}
    title=${pause ? "Talk ist pausiert, weil du diktierst · Klicken: Talk hört wieder zu" : an ? (TALK_TXT[zustand] || "Im Gespräch") + " · Klicken: Gespräch beenden und Talk schließen" : "Mit dem Cockpit sprechen"}
    aria-label=${an ? "Gespräch beenden" : "Mit dem Cockpit sprechen"}>
    <${Icon} n="mic" g=${19} w=${2.1} />
  </button>`;
}
