"""
SPRECHTEXT -- was Piper vorliest, so aufbereitet, wie ein Mensch es sagen wuerde.

Veiko (22.10.2026): "Die Sprachausgabe fuehlt sich sehr technisch an, ohne Pausen, und
vieles ist nicht rund, z. B. wenn Dateinamen vorgelesen werden oder Zahlen." Piper liest,
was dasteht: "1fUwT.jpg" Buchstabe fuer Buchstabe, "21.10.2026" als Zahlenkette, "$ 0.66"
englisch, Markdown-Sternchen und Listenziffern mit, und Grossbuchstaben-Ueberschriften
("OFFENE ENTSCHEIDUNGEN") als Abkuerzung. Und eine ganze Antwort ging als EIN Block hinaus --
Absaetze und Listenpunkte ohne Atempause.

Zwei Teile:
  sprechfassung(text) -> Text, den man so vorlesen kann (Zahlen, Daten, Einheiten,
                         Abkuerzungen, Dateinamen, Kennungen, Markdown)
  abschnitte(text)    -> [(Satzteil, Pause in Sekunden danach)] -- stimme.sprechen setzt
                         daraus EINE Tondatei mit echten Pausen zusammen.

Was hier steht, gilt fuer ALLES Vorlesen (Talk, Team-Chat, Board, Vorlesen-Knopf), weil es
in stimme.sprechen sitzt und nicht in einer einzelnen Oberflaeche.
"""
from __future__ import annotations

import re

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
_EINER = ["", "ein", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf", "zwölf", "dreizehn",
          "vierzehn", "fünfzehn", "sechzehn", "siebzehn", "achtzehn", "neunzehn"]
_ZEHNER = ["", "", "zwanzig", "dreißig", "vierzig", "fünfzig", "sechzig", "siebzig", "achtzig", "neunzig"]


def zahlwort(n: int) -> str:
    """0 bis 999 als Wort (fuer Ordinalzahlen in Daten; Piper spricht Kardinalzahlen selbst gut)."""
    if n == 0:
        return "null"
    if n < 20:
        return "eins" if n == 1 else _EINER[n]
    if n < 100:
        e, z = n % 10, n // 10
        return (_EINER[e] + "und" if e else "") + _ZEHNER[z]
    h, r = divmod(n, 100)
    return ("ein" if h == 1 else _EINER[h]) + "hundert" + (zahlwort(r) if r else "")


def ordinal(n: int, endung: str = "ten") -> str:
    """1 -> ersten, 3 -> dritten, 21 -> einundzwanzigsten (endung "te" fuer "der dritte")."""
    besondere = {1: "ers", 3: "drit", 7: "sieb", 8: "ach"}
    if n in besondere:
        return besondere[n] + endung
    w = zahlwort(n)
    return w + ("s" if n >= 20 else "") + endung


