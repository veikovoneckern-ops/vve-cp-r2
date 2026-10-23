"""
DER MORGENBERICHT PER MAIL (23.10.2026) -- was der Stab seit dem letzten Bericht getan hat.

Bis zum 23.10. schickte das ALTE Cockpit jeden Morgen um 07:00 einen "Stab-Bericht" an Veikos
private Adresse (vvec-tagesbericht.timer, backend/vorgang.py). Mit dem Abschalten des alten
Cockpits fiel er weg; Veiko wollte ihn behalten. Nachgebaut auf den Daten DIESER Fassung --
der alte las sein eigenes Vorgangs-Journal, das es hier nicht gibt.

Abschnitte, nur wenn sie etwas enthalten:
  Achtung        -- seit 6 Stunden keine Plaud-Notiz angekommen; Sicherung gescheitert oder
                    aelter als zwei Tage. (Vom 07. bis 30.09.2026 kam keine Notiz an, und
                    niemand merkte es -- deshalb steht das ganz oben.)
  Wartet auf dich -- offene Entscheidungen (Rueckfragen, Freigaben) des Stabs.
  Neu entstanden -- Ergebnisse seit dem letzten Bericht, mit Daniels Urteil im Klartext.
  Faellig        -- offene Aufgaben, die heute faellig oder ueberfaellig sind.
  Laeuft gerade  -- dieselbe Liste wie die Lage im Cockpit (ueberblick.lage()).

Nichts zu berichten -> keine Mail. Eine taegliche Leermeldung liest nach einer Woche niemand
mehr, und dann auch die eine nicht, auf die es ankommt.

Um 05:00 statt 07:00: Veiko arbeitet ab 5 Uhr (Nachtplan); bis dahin ist die Nacht durch
(RSI, Sicherung, Daily Tasks, Morgens bereit), und der Bericht beschreibt sie vollstaendig.
Der Zeitraum ist "seit dem letzten Bericht", hoechstens eine Woche.

Verschickt wird direkt per SMTP ueber mail._smtp_senden -- derselbe Weg wie jede andere Mail
aus dem Cockpit, aber OHNE Entwurf in der Mail-Liste: ein Bericht an sich selbst ist kein
Schriftverkehr, und 365 Entwuerfe im Jahr wuerden die Liste unbrauchbar machen.
"""
from __future__ import annotations

import asyncio
import datetime
import html as htmlmod
import time
import traceback
from typing import Any
from zoneinfo import ZoneInfo

from . import db

BERLIN = ZoneInfo("Europe/Berlin")
UM = (5, 0)
VORGABE_AN = "von.eckern@outlook.de"   # dieselbe Adresse wie beim alten Cockpit ("VvE-Priv")
SCHALTER = "bericht_aktiv"
EMPFAENGER = "bericht_an"
STAND = "tagesbericht"
WEGE = (("Im Tailnet", "https://vveorgxais.tail4ca1ab.ts.net"),
        ("Unterwegs", "https://cockpit.vveorgxais.org"))
# Die beiden Hostnamen stehen hier woertlich -- die Regel "kein Hostname" gilt fuer fetch()
# im Cockpit, nicht fuer einen Link in einer Mail, die ausserhalb des Cockpits gelesen wird.


def an() -> bool:
    return bool(db.einstellung(SCHALTER, True))


def empfaenger() -> str:
    return str(db.einstellung(EMPFAENGER, VORGABE_AN) or VORGABE_AN)


def stand() -> dict[str, Any]:
    s = db.einstellung(STAND, {}) or {}
    return {**s, "an": an(), "empfaenger": empfaenger(), "um": f"{UM[0]:02d}:{UM[1]:02d}"}


def _h(x: Any) -> str:
    return htmlmod.escape(str(x or ""))


def _wann(t: float | None) -> str:
    return datetime.datetime.fromtimestamp(t, BERLIN).strftime("%d.%m. %H:%M") if t else "nie"


