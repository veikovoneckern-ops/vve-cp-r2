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
    """Verweise einer HTML-Seite (Bilder, CSS, Skripte), die in der Vorschau ins
    Leere gehen: relative, die es neben ihr nicht gibt, und Pfade auf der
    Platte des Servers (/home/..., file:...), die der Browser nie erreicht."""
    from urllib.parse import unquote
    try:
        html = seite.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    fehlt = []
    for m in _VERWEIS.finditer(html):
        ref = (m.group(1) or m.group(2) or "").strip()
        if not ref or ref in fehlt:
            continue
        if _platten_pfad(ref):
            fehlt.append(ref)
            continue
        if re.match(r"^(https?:|data:|mailto:|tel:|javascript:|/|//)", ref, re.I):
            continue
        if not (seite.parent / unquote(ref)).exists():
            fehlt.append(ref)
    return fehlt[:8]


def _platten_pfad(ref: str) -> bool:
    return bool(re.match(r"^(file:|/home/|/tmp/|/var/|~/)", ref, re.I) or "daten/uploads/" in ref)


def _sauber(name: str) -> str:
    return re.sub(r"[^\w.-]+", "-", name).strip("-").lower()


_ANHANG = re.compile(r"\[Angehängt: (.+?) -- liegt unter (.+?)\]")


def anhaenge_im_gespraech(gid: str) -> list[dict[str, Any]]:
    """Alle Dateien, die Veiko in diesem Gespraech angehaengt hat -- aus dem Text
    der Nachrichten, damit auch alte Anhaenge zaehlen (die Kennzeichnung steht
    dort seit dem ersten Tag). Lehre vom 01.10.2026: das Logo hing zehn
    Nachrichten zurueck, Neo hatte es aus dem Blick verloren und zeichnete
    zweimal einen Farbkreis mit "V" statt Veikos Logo."""
    out: dict[str, dict[str, Any]] = {}
    for m in db.alle("SELECT text FROM nachrichten WHERE gespraech_id=? AND rolle='du' ORDER BY id", (gid,)):
        for name, pfad in _ANHANG.findall(m["text"] or ""):
            pfad = pfad.strip()
            if Path(pfad).is_file():
                out.pop(pfad, None)  # juengste Erwaehnung zuletzt
                out[pfad] = {"name": name.strip(), "pfad": pfad, "sauber": _sauber(name),
                             "bild": bool(re.search(r"\.(png|jpe?g|gif|svg|webp|ico)$", name, re.I))}
    return list(out.values())


def _verweise_reparieren(seite: Path, anhaenge: list[dict[str, Any]]) -> list[str]:
    """Zeigt die Seite auf einen Anhang, der nicht neben ihr liegt (Name aus dem
    Upload, mit oder ohne Kennung davor, oder gleich der Upload-Pfad), dann legt
    das Cockpit ihn selbst daneben. Das ist kein Raten: welche Datei gemeint
    ist, steht eindeutig im Verweis. Ohne eindeutigen Treffer bleibt der
    Verweis als Fehler stehen."""
    from urllib.parse import unquote
    import shutil
    if not anhaenge:
        return []
    try:
        html = seite.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    getan, neu = [], html
    for ref in _fehlende_verweise(seite):
        roh = unquote(ref)
        basis = Path(roh.replace("file://", "")).name.lower()
        treffer = None
        for a in anhaenge:
            auf_platte = Path(a["pfad"]).name.lower()
            if basis in (auf_platte, a["name"].lower(), a["sauber"], auf_platte.split("_", 1)[-1]):
                treffer = a
                break
        if not treffer:
            continue
        ziel_name = treffer["sauber"] if _platten_pfad(ref) else Path(roh).name
        try:
            shutil.copyfile(treffer["pfad"], seite.parent / ziel_name)
        except OSError:
            continue
        if _platten_pfad(ref):
            neu = neu.replace(ref, ziel_name)
        getan.append(f"{treffer['name']} -> {seite.parent / ziel_name}")
    if neu != html:
        seite.write_text(neu, encoding="utf-8")
    return getan


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
        repariert = _verweise_reparieren(z, lauf.get("anhaenge") or [])
        lauf["vorschau"] = url
        lauf["gezeigt"] = str(z)
        await lauf["schlange"].put({"typ": "vorschau", "url": url})
        vorab = ("Das Cockpit hat fehlende Anhänge selbst neben die Seite gelegt: " + "; ".join(repariert) + "\n") if repariert else ""
        fehlt = _fehlende_verweise(z)
        if fehlt:
            # Lehre vom 01.10.2026: Neo trug den Namen eines angehaengten Logos ein,
            # ohne es in den Ordner zu kopieren -- die Seite zeigte ein leeres Bild,
            # und Neo meldete "erledigt". Jetzt bekommt er das als Fehler zurueck.
            return (vorab + f"Vorschau gezeigt: {url}\nNICHT FERTIG: Die Seite verweist auf Dateien, die im Ordner {z.parent} fehlen: "
                    + ", ".join(fehlt) + ". Kopiere sie mit datei_kopieren dorthin (oder korrigiere den Verweis) und zeig die Seite erneut.")
        return vorab + f"Vorschau gezeigt: {url}"
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


