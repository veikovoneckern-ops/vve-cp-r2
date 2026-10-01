"""
NEO -- der Cockpit Engineer, mit echten Werkzeugen auf dem Server.

Der Werkzeugkreislauf stammt aus Iteration 1 dieses Repos (archiv/iteration-1)
und hat sich dort bewaehrt: Neo liest, schreibt und fuehrt Befehle als
vveadmin aus, sofort, ohne Rueckfrage (Veikos ausdruecklicher Wunsch vom
09.09.2026). Eine kleine Sperrliste bleibt.

Neu gegenueber Iteration 1:
  - GESPRAECHE BLEIBEN. Jede Nachricht und jeder Arbeitsschritt steht in der
    Datenbank (Befund B7: im alten Cockpit verschwanden 10 von 14 Gespraechen).
  - EIN AUFTRAG LAEUFT WEITER, auch wenn der Browser die Seite wechselt oder
    die Verbindung abreisst. Der Browser holt sich die Ereignisse per
    Nachfrage ab (long polling), statt an einem offenen Strom zu haengen.
  - ABBRECHEN geht jederzeit; was bis dahin getan wurde, bleibt sichtbar.
  - VORSCHAU: Neo kann eine Seite in die Vorschau-Spalte legen.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from . import db, llm
from .konfig import MODELL_NEO, UPLOADS, VORSCHAU_DIR, WURZEL

MAX_SCHRITTE = 40
BEFEHL_TIMEOUT = 180
VOLLE_SCHRITTE = 10
NUM_CTX = 65536

GESPERRT = tuple(str(Path(p).expanduser()) for p in (
    "/etc", "/boot", "/sys", "/proc", "/root", "~/.ssh", "/opt/vvec", "/srv/www", "/var/lib/vvec"))
BEFEHL_GESPERRT = re.compile("|".join([
    r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+/(\s|$)", r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(/home|~)\b",
    r"\bmkfs(\.\w+)?\b", r"\bdd\s+.*of=/dev/", r"\b(shutdown|poweroff|halt|reboot)\b",
]), re.I)

WERKZEUGE = [
    {"name": "datei_lesen", "description": "Liest eine Datei (absoluter Pfad oder relativ zum Repo der neuen Fassung ~/vve-cp-r2). Lange Dateien mit 'ab_zeile' abschnittsweise.",
     "parameters": {"type": "object", "properties": {"pfad": {"type": "string"}, "ab_zeile": {"type": "integer"}}, "required": ["pfad"]}},
    {"name": "suche", "description": "Sucht rekursiv nach Text in einem Ordner (grep). Vorgabe: Repo der neuen Fassung.",
     "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "ordner": {"type": "string"}}, "required": ["text"]}},
    {"name": "datei_schreiben", "description": "Schreibt sofort die VOLLSTAENDIGE neue Fassung einer Datei. Erst lesen, dann ersetzen. Gesperrt: Systempfade, /opt/vvec, /srv/www, /var/lib/vvec.",
     "parameters": {"type": "object", "properties": {"pfad": {"type": "string"}, "inhalt": {"type": "string"}, "begruendung": {"type": "string"}}, "required": ["pfad", "inhalt"]}},
    {"name": "datei_kopieren", "description": "Kopiert eine Datei unveraendert, auch Bilder, PDFs und andere Binaerdateien (datei_schreiben kann nur Text). Typisch: ein angehaengtes Bild in den Ordner einer Vorschau-Seite, damit die Seite es zeigen kann. Zielname ohne Leerzeichen waehlen.",
     "parameters": {"type": "object", "properties": {"von": {"type": "string"}, "nach": {"type": "string"}}, "required": ["von", "nach"]}},
    {"name": "befehl_ausfuehren", "description": "Fuehrt einen Shell-Befehl als vveadmin aus (kein sudo-Passwort). Sofort, ohne Rueckfrage, Zeitlimit 180 s. Verkette mit && statt vieler Einzelaufrufe.",
     "parameters": {"type": "object", "properties": {"befehl": {"type": "string"}, "arbeitsverzeichnis": {"type": "string"}}, "required": ["befehl"]}},
    {"name": "vorschau_zeigen", "description": "Zeigt eine HTML-Datei in Veikos Vorschau-Spalte. Die Datei muss unter ~/vve-cp-r2/daten/vorschau/ liegen (z. B. daten/vorschau/entwurf/index.html). Erst mit datei_schreiben anlegen, dann zeigen.",
     "parameters": {"type": "object", "properties": {"pfad": {"type": "string"}}, "required": ["pfad"]}},
    {"name": "dokument_erstellen", "description": "Erstellt ein Dokument zum Herunterladen: format 'docx' (Word), 'pptx' (PowerPoint), 'html' oder 'md'. 'inhalt' ist Markdown (Überschriften mit #, Listen mit -, Tabellen mit |). Bei pptx trennt eine Zeile '---' die Folien. Veiko bekommt einen Download-Knopf. Der EINZIGE Weg zu Word- und PowerPoint-Dateien -- es gibt kein pandoc und kein LibreOffice.",
     "parameters": {"type": "object", "properties": {"titel": {"type": "string"}, "inhalt": {"type": "string"}, "format": {"type": "string", "enum": ["docx", "pptx", "html", "md"]}}, "required": ["titel", "inhalt", "format"]}},
]

# Behauptung ohne Beleg erkennen (Lehre aus dem alten Cockpit, 07.09.2026):
# Neo schrieb "Ich habe die Datei erstellt", ohne ein Werkzeug aufgerufen zu
# haben -- am 01.10.2026 zweimal in der neuen Fassung, mit leerer Vorschau.
BEHAUPTUNG = re.compile(r"\b(habe|hab)\b[^.?!\n]{0,120}\b(erstellt|geschrieben|gebaut|angelegt|erzeugt|exportiert|gespeichert|"
                        r"geändert|aktualisiert|umgesetzt|hochgeladen|gepusht|installiert|eingerichtet|abgelegt)\b", re.I)


def _pfad(p: str) -> Path:
    x = Path(str(p).strip()).expanduser()
    if not x.is_absolute():
        x = WURZEL / x
    return x.resolve()


def _gesperrt(p: Path) -> bool:
    s = str(p)
    return any(s == g or s.startswith(g.rstrip("/") + "/") for g in GESPERRT)


_VERWEIS = re.compile(r"""(?:src|href)\s*=\s*["']([^"'#?]+)|url\(\s*["']?([^"')#?]+)""", re.I)


def _fehlende_verweise(seite: Path) -> list[str]:
    """Relative Verweise einer HTML-Seite (Bilder, CSS, Skripte), die es neben ihr nicht gibt."""
    from urllib.parse import unquote
    try:
        html = seite.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    fehlt = []
    for m in _VERWEIS.finditer(html):
        ref = (m.group(1) or m.group(2) or "").strip()
        if not ref or re.match(r"^(https?:|data:|mailto:|tel:|javascript:|/|//)", ref, re.I):
            continue
        if not (seite.parent / unquote(ref)).exists() and ref not in fehlt:
            fehlt.append(ref)
    return fehlt[:8]


def _kurz(eingabe: dict[str, Any]) -> str:
    teile = []
    for k, v in eingabe.items():
        if k == "inhalt":
            teile.append(f"inhalt=({len(str(v))} Zeichen)")
            continue
        t = str(v).replace("\n", " ")
        teile.append(f"{k}={t[:70]}{'…' if len(t) > 70 else ''}")
    return ", ".join(teile)


async def werkzeug(name: str, e: dict[str, Any], lauf: dict[str, Any]) -> str:
    if name == "datei_lesen":
        try:
            z = _pfad(e.get("pfad", ""))
            zeilen = z.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as f:
            return f"Fehler: {f}"
        ab = max(int(e.get("ab_zeile") or 1), 1)
        stueck = zeilen[ab - 1: ab - 1 + 600]
        text = "\n".join(f"{ab + i}\t{z_}" for i, z_ in enumerate(stueck))
        if ab - 1 + 600 < len(zeilen):
            text += f"\n... [Datei hat {len(zeilen)} Zeilen -- weiter mit ab_zeile={ab + 600}]"
        return text[:20000] or "(leer)"
    if name == "suche":
        ordner = _pfad(e.get("ordner") or str(WURZEL))
        return await _shell(["grep", "-rnI", "--exclude-dir=.git", "--exclude-dir=.venv", "--exclude-dir=node_modules",
                             "-m", "5", e.get("text", ""), str(ordner)], None, liste=True, kappen=6000)
    if name == "datei_schreiben":
        if e.get("inhalt") is None:
            return "Fehler: 'inhalt' fehlt -- schick die vollstaendige Datei."
        z = _pfad(e.get("pfad", ""))
        if _gesperrt(z):
            return f"Fehler: '{z}' ist gesperrt. Release 1 aenderst du ueber das Repo vve-cp, nicht in der laufenden Auslieferung."
        try:
            z.parent.mkdir(parents=True, exist_ok=True)
            z.write_text(str(e["inhalt"]), encoding="utf-8")
        except OSError as f:
            return f"Fehler beim Schreiben: {f}"
        lauf["dateien"].append({"pfad": str(z), "begruendung": e.get("begruendung") or ""})
        return f"Geschrieben: {z} ({len(str(e['inhalt']))} Zeichen)"
    if name == "datei_kopieren":
        von, nach = _pfad(e.get("von", "")), _pfad(e.get("nach", ""))
        if _gesperrt(nach):
            return f"Fehler: '{nach}' ist gesperrt."
        if not von.is_file():
            return f"Fehler: {von} gibt es nicht."
        if nach.is_dir() or str(e.get("nach", "")).endswith("/"):
            nach = nach / von.name.replace(" ", "-")
        try:
            import shutil
            nach.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(von, nach)
        except OSError as f:
            return f"Fehler beim Kopieren: {f}"
        lauf["dateien"].append({"pfad": str(nach), "begruendung": e.get("begruendung") or "kopiert"})
        return f"Kopiert: {von} -> {nach} ({nach.stat().st_size // 1024 + 1} KB)"
    if name == "befehl_ausfuehren":
        befehl = str(e.get("befehl") or "").strip()
        if not befehl:
            return "Fehler: 'befehl' fehlt."
        if BEFEHL_GESPERRT.search(befehl):
            return "Fehler: Dieser Befehl ist gesperrt (Neustart/Abschalten, Formatieren, rekursives Loeschen von / oder ~)."
        cwd = _pfad(e.get("arbeitsverzeichnis") or str(WURZEL))
        if not cwd.is_dir():
            return f"Fehler: Arbeitsverzeichnis {cwd} gibt es nicht."
        return await _shell(befehl, str(cwd))
    if name == "vorschau_zeigen":
        roh = str(e.get("pfad", "")).strip()
        z = _pfad(roh)
        if not z.exists() and not roh.startswith(("/", "~")):
            z = (VORSCHAU_DIR / roh.removeprefix("daten/vorschau/").removeprefix("vorschau/")).resolve()
        if z.is_dir():
            z = z / "index.html"
        if not z.is_file():
            return f"Fehler: {z} gibt es nicht. Erst mit datei_schreiben anlegen (z. B. {VORSCHAU_DIR}/<name>/index.html), dann zeigen."
        try:
            rel = z.relative_to(VORSCHAU_DIR.resolve())
        except ValueError:
            # Liegt woanders (oefter: im Repo oder in /tmp)? Dann samt Nachbardateien
            # in die Vorschau-Ablage kopieren, statt abzulehnen -- eine Ablehnung
            # fuehrte dazu, dass Neo Veiko zur Handarbeit schickte.
            if z.suffix.lower() not in (".html", ".htm"):
                return "Fehler: Die Vorschau zeigt HTML-Seiten. Schreib eine .html-Datei."
            ziel_dir = VORSCHAU_DIR / (z.parent.name or "vorschau")
            ziel_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            for f in z.parent.iterdir():
                if f.is_file() and f.stat().st_size < 5_000_000:
                    shutil.copy2(f, ziel_dir / f.name)
            z = ziel_dir / z.name
            rel = z.relative_to(VORSCHAU_DIR.resolve())
        url = "/api/neo/vorschau/" + str(rel).replace("\\", "/")
        lauf["vorschau"] = url
        await lauf["schlange"].put({"typ": "vorschau", "url": url})
        fehlt = _fehlende_verweise(z)
        if fehlt:
            # Lehre vom 01.10.2026: Neo trug den Namen eines angehaengten Logos ein,
            # ohne es in den Ordner zu kopieren -- die Seite zeigte ein leeres Bild,
            # und Neo meldete "erledigt". Jetzt bekommt er das als Fehler zurueck.
            return (f"Vorschau gezeigt: {url}\nNICHT FERTIG: Die Seite verweist auf Dateien, die im Ordner {z.parent} fehlen: "
                    + ", ".join(fehlt) + ". Kopiere sie mit datei_kopieren dorthin (oder korrigiere den Verweis) und zeig die Seite erneut.")
        return f"Vorschau gezeigt: {url}"
    if name == "dokument_erstellen":
        from . import dokumente
        inhalt = str(e.get("inhalt") or "")
        if len(inhalt.strip()) < 20:
            return "Fehler: 'inhalt' ist leer oder zu kurz. Schick den vollständigen Text als Markdown."
        try:
            ziel = dokumente.erstellen(str(e.get("titel") or "Dokument"), inhalt, str(e.get("format") or "docx"))
        except Exception as f:  # noqa: BLE001
            return f"Fehler beim Erstellen: {f}"
        url = "/api/neo/export/" + ziel.name
        lauf["dateien"].append({"pfad": str(ziel), "begruendung": "zum Herunterladen", "download": url, "name": ziel.name})
        await lauf["schlange"].put({"typ": "datei", "name": ziel.name, "url": url})
        if ziel.suffix == ".html":
            vz = VORSCHAU_DIR / ziel.stem
            vz.mkdir(parents=True, exist_ok=True)
            (vz / "index.html").write_text(ziel.read_text(encoding="utf-8"), encoding="utf-8")
            lauf["vorschau"] = f"/api/neo/vorschau/{ziel.stem}/index.html"
            await lauf["schlange"].put({"typ": "vorschau", "url": lauf["vorschau"]})
        return (f"Erstellt: {ziel.name} ({ziel.stat().st_size // 1024 + 1} KB). Der Download-Knopf erscheint direkt "
                "unter deiner Antwort im Gespräch -- sag Veiko genau das, nichts anderes.")
    return f"Fehler: unbekanntes Werkzeug {name}"


async def _shell(befehl: Any, cwd: str | None, liste: bool = False, kappen: int = 8000) -> str:
    try:
        if liste:
            p = await asyncio.create_subprocess_exec(*befehl, cwd=cwd, stdout=asyncio.subprocess.PIPE,
                                                     stderr=asyncio.subprocess.STDOUT)
        else:
            p = await asyncio.create_subprocess_shell(befehl, cwd=cwd, stdout=asyncio.subprocess.PIPE,
                                                      stderr=asyncio.subprocess.STDOUT, executable="/bin/bash")
    except OSError as f:
        return f"Fehler beim Starten: {f}"
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout=BEFEHL_TIMEOUT)
    except asyncio.TimeoutError:
        p.kill()
        return f"Fehler: lief laenger als {BEFEHL_TIMEOUT} s und wurde abgebrochen."
    text = out.decode("utf-8", "replace")
    if len(text) > kappen:
        text = text[:kappen] + "\n... [gekuerzt]"
    return (f"Exit-Code {p.returncode}\n" if not liste else "") + (text.strip() or "(keine Ausgabe)")


