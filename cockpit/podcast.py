"""
PODCASTS ALS QUELLE (17.10.2026).

Anlass: YouTube sperrte am 17.10. die Abschrift-Schnittstelle fuer diesen
Server. Viele Kanaele (Peter Diamandis' "Moonshots" etwa) gibt es aber auch als
Audio-Podcast -- und der Ton liegt als MP3 beim Podcast-Anbieter, nicht bei
YouTube. Den laedt das Cockpit und schreibt ihn mit dem EIGENEN Whisper ab
(stimme.abschreiben_datei, Grafikkarte). Kein fremder Dienst bekommt etwas zu
sehen, und keine Sperre einer Plattform haelt es auf.

Gefunden wird ueber das oeffentliche Podcast-Verzeichnis von Apple (iTunes
Search API: frei, ohne Schluessel, liefert die RSS-Adresse jedes Podcasts und
einzelne Folgen zu einem Suchbegriff). Ein RSS-Link oder ein Apple-Podcasts-Link
in Veikos Nachricht geht direkt. Spotify-Links nicht: Spotify gibt keinen Feed
heraus -- dann ueber den Namen suchen.

Jede Abschrift wird eine Unterlage (wie bei YouTube); dieselbe Folge wird nie
ein zweites Mal geladen (Adresse in Zeile 2 der Unterlage).
"""
from __future__ import annotations

import asyncio
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from typing import Any

import httpx

ITUNES = "https://itunes.apple.com"
KOPF = {"User-Agent": "VvE-Cockpit/1.0 (+podcast reader)"}
MAX_MB = 400                     # eine Folge; groesser ist kein Podcast mehr
APPLE_ID = re.compile(r"podcasts\.apple\.com/.*/id(\d+)")
RSS_LINK = re.compile(r"\.(rss|xml)(\?|$)|/feed/?(\?|$)|feeds?\.", re.I)


async def suchen(name: str, anzahl: int = 5) -> list[dict[str, Any]]:
    """Podcasts zu einem Namen -> [{name, autor, feed, folgen}]."""
    async with httpx.AsyncClient(timeout=20, headers=KOPF) as c:
        r = await c.get(f"{ITUNES}/search", params={"term": name, "media": "podcast", "entity": "podcast", "limit": anzahl})
        r.raise_for_status()
    return [{"name": x.get("collectionName") or "", "autor": x.get("artistName") or "", "feed": x.get("feedUrl") or "",
             "folgen": x.get("trackCount")} for x in (r.json().get("results") or []) if x.get("feedUrl")]


async def folgen_suchen(begriff: str, anzahl: int = 8) -> list[dict[str, Any]]:
    """Einzelne Folgen zu einem Thema (quer ueber alle Podcasts) -> [{titel, audio, podcast, datum, dauer_min}]."""
    async with httpx.AsyncClient(timeout=20, headers=KOPF) as c:
        r = await c.get(f"{ITUNES}/search", params={"term": begriff, "media": "podcast", "entity": "podcastEpisode", "limit": anzahl})
        r.raise_for_status()
    aus = []
    for x in r.json().get("results") or []:
        audio = x.get("episodeUrl") or ""
        if audio:
            aus.append({"titel": x.get("trackName") or "", "audio": audio, "podcast": x.get("collectionName") or "",
                        "datum": (x.get("releaseDate") or "")[:10], "dauer_min": round((x.get("trackTimeMillis") or 0) / 60000)})
    return aus


async def feed_aus_link(url: str) -> str | None:
    m = APPLE_ID.search(url)
    if m:
        async with httpx.AsyncClient(timeout=20, headers=KOPF) as c:
            r = await c.get(f"{ITUNES}/lookup", params={"id": m.group(1), "entity": "podcast"})
        for x in r.json().get("results") or []:
            if x.get("feedUrl"):
                return x["feedUrl"]
        return None
    return url if RSS_LINK.search(url) else None


async def folgen(feed: str) -> tuple[str, list[dict[str, Any]]]:
    """(Podcastname, Folgen neueste zuerst) aus einem RSS-Feed."""
    async with httpx.AsyncClient(timeout=40, headers=KOPF, follow_redirects=True) as c:
        r = await c.get(feed)
        r.raise_for_status()
    try:
        wurzel = ET.fromstring(r.content)
    except ET.ParseError as e:
        raise RuntimeError(f"Der Feed ist kein lesbares RSS ({e}).")
    kanal = wurzel.find("channel")
    if kanal is None:
        raise RuntimeError("Der Feed enthält keinen Podcast.")
    name = (kanal.findtext("title") or "Podcast").strip()
    aus = []
    for it in kanal.findall("item"):
        enc = it.find("enclosure")
        audio = enc.get("url") if enc is not None else None
        if audio:
            aus.append({"id": audio, "titel": (it.findtext("title") or "").strip(), "audio": audio,
                        "datum": (it.findtext("pubDate") or "").strip()})
    if not aus:
        raise RuntimeError("Im Feed stehen keine Folgen mit Ton.")
    return name, aus


def gespeichert(audio: str) -> str | None:
    """Schon abgeschrieben? Dann aus den Unterlagen -- nie zweimal laden und rechnen."""
    from . import db
    for z in db.alle("SELECT text FROM dateien WHERE text LIKE ? ORDER BY erstellt DESC LIMIT 5", (f"%{audio}%",)):
        kopf, _, rest = (z.get("text") or "").partition("\n\n")
        zeilen = kopf.split("\n")
        if len(zeilen) == 2 and zeilen[1].strip() == audio and rest.strip():
            return rest
    return None


async def abschrift(audio: str) -> str:
    """Folge laden und mit dem eigenen Whisper abschreiben. Wirft RuntimeError."""
    alt = gespeichert(audio)
    if alt:
        return alt
    from . import llm, stimme
    fd, pfad = tempfile.mkstemp(suffix=".audio")
    os.close(fd)
    try:
        groesse = 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=120), headers=KOPF, follow_redirects=True) as c:
            async with c.stream("GET", audio) as r:
                if r.status_code >= 400:
                    raise RuntimeError(f"Ton nicht abrufbar (HTTP {r.status_code}).")
                with open(pfad, "wb") as f:
                    async for teil in r.aiter_bytes(1 << 20):
                        groesse += len(teil)
                        if groesse > MAX_MB * 1e6:
                            raise RuntimeError(f"Die Folge ist größer als {MAX_MB} MB.")
                        f.write(teil)
        with llm.taetig("Whisper schreibt eine Podcast-Folge ab"):
            text, _sprache = await asyncio.to_thread(stimme.abschreiben_datei, pfad)
    except httpx.HTTPError as e:
        raise RuntimeError(f"Ton nicht abrufbar ({e.__class__.__name__}).")
    finally:
        try:
            os.unlink(pfad)
        except OSError:
            pass
    if not text.strip():
        raise RuntimeError("Whisper hat in dieser Folge keine Sprache erkannt.")
    return text
