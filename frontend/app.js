(function () {
  "use strict";
  const ORTE = [
    { id: "start", name: "Start" },
    { id: "themen", name: "Themen" },
    { id: "stab", name: "Stab" },
    { id: "eingang", name: "Eingang" },
    { id: "reports", name: "Reports" },
    { id: "server", name: "Server" },
    { id: "einstellungen", name: "Einstellungen" }
  ];
  const S = {
    ort: "start",
    einstellungen: { thema: "dunkel", schrift_fluss: 18, schrift_neben: 16, schrift_nav: 15, schrift_eingabe: 18 },
    lage: null, rollen: null, server: null, lauf: "kein Lauf", logoLaeuft: false,
    verlauf: [], vorschlag: null, eingabe: "", fehler: ""
  };
  function $(sel, wurzel) { return (wurzel || document).querySelector(sel); }
  function esc(text) {
    return String(text == null ? "" : text).replace(/&/g, "&").replace(/</g, "<").replace(/>/g, ">");
  }
  async function api(pfad, opt) {
    const antwort = await fetch(pfad, opt);
    const roh = await antwort.text();
    let paket = null;
    try { paket = roh ? JSON.parse(roh) : null; } catch (e) { paket = { detail: roh }; }
    if (!antwort.ok) {
      const detail = paket && paket.detail ? paket.detail : antwort.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return paket;
  }
  function schriftAnwenden() {
    const w = document.documentElement;
    w.dataset.thema = S.einstellungen.thema === "hell" ? "hell" : "dunkel";
    w.style.setProperty("--fluss", S.einstellungen.schrift_fluss + "px");
    w.style.setProperty("--neben-px", S.einstellungen.schrift_neben + "px");
    w.style.setProperty("--nav-px", S.einstellungen.schrift_nav + "px");
    w.style.setProperty("--eingabe-px", S.einstellungen.schrift_eingabe + "px");
  }
  function schildText() { return S.fehler || S.lauf; }
  function zeichnen() {
    schriftAnwenden();
    const app = document.getElementById("app");
    const voll = S.ort === "server";
    app.innerHTML = leisteHtml() +
      '<section class="schild"><div class="lauf">' + esc(schildText()) +
      '</div><div class="ort">' + esc(ORTE.find(function (o) { return o.id === S.ort; }).name) +
      '</div></section><main class="inhalt' + (voll ? " voll" : "") + '" id="view"></main>';
    const logo = $("#logo");
    if (logo) logo.classList.toggle("laeuft", S.logoLaeuft);
    document.querySelectorAll("[data-ort]").forEach(function (knopf) {
      knopf.addEventListener("click", function () { ortWechseln(knopf.getAttribute("data-ort")); });
    });
    const view = document.getElementById("view");
    if (S.ort === "start") view.innerHTML = startHtml();
    else if (S.ort === "stab") view.innerHTML = stabHtml();
    else if (S.ort === "server") view.innerHTML = serverHtml();
    else if (S.ort === "einstellungen") view.innerHTML = einstellungenHtml();
    else view.innerHTML = leerHtml();
    anhaengen();
  }
  function leisteHtml() {
    const knoepfe = ORTE.map(function (ort) {
      return '<button type="button" data-ort="' + ort.id + '"' +
        (ort.id === S.ort ? ' class="aktiv"' : "") + ">" + esc(ort.name) + "</button>";
    }).join("");
    return '<nav class="leiste"><div class="marke"><div class="logo" id="logo" aria-hidden="true"></div>' +
      "<div><strong>VVE Cockpit</strong><span>Release 2</span></div></div>" + knoepfe + "</nav>";
  }
  function startHtml() {
    const lage = S.lage || {};
    const karten = karte("Seit du weg warst", lage.seit_weg || "Lage wird gelesen.") +
      karte("Bewegte Projekte", leerListe(lage.projekte, "Noch kein bewegtes Projekt in diesem Release.")) +
      karte("Gerade in Arbeit", leerListe(lage.in_arbeit, "Nichts in Arbeit. Hoechstens drei gleichzeitig."));
    const blasen = S.verlauf.map(function (eintrag) {
      return '<div class="blase' + (eintrag.wer === "veiko" ? " ich" : "") + '">' +
        '<div class="wer">' + esc(eintrag.wer) + "</div><div>" + esc(eintrag.text) + "</div></div>";
    }).join("");
    let vorschlag = "";
    if (S.vorschlag && S.vorschlag.length) {
      const zeilen = S.vorschlag.map(function (d) {
        return "<div><code>" + esc(d.pfad) + "</code> — " + esc(d.begruendung || "Aenderung") + "</div>";
      }).join("");
      vorschlag = '<div class="vorschlag"><h2>Neo schlaegt Dateien vor</h2>' + zeilen +
        '<div class="zeile" style="margin-top:10px">' +
        '<button type="button" class="primaer" id="btn-einspielen">Einspielen</button>' +
        '<button type="button" class="gefahr" id="btn-verwerfen">Verwerfen</button></div></div>';
    }
    return "<h1>Lage</h1><p class=\"leise\">Gespraech mit Neo. Andere Rollen kommen in der naechsten Stufe.</p>" +
      '<div class="karten">' + karten + '</div><div class="gespraech">' +
      '<div class="verlauf">' + (blasen || '<p class="leise">Noch kein Gespraech in dieser Sitzung.</p>') + "</div>" +
      vorschlag + '<div class="eingabe-box"><textarea id="feld" placeholder="Was soll Neo an der Loesung aendern oder erklaeren?">' +
      esc(S.eingabe) + '</textarea><div class="zeile" style="margin-top:8px">' +
      '<button type="button" class="primaer" id="btn-senden">An Neo</button>' +
      '<button type="button" class="neben" id="btn-abbruch">Unterbrechen</button></div></div></div>';
  }
  function karte(titel, text) {
    return '<article class="karte"><h2>' + esc(titel) + "</h2><p>" + esc(text) + "</p></article>";
  }
  function leerListe(arr, leer) { return (!arr || !arr.length) ? leer : arr.join(", "); }
  function stabHtml() {
    const daten = S.rollen || {};
    const lokal = (daten.lokal || []).map(function (r) {
      return '<div class="mitglied' + (r.aktiv ? " aktiv" : "") + '"><strong>' + esc(r.name) +
        '</strong><div class="amt">' + esc(r.titel) + (r.aktiv ? " — arbeitet" : " — noch nicht") + "</div></div>";
    }).join("");
    const extern = (daten.extern || []).map(function (r) {
      return '<div class="mitglied"><strong>' + esc(r.name) +
        '</strong><div class="amt">' + esc(r.anbieter) + " — extern</div></div>";
    }).join("");
    return "<h1>Stab</h1><p class=\"leise\">Org-Chart Iteration 1: sichtbar. Ziehen kommt in Stufe 3.</p>" +
      '<h2>Lokal</h2><div class="team">' + lokal + '</div><h2 style="margin-top:18px">Extern</h2><div class="team">' + extern + "</div>";
  }
  function serverHtml() {
    const s = S.server || {};
    function wert(name, key) {
      return '<div class="wert"><small>' + esc(name) + "</small>" + esc(s[key] || "nicht verfuegbar") + "</div>";
    }
    return '<div class="server"><section class="streifen"><h2>Lage</h2><div class="werte">' +
      wert("Dienste", "dienste") + wert("Strom Server", "strom_server") +
      wert("Strom Dock", "strom_dock") + wert("Temperatur", "temperatur") +
      '</div></section><section class="streifen"><h2>Arbeit</h2><div class="werte">' +
      wert("Modell", "modell") + wert("Jobs", "jobs") + wert("Quelle", "quelle") +
      '</div></section><section class="streifen"><h2>Bestand</h2>' +
      '<p class="leise">Updates und gefaehrliche Aktionen liegen hier spaeter. Nichts simuliert.</p></section></div>';
  }
  function einstellungenHtml() {
    const e = S.einstellungen;
    function range(id, label, wert) {
      return '<div class="form-reihe"><label for="' + id + '">' + esc(label) + " — " + wert + " px</label>" +
        '<input id="' + id + '" type="range" min="14" max="24" step="1" value="' + wert + '"></div>';
    }
    return "<h1>Einstellungen</h1><p class=\"leise\">Gilt sofort und bleibt unter daten/einstellungen.json.</p>" +
      range("schrift_fluss", "Fliesstext", e.schrift_fluss) +
      range("schrift_neben", "Nebenzellen", e.schrift_neben) +
      range("schrift_nav", "Navigation", e.schrift_nav) +
      range("schrift_eingabe", "Eingabefeld", e.schrift_eingabe) +
      '<div class="form-reihe"><label>Darstellung</label><div class="zeile">' +
      '<button type="button" class="neben" data-thema="dunkel">Dunkel</button>' +
      '<button type="button" class="neben" data-thema="hell">Hell</button></div></div>';
  }
  function leerHtml() {
    const texte = {
      themen: "Noch keine Projekte in diesem Release. Der Abzug kommt nach dem Review.",
      eingang: "Noch keine unzugeordneten Notizen hier. Ziehen auf Projekte folgt, sobald Notizen liegen.",
      reports: "Noch keine Messreihe. Reports zeigen nur Werte, die wirklich anfallen."
    };
    return "<h1>" + esc(ORTE.find(function (o) { return o.id === S.ort; }).name) +
      "</h1><p class=\"leise\">" + esc(texte[S.ort] || "") + "</p>";
  }
  function anhaengen() {
    const feld = $("#feld");
    if (feld) {
      feld.addEventListener("input", function () { S.eingabe = feld.value; });
      feld.addEventListener("keydown", function (ev) {
        if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") senden();
      });
    }
    const sendenBtn = $("#btn-senden");
    if (sendenBtn) sendenBtn.addEventListener("click", senden);
    const abbruch = $("#btn-abbruch");
    if (abbruch) abbruch.addEventListener("click", unterbrechen);
    const ein = $("#btn-einspielen");
    if (ein) ein.addEventListener("click", einspielen);
    const weg = $("#btn-verwerfen");
    if (weg) weg.addEventListener("click", function () { S.vorschlag = null; zeichnen(); });
    document.querySelectorAll("[data-thema]").forEach(function (knopf) {
      knopf.addEventListener("click", function () {
        S.einstellungen.thema = knopf.getAttribute("data-thema");
        speichernEinstellungen();
        zeichnen();
      });
    });
    ["schrift_fluss", "schrift_neben", "schrift_nav", "schrift_eingabe"].forEach(function (id) {
      const el = document.getElementById(id);
      if (!el) return;
      el.addEventListener("change", function () {
        S.einstellungen[id] = Number(el.value);
        speichernEinstellungen();
        zeichnen();
      });
    });
  }
  let steuer = null;
  async function senden() {
    const text = (S.eingabe || "").trim();
    if (!text || S.logoLaeuft) return;
    S.verlauf.push({ wer: "veiko", text: text });
    S.eingabe = ""; S.fehler = ""; S.vorschlag = null;
    S.logoLaeuft = true; S.lauf = "Neo liest den Auftrag …"; zeichnen();
    steuer = new AbortController();
    try {
      const antwort = await fetch("/api/gespraech", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text, an: "neo" }), signal: steuer.signal
      });
      const paket = await antwort.json();
      if (!antwort.ok) throw new Error(paket.detail || "Neo-Fehler");
      S.verlauf.push({ wer: paket.wer || "neo", text: paket.text || "" });
      S.vorschlag = paket.dateien || [];
      S.lauf = paket.lauf || "fertig";
    } catch (err) {
      if (err.name === "AbortError") {
        S.lauf = "unterbrochen";
        S.verlauf.push({ wer: "cockpit", text: "Lauf unterbrochen." });
      } else {
        S.fehler = String(err.message || err);
        S.lauf = "Neo nicht erreichbar";
        S.verlauf.push({ wer: "cockpit", text: S.fehler });
      }
    } finally {
      S.logoLaeuft = false; steuer = null; zeichnen();
    }
  }
  function unterbrechen() {
    if (steuer) steuer.abort();
    S.logoLaeuft = false; S.lauf = "unterbrochen"; zeichnen();
  }
  async function einspielen() {
    if (!S.vorschlag || !S.vorschlag.length) return;
    S.lauf = "Veiko spielt ein …"; S.logoLaeuft = true; zeichnen();
    try {
      const paket = await api("/api/neo/einspielen", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dateien: S.vorschlag })
      });
      S.lauf = "eingespielt: " + (paket.geschrieben || []).join(", ");
      S.vorschlag = null;
      S.verlauf.push({ wer: "cockpit", text: S.lauf });
    } catch (err) {
      S.fehler = String(err.message || err);
      S.lauf = "Einspielen fehlgeschlagen";
    } finally {
      S.logoLaeuft = false; zeichnen();
    }
  }
  async function speichernEinstellungen() {
    schriftAnwenden();
    try {
      S.einstellungen = await api("/api/einstellungen", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(S.einstellungen)
      });
    } catch (err) { S.fehler = String(err.message || err); }
  }
  async function ortWechseln(id) {
    S.ort = id;
    S.lauf = S.logoLaeuft ? S.lauf : "kein Lauf";
    if (id === "server") {
      try { S.server = await api("/api/server"); } catch (e) { S.server = null; }
    }
    if (id === "stab" && !S.rollen) {
      try { S.rollen = await api("/api/rollen"); } catch (e) { S.rollen = { lokal: [], extern: [] }; }
    }
    zeichnen();
  }
  async function start() {
    try { S.einstellungen = await api("/api/einstellungen"); } catch (e) {}
    try { S.lage = await api("/api/lage"); } catch (e) {}
    try { S.rollen = await api("/api/rollen"); } catch (e) {}
    zeichnen();
  }
  start();
})();
