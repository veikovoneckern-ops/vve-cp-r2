// ERGEBNISSE ZEIGEN -- was beide Orte brauchen, an denen Ergebnisse erscheinen:
// das Ergebnisfenster (projects.js) und der Case in der Inbox (inbox.js).
// Eigenes Modul, damit es den Video-Teil und die Vorschau nur einmal gibt.
import { html, useState, useEffect, useRef, Icon, Avatar, Md, toast, fehlerMelden, zeitText, bus, kopieren, useEsc } from "./ui.js";
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

// Aussehen einer Praesentation (folien_stil.py, 18.10.2026). Veiko: "ich moechte
// waehlen koennen, ob es in diesem Look and Feel erstellt werden soll oder andere
// Vorgaben gelten." Umschalten rechnet nichts neu -- Ansicht und PowerPoint
// entstehen bei jedem Abruf aus dem Text. Dieselben Wahlen wie im Auftrag (StilFelder).
export const STIL_WAHL = [["vveorg", "VVEORG-Vorlage"], ["cockpit", "Cockpit-Design"], ["eigen", "Eigene Vorgaben"]];
export function StilFelder({ stil, setStil, text, setText, id = "stil" }) {
  return html`<div class="feld"><label for=${id}>Aussehen der Folien</label>
      <select id=${id} class="eingabe" value=${stil} onChange=${(e) => setStil(e.target.value)}>
        ${STIL_WAHL.map(([k, t]) => html`<option value=${k}>${t}</option>`)}</select></div>
    ${stil === "eigen" && html`<div class="feld" style="margin-top:8px"><label for=${id + "-text"}>Deine Vorgaben</label>
      <textarea id=${id + "-text"} class="eingabe" rows="3" value=${text} onInput=${(e) => setText(e.target.value)}
        placeholder="z. B. hell und freundlich, Grün als Akzentfarbe, Schrift Arial, im Footer „Kanzlei Muster · Vertraulich“, ohne Logo"></textarea>
      <p class="leise klein">Das Layout der VVEORG-Vorlage bleibt; Farben, Schriften und Footer richten sich nach deinen Worten.</p></div>`}`;
}
export function StilWahl({ e, geaendert }) {
  const jetzt = (e.stil && e.stil.id) || "vveorg";
  const [auf, setAuf] = useState(false);
  const [stil, setStil] = useState(jetzt);
  const [text, setText] = useState((e.stil && e.stil.text) || "");
  const [laeuft, setLaeuft] = useState(false);
  async function uebernehmen(id, t) {
    setLaeuft(true);
    try {
      await api(`/ergebnisse/${e.id}/stil`, { methode: "POST", daten: { stil: id, stil_text: t } });
      toast(id === "eigen" ? "Deine Vorgaben sind umgesetzt." : "Aussehen umgestellt.");
      setAuf(false); geaendert && geaendert();
    } catch (x) { fehlerMelden(x); } finally { setLaeuft(false); }
  }
  function waehlen(id) {
    setStil(id);
    if (id === "eigen") { setAuf(true); return; }
    if (id !== jetzt) uebernehmen(id, "");
  }
  return html`<div class="erg-stil">
    <div class="knopfreihe klein"><span class="leise">Aussehen</span>
      <div class="segment">${STIL_WAHL.map(([k, t]) => html`<button class=${jetzt === k ? "an" : ""} disabled=${laeuft}
        title=${k === "eigen" ? "Farben, Schriften und Footer nach deinen Worten" : ""} onClick=${() => waehlen(k)}>${t}</button>`)}</div>
      ${laeuft && html`<span class="leise">stellt um …</span>`}</div>
    ${auf && html`<div class="erg-stil-eigen">
      <${StilFelder} stil="eigen" setStil=${() => {}} text=${text} setText=${setText} id=${"stil-" + e.id} />
      <div class="knopfreihe"><button class="btn klein primaer" disabled=${laeuft || !text.trim()} onClick=${() => uebernehmen("eigen", text)}>
        ${laeuft ? "Setzt um … (ein paar Sekunden)" : "Vorgaben übernehmen"}</button>
        <button class="btn klein geist" onClick=${() => { setAuf(false); setStil(jetzt); }}>Abbrechen</button></div></div>`}
  </div>`;
}

