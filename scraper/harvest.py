"""Link harvesting: official page HTML -> list of notice dicts.

The harvester is deliberately generic. Instead of depending on each government
site's exact HTML layout (which changes often), it walks every link on the page,
keeps the ones whose text looks like a recruitment / admit card / result notice,
works out a category from keywords, and picks up a nearby date if one is shown.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from urllib.parse import urldefrag, urljoin, urlparse

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Categories (order matters: first match wins)
# ---------------------------------------------------------------------------
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("answer-key", [
        r"answer[\s-]*keys?", r"\bkeys? of\b", r"objection", r"response sheet",
        r"उत्तर\s*कुंजी", r"मॉडल\s*उत्तर",
    ]),
    ("admit-card", [
        r"admit[\s-]*cards?", r"e[\s-]*admit", r"admit certificate", r"hall[\s-]*tickets?",
        r"call[\s-]*letters?", r"exam(ination)? city", r"city intimation", r"city slip",
        r"प्रवेश[\s-]*पत्र", r"एडमिट\s*कार्ड",
    ]),
    ("result", [
        r"\bresults?\b", r"merit[\s-]*list", r"select(ion|ed)[\s-]*(list|candidates)",
        r"final[\s-]*selection", r"cut[\s-]*off", r"\bmarks\b", r"score[\s-]*card",
        r"provisional(ly)? selected", r"recommended candidates", r"waiting list",
        r"परिणाम", r"परीक्षा\s*फल", r"चयन\s*सूची", r"मेरिट\s*सूची", r"रिजल्ट",
    ]),
    ("syllabus", [
        r"syllabus", r"scheme of (exam|examination)", r"exam(ination)? pattern",
        r"पाठ्यक्रम", r"सिलेबस",
    ]),
    ("latest-jobs", [
        r"recruitment", r"recruit", r"vacanc", r"advertisement", r"\badvt\b", r"\bnotification\b",
        r"apply online", r"online application", r"applications? (are|is)? ?invited",
        r"engagement of", r"walk[\s-]*in", r"\bposts? of\b", r"empanelment", r"apprentice",
        r"भर्ती", r"विज्ञापन", r"रिक्ति", r"आवेदन", r"नियुक्ति",
    ]),
    ("notices", [
        r"exam(ination)? (date|schedule|calendar)", r"date[\s-]*sheet", r"time[\s-]*table",
        r"corrigendum", r"addendum", r"\bnotice\b", r"postpone", r"reschedul",
        r"extension", r"extended", r"interview", r"document verification", r"\bdv\b",
        r"skill test", r"physical (test|efficiency|standard)", r"\bpet\b", r"\bpst\b",
        r"calendar", r"important", r"सूचना", r"शुद्धि\s*पत्र", r"साक्षात्कार", r"परीक्षा",
    ]),
]
_COMPILED = [(cat, re.compile("|".join(pats), re.I)) for cat, pats in CATEGORY_RULES]

CATEGORY_LABELS = {
    "latest-jobs": ("Latest Jobs", "नई भर्ती"),
    "admit-card": ("Admit Card", "एडमिट कार्ड"),
    "result": ("Result", "रिजल्ट"),
    "answer-key": ("Answer Key", "आंसर की"),
    "syllabus": ("Syllabus", "सिलेबस"),
    "notices": ("Important Notice", "जरूरी सूचना"),
}

# Links that are never job notices.
EXCLUDE = re.compile(
    r"tender|e-?bid|\bbids?\b|quotation|auction|\brti\b|right to information|annual report|"
    r"citizen'?s? charter|results?[\s-]*framework|\brfd\b|budget|purchase of|supply of|procurement|"
    r"court case|judg(e)?ment|minutes of|\bmou\b|press release|photo gallery|video gallery|"
    r"screen reader|skip to|sitemap|feedback|privacy policy|terms (of|and)|disclaimer|"
    r"copyright|hyperlink|accessibility|help ?desk|contact us|about us|\blogin\b|log in|sign in|"
    r"register(ation)? here|forgot|archive|older (news|notices)|view all|more\.{0,3}$|"
    r"empanelment of (vendors|agencies|firms)|newsletter|hindi pakhwada|swachh|yoga day|"
    r"pension|gpf|leave rules|transfer order|posting order|promotion order|seniority list|"
    r"\bdak\b|circular regarding|office order|internal circular|important links|useful links|"
    r"related links|quick links|notice ?board$|what'?s new$|all notices|latest news$|announcements?$",
    re.I,
)

GENERIC_LINK_TEXT = re.compile(
    r"^(click here|click|here|download|view|view details?|details?|pdf|open|link|read more|more|"
    r"new|देखें|डाउनलोड|यहाँ क्लिक करें|विवरण|\(?\d+(\.\d+)?\s*(kb|mb)\)?|english|hindi|हिंदी)$",
    re.I,
)

BAD_SCHEMES = ("javascript:", "mailto:", "tel:", "whatsapp:")
SOCIAL = re.compile(r"facebook\.|twitter\.|x\.com|instagram\.|youtube\.|linkedin\.|t\.me/|telegram\.|koo\.in|whatsapp\.", re.I)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

DATE_PATTERNS = [
    # 02-10-2026, 02/10/2026, 02.10.2026, 2-10-26
    (re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})\b"), "dmy"),
    # 2026-10-02
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    # 02 Oct 2026, 2nd October, 2026, 02-Oct-2026
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s.-]*([A-Za-z]{3,9})[\s.,-]*(\d{4})\b"), "dMy"),
    # October 2, 2026
    (re.compile(r"\b([A-Za-z]{3,9})[\s.]+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})\b"), "Mdy"),
]


def _mk_date(y: int, m: int, d: int) -> dt.date | None:
    if y < 100:
        y += 2000
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[dt.date]:
    out: list[dt.date] = []
    for rx, kind in DATE_PATTERNS:
        for m in rx.finditer(text):
            a, b, c = m.groups()
            if kind == "dmy":
                d = _mk_date(int(c), int(b), int(a))
            elif kind == "ymd":
                d = _mk_date(int(a), int(b), int(c))
            elif kind == "dMy":
                mon = MONTHS.get(b[:3].lower())
                d = _mk_date(int(c), mon, int(a)) if mon else None
            else:
                mon = MONTHS.get(a[:3].lower())
                d = _mk_date(int(c), mon, int(b)) if mon else None
            if d and 2000 <= d.year <= 2100:
                out.append(d)
    return out


def pick_date(text: str, today: dt.date) -> dt.date | None:
    """Most recent date that is not in the future (a notice's issue date).

    Future dates in a row are usually 'last date' / 'exam date', not the publish date.
    """
    dates = [d for d in find_dates(text) if d <= today + dt.timedelta(days=1)]
    return max(dates) if dates else None


def classify(title: str, default: str | None = None) -> str | None:
    for cat, rx in _COMPILED:
        if rx.search(title):
            return cat
    return default


def clean_text(s: str) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    s = re.sub(r"^(new|नया|नवीन)\s*[:\-–]?\s*", "", s, flags=re.I)
    s = re.sub(r"\s*\b(new|click here)\b\s*$", "", s, flags=re.I)
    s = re.sub(r"\(\s*\d+(\.\d+)?\s*(kb|mb)\s*\)", "", s, flags=re.I)
    return s.strip(" -–|:").strip()


def normalize_url(href: str, base: str) -> str | None:
    href = (href or "").strip()
    if not href or href.startswith("#") or href.lower().startswith(BAD_SCHEMES):
        return None
    url = urldefrag(urljoin(base, href))[0]
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        return None
    if SOCIAL.search(p.netloc + p.path):
        return None
    return url.replace(" ", "%20")


def make_id(url: str, title: str) -> str:
    key = url.lower().rstrip("/") + "|" + re.sub(r"[^a-z0-9ऀ-ॿ]+", "", title.lower())[:120]
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def _row_text(a) -> str:
    """Text of the table row / list item / paragraph the link sits in."""
    node = a
    for _ in range(4):
        node = node.parent
        if node is None:
            break
        if node.name in ("tr", "li", "p", "dd", "article"):
            return node.get_text(" ", strip=True)
        if node.name == "div" and len(node.get_text(" ", strip=True)) < 500:
            return node.get_text(" ", strip=True)
    return ""


def _title_from_row(a, link_text: str) -> str:
    tr = a.find_parent("tr")
    if tr is not None:
        cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        cells = [c for c in cells if not re.fullmatch(r"[\d\s./-]*", c) and not GENERIC_LINK_TEXT.match(c)]
        return max(cells, key=len) if cells else ""
    text = _row_text(a)
    if link_text:
        text = text.replace(a.get_text(" ", strip=True), " ")
    return re.sub(r"^\s*\d{1,3}[.)]?\s+", "", clean_text(text))


def harvest(html: str, page_url: str, source: dict, today: dt.date | None = None) -> list[dict]:
    """Return candidate notices found on one page, in page order, de-duplicated."""
    today = today or dt.date.today()
    soup = BeautifulSoup(html, "html.parser")
    for bad in soup(["script", "style", "noscript"]):
        bad.decompose()

    roots = soup.select(source["selector"]) if source.get("selector") else [soup]
    include = re.compile(source["include"], re.I) if source.get("include") else None
    exclude = re.compile(source["exclude"], re.I) if source.get("exclude") else None

    seen: set[str] = set()
    items: list[dict] = []
    for root in roots:
        for a in root.find_all("a", href=True):
            url = normalize_url(a["href"], page_url)
            if not url or url.rstrip("/") == page_url.rstrip("/"):
                continue

            link_text = clean_text(a.get_text(" ", strip=True) or a.get("title", ""))
            row = clean_text(_row_text(a))
            if not link_text or GENERIC_LINK_TEXT.match(link_text) or len(link_text) < 12:
                # "Download" / "Click here" style link: the real title is in the row.
                title = _title_from_row(a, link_text)
            else:
                title = link_text
            title = clean_text(title)
            if len(title) < 15:
                continue
            if len(title) > 260:
                title = title[:257].rsplit(" ", 1)[0] + "…"

            if EXCLUDE.search(title) or (exclude and exclude.search(title)):
                continue
            if include and not include.search(title):
                continue

            category = classify(title, source.get("default_category"))
            if not category:
                continue

            nid = make_id(url, title)
            if nid in seen:
                continue
            seen.add(nid)

            date = pick_date(title + " " + row, today)
            items.append({
                "id": nid,
                "title": title,
                "url": url,
                "is_pdf": urlparse(url).path.lower().endswith(".pdf"),
                "category": category,
                "date": date.isoformat() if date else None,
            })
    return items
