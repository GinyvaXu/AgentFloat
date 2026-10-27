# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skill 车间数据模型（C 线 · C2）

设计约束（对应风暴稿 §3.C）：
- **一个条目 = 仓库来源 + 多个安装副本**：``SkillEntry.installed`` 按 Agent/root
  记录版本、commit、备份与 installId，避免「一个 Skill 装到三个 Agent」被拆成三张卡。
- **固定 commit**：远程来源必须记录安装时的完整 commit，不允许把 ``HEAD`` 当作版本。
- **逐 Agent 独立事务**：``InstallPlan`` 每个目标单独状态、单独重试、单独回滚，
  整体结果允许 ``已安装 2/3`` 这种部分成功。

本模块只放纯数据与状态机，不读写文件、不联网，便于单测。
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import re
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

#: 默认安装目标（Agent/客户端 → skills 根目录）
_DEFAULT_TARGETS = (
    ("codex", "Codex CLI", (".codex", "skills")),
    ("claude", "Claude Code", (".claude", "skills")),
    ("opencode", "OpenCode", (".config", "opencode", "skills")),
    ("agents", "通用 Agents", (".agents", "skills")),
)

#: 安装目标状态
TARGET_PENDING = "pending"
TARGET_INSTALLING = "installing"
TARGET_DONE = "done"
TARGET_ERROR = "error"
TARGET_SKIPPED = "skipped"
TARGET_ROLLED_BACK = "rolled_back"

#: 事务整体状态
PLAN_PENDING = "pending"
PLAN_RUNNING = "running"
PLAN_DONE = "done"
PLAN_PARTIAL = "partial"
PLAN_FAILED = "failed"

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")
_WIN_RESERVED = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}


def now_iso() -> str:
    """当前本地时间（秒级 ISO 8601），与已有日志格式保持一致。"""
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "是")
    return default


def slugify(value: str, fallback: str = "skill") -> str:
    """把 Skill 名规范成稳定 slug（用于 entryId，不用于真实目录名）。"""
    raw = str(value or "").strip().lower()
    raw = raw.replace(":", "-").replace("/", "-").replace("\\", "-")
    raw = _SLUG_RE.sub("-", raw).strip("-._")
    return raw[:64] or fallback


def safe_skill_name(name: str) -> bool:
    """目录名白名单：禁止分隔符、``..``、Windows 保留名与尾随点/空格。"""
    value = str(name or "")
    if not value or value in (".", ".."):
        return False
    if len(value) > 64:
        return False
    if any(ch in value for ch in ("/", "\\", "\x00", ":", "*", "?", '"', "<", ">", "|")):
        return False
    if value != value.strip() or value.endswith("."):
        return False
    if value.lower() in _WIN_RESERVED:
        return False
    return True


def canonical_entry_id(source_type: str, name: str, repo: str = "", subpath: str = "") -> str:
    """生成条目标识：远程按仓库+子路径，本地按名称。

    远程条目在不同 Agent 上安装后仍共享同一个 entryId，这是「一个条目 + installed[]」
    能成立的前提。
    """
    repo = (repo or "").strip().strip("/").lower()
    sub = (subpath or "").strip().strip("/")
    if repo:
        base = "github:%s" % repo
        if sub:
            base += ":%s" % sub
        return base
    kind = (source_type or "local").strip().lower() or "local"
    return "%s:%s" % (kind, slugify(name))


def default_targets(home: Optional[str] = None) -> List[Dict[str, Any]]:
    """默认安装目标列表（只描述位置，不创建目录）。"""
    base = os.path.abspath(os.path.expanduser(home or "~"))
    out = []
    for tid, label, parts in _DEFAULT_TARGETS:
        root = os.path.join(base, *parts)
        out.append({
            "id": tid,
            "label": label,
            "root": root,
            "exists": os.path.isdir(root),
        })
    return out


