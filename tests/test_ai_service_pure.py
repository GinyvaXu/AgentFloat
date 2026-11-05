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


def test_run_services_falls_back_to_agent_when_llm_fails(tmp_path, monkeypatch):
    """P1：AI 接入坏了必须回退 CLI Agent（Skills 翻译不能整体报错）。"""
    from types import SimpleNamespace

    from agentfloat.services import llm
    from agentfloat.services.skills import scanner

    root = tmp_path / "skills"
    _make_skill(root, "untranslated-skill")
    monkeypatch.setattr(scanner, "scan_skills",
                        lambda roots: [SimpleNamespace(name="untranslated-skill",
                                                       description="desc")])
    monkeypatch.setattr(scanner, "default_skill_roots", lambda: [str(root)])
    monkeypatch.setattr(ai, "_load_custom_translations", lambda: {})
    monkeypatch.setattr(ai, "_save_custom_translations", lambda data: None)
    monkeypatch.setattr(ai, "_save_report", lambda text: "")

    def boom(*a, **k):
        raise llm.LLMError("HTTP 401: 无效 Key")

    monkeypatch.setattr(llm, "chat", boom)

    agent_calls = []

    def fake_headless(agent, prompt, cancel=None, timeout=None):
        agent_calls.append(agent)
        return ('{"translations": {"untranslated-skill": ["未翻译技能", "描述"]}}', None)

    monkeypatch.setattr(ai, "_run_headless", fake_headless)

    config = {
        "llm": {"providers": [{"id": "ds", "name": "DS", "kind": "money",
                               "base_url": "https://api.deepseek.com/v1",
                               "model": "deepseek-chat", "api_key": "sk-1",
                               "enabled": True}],
                "active": "ds"},
        "skills": {"roots": [str(root)]},
    }
    agent = {"id": "claude", "name": "Claude", "command": "claude", "launcher": "terminal"}
    result = ai.run_services(config, agent, tasks=("skills",))

    assert result["ok"] is True
    assert agent_calls == [agent]                    # 真的走了 CLI Agent
    assert result["skills"]["added"] == 1
    assert any("回退" in w for w in result.get("warnings") or [])
