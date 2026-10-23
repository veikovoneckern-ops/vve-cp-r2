"""
MAIL -- ein Postausgang mit Entwuerfen, Adressbuch und Formulierungshilfe (22.10.2026).

Veiko: "das Cockpit soll auch E-Mails an neue Adressen schicken koennen, z. B. Ergebnisse,
Aufgaben, Notizen. Hierbei moechte ich das auch mit Talk ausfuehren koennen, und es sollen
gleich gute Vorschlaege zur Formulierung gemacht werden. Ich brauche dazu eine Art E-Mail-
Client im Cockpit mit sehr guten Funktionalitaeten."

Versendet wird ueber info@veikovoneckern.org bei one.com. Bis zum 23.10.2026 lief das ueber den
Postausgang des ALTEN Backends (/api/mail/senden), weil nur dort die Zugangsdaten lagen. Seit Veiko
das alte Cockpit loeschen will, schickt diese Fassung SELBST per SMTP (_smtp_senden, dieselbe
Verbindungslogik wie dort: Port 465 = TLS ab der ersten Sekunde, sonst STARTTLS), sobald die fuenf
VVEC_SMTP_*-Zeilen in ~/.config/vve-cp-r2.env stehen (cloud.einrichten_befehl, einmal mit Passwort).
Bis dahin bleibt der alte Weg -- der Umzug soll keine Mail verlieren.

Drei Riegel, weil eine Mail nach aussen nicht zurueckzuholen ist:
  1. Gesendet wird NUR auf Veikos ausdrueckliches Senden (Knopf oder Ja in Talk). Der Stab
     kann Entwuerfe anlegen, nie abschicken.
  2. Adressen werden vor dem Senden geprueft (Form, keine Zeilenumbrueche -- dieselbe Pruefung
     wie im alten Backend gegen eine eingeschleuste Kopfzeile).
  3. Jede gesendete Mail bleibt mit Empfaengern, Text und Anhaengen unter "Gesendet" stehen.

Anhaenge kommen aus dem Cockpit (Ergebnis als Word/PowerPoint/PDF-faehiges Dokument, Unterlage
als Originaldatei) oder werden als Unterlage hochgeladen -- es gibt keinen zweiten Dateispeicher.
"""
from __future__ import annotations

import base64
import html as htmlmod
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

import httpx

from . import db, llm, stab
from .konfig import env_wert

ADRESSE_RE = re.compile(r"^[^\s@,;<>\"]+@[^\s@,;<>\"]+\.[^\s@,;<>\"]{2,}$")
MAX_ANHANG = 20 * 1024 * 1024        # wie im alten Backend: one.com deckelt die ganze Nachricht
FORMATE = {"docx": "Word", "pptx": "PowerPoint", "md": "Text (Markdown)", "html": "Webseite"}


# ---------------------------------------------------------------- Adressen und Kontakte
def adressen(wert: Any) -> list[str]:
    """'Hanna <h@x.de>, b@y.de; c@z.de' -> ['h@x.de', 'b@y.de', 'c@z.de']. Namen ohne @ werden im
    Adressbuch gesucht; was dort nicht steht, bleibt als Fehler sichtbar (pruefen)."""
    teile = wert if isinstance(wert, list) else re.split(r"[,;\n]+", str(wert or ""))
    raus = []
    for t in teile:
        t = str(t).strip()
        if not t:
            continue
        m = re.search(r"<([^>]+)>", t)
        t = gesprochen_zu_adresse((m.group(1) if m else t).strip())
        if "@" not in t:
            k = kontakt_finden(t)
            t = k["email"] if k else t
        if t.lower() not in [r.lower() for r in raus]:
            raus.append(t)
    return raus


# Gesprochene Adressen (22.10.2026): Whisper schreibt "von.eckern.web.de" (das "at" verschluckt), "von eckern at
# web punkt de" oder "von.äckern". Haeufige Anbieter erkennt das Cockpit am Ende und setzt das @ selbst.
ANBIETER = r"(web\.de|gmx\.(?:de|net|at|ch)|gmail\.com|googlemail\.com|outlook\.(?:de|com)|hotmail\.(?:de|com)|live\.(?:de|com)|t-online\.de|" \
           r"icloud\.com|me\.com|yahoo\.(?:de|com)|freenet\.de|posteo\.de|mailbox\.org|aol\.com|krones\.com|veikovoneckern\.org)"


