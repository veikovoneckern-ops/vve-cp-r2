// MAIL (22.10.2026) -- ein Postausgang im Cockpit: Entwuerfe, Gesendet, Adressbuch.
// Veiko: "das Cockpit soll E-Mails an neue Adressen schicken koennen, z. B. Ergebnisse, Aufgaben,
// Notizen ... mit Talk ausfuehren ... gleich gute Vorschlaege zur Formulierung ... eine Art
// E-Mail-Client im Cockpit mit sehr guten Funktionalitaeten."
// Versendet wird ueber den Postausgang des alten Backends (info@veikovoneckern.org, mail.py).
// Der Text ist echter Fliesstext mit Formatierung (contenteditable): fett, kursiv, Listen, Links.
// Die Werkzeugknoepfe haengen an mousedown mit preventDefault -- ein Klick naehme dem Schreibfeld
// sonst zuerst die Markierung, bevor der Befehl laeuft (dieselbe Falle wie im alten Cockpit).
// Gespeichert wird von selbst (1,2 s nach der letzten Eingabe); gesendet nur auf Knopfdruck
// mit Rueckfrage -- eine Mail nach aussen ist nicht zurueckzuholen.
import { html, useState, useEffect, useRef, Icon, Leer, Modal, bus, escFensterZu, toast, fehlerMelden, aktualisieren, zeitText, useAbruf, navigiere } from "./ui.js";
import { api, hochladen } from "./api.js";
import { Textfeld } from "./composer.js";
import { diktieren, mikrofonGrund, mikroAnfordern, mikroFreigeben } from "./stimme.js";

const KI = [["entwurf", "Entwurf schreiben", "Schreibt die Mail aus Anhang, Bezug und deiner Anweisung"],
  ["klarer", "Klarer", "Anliegen zuerst, was der Empfänger tun soll"], ["kuerzer", "Kürzer", "Gleicher Inhalt, deutlich knapper"],
  ["freundlicher", "Freundlicher", "Wärmer und persönlicher"], ["foermlicher", "Förmlicher", "Geschäftlicher Ton"],
  ["englisch", "Englisch", "Ins Englische übersetzen"], ["korrektur", "Korrektur lesen", "Nur Rechtschreibung und Grammatik"]];

