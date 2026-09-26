# -*- coding: utf-8 -*-
"""本地 AI 服务纯逻辑测试：平台 URL 补全 / 新 skill 检测（首轮基线 / 新装触发 / 防重复）"""
from agentfloat.services.skills import ai_service as ai


def _make_skill(root, name):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        "---\nname: %s\ndescription: 描述 %s。\n---\n" % (name, name), encoding="utf-8")
    return d


def test_ensure_platform_url():
    ep = ai._ensure_platform_url({"name": "DeepSeek API"})
    assert "platform.deepseek.com" in ep["platform_url"]

    keep = ai._ensure_platform_url({"name": "X", "platform_url": "https://keep"})
    assert keep["platform_url"] == "https://keep"

    unknown = ai._ensure_platform_url({"name": "some-random-service"})
    assert not unknown.get("platform_url")


def test_find_new_skills_first_run_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "SKILL_STATE_PATH", str(tmp_path / "skill_state.json"))
    root = tmp_path / "skills"
    _make_skill(root, "s1")
    assert ai.find_new_skills([str(root)]) == [], "首次运行只建立基线，不触发翻译"
    assert (tmp_path / "skill_state.json").exists()


def test_find_new_skills_detects_and_dedupes(tmp_path, monkeypatch):
    state = tmp_path / "skill_state.json"
    monkeypatch.setattr(ai, "SKILL_STATE_PATH", str(state))
    root = tmp_path / "skills"
    _make_skill(root, "s1")
    ai.find_new_skills([str(root)])                 # 建立基线

    _make_skill(root, "brand-new-skill")            # 新装一个未翻译的 skill
    new = ai.find_new_skills([str(root)])
    assert [s.name for s in new] == ["brand-new-skill"]

    again = ai.find_new_skills([str(root)])         # 2 天内不重复触发
    assert again == []


def test_find_new_skills_ignores_translated(tmp_path, monkeypatch):
    monkeypatch.setattr(ai, "SKILL_STATE_PATH", str(tmp_path / "skill_state.json"))
    root = tmp_path / "skills"
    _make_skill(root, "s1")
    ai.find_new_skills([str(root)])

    _make_skill(root, "find-skills")                # 内置翻译表已收录该名称
    assert ai.find_new_skills([str(root)]) == []
