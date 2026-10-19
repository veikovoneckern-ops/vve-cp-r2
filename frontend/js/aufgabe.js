// DAS AUFGABENFENSTER (17.10.2026). Veiko: "wenn ich bei Aufgaben Editieren
// anklicke, tut sich nichts. Ich moechte Informationen eingeben, sie zu
// Langlaeufern machen, Anhaenge mitgeben -- und das auch, wenn ich den Titel
// anklicke." Vorher gab es fuer eine Aufgabe nur das Umbenennen direkt in der
// Zeile (Stift bzw. Doppelklick) -- ein Fenster dafuer gab es nicht.
//
// EIN Fenster fuer alle Stellen, an denen Aufgaben stehen (Briefing, Projekt,
// Aufgabenliste, Zeitplan, Struktur): geoeffnet ueber bus "aufgabe-zeigen" mit
// der Kennung, gezeigt von app.js. Was es zeigt, kommt aus /aufgaben/{id};
// geschrieben wird ueber dieselben Wege wie anderswo (PATCH /aufgaben, Upload
// /dateien mit aufgabe_id, langlaufStarten) -- kein zweiter Weg.
import { html, useState, useEffect, useRef, Icon, Modal, toast, fehlerMelden, zeitText, bus, aktualisieren, navigiere, useFensterKontext } from "./ui.js";
import { api, hochladen } from "./api.js";
import { langlaufStarten } from "./langlauf.js";

const PRIO = [[1, "hoch"], [2, "normal"], [3, "niedrig"]];
const groesse = (b) => (b >= 1e6 ? (b / 1e6).toFixed(1).replace(".", ",") + " MB" : Math.max(1, Math.round(b / 1e3)) + " KB");
const LL_STAND = { plant: "plant", laeuft: "läuft", wartet: "wartet auf dich", pausiert: "pausiert", fehler: "hängt", fertig: "fertig", abgebrochen: "abgebrochen" };