def gesprochen_zu_adresse(t: str) -> str:
    s = t.strip().strip(".,;:!?„“\"'").lower()
    s = re.sub(r"\s+(at|ät|@)\s+", "@", s)
    s = re.sub(r"\s+(punkt|dot)\s+", ".", s)
    s = re.sub(r"\s*@\s*", "@", s)
    if "@" not in s:
        m = re.match(r"^([\w.+-]+?)[.\s]+" + ANBIETER + r"$", s)
        if m:
            s = f"{m.group(1)}@{m.group(2)}"
    if "@" in s:
        s = re.sub(r"\s+", "", s)
        return s
    return t.strip()


def adresse_im_text(text: str) -> str | None:
    """Die Adresse oder der Kontakt in einem gesprochenen Satz ("schreib eine Mail an von.eckern.web.de")."""
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
    if m:
        return m.group(0)
    m = re.search(r"\ban\s+([\w.+-]+(?:\s+(?:at|ät|punkt)\s+[\w.-]+)*(?:[.\s]+" + ANBIETER + r")?)", text, re.I)
    if m:
        a = gesprochen_zu_adresse(m.group(1))
        if ADRESSE_RE.match(a):
            return a
        k = kontakt_finden(m.group(1).split()[0])
        if k:
            return k["email"]
    return None


def pruefen(liste: list[str]) -> list[str]:
    return [a for a in liste if not ADRESSE_RE.match(a) or "\n" in a or "\r" in a]


def kontakte(q: str = "", grenze: int = 50) -> list[dict[str, Any]]:
    if q:
        m = f"%{q.lower()}%"
        return db.alle("SELECT * FROM kontakte WHERE lower(name) LIKE ? OR lower(email) LIKE ? ORDER BY anzahl DESC, zuletzt DESC LIMIT ?",
                       (m, m, grenze))
    return db.alle("SELECT * FROM kontakte ORDER BY zuletzt DESC, name LIMIT ?", (grenze,))


def kontakt_finden(name: str) -> dict[str, Any] | None:
    """Ein Name aus Talk ("schick es an Hanna") -> genau ein Kontakt, sonst None."""
    n = name.strip().lower()
    if not n:
        return None
    k = db.eine("SELECT * FROM kontakte WHERE lower(name)=? OR lower(email)=?", (n, n))
    if k:
        return k
    treffer = db.alle("SELECT * FROM kontakte WHERE lower(name) LIKE ? ORDER BY anzahl DESC", (f"%{n}%",))
    return treffer[0] if len(treffer) == 1 else None


def kontakt_speichern(email: str, name: str = "", notiz: str | None = None, benutzt: bool = False) -> dict[str, Any]:
    email = email.strip()
    if not ADRESSE_RE.match(email):
        raise ValueError(f"„{email}“ ist keine gültige Adresse.")
    k = db.eine("SELECT * FROM kontakte WHERE lower(email)=?", (email.lower(),))
    if k:
        werte: dict[str, Any] = {}
        if name and name != k.get("name"):
            werte["name"] = name[:80]
        if notiz is not None:
            werte["notiz"] = notiz[:500]
        if benutzt:
            werte.update(anzahl=(k.get("anzahl") or 0) + 1, zuletzt=time.time())
        if werte:
            db.aendern("kontakte", k["id"], werte)
        return db.holen("kontakte", k["id"]) or k
    return db.anlegen("kontakte", {"id": db.neue_id("k"), "name": (name or email.split("@")[0])[:80], "email": email,
                                   "notiz": (notiz or "")[:500], "anzahl": 1 if benutzt else 0,
                                   "zuletzt": time.time() if benutzt else None, "erstellt": time.time()})


# ---------------------------------------------------------------- Entwuerfe
def _leer() -> dict[str, Any]:
    return {"anhaenge": [], "bezug": None, "verlauf": []}


def holen(mid: str) -> dict[str, Any] | None:
    m = db.holen("mails", mid)
    if m:
        m["daten"] = {**_leer(), **(m.get("daten") or {})}
    return m


