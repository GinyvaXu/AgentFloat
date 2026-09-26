# -*- coding: utf-8 -*-
"""快报生成线程辅助测试：当日是否存在 / 来源反查"""
from agentfloat.services.news import worker as nw


def test_today_news_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(nw, "news_storage_dir", lambda: str(tmp_path))
    assert nw.today_news_exists() is False
    (tmp_path / ("%s.json" % nw._cur_date())).write_text("{}", encoding="utf-8")
    assert nw.today_news_exists() is True


def test_guess_source():
    fetched = [{"url": "https://a.example/x", "source": "源A"}]
    assert nw._guess_source("HTTPS://A.EXAMPLE/X", fetched) == "源A"
    assert nw._guess_source("https://news.ycombinator.com/item?id=1", []) == "Hacker News"
    assert nw._guess_source("https://github.com/o/r", []) == "GitHub"
    assert nw._guess_source("https://sspai.com/post/1", []) == "少数派"
    assert nw._guess_source("https://unknown.example/x", []) == ""
    assert nw._guess_source("", []) == ""


def test_cur_date_format():
    d = nw._cur_date()
    assert len(d) == 10 and d[4] == "-" and d[7] == "-"