def bauen(seit: float | None = None) -> dict[str, str] | None:
    """Betreff, Text und HTML -- oder None, wenn nichts zu berichten ist."""
    from . import sicherung, stab, ueberblick
    from .api import kurztitel
    jetzt = time.time()
    if seit is None:
        seit = float((db.einstellung(STAND, {}) or {}).get("zeit") or 0)
    seit = max(seit, jetzt - 7 * 86400)

    achtung: list[str] = []
    sync = stab.gesundheit().get("sync")
    if sync and jetzt - float(sync) > 6 * 3600:
        achtung.append(f"Seit {int((jetzt - float(sync)) // 3600)} Stunden ist keine Sprachnotiz mehr von Plaud angekommen -- "
                       "das Team hat dadurch nichts Neues zu tun. Häufigste Ursache: die Plaud-Anmeldung ist abgelaufen.")
    si = sicherung.stand()
    if si.get("eingerichtet"):
        if si.get("zustand") == "fehler":
            achtung.append("Die nächtliche Sicherung ist gescheitert: " + str(si.get("fehler") or "")[:200])
        elif si.get("zeit") and jetzt - float(si["zeit"]) > 48 * 3600:
            achtung.append(f"Die letzte Sicherung ist vom {_wann(si['zeit'])} -- älter als zwei Tage.")

    ents = db.alle("SELECT e.frage, e.wer, v.titel AS vorgang FROM entscheidungen e LEFT JOIN vorgaenge v ON v.id=e.vorgang_id "
                   "WHERE e.stand='offen' ORDER BY e.erstellt DESC LIMIT 10")
    neu = [e for e in stab.neu_entstanden(tage=8, anzahl=40) if float(e.get("bearbeitet") or e.get("erstellt") or 0) >= seit]
    heute = datetime.datetime.now(BERLIN).date().isoformat()
    faellig = db.alle("SELECT a.titel, a.faellig, p.name AS projekt FROM aufgaben a LEFT JOIN projekte p ON p.id=a.projekt_id "
                      "WHERE a.status!='erledigt' AND COALESCE(a.archiviert,0)=0 AND COALESCE(a.faellig,'')!='' "
                      "AND a.faellig<=? ORDER BY a.faellig LIMIT 15", (heute,))
    lage = ueberblick.lage()
    notizen_neu = db.wert("SELECT COUNT(*) FROM notizen WHERE erstellt>=?", (seit,)) or 0
    from . import rsi_serie
    rels = [r for r in rsi_serie.releases() if r["zeit"] >= seit]      # RSI-Releases seit dem letzten Bericht

    if not (achtung or ents or neu or faellig or rels):
        return None

    t: list[str] = []
    h: list[str] = []

    def abschnitt(titel: str) -> None:
        t.append("\n" + titel.upper() + "\n" + "-" * len(titel))
        h.append(f'<h3 style="margin:22px 0 8px;font-size:15px;color:#8f1d18">{_h(titel)}</h3>')

    if achtung:
        abschnitt("Achtung")
        for a in achtung:
            t.append(a)
            h.append(f'<p style="background:#fdecea;padding:10px 12px;border-radius:8px">{_h(a)}</p>')
    if rels:
        abschnitt("Neues Release des Cockpits")
        for r in rels:
            satz = (f"{_wann(r['zeit'])}: " + ", ".join(p["titel"] for p in r["punkte"])
                    + (" -- inzwischen zurückgenommen." if r.get("zurueckgenommen") else ". Zurücknehmen geht auf der Seite RSI oder in Talk."))
            t.append(satz)
            h.append(f"<p>{_h(satz)}</p>")
    if ents:
        abschnitt(f"Wartet auf dich ({len(ents)})")
        h.append("<ul>")
        for e in ents:
            wer = stab.rollen_name(e["wer"]) if e.get("wer") else ""
            t.append(f"- {e['frage']}" + (f" ({e['vorgang']})" if e.get("vorgang") else "") + (f" -- {wer}" if wer else ""))
            h.append(f"<li>{_h(e['frage'])}" + (f" <span style='color:#6b7280'>({_h(e['vorgang'])}"
                     + (f", {_h(wer)}" if wer else "") + ")</span>" if e.get("vorgang") or wer else "") + "</li>")
        h.append("</ul>")
    if neu:
        abschnitt(f"Neu entstanden ({len(neu)})")
        h.append("<ul>")
        for e in neu[:20]:
            # Derselbe Kurztitel wie im Ueberblick-Fenster -- sonst stuende hier mancher Auftragstext im Wortlaut.
            titel = kurztitel({**(db.holen("ergebnisse", e["id"]) or {}), "vorgang_titel": e.get("vorgang_titel")}) or "Ergebnis"
            unter = ", ".join(x for x in (e.get("wer_name"), e.get("projekt_name")) if x)
            t.append(f"- {titel}" + (f" ({unter})" if unter else "") + f": {e.get('urteil_text') or ''}")
            h.append(f"<li><b>{_h(titel)}</b>" + (f" <span style='color:#6b7280'>({_h(unter)})</span>" if unter else "")
                     + f"<br><span style='color:#374151'>{_h(e.get('urteil_text'))}</span></li>")
        h.append("</ul>")
    if faellig:
        abschnitt(f"Heute fällig oder überfällig ({len(faellig)})")
        h.append("<ul>")
        for a in faellig:
            try:
                datum = "heute" if a["faellig"][:10] == heute else datetime.date.fromisoformat(a["faellig"][:10]).strftime("%d.%m.")
            except ValueError:
                datum = a["faellig"]
            t.append(f"[ ] {a['titel']} ({datum}" + (f", {a['projekt']}" if a.get("projekt") else "") + ")")
            h.append(f"<li>&#9744; {_h(a['titel'])} <span style='color:#6b7280'>({_h(datum)}"
                     + (f", {_h(a['projekt'])}" if a.get("projekt") else "") + ")</span></li>")
        h.append("</ul>")
    if lage.get("laeuft") or notizen_neu:
        abschnitt("Läuft gerade")
        satz = (f"{notizen_neu} neue Notiz(en) seit dem letzten Bericht."
                + (" In Arbeit: " + "; ".join(lage["laeuft"][:5]) + "." if lage.get("laeuft") else ""))
        t.append(satz)
        h.append(f"<p>{_h(satz)}</p>")

    t.append("\nIm Cockpit:")
    links = []
    for wo, url in WEGE:
        t.append(f"  {wo}: {url}")
        links.append(f'<a href="{_h(url)}">{_h(wo)}</a>')
    h.append('<p style="margin-top:24px;color:#6b7280">Im Cockpit: ' + " · ".join(links) + "</p>")

    teile = ["neues Release" if rels else "", f"{len(ents)} wartet auf dich" if ents else "", f"{len(neu)} neu" if neu else "",
             f"{len(faellig)} fällig" if faellig else "", "Achtung" if achtung else ""]
    datum = datetime.datetime.now(BERLIN).strftime("%d.%m.")
    betreff = f"Stab-Bericht {datum}: " + ", ".join(x for x in teile if x)
    kopf = (f'<p style="color:#6b7280">Seit dem letzten Bericht ({_h(_wann(seit))}).</p>')
    html = ('<div style="font-family:Calibri,Arial,sans-serif;font-size:11pt;line-height:1.45">'
            + kopf + "".join(h) + "</div>")
    return {"betreff": betreff, "text": f"Seit dem letzten Bericht ({_wann(seit)}).\n" + "\n".join(t), "html": html}