# Abkuerzungen, die man ausspricht -- laengere zuerst, damit "z. B." vor "B." greift.
ABKUERZUNGEN = [
    (r"\bz\.\s?B\.", "zum Beispiel"), (r"\bd\.\s?h\.", "das heißt"), (r"\bu\.\s?a\.", "unter anderem"),
    (r"\bu\.\s?U\.", "unter Umständen"), (r"\bi\.\s?d\.\s?R\.", "in der Regel"), (r"\bo\.\s?ä\.", "oder ähnliches"),
    (r"\bbzw\.", "beziehungsweise"), (r"\bca\.", "circa"), (r"\binkl\.", "inklusive"), (r"\bexkl\.", "exklusive"),
    (r"\bevtl\.", "eventuell"), (r"\bggf\.", "gegebenenfalls"), (r"\busw\.", "und so weiter"), (r"\betc\.", "und so weiter"),
    (r"\bvgl\.", "vergleiche"), (r"\bNr\.", "Nummer"), (r"\bStd\.", "Stunden"), (r"\bMin\.", "Minuten"), (r"\bSek\.", "Sekunden"),
    (r"\bMio\.", "Millionen"), (r"\bMrd\.", "Milliarden"), (r"\bTsd\.", "Tausend"), (r"\bvs\.", "gegen"), (r"\bggü\.", "gegenüber"),
    (r"\bS\.\s(?=\d)", "Seite "), (r"\bKap\.\s(?=\d)", "Kapitel "), (r"\bAbs\.\s(?=\d)", "Absatz "), (r"\bbzgl\.", "bezüglich"),
    (r"\bsog\.", "sogenannte"), (r"\bgem\.", "gemäß"), (r"\bmind\.", "mindestens"), (r"\bmax\.", "maximal"), (r"\bmin\.", "mindestens"),
]
EINHEITEN = [
    (r"(?<=\d)\s?Tok/s\b", " Token pro Sekunde"), (r"(?<=\d)\s?km/h\b", " Kilometer pro Stunde"), (r"(?<=\d)\s?MB/s\b", " Megabyte pro Sekunde"),
    (r"(?<=\d)\s?°C\b", " Grad"), (r"(?<=\d)\s?°", " Grad"), (r"(?<=\d)\s?%", " Prozent"), (r"(?<=\d)\s?GB\b", " Gigabyte"),
    (r"(?<=\d)\s?MB\b", " Megabyte"), (r"(?<=\d)\s?KB\b", " Kilobyte"), (r"(?<=\d)\s?TB\b", " Terabyte"), (r"(?<=\d)\s?kWh\b", " Kilowattstunden"),
    (r"(?<=\d)\s?W\b", " Watt"), (r"(?<=\d)\s?ms\b", " Millisekunden"), (r"(?<=\d)\s?km\b", " Kilometer"), (r"(?<=\d)\s?kg\b", " Kilo"),
    (r"(?<=\d)\s?h\b", " Stunden"), (r"(?<=\d)\s?s\b", " Sekunden"), (r"(?<=\d)\s?Min\b", " Minuten"),
]
# Kurze Abkuerzungen in Grossbuchstaben bleiben so (Piper buchstabiert sie richtig); laengere
# Woerter in Grossbuchstaben sind Ueberschriften und werden normal gesprochen.
BUCHSTABIEREN = {"KI", "HR", "IT", "PDF", "OTH", "BVE", "USA", "EU", "CPU", "GPU", "VVEORG", "API", "URL", "PMO", "DSGVO", "ERP", "SAP",
                 "CEO", "CFO", "CTO", "CHRO", "KPI", "KPIs", "FAQ", "PC", "TV", "VW", "BMW", "SPD", "CDU", "UBT"}
DATEI_ART = {"jpg": "Bild", "jpeg": "Bild", "png": "Bild", "gif": "Bild", "webp": "Bild", "svg": "Grafik", "pdf": "PDF",
             "doc": "Word-Datei", "docx": "Word-Datei", "xls": "Excel-Datei", "xlsx": "Excel-Datei", "csv": "Tabelle",
             "ppt": "Präsentation", "pptx": "Präsentation", "mp4": "Video", "mov": "Video", "mp3": "Tondatei", "wav": "Tondatei",
             "m4a": "Tondatei", "zip": "Archiv", "txt": "Textdatei", "md": "Textdatei", "html": "Webseite", "json": "Datei", "py": "Programmdatei",
             "js": "Programmdatei"}
_DATEI = re.compile(r"\b[\w.\-]+\.(" + "|".join(DATEI_ART) + r")\b", re.I)
_ZAHL_WORT = {2: "zwei", 3: "drei", 4: "vier", 5: "fünf", 6: "sechs", 7: "sieben", 8: "acht", 9: "neun", 10: "zehn"}