def _kontext_text() -> str:
    datei = WURZEL / "NEO-KONTEXT.md"
    try:
        return datei.read_text(encoding="utf-8")
    except OSError:
        return "Du bist Neo, Cockpit Engineer in Veikos Stab."


def system_text() -> str:
    from .stab import gedaechtnis_text
    return (_kontext_text() +
            f"\n\n## Was über Veiko bekannt ist\n{gedaechtnis_text()}\n\n"
            "## Wie du arbeitest\n"
            "Sieh nach, bevor du etwas behauptest -- nicht raten. datei_schreiben und befehl_ausfuehren wirken SOFORT. "
            "Lies eine Datei, bevor du sie ersetzt. Verkette Befehle mit && statt vieler Einzelaufrufe. "
            f"Bis zu {MAX_SCHRITTE} Werkzeugaufrufe je Auftrag. Nur die letzten {VOLLE_SCHRITTE} Werkzeugergebnisse bleiben dir in voller Länge.\n"
            "\n## Was Veiko häufig will und wie du es lieferst\n"
            "- Ein Dokument (Word, PowerPoint): schreib den vollständigen Inhalt als Markdown und ruf dokument_erstellen auf "
            "(format docx oder pptx). Angehängte Unterlagen liest du vorher mit datei_lesen (Pfad steht in der Nachricht).\n"
            f"- Etwas zum Ansehen (Seite, Entwurf, Übersicht): datei_schreiben nach {VORSCHAU_DIR}/<name>/index.html, dann vorschau_zeigen "
            "mit genau diesem Pfad. vorschau_zeigen ist ein Werkzeug wie jedes andere -- du rufst es selbst auf, Veiko muss nichts tun.\n"
            "- Bilder und andere Dateien für eine Seite: mit datei_kopieren in den Ordner der Seite legen und relativ einbinden. "
            "Meldet vorschau_zeigen „NICHT FERTIG“, fehlt etwas -- beheben und erneut zeigen, erst dann ist es fertig.\n"
            f"- „Mein Logo“ / „das Logo vom Cockpit“: {WURZEL}/frontend/bilder/logo-maske.png (schwarzer Ring auf transparentem Grund, "
            f"198×120) und {WURZEL}/frontend/bilder/favicon.png (der rote Ring). Hängt Veiko eine Datei an, nimm die.\n"
            "- Etwas am Server oder Cockpit prüfen oder ändern: befehl_ausfuehren, datei_lesen, datei_schreiben.\n"
            "\n## Ehrlichkeit\n"
            "Etwas ist erst getan, wenn du das Werkzeug dafür aufgerufen hast und es ohne Fehler zurückkam. "
            "Schreib NIE „ich habe … erstellt“, wenn du in diesem Auftrag kein Werkzeug dafür benutzt hast. "
            "Wenn etwas scheitert, sag das und warum. Beschreib nur, was die Werkzeugergebnisse belegen -- "
            "nicht, was du vorhattest (wer „dein Logo“ schreibt, muss die Datei kopiert haben).\n"
            "\nWenn du fertig bist, antworte Veiko auf Deutsch: zuerst in ein bis zwei Sätzen das Ergebnis, dann was du konkret "
            "getan hast (Dateien, Befehle), dann was er prüfen sollte. Kein Fachbegriff ohne kurze Erklärung. "
            "Schick ihn nie zu Handarbeit, die du selbst erledigen kannst.")


