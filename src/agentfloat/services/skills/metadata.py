# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skill 元数据规范化

把扫描器解析出的 ``SkillInfo`` 与 SKILL.md frontmatter 合成统一条目：
来源（本地/远程）、分类、版本、触发方式、依赖、许可证、标签。

实现原则：
- 不引入 YAML 依赖，只支持 Agent Skills 实际常见的 frontmatter 子集；
- 任何字段坏掉都降级为空，不阻塞扫描；
- 安装标记 ``.agentfloat-skill.json`` 是「受管副本」的唯一凭据。
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from typing import Any, Dict, Iterable, List, Optional

from agentfloat.services.skills import scanner
from agentfloat.services.skills.models import (
    SCHEMA_VERSION, SkillEntry, SkillInstall, SkillSource, agent_from_root,
    as_bool, canonical_entry_id, now_iso, safe_skill_name, slugify,
)

MARKER_NAME = ".agentfloat-skill.json"
MAX_README_BYTES = 120 * 1024

_FM_RE = re.compile(r"\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)", re.S)
_BLOCK_SCALAR = (">", "|", ">-", ">- ", "|-", "|- ", ">+", "|+", ">+ ", "|+ ")


# ── frontmatter 解析 ─────────────────────────────────
def _strip_quotes(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def _parse_inline_list(value: str) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    items = []
    buf = ""
    quote = ""
    for ch in text:
        if quote:
            buf += ch
            if ch == quote:
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
            buf += ch
            continue
        if ch in (",", "，"):
            items.append(buf)
            buf = ""
            continue
        buf += ch
    if buf.strip():
        items.append(buf)
    return [_strip_quotes(x) for x in items if _strip_quotes(x)]


def _collect_block(lines: List[str], start: int, base_indent: int) -> (List[str], int):
    """收集缩进大于 base_indent 的块，返回 (去掉公共缩进的文本行, 下一个下标)。"""
    raw = []
    idx = start
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            raw.append("")
            idx += 1
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent <= base_indent:
            break
        raw.append(line)
        idx += 1
    if not raw:
        return [], idx
    # 以第一个非空行的缩进为基准
    base = None
    for line in raw:
        if line.strip():
            base = len(line) - len(line.lstrip(" "))
            break
    base = base if base is not None else base_indent + 2
    out = []
    for line in raw:
        if not line.strip():
            out.append("")
        else:
            out.append(line[base:] if len(line) >= base else line.lstrip(" "))
    return out, idx


def parse_frontmatter(text: str) -> Dict[str, Any]:
    """解析 SKILL.md 顶部 frontmatter（支持标量/块列表/块标量/一层 metadata）。"""
    m = _FM_RE.match(text or "")
    if not m:
        return {}
    lines = m.group(1).splitlines()
    data: Dict[str, Any] = {}
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if not line.strip() or line.lstrip().startswith("#"):
            idx += 1
            continue
        km = re.match(r"^([A-Za-z0-9_.-]+)\s*:\s*(.*)$", line)
        if not km:
            idx += 1
            continue
        key = km.group(1).strip().lower()
        value = km.group(2).strip()
        base_indent = len(line) - len(line.lstrip(" "))
        # 块标量
        if value in _BLOCK_SCALAR:
            block, idx = _collect_block(lines, idx + 1, base_indent)
            if value.startswith(">"):
                joined = " ".join(x.strip() for x in block if x.strip())
            else:
                joined = "\n".join(block).strip("\n")
            data[key] = joined.strip()
            continue
        # 空值：可能是块列表或嵌套 metadata
        if value == "":
            block, idx = _collect_block(lines, idx + 1, base_indent)
            if not block:
                data[key] = ""
                continue
            items = []
            nested: Dict[str, Any] = {}
            is_list = True
            for b in block:
                s = b.strip()
                if not s:
                    continue
                lm = re.match(r"^-\s*(.*)$", s)
                if lm:
                    items.append(_strip_quotes(lm.group(1)))
                else:
                    is_list = False
                    nm = re.match(r"^([A-Za-z0-9_.-]+)\s*:\s*(.*)$", s)
                    if nm:
                        nested[nm.group(1).lower()] = _strip_quotes(nm.group(2))
            if is_list and items:
                data[key] = items
            elif nested:
                data[key] = nested
            else:
                data[key] = "\n".join(x.strip() for x in block).strip()
            continue
        # 行内列表
        if value.startswith("[") and value.endswith("]"):
            data[key] = _parse_inline_list(value)
        else:
            data[key] = _strip_quotes(value)
        idx += 1
    return data


def _fm_get(fm: Dict[str, Any], *keys: str) -> Any:
    """读取 frontmatter 字段，支持 ``metadata.version`` 这类一层嵌套。"""
    for key in keys:
        if key in fm and fm[key] not in ("", None):
            return fm[key]
        if "." in key:
            head, tail = key.split(".", 1)
            nested = fm.get(head)
            if isinstance(nested, dict) and nested.get(tail) not in ("", None):
                return nested.get(tail)
    return None


def normalize_dependencies(value: Any) -> List[str]:
    """依赖统一为字符串列表：支持列表、逗号/分号分隔、``name@version`` 写法。"""
    if value is None:
        return []
    if isinstance(value, dict):
        raw: Iterable[Any] = value.keys()
    elif isinstance(value, (list, tuple, set)):
        raw = value
    else:
        raw = re.split(r"[,;\n]+", str(value))
    out: List[str] = []
    seen = set()
    for item in raw:
        text = _strip_quotes(str(item or "")).strip()
        text = text.lstrip("-").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text[:120])
    return out