export function AufgabeFenster({ id, zu }) {
  const [a, setA] = useState(null);
  const [f, setF] = useState(null);           // Entwurf der Felder
  const [projekte, setProjekte] = useState([]);
  const [laedt, setLaedt] = useState([]);     // Uploads in Arbeit: {name, anteil}
  const [ziehen, setZiehen] = useState(false);
  const [speichert, setSpeichert] = useState(false);
  const wahl = useRef(null);
  useFensterKontext(a && { art: "aufgabe", id: a.id, titel: a.titel });
  const holen = () => api("/aufgaben/" + id).then((x) => {
    setA(x);
    setF((alt) => alt || { titel: x.titel, notiz: x.notiz || "", faellig: x.faellig || "", start: x.start || "", prio: x.prio || 2, projekt_id: x.projekt_id || "" });
  }).catch((e) => { fehlerMelden(e); zu(); });
  useEffect(() => { holen(); api("/projekte").then((d) => setProjekte(d.projekte || [])).catch(() => {}); }, [id]);
  // Laeuft etwas fuer die Aufgabe (Recherche, Gespraech), alle acht Sekunden nachsehen.
  const laeuftWas = a && (a.nebenbei || []).length > 0;
  useEffect(() => { if (!laeuftWas) return undefined; const t = setInterval(holen, 8000); return () => clearInterval(t); }, [laeuftWas]);

  if (!a || !f) return html`<${Modal} titel="Aufgabe" zu=${zu}><div class="lade">Lade …</div><//>`;
  const geaendert = f.titel !== a.titel || f.notiz !== (a.notiz || "") || f.faellig !== (a.faellig || "") || f.start !== (a.start || "")
    || Number(f.prio) !== Number(a.prio || 2) || f.projekt_id !== (a.projekt_id || "");
  const s = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function speichern(danach) {
    if (!f.titel.trim()) { toast("Der Titel fehlt."); return false; }
    setSpeichert(true);
    try {
      await api("/aufgaben/" + id, { methode: "PATCH", daten: { titel: f.titel.trim(), notiz: f.notiz, faellig: f.faellig, start: f.start || null,
        prio: Number(f.prio), projekt_id: f.projekt_id || null } });
      aktualisieren();
      setA({ ...a, ...f, titel: f.titel.trim() });
      if (!danach) toast("Gespeichert.");
      return true;
    } catch (e) { fehlerMelden(e); return false; }
    finally { setSpeichert(false); }
  }
  // Schliessen mit ungespeicherten Eingaben: erst speichern -- Informationen,
  // die man getippt hat, sollen nicht durch Escape verloren gehen.
  async function schliessen() { if (geaendert && !(await speichern(true))) return; zu(); }
  async function status(neu) {
    try { await api("/aufgaben/" + id, { methode: "PATCH", daten: { status: neu } }); setA({ ...a, status: neu }); aktualisieren(); }
    catch (e) { fehlerMelden(e); }
  }
  async function dateienHoch(liste) {
    const dateien = [...liste];          // eigene Kopie: input.files ist eine lebende Liste (FileList-Falle)
    for (const d of dateien) {
      setLaedt((l) => [...l, { name: d.name, anteil: 0 }]);
      try {
        const r = await hochladen(d, { aufgabe_id: id, fortschritt: (x) => setLaedt((l) => l.map((y) => (y.name === d.name ? { ...y, anteil: x } : y))) });
        if (r.hinweis) toast(`${d.name}: ${r.hinweis}`);
      } catch (e) { fehlerMelden(e); }
      setLaedt((l) => l.filter((y) => y.name !== d.name));
    }
    holen(); aktualisieren();
  }
  async function loesen(did, name) {
    try { await api("/dateien/" + did, { methode: "PATCH", daten: { aufgabe_id: null } }); toast(`${name} hängt nicht mehr an der Aufgabe (bleibt in den Unterlagen des Projekts).`); holen(); }
    catch (e) { fehlerMelden(e); }
  }
  async function alsLanglaeufer() {
    if (geaendert && !(await speichern(true))) return;
    const auftrag = [f.titel.trim(), f.notiz.trim()].filter(Boolean).join("\n\n");
    zu();
    langlaufStarten({ projekt_id: f.projekt_id || "", aufgabe_id: id, aufgabe_titel: f.titel.trim(), titel: f.titel.trim(), auftrag });
  }
  async function besprechen() {
    if (geaendert && !(await speichern(true))) return;
    zu();
    // Talk mit der Aufgabe als Bezug (Projekt bzw. Case), wie bisher der Klick im Briefing.
    // Seit 19.10.2026 die Aufgabe selbst (gespraech.kontext_text art aufgabe): Talk kennt
    // dann Informationen und Anhaenge, und alles, was daraus entsteht, haengt an ihr.
    const kontext = { art: "aufgabe", id, titel: f.titel };
    bus.sende("talk-oeffnen", { kontext, vorlage: `Zur Aufgabe „${f.titel.trim()}“: ` });
  }
  async function archivieren() {
    try { await api("/aufgaben/" + id, { methode: "DELETE" }); toast("Archiviert.", { aktion: { text: "Rückgängig", fn: () => api("/aufgaben/" + id, { methode: "PATCH", daten: { archiviert: 0 } }).then(aktualisieren) } }); aktualisieren(); zu(); }
    catch (e) { fehlerMelden(e); }
  }
  const erledigt = a.status === "erledigt";
  const laeufer = (a.langlaeufe || []).filter((l) => l.stand !== "abgebrochen");

  return html`<${Modal} titel="Aufgabe" zu=${schliessen} breit
    kopf=${html`<span class=${"pill " + (erledigt ? "gruen" : "")}>${erledigt ? "erledigt" : "offen"}</span>`}
    fuss=${html`
      <button class="btn geist" onClick=${archivieren} title="Archivieren -- zurückholen geht über Rückgängig"><${Icon} n="archiv" g=${14} />Archivieren</button>
      <span class="luecke"></span>
      <button class="btn" onClick=${() => status(erledigt ? "offen" : "erledigt")}><${Icon} n=${erledigt ? "undo" : "check"} g=${14} />${erledigt ? "Wieder öffnen" : "Erledigt"}</button>
      <button class="btn primaer" disabled=${!geaendert || speichert} onClick=${() => speichern()}>${speichert ? "speichert …" : geaendert ? "Speichern" : "Gespeichert"}</button>`}>
    <div class="af">
      <div class="af-haupt">
        <label class="feld"><span>Titel</span>
          <input class="eingabe af-titel" value=${f.titel} onInput=${s("titel")} onKeyDown=${(e) => { if (e.key === "Enter") speichern(); }} /></label>
        <label class="feld"><span>Informationen <span class="leise klein">-- was gehört dazu, worauf kommt es an, was ist schon geklärt? Das Team liest das mit, wenn es an der Aufgabe arbeitet.</span></span>
          <textarea class="eingabe af-notiz" rows="9" value=${f.notiz} onInput=${s("notiz")}
            onKeyDown=${(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) speichern(); }}
            placeholder="z. B. Hintergrund, Ansprechpartner, Zahlen, Entscheidungen, was am Ende vorliegen soll …"></textarea></label>

        <div class=${"af-anhaenge" + (ziehen ? " zieht" : "")}
          onDragOver=${(e) => { e.preventDefault(); setZiehen(true); }} onDragLeave=${() => setZiehen(false)}
          onDrop=${(e) => { e.preventDefault(); setZiehen(false); if (e.dataTransfer.files.length) dateienHoch(e.dataTransfer.files); }}>
          <div class="af-anh-kopf"><b>Anhänge</b><span class="leise klein">PDF, Word, Excel, PowerPoint, Bilder, Text -- hierher ziehen oder</span>
            <button class="btn klein" onClick=${() => wahl.current && wahl.current.click()}><${Icon} n="clip" g=${13} />Datei wählen</button>
            <input type="file" multiple hidden ref=${wahl} onChange=${(e) => { const l = [...e.target.files]; e.target.value = ""; if (l.length) dateienHoch(l); }} /></div>
          ${(a.dateien || []).map((d) => html`<div class="af-datei" key=${d.id}>
            <a href=${"/api/dateien/" + d.id} onClick=${(e) => { e.preventDefault(); bus.sende("datei-zeigen", d.id); }}><${Icon} n="clip" g=${13} />${d.name}</a>
            <span class="leise klein">${groesse(d.groesse || 0)}${d.zeichen ? "" : " · Inhalt nicht lesbar"} · ${zeitText(d.erstellt)}</span>
            <button class="btn klein geist" onClick=${() => loesen(d.id, d.name)} title="Von der Aufgabe lösen (die Datei bleibt erhalten)"><${Icon} n="x" g=${12} /></button></div>`)}
          ${laedt.map((d) => html`<div class="af-datei" key=${"l" + d.name}><span>${d.name}</span><span class="leise klein">lädt … ${Math.round(d.anteil * 100)} %</span></div>`)}
          ${!(a.dateien || []).length && !laedt.length && html`<div class="leise klein">Noch keine. Angehängtes lesen Talk, Team-Chat und ein LongRun zu dieser Aufgabe mit.</div>`}
        </div>
      </div>

      <div class="af-seite">
        <label class="feld"><span>Projekt</span>
          <select class="eingabe" value=${f.projekt_id} onChange=${s("projekt_id")}>
            <option value="">— ohne Projekt —</option>
            ${projekte.filter((p) => p.status !== "archiviert" || p.id === f.projekt_id).map((p) => html`<option value=${p.id}>${p.name}</option>`)}</select></label>
        <div class="af-zwei">
          <label class="feld"><span>Beginn</span><input type="date" class="eingabe" value=${f.start} onInput=${s("start")} /></label>
          <label class="feld"><span>Fällig</span><input type="date" class="eingabe" value=${f.faellig} onInput=${s("faellig")} /></label>
        </div>
        <label class="feld"><span>Priorität</span>
          <select class="eingabe" value=${f.prio} onChange=${s("prio")}>${PRIO.map(([k, t]) => html`<option value=${k}>${t}</option>`)}</select></label>

        <div class="af-block">
          <b>Weiterarbeiten</b>
          ${(a.nebenbei || []).map((x) => html`<div class="af-laeuft"><span class="punkt-laeuft"></span><span><b>${x.art_name}</b> ${x.titel}<span class="leise klein">${x.schritt ? " · " + x.schritt : ""}${x.teile ? " · " + x.teile : ""}</span></span></div>`)}
          <button class="btn" onClick=${besprechen} title="Talk öffnen, mit dieser Aufgabe als Bezug"><${Icon} n="chat" g=${14} />Im Gespräch besprechen</button>
          ${!erledigt && html`<button class="btn" onClick=${alsLanglaeufer} title="Das Team arbeitet die Aufgabe in Etappen ab, mit Zwischenprüfung"><${Icon} n="langlauf" g=${14} />Als LongRun starten</button>`}
          ${laeufer.map((l) => html`<a class="af-link" href=${"#/langlauf/" + l.id} onClick=${zu}><${Icon} n="langlauf" g=${13} />LongRun: ${l.titel}
            <span class="pill">${LL_STAND[l.stand] || l.stand}${l.etappen ? ` · ${l.fertig}/${l.etappen}` : ""}</span></a>`)}
          ${(a.ergebnisse || []).map((e) => html`<button class="af-link" onClick=${() => { zu(); bus.sende("ergebnis-zeigen", e.id); }}><${Icon} n="auge" g=${13} />Ergebnis: ${e.titel}</button>`)}
          ${(a.gespraeche || []).map((g) => html`<button class="af-link" onClick=${() => {
              zu();
              if (g.art === "talk") bus.sende("talk-oeffnen", { gid: g.id });
              else navigiere(g.art === "team" && g.wer ? `/team/chat/${g.wer}/${g.id}` : g.art === "board" ? "/board/" + g.id : "/neo/" + g.id);
            }}><${Icon} n="chat" g=${13} />Gespräch: ${g.titel || "ohne Titel"} <span class="leise klein">${zeitText(g.geaendert)}</span></button>`)}
          ${a.vorgang_id && html`<a class="af-link" href=${"#/inbox/" + a.vorgang_id} onClick=${zu}><${Icon} n="inbox" g=${13} />Herkunft: die Notiz und was das Team daraus gemacht hat</a>`}
        </div>
        <div class="leise klein">${a.quelle === "stab" ? "Vom Team angelegt" : "Von dir angelegt"} ${zeitText(a.erstellt)}${a.geaendert ? ` · geändert ${zeitText(a.geaendert)}` : ""}</div>
      </div>
    </div>
  <//>`;
}
