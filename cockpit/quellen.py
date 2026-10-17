"""
VERLINKTES DIREKT LESEN (17.10.2026).

Anlass: Veiko schrieb Neal im Gespraech zum Langlaeufer zwei Links -- einen
YouTube-Kanal und eine Seite mit seinen eigenen Fragen -- und Neal musste
ehrlich sagen, dass er keinen davon sehen kann. Die Recherche (stab.recherche,
SearXNG) sucht nach STICHWORTEN; einen Link, den Veiko ausdruecklich gibt, hat
bis dahin niemand geoeffnet.

Hier wird er geoeffnet, IMMER (auch bei "Schnelle Antwort" und in Talk ohne
Globus): ein Link in Veikos Nachricht ist ein ausdruecklicher Auftrag, kein
Fall fuer die Abwaegung "braucht das Netzwissen?". Lokal, ohne fremden Dienst.

- Normale Seite: sichtbarer Text, und dazu Texte aus eingebetteten Skripten.
  Gemessen an veikovoneckern.org/…/zentrale-fragen-interaktiv: sichtbar waren
  3.154 Zeichen Menue, die 35 Fragen standen nur im Skript der Seite.
- PDF/Word/Excel/PowerPoint-Link: ueber denselben Leser wie Anhaenge (anhang.py).
- YouTube-Video: die Abschrift (youtube-transcript-api). yt-dlp bekam am 17.10.
  fuer Untertitel "429 Too Many Requests", diese Schnittstelle nicht.
- YouTube-Kanal oder Playlist: zu viele Folgen fuer eine Antwort (Peter
  Diamandis: 909, je rund zwei Stunden) -- das macht youtube.py im Hintergrund.
"""
from __future__ import annotations

import asyncio
import html as htmlmod
import json
import re
from typing import Any

import httpx

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")
MAX_LINKS = 5
SEITE_GRENZE = 40000
YT_VIDEO = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")
YT_SAMMLUNG = re.compile(r"youtube\.com/(?:@[^/?#\s]+|channel/[^/?#\s]+|c/[^/?#\s]+|user/[^/?#\s]+|playlist\?list=[^&#\s]+)")
KOPF = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36",
        "Accept-Language": "de,en;q=0.8"}


def links(text: str) -> list[str]:
    aus = []
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,;:!?")
        if u not in aus:
            aus.append(u)
    return aus[:MAX_LINKS]


def _skript_texte(h: str, schon: str) -> list[str]:
    """Saetze aus eingebetteten Skripten und Daten: Zeichenketten, die nach
    Sprache aussehen (Leerzeichen, Buchstaben, kein Code, keine Adresse)."""
    aus: list[str] = []
    for block in re.findall(r"(?is)<script[^>]*>(.*?)</script>", h):
        for roh in re.findall(r'"((?:[^"\\]|\\.){25,2000})"|\'((?:[^\'\\]|\\.){25,2000})\'|`([^`]{25,4000})`', block):
            s = next(x for x in roh if x)
            try:
                s = json.loads('"' + s.replace('"', '\\"') + '"') if "\\" in s else s
            except ValueError:
                pass
            s = re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", s))).strip()
            if (len(s) < 25 or s.count(" ") < 3 or re.search(r"https?://|function\s*\(|=>|\{|\};|var |const |\.js\b|\.css\b", s)
                    or sum(c.isalpha() for c in s) < 0.6 * len(s) or s in schon or s in aus):
                continue
            aus.append(s)
    return aus


def html_zu_text(h: str) -> str:
    from .stab import _html_zu_text
    sichtbar = _html_zu_text(h)
    eingebettet = _skript_texte(h, sichtbar)
    if eingebettet:
        sichtbar += "\n\nTEXTE AUS DEN EINGEBETTETEN DATEN DER SEITE (z. B. interaktive Inhalte):\n" + "\n".join("- " + s for s in eingebettet)
    return sichtbar


