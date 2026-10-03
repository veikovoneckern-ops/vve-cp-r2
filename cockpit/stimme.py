"""
HOEREN UND SPRECHEN -- Whisper im eigenen Prozess, Piper ueber seinen Dienst.

Whisper laeuft hier selbst (faster-whisper), weil die neue Fassung den
Cockpit-Token des alten Backends nicht kennt und dessen /api/dialog/hoeren
deshalb nicht nutzen kann. Das Modell liegt schon im Cache von vveadmin.

Zwei Lehren aus dem alten dialog.py sind eingebaut:
  - Die Endung der Aufnahme kommt aus ihrer SIGNATUR, nicht aus dem
    Dateinamen. Safari nimmt MP4 auf, nicht WebM; ein falscher Name liess
    PyAV am falschen Demuxer scheitern ("auf dem iPad geht Sprache nicht").
  - Scheitert die Erkennung auf der Karte (cuBLAS fehlte zeitweise), geht
    der zweite Versuch fest auf die CPU, statt es auf der Karte erneut zu
    probieren.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import threading
from typing import Any

import httpx

from .konfig import PIPER, PIPER_STIMME, WHISPER_GERAET, WHISPER_MODELL

_modelle: dict[str, Any] = {}
_mlock = threading.Lock()


_cuda_vorgeladen = False


def _cuda_vorladen() -> None:
    """cuBLAS/cuDNN aus den Pip-Paketen (site-packages/nvidia/*/lib) vorab laden.
    ctranslate2 sucht sie nur im Systempfad und meldet sonst "libcublas.so.12
    is not found" -- obwohl die Datei in der eigenen Umgebung liegt (gemessen
    am 01.10.2026). Mit RTLD_GLOBAL geladen, findet es sie danach."""
    global _cuda_vorgeladen
    if _cuda_vorgeladen:
        return
    _cuda_vorgeladen = True
    import ctypes
    import glob
    import site
    wurzeln = site.getsitepackages() + [site.getusersitepackages()]
    for muster in ("libcublasLt.so.*", "libcublas.so.*", "libcudnn*.so.*"):
        for w in wurzeln:
            for pfad in sorted(glob.glob(os.path.join(w, "nvidia", "*", "lib", muster))):
                try:
                    ctypes.CDLL(pfad, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


_geladen_als: dict[str, str] = {}


def _laden(geraet: str):
    if geraet == "cuda":
        _cuda_vorladen()
    from faster_whisper import WhisperModel  # erst hier: ohne Paket laeuft der Rest weiter
    typ = "float16" if geraet == "cuda" else "int8"
    # Nur was schon auf der Platte liegt (local_files_only): das erste Herunterladen
    # von large-v3-turbo dauerte ueber WLAN mehrere Minuten -- so lange darf keine
    # Spracheingabe haengen. Fehlt das gewuenschte Modell, nimmt Whisper das beste
    # vorhandene und laedt das gewuenschte im Hintergrund nach.
    letzter: Exception | None = None
    for name in dict.fromkeys([WHISPER_MODELL, "medium", "small"]):
        try:
            m = WhisperModel(name, device=geraet, compute_type=typ, local_files_only=True)
            _geladen_als[geraet] = name
            if name != WHISPER_MODELL:
                _nachladen_starten()
            return m
        except Exception as e:  # noqa: BLE001
            letzter = e
    try:
        m = WhisperModel("small", device=geraet, compute_type=typ)  # gar nichts da: das kleinste holen
        _geladen_als[geraet] = "small"
        _nachladen_starten()
        return m
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Kein Whisper-Modell ladbar: {e or letzter}") from e


_nachladen = {"laeuft": False}


def _nachladen_starten() -> None:
    if _nachladen["laeuft"]:
        return
    _nachladen["laeuft"] = True

    def lauf():
        try:
            from faster_whisper.utils import download_model
            download_model(WHISPER_MODELL)
            with _mlock:
                _modelle.clear()  # naechste Erkennung laedt das bessere Modell
        except Exception:  # noqa: BLE001 -- dann bleibt es beim vorhandenen
            pass
        finally:
            _nachladen["laeuft"] = False
    threading.Thread(target=lauf, daemon=True).start()


def _modell(geraet: str):
    with _mlock:
        if geraet not in _modelle:
            _modelle[geraet] = _laden(geraet)
        return _modelle[geraet]


def verfuegbar() -> dict[str, Any]:
    try:
        import faster_whisper  # noqa: F401
        return {"whisper": True, "modell": WHISPER_MODELL,
                "geladen": [f"{g} ({_geladen_als.get(g, '?')})" for g in _modelle]}
    except ImportError:
        return {"whisper": False, "grund": "faster-whisper ist in dieser Python-Umgebung nicht installiert."}


def _endung(roh: bytes) -> str:
    if roh[:4] == b"\x1aE\xdf\xa3":
        return ".webm"
    if roh[4:8] == b"ftyp":
        return ".mp4"
    if roh[:4] == b"OggS":
        return ".ogg"
    if roh[:4] == b"RIFF" and roh[8:12] == b"WAVE":
        return ".wav"
    if roh[:3] == b"ID3" or (len(roh) > 1 and roh[0] == 0xFF and roh[1] & 0xE0 == 0xE0):
        return ".mp3"
    return ".webm"


def _plappert_nach(text: str, vorlage: str) -> bool:
    """Besteht die Erkennung fast nur aus Woertern der Hoerhilfe, in Listenform?"""
    import re
    woerter = re.findall(r"\w+", text.lower())
    if len(woerter) < 3 or text.count(",") < 2:
        return False
    aus_vorlage = set(re.findall(r"\w+", vorlage.lower()))
    return sum(w in aus_vorlage for w in woerter) / len(woerter) > 0.85


def _erkennen(pfad: str, vorlage: str) -> tuple[str, str]:
    reihenfolge = [WHISPER_GERAET, "cpu"] if WHISPER_GERAET != "cpu" else ["cpu"]
    letzter: Exception | None = None
    for geraet in reihenfolge:
        try:
            m = _modell(geraet)
            segmente, _info = m.transcribe(pfad, language="de", vad_filter=True, beam_size=5,
                                           initial_prompt=vorlage or None)
            text = " ".join(s.text.strip() for s in segmente).strip()
            if vorlage and _plappert_nach(text, vorlage):
                # Gemessen am 03.10.2026 mit medium: statt des Satzes kam nur die
                # Hoerhilfe-Liste zurueck. Dann ohne Hoerhilfe noch einmal.
                segmente, _info = m.transcribe(pfad, language="de", vad_filter=True, beam_size=5)
                text = " ".join(s.text.strip() for s in segmente).strip()
            return text, geraet
        except Exception as e:  # noqa: BLE001 -- jeder Fehler auf der Karte -> CPU versuchen
            letzter = e
            with _mlock:
                _modelle.pop(geraet, None)
    raise RuntimeError(f"Spracherkennung fehlgeschlagen: {letzter}")


async def hoeren(roh: bytes, vorlage: str = "") -> dict[str, Any]:
    if len(roh) < 800:
        return {"text": "", "hinweis": "Die Aufnahme war zu kurz."}
    fd, pfad = tempfile.mkstemp(suffix=_endung(roh))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(roh)
        text, geraet = await asyncio.to_thread(_erkennen, pfad, vorlage)
    finally:
        try:
            os.unlink(pfad)
        except OSError:
            pass
    return {"text": text, "geraet": geraet,
            "hinweis": "" if text else "Nichts verstanden. War die Aufnahme still?"}


# ------------------------------------------------------------ Aussprache
# Piper spricht mit einer DEUTSCHEN Stimme und liest jedes Wort nach deutschen
# Regeln: "Team" wird "Te-am", "Briefing" wird "Brie-fing" (Veiko, 03.10.).
# Deshalb werden englische Woerter vor dem Vorlesen in deutsche Lautschrift
# umgeschrieben. Nur fuers Ohr -- der Text im Gespraech bleibt unveraendert.
# Ergaenzen geht ohne Code: Memory-Eintraege der Art "aussprache"
# (Begriff = wie es geschrieben wird, Bedeutung = wie es klingen soll),
# auch per Talk ("merk dir: Slides spricht man Slaids").
AUSSPRACHE = {
    "Advisory Board": "Äd-weisori Bord", "Kill Switch": "Kill-Switsch", "Safety Shutdown": "Säifti Schatt-daun",
    "Use Cases": "Jus Käises", "Use Case": "Jus Käis", "Red Team": "Redd Tiem", "Head of": "Hedd of",
    "Creative Director": "Kri-äitiw Dairektor", "Video Producer": "Video Produhsser", "Cockpit Engineer": "Cockpit Endschinier",
    "Teams": "Tiems", "Team": "Tiem", "Board": "Bord", "Briefing": "Brieefing", "Inbox": "Inn-Box", "Capture": "Käptscher",
    "Cases": "Käises", "Case": "Käis", "Memory": "Memmori", "Talk": "Tohk", "Projects": "Prodschekts",
    "WatchDog": "Wotsch-Dogg", "BrainStrom": "Bräin-Strom", "Brainstorming": "Bräin-storming", "ExO": "Ex-O",
    "Shutdown": "Schatt-daun", "Reboot": "Ribuht", "Safety": "Säifti", "Updates": "Ap-däits", "Update": "Ap-däit",
    "Downloads": "Daun-louds", "Download": "Daun-loud", "Upload": "Ap-loud", "Workshops": "Wörk-schopps", "Workshop": "Wörk-schopp",
    "Meetings": "Mietings", "Meeting": "Mieting", "Feedback": "Fied-bäck", "Deadline": "Dedd-lein", "Masterclass": "Master-klahs",
    "Engineer": "Endschinier", "Leadership": "Lieder-schipp", "Lead": "Lied", "Business": "Bisness", "Learning": "Lörning",
    "Story": "Stori", "Chat": "Tschätt", "Strategy": "Strätedschi", "Publishing": "Pablisching", "Workflow": "Wörk-flou",
    "Tools": "Tuhls", "Tool": "Tuhl", "Slides": "Slaids", "Keynote": "Kie-nout", "Pitch": "Pitsch", "Server": "Sörver",
    "Software": "Soft-wär", "Hardware": "Hard-wär", "online": "onn-lein", "offline": "off-lein", "E-Mail": "I-Mäil",
    "Mail": "Mäil", "okay": "o-käi", "Shelly": "Schelli", "PMO": "Pe Em O", "Jason": "Dschäisen", "Clayton": "Kläiten",
    "Neal": "Niel", "Annie": "Änni", "Ridley": "Riddli", "Elon": "Ielonn", "Agent": "Äidschent", "Agents": "Äidschents",
}


def aussprache(text: str) -> str:
    import re
    eintraege = dict(AUSSPRACHE)
    try:
        from . import db
        for g in db.alle("SELECT begriff, bedeutung FROM gedaechtnis WHERE art='aussprache' AND bestaetigt=1"):
            if g["begriff"] and g["bedeutung"]:
                eintraege[g["begriff"]] = g["bedeutung"]
    except Exception:  # noqa: BLE001 -- ohne Memory gilt die feste Liste
        pass
    # EIN Durchgang, laengere zuerst ("Advisory Board" vor "Board") -- nacheinander
    # ersetzt koennte eine Lautschrift selbst noch einmal ersetzt werden.
    klein = {k.lower(): v for k, v in eintraege.items()}
    muster = re.compile(r"(?<![\wÄÖÜäöüß-])(" + "|".join(re.escape(w) for w in sorted(eintraege, key=len, reverse=True)) +
                        r")(?![\wÄÖÜäöüß])", re.IGNORECASE)
    return muster.sub(lambda m: klein.get(m.group(1).lower(), m.group(1)), text)


async def sprechen(text: str) -> bytes:
    text = aussprache((text or "").strip()[:4000])
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{PIPER}/v1/audio/speech",
                         json={"model": "tts-1", "input": text, "voice": PIPER_STIMME, "response_format": "mp3"})
    if r.status_code >= 400:
        raise RuntimeError(f"Piper antwortet {r.status_code}")
    return r.content