def agent_from_root(root: str) -> str:
    """根据 skills 根目录推断 Agent id（用于本地扫描的来源标注）。"""
    r = (root or "").replace("\\", "/").lower()
    if "/.codex/" in r or r.endswith("/.codex/skills"):
        return "codex"
    if "/.claude/" in r or r.endswith("/.claude/skills"):
        return "claude"
    if "opencode" in r:
        return "opencode"
    if "/.agents/" in r or r.endswith("/.agents/skills"):
        return "agents"
    return "custom"


def agent_label(agent_id: str) -> str:
    return {
        "codex": "Codex CLI",
        "claude": "Claude Code",
        "opencode": "OpenCode",
        "agents": "通用 Agents",
        "custom": "自定义目录",
    }.get(str(agent_id or "").lower(), str(agent_id or "自定义"))


def _slug_source_id(value: str) -> str:
    """生成短的稳定指纹（只用于本地手动 Skill 的分组/ID）。"""
    digest = hashlib.sha1(str(value or "").encode("utf-8")).hexdigest()[:10]
    return digest


@dataclasses.dataclass
class SkillSource:
    """Skill 来源（本地目录 / GitHub 仓库 / 精选列表 / 粘贴 URL）。"""

    type: str = "local"              # local / github / awesome / url / builtin
    repo: str = ""                   # owner/repo
    subpath: str = ""                # 仓库内 Skill 目录
    url: str = ""                    # 可读的网页地址
    commit: str = ""                 # 固定 commit（远程安装必需）
    ref: str = ""                    # 用户粘贴时携带的分支/tag（仅展示）
    license: str = ""
    stars: int = 0
    pushed_at: str = ""
    trust: float = 0.6
    verified: bool = False
    local_path: str = ""             # 本地/暂存目录（API 输出时剔除）

    def to_dict(self, public: bool = True) -> Dict[str, Any]:
        data = {
            "type": self.type or "local",
            "repo": self.repo or "",
            "subpath": self.subpath or "",
            "url": self.url or "",
            "commit": self.commit or "",
            "ref": self.ref or "",
            "license": self.license or "",
            "stars": as_int(self.stars),
            "pushedAt": self.pushed_at or "",
            "trust": round(as_float(self.trust, 0.6), 3),
            "verified": bool(self.verified),
        }
        if not public and self.local_path:
            data["localPath"] = self.local_path
        return data

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SkillSource":
        raw = data if isinstance(data, dict) else {}
        return cls(
            type=str(raw.get("type") or "local"),
            repo=str(raw.get("repo") or ""),
            subpath=str(raw.get("subpath") or ""),
            url=str(raw.get("url") or ""),
            commit=str(raw.get("commit") or ""),
            ref=str(raw.get("ref") or ""),
            license=str(raw.get("license") or ""),
            stars=as_int(raw.get("stars")),
            pushed_at=str(raw.get("pushedAt") or raw.get("pushed_at") or ""),
            trust=as_float(raw.get("trust"), 0.6),
            verified=as_bool(raw.get("verified")),
            local_path=str(raw.get("localPath") or raw.get("local_path") or ""),
        )


