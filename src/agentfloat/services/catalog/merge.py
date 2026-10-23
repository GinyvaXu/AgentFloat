# -*- coding: utf-8 -*-
"""AgentFloat — Content Catalog / 三层合并

``bundled``（随包，最全）< ``remote``（远程目录，只能改易变层）< ``user``（本机覆盖，优先级最高）。

合并规则（HANDOFF-vNext §3.3 + 风暴稿 A4 结论）：
1. 按 ``id`` 对齐，不做模糊匹配；
2. 远程条目**只能**覆盖 :data:`schema.VOLATILE_FIELDS`；想改名称/图标/分组 → 忽略该字段并留痕；
3. 远程条目不能新增 Agent（新增需要稳定层字段，只能随包发）；
4. 用户条目可以改任意字段（含稳定层），也能新增本机私有 Agent；
5. 单条非法只丢该条，永远保留内置兜底（断网 / 坏合并都不影响启动）。
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .schema import (
    GROUP_ORDER,
    VOLATILE_FIELDS,
    AgentSpec,
    CatalogError,
)

logger = logging.getLogger("AgentFloat.Catalog.Merge")


@dataclass
class MergeResult:
    """合并结果 + 可审计的留痕（谁被覆盖、谁被丢弃、为什么）。"""

    agents: List[AgentSpec] = field(default_factory=list)
    patched: List[str] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    dropped: List[Tuple[str, str]] = field(default_factory=list)
    ignored_fields: List[Tuple[str, str]] = field(default_factory=list)

    def get(self, agent_id: str) -> Optional[AgentSpec]:
        for agent in self.agents:
            if agent.id == agent_id:
                return agent
        return None

    def by_group(self) -> Dict[str, List[AgentSpec]]:
        groups: Dict[str, List[AgentSpec]] = {}
        for agent in self.agents:
            groups.setdefault(agent.group, []).append(agent)
        return groups


def _sort_key(spec: AgentSpec) -> Tuple[int, str]:
    return GROUP_ORDER.get(spec.group, len(GROUP_ORDER)), spec.id


def _as_dicts(items: Optional[Iterable[Any]]) -> List[Dict[str, Any]]:
    return [item for item in (items or []) if isinstance(item, dict)]


def _apply_volatile(base: Dict[str, Any], overlay: Dict[str, Any], ignored: List[Tuple[str, str]]) -> Dict[str, Any]:
    """把远程条目的易变字段盖到 base 上；稳定字段一律忽略并留痕。"""
    merged = copy.deepcopy(base)
    agent_id = str(base.get("id") or "")
    for key, value in overlay.items():
        if key in ("schemaVersion", "id"):
            continue
        if key not in VOLATILE_FIELDS:
            ignored.append((agent_id, key))
            continue
        merged[key] = copy.deepcopy(value)
    return merged


def _apply_user(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """用户覆盖：除 id / schemaVersion 外全部可改（本地优先）。"""
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if key in ("id", "schemaVersion"):
            continue
        merged[key] = copy.deepcopy(value)
    return merged


def merge_layers(
    bundled: Optional[Iterable[Any]],
    remote: Optional[Iterable[Any]] = None,
    user: Optional[Iterable[Any]] = None,
) -> MergeResult:
    """三层合并。输入是原始 dict 列表（已从 JSON 读出的形态）。"""
    result = MergeResult()

    # 1) 内置层：逐条校验，非法只丢该条
    base_map: Dict[str, Dict[str, Any]] = {}
    for raw in _as_dicts(bundled):
        agent_id = str(raw.get("id") or "")
        try:
            spec = AgentSpec.from_dict(raw)
        except CatalogError as exc:
            result.dropped.append((agent_id or "<unknown>", "内置条目非法：%s" % exc))
            continue
        if spec.id in base_map:
            result.dropped.append((spec.id, "内置条目重复 id"))
            continue
        base_map[spec.id] = raw

    # 2) 远程层：只改易变字段，且不能新增
    for raw in _as_dicts(remote):
        agent_id = str(raw.get("id") or "")
        if not agent_id:
            result.dropped.append(("<unknown>", "远程条目缺少 id"))
            continue
        if agent_id not in base_map:
            result.dropped.append((agent_id, "远程条目不能新增 Agent（缺稳定层）"))
            continue
        candidate = _apply_volatile(base_map[agent_id], raw, result.ignored_fields)
        try:
            AgentSpec.from_dict(candidate)
        except CatalogError as exc:
            # 坏补丁不推翻内置条目：保留原样，留痕
            result.dropped.append((agent_id, "远程补丁非法，已回退内置：%s" % exc))
            continue
        base_map[agent_id] = candidate
        result.patched.append(agent_id)

    # 3) 用户层：最高优先级，可新增
    for raw in _as_dicts(user):
        agent_id = str(raw.get("id") or "")
        if not agent_id:
            result.dropped.append(("<unknown>", "用户条目缺少 id"))
            continue
        if agent_id in base_map:
            candidate = _apply_user(base_map[agent_id], raw)
            try:
                AgentSpec.from_dict(candidate)
            except CatalogError as exc:
                result.dropped.append((agent_id, "用户覆盖非法，已回退上一层：%s" % exc))
                continue
            base_map[agent_id] = candidate
            if agent_id not in result.patched:
                result.patched.append(agent_id)
        else:
            try:
                AgentSpec.from_dict(raw)
            except CatalogError as exc:
                result.dropped.append((agent_id, "用户新增条目非法：%s" % exc))
                continue
            base_map[agent_id] = raw
            result.added.append(agent_id)

    # 4) 收口：统一校验 + 排序
    specs: List[AgentSpec] = []
    for agent_id, raw in base_map.items():
        try:
            specs.append(AgentSpec.from_dict(raw))
        except CatalogError as exc:
            result.dropped.append((agent_id, "合并结果非法，已丢弃：%s" % exc))
    result.agents = sorted(specs, key=_sort_key)

    if result.dropped:
        logger.warning("目录合并丢弃 %d 条：%s", len(result.dropped), result.dropped)
    if result.ignored_fields:
        logger.info("目录合并忽略了远程的稳定层字段：%s", result.ignored_fields)
    return result


def diff_specs(old: Iterable[AgentSpec], new: Iterable[AgentSpec]) -> Dict[str, List[str]]:
    """两份目录的 id 级差异，供 ``af catalog verify`` 打印人审用的 diff。"""
    old_map = {spec.id: spec for spec in old}
    new_map = {spec.id: spec for spec in new}
    return {
        "added": sorted(set(new_map) - set(old_map)),
        "removed": sorted(set(old_map) - set(new_map)),
        "changed": sorted(
            agent_id for agent_id in set(old_map) & set(new_map)
            if old_map[agent_id].to_dict() != new_map[agent_id].to_dict()
        ),
    }
