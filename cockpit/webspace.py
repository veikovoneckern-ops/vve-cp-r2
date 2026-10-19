"""
WebSpace -- die Website veikovoneckern.org im Cockpit bearbeiten (18.10.2026).

Veiko: "in meinem Cockpit einen Button WebSpace ... einen eigenen Editor für
Webseiten, die ich mit meinem Cockpit erstellen und bearbeiten kann."

Die Website ist seit dem 18.10. kein one.com-Baukasten mehr, sondern ein Repo
(veikovoneckern-ops/veikovoneckern-org) aus kleinen HTML-Dateien unter inhalt/,
einer Vorlage und bauen.js; ein Push auf main veröffentlicht sie über GitHub
Pages. Dieses Modul arbeitet auf einem eigenen Klon unter daten/webspace/ und
hält drei Dinge auseinander:

  bearbeiten     schreibt nur in den Klon (nichts ist öffentlich)
  Vorschau       baut den Klon mit Vorspann /api/webspace/vorschau und liefert aus
  veröffentlichen  commit + push -- NUR auf ausdrücklichen Klick (Vertrauensstufe:
                 "nach außen" geht nie vom Stab aus)

Geschrieben wird mit einem eigenen Deploy-Schlüssel (~/.ssh/webspace_ed25519),
der nur dieses eine Repo erreicht -- nicht der Lese-Schlüssel des Cockpit-Repos.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from . import llm
from .konfig import DATEN

router = APIRouter(prefix="/api/webspace")

REPO_URL = "git@github.com:veikovoneckern-ops/veikovoneckern-org.git"
REPO_API = "https://api.github.com/repos/veikovoneckern-ops/veikovoneckern-org"
LIVE = "https://veikovoneckern.org"
KLON = DATEN / "webspace" / "veikovoneckern-org"
SCHLUESSEL = Path("~/.ssh/webspace_ed25519").expanduser()
VORSCHAU_BASIS = "/api/webspace/vorschau"
VORSCHAU_ORDNER = "_vorschau"
# Was der WebSpace verändern und veröffentlichen darf. Vorlage und Bauskript
# gehören nicht dazu: daran hängt jede Seite, das bleibt Arbeit für Neo/Claude.
BEREICHE = ("inhalt", "bilder", "seiten.json")

PFAD_RE = re.compile(r"^[a-z0-9-]+(/[a-z0-9-]+)*\.html$")
BILD_ENDUNGEN = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".mp4"}
KOPF_RE = re.compile(r"^\s*<!--seite\s*([\s\S]*?)-->\s*")

_sperre = asyncio.Lock()
_letzter_abgleich = 0.0
_vorschau_stand = 0.0
_lauf_merker: dict[str, Any] = {"zeit": 0.0, "wert": None}


class WebspaceFehler(Exception):
    pass


# ---------------------------------------------------------------- Werkzeuge

async def _ausfuehren(*befehl: str, umgebung: dict[str, str] | None = None, zeit: float = 120) -> str:
    import os
    env = dict(os.environ)
    env["GIT_SSH_COMMAND"] = f"ssh -i {SCHLUESSEL} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
    env.update(umgebung or {})
    p = await asyncio.create_subprocess_exec(*befehl, cwd=str(KLON) if KLON.exists() else str(KLON.parent),
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
    try:
        aus, fehl = await asyncio.wait_for(p.communicate(), zeit)
    except TimeoutError as e:
        p.kill()
        raise WebspaceFehler(f"{befehl[0]} {befehl[1] if len(befehl) > 1 else ''}: keine Antwort binnen {round(zeit)} s") from e
    if p.returncode != 0:
        text = (fehl or aus).decode("utf-8", "replace").strip()
        raise WebspaceFehler(f"{' '.join(befehl[:2])} fehlgeschlagen: {text[-600:]}")
    return aus.decode("utf-8", "replace")


async def _git(*args: str, zeit: float = 120) -> str:
    return await _ausfuehren("git", *args, zeit=zeit)


async def _klon_sicher() -> None:
    """Klon anlegen bzw. mit GitHub abgleichen, solange nichts ungespeichert ist."""
    global _letzter_abgleich
    if not KLON.exists():
        KLON.parent.mkdir(parents=True, exist_ok=True)
        await _ausfuehren("git", "clone", "-q", REPO_URL, str(KLON), zeit=300)
        await _git("config", "core.sshCommand", f"ssh -i {SCHLUESSEL} -o IdentitiesOnly=yes")
        await _git("config", "user.name", "VvE Cockpit (WebSpace)")
        await _git("config", "user.email", "info@veikovoneckern.org")
        _letzter_abgleich = time.time()
        return
    if time.time() - _letzter_abgleich < 60:
        return
    _letzter_abgleich = time.time()
    # Nur vorspulen, wenn hier nichts in Arbeit ist -- sonst gewinnt beim
    # Veröffentlichen ein rebase, und ein Konflikt wird ehrlich gemeldet.
    if not (await _git("status", "--porcelain")).strip():
        try:
            await _git("pull", "-q", "--ff-only", zeit=60)
        except WebspaceFehler as e:
            print(f"[webspace] Abgleich mit GitHub gescheitert: {e}", flush=True)


def _sicherer_pfad(pfad: str) -> Path:
    pfad = (pfad or "").strip().lstrip("/")
    if not PFAD_RE.match(pfad):
        raise HTTPException(400, "Ungültiger Seitenpfad (erlaubt: kleine Buchstaben, Ziffern, Bindestrich, endet auf .html)")
    p = (KLON / "inhalt" / pfad).resolve()
    if not str(p).startswith(str((KLON / "inhalt").resolve())):
        raise HTTPException(400, "Pfad liegt außerhalb der Seiten")
    return p


def _lesen(datei: Path) -> tuple[dict[str, Any], str]:
    roh = datei.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = KOPF_RE.match(roh)
    if not m:
        return {"titel": datei.stem}, roh
    try:
        kopf = json.loads(m.group(1))
    except json.JSONDecodeError:
        kopf = {"titel": datei.stem, "_kopf_fehler": True}
    return kopf, roh[m.end():]


def _schreiben(datei: Path, kopf: dict[str, Any], inhalt: str) -> None:
    kopf = {k: v for k, v in kopf.items() if not k.startswith("_")}
    if not str(kopf.get("titel") or "").strip():
        raise HTTPException(400, "Die Seite braucht einen Titel")
    text = "<!--seite\n" + json.dumps(kopf, ensure_ascii=False, indent=2) + "\n-->\n\n" + inhalt.strip() + "\n"
    datei.parent.mkdir(parents=True, exist_ok=True)
    datei.write_text(text, encoding="utf-8")


def _adresse(rel: str) -> str:
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel[: -len(".html")]


def _slug(text: str) -> str:
    t = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:60].strip("-") or "seite"


def _menue_lesen() -> dict[str, Any]:
    return json.loads((KLON / "seiten.json").read_text(encoding="utf-8"))


def _menue_schreiben(cfg: dict[str, Any]) -> None:
    (KLON / "seiten.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def _aenderungen() -> list[dict[str, str]]:
    aus = await _git("status", "--porcelain", "-uall", "--", *BEREICHE)
    liste = []
    for z in aus.splitlines():
        if len(z) < 4:
            continue
        code, datei = z[:2], z[3:].strip().strip('"')
        art = "neu" if "?" in code or "A" in code else "gelöscht" if "D" in code else "geändert"
        liste.append({"datei": datei, "art": art})
    return liste


# ---------------------------------------------------------------- Stand

@router.get("/stand")
async def stand():
    async with _sperre:
        try:
            await _klon_sicher()
            aend = await _aenderungen()
            letzter = (await _git("log", "-1", "--format=%h%x1f%s%x1f%cI")).strip().split("\x1f")
        except WebspaceFehler as e:
            raise HTTPException(503, str(e)) from e
    geaendert = {a["datei"] for a in aend}
    seiten = []
    for f in sorted((KLON / "inhalt").rglob("*.html")):
        rel = f.relative_to(KLON / "inhalt").as_posix()
        kopf, _ = _lesen(f)
        seiten.append({"pfad": rel, "titel": kopf.get("titel") or rel, "beschreibung": kopf.get("beschreibung") or "",
                       "adresse": _adresse(rel), "blog": kopf.get("blog"), "liste": bool(kopf.get("blogliste")),
                       "geaendert": ("inhalt/" + rel) in geaendert})
    # Nicht mehr vorhandene (gelöschte) Seiten stehen nur in den Änderungen.
    return {"seiten": seiten, "aenderungen": aend, "live": LIVE,
            "menue": _menue_lesen().get("navigation", []),
            "letzter": {"sha": letzter[0], "text": letzter[1], "zeit": letzter[2]} if len(letzter) == 3 else None,
            "veroeffentlichung": await _veroeffentlichung()}


async def _veroeffentlichung() -> dict[str, Any] | None:
    """Letzter Lauf auf GitHub (Bauen + Veröffentlichen), 15 s gemerkt. Öffentliche
    Schnittstelle ohne Anmeldung -- das Repo ist öffentlich."""
    if time.time() - _lauf_merker["zeit"] < 15:
        return _lauf_merker["wert"]
    wert = None
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(REPO_API + "/actions/runs", params={"per_page": 1},
                            headers={"Accept": "application/vnd.github+json"})
            if r.status_code == 200 and r.json().get("workflow_runs"):
                l = r.json()["workflow_runs"][0]
                wert = {"stand": l.get("status"), "ergebnis": l.get("conclusion"), "sha": (l.get("head_sha") or "")[:7],
                        "titel": l.get("display_title"), "zeit": l.get("updated_at"), "url": l.get("html_url")}
    except httpx.HTTPError:
        wert = None
    _lauf_merker.update(zeit=time.time(), wert=wert)
    return wert


# ---------------------------------------------------------------- Seiten

@router.get("/seite")
async def seite_holen(pfad: str):
    datei = _sicherer_pfad(pfad)
    if not datei.exists():
        raise HTTPException(404, "Seite gibt es nicht")
    kopf, inhalt = _lesen(datei)
    return {"pfad": pfad, "kopf": kopf, "inhalt": inhalt, "adresse": _adresse(pfad)}


@router.post("/seite")
async def seite_speichern(d: dict[str, Any]):
    datei = _sicherer_pfad(d.get("pfad", ""))
    if not datei.exists():
        raise HTTPException(404, "Seite gibt es nicht -- neue Seiten über „Neue Seite“ anlegen")
    kopf = d.get("kopf") or {}
    inhalt = str(d.get("inhalt") or "")
    if len(inhalt) > 400_000:
        raise HTTPException(413, "Die Seite ist zu groß (über 400.000 Zeichen)")
    for name in re.findall(r"<!--baustein ([a-z0-9-]+)-->", inhalt):
        if not (KLON / "bausteine" / f"{name}.html").exists():
            raise HTTPException(400, f"Der Baustein „{name}“ existiert nicht")
    async with _sperre:
        _schreiben(datei, kopf, inhalt)
    return {"ok": True}


@router.post("/neu")
async def seite_neu(d: dict[str, Any]):
    titel = str(d.get("titel") or "").strip()
    if not titel:
        raise HTTPException(400, "Titel fehlt")
    art = d.get("art") or "seite"
    if art == "blog":
        ordner = "inspiration-blog"
    else:
        ordner = str(d.get("ordner") or "").strip("/")
        if ordner and not re.fullmatch(r"[a-z0-9-]+(/[a-z0-9-]+)*", ordner):
            raise HTTPException(400, "Ungültiger Ordner")
    basis = _slug(d.get("pfad_name") or titel)
    rel = (ordner + "/" if ordner else "") + basis + ".html"
    n = 2
    while (KLON / "inhalt" / rel).exists():
        rel = (ordner + "/" if ordner else "") + f"{basis}-{n}.html"
        n += 1
    datei = _sicherer_pfad(rel)
    kopf: dict[str, Any] = {"titel": titel, "beschreibung": str(d.get("beschreibung") or "")}
    if art == "blog":
        # Neue Artikel vorn: eine kleinere "reihe" als alle vorhandenen.
        reihen = []
        for f in (KLON / "inhalt" / "inspiration-blog").glob("*.html"):
            k, _ = _lesen(f)
            if k.get("blog") and isinstance(k["blog"].get("reihe"), (int, float)):
                reihen.append(k["blog"]["reihe"])
        # Bild und Auszug kommen seit dem 19.10. gleich aus dem Dialog "Neuer Blogbeitrag".
        bild = str(d.get("bild") or "")
        if bild and not re.fullmatch(r"/bilder/[\w.-]+", bild):
            raise HTTPException(400, "Ungültiges Bild")
        auszug = str(d.get("auszug") or "").strip()[:400]
        kopf["blog"] = {"reihe": (min(reihen) - 1) if reihen else 1, "bild": bild, "auszug": auszug}
        inhalt = '<div class="fliess">\n<p>Hier beginnt der Artikel.</p>\n</div>'
    else:
        inhalt = (f'<section class="band" style="--h:260px">\n  <div class="band-innen">\n    <h1>{titel}</h1>\n  </div>\n</section>\n\n'
                  '<div class="fliess">\n<p>Hier beginnt der Text.</p>\n</div>')
    async with _sperre:
        _schreiben(datei, kopf, inhalt)
        unter = d.get("menue")
        if art != "blog" and unter is not None:
            cfg = _menue_lesen()
            punkt = {"text": titel, "href": _adresse(rel)}
            if unter == "":
                cfg["navigation"].append(punkt)
            else:
                eltern = next((p for p in cfg["navigation"] if p.get("href") == unter), None)
                if not eltern:
                    raise HTTPException(400, "Menüpunkt zum Einhängen nicht gefunden")
                eltern.setdefault("unter", []).append(punkt)
            _menue_schreiben(cfg)
    return {"pfad": rel, "adresse": _adresse(rel)}


@router.post("/loeschen")
async def seite_loeschen(d: dict[str, Any]):
    rel = str(d.get("pfad") or "")
    datei = _sicherer_pfad(rel)
    if rel == "index.html":
        raise HTTPException(400, "Die Startseite lässt sich nicht löschen")
    if not datei.exists():
        raise HTTPException(404, "Seite gibt es nicht")
    async with _sperre:
        datei.unlink()
        # Aus dem Menü nehmen, wo sie stand.
        cfg = _menue_lesen()
        adr = _adresse(rel)

        def weg(liste: list[dict[str, Any]]) -> list[dict[str, Any]]:
            neu = []
            for p in liste:
                if p.get("href") == adr:
                    continue
                if p.get("unter"):
                    p["unter"] = weg(p["unter"])
                    if not p["unter"]:
                        del p["unter"]
                neu.append(p)
            return neu
        cfg["navigation"] = weg(cfg["navigation"])
        _menue_schreiben(cfg)
    return {"ok": True}


@router.post("/bild")
async def bild_hoch(datei: UploadFile = File(...)):
    roh = await datei.read()
    if len(roh) > 25 * 1024 * 1024:
        raise HTTPException(413, "Das Bild ist größer als 25 MB")
    name = Path(datei.filename or "bild.jpg")
    endung = name.suffix.lower()
    if endung not in BILD_ENDUNGEN:
        raise HTTPException(400, f"Dateityp {endung or '?'} wird nicht unterstützt (erlaubt: {', '.join(sorted(BILD_ENDUNGEN))})")
    basis = _slug(name.stem)
    ziel = KLON / "bilder" / f"{basis}{endung}"
    n = 2
    while ziel.exists():
        ziel = KLON / "bilder" / f"{basis}-{n}{endung}"
        n += 1
    async with _sperre:
        ziel.write_bytes(roh)
    return {"pfad": "/bilder/" + ziel.name}


@router.get("/bausteine")
async def bausteine_liste():
    """Die fertig programmierten Bausteine -- für "Abschnitt einfügen"."""
    return {"bausteine": sorted(f.stem for f in (KLON / "bausteine").glob("*.html"))}


@router.get("/bilder")
async def bilder_liste():
    return {"bilder": sorted("/bilder/" + f.name for f in (KLON / "bilder").glob("*") if f.suffix.lower() in BILD_ENDUNGEN)}


# ---------------------------------------------------------------- Vorschau

async def _vorschau_bauen() -> None:
    """Baut nur, wenn sich seit dem letzten Bau etwas geändert hat."""
    global _vorschau_stand
    neuste = max((f.stat().st_mtime for b in ("inhalt", "bilder", "bausteine", "vorlage")
                  for f in (KLON / b).rglob("*") if f.is_file()), default=0)
    neuste = max(neuste, (KLON / "seiten.json").stat().st_mtime, (KLON / "bauen.js").stat().st_mtime)
    if neuste <= _vorschau_stand and (KLON / VORSCHAU_ORDNER / "_editor.html").exists():
        return
    await _ausfuehren("node", "bauen.js", umgebung={"AUSGABE": VORSCHAU_ORDNER, "BASIS": VORSCHAU_BASIS,
                                                     "EDITOR_RAHMEN": "1"}, zeit=60)
    _vorschau_stand = time.time()


@router.get("/vorschau/{rest:path}")
async def vorschau(rest: str = ""):
    async with _sperre:
        try:
            await _klon_sicher()
            await _vorschau_bauen()
        except WebspaceFehler as e:
            return Response(f"<p style='font-family:sans-serif;padding:24px'>Vorschau lässt sich nicht bauen:<br><code>{e}</code></p>",
                            media_type="text/html", status_code=500)
    wurzel = (KLON / VORSCHAU_ORDNER).resolve()
    rest = rest.strip("/")
    for k in ([rest, rest + ".html", rest + "/index.html"] if rest else ["index.html"]):
        f = (wurzel / k).resolve()
        if str(f).startswith(str(wurzel)) and f.is_file():
            return FileResponse(f, headers={"Cache-Control": "no-store"})
    return FileResponse(wurzel / "404.html", status_code=404)


# ---------------------------------------------------------------- KI-Assistent

ASSISTENT_SYSTEM = """Du bearbeitest eine Seite der Website veikovoneckern.org (Veiko von Eckern: Künstliche Intelligenz, Singularität, HR-Strategie und Transformation). Schreibe auf Deutsch, klar und hochwertig, im Ton der vorhandenen Seiten.

