// MASCHINE (bis 17.10.2026 "System") -- alles zum Server an einem Ort: oben die
// Server-Sektion (Aufbau, Updates, Sicherungen, Software, Messwerte), darunter
// der WatchDog (Temperatur, Notabschaltung, Sicherheit). Die Kaestchen in der
// Kopfzeile fuehren hierher.
//
// Neu geordnet (Veiko, 17.10.2026: "viele Punkte zu System und Setup sind auf
// unterschiedliche Ansichten verteilt"): der WatchDog hatte eine eigene Seite mit
// einer zweiten Kopie von Aufbau und Wartung; Team-Pipeline, Daten und Konto
// stehen jetzt unter Einstellungen, Modelle und Verbrauch unter Stab & Modelle.
// Die Kennung bleibt "system", damit alte Links und die Kopfzeile weiter passen.
import { html, useEffect, bus } from "./ui.js";
import { ServerSektion } from "./server.js";
import { WatchDog } from "./watchdog.js";

export function System({ gesundheit }) {
  useEffect(() => { bus.sende("talk-kontext", null); }, []);
  return html`<div class="seite">
    <${ServerSektion} gesundheit=${gesundheit} />
    <div class="sv-gruppe maschine-wd"><b>WatchDog</b><em>Temperatur, Notabschaltung und Sicherheit -- läuft unabhängig vom Cockpit</em></div>
    <${WatchDog} eingebettet=${true} />
  </div>`;
}
