// STACK (bis 17.10.2026 "System", bis 19.10.2026 "Maschine") -- alles zum Server an
// einem Ort: oben die Server-Sektion (Aufbau, Updates, Sicherungen, Software,
// Messwerte), darunter der WatchDog (Temperatur, Notabschaltung, Sicherheit) und
// ganz unten die Website (Veiko, 19.10.2026: "welche Hauptseiten gibt es, wie
// aktuell ist meine Webseite, und wie ist das angebunden -- kuenftig moechte ich da
// noch mehr haben, und das soll dann auch immer aktuell sein"). Nichts davon ist von
// Hand gepflegt: webspace.stack_ueberblick liest Menue, Seiten und Blog aus dem Klon,
// den Bau von GitHub und die Erreichbarkeit aus einem echten Abruf.
//
// Neu geordnet (Veiko, 17.10.2026: "viele Punkte zu System und Setup sind auf
// unterschiedliche Ansichten verteilt"): der WatchDog hatte eine eigene Seite mit
// einer zweiten Kopie von Aufbau und Wartung; Team-Pipeline, Daten und Konto
// stehen unter Einstellungen, Modelle unter Team, Verbrauch unter Usage.
// Die Kennung bleibt "system", damit alte Links und die Kopfzeile weiter passen.
import { html, useState, useEffect, Icon, bus, Klappe, useAbschnitt, zeitText, fehlerMelden } from "./ui.js";
import { api } from "./api.js";
import { ServerSektion } from "./server.js";
import { WatchDog } from "./watchdog.js";

export function System({ gesundheit, abschnitt }) {
  useEffect(() => { bus.sende("talk-kontext", { art: "stack", id: "stack", titel: "Stack" }); return () => bus.sende("talk-kontext", null); }, []);
  useAbschnitt(abschnitt);
  return html`<div class="seite">
    <${ServerSektion} gesundheit=${gesundheit} />
    <div style="margin-top:14px"><${Klappe} id="watchdog" titel="WatchDog" unter="Temperatur, Notabschaltung und Sicherheit -- läuft unabhängig vom Cockpit" vorgabe=${true}>
      <${WatchDog} eingebettet=${true} /></${Klappe}></div>
    <${Klappe} id="website" titel="Website veikovoneckern.org" unter="Was online ist, wie aktuell es ist und wie es angebunden ist" vorgabe=${true}>
      <${WebsiteStand} /></${Klappe}>
  </div>`;
}

const ohneSchraeg = (h) => String(h || "").replace(/\/+$/, "") || "/";

