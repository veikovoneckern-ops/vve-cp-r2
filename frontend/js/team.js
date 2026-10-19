// TEAM -- Veikos KI-Team: wer ist da, womit rechnet er, was hat er zuletzt getan.
// Seit dem 19.10.2026 EINE Seite mit aufklappbaren Abschnitten (Veiko: "Kombiniere
// Team und Stab & Modelle in eine gute Seite mit dem Namen Team ... Sektionen, die
// man auf- und zuklappen kann, die Auf- und Zuklappfunktion aber gut sichtbar"):
// Mitglieder, Extern, dann die Modelle (modelle.js). Memory steht unter
// Einstellungen, Freigaben ebenfalls. Das Advisory Board hat einen eigenen Bereich.
import { escEigen, html, enterBestaetigt, useState, useEffect, useRef, Icon, Avatar, Leer, Modal, toast, fehlerMelden, aktualisieren, zeitText, useAbruf, navigiere, bus, Klappe, useAbschnitt } from "./ui.js";
import { api } from "./api.js";
import { TeamGespraeche } from "./teamchat.js";
import { ModelleAbschnitte } from "./modelle.js";

// #/team/chat/<wer>[/<gespraech>] ist das Gespraech mit einem Mitglied; #/team/<abschnitt>
// oeffnet einen Abschnitt (besetzung, installiert, optimierung, neu, extern).
export function Team({ id, rest = [] }) {
  if (id === "chat") return html`<${TeamGespraeche} wer=${rest[0] || ""} gid=${rest[1] || null} />`;
  return html`<${TeamSeite} abschnitt=${id} />`;
}

function TeamSeite({ abschnitt }) {
  // Alte Adressen: "vertrauen" (Freigaben) und "gedaechtnis" (Memory) stehen unter Einstellungen.
  useEffect(() => { if (abschnitt === "vertrauen") navigiere("/einstellungen"); if (abschnitt === "gedaechtnis") navigiere("/einstellungen/memory"); }, [abschnitt]);
  useEffect(() => { bus.sende("talk-kontext", { art: "team", id: "team", titel: "Team" }); return () => bus.sende("talk-kontext", null); }, []);
  useAbschnitt(abschnitt);
  const [d, laden] = useAbruf("/team", 15000, []);
  const aktiv = d ? d.team.filter((m) => m.aktiv).length : null;
  return html`<div class="seite team-seite">
    <${Klappe} id="mitglieder" titel="Mitglieder" unter="Wer im Team arbeitet, womit, was gerade läuft -- mit jedem direkt chatten"
      zahl=${d ? `${aktiv} von ${d.team.length} aktiv` : null} vorgabe=${true}>
      <${Mitglieder} d=${d} laden=${laden} /></${Klappe}>
    <${Klappe} id="extern" titel="Extern" unter="Dario, Elon und Demmis -- über die Cloud, kosten Geld je Nachricht, arbeiten nie von selbst"
      zahl=${d ? (d.externe || []).length : null}>
      ${d ? html`<div class="team-raster">${(d.externe || []).map((x) => html`<${ExternKarte} key=${x.id} x=${x} nachher=${laden} />`)}</div>` : html`<div class="lade">Lade …</div>`}
    </${Klappe}>
    <${ModelleAbschnitte} />
  </div>`;
}