def liste() -> dict[str, list[dict[str, Any]]]:
    def kurz(m: dict[str, Any]) -> dict[str, Any]:
        d = {**_leer(), **(m.get("daten") or {})}
        return {k: m.get(k) for k in ("id", "stand", "an", "betreff", "erstellt", "geaendert", "gesendet", "fehler")} | {
            "auszug": re.sub(r"\s+", " ", _html_zu_text(m.get("html") or ""))[:140], "anhaenge": len(d["anhaenge"])}
    return {"entwuerfe": [kurz(m) for m in db.alle("SELECT * FROM mails WHERE stand IN ('entwurf','fehler') ORDER BY geaendert DESC LIMIT 100")],
            "gesendet": [kurz(m) for m in db.alle("SELECT * FROM mails WHERE stand='gesendet' ORDER BY gesendet DESC LIMIT 200")]}


def anlegen(werte: dict[str, Any] | None = None, wer: str = "du") -> dict[str, Any]:
    w = werte or {}
    daten = _leer()
    html = str(w.get("html") or "")
    betreff = str(w.get("betreff") or "")
    bezug = w.get("bezug")
    if bezug and bezug.get("art") in BEZUG:
        b = bezug_lesen(bezug)
        if b:
            daten["bezug"] = {"art": bezug["art"], "id": bezug["id"], "titel": b["titel"]}
            betreff = betreff or b["titel"][:150]
            if b.get("anhang"):
                daten["anhaenge"].append(b["anhang"])
            if not html and b.get("text_einfuegen"):
                html = text_zu_html(b["text_einfuegen"])
    for a in w.get("anhaenge") or []:
        a = anhang_pruefen(a)
        if a and a not in daten["anhaenge"]:
            daten["anhaenge"].append(a)
    mid = db.neue_id("m")
    db.anlegen("mails", {"id": mid, "stand": "entwurf", "an": ", ".join(adressen(w.get("an"))), "cc": ", ".join(adressen(w.get("cc"))),
                         "bcc": ", ".join(adressen(w.get("bcc"))), "betreff": betreff[:180], "html": html, "daten": daten,
                         "fehler": None, "erstellt": time.time(), "geaendert": time.time(), "gesendet": None}, wer=wer)
    return holen(mid) or {}


def aendern(mid: str, werte: dict[str, Any]) -> dict[str, Any]:
    m = holen(mid)
    if not m:
        raise ValueError("Diesen Entwurf gibt es nicht.")
    if m["stand"] == "gesendet":
        raise ValueError("Eine gesendete Mail lässt sich nicht mehr ändern -- „Erneut verwenden“ legt einen neuen Entwurf an.")
    neu: dict[str, Any] = {}
    for k in ("an", "cc", "bcc"):
        if k in werte:
            neu[k] = str(werte[k] or "")[:2000]
    if "betreff" in werte:
        neu["betreff"] = str(werte["betreff"] or "")[:180]
    if "html" in werte:
        neu["html"] = str(werte["html"] or "")[:400000]
    if "anhaenge" in werte:
        d = m["daten"]
        d["anhaenge"] = [a for a in (anhang_pruefen(x) for x in werte["anhaenge"] or []) if a]
        neu["daten"] = d
    if neu:
        neu["geaendert"] = time.time()
        if m["stand"] == "fehler":
            neu.update(stand="entwurf", fehler=None)
        db.aendern("mails", mid, neu)
    return holen(mid) or {}


def loeschen(mid: str) -> None:
    m = holen(mid)
    if m and m["stand"] != "gesendet":
        db.loeschen("mails", mid)


def wiederverwenden(mid: str) -> dict[str, Any]:
    m = holen(mid)
    if not m:
        raise ValueError("Diese Mail gibt es nicht.")
    return anlegen({"an": m["an"], "cc": m["cc"], "betreff": m["betreff"], "html": m["html"], "anhaenge": m["daten"]["anhaenge"]})


# ---------------------------------------------------------------- Bezug und Anhaenge
BEZUG = ("ergebnis", "aufgabe", "notiz", "datei", "projekt")


