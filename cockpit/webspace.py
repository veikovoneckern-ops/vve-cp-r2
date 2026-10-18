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
        kopf["blog"] = {"reihe": (min(reihen) - 1) if reihen else 1, "bild": "", "auszug": ""}
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
    bilder = sorted(f.name for f in (KLON / "bilder").glob("*") if f.suffix.lower() in BILD_ENDUNGEN)
    nutzer = (f"SEITE: {kopf.get('titel', '')} ({d.get('pfad', '')})\n"
              f"VORHANDENE BILDER: {', '.join(bilder)}\n\n"
              f"AKTUELLER HTML-AUSSCHNITT:\n{inhalt}\n\nAUFTRAG VON VEIKO:\n{auftrag}")
    modell = llm.vorgabe("arbeit")
    try:
        antwort = await llm.mit_zweck("webspace:" + str(d.get("pfad", "")),
                                      llm.chat(modell, ASSISTENT_SYSTEM, [{"role": "user", "content": nutzer}],
                                               denken=False, num_ctx=32768, timeout=900))
    except llm.ModellFehler as e:
        raise HTTPException(503, f"Das Modell hat nicht geantwortet: {e}") from e
    m = re.search(r"<<<SEITE>>>\s*([\s\S]*?)\s*<<<ENDE>>>", antwort)
    if not m:
        raise HTTPException(502, "Das Modell hat keine Seite geliefert. Bitte den Auftrag noch einmal, etwas konkreter.")
    neu = m.group(1).strip()
    neu = re.sub(r"^```(?:html)?\s*|\s*```$", "", neu)
    # Prüfungen statt Vertrauen: verbotene Teile fliegen raus, feste Marken müssen bleiben.
    neu = re.sub(r"<script[\s\S]*?</script>", "", neu, flags=re.I)
    neu = re.sub(r"<style[\s\S]*?</style>", "", neu, flags=re.I)
    hinweise = []
    for marke in re.findall(r"<!--(?:baustein [a-z0-9-]+|blogliste)-->", inhalt):
        if marke not in neu:
            neu += "\n\n" + marke
            hinweise.append(f"{marke} fehlte in der Antwort und wurde wieder angehängt")
    if inhalt and len(neu) < 0.4 * len(inhalt) and not re.search(r"kürz|streich|lösch|entfern|weg", auftrag, re.I):
        raise HTTPException(502, "Das Modell hat die Seite stark gekürzt, ohne dass du das verlangt hast. Nichts übernommen.")
    erklaerung = antwort[m.end():].strip()[:800]
    return {"inhalt": neu, "erklaerung": erklaerung, "hinweise": hinweise, "modell": modell}


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
