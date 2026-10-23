// DAILY TASKS (22.10.2026) -- was das Team jeden Tag untersucht und als Briefing liefert.
// Veiko: "taegliche Aufgaben fuer das Team anlegen, irgendetwas, was sie taeglich untersuchen
// sollen, und dann ein Briefing in Bezug auf den Daily Task -- mit kompletter sprachlicher
// Interaktion: Fragen stellen, tiefer untersuchen, gleich weiter bearbeiten."
// Kein eigener Arbeitsweg: ein Daily Task ist ein Auftrag mit Zeitplan (daily.py), das Briefing
// ist ein Ergebnis -- deshalb dieselbe Vorschau und DERSELBE Team-Chat wie im Ergebnisfenster
// (Weiterarbeiten, neue Fassung, Externe dazu, Praesentation daraus). Talk schaut auf den
// gewaehlten Daily Task und kennt sein neuestes Briefing (gespraech.kontext_text, art "daily").
import { html, useState, useEffect, Icon, Avatar, Leer, bus, toast, fehlerMelden, aktualisieren, zeitText, useAbruf, navigiere } from "./ui.js";
import { api } from "./api.js";
import { ErgebnisVorschau } from "./ergebnis.js";
import { TeamChat, gespraechsPartner } from "./teamchat.js";
import { Textfeld } from "./composer.js";

const TAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const BEWERTUNG = { ruhig: ["", "ruhig"], beachtenswert: ["gelb", "beachtenswert"], wichtig: ["rot", "wichtig"] };

function BewertungPill({ b }) {
  if (!b || !BEWERTUNG[b]) return "";
  return html`<span class=${"pill " + BEWERTUNG[b][0]} title="Wie das Team den Tag einschätzt">${BEWERTUNG[b][1]}</span>`;
}