def bezug_lesen(b: dict[str, Any]) -> dict[str, Any] | None:
    """Was eine Mail ueber ein Ding aus dem Cockpit braucht: Titel, Inhalt fuer den Entwurf und
    gegebenenfalls den passenden Anhang. Ergebnisse gehen als Word mit, Unterlagen als Original;
    Aufgaben und Notizen sind kurz und stehen im Text selbst."""
    art, bid = b.get("art"), str(b.get("id") or "")
    if art == "ergebnis":
        e = db.holen("ergebnisse", bid)
        if not e:
            return None
        fmt = "pptx" if e.get("form") == "praesentation" else "docx"
        return {"titel": e["titel"] or "Ergebnis", "inhalt": e.get("inhalt") or "",
                "anhang": {"art": "ergebnis", "id": bid, "format": fmt, "name": f"{e['titel'][:80]}.{fmt}"}}
    if art == "datei":
        d = db.holen("dateien", bid)
        if not d:
            return None
        return {"titel": d["name"], "inhalt": d.get("text") or "", "anhang": {"art": "datei", "id": bid, "name": d["name"]}}
    if art == "aufgabe":
        a = db.holen("aufgaben", bid)
        if not a:
            return None
        p = db.holen("projekte", a.get("projekt_id") or "") if a.get("projekt_id") else None
        zeilen = [f"Aufgabe: {a['titel']}"] + ([f"Projekt: {p['name']}"] if p else []) + \
                 ([f"Fällig: {a['faellig']}"] if a.get("faellig") else []) + ([a["notiz"]] if (a.get("notiz") or "").strip() else [])
        return {"titel": a["titel"], "inhalt": "\n".join(zeilen), "text_einfuegen": "\n".join(zeilen)}
    if art == "notiz":
        n = db.holen("notizen", bid)
        if not n:
            return None
        t = n.get("text") or n.get("kurz") or ""
        return {"titel": n.get("titel") or "Notiz", "inhalt": t, "text_einfuegen": t[:20000]}
    if art == "projekt":
        p = db.holen("projekte", bid)
        if not p:
            return None
        auf = db.alle("SELECT titel, status, faellig FROM aufgaben WHERE projekt_id=? AND archiviert=0 ORDER BY status, faellig LIMIT 30", (bid,))
        return {"titel": p["name"], "inhalt": f"Projekt {p['name']}" + (f" -- Ziel: {p['ziel']}" if p.get("ziel") else "") + "\nAufgaben:\n"
                + "\n".join(f"- {a['titel']} ({a['status']}{', fällig ' + a['faellig'] if a.get('faellig') else ''})" for a in auf)}
    return None


def anhang_pruefen(a: Any) -> dict[str, Any] | None:
    if not isinstance(a, dict):
        return None
    if a.get("art") == "ergebnis":
        e = db.holen("ergebnisse", str(a.get("id") or ""))
        if not e:
            return None
        fmt = a.get("format") if a.get("format") in FORMATE else "docx"
        return {"art": "ergebnis", "id": e["id"], "format": fmt, "name": f"{(e['titel'] or 'Ergebnis')[:80]}.{fmt}"}
    if a.get("art") == "datei":
        d = db.holen("dateien", str(a.get("id") or ""))
        return {"art": "datei", "id": d["id"], "name": d["name"]} if d else None
    return None


def _anhang_bytes(a: dict[str, Any]) -> tuple[bytes, str, str]:
    from . import dokumente
    if a["art"] == "ergebnis":
        e = db.holen("ergebnisse", a["id"])
        if not e:
            raise ValueError("Ein angehängtes Ergebnis gibt es nicht mehr.")
        fmt, text = a.get("format") or "docx", e.get("inhalt") or ""
        if fmt == "pptx":
            roh, typ = dokumente.zu_pptx(e["titel"], text, e["id"], e.get("stil")), "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        elif fmt == "html":
            roh, typ = dokumente.zu_html(e["titel"], text, e["id"]).encode("utf-8"), "text/html"
        elif fmt == "md":
            roh, typ = text.encode("utf-8"), "text/markdown"
        else:
            roh, typ = dokumente.zu_docx(e["titel"], text, e["id"]), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        return roh, typ, dokumente.dateiname(e["titel"], fmt)
    d = db.holen("dateien", a["id"])
    if not d or not d.get("pfad") or not Path(d["pfad"]).exists():
        raise ValueError(f"Die Unterlage „{a.get('name')}“ liegt nicht mehr auf dem Server.")
    return Path(d["pfad"]).read_bytes(), d.get("typ") or mimetypes.guess_type(d["name"])[0] or "application/octet-stream", d["name"]