function Mitglieder({ d, laden }) {
  const [offen, setOffen] = useState(null);
  if (!d) return html`<div class="lade">Lade …</div>`;
  async function setzen(m, daten, meldung) {
    try { await api("/team/" + m.id, { methode: "PATCH", daten }); toast(meldung); laden(); } catch (e) { fehlerMelden(e); }
  }
  return html`
    <p class="leise" style="margin-bottom:12px">Jason ordnet jede neue Notiz ein und plant. Die anderen arbeiten, wenn eine Notiz oder du es ausdrücklich verlangst. Daniel prüft jedes Ergebnis, bevor du es siehst. Das Team rechnet lokal auf deinem Server. Mit jedem kannst du direkt sprechen.</p>
    <div class="team-raster">${d.team.map((m) => {
      const tut = (d.laeuft && d.laeuft.wer === m.id) ? d.laeuft.was : (m.id === "cockpit" && d.neo_laeuft ? "arbeitet an einem Auftrag" : "");
      return html`<div class="karte mitglied" key=${m.id}>
        <div class="kopf"><${Avatar} wer=${m.id} name=${m.name} g=${38} /><div style="min-width:0"><b>${m.name}</b><small>${m.titel}</small></div>
          <label class="klein leise" style="margin-left:auto;display:flex;gap:5px;align-items:center" title="Darf mitarbeiten">
            <input type="checkbox" checked=${!!m.aktiv} onChange=${(e) => setzen(m, { aktiv: e.target.checked ? 1 : 0 }, e.target.checked ? `${m.name} arbeitet mit.` : `${m.name} pausiert.`)} />aktiv</label></div>
        <div class="leise klein">${m.kurz}</div>
        ${tut && html`<div class="tut">● ${tut}</div>`}
        <div class="feld"><label for=${"mod-" + m.id}>Modell</label>
          <select id=${"mod-" + m.id} class="eingabe" value=${m.modell || ""} onChange=${(e) => setzen(m, { modell: e.target.value }, `${m.name} rechnet jetzt mit ${e.target.value || "der Vorgabe"}.`)}>
            <option value="">Vorgabe</option>
            ${!d.modelle.includes(m.modell) && m.modell && html`<option value=${m.modell}>${m.modell} (nicht installiert)</option>`}
            ${d.modelle.filter((x) => !x.includes("embed")).map((x) => html`<option value=${x}>${x}</option>`)}
          </select></div>
        <div class="knopfreihe">
          <span class="leise klein">${m.heute ? `heute an ${m.heute} Cases` : "heute noch nichts"}${m.ergebnisse ? ` · ${m.ergebnisse} Ergebnisse` : ""}</span>
          <span style="flex:1"></span>
          ${m.id === "cockpit" ? html`<a class="btn klein primaer" href="#/neo">Mit Neo arbeiten</a>`
            : html`<button class="btn klein" onClick=${() => setOffen(m.id)}>Details</button>
              <a class="btn klein primaer" href=${"#/team/chat/" + m.id}><${Icon} n="chat" g=${14} />Chatten</a>`}
        </div>
      </div>`;
    })}</div>
    ${offen && html`<${MitgliedDetail} id=${offen} zu=${() => setOffen(null)} nachher=${laden} />`}`;
}

// Die drei Externen: Claude, Grok, Gemini. Kein "aktiv"-Schalter -- sie arbeiten
// nie von selbst, nur wenn Veiko ihnen schreibt. Das Modell waehlt Veiko hier.
function ExternKarte({ x, nachher }) {
  async function modell(w) {
    try { await api("/teamchat/extern/" + x.id, { methode: "PATCH", daten: { modell: w } }); toast(`${x.name} rechnet jetzt mit ${w || "der Vorgabe"}.`); nachher(); } catch (e) { fehlerMelden(e); }
  }
  const marke = x.schluessel === false ? ["rot", "kein Schlüssel"] : x.schluessel ? ["gelb", "kostet Geld"] : ["", "Stand unbekannt"];
  return html`<div class="karte mitglied extern">
    <div class="kopf"><${Avatar} wer=${x.id} name=${x.name} g=${38} /><div style="min-width:0"><b>${x.name}</b><small>${x.titel}</small></div>
      <span class=${"pill " + marke[0]} style="margin-left:auto">${marke[1]}</span></div>
    <div class="leise klein">${x.kurz}</div>
    <div class="feld"><label for=${"mod-" + x.id}>Modell</label>
      <select id=${"mod-" + x.id} class="eingabe" value=${x.modell || ""} onChange=${(e) => modell(e.target.value)} disabled=${!x.modelle.length}>
        <option value="">Vorgabe${x.vorgabe ? ` (${x.vorgabe})` : ""}</option>
        ${x.modelle.map((m) => html`<option value=${m}>${m}</option>`)}</select></div>
    <div class="knopfreihe"><span class="leise klein">${x.modelle.length ? x.modelle.length + " Modelle verfügbar" : "Modellliste nicht abrufbar"}</span>
      <span style="flex:1"></span>
      <a class="btn klein primaer" href=${"#/team/chat/" + x.id}><${Icon} n="chat" g=${14} />Chatten</a></div>
  </div>`;
}