async def schicken(erzwingen: bool = False) -> dict[str, Any]:
    """Bauen und verschicken. erzwingen: auch bei ausgeschaltetem Schalter (Knopf "Jetzt schicken")."""
    from . import mail
    if not erzwingen and not an():
        return {"ok": False, "grund": "Der Morgenbericht ist ausgeschaltet."}
    if not mail.smtp_stand()["ok"]:
        raise ValueError("Der Postausgang ist nicht eingerichtet.")
    b = bauen()
    jetzt = time.time()
    if not b:
        db.einstellung_setzen(STAND, {**(db.einstellung(STAND, {}) or {}), "geprueft": jetzt, "leer": True})
        return {"ok": True, "gesendet": False, "grund": "Nichts zu berichten -- keine Mail."}
    await asyncio.to_thread(mail._smtp_senden, {"an": empfaenger(), "betreff": b["betreff"], "text": b["text"], "html": b["html"]})
    # Bestehende Felder behalten -- "tag" ist die Marke der Schleife; ginge sie verloren, kaeme in zwei Minuten der naechste Bericht.
    db.einstellung_setzen(STAND, {**(db.einstellung(STAND, {}) or {}), "zeit": jetzt, "geprueft": jetzt, "betreff": b["betreff"],
                                  "an_adresse": empfaenger(), "fehler": None, "leer": False})
    return {"ok": True, "gesendet": True, "betreff": b["betreff"]}


async def schleife() -> None:
    await asyncio.sleep(200)
    while True:
        try:
            jetzt = datetime.datetime.now(BERLIN)
            heute = jetzt.date().isoformat()
            s = db.einstellung(STAND, {}) or {}
            if an() and (jetzt.hour, jetzt.minute) >= UM and jetzt.hour < 12 and s.get("tag") != heute:
                db.einstellung_setzen(STAND, {**s, "tag": heute})
                try:
                    await schicken()
                except Exception as e:  # noqa: BLE001 -- im Stand vermerken; die Settings zeigen es
                    db.einstellung_setzen(STAND, {**(db.einstellung(STAND, {}) or {}), "fehler": f"{e}"[:300], "tag": heute})
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        await asyncio.sleep(120)