# ---------------------------------------------------------------- Text
def _html_zu_text(h: str) -> str:
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", h or "")
    h = re.sub(r"(?i)<li[^>]*>", "• ", h)
    return htmlmod.unescape(re.sub(r"<[^>]+>", "", h)).strip()


def text_zu_html(t: str) -> str:
    """Absaetze und Aufzaehlungen aus einem Modelltext -- mehr Formatierung braucht eine Mail nicht."""
    bloecke = re.split(r"\n\s*\n", (t or "").strip())
    raus = []
    for b in bloecke:
        zeilen = [z for z in b.split("\n") if z.strip()]
        if zeilen and all(re.match(r"^\s*([-*•]|\d+[.)])\s+", z) for z in zeilen):
            tag = "ol" if re.match(r"^\s*\d", zeilen[0]) else "ul"
            raus.append(f"<{tag}>" + "".join(f"<li>{_inline(re.sub(r'^\s*([-*•]|\d+[.)])\s+', '', z))}</li>" for z in zeilen) + f"</{tag}>")
        elif zeilen:
            raus.append("<p>" + "<br>".join(_inline(z) for z in zeilen) + "</p>")
    return "".join(raus)


def _inline(z: str) -> str:
    z = htmlmod.escape(z.strip())
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", z)


# ---------------------------------------------------------------- Formulieren
STIL = ("Du schreibst E-Mails für Veiko von Eckern (Head of Corporate HR Transformation). Deutsch, sofern nicht anders verlangt. "
        "Klar, freundlich, auf den Punkt, ohne Floskeln wie „ich hoffe, diese Mail erreicht Sie gut“. Anrede passend zum Empfänger "
        "(du/Sie wie in der Vorlage oder in Veikos Anweisung; im Zweifel Sie). Gruß: „Viele Grüße\nVeiko von Eckern“. "
        "Erfinde keine Fakten, Termine oder Zusagen, die nicht in den Unterlagen oder Veikos Anweisung stehen. "
        "Ein Anhang wird erwähnt, nicht abgeschrieben. Titel von Werken, Produkten und Firmen bleiben wörtlich, "
        "auch in einer Übersetzung (gemessen: „KI & Menschen“ wurde sonst zu „AI & Humans“).")

AUFTRAEGE = {
    "entwurf": "Schreibe die Mail.",
    "kuerzer": "Mach die Mail deutlich kürzer, ohne Inhalt zu verlieren.",
    "freundlicher": "Formuliere die Mail wärmer und persönlicher, gleicher Inhalt.",
    "foermlicher": "Formuliere die Mail förmlicher und geschäftlicher, gleicher Inhalt.",
    "klarer": "Mach die Mail klarer: Anliegen zuerst, was der Empfänger tun soll, deutlich benennen.",
    "englisch": "Übersetze die Mail ins Englische, natürlich und geschäftlich.",
    "korrektur": "Korrigiere nur Rechtschreibung, Grammatik und Zeichensetzung. Ändere sonst nichts.",
}


