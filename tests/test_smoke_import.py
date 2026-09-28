# -*- coding: utf-8 -*-
"""P1 骨架测试：核心纯逻辑模块可导入 + 版本/主题/注册表一致性。

说明：tests/ 的完整测试体系在 P3 阶段落地；本文件用于验证 src 结构
（pytest 配置、导入链路）处于健康状态，不依赖 Qt/网络。
"""
import importlib
import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


def test_core_modules_import():
    for name in (
        "agentfloat.core.paths",
        "agentfloat.core.registry",
        "agentfloat.core.theme",
        "agentfloat.core.version",
        "agentfloat.services.api_monitor.config",
        "agentfloat.services.skills.scanner",
        "agentfloat.services.skills.translations",
        "agentfloat.services.webagent",
    ):
        importlib.import_module(name)


def test_version_file_is_unique_source():
    from agentfloat.core.version import VERSION
    root = os.path.dirname(SRC)
    with open(os.path.join(root, "VERSION"), encoding="utf-8-sig") as f:
        assert VERSION == f.read().strip()


def test_theme_single_source():
    from agentfloat.core.theme import THEMES, get_colors
    assert set(THEMES) == {"light", "dark"}
    # v2.4.0 起对齐 ProjectDock：强调色统一 #0a84ff（亮/暗）
    assert get_colors("dark")["ACCENT"] == (10, 132, 255)
    assert get_colors("light")["ACCENT"] == (10, 132, 255)
    assert get_colors("light")["ACCENT_STRONG"] == (0, 113, 227)
    assert get_colors("dark")["TEXT"] == (245, 245, 247)


def test_registry_defaults():
    from agentfloat.core.registry import get_primary_agent, normalize_agents
    agents = normalize_agents([])
    assert agents
    assert get_primary_agent(agents) is agents[0]
    assert all(a.get("id") for a in agents)


def test_paths_project_dir():
    from agentfloat.core import paths
    assert os.path.isdir(paths.PROJECT_DIR)
    assert os.path.isfile(os.path.join(paths.PROJECT_DIR, "VERSION"))