def _dateien(text: str) -> str:
    """'1fUwT.jpg, 6mrmi.jpg, adZKL.jpg' -> 'drei Bilder'; ein einzelner Name -> 'die PDF „Bericht“'."""
    def gruppe(m: re.Match[str]) -> str:
        namen = _DATEI.findall(m.group(0))
        arten = [DATEI_ART[e.lower()] for e in namen]
        if len(arten) > 1:
            n = len(arten)
            if len(set(arten)) == 1:
                a = arten[0]
                mehr = {"Bild": "Bilder", "Grafik": "Grafiken", "PDF": "PDFs", "Video": "Videos", "Tabelle": "Tabellen",
                        "Präsentation": "Präsentationen", "Webseite": "Webseiten", "Datei": "Dateien"}.get(a, a.replace("Datei", "Dateien") if a.endswith("Datei") else a + "s")
                return f"{_ZAHL_WORT.get(n, str(n))} {mehr}"
            return f"{_ZAHL_WORT.get(n, str(n))} Dateien"
        name = m.group(0)
        stamm = re.sub(r"\.[^.]+$", "", name)
        lesbar = re.sub(r"[_\-]+", " ", stamm).strip()
        # Kryptische Namen (Zufallskennungen, keine Woerter) nennt man nicht beim Namen.
        if not re.search(r"[a-zäöüß]{3,}", lesbar.lower()) or re.fullmatch(r"[A-Za-z0-9]{4,8}", stamm) and not re.search(r"[aeiouäöü]{1}[a-z]{2}", stamm):
            return {"Bild": "ein Bild", "Grafik": "eine Grafik", "Video": "ein Video", "Tabelle": "eine Tabelle", "Präsentation": "eine Präsentation",
                    "Webseite": "eine Webseite", "PDF": "ein PDF"}.get(arten[0], "eine Datei")
        return f"{arten[0]} „{lesbar}“" if arten[0] != "PDF" else f"das PDF „{lesbar}“"
    return re.sub(r"(?:\b[\w.\-]+\.(?:" + "|".join(DATEI_ART) + r")\b(?:\s*(?:,|und)\s*)?)+", lambda m: gruppe(m) + (" " if m.group(0).rstrip() != m.group(0) else ""), text, flags=re.I)


def _datum(text: str) -> str:
    def dm(m: re.Match[str], tag: str, monat: str, jahr: str | None) -> str:
        t, mo = int(tag), int(monat)
        if not (1 <= t <= 31 and 1 <= mo <= 12):
            return m.group(0)
        vor = text[max(0, m.start() - 6):m.start()].lower()
        endung = "ten" if re.search(r"\b(am|vom|bis|zum|ab|seit|dem)\s*$", vor) else "te"
        return f"{ordinal(t, endung)} {MONATE[mo - 1]}" + (f" {jahr}" if jahr else "")
    text = re.sub(r"\b(\d{4})-(\d{2})-(\d{2})\b", lambda m: dm(m, m.group(3), m.group(2), m.group(1)), text)
    text = re.sub(r"\b(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})\b", lambda m: dm(m, m.group(1), m.group(2), m.group(3)), text)
    text = re.sub(r"\b(\d{1,2})\.\s?(\d{1,2})\.(?!\d)", lambda m: dm(m, m.group(1), m.group(2), None), text)
    # Uhrzeiten: 13:30 -> 13 Uhr 30, 9:00 -> 9 Uhr (Sekunden fallen weg)
    text = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?(?:\s*Uhr\b)?",
                  lambda m: f"{int(m.group(1))} Uhr" + (f" {int(m.group(2))}" if int(m.group(2)) else ""), text)
    return text