_XML_FN = re.compile(r"<function=([\w-]+)>(.*?)(?:</function>|(?=<function=)|\Z)", re.S)
_XML_PARAM = re.compile(r"<parameter=([\w-]+)>\n?(.*?)\n?(?:</parameter>|(?=<parameter=)|(?=</function>)|\Z)", re.S)


def _xml_aufrufe(text: str) -> tuple[str, list[dict[str, Any]]]:
    """qwen3-coder schreibt Werkzeugaufrufe in seinem eigenen XML-Format
    (<function=name><parameter=x>…</parameter></function>). Bei langen Inhalten
    erkennt Ollama das nicht und reicht es als TEXT durch -- dann passierte
    gar nichts (gemessen am 01.10.2026 mit dokument_erstellen). Hier wird es
    in einen echten Aufruf uebersetzt."""
    if "<function=" not in text:
        return text, []
    aufrufe = []
    bekannte = {w["name"] for w in WERKZEUGE}
    for m in _XML_FN.finditer(text):
        name = m.group(1)
        if name not in bekannte:
            continue
        args = {p.group(1): p.group(2).strip("\n") for p in _XML_PARAM.finditer(m.group(2))}
        aufrufe.append({"function": {"name": name, "arguments": args}})
    vorne = text.split("<function=", 1)[0]
    vorne = re.sub(r"<tool_call>\s*$", "", vorne).strip()
    return vorne, aufrufe


