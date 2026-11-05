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


# ── AI 通道选择 / 失败回退（4.0 回归面）──────────────
def test_generate_ai_with_fallback_prefers_llm():
    calls = []
    result, meta, used, channel = nw.generate_ai_with_fallback(
        True, True,
        lambda: (calls.append("llm") or {"valid": 3}, {"valid": 3}),
        lambda: (calls.append("agent") or {"valid": 3}, {"valid": 3}))
    assert used is True and channel == "llm"
    assert calls == ["llm"]


def test_generate_ai_with_fallback_uses_agent_when_llm_fails():
    labels = []
    calls = []

    def run_llm():
        calls.append("llm")
        return None, {"valid": 0, "errors": ["HTTP 401: 无效 Key"]}

    def run_agent():
        calls.append("agent")
        return {"valid": 3}, {"valid": 3, "errors": []}

    result, meta, used, channel = nw.generate_ai_with_fallback(
        True, True, run_llm, run_agent, emit=labels.append)
    assert calls == ["llm", "agent"]           # LLM 失败后确实调用了 Agent
    assert used is True and channel == "agent"
    assert meta["valid"] == 3
    assert any("回退" in label for label in labels)


def test_generate_ai_with_fallback_skips_without_channels():
    labels = []
    result, meta, used, channel = nw.generate_ai_with_fallback(
        False, False, lambda: (None, {}), lambda: (None, {}), emit=labels.append)
    assert result is None and used is False and channel == ""
    assert meta["valid"] == 0
    assert any("未找到可用的 AI 通道" in label for label in labels)


def test_generate_ai_with_fallback_agent_only():
    result, meta, used, channel = nw.generate_ai_with_fallback(
        False, True, lambda: (None, {}), lambda: ({"valid": 2}, {"valid": 2}))
    assert used is True and channel == "agent"