def _geld_und_zahlen(text: str) -> str:
    def betrag(m: re.Match[str], waehrung: str) -> str:
        roh = m.group("z").replace(" ", "")
        if "," in roh and "." in roh:
            roh = roh.replace(".", "").replace(",", ".")
        elif "," in roh:
            roh = roh.replace(",", ".")
        try:
            w = float(roh)
        except ValueError:
            return m.group(0)
        ganz, rest = int(w), round((w - int(w)) * 100)
        name = {"$": ("Dollar", "Cent"), "€": ("Euro", "Cent"), "EUR": ("Euro", "Cent"), "USD": ("Dollar", "Cent")}[waehrung]
        if ganz == 0 and rest:
            return f"{rest} {name[1]}"
        return f"{ganz} {name[0]}" + (f" {rest}" if rest else "")
    for zeichen in ("$", "€", "EUR", "USD"):
        z = re.escape(zeichen)
        text = re.sub(rf"{z}\s?(?P<z>\d[\d.,]*\d|\d)", lambda m, w=zeichen: betrag(m, w), text)
        text = re.sub(rf"(?P<z>\d[\d.,]*\d|\d)\s?{z}", lambda m, w=zeichen: betrag(m, w), text)
    # Spannen: 3–5, 3-5 -> 3 bis 5
    text = re.sub(r"(?<=\d)\s?[–-]\s?(?=\d)", " bis ", text)
    # Tausenderpunkte: 131.522 -> 131522 (Piper liest den Punkt sonst mit)
    text = re.sub(r"\b(\d{1,3})((?:\.\d{3})+)\b(?!\.\d)", lambda m: m.group(1) + m.group(2).replace(".", ""), text)
    # Englischer Dezimalpunkt in Zahlen wie 0.66 -> 0,66; Versionen 0.33.3 -> 0 Punkt 33 Punkt 3
    text = re.sub(r"\b\d+(?:\.\d+){2,}\b", lambda m: " Punkt ".join(m.group(0).split(".")), text)
    text = re.sub(r"\b(\d+)\.(\d{1,2})\b(?!\.)", r"\1,\2", text)
    text = re.sub(r"(?<=\d)\s?[x×]\s?(?=\d)", " mal ", text)
    return text


def sprechfassung(text: str) -> str:
    t = str(text or "")
    t = re.sub(r"```.*?```", " ", t, flags=re.S)                         # Code liest niemand vor
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)                          # Bilder in Markdown
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)                       # Links: nur der Text
    t = re.sub(r"https?://\S+", "ein Link", t)
    t = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", "eine E-Mail-Adresse", t)
    t = re.sub(r"\b[rtvpnemgdl][0-9a-f]{10}\b", "", t)                    # interne Kennungen
    # Modellnamen: "qwen3.8:27b" -> "qwen 3.8" (die Groesse hinter dem Doppelpunkt liest keiner gern)
    t = re.sub(r"\b([A-Za-z][A-Za-z-]{2,})(\d+(?:\.\d+)?)(?::[\w.-]+)?", r"\1 \2", t)
    t = re.sub(r"\b([A-Za-z][\w.-]*):\d+(?:\.\d+)?[bmBM]\b", r"\1", t)
    t = re.sub(r"(?m)^\s*\|?\s*:?-{3,}.*$", "", t)                       # Trennzeilen von Tabellen
    t = re.sub(r"(?m)^\s*\|(.+)\|\s*$", lambda m: ", ".join(x.strip() for x in m.group(1).split("|") if x.strip()) + ".", t)
    t = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", t)                          # Ueberschriften: Zeichen weg, Zeile bleibt
    t = re.sub(r"(?m)^\s*>\s?", "", t)
    t = re.sub(r"(?m)^\s*[-*•·]\s+", "", t)                              # Aufzaehlungspunkte
    t = re.sub(r"(?m)^\s*(\d{1,2})[.)]\s+", "", t)                       # Listenziffern "1. "
    t = t.replace("**", "").replace("__", "").replace("`", "")
    t = re.sub(r"(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)", "", t)
    t = _dateien(t)
    for muster, ersatz in ABKUERZUNGEN:
        t = re.sub(muster, ersatz, t)
    t = _datum(t)
    t = _geld_und_zahlen(t)
    for muster, ersatz in EINHEITEN:
        t = re.sub(muster, ersatz, t)
    t = re.sub(r"\s(--|–|—)\s", ", ", t)
    t = re.sub(r"\s?(->|→|=>)\s?", " zu ", t)
    t = t.replace("&", " und ").replace("…", ".").replace("...", ".")
    t = re.sub(r"(?<=\w)/(?=\w)", " oder ", t)
    t = re.sub(r"[„“”\"»«]", "", t)
    t = re.sub(r"\s*\(([^()]{1,200})\)", r", \1,", t)                    # Klammern als Einschub
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿️]", "", t)     # Emojis
    # Ueberschriften in Grossbuchstaben normal sprechen, kurze Abkuerzungen buchstabieren lassen.
    # Eine Ueberschrift aus Grossbuchstaben ("NEU ENTSTANDEN", "OFFENE ENTSCHEIDUNGEN"): ALLE ihre
    # Woerter normal sprechen -- sonst buchstabiert Piper "N-E-U". Nur bei mindestens zwei Woertern
    # hintereinander; eine einzelne kurze Abkuerzung ("OKR Prozess") bleibt buchstabiert.
    gross = lambda w: w if w in BUCHSTABIEREN else w.capitalize()  # noqa: E731
    t = re.sub(r"\b[A-ZÄÖÜ]{2,}(?:[ \t]+[A-ZÄÖÜ]{2,})+\b", lambda m: " ".join(gross(w) for w in m.group(0).split()), t)
    t = re.sub(r"\b[A-ZÄÖÜ]{5,}\b", lambda m: gross(m.group(0)), t)
    t = re.sub(r"\s+([.,;:!?])", r"\1", t)
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r",\s*([.,;:!?])", r"\1", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t.strip()