def system_text(anhaenge: list[dict[str, Any]] | None = None) -> str:
    from .stab import gedaechtnis_text
    anh = ""
    if anhaenge:
        anh = ("\n\n## Dateien, die Veiko in diesem Gespräch angehängt hat\n" + "\n".join(
            f"- {a['name']}: {a['pfad']}" + (f" (BILD -- für eine Seite mit datei_kopieren nach <Seitenordner>/{a['sauber']} legen, "
                                            f"dann <img src=\"{a['sauber']}\">)" if a["bild"] else "") for a in anhaenge) +
               "\nSpricht Veiko von „der angehängten Datei“, „meinem Logo“ oder „dem Bild“, ist eine dieser Dateien gemeint -- "
               "die letzte in der Liste, wenn nichts anderes gesagt ist. Nie durch etwas Selbstgezeichnetes ersetzen.")
    return (_kontext_text() + anh +
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
            "Schick ihn nie zu Handarbeit, die du selbst erledigen kannst.\n"
            "\n## Wenn Veiko etwas noch einmal verlangt\n"
            "„Bau das noch mal“, „das ist nicht mein Logo“, „das stimmt nicht“: dein letzter Versuch war falsch. Wiederhole ihn NICHT "
            "und schreib deine alte Antwort nicht ab. Sieh zuerst nach, was schiefging (die Seite mit datei_lesen lesen, den Ordner "
            "mit befehl_ausfuehren ls -la ansehen), behebe genau das und zeig das Ergebnis erneut. Nach deiner Antwort prüft das "
            "Cockpit selbst, ob die Seite gezeigt wird und alle Bilder neben ihr liegen.")


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


def _klammer_ende(text: str, start: int) -> int:
    """Index der schliessenden Klammer zu text[start] == '(' -- Zeichenketten beachtet."""
    tiefe, i, quote = 0, start, None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            tiefe += 1
        elif ch == ")":
            tiefe -= 1
            if tiefe == 0:
                return i
        i += 1
    return -1


def _text_aufrufe(text: str) -> list[dict[str, Any]]:
    """Werkzeugaufrufe, die das Modell als TEXT schreibt: datei_schreiben(pfad="…", inhalt="…").

    Gemessen am 01.10.2026 (Logo-Auftrag, zweiter Anlauf): qwen3-coder schrieb den
    richtigen Plan -- Logo kopieren, Seite schreiben, zeigen -- vollstaendig als
    solche Zeilen in seine Antwort, ohne einen einzigen echten Aufruf. Die Zeilen
    sind gueltige Python-Aufrufe; ast liest sie ohne Raten. Nur bekannte Werkzeuge,
    nur feste Werte (keine Ausdruecke) -- alles andere bleibt Text."""
    import ast
    bekannte = {w["name"]: w for w in WERKZEUGE}
    aufrufe = []
    for m in re.finditer(r"\b(" + "|".join(bekannte) + r")\(", text):
        ende = _klammer_ende(text, m.end() - 1)
        if ende < 0:
            continue
        try:
            knoten = ast.parse(text[m.start():ende + 1], mode="eval").body
        except SyntaxError:
            continue
        if not isinstance(knoten, ast.Call):
            continue
        args: dict[str, Any] = {}
        pflicht = bekannte[m.group(1)]["parameters"].get("required", [])
        try:
            for i, a in enumerate(knoten.args):
                if i < len(pflicht):
                    args[pflicht[i]] = ast.literal_eval(a)
            for k in knoten.keywords:
                if k.arg:
                    args[k.arg] = ast.literal_eval(k.value)
        except ValueError:
            continue
        if all(p in args for p in pflicht):
            aufrufe.append({"function": {"name": m.group(1), "arguments": args}})
    return aufrufe[:8]


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
            schritte = (m.get("daten") or {}).get("schritte") if isinstance(m.get("daten"), dict) else None
            if not schritte and BEHAUPTUNG.search(text):
                # Eine Erzaehlung von Arbeit, die nie stattfand, ist das schlechteste
                # Vorbild im Verlauf: das Modell schrieb sie beim naechsten Mal fast
                # wortgleich ab (Logo-Auftrag, 01.10.2026). Ehrlich vermerken statt zeigen.
                text = ("[Frühere Antwort von dir, die Arbeit beschrieb, ohne ein einziges Werkzeug aufzurufen -- "
                        "es ist also nichts davon passiert. Mach es diesmal mit echten Werkzeugaufrufen.]")
            out.append({"role": "assistant", "content": text[:6000]})
    return out