def _gekuerzt(verlauf: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_idx = [i for i, m in enumerate(verlauf) if m.get("role") == "tool"]
    alt = set(tool_idx[:-VOLLE_SCHRITTE]) if len(tool_idx) > VOLLE_SCHRITTE else set()
    out = []
    for i, m in enumerate(verlauf):
        if i in alt and len(m.get("content", "")) > 500:
            m = {**m, "content": m["content"][:500] + "\n... [aus einem älteren Schritt gekürzt]"}
        out.append(m)
    return out


def _vorgeschichte(gid: str, grenze: int = 14) -> list[dict[str, Any]]:
    msgs = db.alle("SELECT rolle, text, daten FROM nachrichten WHERE gespraech_id=? ORDER BY id DESC LIMIT ?", (gid, grenze))
    out = []
    for m in reversed(msgs):
        if m["rolle"] == "du":
            out.append({"role": "user", "content": m["text"]})
        elif m["rolle"] == "neo":
            # Nur der Antworttext -- KEINE Zusammenfassung der Schritte in eckigen
            # Klammern. Das Modell ahmte genau dieses Format nach und schrieb
            # erfundene "Arbeitsschritte" als Text, statt Werkzeuge aufzurufen
            # (gemessen am 01.10.2026: Antwort nach 3 s, kein einziger Schritt).
            text = re.sub(r"\[Deine Arbeitsschritte damals:.*?\]\s*$", "", m["text"] or "", flags=re.S).strip()
            out.append({"role": "assistant", "content": text[:6000]})
    return out


# ---------------------------------------------------------------- Auftraege
JOBS: dict[str, dict[str, Any]] = {}


def laufender_job(gid: str) -> str | None:
    for jid, j in JOBS.items():
        if j["gespraech_id"] == gid and not j["fertig"]:
            return jid
    return None


async def _kern(gid: str, modell: str, lauf: dict[str, Any]) -> None:
    schlange: asyncio.Queue = lauf["schlange"]
    verlauf = _vorgeschichte(gid)
    system = system_text()
    letzter_text = ""
    nachgefragt = 0
    try:
        for _ in range(MAX_SCHRITTE):
            antwort = await llm.chat_mit_werkzeugen(modell, system, _gekuerzt(verlauf),
                                                    [{"type": "function", "function": w} for w in WERKZEUGE],
                                                    num_ctx=NUM_CTX)
            text = (antwort.get("content") or "").strip()
            aufrufe = antwort.get("tool_calls") or []
            if not text and not aufrufe:
                antwort = await llm.chat_mit_werkzeugen(modell, system, _gekuerzt(verlauf),
                                                        [{"type": "function", "function": w} for w in WERKZEUGE],
                                                        num_ctx=NUM_CTX)
                text = (antwort.get("content") or "").strip()
                aufrufe = antwort.get("tool_calls") or []
                if not text and not aufrufe:
                    letzter_text = (letzter_text + "\n\n" if letzter_text else "") + "Das Modell hat auf diesen Schritt nichts geliefert (zweimal versucht)."
                    break
            if not aufrufe and "<function=" in text:
                text, aufrufe = _xml_aufrufe(text)
            verlauf.append({"role": "assistant", "content": text,
                            **({"tool_calls": aufrufe} if aufrufe else {})})
            if text:
                letzter_text = text
                if aufrufe:
                    await schlange.put({"typ": "zwischen", "text": text})
            if not aufrufe:
                # Behauptet, etwas getan zu haben, aber in DIESEM Auftrag kein
                # Werkzeug benutzt? Dann einmal (hoechstens zweimal) zurueckschicken.
                if not lauf["schritte"] and BEHAUPTUNG.search(text) and nachgefragt < 2:
                    nachgefragt += 1
                    await schlange.put({"typ": "zwischen", "text": "(Neo hat etwas behauptet, ohne es getan zu haben. Ich schicke ihn zurück an die Arbeit.)"})
                    verlauf.append({"role": "user", "content":
                                    "Du hast geschrieben, dass du etwas getan hast, aber in diesem Auftrag kein einziges Werkzeug "
                                    "aufgerufen. Es ist also NICHT passiert. Erledige es jetzt wirklich mit den Werkzeugen "
                                    "(z. B. dokument_erstellen, datei_schreiben, vorschau_zeigen, befehl_ausfuehren). "
                                    "Wenn du es nicht kannst, sag ehrlich warum."})
                    continue
                break
            for a in aufrufe:
                fn = a.get("function") or {}
                name = fn.get("name") or ""
                eingabe = fn.get("arguments")
                if isinstance(eingabe, str):
                    try:
                        eingabe = json.loads(eingabe)
                    except ValueError:
                        eingabe = {}
                eingabe = eingabe if isinstance(eingabe, dict) else {}
                await schlange.put({"typ": "schritt_start", "name": name, "kurz": _kurz(eingabe)})
                ergebnis = await werkzeug(name, eingabe, lauf)
                schritt = {"name": name, "kurz": _kurz(eingabe), "ergebnis": ergebnis[:2500], "zeit": time.time()}
                lauf["schritte"].append(schritt)
                await schlange.put({"typ": "schritt", **schritt})
                verlauf.append({"role": "tool", "content": ergebnis})
        else:
            letzter_text += f"\n\nIch habe die Grenze von {MAX_SCHRITTE} Arbeitsschritten erreicht. Sag mir, ob ich weitermachen soll."
    except asyncio.CancelledError:
        letzter_text = (letzter_text + "\n\n" if letzter_text else "") + "Abgebrochen."
        _abschliessen(gid, lauf, letzter_text, modell, abgebrochen=True)
        await schlange.put({"typ": "fertig", "text": letzter_text})
        raise
    except llm.ModellFehler as f:
        letzter_text = (letzter_text + "\n\n" if letzter_text else "") + f"Das lokale Modell hat nicht geliefert: {f}"
    _abschliessen(gid, lauf, letzter_text, modell)
    await schlange.put({"typ": "fertig", "text": letzter_text})


def _abschliessen(gid: str, lauf: dict[str, Any], text: str, modell: str, abgebrochen: bool = False) -> None:
    if lauf.get("gespeichert"):
        return
    lauf["gespeichert"] = True
    # Dieselbe Datei zweimal geschrieben -> einmal nennen (der letzte Stand zaehlt).
    eindeutig: dict[str, Any] = {}
    for f in lauf["dateien"]:
        eindeutig[f.get("download") or f["pfad"]] = f
    lauf["dateien"] = list(eindeutig.values())
    db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                  (gid, "neo", text or "(keine Antwort)", json.dumps({
                      "schritte": lauf["schritte"], "dateien": lauf["dateien"], "vorschau": lauf.get("vorschau"),
                      "modell": modell, "dauer": round(time.time() - lauf["start"]), "abgebrochen": abgebrochen,
                  }, ensure_ascii=False), time.time()))
    db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), gid))


