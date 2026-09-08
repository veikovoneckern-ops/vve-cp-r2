# Stand Iteration 2

Stand: 8. September 2026. Gebaut von Claude (dieser Session), auf Veikos Auftrag: Neo soll mit
echten Werkzeugen arbeiten -- lesen, auflisten, durchsuchen, Aenderungen vorschlagen -- statt
einer einzelnen Textantwort mit einem JSON-Block. Iteration 1 war von Grok.

## Laeuft jetzt wirklich auf dem Server

`http://100.65.221.106:8780` (Tailscale-Adresse von `vveorgxais`), als `systemctl --user`-Dienst
(`vve-cp-r2.service`, siehe `systemd/`), uebersteht Neustart dank `loginctl enable-linger`. Getestet
mit dem echten `qwen3.6:27b` auf der 3090 -- zwei echte Gespraeche liefen durch (README
zusammengefasst, Projektsuche mit korrekten Zeilennummern), der Werkzeug-Kreislauf funktioniert
also nicht nur gegen den Test-Ersatz.

## Anmeldung (neu)

Ein Konto, Einrichten/Anmelden/Abmelden/Passwort aendern/Passwort per E-Mail zuruecksetzen. Jeder
API-Aufruf ausser `/`, `/status`, `/static/*`, `/api/konto/*` verlangt eine gueltige Sitzung
(Middleware in `server.py`). Passwoerter mit PBKDF2-HMAC-SHA256 gehasht (Python-Stdlib, kein
Fremdpaket), Sitzungen leben im Speicher (ueberleben also keinen Neustart -- fuer ein persoenliches
Cockpit bewusst in Kauf genommen statt eines Sitzungsspeichers).

**Auf dem Server noch NICHT eingerichtet** -- kein SMTP dort konfiguriert, also noch kein Konto
angelegt. Sobald Veiko SMTP-Zugangsdaten gibt, kommen sie in `~/.config/vve-cp-r2.env` auf dem
Server (siehe README, Abschnitt Anmeldung), der Dienst neu gestartet, dann einmalig im Browser
"Konto einrichten" ausfuellen.

## Was sich in dieser Iteration geaendert hat

- `server.py`: Werkzeug-Kreislauf (`neo_agentenlauf`). Neo bekommt vier Werkzeuge
  (`dateien_auflisten`, `datei_lesen`, `suche`, `datei_schreiben`) und kann sie bis zu
  `VVEC_NEO_MAX_SCHRITTE` (Vorgabe 8) mal hintereinander aufrufen, bevor er antwortet.
  `datei_schreiben` schreibt nichts direkt -- es merkt einen Vorschlag vor, den Veiko im Cockpit
  sieht und erst mit "Einspielen" wirklich schreibt.
- Internes Format ist durchgehend das Claude-Format (Liste aus `{role, content:[Bloecke]}`) --
  derselbe Kunstgriff wie im Release-1-Backend ("Anthropic-Format ist die Innensprache"), damit ein
  zweiter Anbieter sich anschliessen laesst, ohne den Kreislauf zweimal zu bauen.
- **Neo kann wahlweise auf Claude laufen**, nicht nur auf dem lokalen Ollama --
  `VVEC_NEO_ANBIETER=claude` plus `ANTHROPIC_API_KEY` und `VVEC_NEO_CLAUDE_MODELL`. Vorgabe bleibt
  lokal. Ungeprueft von hier (kein Schluessel verfuegbar).
- `/api/neo/einspielen` prueft zusaetzlich die erlaubte Pfadliste (vorher nur Endung/Traversal) und
  meldet abgelehnte Dateien einzeln zurueck.
- `VVEC_HOST` macht die Bind-Adresse einstellbar -- auf dem Server auf die Tailscale-Adresse
  gesetzt, ohne 0.0.0.0 zu binden und ohne Caddy anzufassen.
- Systemd-User-Dienst (`systemd/vve-cp-r2.service`), weil `vveadmin` keine root-Rechte fuer
  `/etc/systemd/system` hat.
- **Anmeldung** komplett neu (siehe oben) -- Auftrag von Veiko, nachdem klar war, dass Cloudflare
  Access (MFA, wie bei Release 1) fuer Release 2 mangels API-Zugang nicht automatisch einzurichten
  ist. Bewusst **ein** Konto, kein Mehrbenutzer-System mit Rollen -- dieses Cockpit ist laut
  Release-1-UEBERGABE.md fuer genau einen Nutzer gebaut, ein zweites Konto haette in einem
  Datenmodell ohne Mandantentrennung (`S.projects`, `S.todos` sind global) keine Wirkung ausser
  einem zweiten Satz Zugangsdaten fuers selbe Cockpit.
