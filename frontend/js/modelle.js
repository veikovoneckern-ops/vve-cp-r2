// MODELLE IM TEAM (17.10.2026 als Seite "Stab & Modelle"; seit 19.10.2026 Abschnitte der Seite Team).
//
// Vier Abschnitte, in dieser Reihenfolge, weil das die Fragen sind, die man hier hat:
//   Übersicht     Das Team als Schaubild: wer arbeitet mit wem, womit rechnet jede
//                 Rolle, und je Rolle der EINE naechste Schritt (umstellen, laden,
//                 messen) samt dem Weg zurueck. Dazu, was nicht mehr gebraucht wird.
//   Installiert   Was auf der Platte liegt, wer es braucht, und Entfernen.
//   Optimierung   Die Modell-Revision selbst: Laeufe, Messungen, Verlauf.
//   Neu bei Ollama  Neueste Modelle und Nachfolger, je mit Einordnung.
//   (Verbrauch hat seit dem 19.10.2026 eine eigene Seite: Usage.)
//
// Veiko, 17.10.2026 (zweite Runde): "zu aufwendig, mich zurechtzufinden und zu
// entscheiden, was muss ich wo wie machen". Vorher lagen die Vorschlaege zum
// Umstellen, zum Laden und die neuen Rollen auf "Optimierung", die Besetzung auf
// einem anderen Reiter und die Downloads auf einem dritten -- fuer EINE Frage
// ("soll Jason ein anderes Modell bekommen?") musste man drei Stellen
// zusammenlesen. Jetzt steht alles an der Karte der Rolle; jede Sache hat EINEN
// Ort (Bauregel 2): Vorschlaege nur in der Uebersicht, Downloads nur unter
// Current Actions (hier nur der Balken am Knopf), Messungen nur unter Optimierung.
//
// Ersetzen ist ein Weg in drei Schritten, und die Karte zeigt immer nur den
// faelligen: laden -> (messen oder gleich) umstellen -> das alte entfernen, wenn
// es sonst niemand braucht (revision.gebraucht_von; was etwas braucht, sperrt).
import { html, useState, useEffect, Icon, Avatar, toast, fehlerMelden, zeitText, Klappe } from "./ui.js";
import { api } from "./api.js";

const tok = (n) => (n >= 1e6 ? (n / 1e6).toFixed(1).replace(".", ",") + " Mio." : n >= 1e3 ? Math.round(n / 1e3) + " Tsd." : String(n || 0));
const zahl = (x) => (x == null ? "—" : String(Math.round(x * 10) / 10).replace(".", ","));
const gbText = (g) => (g == null ? "?" : String(g).replace(".", ",")) + " GB";
const URTEIL_KURZ = { tragfaehig: "in Ordnung", eingearbeitet: "eingearbeitet", abgeschlossen: "abschließend geprüft", nachbessern: "mit Einwänden", rueckfrage: "mit Rückfrage", ungeprueft: "ungeprüft" };

async function tun(pfad, daten, text, nachher) {
  try { const r = await api(pfad, { methode: "POST", daten: daten || {} }); if (text) toast(text); nachher && nachher(); return r; }
  catch (e) { fehlerMelden(e); return null; }
}

function LadenKnopf({ name, laden, nachher, text = "Laden" }) {
  const j = laden[name];
  if (j && j.stand === "laeuft") return html`<a class="pill lila" href="#/aktionen" title="Läuft -- pausieren oder abbrechen unter Current Actions">lädt · ${j.prozent || 0} %</a>`;
  if (j && j.stand === "pausiert") return html`<a class="pill gelb" href="#/aktionen" title="Fortsetzen unter Current Actions">pausiert · ${j.prozent || 0} %</a>`;
  if (j && j.stand === "fertig") return html`<span class="pill gruen">geladen</span>`;
  return html`<button class="btn klein primaer" onClick=${() => tun("/system/modell-laden", { name }, `${name} wird geladen. Pausieren oder abbrechen: Current Actions.`, nachher)}
    title=${"Bei Ollama laden: " + name}><${Icon} n="download" g=${13} />${text}</button>`;
}

// Inline-Rueckfrage statt Browser-Box, wie FrageKnopf in langlauf.js.
function Rueckfrage({ text, frage, ja, aktion, gefahr }) {
  const [auf, setAuf] = useState(false);
  if (auf) return html`<span class="knopfreihe mo-frage"><span class="klein">${frage}</span>
    <button class=${"btn klein " + (gefahr ? "gefahr voll" : "primaer")} onClick=${() => { setAuf(false); aktion(); }}>${ja}</button>
    <button class="btn klein geist" onClick=${() => setAuf(false)}>Nein</button></span>`;
  return html`<button class=${"btn klein " + (gefahr ? "gefahr" : "")} onClick=${() => setAuf(true)}>${text}</button>`;
}

// Entfernen eines Modells: gesperrt, solange etwas es braucht ("fest"); bei einem
// blossen Hinweis ("zuletzt benutzt") mit Rueckfrage, die den Hinweis nennt.
function EntfernenKnopf({ name, gebraucht, gb, nachher }) {
  const g = gebraucht[name] || [];
  const fest = g.filter((x) => x.art === "fest");
  if (fest.length) return html`<span class="leise klein" title=${fest.map((x) => x.text).join("\n")}>wird gebraucht</span>`;
  const hinweis = g.map((x) => x.text).join("; ");
  return html`<${Rueckfrage} text=${`Entfernen${gb ? " (" + gbText(gb) + ")" : ""}`} gefahr=${true} ja="Entfernen"
    frage=${`${name} löschen?${hinweis ? " Achtung: " + hinweis + "." : ""} Neu laden ginge jederzeit.`}
    aktion=${() => tun("/modelle/entfernen", { name, trotzdem: true }, `${name} entfernt.`, nachher)} />`;
}

