"""
MODELLE AKTUELL HALTEN -- welches Modell fuer welche Aufgabe, und ob es Besseres
oder Neueres gibt. Uebernommen aus dem alten Cockpit (AUFGABEN, NEO_AUSSCHAU,
/api/modelle/neuheiten), dazu eine Pruefung, die es dort nicht gab:

  1. AKTUALISIERUNG: Ollama tauscht Gewichte manchmal unter DEMSELBEN Namen
     aus. Verglichen wird die Modelldatei (digest) des installierten Modells
     mit der aktuellen bei Ollama -- am 01.10.2026 fand das sofort gemma4:e4b.
  2. ERSATZ: Je Aufgabe ist der Katalog eine Rangfolge. Gibt es ein Modell,
     das VOR dem besten installierten steht, bei Ollama existiert und auf die
     Karten passt, wird es vorgeschlagen.
  3. AUSSCHAU: Namen kommender Generationen (qwen4, gemma5 ...). Ein 404 ist
     die belastbare Antwort "noch nicht da"; ein 200 steht sofort im Cockpit.

Die Rangfolge ist von Hand gepflegt und begruendet (Messungen im alten Repo,
CLAUDE.md "Leistung und Optimierung"); die Registry sagt nur, OB es etwas
gibt, nicht ob es besser ist. Abgefragt wird je Modell genau EIN Manifest --
die Tag-Liste der Registry antwortet seit September mit 404.
Geladen wird ueber Ollamas eigene Schnittstelle; das braucht kein sudo.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx

from .konfig import DATEN, OLLAMA

AUFGABEN = [
    {"id": "code", "name": "Programmieren", "kandidaten": ["qwen3-coder:30b", "qwen3.8:27b", "qwen3.6:27b", "devstral:24b"]},
    {"id": "allgemein", "name": "Allgemeine Textarbeit", "kandidaten": ["qwen3.8:27b", "gemma4:12b", "gemma4:e4b", "llama3.3:70b", "qwen3:32b"]},
    {"id": "denken", "name": "Analyse und langes Denken", "kandidaten": ["qwen3.8:27b", "deepseek-r1:32b", "qwen3:32b"]},
    {"id": "schnell", "name": "Schnelle Antworten", "kandidaten": ["gemma4:e4b", "qwen3:30b-a3b", "glm-4.7-flash:latest", "qwen3:8b"]},
    {"id": "werkzeuge", "name": "Werkzeug-Aufrufe", "kandidaten": ["qwen3.8:27b", "gpt-oss:20b", "qwen3:32b"]},
    {"id": "bilder", "name": "Bilder lesen", "kandidaten": ["nemotron3:33b", "qwen3.8:27b", "llava:13b"]},
    {"id": "suche", "name": "Suche über Dokumente", "kandidaten": ["nomic-embed-text:latest", "mxbai-embed-large:latest"]},
]
AUSSCHAU = ["qwen4:27b", "qwen3.9:27b", "gemma5:12b", "llama5:70b", "deepseek-r2:32b", "devstral2:24b", "qwen4-coder:30b"]

DATEI = DATEN / "modell-neuheiten.json"
FRISCH_SEK = 6 * 3600
ACCEPT = "application/vnd.docker.distribution.manifest.v2+json"
MANIFESTE = Path("/usr/share/ollama/.ollama/models/manifests/registry.ollama.ai/library")
LADEN: dict[str, dict[str, Any]] = {}


def _tag(n: str) -> str:
    return n if ":" in n else n + ":latest"


def lokal() -> dict[str, str]:
    """Installierte Modelle -> digest ihrer Modelldatei (aus Ollamas Manifesten)."""
    aus = {}
    try:
        for f in MANIFESTE.glob("*/*"):
            try:
                for l in json.loads(f.read_text(encoding="utf-8")).get("layers") or []:
                    if str(l.get("mediaType", "")).endswith(".model"):
                        aus[f"{f.parent.name}:{f.name}"] = l["digest"]
            except (OSError, ValueError, KeyError):
                continue
    except OSError:
        pass
    return aus


def lokal_gb() -> dict[str, float]:
    """Installierte Modelle -> Groesse in GB (Summe der Schichten im Manifest)."""
    aus = {}
    try:
        for f in MANIFESTE.glob("*/*"):
            try:
                schichten = json.loads(f.read_text(encoding="utf-8")).get("layers") or []
                aus[f"{f.parent.name}:{f.name}"] = round(sum(int(l.get("size") or 0) for l in schichten) / 1e9, 1)
            except (OSError, ValueError):
                continue
    except OSError:
        pass
    return aus


async def _eins(cl: httpx.AsyncClient, tag: str) -> dict[str, Any]:
    familie, _, ausgabe = tag.partition(":")
    try:
        r = await cl.get(f"https://registry.ollama.ai/v2/library/{familie}/manifests/{ausgabe}", headers={"Accept": ACCEPT})
    except httpx.HTTPError as e:
        return {"fehler": e.__class__.__name__}
    if r.status_code == 404:
        return {"da": False}
    if r.status_code >= 400:
        return {"fehler": f"HTTP {r.status_code}"}
    try:
        schichten = r.json().get("layers") or []
    except ValueError:
        return {"da": True}
    modell = next((s.get("digest") for s in schichten if str(s.get("mediaType", "")).endswith(".model")), None)
    groesse = sum(int(s.get("size") or 0) for s in schichten)
    return {"da": True, "gb": round(groesse / 1e9, 1) if groesse else None, "digest": modell}


async def pruefen(frisch: bool = False) -> dict[str, Any]:
    if not frisch:
        try:
            d = json.loads(DATEI.read_text(encoding="utf-8"))
            if time.time() - d.get("zeit", 0) < FRISCH_SEK:
                return d
        except (OSError, ValueError):
            pass
    tags = sorted({_tag(k) for a in AUFGABEN for k in a["kandidaten"]} | set(AUSSCHAU) | set(lokal()))
    ergebnis: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "vve-cockpit-r2"}) as cl:
        for i in range(0, len(tags), 6):
            teil = tags[i:i + 6]
            ergebnis.update(dict(zip(teil, await asyncio.gather(*[_eins(cl, t) for t in teil]))))
    d = {"zeit": time.time(), "ergebnis": ergebnis}
    try:
        DATEI.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass
    return d


def _passt(gb: float | None, vram_gesamt: float) -> str:
    if not gb:
        return "Größe unbekannt"
    g = gb * 1.08
    return "passt auf eine Karte" if g < 22.5 else "passt auf beide Karten" if g < vram_gesamt - 1.5 else "nur mit Auslagerung (langsam)"


def vorschlaege(stand: dict[str, Any] | None, vram_gesamt: float = 48.0) -> list[dict[str, Any]]:
    """Empfehlungen in derselben Form wie systeminfo.empfehlungen()."""
    if not stand:
        return []
    erg = stand.get("ergebnis") or {}
    inst = lokal()
    aus: list[dict[str, Any]] = []
    # 1. gleicher Name, neue Gewichte
    for name, digest in sorted(inst.items()):
        r = erg.get(name) or {}
        if r.get("da") and r.get("digest") and r["digest"] != digest:
            aus.append({"stufe": "einspielen", "titel": f"{name}: neuere Fassung bei Ollama",
                        "warum": f"Unter demselben Namen liegen bei Ollama neue Gewichte ({r.get('gb') or '?'} GB). "
                                 "Laden ersetzt die installierte Fassung; Team-Zuordnungen bleiben.",
                        "aktion": {"art": "modell", "name": name, "text": "Aktualisieren"}})
    # 2. besser eingestuft als das beste installierte
    gesehen = set()
    for a in AUFGABEN:
        kand = [_tag(k) for k in a["kandidaten"]]
        bester = next((i for i, k in enumerate(kand) if k in inst), None)
        grenze = bester if bester is not None else len(kand)
        for k in kand[:grenze]:
            r = erg.get(k) or {}
            if not r.get("da") or k in gesehen:
                continue
            passt = _passt(r.get("gb"), vram_gesamt)
            if "Auslagerung" in passt:
                continue
            gesehen.add(k)
            aus.append({"stufe": "einspielen", "titel": f"{a['name']}: {k} verfügbar",
                        "warum": (f"Steht im Katalog vor dem installierten {kand[bester]}" if bester is not None else "Für diese Aufgabe ist noch kein Modell installiert")
                                 + f". {r.get('gb') or '?'} GB, {passt}. Danach im Team der Rolle zuweisen.",
                        "aktion": {"art": "modell", "name": k, "text": "Laden"}})
            break
    # 3. neue Generation
    for k in AUSSCHAU:
        r = erg.get(k) or {}
        if r.get("da") and k not in inst:
            aus.append({"stufe": "einspielen", "titel": f"Neue Modellgeneration: {k}",
                        "warum": f"Erstmals bei Ollama verfügbar ({r.get('gb') or '?'} GB, {_passt(r.get('gb'), vram_gesamt)}). "
                                 "Noch nicht auf dieser Maschine gemessen -- vor dem Einsatz testen.",
                        "aktion": {"art": "modell", "name": k, "text": "Laden"}})
    return aus


async def _laden(name: str) -> None:
    j = LADEN[name]
    schichten: dict[str, list[int]] = {}
    # Tempo aus den eigenen Zaehlern von Ollama, ueber ~20 s geglaettet -- eine
    # Restzeit aus EINEM Messpunkt springt bei dieser Leitung um Stunden.
    probe: list[tuple[float, int]] = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(None, connect=10)) as cl:
            async with cl.stream("POST", f"{OLLAMA}/api/pull", json={"model": name, "stream": True}) as r:
                async for zeile in r.aiter_lines():
                    if not zeile.strip():
                        continue
                    try:
                        d = json.loads(zeile)
                    except ValueError:
                        continue
                    if d.get("error"):
                        j.update(stand="fehler", fehler=d["error"])
                        return
                    if d.get("digest") and d.get("total"):
                        schichten[d["digest"]] = [int(d.get("completed") or 0), int(d["total"])]
                        fertig, ges = sum(v[0] for v in schichten.values()), sum(v[1] for v in schichten.values())
                        j.update(prozent=round(fertig / ges * 100, 1), gb=round(ges / 1e9, 2 if ges < 1e10 else 1), geladen_gb=round(fertig / 1e9, 2))
                        jetzt = time.time()
                        probe.append((jetzt, fertig))
                        while len(probe) > 2 and jetzt - probe[0][0] > 20:
                            probe.pop(0)
                        dt, db_ = jetzt - probe[0][0], fertig - probe[0][1]
                        if dt >= 5 and db_ > 0:
                            j["mb_s"] = round(db_ / dt / 1e6, 2)
                            j["rest_s"] = round((ges - fertig) / (db_ / dt))
                    j["schritt"] = d.get("status") or j.get("schritt")
        j.update(stand="fertig", prozent=100, ende=time.time(), rest_s=None)
        try:
            DATEI.unlink()   # naechste Pruefung frisch: das Geladene ist jetzt installiert
        except OSError:
            pass
    except asyncio.CancelledError:
        # Pausieren oder Abbrechen (laden_steuern). Ollama bricht den Pull ab,
        # sobald die Verbindung zugeht; die schon geladenen Teile bleiben liegen,
        # ein neuer Pull setzt dort fort.
        j.update(rest_s=None, mb_s=None)
        raise
    except httpx.HTTPError as e:
        j.update(stand="fehler", fehler=f"Ollama nicht erreichbar: {e.__class__.__name__}")
    finally:
        # Nur die eigene Aufgabe austragen: nach Pausieren und sofortigem
        # Fortsetzen steht dort schon die neue.
        if _LADE_TASKS.get(name) is asyncio.current_task():
            _LADE_TASKS.pop(name, None)


# Die laufenden Pull-Aufgaben, getrennt von LADEN: LADEN geht als JSON an den Browser.
_LADE_TASKS: dict[str, asyncio.Task] = {}


def laden_starten(name: str) -> dict[str, Any]:
    if name in LADEN and LADEN[name].get("stand") == "laeuft":
        return LADEN[name]
    vorher = LADEN.get(name) or {}
    # Fortsetzen nach einer Pause behaelt den Stand, damit der Balken nicht auf 0 springt.
    LADEN[name] = {"name": name, "stand": "laeuft", "prozent": vorher.get("prozent", 0) if vorher.get("stand") == "pausiert" else 0,
                   "gb": vorher.get("gb"), "start": vorher.get("start") if vorher.get("stand") == "pausiert" else time.time(),
                   "schritt": "setzt fort" if vorher.get("stand") == "pausiert" else "beginne"}
    _LADE_TASKS[name] = asyncio.create_task(_laden(name))
    return LADEN[name]


def laden_steuern(name: str, aktion: str) -> dict[str, Any]:
    """Pausieren, fortsetzen, abbrechen, aus der Liste nehmen (Current Actions).

    Pausieren und Abbrechen beenden beide den Pull bei Ollama. Der Unterschied:
    pausiert bleibt der Eintrag mit seinem Stand stehen und "Fortsetzen" holt
    nur den Rest. Abgebrochen verschwindet er aus der Liste; die schon geladenen
    Teile liegen als Teildateien in Ollamas Ablage, und ein spaeteres Laden
    desselben Modells setzt dort fort. Wegraeumen kann sie das Cockpit nicht --
    Ollamas Ablage gehoert dem Nutzer ollama.
    """
    j = LADEN.get(name)
    if not j:
        raise ValueError("Diesen Download gibt es nicht (mehr).")
    t = _LADE_TASKS.get(name)
    if aktion in ("pausieren", "abbrechen"):
        if t and not t.done():
            t.cancel()
        if aktion == "pausieren":
            if j.get("stand") != "laeuft":
                raise ValueError("Der Download läuft nicht.")
            j.update(stand="pausiert", schritt="pausiert", pausiert=time.time())
        else:
            LADEN.pop(name, None)
        return {"ok": True}
    if aktion == "fortsetzen":
        if j.get("stand") not in ("pausiert", "fehler"):
            raise ValueError("Der Download läuft schon.")
        return laden_starten(name)
    if aktion == "weg":
        if j.get("stand") == "laeuft":
            raise ValueError("Ein laufender Download wird abgebrochen, nicht weggeräumt.")
        LADEN.pop(name, None)
        return {"ok": True}
    raise ValueError("Unbekannte Aktion.")


async def entfernen(name: str) -> None:
    """Ein Modell bei Ollama loeschen. Ob es noch jemand braucht, prueft der
    Aufrufer (revision.gebraucht_von) -- hier wird nur geloescht."""
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.request("DELETE", f"{OLLAMA}/api/delete", json={"model": name})
    if r.status_code == 404:
        raise ValueError("Das Modell ist nicht (mehr) installiert.")
    if r.status_code >= 400:
        raise RuntimeError(f"Ollama hat das Löschen abgelehnt (HTTP {r.status_code}): {r.text[:200]}")
    try:
        DATEI.unlink()
    except OSError:
        pass


# ---------------------------------------------------------------- Neu bei Ollama
# Warum es das gibt (Veiko, 16.10.2026: "warum werden mir keine neuen mehr
# empfohlen?"): die Rangfolge oben ist von Hand gepflegt und kannte die neuen
# Modelle nicht -- qwen3.8:27b stand ueberall oben und war installiert, also gab
# es "nichts Besseres". Hier liest das Cockpit die Liste der neuesten Modelle auf
# ollama.com und je Modell die verfuegbaren Groessen, und rechnet aus, was auf
# die beiden Karten passt. Das ist eine Liste dessen, was ES GIBT -- ob es hier
# besser ist, sagt erst eine Messung; deshalb steht "ungetestet" dabei.
import html as _html
import re as _re

NEU_DATEI = DATEN / "ollama-neu.json"
NEU_FRISCH_SEK = 24 * 3600
WEB = "https://ollama.com"
# Ausgaben fuer andere Hardware oder volle Genauigkeit -- auf zwei RTX 3090 nicht sinnvoll.
# (mlx = Apple, nvfp4/mxfp8 = neuere NVIDIA-Karten). q8_0 laeuft auf der 3090 und
# bleibt, solange es zu derselben Groesse keine kleinere Ausgabe gibt.
_FREMD = _re.compile(r"mlx|nvfp4|mxfp8|bf16|fp16|fp8|-mtp|-cloud|instruct-fp")


def _version(familie: str) -> float | None:
    """qwen3.8 -> 3.8, gemma4 -> 4.0, qwen3-coder -> 3.0, deepseek-r1 -> 1.0,
    deepseek-v4-pro -> 4.0, nemotron-3.5-bolt -> 3.5, deepseek-coder -> None."""
    m = _re.match(r"[a-z]+-?[a-z]?(\d+(?:\.\d+)?)", familie or "")
    return float(m.group(1)) if m else None


def familie_wurzel(name: str) -> str:
    m = _re.match(r"[a-z]+", name or "")
    return m.group(0) if m else ""


def _text(s: str) -> str:
    return _html.unescape(_re.sub(r"<[^>]+>", " ", s)).strip()


def _suche_lesen(h: str) -> list[dict[str, Any]]:
    aus = []
    for block in _re.split(r'<li\s+class="border-b', h)[1:]:   # ollama.com schreibt "<li  class" mit zwei Leerzeichen
        m = _re.search(r'href="/library/([a-z0-9._-]+)"', block)
        if not m:
            continue
        b = _re.search(r'<p class="mt-1[^"]*" title="([^"]*)"', block)
        faeh = _re.findall(r'bg-indigo-50[^"]*">([a-z ]+)</span>', block)
        nur_cloud = 'bg-cyan-50' in block and not _re.search(r'bg-blue-50|x-test-size', block)
        dl = _re.search(r'title="([\d,.]+) downloads"', block)
        aus.append({"familie": m.group(1), "beschreibung": _html.unescape(b.group(1)) if b else "",
                    "faehigkeiten": [f.strip() for f in faeh], "nur_cloud": nur_cloud,
                    "downloads": int(dl.group(1).replace(",", "").replace(".", "")) if dl else None})
    return aus


def _tags_lesen(familie: str, h: str) -> list[dict[str, Any]]:
    aus = []
    # Grossbuchstaben gehoeren dazu: die 4-Bit-Ausgaben heissen "…-q4_K_M".
    for m in _re.finditer(r'<a href="/library/(' + _re.escape(familie) + r':[A-Za-z0-9._-]+)" class="md:hidden(.*?)</a>', h, _re.S):
        teile = [t.strip() for t in _text(m.group(2)).split("•")]
        # Kurznamen (qwen3.6:35b-a3b) tragen eine Spanne: "23GB - 24GB" -- es zaehlt die erste Zahl.
        groesse = next((t for t in teile if _re.fullmatch(r"[\d.]+\s*(GB|MB|TB)(\s*-\s*[\d.]+\s*(GB|MB|TB))?", t)), None)
        if not groesse:
            continue
        zahl = float(_re.match(r"[\d.]+", groesse).group(0))
        einheit = _re.match(r"[\d.]+\s*(GB|MB|TB)", groesse).group(1)
        gb = zahl / 1000 if einheit == "MB" else zahl * 1000 if einheit == "TB" else zahl
        kontext = next((t.replace(" context window", "") for t in teile if "context window" in t), "")
        rest = next((t for t in teile if "input" in t), "")
        alter = next((t for t in reversed(teile) if "ago" in t), "")
        aus.append({"name": m.group(1), "gb": round(gb, 1), "kontext": kontext,
                    "bilder": "Image" in rest, "alter": alter})
    return aus


async def neu_bei_ollama(frisch: bool = False, vram_gesamt: float = 48.0, anzahl: int = 40) -> dict[str, Any]:
    if not frisch:
        try:
            d = json.loads(NEU_DATEI.read_text(encoding="utf-8"))
            if time.time() - d.get("zeit", 0) < NEU_FRISCH_SEK:
                return d
        except (OSError, ValueError):
            pass
    try:
        async with httpx.AsyncClient(timeout=40, headers={"User-Agent": "vve-cockpit-r2"}, follow_redirects=True) as cl:
            # Zwei Quellen: (1) die 20 neuesten Modelle ueberhaupt, (2) je Familie,
            # die hier schon laeuft (qwen, gemma, deepseek ...), die Suche nach
            # ihrem Namen -- dort stehen die Nachfolger (qwen3.6 neben qwen3.8,
            # gemma4 in groesseren Ausgaben). Unter "neueste" allein standen am
            # 16.10. fast nur Exoten. Aeltere Generationen (qwen2.5 neben qwen3.8)
            # fallen ueber die Versionsnummer heraus.
            inst = lokal()
            inst_gb = lokal_gb()
            fam_inst: dict[str, float] = {}
            for n, gb in inst_gb.items():
                fam_inst[n.split(":")[0]] = max(fam_inst.get(n.split(":")[0], 0), gb)
            wurzeln = {familie_wurzel(n) for n in inst} - {"nomic", "mxbai", "llava"}
            hoechste: dict[str, float] = {}
            for n in inst:
                v = _version(n.split(":")[0])
                if v is not None:
                    hoechste[familie_wurzel(n)] = max(hoechste.get(familie_wurzel(n), 0), v)
            liste = _suche_lesen((await cl.get(f"{WEB}/search?o=newest")).text)
            for w in sorted(wurzeln):
                for f in _suche_lesen((await cl.get(f"{WEB}/search", params={"q": w})).text)[:8]:
                    v = _version(f["familie"])
                    # Bleiben: dieselbe oder eine neuere Generation, und Familien, die hier
                    # schon laufen (fuer groessere Ausgaben). Ohne Versionsnummer kein Vergleich.
                    if familie_wurzel(f["familie"]) == w and (f["familie"] in fam_inst or (v is not None and v >= hoechste.get(w, 0) - 0.5)):
                        liste.append(f)
            gesehen: set[str] = set()
            # "nur Cloud" laut Suchseite wird nicht gefiltert: gemma4 traegt das Abzeichen
            # UND lokale Ausgaben. Reine Cloud-Modelle fallen unten heraus, weil sie keine
            # Ausgabe mit Groesse haben.
            liste = [f for f in liste if "embedding" not in f["faehigkeiten"]
                     and not _re.search(r"embed|ocr|guard|shield", f["familie"])
                     and not (f["familie"] in gesehen or gesehen.add(f["familie"]))][:anzahl]
            sem = asyncio.Semaphore(4)

            async def tags(f: dict[str, Any]) -> None:
                async with sem:
                    try:
                        f["ausgaben"] = _tags_lesen(f["familie"], (await cl.get(f"{WEB}/library/{f['familie']}/tags")).text)
                    except httpx.HTTPError:
                        f["ausgaben"] = []
            await asyncio.gather(*[tags(f) for f in liste])
    except httpx.HTTPError as e:
        return {"zeit": time.time(), "fehler": f"ollama.com nicht erreichbar: {e.__class__.__name__}", "familien": []}
    familien = []
    for f in liste:
        brauchbar = [a for a in f.get("ausgaben") or [] if not _FREMD.search(a["name"].split(":", 1)[1]) and a["gb"] * 1.08 < vram_gesamt - 1.5]
        # Je Groesse (27b, 35b-a3b …) nur EINE Ausgabe: die kleinste, also 4 Bit; bei
        # gleicher Groesse der kuerzere Name (qwen3.6:35b-a3b statt …-q4_K_M). Sonst
        # stuende dasselbe Modell in hoeherer Genauigkeit als "groessere Ausgabe" da.
        je_groesse: dict[str, dict[str, Any]] = {}
        for a in brauchbar:
            k = _re.sub(r"-(it-)?(q\d[A-Za-z0-9_]*|int\d+|qat|fp\d+)$", "", a["name"].split(":", 1)[1])
            b = je_groesse.get(k)
            def rang(x: dict[str, Any]) -> tuple:   # 35b-a3b sagt mehr als 35b (Mixture of Experts)
                return (x["gb"], 0 if _re.search(r"-a\d+b", x["name"]) else 1, len(x["name"]))
            if not b or rang(a) < rang(b):
                je_groesse[k] = a
        brauchbar = list(je_groesse.values())
        # "latest" ist nur ein Zweitname einer bestimmten Groesse (qwen3.6:latest =
        # 35b-a3b) -- dann gilt der sprechende Name. Spezialausgaben (…-coding)
        # nur, wenn es die allgemeine in der Groesse nicht gibt.
        allgemein = [a for a in brauchbar if "-coding" not in a["name"]]
        brauchbar = allgemein or brauchbar

        def zweitname(a: dict[str, Any]) -> bool:
            t = a["name"].split(":", 1)[1]
            return any(b is not a and abs(b["gb"] - a["gb"]) <= 1 and
                       (t == "latest" or _re.fullmatch(_re.escape(t) + r"-a\d+b", b["name"].split(":", 1)[1]))
                       for b in brauchbar)
        brauchbar = [a for a in brauchbar if not zweitname(a)]
        # Eine Familie, die hier schon laeuft, zaehlt nur mit deutlich groesseren
        # Ausgaben (gemma4:26b neben dem installierten e4b) -- dieselbe Groesse
        # unter anderem Namen (qwen3.8:latest = qwen3.8:27b) ist nichts Neues.
        installiert_gb = fam_inst.get(f["familie"])
        if installiert_gb:
            brauchbar = [a for a in brauchbar if a["gb"] >= installiert_gb * 1.5]
        if not brauchbar:
            continue
        eine = [a for a in brauchbar if a["gb"] * 1.08 < 22.5]
        wahl = []
        if eine:
            wahl.append(max(eine, key=lambda a: a["gb"]))
        groesste = max(brauchbar, key=lambda a: a["gb"])
        if groesste not in wahl:
            wahl.append(groesste)
        for a in wahl:
            a["passt"] = _passt(a["gb"], vram_gesamt)
            a["installiert"] = _tag(a["name"]) in inst
        v = _version(f["familie"])
        wurzel = familie_wurzel(f["familie"])
        familien.append({**{k: f[k] for k in ("familie", "beschreibung", "faehigkeiten", "downloads")},
                         "ausgaben": wahl, "verwandt": wurzel in wurzeln,
                         "neuer": bool(wurzel in wurzeln and not installiert_gb and v is not None and v > hoechste.get(wurzel, 0)),
                         "groesser": bool(installiert_gb)})
    d = {"zeit": time.time(), "familien": familien}
    try:
        NEU_DATEI.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass
    return d


def neu_vorschlaege(neu: dict[str, Any] | None, anzahl: int = 3) -> list[dict[str, Any]]:
    """Fuer die Empfehlungen: neue Fassungen von Familien, die hier schon laufen
    (qwen, gemma, deepseek ...) -- das ist der Fall "sollte ich ersetzen?"."""
    kandidaten = []
    for f in (neu or {}).get("familien") or []:
        if not f.get("verwandt"):
            continue
        if (f.get("einordnung") or {}).get("aelter"):
            continue
        offen = [x for x in f["ausgaben"] if not x.get("installiert")]
        if not offen:
            continue
        wurzel = familie_wurzel(f["familie"])
        # Drei Gruende, an eine neue Ausgabe zu denken -- in dieser Reihenfolge.
        # "Mixture of Experts" (…-a3b): pro Wort rechnet nur ein kleiner Teil des
        # Modells, deshalb deutlich schneller als ein gleich grosses dichtes Modell.
        moe_aus = next((x for x in offen if _re.search(r"-a\d+b", x["name"])), None)
        a = offen[0] if (f.get("neuer") or f.get("groesser") or not moe_aus) else moe_aus
        moe = bool(moe_aus)
        if f.get("neuer"):
            rang, grund = 0, f"Neuere Generation der Familie {wurzel}, die du schon nutzt."
        elif f.get("groesser"):
            rang, grund = 1, f"Größere Ausgabe von {f['familie']}, das hier schon läuft -- mehr Qualität, mehr Speicher."
        elif moe:
            rang, grund = 2, (f"Schnellere Bauart aus der Familie {wurzel} (Mixture of Experts: je Wort rechnet nur ein "
                              "kleiner Teil des Modells).")
        else:
            continue
        kandidaten.append((rang, {"stufe": "einspielen", "titel": f"Neu bei Ollama: {a['name']}",
                                  "warum": f"{grund} {a['gb']} GB, {a['passt']}. {f['beschreibung'][:120]} "
                                           f"{_einordnung_text(f)}Ungetestet -- erst laden und messen, dann ersetzen.",
                                  "aktion": {"art": "modell", "name": a["name"], "text": "Laden"}}))
    return [k for _, k in sorted(kandidaten, key=lambda x: x[0])][:anzahl]


# ------------------------------------------------- Einordnung neuer Modelle
# Veiko, 17.10.2026: zu jedem neuen Modell will er wissen, WELCHES installierte
# es ersetzen koennte, fuer WELCHE Rolle im Team es taugt -- oder welche NEUE
# Rolle es abdecken koennte. Die Antwort ist eine Ableitung aus Faehigkeiten
# (von ollama.com), Groesse und dem, was hier laeuft -- keine Messung. Deshalb
# steht im Text "koennte", und bei allem bleibt "ungetestet".
_FAEHIG_AUFGABE = {"thinking": "denken", "tools": "werkzeuge", "vision": "bilder"}
# Was es im Team noch nicht gibt: Faehigkeit -> (Rollenname, wofuer). Nur
# Faehigkeiten, fuer die heute keine Rolle zustaendig ist.
_NEUE_ROLLE = {
    "vision": ("Dokumenten- und Bildleser", "liest Scans, Fotos, Folien und Screenshots und macht daraus Text, den das Team weiterverarbeitet"),
    "decision": ("Entscheidungsvorbereiter", "wägt bei offenen Entscheidungen die Optionen ab und schlägt eine begründete Wahl vor"),
    "audio": ("Zuhörer", "versteht Sprachaufnahmen direkt, auch Tonfall und mehrere Sprecher -- ohne Umweg über die Abschrift"),
}
# Wo eine solche Rolle im Ablauf saesse (fuer das Schaubild auf Stab & Modelle):
# "eingang" = vor Jason (bereitet Material auf), "entscheidung" = zwischen Daniel
# und Veiko. Dazu, mit wem sie arbeiten wuerde -- Rollenkennungen aus team.
_NEUE_ROLLE_STELLE = {
    "vision": ("eingang", ["pmo"], "liefert Jason den Text aus Bildern und Scans, bevor er einordnet"),
    "audio": ("eingang", ["pmo"], "hört die Plaud-Aufnahme selbst und gibt Jason Tonfall und Sprecher mit"),
    "decision": ("entscheidung", ["kritiker"], "nimmt Daniels geprüfte Ergebnisse und bereitet dir die Entscheidung vor"),
}


def _aufgaben_fuer(f: dict[str, Any], gb: float) -> list[str]:
    faeh = f.get("faehigkeiten") or []
    auf = [_FAEHIG_AUFGABE[x] for x in faeh if x in _FAEHIG_AUFGABE]
    if "coder" in f["familie"] or "devstral" in f["familie"]:
        auf.insert(0, "code")
    if gb <= 10:
        auf.append("schnell")
    elif "decision" not in faeh or auf:
        auf.append("allgemein")
    return list(dict.fromkeys(auf))


def einordnen(neu: dict[str, Any] | None, inst_gb: dict[str, float], team: list[dict[str, Any]],
              modelle: dict[str, str]) -> None:
    """Haengt an jede neue Familie {ersetzt, rollen, neue_rolle}.

    team: Zeilen der Tabelle team (id, name, titel, art, modell).
    modelle: Bedienung -> Modell, das sie ohne eigene Wahl nimmt
             ("arbeit", "talk").
    """
    namen = {a["id"]: a["name"] for a in AUFGABEN}
    bester = {}
    for a in AUFGABEN:
        bester[a["id"]] = next((_tag(k) for k in a["kandidaten"] if _tag(k) in inst_gb), None)
    abgedeckt = {"vision": False, "decision": False, "audio": False}
    for t in team:
        if t.get("art") == "bilder":
            abgedeckt["vision"] = True
    for f in (neu or {}).get("familien") or []:
        # "installiert" stammt aus der Pruefung bei ollama.com und ist bis zu 24 h
        # alt. Am 17.10. bot die Uebersicht so qwen3.6:35b-a3b zum Laden an, mit
        # dem Jason laengst rechnete. Hier wird es gegen die Platte nachgezogen.
        for x in f["ausgaben"]:
            x["installiert"] = _tag(x["name"]) in inst_gb
        offen = [x for x in f["ausgaben"] if not x.get("installiert")] or f["ausgaben"]
        a = offen[-1] if offen else None
        if not a:
            continue
        gb = a["gb"] or 0
        aufgaben = _aufgaben_fuer(f, gb)
        wurzel = familie_wurzel(f["familie"])
        # 1. Ersatz: zuerst ein installiertes Modell derselben Familie in
        #    aehnlicher Groesse, sonst das heute beste fuer die Hauptaufgabe --
        #    aber nur, wenn das neue nicht drastisch kleiner ist (ein 3B-Modell
        #    ersetzt kein 27B-Modell, es kann es hoechstens entlasten).
        ersetzt, aelter = [], False
        v_neu = _version(f["familie"])
        gleich = [(n, g) for n, g in inst_gb.items()
                  if familie_wurzel(n.split(":")[0]) == wurzel and g > 1 and gb >= 0.6 * g]
        # Eine AELTERE Generation ersetzt keine neuere (qwen3.5 nicht qwen3.6).
        if v_neu is not None and gleich:
            neuer_inst = [n for n, _ in gleich if (_version(n.split(":")[0]) or 0) > v_neu]
            if neuer_inst:
                aelter, gleich = True, []
        if gleich:
            ersetzt = [min(gleich, key=lambda x: abs(x[1] - gb))[0]]
        elif not aelter:
            for auf in aufgaben:
                b = bester.get(auf)
                if b and gb >= 0.6 * inst_gb.get(b, 0):
                    ersetzt = [b]
                    break
        # 2. Rollen: wer heute mit dem ersetzten Modell rechnet, oder wessen
        #    Aufgabenart das neue Modell abdeckt -- aber nur, wenn es nicht
        #    deutlich kleiner ist als das, womit die Rolle heute rechnet.
        rollen, rollen_ids = [], []
        for t in team:
            eigen = t.get("modell") or modelle.get("arbeit")
            gross_genug = gb >= 0.6 * inst_gb.get(eigen, 0)
            if gross_genug and (eigen in ersetzt or (t.get("art") in aufgaben and t.get("art") != "allgemein")):
                rollen.append(f"{t['name']} ({t.get('titel') or ''})".replace(" ()", ""))
                rollen_ids.append("rolle:" + t["id"])
        if not aelter and (modelle.get("talk") in ersetzt or (_re.search(r"-a\d+b", a["name"]) and gb <= 30)):
            rollen.append("Talk (Gespräch mit dem Cockpit)")
            rollen_ids.append("vorgabe:talk")
        if aelter:
            rollen, rollen_ids = [], []
        # 3. Neue Rolle: eine Faehigkeit, fuer die es heute niemanden gibt.
        neue = None
        for x in ("decision", "vision", "audio"):
            if x in (f.get("faehigkeiten") or []) and not abgedeckt.get(x):
                st = _NEUE_ROLLE_STELLE[x]
                neue = {"name": _NEUE_ROLLE[x][0], "wofuer": _NEUE_ROLLE[x][1], "faehigkeit": x,
                        "stelle": st[0], "mit": st[1], "wie": st[2]}
                break
        f["einordnung"] = {"aufgaben": [namen[x] for x in aufgaben if x in namen], "ersetzt": ersetzt,
                           "rollen": list(dict.fromkeys(rollen)), "plaetze": list(dict.fromkeys(rollen_ids)),
                           "neue_rolle": neue, "aelter": aelter}


def _einordnung_text(f: dict[str, Any]) -> str:
    e = f.get("einordnung") or {}
    teile = []
    if e.get("ersetzt"):
        teile.append("Könnte " + ", ".join(e["ersetzt"]) + " ersetzen.")
    if e.get("rollen"):
        teile.append("Geeignet für " + ", ".join(e["rollen"]) + ".")
    if e.get("neue_rolle"):
        teile.append(f"Neue Rolle denkbar: {e['neue_rolle']['name']}.")
    return (" ".join(teile) + " ") if teile else ""
