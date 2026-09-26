# -*- coding: utf-8 -*-
"""AI 快报测试：URL 归一 / 去重 / 分类 / Markdown 兜底 / 落盘读取 / RSS 时间解析"""
from agentfloat.services.news import fetcher as nf


def test_norm_url():
    assert nf._norm_url("HTTPS://WWW.Example.com/Path/") == "example.com/path"
    assert nf._norm_url("") == ""


def test_dedupe_and_sort_and_limit():
    items = [
        {"title": "a", "url": "https://x.com/p1", "ts": 100},
        {"title": "a-dup", "url": "http://www.x.com/p1/", "ts": 90},
        {"title": "b", "url": "https://x.com/p2", "ts": 300},
        {"title": "c", "url": "", "ts": 200},          # 无 URL → 用标题做键
    ]
    out = nf.dedupe(items, max_total=3)
    assert [i["title"] for i in out] == ["b", "c", "a"], "按时间倒序且去重"


def test_guess_category():
    assert nf.guess_category("DeepSeek 开源新模型发布") == "模型"
    assert nf.guess_category("某公司完成 10 亿元融资") == "行业"
    assert nf.guess_category("全新 CLI 工具上线", url="https://github.com/x") == "工具"
    assert nf.guess_category("今天的天气不错") == "综合"


def test_build_raw_markdown():
    md = nf.build_raw_markdown([{"title": "T1", "url": "https://a", "source": "HN"}], "2026-01-01")
    assert "2026-01-01" in md and "[T1](https://a)" in md
    md_en = nf.build_raw_markdown([], "2026-01-01", language="en")
    assert md_en.startswith("AI Daily Brief")


def test_parse_rss_time():
    assert nf._parse_rss_time("Wed, 01 Jan 2026 00:00:00 +0000") > 1700000000
    assert nf._parse_rss_time("2026-01-01T00:00:00Z") == 1767225600
    now = nf._parse_rss_time("")            # 解析失败 → 当前时间
    assert now > 1700000000


def test_save_and_load_report(tmp_path, monkeypatch):
    monkeypatch.setattr(nf, "news_storage_dir", lambda: str(tmp_path))
    payload = nf.save_report("2026-01-02", [{"title": "t", "url": "u"}], "# md", "zh", False, [])
    assert payload["count"] == 1
    assert (tmp_path / "2026-01-02.json").exists()
    assert (tmp_path / "2026-01-02.md").exists()
    latest = nf.load_latest()
    assert latest["date"] == "2026-01-02"
    arch = nf.list_archives()
    assert arch and arch[0][0] == "2026-01-02"
    assert nf.load_archive("2026-01-02")["count"] == 1
    assert nf.load_archive("1999-01-01") is None


def test_load_latest_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(nf, "news_storage_dir", lambda: str(tmp_path))
    assert nf.load_latest() is None
    assert nf.list_archives() == []