// ------------------------------------------------------------ Urteil und Ruf im Netz
// Veiko, 18.10.2026: "nicht nur den technischen Teil, sondern vor allem die
// Qualitaet der Ergebnisse -- und ein klares Statement". Jede Empfehlung traegt
// deshalb oben EIN Wort und EINEN Satz (ruf.statement: eigene Messung vor Ruf im
// Netz vor Technik), darunter aufklappbar, was im Netz steht -- mit Quellen.
const URTEIL_FARBE = { "sehr gut": "gruen", gut: "gruen", durchwachsen: "gelb", schwach: "rot", unklar: "" };
function Urteil({ st }) {
  if (!st) return null;
  return html`<div class=${"mo-urteil " + (st.farbe || "")}><b>${st.wort}</b><span>${st.satz}</span></div>`;
}
function RufPill({ r }) {
  if (!r) return html`<span class="pill" title="Wird nachts im Netz geprüft">Netz: offen</span>`;
  return html`<span class=${"pill " + (URTEIL_FARBE[r.urteil] || "")} title=${r.satz || ""}>Netz: ${r.urteil}</span>`;
}
function RufDetails({ name, r }) {
  if (!r) return html`<div class="leise klein">Was andere mit ${name} erleben, ist noch nicht geprüft -- das passiert heute Nacht oder per „Im Netz prüfen“ oben.</div>`;
  return html`<div class="mo-ruf klein">
    <div><b class="mono">${name}</b> <${RufPill} r=${r} /> <span class="leise">geprüft ${zeitText(r.zeit)}${r.verdichtet_mit ? " · verdichtet mit " + r.verdichtet_mit : ""}</span></div>
    ${r.satz && html`<div>${r.satz}</div>`}
    ${(r.staerken || []).length > 0 && html`<div class="mo-ruf-liste"><span class="leise">Stärken:</span>${r.staerken.map((x) => html`<div>+ ${x}</div>`)}</div>`}
    ${(r.schwaechen || []).length > 0 && html`<div class="mo-ruf-liste"><span class="leise">Schwächen:</span>${r.schwaechen.map((x) => html`<div>− ${x}</div>`)}</div>`}
    ${(r.vergleiche || []).length > 0 && html`<div class="mo-ruf-liste"><span class="leise">Im Vergleich:</span>${r.vergleiche.map((x) => html`<div>${x}</div>`)}</div>`}
    ${r.deutsch && r.deutsch !== "unbekannt" && html`<div><span class="leise">Deutsch:</span> ${r.deutsch}</div>`}
    ${(r.quellen || []).length > 0 && html`<ol class="mo-ruf-quellen">${r.quellen.map((q) => html`<li><a href=${q.url} target="_blank" rel="noopener">${q.titel || q.url}</a></li>`)}</ol>`}
  </div>`;
}

// ------------------------------------------------------------ Übersicht
// Wo jede Rolle im Ablauf sitzt. Unbekannte (selbst angelegte) Rollen arbeiten aus.
const STUFE = { pmo: "planen", kritiker: "pruefen" };
const SPALTEN = [
  ["eingang", "Hereinkommen", "Plaud-Notizen, Mails, Capture"],
  ["planen", "Einordnen und planen", "entscheidet, wer was macht"],
  ["arbeiten", "Ausarbeiten", "auf Auftrag von Jason oder dir"],
  ["pruefen", "Prüfen", "jedes Ergebnis, bevor du es siehst"],
  ["entscheidung", "Du entscheidest", "Briefing, Inbox, Talk"],
];

// Der EINE naechste Schritt je Rolle, in dieser Reihenfolge:
// gemessen besser > geladen, aber ungemessen > lohnt sich zu laden > nichts.
function naechster(p, rev, laden) {
  const gemessen = rev.vorschlaege.filter((v) => v.platz === p.platz);
  if (gemessen.length) return { art: "gemessen", v: gemessen[0], weitere: gemessen.slice(1) };
  const geladen = (rev.geladen_ungemessen[p.platz] || []).filter((n) => n !== p.modell);
  if (geladen.length) return { art: "geladen", name: geladen[0], st: ((rev.urteile || {}).geladen || {})[p.platz + "|" + geladen[0]], weitere: geladen.slice(1) };
  // Nach dem Urteil geordnet. Faellig ist nur, was sich laut Netz lohnt ("... lohnt sich")
  // oder bewusst abzuwaegen ist; "Kein Muss", "Nur zum Testen", "Noch offen" und
  // "Nicht laden" stehen unter "weitere" -- sonst trug jede Rolle einen Schritt, der
  // keiner ist (18.10.2026: "Nur zum Testen: clef-flash" an fuenf Karten).
  const rang = (s) => (!s ? 3 : s.farbe === "gruen" ? 0 : s.wort === "Abwägen" ? 1 : s.farbe === "rot" ? 4 : 2);
  const st = (x) => ((rev.urteile || {}).laden || {})[p.platz + "|" + x.name];
  const lad = rev.laden.filter((x) => (x.plaetze || []).includes(p.platz)).sort((a, b) => rang(st(a)) - rang(st(b)));
  // Ein Download, der fuer diese Rolle laeuft, zaehlt immer -- der Knopf zeigt dann den Balken.
  const laeuft = lad.find((x) => laden[x.name]);
  const erstes = laeuft || lad[0];
  if (erstes && (laeuft || rang(st(erstes)) <= 1)) return { art: "laden", x: erstes, st: st(erstes), weitere: lad.filter((x) => x !== erstes) };
  // Nichts Faelliges, aber weitere Kandidaten: die stehen dann unter Details.
  if (lad.length) return { art: "keins", weitere: lad };
  return null;
}