// Daniels Urteil als EINE Zeile; Begruendung und Maengel klappen auf.
// Vorher ein grosser Kasten ueber dem Ergebnis, der es aus dem Blick schob
// (Veiko, 16.10.: "das ist alles noch sehr sperrig").
// Was Veiko mit Daniels Urteil anfangen kann -- "trägt" und "mit Mängeln" sagten
// ihm nichts (16.10.). Jetzt: Klartext, und bei Einwaenden ein Knopf, der sie im
// Ergebnisfenster einarbeiten laesst (die Bitte steht vorbereitet im Chat).
export const URTEIL = {
  tragfaehig: { wort: "Geprüft: in Ordnung", farbe: "gruen", tun: "Daniel hat nichts Wesentliches gefunden. Du kannst das Ergebnis so verwenden." },
  nachbessern: { wort: "Daniel hat Einwände", farbe: "gelb", tun: "Brauchbar, aber Daniel sieht Schwächen. Lies seine Punkte und lass sie einarbeiten, wenn du zustimmst." },
  rueckfrage: { wort: "Rückfrage an dich", farbe: "gelb", tun: "Daniel braucht eine Angabe von dir, bevor es weitergeht." },
  // Recherche-Dossier (dossier.py, 19.10.2026): aus Quellen verdichtet, nicht von Daniel geprueft.
  recherche: { wort: "Recherche, ungeprüft", farbe: "blau", tun: "Das Cockpit hat die Quellen zusammengefasst; die Quelle steht über jedem Abschnitt. Daniel hat es nicht geprüft -- wenn du mehr willst, lass im Chat rechts daraus ein Konzept oder einen Vorschlag machen." },
  ungeprueft: { wort: "Noch nicht geprüft", farbe: "", tun: "Die Prüfung ist ausgefallen; das Ergebnis ist ungeprüft." },
};
export function einarbeitenText(p) {
  const m = (p && p.maengel) || [];
  // Ohne "vollständige neue Fassung": bei einem Langläufer-Ergebnis gehen die Einwände
  // Kapitel für Kapitel (teamchat._langlauf_ergebnis_text), sonst schreibt das Mitglied
  // ohnehin die ganze Fassung -- das sagt ihm seine Anweisung.
  return "Bitte arbeite Daniels Einwände ein."
    + (m.length ? "\n" + m.map((x) => "- " + x).join("\n") : "");
}
export function Pruefung({ p, eid, einarbeiten }) {
  const [auf, setAuf] = useState(false);
  const ref = useRef(null);
  // Aufgeklappt liegt der Kasten UEBER der Zeile (CSS .zeile .pruef-text) --
  // innerhalb der Zeile drueckte er den Titel auf einen Buchstaben Breite
  // (Veiko, 17.10.2026). Ein Klick daneben oder Escape klappt ihn wieder zu.
  useEffect(() => {
    if (!auf) return;
    const weg = (x) => { if (ref.current && !ref.current.contains(x.target)) setAuf(false); };
    const esc = (x) => { if (x.key === "Escape") { x.stopPropagation(); setAuf(false); } };
    document.addEventListener("pointerdown", weg);
    document.addEventListener("keydown", esc, true);
    return () => { document.removeEventListener("pointerdown", weg); document.removeEventListener("keydown", esc, true); };
  }, [auf]);
  if (!p || !p.urteil) return "";
  const u = URTEIL[p.urteil] || { wort: p.urteil, farbe: "", tun: "" };
  const los = einarbeiten || (eid ? () => bus.sende("ergebnis-zeigen", { id: eid, vorlage: einarbeitenText(p) }) : null);
  return html`<div class="pruef-zeile" ref=${ref}>
    <button class=${"pill " + u.farbe} onClick=${() => setAuf(!auf)} aria-expanded=${auf}
      title="Daniel (Red Team) prüft jedes Ergebnis. Klicken für seine Begründung und was du tun kannst.">${u.wort}${auf ? " ▴" : " ▾"}</button>
    ${auf && html`<div class="pruef-text klein">
      <div><b>Was das heißt:</b> ${u.tun}</div>
      ${p.begruendung && html`<div style="margin-top:6px"><b>Daniels Begründung:</b> ${p.begruendung}</div>`}
      ${(p.maengel || []).length > 0 && html`<div style="margin-top:6px"><b>Seine Punkte:</b><ul>${p.maengel.map((m) => html`<li>${m}</li>`)}</ul></div>`}
      ${p.urteil === "nachbessern" && los && html`<button class="btn klein primaer" style="margin-top:8px" onClick=${(x) => { x.stopPropagation(); setAuf(false); los(); }}>
        <${Icon} n="chat" g=${13} />Einwände einarbeiten lassen</button>`}</div>`}
  </div>`;
}