function Formular({ d, rollen, vorlagen, zu, fertig }) {
  const [f, setF] = useState(() => d ? { titel: d.titel, auftrag: d.auftrag, rolle: d.rolle, uhrzeit: d.uhrzeit, tage: d.tage, netz: !!d.netz, projekt_id: d.projekt_id || "" }
    : { titel: "", auftrag: "", rolle: "stratege", uhrzeit: "04:00", tage: [0, 1, 2, 3, 4], netz: true, projekt_id: "" });
  const [projekte, setProjekte] = useState([]);
  const [sendet, setSendet] = useState(false);
  useEffect(() => { api("/projekte").then((x) => setProjekte(x.projekte)).catch(() => {}); }, []);
  const s = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const tag = (i) => setF((x) => ({ ...x, tage: x.tage.includes(i) ? x.tage.filter((t) => t !== i) : [...x.tage, i].sort() }));
  async function speichern() {
    setSendet(true);
    try {
      const r = await api(d ? "/daily/" + d.id : "/daily", { methode: "POST", daten: f });
      toast(d ? "Gespeichert." : "Daily Task angelegt.");
      fertig(r);
    } catch (e) { fehlerMelden(e); }
    setSendet(false);
  }
  return html`<section class="karte dt-form">
    <div class="karte-kopf"><h3>${d ? "Daily Task bearbeiten" : "Neuer Daily Task"}</h3>
      <button class="btn klein geist rechts" onClick=${zu}>Abbrechen</button></div>
    ${!d && html`<div class="dt-vorlagen"><span class="leise klein">Ideen zum Start:</span>
      ${vorlagen.map((v) => html`<button class="btn klein" onClick=${() => setF((x) => ({ ...x, titel: v.titel, auftrag: v.auftrag, rolle: v.rolle }))}>${v.titel}</button>`)}</div>`}
    <label class="feld"><span>Titel</span><input class="eingabe" value=${f.titel} onInput=${s("titel")} placeholder="z. B. KI im Personalwesen" /></label>
    <label class="feld"><span>Was soll jeden Tag untersucht werden?</span>
      <${Textfeld} rows="4" value=${f.auftrag} onInput=${s("auftrag")} placeholder="Worauf das Team achten soll, welche Quellen, was für dich wichtig ist …" /></label>
    <div class="dt-zeile">
      <label class="feld"><span>Wer arbeitet daran</span>
        <select class="eingabe" value=${f.rolle} onChange=${s("rolle")}>${rollen.map((r) => html`<option value=${r.id}>${r.name}${r.titel ? " · " + r.titel : ""}</option>`)}</select></label>
      <label class="feld"><span>Uhrzeit</span><input class="eingabe" type="time" value=${f.uhrzeit} onInput=${s("uhrzeit")} /></label>
      <label class="feld"><span>Projekt (optional)</span>
        <select class="eingabe" value=${f.projekt_id} onChange=${s("projekt_id")}><option value="">ohne Projekt</option>
          ${projekte.map((p) => html`<option value=${p.id}>${p.name}</option>`)}</select></label>
    </div>
    <div class="feld"><span>An welchen Tagen</span>
      <div class="dt-tage">${TAGE.map((t, i) => html`<button class=${"dt-tag" + (f.tage.includes(i) ? " an" : "")} onClick=${() => tag(i)} aria-pressed=${f.tage.includes(i)}>${t}</button>`)}
        <button class="btn klein geist" onClick=${() => setF((x) => ({ ...x, tage: [0, 1, 2, 3, 4] }))}>werktags</button>
        <button class="btn klein geist" onClick=${() => setF((x) => ({ ...x, tage: [0, 1, 2, 3, 4, 5, 6] }))}>täglich</button></div></div>
    <label class="dt-netz"><input type="checkbox" checked=${f.netz} onChange=${(e) => setF((x) => ({ ...x, netz: e.target.checked }))} />
      Im Internet nach aktuellen Meldungen suchen (letzte sieben Tage)</label>
    <div class="knopfreihe" style="margin-top:12px"><button class="btn primaer" disabled=${sendet || !f.titel.trim() || !f.auftrag.trim()} onClick=${speichern}>
      ${sendet ? "Speichert …" : d ? "Speichern" : "Anlegen"}</button></div>
  </section>`;
}