function WebsiteStand() {
  const [d, setD] = useState(null);
  const [fehler, setFehler] = useState("");
  const [prueft, setPrueft] = useState(false);
  const holen = (frisch) => {
    setPrueft(true);
    return api("/webspace/stack" + (frisch ? "?frisch=1" : "")).then((x) => { setD(x); setFehler(""); })
      .catch((e) => setFehler(e.message)).finally(() => setPrueft(false));
  };
  useEffect(() => { holen(false); }, []);
  if (fehler && !d) return html`<div class="fehlerbox">Der Stand der Website ist gerade nicht abrufbar: ${fehler}</div>`;
  if (!d) return html`<div class="lade">Prüfe die Website …</div>`;
  const live = d.erreichbar || {};
  const v = d.veroeffentlichung || {};
  const seitenNach = new Map(d.seiten.concat(d.blog).map((s) => [ohneSchraeg(s.adresse), s]));
  const imMenue = new Set();
  d.menue.forEach((m) => { imMenue.add(ohneSchraeg(m.href)); (m.unter || []).forEach((u) => imMenue.add(ohneSchraeg(u.href))); });
  const ausserhalb = d.seiten.filter((s) => !imMenue.has(ohneSchraeg(s.adresse)));
  const bearbeiten = (href) => { const s = seitenNach.get(ohneSchraeg(href)); return s ? "#/webspace/" + encodeURIComponent(s.pfad) : null; };
  const vOk = v.ergebnis === "success";
  const aend = d.unveroeffentlicht;
  // Der Weg einer Aenderung, von links nach rechts -- je Glied, was gerade gilt.
  const KETTE = [
    ["Cockpit · WebSpace", "hier bearbeitest du die Seiten", aend ? `${aend} Änderung${aend === 1 ? "" : "en"} noch nicht veröffentlicht` : "alles veröffentlicht", aend ? "gelb" : "gruen"],
    ["GitHub · Repo", "veikovoneckern-org, öffentlich", d.letzter ? `zuletzt: ${d.letzter.text}` : "Stand unbekannt", ""],
    ["GitHub · Bauen", (d.workflows || []).join(", ") || "Workflow", v.zeit ? `${vOk ? "gelungen" : v.ergebnis || v.stand} · ${zeitText(Date.parse(v.zeit) / 1000)}` : "nicht abrufbar", v.zeit ? (vOk ? "gruen" : "rot") : ""],
    ["GitHub Pages", "liefert die fertigen Seiten aus", live.server ? `Server: ${live.server}` : "", ""],
    ["Domain", (d.domain || "veikovoneckern.org") + " · DNS bei one.com", live.erreichbar ? `erreichbar · ${live.ms} ms` : `nicht erreichbar${live.fehler ? ": " + live.fehler : live.status ? " (" + live.status + ")" : ""}`, live.erreichbar ? "gruen" : "rot"],
  ];
  return html`<div class="ws-stack">
    <div class="knopfreihe" style="margin-bottom:12px">
      <span class=${"pill " + (live.erreichbar ? "gruen" : "rot")}>${live.erreichbar ? "online" : "nicht erreichbar"}</span>
      <a href=${d.live} target="_blank" rel="noopener"><b>${d.live.replace("https://", "")}</b></a>
      <span class="leise klein">geprüft ${zeitText(d.geprueft)}</span>
      <span style="flex:1"></span>
      <a class="btn klein" href="#/webspace"><${Icon} n="stift" g=${13} />Im WebSpace bearbeiten</a>
      <button class="btn klein geist" disabled=${prueft} onClick=${() => holen(true).catch(fehlerMelden)}><${Icon} n="neu_laden" g=${13} />${prueft ? "Prüft …" : "Neu prüfen"}</button>
    </div>
    <h4 class="ws-h">So ist die Website angebunden</h4>
    <ol class="ws-kette">${KETTE.map(([name, was, stand, farbe]) => html`<li>
      <b>${name}</b><span class="leise klein">${was}</span>${stand && html`<span class=${"klein ws-stand " + farbe}>${stand}</span>`}</li>`)}</ol>
    <p class="leise klein">Veröffentlichen ist immer ein Klick im WebSpace: das Cockpit schickt die Seiten an GitHub, GitHub baut sie und stellt sie über GitHub Pages unter deiner Domain online. E-Mail (${d.mail || "info@veikovoneckern.org"}) läuft weiter über one.com.${d.nur_hier ? ` Achtung: ${d.nur_hier} Stand${d.nur_hier === 1 ? "" : "e"} liegen nur auf dem Server und noch nicht auf GitHub.` : ""}</p>
    <div class="raster-gleich zwei ws-raster">
      <section class="karte"><div class="karte-kopf"><h3>Hauptseiten</h3><span class="pill">${d.menue.length}</span></div>
        <ul class="ws-menue">${d.menue.map((m) => html`<li>
          <a href=${d.live + m.href} target="_blank" rel="noopener">${m.text}</a>
          ${bearbeiten(m.href) && html` <a class="leise" href=${bearbeiten(m.href)} title="Im WebSpace bearbeiten" aria-label=${m.text + " bearbeiten"}><${Icon} n="stift" g=${12} /></a>`}
          ${(m.unter || []).length ? html`<ul>${m.unter.map((u) => html`<li><a href=${d.live + u.href} target="_blank" rel="noopener">${u.text}</a>
            ${bearbeiten(u.href) && html` <a class="leise" href=${bearbeiten(u.href)} title="Im WebSpace bearbeiten" aria-label=${u.text + " bearbeiten"}><${Icon} n="stift" g=${12} /></a>`}</li>`)}</ul>` : ""}
        </li>`)}</ul>
        ${ausserhalb.length ? html`<details class="klein" style="margin-top:8px"><summary>${ausserhalb.length} weitere Seite${ausserhalb.length === 1 ? "" : "n"} ohne Menüpunkt</summary>
          <ul class="ws-menue">${ausserhalb.map((s) => html`<li><a href=${d.live + s.adresse} target="_blank" rel="noopener">${s.titel}</a></li>`)}</ul></details>` : ""}
      </section>
      <section class="karte"><div class="karte-kopf"><h3>Blog</h3><span class="pill">${d.blog.length}</span></div>
        ${d.blog.length ? html`<ul class="ws-menue">${d.blog.slice(0, 8).map((b) => html`<li><a href=${d.live + b.adresse} target="_blank" rel="noopener">${b.titel}</a>
          ${b.datum && html` <span class="leise klein">${b.datum}</span>`}</li>`)}</ul>
          ${d.blog.length > 8 && html`<p class="leise klein">und ${d.blog.length - 8} weitere</p>`}` : html`<p class="leise">Noch kein Beitrag.</p>`}
        <p class="leise klein" style="margin-top:8px">${d.seiten.length} Seiten und ${d.blog.length} Beiträge insgesamt. Neues erscheint hier von selbst, sobald es im WebSpace angelegt ist.</p>
      </section>
    </div>
  </div>`;
}