def abschnitte(text: str, grenze: int = 4000) -> list[tuple[str, float]]:
    """Teilt die Sprechfassung in Stuecke mit einer Pause danach: Absatz 0,6 s, Zeile
    (Listenpunkt, Ueberschrift) 0,45 s. Innerhalb eines Stuecks setzt Piper die Satzpausen selbst.
    Eine Zeile ohne Satzzeichen am Ende (Ueberschrift, Listenpunkt) bekommt einen Punkt,
    sonst zieht Piper sie in einem Atemzug mit der naechsten zusammen."""
    roh = str(text or "")
    stuecke: list[tuple[str, float]] = []
    gesamt = 0
    for absatz in re.split(r"\n\s*\n", roh):
        zeilen: list[str] = []
        for z in (z.strip() for z in absatz.split("\n")):
            if not z:
                continue
            # Ein harter Zeilenumbruch mitten im Satz (Mails, Notizen) ist keine Pause.
            if (zeilen and not re.match(r"([-*•·#>]|\d{1,2}[.)])\s", z) and re.match(r"[a-zäöüß]", z)
                    and not re.search(r"[.!?:;]$", zeilen[-1])):
                zeilen[-1] += " " + z
            else:
                zeilen.append(z)
        for i, z in enumerate(zeilen):
            s = sprechfassung(z)
            if not s or not re.search(r"\w", s):
                continue
            s = s[0].upper() + s[1:]
            if not re.search(r"[.!?:;]$", s):
                s += "."
            if gesamt + len(s) > grenze:
                # Am Satzende kuerzen, nicht mitten im Wort.
                rest = grenze - gesamt
                if rest > 80:
                    teil = s[:rest]
                    teil = teil[:max(teil.rfind(". "), teil.rfind("? "), teil.rfind("! ")) + 1] or teil
                    stuecke.append((teil, 0.0))
                return stuecke
            gesamt += len(s)
            stuecke.append((s, 0.45 if i < len(zeilen) - 1 else 0.6))
    if stuecke:
        stuecke[-1] = (stuecke[-1][0], 0.0)
    return stuecke