function Detail({ id, rollen, vorlagen, nachher }) {
  const [d, laden] = useAbruf("/daily/" + id, 15000, [id]);
  const [briefing, setBriefing] = useState(null);       // welches Briefing gezeigt wird; null = das neueste
  const [bearbeiten, setBearbeiten] = useState(false);
  const [team, setTeam] = useState(null);
  const [gid, setGid] = useState(null);
  const [vorlage, setVorlage] = useState(null);
  const [stand, setStand] = useState(0);                 // zaehlt Fassungen hoch: die Vorschau laedt neu
  useEffect(() => { api("/team").then(setTeam).catch(() => {}); }, []);
  useEffect(() => { setBriefing(null); setBearbeiten(false); setGid(null); }, [id]);
  // Talk schaut auf diesen Daily Task und kennt sein neuestes Briefing.
  useEffect(() => { if (d) bus.sende("talk-kontext", { art: "daily", id, titel: d.titel }); }, [d && d.titel, id]);
  if (!d) return html`<div class="lade">Lade …</div>`;
  const zeigen = briefing || (d.verlauf[0] && d.verlauf[0].id);
  async function tun(pfad, methode = "POST", daten) {
    try { const r = await api(pfad, { methode, daten }); laden(); nachher(); aktualisieren(); return r; } catch (e) { fehlerMelden(e); }
  }
  const frage = (text) => setVorlage((v) => ({ text, n: ((v && v.n) || 0) + 1 }));
  return html`<div class="dt-detail">
    ${bearbeiten ? html`<${Formular} d=${d} rollen=${rollen} vorlagen=${vorlagen} zu=${() => setBearbeiten(false)} fertig=${() => { setBearbeiten(false); laden(); nachher(); }} />` : html`
    <section class="karte">
      <div class="dt-kopf">
        <${Avatar} wer=${d.rolle} name=${d.rolle_name} g=${34} />
        <div class="haupt-text"><h2>${d.titel}</h2>
          <div class="leise klein">${d.zeitplan} · ${d.rolle_name}${d.aktiv ? (d.naechster ? " · nächstes Briefing " + new Date(d.naechster * 1000).toLocaleString("de-DE", { weekday: "short", hour: "2-digit", minute: "2-digit" }) : "") : " · pausiert"}</div></div>
        <div class="knopfreihe">
          <button class="btn primaer" disabled=${!!d.laeuft} onClick=${async () => { if (await tun("/daily/" + id + "/ausfuehren")) toast("Läuft. Das Briefing erscheint hier, sobald es fertig ist."); }}>
            <${Icon} n="play" g=${14} />${d.laeuft ? "Läuft …" : "Jetzt ausführen"}</button>
          <button class="btn" onClick=${() => setBearbeiten(true)}><${Icon} n="stift" g=${14} />Bearbeiten</button>
          <button class="btn" onClick=${() => tun("/daily/" + id, "POST", { aktiv: !d.aktiv })}>${d.aktiv ? "Pausieren" : "Fortsetzen"}</button>
          <button class="btn gefahr" onClick=${async () => { if (await tun("/daily/" + id, "DELETE")) { toast("Gelöscht. Die Briefings bleiben unter Ergebnisse."); navigiere("/daily"); } }}>Löschen</button>
        </div>
      </div>
      <p class="dt-auftrag">${d.auftrag}</p>
      ${d.laeuft && html`<div class="hinweisbox" style="margin-top:8px;background:var(--violett-soft);border-color:transparent">
        <b>${d.rolle_name}</b> ${d.laeuft.was || "arbeitet am heutigen Briefing"} …</div>`}
    </section>`}
    <div class="dt-raster">
      <section class="karte dt-briefing">
        <div class="karte-kopf"><h3>Briefing</h3>
          ${d.verlauf.length > 0 && html`<div class="dt-verlauf">${d.verlauf.slice(0, 10).map((b, i) => html`<button key=${b.id}
            class=${"dt-tagknopf" + (b.id === zeigen ? " an" : "")} onClick=${() => setBriefing(b.id)} title=${b.titel}>
            ${i === 0 ? "Neuestes" : new Date(b.erstellt * 1000).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit" })}
            ${b.bewertung && b.bewertung !== "ruhig" && html`<span class=${"dt-punkt " + b.bewertung}></span>`}</button>`)}</div>`}</div>
        ${zeigen ? html`<${ErgebnisVorschau} key=${zeigen + ":" + stand} id=${zeigen} />`
          : html`<${Leer} titel="Noch kein Briefing.">Das erste entsteht ${d.aktiv && d.naechster ? "zur geplanten Zeit" : "auf Knopfdruck"} -- oder jetzt mit „Jetzt ausführen“.</${Leer}>`}
      </section>
      <section class="karte dt-chat">
        <div class="karte-kopf"><h3>Mit ${d.rolle_name} weiterarbeiten</h3>
          ${gid && html`<button class="btn klein geist rechts" onClick=${() => setGid(null)}><${Icon} n="neu" g=${13} />Neu</button>`}</div>
        <div class="dt-fragen">
          ${[["Tiefer untersuchen", "Untersuche den wichtigsten Punkt aus diesem Briefing tiefer: Hintergründe, Zahlen, was das für mich bei Krones heißt."],
             ["Was heißt das für mich?", "Was bedeutet dieses Briefing konkret für meine Arbeit als Head of Corporate HR Transformation? Drei Sätze."],
             ["Aufgabe daraus", "Welche Aufgabe sollte ich mir aus diesem Briefing anlegen? Schlag eine vor."],
             ["Präsentation daraus", "Mach aus diesem Briefing eine kurze Präsentation für mein Team."]].map(([t, x]) =>
            html`<button class="btn klein" disabled=${!zeigen} onClick=${() => frage(x)}>${t}</button>`)}
        </div>
        ${!zeigen ? html`<div class="leise klein" style="padding:8px 0">Sobald es ein Briefing gibt, sprichst du hier mit ${d.rolle_name} darüber.</div>`
          : team ? html`<${TeamChat} key=${d.rolle + ":" + zeigen + ":" + (gid || "neu")} wer=${d.rolle} partnerListe=${gespraechsPartner(team)} gid=${gid}
              ergebnisId=${zeigen} projektId=${d.projekt_id || ""} beiGespraech=${setGid} beiFassung=${() => { setBriefing(zeigen); setStand((n) => n + 1); aktualisieren(); }} vorlage=${vorlage}
              leerText=${"Frag nach, lass etwas tiefer untersuchen oder mach daraus etwas Neues. Talk kennt dieses Briefing auch."} />`
          : html`<div class="lade">Lade …</div>`}
      </section>
    </div>
  </div>`;
}

