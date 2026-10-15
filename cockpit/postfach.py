"""
E-MAILS ANS COCKPIT -- eine Mail wird bearbeitet wie eine Plaud-Notiz.

Veiko (15.10.2026): "ich möchte auch eine E-Mail ans Cockpit schicken können,
und die Bearbeitung soll wie bei einer Plaud-Notiz erfolgen." Also: Mail ->
Notiz (quelle 'mail') -> Vorgang -> Jason ordnet ein, leitet Aufgaben ab, die
Fachrolle arbeitet aus, Daniel prueft. Kein eigener Weg danach.

Warum IMAP und nicht ein Mailserver auf der eigenen Maschine: eingehende Mail
braucht einen oeffentlich erreichbaren Port 25, MX-Eintraege und Spamschutz --
genau die Angriffsflaeche, die hier gerade erst geschlossen wurde (ufw-Fund vom
10.09.). Ein Postfach beim eigenen Anbieter abzuholen kommt ohne jede offene
Tuer aus; der Server fragt nur hinaus.

Drei Riegel, weil diese Adresse von aussen beschreibbar ist:
  1. Nur Absender aus VVEC_MAIL_ERLAUBT. Fehlt die Liste, wird NICHTS
     verarbeitet -- ein leerer Filter darf nie "alle" heissen.
  2. Meldet der Anbieter im Kopf Authentication-Results ein Scheitern von
     SPF, DKIM oder DMARC, wird die Mail abgewiesen: ein gefaelschter Absender
     ist der naheliegende Weg, dem Stab Auftraege unterzuschieben.
  3. Danach gelten dieselben Vertrauensstufen wie fuer jede Notiz: kein Geld,
     keine Mail nach aussen, kein Loeschen.

Die Zugangsdaten stehen in ~/.config/vve-cp-r2.env (nur fuer vveadmin lesbar),
nie im Browser und nie in der Datenbank.
"""
from __future__ import annotations

import email
import email.policy
import hashlib
import html as htmlmod
import imaplib
import mimetypes
import os
import re
import time
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any

from . import db
from .konfig import UPLOADS

HOST = os.environ.get("VVEC_MAIL_IMAP", "").strip()
PORT = int(os.environ.get("VVEC_MAIL_IMAP_PORT", "993"))
KONTO = os.environ.get("VVEC_MAIL_KONTO", "").strip()
PASSWORT = os.environ.get("VVEC_MAIL_PASSWORT", "")
ORDNER = os.environ.get("VVEC_MAIL_ORDNER", "INBOX").strip() or "INBOX"
ERLAUBT = {a.strip().lower() for a in os.environ.get("VVEC_MAIL_ERLAUBT", "").split(",") if a.strip()}
TAKT_SEK = int(os.environ.get("VVEC_MAIL_TAKT", "120"))
MAX_JE_LAUF = 10
MAX_ANHANG = 25 * 1024 * 1024

ZUSTAND: dict[str, Any] = {"letzter_abruf": None, "letzter_fehler": None, "neu_gesamt": 0, "naechster": 0.0}
_FAIL = re.compile(r"\b(spf|dkim|dmarc)=(fail|softfail|permerror)\b", re.I)


def eingerichtet() -> bool:
    return bool(HOST and KONTO and PASSWORT)


def stand() -> dict[str, Any]:
    return {"eingerichtet": eingerichtet(), "adresse": KONTO or None, "server": HOST or None,
            "erlaubt": sorted(ERLAUBT), "letzter_abruf": ZUSTAND["letzter_abruf"],
            "letzter_fehler": ZUSTAND["letzter_fehler"], "neu_gesamt": ZUSTAND["neu_gesamt"],
            "abgewiesen": (db.einstellung("mail_abgewiesen", []) or [])[-10:]}


def _text_aus(msg: email.message.EmailMessage) -> str:
    teil = msg.get_body(preferencelist=("plain", "html"))
    if teil is None:
        return ""
    try:
        t = teil.get_content()
    except (LookupError, ValueError):
        t = (teil.get_payload(decode=True) or b"").decode("utf-8", "replace")
    if teil.get_content_type() == "text/html":
        t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
        t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", t)
        t = htmlmod.unescape(re.sub(r"(?s)<[^>]+>", " ", t))
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _anhaenge(msg: email.message.EmailMessage) -> list[dict[str, Any]]:
    """Anhaenge landen in derselben Ablage wie hochgeladene Dateien, mit gelesenem Text."""
    from .anhang import _auswerten
    out = []
    for teil in msg.iter_attachments():
        name = Path(teil.get_filename() or "anhang").name[:120]
        roh = teil.get_payload(decode=True) or b""
        if not roh or len(roh) > MAX_ANHANG:
            out.append({"name": name, "text": "", "hinweis": "zu groß oder leer, nicht übernommen"})
            continue
        did = db.neue_id("d")
        ziel = UPLOADS / f"{did}_{name}"
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(roh)
        text, hinweis = "", ""
        try:
            text = ((_auswerten(name, roh) or {}).get("text") or "")[:120000]
        except Exception as e:  # noqa: BLE001 -- ein unlesbarer Anhang darf die Mail nicht verwerfen
            hinweis = str(getattr(e, "detail", e))[:200]
        db.einfuegen("dateien", {"id": did, "name": name, "typ": teil.get_content_type() or mimetypes.guess_type(name)[0] or "",
                                 "groesse": len(roh), "pfad": str(ziel), "text": text, "projekt_id": None,
                                 "erstellt": time.time()})
        out.append({"id": did, "name": name, "text": text, "hinweis": hinweis})
    return out