function MitgliedDetail({ id, zu, nachher }) {
  const [m, setM] = useState(null);
  const [auftrag, setAuftrag] = useState("");
  useEffect(() => { api("/team/" + id).then((x) => { setM(x); setAuftrag(x.auftrag || ""); }).catch(fehlerMelden); }, [id]);
  if (!m) return html`<${Modal} titel="Mitglied" zu=${zu}><div class="lade">Lade …</div><//>`;
  async function speichern() {
    try { await api("/team/" + id, { methode: "PATCH", daten: { auftrag } }); toast("Auftrag gespeichert."); nachher(); zu(); } catch (e) { fehlerMelden(e); }
  }
  return html`<${Modal} titel=${`${m.name} · ${m.titel}`} zu=${zu} breit=${true} fuss=${html`<button class="btn geist" onClick=${zu}>Schließen</button>
      <button class="btn primaer" disabled=${auftrag === (m.auftrag || "")} onClick=${speichern}>Auftrag speichern</button>`}>
    <div class="raster zwei">
      <div class="feld"><label for="md-auftrag">Auftrag (so arbeitet ${m.name})</label>
        <textarea id="md-auftrag" class="eingabe" rows="16" value=${auftrag} onInput=${(e) => setAuftrag(e.target.value)} onKeyDown=${enterBestaetigt} style="font-size:13px"></textarea></div>
      <div><h4 style="margin-bottom:8px">Zuletzt</h4>
        ${m.zuletzt.length ? m.zuletzt.map((z) => html`<div class="zeile"><div class="haupt-text"><a href=${"#/inbox/" + z.vorgang_id} onClick=${zu}>${z.titel || "Case"}</a>
          <div class="leise klein">${z.text.slice(0, 120)}</div></div><span class="neben">${zeitText(z.zeit)}</span></div>`) : html`<${Leer}>Noch nichts in der neuen Fassung.</${Leer}>`}
      </div>
    </div>
  <//>`;
}

const ARTEN = [["person", "Person"], ["organisation", "Organisation"], ["begriff", "Begriff, Abkürzung"], ["hoerfehler", "Hörfehler (wird korrigiert)"], ["aussprache", "Aussprache (so wird vorgelesen)"]];

