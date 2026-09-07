# Stand Iteration 2

Stand: 7. September 2026. Gebaut von Claude (dieser Session), auf Veikos Auftrag: Neo soll mit
echten Werkzeugen arbeiten -- lesen, auflisten, durchsuchen, Aenderungen vorschlagen -- statt
einer einzelnen Textantwort mit einem JSON-Block. Iteration 1 war von Grok.

## Was sich geaendert hat

- `server.py`: neuer Werkzeug-Kreislauf (`neo_agentenlauf`). Neo bekommt vier Werkzeuge
  (`dateien_auflisten`, `datei_lesen`, `suche`, `datei_schreiben`) und kann sie bis zu
  `VVEC_NEO_MAX_SCHRITTE` (Vorgabe 8) mal hintereinander aufrufen, bevor er antwortet.
  `datei_schreiben` schreibt nichts direkt -- es merkt einen Vorschlag vor, den Veiko im Cockpit
  sieht und erst mit "Einspielen" wirklich schreibt. Dieselbe Sicherung wie in Iteration 1.
- Internes Format ist jetzt durchgehend das Claude-Format (Liste aus `{role, content:[Bloecke]}`) --
  derselbe Kunstgriff wie im Release-1-Backend ("Anthropic-Format ist die Innensprache"), damit ein
  zweiter Anbieter sich anschliessen laesst, ohne den Kreislauf zweimal zu bauen.
- **Neo kann jetzt wahlweise auf Claude laufen**, nicht nur auf dem lokalen Ollama --
  `VVEC_NEO_ANBIETER=claude` plus `ANTHROPIC_API_KEY` und `VVEC_NEO_CLAUDE_MODELL`. Vorgabe bleibt
  lokal. Das war Veikos ausdruecklicher Wunsch: "Neo soll so funktionieren wie Du."
- `/api/neo/einspielen` prueft jetzt zusaetzlich die erlaubte Pfadliste (vorher nur Endung/Traversal)
  und meldet abgelehnte Dateien einzeln zurueck, statt sie stillschweigend zu ignorieren.
- Frontend zeigt aufklappbar, welche Arbeitsschritte Neo fuer eine Antwort gemacht hat.
- `README.md`, `anforderungen/AUFTRAG-NEO.md`, `anforderungen/NEO-KONTEXT.md` nachgezogen.

## Was bewusst NICHT gebaut wurde

- **Kein Shell-Werkzeug.** Neo kann keine Befehle ausfuehren, nur Dateien lesen/auflisten/
  durchsuchen/vorschlagen. Das war die groesste offene Frage bei "soll arbeiten wie Du" -- ein
  Shell-Zugriff waere ein grosser Schritt mit echtem Schadenspotenzial (loeschen, Netzwerk,
  Pakete). Ohne ausdrueckliche Nachfrage nicht gebaut. Wenn gewuenscht: eigener, klein geschnittener
  Auftrag.
- Kein automatisches `git commit`/`push` nach "Einspielen". Die Datei wird geschrieben, den Rest
  (git add/commit/push) macht Veiko weiter selbst -- Iteration 2 sollte "die reinen Funktionalitaeten
  von Neo" liefern, keine Deployment-Automatik obendrauf.
- Der `neo-zweig`/`neo-datei`-Vorschlagsweg aus `AUFTRAG-NEO.md` Abschnitt 6 (GitHub-Zweig direkt
  aus dem Gespraech vorschlagen) ist damit nicht mehr der Weg fuer Dateiaenderungen -- der ist jetzt
  der Werkzeug-Kreislauf oben. Abschnitt 6 bleibt in der Datei stehen und dokumentiert, warum ein
  reiner Text-Ansatz an Escaping scheiterte; ein Nachtrag am Ende der Datei sagt das.

## Getestet, aber nicht auf Veikos Server

Von hier aus kein Zugriff auf `vveorgxais` (Ollama, Anthropic-Schluessel). Getestet auf dem
Windows-Rechner mit lokal installiertem Python 3.12 und einem Test-Ersatz fuer Ollama, der eine
feste Folge von Werkzeugaufrufen zurueckgibt:

1. `python -m py_compile server.py` -- fehlerfrei.
2. Server startet ohne Ollama und ohne Anthropic-Schluessel; `/api/gespraech` antwortet dann mit
   einer klaren 503-Meldung statt eines Absturzes oder einer erfundenen Antwort.
3. Voller Werkzeug-Kreislauf gegen den Test-Ersatz, **echt im Browser geklickt**: Neo listet
   `frontend/`, liest `README.md`, durchsucht das Projekt nach "Iteration", versucht einmal (zu
   Recht abgelehnt) nach `daten/` zu schreiben, schlaegt dann `doku/test-neo.md` vor. Die Antwort
   zeigt "5 Arbeitsschritt(e)" aufklappbar, der Dateivorschlag erscheint, "Einspielen" schreibt die
   Datei wirklich auf die Platte. Testdatei danach geloescht.
4. Alle bestehenden Endpunkte (`/api/dateien`, `/api/datei`, `/api/einstellungen`, `/api/rollen`,
   `/api/lage`, `/`, `/static/app.js`) laufen unveraendert weiter.

## Nicht geprueft (kein Zugriff auf Veikos Server von hier)

- Ollama `qwen3.6:27b` auf der 3090 -- insbesondere, ob dieses Modell in dieser Ollama-Version
  wirklich Werkzeugaufrufe unterstuetzt. Qwen-3-Modelle koennen das laut Kartenbeschreibung, aber
  ungeprueft ist ungeprueft.
- Der Claude-Pfad (`VVEC_NEO_ANBIETER=claude`) -- Code ist geschrieben und gegen die
  Anthropic-Messages-API gebaut, aber ohne Schluessel von hier aus nicht gegen den echten Dienst
  gelaufen.
- Shelly / vve-status
- Subdomain cockpit-v1-r2

## Review klicken

1. Jeder Punkt links, Arbeitsschild oben
2. Einstellungen: Schrift 16/18/20, Hell und Dunkel
3. Start: Eingabefeld hoch, Satz an Neo -- z. B. "Lies dir server.py an und sag, was auffaellt."
4. Neo sollte zuerst lesen (sichtbar an "N Arbeitsschritt(e)"), erst danach antworten
5. Server: Vollflaeche, nicht verfuegbar wo nichts gemessen wird
6. Vorschlag von Neo erst nach Einspielen in den Dateien; abgelehnte Pfade werden benannt