def _titel(h: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", h)
    return re.sub(r"\s+", " ", htmlmod.unescape(m.group(1))).strip()[:160] if m else ""


# YouTube sperrte am 17.10.2026 die Abschrift-Schnittstelle fuer diesen Server
# ("IpBlocked"), nachdem Tests und ein 200-Folgen-Auftrag in kurzer Zeit gut
# zwei Dutzend Abschriften geholt und nach der ersten Sperre weiter angeklopft
# hatten. Seither drei Riegel: (1) nach einer Sperre 24 Stunden GAR KEINE
# Abfrage mehr (jede weitere verlaengert die Sperre), (2) eine schon geholte
# Abschrift kommt aus den Unterlagen statt von YouTube, (3) youtube.py wartet
# zwischen Folgen deutlich laenger.
SPERRE_STUNDEN = 24


def zeit_text(ts: float) -> str:
    import datetime
    from zoneinfo import ZoneInfo
    return datetime.datetime.fromtimestamp(ts, ZoneInfo("Europe/Berlin")).strftime("%d.%m. %H:%M")


def sperre_bis() -> float:
    from . import db
    return float(db.einstellung("youtube_sperre_bis", 0) or 0)


def _gespeichert(video_id: str) -> str | None:
    from . import db
    # Eine gespeicherte Abschrift (youtube._datei) beginnt mit Titel, Adresse, Leerzeile.
    # Das Dossier enthaelt dieselbe Adresse auch -- deshalb muss sie GENAU in Zeile 2 stehen.
    url = f"https://www.youtube.com/watch?v={video_id}"
    for z in db.alle("SELECT text FROM dateien WHERE text LIKE ? ORDER BY erstellt DESC LIMIT 5", (f"%{url}%",)):
        kopf, _, rest = (z.get("text") or "").partition("\n\n")
        zeilen = kopf.split("\n")
        if len(zeilen) == 2 and zeilen[1].strip() == url and rest.strip():
            return rest
    return None


def abschrift(video_id: str) -> str:
    """Die Abschrift eines Videos (blockierend -- im Thread aufrufen). Wirft RuntimeError mit Klartextgrund."""
    import time as _t
    from . import db
    alt = _gespeichert(video_id)
    if alt:
        return alt
    bis = sperre_bis()
    if bis > _t.time():
        raise RuntimeError(f"YouTube hat diesen Server für Abschriften gesperrt; das Cockpit fragt bis "
                           f"{zeit_text(bis)} Uhr bewusst nicht (jede Anfrage verlängert die Sperre). Gesperrt")
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        raise RuntimeError("youtube-transcript-api ist nicht installiert (requirements.txt).")
    try:
        api = YouTubeTranscriptApi()
        try:
            t = api.fetch(video_id, languages=["de", "en"])
        except Exception as e1:  # noqa: BLE001
            # Nur wenn es schlicht keine de/en-Spur gibt, eine andere nehmen. Vorher
            # wurde auch bei einer Sperre ein zweites Mal gefragt.
            if "NoTranscript" not in e1.__class__.__name__:
                raise
            t = next(iter(api.list(video_id))).fetch()
    except Exception as e:  # noqa: BLE001
        name = e.__class__.__name__
        if "Blocked" in name or "TooMany" in name or "429" in str(e):
            db.einstellung_setzen("youtube_sperre_bis", _t.time() + SPERRE_STUNDEN * 3600)
            print(f"[quellen] YouTube sperrt Abschriften ({name}) -- {SPERRE_STUNDEN} h keine Abfrage", flush=True)
            raise RuntimeError(f"YouTube hat diesen Server gerade für Abschriften gesperrt; das Cockpit fragt jetzt "
                               f"{SPERRE_STUNDEN} Stunden lang nicht mehr. Gesperrt")
        if "Disabled" in name or "NoTranscript" in name:
            raise RuntimeError("Für dieses Video gibt es keine Abschrift.")
        raise RuntimeError(f"Abschrift nicht abrufbar ({name}).")
    return re.sub(r"\s+", " ", " ".join(s.text for s in t)).strip()


async def _yt_titel(c: httpx.AsyncClient, url: str) -> str:
    try:
        r = await c.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, timeout=10)
        return (r.json() or {}).get("title") or ""
    except (httpx.HTTPError, ValueError):
        return ""