def _read_text(path: str, limit: int = MAX_README_BYTES) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def read_skill_body(path: str) -> str:
    """读取 SKILL.md 正文（去掉 frontmatter），限制长度。"""
    text = _read_text(path)
    m = _FM_RE.match(text)
    if m:
        text = text[m.end():]
    return text.strip()


def read_readme(skill_dir: str) -> str:
    """优先 README.md，回退 SKILL.md 正文，供 Web 详情页只读展示。"""
    for name in ("README.md", "README.MD", "readme.md"):
        path = os.path.join(skill_dir, name)
        if os.path.isfile(path):
            text = _read_text(path)
            if text.strip():
                return text
    for name in ("SKILL.md", "SKILL.md.disabled"):
        path = os.path.join(skill_dir, name)
        if os.path.isfile(path):
            body = read_skill_body(path)
            if body.strip():
                return body
    return ""


def _guess_trigger(text: str) -> str:
    """从正文中猜一个短触发指令（只用于展示，不参与执行）。"""
    m = re.search(r"(?:触发指令|使用方式|触发方式|Usage|Trigger)\s*[:：]?\s*`([^`\n]{1,40})`",
                  text or "", re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"^\s*[-*]\s*(?:输入|在聊天(?:框|中)?输入)\s*`([^`\n]{1,40})`",
                  text or "", re.M)
    return m.group(1).strip() if m else ""


def metadata_from_text(text: str, name_hint: str = "", root: str = "",
                       category: str = "") -> Dict[str, Any]:
    """从 SKILL.md 文本直接提取元数据（发现层下载后使用，不落盘）。"""
    raw = text or ""
    fm = parse_frontmatter(raw)
    body = raw
    m = _FM_RE.match(raw)
    if m:
        body = raw[m.end():]
    name = str(_fm_get(fm, "name") or name_hint or "").strip()
    description = str(_fm_get(fm, "description") or "").strip()
    if not description:
        for line in body.splitlines():
            s = line.strip().lstrip("#").strip()
            if s and not s.startswith(("---", "```", "|")):
                description = s[:300]
                break
    raw_tags = _fm_get(fm, "tags", "keywords", "metadata.tags")
    if isinstance(raw_tags, (list, tuple)):
        tags = [str(x).strip() for x in raw_tags if str(x).strip()]
    else:
        tags = _parse_inline_list(raw_tags or "")
    trigger = str(_fm_get(fm, "trigger", "usage") or "").strip() or _guess_trigger(body)
    return {
        "name": name,
        "description": description,
        "version": str(_fm_get(fm, "version", "metadata.version") or "").strip(),
        "category": category or str(_fm_get(fm, "category", "metadata.category") or "").strip(),
        "license": str(_fm_get(fm, "license", "metadata.license") or "").strip(),
        "dependencies": normalize_dependencies(_fm_get(
            fm, "dependencies", "requires", "requirements",
            "metadata.dependencies", "metadata.requires")),
        "tags": tags,
        "trigger": trigger[:80],
        "trigger_doc": scanner._extract_trigger_doc(body) if hasattr(
            scanner, "_extract_trigger_doc") else "",
        "has_manual_trigger": bool(trigger or "trigger" in body.lower()),
        "skill_dir": "",
        "root": root,
    }


