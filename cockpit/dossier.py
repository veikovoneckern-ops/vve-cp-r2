"""
RECHERCHE-DOSSIER: das gesamte Internet als Quelle (17.10.2026).

Veiko: "kuenftig auch andere Themen angehen, und dann sollen Informationen aus
YouTube, Podcasts, Webseiten -- also das gesamte Internet -- genutzt werden."
Ein Auftrag im Hintergrund (Current Actions, abbrechbar), EIN Weg fuer drei
Einstiege:

  kanal(url)    ein YouTube-Kanal oder eine Playlist: die neuesten N Folgen.
                Sperrt YouTube (17.10.: "IpBlocked"), sucht das Cockpit denselben
                Kanal als Audio-Podcast und macht dort mit eigenem Whisper weiter.
  podcast(feed) ein Podcast (RSS-Link oder Apple-Podcasts-Link): die neuesten N Folgen.
  thema(text)   ein Thema: das lokale Modell plant Suchanfragen; gelesen werden
                Webseiten (SearXNG), einzelne Podcast-Folgen (Apple-Verzeichnis,
                eigenes Whisper) und YouTube-Videos (gefunden ueber SearXNG "!yt",
                Abschrift nur ohne Sperre).

Je Quelle: Text holen (nie zweimal -- Abschriften liegen als Unterlagen),
lokale Kurzfassung auf Veikos Fokus, am Ende EIN Dossier als Unterlage --
beim Langlaeufer im Material und als Hinweis -- und eine Meldung im Gespraech,
aus dem der Auftrag kam. Alles lokal; kostet nichts ausser Rechenzeit.

Ersetzt youtube.py (die erste Fassung kannte nur YouTube-Kanaele).
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from typing import Any

from . import db, llm, stab

VORGABE_FOLGEN = 40
MAX_FOLGEN = 200
# Zwischen zwei YouTube-Abschriften (17.10.2026: 6 s fuehrten nach zwoelf Folgen zur Sperre).
PAUSE_YT = 35
DOSSIER_ZEICHEN = 60000
THEMA_WEB, THEMA_PODCAST, THEMA_YOUTUBE = 10, 4, 4
JOBS: dict[str, dict[str, Any]] = {}
_TASKS: dict[str, asyncio.Task] = {}

ANWEISUNG = (
    "RECHERCHE-DOSSIER: Will Veiko ausdrücklich, dass ein Thema gründlich im Internet recherchiert wird (Webseiten, "
    "Podcasts, YouTube -- „recherchier das gründlich“, „schau, was es dazu gibt“), dann schreib einen Satz dazu und "
    "danach den Block\n<<<RECHERCHE>>>\ndas Thema und worauf es ankommt, in ein bis drei Sätzen\n<<<ENDE>>>\n"
    "Das Cockpit startet dann einen Auftrag im Hintergrund (lokal, kostenlos, etwa 20 bis 40 Minuten) und meldet sich "
    "hier mit dem Dossier. Behaupte nicht, du hättest schon recherchiert. Für eine schnelle Frage reicht die normale Suche.")
BLOCK_RE = re.compile(r"<<<RECHERCHE>>>\s*(.*?)\s*(?:<<<ENDE>>>|$)", re.S)


def anzahl_aus(text: str) -> int:
    t = (text or "").lower()
    m = re.search(r"(\d{1,3})\s*(?:neueste[nr]?\s+|letzte[nr]?\s+)?(?:folgen|videos|episoden|podcasts)", t)
    if m:
        return max(1, min(MAX_FOLGEN, int(m.group(1))))
    if re.search(r"\balle\s+(?:folgen|videos|episoden)", t):
        return MAX_FOLGEN
    return VORGABE_FOLGEN


# ---------------------------------------------------------------- Quellen finden
def _yt_liste(url: str) -> tuple[str, list[dict[str, Any]], Any]:
    """(Kanalname, Folgen neueste zuerst, Gesamtzahl) -- blockierend. Nur die Liste,
    nicht die gesperrte Abschrift-Schnittstelle."""
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp ist nicht installiert (requirements.txt).")
    if re.search(r"youtube\.com/(@[^/?#]+|channel/[^/?#]+|c/[^/?#]+|user/[^/?#]+)/?$", url):
        url = url.rstrip("/") + "/videos"
    try:
        with yt_dlp.YoutubeDL({"extract_flat": True, "quiet": True, "skip_download": True, "playlistend": MAX_FOLGEN}) as y:
            info = y.extract_info(url, download=False)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Folgenliste nicht abrufbar: {str(e)[:200]}")
    eintraege = [e for e in (info or {}).get("entries") or [] if e and e.get("id")]
    if not eintraege:
        raise RuntimeError("Der Kanal liefert keine Folgen.")
    folgen = [{"quelle": "youtube", "id": e["id"], "titel": e.get("title") or e["id"],
               "url": f"https://www.youtube.com/watch?v={e['id']}"} for e in eintraege]
    gesamt = len(folgen) if len(folgen) < MAX_FOLGEN else f"über {MAX_FOLGEN}"
    name = (info or {}).get("channel") or (info or {}).get("uploader") or (info or {}).get("title") or "YouTube"
    return name, folgen, gesamt


async def _podcast_zum_kanal(name: str) -> dict[str, Any] | None:
    """Den Audio-Podcast zu einem YouTube-Kanal finden: ein Treffer, dessen Name
    oder Autor die tragenden Woerter des Kanalnamens enthaelt. Lieber keiner als
    ein falscher -- sonst landet ein fremder Podcast im Dossier."""
    from . import podcast
    woerter = [w for w in re.findall(r"\w{4,}", name.lower()) if w not in ("with", "show", "podcast", "official")]
    if not woerter:
        return None
    # Erst mit den tragenden Woertern allein: "Peter H. Diamandis" fand am 17.10. nichts,
    # "peter diamandis" fand "Moonshots with Peter Diamandis".
    for begriff in dict.fromkeys([" ".join(woerter), name]):
        try:
            treffer = await podcast.suchen(begriff, 8)
        except Exception:  # noqa: BLE001
            continue
        for t in treffer:
            hay = f"{t['name']} {t['autor']}".lower()
            if all(w in hay for w in woerter[-2:]):
                return t
    return None


def _schon_drin(titel: str, erledigt: list[str]) -> bool:
    """Ist diese Podcast-Folge dieselbe wie eine schon ausgewertete YouTube-Folge?
    Die Titel unterscheiden sich (YouTube "AI Solves 722 Math Problems …",
    Podcast "OpenAI Bulk-Solves 722 Math Problems …") -- deshalb ueber die
    tragenden Woerter: ab 40 % gemeinsamer Woerter (mindestens drei) gilt sie als dieselbe."""
    def woerter(t: str) -> set[str]:
        return {w for w in re.findall(r"\w{4,}|\d+", t.lower()) if w not in ("with", "this", "that", "from", "will")}
    a = woerter(titel)
    return bool(a) and any(len(a & woerter(e)) >= max(3, 0.4 * min(len(a), len(woerter(e)) or 1)) for e in erledigt)


async def _web_suchen(anfrage: str, anzahl: int) -> list[dict[str, Any]]:
    import httpx
    from .konfig import SEARX
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{SEARX}/search", params={"q": anfrage, "format": "json", "language": "de"})
            return [{"quelle": "web", "id": t["url"], "titel": t.get("title") or t["url"], "url": t["url"]}
                    for t in (r.json().get("results") or [])[:anzahl] if (t.get("url") or "").startswith("http")
                    and "youtube.com" not in t["url"]]
    except Exception:  # noqa: BLE001
        return []


async def _yt_suchen(anfrage: str, anzahl: int) -> list[dict[str, Any]]:
    import httpx
    from .konfig import SEARX
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{SEARX}/search", params={"q": "!yt " + anfrage, "format": "json"})
        aus = []
        for t in r.json().get("results") or []:
            m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", t.get("url") or "")
            if m:
                aus.append({"quelle": "youtube", "id": m.group(1), "titel": t.get("title") or m.group(1), "url": t["url"]})
        return aus[:anzahl]
    except Exception:  # noqa: BLE001
        return []


# ---------------------------------------------------------------- Auftraege anlegen
def _neu(art: str, titel: str, anzahl: int, ziel: dict[str, Any], **mehr: Any) -> dict[str, Any]:
    jid = db.neue_id("y")
    j = {"id": jid, "art": art, "anzahl": anzahl, "fertig": 0, "ohne": 0, "stand": "laeuft", "schritt": "beginnt",
         "start": time.time(), "ziel": ziel, "fehler": None, "dossier_titel": titel, "quellen": {}, "notizen": [], **mehr}
    JOBS[jid] = j
    return j


async def kanal(url: str, fokus: str, ziel: dict[str, Any], anzahl: int, zusatz: str = "") -> dict[str, Any]:
    from .quellen import sperre_bis
    name, folgen, gesamt = await asyncio.to_thread(_yt_liste, url)
    folgen = folgen[:anzahl]
    j = _neu("kanal", f"Dossier: {name} ({len(folgen)} Folgen)", len(folgen), ziel, url=url, kanal=name, gesamt=gesamt,
             minuten=max(2, round(len(folgen) * 1.3)))
    if sperre_bis() > time.time():
        j["notizen"].append("YouTube-Abschriften sind gerade gesperrt -- Folgen ohne vorhandene Abschrift kommen aus dem Podcast des Kanals.")
    _TASKS[j["id"]] = asyncio.create_task(_lauf(j, folgen, fokus, zusatz))
    return j


async def podcast_feed(feed: str, fokus: str, ziel: dict[str, Any], anzahl: int, zusatz: str = "") -> dict[str, Any]:
    from . import podcast
    name, folgen = await podcast.folgen(feed)
    folgen = [{"quelle": "podcast", **f} for f in folgen[:anzahl]]
    # Whisper braucht je Folge Minuten statt Sekunden.
    j = _neu("podcast", f"Dossier: {name} ({len(folgen)} Folgen)", len(folgen), ziel, url=feed, kanal=name,
             gesamt=len(folgen), minuten=max(3, len(folgen) * 6))
    _TASKS[j["id"]] = asyncio.create_task(_lauf(j, folgen, fokus, zusatz))
    return j


async def thema(text: str, ziel: dict[str, Any]) -> dict[str, Any]:
    titel = stab._kurz(re.sub(r"\s+", " ", text), 70)
    j = _neu("thema", f"Recherche-Dossier: {titel}", 0, ziel, url="", kanal=titel, gesamt=0, minuten=30)
    j["schritt"] = "plant die Suche"
    _TASKS[j["id"]] = asyncio.create_task(_thema_lauf(j, text))
    return j


async def _thema_lauf(j: dict[str, Any], text: str) -> None:
    from .quellen import sperre_bis
    modell = await llm.modell_waehlen(llm.vorgabe("talk"), llm.vorgabe("arbeit"), "qwen3.6:27b")
    plan: dict[str, Any] = {}
    if modell:
        try:
            plan = llm.json_aus(await llm.chat(modell, "", [{"role": "user", "content":
                f"THEMA: {text}\n\nPlane eine gründliche Internet-Recherche. Antworte NUR mit JSON: "
                '{"web": ["4 Suchanfragen, gemischt deutsch und englisch"], "podcast": ["2 englische Suchbegriffe für Podcast-Folgen"], '
                '"youtube": ["2 Suchbegriffe für Videos"]}'}], json_format=True, temperatur=0.2, denken=False, timeout=180)) or {}
        except llm.ModellFehler:
            plan = {}
    web = [q for q in (plan.get("web") or [text]) if isinstance(q, str)][:4]
    pod = [q for q in (plan.get("podcast") or [text]) if isinstance(q, str)][:2]
    yt = [q for q in (plan.get("youtube") or [text]) if isinstance(q, str)][:2]
    j["schritt"] = "sucht Quellen"
    gefunden: list[dict[str, Any]] = []
    for q in web:
        gefunden += await _web_suchen(q, 5)
    from . import podcast
    for q in pod:
        try:
            gefunden += [{"quelle": "podcast", "id": f["audio"], "titel": f"{f['podcast']}: {f['titel']}", "audio": f["audio"]}
                         for f in await podcast.folgen_suchen(q, 4) if 5 <= (f.get("dauer_min") or 30) <= 150]
        except Exception:  # noqa: BLE001
            j["notizen"].append("Das Podcast-Verzeichnis war nicht erreichbar.")
    if sperre_bis() > time.time():
        j["notizen"].append("YouTube-Abschriften sind gerade gesperrt -- Videos wurden ausgelassen.")
    else:
        for q in yt:
            gefunden += await _yt_suchen(q, 3)
    # je Art begrenzen, Doppelte raus
    zahl = {"web": THEMA_WEB, "podcast": THEMA_PODCAST, "youtube": THEMA_YOUTUBE}
    gesehen, auswahl = set(), []
    for g in gefunden:
        if g["id"] in gesehen or zahl[g["quelle"]] <= 0:
            continue
        gesehen.add(g["id"])
        zahl[g["quelle"]] -= 1
        auswahl.append(g)
    j["anzahl"] = len(auswahl)
    j["minuten"] = max(5, sum(6 if a["quelle"] == "podcast" else 1 for a in auswahl))
    if not auswahl:
        j.update(stand="fehler", fehler="Keine einzige Quelle gefunden.", ende=time.time(), schritt="nichts gefunden")
        return
    await _lauf(j, auswahl, text, "")


def abbrechen(jid: str) -> bool:
    t = _TASKS.get(jid)
    if not t or t.done():
        return False
    t.cancel()
    JOBS[jid].update(stand="abgebrochen", schritt="von dir abgebrochen -- aus dem Fertigen entsteht trotzdem ein Dossier")
    return True


# ---------------------------------------------------------------- Ablauf
async def _text(q: dict[str, Any]) -> str:
    """Text einer Quelle. Wirft RuntimeError; "Gesperrt" im Text = YouTube-Sperre."""
    if q["quelle"] == "youtube":
        from .quellen import abschrift
        return await asyncio.to_thread(abschrift, q["id"])
    if q["quelle"] == "podcast":
        from . import podcast
        return await podcast.abschrift(q["audio"])
    from .quellen import lesen
    r = await lesen(q["url"], 60000)
    if not r["text"]:
        raise RuntimeError(r["hinweis"] or "nicht lesbar")
    if r.get("titel"):
        q["titel"] = r["titel"]
    return r["text"]


def _schon_abgelegt(q: dict[str, Any]) -> bool:
    if q["quelle"] == "youtube":
        from .quellen import _gespeichert
        return _gespeichert(q["id"]) is not None
    if q["quelle"] == "podcast":
        from . import podcast
        return podcast.gespeichert(q["audio"]) is not None
    return True     # Webseiten werden nicht einzeln abgelegt -- sie stehen online


async def _auf_podcast_wechseln(j: dict[str, Any], rest: list[dict[str, Any]], erledigt: list[str]) -> list[dict[str, Any]]:
    from . import podcast
    p = await _podcast_zum_kanal(j.get("kanal") or "")
    if not p:
        j["notizen"].append("Einen Podcast zu diesem Kanal hat das Cockpit nicht gefunden.")
        return []
    try:
        _name, folgen = await podcast.folgen(p["feed"])
    except Exception as e:  # noqa: BLE001
        j["notizen"].append(f"Podcast „{p['name']}“ nicht lesbar: {e}")
        return []
    neu = [{"quelle": "podcast", **f} for f in folgen if not _schon_drin(f["titel"], erledigt)][:len(rest)]
    j["notizen"].append(f"Ab hier aus dem Podcast „{p['name']}“ (eigenes Whisper), weil YouTube Abschriften sperrt.")
    j["minuten"] = round((time.time() - j["start"]) / 60) + len(neu) * 6
    return neu


async def _lauf(j: dict[str, Any], quellen: list[dict[str, Any]], fokus: str, zusatz: str) -> None:
    from .quellen import sperre_bis
    ziel = j["ziel"]
    pid, aid = ziel.get("projekt_id"), ziel.get("aufgabe_id")
    modell = await llm.modell_waehlen(llm.vorgabe("talk"), llm.vorgabe("arbeit"), "qwen3.6:27b")
    kurz: list[str] = []
    erledigt: list[str] = []
    liste = list(quellen)
    # Bei bestehender YouTube-Sperre trotzdem der Reihe nach: schon geholte
    # Abschriften kommen ohne Anfrage aus den Unterlagen, und erst bei der ersten
    # fehlenden wechselt der Auftrag auf den Podcast (abschrift() fragt dabei
    # YouTube nicht, solange die Sperre gilt). Am 17.10. leitete die erste Fassung
    # bei Sperre ALLES um -- auch zwoelf Folgen, die schon vorlagen.
    try:
        i = 0
        while i < len(liste):
            q = liste[i]
            art = {"youtube": "YouTube", "podcast": "Podcast", "web": "Seite"}[q["quelle"]]
            j["schritt"] = f"{i + 1} von {len(liste)}: {art} „{q['titel'][:70]}“" + (" -- Whisper schreibt ab" if q["quelle"] == "podcast" else "")
            schon = _schon_abgelegt(q)
            try:
                text = await _text(q)
            except RuntimeError as e:
                if "Gesperrt" in str(e):
                    if j["art"] == "kanal":
                        neu = await _auf_podcast_wechseln(j, liste[i:], erledigt)
                        liste = liste[:i] + neu
                        j["anzahl"] = len(liste)
                        continue
                    # Thema: YouTube-Quellen auslassen, der Rest laeuft weiter.
                    j["notizen"].append("YouTube sperrte Abschriften -- die übrigen Videos wurden ausgelassen.")
                    liste = liste[:i] + [x for x in liste[i:] if x["quelle"] != "youtube"]
                    j["anzahl"] = len(liste)
                    continue
                j["ohne"] += 1
                i += 1
                continue
            adresse = q.get("audio") or q["url"]
            if q["quelle"] != "web" and not schon:
                _datei(f"{art} {_kurzname(j)} -- {q['titel']}.txt", f"{q['titel']}\n{adresse}\n\n{text}", pid, aid)
            erledigt.append(q["titel"])
            if modell:
                j["schritt"] = f"{i + 1} von {len(liste)}: Kurzfassung"
                je = max(500, min(2500, DOSSIER_ZEICHEN // max(1, len(liste))))
                with llm.taetig(f"Dossier: fasst Quelle {i + 1} von {len(liste)} zusammen"):
                    try:
                        k = await llm.chat(modell, "Du fasst Quellen für Veiko von Eckern auf Deutsch zusammen. Nur was in der Quelle steht; "
                                                   "Zahlen, Namen und Aussagen genau, mit Sprecher bzw. Autor, wo erkennbar. Keine Einleitung.",
                                           [{"role": "user", "content": f"WORAUF ES VEIKO ANKOMMT:\n{fokus[:3000]}\n\n"
                                             + (f"MITVERLINKT (z. B. seine Fragen):\n{zusatz[:6000]}\n\n" if zusatz else "")
                                             + f"QUELLE ({art}): {q['titel']}\n\nINHALT:\n{text[:100000]}\n\n"
                                             f"Fasse in höchstens {je} Zeichen zusammen, was diese Quelle zu Veikos Thema und Fragen beiträgt: "
                                             "Kernaussagen als Stichpunkte, mit Zahlen und wer es sagt. Trägt sie nichts bei, schreib das in einem Satz."}],
                                           temperatur=0.2, denken=False, num_ctx=65536, timeout=900)
                    except llm.ModellFehler as e:
                        k = f"(Kurzfassung gescheitert: {e})"
                kurz.append(f"## {art}: {q['titel']}\n{adresse}\n\n{k.strip()[:je + 400]}")
            j["fertig"] += 1
            i += 1
            if q["quelle"] == "youtube" and not schon:
                await asyncio.sleep(PAUSE_YT + random.uniform(0, 20))
        j["stand"] = "fertig"
    except asyncio.CancelledError:
        j["stand"] = "abgebrochen"
    except Exception as e:  # noqa: BLE001
        j.update(stand="fehler", fehler=str(e)[:300])
    if kurz:
        _abschluss(j, kurz)
    elif j["stand"] == "fertig":
        j.update(stand="fehler", fehler="Keine einzige Quelle ließ sich lesen.")
    j["ende"] = time.time()
    j["schritt"] = {"fertig": "fertig", "abgebrochen": "abgebrochen", "fehler": j.get("fehler") or "gescheitert"}.get(j["stand"], j["stand"])


def _kurzname(j: dict[str, Any]) -> str:
    return re.sub(r"[^\w .-]", "", j.get("kanal") or "")[:40]


def _datei(name: str, text: str, pid: str | None, aid: str | None) -> str:
    from .konfig import UPLOADS
    did = db.neue_id("d")
    name = re.sub(r'[\\/:*?"<>|]', "-", name)[:120]
    ziel = UPLOADS / f"{did}_{name}"
    ziel.write_text(text, encoding="utf-8")
    db.einfuegen("dateien", {"id": did, "name": name, "typ": "text/plain", "groesse": len(text.encode("utf-8")), "pfad": str(ziel),
                             "text": text[:120000], "projekt_id": pid, "aufgabe_id": aid, "erstellt": time.time()})
    return did


def _abschluss(j: dict[str, Any], kurz: list[str]) -> None:
    ziel = j["ziel"]
    titel = re.sub(r"\(\d+ Folgen\)", f"({len(kurz)} Quellen)", j["dossier_titel"]) if j["art"] == "kanal" or j["art"] == "podcast" else j["dossier_titel"]
    j["dossier_titel"] = titel
    kopf = (f"# {titel}\n\n" + (f"Ausgangspunkt: {j['url']}\n\n" if j.get("url") else "")
            + f"{len(kurz)} Quellen ausgewertet" + (f", {j['ohne']} nicht lesbar übersprungen" if j["ohne"] else "")
            + (f" (Lauf {j['stand']})" if j["stand"] != "fertig" else "") + ". Abschriften von Videos und Podcasts liegen als eigene Unterlagen daneben.\n"
            + "".join(f"\n- {n}" for n in j["notizen"]) + "\n\n")
    did = _datei(titel + ".md", kopf + "\n\n".join(kurz), ziel.get("projekt_id"), ziel.get("aufgabe_id"))
    j["dossier_id"] = did
    meldung = f"Das Dossier ist da: „{titel}“." + ("".join(" " + n for n in j["notizen"]) if j["notizen"] else "")
    lid = ziel.get("langlauf_id")
    if lid:
        from . import langlauf
        l = langlauf.holen(lid)
        if l:
            d = l["daten"]
            d.setdefault("material", []).append({"art": "datei", "id": did})
            d.setdefault("hinweise", []).append({"zeit": time.time(), "von": "Cockpit",
                                                 "text": f"Neues Material: „{titel}“ -- stütze Aussagen über diese Quellen darauf."})
            langlauf._speichern(l)
            meldung += " Es steht im Material dieses Langläufers. Sag mir, was daraus werden soll -- z. B. das neue Kapitel."
    meldung += " Du findest es auch unter den Unterlagen" + (" des Projekts." if ziel.get("projekt_id") else " (Anhänge).")
    if ziel.get("gespraech_id") and db.holen("gespraeche", ziel["gespraech_id"]):
        db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                      (ziel["gespraech_id"], ziel.get("wer") or "assistent", meldung, json.dumps({"dossier": j["id"]}), time.time()))
        db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), ziel["gespraech_id"]))


# ---------------------------------------------------------------- aus einer Antwort
async def aus_antwort(text: str, ziel: dict[str, Any]) -> tuple[str, list[str]]:
    """<<<RECHERCHE>>>-Block aus einer Modellantwort ausfuehren (Talk, Team-Chat,
    Board). Gibt den Text ohne Block und die Meldung fuer Veiko zurueck."""
    m = BLOCK_RE.search(text or "")
    if not m or not m.group(1).strip():
        return text, []
    j = await thema(m.group(1).strip(), ziel)
    rest = BLOCK_RE.sub("", text).strip()
    return rest, [f"Recherche gestartet: „{j['kanal']}“ -- Webseiten, Podcasts und Videos, im Hintergrund (Current Actions). "
                  "Das Dossier meldet sich hier, sobald es fertig ist."]