@dataclasses.dataclass
class SkillInstall:
    """某个 Agent/root 上的一份已安装副本。"""

    install_id: str
    name: str
    agent: str
    root: str
    path: str
    version: str = ""
    commit: str = ""
    backup: str = ""
    enabled: bool = True
    managed: bool = False
    source_type: str = "local"
    repo: str = ""
    source_known: bool = False
    installed_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "installId": self.install_id,
            "name": self.name,
            "agent": self.agent,
            "agentLabel": agent_label(self.agent),
            "root": self.root,
            "path": self.path,
            "version": self.version or "",
            "commit": self.commit or "",
            "backup": self.backup or "",
            "enabled": bool(self.enabled),
            "managed": bool(self.managed),
            "sourceType": self.source_type or "local",
            "repo": self.repo or "",
            "sourceKnown": bool(self.source_known),
            "installedAt": self.installed_at or "",
            "updatedAt": self.updated_at or "",
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SkillInstall":
        raw = data if isinstance(data, dict) else {}
        return cls(
            install_id=str(raw.get("installId") or raw.get("install_id") or ""),
            name=str(raw.get("name") or ""),
            agent=str(raw.get("agent") or "custom"),
            root=str(raw.get("root") or ""),
            path=str(raw.get("path") or ""),
            version=str(raw.get("version") or ""),
            commit=str(raw.get("commit") or ""),
            backup=str(raw.get("backup") or ""),
            enabled=as_bool(raw.get("enabled"), True),
            managed=as_bool(raw.get("managed")),
            source_type=str(raw.get("sourceType") or raw.get("source_type") or "local"),
            repo=str(raw.get("repo") or ""),
            source_known=as_bool(raw.get("sourceKnown") if "sourceKnown" in raw else raw.get("source_known")),
            installed_at=str(raw.get("installedAt") or raw.get("installed_at") or ""),
            updated_at=str(raw.get("updatedAt") or raw.get("updated_at") or ""),
        )


@dataclasses.dataclass
class SkillEntry:
    """Skill 车间的一个条目：仓库来源 + 多个已安装副本。"""

    entry_id: str
    name: str
    description: str = ""
    category: str = "其他"
    version: str = ""
    trigger: str = ""
    trigger_doc: str = ""
    has_manual_trigger: bool = False
    dependencies: List[str] = dataclasses.field(default_factory=list)
    tags: List[str] = dataclasses.field(default_factory=list)
    source: SkillSource = dataclasses.field(default_factory=SkillSource)
    readme: str = ""
    has_skill_md: bool = True
    score: float = 0.0
    factors: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    installed: List[SkillInstall] = dataclasses.field(default_factory=list)
    update_available: bool = False
    latest_commit: str = ""
    kind: str = "skill"              # skill / mcp / plugin（首版只安装 skill）
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    # ── 派生属性 ────────────────────────────────
    @property
    def installed_count(self) -> int:
        return len(self.installed)

    @property
    def managed(self) -> bool:
        """至少有一个受管副本（AgentFloat 安装的才允许自动更新/卸载）。"""
        return any(i.managed for i in self.installed)

    @property
    def installable(self) -> bool:
        """是否具备安装条件：远程必须固定 commit，本地必须有可用源目录。"""
        if self.kind != "skill" or not self.has_skill_md:
            return False
        src = self.source
        if src.type in ("github", "url", "awesome"):
            return bool(re.fullmatch(r"[0-9a-fA-F]{40}", src.commit or ""))
        if src.local_path and os.path.isdir(src.local_path):
            return True
        return any(os.path.isdir(i.path) for i in self.installed)

    def merge_install(self, install: SkillInstall) -> None:
        """按 installId/path 去重合并安装记录。"""
        for idx, old in enumerate(self.installed):
            if old.install_id and old.install_id == install.install_id:
                self.installed[idx] = install
                return
            if os.path.normcase(os.path.abspath(old.path)) == os.path.normcase(
                    os.path.abspath(install.path)):
                self.installed[idx] = install
                return
        self.installed.append(install)

    def to_dict(self, include_readme: bool = True) -> Dict[str, Any]:
        data = {
            "entryId": self.entry_id,
            "name": self.name,
            "description": self.description or "",
            "category": self.category or "其他",
            "version": self.version or "",
            "trigger": self.trigger or "",
            "triggerDoc": self.trigger_doc or "",
            "hasManualTrigger": bool(self.has_manual_trigger),
            "dependencies": list(self.dependencies or []),
            "tags": list(self.tags or []),
            "source": self.source.to_dict(public=True),
            "hasSkillMd": bool(self.has_skill_md),
            "score": round(as_float(self.score), 1),
            "factors": list(self.factors or []),
            "installed": [i.to_dict() for i in self.installed],
            "installedCount": self.installed_count,
            "managed": self.managed,
            "installable": self.installable,
            "updateAvailable": bool(self.update_available),
            "latestCommit": self.latest_commit or "",
            "kind": self.kind or "skill",
            "extra": dict(self.extra or {}),
        }
        if include_readme:
            data["readme"] = self.readme or ""
        return data

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "SkillEntry":
        raw = data if isinstance(data, dict) else {}
        entry = cls(
            entry_id=str(raw.get("entryId") or raw.get("entry_id") or ""),
            name=str(raw.get("name") or ""),
            description=str(raw.get("description") or ""),
            category=str(raw.get("category") or "其他"),
            version=str(raw.get("version") or ""),
            trigger=str(raw.get("trigger") or ""),
            trigger_doc=str(raw.get("triggerDoc") or raw.get("trigger_doc") or ""),
            has_manual_trigger=as_bool(raw.get("hasManualTrigger") if "hasManualTrigger" in raw
                                      else raw.get("has_manual_trigger")),
            dependencies=[str(x) for x in (raw.get("dependencies") or []) if str(x).strip()],
            tags=[str(x) for x in (raw.get("tags") or []) if str(x).strip()],
            source=SkillSource.from_dict(raw.get("source")),
            readme=str(raw.get("readme") or ""),
            has_skill_md=as_bool(raw.get("hasSkillMd") if "hasSkillMd" in raw else raw.get("has_skill_md"), True),
            score=as_float(raw.get("score")),
            factors=[f for f in (raw.get("factors") or []) if isinstance(f, dict)],
            installed=[SkillInstall.from_dict(i) for i in (raw.get("installed") or [])
                       if isinstance(i, dict)],
            update_available=as_bool(raw.get("updateAvailable") if "updateAvailable" in raw
                                     else raw.get("update_available")),
            latest_commit=str(raw.get("latestCommit") or raw.get("latest_commit") or ""),
            kind=str(raw.get("kind") or "skill"),
            extra=dict(raw.get("extra") or {}) if isinstance(raw.get("extra"), dict) else {},
        )
        return entry


