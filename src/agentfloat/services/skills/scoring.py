# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Skill 发现排序（C 线 · C2）

风暴稿口径：先过「有 SKILL.md / 可识别 Skill 结构」门槛，再按
**热度 35 / 活跃 25 / 信任 20 / 匹配 20** 加权，卡片至少展示两个因子。

本模块是纯函数：不联网、不读文件（时间可由 ``now`` 注入）。
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from agentfloat.services.skills.models import SkillEntry, as_float

WEIGHTS = {"hot": 35.0, "active": 25.0, "trust": 20.0, "match": 20.0}
FACTOR_LABELS = {"hot": "热度", "active": "活跃", "trust": "信任", "match": "匹配"}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _parse_time(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _now_ts(now: Optional[float]) -> float:
    if now is None:
        return datetime.now(timezone.utc).timestamp()
    return float(now)


def gate_entry(entry: SkillEntry) -> Tuple[bool, str]:
    """发现门槛：没有 SKILL.md / 名称非法 / 非 Skill 类型 → 不进入排序。"""
    if entry is None:
        return False, "条目为空"
    if entry.kind != "skill":
        return False, "首版只收录 Skill（MCP / 插件只展示说明）"
    if not entry.has_skill_md:
        return False, "未找到 SKILL.md"
    name = str(entry.name or "").strip()
    if not name:
        return False, "缺少 Skill 名称"
    if len(name) > 120:
        return False, "Skill 名称过长"
    return True, ""


def _hot_score(entry: SkillEntry) -> Tuple[float, str]:
    stars = max(0, int(entry.source.stars or 0))
    # log10(1+stars)/4：1k ≈ 0.75，10k ≈ 1.0；避免头部项目把长尾完全压死
    ratio = _clamp(math.log10(1 + stars) / 4.0)
    return WEIGHTS["hot"] * ratio, ("%s stars" % stars) if stars else "本地 / 无星标"


def _active_score(entry: SkillEntry, now: float) -> Tuple[float, str]:
    dt = _parse_time(entry.source.pushed_at)
    if dt is None:
        return 0.0, "活跃度未知"
    days = max(0.0, (now - dt.timestamp()) / 86400.0)
    if days <= 7:
        ratio = 1.0
    elif days <= 30:
        ratio = 0.8
    elif days <= 90:
        ratio = 0.5
    elif days <= 180:
        ratio = 0.25
    else:
        ratio = 0.0
    text = "今天更新" if days < 1 else ("%d 天前更新" % int(days))
    return WEIGHTS["active"] * ratio, text


def _trust_score(entry: SkillEntry) -> Tuple[float, str]:
    trust = _clamp(as_float(entry.source.trust, 0.6))
    labels = []
    if entry.source.verified:
        labels.append("已核实")
    if entry.source.type == "awesome":
        labels.append("精选列表")
    elif entry.source.type == "github":
        labels.append("GitHub")
    elif entry.source.type == "local":
        labels.append("本地")
    text = " · ".join(labels) or "来源未知"
    return WEIGHTS["trust"] * trust, text


def _query_tokens(query: str) -> List[str]:
    return [x for x in re.split(r"\s+", str(query or "").strip().lower()) if x]


def _match_score(entry: SkillEntry, query: str) -> Tuple[float, str]:
    tokens = _query_tokens(query)
    if not tokens:
        return 0.0, ""
    hay = " ".join([
        entry.name or "", entry.description or "", entry.category or "",
        " ".join(entry.tags or []), entry.source.repo or "",
    ]).lower()
    hits = sum(1 for t in tokens if t in hay)
    ratio = hits / float(len(tokens))
    return WEIGHTS["match"] * ratio, ("命中 %d/%d 关键词" % (hits, len(tokens)))


def score_entry(entry: SkillEntry, query: str = "", now: Optional[float] = None) -> float:
    """计算 0–100 分，并把因子写回 ``entry.factors``（至少两个可展示因子）。"""
    ok, _reason = gate_entry(entry)
    if not ok:
        entry.score = 0.0
        entry.factors = []
        return 0.0
    ts = _now_ts(now)
    hot, hot_text = _hot_score(entry)
    active, active_text = _active_score(entry, ts)
    trust, trust_text = _trust_score(entry)
    match, match_text = _match_score(entry, query)
    factors = [
        {"key": "hot", "label": FACTOR_LABELS["hot"], "value": round(hot, 1),
         "max": WEIGHTS["hot"], "text": hot_text},
        {"key": "active", "label": FACTOR_LABELS["active"], "value": round(active, 1),
         "max": WEIGHTS["active"], "text": active_text},
        {"key": "trust", "label": FACTOR_LABELS["trust"], "value": round(trust, 1),
         "max": WEIGHTS["trust"], "text": trust_text},
        {"key": "match", "label": FACTOR_LABELS["match"], "value": round(match, 1),
         "max": WEIGHTS["match"], "text": match_text or "未输入关键词"},
    ]
    entry.factors = factors
    entry.score = round(hot + active + trust + match, 1)
    return entry.score


def rank_entries(entries: List[SkillEntry], query: str = "",
                 now: Optional[float] = None) -> List[SkillEntry]:
    """过滤门槛并排序；同分按星标、名称稳定排序。"""
    passed = []
    for entry in entries or []:
        ok, _reason = gate_entry(entry)
        if not ok:
            continue
        score_entry(entry, query=query, now=now)
        passed.append(entry)
    passed.sort(key=lambda e: (-e.score, -(int(e.source.stars or 0)), e.name.lower()))
    return passed


def gate_reason(entry: SkillEntry) -> str:
    return gate_entry(entry)[1]


def explain(entry: SkillEntry) -> List[str]:
    """给 UI 用的一句话理由（至少两个因子）。"""
    out = []
    for f in entry.factors or []:
        text = str(f.get("text") or "").strip()
        if text:
            out.append("%s：%s" % (f.get("label") or "", text))
    return out[:4]