function Vorschlag({ p, n, rev, laden, neuLaden }) {
  if (!n || n.art === "keins") return html`<div class="mo-vs ruhig klein"><${Urteil} st=${((rev.urteile || {}).behalten || {})[p.platz]} />
    <div class="leise">${n ? "Kein Kandidat, der sich laut Netz klar lohnt -- die übrigen stehen unter Details." : "Kein besserer Kandidat bekannt."} Die Revision sucht jede Nacht weiter.</div></div>`;
  const umstellen = (modell, messung) => tun("/revision/umstellen", { platz: p.platz, modell, messung }, `${p.name} rechnet jetzt mit ${modell}.`, neuLaden);
  if (n.art === "gemessen") {
    const v = n.v;
    return html`<div class="mo-vs gruen">
      <${Urteil} st=${v.statement} />
      <div class="mo-vs-kopf"><span class="pill gruen">gemessen besser</span>${v.art === "abwaegen" ? html`<span class="pill gelb">abwägen</span>` : ""}<${RufPill} r=${(rev.ruf || {})[v.kandidat]} /></div>
      <div><b class="mono">${v.kandidat}</b> statt <span class="mono">${v.bisher}</span></div>
      <div class="leise klein">${v.warum} Gemessen ${zeitText(v.zeit)}.</div>
      <div class="knopfreihe"><button class="btn klein primaer" onClick=${() => umstellen(v.kandidat, v.messung)}>Umstellen</button>
        <button class="btn klein geist" onClick=${() => tun("/revision/verwerfen", { messung: v.messung }, "Verworfen.", neuLaden)}>Verwerfen</button></div></div>`;
  }
  if (n.art === "geladen") {
    const st = rev.stand || {};
    return html`<div class="mo-vs blau">
      <${Urteil} st=${n.st} />
      <div class="mo-vs-kopf"><span class="pill blau">geladen, noch nicht gemessen</span><${RufPill} r=${(rev.ruf || {})[n.name]} /></div>
      <div><b class="mono">${n.name}</b> ${rev.groessen[n.name] ? html`<span class="leise klein">${gbText(rev.groessen[n.name])}</span>` : ""}</div>
      <div class="leise klein">Liegt auf dem Server und passt zu dieser Rolle. Die Revision vergleicht es heute Nacht mit echten Aufgaben von ${p.name} -- oder jetzt.</div>
      <div class="knopfreihe"><button class="btn klein primaer" disabled=${st.laeuft} onClick=${() => tun("/revision/start", null, "Die Revision misst jetzt (einige Minuten je Vergleich).", neuLaden)}>
          ${st.laeuft ? "misst gerade …" : "Jetzt messen"}</button>
        <${Rueckfrage} text="Ungetestet umstellen" ja="Umstellen" frage=${`${p.name} sofort auf ${n.name} umstellen, ohne Messung? Zurück geht jederzeit.`} aktion=${() => umstellen(n.name)} /></div></div>`;
  }
  const x = n.x;
  return html`<div class="mo-vs">
    <${Urteil} st=${n.st} />
    <div class="mo-vs-kopf"><span class="pill lila">${x.neuer ? "Nachfolger bei Ollama" : "neu bei Ollama"}</span><span class="pill">ungetestet</span><${RufPill} r=${(rev.ruf || {})[x.name]} /></div>
    <div><b class="mono">${x.name}</b> <span class="leise klein">${gbText(x.gb)} · ${x.passt}</span></div>
    <div class="leise klein">${x.ersetzt.includes(p.modell) ? `Würde ${p.modell} ersetzen. ` : `Passt zur Arbeit von ${p.name}. `}Nach dem Laden misst die nächste Nacht, ob es für ${p.name} besser ist.</div>
    <div class="knopfreihe"><${LadenKnopf} name=${x.name} laden=${laden} nachher=${neuLaden} /></div></div>`;
}

// Nach einer Umstellung: das vorige Modell -- noch gebraucht, oder kann weg?
function Vorher({ p, rev, neuLaden }) {
  const u = (rev.umgestellt || []).find((x) => x.platz === p.platz);
  if (!u || u.zurueck || !u.vorher || u.vorher === p.modell) return null;
  const istDa = u.vorher in rev.groessen;
  const andere = (rev.gebraucht[u.vorher] || []).filter((g) => g.art === "fest");
  return html`<div class="mo-vorher klein">
    <span>Vorher: <span class="mono">${u.vorher}</span> (umgestellt ${zeitText(u.zeit)})</span>
    <span class="knopfreihe">
      ${!istDa ? html`<span class="leise">schon entfernt</span>`
        : andere.length ? html`<span class="leise" title=${andere.map((g) => g.text).join("\n")}>noch gebraucht: ${andere.map((g) => g.text).join(", ")}</span>`
        : html`<span class="pill gruen">wird nicht mehr gebraucht</span><${EntfernenKnopf} name=${u.vorher} gebraucht=${rev.gebraucht} gb=${rev.groessen[u.vorher]} nachher=${neuLaden} />`}
      <button class="btn klein geist" onClick=${() => tun("/revision/zurueck", { platz: p.platz }, "Zurückgestellt.", neuLaden)}><${Icon} n="undo" g=${13} />Zurück</button>
    </span></div>`;
}

// mitVorschlag: auf der Seite Recommendations steht der faellige Schritt mit seinen
// Knoepfen an der Karte; in der Besetzung (Team) nur ein Hinweis dorthin (Ein Ort je Sache).
function RollenKarte({ p, rev, laden, neuLaden, mitVorschlag = false }) {
  const [auf, setAuf] = useState(false);
  const n = naechster(p, rev, laden);
  const urteile = Object.entries(p.urteile || {});
  const weitere = n && n.weitere && n.weitere.length;
  const vorgeschlagen = n ? (n.v ? n.v.kandidat : n.name || (n.x && n.x.name)) : null;
  const zustand = !n || n.art === "keins" ? "" : n.art === "gemessen" ? " hat-gruen" : n.art === "geladen" ? " hat-blau" : " hat-lila";
  return html`<div class=${"mo-rolle" + zustand}>
    <div class="mo-rolle-kopf">${p.rolle ? html`<${Avatar} wer=${p.rolle} name=${p.name} g=${30} />` : html`<span class="mo-talk-ico"><${Icon} n="talk" g=${16} /></span>`}
      <div class="mo-rolle-name"><b>${p.name}</b><small>${p.titel}</small></div></div>
    <div class="mo-modell"><span class="mono">${p.modell || "— keins —"}</span>${rev.groessen[p.modell] ? html`<span class="leise klein">${gbText(rev.groessen[p.modell])}</span>` : ""}</div>
    ${p.eigen_fehlt && html`<div class="mo-warn klein">Eingetragen ist <b class="mono">${p.eigen}</b> -- nicht installiert, deshalb rechnet still dieses hier.</div>`}
    <div class="leise klein mo-zahlen">${p.aufrufe ? `${p.aufrufe} Aufrufe in 30 T. · Ø ${zahl(p.dauer_mittel)} s` : "in 30 Tagen nicht aufgerufen"}${urteile.length ? " · Daniel: " + urteile.map(([u, k]) => `${k}× ${URTEIL_KURZ[u] || u}`).join(", ") : ""}</div>
    ${mitVorschlag ? html`<${Vorschlag} p=${p} n=${n} rev=${rev} laden=${laden} neuLaden=${neuLaden} />`
      : n && n.art !== "keins" ? html`<a class="mo-empf-hin klein" href="#/empfehlungen/modelle"><${Icon} n="tipp" g=${13} />Empfehlung offen -- unter Recommendations</a>` : ""}
    ${!mitVorschlag && html`<${Vorher} p=${p} rev=${rev} neuLaden=${neuLaden} />`}
    <button class="mo-mehr klein" onClick=${() => setAuf(!auf)} aria-expanded=${auf}><${Icon} n=${auf ? "runter" : "rechts"} g=${12} />Details${weitere ? ` · ${weitere} weitere Vorschläge` : ""}</button>
    ${auf && html`<div class="mo-details klein">
      <label class="leise" for=${"wahl-" + p.platz}>Von Hand umstellen (gilt sofort):</label>
      <select id=${"wahl-" + p.platz} class="eingabe mo-wahl" value=${p.modell || ""}
        onChange=${(e) => tun("/revision/umstellen", { platz: p.platz, modell: e.target.value }, `${p.name} rechnet jetzt mit ${e.target.value}.`, neuLaden)}>
        ${!p.modell && html`<option value="">— keins installiert —</option>`}
        ${rev.installiert.map((m) => html`<option value=${m}>${m}</option>`)}</select>
      ${weitere ? html`<div class="mo-weitere">${n.weitere.map((w) => html`<div>${w.kandidat ? html`<b class="mono">${w.kandidat}</b>: ${w.warum}`
          : w.name ? html`<b class="mono">${w.name}</b> ${w.gb ? `(${gbText(w.gb)}, ${w.passt})` : "(geladen, ungemessen)"}${((rev.urteile || {}).laden || {})[p.platz + "|" + w.name] ? html` -- <b>${rev.urteile.laden[p.platz + "|" + w.name].wort}</b>: ${rev.urteile.laden[p.platz + "|" + w.name].satz}` : ""}` : html`<b class="mono">${w}</b> (geladen, ungemessen)`}</div>`)}</div>` : ""}
      <div class="mo-ruf-kopf leise">Was andere im Netz mit den Modellen erleben</div>
      <${RufDetails} name=${p.modell} r=${(rev.ruf || {})[p.modell]} />
      ${vorgeschlagen && html`<${RufDetails} name=${vorgeschlagen} r=${(rev.ruf || {})[vorgeschlagen]} />`}
      <div class="leise">„Ø“ ist die mittlere Wartezeit je Aufruf, Lesen und Laden eingeschlossen; das reine Schreibtempo misst die Optimierung.</div>
    </div>`}
  </div>`;
}

