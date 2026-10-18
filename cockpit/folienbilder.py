"""
BILDER FUER PRAESENTATIONEN -- je Folie ein Bild aus ComfyUI, in der Vorschau
UND in der PowerPoint-Datei.

Anlass (Veiko, 16.10.2026): "wenn ich eine ppt erstellen lasse und Bilder drin
haben will, funktioniert das nicht". Annies Folien trugen zwar Zeilen wie
"Bildbeschreibung: …", aber nichts machte daraus ein Bild -- sie standen als
Text auf der Folie.

Wie es laeuft:
  - Jede Folie darf EINE Zeile "Bild: <Beschreibung>" tragen (auch
    "Bildbeschreibung:", "Visual:"). Das ist die Vorgabe an Annie (stab.FORMEN)
    und zugleich alles, was hier gelesen wird.
  - Gerechnet wird mit derselben Bildvorlage wie im Gespraech (medien.py,
    Z-Image Turbo auf der zweiten Karte, ~15 s je Bild), Querformat.
  - Abgelegt wird je Bild unter einem SCHLUESSEL AUS DER BESCHREIBUNG, nicht
    unter der Foliennummer. Wird die Praesentation im Ergebnisfenster
    ueberarbeitet, bleiben unveraenderte Bilder gueltig, eine geaenderte
    Beschreibung zeigt bis zum Neurechnen kein falsches Bild -- es braucht
    dafuer keine zweite Buchfuehrung.
  - Als JPEG in 1280 Punkt Breite (Pillow kommt mit python-pptx ohnehin mit):
    die Ansicht bettet die Bilder ein (der abgeschottete Rahmen der Vorschau
    darf keine Anfragen mit Anmeldung stellen), und sieben PNG zu je 2 MB
    waeren eine 14-MB-Seite.

Kostet nur Rechenzeit auf der eigenen Hardware -- laeuft deshalb ohne Rueckfrage.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx

from . import db, llm
from .konfig import MEDIEN_DIR

BILD_ZEILE = re.compile(r"^\s*[-*•]?\s*\**\s*(bildbeschreibung|bildidee|bild|visual|image)\b[^:]{0,30}:\s*\**\s*(.+)$", re.I)
# Bis 17.10.2026 ging die DEUTSCHE Beschreibung samt "ohne Schrift" an Z-Image --
# und das Modell malte deutsche Woerter als verstuemmelte Schrift ins Bild
# ("Ein vied eet Keim", "Verbüћgt ezer Mensch" in der ExO-Praesentation).
# Jetzt: das lokale Modell schreibt fuer ALLE Bilder einer Praesentation auf
# einmal englische Bildanweisungen in EINEM Stil (_kunstregie), gerechnet wird
# mit Qwen-Image und einer Liste dessen, was NICHT ins Bild soll.
ZUSATZ = (", premium editorial illustration for a keynote presentation, cinematic lighting, clean composition, "
          "generous negative space, high detail, purely pictorial, wordless")   # nicht "no text": das Wort zieht Schrift an
NEGATIV = ("text, letters, words, typography, caption, title, label, signage, watermark, logo, signature, numbers, "
           "blurry, low quality, deformed, distorted hands, extra fingers, cluttered")
VORLAGE, VORLAGE_ERSATZ = "qwen", "z-image"
# Jedes fertige Bild wird ANGESEHEN, bevor es zaehlt (Veiko, 17.10.2026: "die
# Bilder werden immer noch mit massiven Fehlern generiert ... viele Schreibfehler").
# Eine Anweisung "no text" allein haelt ein Bildmodell nicht zuverlaessig ein;
# ein lokales Modell, das sehen kann, prueft auf Schrift und grobe Fehler, und das
# Bild wird mit neuem Zufallswert neu gerechnet -- hoechstens VERSUCHE Mal.
PRUEF_MODELL = "gemma4:e4b"
VERSUCHE = 3
LAUFEND: dict[str, asyncio.Task] = {}
MAX_BILDER = 20


def folien_roh(md: str) -> list[str]:
    """Die Folien als Rohtext -- dieselbe Aufteilung fuer Vorschau, PowerPoint
    und Bilder, sonst landet ein Bild auf der falschen Folie."""
    teile = [t for t in re.split(r"(?m)^\s*---+\s*$", md or "") if t.strip()]
    if len(teile) <= 1:
        teile = [t for t in re.split(r"(?m)^(?=#{1,2}\s)", md or "") if t.strip()]
    return teile


def bild_text(roh: str) -> str:
    """Die Beschreibung aus einer Bildzeile, ohne Markdown-Reste. EINE Stelle,
    weil der Dateischluessel daraus entsteht: weicht das Saeubern beim Rechnen
    und beim Einbauen ab, findet der Einbau das Bild nie."""
    return re.sub(r"\*\*|__", "", roh).strip().strip("*").strip()[:900]


def bild_prompt(folie: str) -> str | None:
    for z in folie.splitlines():
        m = BILD_ZEILE.match(z)
        if m and len(bild_text(m.group(2))) >= 8:
            return bild_text(m.group(2))
    return None


# Wo Bilder gerechnet werden: Folien und alles, was als Text/Word ausgegeben
# wird. Webseiten bringen ihr eigenes HTML mit, Videos haben ein Drehbuch.
MIT_BILDERN = ("praesentation", "text", "aufstellung", "konzept", "dokument")


def prompts(md: str, form: str = "praesentation") -> list[str | None]:
    """Praesentation: ein Bild je Folie (das erste der Folie). Sonst: jede
    Bildzeile im Text, an ihrer Stelle."""
    if form == "praesentation":
        return [bild_prompt(f) for f in folien_roh(md)]
    return [bild_text(m.group(2)) for z in (md or "").splitlines()
            if (m := BILD_ZEILE.match(z)) and len(bild_text(m.group(2))) >= 8]


def _schluessel(prompt: str) -> str:
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12]


def datei(eid: str, prompt: str) -> Path:
    return MEDIEN_DIR / f"{eid}-f{_schluessel(prompt)}.jpg"


def vorhanden(eid: str, prompt: str | None) -> bytes | None:
    if not prompt:
        return None
    p = datei(eid, prompt)
    return p.read_bytes() if p.is_file() else None


def daten_uri(roh: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(roh).decode("ascii")


# ------------------------------------------------------------ Stand am Ergebnis
def _stand_setzen(eid: str, **werte: Any) -> None:
    e = db.holen("ergebnisse", eid) or {}
    m = e.get("medien") if isinstance(e.get("medien"), dict) else {}
    s = dict(m.get("folienbilder") or {})
    s.update(werte, geaendert=time.time())
    m["folienbilder"] = s
    db.ausfuehren("UPDATE ergebnisse SET medien=? WHERE id=?", (json.dumps(m, ensure_ascii=False), eid))


def stand(e: dict[str, Any]) -> dict[str, Any] | None:
    """Was die Oberflaeche braucht: wie viele Bilder gewuenscht sind, wie viele
    es schon gibt, und ob gerade gerechnet wird. None bei Formen ohne Bilder."""
    if e.get("form") not in MIT_BILDERN:
        return None
    ps = [p for p in prompts(e.get("inhalt") or "", e["form"]) if p]
    s = dict(((e.get("medien") if isinstance(e.get("medien"), dict) else {}) or {}).get("folienbilder") or {})
    if s.get("stand") == "rechnet" and e["id"] not in LAUFEND:
        s["stand"] = "abgebrochen"
    s["gewuenscht"] = len(ps)
    s["vorhanden"] = sum(1 for p in ps if datei(e["id"], p).is_file())
    return s


# ------------------------------------------------------------ rechnen
def _als_jpeg(png: bytes) -> bytes:
    from PIL import Image
    b = Image.open(BytesIO(png)).convert("RGB")
    if b.width > 1280:
        b = b.resize((1280, round(b.height * 1280 / b.width)))
    out = BytesIO()
    b.save(out, "JPEG", quality=84, optimize=True)
    return out.getvalue()


PRUEF_FRAGE = ("Inspect this image carefully. Answer ONLY with JSON: "
               '{"text": true or false, "defekt": true or false, "was": "short reason in German"}. '
               '"text" is true if ANY letters, words, numbers, captions, labels, signs, logos, code, or pseudo-writing '
               "appear anywhere, even small or blurry. \"defekt\" is true if there are clearly deformed hands, faces "
               "or bodies, melted or broken objects, or the image is mostly empty or muddy.")


async def bild_pruefen(png: bytes) -> str | None:
    """Der Mangel in Klartext, oder None, wenn das Bild in Ordnung ist -- oder wenn
    nicht geprueft werden konnte (dann zaehlt das Bild, statt alles anzuhalten)."""
    modell = await llm.modell_waehlen(PRUEF_MODELL)
    if not modell:
        return None

    def klein() -> str:
        from PIL import Image
        b = Image.open(BytesIO(png)).convert("RGB")
        b.thumbnail((896, 896))
        out = BytesIO()
        b.save(out, "JPEG", quality=85)
        return base64.b64encode(out.getvalue()).decode("ascii")
    try:
        bild = await asyncio.to_thread(klein)
        d = llm.json_aus(await llm.chat(modell, "", [{"role": "user", "content": PRUEF_FRAGE, "images": [bild]}],
                                        json_format=True, temperatur=0, denken=False, num_ctx=4096, timeout=120)) or {}
    except (llm.ModellFehler, OSError, ValueError):
        return None
    if d.get("text") is True:
        return "Schrift im Bild" + (f" ({d.get('was')})" if d.get("was") else "")
    if d.get("defekt") is True:
        return "grober Bildfehler" + (f" ({d.get('was')})" if d.get("was") else "")
    return None


_ENTSCHAERFEN = re.compile(r"\b(digital|data|code|coding|binary|matrix|screens?|monitors?|displays?|interfaces?|holograms?|"
                           r"holographic|dashboards?|charts?|graphs?|documents?|papers?|books?|quote|quotation|symbols?)\b", re.I)
RUHIG = (". Calm, uncluttered background: soft gradients, light and atmosphere only -- no screens, no panels, "
         "no glyphs, digits or patterns that could look like writing")


async def medien_bild(c: httpx.AsyncClient, prompt: str, vorlage: str, breite: int, hoehe: int) -> bytes:
    from . import medien
    return await medien.comfy_bild(c, prompt, vorlage, breite, hoehe, NEGATIV)


async def bild_ohne_fehler(c: httpx.AsyncClient, prompt: str, breite: int = 1344, hoehe: int = 768,
                           melden=None) -> tuple[bytes, str | None]:
    """Ein Bild rechnen, ansehen, bei Schrift oder groben Fehlern neu rechnen.
    Gibt das Bild und -- falls auch der letzte Versuch einen Mangel hatte -- den
    Mangel zurueck. EIN Weg fuer Folien, Texte und Video (video.py)."""
    png, mangel = b"", None
    for versuch in range(VERSUCHE):
        # Ab dem zweiten Versuch entschaerft: Woerter wie "digital", "data", "screen"
        # rufen Bildschirme mit Zeichenkolonnen hervor (gemessen 17.10.: dreimal
        # Code-Zeilen hinter der "Autoritaetsfalle", trotz Verbot).
        p = prompt if versuch == 0 else (_ENTSCHAERFEN.sub("", prompt) + RUHIG)
        try:
            png = await medien_bild(c, p + ZUSATZ, VORLAGE, breite, hoehe)
        except RuntimeError as x:
            print(f"[folienbilder] {VORLAGE} gescheitert ({x}) -- nehme {VORLAGE_ERSATZ}", flush=True)
            png = await medien_bild(c, p + ZUSATZ, VORLAGE_ERSATZ, breite, hoehe)
        if melden:
            melden(f"prüft das Bild (Versuch {versuch + 1} von {VERSUCHE})")
        mangel = await bild_pruefen(png)
        if not mangel:
            return png, None
        print(f"[folienbilder] Versuch {versuch + 1}: {mangel} -- rechne neu", flush=True)
    return png, mangel


async def _kunstregie(eid: str, liste: list[str]) -> list[str]:
    e = db.holen("ergebnisse", eid) or {}
    # Der Praesentations-Stil bringt seine Bildsprache mit (folien_stil.py): die
    # VVEORG-Vorlage arbeitet mit dunklen, kinematografischen Bildern.
    from . import folien_stil
    bs = folien_stil.bildstil(e.get("stil")) if e.get("form") == "praesentation" else ""
    return await kunstregie(e.get("titel") or "", liste, "PRÄSENTATION",
                            f"BILDSPRACHE DIESER PRÄSENTATION: {bs}. " if bs else "")


async def kunstregie(titel: str, liste: list[str], art: str = "PRÄSENTATION", zusatz: str = "") -> list[str]:
    """Bildwuensche (deutsch oder englisch) -> englische Bildanweisungen in EINEM
    Stil fuer das ganze Werk. Ein Weg fuer Folien und Video (video.py, 17.10.2026).
    Faellt das Modell aus, gehen die Wuensche unveraendert raus (schlechter, aber
    kein Abbruch)."""
    from . import llm
    modell = await llm.modell_waehlen(llm.vorgabe("arbeit"), llm.vorgabe("talk"), "qwen3.6:27b")
    if not modell:
        return liste
    frage = (f"{art}: {titel}\n\nBILDWÜNSCHE (in dieser Reihenfolge):\n"
             + "\n".join(f"{i + 1}. {p}" for i, p in enumerate(liste))
             + "\n\nDu bist Art Director. Lege EINEN gemeinsamen visuellen Stil für alle Bilder fest (Bildsprache, Farbpalette, "
               "Licht, Materialien -- passend zu einem eleganten, dunkelblau-warmen Business-Design) und schreibe für jeden "
               "Wunsch eine englische Bildanweisung für ein Bildmodell: konkretes Motiv, Komposition (Platz links oder rechts "
               "für Text, wo sinnvoll), Perspektive, Licht, Stil. 40 bis 80 Wörter je Bild. NIEMALS Text, Buchstaben, Zahlen, "
               "Schilder, Logos oder Bildschirme mit Schrift; keine echten, erkennbaren Personen. Auch keine Anführungszeichen "
               "oder andere Satzzeichen als Bildmotiv, keine Zahlen- oder Code-Kolonnen, keine Dokumente, Bücher mit "
               "sichtbaren Seiten, Diagramme mit Beschriftung oder Tafeln -- daraus macht ein Bildmodell verstümmelte Schrift. "
               "Übernimm Begriffe aus dem Wunsch NICHT wörtlich in Anführungszeichen; setze sie in ein Bild um "
               "(„Autoritätsfalle“ → eine Figur, die einer leuchtenden, hohlen Hülle folgt). " + zusatz + "Antworte NUR mit JSON: "
               '{"stil": "der gemeinsame Stil auf Englisch", "bilder": ["Anweisung 1", "..."]}')
    try:
        d = llm.json_aus(await llm.chat(modell, "", [{"role": "user", "content": frage}], json_format=True,
                                        temperatur=0.4, denken=False, timeout=300)) or {}
    except llm.ModellFehler:
        return liste
    # Anfuehrungszeichen raus: was in Anfuehrungszeichen steht, malt ein Bildmodell
    # gern als Schriftzug (gemessen: "überwachtes Modell" -> "überwachges Modell").
    bilder = [re.sub(r"[\"“”„‚‘’«»]", "", str(b)).strip() for b in (d.get("bilder") or []) if str(b).strip()]
    if len(bilder) != len(liste):
        return liste
    stil = str(d.get("stil") or "").strip()
    return [f"{b}. Style: {stil}" if stil else b for b in bilder]


async def _lauf(eid: str, liste: list[str]) -> None:
    from . import medien
    t0 = time.time()
    _stand_setzen(eid, stand="rechnet", anzahl=len(liste), fertig=0, fehler=None, start=t0, schritt="Art Direction: Bildstil festlegen")
    fehler = 0
    maengel: list[str] = []   # Bilder, die auch nach allen Versuchen noch einen Mangel hatten
    try:
        englisch = await _kunstregie(eid, liste)
        async with httpx.AsyncClient(timeout=60) as c:
            for i, p in enumerate(liste):
                # Bilder geben dem Team Vortritt (18.10.2026): rechnet gerade ein Schritt von
                # Pipeline oder Langlaeufer, wartet das naechste Bild -- beide brauchen Karte 2,
                # und gleichzeitig reichte der Speicher nicht. Hoechstens 20 Minuten, dann weiter.
                warten_bis = time.time() + 1200
                while _team_rechnet() and time.time() < warten_bis:
                    _stand_setzen(eid, schritt=f"Bild {i + 1} von {len(liste)}: wartet, bis das Team fertig gerechnet hat", fertig=i)
                    await asyncio.sleep(10)
                _stand_setzen(eid, schritt=f"Bild {i + 1} von {len(liste)}", fertig=i)
                try:
                    png, mangel = await bild_ohne_fehler(c, englisch[i], melden=lambda s, i=i: _stand_setzen(
                        eid, schritt=f"Bild {i + 1} von {len(liste)}: {s}"))
                    if mangel:
                        maengel.append(f"Bild {i + 1}: {mangel}")
                    # Abgelegt unter der DEUTSCHEN Beschreibung -- daran findet der Einbau das Bild.
                    datei(eid, p).write_bytes(await asyncio.to_thread(_als_jpeg, png))
                except Exception as x:  # noqa: BLE001 -- ein Bild darf scheitern, die anderen nicht
                    fehler += 1
                    print(f"[folienbilder] {eid} Bild {i + 1}: {x}", flush=True)
        _stand_setzen(eid, stand="fertig" if not fehler else "fehler", fertig=len(liste) - fehler,
                      fehler=(f"{fehler} von {len(liste)} Bildern ließen sich nicht rechnen." if fehler else None),
                      maengel=maengel or None, dauer_s=round(time.time() - t0))
    except Exception as x:  # noqa: BLE001
        _stand_setzen(eid, stand="fehler", fehler=f"{x.__class__.__name__}: {str(x)[:300]}")
    finally:
        LAUFEND.pop(eid, None)


def starten(eid: str, neu: bool = False) -> int:
    """Rechnet die fehlenden Bilder (mit neu=True alle). Gibt die Zahl der zu
    rechnenden Bilder zurueck; 0 = nichts zu tun oder laeuft schon."""
    if eid in LAUFEND:
        return 0
    e = db.holen("ergebnisse", eid)
    if not e or e.get("form") not in MIT_BILDERN:
        return 0
    ps = [p for p in prompts(e.get("inhalt") or "", e["form"]) if p][:MAX_BILDER]
    if neu:
        for p in ps:
            datei(eid, p).unlink(missing_ok=True)
    liste = [p for p in dict.fromkeys(ps) if not datei(eid, p).is_file()]
    if not liste:
        return 0
    # Sofort als "rechnet" vermerken: die Antwort auf das Oeffnen soll den
    # Fortschritt schon zeigen, nicht erst der naechste Abruf.
    _stand_setzen(eid, stand="rechnet", anzahl=len(liste), fertig=0, fehler=None, schritt="beginnt")
    LAUFEND[eid] = asyncio.create_task(llm.mit_zweck("folienbilder:" + eid, _lauf(eid, liste)))
    return len(liste)


# ------------------------------------------------------------ nachholen
# Veiko, 18.10.2026: "warum rechnet er erst jetzt die Bilder, wenn ich es oeffne?
# Das soll im Verlauf der Bearbeitung gleich passieren." Angestossen wurde zwar
# sofort (neues Ergebnis, neue Fassung, Ende eines Langlaeufers) -- aber ein Lauf,
# den ein Neustart des Dienstes abbrach, blieb liegen, ein Zwischenstand bekam mit
# jeder Etappe neue Bildzeilen ohne neuen Anstoss, und einiges war nie angestossen.
# Gemessen am 18.10.: drei Ergebnisse mit 2/16, 0/17 und 0/6 Bildern. Gerechnet
# wurde jeweils erst beim Oeffnen. Diese Schleife holt das nach: alle fuenf
# Minuten das zuletzt bearbeitete Ergebnis der letzten NACHHOL_TAGE, dem Bilder
# fehlen -- eines nach dem anderen, nie neben einem Video (beide auf Karte 2) und
# nie nach einem gescheiterten Lauf (dafuer gibt es "Neu rechnen").
NACHHOL_TAGE = 14


def _team_rechnet() -> bool:
    """Rechnet gerade ein Schritt von Pipeline oder Langlaeufer (beide unter stab._lock)?"""
    from . import stab
    return stab._lock.locked()


async def nachholen() -> str | None:
    from . import video
    if any(t and not t.done() for t in LAUFEND.values()) or any(t and not t.done() for t in video.LAUFEND.values()):
        return None
    # Nachholen ist nie eilig: nur, wenn das Team gerade nicht rechnet (18.10.2026, siehe _lauf).
    if _team_rechnet():
        return None
    seit = time.time() - NACHHOL_TAGE * 86400
    formen = ",".join("?" * len(MIT_BILDERN))
    for e in db.alle(f"SELECT e.*, COALESCE((SELECT MAX(p.zeit) FROM protokoll p WHERE p.tabelle='ergebnisse' AND p.datensatz_id=e.id), "
                     f"e.erstellt) AS zuletzt FROM ergebnisse e WHERE e.form IN ({formen}) ORDER BY zuletzt DESC LIMIT 200", MIT_BILDERN):
        if (e.get("zuletzt") or 0) < seit:
            break
        s = stand(e) or {}
        if s.get("gewuenscht", 0) > s.get("vorhanden", 0) and s.get("stand") != "fehler" and starten(e["id"]):
            return e["id"]
    return None


async def nachhol_schleife() -> None:
    await asyncio.sleep(120)   # nach einem Neustart erst einmal die Pipeline anlaufen lassen
    while True:
        try:
            eid = await nachholen()
            if eid:
                print(f"[folienbilder] hole fehlende Bilder nach: {eid}", flush=True)
        except Exception as x:  # noqa: BLE001 -- die Schleife darf nie sterben
            print(f"[folienbilder] Nachholen gescheitert: {x}", flush=True)
        await asyncio.sleep(300)
