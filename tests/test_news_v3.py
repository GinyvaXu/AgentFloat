# -*- coding: utf-8 -*-
"""B 线 · AI 日报 2.0 数据层 / AI 契约 / 状态机单测（纯函数，不联网、不起 GUI）"""
import json
import time

import pytest

from agentfloat.services.news import fetcher as nf

NOW = 1_800_000_000


@pytest.fixture()
def news_dir(tmp_path, monkeypatch):
    d = tmp_path / "news"
    d.mkdir()
    monkeypatch.setattr(nf, "news_storage_dir", lambda: str(d))
    return d


# ── 源注册表 ───────────────────────────────────────
def test_source_registry_has_15_sources_and_metadata():
    assert len(nf.SOURCES) == 15
    ids = [s["id"] for s in nf.SOURCES]
    assert len(set(ids)) == 15
    waves = [s["wave"] for s in nf.SOURCES]
    assert waves.count(1) == 10 and waves.count(2) == 5
    layers = {s["layer"] for s in nf.SOURCES}
    assert layers <= set(nf.SOURCE_LAYERS)
    for src in nf.SOURCES:
        assert callable(src["fetch"])
        assert 0.5 <= float(src["trust"]) <= 1.0
        assert src.get("default_on") is False or src.get("default_on") is True
    assert not nf.SOURCE_MAP["arxiv_ai"]["default_on"], "arXiv 按 B2 约定默认未开"
    assert nf.SOURCE_MAP["openai_news"]["trust"] >= 0.9
    assert nf.SOURCE_MAP["product_hunt"]["trust"] <= 0.65


def test_source_catalog_marks_enabled():
    catalog = nf.source_catalog(["openai_news", "qbitai"])
    by_id = {row["id"]: row for row in catalog}
    assert by_id["openai_news"]["enabled"] is True
    assert by_id["qbitai"]["enabled"] is True
    assert by_id["deepseek_news"]["enabled"] is False
    assert by_id["openai_news"]["layer_label"] == "官方"


# ── 硬过滤 / 相关来源 ─────────────────────────────
def test_prefilter_hard_filters_and_related_sources():
    items = [
        {"title": "OpenAI 发布新模型", "url": "https://a.com/x", "ts": NOW - 3600,
         "source": "OpenAI News", "source_id": "openai_news", "source_trust": 0.95},
        {"title": "", "url": "https://empty.com", "ts": NOW},
        {"title": "招聘广告：AI 工程师", "url": "https://job.com", "ts": NOW},
        {"title": "八天前的旧闻", "url": "https://old.com", "ts": NOW - 8 * 86400},
        {"title": "低信任来源", "url": "https://bad.com", "ts": NOW, "source_trust": 0.4},
        {"title": "OpenAI 发布新模型（转载）", "url": "http://www.a.com/x/", "ts": NOW - 7200,
         "source": "量子位"},
        {"title": "OpenAI 发布新模型", "url": "https://b.com/y", "ts": NOW - 600,
         "source": "机器之心"},
    ]
    kept, stats = nf.prefilter_items(
        items, blocked_keywords=["广告"], now=NOW, max_age_days=7, min_trust=0.5)
    assert len(kept) == 1
    assert kept[0]["url"] == "https://a.com/x"
    assert stats["empty"] == 1
    assert stats["blocked"] == 1
    assert stats["stale"] == 1
    assert stats["low_trust"] == 1
    assert stats["duplicate"] == 1
    assert stats["similar"] == 1
    assert len(kept[0].get("related") or []) == 2
    sources = {r["source"] for r in kept[0]["related"]}
    assert sources == {"量子位", "机器之心"}