async def formulieren(mid: str, art: str, anweisung: str = "") -> dict[str, Any]:
    """Ein Vorschlag fuer Betreff und Text -- ersetzt nichts, das Uebernehmen entscheidet Veiko."""
    m = holen(mid)
    if not m:
        raise ValueError("Diesen Entwurf gibt es nicht.")
    if art not in AUFTRAEGE:
        art = "entwurf"
    unterlagen = []
    if m["daten"].get("bezug"):
        b = bezug_lesen(m["daten"]["bezug"])
        if b:
            # Gemessen am 22.10.: ohne diesen Satz schrieb das Modell "ich habe mir DEIN Feedback angesehen" --
            # es hielt das angehaengte Ergebnis fuer etwas, das der Empfaenger geschrieben hatte.
            unterlagen.append(f"WAS VEIKO DEM EMPFÄNGER SCHICKT (stammt von Veiko bzw. seinem Team und betrifft Veikos eigene Arbeit -- NICHT vom Empfänger und nicht dessen Werk"
                              f"{'; geht als Anhang mit' if m['daten']['anhaenge'] else ''}): „{b['titel']}“\n{(b.get('inhalt') or '')[:9000]}")
    for a in m["daten"]["anhaenge"]:
        if a.get("art") == "ergebnis" and (m["daten"].get("bezug") or {}).get("id") != a["id"]:
            e = db.holen("ergebnisse", a["id"]) or {}
            unterlagen.append(f"ANHANG „{e.get('titel')}“ (Auszug):\n{(e.get('inhalt') or '')[:4000]}")
        elif a.get("art") == "datei":
            unterlagen.append(f"ANHANG „{a['name']}“")
    empf = ", ".join(f"{k['name']} <{k['email']}>" + (f" ({k['notiz']})" if k.get("notiz") else "")
                     for k in (db.eine("SELECT * FROM kontakte WHERE lower(email)=?", (x.lower(),)) for x in adressen(m["an"])) if k)
    jetzt = _html_zu_text(m.get("html") or "")
    nutzer = (f"EMPFÄNGER: {empf or m['an'] or 'noch offen'}\nBETREFF BISHER: {m.get('betreff') or '-'}\n\n"
              + ("\n\n".join(unterlagen) + "\n\n" if unterlagen else "")
              + (f"BISHERIGER TEXT:\n{jetzt}\n\n" if jetzt else "")
              + (f"VEIKOS ANWEISUNG: {anweisung}\n\n" if anweisung else "")
              + f"AUFGABE: {AUFTRAEGE[art]}\nAntworte NUR als JSON: {{\"betreff\": \"…\", \"text\": \"Mailtext mit Absätzen, Aufzählungen mit - \"}}")
    modell = await llm.modell_waehlen(llm.vorgabe("arbeit"), llm.vorgabe("talk"))
    if not modell:
        raise ValueError("Kein lokales Modell installiert.")
    with llm.taetig("Mail formulieren"):
        roh = await llm.chat(modell, STIL, [{"role": "user", "content": nutzer}], json_format=True, temperatur=0.4, denken=False, num_ctx=24576)
    d = llm.json_aus(roh) or {}
    text = str(d.get("text") or "").strip()
    if not text:
        raise ValueError("Das Modell hat keinen Vorschlag geliefert. Bitte noch einmal.")
    return {"betreff": str(d.get("betreff") or m.get("betreff") or "")[:180], "text": text, "html": text_zu_html(text), "art": art, "modell": modell}