# ---------------------------------------------------------------- Auftraege
JOBS: dict[str, dict[str, Any]] = {}


def laufender_job(gid: str) -> str | None:
    for jid, j in JOBS.items():
        if j["gespraech_id"] == gid and not j["fertig"]:
            return jid
    return None


def _seiten_dieses_auftrags(lauf: dict[str, Any]) -> list[Path]:
    basis = str(VORSCHAU_DIR.resolve())
    seiten: list[Path] = []
    for f in lauf["dateien"]:
        p = Path(f.get("pfad") or "")
        if p.suffix.lower() in (".html", ".htm") and str(p).startswith(basis) and p.is_file() and p not in seiten:
            seiten.append(p)
    return seiten


async def _abschluss_pruefen(lauf: dict[str, Any], text: str) -> str | None:
    """Was Neo am Ende meldet, wird gegen das gehalten, was wirklich da ist.

    Anlass (01.10.2026, Logo-Auftrag): Neo schrieb eine Seite, rief
    vorschau_zeigen NICHT auf, verwies auf ein Bild, das nicht neben der Seite
    lag -- und meldete "in deiner Vorschau verfuegbar". Die Pruefung in
    vorschau_zeigen griff nie, weil das Werkzeug gar nicht lief. Darum hier,
    nach der letzten Antwort, unabhaengig davon, was Neo aufgerufen hat:
      1. Eine geschriebene Seite, die nicht gezeigt wurde, zeigt das Cockpit selbst.
      2. Fehlt ein Anhang neben der Seite, legt das Cockpit ihn dazu (eindeutiger Name).
      3. Bleibt ein Verweis ins Leere, geht Neo zurueck an die Arbeit.
      4. Behauptet er eine Vorschau, die es nicht gibt, ebenso.
    Rueckgabe: ein Auftrag fuer die naechste Runde, oder None, wenn alles stimmt."""
    seiten = _seiten_dieses_auftrags(lauf)
    if seiten and not lauf.get("vorschau"):
        ziel = seiten[-1]
        ergebnis = await werkzeug("vorschau_zeigen", {"pfad": str(ziel)}, lauf)
        schritt = {"name": "vorschau_zeigen", "kurz": f"pfad={ziel} (vom Cockpit nachgeholt)", "ergebnis": ergebnis[:2500], "zeit": time.time()}
        lauf["schritte"].append(schritt)
        await lauf["schlange"].put({"typ": "schritt", **schritt})
    elif lauf.get("gezeigt"):
        repariert = _verweise_reparieren(Path(lauf["gezeigt"]), lauf.get("anhaenge") or [])
        if repariert:
            schritt = {"name": "datei_kopieren", "kurz": "vom Cockpit nachgeholt", "ergebnis": "; ".join(repariert), "zeit": time.time()}
            lauf["schritte"].append(schritt)
            await lauf["schlange"].put({"typ": "schritt", **schritt})
            await lauf["schlange"].put({"typ": "vorschau", "url": lauf["vorschau"]})
    gezeigt = [Path(lauf["gezeigt"])] if lauf.get("gezeigt") else []
    for s in dict.fromkeys(seiten + gezeigt):
        fehlt = _fehlende_verweise(s)
        if fehlt:
            return (f"PRÜFUNG DES COCKPITS: NICHT FERTIG. Die Seite {s} verweist auf Dateien, die im Browser ins Leere gehen: "
                    + ", ".join(fehlt) + ". Lege jede mit datei_kopieren in den Ordner " + str(s.parent)
                    + " und binde sie relativ ein (nur der Dateiname, ohne Leerzeichen). Dann vorschau_zeigen. "
                    "Antworte erst danach, und beschreib nur, was die Werkzeuge belegen.")
    if (not lauf.get("vorschau") and re.search(r"vorschau", text, re.I)
            and re.search(r"\b(verfügbar|gezeigt|angezeigt|zeige|sehen)\b", text, re.I)):
        return ("PRÜFUNG DES COCKPITS: Du schreibst von der Vorschau, aber in diesem Auftrag wurde keine Seite gezeigt. "
                f"Schreib die Seite nach {VORSCHAU_DIR}/<name>/index.html und ruf vorschau_zeigen auf -- oder sag ehrlich, warum nicht.")
    return None


