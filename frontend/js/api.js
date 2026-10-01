// Ein Weg zum Server. Alle Pfade relativ -- nie einen Hostnamen eintragen,
// sonst funktioniert das Cockpit nur ueber einen Zugangsweg.

export class ApiFehler extends Error {
  constructor(text, status) { super(text); this.status = status; }
}

export async function api(pfad, { methode = "GET", daten } = {}) {
  let r;
  try {
    r = await fetch("/api" + pfad, {
      method: methode,
      credentials: "same-origin",
      headers: daten !== undefined ? { "Content-Type": "application/json" } : {},
      body: daten !== undefined ? JSON.stringify(daten) : undefined,
    });
  } catch (e) {
    throw new ApiFehler("Server nicht erreichbar. Netz weg oder Dienst neu gestartet?", 0);
  }
  if (r.status === 401 && !pfad.startsWith("/konto/")) {
    window.dispatchEvent(new CustomEvent("vvec-abgemeldet"));
  }
  const typ = r.headers.get("content-type") || "";
  const inhalt = typ.includes("json") ? await r.json().catch(() => ({})) : await r.text();
  if (!r.ok) {
    const text = typeof inhalt === "object" ? (inhalt.detail || JSON.stringify(inhalt)) : String(inhalt).slice(0, 200);
    throw new ApiFehler(typeof text === "string" ? text : JSON.stringify(text), r.status);
  }
  return inhalt;
}

// NDJSON-Strom lesen (Talk). Ruft fuer jede Zeile beiZeile(objekt) auf.
export async function strom(pfad, daten, beiZeile, signal) {
  const r = await fetch("/api" + pfad, {
    method: "POST", credentials: "same-origin", signal,
    headers: { "Content-Type": "application/json" }, body: JSON.stringify(daten),
  });
  if (!r.ok) {
    const t = await r.json().catch(() => ({}));
    throw new ApiFehler(t.detail || `Fehler ${r.status}`, r.status);
  }
  const leser = r.body.getReader();
  const dek = new TextDecoder();
  let puffer = "";
  for (;;) {
    const { value, done } = await leser.read();
    if (done) break;
    puffer += dek.decode(value, { stream: true });
    let i;
    while ((i = puffer.indexOf("\n")) >= 0) {
      const zeile = puffer.slice(0, i).trim();
      puffer = puffer.slice(i + 1);
      if (zeile) { try { beiZeile(JSON.parse(zeile)); } catch (e) { /* halbe Zeile */ } }
    }
  }
}

// Hochladen mit Fortschritt. XMLHttpRequest statt fetch: fetch meldet beim
// Senden nichts, und bei 20 MB ueber das Tailnet ist das der Unterschied
// zwischen "es passiert etwas" und "es haengt".
export function hochladen(datei, { projekt_id = "", fortschritt } = {}) {
  return new Promise((ok, nein) => {
    const fd = new FormData();
    fd.append("datei", datei, datei.name || "datei");
    const x = new XMLHttpRequest();
    x.open("POST", "/api/dateien" + (projekt_id ? "?projekt_id=" + encodeURIComponent(projekt_id) : ""));
    x.withCredentials = true;
    if (fortschritt) x.upload.onprogress = (e) => { if (e.lengthComputable) fortschritt(e.loaded / e.total); };
    x.onload = () => {
      let d = {};
      try { d = JSON.parse(x.responseText); } catch (e) { /* leer */ }
      if (x.status >= 200 && x.status < 300) ok(d); else nein(new ApiFehler(d.detail || `Hochladen fehlgeschlagen (${x.status})`, x.status));
    };
    x.onerror = () => nein(new ApiFehler("Hochladen fehlgeschlagen: Server nicht erreichbar", 0));
    x.send(fd);
  });
}
