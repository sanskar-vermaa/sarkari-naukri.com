from pathlib import Path

from scraper import update

FIX = Path(__file__).parent / "fixtures"


def test_update_merges_and_survives_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "NOTICES", tmp_path / "notices.json")
    monkeypatch.setattr(update, "STATUS", tmp_path / "status.json")
    cfg = {"max_age_days": 150, "keep_days": 400, "max_new_per_source": 30}
    sources = {"sources": [
        {"id": "good", "name": "Good Board", "short": "GB", "url": "https://good.example.gov.in/"},
        {"id": "bad", "name": "Broken Board", "short": "BB", "url": "https://bad.example.gov.in/"},
    ]}
    monkeypatch.setattr(update, "load_yaml", lambda n: cfg if n == "config.yaml" else sources)

    def fake_fetch(url):
        if "bad" in url:
            raise ConnectionError("site down")
        return (FIX / "sample_board.html").read_text(encoding="utf-8")
    monkeypatch.setattr(update.fetch, "fetch_html", fake_fetch)

    update.main([])
    notices = update.load_json(update.NOTICES, [])
    status = update.load_json(update.STATUS, {})
    titles = " ".join(n["title"] for n in notices)
    assert notices and "Assistant Section Officer 2019" not in titles  # too old
    assert all(n["source"] == "good" and n["org"] == "GB" for n in notices)
    st = {s["id"]: s for s in status["sources"]}
    assert st["good"]["ok"] and st["good"]["new"] == len(notices)
    assert not st["bad"]["ok"] and "site down" in st["bad"]["error"]

    # second run adds nothing new
    update.main([])
    assert len(update.load_json(update.NOTICES, [])) == len(notices)
    assert update.load_json(update.STATUS, {})["new_this_run"] == 0
