# -*- coding: utf-8 -*-
"""v3.9.0 AI 快报数据层测试：报告 v2 / 已读收藏状态 / 屏蔽词 / 单源重试 / 保留清理 / 导出 / 下次时间"""
import datetime
import os
import time

import pytest

from agentfloat.services.news import fetcher as nf


@pytest.fixture()
def news_dir(tmp_path, monkeypatch):
    d = tmp_path / "news"
    d.mkdir()
    monkeypatch.setattr(nf, "news_storage_dir", lambda: str(d))
    return d


# ── 报告 v2 ───────────────────────────────────────
def test_save_report_v2_enriches_items(news_dir):
    rep = nf.save_report("2026-10-08",
                         [{"title": "DeepSeek 开源新模型", "url": "https://x/a"},
                          {"title": "某公司融资 10 亿元", "url": "https://y/b"}],
                         "# md", "zh", True, [], sources=[{"id": "sspai", "ok": True}],
                         stats={"raw": 2, "shown": 2}, headline="今日头条")
    assert rep["version"] == 2
    assert rep["headline"] == "今日头条"
    for it in rep["items"]:
        assert it["id"] and len(it["id"]) == 16
        assert it["category"] in ("模型", "工具", "论文", "产品", "行业", "综合")
        assert it["read"] is False and it["starred"] is False
    assert rep["items"][0]["category"] == "模型"
    assert rep["sources"] and rep["stats"]["shown"] == 2
    # 兼容旧字段
    assert rep["count"] == 2 and rep["raw_md"] == "# md"
    assert nf.load_latest()["headline"] == "今日头条"


def test_item_id_stable_across_calls():
    a = nf.item_id("https://Example.com/x/", "标题")
    b = nf.item_id("http://www.example.com/x", "标题")
    assert a == b, "归一化后同一链接应得到同一 id（已读状态才能延续）"
    assert a != nf.item_id("https://example.com/y", "标题")


# ── 已读 / 收藏状态 ───────────────────────────────
def test_read_and_star_state_roundtrip(news_dir):
    iid = "abc123"
    nf.mark_read(iid, True)
    st = nf.load_state()
    assert iid in st["read"]
    nf.mark_read(iid, False)
    assert iid not in nf.load_state()["read"]
    _st, starred = nf.toggle_star(iid)
    assert starred is True and iid in nf.load_state()["starred"]
    _st, starred2 = nf.toggle_star(iid)
    assert starred2 is False and iid not in nf.load_state()["starred"]


def test_apply_state_sets_flags_and_unread(news_dir):
    nf.save_report("2026-10-08",
                   [{"title": "A", "url": "https://a"}, {"title": "B", "url": "https://b"}],
                   "#", "zh", False, [])
    rep = nf.load_latest()
    nf.mark_read(rep["items"][0]["id"], True)
    _st, _ = nf.toggle_star(rep["items"][1]["id"])
    nf.apply_state(rep)
    assert rep["items"][0]["read"] is True and rep["items"][1]["read"] is False
    assert rep["items"][1]["starred"] is True
    assert rep["unread"] == 1


def test_mark_all_read(news_dir):
    nf.save_report("2026-10-08", [{"title": "A", "url": "https://a"},
                                  {"title": "B", "url": "https://b"}], "#", "zh", False, [])
    nf.mark_all_read()
    rep = nf.load_latest()
    nf.apply_state(rep)
    assert rep["unread"] == 0


def test_state_file_survives_corruption(news_dir):
    (news_dir / "news_state.json").write_text("{ not json", encoding="utf-8")
    assert nf.load_state() == {"read": {}, "starred": []}


# ── 屏蔽词 / 单源 ─────────────────────────────────
def test_filter_blocked():
    items = [{"title": "招聘：AI 工程师", "url": "a"},
             {"title": "大模型发布", "url": "b", "summary": "含 广告 字样"},
             {"title": "正常资讯", "url": "c"}]
    out = nf.filter_blocked(items, ["招聘", "广告"])
    assert [i["url"] for i in out] == ["c"]
    assert nf.filter_blocked(items, []) == items
    assert nf.filter_blocked(items, ["  ", ""]) == items


def test_fetch_one_unknown_source():
    items, err = nf.fetch_one("not-a-source")
    assert items == [] and "未知数据源" in err


def test_fetch_all_stats_reports_per_source(monkeypatch):
    monkeypatch.setitem(nf.SOURCE_MAP, "ok_src",
                        {"id": "ok_src", "name": "ok", "zh": "正常源",
                         "fetch": lambda n: [{"title": "t", "url": "u"}]})
    monkeypatch.setitem(nf.SOURCE_MAP, "bad_src",
                        {"id": "bad_src", "name": "bad", "zh": "故障源",
                         "fetch": lambda n: (_ for _ in ()).throw(RuntimeError("boom"))})
    items, errors, stats = nf.fetch_all_stats(["ok_src", "bad_src"])
    assert len(items) == 1 and errors
    by_id = {s["id"]: s for s in stats}
    assert by_id["ok_src"]["ok"] is True and by_id["ok_src"]["count"] == 1
    assert by_id["bad_src"]["ok"] is False and "boom" in by_id["bad_src"]["error"]


