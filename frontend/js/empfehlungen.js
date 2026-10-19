// RECOMMENDATIONS (19.10.2026) -- Veiko: "bau eine eigene Seite fuer Recommendations
// und dort bring alles unter, was in Summe zu Empfehlungen passt." Vorher lagen sie an
// vier Stellen: in der Server-Kachel (Updates, Dienste, Sicherungen, Modellkatalog), in
// der Team-Besetzung (je Rolle der faellige Schritt, Gesamtplan, neue Rollen, Modelle,
// die niemand braucht), unter Optimierung (Modellkatalog, ein zweites Mal) und gar
// nicht (Hinweise zur Website kamen nur im Veroeffentlichen-Dialog).
//
// Jetzt hier und NUR hier (Ein Ort je Sache): die Server-Kachel und die Team-Karten
// zeigen nur noch, dass es etwas gibt, und fuehren hierher. Oben die Zahlen je Bereich,
// darunter je Bereich ein aufklappbarer Abschnitt mit den Knoepfen. Nichts davon wird
// hier gerechnet -- dieselben Quellen wie vorher (systeminfo, revision, webspace).
import { html, useState, useEffect, Icon, bus, Klappe, useAbschnitt, navigiere } from "./ui.js";
import { api } from "./api.js";
import { useDetails, Empfehlung, ModellEmpfehlung } from "./server.js";
import { useModellDaten, ModellEmpfehlungen, modellPunkte } from "./modelle.js";

export function Empfehlungen({ abschnitt }) {
  useEffect(() => { bus.sende("talk-kontext", { art: "empfehlungen", id: "empfehlungen", titel: "Recommendations" }); return () => bus.sende("talk-kontext", null); }, []);
  useAbschnitt(abschnitt);
  const d = useDetails({ mitSystem: false });
  const { det, starten, modellLaden } = d;
  const m = useModellDaten();
  const [web, setWeb] = useState(null);
  useEffect(() => { api("/webspace/pruefen?alle=true").then((x) => setWeb(x.warnungen || [])).catch((e) => setWeb({ fehler: e.message })); }, []);

  const alle = det ? det.empfehlungen || [] : null;
  const server = alle && alle.filter((e) => !(e.aktion && e.aktion.art === "modell"));
  const neue = alle && alle.filter((e) => e.aktion && e.aktion.art === "modell");
  const mp = m.rev ? modellPunkte(m.rev, m.laden) : null;
  const webListe = Array.isArray(web) ? web : null;
  const webFehler = webListe ? webListe.filter((w) => w.stufe === "fehler").length : 0;
  const jetzt = server ? server.filter((e) => e.stufe === "achtung").length : 0;
  // "offen" ist nur, was zu tun ist; ein Hinweis ("nicht einspielen") zaehlt nicht als offen.
  const offen = server ? server.filter((e) => e.stufe === "achtung" || e.stufe === "einspielen").length : 0;

  const KACHELN = [
    ["server", "Server & Software", !server ? "…" : offen ? `${offen} offen` : server.length ? `${server.length} Hinweis${server.length === 1 ? "" : "e"}` : "nichts offen", !server ? "Prüfe …" : jetzt ? `${jetzt} davon jetzt` : "Updates, Dienste, Sicherungen", jetzt ? "rot" : offen ? "gelb" : server ? "gruen" : ""],
    ["modelle", "Modelle im Team", mp ? (mp.faellig ? `${mp.faellig} fällig` : "nichts fällig") : "…", !mp ? "Prüfe …" : mp.frei.length ? `${mp.frei.length} Modelle frei` : "Besetzung, Gesamtplan", !mp ? "" : mp.faellig ? "gelb" : "gruen"],
    ["neue-modelle", "Neue Modelle", neue ? (neue.length ? `${neue.length} zum Laden` : "keine") : "…", neue ? "aus dem Modellkatalog, ungetestet" : "Prüfe …", neue && neue.length ? "blau" : ""],
    ["website", "Website", webListe ? (webListe.length ? `${webListe.length} Hinweise` : "alles in Ordnung") : web && web.fehler ? "nicht abrufbar" : "…", !webListe && !(web && web.fehler) ? "Prüfe …" : webFehler ? `${webFehler} Fehler` : "Links, Bilder, Beschreibungen", webFehler ? "rot" : webListe && webListe.length ? "gelb" : webListe ? "gruen" : ""],
  ];

  return html`<div class="seite emp">
    <div class="emp-kacheln">${KACHELN.map(([id, titel, wert, unter, farbe]) => html`<button class=${"karte emp-kachel " + farbe} onClick=${() => navigiere("/empfehlungen/" + id)}>
      <span class="leise klein">${titel}</span><b>${wert}</b><span class="klein leise">${unter}</span></button>`)}</div>

    <${Klappe} id="server" titel="Server & Software" unter="Updates, Dienste, Sicherungen, Ollama -- was der Server meldet" zahl=${server && server.length ? (offen ? offen + " offen" : server.length + " Hinweis" + (server.length === 1 ? "" : "e")) : null} vorgabe=${true}>
      ${!det ? html`<div class="lade">Prüfe …</div>` : server.length
        ? html`<div class="empf-raster">${server.map((x, i) => html`<${Empfehlung} key=${i} e=${x} auftrag=${det.auftrag} starten=${starten} laden=${det.laden} modellLaden=${modellLaden} />`)}</div>`
        : html`<p class="leise">Nichts zu tun: keine Updates offen, alle Dienste laufen, Sicherungen frisch.</p>`}
      ${det && det.auftrag && det.auftrag.laeuft && html`<p class="klein" style="margin-top:8px"><a href="#/system">Ein Auftrag läuft -- den Fortschritt siehst du im Stack.</a></p>`}
    </${Klappe}>

    <${Klappe} id="modelle" titel="Modelle im Team" unter="Je Rolle der fällige Schritt, der Gesamtplan für beide Karten, neue Rollen, Aufräumen"
      zahl=${mp && mp.faellig ? mp.faellig : null} vorgabe=${true}>
      <div class="mo"><${ModellEmpfehlungen} rev=${m.rev} laden=${m.laden} neuLaden=${m.alles} /></div>
    </${Klappe}>

    <${Klappe} id="neue-modelle" titel="Neue Modelle zum Laden" unter="Aus dem Modellkatalog -- ungetestet: erst laden, dann misst die Revision nachts" zahl=${neue && neue.length ? neue.length : null} vorgabe=${true}>
      ${!det ? html`<div class="lade">Prüfe …</div>` : neue.length
        ? html`<div class="empf-raster">${neue.map((x, i) => html`<${ModellEmpfehlung} key=${i} e=${x} l=${(det.laden || {})[x.aktion.name]} modellLaden=${modellLaden} />`)}</div>`
        : html`<p class="leise">Gerade nichts. Was es sonst Neues gibt, steht im Team unter <a href="#/team/neu">Neu bei Ollama</a>.</p>`}
    </${Klappe}>

    <${Klappe} id="website" titel="Website veikovoneckern.org" unter="Was die Prüfung an allen Seiten findet: Links ins Leere, fehlende Bilder, Beschreibungen"
      zahl=${webListe && webListe.length ? webListe.length : null} vorgabe=${true}>
      <${WebHinweise} web=${web} />
    </${Klappe}>
  </div>`;
}