@dataclasses.dataclass
class InstallTarget:
    """安装事务中的单个目标。"""

    agent: str
    root: str
    label: str = ""
    status: str = TARGET_PENDING
    install_id: str = ""
    path: str = ""
    backup: str = ""
    error: str = ""
    error_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "label": self.label or agent_label(self.agent),
            "root": self.root,
            "status": self.status,
            "installId": self.install_id or "",
            "path": self.path or "",
            "backup": self.backup or "",
            "error": self.error or "",
            "errorCode": self.error_code or "",
        }


@dataclasses.dataclass
class InstallPlan:
    """逐 Agent 独立安装事务状态机。

    状态流转::

        pending → installing → done
                          ↘ error（可 retry 回 pending）
        完成后整体: done（全部成功）/ partial（部分成功）/ failed（全部失败）

    ``rollback_target`` 只回滚单个已成功目标，不牵连其他目标。
    """

    entry_id: str
    name: str
    commit: str = ""
    action: str = "install"          # install / update
    targets: List[InstallTarget] = dataclasses.field(default_factory=list)
    state: str = PLAN_PENDING
    message: str = ""
    warnings: List[str] = dataclasses.field(default_factory=list)

    @classmethod
    def build(cls, entry_id: str, name: str, targets: List[Dict[str, Any]],
              commit: str = "", action: str = "install") -> "InstallPlan":
        items = []
        for t in targets or []:
            items.append(InstallTarget(
                agent=str(t.get("id") or t.get("agent") or "custom"),
                root=str(t.get("root") or ""),
                label=str(t.get("label") or ""),
            ))
        return cls(entry_id=entry_id, name=name, commit=commit, action=action, targets=items)

    def _target(self, agent: str) -> Optional[InstallTarget]:
        for t in self.targets:
            if t.agent == agent:
                return t
        return None

    def begin(self, agent: str) -> bool:
        t = self._target(agent)
        if t is None or t.status not in (TARGET_PENDING, TARGET_ERROR):
            return False
        t.status = TARGET_INSTALLING
        t.error = ""
        t.error_code = ""
        self.state = PLAN_RUNNING
        return True

    def complete(self, agent: str, install_id: str = "", path: str = "",
                 backup: str = "") -> bool:
        t = self._target(agent)
        if t is None:
            return False
        t.status = TARGET_DONE
        t.install_id = install_id or t.install_id
        t.path = path or t.path
        t.backup = backup or t.backup
        t.error = ""
        t.error_code = ""
        self._refresh()
        return True

    def fail(self, agent: str, error: str, code: str = "") -> bool:
        t = self._target(agent)
        if t is None:
            return False
        t.status = TARGET_ERROR
        t.error = str(error or "安装失败")
        t.error_code = str(code or "")
        self._refresh()
        return True

    def retry(self, agent: str) -> bool:
        t = self._target(agent)
        if t is None or t.status not in (TARGET_ERROR, TARGET_SKIPPED):
            return False
        t.status = TARGET_PENDING
        t.error = ""
        t.error_code = ""
        self.state = PLAN_PARTIAL if self._done_count() else PLAN_PENDING
        return True

    def rollback_target(self, agent: str) -> bool:
        t = self._target(agent)
        if t is None or t.status != TARGET_DONE:
            return False
        t.status = TARGET_ROLLED_BACK
        self._refresh()
        return True

    def skip(self, agent: str, reason: str = "") -> bool:
        t = self._target(agent)
        if t is None:
            return False
        t.status = TARGET_SKIPPED
        t.error = str(reason or "")
        t.error_code = "skipped"
        self._refresh()
        return True

    def _done_count(self) -> int:
        return sum(1 for t in self.targets if t.status == TARGET_DONE)

    def _failed_count(self) -> int:
        return sum(1 for t in self.targets if t.status == TARGET_ERROR)

    def _refresh(self) -> None:
        total = len(self.targets)
        done = self._done_count()
        failed = self._failed_count()
        pending = sum(1 for t in self.targets if t.status in (TARGET_PENDING, TARGET_INSTALLING))
        rolled = sum(1 for t in self.targets if t.status == TARGET_ROLLED_BACK)
        if total == 0:
            self.state = PLAN_FAILED
            self.message = "没有可用的安装目标"
        elif done == total:
            self.state = PLAN_DONE
            self.message = "已安装 %d/%d" % (done, total)
        elif done and (failed or pending or rolled):
            self.state = PLAN_PARTIAL
            self.message = "已安装 %d/%d" % (done, total)
        elif failed and not done and not pending:
            self.state = PLAN_FAILED
            self.message = "安装失败 0/%d" % total
        elif pending and not done and not failed:
            self.state = PLAN_RUNNING if any(
                t.status == TARGET_INSTALLING for t in self.targets) else PLAN_PENDING
            self.message = "等待安装 0/%d" % total
        elif rolled and not done and not failed and not pending:
            self.state = PLAN_PARTIAL
            self.message = "已回滚 0/%d" % total
        else:
            self.state = PLAN_PARTIAL
            self.message = "已安装 %d/%d" % (done, total)

    def summary(self) -> str:
        return self.message or ("已安装 %d/%d" % (self._done_count(), len(self.targets)))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.state in (PLAN_DONE, PLAN_PARTIAL),
            "entryId": self.entry_id,
            "name": self.name,
            "commit": self.commit or "",
            "action": self.action,
            "state": self.state,
            "message": self.summary(),
            "summary": self.summary(),
            "counts": {
                "total": len(self.targets),
                "done": self._done_count(),
                "failed": self._failed_count(),
                "pending": sum(1 for t in self.targets
                               if t.status in (TARGET_PENDING, TARGET_INSTALLING)),
                "rolledBack": sum(1 for t in self.targets if t.status == TARGET_ROLLED_BACK),
            },
            "targets": [t.to_dict() for t in self.targets],
            "warnings": list(self.warnings or []),
        }