def parse_skill_metadata(skill_md_path: str, root: str = "") -> Dict[str, Any]:
    """解析单个 SKILL.md 的规范化元数据（不联网、不写文件）。"""
    info = scanner.parse_skill_md(skill_md_path, root=root)
    text = _read_text(skill_md_path)
    fm = parse_frontmatter(text)
    name = str(info.name or _fm_get(fm, "name") or os.path.basename(
        os.path.dirname(skill_md_path)) or "").strip()
    description = str(info.description or _fm_get(fm, "description") or "").strip()
    version = str(_fm_get(fm, "version", "metadata.version") or "").strip()
    category = str(_fm_get(fm, "category", "metadata.category") or "").strip()
    license_name = str(_fm_get(fm, "license", "metadata.license") or "").strip()
    deps = normalize_dependencies(_fm_get(
        fm, "dependencies", "requires", "requirements",
        "metadata.dependencies", "metadata.requires"))
    raw_tags = _fm_get(fm, "tags", "keywords", "metadata.tags")
    if isinstance(raw_tags, (list, tuple)):
        tags = [str(x).strip() for x in raw_tags if str(x).strip()]
    else:
        tags = _parse_inline_list(raw_tags or "")
    return {
        "name": name,
        "description": description,
        "version": version,
        "category": category,
        "license": license_name,
        "dependencies": deps,
        "tags": tags,
        "trigger": info.trigger or "",
        "trigger_doc": info.trigger_doc or "",
        "has_manual_trigger": bool(info.has_manual_trigger),
        "skill_dir": os.path.dirname(skill_md_path),
        "root": root,
    }


# ── 安装标记 ─────────────────────────────────────────
def marker_path(skill_dir: str) -> str:
    return os.path.join(skill_dir, MARKER_NAME)


def read_marker(skill_dir: str) -> Optional[Dict[str, Any]]:
    """读取受管标记；损坏/非对象返回 None（按手动 Skill 处理，绝不猜测）。"""
    path = marker_path(skill_dir)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get("schemaVersion") or "") not in ("", str(SCHEMA_VERSION)):
        return None
    if not data.get("installId") or not data.get("name"):
        return None
    return data


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".af-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def write_marker(skill_dir: str, record: Dict[str, Any]) -> str:
    """原子写入安装标记。"""
    path = marker_path(skill_dir)
    _atomic_write_json(path, record)
    return path


def install_from_marker(marker: Dict[str, Any], skill_dir: str, root: str) -> SkillInstall:
    """把标记转换成安装副本记录。"""
    source = SkillSource.from_dict(marker.get("source"))
    return SkillInstall(
        install_id=str(marker.get("installId") or ""),
        name=str(marker.get("name") or os.path.basename(skill_dir)),
        agent=str(marker.get("agent") or agent_from_root(root)),
        root=root or str(marker.get("root") or ""),
        path=skill_dir,
        version=str(marker.get("version") or ""),
        commit=str(marker.get("commit") or source.commit or ""),
        backup=str(marker.get("backup") or ""),
        enabled=as_bool(marker.get("enabled"), True),
        managed=True,
        source_type=str(marker.get("sourceType") or source.type or "local"),
        repo=str(marker.get("repo") or source.repo or ""),
        source_known=bool(marker.get("installId")),
        installed_at=str(marker.get("installedAt") or ""),
        updated_at=str(marker.get("updatedAt") or ""),
    )


def local_install_from_scan(info: Any, root: str, marker: Optional[Dict[str, Any]] = None) -> SkillInstall:
    """从扫描结果生成安装副本；无标记 → 手动安装（只读管理）。"""
    if marker:
        return install_from_marker(marker, os.path.dirname(info.path), root)
    return SkillInstall(
        install_id="manual-%s" % slugify(info.name)[:40],
        name=info.name,
        agent=agent_from_root(root),
        root=root,
        path=os.path.dirname(info.path),
        version="",
        commit="",
        backup="",
        enabled=True,
        managed=False,
        source_type="local",
        repo="",
        source_known=False,
        installed_at="",
        updated_at="",
    )


