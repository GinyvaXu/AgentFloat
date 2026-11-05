# -*- coding: utf-8 -*-
"""读取已安装 Skill 的 README / SKILL.md / 文件树 / 许可证（只读）。"""
from __future__ import annotations

import os
from typing import Any, Dict, List

README_NAMES = ("README.md", "README.MD", "readme.md", "README", "README.txt")
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "COPYING.md", "NOTICE")
IGNORED_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}
MAX_README = 24000
MAX_FILES = 240


def _read_text(path: str, limit: int = MAX_README) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _license_label(text: str, filename: str) -> str:
    low = (text or "").lower()
    if "mit license" in low or ("permission is hereby granted" in low and "mit" in low):
        return "MIT"
    if "apache license" in low:
        return "Apache-2.0"
    if "gnu affero general public license" in low:
        return "AGPL-3.0"
    if "gnu general public license" in low:
        return "GPL-3.0" if "version 3" in low else ("GPL-2.0" if "version 2" in low else "GPL")
    if "mozilla public license" in low:
        return "MPL-2.0"
    if "bsd 3-clause" in low or "redistribution and use in source and binary forms" in low:
        return "BSD"
    if "the unlicense" in low:
        return "Unlicense"
    first = next((line.strip() for line in (text or "").splitlines() if line.strip()), "")
    return (first[:60] or filename or "未知")


def _tree(root: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    base = os.path.abspath(root)
    for cur, dirs, files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        rel_dir = os.path.relpath(cur, base)
        for name in sorted(files):
            full = os.path.join(cur, name)
            rel = name if rel_dir == "." else os.path.join(rel_dir, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                size = 0
            rows.append({"path": rel.replace("\\", "/"), "size": int(size)})
            if len(rows) >= MAX_FILES:
                return rows
    return rows


def read_bundle(skill_dir: str) -> Dict[str, Any]:
    root = os.path.abspath(str(skill_dir or ""))
    if not os.path.isdir(root):
        return {"ok": False, "error": "目录不存在"}
    readme = ""
    readme_name = ""
    for name in README_NAMES:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            readme = _read_text(path)
            readme_name = name
            break
    skill_md = ""
    for name in ("SKILL.md", "skill.md"):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            skill_md = _read_text(path)
            break
    if not readme and skill_md:
        readme, readme_name = skill_md, "SKILL.md"
    license_text = ""
    license_name = ""
    for name in LICENSE_NAMES:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            license_text = _read_text(path, 6000)
            license_name = name
            break
    license_label = _license_label(license_text, license_name) if (license_text or license_name) else ""
    return {
        "ok": True,
        "path": root,
        "readme": readme,
        "readmeName": readme_name,
        "skillMd": skill_md,
        "files": _tree(root),
        "license": license_label,
        "licenseFile": license_name,
        "licenseText": license_text,
    }
