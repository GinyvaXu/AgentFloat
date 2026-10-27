# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skill 安装/更新/卸载文件事务

安全底线（对应 C1 / G3）：
1. **预览 + 固定 commit + 暂存校验**：远程条目必须带 40 位 commit；先复制到同目录
   暂存区并校验（SKILL.md、路径穿越、符号链接、体积/数量上限），再原子换入；
2. **备份 + 回滚**：覆盖前先完整备份；换入失败自动恢复旧目录；卸载先备份再移入
   应用回收站，不静默删除；
3. **不静默覆盖用户已有 Skill**：目标目录没有 AgentFloat 安装标记时直接拒绝；
4. **默认不执行仓库脚本**：本模块只做文件复制与校验，从不调用子进程。
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import shutil
import time
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from agentfloat.services.skills.metadata import MARKER_NAME, read_marker, write_marker
from agentfloat.services.skills.models import (
    SCHEMA_VERSION, agent_from_root, now_iso, safe_skill_name,
)

MAX_FILES = 300
MAX_TOTAL_BYTES = 40 * 1024 * 1024
MAX_SINGLE_BYTES = 8 * 1024 * 1024
MAX_SKILL_MD_BYTES = 2 * 1024 * 1024
IGNORED_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".idea", ".vscode"}
IGNORED_FILES = {".DS_Store", "Thumbs.db"}
RISKY_EXT = {".exe", ".dll", ".bat", ".cmd", ".ps1", ".msi", ".scr", ".lnk", ".vbs"}


class SkillInstallError(Exception):
    """带稳定错误码的安装异常，供 Web/UI 显示可操作的中文提示。"""

    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = str(code or "skill_error")
        self.message = str(message or "操作失败")
        self.detail = str(detail or "")

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "error": self.message, "detail": self.detail}


@dataclasses.dataclass
class TreeInfo:
    files: List[Tuple[str, int]]
    total_bytes: int
    digest: str
    warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "files": len(self.files),
            "bytes": self.total_bytes,
            "digest": self.digest,
            "warnings": list(self.warnings),
        }


# ── 路径校验 ─────────────────────────────────────────
def is_within(base: str, path: str) -> bool:
    """路径是否位于 base 内（解析符号链接后比较，防目录逃逸）。"""
    try:
        b = os.path.normcase(os.path.realpath(os.path.abspath(base)))
        p = os.path.normcase(os.path.realpath(os.path.abspath(path)))
    except (OSError, ValueError):
        return False
    if p == b:
        return True
    return p.startswith(b + os.sep)


def validate_target_root(root: str, allowed_roots: Optional[Iterable[str]] = None) -> str:
    """校验安装根目录：必须是绝对路径，且落在允许的根内。"""
    text = str(root or "").strip()
    if not text:
        raise SkillInstallError("target_invalid", "安装目标为空")
    if not os.path.isabs(text):
        raise SkillInstallError("target_invalid", "安装目标必须是绝对路径")
    normalized = os.path.abspath(os.path.expanduser(text))
    if normalized != os.path.abspath(text):
        raise SkillInstallError("target_invalid", "安装目标包含非法路径片段")
    allowed = list(allowed_roots or [])
    if allowed and not any(is_within(a, normalized) for a in allowed):
        raise SkillInstallError("target_not_allowed", "安装目标不在允许的目录内")
    return normalized


def safe_join(root: str, name: str) -> str:
    """拼出 Skill 目录并阻断 ``..`` / 分隔符 / 保留名。"""
    if not safe_skill_name(name):
        raise SkillInstallError(
            "name_invalid",
            "Skill 名称不合法：不能包含路径分隔符、``..`` 或 Windows 保留名",
        )
    dest = os.path.abspath(os.path.join(root, name))
    if not is_within(root, dest) or os.path.dirname(dest) != os.path.abspath(root):
        raise SkillInstallError("name_invalid", "Skill 名称导致目录逃逸")
    return dest