Die Seite ist ein HTML-Ausschnitt (nur der Inhalt, Kopf/Menü/Fuß kommen aus der Vorlage). Erlaubte Bausteine:
- Band (dunkler Streifen, weiße Schrift): <section class="band" style="--h:300px"><div class="band-bild" style="background-image:url('/bilder/NAME');opacity:0.4"></div><div class="band-innen"><h2>…</h2></div></section>  (band-bild ist optional; data-effekt="aufdecken" oder "parallax" am section möglich)
- Fließtext: <div class="fliess"> mit h2, h3, p, ul/ol, figure mit img </div>
- Dunkler Balken mit Überschrift: <div class="balken"><h3>…</h3></div>
- Zwei Spalten: <div class="spalten"><div>…</div><div>…</div></div>
- Karten: <div class="karten"><div class="karte"><img src="/bilder/NAME" alt=""><h4>Titel</h4><p>Text</p></div>…</div>
- Knopf: <p class="knopfzeile"><a class="knopf" href="/pfad">TEXT</a></p>
- Zitat: <blockquote class="zitat"><p>…</p><cite>Name</cite></blockquote> (nur wörtliche, belegte Zitate)
- Bild mit Unterschrift: <figure class="mittel"><img src="/bilder/NAME" alt="Beschreibung"><figcaption>…</figcaption></figure>
- Trennlinie: <hr class="trenner">
- Marken wie <!--baustein name--> und <!--blogliste--> stehen für fest eingebaute Teile: unverändert stehen lassen.

