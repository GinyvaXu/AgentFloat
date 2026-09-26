# -*- coding: utf-8 -*-
"""Web 壳后端辅助测试：skills payload / news payload / 前端目录定位"""
import json
import os

from agentfloat.webshell import server as srv


def _make_skill(root, name):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "---\nname: %s\ndescription: 示例技能 %s。\n---\n\n## 使用\n/run %s\n"
        % (name, name, name), encoding="utf-8")
    return d


def test_skills_payload(tmp_path):
    root = tmp_path / "skills"
    _make_skill(root, "alpha-skill")
    payload = srv._skills_payload({"roots": [str(root)]})
    assert payload["skills"], "应扫描到示例技能"
    assert payload["skills"][0]["name"] == "alpha-skill"
    assert payload["skills"][0]["description"]
    # categorize_skills 返回有序列表 [(类名, [技能...]), ...]
    assert isinstance(payload["categories"], (list, dict)) and len(payload["categories"]) > 0


def test_skills_payload_bad_root(tmp_path):
    payload = srv._skills_payload({"roots": [str(tmp_path / "nope")]})
    assert payload["skills"] == []


def test_news_payload(tmp_path, monkeypatch):
    from agentfloat.services.news import fetcher as nf
    monkeypatch.setattr(nf, "news_storage_dir", lambda: str(tmp_path))
    (tmp_path / "2026-01-02.json").write_text(
        json.dumps({"date": "2026-01-02", "items": [{"title": "t"}]}), encoding="utf-8")
    (tmp_path / "latest.json").write_text(
        json.dumps({"date": "2026-01-02", "items": [{"title": "t"}]}), encoding="utf-8")
    payload = srv._news_payload(None, None)
    assert payload["report"]["date"] == "2026-01-02"
    assert "2026-01-02" in payload["dates"]
    dated = srv._news_payload(None, "2026-01-02")
    assert dated["report"]["date"] == "2026-01-02"


def test_news_payload_empty(tmp_path, monkeypatch):
    from agentfloat.services.news import fetcher as nf
    monkeypatch.setattr(nf, "news_storage_dir", lambda: str(tmp_path))
    payload = srv._news_payload(None, None)
    assert payload["report"] is None and payload["dates"] == []


def test_locate_web_dir():
    d = srv._locate_web_dir()
    assert os.path.isfile(os.path.join(d, "index.html"))