function NeueRolleKarte({ r, laden, neuLaden }) {
  return html`<div class="mo-rolle mo-neue-rolle">
    <div class="mo-rolle-kopf"><span class="mo-talk-ico"><${Icon} n="plus" g=${15} /></span><div class="mo-rolle-name"><b>${r.name}</b><small>denkbare neue Rolle</small></div></div>
    <div class="leise klein">${r.wofuer}.</div>
    ${r.wie && html`<div class="klein"><span class="leise">Arbeitet mit:</span> ${r.wie}.</div>`}
    <div class="mo-rollen-modelle">${r.modelle.map((m) => html`<span class="mo-rollen-modell"><span class="mono klein">${m.name}</span> <span class="leise klein">${gbText(m.gb)}</span>
      ${m.installiert ? html`<span class="pill gruen">installiert</span>` : html`<${LadenKnopf} name=${m.name} laden=${laden} nachher=${neuLaden} />`}</span>`)}</div>
    <div class="leise klein">Einrichten heißt entscheiden, welche Aufgaben sie übernimmt -- sag es mir oder Neo.</div>
  </div>`;
}

function ExterneReihe({ extern }) {
  if (!extern || !extern.length) return null;
  return html`<div class="mo-extern">
    <div class="mo-extern-kopf"><b>Extern, auf Zuruf</b><span class="leise klein">arbeiten nie von selbst; du holst sie im Gespräch dazu, jedes Gespräch braucht einmal die Kostenfreigabe</span></div>
    <div class="mo-extern-liste">${extern.map((x) => html`<div class="mo-extern-karte">
      <${Avatar} wer=${x.id} name=${x.name} g=${26} /><div style="min-width:0"><b>${x.name}</b> <small class="leise">${x.titel}</small>
        <div class="mono klein">${x.modell || x.vorgabe || "—"}${x.schluessel === false ? html` <span class="pill rot">kein Schlüssel</span>` : ""}</div></div></div>`)}</div>
  </div>`;
}

// Gesamtplan (17.10.2026, revision.gesamtplan): Varianten fuer die GANZE Besetzung
// beider Karten, gegeneinander abgewogen -- Veiko: "ich suche das Gesamtoptimum
// fuer mein Setup". Die Einzelvorschlaege an den Rollenkarten bleiben darunter.
function Gesamtplan({ plan, laden, neuLaden }) {
  if (!plan || !(plan.varianten || []).length) return null;
  return html`<section class="karte mo-plan">
    <div class="karte-kopf"><h3>Gesamtplan für deine zwei Karten</h3>
      <span class="leise klein">je Karte 24 GB · Neo behält sein Code-Modell (${plan.neo || "—"}) und lädt nur, wenn du mit ihm arbeitest</span></div>
    ${plan.fazit && html`<div class="mo-urteil gruen mo-fazit"><b>Empfehlung</b><span>${plan.fazit.replace(/^Klare Empfehlung: /, "")}</span></div>`}
    ${plan.hinweis && html`<p class="hinweisbox klein">${plan.hinweis}</p>`}
    <div class="mo-plan-raster">${plan.varianten.map((v) => {
      const an = v.name === plan.empfohlen;
      return html`<div class=${"mo-variante" + (an ? " empfohlen" : "")} key=${v.name}>
        <div class="mo-var-kopf"><b>${v.name}</b>${an ? html`<span class="pill gruen">Empfehlung</span>` : ""}</div>
        <div class="leise klein">${v.kurz}</div>
        <div class="mo-var-modelle">${v.modelle.map((m) => html`<div class="mo-var-modell">
          <span class="mono">${m.name}</span> <span class=${"pill " + (m.eine_karte ? "" : "gelb")}>${String(m.gb).replace(".", ",")} GB${m.eine_karte ? "" : " · beide Karten"}</span>
          ${m.installiert === false && html`<span class="pill lila">noch nicht geladen</span>`}
          <div class="leise klein">${m.wer.join(", ")}</div>
          <div class="klein mo-var-netz">${m.urteil ? html`<span class=${"pill " + (URTEIL_FARBE[m.urteil] || "")}>Netz: ${m.urteil}</span> ` : ""}${m.netz}</div></div>`)}</div>
        <div class="klein mo-var-pro">${v.vorteile.map((x) => html`<div>+ ${x}</div>`)}</div>
        ${v.nachteile.length ? html`<div class="klein mo-var-contra">${v.nachteile.map((x) => html`<div>− ${x}</div>`)}</div>` : ""}
        ${(v.laden || []).length > 0 && html`<div class="knopfreihe">${v.laden.map((m) => html`<${LadenKnopf} name=${m} laden=${laden} nachher=${neuLaden} text=${"Erst laden: " + m} />`)}
          <span class="leise klein">Danach misst die nächste Nacht; übernehmen geht, sobald es installiert ist.</span></div>`}
        ${v.aktiv && v.name !== "Heutige Besetzung" && html`<span class="pill gruen">so eingestellt</span>`}
        ${v.name !== "Heutige Besetzung" && !v.aktiv && !(v.laden || []).length && html`<button class=${"btn klein " + (an ? "primaer" : "")}
          onClick=${() => tun("/revision/plan", { variante: v.name }, `Umgestellt auf „${v.name}“. Jede Rolle lässt sich einzeln zurückstellen.`, neuLaden)}>
          Diese Besetzung übernehmen</button>`}
      </div>`; })}</div>
    ${(plan.frei || []).length > 0 && html`<p class="leise klein" style="margin-top:8px">Mit der Empfehlung braucht niemand mehr:
      ${plan.frei.map((m) => `${m.name} (${String(m.gb).replace(".", ",")} GB)`).join(", ")} -- entfernen unten unter „Wird von niemandem gebraucht“, sobald es so weit ist.</p>`}
  </section>`;
}