# ---------------------------------------------------------------- Senden
async def senden(mid: str) -> dict[str, Any]:
    m = holen(mid)
    if not m:
        raise ValueError("Diesen Entwurf gibt es nicht.")
    if m["stand"] == "gesendet":
        raise ValueError("Diese Mail ist schon gesendet.")
    an, cc, bcc = adressen(m["an"]), adressen(m["cc"]), adressen(m["bcc"])
    if not an:
        raise ValueError("Es fehlt ein Empfänger.")
    falsch = pruefen(an + cc + bcc)
    if falsch:
        raise ValueError("Diese Adressen sind nicht gültig oder stehen nicht im Adressbuch: " + ", ".join(falsch))
    html = m.get("html") or ""
    if not _html_zu_text(html) and not m["daten"]["anhaenge"]:
        raise ValueError("Die Mail ist leer.")
    # Nur noch direkt per SMTP; der Umweg ueber das alte Backend ist seit dem 23.10.2026 weg.
    if not smtp_stand()["ok"]:
        raise ValueError("Der Postausgang ist nicht eingerichtet: die VVEC_SMTP_*-Zeilen fehlen in ~/.config/vve-cp-r2.env "
                         "(der Befehl dafür steht unter Recommendations).")
    anh, gesamt = [], 0
    for a in m["daten"]["anhaenge"]:
        roh, typ, name = _anhang_bytes(a)
        gesamt += len(roh)
        if gesamt > MAX_ANHANG:
            raise ValueError(f"Die Anhänge sind zusammen größer als {MAX_ANHANG // 1024 // 1024} MB.")
        anh.append({"name": name, "typ": typ, "daten": base64.b64encode(roh).decode("ascii")})
    koerper = ("<div style=\"font-family:Calibri,Arial,sans-serif;font-size:11pt;line-height:1.45\">" + html + "</div>")
    body = {"an": ", ".join(an), "cc": ", ".join(cc), "bcc": ", ".join(bcc), "betreff": m.get("betreff") or "(ohne Betreff)",
            "html": koerper, "text": _html_zu_text(html), "anhaenge": anh}
    try:
        import asyncio
        await asyncio.to_thread(_smtp_senden, body)
    except (httpx.HTTPError, ValueError, OSError) as f:
        grund = (str(f) if isinstance(f, ValueError) else
                 f"Mailserver: {f}"[:300] if isinstance(f, OSError) and str(f) else f"Postausgang nicht erreichbar ({f.__class__.__name__})")
        db.aendern("mails", mid, {"stand": "fehler", "fehler": grund[:500], "geaendert": time.time()})
        raise ValueError(grund) from f
    db.aendern("mails", mid, {"stand": "gesendet", "fehler": None, "gesendet": time.time(), "geaendert": time.time(),
                              "an": ", ".join(an), "cc": ", ".join(cc), "bcc": ", ".join(bcc)})
    for x in an + cc + bcc:
        try:
            kontakt_speichern(x, benutzt=True)
        except ValueError:
            pass
    b = m["daten"].get("bezug")
    if b and b.get("art") == "aufgabe":
        # Am Ding vermerken, dass es verschickt wurde -- sonst fragt man sich spaeter, ob.
        a = db.holen("aufgaben", b["id"])
        if a:
            db.aendern("aufgaben", a["id"], {"notiz": ((a.get("notiz") or "") + f"\n\nPer Mail an {', '.join(an)} geschickt "
                                                                                  f"({time.strftime('%d.%m.%Y %H:%M')}).").strip()})
    return {"ok": True, "an": an, "betreff": m.get("betreff")}


def smtp_stand() -> dict[str, Any]:
    """Die eigenen SMTP-Zugangsdaten (seit 23.10.2026) -- dieselben fuenf Namen wie im alten Backend."""
    host, user, pw = env_wert("VVEC_SMTP_HOST"), env_wert("VVEC_SMTP_USER"), env_wert("VVEC_SMTP_PASS")
    von = env_wert("VVEC_SMTP_FROM") or user
    try:
        port = int(env_wert("VVEC_SMTP_PORT") or "587")
    except ValueError:
        port = 587
    ok = bool(host and user and pw and von)
    return {"ok": ok, "host": host, "port": port, "user": user, "absender": von,
            "fehlt": [] if ok else [n for n, da in (("VVEC_SMTP_HOST", host), ("VVEC_SMTP_USER", user),
                                                     ("VVEC_SMTP_PASS", pw), ("VVEC_SMTP_FROM", von)) if not da]}