def test_fetch_with_retry_recovers_flaky_source(monkeypatch):
    state = {"calls": 0}

    def flaky(limit):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("第一次失败")
        return [{"title": "恢复成功", "url": "https://ok/1", "ts": NOW}]

    fake = [{"id": "flaky", "name": "Flaky", "zh": "波动源", "trust": 0.7,
             "layer": "community", "wave": 1, "fetch": flaky}]
    monkeypatch.setattr(nf, "SOURCES", fake)
    monkeypatch.setattr(nf, "SOURCE_MAP", {s["id"]: s for s in fake})
    items, errors, stats = nf.fetch_with_retry(["flaky"], retries=1)
    assert [it["title"] for it in items] == ["恢复成功"]
    assert errors == []
    assert stats[0]["attempts"] == 2 and stats[0]["retried"] is True
    assert stats[0]["status"] == "ok" and stats[0]["count"] == 1


def test_fetch_rss_extracts_description(monkeypatch):
    xml = """<rss version="2.0"><channel><item>
    <title>标题一</title><link>https://example.com/a</link>
    <pubDate>Wed, 01 Jan 2026 00:00:00 +0000</pubDate>
    <description><![CDATA[<p>这是一段 <b>摘要</b>。</p>]]></description>
    </item></channel></rss>"""
    monkeypatch.setattr(nf, "_http_get", lambda url, timeout=20: xml)
    items = nf._fetch_rss("https://example.com/rss", "测试源", 5)
    assert items[0]["title"] == "标题一"
    assert items[0]["desc"] == "这是一段 摘要 。"


def test_fetch_html_links_and_rss_fallback(monkeypatch):
    html = ('<a href="/news/abc">这是一个足够长的新闻标题</a>'
            '<a href="/about">关于我们</a>')
    monkeypatch.setattr(nf, "_http_get", lambda url, timeout=20: html)
    items = nf._fetch_html_links("https://example.com/news", "测试源", r"/news/", 5)
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/news/abc"
    assert items[0]["title"] == "这是一个足够长的新闻标题"

    monkeypatch.setattr(nf, "_fetch_rss", lambda *a, **kw: [])
    monkeypatch.setattr(nf, "_fetch_html_links", lambda *a, **kw: [{"title": "兜底"}])
    got = nf._fetch_rss_or_html("https://example.com/rss", "https://example.com/news",
                                "测试源", r"/news/", 5)
    assert got == [{"title": "兜底"}]


def test_guess_category_recognizes_plain_model_and_industry():
    assert nf.guess_category("OpenAI 发布新模型") == "模型"
    assert nf.guess_category("行业观察：本周 AI 市场动态") == "行业"
    assert nf.guess_category("全新 CLI 工具上线") == "工具"


def test_title_similarity_threshold():
    assert nf.title_similarity("OpenAI 发布新模型", "OpenAI 发布新模型") == 1.0
    assert nf.title_similarity("OpenAI 发布新模型", "OpenAI 正式发布新模型") > 0.9
    assert nf.title_similarity("完全不同的标题", "另一个内容") < 0.5
    assert nf.title_similarity("", "x") == 0.0


# ── 五因子 / 分类配额 / MMR ───────────────────────
def _item(title, url, category="模型", trust=0.95, extra="", desc=""):
    return {"title": title, "url": url, "category": category, "ts": NOW - 3600,
            "source": "OpenAI News", "source_id": "openai_news",
            "source_trust": trust, "source_layer": "official",
            "extra": extra, "desc": desc}


def test_score_breakdown_and_reasons():
    item = _item("OpenAI 开源新模型发布", "https://a/1", extra="▲ 500",
                 desc="state of the art benchmark")
    bd = nf.score_breakdown(item, [{"label": "开源, 模型", "weight": 5}], now=NOW)
    assert set(bd["factors"]) == {"trust", "freshness", "interest", "importance"}
    assert bd["factors"]["trust"] == 23.8
    assert bd["factors"]["freshness"] == 20
    assert bd["factors"]["interest"] == 20
    assert bd["factors"]["importance"] >= 18
    assert 0 < bd["score"] <= 90
    reasons = nf.score_reasons(item, bd["factors"])
    assert len(reasons) >= 2
    assert "官方源" in reasons


