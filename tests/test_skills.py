# -*- coding: utf-8 -*-
"""Skills 测试：扫描 / SKILL.md 解析 / frontmatter / 触发指令提取 / 分类 / 翻译表"""
from agentfloat.services.skills import scanner as sc
from agentfloat.services.skills import translations as tr


def make_skill(root, name, body="", fm_name=None, fm_desc=None):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    parts = []
    if fm_name or fm_desc:
        parts.append("---")
        if fm_name:
            parts.append("name: %s" % fm_name)
        if fm_desc:
            parts.append("description: %s" % fm_desc)
        parts.append("---")
    parts.append(body or ("# %s\n" % name))
    (d / "SKILL.md").write_text("\n".join(parts), encoding="utf-8")
    return d


# ── 解析 ─────────────────────────────────────────────
def test_parse_skill_md_frontmatter(tmp_path):
    d = make_skill(tmp_path, "demo-skill",
                   fm_name="demo-skill", fm_desc="用于测试的示例技能。",
                   body="# Demo\n\n## 使用\n输入 `demo-skill` 即可触发。\n")
    info = sc.parse_skill_md(str(d / "SKILL.md"), root=str(tmp_path))
    assert info.name == "demo-skill"
    assert "示例技能" in info.description
    assert info.trigger == "demo-skill", "应提取到反引号包裹的触发指令"
    assert "/run" in info.trigger_doc or "## 使用" in info.trigger_doc or info.trigger_doc
    assert info.has_manual_trigger is True


def test_parse_skill_md_fallback_dirname(tmp_path):
    d = make_skill(tmp_path, "bare-skill", body="没有 frontmatter 的技能说明段落内容。")
    info = sc.parse_skill_md(str(d / "SKILL.md"), root=str(tmp_path))
    assert info.name == "bare-skill"
    assert info.description, "应回退取正文首段"


def test_parse_desc_block_scalar():
    body = "description: >\n  第一行\n  第二行\nname: x"
    assert tr.__name__  # sanity
    assert sc._parse_desc(body) == "第一行 第二行"
    body2 = "description: |\n  行一\n  行二"
    assert sc._parse_desc(body2) == "行一\n行二"


def test_extract_trigger_doc_section():
    text = "# T\n\n## 使用\n输入 `/do thing` 触发。\n\n## 其他\nxxx"
    doc = sc._extract_trigger_doc(text)
    assert "/do thing" in doc


# ── 扫描 ─────────────────────────────────────────────
def test_scan_skills(tmp_path):
    root = tmp_path / "skills"
    make_skill(root, "alpha", fm_name="alpha", fm_desc="A 技能。")
    make_skill(root, "beta", fm_name="beta", fm_desc="B 技能。")
    (root / "not-a-skill").mkdir()          # 无 SKILL.md → 跳过
    results = sc.scan_skills([str(root)])
    names = [s.name for s in results]
    assert names == ["alpha", "beta"]


def test_scan_skills_duplicate_name_suffix(tmp_path):
    r1 = tmp_path / "r1"
    r2 = tmp_path / "r2"
    make_skill(r1, "same", fm_name="same", fm_desc="d")
    make_skill(r2, "same", fm_name="same", fm_desc="d")
    results = sc.scan_skills([str(r1), str(r2)])
    assert len(results) == 2
    assert results[1].name.startswith("same ("), "重名应加来源后缀"


def test_scan_skills_missing_root(tmp_path):
    assert sc.scan_skills([str(tmp_path / "nope")]) == []


def test_default_skill_roots_is_list():
    roots = sc.default_skill_roots()
    assert isinstance(roots, list) and roots


def test_expand_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AF_EXPAND_XYZ", str(tmp_path))
    assert sc._expand("$AF_EXPAND_XYZ") == str(tmp_path)


# ── 分类 ─────────────────────────────────────────────
def test_categorize_skills(tmp_path):
    root = tmp_path / "roots"
    make_skill(root / "pool", "godot-builder", fm_name="godot-builder", fm_desc="d")
    make_skill(root / "pool", "caveman", fm_name="caveman", fm_desc="d")
    make_skill(root / "pool", "random-xyz", fm_name="random-xyz", fm_desc="d")
    make_skill(root / "browser" / "inner", "foo", fm_name="foo", fm_desc="d")
    make_skill(root / ".system", "sys-skill", fm_name="sys-skill", fm_desc="d")

    skills = sc.scan_skills([str(root / "pool"), str(root / "browser" / "inner"),
                             str(root / ".system")])
    cats = dict(sc.categorize_skills(skills))
    assert [s.name for s in cats.get("Godot 游戏开发", [])] == ["godot-builder"]
    assert [s.name for s in cats.get("开发辅助", [])] == ["caveman"]
    assert [s.name for s in cats.get("浏览器自动化", [])] == ["foo"]
    assert [s.name for s in cats.get("Codex 系统", [])] == ["sys-skill"]
    assert [s.name for s in cats.get("其他", [])] == ["random-xyz"]


def test_skill_key_prefix():
    assert sc._skill_key("latex:latex-compile") == "latex"
    assert sc._skill_key("  Godot-X  ") == "godot-x"


# ── 翻译表 ───────────────────────────────────────────
def test_get_zh_builtin():
    zh = tr.get_zh("find-skills")
    assert zh[0] and "Skills" in zh[0] or "发现" in zh[0]


def test_get_zh_unknown():
    assert tr.get_zh("no-such-skill-xyz") == (None, None)


def test_get_zh_custom_priority(tmp_path, monkeypatch):
    custom = tmp_path / "skills_translations_ai.json"
    custom.write_text('{"find-skills": ["自定义名", "自定义简介"]}', encoding="utf-8")
    if hasattr(tr._load_custom, "_cache"):
        delattr(tr._load_custom, "_cache")     # 清掉懒加载缓存，确保重新读取
    monkeypatch.setattr(tr, "_custom_path", lambda: str(custom))
    try:
        zh = tr.get_zh("find-skills")
        assert zh == ("自定义名", "自定义简介")
    finally:
        if hasattr(tr._load_custom, "_cache"):
            delattr(tr._load_custom, "_cache")
