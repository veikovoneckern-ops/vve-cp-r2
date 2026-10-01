// KOPFZEILE -- Logo, Lage der Maschine, Sprechen.
//
// Das Logo ist Veikos eigenes (aus dem alten Cockpit uebernommen) und wird als
// MASKE gezeichnet, nicht als Bild: so nimmt es die Schriftfarbe an, sieht im
// hellen wie im dunklen Modus sauber aus und kann sich gruen faerben. Es dreht
// sich, solange eine lokale KI rechnet -- eigene Aufrufe (Stab, Talk, Neo)
// ODER Last auf den Grafikkarten (altes Cockpit, ComfyUI rechnen dort auch).
//
// Die Statusleiste zeigt dieselbe Auswahl wie die Kaestchen im alten Cockpit,
// knapper. Ein Klick fuehrt in den Bereich System, der alle Einzelheiten hat.
// Werte, die nicht gemeldet werden, fehlen -- es wird nichts geschaetzt.
import { html, useEffect, useState, Icon, bus, navigiere } from "./ui.js";
import { api } from "./api.js";

let letzterKopf = null;

// Ein Abruf fuer alle: die Kopfzeile und das Logo lesen denselben Stand.
export function useKopf() {
  const [k, setK] = useState(letzterKopf);
  useEffect(() => bus.an("kopf", setK), []);
  return k;
}

export function kopfAbruf() {
  let aus = false, timer = null;
  const holen = async () => {
    if (aus) return;
    if (!document.hidden) {
      try {
        letzterKopf = await api("/kopf");
        bus.sende("kopf", letzterKopf);
        document.documentElement.classList.toggle("ki-arbeitet", !!(letzterKopf.ki && letzterKopf.ki.arbeitet));
      } catch (e) { /* Kopfzeile bleibt beim letzten Stand; die Ampel sagt es */ }
    }
    // Schneller, solange gerechnet wird -- dann soll das Logo auch zeitig stehen bleiben.
    timer = setTimeout(holen, letzterKopf && letzterKopf.ki && letzterKopf.ki.arbeitet ? 3000 : 6000);
  };
  holen();
  const sofort = bus.an("ki-start", () => { clearTimeout(timer); document.documentElement.classList.add("ki-arbeitet"); timer = setTimeout(holen, 2500); });
  return () => { aus = true; clearTimeout(timer); sofort(); };
}

export function Logo({ gross = false }) {
  const k = useKopf();
  const ki = k && k.ki;
  const titel = ki && ki.arbeitet
    ? (ki.aufrufe ? `Lokale KI rechnet (${ki.aufrufe} ${ki.aufrufe === 1 ? "Anfrage" : "Anfragen"})` : `Grafikkarten arbeiten (${ki.gpu_last} %)`)
    : "Zum Briefing";
  return html`<a class=${"logo-knopf" + (gross ? " gross" : "")} href="#/briefing" title=${titel} aria-label=${titel}>
    <span class="logo" aria-hidden="true"></span></a>`;
}

const TEXT_STUFE = { ok: "", warn: "warn", krit: "krit" };
function stufe(wert, warn, krit) { return wert == null ? "" : wert >= krit ? "krit" : wert >= warn ? "warn" : "ok"; }

function alterText(h) {
  if (h == null) return "nie";
  if (h < 24) return "heute";
  return Math.floor(h / 24) + " T";
}

// Die Ampel vorn: das Wichtigste in einem Satz. Reihenfolge = Dringlichkeit.
function ampel(k, gesundheit) {
  if (!k) return ["", "Stand wird geholt …"];
  if (!k.status_da) return ["krit", "Status-Dienst antwortet nicht"];
  const e = k.empfehlungen;
  if (e && e.achtung) return ["krit", e.titel[0] || `${e.achtung} Punkt${e.achtung > 1 ? "e" : ""} zur Beachtung`];
  const jetzt = Date.now() / 1000;
  if (gesundheit && gesundheit.sync && jetzt - gesundheit.sync > 1800) return ["krit", "Plaud-Abruf hängt"];
  if (k.updates && k.updates.neustart) return ["warn", "Neustart fällig"];
  if (gesundheit && !gesundheit.stab_aktiv) return ["warn", "Stab ist ausgeschaltet"];
  if (gesundheit && gesundheit.letzter_fehler) return ["warn", "Letzter Stab-Durchgang mit Fehler"];
  if (e && e.einspielen) return ["warn", e.titel[0] || "Updates bereit"];
  return ["ok", "Alles läuft"];
}