def test_rank_items_category_cap_and_optional_relax():
    items = [_item("模型新闻 %d" % i, "https://m/%d" % i, "模型") for i in range(5)]
    items += [_item("工具新闻 %d" % i, "https://t/%d" % i, "工具") for i in range(2)]
    picked = nf.rank_items(items, max_items=4, now=NOW, category_cap=2)
    assert len(picked) == 4
    cats = [it["category"] for it in picked]
    assert cats.count("模型") == 2 and cats.count("工具") == 2
    # 严格配额：只有 2 类时最多 4 条，不会为了凑数突破单类上限
    strict = nf.rank_items(items, max_items=6, now=NOW, category_cap=2)
    assert len(strict) == 4
    # 显式放宽时补足名额（仅供特殊场景使用）
    relaxed = nf.rank_items(items, max_items=6, now=NOW, category_cap=2, relax_cap=True)
    assert len(relaxed) == 6
    for it in strict:
        assert 0 <= it["score"] <= 100
        assert len(it["reasons"]) >= 2


def test_rank_items_mmr_prefers_information_diversity():
    a = _item("OpenAI 发布新模型", "https://a/1", extra="▲ 900")
    b = _item("OpenAI 发布新模型", "https://a/2", extra="▲ 900")
    c = _item("量子计算硬件取得突破", "https://c/1", category="产品",
              desc="重磅发布")
    picked = nf.rank_items([a, b, c], max_items=2, now=NOW,
                           interests=[{"label": "模型", "weight": 5}])
    assert len(picked) == 2
    assert picked[0]["url"] == "https://a/1"
    assert picked[1]["url"] == "https://c/1", "MMR 应避免与已选条目高度相似"
    assert picked[0]["factors"]["diversity"] == 10.0
    assert picked[1]["factors"]["diversity"] == 10.0


def test_rank_items_interest_boost():
    plain = _item("普通行业资讯", "https://p/1", category="行业", trust=0.8)
    plain["source_layer"] = "community"
    liked = _item("DeepSeek 新模型发布", "https://p/2", category="行业", trust=0.8)
    liked["source_layer"] = "community"
    picked = nf.rank_items([plain, liked], max_items=1, now=NOW,
                           interests=[{"label": "DeepSeek", "weight": 5}])
    assert picked[0]["url"] == "https://p/2"


# ── AI 契约 ───────────────────────────────────────
def test_ai_prompt_contains_v3_contract():
    from agentfloat.services.news import worker as nw
    items = [dict(_item("OpenAI 发布新模型", "https://a/1"),
                  id="id-1", category="模型")]
    prompt = nw.build_ai_prompt(items, "zh", 6,
                                [{"label": "新模型", "weight": 4}], date="2026-10-26")
    assert "prompt_version=news-v3" in prompt
    assert "2026-10-26" in prompt and "id=id-1" in prompt
    for field in ("title_zh", "summary_zh", "why", "importance", "category", "headline"):
        assert field in prompt
    assert "新模型" in prompt and "权重4" in prompt


def test_validate_ai_payload_valid():
    from agentfloat.services.news import worker as nw
    source = [dict(_item("OpenAI 发布新模型", "https://a/1"), id="id-1", category="模型"),
              dict(_item("新工具上线", "https://a/2"), id="id-2", category="工具")]
    payload = {
        "headline": "今日模型与工具",
        "items": [
            {"id": "id-1", "title_zh": "OpenAI 发布新模型", "summary_zh": "摘要一",
             "why": "官方源且重要性高", "category": "模型", "importance": 5},
            {"id": "id-2", "title_zh": "新工具上线", "summary_zh": "摘要二",
             "why": "时效新", "category": "工具", "importance": 3},
        ],
    }
    res = nw.validate_ai_payload(payload, source)
    assert res["valid"] == 2 and res["fallback"] is False
    assert res["errors"] == []
    assert res["translation_coverage"] == 1.0
    assert {it["id"] for it in res["items"]} == {"id-1", "id-2"}
    assert all(it["degraded"] is False for it in res["items"])


