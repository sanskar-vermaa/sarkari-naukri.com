import datetime as dt
from pathlib import Path

from scraper.harvest import classify, harvest, pick_date

FIX = Path(__file__).parent / "fixtures"
TODAY = dt.date(2026, 10, 2)
SRC = {"id": "test", "name": "Test Board"}


def run():
    html = (FIX / "sample_board.html").read_text(encoding="utf-8")
    return harvest(html, "https://example.gov.in/notices/", SRC, TODAY)


def by_title(items, needle):
    return next(i for i in items if needle in i["title"])


def test_categories():
    items = run()
    assert by_title(items, "Combined Graduate")["category"] == "notices"
    assert by_title(items, "e-Admit Card")["category"] == "admit-card"
    assert by_title(items, "Final Result")["category"] == "result"
    assert by_title(items, "Answer Keys")["category"] == "answer-key"
    assert by_title(items, "स्टाफ नर्स")["category"] == "latest-jobs"
    assert by_title(items, "Syllabus")["category"] == "syllabus"


def test_generic_link_text_uses_row_title_and_absolute_url():
    it = by_title(run(), "Combined Graduate")
    assert it["url"] == "https://example.gov.in/files/cgl2026.pdf"
    assert "Download" not in it["title"] and "MB" not in it["title"]
    assert it["is_pdf"]


def test_dates():
    items = run()
    assert by_title(items, "e-Admit")["date"] == "2026-09-28"
    assert by_title(items, "Final Result")["date"] == "2026-09-30"
    # future "last date" must not be used as publish date
    assert by_title(items, "स्टाफ नर्स")["date"] == "2026-09-29"
    assert by_title(items, "Assistant Section Officer")["date"] == "2019-03-10"


def test_excludes_junk():
    titles = " ".join(i["title"] for i in run())
    assert "Tender" not in titles
    assert "Facebook" not in titles
    assert "Privacy" not in titles
    assert sum("Syllabus" in i["title"] for i in run()) == 1  # javascript: link dropped


def test_helpers():
    assert classify("Recruitment of 500 Constables") == "latest-jobs"
    assert classify("Hall Ticket for Group D") == "admit-card"
    assert classify("Annual sports meet photos") is None
    assert pick_date("Uploaded on October 1, 2026; exam on 20 Nov 2026", TODAY) == dt.date(2026, 10, 1)