async def lesen(url: str, grenze: int = SEITE_GRENZE) -> dict[str, Any]:
    """Ein Link -> {url, titel, text, art, hinweis}. Wirft nie; ein Fehler steht im hinweis."""
    m = YT_VIDEO.search(url)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=KOPF) as c:
        if m:
            titel = await _yt_titel(c, url)
            try:
                t = await asyncio.to_thread(abschrift, m.group(1))
                return {"url": url, "titel": titel or "YouTube-Video", "art": "youtube", "text": t[:grenze],
                        "hinweis": f"gekürzt auf {grenze} von {len(t)} Zeichen" if len(t) > grenze else ""}
            except RuntimeError as e:
                return {"url": url, "titel": titel or "YouTube-Video", "art": "youtube", "text": "", "hinweis": str(e).replace(" Gesperrt", "")}
        if YT_SAMMLUNG.search(url):
            return {"url": url, "titel": "YouTube-Kanal", "art": "youtube-kanal", "text": "", "hinweis": ""}
        try:
            r = await c.get(url)
        except httpx.HTTPError as e:
            return {"url": url, "titel": "", "art": "fehler", "text": "", "hinweis": f"nicht erreichbar ({e.__class__.__name__})"}
        if r.status_code >= 400:
            return {"url": url, "titel": "", "art": "fehler", "text": "", "hinweis": f"die Seite antwortet mit HTTP {r.status_code}"}
        typ = r.headers.get("content-type", "")
        if "html" in typ or not typ:
            t = html_zu_text(r.text)
            return {"url": url, "titel": _titel(r.text), "art": "seite", "text": t[:grenze],
                    "hinweis": f"gekürzt auf {grenze} von {len(t)} Zeichen" if len(t) > grenze else ""}
        if typ.startswith("text/"):
            return {"url": url, "titel": url.rsplit("/", 1)[-1], "art": "text", "text": r.text[:grenze], "hinweis": ""}
        try:
            from .anhang import _auswerten
            d = _auswerten(url.rsplit("/", 1)[-1].split("?")[0] or "datei", r.content)
            return {"url": url, "titel": url.rsplit("/", 1)[-1], "art": d.get("art") or "datei", "text": (d.get("text") or "")[:grenze], "hinweis": ""}
        except Exception as e:  # noqa: BLE001
            return {"url": url, "titel": "", "art": "fehler", "text": "", "hinweis": f"Inhalt nicht lesbar ({typ}): {getattr(e, 'detail', e)}"}


async def einbinden(text: str, ziel: dict[str, Any]) -> tuple[str, list[str]]:
    """Fuer Talk, Team-Chat und Board: alle Links aus Veikos Nachricht lesen.
    Gibt den Systemtext und Statuszeilen zurueck. Ein YouTube-Kanal startet
    youtube.py im Hintergrund (ziel: projekt_id, aufgabe_id, langlauf_id,
    gespraech_id, wer) -- die Antwort sagt Veiko, dass und wie lange."""
    urls = links(text)
    if not urls:
        return "", []
    gelesen = await asyncio.gather(*[lesen(u) for u in urls])
    teile, status = [], []
    fokus = URL_RE.sub("", text).strip()
    for i, q in enumerate(gelesen):
        if q["art"] == "youtube-kanal":
            from . import youtube
            try:
                j = await youtube.starten(q["url"], fokus, ziel, youtube.anzahl_aus(text),
                                          zusatz="\n\n".join(x["text"][:6000] for x in gelesen if x["text"]))
                status.append(f"YouTube: {j['anzahl']} Folgen werden im Hintergrund abgeschrieben")
                teile.append(f"[L{i + 1}] YOUTUBE-KANAL {q['url']}: Das Cockpit hat gerade einen Hintergrundauftrag gestartet "
                             f"(sichtbar unter Current Actions): die neuesten {j['anzahl']} von {j['gesamt']} Folgen werden abgeschrieben "
                             f"und lokal zusammengefasst, Dauer etwa {j['minuten']} Minuten. Daraus entsteht das Dossier „{j['dossier_titel']}“ "
                             + ("im Material dieses Langläufers. " if ziel.get("langlauf_id") else "als Unterlage. ")
                             + "Sobald es fertig ist, meldet sich das Cockpit hier im Gespräch. Sag Veiko das ehrlich. Schreibe den Text, "
                             "der auf den Folgen beruhen soll, NOCH NICHT und leg dafür noch keine Etappe an -- du kennst die Folgen erst, "
                             "wenn das Dossier da ist. Frag nicht nach, ob du anfangen sollst; das Cockpit startet bereits.")
            except RuntimeError as e:
                status.append(f"YouTube-Kanal nicht abrufbar: {e}")
                teile.append(f"[L{i + 1}] YOUTUBE-KANAL {q['url']}: konnte nicht gelesen werden ({e}). Sag Veiko das so.")
            continue
        if q["text"]:
            status.append(f"gelesen: {q['titel'] or q['url']} ({len(q['text']):,} Zeichen)".replace(",", "."))
            teile.append(f"[L{i + 1}] {q['titel'] or ''} — {q['url']}" + (f" ({q['hinweis']})" if q["hinweis"] else "")
                         + f"\n{q['text']}")
        else:
            status.append(f"nicht lesbar: {q['url']} -- {q['hinweis']}")
            teile.append(f"[L{i + 1}] {q['url']}: NICHT LESBAR ({q['hinweis']}). Sag Veiko das so, statt über den Inhalt zu raten.")
    return ("VON VEIKO VERLINKT -- das Cockpit hat die Links gerade selbst geöffnet. Stütze dich darauf und zitiere als [L1], [L2]. "
            "Behaupte nicht, du könntest Links nicht öffnen: der Inhalt steht hier.\n\n" + "\n\n".join(teile)), status