def test_validate_ai_payload_degrades_items():
    from agentfloat.services.news import worker as nw
    source = [dict(_item("OpenAI 发布新模型", "https://a/1"),
                   id="id-1", category="模型",
                   desc="这是一段原始描述，可用于抽取式降级。")]
    payload = {
        "items": [
            {"id": "id-1", "title_zh": "", "summary_zh": "", "why": "",
             "category": "不存在的分类", "importance": 9},
            {"id": "not-exists", "title_zh": "x", "summary_zh": "y",
             "why": "z", "category": "模型", "importance": 3},
            {"id": "id-1", "title_zh": "重复", "summary_zh": "重复",
             "why": "重复", "category": "模型", "importance": 3},
        ],
    }
    res = nw.validate_ai_payload(payload, source)
    assert res["valid"] == 1 and res["fallback"] is True
    assert res["headline"] == ""
    item = res["items"][0]
    assert item["title"] == "OpenAI 发布新模型"
    assert item["summary"].startswith("这是一段原始描述")
    assert item["category"] == nf.guess_category("OpenAI 发布新模型") and item["importance"] == 3
    assert item["translated"] is False and item["degraded"] is True
    joined = "\n".join(res["errors"])
    assert "headline" in joined and "id 不存在" in joined and "分类非法" in joined


def test_repair_prompt_and_cache_prompt_version(news_dir):
    from agentfloat.services.news import worker as nw
    prompt = nw.build_repair_prompt('{"items":[]}', ["缺少 headline", "id 不存在"])
    assert "缺少 headline" in prompt and '{"items":[]}' in prompt
    assert "只输出修复后的 JSON" in prompt

    items = [{"id": "a", "title": "t", "url": "u"}]
    key1 = nf.ai_cache_key("2026-10-26", "zh", [{"label": "模型", "weight": 3}], items)
    key2 = nf.ai_cache_key("2026-10-26", "zh", [{"label": "模型", "weight": 3}], items,
                           prompt_version="news-v4")
    assert key1 != key2, "prompt_version 必须进入缓存 key"
    payload = {"headline": "h", "items": [{"id": "a"}]}
    assert nf.save_ai_cache(key1, payload) is True
    assert nf.load_ai_cache(key1) == payload
    assert nf.load_ai_cache("missing") is None


# ── 报告 v2 向后兼容 / 批次 / 质量 ───────────────
def test_save_report_b_line_fields(news_dir):
    rep = nf.save_report(
        "2026-10-26",
        [{"title": "OpenAI 发布新模型", "url": "https://a/1", "source": "OpenAI News",
          "source_id": "openai_news", "time": "10-26", "summary": "摘要",
          "related": [{"title": "转载", "url": "https://b/1", "source": "量子位"}]}],
        "# md", "zh", True, [],
        sources=[{"id": "openai_news", "ok": True, "count": 1},
                 {"id": "qbitai", "ok": True, "count": 0, "error": ""},
                 {"id": "infoq_ai", "ok": False, "count": 0, "error": "boom"}],
        stats={"raw": 10, "blocked": 2, "deduped": 4, "shown": 1},
        headline="今日头条",
        quality={"duplicate": 3, "translation_coverage": 1.0},
        batch={"id": "20261026-090000", "status": "partial"},
        prompt_version=nf.NEWS_PROMPT_VERSION)
    assert rep["version"] == 2
    assert rep["prompt_version"] == "news-v3"
    assert rep["batch"]["id"] == "20261026-090000" and rep["batch"]["status"] == "partial"
    assert rep["quality"]["duplicate"] == 3
    assert rep["source_health"]["failed"] == 1
    statuses = {s["id"]: s["status"] for s in rep["sources"]}
    assert statuses == {"openai_news": "ok", "qbitai": "degraded", "infoq_ai": "failed"}
    item = rep["items"][0]
    assert item["id"] and item["why"] and len(item["reasons"]) >= 2
    assert item["score"] > 0 and "trust" in item["factors"]
    assert item["related"][0]["source"] == "量子位"
    # 旧字段保持
    assert rep["count"] == 1 and rep["raw_md"] == "# md"
    assert nf.load_latest()["batch"]["id"] == "20261026-090000"