# ── 条目构造 ─────────────────────────────────────────
def entry_from_local(info: Any, category: str = "", marker: Optional[Dict[str, Any]] = None,
                     meta: Optional[Dict[str, Any]] = None) -> SkillEntry:
    """把扫描到的 SkillInfo 规范化成 SkillEntry（兼容旧 scan_skills）。"""
    skill_dir = os.path.dirname(info.path)
    root = info.root or ""
    if meta is None:
        meta = parse_skill_metadata(info.path, root=root)
    install = local_install_from_scan(info, root, marker)
    source = SkillSource.from_dict((marker or {}).get("source"))
    if not source.repo:
        source.type = "local"
        source.local_path = skill_dir
        source.trust = 1.0
    entry_id = str((marker or {}).get("entryId") or "").strip()
    if not entry_id:
        entry_id = canonical_entry_id(source.type, info.name, repo=source.repo,
                                      subpath=source.subpath)
    version = str(install.version or meta.get("version") or "").strip()
    entry = SkillEntry(
        entry_id=entry_id,
        name=str(info.name or meta.get("name") or os.path.basename(skill_dir)),
        description=str(info.description or meta.get("description") or ""),
        category=category or str(meta.get("category") or "") or "其他",
        version=version,
        trigger=str(info.trigger or ""),
        trigger_doc=str(info.trigger_doc or ""),
        has_manual_trigger=bool(info.has_manual_trigger),
        dependencies=list(meta.get("dependencies") or []),
        tags=list(meta.get("tags") or []),
        source=source,
        readme=read_readme(skill_dir),
        has_skill_md=os.path.isfile(os.path.join(skill_dir, "SKILL.md")),
        installed=[install],
        latest_commit=install.commit or source.commit or "",
    )
    return entry


def entry_from_remote(raw: Dict[str, Any]) -> SkillEntry:
    """把发现层返回的原始字典规范成 SkillEntry，字段缺失不抛异常。"""
    if not isinstance(raw, dict):
        return SkillEntry(entry_id="", name="", has_skill_md=False)
    source = SkillSource.from_dict(raw.get("source"))
    name = str(raw.get("name") or "").strip()
    subpath = source.subpath or str(raw.get("subpath") or "")
    entry_id = str(raw.get("entryId") or "").strip() or canonical_entry_id(
        source.type, name, repo=source.repo, subpath=subpath)
    entry = SkillEntry(
        entry_id=entry_id,
        name=name or os.path.basename(subpath.rstrip("/")),
        description=str(raw.get("description") or "").strip(),
        category=str(raw.get("category") or "其他"),
        version=str(raw.get("version") or ""),
        trigger=str(raw.get("trigger") or ""),
        trigger_doc=str(raw.get("triggerDoc") or raw.get("trigger_doc") or ""),
        has_manual_trigger=as_bool(raw.get("hasManualTrigger") if "hasManualTrigger" in raw
                                  else raw.get("has_manual_trigger")),
        dependencies=normalize_dependencies(raw.get("dependencies")),
        tags=[str(x) for x in (raw.get("tags") or []) if str(x).strip()],
        source=source,
        readme=str(raw.get("readme") or ""),
        has_skill_md=as_bool(raw.get("hasSkillMd") if "hasSkillMd" in raw
                             else raw.get("has_skill_md"), bool(subpath or raw.get("hasSkillMd"))),
        latest_commit=str(raw.get("latestCommit") or source.commit or ""),
        kind=str(raw.get("kind") or "skill"),
        extra=dict(raw.get("extra") or {}) if isinstance(raw.get("extra"), dict) else {},
    )
    if entry.source.type in ("github", "url", "awesome"):
        entry.source.verified = bool(entry.source.verified)
    return entry


def skill_dir_name(info: Any) -> str:
    """扫描结果对应的真实目录名（用于安全校验）。"""
    return os.path.basename(os.path.dirname(getattr(info, "path", "")))


def validate_local_dir(path: str) -> bool:
    """本地目录是否像一个 Skill（根目录有 SKILL.md，名称合法）。"""
    return bool(path and os.path.isdir(path)
                and safe_skill_name(os.path.basename(os.path.abspath(path)))
                and os.path.isfile(os.path.join(path, "SKILL.md")))


def timestamp() -> str:
    return now_iso()