// Stand der Netzpruefung: wie viele Modelle ein Urteil haben, wann zuletzt, und von Hand anstossen.
function RufKopf({ rev, neuLaden }) {
  const st = rev.ruf_stand || {};
  const ruf = rev.ruf || {};
  const namen = rev.installiert || [];
  const mit = namen.filter((n) => ruf[n]).length;
  const juengst = Object.values(ruf).reduce((m, r) => Math.max(m, r.zeit || 0), 0);
  return html`<div class="karte mo-ruf-leiste">
    <div class="haupt-text"><b>Qualität laut Netz</b>
      <div class="leise klein">${st.laeuft ? `Prüft gerade: ${st.schritt || ""} (${st.fertig || 0} von ${st.geplant || "?"})`
        : `${mit} von ${namen.length} installierten Modellen haben ein Urteil${juengst ? ", zuletzt " + zeitText(juengst) : ""}. Jede Nacht werden neue Modelle zuerst geprüft, alle anderen alle zwei Wochen erneut -- aus Testberichten, Reddit und Benchmarks, über deine eigene Suche, verdichtet auf deinem Server.`}
        ${st.fehler && !st.laeuft ? html` <span class="pill gelb" title=${st.fehler}>zuletzt mit Fehler</span>` : ""}</div></div>
    <button class="btn klein" disabled=${st.laeuft} onClick=${() => tun("/revision/ruf", {}, "Die Prüfung im Netz läuft -- je Modell etwa eine Minute. Stand unter Current Actions.", neuLaden)}>
      <${Icon} n="suche" g=${13} />${st.laeuft ? "prüft …" : "Im Netz prüfen"}</button>
  </div>`;
}

// Was es bei den Modellen zu tun gibt, gezaehlt aus denselben Quellen wie die Karten
// (Recommendations, Kachel oben). Gezaehlt nach dem Urteil der Karte: was "Abwägen"
// heisst, ist kein "umstellen" oder "laden" -- sonst sagte die Zahl etwas anderes als die Karte.
export function modellPunkte(rev, laden) {
  const plaetze = rev.bestand.plaetze;
  const nae = plaetze.map((p) => naechster(p, rev, laden || {})).filter(Boolean);
  const urteilVon = (x) => (x.art === "gemessen" ? x.v.statement : x.st) || {};
  const abwaegen = nae.filter((x) => x.art !== "keins" && urteilVon(x).wort === "Abwägen").length;
  const zaehl = (a) => nae.filter((x) => x.art === a && urteilVon(x).wort !== "Abwägen").length;
  const frei = Object.keys(rev.groessen).filter((m) => !(rev.gebraucht[m] || []).some((g) => g.art === "fest"));
  const freiGb = frei.reduce((s, m) => s + (rev.groessen[m] || 0), 0);
  const punkte = [
    zaehl("gemessen") && [`${zaehl("gemessen")}× umstellen`, "gemessen besser", "gruen"],
    zaehl("geladen") && [`${zaehl("geladen")}× messen`, "schon geladen", "blau"],
    zaehl("laden") && [`${zaehl("laden")}× laden`, "lohnt sich laut Netz", "lila"],
    abwaegen && [`${abwaegen}× abwägen`, "besser, weicht aber vom Plan ab", "gelb"],
    frei.length && [`${frei.length} Modelle frei`, `${Math.round(freiGb)} GB, braucht niemand`, ""],
  ].filter(Boolean);
  return { punkte, frei, faellig: nae.filter((x) => x.art !== "keins").length };
}

// Besetzung (Seite Team): wer arbeitet mit wem, womit rechnet jede Rolle. Die Vorschlaege
// dazu stehen seit dem 19.10.2026 auf der Seite Recommendations (ModellEmpfehlungen);
// hier zeigt eine Karte nur, DASS es einen gibt.
function Uebersicht({ rev, laden, neuLaden }) {
  if (!rev) return html`<div class="lade">Lade …</div>`;
  const plaetze = rev.bestand.plaetze;
  const talk = plaetze.find((p) => p.platz === "vorgabe:talk");
  const rollen = plaetze.filter((p) => p.rolle);
  const inSpalte = (s) => rollen.filter((p) => (STUFE[p.rolle] || "arbeiten") === s);
  return html`
    <div class="mo-fluss" role="list" aria-label="Wie das Team zusammenarbeitet">
      ${SPALTEN.map(([id, titel, unter], i) => html`<div class="mo-spalte" role="listitem">
        <div class="mo-spalte-kopf"><span class="mo-schritt">${i + 1}</span><div><b>${titel}</b><small>${unter}</small></div></div>
        <div class="mo-spalte-karten">
        ${id === "eingang" && html`<div class="mo-quelle klein"><${Icon} n="inbox" g=${14} />Plaud, Mail, Capture<span class="leise">gehen an Jason</span></div>`}
        ${id === "entscheidung" && html`<div class="mo-quelle klein"><${Icon} n="briefing" g=${14} />Veiko<span class="leise">sagt Ja, Nein, Weiter</span></div>`}
        ${inSpalte(id).map((p) => html`<${RollenKarte} key=${p.platz} p=${p} rev=${rev} laden=${laden} neuLaden=${neuLaden} />`)}
        ${id === "entscheidung" && talk && html`<${RollenKarte} p=${talk} rev=${rev} laden=${laden} neuLaden=${neuLaden} />`}
      </div></div>`)}
    </div>
    <p class="leise klein mo-fluss-text">So läuft es: Jason ordnet jede neue Notiz ein und vergibt die Arbeit; Clayton, Neal, Annie und Ridley arbeiten aus; Daniel prüft jedes Ergebnis, bevor es bei dir ankommt. Neo arbeitet nur auf deinen Auftrag am Cockpit. Talk ist dein Gespräch mit allen. Was sich an der Besetzung verbessern ließe, steht unter <a href="#/empfehlungen/modelle">Recommendations</a>.</p>
    <${ExterneReihe} extern=${rev.extern} />`;
}