export function Daily({ id }) {
  const [d, laden] = useAbruf("/daily", 20000, []);
  const [neu, setNeu] = useState(id === "neu");
  useEffect(() => { setNeu(id === "neu"); }, [id]);
  useEffect(() => { if (!id || id === "neu") bus.sende("talk-kontext", { art: "daily", id: "alle", titel: "Daily Tasks" }); }, [id]);
  useEffect(() => () => bus.sende("talk-kontext", null), []);
  // Am Rechner gleich den ersten zeigen -- eine leere rechte Haelfte erklaert nichts.
  useEffect(() => { if (d && !id && d.daily.length && innerWidth > 820) navigiere("/daily/" + d.daily[0].id); }, [id, d && d.daily.length]);
  if (!d) return html`<div class="seite"><div class="lade">Lade Daily Tasks …</div></div>`;
  const aktuell = id && id !== "neu" ? id : null;
  return html`<div class="seite dt">
    <aside class="dt-liste">
      <button class="btn primaer voll" onClick=${() => { setNeu(true); navigiere("/daily/neu"); }}><${Icon} n="plus" g=${15} />Neuer Daily Task</button>
      ${!d.daily.length && !neu && html`<${Leer} titel="Noch keine Daily Tasks.">Lege fest, was das Team jeden Tag für dich untersucht -- jeden Morgen kommt ein Briefing dazu. Oder sag Talk: „Leg einen Daily Task an: …“</${Leer}>`}
      ${d.daily.map((t) => html`<button key=${t.id} class=${"dt-eintrag" + (t.id === aktuell ? " an" : "") + (t.aktiv ? "" : " pausiert")} onClick=${() => navigiere("/daily/" + t.id)}>
        <div class="dt-eintrag-kopf"><b>${t.titel}</b><${BewertungPill} b=${t.letztes && t.letztes.bewertung} /></div>
        <div class="leise klein">${t.zeitplan} · ${t.rolle_name}${t.aktiv ? "" : " · pausiert"}</div>
        <div class="leise klein">${t.laeuft ? "arbeitet gerade …" : t.letztes ? "letztes Briefing " + zeitText(t.letztes.erstellt) : "noch kein Briefing"}</div>
      </button>`)}
    </aside>
    <div class="dt-haupt">
      ${neu ? html`<${Formular} rollen=${d.rollen} vorlagen=${d.vorlagen} zu=${() => { setNeu(false); navigiere("/daily"); }}
          fertig=${(r) => { setNeu(false); laden(); navigiere("/daily/" + r.id); }} />`
        : aktuell ? html`<${Detail} id=${aktuell} rollen=${d.rollen} vorlagen=${d.vorlagen} nachher=${laden} />`
        : d.daily.length ? html`<div class="lade">…</div>` : ""}
    </div>
  </div>`;
}