export function Gedaechtnis() {
  const [d, laden] = useAbruf("/gedaechtnis", 0, []);
  const [neu, setNeu] = useState({ art: "person", begriff: "", bedeutung: "" });
  const [bearb, setBearb] = useState(null);
  async function anlegen() {
    try { await api("/gedaechtnis", { methode: "POST", daten: neu }); setNeu({ ...neu, begriff: "", bedeutung: "" }); toast("Gemerkt."); laden(); } catch (e) { fehlerMelden(e); }
  }
  async function speichern() {
    try { await api("/gedaechtnis/" + bearb.id, { methode: "PATCH", daten: bearb }); setBearb(null); laden(); } catch (e) { fehlerMelden(e); }
  }
  async function loeschen(g) {
    try { await api("/gedaechtnis/" + g.id, { methode: "DELETE" }); toast("Vergessen: " + g.begriff); laden(); } catch (e) { fehlerMelden(e); }
  }
  return html`<div class="raster zwei">
    <section class="karte">
      <div class="karte-kopf"><h3>Was dein Team über dich weiß</h3><span class="pill">${d ? d.eintraege.length : "…"}</span></div>
      ${!d ? html`<div class="lade">Lade …</div>` : !d.eintraege.length ? html`<${Leer} titel="Noch leer.">Dein Team schlägt Einträge vor, wenn er auf unbekannte Namen stößt. Du kannst auch selbst etwas eintragen.</${Leer}>`
        : d.eintraege.map((g) => bearb && bearb.id === g.id ? html`<div class="zeile" key=${g.id} style="flex-wrap:wrap">
            <input class="eingabe" style="flex:1;min-width:120px" value=${bearb.begriff} onInput=${(e) => setBearb({ ...bearb, begriff: e.target.value })} />
            <input class="eingabe" style="flex:2;min-width:160px" value=${bearb.bedeutung} onInput=${(e) => setBearb({ ...bearb, bedeutung: e.target.value })}
              onKeyDown=${(e) => { if (e.key === "Enter") speichern(); if (escEigen(e)) setBearb(null); }} />
            <button class="btn ja klein" onClick=${speichern}>Speichern</button><button class="btn geist klein" onClick=${() => setBearb(null)}>Abbrechen</button></div>`
          : html`<div class="zeile" key=${g.id}>
            <span class="pill">${(ARTEN.find((a) => a[0] === g.art) || [0, g.art])[1].split(" ")[0]}</span>
            <div class="haupt-text"><b>${g.begriff}</b> ${g.art === "hoerfehler" ? "→" : g.art === "aussprache" ? "🔊" : "="} ${g.bedeutung}</div>
            <button class="btn klein geist icon" aria-label="Bearbeiten" onClick=${() => setBearb({ ...g })}><${Icon} n="stift" g=${14} /></button>
            <button class="btn klein geist icon" aria-label="Vergessen" onClick=${() => loeschen(g)}><${Icon} n="x" g=${14} /></button></div>`)}
    </section>
    <section class="karte">
      <div class="karte-kopf"><h3>Etwas eintragen</h3></div>
      <div class="feld"><label for="gd-art">Art</label><select id="gd-art" class="eingabe" value=${neu.art} onChange=${(e) => setNeu({ ...neu, art: e.target.value })}>
        ${ARTEN.map(([k, t]) => html`<option value=${k}>${t}</option>`)}</select></div>
      <div class="feld" style="margin-top:8px"><label for="gd-b">${neu.art === "hoerfehler" ? "Was Whisper versteht" : neu.art === "aussprache" ? "Wort, wie es geschrieben wird" : "Begriff oder Name"}</label>
        <input id="gd-b" class="eingabe" value=${neu.begriff} placeholder=${neu.art === "hoerfehler" ? "z. B. Kronis" : "z. B. Mutti"} onInput=${(e) => setNeu({ ...neu, begriff: e.target.value })} onKeyDown=${(e) => { if (e.key === "Enter" && neu.begriff && neu.bedeutung) anlegen(); }} /></div>
      <div class="feld" style="margin-top:8px"><label for="gd-bed">${neu.art === "hoerfehler" ? "Was gemeint ist" : neu.art === "aussprache" ? "So soll es klingen (deutsche Lautschrift, z. B. Slaids)" : "Bedeutung"}</label>
        <input id="gd-bed" class="eingabe" value=${neu.bedeutung} placeholder=${neu.art === "hoerfehler" ? "z. B. Krones" : "z. B. Brunhilde von Eckern, meine Mutter"} onInput=${(e) => setNeu({ ...neu, bedeutung: e.target.value })}
          onKeyDown=${(e) => { if (e.key === "Enter" && neu.begriff && neu.bedeutung) anlegen(); }} /></div>
      <button class="btn primaer" style="margin-top:10px" disabled=${!neu.begriff.trim() || !neu.bedeutung.trim()} onClick=${anlegen}>Merken</button>
      <p class="leise klein" style="margin-top:12px">Jede Rolle bekommt diese Liste bei jeder Arbeit mit. Hörfehler werden korrigiert, bevor das Team eine Notiz liest, und die Namen helfen Whisper schon beim Zuhören.</p>
    </section>
  </div>`;
}