// Alles, was bei den Modellen zu empfehlen ist (Seite Recommendations, 19.10.2026):
// was zu tun ist, der Gesamtplan, je Rolle der faellige Schritt mit seinen Knoepfen,
// denkbare neue Rollen und was niemand mehr braucht.
export function ModellEmpfehlungen({ rev, laden, neuLaden }) {
  if (!rev) return html`<div class="lade">Lade …</div>`;
  const { punkte, frei } = modellPunkte(rev, laden);
  const plaetze = rev.bestand.plaetze.filter((p) => { const n = naechster(p, rev, laden); return n && n.art !== "keins"; });
  const neue = rev.neue_rollen || [];
  const downloads = Object.values(laden).filter((j) => j.stand === "laeuft" || j.stand === "pausiert").length;
  return html`
    <div class="mo-todo karte">
      ${punkte.length ? html`<b>Was du tun kannst</b>
        <div class="mo-todo-liste">${punkte.map(([t, u, f]) => html`<span class=${"mo-todo-punkt " + f}><b>${t}</b><small>${u}</small></span>`)}</div>`
        : html`<b>Nichts zu tun.</b><span class="leise klein">Jede Rolle rechnet mit dem besten bekannten Modell. Die Revision sucht jede Nacht weiter.</span>`}
      ${downloads > 0 && html`<a class="btn klein" href="#/aktionen"><${Icon} n="download" g=${13} />${downloads} Download${downloads > 1 ? "s" : ""} -- Current Actions</a>`}
    </div>
    <${RufKopf} rev=${rev} neuLaden=${neuLaden} />
    <${Gesamtplan} plan=${rev.gesamtplan} laden=${laden} neuLaden=${neuLaden} />
    ${plaetze.length > 0 && html`<h4 class="emp-h">Je Rolle der fällige Schritt</h4>
      <div class="emp-raster">${plaetze.map((p) => html`<${RollenKarte} key=${p.platz} p=${p} rev=${rev} laden=${laden} neuLaden=${neuLaden} mitVorschlag=${true} />`)}</div>`}
    ${neue.length > 0 && html`<h4 class="emp-h">Denkbare neue Rollen</h4>
      <div class="emp-raster">${neue.map((r) => html`<${NeueRolleKarte} key=${r.name} r=${r} laden=${laden} neuLaden=${neuLaden} />`)}</div>`}
    ${frei.length > 0 && html`<section class="karte">
      <div class="karte-kopf"><h3>Wird von niemandem gebraucht</h3><span class="leise klein">keine Rolle, keine Vorgabe rechnet damit -- Entfernen schafft Platz</span></div>
      ${frei.sort((a, b) => rev.groessen[b] - rev.groessen[a]).map((m) => html`<div class="zeile"><div class="haupt-text"><b class="mono">${m}</b>
          <div class="leise klein">${gbText(rev.groessen[m])}${(rev.gebraucht[m] || []).length ? " · " + rev.gebraucht[m].map((g) => g.text).join("; ") : ""}</div></div>
        <${EntfernenKnopf} name=${m} gebraucht=${rev.gebraucht} gb=${rev.groessen[m]} nachher=${neuLaden} /></div>`)}
      <p class="leise klein">Das alte Cockpit (Board-Stand nachts) nimmt sich selbst das erste installierte Modell aus seiner Liste -- es bricht nicht, wenn eines hier fehlt.</p>
    </section>`}`;
}

// Der gemeinsame Stand der Modelle (Liste, Revision, Downloads) -- fuer Team und
// Recommendations derselbe Weg, je Seite ein Abruf.
export function useModellDaten() {
  const [d, setD] = useState(null);
  const [rev, setRev] = useState(null);
  const [laden, setLaden] = useState({});
  const [prueft, setPrueft] = useState(false);
  const holen = (frisch) => {
    setPrueft(!!frisch);
    return api("/modelle" + (frisch ? "?frisch=1" : "")).then((x) => { setD(x); setLaden(x.laden || {}); })
      .catch(fehlerMelden).finally(() => setPrueft(false));
  };
  const revHolen = () => api("/revision").then((x) => { setRev(x); setLaden(x.laeuft_download || {}); }).catch(fehlerMelden);
  const alles = () => { holen(false); revHolen(); };
  useEffect(() => { holen(false); revHolen(); }, []);
  // Laeuft ein Download oder eine Revision, alle paar Sekunden den Stand holen.
  const laedt = Object.values(laden).some((j) => j.stand === "laeuft");
  const prueftRev = !!(rev && ((rev.stand && rev.stand.laeuft) || (rev.ruf_stand && rev.ruf_stand.laeuft)));
  useEffect(() => {
    if (!laedt) return undefined;
    const t = setInterval(() => api("/system/modell-laden").then((x) => {
      setLaden(x.laden || {});
      if (!Object.values(x.laden || {}).some((j) => j.stand === "laeuft")) alles();
    }).catch(() => {}), 5000);
    return () => clearInterval(t);
  }, [laedt]);
  useEffect(() => {
    if (!prueftRev) return undefined;
    const t = setInterval(revHolen, 10000);
    return () => clearInterval(t);
  }, [prueftRev]);
  return { d, rev, laden, prueft, alles, holen };
}

