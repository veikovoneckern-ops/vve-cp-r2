"""
YOUTUBE-KANAL ALS DOSSIER (17.10.2026).

Veiko an Neal: "in diesem Podcast sind viele Informationen zu KI enthalten,
schau dir alle Folgen an". Der Kanal hat 909 Folgen, je rund zwei Stunden --
das passt in keine Antwort und in kein Kontextfenster. Deshalb ein Auftrag im
Hintergrund (sichtbar und abbrechbar unter Current Actions):

  1. Folgenliste mit yt-dlp (nur die Liste, kein Video), neueste zuerst.
  2. Je Folge die Abschrift (quellen.abschrift), mit Pause dazwischen -- YouTube
     sperrt sonst mit 429. Jede Abschrift wird eine Unterlage (dateien), damit
     sie spaeter vollstaendig nachlesbar ist.
  3. Je Folge eine Kurzfassung durch das lokale Modell, ausgerichtet auf Veikos
     Fokus (seine Nachricht plus mitverlinkte Seiten, z. B. seine Fragenliste).
  4. Ein Dossier aus allen Kurzfassungen -- als Unterlage, beim Langlaeufer im
     Material und mit einem Hinweis, und eine Nachricht im Gespraech, aus dem
     der Auftrag kam.

Nicht alle 909: Vorgabe sind die neuesten 40; "die letzten 100 Folgen" in der
Nachricht nimmt 100, "alle" nimmt hoechstens MAX_FOLGEN -- und sagt das. Die
Laenge der Kurzfassungen richtet sich nach der Zahl, damit das Dossier in das
Material eines Langlaeufers passt (dort ~30.000 Zeichen je Stueck).
Folgen ohne Abschrift werden uebersprungen und gezaehlt (kein eigenes Whisper
ueber zwei Stunden Ton je Folge -- das waere ein eigener, viel laengerer Weg).
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

from . import db, llm, stab

VORGABE_FOLGEN = 40
MAX_FOLGEN = 200
PAUSE_SEK = 6
DOSSIER_ZEICHEN = 60000
JOBS: dict[str, dict[str, Any]] = {}
_TASKS: dict[str, asyncio.Task] = {}


def anzahl_aus(text: str) -> int:
    t = (text or "").lower()
    m = re.search(r"(\d{1,3})\s*(?:neueste[nr]?\s+|letzte[nr]?\s+)?(?:folgen|videos|episoden|podcasts)", t)
    if m:
        return max(1, min(MAX_FOLGEN, int(m.group(1))))
    if re.search(r"\balle\s+(?:folgen|videos|episoden)", t):
        return MAX_FOLGEN
    return VORGABE_FOLGEN


def _liste(url: str) -> tuple[str, list[dict[str, Any]], Any]:
    """(Kanalname, Folgen neueste zuerst) -- blockierend, im Thread aufrufen."""
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
    folgen = [{"id": e["id"], "titel": e.get("title") or e["id"], "dauer": e.get("duration")} for e in eintraege]
    # Die Liste endet bei MAX_FOLGEN; volle Kanaele melden dann keine echte Gesamtzahl.
    gesamt = len(folgen) if len(folgen) < MAX_FOLGEN else f"über {MAX_FOLGEN}"
    return (info or {}).get("channel") or (info or {}).get("uploader") or (info or {}).get("title") or "YouTube", folgen, gesamt


async def starten(url: str, fokus: str, ziel: dict[str, Any], anzahl: int, zusatz: str = "") -> dict[str, Any]:
    kanal, folgen, gesamt = await asyncio.to_thread(_liste, url)
    folgen = folgen[:anzahl]
    jid = db.neue_id("y")
    j = {"id": jid, "url": url, "kanal": kanal, "anzahl": len(folgen), "gesamt": gesamt, "fertig": 0, "ohne": 0,
         "stand": "laeuft", "schritt": "beginnt", "start": time.time(), "ziel": ziel, "fehler": None,
         "dossier_titel": f"YouTube-Dossier: {kanal} ({len(folgen)} Folgen)",
         # gemessen am 17.10.: knapp eine Minute je zweistuendiger Folge (Abschrift, Pause, Kurzfassung)
         "minuten": max(2, len(folgen))}
    JOBS[jid] = j
    _TASKS[jid] = asyncio.create_task(_lauf(j, folgen, fokus, zusatz))
    return j


def abbrechen(jid: str) -> bool:
    t = _TASKS.get(jid)
    if not t or t.done():
        return False
    t.cancel()
    JOBS[jid].update(stand="abgebrochen", schritt="von dir abgebrochen -- fertige Folgen bleiben als Unterlagen")
    return True


async def _lauf(j: dict[str, Any], folgen: list[dict[str, Any]], fokus: str, zusatz: str) -> None:
    from .quellen import abschrift
    ziel = j["ziel"]
    pid = ziel.get("projekt_id")
    je = max(500, min(2500, DOSSIER_ZEICHEN // max(1, len(folgen))))
    modell = await llm.modell_waehlen(llm.vorgabe("talk"), llm.vorgabe("arbeit"), "qwen3.6:27b")
    kurz: list[str] = []
    gesperrt = 0
    try:
        for i, f in enumerate(folgen):
            j["schritt"] = f"Folge {i + 1} von {len(folgen)}: Abschrift „{f['titel'][:70]}“"
            try:
                text = await asyncio.to_thread(abschrift, f["id"])
                gesperrt = 0
            except RuntimeError as e:
                if "blockiert" in str(e):
                    gesperrt += 1
                    if gesperrt >= 3:
                        raise RuntimeError("YouTube sperrt diesen Server gerade für Abschriften. Das Dossier enthält, was bis hierher kam.")
                    j["schritt"] = "YouTube bremst -- eine Minute Pause"
                    await asyncio.sleep(60)
                    continue
                j["ohne"] += 1
                await asyncio.sleep(PAUSE_SEK)
                continue
            url = f"https://www.youtube.com/watch?v={f['id']}"
            _datei(f"YouTube {kanal_kurz(j)} -- {f['titel']}.txt", f"{f['titel']}\n{url}\n\n{text}", pid, ziel.get("aufgabe_id"))
            if modell:
                j["schritt"] = f"Folge {i + 1} von {len(folgen)}: Kurzfassung"
                with llm.taetig(f"YouTube-Dossier: fasst Folge {i + 1} von {len(folgen)} zusammen"):
                    try:
                        k = await llm.chat(modell, "Du fasst Podcast-Abschriften für Veiko von Eckern auf Deutsch zusammen. Nur was in der Abschrift steht; "
                                                   "Zahlen, Namen und Aussagen genau, mit Sprecher, wo erkennbar. Keine Einleitung.",
                                           [{"role": "user", "content": f"WORAUF ES VEIKO ANKOMMT:\n{fokus[:3000]}\n\n"
                                             + (f"MITVERLINKT (z. B. seine Fragen):\n{zusatz[:6000]}\n\n" if zusatz else "")
                                             + f"FOLGE: {f['titel']}\n\nABSCHRIFT:\n{text[:100000]}\n\n"
                                             f"Fasse in höchstens {je} Zeichen zusammen, was diese Folge zu Veikos Thema und Fragen beiträgt: "
                                             "Kernaussagen als Stichpunkte, mit Zahlen und wer es sagt. Trägt sie nichts bei, schreib das in einem Satz."}],
                                           temperatur=0.2, denken=False, num_ctx=65536, timeout=900)
                    except llm.ModellFehler as e:
                        k = f"(Kurzfassung gescheitert: {e})"
                kurz.append(f"## {f['titel']}\n{url}\n\n{k.strip()[:je + 400]}")
            j["fertig"] += 1
            await asyncio.sleep(PAUSE_SEK)
        j["stand"] = "fertig"
    except asyncio.CancelledError:
        j["stand"] = "abgebrochen"
    except Exception as e:  # noqa: BLE001
        j.update(stand="fehler", fehler=str(e)[:300])
    if kurz:
        _abschluss(j, kurz)
    elif j["stand"] == "fertig":
        j.update(stand="fehler", fehler="Keine einzige Folge hatte eine Abschrift.")
    j["ende"] = time.time()
    j["schritt"] = {"fertig": "fertig", "abgebrochen": "abgebrochen", "fehler": j.get("fehler") or "gescheitert"}.get(j["stand"], j["stand"])


def kanal_kurz(j: dict[str, Any]) -> str:
    return re.sub(r"[^\w .-]", "", j["kanal"])[:40]


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
    kopf = (f"# {j['dossier_titel']}\n\nQuelle: {j['url']} -- {len(kurz)} Folgen ausgewertet"
            + (f", {j['ohne']} ohne Abschrift übersprungen" if j["ohne"] else "")
            + (f" (Lauf {j['stand']})" if j["stand"] != "fertig" else "") + ". Die vollständigen Abschriften liegen als eigene Unterlagen daneben.\n\n")
    did = _datei(j["dossier_titel"] + ".md", kopf + "\n\n".join(kurz), ziel.get("projekt_id"), ziel.get("aufgabe_id"))
    j["dossier_id"] = did
    meldung = (f"Das YouTube-Dossier ist da: {len(kurz)} Folgen von {j['kanal']} abgeschrieben und zusammengefasst"
               + (f" ({j['ohne']} ohne Abschrift)" if j["ohne"] else "") + ".")
    lid = ziel.get("langlauf_id")
    if lid:
        from . import langlauf
        l = langlauf.holen(lid)
        if l:
            d = l["daten"]
            d.setdefault("material", []).append({"art": "datei", "id": did})
            d.setdefault("hinweise", []).append({"zeit": time.time(), "von": "Cockpit",
                                                 "text": f"Neues Material: „{j['dossier_titel']}“ -- stütze Aussagen über diese Folgen darauf."})
            langlauf._speichern(l)
            meldung += " Es steht im Material dieses Langläufers. Sag mir, was daraus werden soll -- z. B. das neue Kapitel."
    if ziel.get("gespraech_id") and db.holen("gespraeche", ziel["gespraech_id"]):
        db.ausfuehren("INSERT INTO nachrichten (gespraech_id,rolle,text,daten,zeit) VALUES (?,?,?,?,?)",
                      (ziel["gespraech_id"], ziel.get("wer") or "system", meldung + " Du findest es auch unter den Unterlagen" + (" des Projekts." if ziel.get("projekt_id") else " (Anhänge)."),
                       json.dumps({"youtube": j["id"]}), time.time()))
        db.ausfuehren("UPDATE gespraeche SET geaendert=? WHERE id=?", (time.time(), ziel["gespraech_id"]))