async def senden(gid: str, text: str, anhaenge: list[str]) -> str:
    if laufender_job(gid):
        raise ValueError("Neo arbeitet in diesem Gespräch noch. Warte oder brich ab.")
    voll = text
    namen = []
    for did in anhaenge or []:
        d = db.holen("dateien", did)
        if not d:
            continue
        namen.append(d["name"])
        voll += f"\n\n[Angehängt: {d['name']} -- liegt unter {d['pfad']}]"
        if re.search(r"\.(png|jpe?g|gif|svg|webp|ico)$", d["name"], re.I):
            # Neo kann Bilder nicht ansehen, aber verwenden -- und genau das ging schief.
            sauber = re.sub(r"[^\w.-]+", "-", d["name"]).strip("-").lower()
            voll += (f"\nDas ist ein BILD. Du kannst es nicht ansehen, aber verwenden: Soll es auf eine Seite, kopiere es mit "
                     f"datei_kopieren in den Ordner der Seite (z. B. nach {VORSCHAU_DIR}/<name>/{sauber}) und binde es dort "
                     f"relativ ein (<img src=\"{sauber}\">). Ein Verweis auf den Upload-Pfad funktioniert in der Vorschau NICHT.")
        if d.get("text"):
            voll += f"\nInhalt:\n{d['text'][:20000]}"
    db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                  (gid, "du", voll, json.dumps({"anzeige": text, "anhaenge": namen}, ensure_ascii=False), time.time()))
    g = db.holen("gespraeche", gid)
    if g and (not g.get("titel") or g["titel"] == "Neues Gespräch"):
        db.ausfuehren("UPDATE gespraeche SET titel=? WHERE id=?", (text.strip().splitlines()[0][:70] if text.strip() else "Gespräch", gid))
    team = db.holen("team", "cockpit") or {}
    modell = await llm.modell_waehlen(team.get("modell"), MODELL_NEO, "qwen3-coder:30b", "qwen3.6:27b")
    if not modell:
        raise ValueError("Für Neo ist kein lokales Modell installiert.")
    jid = db.neue_id("j")
    lauf = {"schlange": asyncio.Queue(), "schritte": [], "dateien": [], "start": time.time()}
    job = {"gespraech_id": gid, "ereignisse": [], "fertig": False, "start": time.time(), "modell": modell,
           "lauf": lauf, "neu": asyncio.Event()}

    async def sammler():
        while True:
            e = await lauf["schlange"].get()
            job["ereignisse"].append(e)
            job["neu"].set()
            if e.get("typ") == "fertig":
                job["fertig"] = True
                job["neu"].set()
                break

    async def ausfuehren():
        try:
            await _kern(gid, modell, lauf)
        except asyncio.CancelledError:
            pass
        except Exception as f:  # noqa: BLE001 -- nie einen Auftrag ohne Abschluss haengen lassen
            _abschliessen(gid, lauf, f"Fehler im Ablauf: {f}", modell)
            await lauf["schlange"].put({"typ": "fertig", "text": f"Fehler im Ablauf: {f}"})

    job["sammler"] = asyncio.create_task(sammler())
    job["task"] = asyncio.create_task(ausfuehren())
    JOBS[jid] = job
    # alte, fertige Auftraege nach einer Stunde vergessen
    for alt in [k for k, j in JOBS.items() if j["fertig"] and time.time() - j["start"] > 3600]:
        JOBS.pop(alt, None)
    return jid


async def ereignisse(jid: str, ab: int, warten: float = 20) -> dict[str, Any]:
    job = JOBS.get(jid)
    if not job:
        return {"unbekannt": True, "fertig": True, "ereignisse": [], "naechste": ab}
    if len(job["ereignisse"]) <= ab and not job["fertig"]:
        job["neu"].clear()
        try:
            await asyncio.wait_for(job["neu"].wait(), timeout=warten)
        except asyncio.TimeoutError:
            pass
    ev = job["ereignisse"][ab:]
    return {"ereignisse": ev, "naechste": ab + len(ev), "fertig": job["fertig"], "modell": job["modell"],
            "start": job["start"]}


def abbrechen(jid: str) -> bool:
    job = JOBS.get(jid)
    if not job or job["fertig"]:
        return False
    job["task"].cancel()
    return True


def upload_pfad(name: str) -> Path:
    return UPLOADS / name