function WebHinweise({ web }) {
  if (!web) return html`<div class="lade">Prüfe die Seiten …</div>`;
  if (web.fehler) return html`<div class="fehlerbox">Die Website-Prüfung ist gerade nicht abrufbar: ${web.fehler}</div>`;
  if (!web.length) return html`<p class="leise">Alle Seiten in Ordnung: keine Links ins Leere, alle Bilder da, Beschreibungen passend.</p>`;
  const jeSeite = new Map();
  web.forEach((w) => { if (!jeSeite.has(w.pfad)) jeSeite.set(w.pfad, []); jeSeite.get(w.pfad).push(w); });
  return html`<div class="emp-web">${[...jeSeite.entries()].map(([pfad, liste]) => html`<div class="karte emp-web-seite">
      <div class="karte-kopf"><b>${pfad === "seiten.json" ? "Menü" : pfad.replace(/\.html$/, "")}</b>
        ${pfad !== "seiten.json" ? html`<a class="btn klein" href=${"#/webspace/" + encodeURIComponent(pfad)}><${Icon} n="stift" g=${12} />Bearbeiten</a>` : html`<a class="btn klein" href="#/webspace">Im WebSpace</a>`}</div>
      ${liste.map((w) => html`<div class="zeile klein"><span class=${"pill " + (w.stufe === "fehler" ? "rot" : "gelb")}>${w.stufe === "fehler" ? "Fehler" : "Hinweis"}</span><span class="haupt-text">${w.text}</span></div>`)}
    </div>`)}
    <p class="leise klein">Dieselbe Prüfung läuft vor jedem Veröffentlichen im WebSpace noch einmal.</p></div>`;
}