- Frontend zeigt aufklappbar, welche Arbeitsschritte Neo fuer eine Antwort gemacht hat.

## Was bewusst NICHT gebaut wurde

- **Kein Shell-Werkzeug fuer Neo.** Nur Dateien lesen/auflisten/durchsuchen/vorschlagen. Echtes
  Schadenspotenzial (loeschen, Netzwerk, Pakete), ohne ausdrueckliche Nachfrage nicht gebaut.
- Kein automatisches `git commit`/`push` nach "Einspielen" -- das bleibt Veikos Schritt.
- **Noch kein Caddy/Cloudflare-Routing fuer eine oeffentliche Adresse.** Veiko wollte urspruenglich
  Internet-Zugriff via `cockpit-v1-r2.vveorgxais.org`; das haette Release 2 ohne Cloudflare Access
  (MFA) offen ins Internet gestellt, weil hier kein Cloudflare-API-Zugang verfuegbar ist, um die
  gleiche Absicherung wie bei Release 1 zu bauen. Veikos Entscheidung: erst die Anmeldung im
  Cockpit selbst bauen (siehe oben), das Caddy/Cloudflare-Routing kommt als naechster Schritt,
  sobald SMTP steht und die Anmeldung auf dem Server eingerichtet ist.
- Der `neo-zweig`/`neo-datei`-Vorschlagsweg aus `AUFTRAG-NEO.md` Abschnitt 6 (GitHub-Zweig direkt
  aus dem Gespraech vorschlagen) ist fuer diesen integrierten Betrieb abgeloest vom
  Werkzeug-Kreislauf; ein Nachtrag am Ende der Datei erklaert das.

## Getestet

1. `python -m py_compile server.py` -- fehlerfrei, auf dem Windows-Rechner (Python 3.12 lokal
   installiert, da vorher keins da war) und auf dem Server (Python 3.14).
2. Server startet ohne Ollama/Anthropic-Schluessel/SMTP; die jeweiligen Endpunkte antworten dann
   mit einer klaren Fehlermeldung statt eines Absturzes oder einer erfundenen Antwort.
3. Werkzeug-Kreislauf, echt im Browser geklickt, gegen einen Test-Ersatz fuer Ollama: Auflisten,
   Lesen, Suchen, ein zu Recht abgelehnter Schreibversuch unter `daten/`, ein angenommener
   Vorschlag, "Einspielen" schreibt die Datei wirklich.
4. Derselbe Werkzeug-Kreislauf gegen das **echte** `qwen3.6:27b` auf dem Server (siehe oben).
5. Anmeldung komplett durchgeklickt: Konto einrichten -> eingeloggt, Abmelden, falsches Passwort
   abgewiesen, richtiges Passwort angenommen, "Passwort vergessen" ohne SMTP meldet den Fehler statt
   eine Mail vorzutaeuschen, mit nicht-registrierter Adresse kommt dieselbe Antwort wie bei einer
   passenden (keine Kontoerkennung von aussen), ein gueltiger Reset-Token setzt das Passwort wirklich
   neu, Anmeldung mit dem neuen Passwort funktioniert, Passwort-Aendern im eingeloggten Zustand
   funktioniert. Alles lokal getestet, Testkonto danach geloescht.
6. Middleware: geschuetzte Endpunkte (`/api/lage`, `/api/dateien`, ...) antworten ohne Sitzung mit
   401, nicht mit leeren Daten.

## Nicht geprueft

- Der Claude-Pfad (`VVEC_NEO_ANBIETER=claude`) -- Code gegen die Anthropic-Messages-API gebaut,
  aber ohne Schluessel von hier aus nicht gegen den echten Dienst gelaufen.
- E-Mail-Versand mit echtem SMTP -- der Fehlerpfad ("kein SMTP eingerichtet") ist geprueft, der
  Erfolgspfad noch nicht, weil keine Zugangsdaten vorliegen.
- Shelly / vve-status
- Reboot-Test des Servers selbst (Linger + systemd --user sollten das Cockpit automatisch wieder
  hochbringen, aber ein echter Neustart des Servers wurde nicht ausgeloest, um den laufenden Betrieb
  nicht zu stoeren).

## Review klicken

1. `http://100.65.221.106:8780` im Tailnet oeffnen -- zeigt "Konto einrichten" (noch kein Konto).
2. Jeder Punkt links, Arbeitsschild oben.
3. Start: Eingabefeld, Satz an Neo -- z. B. "Lies dir server.py an und sag, was auffaellt."
4. Neo sollte zuerst lesen (sichtbar an "N Arbeitsschritt(e)"), erst danach antworten.
5. Nutzerverwaltung: Passwort aendern, Abmelden -- danach wieder die Login-Maske.
6. Server: Vollflaeche, nicht verfuegbar wo nichts gemessen wird.