def _safe_rel_path(rel: str) -> str:
    """校验仓库内相对路径（资源文件允许中文/空格，但禁止穿越与 ADS）。"""
    text = str(rel or "").replace("\\", "/").strip("/")
    if not text:
        raise SkillInstallError("unsafe_path", "仓库包含空路径")
    parts = text.split("/")
    for part in parts:
        if part in ("", ".", ".."):
            raise SkillInstallError("unsafe_path", "仓库路径包含 ``..`` 或空段")
        if len(part) > 180:
            raise SkillInstallError("unsafe_path", "仓库文件名过长")
        if any(ord(ch) < 32 for ch in part):
            raise SkillInstallError("unsafe_path", "仓库文件名包含控制字符")
        if part != part.rstrip(" ."):
            raise SkillInstallError("unsafe_path", "仓库文件名以点或空格结尾")
        if ":" in part:
            raise SkillInstallError("unsafe_path", "仓库文件名包含非法字符")
        if part.lower().split(".")[0] in (
                "con", "prn", "aux", "nul", "com1", "com2", "com3", "com4",
                "com5", "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3",
                "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9"):
            raise SkillInstallError("unsafe_path", "仓库文件名是 Windows 保留名")
    return "/".join(parts)


# ── 源目录校验 ───────────────────────────────────────
def inspect_tree(src: str) -> TreeInfo:
    """校验待安装目录并返回文件清单/哈希/风险提示（不跟随符号链接）。"""
    source = os.path.abspath(str(src or ""))
    if not os.path.isdir(source):
        raise SkillInstallError("source_missing", "安装源目录不存在")
    skill_md = os.path.join(source, "SKILL.md")
    if not os.path.isfile(skill_md):
        raise SkillInstallError("skill_md_missing", "安装源根目录缺少 SKILL.md，未识别为 Skill")
    try:
        if os.path.getsize(skill_md) > MAX_SKILL_MD_BYTES:
            raise SkillInstallError("skill_md_too_large", "SKILL.md 超过 2MB，拒绝安装")
    except OSError as exc:
        raise SkillInstallError("source_unreadable", "SKILL.md 无法读取：%s" % exc)

    files: List[Tuple[str, int]] = []
    total = 0
    warnings: List[str] = []
    hasher = hashlib.sha256()

    for dirpath, dirnames, filenames in os.walk(source, topdown=True, followlinks=False):
        for d in list(dirnames):
            full = os.path.join(dirpath, d)
            if os.path.islink(full):
                raise SkillInstallError("symlink_blocked", "安装源包含符号链接，已拒绝：%s" % d)
            if d in IGNORED_DIRS:
                dirnames.remove(d)
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            if os.path.islink(full):
                raise SkillInstallError("symlink_blocked", "安装源包含符号链接，已拒绝：%s" % fn)
            if fn == MARKER_NAME or fn in IGNORED_FILES:
                continue
            rel = os.path.relpath(full, source).replace("\\", "/")
            rel = _safe_rel_path(rel)
            try:
                size = os.path.getsize(full)
            except OSError as exc:
                raise SkillInstallError("source_unreadable", "文件无法读取：%s（%s）" % (rel, exc))
            if size > MAX_SINGLE_BYTES:
                raise SkillInstallError("file_too_large", "单个文件超过 8MB：%s" % rel)
            total += size
            if total > MAX_TOTAL_BYTES:
                raise SkillInstallError("source_too_large", "Skill 总大小超过 40MB")
            if len(files) >= MAX_FILES:
                raise SkillInstallError("too_many_files", "Skill 文件数超过 %d 个" % MAX_FILES)
            ext = os.path.splitext(fn)[1].lower()
            if ext in RISKY_EXT:
                warnings.append("包含可执行/脚本文件 %s（不会被自动执行）" % rel)
            files.append((rel, size))
            hasher.update(rel.encode("utf-8"))
            hasher.update(b"\0")
            try:
                with open(full, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1024 * 256), b""):
                        hasher.update(chunk)
            except OSError as exc:
                raise SkillInstallError("source_unreadable", "文件无法读取：%s（%s）" % (rel, exc))
    if not files:
        raise SkillInstallError("source_empty", "安装源没有可复制文件")
    return TreeInfo(files=files, total_bytes=total, digest=hasher.hexdigest(), warnings=warnings)


def _copy_tree(src: str, dst: str) -> None:
    """复制目录（过滤缓存/标记），符号链接已在 inspect_tree 阶段拒绝。"""
    ignore = shutil.ignore_patterns(*IGNORED_DIRS, *IGNORED_FILES, MARKER_NAME)
    shutil.copytree(src, dst, ignore=ignore, symlinks=False)