// ------------------------------------------------------------ Installiert
function Installiert({ d, rev, neuLaden }) {
  if (!d || !rev) return html`<div class="lade">Lade …</div>`;
  const gesamt = d.installiert.reduce((s, m) => s + m.gb, 0);
  return html`<section class="karte">
    <div class="karte-kopf"><h3>Installiert</h3><span class="leise klein">${d.installiert.length} Modelle · ${gesamt.toFixed(0)} GB${d.frei_gb ? ` · ${Math.round(d.frei_gb)} GB frei` : ""} · ${d.vram.toFixed(0)} GB auf den Grafikkarten</span></div>
    <div class="tabelle-wrap"><table class="tabelle mo-tabelle"><thead><tr>
      <th>Modell</th><th class="zahl">Größe</th><th>Passt</th><th>Bestes installiertes für</th><th>Gebraucht von</th><th class="zahl">Aufrufe 30 T.</th><th>Zuletzt</th><th></th></tr></thead>
      <tbody>${d.installiert.map((m) => {
        const g = rev.gebraucht[m.name] || [];
        return html`<tr>
        <td class="mono">${m.name}${m.geladen ? html` <span class="pill lila">im Speicher</span>` : ""}</td>
        <td class="zahl">${m.gb.toFixed(1).replace(".", ",")} GB</td>
        <td class="leise">${m.passt.replace("passt auf ", "")}</td>
        <td>${m.aufgaben.join(", ") || html`<span class="leise">—</span>`}</td>
        <td class="klein mo-gebraucht">${g.length ? g.map((x) => html`<div class=${x.art === "fest" ? "" : "leise"}>${x.text}</div>`) : html`<span class="pill gruen">niemand</span>`}</td>
        <td class="zahl">${m.aufrufe ? `${m.aufrufe} · ${tok(m.token)}` : html`<span class="leise">—</span>`}</td>
        <td class="leise klein">${m.zuletzt ? zeitText(m.zuletzt) : "—"}</td>
        <td><${EntfernenKnopf} name=${m.name} gebraucht=${rev.gebraucht} gb=${m.gb} nachher=${neuLaden} /></td></tr>`; })}</tbody></table></div>
    <p class="leise klein" style="margin-top:8px">Entfernen ist gesperrt, solange eine Rolle, eine Vorgabe oder die Suche das Modell braucht -- erst in der Übersicht umstellen. „Zuletzt benutzt“ fragt nur nach. Gezählt wird seit ${d.erfasst_seit ? new Date(d.erfasst_seit * 1000).toLocaleDateString("de-DE") : "heute"}.</p>
  </section>`;
}

// ------------------------------------------------------------ Optimierung
function Messung({ m }) {
  const [auf, setAuf] = useState(false);
  const n = m.aufgaben;
  const ergebnis = m.siege_kandidat > m.siege_bisher ? ["gruen", "neues vorn"] : m.siege_kandidat < m.siege_bisher ? ["", "bisheriges vorn"] : ["", "gleich"];
  return html`<div class="mo-messung">
    <div class="mo-messung-kopf" role="button" onClick=${() => setAuf(!auf)}>
      <span><b>${(m.daten || {}).name || m.platz}</b>: <span class="mono">${m.bisher}</span> gegen <span class="mono">${m.kandidat}</span></span>
      <span class=${"pill " + ergebnis[0]}>${ergebnis[1]} · ${m.siege_kandidat}:${m.siege_bisher}${m.gleich ? ` (${m.gleich}× gleich)` : ""} von ${n}</span>
      <span class="leise klein">${zahl(m.tps_bisher)} → ${zahl(m.tps_kandidat)} Tok/s · ${zeitText(m.zeit)}</span>
      <${Icon} n=${auf ? "runter" : "rechts"} g=${14} /></div>
    ${auf && html`<div class="mo-messung-leib klein">
      <p class="leise">Verdeckter Vergleich: ${m.richter} las beide Antworten als A und B in zufälliger Reihenfolge, ohne zu wissen, welche von welchem Modell kam. Antwortzeit ohne Laden: ${zahl(m.dauer_bisher)} s gegen ${zahl(m.dauer_kandidat)} s.</p>
      ${((m.daten || {}).einzeln || []).map((e, i) => html`<div class="mo-einzeln">
        <div><b>Aufgabe ${i + 1}:</b> ${e.aufgabe}</div>
        <div><span class=${"pill " + (e.sieger === "kandidat" ? "gruen" : "")}>${e.sieger === "kandidat" ? m.kandidat + " besser" : e.sieger === "bisher" ? m.bisher + " besser" : "gleich gut"}</span> ${e.begruendung}</div>
        <details><summary>Beide Antworten (Anfang)</summary><div class="mo-zwei"><div><b class="mono">${m.bisher}</b><p>${e.bisher_text}</p></div><div><b class="mono">${m.kandidat}</b><p>${e.kandidat_text}</p></div></div></details>
      </div>`)}</div>`}
  </div>`;
}

function Optimierung({ rev, d, laden, neuLaden }) {
  if (!rev) return html`<div class="lade">Lade …</div>`;
  const st = rev.stand || {};
  return html`
    <div class="mo-rev-kopf karte">
      <div class="haupt-text">
        ${st.laeuft ? html`<b><span class="vf-spin"></span> Prüft gerade${st.geplant ? ` (${st.fertig || 0} von ${st.geplant} Vergleichen)` : ""}</b>
            <div class="leise klein">${st.schritt || ""} -- das dauert je Vergleich einige Minuten. Abbrechen: Current Actions.</div>`
          : html`<b>Modell-Revision</b>
            <div class="leise klein">Sucht jede Nacht (2--5 Uhr) selbst nach besseren Modellen und misst sie mit echten Aufgaben des Teams. Was dabei herauskommt, steht unter Recommendations.
              ${st.ende ? ` Zuletzt ${zeitText(st.ende)}: ${st.fehler ? "gescheitert -- " + st.fehler : st.ergebnis || ""}` : " Noch kein Lauf."}</div>`}
      </div>
      <button class="btn klein" disabled=${st.laeuft} onClick=${() => tun("/revision/start", null, "Die Revision misst jetzt. Das dauert je Vergleich einige Minuten.", neuLaden)}>
        <${Icon} n="play" g=${13} />Jetzt prüfen</button>
    </div>

    ${(rev.umgestellt || []).length > 0 && html`<section class="karte">
      <div class="karte-kopf"><h3>Verlauf der Umstellungen</h3><span class="leise klein">zurückstellen geht an der Karte der Rolle</span></div>
      ${rev.umgestellt.map((u) => html`<div class="zeile klein"><div class="haupt-text">${zeitText(u.zeit)}: <b>${u.platz.replace("rolle:", "").replace("vorgabe:", "")}</b> von <span class="mono">${u.vorher || "Vorgabe"}</span> auf <span class="mono">${u.nachher}</span>${u.zurueck ? html` <span class="pill">zurückgestellt</span>` : ""}</div></div>`)}
    </section>`}

    <section class="karte">
      <div class="karte-kopf"><h3>Messungen</h3><span class="leise klein">die letzten 20 -- anklicken für Aufgaben und Begründungen</span></div>
      ${rev.messungen.length ? rev.messungen.map((m) => html`<${Messung} key=${m.id} m=${m} />`) : html`<p class="leise">Noch keine.</p>`}
    </section>`;
}

