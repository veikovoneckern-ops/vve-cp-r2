// ERGEBNISSE ZEIGEN -- was beide Orte brauchen, an denen Ergebnisse erscheinen:
// das Ergebnisfenster (projects.js) und der Case in der Inbox (inbox.js).
// Eigenes Modul, damit es den Video-Teil und die Vorschau nur einmal gibt.
import { html, useState, useEffect, Icon, Avatar, Md, toast, fehlerMelden, zeitText, bus, kopieren } from "./ui.js";
import { api } from "./api.js";

// Downloads je Form -- dieselben Endpunkte wie im Ergebnisfenster.
export function Downloads({ e }) {
  const basis = "/api/ergebnisse/" + e.id;
  return html`<div class="knopfreihe erg-downloads">
    ${e.video && e.video.stand === "fertig" && html`<a class="btn klein primaer" href=${basis + "/video?download=1"}><${Icon} n="download" g=${13} />Video (MP4)</a>`}
    ${e.form === "praesentation" && html`<a class="btn klein" href=${basis + "/datei?format=pptx"} download><${Icon} n="download" g=${13} />PowerPoint</a>`}
    ${e.form === "webseite" && html`<a class="btn klein" href=${basis + "/datei?format=html"} download><${Icon} n="download" g=${13} />Webseite (HTML)</a>`}
    <a class="btn klein" href=${basis + "/datei?format=docx"} download><${Icon} n="download" g=${13} />Word</a>
    <a class="btn klein geist" href=${basis + "/datei?format=md"} download>Markdown</a>
    <button class="btn klein geist" onClick=${async () => { if (await kopieren(e.inhalt || "")) toast("Kopiert."); }}><${Icon} n="kopie" g=${13} />Kopieren</button>
  </div>`;
}

// Die Vorschau im Case (Veiko, 16.10.: "ich moechte auch dort ein
// Vorschaufenster fuer die Ergebnisse haben und dann die Downloadmoeglichkeit
// dazu"). Vorher stand ein Ergebnis nur als schmale Zeile mit "Ansehen" rechts
// unten -- das OODA-Video war darueber nicht zu finden.
export function ErgebnisVorschau({ id }) {
  const [e, setE] = useState(null);
  const [fehler, setFehler] = useState("");
  const laden = () => api("/ergebnisse/" + id).then(setE).catch((x) => setFehler(x.message));
  useEffect(() => { laden(); }, [id]);
  if (fehler) return html`<div class="fehlerbox">${fehler}</div>`;
  if (!e) return html`<div class="lade">Lade Ergebnis …</div>`;
  const p = e.pruefung || {};
  const hatVideo = e.form === "video" || e.video;
  return html`<div class="erg-vorschau">
    <div class="erg-vorschau-kopf">
      <${Avatar} wer=${e.rolle} name=${e.wer_name} g=${26} />
      <div class="haupt-text"><b>${e.titel}</b>
        <div class="leise klein">${e.wer_name} · ${e.form} · ${zeitText(e.erstellt)}</div></div>
      ${p.urteil && html`<span class=${"pill " + (p.urteil === "tragfaehig" ? "gruen" : "gelb")} title=${p.begruendung || ""}>Daniel: ${p.urteil === "tragfaehig" ? "trägt" : p.urteil}</span>`}
      <button class="btn klein" onClick=${() => bus.sende("ergebnis-zeigen", e.id)} title="Groß öffnen, mit dem Team weiterarbeiten"><${Icon} n="voll" g=${13} />Öffnen und weiterarbeiten</button>
    </div>
    ${hatVideo ? html`<${VideoBlock} e=${e} neuLaden=${laden} ohneDownload=${true} />`
      : e.ansicht ? html`<div class="erg-vorschau-rahmen"><iframe src=${"/api/ergebnisse/" + e.id + "/ansicht"} sandbox="allow-scripts allow-forms allow-popups" title=${e.titel}></iframe></div>`
      : html`<div class="erg-vorschau-text"><${Md} text=${e.inhalt || ""} /></div>`}
    <${Downloads} e=${e} />
  </div>`;
}

// Erklaervideo am Ergebnis (video.py): waehrend des Rechnens der Fortschritt,
// danach der Player. Ein Lauf, den es nach einem Neustart nicht mehr gibt,
// heisst "abgebrochen" und laesst sich neu starten -- ebenso nach einem im
// Weiterarbeiten-Gespraech ueberarbeiteten Drehbuch.
export function VideoBlock({ e, neuLaden, ohneDownload = false }) {
  const v = e.video;
  const rechnet = v && v.stand === "rechnet";
  useEffect(() => {
    if (!rechnet) return;
    const t = setInterval(neuLaden, 10000);
    return () => clearInterval(t);
  }, [rechnet]);
  async function starten() {
    try { await api(`/ergebnisse/${e.id}/video`, { methode: "POST" }); toast("Video wird gerechnet. Das dauert pro Szene einige Minuten."); neuLaden(); }
    catch (x) { fehlerMelden(x); }
  }
  if (!v) return html`<div class="hinweisbox video-block">Zu diesem Drehbuch wurde noch kein Video gerechnet.
    <button class="btn klein primaer" style="margin-left:8px" onClick=${starten}><${Icon} n="play" g=${13} />Video rechnen</button></div>`;
  if (v.stand === "fertig") return html`<div class="video-block">
    <video controls preload="metadata" src=${"/api/ergebnisse/" + e.id + "/video?t=" + Math.round(v.geaendert || 0)}></video>
    <div class="knopfreihe klein leise" style="margin-top:6px">${v.laenge_s ? `${Math.round(v.laenge_s)} s` : ""} · ${v.szenen} Szenen · gerechnet in ${Math.round((v.dauer_s || 0) / 60)} Min.
      ${!ohneDownload && html`<a class="btn klein" href=${"/api/ergebnisse/" + e.id + "/video?download=1"}><${Icon} n="download" g=${13} />Herunterladen</a>`}
      <button class="btn klein geist" onClick=${starten}>Neu rechnen</button></div></div>`;
  const anteil = v.szenen ? Math.round(((v.fertig || 0) / v.szenen) * 100) : 0;
  return html`<div class=${"hinweisbox video-block" + (v.stand === "fehler" ? " fehler" : "")}>
    ${rechnet ? html`<b>Video wird gerechnet</b> · ${v.schritt || ""} · seit ${zeitText(v.start)}
        <div class="video-balken"><i style=${`width:${anteil}%`}></i></div>
        <div class="leise klein">Jede Szene braucht auf der zweiten Grafikkarte einige Minuten. Du kannst das Fenster schließen, es rechnet weiter.</div>`
      : html`<b>${v.stand === "fehler" ? "Video gescheitert" : "Video-Rechnung abgebrochen"}</b>${v.fehler ? `: ${v.fehler}` : " (der Dienst wurde neu gestartet)."}
        <button class="btn klein primaer" style="margin-left:8px" onClick=${starten}>Neu rechnen</button>`}
  </div>`;
}

