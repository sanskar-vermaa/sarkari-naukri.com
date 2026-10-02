"""Static site builder: data/notices.json + content/ -> public/

Run:  python -m builder.build
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
from collections import defaultdict
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlparse

import markdown
import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from scraper.harvest import CATEGORY_LABELS

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "public"
TPL = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

CATEGORY_ORDER = ["result", "admit-card", "latest-jobs", "answer-key", "syllabus", "notices"]
CATEGORY_INFO = {
    "latest-jobs": "Nayi sarkari bhartiyon ke notification aur online form — UPSC, SSC, Railway, Bank, Police, State PSC.",
    "admit-card": "Exam ke admit card, hall ticket, call letter aur exam city slip ke official links.",
    "result": "Sarkari exam ke result, merit list, cut off marks aur final selection list.",
    "answer-key": "Provisional aur final answer key, objection notice aur response sheet.",
    "syllabus": "Exam syllabus aur exam pattern ke official PDF.",
    "notices": "Exam date, schedule, corrigendum, interview aur document verification ki zaroori suchnaayein.",
}
REGIONS = {
    "central": ("Central Govt Jobs", "केंद्र सरकार"),
    "mp": ("MP Govt Jobs", "मध्य प्रदेश"),
    "delhi": ("Delhi Govt Jobs", "दिल्ली"),
    "up": ("UP Govt Jobs", "उत्तर प्रदेश"),
    "bihar": ("Bihar Govt Jobs", "बिहार"),
    "rajasthan": ("Rajasthan Govt Jobs", "राजस्थान"),
    "haryana": ("Haryana Govt Jobs", "हरियाणा"),
    "cg": ("Chhattisgarh Govt Jobs", "छत्तीसगढ़"),
}


# ---------------------------------------------------------------------------
def slugify(text: str, fallback: str = "") -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:70].strip("-")
    return s if len(s) >= 6 else (slugify(fallback) if fallback else s or "notice")


def load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def read_front_matter(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        return (yaml.safe_load(fm) or {}), body.strip()
    return {}, text


def to_date(v) -> dt.date | None:
    if v is None or v == "":
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


# ---------------------------------------------------------------------------
class Site:
    def __init__(self):
        self.cfg = load_yaml(ROOT / "config.yaml")
        self.base_url = self.cfg["base_url"].rstrip("/")
        self.base = urlparse(self.base_url).path.rstrip("/")  # "" or "/repo-name"
        self.now = dt.datetime.now(IST)
        self.today = self.now.date()
        self.pages_for_sitemap: list[tuple[str, str]] = []

        self.env = Environment(loader=FileSystemLoader(TPL), autoescape=select_autoescape(["html", "xml"]),
                               trim_blocks=True, lstrip_blocks=True)
        self.env.filters["d"] = self.fmt_date
        self.env.globals.update(
            cfg=self.cfg, base=self.base, base_url=self.base_url, CATS=CATEGORY_LABELS,
            CATEGORY_ORDER=CATEGORY_ORDER, REGIONS=REGIONS, year=self.today.year,
            build_time=self.now.strftime("%d/%m/%Y %I:%M %p"),
        )

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def fmt_date(v) -> str:
        d = to_date(v[:10] if isinstance(v, str) else v)
        return d.strftime("%d/%m/%Y") if d else ""

    def is_new(self, first_seen: str | None) -> bool:
        if not first_seen:
            return False
        d = to_date(first_seen[:10])
        return bool(d) and (self.today - d).days < int(self.cfg.get("new_badge_days", 3))

    def write(self, rel: str, content: str, sitemap: bool = True, lastmod: str | None = None):
        """rel like 'result/' (directory page) or 'sitemap.xml'."""
        path = OUT / rel
        if rel.endswith("/") or rel == "":
            path = path / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if sitemap:
            self.pages_for_sitemap.append((rel, lastmod or self.today.isoformat()))

    def render(self, tpl: str, **ctx) -> str:
        return self.env.get_template(tpl).render(**ctx)

    # -- data -------------------------------------------------------------
    def load(self):
        notices = json.loads((ROOT / "data/notices.json").read_text(encoding="utf-8")) \
            if (ROOT / "data/notices.json").exists() else []
        status_path = ROOT / "data/status.json"
        self.status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}

        # Detailed posts written by hand
        self.posts = []
        for p in sorted((ROOT / "content/posts").glob("*.md")):
            if p.name.startswith("_"):
                continue
            fm, body = read_front_matter(p)
            if fm.get("draft"):
                continue
            slug = fm.get("slug") or slugify(fm.get("title", p.stem), p.stem)
            date = to_date(fm.get("date")) or self.today
            updated = to_date(fm.get("updated")) or date
            post = {
                **fm,
                "kind": "post",
                "slug": slug,
                "path": f"post/{slug}/",
                "category": fm.get("category", "latest-jobs"),
                "date": date.isoformat(),
                "updated": updated.isoformat(),
                "first_seen": date.isoformat(),
                "body_html": markdown.markdown(body, extensions=["tables", "sane_lists"]),
                "match": [m.lower() for m in fm.get("match", [])],
                "org": fm.get("org", ""),
            }
            self.posts.append(post)

        # Auto notices
        self.notices = []
        for n in notices:
            n = dict(n)
            n["kind"] = "notice"
            n["slug"] = slugify(n["title"], f"{n['org']}-{n['category']}") + "-" + n["id"]
            n["path"] = f"n/{n['slug']}/"
            n["post"] = self.match_post(n)
            self.notices.append(n)

        for item in self.posts + self.notices:
            item["new"] = self.is_new(item.get("first_seen"))
            item["sort"] = (item.get("date") or item["first_seen"][:10]) + (item.get("first_seen") or "")
        self.all_items = sorted(self.posts + self.notices, key=lambda x: x["sort"], reverse=True)

        self.by_cat = defaultdict(list)
        self.by_org = defaultdict(list)
        self.by_region = defaultdict(list)
        for it in self.all_items:
            self.by_cat[it["category"]].append(it)
            if it.get("org"):
                self.by_org[slugify(it["org"], it["org"]) or "org"].append(it)
            if it.get("region"):
                self.by_region[it["region"]].append(it)

    def match_post(self, n: dict):
        title = n["title"].lower()
        for p in self.posts:
            if p["match"] and any(m in title for m in p["match"]) and \
                    (not p["org"] or p["org"].lower() == n["org"].lower()):
                return {"title": p["title"], "path": p["path"]}
        return None

    # -- pages ------------------------------------------------------------
    def build(self):
        if OUT.exists():
            shutil.rmtree(OUT)
        OUT.mkdir(parents=True)
        shutil.copytree(STATIC, OUT / "static")
        self.load()

        n_per_box = int(self.cfg.get("home_items_per_box", 25))
        featured = [p for p in self.posts if p.get("featured")][:8]
        self.write("", self.render(
            "index.html", boxes=[(c, self.by_cat.get(c, [])[:n_per_box], len(self.by_cat.get(c, [])))
                                 for c in CATEGORY_ORDER],
            featured=featured, latest=self.all_items[:12], total=len(self.all_items),
            regions=[(r, len(self.by_region.get(r, []))) for r in REGIONS if self.by_region.get(r)],
            orgs=sorted(((k, v[0]["org"], len(v)) for k, v in self.by_org.items()), key=lambda x: -x[2])[:24],
            status=self.status,
            page_title=f"{self.cfg['site_name']} – Latest Govt Jobs, Admit Card, Result {self.today.year}",
            description=self.cfg.get("tagline", ""), canonical="",
        ))

        for c in CATEGORY_ORDER:
            en, hi = CATEGORY_LABELS[c]
            self.write(f"{c}/", self.render(
                "list.html", items=self.by_cat.get(c, [])[:400], heading=f"{en} {self.today.year}", heading_hi=hi,
                intro=CATEGORY_INFO[c], cat=c,
                page_title=f"{en} {self.today.year} – Sarkari {en} Official Links | {self.cfg['site_name']}",
                description=CATEGORY_INFO[c], canonical=f"{c}/",
            ))

        for r, items in self.by_region.items():
            en, hi = REGIONS.get(r, (r.title(), r))
            self.write(f"state/{r}/", self.render(
                "list.html", items=items[:400], heading=f"{en} {self.today.year}", heading_hi=hi,
                intro=f"{en}: sabhi bhartiyan, admit card aur result ek jagah — seedhe official website ke link ke saath.",
                page_title=f"{en} {self.today.year} – Vacancy, Admit Card, Result | {self.cfg['site_name']}",
                description=f"Latest {en} notifications, admit card and result with official links.",
                canonical=f"state/{r}/",
            ))

        for key, items in self.by_org.items():
            org = items[0]["org"]
            self.write(f"org/{key}/", self.render(
                "list.html", items=items[:400], heading=f"{org} Notifications {self.today.year}",
                heading_hi=items[0].get("org_name", ""),
                intro=f"{items[0].get('org_name', org)} ki sabhi latest bhartiyan, admit card, result aur notices.",
                org_url=items[0].get("org_url"),
                page_title=f"{org} Recruitment {self.today.year}, Admit Card, Result | {self.cfg['site_name']}",
                description=f"All latest {org} notifications with official links.", canonical=f"org/{key}/",
            ))

        for n in self.notices:
            related = [x for x in self.by_org.get(slugify(n["org"], n["org"]), []) if x is not n][:8]
            self.write(n["path"], self.render(
                "notice.html", n=n, related=related,
                page_title=f"{n['title'][:90]} – {n['org']} | {self.cfg['site_name']}",
                description=f"{n['org']} {CATEGORY_LABELS[n['category']][0]}: {n['title'][:140]}. Official link and date.",
                canonical=n["path"],
            ), lastmod=(n.get("date") or n["first_seen"][:10]))

        for p in self.posts:
            related = [x for x in self.by_cat.get(p["category"], []) if x is not p][:10]
            self.write(p["path"], self.render(
                "post.html", p=p, related=related,
                page_title=f"{p['title']} | {self.cfg['site_name']}",
                description=p.get("short") or p["title"], canonical=p["path"],
            ), lastmod=p["updated"])

        for page in sorted((ROOT / "content/pages").glob("*.md")):
            fm, body = read_front_matter(page)
            body = body.replace("{{site_name}}", self.cfg["site_name"]) \
                       .replace("{{base_url}}", self.base_url) \
                       .replace("{{contact_email}}", self.cfg.get("contact_email") or "(email address config.yaml me add karein)") \
                       .replace("{{today}}", self.today.strftime("%d/%m/%Y"))
            slug = page.stem
            self.write(f"{slug}/", self.render(
                "page.html", title=fm.get("title", slug.title()),
                body_html=markdown.markdown(body, extensions=["tables"]),
                page_title=f"{fm.get('title', slug)} | {self.cfg['site_name']}",
                description=fm.get("description", ""), canonical=f"{slug}/",
            ))

        self.write("search/", self.render("search.html", page_title=f"Search | {self.cfg['site_name']}",
                                          description="Search government job notifications", canonical="search/",
                                          noindex=True), sitemap=False)
        self.write("status/", self.render("status.html", status=self.status,
                                          page_title=f"Source Status | {self.cfg['site_name']}",
                                          description="", canonical="status/", noindex=True), sitemap=False)
        self.write("404.html", self.render("404.html", page_title="Page not found", description="", canonical=""),
                   sitemap=False)

        self.write_machine_files()
        print(f"Built {len(self.pages_for_sitemap)} pages "
              f"({len(self.notices)} notices, {len(self.posts)} posts) -> {OUT}")

    def write_machine_files(self):
        search = [{"t": it["title"], "u": it["path"], "c": it["category"], "o": it.get("org", ""),
                   "d": self.fmt_date(it.get("date") or it["first_seen"])} for it in self.all_items[:3000]]
        self.write("search.json", json.dumps(search, ensure_ascii=False, separators=(",", ":")), sitemap=False)

        urls = "\n".join(
            f"<url><loc>{html.escape(self.base_url + '/' + rel)}</loc><lastmod>{lm}</lastmod></url>"
            for rel, lm in self.pages_for_sitemap)
        self.write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
                   '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "\n</urlset>\n",
                   sitemap=False)
        self.write("robots.txt", f"User-agent: *\nAllow: /\nDisallow: {self.base}/status/\n"
                   f"Disallow: {self.base}/search/\n\nSitemap: {self.base_url}/sitemap.xml\n", sitemap=False)

        client = (self.cfg.get("adsense") or {}).get("client", "")
        if client:
            pub = client.replace("ca-", "")
            self.write("ads.txt", f"google.com, {pub}, DIRECT, f08c47fec0942fa0\n", sitemap=False)

        items = []
        for it in self.all_items[:60]:
            d = to_date((it.get("first_seen") or it["date"])[:10]) or self.today
            pub = format_datetime(dt.datetime.combine(d, dt.time(9, 0), IST))
            link = f"{self.base_url}/{it['path']}"
            items.append(
                f"<item><title>{html.escape(it['title'])}</title><link>{link}</link><guid>{link}</guid>"
                f"<category>{CATEGORY_LABELS[it['category']][0]}</category><pubDate>{pub}</pubDate></item>")
        self.write("feed.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
                   f"<title>{html.escape(self.cfg['site_name'])}</title><link>{self.base_url}/</link>"
                   f"<description>{html.escape(self.cfg.get('tagline', ''))}</description>"
                   + "".join(items) + "</channel></rss>\n", sitemap=False)
        (OUT / ".nojekyll").write_text("")


if __name__ == "__main__":
    Site().build()
