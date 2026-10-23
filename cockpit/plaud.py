"""
PLAUD-ABRUF DER NEUEN FASSUNG (23.10.2026) -- ohne das alte Cockpit.

Bis dahin holte das ALTE Cockpit die Sprachnotizen (vvec-plaud-sync.timer, /opt/vvec/plaud_sync.py
als Nutzer vvec, Ablage /var/lib/vvec/plaud), und diese Fassung las die Ablage nur mit. Veiko will
das alte Cockpit loeschen -- dann kaeme keine einzige Notiz mehr an, und Notizen sind der Anfang
von allem, was das Team tut.

Jetzt holt diese Fassung selbst: als vveadmin, mit der offiziellen Plaud-CLI (/usr/local/bin/plaud,
liegt global und laeuft fuer jeden Nutzer), Anmeldung in ~/.plaud (einmal von Veiko aus dem alten
Cockpit kopiert, siehe einrichten_befehl()), Ablage daten/plaud. Gleiches Dateiformat und GLEICHE
Kennungen wie bisher -- stab.plaud_scannen erkennt Bekanntes an plaud_id = Dateiname, beim Umzug
kommt also nichts doppelt.

Uebernommen aus dem alten plaud_sync.py, weil jede dieser Regeln aus einem echten Ausfall stammt:
  - DIE CLI ENDET AUCH BEI EINEM FEHLER MIT 0 (30.09.2026: abgelaufene Anmeldung, rc 0, auf stderr
    "[AUTH_FAILED]") -- drei Wochen kam nichts, ohne dass irgendwo ein Fehler stand. Ausgewertet
    wird deshalb die Fehlermarke selbst.
  - KENNUNGEN TRAGEN SEIT SEPTEMBER EIN PRAEFIX ("of_ef86…"); gespeichert wird ohne, an die CLI
    geht die volle Kennung.
  - EINE LEERE LISTE IST FAST IMMER EIN FEHLER, KEIN LEERES KONTO -- der Index bleibt dann stehen.
  - MEHR ALS 50 "NEUE" IN EINEM LAUF heisst fast sicher: Kennungsformat geaendert -- anhalten,
    statt den ganzen Bestand doppelt zu holen.
  - SCHNELLPRUEFUNG im Minutentakt: nur Seite 1 ansehen; erst wenn dort etwas Unbekanntes steht,
    der volle Lauf.
  - NUR TRANSKRIPTE -- die Verarbeitung macht das Team, nicht Plauds eigene Zusammenfassung.

Der Stand jedes Laufs steht in daten/plaud/stand.json (ok/fehler, Grund, neu) -- die Empfehlungen
im Stack lesen ihn, damit ein Stillstand nicht still bleibt.

Aufruf: .venv/bin/python -m cockpit.plaud [--schnell | --all]   (Zeitgeber vve-cp-r2-plaud.timer)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .konfig import ALT_DATEN, DATEN

ORDNER = DATEN / "plaud"
INDEX = ORDNER / "index.json"
STAND = ORDNER / "stand.json"
TOKENS = Path.home() / ".plaud" / "tokens.json"
ALT_ORDNER = ALT_DATEN / "plaud"
SEITEN, SEITE = 3, 100
MAX_NEU = 50
SUCHORTE = ["/usr/local/bin/plaud", "/usr/bin/plaud"]

ID_RE = re.compile(r"(?<![0-9a-z])((?:[a-z]{1,6}_)?([0-9a-f]{12,}(?:-[0-9a-f]{4,}){0,4}))\b", re.I)
PRAEFIX_RE = re.compile(r"^[a-z]{1,6}_", re.I)
DATUM_RE = re.compile(r"(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?)")


class PlaudFehler(Exception):
    pass


# ---------------------------------------------------------------- Einrichtung
def eingerichtet() -> bool:
    return TOKENS.is_file()


def einrichten_befehl() -> str:
    """Einmal von Veiko (Passwort): die Plaud-Anmeldung des alten Cockpits uebernehmen und dessen
    Abruf abschalten. Abschalten gehoert dazu: zwei Abrufe mit derselben Anmeldung frischen sie
    gegenseitig auf, und einer davon steht dann mit einer verbrauchten Anmeldung da."""
    return ("mkdir -p ~/.plaud && sudo cp -r /var/lib/vvec/.plaud/. ~/.plaud/ && sudo chown -R $USER: ~/.plaud "
            "&& chmod 700 ~/.plaud && chmod 600 ~/.plaud/* && sudo systemctl disable --now vvec-plaud-sync.timer "
            "&& echo uebernommen")


def ordner() -> Path:
    """Wo die Notizen liegen, die das Team liest: die eigene Ablage, sobald der eigene Abruf
    eingerichtet ist -- vorher wie bisher die des alten Cockpits."""
    return ORDNER if eingerichtet() else ALT_ORDNER


def stand() -> dict[str, Any]:
    try:
        s = json.loads(STAND.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    s["eingerichtet"] = eingerichtet()
    try:
        s["synced"] = json.loads((ordner() / "index.json").read_text(encoding="utf-8")).get("synced")
    except (OSError, ValueError):
        s["synced"] = None
    return s


def _stand_setzen(**w: Any) -> None:
    ORDNER.mkdir(parents=True, exist_ok=True)
    s = {}
    try:
        s = json.loads(STAND.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    s.update(w)
    tmp = STAND.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STAND)


# ---------------------------------------------------------------- CLI
def _cli() -> str:
    gefunden = shutil.which("plaud")
    if gefunden:
        return gefunden
    for p in SUCHORTE:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    raise PlaudFehler("Plaud-CLI nicht gefunden (/usr/local/bin/plaud). Installieren: sudo npm install -g @plaud-ai/cli")


def _lauf(args: list[str], timeout: int = 120) -> str | None:
    try:
        p = subprocess.run([_cli(), *args], capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(Path.home())})
    except subprocess.TimeoutExpired:
        return None
    fehler = (p.stderr or "").strip()
    if p.returncode == 2 or "[AUTH_FAILED]" in fehler:
        raise PlaudFehler("Plaud-Anmeldung abgelaufen oder ungültig. Neu anmelden: auf dem Laptop „plaud login“, dann "
                          "~/.plaud/tokens.json auf den Server nach ~/.plaud/ kopieren.")
    if p.returncode != 0 or re.search(r"✗\s*\[[A-Z_]+\]", fehler):
        _stand_setzen(letzte_cli_meldung=fehler[:300])
        return None
    return p.stdout


def kennung(roh: str) -> str:
    return PRAEFIX_RE.sub("", str(roh))


def liste_lesen(roh: str | None) -> list[dict[str, Any]]:
    """[{id, cli_id, name, created_at}] -- erst JSON, sonst die Textausgabe der CLI."""
    roh = (roh or "").strip()
    if not roh:
        return []
    if roh[0] in "[{":
        try:
            d = json.loads(roh)
            items = d if isinstance(d, list) else d.get("data", d.get("files", []))
            return [{"id": kennung(i.get("id")), "cli_id": str(i.get("id")), "name": i.get("name") or "Ohne Titel",
                     "created_at": i.get("created_at") or i.get("start_at")} for i in items if i.get("id")]
        except (ValueError, AttributeError):
            pass
    out, gesehen = [], set()
    for z in roh.splitlines():
        m = ID_RE.search(z)
        if not m or m.group(2) in gesehen:
            continue
        gesehen.add(m.group(2))
        d = DATUM_RE.search(z)
        name = z.replace(m.group(1), "").strip(" |\t-─│")
        if d:
            name = name.replace(d.group(1), "").strip(" |\t-─│")
        out.append({"id": m.group(2), "cli_id": m.group(1), "name": name or "Ohne Titel", "created_at": d.group(1) if d else None})
    return out


def _ts(v: Any) -> float:
    if not v:
        return 0.0
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T")).replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return 0.0


# ---------------------------------------------------------------- Umzug
def bestand_uebernehmen() -> int:
    """Einmal: die bisher vom alten Cockpit geholten Notizen in die eigene Ablage kopieren -- gleiche
    Dateinamen, gleicher Inhalt. Sonst hielte der eigene Abruf sie fuer neu (Grenze MAX_NEU) und das
    Team bekaeme nichts davon in seiner Ablage zu sehen."""
    ORDNER.mkdir(parents=True, exist_ok=True)
    n = 0
    if ALT_ORDNER.is_dir():
        for f in ALT_ORDNER.glob("*.json"):
            if f.name == "index.json":
                continue
            ziel = ORDNER / f.name
            if not ziel.exists():
                try:
                    shutil.copy2(f, ziel)
                    n += 1
                except OSError:
                    pass
    return n


# ---------------------------------------------------------------- Abruf
def _schnell_nichts_neu() -> bool:
    stapel = liste_lesen(_lauf(["files", "--page", "1", "--page-size", str(SEITE)]))
    if not stapel or any(not (ORDNER / f"{i['id']}.json").exists() for i in stapel):
        return False   # keine Antwort ist KEIN "nichts Neues" -- dann der volle Lauf, der meldet ordentlich
    _index_zeit()
    return True


def _index_zeit() -> None:
    try:
        idx = json.loads(INDEX.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        idx = {"notes": [], "count": 0}
    idx["synced"] = time.time()
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(INDEX)


def abrufen(schnell: bool = False, alle: bool = False) -> dict[str, Any]:
    if not eingerichtet():
        raise PlaudFehler("Plaud ist für die neue Fassung noch nicht eingerichtet (~/.plaud/tokens.json fehlt).")
    if not any(ORDNER.glob("*.json")) or not (ORDNER / ".uebernommen").exists():
        n = bestand_uebernehmen()
        (ORDNER / ".uebernommen").write_text(str(n), encoding="utf-8")
    if schnell and not alle and _schnell_nichts_neu():
        _stand_setzen(zeit=time.time(), ok=True, fehler=None, neu=0)
        return {"neu": 0, "schnell": True}
    liste: list[dict[str, Any]] = []
    for s in range(1, SEITEN + 1):
        stapel = liste_lesen(_lauf(["files", "--page", str(s), "--page-size", str(SEITE)]))
        if not stapel:
            break
        liste += stapel
        if len(stapel) < SEITE:
            break
    vorhanden = [f for f in ORDNER.glob("*.json") if f.name not in ("index.json", "stand.json")]
    if not liste:
        if vorhanden and not alle:
            raise PlaudFehler(f"Plaud lieferte keine einzige Aufnahme, hier liegen aber {len(vorhanden)}. "
                              "Anmeldung und Ausgabeformat der CLI prüfen.")
    fehlend = [i for i in liste if not (ORDNER / f"{i['id']}.json").exists()]
    if len(fehlend) > MAX_NEU and not alle:
        raise PlaudFehler(f"{len(fehlend)} Aufnahmen gelten als neu (Grenze {MAX_NEU}) -- das spricht für ein geändertes "
                          f"Kennungsformat, nicht für so viele neue Notizen. Nichts geholt. Beispiel: {fehlend[0].get('cli_id')!r}.")
    neu, ohne_text, notizen = 0, 0, []
    for it in liste:
        ziel = ORDNER / f"{it['id']}.json"
        if ziel.exists() and not alle:
            try:
                r = json.loads(ziel.read_text(encoding="utf-8"))
                notizen.append({k: r.get(k) for k in ("id", "name", "created_at", "created_ts", "chars", "source")})
            except (OSError, ValueError):
                pass
            continue
        text = (_lauf(["transcript", it.get("cli_id") or it["id"]]) or "").strip()
        rec = {"id": it["id"], "name": it["name"], "created_at": it.get("created_at"), "created_ts": _ts(it.get("created_at")),
               "summary": "", "transcript": text, "chars": len(text), "source": "plaud-cli", "fetched": time.time()}
        if not text:
            # Noch nicht transkribiert: NICHT ablegen -- sonst gaelte sie als bekannt und kaeme nie mehr.
            ohne_text += 1
            continue
        tmp = ziel.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(ziel)
        notizen.append({k: rec[k] for k in ("id", "name", "created_at", "created_ts", "chars", "source")})
        neu += 1
    idx = {"synced": time.time(), "synced_iso": datetime.now(timezone.utc).isoformat(), "count": len(notizen),
           "notes": sorted(notizen, key=lambda n: n.get("created_ts") or 0, reverse=True)}
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(INDEX)
    _stand_setzen(zeit=time.time(), ok=True, fehler=None, neu=neu, ohne_text=ohne_text, gesamt=len(notizen))
    return {"neu": neu, "ohne_text": ohne_text, "gesamt": len(notizen)}


if __name__ == "__main__":
    if not eingerichtet():
        # Vor der Einrichtung holt noch das alte Cockpit -- kein Fehler, nur nichts zu tun.
        print("Plaud: noch nicht eingerichtet (~/.plaud/tokens.json fehlt) -- das alte Cockpit holt.")
        sys.exit(0)
    try:
        r = abrufen(schnell="--schnell" in sys.argv, alle="--all" in sys.argv)
        print(f"Plaud {datetime.now():%H:%M:%S}: {r}")
    except PlaudFehler as f:
        _stand_setzen(zeit=time.time(), ok=False, fehler=str(f))
        print(f"FEHLER: {f}", file=sys.stderr)
        sys.exit(1)