export function KopfStatus({ gesundheit }) {
  const k = useKopf();
  const [s, satz] = ampel(k, gesundheit);
  const z = [];
  if (k && k.status_da) {
    if (k.netz) z.push({ b: k.netz.art, w: k.netz.tempo || "", s: k.netz.art === "WLAN" ? "warn" : "ok", p: 2,
      t: k.netz.art === "WLAN" ? "Server hängt am WLAN statt am Kabel" : "Server per Kabel verbunden" });
    if (k.cpu_c != null) z.push({ b: "CPU", w: Math.round(k.cpu_c) + "°", s: stufe(k.cpu_c, 80, 88), p: 1, t: "Prozessortemperatur" });
    if (k.ram_p != null) z.push({ b: "RAM", w: k.ram_p + " %", s: stufe(k.ram_p, 80, 92), p: 2, t: "Arbeitsspeicher belegt" });
    if (k.gpus && k.gpus.length) {
      const heiss = Math.max(...k.gpus.map((g) => g.temp));
      const belegt = k.gpus.reduce((a, g) => a + g.belegt_gb, 0), ges = k.gpus.reduce((a, g) => a + g.gesamt_gb, 0);
      z.push({ b: "GPU", w: k.gpus.map((g) => g.temp + "°").join(" "), s: stufe(heiss, 80, 88), p: 1,
        t: k.gpus.map((g, i) => `Karte ${i + 1}: ${g.temp} °C, Last ${g.last} %, ${g.belegt_gb} von ${g.gesamt_gb} GB`).join("\n") });
      z.push({ b: "VRAM", w: `${Math.round(belegt)}/${ges} GB`, s: stufe(belegt / (ges || 1) * 100, 85, 95), p: 3, t: "Grafikspeicher beider Karten" });
    }
    if (k.watt != null) z.push({ b: "Strom", w: k.watt + " W", s: "ok", p: 3, t: "Server und Docks zusammen, gemessen an den Steckdosen" });
    if (k.updates && k.updates.offen != null) z.push({ b: "Updates", w: String(k.updates.offen),
      s: k.updates.sicherheit ? "krit" : k.updates.offen ? "warn" : "ok", p: 2,
      t: k.updates.sicherheit ? `${k.updates.offen} offen, davon ${k.updates.sicherheit} Sicherheit` : `${k.updates.offen} Pakete aktualisierbar (gestaffelte mitgezählt)` });
  }
  if (k && k.sicherungen) {
    [["inhalt", "Cockpit", 2], ["server", "Server", 9]].forEach(([art, name, grenzeTage]) => {
      const x = k.sicherungen[art];
      if (!x) return;
      const s2 = x.zustand && x.zustand !== "ok" ? "krit" : x.alter_h == null ? "warn" : x.alter_h / 24 > grenzeTage ? "warn" : "ok";
      z.push({ b: "Backup " + name, w: x.zustand && x.zustand !== "ok" ? "Fehler" : alterText(x.alter_h), s: s2, p: 3, t: "Sicherung nach OneDrive" });
    });
  }
  const titel = [satz, k && k.host ? `${k.host}${k.uptime ? " · läuft seit " + k.uptime : ""}` : ""].filter(Boolean).join("\n") + "\n\nKlicken für alle Einzelheiten";
  return html`<button class="kopf-status" onClick=${() => navigiere("/system")} title=${titel} aria-label=${"Systemstatus: " + satz + ". Für Einzelheiten öffnen."}>
    <span class=${"ampel " + TEXT_STUFE[s]}><i></i><span class="satz">${satz}</span></span>
    ${z.map((x) => html`<span class=${"chip p" + x.p + " " + x.s} title=${x.t}><span>${x.b}</span><b>${x.w}</b></span>`)}
  </button>`;
}

// Der zentrale Knopf: ein Klick, und das Gespraech laeuft (Talk geht auf und
// hoert sofort zu). Noch ein Klick beendet es. Der Zustand kommt vom Talk selbst.
export function SprechKnopf() {
  const [zustand, setZustand] = useState(null);
  useEffect(() => bus.an("dialog-zustand", setZustand), []);
  const TXT = { hoert: "Ich höre zu", erkennt: "Verstehe …", denkt: "Denke nach …", spricht: "Spreche …" };
  const an = !!zustand;
  return html`<button class=${"sprech-knopf" + (an ? " an " + zustand : "")} aria-pressed=${an}
    onClick=${() => bus.sende(an ? "dialog-ende" : "dialog-start")}
    title=${an ? "Gespräch beenden (oder sag „Dialog beenden“)" : "Mit dem Cockpit sprechen"}>
    <span class="sk-symbol"><${Icon} n="mic" g=${16} w=${2.1} /></span>
    <span class="sk-text">${an ? TXT[zustand] || "Im Gespräch" : "Sprechen"}</span>
    ${an && html`<span class="sk-ende" aria-hidden="true"><${Icon} n="x" g=${12} w=${2.4} /></span>`}
  </button>`;
}