def _abweisen(von: str, betreff: str, grund: str) -> None:
    liste = db.einstellung("mail_abgewiesen", []) or []
    liste.append({"zeit": time.time(), "von": von, "betreff": betreff[:120], "grund": grund})
    db.einstellung_setzen("mail_abgewiesen", liste[-30:])
    print(f"[postfach] abgewiesen: {von} -- {grund}", flush=True)


def verarbeiten(roh: bytes) -> str | None:
    """Eine Mail -> Notiz + Vorgang. Gibt die Vorgangs-Kennung zurueck, oder None,
    wenn sie abgewiesen oder schon bekannt war. Getrennt vom Abruf, damit sie sich
    ohne Postfach pruefen laesst."""
    from . import stab
    msg = email.message_from_bytes(roh, policy=email.policy.default)
    mid = str(msg.get("Message-ID") or "").strip() or "ohne-id-" + hashlib.sha1(roh).hexdigest()
    if db.wert("SELECT 1 FROM notizen WHERE mail_id=?", (mid,)):
        return None
    absender = [a.lower() for _, a in getaddresses([str(msg.get("From") or "")]) if a]
    von = absender[0] if absender else ""
    betreff = str(msg.get("Subject") or "").strip() or "(ohne Betreff)"
    if not ERLAUBT:
        _abweisen(von, betreff, "Keine erlaubten Absender eingetragen (VVEC_MAIL_ERLAUBT).")
        return None
    if von not in ERLAUBT:
        _abweisen(von, betreff, "Absender steht nicht auf der Liste.")
        return None
    pruef = " ".join(str(h) for h in (msg.get_all("Authentication-Results") or []))
    if _FAIL.search(pruef):
        _abweisen(von, betreff, "Absender nicht bestätigt (" + _FAIL.search(pruef).group(0) + ").")
        return None

    text = _text_aus(msg)
    anh = _anhaenge(msg)
    voll = f"E-Mail an das Cockpit\nBetreff: {betreff}\n\n{text}"
    for a in anh:
        voll += f"\n\n[Angehängt: {a['name']}]" + (f"\n{a['text'][:20000]}" if a.get("text") else f" -- {a.get('hinweis') or 'Inhalt nicht lesbar'}")
    try:
        datum = parsedate_to_datetime(str(msg.get("Date"))).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        datum = time.strftime("%Y-%m-%d")
    nid = db.neue_id("m")
    db.einfuegen("notizen", {"id": nid, "titel": betreff[:120], "datum": datum, "text": voll, "kurz": "",
                             "quelle": "mail", "projekt_id": None, "mail_id": mid, "erstellt": time.time()})
    # Bewusst UNABHAENGIG vom Schalter "Neue Plaud-Notizen bearbeiten": eine Mail
    # ans Cockpit ist ein ausdruecklicher Auftrag, wie Capture.
    v = stab.vorgang_anlegen(db.holen("notizen", nid) or {"id": nid, "text": voll}, "mail", titel=betreff[:120])
    ZUSTAND["neu_gesamt"] += 1
    return v["id"]


def abrufen() -> int:
    """Ungelesene Mails holen (laeuft in einem Thread -- imaplib blockiert).
    Gelesen markiert wird erst NACH dem Verarbeiten: faellt der Dienst dazwischen
    aus, kommt die Mail beim naechsten Mal wieder; doppelt angelegt wird sie
    trotzdem nicht (Message-ID)."""
    if not eingerichtet():
        return 0
    neu = 0
    try:
        with imaplib.IMAP4_SSL(HOST, PORT, timeout=30) as m:
            m.login(KONTO, PASSWORT)
            m.select(ORDNER)
            typ, daten = m.search(None, "UNSEEN")
            for num in (daten[0].split() if typ == "OK" and daten and daten[0] else [])[:MAX_JE_LAUF]:
                typ, teile = m.fetch(num, "(BODY.PEEK[])")
                roh = next((t[1] for t in teile or [] if isinstance(t, tuple)), None)
                if not roh:
                    continue
                if verarbeiten(roh):
                    neu += 1
                m.store(num, "+FLAGS", "\\Seen")
        ZUSTAND["letzter_fehler"] = None
    except (imaplib.IMAP4.error, OSError) as e:
        ZUSTAND["letzter_fehler"] = f"{e.__class__.__name__}: {str(e)[:200]}"
        print(f"[postfach] Abruf gescheitert: {ZUSTAND['letzter_fehler']}", flush=True)
    ZUSTAND["letzter_abruf"] = time.time()
    return neu


def faellig() -> bool:
    if not eingerichtet() or time.time() < ZUSTAND["naechster"]:
        return False
    ZUSTAND["naechster"] = time.time() + TAKT_SEK
    return True