def test_normalize_old_latest_report(news_dir):
    (news_dir / "latest.json").write_text(json.dumps({
        "date": "2026-01-01",
        "items": [{"title": "旧数据", "url": "https://old/1"}],
        "count": 1,
    }, ensure_ascii=False), encoding="utf-8")
    rep = nf.load_latest()
    assert rep["version"] == 2
    assert rep["quality"] == {} and rep["batch"] == {} and rep["sources"] == []
    item = rep["items"][0]
    assert item["id"] and item["category"] and item["why"] == ""
    assert item["score"] == 0 and item["related"] == []


def test_old_news_config_gets_new_defaults_without_overwriting(tmp_path, monkeypatch):
    from agentfloat.core import config as cfgmod
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "news": {"sources": ["hackernews"], "use_ai": False},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cfgmod, "CONFIG_PATH", str(cfg_path))
    monkeypatch.setattr(cfgmod, "_OLD_CONFIG_PATH", str(tmp_path / "old.json"))
    cfg = cfgmod.load_config()
    assert cfg["news"]["sources"] == ["hackernews"], "不能覆盖用户已有数据源"
    assert cfg["news"]["use_ai"] is False
    assert cfg["news"]["max_age_days"] == 7
    assert cfg["news"]["category_cap"] == 3
    assert cfg["news"]["retry_failed_sources"] is True


def test_list_archives_ignores_state_and_cache(news_dir):
    (news_dir / "2026-10-01.json").write_text('{"items": []}', encoding="utf-8")
    (news_dir / "news_state.json").write_text("{}", encoding="utf-8")
    (news_dir / "news_ai_cache.json").write_text("{}", encoding="utf-8")
    assert nf.list_archives() == [("2026-10-01", 0)]


# ── 单源重试合并 ──────────────────────────────────
def test_merge_source_retry_updates_health_and_related(news_dir):
    nf.save_report("2026-10-26",
                   [{"title": "OpenAI 发布新模型", "url": "https://a/1",
                     "source": "OpenAI News", "source_id": "openai_news"}],
                   "#", "zh", False, [],
                   sources=[{"id": "qbitai", "ok": True, "count": 1}])
    report = nf.load_latest()
    incoming = [
        {"title": "OpenAI 发布新模型", "url": "https://b/1", "source": "量子位",
         "ts": NOW - 100},
        {"title": "DeepSeek 开源新模型", "url": "https://b/2", "source": "量子位",
         "ts": NOW - 200, "desc": "新模型摘要"},
    ]
    new_report, result = nf.merge_source_retry(
        report, "qbitai", incoming, now=NOW,
        interests=[{"label": "DeepSeek", "weight": 5}])
    assert result["ok"] is True and result["added"] == 1
    assert result["duplicates"] == 1 and result["quota_skipped"] == 0
    src = [s for s in new_report["sources"] if s["id"] == "qbitai"][0]
    assert src["retried"] is True and src["attempts"] == 2 and src["count"] == 2
    assert new_report["batch"]["retries"][-1]["source_id"] == "qbitai"
    assert new_report["items"][0]["related"], "重复项应挂到相关来源"
    added = [it for it in new_report["items"] if it["url"] == "https://b/2"][0]
    assert added["score"] > 0 and added["why"] and added["reasons"]


def test_merge_source_retry_respects_category_cap(news_dir):
    items = [{"title": "模型新闻 %d" % i, "url": "https://m/%d" % i,
              "category": "模型", "source": "量子位"} for i in range(3)]
    nf.save_report("2026-10-26", items, "#", "zh", False, [],
                   sources=[{"id": "qbitai", "ok": True, "count": 3}])
    incoming = [{"title": "另一个模型发布", "url": "https://new/model",
                 "category": "模型", "source": "量子位", "ts": NOW - 60}]
    new_report, result = nf.merge_source_retry(
        nf.load_latest(), "qbitai", incoming, now=NOW, category_cap=3)
    assert result["added"] == 0 and result["quota_skipped"] == 1
    assert new_report["count"] == 3
    assert new_report["quality"]["quota_skipped"] == 1


