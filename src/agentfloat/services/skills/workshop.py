# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skill 车间服务层（C 线 · C2）

把「扫描 / 发现 / 安装 / 启停 / 更新 / 卸载」收口到一个无 Qt 依赖的服务：

- ``list_entries``：已安装 / 发现 / 周榜 / 更新四个分页；
- ``get_entry``：详情 + README（按需联网）；
- ``install``：逐 Agent 独立事务，部分成功保留、失败目标可单独重试/回滚；
- ``update``：只对 AgentFloat 受管副本生效，先备份再覆盖；
- ``uninstall``：先备份再移入应用回收站；
- ``set_enabled``：只对受管副本生效，重命名 SKILL.md 实现可逆启停。

手动安装（无 ``.agentfloat-skill.json``）的 Skill 也会出现在「已安装」，
但只读展示、不允许自动更新/卸载 —— 对应 C2「管理所有 Skill，来源未知只手动处理」。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import Any, Dict, Iterable, List, Optional, Tuple

from agentfloat.services.skills import discovery, installer, metadata, scanner, scoring
from agentfloat.services.skills.models import (
    InstallPlan, SCHEMA_VERSION, SkillEntry, SkillInstall,
    default_targets, now_iso, slugify,
)

CACHE_NAME = "index.json"


class SkillWorkshopError(Exception):
    def __init__(self, code: str, message: str, detail: str = ""):
        super().__init__(message)
        self.code = str(code or "skill_error")
        self.message = str(message or "操作失败")
        self.detail = str(detail or "")

    def to_dict(self) -> Dict[str, str]:
        return {"code": self.code, "error": self.message, "detail": self.detail}


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
        old = path + ".bak"
        if os.path.exists(path):
            try:
                os.replace(path, old)
            except OSError:
                pass
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _normalize_roots(roots: Optional[Iterable[str]]) -> List[str]:
    out = []
    seen = set()
    for root in roots or []:
        text = str(root or "").strip()
        if not text:
            continue
        path = os.path.abspath(os.path.expandvars(os.path.expanduser(text)))
        key = os.path.normcase(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class SkillWorkshop(object):
    """Skill 车间服务门面。默认数据目录在 AgentFloat 配置目录下。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None,
                 roots: Optional[Iterable[str]] = None,
                 home: Optional[str] = None,
                 data_dir: Optional[str] = None,
                 targets: Optional[List[Dict[str, Any]]] = None,
                 fetcher: Optional[discovery.Fetcher] = None,
                 materializer: Any = None):
        cfg = config if isinstance(config, dict) else {}
        skill_cfg = cfg.get("skills") if isinstance(cfg.get("skills"), dict) else cfg
        configured_roots = roots if roots is not None else (skill_cfg.get("roots") or [])
        self.roots = _normalize_roots(configured_roots) or _normalize_roots(
            scanner.default_skill_roots())
        self.home = os.path.abspath(os.path.expanduser(home or "~"))
        self.data_dir = os.path.abspath(data_dir or os.path.join(
            os.path.dirname(os.path.expanduser("~")), ".agentfloat", "skills_workshop"))
        self.backups_dir = os.path.join(self.data_dir, "backups")
        self.trash_dir = os.path.join(self.data_dir, "trash")
        self.cache_path = os.path.join(self.data_dir, CACHE_NAME)
        self.fetcher = fetcher
        self.materializer = materializer or discovery.materialize
        self.targets = self._build_targets(targets)
        self._cache: Optional[Dict[str, Any]] = None
        self.cache_error = ""

    # ── 配置与缓存 ────────────────────────────────
    def _build_targets(self, targets: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        if targets:
            out = []
            for item in targets:
                if not isinstance(item, dict):
                    continue
                root = str(item.get("root") or "").strip()
                tid = str(item.get("id") or "").strip()
                if not root or not tid:
                    continue
                out.append({
                    "id": tid,
                    "label": str(item.get("label") or tid),
                    "root": os.path.abspath(os.path.expanduser(root)),
                    "exists": os.path.isdir(os.path.expanduser(root)),
                })
            if out:
                return out
        return default_targets(self.home)

    def _load_cache(self) -> Dict[str, Any]:
        if self._cache is not None:
            return self._cache
        data = _read_json(self.cache_path)
        if data is None:
            if os.path.exists(self.cache_path):
                self.cache_error = "本地发现缓存损坏，已按空缓存处理"
            data = {}
        if not isinstance(data.get("modes"), dict):
            data["modes"] = {}
        data.setdefault("schemaVersion", SCHEMA_VERSION)
        data.setdefault("updatedAt", "")
        self._cache = data
        return data

    def _save_cache(self) -> None:
        data = self._load_cache()
        data["schemaVersion"] = SCHEMA_VERSION
        data["updatedAt"] = now_iso()
        try:
            _atomic_write_json(self.cache_path, data)
            self.cache_error = ""
        except OSError as exc:
            self.cache_error = "写入发现缓存失败：%s" % exc

    def cache_info(self) -> Dict[str, Any]:
        data = self._load_cache()
        counts = {}
        for key, value in (data.get("modes") or {}).items():
            counts[key] = len((value or {}).get("entries") or [])
        return {
            "updatedAt": data.get("updatedAt") or "",
            "error": self.cache_error,
            "counts": counts,
        }

    def save_remote_entries(self, entries: List[SkillEntry], mode: str = "search",
                            query: str = "", warnings: Optional[List[str]] = None) -> None:
        """写入/覆盖某一发现路径的缓存（测试与发现层共用）。"""
        data = self._load_cache()
        payload = []
        for entry in entries or []:
            item = entry.to_dict(include_readme=True)
            item["installed"] = []          # 安装副本始终以磁盘标记为准
            payload.append(item)
        data.setdefault("modes", {})[str(mode or "search")] = {
            "fetchedAt": now_iso(),
            "query": str(query or ""),
            "entries": payload,
            "warnings": [str(w) for w in (warnings or [])],
        }
        self._save_cache()

    def _remote_for_modes(self, modes: Iterable[str]) -> List[SkillEntry]:
        data = self._load_cache()
        out: Dict[str, SkillEntry] = {}
        for mode in modes:
            block = (data.get("modes") or {}).get(mode) or {}
            for raw in block.get("entries") or []:
                entry = metadata.entry_from_remote(raw)
                if entry.entry_id:
                    out[entry.entry_id] = entry
        return list(out.values())

    def _all_remote(self) -> List[SkillEntry]:
        data = self._load_cache()
        return self._remote_for_modes(list((data.get("modes") or {}).keys()))

    # ── 本地扫描 ──────────────────────────────────
    def _scan_local(self) -> List[SkillEntry]:
        """扫描全部 skills 根，包含已停用的受管 Skill。"""
        active = scanner.scan_skills(self.roots)
        items: List[Tuple[Any, bool]] = [(info, True) for info in active]
        seen_dirs = {os.path.normcase(os.path.dirname(info.path)) for info in active}
        for root in self.roots:
            for marker in installer.read_installed_markers(root):
                name = str(marker.get("name") or "")
                if not name:
                    continue
                skill_dir = os.path.join(root, name)
                key = os.path.normcase(os.path.abspath(skill_dir))
                if key in seen_dirs:
                    continue
                disabled = os.path.join(skill_dir, "SKILL.md.disabled")
                if os.path.isfile(disabled):
                    info = scanner.parse_skill_md(disabled, root=root)
                    if info.name:
                        items.append((info, False))
                        seen_dirs.add(key)

        cat_by_path: Dict[str, str] = {}
        try:
            for cat, group in scanner.categorize_skills([info for info, _ in items]):
                for info in group:
                    cat_by_path[os.path.normcase(info.path)] = cat
        except Exception:  # noqa: BLE001
            cat_by_path = {}

        grouped: Dict[str, SkillEntry] = {}
        order: List[str] = []
        for info, enabled in items:
            skill_dir = os.path.dirname(info.path)
            marker = metadata.read_marker(skill_dir)
            meta = metadata.parse_skill_metadata(info.path, root=info.root)
            category = meta.get("category") or cat_by_path.get(
                os.path.normcase(info.path), "") or "其他"
            entry = metadata.entry_from_local(info, category=category, marker=marker, meta=meta)
            if not enabled:
                entry.has_skill_md = True
                entry.extra["disabled"] = True
            install = entry.installed[0] if entry.installed else None
            if install is not None and not enabled:
                install.enabled = False
            key = entry.entry_id
            if key not in grouped:
                grouped[key] = entry
                order.append(key)
            else:
                cur = grouped[key]
                if install is not None:
                    cur.merge_install(install)
                if not cur.readme and entry.readme:
                    cur.readme = entry.readme
                if not cur.description and entry.description:
                    cur.description = entry.description
                if entry.extra.get("disabled"):
                    cur.extra["disabled"] = True
        return [grouped[k] for k in order]

    def _installs_by_entry(self, local: List[SkillEntry]) -> Dict[str, List[SkillInstall]]:
        out: Dict[str, List[SkillInstall]] = {}
        for entry in local:
            out.setdefault(entry.entry_id, []).extend(entry.installed)
        return out

    def _decorate_updates(self, local: List[SkillEntry], remote: List[SkillEntry]) -> None:
        remote_by_id = {e.entry_id: e for e in remote}
        for entry in local:
            latest = remote_by_id.get(entry.entry_id)
            if latest is None or not latest.source.commit:
                continue
            entry.latest_commit = latest.source.commit
            if any((i.commit or "") != latest.source.commit for i in entry.installed if i.managed):
                entry.update_available = True
        local_by_id = {e.entry_id: e for e in local}
        for entry in remote:
            installs = (local_by_id.get(entry.entry_id) or entry).installed
            if installs and entry.source.commit:
                entry.update_available = any(
                    (i.commit or "") != entry.source.commit for i in installs if i.managed)

    def _snapshot(self) -> Tuple[List[SkillEntry], List[SkillEntry], List[SkillEntry], Dict[str, Any]]:
        local = self._scan_local()
        all_remote = self._all_remote()
        data = self._load_cache()
        discover_remote = self._remote_for_modes(
            [m for m in ("search", "awesome", "url") if m in (data.get("modes") or {})])
        weekly_remote = self._remote_for_modes(["weekly"])
        self._decorate_updates(local, all_remote)
        remote_by_id = {e.entry_id: e for e in all_remote}
        for entry in discover_remote:
            if entry.entry_id in remote_by_id:
                entry.update_available = remote_by_id[entry.entry_id].update_available
        for entry in weekly_remote:
            if entry.entry_id in remote_by_id:
                entry.update_available = remote_by_id[entry.entry_id].update_available
        updates = [e for e in local if e.update_available]
        seen = {e.entry_id for e in updates}
        for entry in all_remote:
            if entry.update_available and entry.entry_id not in seen:
                updates.append(entry)
                seen.add(entry.entry_id)
        return local, discover_remote, weekly_remote, {
            "allRemote": all_remote,
            "updates": updates,
            "cache": self.cache_info(),
        }

    def _attach_installs(self, entry: SkillEntry, local: List[SkillEntry]) -> SkillEntry:
        for item in local:
            if item.entry_id == entry.entry_id:
                entry.installed = list(item.installed)
                if not entry.readme:
                    entry.readme = item.readme
                break
        return entry

    # ── 列表 / 详情 ────────────────────────────────
    def list_entries(self, tab: str = "installed", query: str = "",
                     category: str = "") -> Dict[str, Any]:
        local, discover_remote, weekly_remote, extra = self._snapshot()
        tab = str(tab or "installed").strip().lower()
        if tab == "discover":
            entries = [self._attach_installs(e, local) for e in discover_remote]
        elif tab == "weekly":
            entries = [self._attach_installs(e, local) for e in weekly_remote]
        elif tab == "updates":
            entries = [self._attach_installs(e, local) for e in extra["updates"]]
        else:
            tab = "installed"
            entries = local

        cat = str(category or "").strip()
        if cat and cat not in ("全部", "all"):
            entries = [e for e in entries if (e.category or "其他") == cat]
        q = str(query or "").strip()
        if q:
            needle = q.lower()
            entries = [e for e in entries if needle in " ".join([
                e.name, e.description, e.category, e.source.repo,
                " ".join(e.tags or []),
            ]).lower()]

        if tab in ("discover", "weekly", "updates"):
            entries = scoring.rank_entries(entries, query=q)
        else:
            entries.sort(key=lambda e: (e.name or "").lower())

        categories = sorted({(e.category or "其他") for e in (local + discover_remote + weekly_remote)})
        counts = {
            "installed": len(local),
            "discover": len(discover_remote),
            "weekly": len(weekly_remote),
            "updates": len(extra["updates"]),
        }
        return {
            "ok": True,
            "tab": tab,
            "query": q,
            "category": cat,
            "total": len(entries),
            "entries": [e.to_dict(include_readme=False) for e in entries],
            "categories": categories,
            "targets": self.targets_payload(),
            "counts": counts,
            "cache": extra["cache"],
        }

    def get_entry(self, entry_id: str, fetch_readme: bool = False) -> Dict[str, Any]:
        eid = str(entry_id or "").strip()
        if not eid:
            raise SkillWorkshopError("entry_missing", "缺少条目 ID")
        local = self._scan_local()
        remote = self._all_remote()
        self._decorate_updates(local, remote)
        found = None
        for entry in local + remote:
            if entry.entry_id == eid:
                found = entry
                break
        if found is None:
            raise SkillWorkshopError("entry_not_found", "找不到该 Skill 条目（可能已从缓存移除）")
        found = self._attach_installs(found, local)
        if fetch_readme and not found.readme and found.source.repo:
            try:
                found.readme = discovery.read_readme(found, self.fetcher)
            except discovery.SourceError as exc:
                found.extra["readmeError"] = exc.message
        return {"ok": True, "entry": found.to_dict(include_readme=True),
                "targets": self.targets_payload()}

    # ── 发现 ─────────────────────────────────────
    def refresh_discovery(self, mode: str = "search", query: str = "",
                          limit: int = 12, subpath: str = "", ref: str = "") -> Dict[str, Any]:
        mode = str(mode or "search").strip().lower()
        if mode not in ("search", "weekly", "awesome", "url"):
            raise SkillWorkshopError("mode_invalid", "不支持的发现方式：%s" % mode)
        try:
            result = discovery.discover(query=query, mode=mode, limit=limit,
                                        fetcher=self.fetcher, subpath=subpath, ref=ref)
        except discovery.SourceError as exc:
            return {"ok": False, "code": exc.code, "error": exc.message,
                    "detail": exc.detail, "cache": self.cache_info()}
        entries = result.get("entries") or []
        self.save_remote_entries(entries, mode=mode, query=query,
                                 warnings=result.get("warnings") or [])
        ranked = scoring.rank_entries(entries, query=query if mode != "url" else "")
        return {
            "ok": True,
            "mode": mode,
            "total": len(ranked),
            "entries": [e.to_dict(include_readme=False) for e in ranked],
            "warnings": result.get("warnings") or [],
            "sources": result.get("sources") or [],
            "cache": self.cache_info(),
        }

    # ── 目标选择 ──────────────────────────────────
    def targets_payload(self) -> List[Dict[str, Any]]:
        local = self._scan_local()
        counts: Dict[str, int] = {}
        for entry in local:
            for inst in entry.installed:
                counts[inst.agent] = counts.get(inst.agent, 0) + 1
        out = []
        for item in self.targets:
            row = dict(item)
            row["exists"] = os.path.isdir(row["root"])
            row["installed"] = counts.get(row["id"], 0)
            out.append(row)
        return out

    def _select_targets(self, target_ids: Optional[Iterable[str]]) -> List[Dict[str, Any]]:
        by_id = {t["id"]: t for t in self.targets}
        if target_ids is None:
            selected = [t for t in self.targets if os.path.isdir(t["root"])]
            if not selected:
                selected = []
        else:
            ids = [str(x).strip() for x in target_ids if str(x).strip()]
            unknown = [x for x in ids if x not in by_id]
            if unknown:
                raise SkillWorkshopError("target_unknown", "未知安装目标：%s" % "、".join(unknown))
            selected = [by_id[x] for x in dict.fromkeys(ids)]
        if not selected:
            raise SkillWorkshopError(
                "target_missing",
                "没有可用的安装目标：请先选择至少一个 Agent（Codex / Claude Code / OpenCode / 通用 Agents）",
            )
        allowed = [self.home, self.data_dir] + [t["root"] for t in self.targets] + self.roots
        for item in selected:
            try:
                installer.validate_target_root(item["root"], allowed)
            except installer.SkillInstallError as exc:
                raise SkillWorkshopError(exc.code, exc.message, exc.detail)
        return selected

    def _find_install(self, entry: SkillEntry, agent: str) -> Optional[SkillInstall]:
        for inst in entry.installed:
            if inst.agent == agent:
                return inst
        return None

    def _install_name(self, entry: SkillEntry) -> str:
        for inst in entry.installed:
            if inst.managed and inst.name:
                return inst.name
        if entry.source.subpath:
            name = os.path.basename(entry.source.subpath.rstrip("/"))
            if name and metadata.safe_skill_name(name):
                return name
        name = str(entry.name or "").strip()
        if metadata.safe_skill_name(name):
            return name
        return slugify(name)

    # ── 安装 / 更新 ────────────────────────────────
    def _perform(self, entry: SkillEntry, targets: List[Dict[str, Any]], action: str,
                 source_dir: Optional[str] = None) -> Dict[str, Any]:
        plan = InstallPlan.build(entry.entry_id, entry.name, targets,
                                 commit=entry.source.commit, action=action)
        if entry.kind != "skill" or not entry.has_skill_md:
            msg = "首版只安装 Skill（需包含 SKILL.md）；MCP / 插件请按官方命令手动配置"
            for target in targets:
                plan.fail(target["id"], msg, "not_a_skill")
            return plan.to_dict()

        if entry.source.type in ("github", "url", "awesome") and not discovery.HEX40_RE.match(
                entry.source.commit or ""):
            msg = "远程安装必须固定 commit（不允许装 HEAD）；请刷新条目后重试"
            for target in targets:
                plan.fail(target["id"], msg, "commit_required")
            return plan.to_dict()

        temp = None
        stage = source_dir
        try:
            if not stage:
                temp = tempfile.mkdtemp(prefix="af-skill-", dir=self._ensure_data_dir())
                stage = os.path.join(temp, "source")
                self.materializer(entry, stage, self.fetcher)
            info = installer.inspect_tree(stage)
            plan.warnings.extend(info.warnings)
        except (discovery.SourceError, installer.SkillInstallError) as exc:
            for target in targets:
                plan.fail(target["id"], exc.message, exc.code)
            return self._cleanup_and_return(plan, temp)
        except Exception as exc:  # noqa: BLE001
            for target in targets:
                plan.fail(target["id"], "准备安装源失败：%s" % exc, "source_error")
            return self._cleanup_and_return(plan, temp)

        meta = {
            "entryId": entry.entry_id,
            "sourceType": entry.source.type,
            "repo": entry.source.repo,
            "source": entry.source.to_dict(public=True),
            "version": entry.version,
            "commit": entry.source.commit or "",
        }
        name = self._install_name(entry)
        for target in targets:
            plan.begin(target["id"])
            try:
                result = installer.install_tree(
                    stage, target["root"], name, meta=meta,
                    backups_root=self.backups_dir, entry_id=entry.entry_id)
                plan.complete(target["id"], install_id=result["record"]["installId"],
                              path=result["path"], backup=result.get("backup") or "")
                for warning in result.get("warnings") or []:
                    if warning not in plan.warnings:
                        plan.warnings.append(warning)
            except installer.SkillInstallError as exc:
                plan.fail(target["id"], exc.message, exc.code)
            except Exception as exc:  # noqa: BLE001
                plan.fail(target["id"], "安装异常：%s" % exc, "install_failed")
        return self._cleanup_and_return(plan, temp)

    def _cleanup_and_return(self, plan: InstallPlan, temp: Optional[str]) -> Dict[str, Any]:
        if temp:
            shutil.rmtree(temp, ignore_errors=True)
        payload = plan.to_dict()
        try:
            payload["entry"] = self.get_entry(plan.entry_id).get("entry")
        except SkillWorkshopError:
            payload["entry"] = None
        return payload

    def install(self, entry_id: str, target_ids: Optional[Iterable[str]] = None,
                source_dir: Optional[str] = None) -> Dict[str, Any]:
        entry = self._load_entry(entry_id)
        targets = self._select_targets(target_ids)
        return self._perform(entry, targets, "install", source_dir=source_dir)

    def update(self, entry_id: str, target_ids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        entry = self._load_entry(entry_id)
        managed = [i for i in entry.installed if i.managed]
        if not managed:
            raise SkillWorkshopError(
                "manual_required",
                "该 Skill 不是 AgentFloat 安装（或来源未知），不会自动更新；请手动处理",
            )
        if entry.source.type == "local":
            raise SkillWorkshopError(
                "no_upstream",
                "本地来源的 Skill 没有可检查的上游版本；请重新选择来源后安装",
            )
        targets = self._select_targets(
            target_ids if target_ids is not None else [i.agent for i in managed])
        for target in targets:
            if self._find_install(entry, target["id"]) is None:
                raise SkillWorkshopError(
                    "not_installed",
                    "%s 上没有该 Skill 的受管副本，无法更新" % (
                        target.get("label") or target["id"]),
                )
        return self._perform(entry, targets, "update")

    # ── 启停 / 卸载 / 回滚 ─────────────────────────
    def set_enabled(self, entry_id: str, target_id: str, enabled: bool) -> Dict[str, Any]:
        entry = self._load_entry(entry_id)
        inst = self._find_install(entry, str(target_id or ""))
        if inst is None:
            raise SkillWorkshopError("not_installed", "该目标上没有这个 Skill")
        if not inst.managed:
            raise SkillWorkshopError(
                "manual_required",
                "该 Skill 不是 AgentFloat 安装，来源未知；只读展示，请手动处理",
            )
        result = installer.set_enabled(inst.root, inst.name, bool(enabled))
        return {"ok": True, "enabled": bool(enabled), "entry": self.get_entry(entry_id)["entry"],
                "path": result.get("path") or inst.path}

    def uninstall(self, entry_id: str, target_id: str) -> Dict[str, Any]:
        entry = self._load_entry(entry_id)
        inst = self._find_install(entry, str(target_id or ""))
        if inst is None:
            raise SkillWorkshopError("not_installed", "该目标上没有这个 Skill")
        if not inst.managed:
            raise SkillWorkshopError(
                "manual_required",
                "该 Skill 不是 AgentFloat 安装，来源未知；为避免误删，请在文件管理器中手动处理",
            )
        result = installer.uninstall_tree(inst.root, inst.name, self.backups_dir, self.trash_dir)
        return {"ok": True, "action": "uninstall", "backup": result.get("backup") or "",
                "trash": result.get("trash") or "", "entry": self.get_entry(entry_id)["entry"]}

    def rollback(self, entry_id: str, target_id: str) -> Dict[str, Any]:
        """安装事务的逐 Agent 回滚：备份后移入回收站。"""
        result = self.uninstall(entry_id, target_id)
        result["action"] = "rollback"
        result["message"] = "已回滚该 Agent 上的安装（备份保留在 AgentFloat 数据目录）"
        return result

    # ── Qt / 路径快捷接口 ──────────────────────────
    def install_for_path(self, path: str) -> Optional[Dict[str, Any]]:
        skill_dir = os.path.dirname(os.path.abspath(str(path or "")))
        root = os.path.dirname(skill_dir)
        marker = metadata.read_marker(skill_dir)
        if marker is None:
            return None
        inst = metadata.install_from_marker(marker, skill_dir, root)
        data = inst.to_dict()
        data["entryId"] = str(marker.get("entryId") or "")
        return data

    def set_enabled_for_path(self, path: str, enabled: bool) -> Dict[str, Any]:
        item = self.install_for_path(path)
        if not item:
            raise SkillWorkshopError(
                "manual_required",
                "该 Skill 不是 AgentFloat 安装，来源未知；只读展示，请手动处理",
            )
        return self.set_enabled(item.get("entryId") or "", item["agent"], enabled)

    # ── 内部 ─────────────────────────────────────
    def _ensure_data_dir(self) -> str:
        os.makedirs(self.data_dir, exist_ok=True)
        return self.data_dir

    def _load_entry(self, entry_id: str) -> SkillEntry:
        eid = str(entry_id or "").strip()
        if not eid:
            raise SkillWorkshopError("entry_missing", "缺少条目 ID")
        local = self._scan_local()
        for entry in local:
            if entry.entry_id == eid:
                return entry
        for entry in self._all_remote():
            if entry.entry_id == eid:
                return self._attach_installs(entry, local)
        raise SkillWorkshopError("entry_not_found", "找不到该 Skill 条目（可能已从缓存移除）")


def default_workshop(config: Optional[Dict[str, Any]] = None,
                     home: Optional[str] = None) -> SkillWorkshop:
    """为 Web/Qt 创建默认实例（数据目录在 AgentFloat 配置目录下）。"""
    from agentfloat.core.paths import config_dir
    return SkillWorkshop(config=config, home=home,
                         data_dir=os.path.join(config_dir(), "skills_workshop"))