// ------------------------------------------------------------ Neu bei Ollama
function NeuBeiOllama({ d, laden, neuLaden, prueft, frisch }) {
  if (!d) return html`<div class="lade">Lade …</div>`;
  const downloads = Object.values(laden).filter((j) => j.stand === "laeuft" || j.stand === "pausiert" || j.stand === "fehler");
  const familien = (d.neu && d.neu.familien) || [];
  const art = (f) => f.neuer ? ["lila", "Nachfolger"] : f.groesser ? ["gelb", "größere Ausgabe"] : f.verwandt ? ["", "aus deiner Familie"] : ["", "neu, andere Familie"];
  return html`
    ${downloads.length > 0 && html`<div class="karte mo-hinweis"><span>${downloads.length} Download${downloads.length > 1 ? "s" : ""} laufen oder warten.</span>
      <a class="btn klein" href="#/aktionen">Current Actions -- pausieren, fortsetzen, abbrechen</a></div>`}
    <section class="karte">
      <div class="karte-kopf"><h3>Neu bei Ollama</h3><span class="leise klein">${d.neu && d.neu.zeit ? `zuletzt geprüft ${zeitText(d.neu.zeit)}` : ""}</span><span class="luecke"></span>
        <button class="btn klein" onClick=${frisch} disabled=${prueft}><${Icon} n="neu" g=${14} />${prueft ? "prüft …" : "Jetzt neu prüfen"}</button></div>
      ${familien.length ? html`<div class="mo-neu">${familien.map((f) => { const [farbe, label] = art(f); return html`<div class="mo-familie">
          <div class="mo-familie-kopf"><b class="mono">${f.familie}</b> <span class=${"pill " + farbe}>${label}</span>
            ${(f.faehigkeiten || []).map((x) => html` <span class="pill">${{ vision: "Bilder", tools: "Werkzeuge", thinking: "denkt", decision: "Entscheidungen", audio: "Ton" }[x] || x}</span>`)}</div>
          <div class="leise klein">${f.beschreibung}</div>
          ${f.einordnung && html`<div class="mo-einordnung klein">
            ${f.einordnung.aufgaben.length > 0 && html`<div><span class="leise">Taugt für:</span> ${f.einordnung.aufgaben.join(", ")}</div>`}
            <div><span class="leise">Könnte ersetzen:</span> ${f.einordnung.ersetzt.length ? html`<span class="mono">${f.einordnung.ersetzt.join(", ")}</span>` : f.einordnung.aelter ? "nichts -- du hast schon eine neuere Fassung dieser Familie" : "nichts Installiertes -- käme dazu"}</div>
            ${f.einordnung.rollen.length > 0 && html`<div><span class="leise">Im Team geeignet für:</span> ${f.einordnung.rollen.join(", ")}</div>`}
            ${f.einordnung.neue_rolle && html`<div><span class="leise">Neue Rolle denkbar:</span> <b>${f.einordnung.neue_rolle.name}</b> -- ${f.einordnung.neue_rolle.wofuer}</div>`}
          </div>`}
          ${f.ausgaben.map((a) => html`<div class="mo-ausgabe"><span class="mono klein">${a.name}</span><span class="leise klein">${a.gb} GB · ${a.passt}</span>
            ${(d.ruf || {})[a.name] && html`<${RufPill} r=${d.ruf[a.name]} />`}
            ${a.installiert ? html`<span class="pill gruen">installiert</span>` : html`<${LadenKnopf} name=${a.name} laden=${laden} nachher=${neuLaden} />`}</div>`)}
        </div>`; })}</div>`
        : html`<p class="leise">${d.neu && d.neu.fehler ? "ollama.com war nicht erreichbar: " + d.neu.fehler : "Noch nicht geprüft."}</p>`}
    </section>`;
}

// ------------------------------------------------------------ Abschnitte auf der Seite Team
// Seit dem 19.10.2026 keine eigene Seite mehr (Veiko: "Kombiniere Team und Stab & Modelle
// in eine gute Seite mit dem Namen Team ... mit Sektionen, die man auf- und zuklappen
// kann"). Aus den Reitern wurden aufklappbare Abschnitte (ui.Klappe); der Verbrauch hat
// eine eigene Seite (Usage). Der gemeinsame Stand (Modelle, Revision, Downloads) liegt
// hier EINMAL fuer alle vier Abschnitte -- vier eigene Abrufe waeren vier Wahrheiten.
export function ModelleAbschnitte() {
  const { d, rev, laden, prueft, alles, holen } = useModellDaten();
  const offen = rev ? modellPunkte(rev, laden).faellig : 0;
  const inst = d ? (d.installiert || []).length : null;
  const neuZahl = d && d.neu ? (d.neu.familien || []).length : null;
  return html`<div class="mo">
    <${Klappe} id="besetzung" titel="Besetzung" unter="Wer arbeitet mit wem und rechnet womit -- Empfehlungen dazu unter Recommendations"
      zahl=${offen ? offen + " Empfehlungen offen" : null} vorgabe=${true}>
      <${Uebersicht} rev=${rev} laden=${laden} neuLaden=${alles} /></${Klappe}>
    <${Klappe} id="installiert" titel="Installierte Modelle" unter="Was auf der Platte liegt, wer es braucht, Entfernen" zahl=${inst}>
      <${Installiert} d=${d} rev=${rev} neuLaden=${alles} /></${Klappe}>
    <${Klappe} id="optimierung" titel="Optimierung" unter="Die Modell-Revision: Läufe, Messungen, Verlauf">
      <${Optimierung} rev=${rev} d=${d} laden=${laden} neuLaden=${alles} /></${Klappe}>
    <${Klappe} id="neu" titel="Neu bei Ollama" unter="Neueste Modelle und Nachfolger, je mit Einordnung" zahl=${neuZahl}>
      <${NeuBeiOllama} d=${d} laden=${laden} neuLaden=${alles} prueft=${prueft} frisch=${() => holen(true)} /></${Klappe}>
  </div>`;
}