// Der eigentliche Inhalt eines Ergebnisses -- Video, Ansicht (Folien, Dokument,
// Webseite) oder Text. hoch: die Vorschau fuellt den verfuegbaren Platz (Gross ansehen).
function Inhalt({ e, laden, hoch }) {
  if (e.form === "video" || e.video) return html`<${VideoBlock} e=${e} neuLaden=${laden} ohneDownload=${true} />`;
  const b = e.folienbilder ? e.folienbilder.vorhanden : 0;
  if (e.ansicht) return html`${!hoch && html`<${FolienbilderBlock} e=${e} neuLaden=${laden} />`}
    <div class=${"erg-vorschau-rahmen form-" + e.form + (hoch ? " hoch" : "")}>
    <iframe src=${"/api/ergebnisse/" + e.id + "/ansicht?b=" + b} sandbox="allow-scripts allow-forms allow-popups" title=${e.kurztitel || e.titel}></iframe></div>`;
  return html`<div class=${"erg-vorschau-text" + (hoch ? " hoch" : "")}><${Md} text=${e.inhalt || ""} /></div>`;
}

// Gross ansehen: das Ergebnis ueber das ganze Fenster, EINE Scrollflaeche,
// Downloads oben, Escape schliesst. Ersetzt das Scrollen in einer Vorschau,
// die selbst in einer scrollenden Spalte steckt.
export function GrossAnsicht({ e, laden, zu }) {
  useEsc(zu);
  return html`<div class="gross-ansicht" role="dialog" aria-label=${e.kurztitel || e.titel}>
    <div class="gross-kopf">
      <b>${e.kurztitel || e.titel}</b>
      <span class="luecke"></span>
      <${Downloads} e=${e} />
      <button class="btn geist icon" onClick=${zu} title="Schließen (Esc)"><${Icon} n="x" /></button>
    </div>
    <div class="gross-inhalt"><${Inhalt} e=${e} laden=${laden} hoch=${true} /></div>
  </div>`;
}

// Die Vorschau eines Ergebnisses -- im Case, im Briefing (aufgeklappt) und als
// Kopf des Ergebnisfensters dieselbe Darstellung (Veiko, 16.10.: Briefing,
// Chats und Ergebnisse sollen sich gleich anfuehlen).
export function ErgebnisVorschau({ id, ohneOeffnen = false, ohneKopf = false }) {
  const [e, setE] = useState(null);
  const [fehler, setFehler] = useState("");
  const [gross, setGross] = useState(false);
  const laden = () => api("/ergebnisse/" + id).then(setE).catch((x) => setFehler(x.message));
  useEffect(() => { laden(); }, [id]);
  if (fehler) return html`<div class="fehlerbox">${fehler}</div>`;
  if (!e) return html`<div class="lade">Lade Ergebnis …</div>`;
  return html`<div class="erg-vorschau">
    ${!ohneKopf && html`<div class="erg-vorschau-kopf">
      <${Avatar} wer=${e.rolle} name=${e.wer_name} g=${26} />
      <div class="haupt-text"><b>${e.kurztitel || e.titel}</b>
        <div class="leise klein">${e.wer_name} · ${zeitText(e.erstellt)}${e.projekt_name ? " · " + e.projekt_name : ""}</div></div>
      <${Pruefung} p=${e.pruefung} eid=${e.id} />
    </div>`}
    <div class="erg-vorschau-feld">
      <${Inhalt} e=${e} laden=${laden} />
      ${!(e.form === "video" || e.video) && html`<button class="btn klein gross-knopf" onClick=${() => setGross(true)} title="Über das ganze Fenster ansehen">
        <${Icon} n="voll" g=${13} />Groß ansehen</button>`}
    </div>
    <div class="erg-vorschau-fuss">
      <${Downloads} e=${e} />
      ${!ohneOeffnen && html`<button class="btn klein primaer" onClick=${() => bus.sende("ergebnis-zeigen", e.id)} title="Mit dem Team am Ergebnis weiterarbeiten">
        <${Icon} n="chat" g=${13} />Weiterarbeiten</button>`}
    </div>
    ${gross && html`<${GrossAnsicht} e=${e} laden=${laden} zu=${() => setGross(false)} />`}
  </div>`;
}