def test_merge_source_retry_error_marks_failed(news_dir):
    nf.save_report("2026-10-26", [{"title": "A", "url": "https://a/1"}], "#", "zh", False, [],
                   sources=[{"id": "qbitai", "ok": True, "count": 1}])
    report = nf.load_latest()
    new_report, result = nf.merge_source_retry(
        report, "qbitai", [], now=NOW, error="网络超时")
    assert result["ok"] is False and result["error"] == "网络超时"
    src = [s for s in new_report["sources"] if s["id"] == "qbitai"][0]
    assert src["status"] == "failed" and src["error"] == "网络超时"
    assert new_report["batch"]["status"] == "partial"
    assert any("网络超时" in e for e in new_report["source_errors"])


def test_retry_source_report_persists(news_dir, monkeypatch):
    nf.save_report("2026-10-26", [{"title": "A", "url": "https://a/1"}], "#", "zh", False, [],
                   sources=[{"id": "qbitai", "ok": True, "count": 1}])
    monkeypatch.setattr(nf, "fetch_one", lambda sid, per_source=12, timeout=15: (
        [{"title": "新工具发布", "url": "https://new/1", "source": "量子位",
          "ts": int(time.time()) - 60}], ""))
    res = nf.retry_source_report("qbitai", cfg={"blocked_keywords": [],
                                                "interests": []})
    assert res["ok"] is True and res["added"] == 1
    latest = nf.load_latest()
    assert latest["count"] == 2
    assert [s for s in latest["sources"] if s["id"] == "qbitai"][0]["retried"] is True
    assert latest["batch"]["retries"][-1]["added"] == 1


# ── 生成线程：headless 约束 / AI 映射 ─────────────
def test_worker_headless_only_cli_agents():
    from agentfloat.services.news import worker as nw
    app_agent = {"id": "gui", "name": "GUI", "launcher": "app", "command": "gui.exe"}
    web_agent = {"id": "web", "name": "Web", "launcher": "web", "command": "web.exe"}
    cli_agent = {"id": "cli", "name": "CLI", "launcher": "terminal", "command": "cli.exe"}
    assert nw.is_headless_capable(app_agent) is False
    assert nw.is_headless_capable(web_agent) is False
    assert nw.is_headless_capable(cli_agent) is True
    assert nw.is_headless_capable({"command": ""}) is False
    picked = nw._pick_agent([dict(app_agent, primary=True), web_agent, cli_agent], "")
    assert picked["id"] == "cli", "主 Agent 是 GUI/Web 时必须回退到 CLI"
    assert nw._pick_agent([app_agent, cli_agent], "gui") is None


def test_worker_apply_ai_result_and_fallback():
    from agentfloat.services.news import worker as nw
    ranked = [dict(_item("OpenAI 发布新模型", "https://a/1"),
                   id="id-1", summary="", category="模型",
                   factors={"trust": 23.8, "freshness": 20, "interest": 0,
                            "importance": 15, "diversity": 10},
                   reasons=["官方源", "24 小时内"], why="官方源；24 小时内",
                   related=[{"title": "转载", "url": "https://b/1", "source": "量子位"}])]
    ai_result = {"headline": "今日头条", "items": [{
        "id": "id-1", "title": "OpenAI 新模型发布", "summary": "AI 摘要",
        "category": "模型", "importance": 5, "why": "官方发布",
        "translated": True}]}
    out = nw.NewsWorker._apply_ai_result(ai_result, ranked)
    assert out[0]["title"] == "OpenAI 新模型发布"
    assert out[0]["summary"] == "AI 摘要"
    assert out[0]["factors"]["importance"] == 25
    assert out[0]["score"] <= 100
    assert out[0]["related"], "映射后必须保留相关来源"
    assert out[0]["why"].startswith("官方发布")
    assert len(out[0]["reasons"]) >= 2
    fb = nw.NewsWorker._fallback_item(ranked[0])
    assert fb["translated"] is None and fb["title_original"] == "OpenAI 发布新模型"