def _smtp_senden(body: dict[str, Any]) -> None:
    """Direkt per SMTP (blockierend, im Thread). Port 465 spricht TLS von der ersten Sekunde an
    (one.com), alles andere startet offen und hebt per STARTTLS an -- das ist Protokoll, kein
    Geschmack: ein SMTP_SSL-Server versteht ein Klartext-EHLO gar nicht erst.
    Nur fuer den Test (VVEC_SMTP_TEST=1, Host 127.0.0.1): unverschluesselt und ohne Anmeldung,
    an einen nachgestellten Mailserver -- damit kein Test je eine echte Mail verschickt."""
    import smtplib
    import ssl
    from email.message import EmailMessage
    from email.utils import make_msgid
    st = smtp_stand()
    msg = EmailMessage()
    msg["Subject"] = re.sub(r"[\r\n]+", " ", str(body.get("betreff") or ""))[:180]
    msg["From"] = st["absender"]
    msg["To"] = body["an"]
    if body.get("cc"):
        msg["Cc"] = body["cc"]
    msg["Message-Id"] = make_msgid(domain=st["absender"].split("@")[-1] if "@" in st["absender"] else None)
    msg.set_content(body.get("text") or " ")
    if body.get("html"):
        msg.add_alternative(body["html"], subtype="html")
    for a in body.get("anhaenge") or []:
        haupt, _, sub = (a.get("typ") or "application/octet-stream").partition("/")
        msg.add_attachment(base64.b64decode(a["daten"]), maintype=haupt, subtype=sub or "octet-stream", filename=a["name"])
    alle = [x.strip() for x in ",".join(body.get(k) or "" for k in ("an", "cc", "bcc")).split(",") if x.strip()]
    test = env_wert("VVEC_SMTP_TEST") == "1" and st["host"] in ("127.0.0.1", "localhost")
    if test:
        verbindung = smtplib.SMTP(st["host"], st["port"], timeout=25)
    elif st["port"] == 465:
        verbindung = smtplib.SMTP_SSL(st["host"], st["port"], context=ssl.create_default_context(), timeout=25)
    else:
        verbindung = smtplib.SMTP(st["host"], st["port"], timeout=25)
        verbindung.ehlo()
        verbindung.starttls(context=ssl.create_default_context())
        verbindung.ehlo()
    with verbindung as s:
        if not test:
            s.login(st["user"], env_wert("VVEC_SMTP_PASS"))
        s.send_message(msg, to_addrs=alle)


def absender() -> dict[str, Any]:
    """Wer als Absender erscheint -- aus den eigenen Zugangsdaten, sonst ehrlich 'nicht eingerichtet'."""
    st = smtp_stand()
    if st["ok"]:
        return {"ok": True, "absender": st["absender"], "fehlt": [], "weg": "direkt"}
    return {"ok": False, "absender": None, "fehlt": st.get("fehlt") or ["VVEC_SMTP_*-Zeilen in ~/.config/vve-cp-r2.env"]}


def stand_satz(mid: str | None = None) -> str:
    """Ob eine Mail raus ist -- aus der Datenbank, nie aus dem Gedaechtnis des Modells (22.10.2026)."""
    m = holen(mid) if mid and mid != "alle" else None
    if not m:
        r = db.eine("SELECT id FROM mails ORDER BY geaendert DESC LIMIT 1")
        m = holen(r["id"]) if r else None
    if not m:
        return "Es gibt noch keine Mail im Cockpit."
    an = m.get("an") or "noch niemanden"
    if m["stand"] == "gesendet":
        return f"Ja, gesendet am {time.strftime('%d.%m. um %H:%M', time.localtime(m['gesendet']))} an {an}."
    if m["stand"] == "fehler":
        return (f"Nein, verschickt ist sie nicht -- der letzte Versuch ist gescheitert: {m.get('fehler')}. "
                f"Der Entwurf an {an} liegt bereit; sag „schick sie ab“, dann versuche ich es noch einmal.")
    if not _html_zu_text(m.get("html") or "").strip():
        return f"Nein, verschickt ist sie noch nicht -- der Entwurf an {an} hat noch keinen Text. Sag mir, was drinstehen soll."
    return f"Nein, verschickt ist sie noch nicht: der Entwurf „{m.get('betreff') or '(ohne Betreff)'}“ an {an} wartet. Sag „schick sie ab“, dann geht sie raus."


def talk_text() -> str:
    """Fuer Talk: Adressbuch und offene Entwuerfe, knapp."""
    k = kontakte(grenze=25)
    e = db.alle("SELECT id, an, betreff FROM mails WHERE stand IN ('entwurf','fehler') ORDER BY geaendert DESC LIMIT 5")
    teile = []
    if k:
        teile.append("ADRESSBUCH (Name -> Adresse):\n" + "\n".join(f"- {x['name']}: {x['email']}" + (f" ({x['notiz']})" if x.get("notiz") else "") for x in k))
    if e:
        teile.append("MAIL-ENTWÜRFE:\n" + "\n".join(f"- {x['id']}: „{x['betreff'] or '(ohne Betreff)'}“ an {x['an'] or '?'}" for x in e))
    return "\n\n".join(teile)