// E-Mails ans Cockpit: nur anzeigen, nicht einstellen. Zugangsdaten gehoeren in
// die Konfiguration auf dem Server, nie in den Browser (postfach.py).
function PostfachZeile({ p, nachher }) {
  const [laeuft, setLaeuft] = useState(false);
  if (!p) return "";
  async function abrufen() {
    setLaeuft(true);
    try { const r = await api("/postfach/abrufen", { methode: "POST" }); toast(r.neu ? `${r.neu} Mail(s) ans Team übergeben.` : r.letzter_fehler ? "Abruf gescheitert: " + r.letzter_fehler : "Keine neue Mail."); nachher(); }
    catch (e) { fehlerMelden(e); }
    setLaeuft(false);
  }
  return html`<div class="zeile" style="flex-wrap:wrap"><div class="haupt-text"><b>E-Mails ans Cockpit</b>
      <div class="leise klein">${!p.eingerichtet ? "noch nicht eingerichtet. Die Zugangsdaten kommen in die Konfiguration auf dem Server."
        : html`An <b>${p.adresse}</b> schreiben, Jason bearbeitet die Mail wie eine Plaud-Notiz. Angenommen nur von: ${p.erlaubt.length ? p.erlaubt.join(", ") : html`<b>niemandem (Liste leer)</b>`}.
          ${p.letzter_abruf ? ` Zuletzt abgerufen ${zeitText(p.letzter_abruf)}.` : " Noch nicht abgerufen."}`}</div>
      ${p.letzter_fehler && html`<div class="klein" style="color:var(--rot)">Abruf gescheitert: ${p.letzter_fehler}</div>`}
      ${(p.abgewiesen || []).length > 0 && html`<details class="klein" style="margin-top:4px"><summary style="cursor:pointer">${p.abgewiesen.length} abgewiesen</summary>
        ${p.abgewiesen.slice().reverse().map((a) => html`<div class="leise">${zeitText(a.zeit)} · ${a.von || "?"} · „${a.betreff}“ · ${a.grund}</div>`)}</details>`}</div>
    ${p.eingerichtet ? html`<button class="btn klein" disabled=${laeuft} onClick=${abrufen}><${Icon} n="inbox" g=${14} />${laeuft ? "Ruft ab …" : "Jetzt abrufen"}</button>`
      : html`<span class="pill">aus</span>`}
  </div>`;
}

const STUFEN = [
  ["zuordnen", "Notiz einem bestehenden Projekt zuordnen", "Häufigster Fall, leicht zu korrigieren"],
  ["aufgaben", "Aufgaben für dich aus einer Notiz anlegen", "Das, was bisher am verlässlichsten klappte"],
  ["ausarbeiten", "Ausarbeiten, wenn die Notiz es ausdrücklich verlangt", "Kostet nur Rechenzeit auf deinem Server"],
  ["projekt_neu", "Neue Projekte anlegen", "Ändert deinen Portfolio-Bestand"],
  ["gedaechtnis", "Etwas ins Memory schreiben", "Ein falscher Eintrag verfälscht jede spätere Antwort"],
];

// Mit welcher Stimme Talk und "Vorlesen" sprechen (stimme.STIMMEN). Eine Hoerprobe
// vor der Wahl -- wie natuerlich eine Stimme klingt, misst kein Werkzeug.
function StimmeZeile({ d, setzen }) {
  const [spielt, setSpielt] = useState(null);
  const ton = useRef(null);
  if (!d.stimmen) return "";
  function probe(id) {
    if (ton.current) { ton.current.pause(); ton.current = null; }
    if (spielt === id) { setSpielt(null); return; }
    const a = new Audio("/api/stimme/probe?stimme_id=" + encodeURIComponent(id));
    ton.current = a; setSpielt(id);
    a.onended = () => setSpielt(null);
    a.play().catch((e) => { setSpielt(null); fehlerMelden(e); });
  }
  return html`<div class="zeile stimme-zeile"><div class="haupt-text"><b>Stimme von Talk</b>
      <div class="leise klein">Spricht in Talk und beim Vorlesen. Erst anhören, dann wählen.</div>
      <div class="stimme-liste">${Object.entries(d.stimmen).map(([id, name]) => html`<div class="stimme-wahl">
        <label><input type="radio" name="talk-stimme" checked=${d.talk_stimme === id} onChange=${() => setzen({ talk_stimme: id })} />${name}</label>
        <button class="btn klein geist" onClick=${() => probe(id)} title="Hörprobe"><${Icon} n=${spielt === id ? "stopp" : "play"} g=${13} />${spielt === id ? "Stopp" : "Probe"}</button></div>`)}</div>
    </div></div>`;
}