// Was in einer gesendeten Mail angezeigt wird, stammt aus dem eigenen Editor -- trotzdem ohne
// Skripte und Ereignis-Attribute, falls etwas Eingefuegtes sie mitbrachte.
function sauber(h) {
  return String(h || "").replace(/<(script|style|iframe|object)[\s\S]*?<\/\1>/gi, "").replace(/\son\w+="[^"]*"/gi, "")
    .replace(/\son\w+='[^']*'/gi, "").replace(/javascript:/gi, "");
}
function teilen(s) { return String(s || "").split(/[,;\n]+/).map((x) => x.trim()).filter(Boolean); }
const gueltig = (a) => /^[^\s@,;<>"]+@[^\s@,;<>"]+\.[^\s@,;<>"]{2,}$/.test(a);

// Neue Mail zu einem Ding aus dem Cockpit -- fuer die Knoepfe "Per Mail" an Ergebnis, Aufgabe, Notiz.
export async function mailZu(bezug) {
  try { const m = await api("/mail", { methode: "POST", daten: { bezug } }); escFensterZu("talk"); navigiere("/mail/" + m.id); }
  catch (e) { fehlerMelden(e); }
}

function EmpfaengerFeld({ wert, setWert, kontakte, platzhalter }) {
  const [tippen, setTippen] = useState("");
  const [auf, setAuf] = useState(false);
  const liste = teilen(wert);
  const q = tippen.trim().toLowerCase();
  const vorschlag = q ? kontakte.filter((k) => (k.name + " " + k.email).toLowerCase().includes(q) && !liste.includes(k.email)).slice(0, 6) : [];
  const dazu = (a) => { const t = a.trim(); if (!t) return; setWert([...liste, t].join(", ")); setTippen(""); };
  const weg = (i) => setWert(liste.filter((_, j) => j !== i).join(", "));
  const name = (a) => (kontakte.find((k) => k.email.toLowerCase() === a.toLowerCase()) || {}).name;
  return html`<div class="ml-empf">
    ${liste.map((a, i) => html`<span class=${"ml-chip" + (gueltig(a) ? "" : " falsch")} title=${gueltig(a) ? a : "Keine gültige Adresse -- steht der Name im Adressbuch?"}>
      ${name(a) ? html`<b>${name(a)}</b> ` : ""}${a}<button onClick=${() => weg(i)} aria-label=${"Entfernen: " + a}>×</button></span>`)}
    <input class="ml-empf-ein" value=${tippen} placeholder=${liste.length ? "" : platzhalter}
      onInput=${(e) => { setTippen(e.target.value); setAuf(true); }}
      onKeyDown=${(e) => {
        if (["Enter", ",", ";", "Tab"].includes(e.key) && tippen.trim()) { e.preventDefault(); dazu(vorschlag.length && !tippen.includes("@") ? vorschlag[0].email : tippen); }
        else if (e.key === "Backspace" && !tippen && liste.length) weg(liste.length - 1);
      }}
      onBlur=${() => setTimeout(() => { setAuf(false); if (tippen.trim()) dazu(tippen); }, 150)} />
    ${auf && vorschlag.length > 0 && html`<div class="ml-vorschlag">${vorschlag.map((k) => html`<button key=${k.id}
      onMouseDown=${(e) => { e.preventDefault(); dazu(k.email); }}><b>${k.name}</b> <span class="leise">${k.email}</span></button>`)}</div>`}
  </div>`;
}

function AnhangWahl({ zu, dazu }) {
  const [q, setQ] = useState("");
  const [t, setT] = useState(null);
  useEffect(() => { const h = setTimeout(() => api("/mail/anhaenge?q=" + encodeURIComponent(q)).then((r) => setT(r.treffer)).catch(fehlerMelden), 200); return () => clearTimeout(h); }, [q]);
  return html`<${Modal} titel="Aus dem Cockpit anhängen" zu=${zu}>
    <input class="eingabe" autofocus placeholder="Ergebnis oder Unterlage suchen …" value=${q} onInput=${(e) => setQ(e.target.value)} />
    <div class="ml-wahl">${t === null ? html`<div class="lade">Suche …</div>` : !t.length ? html`<div class="leise">Nichts gefunden.</div>` :
      t.map((x) => html`<button key=${x.art + x.id} class="ml-wahl-zeile" onClick=${() => { dazu(x); zu(); }}>
        <${Icon} n=${x.art === "ergebnis" ? "briefing" : "clip"} g=${15} /><span class="haupt-text"><b>${x.titel}</b>
        <span class="leise klein">${x.art === "ergebnis" ? "Ergebnis" : "Unterlage"}${x.unter ? " · " + x.unter : ""} · ${zeitText(x.zeit)}</span></span></button>`)}</div>
  </${Modal}>`;
}

function Editor({ id, kontakte, formate, postausgang, nachher }) {
  const [m, setM] = useState(null);
  const [cc, setCc] = useState(false);
  const [ki, setKi] = useState({ laeuft: null, vorschlag: null, anweisung: "" });
  const [wahl, setWahl] = useState(false);
  const [sendenFrage, setSendenFrage] = useState(false);
  const [sendet, setSendet] = useState(false);
  const [diktat, setDiktat] = useState(null);
  const [lade, setLade] = useState(null);
  const feld = useRef(null);
  const zeit = useRef(null);
  const offen = useRef({});
  const bereich = useRef(null);
  const mikroId = useRef("diktat:mail");

  useEffect(() => {
    let weg = false;
    setM(null);
    api("/mail/" + id).then((x) => { if (weg) return; setM(x); setCc(!!(x.cc || x.bcc)); }).catch((e) => { fehlerMelden(e); navigiere("/mail"); });
    return () => { weg = true; jetztSpeichern(); };
  }, [id]);
  useEffect(() => { if (m && feld.current && feld.current.dataset.id !== id) { feld.current.innerHTML = m.html || ""; feld.current.dataset.id = id; } }, [m && m.id]);
  useEffect(() => { if (m) bus.sende("talk-kontext", { art: "mail", id, titel: m.betreff || "Neue Mail" }); }, [id, m && m.betreff]);
  useEffect(() => bus.an("mail-neu-laden", (mid) => { if (mid === id) api("/mail/" + id).then((x) => { setM(x); if (feld.current) feld.current.innerHTML = x.html || ""; }).catch(() => {}); }), [id]);
  useEffect(() => () => { if (diktat) diktat.abbrechen(); }, []);

  function setzen(k, v) {
    setM((x) => ({ ...x, [k]: v }));
    offen.current[k] = v;
    clearTimeout(zeit.current);
    zeit.current = setTimeout(jetztSpeichern, 1200);
  }
  async function jetztSpeichern() {
    clearTimeout(zeit.current);
    const d = offen.current;
    if (!Object.keys(d).length) return;
    offen.current = {};
    try { await api("/mail/" + id, { methode: "POST", daten: d }); nachher(); } catch (e) { fehlerMelden(e); }
  }
  if (!m) return html`<div class="lade">Lade …</div>`;
  const gesendet = m.stand === "gesendet";
  const anh = (m.daten && m.daten.anhaenge) || [];

  function befehl(c, wert) { feld.current && feld.current.focus(); document.execCommand(c, false, wert); setzen("html", feld.current.innerHTML); }
  function link() {
    const sel = window.getSelection();
    const url = prompt("Adresse des Links (https://…)", "https://");
    if (url && /^https?:\/\//.test(url)) { if (sel && String(sel)) befehl("createLink", url); else befehl("insertHTML", `<a href="${url}">${url}</a>`); }
  }
  async function mikro() {
    if (diktat) { const d = diktat; setDiktat(null); try { await d.stopp(); } catch (e) { /* schon gemeldet */ } mikroFreigeben(mikroId.current); return; }
    const g = mikrofonGrund(); if (g) return toast(g, { fehler: true });
    feld.current.focus();
    let bisher = "";
    try {
      mikroAnfordern(mikroId.current, () => { setDiktat((d) => { if (d) d.stopp(); return null; }); });
      const d = await diktieren({ beiText: (fertig) => {
        const neu = fertig.slice(bisher.length);
        if (neu) { document.execCommand("insertText", false, (bisher ? "" : "") + neu); bisher = fertig; setzen("html", feld.current.innerHTML); }
      } });
      setDiktat(d);
    } catch (e) { fehlerMelden(e); mikroFreigeben(mikroId.current); }
  }
  async function formulieren(art) {
    await jetztSpeichern();
    setKi((k) => ({ ...k, laeuft: art, vorschlag: null }));
    try {
      const v = await api("/mail/" + id + "/formulieren", { methode: "POST", daten: { art, anweisung: ki.anweisung } });
      setKi((k) => ({ ...k, laeuft: null, vorschlag: v }));
    } catch (e) { fehlerMelden(e); setKi((k) => ({ ...k, laeuft: null })); }
  }
  function uebernehmen() {
    const v = ki.vorschlag;
    feld.current.innerHTML = v.html;
    setzen("html", v.html);
    if (v.betreff && (!m.betreff || ki.vorschlag.art === "entwurf" || ki.vorschlag.art === "englisch")) setzen("betreff", v.betreff);
    setKi((k) => ({ ...k, vorschlag: null }));
  }
  function anhaengeSetzen(liste) { setzen("anhaenge", liste); setM((x) => ({ ...x, daten: { ...x.daten, anhaenge: liste } })); }
  async function hoch(e) {
    const dateien = [...(e.target.files || [])];
    e.target.value = "";
    let liste = anh;
    for (const f of dateien) {
      setLade({ name: f.name, p: 0 });
      try {
        const r = await hochladen(f, { fortschritt: (p) => setLade({ name: f.name, p }) });
        liste = [...liste, { art: "datei", id: r.id, name: r.name }];
      } catch (x) { fehlerMelden(x); }
    }
    setLade(null);
    anhaengeSetzen(liste);
    jetztSpeichern();
  }
  async function senden() {
    setSendet(true);
    await jetztSpeichern();
    try {
      await api("/mail/" + id + "/senden", { methode: "POST" });
      toast("Gesendet an " + teilen(m.an).join(", ") + ".");
      setSendenFrage(false); nachher(); aktualisieren();
      setM((x) => ({ ...x, stand: "gesendet" }));
    } catch (e) { fehlerMelden(e); setSendenFrage(false); }
    setSendet(false);
  }
  const falsch = [...teilen(m.an), ...teilen(m.cc), ...teilen(m.bcc)].filter((a) => !gueltig(a));

  if (gesendet) {
    return html`<section class="karte ml-gelesen">
      <div class="karte-kopf"><h3>${m.betreff || "(ohne Betreff)"}</h3>
        <button class="btn klein rechts" onClick=${async () => { try { const n = await api("/mail/" + id + "/wiederverwenden", { methode: "POST" }); nachher(); navigiere("/mail/" + n.id); } catch (e) { fehlerMelden(e); } }}>
          <${Icon} n="kopie" g=${13} />Erneut verwenden</button></div>
      <div class="ml-kopfzeilen leise klein"><div><b>An:</b> ${m.an}</div>${m.cc && html`<div><b>Cc:</b> ${m.cc}</div>`}${m.bcc && html`<div><b>Bcc:</b> ${m.bcc}</div>`}
        <div><b>Gesendet:</b> ${new Date(m.gesendet * 1000).toLocaleString("de-DE")}</div></div>
      ${anh.length > 0 && html`<div class="ml-anh">${anh.map((a) => html`<span class="ml-chip"><${Icon} n="clip" g=${12} />${a.name}</span>`)}</div>`}
      <div class="ml-text gelesen" dangerouslySetInnerHTML=${{ __html: sauber(m.html) }}></div>
    </section>`;
  }

  return html`<div class="ml-editor">
    <section class="karte">
      ${m.stand === "fehler" && html`<div class="hinweisbox fehler" style="margin-bottom:10px"><b>Nicht gesendet:</b> ${m.fehler}</div>`}
      ${m.daten.bezug && html`<div class="leise klein" style="margin-bottom:6px">Zu ${({ ergebnis: "Ergebnis", aufgabe: "Aufgabe", notiz: "Notiz", datei: "Unterlage", projekt: "Projekt" })[m.daten.bezug.art]}: <b>${m.daten.bezug.titel}</b></div>`}
      <div class="ml-zeile"><span class="ml-etikett">An</span><${EmpfaengerFeld} wert=${m.an} setWert=${(v) => setzen("an", v)} kontakte=${kontakte} platzhalter="Name aus dem Adressbuch oder Adresse" />
        ${!cc && html`<button class="btn klein geist" onClick=${() => setCc(true)}>Cc/Bcc</button>`}</div>
      ${cc && html`<div class="ml-zeile"><span class="ml-etikett">Cc</span><${EmpfaengerFeld} wert=${m.cc} setWert=${(v) => setzen("cc", v)} kontakte=${kontakte} platzhalter="Kopie an" /></div>
        <div class="ml-zeile"><span class="ml-etikett">Bcc</span><${EmpfaengerFeld} wert=${m.bcc} setWert=${(v) => setzen("bcc", v)} kontakte=${kontakte} platzhalter="Blindkopie an" /></div>`}
      <div class="ml-zeile"><span class="ml-etikett">Betreff</span><input class="eingabe ml-betreff" value=${m.betreff} onInput=${(e) => setzen("betreff", e.target.value)} placeholder="Betreff" /></div>
      <div class="ml-werkzeug" role="toolbar" aria-label="Formatierung">
        ${[["bold", "F", "Fett"], ["italic", "K", "Kursiv"], ["underline", "U", "Unterstrichen"]].map(([c, t, n]) => html`<button class=${"ml-wz " + c} title=${n} aria-label=${n}
          onMouseDown=${(e) => { e.preventDefault(); befehl(c); }}>${t}</button>`)}
        <button class="ml-wz" title="Aufzählung" aria-label="Aufzählung" onMouseDown=${(e) => { e.preventDefault(); befehl("insertUnorderedList"); }}><${Icon} n="liste" g=${15} /></button>
        <button class="ml-wz" title="Nummerierte Liste" aria-label="Nummerierte Liste" onMouseDown=${(e) => { e.preventDefault(); befehl("insertOrderedList"); }}>1.</button>
        <button class="ml-wz" title="Link einfügen" aria-label="Link einfügen" onMouseDown=${(e) => { e.preventDefault(); link(); }}><${Icon} n="extern" g=${14} /></button>
        <button class="ml-wz" title="Formatierung entfernen" aria-label="Formatierung entfernen" onMouseDown=${(e) => { e.preventDefault(); befehl("removeFormat"); }}>T̸</button>
        <span class="ml-wz-trenner"></span>
        <button class=${"ml-wz" + (diktat ? " an" : "")} title=${diktat ? "Diktat beenden" : "Diktieren"} aria-label="Diktieren" onMouseDown=${(e) => { e.preventDefault(); mikro(); }}><${Icon} n="mic" g=${15} /></button>
      </div>
      <div class="ml-text" ref=${feld} contenteditable="true" role="textbox" aria-multiline="true" aria-label="Mailtext"
        data-platzhalter="Schreib hier -- oder lass rechts einen Entwurf formulieren."
        onInput=${() => setzen("html", feld.current.innerHTML)}
        onPaste=${(e) => { const t = e.clipboardData && e.clipboardData.getData("text/plain"); if (t && !e.clipboardData.getData("text/html")) return; }}></div>
      <div class="ml-anh">
        ${anh.map((a, i) => html`<span class="ml-chip" key=${a.art + a.id}><${Icon} n="clip" g=${12} /><span class="ml-chip-name" title=${a.name}>${a.name.replace(/\.[^.]+$/, "")}</span>
          ${a.art === "ergebnis" ? html`<select class="ml-format" value=${a.format} onChange=${(e) => { const l = anh.map((x, j) => j === i ? { ...x, format: e.target.value } : x); anhaengeSetzen(l); }}>
            ${Object.entries(formate).map(([k, n]) => html`<option value=${k}>${n}</option>`)}</select>` : html`<span class="leise">.${(a.name.split(".").pop() || "")}</span>`}
          <button onClick=${() => anhaengeSetzen(anh.filter((_, j) => j !== i))} aria-label=${"Anhang entfernen: " + a.name}>×</button></span>`)}
        ${lade && html`<span class="ml-chip leise">${lade.name} … ${Math.round(lade.p * 100)} %</span>`}
        <button class="btn klein" onClick=${() => setWahl(true)}><${Icon} n="plus" g=${13} />Aus dem Cockpit</button>
        <label class="btn klein"><${Icon} n="clip" g=${13} />Datei hochladen<input type="file" multiple hidden onChange=${hoch} /></label>
      </div>
      <div class="knopfreihe ml-fuss">
        <button class="btn primaer" disabled=${!teilen(m.an).length} onClick=${() => setSendenFrage(true)}><${Icon} n="senden" g=${14} />Senden …</button>
        <span class="leise klein">${postausgang && postausgang.absender ? "Absender: " + postausgang.absender : postausgang && postausgang.fehlt && postausgang.fehlt.length ? "Postausgang: " + postausgang.fehlt.join(", ") : ""} · speichert von selbst</span>
        <button class="btn gefahr klein rechts" onClick=${async () => { try { await api("/mail/" + id, { methode: "DELETE" }); offen.current = {}; nachher(); navigiere("/mail"); toast("Entwurf gelöscht."); } catch (e) { fehlerMelden(e); } }}>Entwurf löschen</button>
      </div>
    </section>
    <section class="karte ml-ki" ref=${bereich}>
      <div class="karte-kopf"><h3>Formulierungshilfe</h3></div>
      <label class="feld"><span>Was soll drinstehen? (optional)</span>
        <${Textfeld} rows="3" value=${ki.anweisung} onInput=${(e) => setKi((k) => ({ ...k, anweisung: e.target.value }))}
          placeholder="z. B. „Kurz zusammenfassen, um Rückmeldung bis Freitag bitten, per du“" /></label>
      <div class="ml-ki-knoepfe">${KI.map(([a, t, n]) => html`<button class=${"btn klein" + (a === "entwurf" ? " primaer" : "")} title=${n}
        disabled=${!!ki.laeuft || (a !== "entwurf" && !(m.html || "").replace(/<[^>]+>/g, "").trim())} onClick=${() => formulieren(a)}>${ki.laeuft === a ? "formuliert …" : t}</button>`)}</div>
      ${ki.laeuft && html`<div class="leise klein" style="margin-top:8px">Das lokale Modell schreibt -- meist 10 bis 30 Sekunden.</div>`}
      ${ki.vorschlag && html`<div class="ml-vorschlag-karte">
        <div class="leise klein">Vorschlag${ki.vorschlag.betreff ? html` · Betreff: <b>${ki.vorschlag.betreff}</b>` : ""}</div>
        <div class="ml-text gelesen" dangerouslySetInnerHTML=${{ __html: sauber(ki.vorschlag.html) }}></div>
        <div class="knopfreihe"><button class="btn primaer klein" onClick=${uebernehmen}><${Icon} n="check" g=${13} />Übernehmen</button>
          <button class="btn klein geist" onClick=${() => setKi((k) => ({ ...k, vorschlag: null }))}>Verwerfen</button></div>
      </div>`}
      <div class="leise klein" style="margin-top:10px">Talk kann hier mitarbeiten: „Formulier das freundlicher“, „häng das Buch an“, „schick sie ab“.</div>
    </section>
    ${wahl && html`<${AnhangWahl} zu=${() => setWahl(false)} dazu=${(x) => { if (!anh.some((a) => a.art === x.art && a.id === x.id)) { anhaengeSetzen([...anh, { art: x.art, id: x.id, name: x.titel, format: "docx" }]); jetztSpeichern(); } }} />`}
    ${sendenFrage && html`<${Modal} titel="Mail senden?" zu=${() => setSendenFrage(false)}
      fuss=${html`<button class="btn" onClick=${() => setSendenFrage(false)}>Abbrechen</button>
        <button class="btn primaer" disabled=${sendet || falsch.length > 0} onClick=${senden}>${sendet ? "Sendet …" : "Jetzt senden"}</button>`}>
      <div class="ml-kopfzeilen"><div><b>An:</b> ${teilen(m.an).join(", ")}</div>${m.cc && html`<div><b>Cc:</b> ${m.cc}</div>`}${m.bcc && html`<div><b>Bcc:</b> ${m.bcc}</div>`}
        <div><b>Betreff:</b> ${m.betreff || "(ohne Betreff)"}</div>${anh.length > 0 && html`<div><b>Anhänge:</b> ${anh.map((a) => a.name).join(", ")}</div>`}</div>
      ${falsch.length > 0 ? html`<div class="hinweisbox fehler" style="margin-top:10px">Diese Empfänger sind keine gültigen Adressen: ${falsch.join(", ")}. Bitte korrigieren oder ins Adressbuch eintragen.</div>`
        : html`<p class="leise klein" style="margin-top:10px">Eine gesendete Mail lässt sich nicht zurückholen. Sie bleibt danach unter „Gesendet“.</p>`}
    </${Modal}>`}
  </div>`;
}

function Adressbuch({ kontakte, nachher }) {
  const [f, setF] = useState({ name: "", email: "", notiz: "" });
  async function speichern() {
    try { await api("/mail/kontakte", { methode: "POST", daten: f }); setF({ name: "", email: "", notiz: "" }); nachher(); toast("Gespeichert."); } catch (e) { fehlerMelden(e); }
  }
  return html`<section class="karte">
    <div class="karte-kopf"><h3>Adressbuch</h3><span class="leise klein">Wer einmal eine Mail bekommen hat, steht hier von selbst.</span></div>
    <div class="ml-kontakt-neu">
      <input class="eingabe" placeholder="Name" value=${f.name} onInput=${(e) => setF({ ...f, name: e.target.value })} />
      <input class="eingabe" placeholder="E-Mail-Adresse" value=${f.email} onInput=${(e) => setF({ ...f, email: e.target.value })} />
      <input class="eingabe" placeholder="Notiz (z. B. „Studentin, per du“)" value=${f.notiz} onInput=${(e) => setF({ ...f, notiz: e.target.value })} />
      <button class="btn primaer" disabled=${!gueltig(f.email.trim())} onClick=${speichern}>Hinzufügen</button>
    </div>
    ${!kontakte.length ? html`<${Leer} titel="Noch leer.">Trag Kontakte ein -- dann reicht in Talk „schick das an Hanna“.</${Leer}>` : html`<div class="ml-kontakte">
      ${kontakte.map((k) => html`<div class="ml-kontakt" key=${k.id}><div class="haupt-text"><b>${k.name}</b> <span class="leise">${k.email}</span>
        ${k.notiz && html`<div class="leise klein">${k.notiz}</div>`}</div>
        <span class="leise klein">${k.anzahl ? k.anzahl + "× angeschrieben" : ""}</span>
        <button class="btn klein" onClick=${async () => { const m = await api("/mail", { methode: "POST", daten: { an: k.email } }); navigiere("/mail/" + m.id); }}>Mail</button>
        <button class="btn klein geist" title="Aus dem Adressbuch entfernen" onClick=${async () => { await api("/mail/kontakte/" + k.id, { methode: "DELETE" }); nachher(); }}><${Icon} n="x" g=${13} /></button></div>`)}</div>`}
  </section>`;
}

export function Mail({ id }) {
  const [d, laden] = useAbruf("/mail", 30000, []);
  const [reiter, setReiter] = useState("entwuerfe");
  useEffect(() => { if (!id) bus.sende("talk-kontext", { art: "mail", id: "alle", titel: "Mail" }); }, [id]);
  useEffect(() => () => bus.sende("talk-kontext", null), []);
  // Eine gesendete Mail geoeffnet (auch aus Talk): links steht dann "Gesendet".
  useEffect(() => { if (d && id) setReiter(d.gesendet.some((x) => x.id === id) ? "gesendet" : d.entwuerfe.some((x) => x.id === id) ? "entwuerfe" : reiter); }, [id, d && d.gesendet.length]);
  if (!d) return html`<div class="seite"><div class="lade">Lade Mail …</div></div>`;
  async function neu() { try { const m = await api("/mail", { methode: "POST", daten: {} }); laden(); navigiere("/mail/" + m.id); } catch (e) { fehlerMelden(e); } }
  const aktuell = id && id !== "adressbuch" ? id : null;
  const liste = reiter === "gesendet" ? d.gesendet : d.entwuerfe;
  return html`<div class="seite dt ml">
    <aside class="dt-liste">
      <button class="btn primaer voll" onClick=${neu}><${Icon} n="plus" g=${15} />Neue Mail</button>
      <div class="ml-reiter" role="tablist">
        ${[["entwuerfe", "Entwürfe", d.entwuerfe.length], ["gesendet", "Gesendet", d.gesendet.length]].map(([k, t, n]) => html`<button role="tab" aria-selected=${reiter === k}
          class=${reiter === k ? "an" : ""} onClick=${() => setReiter(k)}>${t}${n ? html` <span class="leise">${n}</span>` : ""}</button>`)}
        <button class=${id === "adressbuch" ? "an" : ""} onClick=${() => navigiere("/mail/adressbuch")}>Adressbuch</button>
      </div>
      ${!liste.length && html`<${Leer} titel=${reiter === "gesendet" ? "Noch nichts gesendet." : "Keine Entwürfe."}>${reiter === "gesendet" ? "" : "Neue Mail anlegen -- oder an einem Ergebnis, einer Aufgabe oder Notiz „Per Mail“ wählen. Oder Talk sagen: „Schick das Ergebnis an …“"}</${Leer}>`}
      ${liste.map((x) => html`<button key=${x.id} class=${"dt-eintrag" + (x.id === aktuell ? " an" : "")} onClick=${() => navigiere("/mail/" + x.id)}>
        <div class="dt-eintrag-kopf"><b>${x.betreff || "(ohne Betreff)"}</b>${x.stand === "fehler" && html`<span class="pill rot">nicht gesendet</span>`}</div>
        <div class="leise klein">${x.an ? "an " + x.an : "noch kein Empfänger"}${x.anhaenge ? " · " + x.anhaenge + " Anhang" + (x.anhaenge > 1 ? "e" : "") : ""}</div>
        <div class="leise klein">${zeitText(x.gesendet || x.geaendert)}${x.auszug ? " · " + x.auszug : ""}</div>
      </button>`)}
    </aside>
    <div class="dt-haupt">
      ${id === "adressbuch" ? html`<${Adressbuch} kontakte=${d.kontakte} nachher=${laden} />`
        : aktuell ? html`<${Editor} key=${aktuell} id=${aktuell} kontakte=${d.kontakte} formate=${d.formate} postausgang=${d.postausgang} nachher=${laden} />`
        : html`<section class="karte"><${Leer} titel="Mail aus dem Cockpit.">Schreib eine neue Mail, wähle einen Entwurf -- oder sag Talk:
            „Schick das letzte Ergebnis an Hanna, mit einem kurzen freundlichen Text.“ Talk legt den Entwurf an, formuliert ihn und schickt erst auf dein Ja.</${Leer}></section>`}
    </div>
  </div>`;
}