def test_fetch_all_backward_compatible(monkeypatch):
    monkeypatch.setitem(nf.SOURCE_MAP, "x_src",
                        {"id": "x_src", "name": "x", "zh": "X",
                         "fetch": lambda n: [{"title": "t", "url": "u"}]})
    items, errors = nf.fetch_all(["x_src"])
    assert len(items) == 1 and errors == []


# ── 保留清理 / 导出 / 下次时间 ────────────────────
def test_cleanup_old_removes_expired(news_dir):
    today = datetime.date.today()
    old = (today - datetime.timedelta(days=30)).isoformat()
    fresh = (today - datetime.timedelta(days=2)).isoformat()
    for d in (old, fresh):
        (news_dir / ("%s.json" % d)).write_text("{}", encoding="utf-8")
        (news_dir / ("%s.md" % d)).write_text("x", encoding="utf-8")
    (news_dir / "latest.json").write_text("{}", encoding="utf-8")
    (news_dir / "news_state.json").write_text("{}", encoding="utf-8")
    removed = nf.cleanup_old(14)
    assert removed == 2, "应删掉旧日期的 json+md"
    assert not (news_dir / ("%s.json" % old)).exists()
    assert (news_dir / ("%s.md" % fresh)).exists()
    assert (news_dir / "latest.json").exists(), "latest.json 不能被清掉"
    assert (news_dir / "news_state.json").exists(), "状态文件不能被清掉"


def test_export_markdown_writes_file(news_dir):
    nf.save_report("2026-10-08", [{"title": "A", "url": "https://a", "summary": "摘要",
                                   "category": "模型", "source": "量子位"}],
                   "# md", "zh", True, [])
    path, err = nf.export_markdown()
    assert not err and os.path.isfile(path)
    text = open(path, encoding="utf-8").read()
    assert "## 模型" in text and "https://a" in text and "摘要" in text
    assert "AgentFloat" in text


def test_export_markdown_missing_date(news_dir):
    path, err = nf.export_markdown("2020-01-01")
    assert path == "" and "没有快报" in err


def test_build_export_markdown_handles_v1_report():
    md = nf.build_export_markdown({"date": "2026-01-01",
                                   "items": [{"title": "T", "url": "u"}]})
    assert "# " in md and "T" in md


def test_next_run_time_modes():
    assert nf.next_run_time({"schedule_mode": "off"}) == ""
    assert nf.next_run_time({"schedule_mode": "startup"}) == "启动时"
    now = datetime.datetime(2026, 10, 8, 8, 0)
    assert nf.next_run_time({"schedule_mode": "daily", "schedule_time": "09:00"},
                            now=now) == "10-08 09:00"
    # 时间已过 → 明天
    later = datetime.datetime(2026, 10, 8, 10, 0)
    assert nf.next_run_time({"schedule_mode": "daily", "schedule_time": "09:00"},
                            now=later) == "10-09 09:00"
    # 非法时间 → 回退 09:00 不抛异常
    assert nf.next_run_time({"schedule_mode": "daily", "schedule_time": "bad"},
                            now=now) == "10-08 09:00"


def test_worker_has_progress_signal_and_cancel():
    import inspect
    from agentfloat.services.news import worker as nw
    assert hasattr(nw.NewsWorker, "progress"), "生成线程应暴露阶段进度信号"
    assert "cancel" in inspect.getsource(nw.NewsWorker)
    src = inspect.getsource(nw.NewsWorker)
    for phase in ("fetch", "dedupe", "ai", "save"):
        assert '"%s"' % phase in src, "缺少阶段 %s" % phase
    assert "filter_blocked" in src and "cleanup_old" in src


def test_news_handlers_expose_v2_endpoints():
    import inspect
    from agentfloat.webshell import handlers, server
    hsrc = inspect.getsource(handlers)
    for name in ("news_mark_read", "news_star", "news_export", "news_retry_source"):
        assert "def %s" % name in hsrc, "缺少处理器 %s" % name
    ssrc = inspect.getsource(server)
    for route in ("/news/star", "/news/export", "/news/retry_source", "/news/cancel"):
        assert route in ssrc, "缺少路由 %s" % route


def test_read_latest_tolerates_old_seconds():
    """load_state 对缺失/旧格式要稳（升级用户没有 news_state.json）"""
    assert isinstance(nf.load_state(), dict)
    assert isinstance(nf.load_state().get("read"), dict)
    _ = time.time()
