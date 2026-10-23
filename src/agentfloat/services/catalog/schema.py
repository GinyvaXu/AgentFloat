# -*- coding: utf-8 -*-
"""AgentFloat — Content Catalog / 数据结构与校验

目录条目按三层来源拼装：``bundled``（随包）< ``remote``（远程目录）< ``user``（本机覆盖）。
本模块只负责「结构定义 + 校验」，不读文件、不发网络请求，方便单测与工具复用。

四条硬规则（HANDOFF-vNext §3.2）：
1. ``platforms`` 是三值枚举 ``native / wsl / none``，不是布尔——Amp 属于「Windows 能装、
   只能在 WSL 跑」，布尔值会误报；
2. 一个产品一条记录，版本差异放 ``launch.variants[]``；
3. ``status`` 三态：``active / deprecated / eol``（eol 禁止启动，只留迁移说明）；
4. ``verifiedAt`` 超 90 天只在 UI 标黄，校验层不拦。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = 1

#: 分组。顺序即 UI 顺序：国际 CLI → 国内 CLI → 桌面 → WSL 通道
GROUPS = ("intl-cli", "cn-cli", "desktop", "wsl")
GROUP_LABELS = {
    "intl-cli": "国际 CLI",
    "cn-cli": "国内 CLI",
    "desktop": "桌面 IDE",
    "wsl": "WSL 通道",
}
GROUP_ORDER = {name: i for i, name in enumerate(GROUPS)}

PLATFORMS = ("windows", "macos", "linux")
PLATFORM_SUPPORT = ("native", "wsl", "none")

#: 安装方式。winget 优先 → 官方脚本 → npm / pip（风暴稿「winget 覆盖度高于预期」的结论）
INSTALL_TYPES = ("winget", "npm", "pip", "script", "download")
PACKAGE_INSTALL_TYPES = ("winget", "npm", "pip")
URL_INSTALL_TYPES = ("script", "download")

LAUNCH_MODES = ("interactive", "headless", "desktop", "web")
STATUSES = ("active", "deprecated", "eol")

#: 稳定层：只能随包发布，远程目录不许改（供应链防护，见 verify.py 的字段白名单）
STABLE_FIELDS = (
    "schemaVersion", "id", "name", "vendor", "group", "icon", "description", "platforms",
)
#: 易变层：远程目录可覆盖（安装方式 / 命令名 / headless / 版本区间 / 状态）
VOLATILE_FIELDS = (
    "install", "launch", "capability", "health", "status", "statusNote",
    "verifiedAt", "source", "supersedes", "supersededBy", "statusCheckedAt",
)
KNOWN_FIELDS = STABLE_FIELDS + VOLATILE_FIELDS

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.\-]+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STALE_DAYS = 90


class CatalogError(ValueError):
    """目录条目非法。``errors`` 保留全部问题，便于工具一次性报全。"""

    def __init__(self, subject: str, errors: Sequence[str]):
        self.subject = subject
        self.errors = list(errors)
        super().__init__("%s: %s" % (subject, "; ".join(self.errors)))


# ── 小工具 ──────────────────────────────────────────
def semver_key(value: str) -> Optional[Tuple[int, int, int]]:
    """把 ``1.2.3`` 解析成可比较元组；非法返回 None（预发布后缀忽略）。"""
    m = SEMVER_RE.match(str(value or "").strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return bool(value)


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(v) for v in value if str(v).strip()]


def _parse_date(value: str) -> Optional[date]:
    text = str(value or "").strip()
    if not DATE_RE.match(text):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


# ── 子结构 ──────────────────────────────────────────
@dataclass
class InstallStep:
    type: str
    package_or_url: str
    verify: str = ""
    reversible: bool = True
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"type": self.type, "packageOrUrl": self.package_or_url}
        if self.verify:
            out["verify"] = self.verify
        if not self.reversible:
            out["reversible"] = False
        if self.note:
            out["note"] = self.note
        return out

    @classmethod
    def from_dict(cls, data: Any, errors: List[str], where: str = "install[?]") -> "InstallStep":
        if not isinstance(data, dict):
            errors.append("%s 必须是对象" % where)
            return cls(type="", package_or_url="")
        step_type = str(data.get("type") or "").strip()
        if step_type not in INSTALL_TYPES:
            errors.append("%s.type=%r 不在 %s 内" % (where, step_type, "/".join(INSTALL_TYPES)))
        # 兼容两种写法：packageOrUrl（规范）与 url（脚本/下载习惯写法）
        target = data.get("packageOrUrl")
        if target in (None, ""):
            target = data.get("url")
        target = str(target or "").strip()
        if not target:
            errors.append("%s 缺少 packageOrUrl" % where)
        elif step_type in URL_INSTALL_TYPES and not target.startswith(("http://", "https://")):
            errors.append("%s 的 %s 方式必须给 http(s) 地址，实为 %r" % (where, step_type, target))
        reversible = data.get("reversible")
        return cls(
            type=step_type,
            package_or_url=target,
            verify=str(data.get("verify") or ""),
            reversible=True if reversible is None else _as_bool(reversible),
            note=str(data.get("note") or ""),
        )


@dataclass
class Variant:
    id: str
    package: str = ""
    command: str = ""
    min_version: str = ""
    max_version: str = ""
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"id": self.id}
        for key, value in (("package", self.package), ("command", self.command),
                           ("minVersion", self.min_version), ("maxVersion", self.max_version),
                           ("note", self.note)):
            if value:
                out[key] = value
        return out

    @classmethod
    def from_dict(cls, data: Any, errors: List[str], where: str = "launch.variants[]") -> "Variant":
        if not isinstance(data, dict):
            errors.append("%s 必须是对象" % where)
            return cls(id="")
        vid = str(data.get("id") or "").strip()
        if not vid:
            errors.append("%s 缺少 id" % where)
        for key, label in (("minVersion", "minVersion"), ("maxVersion", "maxVersion")):
            raw = data.get(key)
            if raw and not semver_key(raw):
                errors.append("%s.%s=%r 不是合法 semver" % (where, label, raw))
        return cls(
            id=vid,
            package=str(data.get("package") or ""),
            command=str(data.get("command") or ""),
            min_version=str(data.get("minVersion") or ""),
            max_version=str(data.get("maxVersion") or ""),
            note=str(data.get("note") or ""),
        )


@dataclass
class HeadlessSpec:
    args: List[str] = field(default_factory=list)
    verified: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"args": list(self.args), "verified": self.verified}


@dataclass
class LaunchSpec:
    command: str = ""
    modes: List[str] = field(default_factory=lambda: ["interactive"])
    variants: List[Variant] = field(default_factory=list)
    headless: Optional[HeadlessSpec] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"command": self.command, "modes": list(self.modes)}
        if self.variants:
            out["variants"] = [v.to_dict() for v in self.variants]
        if self.headless is not None:
            out["headless"] = self.headless.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: Any, errors: List[str]) -> "LaunchSpec":
        if not isinstance(data, dict):
            errors.append("launch 必须是对象")
            return cls()
        command = str(data.get("command") or "").strip()
        if not command:
            errors.append("launch.command 不能为空")
        modes = _as_str_list(data.get("modes")) or ["interactive"]
        for mode in modes:
            if mode not in LAUNCH_MODES:
                errors.append("launch.modes 含未知模式 %r（可选 %s）" % (mode, "/".join(LAUNCH_MODES)))
        variants = [Variant.from_dict(v, errors, "launch.variants[%d]" % i)
                    for i, v in enumerate(data.get("variants") or [])]
        seen = set()
        for variant in variants:
            if variant.id in seen:
                errors.append("launch.variants 出现重复 id=%r" % variant.id)
            seen.add(variant.id)
        headless = None
        raw_headless = data.get("headless")
        if raw_headless is not None:
            if not isinstance(raw_headless, dict):
                errors.append("launch.headless 必须是对象")
            else:
                headless = HeadlessSpec(
                    args=_as_str_list(raw_headless.get("args")),
                    verified=_as_bool(raw_headless.get("verified")),
                )
        return cls(command=command, modes=modes, variants=variants, headless=headless)


@dataclass
class Capability:
    headless: bool = False
    mcp: bool = False
    skills: bool = False
    resume: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {"headless": self.headless, "mcp": self.mcp, "skills": self.skills, "resume": self.resume}

    @classmethod
    def from_dict(cls, data: Any, errors: List[str]) -> "Capability":
        if data is None:
            return cls()
        if not isinstance(data, dict):
            errors.append("capability 必须是对象")
            return cls()
        unknown = set(data) - set(cls.to_dict_keys())
        for key in sorted(unknown):
            errors.append("capability 含未知字段 %r" % key)
        return cls(
            headless=_as_bool(data.get("headless")),
            mcp=_as_bool(data.get("mcp")),
            skills=_as_bool(data.get("skills")),
            resume=_as_bool(data.get("resume")),
        )

    @staticmethod
    def to_dict_keys() -> Tuple[str, ...]:
        return ("headless", "mcp", "skills", "resume")


@dataclass
class HealthSpec:
    version_cmd: str = ""
    version_pattern: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        if self.version_cmd:
            out["versionCmd"] = self.version_cmd
        if self.version_pattern:
            out["versionPattern"] = self.version_pattern
        return out

    @classmethod
    def from_dict(cls, data: Any, errors: List[str]) -> "HealthSpec":
        if data is None:
            return cls()
        if not isinstance(data, dict):
            errors.append("health 必须是对象")
            return cls()
        pattern = str(data.get("versionPattern") or "")
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                errors.append("health.versionPattern 不是合法正则：%s" % exc)
        return cls(version_cmd=str(data.get("versionCmd") or ""), version_pattern=pattern)


# ── 主结构 ──────────────────────────────────────────
@dataclass
class AgentSpec:
    id: str
    name: str
    group: str
    vendor: str = ""
    schema_version: int = SCHEMA_VERSION
    platforms: Dict[str, str] = field(default_factory=dict)
    install: List[InstallStep] = field(default_factory=list)
    launch: LaunchSpec = field(default_factory=LaunchSpec)
    capability: Capability = field(default_factory=Capability)
    health: HealthSpec = field(default_factory=HealthSpec)
    status: str = "active"
    status_note: str = ""
    verified_at: str = ""
    source: str = ""
    icon: str = ""
    description: str = ""
    supersedes: List[str] = field(default_factory=list)
    superseded_by: str = ""

    # ── 派生属性 ────────────────────────────────
    def support(self, platform: str = "windows") -> str:
        return self.platforms.get(platform, "none")

    def runs_on(self, platform: str = "windows") -> bool:
        return self.support(platform) in ("native", "wsl")

    def is_stale(self, today: Optional[date] = None, days: int = STALE_DAYS) -> bool:
        """``verifiedAt`` 超过 days 天（默认 90）→ UI 标黄。无日期不算过期。"""
        parsed = _parse_date(self.verified_at)
        if parsed is None:
            return False
        return ((today or date.today()) - parsed).days > days

    def primary_install(self, platform: str = "windows") -> Optional[InstallStep]:
        """按「winget 优先 → 官方脚本 → npm / pip」挑一条主安装方式。"""
        order = {name: i for i, name in enumerate(INSTALL_TYPES)}
        candidates = [s for s in self.install if s.type in INSTALL_TYPES]
        if not candidates:
            return None
        return sorted(candidates, key=lambda s: order.get(s.type, 99))[0]

    # ── 序列化 ──────────────────────────────────
    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "id": self.id,
            "name": self.name,
            "group": self.group,
        }
        if self.vendor:
            out["vendor"] = self.vendor
        if self.platforms:
            out["platforms"] = dict(self.platforms)
        if self.install:
            out["install"] = [step.to_dict() for step in self.install]
        out["launch"] = self.launch.to_dict()
        out["capability"] = self.capability.to_dict()
        if self.health.version_cmd or self.health.version_pattern:
            out["health"] = self.health.to_dict()
        out["status"] = self.status
        if self.status_note:
            out["statusNote"] = self.status_note
        if self.verified_at:
            out["verifiedAt"] = self.verified_at
        if self.source:
            out["source"] = self.source
        if self.icon:
            out["icon"] = self.icon
        if self.description:
            out["description"] = self.description
        if self.supersedes:
            out["supersedes"] = list(self.supersedes)
        if self.superseded_by:
            out["supersededBy"] = self.superseded_by
        return out

    @classmethod
    def from_dict(cls, data: Any, *, strict_unknown: bool = True) -> "AgentSpec":
        """校验并构造；非法时抛 :class:`CatalogError`（errors 列全部问题）。"""
        if not isinstance(data, dict):
            raise CatalogError("<unknown>", ["条目必须是对象"])
        errors: List[str] = []
        agent_id = str(data.get("id") or "").strip()
        subject = agent_id or "<missing-id>"

        version = data.get("schemaVersion", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            errors.append("schemaVersion=%r 不受支持（本机支持 %d）" % (version, SCHEMA_VERSION))

        if not agent_id:
            errors.append("缺少 id")
        elif not ID_RE.match(agent_id):
            errors.append("id=%r 只允许小写字母/数字/连字符" % agent_id)

        name = str(data.get("name") or "").strip()
        if not name:
            errors.append("缺少 name")

        group = str(data.get("group") or "").strip()
        if group not in GROUPS:
            errors.append("group=%r 不在 %s 内" % (group, "/".join(GROUPS)))

        # platforms：三值枚举；键必须是已知平台
        platforms: Dict[str, str] = {}
        raw_platforms = data.get("platforms")
        if raw_platforms is None:
            platforms = {p: "native" for p in PLATFORMS}
        elif not isinstance(raw_platforms, dict):
            errors.append("platforms 必须是对象（%s）" % "/".join(PLATFORM_SUPPORT))
        else:
            for key, value in raw_platforms.items():
                if key not in PLATFORMS:
                    errors.append("platforms 含未知平台 %r" % key)
                    continue
                if value not in PLATFORM_SUPPORT:
                    errors.append("platforms.%s=%r 只能是 %s" % (key, value, "/".join(PLATFORM_SUPPORT)))
                    continue
                platforms[key] = value
            for key in PLATFORMS:
                platforms.setdefault(key, "none")

        install_raw = data.get("install") or []
        if not isinstance(install_raw, list):
            errors.append("install 必须是数组")
            install_raw = []
        install = [InstallStep.from_dict(step, errors, "install[%d]" % i)
                   for i, step in enumerate(install_raw)]
        if not install:
            errors.append("install 至少给一条安装方式")

        launch_raw = data.get("launch")
        if launch_raw is None:
            errors.append("缺少 launch")
            launch = LaunchSpec()
        else:
            launch = LaunchSpec.from_dict(launch_raw, errors)

        capability = Capability.from_dict(data.get("capability"), errors)
        health = HealthSpec.from_dict(data.get("health"), errors)

        status = str(data.get("status") or "active").strip()
        if status not in STATUSES:
            errors.append("status=%r 只能是 %s" % (status, "/".join(STATUSES)))
        status_note = str(data.get("statusNote") or "")
        if status == "eol" and not status_note:
            errors.append("status=eol 时必须写 statusNote（迁移说明）")

        verified_at = str(data.get("verifiedAt") or "")
        if verified_at and _parse_date(verified_at) is None:
            errors.append("verifiedAt=%r 需为 YYYY-MM-DD" % verified_at)

        source = str(data.get("source") or "")
        if source and not source.startswith(("http://", "https://")):
            errors.append("source 需为 http(s) 地址，实为 %r" % source)

        supersedes = _as_str_list(data.get("supersedes"))
        for old_id in supersedes:
            if not ID_RE.match(old_id):
                errors.append("supersedes 含非法 id %r" % old_id)
        superseded_by = str(data.get("supersededBy") or "")
        if superseded_by and not ID_RE.match(superseded_by):
            errors.append("supersededBy=%r 不是合法 id" % superseded_by)

        if strict_unknown:
            for key in sorted(set(data) - set(KNOWN_FIELDS)):
                errors.append("未知字段 %r（拼写错误？）" % key)

        if errors:
            raise CatalogError(subject, errors)

        return cls(
            id=agent_id,
            name=name,
            group=group,
            vendor=str(data.get("vendor") or ""),
            schema_version=SCHEMA_VERSION,
            platforms=platforms,
            install=install,
            launch=launch,
            capability=capability,
            health=health,
            status=status,
            status_note=status_note,
            verified_at=verified_at,
            source=source,
            icon=str(data.get("icon") or ""),
            description=str(data.get("description") or ""),
            supersedes=supersedes,
            superseded_by=superseded_by,
        )


# ── 清单（manifest） ────────────────────────────────
@dataclass
class ShardRef:
    name: str
    sha256: str
    group: str = ""
    count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"name": self.name, "sha256": self.sha256}
        if self.group:
            out["group"] = self.group
        if self.count:
            out["count"] = self.count
        return out

    @classmethod
    def from_dict(cls, data: Any, errors: List[str], where: str) -> "ShardRef":
        if not isinstance(data, dict):
            errors.append("%s 必须是对象" % where)
            return cls(name="", sha256="")
        name = str(data.get("name") or "").strip()
        if not re.match(r"^[A-Za-z0-9._-]+\.json$", name):
            errors.append("%s.name=%r 只允许安全文件名（*.json）" % (where, name))
        digest = str(data.get("sha256") or "").strip().lower()
        if not re.match(r"^[0-9a-f]{64}$", digest):
            errors.append("%s.sha256 需为 64 位十六进制" % where)
        group = str(data.get("group") or "")
        if group and group not in GROUPS:
            errors.append("%s.group=%r 不在 %s 内" % (where, group, "/".join(GROUPS)))
        try:
            count = int(data.get("count") or 0)
        except (TypeError, ValueError):
            errors.append("%s.count 需为整数" % where)
            count = 0
        return cls(name=name, sha256=digest, group=group, count=count)


@dataclass
class CatalogManifest:
    catalog_version: int = 0
    schema_version: int = SCHEMA_VERSION
    min_af_version: str = ""
    channel: str = "beta"
    published_at: str = ""
    shards: List[ShardRef] = field(default_factory=list)
    mirrors: List[str] = field(default_factory=list)
    signature: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "schemaVersion": self.schema_version,
            "catalogVersion": self.catalog_version,
            "channel": self.channel,
            "shards": [s.to_dict() for s in self.shards],
        }
        if self.min_af_version:
            out["minAfVersion"] = self.min_af_version
        if self.published_at:
            out["publishedAt"] = self.published_at
        if self.mirrors:
            out["mirrors"] = list(self.mirrors)
        if self.signature:
            out["signature"] = self.signature
        return out

    @classmethod
    def from_dict(cls, data: Any, *, require_signature: bool = False) -> "CatalogManifest":
        if not isinstance(data, dict):
            raise CatalogError("<manifest>", ["manifest 必须是对象"])
        errors: List[str] = []
        try:
            catalog_version = int(data.get("catalogVersion"))
        except (TypeError, ValueError):
            catalog_version = 0
            errors.append("catalogVersion 需为整数")
        if catalog_version < 1:
            errors.append("catalogVersion 必须 >= 1（单调递增）")

        schema_version = data.get("schemaVersion", SCHEMA_VERSION)
        if schema_version != SCHEMA_VERSION:
            errors.append("schemaVersion=%r 不受支持" % (schema_version,))

        min_af = str(data.get("minAfVersion") or "")
        if min_af and not semver_key(min_af):
            errors.append("minAfVersion=%r 不是合法 semver" % min_af)

        shards_raw = data.get("shards") or []
        if not isinstance(shards_raw, list) or not shards_raw:
            errors.append("shards 至少给一项")
            shards_raw = []
        shards = [ShardRef.from_dict(item, errors, "shards[%d]" % i)
                  for i, item in enumerate(shards_raw)]

        mirrors = _as_str_list(data.get("mirrors"))
        for url in mirrors:
            if not url.startswith(("http://", "https://")):
                errors.append("mirrors 含非 http(s) 地址 %r" % url)

        signature = str(data.get("signature") or "")
        if require_signature and not signature:
            errors.append("缺少 signature（正式渠道必须签名）")

        if errors:
            raise CatalogError("<manifest>", errors)

        return cls(
            catalog_version=catalog_version,
            schema_version=SCHEMA_VERSION,
            min_af_version=min_af,
            channel=str(data.get("channel") or "beta"),
            published_at=str(data.get("publishedAt") or ""),
            shards=shards,
            mirrors=mirrors,
            signature=signature,
        )


def validate_agents(items: Iterable[Any], *, strict_unknown: bool = True) -> Tuple[List[AgentSpec], List[Tuple[str, str]]]:
    """批量校验：返回 (合法条目, [(id, 原因)])。

    单条非法只丢该条，不影响整份目录（风暴稿「失败逐条降级」）。
    """
    valid: List[AgentSpec] = []
    dropped: List[Tuple[str, str]] = []
    seen: Dict[str, int] = {}
    for item in items:
        raw_id = ""
        if isinstance(item, dict):
            raw_id = str(item.get("id") or "")
        try:
            spec = AgentSpec.from_dict(item, strict_unknown=strict_unknown)
        except CatalogError as exc:
            dropped.append((raw_id or "<unknown>", str(exc)))
            continue
        if spec.id in seen:
            dropped.append((spec.id, "重复 id（第 %d 条）" % (seen[spec.id] + 1)))
            continue
        seen[spec.id] = len(valid)
        valid.append(spec)
    return valid, dropped
