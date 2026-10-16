// BRIEFING -- die Startseite. Beantwortet die Frage, die man beim Oeffnen hat:
// Was wartet auf mich, was hat der Stab getan, laeuft alles?
import { html, useState, useEffect, Icon, Avatar, Leer, rolleName, bus, toast, fehlerMelden, aktualisieren, zeitText, datumText, navigiere } from "./ui.js";
import { ErgebnisZeile } from "./ergebnis.js";
import { api } from "./api.js";
import { Entscheidung } from "./entscheidung.js";

function gruss() {
  const h = new Date().getHours();
  return h < 11 ? "Guten Morgen" : h < 17 ? "Hallo" : h < 22 ? "Guten Abend" : "Noch wach";
}

function Gesundheit({ g, neo }) {
  if (!g) return null;
  const jetzt = Date.now() / 1000;
  const syncAlt = g.sync && jetzt - g.sync > 1800;
  const notizAlt = g.letzte_datei && jetzt - g.letzte_datei > 6 * 3600;
  const laeuft = g.laeuft;
  return html`<div class="gesundheit" role="status">
    <span><i class=${"punkt" + (syncAlt ? " rot" : notizAlt ? " gelb" : "")}></i>
      ${syncAlt ? html`<b>Plaud-Abruf hängt</b> seit ${zeitText(g.sync).replace("vor ", "")}`
        : html`Plaud: letzte Notiz ${g.letzte_datei ? zeitText(g.letzte_datei) : "unbekannt"}`}</span>
    <span><i class=${"punkt" + (!g.stab_aktiv ? " gelb" : g.letzter_fehler ? " gelb" : "")}></i>
      ${!g.stab_aktiv ? "Team pausiert" : g.letzter_lauf ? `Team: letzter Durchgang ${zeitText(g.letzter_lauf)}` : "Team startet …"}</span>
    ${laeuft && html`<span><i class="punkt lila"></i>${rolleName(laeuft.wer)} ${laeuft.was}</span>`}
    ${neo && neo.length > 0 && html`<span><i class="punkt lila"></i><a href=${"#/neo/" + neo[0].gespraech_id}>Neo arbeitet</a> seit ${zeitText(neo[0].seit).replace("vor ", "")}</span>`}
    ${g.letzter_fehler && html`<span class="leise" title=${g.letzter_fehler}>Letzter Fehler: ${g.letzter_fehler.slice(0, 70)}</span>`}
  </div>`;
}