// Bilder einer Praesentation (folienbilder.py): Stand, Fortschritt und die
// Knoepfe dazu. Waehrend gerechnet wird, fragt der Block alle 8 s nach;
// jedes fertige Bild laedt die Vorschau neu (die Zahl steht in ihrer Adresse).
export function FolienbilderBlock({ e, neuLaden }) {
  const s = e.folienbilder;
  const rechnet = s && s.stand === "rechnet";
  useEffect(() => {
    if (!rechnet) return;
    const t = setInterval(neuLaden, 8000);
    return () => clearInterval(t);
  }, [rechnet]);
  if (!s) return "";
  const folien = e.form === "praesentation";
  const wort = folien ? "Folienbildern" : "Bildern";
  async function starten(neu) {
    try {
      const r = await api(`/ergebnisse/${e.id}/folienbilder${neu ? "?neu=1" : ""}`, { methode: "POST" });
      toast(r.bilder ? `${r.bilder} Bilder werden gerechnet, je etwa 15 Sekunden.` : "Alle Bilder sind schon da.");
      neuLaden();
    } catch (x) { fehlerMelden(x); }
  }
  if (!s.gewuenscht && !folien) return "";
  if (!s.gewuenscht) return html`<div class="hinweisbox folienbilder klein">Diese Präsentation hat keine Bilder.
    Im Chat rechts genügt „Bitte setze Bilder auf die Folien“ – Annie schreibt dann je Folie eine Bildbeschreibung, und die Bilder werden gerechnet.</div>`;
  if (rechnet) {
    const anteil = s.anzahl ? Math.round(((s.fertig || 0) / s.anzahl) * 100) : 0;
    return html`<div class="hinweisbox folienbilder"><b>${folien ? "Folienbilder" : "Bilder"} werden gerechnet</b> · ${s.schritt || ""}
      <div class="video-balken"><i style=${`width:${anteil}%`}></i></div>
      <div class="leise klein">Auf der zweiten Grafikkarte, je Bild etwa 15 Sekunden. Du kannst das Fenster schließen, es rechnet weiter.</div></div>`;
  }
  const fehlen = s.gewuenscht - s.vorhanden;
  return html`<div class=${"knopfreihe klein leise folienbilder" + (s.stand === "fehler" ? " fehler" : "")}>
    <span>${s.vorhanden} von ${s.gewuenscht} ${wort}${s.stand === "fehler" && s.fehler ? ` · ${s.fehler}` : ""}${s.stand === "abgebrochen" ? " · Rechnen wurde unterbrochen" : ""}</span>
    ${fehlen > 0 && html`<button class="btn klein primaer" onClick=${() => starten(false)}><${Icon} n="play" g=${13} />${s.vorhanden ? "Fehlende rechnen" : "Bilder rechnen"}</button>`}
    ${s.vorhanden > 0 && html`<button class="btn klein geist" onClick=${() => starten(true)} title="Alle Bilder neu rechnen -- jedes fällt anders aus">Neu rechnen</button>`}
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

// Ein neu entstandenes Ergebnis als Zeile; "Vorschau" klappt es AN DER STELLE
// auf (dieselbe Darstellung wie im Case), statt in ein Fenster zu springen.
export function ErgebnisZeile({ e, neu, auf, umschalten }) {
  // Ein Klick irgendwo auf die Zeile (ausser auf die Knoepfe) oeffnet das
  // Ergebnis mit seinem Chat (Veiko, 16.10.: "wenn ich in diesem Bereich
  // klicke, soll sich immer der zugehoerige Chat oeffnen").
  const oeffnen = (x) => { if (!x.target.closest("button, a, .pruef-zeile")) bus.sende("ergebnis-zeigen", e.id); };
  return html`<div class=${"erg-zeile" + (auf ? " auf" : "")}>
    <div class="zeile klickbar" onClick=${oeffnen} title="Öffnen und mit dem Team daran weiterarbeiten">
      <${Avatar} wer=${e.rolle} name=${e.wer_name} g=${26} />
      <div class="haupt-text">
        <b>${neu && html`<span class="pill lila neu-marke">neu</span>`}${e.kurztitel || e.titel}</b>
        <div class="leise klein">${e.wer_name} · ${e.bearbeitet && e.bearbeitet - e.erstellt > 120 ? "bearbeitet " + zeitText(e.bearbeitet) : zeitText(e.erstellt)}${e.projekt_name ? " · " + e.projekt_name : ""}</div>
      </div>
      <${Pruefung} p=${e.pruefung} eid=${e.id} />
      <button class=${"btn klein" + (auf ? " an" : "")} onClick=${umschalten} aria-expanded=${auf}>
        <${Icon} n=${auf ? "klein" : "auge"} g=${14} />${auf ? "Zuklappen" : "Vorschau"}</button>
      ${e.vorgang_id && html`<a class="btn klein geist" href=${"#/inbox/" + e.vorgang_id}
        title="Woher das kommt: die ursprüngliche Notiz, was Jason daraus gemacht hat, alle Ergebnisse dazu">Herkunft</a>`}
    </div>
    ${auf && html`<div class="erg-zeile-vorschau"><${ErgebnisVorschau} id=${e.id} ohneKopf=${true} /></div>`}
  </div>`;
}