def _remove_tree(path: str) -> None:
    if path and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)


def _stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def backup_dir(src: str, backups_root: str, install_id: str,
               stamp: Optional[str] = None) -> str:
    """把已有 Skill 完整备份到应用目录；失败则抛异常（调用方不得继续覆盖）。"""
    source = os.path.abspath(src)
    if not os.path.isdir(source):
        raise SkillInstallError("backup_source_missing", "待备份目录不存在")
    target = os.path.join(backups_root, install_id or "unknown", stamp or _stamp())
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copytree(source, target, symlinks=True)
    except OSError as exc:
        raise SkillInstallError("backup_failed", "备份失败，已中止操作：%s" % exc)
    return target


# ── 安装 / 更新 ──────────────────────────────────────
def _build_marker(meta: Dict[str, Any], install_id: str, name: str, target_root: str,
                  backup: str, digest: str, installed_at: str = "") -> Dict[str, Any]:
    source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "installId": install_id,
        "entryId": str(meta.get("entryId") or ""),
        "name": name,
        "agent": str(meta.get("agent") or agent_from_root(target_root)),
        "root": target_root,
        "sourceType": str(meta.get("sourceType") or source.get("type") or "local"),
        "repo": str(meta.get("repo") or source.get("repo") or ""),
        "source": source,
        "version": str(meta.get("version") or ""),
        "commit": str(meta.get("commit") or source.get("commit") or ""),
        "backup": backup or "",
        "enabled": True,
        "managed": True,
        "filesHash": digest,
        "installedAt": installed_at or now_iso(),
        "updatedAt": now_iso(),
    }


def install_tree(src: str, target_root: str, name: str, meta: Optional[Dict[str, Any]] = None,
                 backups_root: str = "", entry_id: str = "") -> Dict[str, Any]:
    """把 ``src`` 安装到 ``target_root/name``。

    - 目标不存在：直接安装；
    - 目标存在且有受管标记：先备份再更新；
    - 目标存在但无标记 / 属于别的条目：拒绝，绝不静默覆盖。
    """
    meta = dict(meta or {})
    source = os.path.abspath(str(src or ""))
    root = validate_target_root(target_root)
    os.makedirs(root, exist_ok=True)
    dest = safe_join(root, name)
    info = inspect_tree(source)

    if os.path.exists(dest) and (os.path.islink(dest) or not os.path.isdir(dest)):
        raise SkillInstallError(
            "target_exists",
            "目标路径已存在且不是普通目录（可能是文件或链接），已停止",
        )
    marker = read_marker(dest) if os.path.isdir(dest) else None
    exists = os.path.isdir(dest)
    if exists and marker is None:
        raise SkillInstallError(
            "target_exists",
            "目标目录已存在同名 Skill 且不是 AgentFloat 安装；为防覆盖已停止。请手动备份/删除后再试。",
        )
    if marker is not None:
        if not marker.get("managed"):
            raise SkillInstallError("target_exists", "目标不是 AgentFloat 受管 Skill，已停止")
        old_entry = str(marker.get("entryId") or "")
        if old_entry and entry_id and old_entry != entry_id:
            raise SkillInstallError(
                "target_conflict",
                "目标目录已安装另一个 Skill（%s），未覆盖" % (marker.get("name") or "未知"),
            )
        if not backups_root:
            raise SkillInstallError("backup_required", "更新已有 Skill 必须先配置备份目录")

    backup = ""
    install_id = str((marker or {}).get("installId") or ("af-" + uuid.uuid4().hex[:12]))
    installed_at = str((marker or {}).get("installedAt") or "")
    if exists:
        backup = backup_dir(dest, backups_root, install_id)
        action = "update"
    else:
        action = "install"

    stage = os.path.join(root, ".agentfloat-staging-%s" % uuid.uuid4().hex[:10])
    old = os.path.join(root, ".agentfloat-old-%s" % uuid.uuid4().hex[:10])
    try:
        _copy_tree(source, stage)
        marker_data = _build_marker(meta, install_id, name, root, backup, info.digest,
                                    installed_at=installed_at)
        marker_data["entryId"] = entry_id or marker_data.get("entryId") or ""
        write_marker(stage, marker_data)
        if exists:
            os.replace(dest, old)
        try:
            os.replace(stage, dest)
        except Exception:
            if os.path.isdir(old) and not os.path.isdir(dest):
                os.replace(old, dest)         # 自动回滚
            raise
        _remove_tree(old)
        return {
            "ok": True,
            "action": action,
            "path": dest,
            "backup": backup,
            "warnings": info.warnings,
            "digest": info.digest,
            "record": marker_data,
        }
    except SkillInstallError:
        _remove_tree(stage)
        raise
    except Exception as exc:  # noqa: BLE001
        _remove_tree(stage)
        if os.path.isdir(old) and not os.path.isdir(dest):
            try:
                os.replace(old, dest)
            except OSError:
                pass
        raise SkillInstallError("install_failed", "写入失败，已回滚：%s" % exc)


