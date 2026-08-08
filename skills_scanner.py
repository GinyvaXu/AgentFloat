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
    trigger_doc: str = ""
    has_manual_trigger: bool = False


def default_skill_roots():
    """默认扫描根：本机常用 agent skills 目录（含 Codex 插件缓存）"""
    import glob
    home = os.path.expanduser("~")
    roots = [
        os.path.join(home, ".agents", "skills"),
        os.path.join(home, ".codex", "skills"),
        os.path.join(home, ".codex", "skills", ".system"),
    ]
    # 插件缓存（版本目录随插件更新变化，用 glob 匹配）
    roots += sorted(glob.glob(os.path.join(home, ".codex", "plugins", "cache", "*", "*", "*", "skills")))
    # 去重并只保留存在的目录
    seen, out = set(), []
    for r in roots:
        key = os.path.normpath(r).lower()
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _expand(path):
    return os.path.abspath(os.path.expandvars(os.path.expanduser((path or "").strip())))


def _extract_trigger_doc(text):
    """提取手动触发的完整说明（用于辅助窗右侧展示）"""
    # 优先取「使用 / 用法 / 触发 / Usage / Trigger」等章节正文
    m = re.search(
        r"^#{1,4}\s*(?:使用|用法|触发|如何使用|怎么用|如何触发|Usage|Trigger|Trigger\s*Instructions)[^\n]*\n(.*?)(?=^#{1,4}\s|\Z)",
        text, re.M | re.I | re.S)
    if m and m.group(1).strip():
        return m.group(1).strip()[:800]
    # 回退：包含 trigger / 手动 / 在聊天 关键词的正文片段
    m = re.search(r"(?:grill me|grill-me|trigger|手动|在聊天|输入)[^\n]{0,80}", text, re.I)
    if m:
        start = max(0, m.start() - 120)
        return text[start:m.end() + 300].strip()[:800]
    return ""


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
        m = re.search(r"^name\s*:\s*(.*)$", body, re.M)
        if m:
            first = m.group(1).strip()
            if first in ("|", ">", "|-", ">-"):
                name = _first_block_line(body[m.end():]) or name
            else:
                name = first.strip("\"'")
        desc = _parse_desc(body)
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

    trigger_doc = _extract_trigger_doc(text)
    has_manual = (bool(trigger) or bool(trigger_doc)
                  or "trigger" in text.lower()
                  or ("手动" in text and "触发" in text))
    return SkillInfo(name=name, description=desc, path=path, root=root,
                     trigger=trigger, trigger_doc=trigger_doc,
                     has_manual_trigger=has_manual)


def _parse_desc(body):
    """解析 frontmatter 中的 description：支持块标量（> 折叠 / | 字面量）与单行"""
    m = re.search(r"^description\s*:\s*(.*)$", body, re.M | re.I)
    if not m:
        return ""
    first = m.group(1).strip()
    # 块标量：>、|、>-、|- 后跟缩进行
    if first in (">", "|", ">-", ">- ", "|-", "|- ", ">+", "|+"):
        indent = None
        lines = []
        for ln in body[m.end():].splitlines():
            if not ln.strip():
                lines.append("")
                continue
            cur = len(ln) - len(ln.lstrip(" "))
            if indent is None:
                indent = cur
            if cur < indent:
                break
            lines.append(ln[indent:])
        joined = " ".join(x.strip() for x in lines) if first.startswith(">") else "\n".join(x for x in lines)
        return joined.strip().strip("\"'")
    return first.strip("\"'")


def _first_block_line(body_tail):
    """块标量取首个非空缩进行"""
    for ln in body_tail.splitlines():
        s = ln.strip()
        if s and not s.startswith("#"):
            return s.strip("\"'")
    return ""


# ── Skills 分类（按包前缀 + 来源目录）───────────────
_DESIGN_SKILLS = {
    "animate", "animation-vocabulary", "apple-design", "emil-design-eng",
    "find-animation-opportunities", "improve-animations", "prototype",
    "review-animations", "pick-ui-library", "ui-ux-pro-max",
}
_DEV_SKILLS = {
    "caveman", "claudefloat-dev", "create-skills", "find-skills",
    "grill-me", "grill-with-docs", "karpathy-guidelines", "review-agent",
    "skill-creator", "skill-installer", "plugin-creator", "template-creator",
    "openai-docs", "visualize", "workspace-organizer", "agentfloat-skills-translator",
}


def _skill_key(name):
    """去掉插件前缀（如 latex:latex-compile → latex）用于规则匹配"""
    return (name or "").strip().split(":")[0].lower()


def _root_has(root, *parts):
    """根路径是否包含指定段（统一正斜杠比较）"""
    r = (root or "").replace("\\", "/").lower()
    return any("/%s/" % p.strip("/") in r for p in parts)


def categorize_skills(skills):
    """把 skill 列表按默认类分组。

    返回有序列表 [(category, [SkillInfo, ...]), ...]。
    规则顺序即优先级：Godot → Firecrawl → 办公文档 → 浏览器 → 设计动画
    → Codex 系统 → 开发辅助 → 其他。
    插件类 skill 的 frontmatter name 可能不带插件前缀（如 excel-live-control），
    因此同时按「名称前缀」与「来源根路径」匹配。
    """
    order = [
        "Godot 游戏开发", "网页抓取", "办公文档", "浏览器自动化",
        "设计 / 动画", "Codex 系统", "开发辅助", "其他",
    ]
    cats = {k: [] for k in order}

    for s in skills:
        key = _skill_key(s.name)
        root = s.root or ""
        if key.startswith("godot-"):
            cats["Godot 游戏开发"].append(s)
        elif key.startswith("firecrawl"):
            cats["网页抓取"].append(s)
        elif key.startswith(("latex", "spreadsheets", "presentations", "documents", "pdf")) or                 _root_has(root, "latex", "spreadsheets", "documents", "presentations", "pdf"):
            cats["办公文档"].append(s)
        elif key.startswith(("browser", "agent-browser")) or _root_has(root, "browser"):
            cats["浏览器自动化"].append(s)
        elif s.name in _DESIGN_SKILLS or key.startswith(("animate", "animation", "apple", "emil",
                                                         "find-animation", "improve-anim", "review-anim",
                                                         "pick-ui", "ui-ux", "prototype")):
            cats["设计 / 动画"].append(s)
        elif ".system" in root.replace("\\", "/"):
            cats["Codex 系统"].append(s)
        elif s.name in _DEV_SKILLS or key.startswith(("skill-", "create-", "find-", "karpathy",
                                                      "review-", "plugin-", "template-",
                                                      "grill", "caveman", "claudefloat", "workspace")):
            cats["开发辅助"].append(s)
        else:
            cats["其他"].append(s)

    return [(cat, cats[cat]) for cat in order if cats[cat]]
