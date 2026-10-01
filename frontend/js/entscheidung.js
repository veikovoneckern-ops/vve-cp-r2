// Eine Entscheidungskarte -- im Briefing und in der Inbox derselbe Baustein.
// Reihenfolge der Knoepfe ueberall gleich: Hauptaktion zuerst, dann Aendern,
// dann Nein, ganz rechts leise "Spaeter".
import { html, useState, Icon, Avatar, toast, fehlerMelden, aktualisieren, bus, navigiere, zeitText } from "./ui.js";
import { api } from "./api.js";
import { Composer } from "./composer.js";

const HAUPT = { projekt_neu: "Anlegen", gedaechtnis: "Merken", ausarbeitung: "Ja, ausarbeiten", zuordnung: "Zuordnen", aufgabe: "Anlegen" };
const AENDERN = { projekt_neu: "Anderer Name", gedaechtnis: "Anders merken", ausarbeitung: "Ergänzen" };
const ART_TEXT = { projekt_neu: "Neues Projekt", gedaechtnis: "Gedächtnis", rueckfrage: "Rückfrage", ausarbeitung: "Ausarbeitung", zuordnung: "Zuordnung", aufgabe: "Aufgabe" };

export function Entscheidung({ e, mitVorgang = true, nachher }) {
  const [modus, setModus] = useState(e.art === "rueckfrage" ? "antwort" : null);
  const [text, setText] = useState(e.art === "projekt_neu" ? (e.daten && e.daten.name) || "" : e.art === "gedaechtnis" ? (e.daten && e.daten.bedeutung) || "" : "");
  const [laeuft, setLaeuft] = useState(false);
  const [weg, setWeg] = useState(false);

  async function antworten(antwort, t = "") {
    setLaeuft(true);
    try {
      await api("/entscheidungen/" + e.id, { methode: "POST", daten: { antwort, text: t } });
      if (antwort === "spaeter") toast("Zurückgestellt.");
      else if (e.art === "rueckfrage") toast("Antwort ist beim Stab.");
      else toast(antwort === "ja" ? "Erledigt." : "Abgelehnt.");
      setWeg(true);
      aktualisieren();
      nachher && nachher();
      return true;
    } catch (x) { fehlerMelden(x); setLaeuft(false); return false; }
  }

  if (weg) return null;
  return html`<div class=${"entscheidung " + e.art}>
    <div class="wer">
      <${Avatar} wer=${e.wer} name=${e.wer_name} g=${20} />
      <span><b>${e.wer_name || "Stab"}</b> · ${ART_TEXT[e.art] || e.art}</span>
      ${mitVorgang && e.vorgang_id && html`<a href=${"#/inbox/" + e.vorgang_id} style="color:inherit">aus „${(e.vorgang_titel || "Vorgang").slice(0, 60)}“</a>`}
      <span class="leise" style="margin-left:auto">${zeitText(e.erstellt)}</span>
    </div>
    <div class="frage">${e.frage}</div>
    ${modus === "antwort" ? html`
      <${Composer} platzhalter="Deine Antwort … (tippen oder diktieren)" erlaubeAnhang=${false} hinweis="" sendenText="Antworten"
        beimSenden=${(t) => antworten("ja", t)} entwurfKey=${"antwort:" + e.id} />
      <div class="knopfreihe" style="margin-top:6px">
        <button class="btn klein" onClick=${() => bus.sende("talk-oeffnen", { kontext: e.vorgang_id ? { art: "vorgang", id: e.vorgang_id, titel: e.vorgang_titel } : null, text: "Lass uns über diese Rückfrage reden: " + e.frage })}><${Icon} n="talk" g=${14} />Im Gespräch klären</button>
        <button class="btn klein geist" disabled=${laeuft} onClick=${() => antworten("nein")}>Nicht beantworten</button>
        <button class="btn klein geist" disabled=${laeuft} onClick=${() => antworten("spaeter")} style="margin-left:auto">Später</button>
      </div>`
    : modus === "aendern" ? html`
      <div class="antwortfeld">
        <input class="eingabe" value=${text} onInput=${(x) => setText(x.target.value)} aria-label="Änderung"
          onKeyDown=${(x) => { if (x.key === "Enter" && text.trim()) antworten("ja", text.trim()); if (x.key === "Escape") setModus(null); }} autofocus />
        <button class="btn ja" disabled=${laeuft || !text.trim()} onClick=${() => antworten("ja", text.trim())}><${Icon} n="check" g=${15} />${HAUPT[e.art] || "Ja"}</button>
        <button class="btn geist" onClick=${() => setModus(null)}>Abbrechen</button>
      </div>`
    : html`<div class="knopfreihe">
        <button class="btn ja" disabled=${laeuft} onClick=${() => antworten("ja")}><${Icon} n="check" g=${15} />${HAUPT[e.art] || "Ja"}</button>
        ${AENDERN[e.art] && html`<button class="btn" disabled=${laeuft} onClick=${() => { if (e.art === "ausarbeitung") setText(""); setModus("aendern"); }}><${Icon} n="stift" g=${14} />${AENDERN[e.art]}</button>`}
        <button class="btn" disabled=${laeuft} onClick=${() => antworten("nein")}>Nein</button>
        <button class="btn geist klein" disabled=${laeuft} onClick=${() => antworten("spaeter")} style="margin-left:auto">Später</button>
      </div>`}
  </div>`;
}

// Verfuegbar fuer den Sprach-Durchgang im Talk.
export async function entscheidungBeantworten(id, antwort, text = "") {
  return api("/entscheidungen/" + id, { methode: "POST", daten: { antwort, text } });
}
export { navigiere };
