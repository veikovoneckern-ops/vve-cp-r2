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


def _laden(geraet: str):
    if geraet == "cuda":
        _cuda_vorladen()
    from faster_whisper import WhisperModel  # erst hier: ohne Paket laeuft der Rest weiter
    typ = "float16" if geraet == "cuda" else "int8"
    return WhisperModel(WHISPER_MODELL, device=geraet, compute_type=typ)


def _modell(geraet: str):
    with _mlock:
        if geraet not in _modelle:
            _modelle[geraet] = _laden(geraet)
        return _modelle[geraet]


def verfuegbar() -> dict[str, Any]:
    try:
        import faster_whisper  # noqa: F401
        return {"whisper": True, "modell": WHISPER_MODELL, "geladen": list(_modelle)}
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


def _erkennen(pfad: str, vorlage: str) -> tuple[str, str]:
    reihenfolge = [WHISPER_GERAET, "cpu"] if WHISPER_GERAET != "cpu" else ["cpu"]
    letzter: Exception | None = None
    for geraet in reihenfolge:
        try:
            m = _modell(geraet)
            segmente, _info = m.transcribe(pfad, language="de", vad_filter=True, beam_size=5,
                                           initial_prompt=vorlage or None)
            return " ".join(s.text.strip() for s in segmente).strip(), geraet
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


async def sprechen(text: str) -> bytes:
    text = (text or "").strip()[:4000]
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{PIPER}/v1/audio/speech",
                         json={"model": "tts-1", "input": text, "voice": PIPER_STIMME, "response_format": "mp3"})
    if r.status_code >= 400:
        raise RuntimeError(f"Piper antwortet {r.status_code}")
    return r.content