async def _kern(gid: str, modell: str, lauf: dict[str, Any]) -> None:
    schlange: asyncio.Queue = lauf["schlange"]
    verlauf = _vorgeschichte(gid)
    lauf["anhaenge"] = anhaenge_im_gespraech(gid)
    system = system_text(lauf["anhaenge"])
    letzter_text = ""
    nachgefragt = 0
    geprueft = 0
    frisch = False
    verlauf_start = list(verlauf)
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
            if not aufrufe:
                aufrufe = _text_aufrufe(text)
                if aufrufe:
                    await schlange.put({"typ": "zwischen", "text": f"(Neo hat {len(aufrufe)} Arbeitsschritt(e) als Text geschrieben statt aufgerufen. Das Cockpit führt sie jetzt wirklich aus.)"})
                    erster = re.search(r"\b" + re.escape(aufrufe[0]["function"]["name"]) + r"\(", text)
                    text = text[:erster.start()].strip() if erster else ""
            verlauf.append({"role": "assistant", "content": text,
                            **({"tool_calls": aufrufe} if aufrufe else {})})
            if text:
                letzter_text = text
                if aufrufe:
                    await schlange.put({"typ": "zwischen", "text": text})
            if not aufrufe:
                # Behauptet, etwas getan zu haben, aber in DIESEM Auftrag kein
                # Werkzeug benutzt? Dann einmal (hoechstens zweimal) zurueckschicken.
                if not lauf["schritte"] and BEHAUPTUNG.search(text) and nachgefragt >= 2 and not frisch:
                    # Zweimal zurueckgeschickt, immer noch nur erzaehlt: das Gespraech ist
                    # "vergiftet" -- Neo schreibt seine eigenen frueheren Erzaehlungen ab
                    # (gemessen am 01.10.2026: im alten Logo-Gespraech null Aufrufe, im
                    # frischen Gespraech mit demselben Auftrag sofort alle vier). Also ein
                    # frischer Anlauf: nur Veikos Nachrichten, ohne Neos alte Antworten.
                    frisch = True
                    await schlange.put({"typ": "zwischen", "text": "(Neo kam in diesem Gespräch nicht ins Arbeiten. Das Cockpit startet einen frischen Anlauf ohne seine alten Antworten.)"})
                    seine = [m["content"] for m in verlauf_start if m.get("role") == "user"][-5:]
                    verlauf = [{"role": "user", "content":
                                "FRISCHER ANLAUF. Deine früheren Antworten in diesem Gespräch sind ausgeblendet: sie beschrieben Arbeit, "
                                "die nie stattfand. Veikos Nachrichten bisher, die letzte ist der aktuelle Auftrag:\n\n"
                                + "\n\n---\n\n".join(seine) +
                                "\n\nErledige den Auftrag JETZT mit echten Werkzeugaufrufen (datei_kopieren, datei_schreiben, vorschau_zeigen …). "
                                "Erst wenn die Werkzeuge ohne Fehler zurückkamen, antwortest du mit dem Ergebnis."}]
                    continue
                if not lauf["schritte"] and BEHAUPTUNG.search(text) and nachgefragt < 2:
                    nachgefragt += 1
                    await schlange.put({"typ": "zwischen", "text": "(Neo hat etwas behauptet, ohne es getan zu haben. Ich schicke ihn zurück an die Arbeit.)"})
                    verlauf.append({"role": "user", "content":
                                    "Du hast geschrieben, dass du etwas getan hast, aber in diesem Auftrag kein einziges Werkzeug "
                                    "aufgerufen. Es ist also NICHT passiert. Erledige es jetzt wirklich mit den Werkzeugen "
                                    "(z. B. dokument_erstellen, datei_schreiben, vorschau_zeigen, befehl_ausfuehren). "
                                    "Wenn du es nicht kannst, sag ehrlich warum."})
                    continue
                # Zum Schluss: stimmt, was er meldet? (siehe _abschluss_pruefen)
                problem = await _abschluss_pruefen(lauf, text)
                if problem and geprueft < 2:
                    geprueft += 1
                    await schlange.put({"typ": "zwischen", "text": "(Das Cockpit hat nachgeprüft: noch nicht fertig. Neo bessert nach.)"})
                    verlauf.append({"role": "user", "content": problem})
                    continue
                if problem:
                    letzter_text = ((letzter_text + "\n\n") if letzter_text else "") + \
                        "**Hinweis des Cockpits:** " + problem.replace("PRÜFUNG DES COCKPITS: ", "")
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
    if llm.fremdschrift(text):
        text = llm.FREMDSCHRIFT.sub("", text)
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