Regeln:
- Kein <html>, <head>, <body>, kein <script>, kein <style>-Block, keine neuen CSS-Klassen.
- Bilder nur aus /bilder/ und nur solche, die in der Liste der vorhandenen Bilder stehen oder schon in der Seite vorkommen.
- Erfinde keine Fakten, Zahlen, Zitate oder Termine. Was fehlt, schreibst du als [noch offen: …].
- Ändere nur, was der Auftrag verlangt; alles andere bleibt Zeichen für Zeichen gleich.

Antwortform, genau so:
<<<SEITE>>>
(der vollständige neue HTML-Ausschnitt)
<<<ENDE>>>
Danach in ein bis drei Sätzen in Alltagssprache, was du geändert hast -- ohne HTML- oder Technikbegriffe (nicht „div“, „Klasse“, „Tag“), so wie man es einem Kollegen sagt."""


@router.post("/assistent")
async def assistent(d: dict[str, Any]):
    auftrag = str(d.get("auftrag") or "").strip()
    if not auftrag:
        raise HTTPException(400, "Was soll geändert werden?")
    kopf = d.get("kopf") or {}
    inhalt = str(d.get("inhalt") or "")
    # Drei Arten (19.10.2026): ganze Seite, EIN Abschnitt (abschnitt = sein HTML),
    # oder ein NEUER Abschnitt (neu = True) -- dann ist "inhalt" nur Kontext.
    abschnitt = str(d.get("abschnitt") or "")
    neu_block = bool(d.get("neu"))
    bilder = sorted(f.name for f in (KLON / "bilder").glob("*") if f.suffix.lower() in BILD_ENDUNGEN)
    kopfzeilen = (f"SEITE: {kopf.get('titel', '')} ({d.get('pfad', '')})\n"
                  f"VORHANDENE BILDER: {', '.join(bilder)}\n\n")
    if abschnitt:
        nutzer = (kopfzeilen + f"DIE GANZE SEITE (nur als Zusammenhang, NICHT zurückgeben):\n{inhalt[:30000]}\n\n"
                  f"DER ABSCHNITT, DEN DU BEARBEITEST:\n{abschnitt}\n\nAUFTRAG VON VEIKO:\n{auftrag}\n\n"
                  "Gib zwischen <<<SEITE>>> und <<<ENDE>>> NUR den neuen Abschnitt zurück, nicht die ganze Seite.")
    elif neu_block:
        nutzer = (kopfzeilen + f"DIE GANZE SEITE (nur als Zusammenhang, NICHT zurückgeben):\n{inhalt[:30000]}\n\n"
                  f"AUFTRAG VON VEIKO für einen NEUEN Abschnitt:\n{auftrag}\n\n"
                  "Gib zwischen <<<SEITE>>> und <<<ENDE>>> NUR den neuen Abschnitt zurück (ein Baustein aus der Liste).")
    else:
        nutzer = kopfzeilen + f"AKTUELLER HTML-AUSSCHNITT:\n{inhalt}\n\nAUFTRAG VON VEIKO:\n{auftrag}"
    modell = llm.vorgabe("arbeit")
    try:
        antwort = await llm.mit_zweck("webspace:" + str(d.get("pfad", "")),
                                      llm.chat(modell, ASSISTENT_SYSTEM, [{"role": "user", "content": nutzer}],
                                               denken=False, num_ctx=32768, timeout=900))
    except llm.ModellFehler as e:
        raise HTTPException(503, f"Das Modell hat nicht geantwortet: {e}") from e
    m = re.search(r"<<<SEITE>>>\s*([\s\S]*?)\s*<<<ENDE>>>", antwort)
    if not m:
        raise HTTPException(502, "Das Modell hat nichts Verwertbares geliefert. Bitte den Auftrag noch einmal, etwas konkreter.")
    neu = m.group(1).strip()
    neu = re.sub(r"^```(?:html)?\s*|\s*```$", "", neu)
    # Prüfungen statt Vertrauen: verbotene Teile fliegen raus, feste Marken müssen bleiben.
    neu = re.sub(r"<script[\s\S]*?</script>", "", neu, flags=re.I)
    neu = re.sub(r"<style[\s\S]*?</style>", "", neu, flags=re.I)
    neu = re.sub(r"\s+on[a-z]+\s*=\s*(\"[^\"]*\"|'[^']*')", "", neu, flags=re.I)
    hinweise = []
    vorlage = abschnitt if abschnitt else ("" if neu_block else inhalt)
    for marke in re.findall(r"<!--(?:baustein [a-z0-9-]+|blogliste)-->", vorlage):
        if marke not in neu:
            neu += "\n\n" + marke
            hinweise.append(f"{marke} fehlte in der Antwort und wurde wieder angehängt")
    if vorlage and len(neu) < 0.4 * len(vorlage) and not re.search(r"kürz|knapp|streich|lösch|entfern|weg", auftrag, re.I):
        raise HTTPException(502, "Das Modell hat den Text stark gekürzt, ohne dass du das verlangt hast. Nichts übernommen.")
    erklaerung = antwort[m.end():].strip()[:800]
    return {"inhalt": neu, "erklaerung": erklaerung, "hinweise": hinweise, "modell": modell,
            "art": "abschnitt" if abschnitt else "neu" if neu_block else "seite"}


# ---------------------------------------------------------------- Prüfung durch die Externen (19.10.2026)
# Veiko: "die externen in meinem Setup auch vor Veröffentlichung prüfen lassen".
# Der Assistent oben rechnet lokal; diese Prüfung geht an Dario/Elon/Demmis über
# den Cloud-Weg des alten Backends (teamchat._cloud_chat, bucht in "Verbrauch")
# und kostet Geld -- deshalb NUR mit ausdrücklicher Freigabe (freigabe=True, die
# Oberfläche fragt vorher mit geschätzten Kosten). Geprüft wird, was veröffentlicht
# würde: die geänderten Seiten in ihrer neuen Fassung, als lesbarer Text.

EXTERN_AUS_TOKEN = 3000

EXTERN_PRUEFEN = """Du bist {name} und prüfst für Veiko von Eckern Seiten seiner Website veikovoneckern.org (Themen: Künstliche Intelligenz, Singularität, HR-Strategie, Transformation), BEVOR er sie veröffentlicht. Die Seite ist öffentlich und trägt seinen Namen.
Prüfe: Rechtschreibung und Grammatik, sachliche Richtigkeit (Fakten, Namen, Zahlen, Zitate), Verständlichkeit, Ton (souverän, fachlich, nicht werblich), Rechtliches (z. B. ungekennzeichnete Zitate, Bildrechte, Behauptungen über Personen), Google (Titel, Beschreibung) und Barrierefreiheit (Bildbeschreibungen).
Antworte AUSSCHLIESSLICH mit JSON:
{{"urteil": "veroeffentlichen|nachbessern", "zusammenfassung": "zwei bis vier Sätze für Veiko, Alltagssprache", "punkte": [{{"seite": "Pfad wie angegeben", "art": "Rechtschreibung|Fakten|Verständlichkeit|Ton|Rechtliches|Google|Barrierefreiheit", "gewicht": "wichtig|hinweis", "stelle": "WÖRTLICHES Zitat aus dem Text, genau so geschrieben", "problem": "ein Satz", "vorschlag": "der korrigierte Text für genau diese Stelle, oder leer"}}]}}
Regeln: höchstens 15 Punkte, die wichtigsten zuerst. "stelle" muss Zeichen für Zeichen im Text vorkommen, sonst lass den Punkt weg. Erfinde keine Fehler; ist alles in Ordnung, ist "punkte" leer. Deutsch."""


def _lesbar(inhalt: str) -> str:
    """HTML-Ausschnitt als lesbarer Text für die Prüfung (Überschriften, Listen, Bilder, Links)."""
    s = re.sub(r"<!--baustein ([a-z0-9-]+)-->", r"\n[Interaktiver Baustein: \1 -- nicht prüfen]\n", inhalt)
    s = s.replace("<!--blogliste-->", "\n[Liste der Blogartikel]\n")
    s = re.sub(r"<img\b[^>]*?src=\"([^\"]+)\"[^>]*?alt=\"([^\"]*)\"[^>]*>", lambda m: f"[Bild: {m.group(1).split('/')[-1]}; Bildbeschreibung: {m.group(2) or 'FEHLT'}]", s)
    s = re.sub(r"<img\b[^>]*?src=\"([^\"]+)\"[^>]*>", lambda m: f"[Bild: {m.group(1).split('/')[-1]}; Bildbeschreibung: FEHLT]", s)
    s = re.sub(r"<a\b[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", r"\2 (Link: \1)", s, flags=re.S)
    s = re.sub(r"<h([1-4])[^>]*>", lambda m: "\n\n" + "#" * int(m.group(1)) + " ", s)
    s = re.sub(r"<li[^>]*>", "\n- ", s)
    s = re.sub(r"</(p|h[1-4]|li|blockquote|figcaption|div|section)>", "\n", s)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&amp;", "&").replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()


async def _pruefstoff() -> tuple[str, list[str]]:
    aend = await _aenderungen()
    teile, pfade = [], []
    for a in aend:
        d = a["datei"]
        if not (d.startswith("inhalt/") and d.endswith(".html")) or a["art"] == "gelöscht" or not (KLON / d).exists():
            continue
        rel = d[len("inhalt/"):]
        kopf, inhalt = _lesen(KLON / d)
        pfade.append(rel)
        teile.append(f"=== SEITE {rel} ({_adresse(rel)}) -- {'neu' if a['art'] == 'neu' else 'geändert'} ===\n"
                     f"Titel: {kopf.get('titel', '')}\nBeschreibung für Google: {kopf.get('beschreibung', '') or 'FEHLT'}\n\n{_lesbar(inhalt)}")
    return "\n\n".join(teile)[:120_000], pfade


@router.get("/externe")
async def externe():
    """Wer prüfen kann, mit welchem Modell, und was es voraussichtlich kostet."""
    from . import langlauf, teamchat
    async with _sperre:
        stoff, pfade = await _pruefstoff()
    ein = int((len(EXTERN_PRUEFEN) + len(stoff)) / 3.5)
    aus = []
    for x in await teamchat.externe_liste():
        modell = await teamchat._extern_modell(x["id"])  # dasselbe Modell, das die Prüfung danach nimmt
        anbieter = teamchat.EXTERNE[x["id"]]["anbieter"]
        aus.append({"id": x["id"], "name": x["name"], "titel": x["titel"], "schluessel": x.get("schluessel"),
                    "modell": modell, "kosten": round(langlauf._usd(anbieter, ein, EXTERN_AUS_TOKEN), 3)})
    return {"externe": aus, "seiten": pfade, "zeichen": len(stoff)}


@router.post("/extern-pruefen")
async def extern_pruefen(d: dict[str, Any]):
    from . import teamchat
    if not d.get("freigabe"):
        raise HTTPException(400, "Die Prüfung durch Externe kostet Geld und braucht deine Freigabe.")
    wer = [w for w in (d.get("wer") or []) if w in teamchat.EXTERNE]
    if not wer:
        raise HTTPException(400, "Wer soll prüfen?")
    async with _sperre:
        stoff, pfade = await _pruefstoff()
    if not pfade:
        raise HTTPException(400, "Es gibt keine geänderten Seiten zu prüfen.")

    async def einer(w: str) -> dict[str, Any]:
        x = teamchat.EXTERNE[w]
        modell = await teamchat._extern_modell(w)
        try:
            antwort = await teamchat._cloud_chat(w, modell, EXTERN_PRUEFEN.format(name=x["name"]),
                                                 [{"role": "user", "content": stoff}])
        except llm.ModellFehler as e:
            return {"wer": w, "name": x["name"], "modell": modell, "fehler": str(e)}
        j = llm.json_aus(antwort)
        if not isinstance(j, dict):
            return {"wer": w, "name": x["name"], "modell": modell, "fehler": "Die Antwort war kein lesbares Ergebnis.", "roh": antwort[:3000]}
        punkte = []
        for p in (j.get("punkte") or [])[:20]:
            if not isinstance(p, dict):
                continue
            seite = str(p.get("seite") or "")
            if seite not in pfade:
                seite = pfade[0] if len(pfade) == 1 else seite
            stelle = str(p.get("stelle") or "")
            # Nur Stellen, die es wirklich gibt, bekommen einen Übernehmen-Knopf.
            vorhanden = False
            if seite in pfade and stelle:
                k, inh = _lesen(KLON / "inhalt" / seite)
                vorhanden = (_im_text(inh, stelle, None)[1] > 0 or stelle in str(k.get("titel") or "")
                             or stelle in str(k.get("beschreibung") or ""))
            punkte.append({"seite": seite, "art": str(p.get("art") or ""), "gewicht": str(p.get("gewicht") or "hinweis"),
                           "stelle": stelle, "problem": str(p.get("problem") or ""), "vorschlag": str(p.get("vorschlag") or ""),
                           "uebernehmbar": vorhanden and bool(p.get("vorschlag"))})
        return {"wer": w, "name": x["name"], "modell": modell, "urteil": str(j.get("urteil") or ""),
                "zusammenfassung": str(j.get("zusammenfassung") or ""), "punkte": punkte}

    ergebnisse = await asyncio.gather(*(llm.mit_zweck("webspace:extern", einer(w)) for w in wer))
    return {"ergebnisse": list(ergebnisse), "seiten": pfade}


@router.post("/stelle-ersetzen")
async def stelle_ersetzen(d: dict[str, Any]):
    """Einen Vorschlag aus der Prüfung übernehmen: genau diese Stelle im sichtbaren Text."""
    datei = _sicherer_pfad(str(d.get("pfad") or ""))
    alt, neu = str(d.get("alt") or ""), str(d.get("neu") or "")
    if not alt or not datei.exists():
        raise HTTPException(400, "Stelle oder Seite fehlt")
    async with _sperre:
        kopf, inhalt = _lesen(datei)
        teile = _TEIL.split(inhalt)
        for i in range(0, len(teile), 2):
            if alt in teile[i]:
                teile[i] = teile[i].replace(alt, neu, 1)
                _schreiben(datei, kopf, "".join(teile))
                return {"ok": True}
        if alt in str(kopf.get("beschreibung") or ""):
            kopf["beschreibung"] = kopf["beschreibung"].replace(alt, neu, 1)
            _schreiben(datei, kopf, inhalt)
            return {"ok": True}
        if alt in str(kopf.get("titel") or ""):
            kopf["titel"] = kopf["titel"].replace(alt, neu, 1)
            _schreiben(datei, kopf, inhalt)
            return {"ok": True}
    raise HTTPException(404, "Die Stelle steht so nicht (mehr) im Text -- vielleicht über mehrere Absätze oder schon geändert.")


# ---------------------------------------------------------------- Verlauf und Vergleich (19.10.2026)

@router.get("/verlauf")
async def verlauf(pfad: str):
    """Veröffentlichte Fassungen einer Seite (aus der Git-Geschichte)."""
    datei = _sicherer_pfad(pfad)
    rel = "inhalt/" + datei.relative_to(KLON / "inhalt").as_posix()
    async with _sperre:
        try:
            aus = await _git("log", "--follow", "-n", "40", "--format=%h%x1f%cI%x1f%s", "--", rel)
        except WebspaceFehler as e:
            raise HTTPException(502, str(e)) from e
    liste = []
    for z in aus.splitlines():
        t = z.split("\x1f")
        if len(t) == 3:
            liste.append({"sha": t[0], "zeit": t[1], "text": t[2]})
    return {"fassungen": liste}


@router.get("/fassung")
async def fassung(pfad: str, sha: str):
    if not re.fullmatch(r"[0-9a-f]{4,40}", sha):
        raise HTTPException(400, "Ungültige Fassung")
    datei = _sicherer_pfad(pfad)
    rel = "inhalt/" + datei.relative_to(KLON / "inhalt").as_posix()
    async with _sperre:
        try:
            roh = await _git("show", f"{sha}:{rel}")
        except WebspaceFehler as e:
            raise HTTPException(404, "Diese Fassung gibt es für die Seite nicht (vielleicht hieß sie damals anders)") from e
    kopf, inhalt = _zerlegen(roh, datei.stem)
    return {"kopf": kopf, "inhalt": inhalt}


def _zerlegen(roh: str, ersatz_titel: str) -> tuple[dict[str, Any], str]:
    roh = roh.replace("\r\n", "\n")
    m = KOPF_RE.match(roh)
    if not m:
        return {"titel": ersatz_titel}, roh
    try:
        return json.loads(m.group(1)), roh[m.end():]
    except json.JSONDecodeError:
        return {"titel": ersatz_titel}, roh[m.end():]


@router.get("/vergleich")
async def vergleich():
    """Für den Veröffentlichen-Dialog: je geänderter Seite der veröffentlichte und der neue Stand."""
    async with _sperre:
        aend = await _aenderungen()
        aus = []
        for a in aend:
            d = a["datei"]
            if not d.startswith("inhalt/") or not d.endswith(".html"):
                aus.append({**a})
                continue
            alt = ""
            if a["art"] != "neu":
                try:
                    alt = await _git("show", f"HEAD:{d}")
                except WebspaceFehler:
                    alt = ""
            neu = (KLON / d).read_text(encoding="utf-8") if (KLON / d).exists() else ""
            ka, ia = _zerlegen(alt, d) if alt else ({}, "")
            kn, iN = _zerlegen(neu, d) if neu else ({}, "")
            aus.append({**a, "pfad": d[len("inhalt/"):], "alt": {"kopf": ka, "inhalt": ia}, "neu": {"kopf": kn, "inhalt": iN}})
    return {"aenderungen": aus}


# ---------------------------------------------------------------- Prüfungen vor dem Veröffentlichen

def _adressen() -> set[str]:
    return {_adresse(f.relative_to(KLON / "inhalt").as_posix()) for f in (KLON / "inhalt").rglob("*.html")}


def _pruefen_seite(rel: str, kopf: dict[str, Any], inhalt: str, adressen: set[str]) -> list[dict[str, str]]:
    w: list[dict[str, str]] = []
    def warn(stufe: str, text: str) -> None:
        w.append({"pfad": rel, "stufe": stufe, "text": text})
    if not str(kopf.get("titel") or "").strip():
        warn("fehler", "Die Seite hat keinen Titel.")
    beschr = str(kopf.get("beschreibung") or "").strip()
    if not beschr:
        warn("hinweis", "Keine Beschreibung für Suchmaschinen (Reiter „Seite“).")
    elif len(beschr) > 170:
        warn("hinweis", f"Die Beschreibung ist {len(beschr)} Zeichen lang; Google zeigt etwa 155.")
    for img in re.findall(r"<img\b[^>]*>", inhalt):
        alt = re.search(r'\balt="([^"]*)"', img)
        if not alt or not alt.group(1).strip():
            name = (re.search(r'src="([^"]+)"', img) or [None, "?"])[1].split("/")[-1]
            warn("hinweis", f"Bild „{name}“ hat keine Bildbeschreibung (wichtig für Barrierefreiheit und Google).")
    for href in re.findall(r'href="([^"]+)"', inhalt):
        if href.startswith("/") and not href.startswith(("/bilder/", "//")):
            ziel = href.split("#")[0].split("?")[0]
            if ziel not in adressen and ziel.rstrip("/") not in {a.rstrip("/") for a in adressen}:
                warn("fehler", f"Der Link „{href}“ führt auf eine Seite, die es nicht gibt.")
        elif href.startswith("http://"):
            warn("hinweis", f"Der Link „{href}“ ist unverschlüsselt (http statt https).")
    for src in re.findall(r'src="(/bilder/[^"]+)"', inhalt) + re.findall(r"url\('(/bilder/[^']+)'\)", inhalt):
        if not (KLON / src.lstrip("/")).exists():
            warn("fehler", f"Das Bild „{src}“ fehlt.")
    if re.search(r"\[noch offen", inhalt, re.I):
        warn("fehler", "Im Text steht noch ein Platzhalter „[noch offen: …]“.")
    if re.search(r"<h[1-4][^>]*>\s*</h[1-4]>", inhalt):
        warn("hinweis", "Eine Überschrift ist leer.")
    blog = kopf.get("blog")
    if blog is not None:
        if not blog.get("bild"):
            warn("hinweis", "Der Artikel hat kein Titelbild für die Übersicht.")
        if not str(blog.get("auszug") or "").strip():
            warn("hinweis", "Der Artikel hat keinen Auszug für die Übersicht.")
    return w


@router.get("/pruefen")
async def pruefen(alle: bool = False):
    adressen = _adressen()
    async with _sperre:
        aend = await _aenderungen()
    if alle:
        pfade = [f.relative_to(KLON / "inhalt").as_posix() for f in (KLON / "inhalt").rglob("*.html")]
    else:
        pfade = [a["datei"][len("inhalt/"):] for a in aend if a["datei"].startswith("inhalt/") and a["art"] != "gelöscht"]
    warnungen: list[dict[str, str]] = []
    for rel in pfade:
        f = KLON / "inhalt" / rel
        if f.exists():
            kopf, inhalt = _lesen(f)
            warnungen += _pruefen_seite(rel, kopf, inhalt, adressen)
    # Menüpunkte, die ins Leere zeigen
    def menue(liste: list[dict[str, Any]]) -> None:
        for p in liste:
            if p.get("href", "").startswith("/") and p["href"] not in adressen:
                warnungen.append({"pfad": "seiten.json", "stufe": "fehler", "text": f"Menüpunkt „{p.get('text')}“ zeigt auf {p['href']}, das gibt es nicht."})
            menue(p.get("unter") or [])
    menue(_menue_lesen().get("navigation", []))
    return {"warnungen": warnungen}


# ---------------------------------------------------------------- Menü

def _menue_pruefen(liste: Any, tiefe: int = 0) -> list[dict[str, Any]]:
    if not isinstance(liste, list):
        raise HTTPException(400, "Menü muss eine Liste sein")
    aus = []
    for p in liste:
        text = str((p or {}).get("text") or "").strip()[:60]
        href = str((p or {}).get("href") or "").strip()[:300]
        if not text or not href:
            raise HTTPException(400, "Jeder Menüpunkt braucht Text und Ziel")
        if not (href.startswith("/") or href.startswith("https://")):
            raise HTTPException(400, f"Ungültiges Ziel „{href}“ (eine Seite /… oder https://…)")
        punkt: dict[str, Any] = {"text": text, "href": href}
        if p.get("unter"):
            if tiefe >= 1:
                raise HTTPException(400, "Das Menü kennt nur eine Unterebene")
            punkt["unter"] = _menue_pruefen(p["unter"], tiefe + 1)
        aus.append(punkt)
    return aus


@router.post("/menue")
async def menue_speichern(d: dict[str, Any]):
    neu = _menue_pruefen(d.get("navigation"))
    async with _sperre:
        cfg = _menue_lesen()
        cfg["navigation"] = neu
        _menue_schreiben(cfg)
    return {"ok": True}


@router.post("/blog-reihenfolge")
async def blog_reihenfolge(d: dict[str, Any]):
    """Reihenfolge der Artikel in der Inspiration-Übersicht (19.10.2026): die Liste
    der Pfade in neuer Reihenfolge; jeder bekommt reihe = Position (1, 2, …).
    Geschrieben wird nur, wo sich die Zahl wirklich ändert."""
    pfade = d.get("pfade")
    if not isinstance(pfade, list) or not pfade:
        raise HTTPException(400, "Reihenfolge fehlt")
    geaendert = 0
    async with _sperre:
        for i, rel in enumerate(pfade, start=1):
            f = _sicherer_pfad(str(rel))
            if not f.exists():
                raise HTTPException(404, f"Artikel {rel} gibt es nicht")
            kopf, inhalt = _lesen(f)
            if not isinstance(kopf.get("blog"), dict):
                raise HTTPException(400, f"{rel} ist kein Blogartikel")
            if kopf["blog"].get("reihe") != i:
                kopf["blog"]["reihe"] = i
                _schreiben(f, kopf, inhalt)
                geaendert += 1
    return {"ok": True, "geaendert": geaendert}


# ---------------------------------------------------------------- Seiten umbenennen und duplizieren

def _links_ersetzen(alt: str, neu: str) -> int:
    """Interne Links auf eine verschobene Seite in allen Seiten nachziehen."""
    n = 0
    muster = re.compile(r'href="' + re.escape(alt) + r'(["#?])')
    for f in (KLON / "inhalt").rglob("*.html"):
        s = f.read_text(encoding="utf-8")
        s2, k = muster.subn(lambda m: f'href="{neu}{m.group(1)}', s)
        if k:
            f.write_text(s2, encoding="utf-8")
            n += k
    return n


@router.post("/umbenennen")
async def umbenennen(d: dict[str, Any]):
    rel = str(d.get("pfad") or "")
    datei = _sicherer_pfad(rel)
    if rel == "index.html" or rel.endswith("/index.html"):
        raise HTTPException(400, "Die Adresse einer Übersichtsseite lässt sich hier nicht ändern")
    name = _slug(str(d.get("name") or ""))
    if not name:
        raise HTTPException(400, "Neuer Name fehlt")
    neu_rel = (rel.rsplit("/", 1)[0] + "/" if "/" in rel else "") + name + ".html"
    ziel = _sicherer_pfad(neu_rel)
    if ziel.exists():
        raise HTTPException(409, "Unter dieser Adresse gibt es schon eine Seite")
    async with _sperre:
        datei.rename(ziel)
        alt_adr, neu_adr = _adresse(rel), _adresse(neu_rel)
        cfg = _menue_lesen()
        def nachziehen(liste: list[dict[str, Any]]) -> None:
            for p in liste:
                if p.get("href") == alt_adr:
                    p["href"] = neu_adr
                nachziehen(p.get("unter") or [])
        nachziehen(cfg["navigation"])
        _menue_schreiben(cfg)
        links = _links_ersetzen(alt_adr, neu_adr)
    return {"pfad": neu_rel, "adresse": neu_adr, "links": links}


@router.post("/duplizieren")
async def duplizieren(d: dict[str, Any]):
    rel = str(d.get("pfad") or "")
    datei = _sicherer_pfad(rel)
    if not datei.exists():
        raise HTTPException(404, "Seite gibt es nicht")
    kopf, inhalt = _lesen(datei)
    stamm = rel[:-5]
    if stamm.endswith("/index"):
        stamm = stamm[:-6] + "-uebersicht"
    neu_rel, n = stamm + "-kopie.html", 2
    while (KLON / "inhalt" / neu_rel).exists():
        neu_rel, n = f"{stamm}-kopie-{n}.html", n + 1
    kopf = {**kopf, "titel": f"{kopf.get('titel', '')} (Kopie)"}
    if kopf.get("blog"):
        kopf["blog"] = {**kopf["blog"]}
    kopf.pop("blogliste", None)
    async with _sperre:
        _schreiben(_sicherer_pfad(neu_rel), kopf, inhalt.replace("<!--blogliste-->", ""))
    return {"pfad": neu_rel, "adresse": _adresse(neu_rel)}


# ---------------------------------------------------------------- Medien

@router.get("/medien")
async def medien():
    texte = [f.read_text(encoding="utf-8") for b in ("inhalt", "bausteine") for f in (KLON / b).rglob("*.html")]
    alles = "\n".join(texte)
    aus = []
    for f in sorted((KLON / "bilder").glob("*"), key=lambda x: -x.stat().st_mtime):
        if f.suffix.lower() not in BILD_ENDUNGEN or f.name == "favicon.png":
            continue
        pfad = "/bilder/" + f.name
        nutzung = alles.count(pfad) + (1 if f.name.startswith("vveorg-logo") else 0)
        aus.append({"pfad": pfad, "groesse": f.stat().st_size, "nutzung": nutzung,
                    "video": f.suffix.lower() == ".mp4"})
    return {"medien": aus}


@router.post("/medien/loeschen")
async def medien_loeschen(d: dict[str, Any]):
    pfad = str(d.get("pfad") or "")
    if not re.fullmatch(r"/bilder/[a-z0-9.\-]+", pfad):
        raise HTTPException(400, "Ungültiger Dateiname")
    f = KLON / pfad.lstrip("/")
    if not f.exists():
        raise HTTPException(404, "Datei gibt es nicht")
    texte = "\n".join(x.read_text(encoding="utf-8") for b in ("inhalt", "bausteine") for x in (KLON / b).rglob("*.html"))
    if pfad in texte or f.name.startswith(("vveorg-logo", "favicon")):
        raise HTTPException(409, "Das Bild wird noch verwendet und lässt sich deshalb nicht löschen")
    async with _sperre:
        f.unlink()
    return {"ok": True}


# ---------------------------------------------------------------- Suchen und Ersetzen über alle Seiten

_TEIL = re.compile(r"(<!--[\s\S]*?-->|<[^>]+>)")


def _im_text(s: str, such: str, ersatz: str | None) -> tuple[str, int]:
    """Nur im sichtbaren Text suchen/ersetzen, nie in Tags oder Marken."""
    teile = _TEIL.split(s)
    n = 0
    for i in range(0, len(teile), 2):
        k = teile[i].count(such)
        if k:
            n += k
            if ersatz is not None:
                teile[i] = teile[i].replace(such, ersatz)
    return "".join(teile), n


@router.get("/suchen")
async def suchen(q: str):
    q = q.strip()
    if len(q) < 2:
        return {"treffer": []}
    aus = []
    for f in sorted((KLON / "inhalt").rglob("*.html")):
        kopf, inhalt = _lesen(f)
        _, n = _im_text(inhalt, q, None)
        n_titel = str(kopf.get("titel") or "").count(q)
        if n or n_titel:
            text = re.sub(r"\s+", " ", _TEIL.sub(" ", inhalt))
            i = text.find(q)
            ausschnitt = ("…" + text[max(0, i - 60): i + len(q) + 60] + "…") if i >= 0 else ""
            rel = f.relative_to(KLON / "inhalt").as_posix()
            aus.append({"pfad": rel, "titel": kopf.get("titel"), "anzahl": n + n_titel, "ausschnitt": ausschnitt})
    return {"treffer": aus}


@router.post("/ersetzen")
async def ersetzen(d: dict[str, Any]):
    such, ersatz = str(d.get("suche") or ""), str(d.get("ersatz") or "")
    if len(such) < 2:
        raise HTTPException(400, "Suchbegriff zu kurz")
    pfade = d.get("pfade")
    gesamt = 0
    async with _sperre:
        for f in sorted((KLON / "inhalt").rglob("*.html")):
            rel = f.relative_to(KLON / "inhalt").as_posix()
            if pfade and rel not in pfade:
                continue
            kopf, inhalt = _lesen(f)
            neu, n = _im_text(inhalt, such, ersatz)
            if str(kopf.get("titel") or "").count(such):
                kopf["titel"] = kopf["titel"].replace(such, ersatz)
                n += 1
            if n:
                _schreiben(f, kopf, neu)
                gesamt += n
    return {"ersetzt": gesamt}


# ---------------------------------------------------------------- Veröffentlichen

@router.post("/veroeffentlichen")
async def veroeffentlichen(d: dict[str, Any]):
    if not d.get("bestaetigt"):
        raise HTTPException(400, "Veröffentlichen braucht deine Bestätigung")
    async with _sperre:
        try:
            aend = await _aenderungen()
            if not aend:
                return {"ok": True, "nichts": True}
            # Erst bauen: was hier scheitert, scheitert auch auf GitHub.
            await _ausfuehren("node", "bauen.js", umgebung={"AUSGABE": VORSCHAU_ORDNER, "BASIS": VORSCHAU_BASIS,
                                                             "EDITOR_RAHMEN": "1"}, zeit=60)
            await _git("add", "-A", "--", *BEREICHE)
            nachricht = str(d.get("nachricht") or "").strip() or (
                "WebSpace: " + ", ".join(sorted({a["datei"].replace("inhalt/", "") for a in aend}))[:180])
            await _git("commit", "-q", "-m", nachricht + "\n\nVeröffentlicht über den WebSpace im VvE Cockpit.")
            try:
                await _git("pull", "-q", "--rebase", zeit=60)
            except WebspaceFehler as e:
                await _git("rebase", "--abort")
                await _git("reset", "-q", "--soft", "HEAD~1")
                raise WebspaceFehler("Auf GitHub gibt es eine neuere Fassung, die sich mit deinen Änderungen überschneidet. "
                                     "Deine Änderungen sind nicht verloren; Neo oder Claude müssen das zusammenführen. "
                                     f"({e})") from e
            await _git("push", "-q", "origin", "HEAD:main", zeit=120)
            sha = (await _git("rev-parse", "--short", "HEAD")).strip()
        except WebspaceFehler as e:
            raise HTTPException(502, str(e)) from e
    _lauf_merker["zeit"] = 0
    return {"ok": True, "sha": sha, "dateien": len(aend)}


@router.post("/verwerfen")
async def verwerfen(d: dict[str, Any]):
    """Nicht veröffentlichte Änderungen zurücknehmen -- eine Seite oder alle."""
    rel = d.get("pfad")
    async with _sperre:
        try:
            if rel:
                ziel = "inhalt/" + _sicherer_pfad(rel).relative_to(KLON / "inhalt").as_posix()
                bekannt = (await _git("ls-files", "--", ziel)).strip()
                if bekannt:
                    await _git("checkout", "--", ziel)
                else:
                    (KLON / ziel).unlink(missing_ok=True)
            else:
                await _git("checkout", "--", *BEREICHE)
                await _git("clean", "-fdq", "--", "inhalt", "bilder")
        except WebspaceFehler as e:
            raise HTTPException(502, str(e)) from e
    return {"ok": True}


def kontext_text(pfad: str | None) -> str:
    """Für Talk: worauf Veiko im WebSpace gerade schaut."""
    if not KLON.exists():
        return "VEIKO IST IM WEBSPACE (Editor für die Website veikovoneckern.org)."
    teil = ""
    if pfad:
        try:
            kopf, inhalt = _lesen(_sicherer_pfad(pfad))
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inhalt))[:1500]
            teil = f"\nGeöffnete Seite: {kopf.get('titel')} ({_adresse(pfad)}). Inhalt (gekürzt): {text}"
        except Exception:  # noqa: BLE001
            teil = ""
    return ("VEIKO IST IM WEBSPACE (Editor für die Website veikovoneckern.org). Änderungen sind erst nach "
            "„Veröffentlichen“ öffentlich; das macht Veiko selbst per Klick, nie Talk." + teil)


# ---------------------------------------------------------------- Überblick im Stack
# Veiko, 19.10.2026: "Im Stack moechte ich ganz unten auch einen Abschnitt haben, der
# mir die Informationen zu dem gibt, was ich auf meiner Webseite habe und wie das
# angebunden ist -- welche Hauptseiten gibt es, wie aktuell ist meine Webseite.
# Kuenftig moechte ich da noch mehr haben, und das soll dann immer aktuell sein."
# Deshalb wird nichts davon von Hand gepflegt: Menue, Seiten und Blog kommen aus dem
# Klon, die Veroeffentlichung aus GitHub, die Erreichbarkeit aus einem echten Abruf.
# Kommt etwas dazu (eine Seite, ein Menuepunkt, eine Domain), steht es von selbst da.
_stack_merker: dict[str, Any] = {"zeit": 0.0, "wert": None}


async def _live_pruefen() -> dict[str, Any]:
    beginn = time.time()
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as c:
            r = await c.get(LIVE + "/")
        return {"erreichbar": r.status_code < 400, "status": r.status_code, "ms": round((time.time() - beginn) * 1000),
                "server": r.headers.get("server"), "geaendert": r.headers.get("last-modified")}
    except httpx.HTTPError as e:
        return {"erreichbar": False, "fehler": str(e)[:200]}


@router.get("/stack")
async def stack_ueberblick(frisch: int = 0):
    if not frisch and time.time() - _stack_merker["zeit"] < 60 and _stack_merker["wert"]:
        return _stack_merker["wert"]
    async with _sperre:
        try:
            await _klon_sicher()
            aend = await _aenderungen()
            letzter = (await _git("log", "-1", "--format=%h%x1f%s%x1f%cI")).strip().split("\x1f")
        except WebspaceFehler as e:
            raise HTTPException(503, str(e)) from e
        try:   # Stand auf GitHub (origin/main) gegen den Klon: liegt etwas nur hier?
            voraus = (await _git("rev-list", "--count", "origin/main..HEAD")).strip()
        except WebspaceFehler:
            voraus = ""
    cfg = _menue_lesen()
    seiten, blog = [], []
    for f in sorted((KLON / "inhalt").rglob("*.html")):
        rel = f.relative_to(KLON / "inhalt").as_posix()
        kopf, inhalt = _lesen(f)
        e = {"pfad": rel, "titel": kopf.get("titel") or rel, "adresse": _adresse(rel),
             "datum": kopf.get("datum"), "zeichen": len(re.sub(r"<[^>]+>", "", inhalt))}
        (blog if kopf.get("blog") else seiten).append(e)
    blog.sort(key=lambda b: str(b.get("datum") or ""), reverse=True)
    domain = ""
    try:
        domain = (KLON / "CNAME").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    workflows = sorted(p.name for p in (KLON / ".github" / "workflows").glob("*.y*ml")) if (KLON / ".github" / "workflows").exists() else []
    wert = {"live": LIVE, "domain": domain or None, "mail": cfg.get("mail"), "repo": REPO_API.replace("api.github.com/repos", "github.com"),
            "workflows": workflows, "menue": cfg.get("navigation", []), "seiten": seiten, "blog": blog,
            "unveroeffentlicht": len(aend), "nur_hier": int(voraus) if voraus.isdigit() else None,
            "letzter": {"sha": letzter[0], "text": letzter[1], "zeit": letzter[2]} if len(letzter) == 3 else None,
            "veroeffentlichung": await _veroeffentlichung(), "erreichbar": await _live_pruefen(), "geprueft": time.time()}
    _stack_merker.update(zeit=time.time(), wert=wert)
    return wert


def stack_text() -> str:
    """Fuer Talk (Stack-Seite): der zuletzt abgerufene Ueberblick, ohne neuen Abruf."""
    w = _stack_merker.get("wert")
    if not w:
        return "WEBSITE veikovoneckern.org: Überblick noch nicht abgerufen (steht ganz unten im Stack)."
    v = w.get("veroeffentlichung") or {}
    menue = "; ".join(m["text"] + (" (" + ", ".join(u["text"] for u in m.get("unter", [])) + ")" if m.get("unter") else "") for m in w["menue"])
    return (f"WEBSITE {w['live']} (GitHub Pages aus {w['repo']}, Domain {w.get('domain') or '?'} bei one.com): "
            f"{'erreichbar' if (w.get('erreichbar') or {}).get('erreichbar') else 'NICHT erreichbar'}; "
            f"letzte Veröffentlichung {v.get('zeit') or 'unbekannt'} ({v.get('ergebnis') or v.get('stand') or '?'}); "
            f"{w['unveroeffentlicht']} unveröffentlichte Änderungen. Menü: {menue}. "
            f"{len(w['seiten'])} Seiten, {len(w['blog'])} Blogbeiträge" + (f", neuester: {w['blog'][0]['titel']}" if w["blog"] else "") + ".")
