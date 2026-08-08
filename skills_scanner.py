# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skills 扫描器

扫描本地 agent skills 根目录，解析 SKILL.md frontmatter 与手动触发指令。
"""
import os
import re
import dataclasses


@dataclasses.dataclass
class SkillInfo(object):
    name: str
    description: str
    path: str
    root: str
    trigger: str = ""
    has_manual_trigger: bool = False


def default_skill_roots():
    """默认扫描根：本机常用 agent skills 目录"""
    home = os.path.expanduser("~")
    return [
        os.path.join(home, ".agents", "skills"),
        os.path.join(home, ".codex", "skills"),
        os.path.join(home, ".codex", "skills", ".system"),
    ]


def _expand(path):
    return os.path.abspath(os.path.expandvars(os.path.expanduser((path or "").strip())))


def scan_skills(roots):
    """扫描多个根目录，返回 SkillInfo 列表（按根目录分组排序）"""
    results = []
    seen = set()
    for root in roots:
        root = _expand(root)
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if not os.path.isdir(d):
                continue
            md = os.path.join(d, "SKILL.md")
            if not os.path.exists(md):
                continue
            info = parse_skill_md(md, root=root)
            if not info.name:
                continue
            if info.name in seen:
                info.name = "%s (%s)" % (info.name, os.path.basename(root))
            seen.add(info.name)
            results.append(info)
    return results


def parse_skill_md(path, root=""):
    """解析单个 SKILL.md：frontmatter name/description + 手动触发指令提取"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        text = ""
    name = os.path.basename(os.path.dirname(path))
    desc = ""
    trigger = ""

    fm = re.match(r"\A---\s*\n(.*?)\n---", text, re.S)
    if fm:
        body = fm.group(1)
        m = re.search(r"^name\s*:\s*(.+)$", body, re.M)
        if m:
            name = m.group(1).strip().strip("\"'")
        m = re.search(r"^description\s*:\s*(.+)$", body, re.M | re.I)
        if m:
            desc = m.group(1).strip().strip("\"'")
    if not desc:
        # 取正文首段作为描述兜底
        body2 = re.sub(r"^---.*?---", "", text, count=1, flags=re.S)
        first = re.search(r"\S[^\n]{10,240}", body2)
        if first:
            desc = first.group(0).strip()

    # 手动触发指令提取（如 grill me 的「在聊天框输入 grill me」）
    markers = [
        r"^##\s*(?:使用|用法|触发|Usage|Trigger|如何使用|怎么用|如何触发)",
        r"(?:触发指令|使用方式|使用方法|触发方式)\s*[:：]",
        r"in the chat|在聊天(?:框|中)?(?:输入|键入)",
    ]
    for pat in markers:
        m = re.search(pat, text, re.M | re.I)
        if m:
            seg = text[m.start(): m.start() + 500]
            cm = re.search(r"(?:`([^`\n]+)`|\bgrill me\b|\bgrill-me\b|\b\$([a-z][\w-]*)\b)", seg, re.I)
            if cm:
                trigger = (cm.group(1) or cm.group(2) or "grill me").strip()
                break
    if not trigger and re.search(r"grill me|grill-me", text, re.I):
        trigger = "grill me"

    has_manual = bool(trigger) or "trigger" in text.lower() or ("手动" in text and "触发" in text)
    return SkillInfo(name=name, description=desc, path=path, root=root,
                     trigger=trigger, has_manual_trigger=has_manual)