# ── 启停 ────────────────────────────────────────────
def set_enabled(target_root: str, name: str, enabled: bool) -> Dict[str, Any]:
    """启停受管 Skill：通过重命名 SKILL.md 实现，可逆且对全部 Agent 生效。"""
    root = validate_target_root(target_root)
    dest = safe_join(root, name)
    marker = read_marker(dest)
    if marker is None or not marker.get("managed"):
        raise SkillInstallError(
            "manual_required",
            "该 Skill 不是 AgentFloat 安装，来源未知；只读展示，请手动处理",
        )
    active = os.path.join(dest, "SKILL.md")
    disabled = os.path.join(dest, "SKILL.md.disabled")
    if enabled:
        if os.path.isfile(active):
            pass
        elif os.path.isfile(disabled):
            os.replace(disabled, active)
        else:
            raise SkillInstallError("skill_md_missing", "目录内找不到 SKILL.md，无法启用")
    else:
        if os.path.isfile(active):
            os.replace(active, disabled)
        elif os.path.isfile(disabled):
            pass
        else:
            raise SkillInstallError("skill_md_missing", "目录内找不到 SKILL.md，无法停用")
    marker["enabled"] = bool(enabled)
    marker["updatedAt"] = now_iso()
    write_marker(dest, marker)
    return {"ok": True, "path": dest, "enabled": bool(enabled), "record": marker}


# ── 卸载 / 回滚 ─────────────────────────────────────
def uninstall_tree(target_root: str, name: str, backups_root: str,
                   trash_root: str) -> Dict[str, Any]:
    """卸载受管 Skill：先备份，再移入回收站（不删除用户文件）。"""
    root = validate_target_root(target_root)
    dest = safe_join(root, name)
    marker = read_marker(dest)
    if marker is None or not marker.get("managed"):
        raise SkillInstallError(
            "manual_required",
            "该 Skill 不是 AgentFloat 安装，来源未知；只读展示，请手动处理",
        )
    if not backups_root or not trash_root:
        raise SkillInstallError("trash_required", "卸载需要备份目录与回收站目录")
    backup = backup_dir(dest, backups_root, str(marker.get("installId") or "unknown"))
    os.makedirs(trash_root, exist_ok=True)
    trash_dest = os.path.join(trash_root, "%s-%s" % (_stamp(), name))
    try:
        shutil.move(dest, trash_dest)
    except OSError as exc:
        raise SkillInstallError("uninstall_failed", "移入回收站失败，原目录未删除：%s" % exc)
    return {
        "ok": True,
        "path": dest,
        "backup": backup,
        "trash": trash_dest,
        "message": "已卸载并移入 AgentFloat 回收站（可手动恢复）",
    }


def read_installed_markers(root: str) -> List[Dict[str, Any]]:
    """扫描一个根目录下的受管标记（包含已停用的 Skill）。"""
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        marker = read_marker(path)
        if marker is not None:
            out.append(marker)
    return out


def cleanup_staging(root: str) -> int:
    """清理崩溃残留的 ``.agentfloat-staging-*``（只动本模块前缀）。"""
    removed = 0
    try:
        names = os.listdir(root)
    except OSError:
        return 0
    for name in names:
        if name.startswith(".agentfloat-staging-") or name.startswith(".agentfloat-old-"):
            _remove_tree(os.path.join(root, name))
            removed += 1
    return removed
