// TEAM -- Veikos KI-Team: wer ist da, womit rechnet er, was hat er zuletzt getan.
// Dazu Memory (was das Team ueber Veiko weiss) und Freigaben (was das Team
// ohne Nachfrage tun darf). Das Advisory Board hat einen eigenen Bereich (board.js).
import { html, enterBestaetigt, useState, useEffect, Icon, Avatar, Leer, Modal, toast, fehlerMelden, aktualisieren, zeitText, useAbruf, navigiere, bus } from "./ui.js";
import { api } from "./api.js";

const TABS = [["mitglieder", "Mitglieder"], ["gedaechtnis", "Memory"], ["vertrauen", "Freigaben"]];

export function Team({ id }) {
  const [tab, setTab] = useState(id && TABS.some((t) => t[0] === id) ? id : "mitglieder");
  useEffect(() => { bus.sende("talk-kontext", null); }, []);
  return html`<div class="seite">
    <div class="tabs" role="tablist">${TABS.map(([k, t]) => html`<button role="tab" aria-selected=${tab === k} class=${tab === k ? "an" : ""} onClick=${() => setTab(k)}>${t}</button>`)}</div>
    ${tab === "mitglieder" && html`<${Mitglieder} />`}
    ${tab === "gedaechtnis" && html`<${Gedaechtnis} />`}
    ${tab === "vertrauen" && html`<${Vertrauen} />`}
  </div>`;
}

function Mitglieder() {
  const [d, laden] = useAbruf("/team", 15000, []);
  const [offen, setOffen] = useState(null);
  if (!d) return html`<div class="lade">Lade …</div>`;
  async function setzen(m, daten, meldung) {
    try { await api("/team/" + m.id, { methode: "PATCH", daten }); toast(meldung); laden(); } catch (e) { fehlerMelden(e); }
  }
  return html`
    <p class="leise" style="margin-bottom:12px;max-width:70ch">Jason ordnet jede neue Notiz ein und plant. Die anderen arbeiten, wenn eine Notiz oder du es ausdrücklich verlangst. Daniel prüft jedes Ergebnis, bevor du es siehst. Alle rechnen lokal auf deinem Server.</p>
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
            : html`<button class="btn klein" onClick=${() => setOffen(m.id)}>Details</button>`}
        </div>
      </div>`;
    })}</div>
    ${offen && html`<${MitgliedDetail} id=${offen} zu=${() => setOffen(null)} nachher=${laden} />`}`;
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

function Gedaechtnis() {
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
              onKeyDown=${(e) => { if (e.key === "Enter") speichern(); if (e.key === "Escape") setBearb(null); }} />
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

const STUFEN = [
  ["zuordnen", "Notiz einem bestehenden Projekt zuordnen", "Häufigster Fall, leicht zu korrigieren"],
  ["aufgaben", "Aufgaben für dich aus einer Notiz anlegen", "Das, was bisher am verlässlichsten klappte"],
  ["ausarbeiten", "Ausarbeiten, wenn die Notiz es ausdrücklich verlangt", "Kostet nur Rechenzeit auf deinem Server"],
  ["projekt_neu", "Neue Projekte anlegen", "Ändert deinen Portfolio-Bestand"],
  ["gedaechtnis", "Etwas ins Memory schreiben", "Ein falscher Eintrag verfälscht jede spätere Antwort"],
];

function Vertrauen() {
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
      <div class="zeile"><div class="haupt-text"><b>Löschen, Code einspielen, Server ändern</b><div class="leise klein">Nur du, im Bereich System oder über Neo</div></div><span class="pill rot">nie vom Team</span></div>
    </section>
    <section class="karte">
      <div class="karte-kopf"><h3>Team in dieser Fassung</h3></div>
      <div class="zeile"><div class="haupt-text"><b>Neue Plaud-Notizen bearbeiten</b>
        <div class="leise klein">${d.stab_aktiv ? `an, für Notizen seit ${new Date(d.stab_ab * 1000).toLocaleString("de-DE")}` : "aus. Notizen kommen trotzdem herein, nur ohne Einordnung."}</div></div>
        <div class="segment"><button class=${d.stab_aktiv ? "an" : ""} onClick=${() => setzen({ stab_aktiv: true })}>an</button>
          <button class=${!d.stab_aktiv ? "an" : ""} onClick=${() => setzen({ stab_aktiv: false })}>aus</button></div></div>
      <div class="hinweisbox" style="margin-top:12px">Das alte Cockpit läuft parallel weiter und bearbeitet dieselben Notizen mit seiner eigenen Pipeline. Beide schreiben in getrennte Ablagen, nichts wird überschrieben. Wenn du ganz umsteigst, schaltest du im alten Cockpit unter Setup Settings die automatische Verarbeitung aus.</div>
    </section>
  </div>`;
}