export function Vertrauen() {
  const [d, laden] = useAbruf("/einstellungen", 0, []);
  if (!d) return html`<div class="lade">Lade …</div>`;
  async function setzen(daten) {
    try { await api("/einstellungen", { methode: "POST", daten }); toast("Gespeichert."); laden(); aktualisieren(); } catch (e) { fehlerMelden(e); }
  }
  return html`<div class="raster zwei">
    <section class="karte">
      <div class="karte-kopf"><h3>Was dein Team ohne Nachfrage tun darf</h3></div>
      ${STUFEN.map(([k, t, w]) => html`<div class="zeile" key=${k}>
        <div class="haupt-text"><b>${t}</b><div class="leise klein">${w}</div></div>
        <div class="segment"><button class=${d.vertrauen[k] === "selbst" ? "an" : ""} onClick=${() => setzen({ vertrauen: { [k]: "selbst" } })}>selbst, mit Rückgängig</button>
          <button class=${d.vertrauen[k] === "fragen" ? "an" : ""} onClick=${() => setzen({ vertrauen: { [k]: "fragen" } })}>erst fragen</button></div>
      </div>`)}
      <div class="zeile"><div class="haupt-text"><b>Cloud-Modelle, Mails verschicken</b><div class="leise klein">Kostet Geld oder geht nach außen</div></div><span class="pill gelb">immer fragen</span></div>
      <div class="zeile"><div class="haupt-text"><b>Löschen, Code einspielen, Server ändern</b><div class="leise klein">Nur du, auf der Seite Stack oder über Neo</div></div><span class="pill rot">nie vom Team</span></div>
    </section>
    <section class="karte">
      <div class="karte-kopf"><h3>Team in dieser Fassung</h3></div>
      <div class="zeile"><div class="haupt-text"><b>Neue Plaud-Notizen bearbeiten</b>
        <div class="leise klein">${d.stab_aktiv ? `an, für Notizen seit ${new Date(d.stab_ab * 1000).toLocaleString("de-DE")}` : "aus. Notizen kommen trotzdem herein, nur ohne Einordnung."}</div></div>
        <div class="segment"><button class=${d.stab_aktiv ? "an" : ""} onClick=${() => setzen({ stab_aktiv: true })}>an</button>
          <button class=${!d.stab_aktiv ? "an" : ""} onClick=${() => setzen({ stab_aktiv: false })}>aus</button></div></div>
      <${StimmeZeile} d=${d} setzen=${setzen} />
      <${PostfachZeile} p=${d.postfach} nachher=${laden} />
      ${(() => {
        const a = d.alt_automatik;
        if (!a) return html`<div class="hinweisbox" style="margin-top:12px">Stand des alten Cockpits nicht lesbar.</div>`;
        const aus = a.verarbeitung_aktiv === false;
        return html`<div class="hinweisbox" style="margin-top:12px"><b>Altes Cockpit:</b> ${aus
          ? "bearbeitet keine Notizen mehr, trägt nichts mehr selbst ein" + (a.bericht_aktiv === false ? " und schickt keinen Morgenbericht" : "") + ". Du arbeitest nur noch hier."
          : "bearbeitet dieselben Notizen parallel mit seiner eigenen Pipeline (doppelte Arbeit auf denselben Grafikkarten). Abschalten: im alten Cockpit unter Setup Settings."}
          ${" "}Sein Notizimport ist ${a.import_aktiv === false ? html`<b>aus -- dann kommen auch hier keine Plaud-Notizen an</b>` : "an; diese Fassung liest dessen Ablage"}.</div>`;
      })()}
    </section>
  </div>`;
}
