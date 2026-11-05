# -*- coding: utf-8 -*-
"""MCP / 内置 Skills 的安装状态与一键安装。"""
from __future__ import annotations

import os
import shutil
import sys

TARGETS = {
    "agents": ("通用 Agents", (".agents", "skills")),
    "codex": ("Codex CLI", (".codex", "skills")),
    "claude": ("Claude Code", (".claude", "skills")),
    "opencode": ("OpenCode", (".config", "opencode", "skills")),
}


def _base() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))


def mcp_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "af-mcp.exe")
    return os.path.join(_base(), "dist", "AgentFloat", "af-mcp.exe")


def bundled_skills():
    root = os.path.join(_base(), "skills")
    rows = []
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if os.path.isfile(os.path.join(path, "SKILL.md")):
                rows.append({"name": name, "path": path})
    return rows


def target_root(target: str) -> str:
    item = TARGETS.get(str(target or "agents"), TARGETS["agents"])
    return os.path.join(os.path.expanduser("~"), *item[1])


def status() -> dict:
    mcp = mcp_path()
    skills = []
    for item in bundled_skills():
        installed = os.path.isfile(os.path.join(target_root("agents"), item["name"], "SKILL.md"))
        skills.append({"name": item["name"], "installed": installed})
    return {
        "mcp": {"path": mcp, "exists": os.path.isfile(mcp), "command": "af-mcp.exe"},
        "skills": skills,
        "skillsRoot": target_root("agents"),
        "targets": [{"id": k, "label": v[0], "root": target_root(k)} for k, v in TARGETS.items()],
    }


def install_skills(target: str = "agents") -> dict:
    dest_root = target_root(target)
    os.makedirs(dest_root, exist_ok=True)
    installed = []
    for item in bundled_skills():
        dest = os.path.join(dest_root, item["name"])
        shutil.copytree(item["path"], dest, dirs_exist_ok=True)
        installed.append(item["name"])
    return {"ok": True, "target": target, "root": dest_root, "installed": installed}