export function Briefing({ lage }) {
  const [offen, setOffen] = useState(undefined);   // welches Ergebnis aufgeklappt ist; undefined = noch nicht entschieden
  // Beim Verlassen merkt sich der Server "gesehen" -- beim naechsten Besuch ist
  // nur neu, was danach kam. Auf dem Server, damit Handy und Rechner gleich zaehlen.
  useEffect(() => () => { api("/lage/gesehen", { methode: "POST" }).catch(() => {}); }, []);
  if (!lage) return html`<div class="seite"><div class="lade">Lage wird geholt …</div></div>`;
  const ents = lage.entscheidungen || [];
  const w = lage.woche || {};
  const gesehen = lage.gesehen || 0;
  const neu = lage.neu || {};
  const ergebnisse = lage.ergebnisse || [];
  // Das neueste NEUE Ergebnis steht beim Oeffnen gleich aufgeklappt da --
  // genau das, was man beim Oeffnen sehen will.
  const vorgabeOffen = (ergebnisse.find((e) => e.erstellt > gesehen) || {}).id || null;
  const aufId = offen === undefined ? vorgabeOffen : offen;

  async function rueckgaengig(pid) {
    try { await api("/rueckgaengig/" + pid, { methode: "POST" }); toast("Zurückgenommen."); aktualisieren(); } catch (e) { fehlerMelden(e); }
  }
  async function erledigen(t) {
    try { await api("/aufgaben/" + t.id, { methode: "PATCH", daten: { status: "erledigt" } }); toast("Erledigt: " + t.titel, { aktion: { text: "Rückgängig", fn: () => api("/aufgaben/" + t.id, { methode: "PATCH", daten: { status: "offen" } }).then(aktualisieren) } }); aktualisieren(); } catch (e) { fehlerMelden(e); }
  }

  const seit = [neu.ergebnisse ? `${neu.ergebnisse} ${neu.ergebnisse === 1 ? "neues Ergebnis" : "neue Ergebnisse"}` : "",
    neu.cases ? `${neu.cases} ${neu.cases === 1 ? "neuer Case" : "neue Cases"}` : "",
    ents.length ? `${ents.length} ${ents.length === 1 ? "Entscheidung wartet" : "Entscheidungen warten"} auf dich` : ""].filter(Boolean);

  return html`<div class="seite">
    <div class="gruss">
      <div><h2>${gruss()}, Veiko.</h2>
        <div class="leise">${gesehen ? `Seit deinem letzten Besuch (${zeitText(gesehen)}): ` : ""}${seit.length ? seit.join(" · ") + "." : "nichts Neues."}</div></div>
      <span style="flex:1"></span>
      <div class="knopfreihe">
        <button class="btn" onClick=${() => bus.sende("erfassen")}><${Icon} n="plus" g=${15} />Capture</button>
        <button class="btn primaer" onClick=${() => bus.sende("talk-oeffnen", { text: "Was liegt an?" })}><${Icon} n="talk" g=${15} />Was liegt an?</button>
      </div>
    </div>
    <${Gesundheit} g=${lage.gesundheit} neo=${lage.neo_laeuft} />
    <div class="raster zwei briefing-raster">
      <div>
        ${ents.length > 0 && html`<section class="karte">
          <div class="karte-kopf"><h3>Wartet auf dich</h3><span class="pill gelb">${ents.length}</span>
            <button class="btn klein rechts" onClick=${() => bus.sende("talk-oeffnen", { durchgehen: true })} title="Das Cockpit liest jede Entscheidung vor, du antwortest mit ja, nein, später oder frei">
              <${Icon} n="play" g=${13} />Per Stimme durchgehen</button></div>
          ${ents.map((e) => html`<${Entscheidung} key=${e.id} e=${e} />`)}
        </section>`}
        <section class="karte">
          <div class="karte-kopf"><h3>Neu entstanden</h3><span class="leise klein">Ergebnisse deines Teams, letzte sieben Tage</span></div>
          ${ergebnisse.length ? ergebnisse.map((e) => html`<${ErgebnisZeile} key=${e.id} e=${e} neu=${gesehen && e.erstellt > gesehen}
              auf=${aufId === e.id} umschalten=${() => setOffen(aufId === e.id ? null : e.id)} />`)
            : html`<${Leer} titel="Noch keine Ergebnisse diese Woche.">Wenn eine Notiz um eine Ausarbeitung bittet, erscheint das Ergebnis hier -- mit Vorschau und Downloads.</${Leer}>`}
        </section>
        ${(lage.laufend.length > 0 || (lage.videos || []).length > 0 || (lage.gespraeche_laufen || []).length > 0) && html`<section class="karte">
          <div class="karte-kopf"><h3>Läuft gerade</h3></div>
          ${(lage.gespraeche_laufen || []).map((g) => html`<div class="zeile" key=${"g" + g.gespraech_id}>
            ${g.wer && html`<${Avatar} wer=${g.wer} name=${g.wer_name} g=${22} />`}
            <div class="haupt-text"><b>${g.wer_name}</b> antwortet dir${g.art === "team" ? " im Team-Chat" : g.art === "talk" ? " in Talk" : " im Advisory Board"}
              <div class="leise klein">${g.status || "schreibt"} · seit ${zeitText(g.start).replace("vor ", "")}</div></div>
            <span class="pill lila">läuft</span></div>`)}
          ${(lage.videos || []).map((v) => html`<div class="zeile" key=${"v" + v.id}>
            <div class="haupt-text"><b>${v.titel}</b><div class="leise klein">${v.schritt || "Video wird gerechnet"} · seit ${zeitText(v.start).replace("vor ", "")}</div>
              <div class="video-balken"><i style=${`width:${v.szenen ? Math.round(v.fertig / v.szenen * 100) : 0}%`}></i></div></div>
            <button class="btn klein" onClick=${() => bus.sende("ergebnis-zeigen", v.id)}>Ansehen</button></div>`)}
          ${lage.laufend.map((v) => html`<div class="zeile" key=${v.id}>
            <div class="haupt-text"><a href=${"#/inbox/" + v.id} style="color:inherit">${v.titel}</a>
              <div class="leise klein">${v.versuche >= 3 ? "hängt nach drei Versuchen" : v.wer_name + " · " + zeitText(v.geaendert)}</div></div>
            ${v.versuche >= 3 ? html`<span class="pill rot">hängt</span>` : html`<span class="pill lila">läuft</span>`}
          </div>`)}
        </section>`}
        ${ents.length === 0 && html`<div class="leise klein briefing-ruhe"><${Icon} n="check" g=${13} /> Nichts wartet auf deine Entscheidung.</div>`}
        <details class="karte eingetragen">
          <summary><b>Vom Team eingetragen</b> <span class="leise klein">${lage.erledigt.length} in drei Tagen${neu.erledigt ? `, ${neu.erledigt} neu` : ""} · Aufgaben, Zuordnungen, Memory · jede Änderung lässt sich zurücknehmen</span></summary>
          ${lage.erledigt.length ? lage.erledigt.map((x) => html`<div class="zeile" key=${x.protokoll_id}>
              <${Avatar} wer=${x.wer} name=${x.wer_name} g=${22} />
              <div class="haupt-text">${gesehen && x.zeit > gesehen ? html`<span class="pill lila neu-marke">neu</span>` : ""}${x.vorgang_id ? html`<a href=${"#/inbox/" + x.vorgang_id} style="color:inherit;text-decoration:none">${x.text}</a>` : x.text}</div>
              <span class="neben">${zeitText(x.zeit)}</span>
              <button class="btn klein geist" onClick=${() => rueckgaengig(x.protokoll_id)} title="Diese Änderung zurücknehmen"><${Icon} n="undo" g=${14} />Rückgängig</button>
            </div>`) : html`<${Leer}>Noch nichts. Sobald eine Notiz hereinkommt, ordnet Jason sie ein und legt Aufgaben an.</${Leer}>`}
        </details>
      </div>
      <div>
        <section class="karte">
          <div class="karte-kopf"><h3>Deine nächsten Aufgaben</h3><a class="rechts klein" href="#/projects/_aufgaben">alle</a></div>
          ${lage.aufgaben.length ? lage.aufgaben.map((t) => html`<div class="zeile" key=${t.id}>
            <button class="check" onClick=${() => erledigen(t)} aria-label=${"Erledigt: " + t.titel} title="Erledigt"></button>
            <div class="haupt-text">${t.titel}
              <div class="leise klein">${t.projekt_name ? html`<span class="punkt" style=${"background:" + (t.projekt_farbe || "#999") + ";width:7px;height:7px;margin-right:5px"}></span>${t.projekt_name}` : "ohne Projekt"}
              ${t.quelle === "stab" ? " · vom Team" : ""}</div></div>
            ${t.faellig && html`<span class="neben">${datumText(t.faellig)}</span>`}
          </div>`) : html`<${Leer}>Keine offenen Aufgaben.</${Leer}>`}
        </section>
        <section class="karte">
          <div class="karte-kopf"><h3>Diese Woche</h3></div>
          <div class="statistik">
            <div><b>${w.entschieden ? `${w.angenommen}/${w.entschieden}` : "—"}</b><span>Vorschläge angenommen</span></div>
            <div><b>${w.notizen ?? "—"}</b><span>neue Notizen</span></div>
            <div><b>${w.erledigt ?? "—"}</b><span>Aufgaben erledigt</span></div>
            <div><b>${w.projekte ?? "—"}</b><span>aktive Projekte</span></div>
          </div>
        </section>
      </div>
    </div>
  </div>`;
}
