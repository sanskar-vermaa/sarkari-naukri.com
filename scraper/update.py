"""Check every official source and merge new notices into data/notices.json.

Run:  python -m scraper.update            (all sources)
      python -m scraper.update upsc ssc   (only these source ids)
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
import traceback
from pathlib import Path

import yaml

from . import fetch
from .harvest import harvest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
NOTICES = DATA / "notices.json"
STATUS = DATA / "status.json"

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def load_yaml(name: str) -> dict:
    with open(ROOT / name, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_json(path: Path, default):
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    tmp.replace(path)


def sort_key(n: dict) -> str:
    return (n.get("date") or n["first_seen"][:10]) + n["first_seen"]


def main(only: list[str]) -> int:
    cfg = load_yaml("config.yaml")
    sources = [s for s in load_yaml("sources.yaml").get("sources", []) if s.get("enabled", True)]
    if only:
        sources = [s for s in sources if s["id"] in only]

    now = dt.datetime.now(IST)
    today = now.date()
    now_s = now.isoformat(timespec="seconds")
    max_age = dt.timedelta(days=int(cfg.get("max_age_days", 150)))
    keep = dt.timedelta(days=int(cfg.get("keep_days", 400)))
    per_source_cap = int(cfg.get("max_new_per_source", 30))

    existing = {n["id"]: n for n in load_json(NOTICES, [])}
    known_urls = {(n["source"], n["url"]) for n in existing.values()}
    old_status = {s["id"]: s for s in load_json(STATUS, {}).get("sources", [])}
    status = []
    total_new = 0

    for src in sources:
        t0 = time.time()
        st = {"id": src["id"], "name": src["name"], "url": src["url"], "checked": now_s,
              "ok": False, "found": 0, "new": 0, "error": None,
              "last_ok": old_status.get(src["id"], {}).get("last_ok")}
        try:
            html = fetch.fetch_rendered(src["url"]) if src.get("js") else fetch.fetch_html(src["url"])
            items = harvest(html, src["url"], src, today)
            st["found"] = len(items)
            st["ok"] = True
            st["last_ok"] = now_s
            added = 0
            for it in items:
                if it["id"] in existing:
                    existing[it["id"]]["last_seen"] = now_s
                    continue
                if (src["id"], it["url"]) in known_urls:
                    continue  # same link, title reworded on the site
                if it["date"] and today - dt.date.fromisoformat(it["date"]) > max_age:
                    continue  # old notice still listed on the site
                if added >= per_source_cap:
                    break
                existing[it["id"]] = {
                    **it,
                    "source": src["id"],
                    "org": src.get("short") or src["name"],
                    "org_name": src["name"],
                    "org_url": src["url"],
                    "region": src.get("region", "central"),
                    "first_seen": now_s,
                    "last_seen": now_s,
                }
                known_urls.add((src["id"], it["url"]))
                added += 1
            st["new"] = added
            total_new += added
            print(f"[ok]   {src['id']:<16} found={len(items):<4} new={added}")
        except Exception as e:  # one broken site must never stop the others
            st["error"] = f"{type(e).__name__}: {str(e)[:220]}"
            print(f"[fail] {src['id']:<16} {st['error']}")
            if "-v" in sys.argv:
                traceback.print_exc()
        st["seconds"] = round(time.time() - t0, 1)
        status.append(st)

    fetch.close()

    # Drop very old notices
    cutoff = (today - keep).isoformat()
    notices = [n for n in existing.values() if (n.get("date") or n["first_seen"][:10]) >= cutoff]
    notices.sort(key=sort_key, reverse=True)
    notices = notices[:6000]

    save_json(NOTICES, notices)
    if only:  # partial run: keep status of sources we didn't check
        merged = {s["id"]: s for s in old_status.values()}
        merged.update({s["id"]: s for s in status})
        status = list(merged.values())
    save_json(STATUS, {"updated": now_s, "new_this_run": total_new, "sources": status})
    print(f"\nTotal new notices: {total_new}   |   Total stored: {len(notices)}")
    return 0


if __name__ == "__main__":
    sys.exit(main([a for a in sys.argv[1:] if not a.startswith("-")]))
