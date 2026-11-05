# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — 统一 AI 模型接入 / 余额监控 / Token 统计

设计目标（v3.28 预览稿「AI 接入」）
  * 一份供应商列表（config.llm.providers），字段与 ccswitch 风格对齐：
    name / base_url / api_key / model / kind(money|sub) / balance_url /
    balance_field / low_balance_warn / enabled（另含 id / preset / currency）。
  * 一键切换 active provider，只影响 AgentFloat 自己发起的调用（AI 快报、
    Skills 翻译），不修改 Claude / Codex 等外部配置文件。
  * 余额：金额型走用户配置的 balance_url；订阅型（OpenCode Go）固定读
    ``GET https://opencode.ai/zen/go/v1/usage`` 的 rolling / weekly / monthly
    percent（已用百分比，只读、不计入总余额）。
  * 用量：每次 chat 调用记录 prompt / completion / total tokens、purpose、
    model、时间；响应无 usage 字段时按字符估算并标记 estimated。

本模块只依赖标准库 + 既有 api_monitor 模板/JSONPath 工具，不依赖 Qt，
因此可在 Web 线程、后台线程与单元测试中直接使用。
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from agentfloat.core.logging_setup import _log
from agentfloat.core.paths import config_dir
from agentfloat.services.api_monitor.config import (
    jsonpath_get, resolve_template,
)

__all__ = [
    "DEFAULT_LLM", "DEFAULTS", "PRESETS", "LLMError",
    "normalize_config", "ensure_config", "has_active_provider",
    "list_providers", "get_provider", "get_active_provider", "active_provider_id",
    "upsert_provider", "delete_provider", "activate_provider",
    "mask_provider", "preset_by_id", "preset_for_provider", "resolve_provider_key",
    "chat", "test_provider", "fetch_balance", "fetch_balance_cached",
    "balances_for", "record_usage", "read_usage", "summarize_usage",
    "usage_path", "estimate_tokens", "summarize_balances",
]

OPENCODE_GO_USAGE_URL = "https://opencode.ai/zen/go/v1/usage"
OPENCODE_GO_KEY_TEMPLATE = "{{env:OPENCODE_GO_API_KEY}}"
OPENCODE_GO_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")

PURPOSES = ("news", "translate", "test")
PURPOSE_LABELS = {"news": "AI 快报", "translate": "Skills 翻译", "test": "测试"}

DEFAULT_LLM = {
    "providers": [],
    "active": "",
}
# 兼容命名（config.py 里习惯叫 DEFAULTS）
DEFAULTS = DEFAULT_LLM


class LLMError(Exception):
    """可读的 LLM / 余额请求错误（页面与日志直接展示）"""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


# ── 内置预设 ──────────────────────────────────────────────
PRESETS = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "description": "OpenAI 兼容；余额走官方 /user/balance（人民币）",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "kind": "money",
        "balance_url": "https://api.deepseek.com/user/balance",
        "balance_field": "balance_infos[0].total_balance",
        "currency": "CNY",
        "low_balance_warn": 5.0,
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "description": "OpenAI 兼容聚合网关；余额走 credits 接口（美元）",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "openai/gpt-4o-mini",
        "kind": "money",
        "balance_url": "https://openrouter.ai/api/v1/credits",
        "balance_field": "data.total_credits",
        "currency": "USD",
        "low_balance_warn": 2.0,
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "description": "官方 OpenAI 兼容接口；官方不提供余额查询，可手填代理余额接口",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "kind": "money",
        "balance_url": "",
        "balance_field": "",
        "currency": "USD",
        "low_balance_warn": 2.0,
    },
    {
        "id": "moonshot",
        "name": "Kimi / Moonshot",
        "description": "OpenAI 兼容；余额走官方 users/me/balance（人民币）",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-8k",
        "kind": "money",
        "balance_url": "https://api.moonshot.cn/v1/users/me/balance",
        "balance_field": "data.available_balance",
        "currency": "CNY",
        "low_balance_warn": 5.0,
    },
    {
        "id": "siliconflow",
        "name": "SiliconFlow",
        "description": "OpenAI 兼容；余额走 user/info（人民币）",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "kind": "money",
        "balance_url": "https://api.siliconflow.cn/v1/user/info",
        "balance_field": "data.totalBalance",
        "currency": "CNY",
        "low_balance_warn": 5.0,
    },
    {
        "id": "opencode-go",
        "name": "OpenCode Go",
        "description": "订阅型：只读 rolling / weekly / monthly 已用百分比，不计入总余额",
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "zen/go",
        "kind": "sub",
        "balance_url": OPENCODE_GO_USAGE_URL,
        "balance_field": "usage.rolling.percent",
        "currency": "",
        "low_balance_warn": 90.0,
    },
    {
        "id": "custom",
        "name": "自定义 OpenAI 兼容",
        "description": "自填 Base URL / 模型 / Key；余额接口可选",
        "base_url": "",
        "model": "",
        "kind": "money",
        "balance_url": "",
        "balance_field": "",
        "currency": "CNY",
        "low_balance_warn": 5.0,
    },
]

_PRESET_MAP = {p["id"]: p for p in PRESETS}

# 按端点名字推导预设（迁移 api_monitor.endpoints 时用）
_PRESET_NAME_HINTS = (
    ("opencode go", "opencode-go"),
    ("deepseek", "deepseek"),
    ("openrouter", "openrouter"),
    ("moonshot", "moonshot"),
    ("kimi", "moonshot"),
    ("siliconflow", "siliconflow"),
    ("openai", "openai"),
)

# 迁移标记：从 api_monitor.endpoints 复用供应商只在「首次」发生一次；
# 标记一旦落盘，即使用户删空供应商也不再复活（同时记录 deleted_ids 作为兜底）。
_MIGRATION_FLAG = "migrated_from_api_monitor"
_DELETED_IDS_KEY = "deleted_ids"
_MAX_DELETED_IDS = 32

_LOCK = threading.RLock()
_BALANCE_CACHE: Dict[str, Dict[str, Any]] = {}
_BALANCE_CACHE_LOCK = threading.RLock()
_DEFAULT_BALANCE_TTL = 60.0


# ── 配置归一化 / 迁移 ─────────────────────────────────────
def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slug(text: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")
    return value or "provider"


def _new_id(name: str = "", existing=()) -> str:
    base = _slug(name)
    candidate = base
    used = {str(x) for x in (existing or [])}
    n = 2
    while candidate in used:
        candidate = "%s-%d" % (base, n)
        n += 1
    return candidate


def _bool(value, default=True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


def _float(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_base_url(url: str) -> str:
    """去掉尾部斜杠；/chat/completions 由 chat() 统一拼接。"""
    value = str(url or "").strip()
    return value.rstrip("/")


def preset_by_id(preset_id: str) -> Optional[dict]:
    return copy.deepcopy(_PRESET_MAP.get(str(preset_id or ""), None))


def preset_for_provider(provider: dict) -> str:
    """返回供应商使用的预设 id（显式 preset 优先，其次按名称/域名推断）。"""
    pid = str((provider or {}).get("preset") or "").strip()
    if pid in _PRESET_MAP:
        return pid
    name = str((provider or {}).get("name") or "").lower()
    base = str((provider or {}).get("base_url") or "").lower()
    for hint, candidate in _PRESET_NAME_HINTS:
        if hint in name or hint.replace(" ", "") in base.replace(" ", ""):
            return candidate
    return "custom"


def _normalize_provider(raw: dict, existing_ids=()) -> dict:
    """补齐字段、校验枚举，不修改入参。"""
    src = copy.deepcopy(raw or {})
    preset_id = preset_for_provider(src)
    preset = _PRESET_MAP.get(preset_id) or {}
    pid = str(src.get("id") or "").strip()
    if not pid:
        pid = _new_id(src.get("name") or preset.get("name") or "", existing_ids)
    kind = str(src.get("kind") or preset.get("kind") or "money").strip().lower()
    if kind not in ("money", "sub"):
        kind = "money"
    item = {
        "id": pid,
        "name": str(src.get("name") or preset.get("name") or "未命名供应商").strip(),
        "base_url": _normalize_base_url(src.get("base_url") or preset.get("base_url") or ""),
        "api_key": str(src.get("api_key") or "").strip(),
        "model": str(src.get("model") or preset.get("model") or "").strip(),
        "kind": kind,
        "balance_url": str(src.get("balance_url") or preset.get("balance_url") or "").strip(),
        "balance_field": str(src.get("balance_field") or preset.get("balance_field") or "").strip(),
        "low_balance_warn": _float(src.get("low_balance_warn"),
                                   preset.get("low_balance_warn", 5.0)),
        "enabled": _bool(src.get("enabled"), True),
        "preset": preset_id,
        "currency": str(src.get("currency") or preset.get("currency") or "").strip(),
    }
    # 订阅型固定读 OpenCode Go 用量接口；不允许改字段/折算金额
    if item["kind"] == "sub":
        item["balance_url"] = OPENCODE_GO_USAGE_URL
        item["balance_field"] = "usage.rolling.percent"
    # 其它可选字段原样保留（备注等），避免保存时丢用户数据
    for key, value in src.items():
        if key not in item and key not in ("created_at", "updated_at"):
            item[key] = value
    return item


def _provider_from_endpoint(ep: dict, existing_ids=()) -> Optional[dict]:
    """从 api_monitor.endpoints 的一条端点推导供应商（要求有 Key + model）。"""
    if not isinstance(ep, dict):
        return None
    name = str(ep.get("name") or "").strip()
    preset_id = "custom"
    for hint, candidate in _PRESET_NAME_HINTS:
        if hint in name.lower():
            preset_id = candidate
            break
    preset = _PRESET_MAP.get(preset_id) or {}
    headers = ep.get("headers") if isinstance(ep.get("headers"), dict) else {}
    auth = ""
    for key, value in headers.items():
        if str(key).lower() == "authorization":
            auth = str(value or "").strip()
            break
    raw_key = re.sub(r"(?i)^bearer\s+", "", auth).strip()
    if not raw_key:
        return None
    body = ep.get("body") if isinstance(ep.get("body"), dict) else {}
    model = str(ep.get("model") or body.get("model") or preset.get("model") or "").strip()
    if not model:
        return None
    base_url = str(ep.get("base_url") or preset.get("base_url") or "").strip()
    if not base_url:
        # 只有能确定平台时才自动迁移，避免把余额接口地址误当 chat 地址
        return None
    first_field = ""
    fields = ep.get("fields") or []
    if fields and isinstance(fields[0], dict):
        first_field = str(fields[0].get("jsonpath") or "").lstrip("$").lstrip(".")
    return _normalize_provider({
        "name": name or preset.get("name") or "默认供应商",
        "base_url": base_url,
        "api_key": raw_key,
        "model": model,
        "kind": preset.get("kind") or "money",
        "balance_url": ep.get("url") or preset.get("balance_url") or "",
        "balance_field": first_field or preset.get("balance_field") or "",
        "low_balance_warn": preset.get("low_balance_warn", 5.0),
        "currency": preset.get("currency", ""),
        "enabled": True,
        "preset": preset_id,
    }, existing_ids)


def normalize_config(config: dict, derive_from_api_monitor: bool = True) -> Tuple[dict, bool]:
    """把 config["llm"] 归一化；返回 (llm_cfg, changed)。

    - 兼容旧配置：缺 llm / 缺字段时补齐；
    - **仅在首次**（没有迁移标记）且 providers 为空时，复用 api_monitor.endpoints
      中第一个有 Key+model 的端点；迁移后写 llm.migrated_from_api_monitor=true，
      之后即使用户删空供应商也不会再派生出来（已删除 id 记在 llm.deleted_ids）；
    - active 指向不存在 / 被禁用的供应商时，回退到第一个可用供应商。
    """
    changed = False
    raw = config.get("llm") if isinstance(config, dict) else None
    if not isinstance(raw, dict):
        raw = {}
        changed = True
    providers_raw = raw.get("providers")
    if not isinstance(providers_raw, list):
        providers_raw = []
        changed = True
    existing_ids = [str(p.get("id") or "") for p in providers_raw if isinstance(p, dict)]
    providers = []
    for item in providers_raw:
        if not isinstance(item, dict):
            changed = True
            continue
        norm = _normalize_provider(item, existing_ids + [p["id"] for p in providers])
        if norm != item:
            changed = True
        providers.append(norm)

    already_migrated = _bool(raw.get(_MIGRATION_FLAG), False)
    deleted_ids = [str(x) for x in (raw.get(_DELETED_IDS_KEY) or []) if str(x or "").strip()]
    if derive_from_api_monitor and isinstance(config, dict) and providers and not already_migrated:
        # 已有供应商说明无需迁移，但先打标记，避免用户删空后又被派生回来
        raw[_MIGRATION_FLAG] = True
        changed = True
    if not providers and derive_from_api_monitor and isinstance(config, dict) and not already_migrated:
        endpoints = ((config.get("api_monitor") or {}).get("endpoints") or [])
        for ep in endpoints:
            derived = _provider_from_endpoint(ep, [p["id"] for p in providers])
            if not derived:
                continue
            if derived.get("id") in deleted_ids:
                _log().info("LLM 配置迁移：跳过已删除供应商 [%s]", derived.get("id"))
                continue
            providers.append(derived)
            changed = True
            _log().info("LLM 配置迁移：从 API 端点复用供应商 [%s]", derived.get("name"))
            break
        raw[_MIGRATION_FLAG] = True      # 无论是否命中，迁移只尝试一次
        changed = True

    active = str(raw.get("active") or "").strip()
    by_id = {p["id"]: p for p in providers}
    if active and active not in by_id:
        changed = True
        active = ""
    if active and not by_id[active].get("enabled", True):
        changed = True
        active = ""
    if not active and providers:
        # 只把「真的有可用 Key」的供应商设为当前；否则保持空，让上层回退 CLI Agent
        for p in providers:
            if p.get("enabled", True) and resolve_provider_key(p):
                active = p["id"]
                changed = True
                break

    llm_cfg = {"providers": providers, "active": active}
    # 保留用户未来可能加在 llm 根部的其它键
    for key, value in raw.items():
        if key not in llm_cfg:
            llm_cfg[key] = value
    if llm_cfg != raw:
        changed = True
    if isinstance(config, dict):
        config["llm"] = llm_cfg
    return llm_cfg, changed


def ensure_config(config: dict) -> dict:
    """归一化并写回 config（供 load_config / Web handlers 调用）。"""
    llm_cfg, _changed = normalize_config(config)
    return llm_cfg


def _llm_of(config: dict) -> dict:
    llm_cfg = (config or {}).get("llm") if isinstance(config, dict) else None
    if not isinstance(llm_cfg, dict):
        llm_cfg, _ = normalize_config(config if isinstance(config, dict) else {})
    return llm_cfg


# ── 供应商 CRUD ───────────────────────────────────────────
def list_providers(config: dict, include_disabled: bool = True) -> List[dict]:
    llm_cfg = _llm_of(config)
    items = [copy.deepcopy(p) for p in (llm_cfg.get("providers") or [])]
    if not include_disabled:
        items = [p for p in items if p.get("enabled", True)]
    return items


def get_provider(config: dict, provider_id: str) -> Optional[dict]:
    pid = str(provider_id or "").strip()
    for p in list_providers(config):
        if p.get("id") == pid:
            return p
    return None


def active_provider_id(config: dict) -> str:
    return str(_llm_of(config).get("active") or "")


def get_active_provider(config: dict) -> Optional[dict]:
    pid = active_provider_id(config)
    if not pid:
        return None
    provider = get_provider(config, pid)
    if provider and provider.get("enabled", True):
        return provider
    return None


def has_active_provider(config: dict) -> bool:
    """当前供应商是否真的可以发请求（base_url + model + 可解析的 Key）。

    没有 Key（新加未填 / {{env:XXX}} 未设置）时返回 False，
    让 AI 快报与 Skills 翻译回退到原有 CLI Agent 通道。
    """
    provider = get_active_provider(config)
    if not provider or not provider.get("base_url") or not provider.get("model"):
        return False
    return bool(resolve_api_key(provider))


def validate_provider(provider: dict) -> List[str]:
    errors = []
    if not str(provider.get("name") or "").strip():
        errors.append("名称不能为空")
    base = str(provider.get("base_url") or "").strip()
    if not base:
        errors.append("Base URL 不能为空")
    elif not re.match(r"^https?://", base, re.I):
        errors.append("Base URL 必须以 http:// 或 https:// 开头")
    if not str(provider.get("model") or "").strip():
        errors.append("模型不能为空")
    kind = str(provider.get("kind") or "money")
    if kind not in ("money", "sub"):
        errors.append("kind 只能是 money 或 sub")
    balance = str(provider.get("balance_url") or "").strip()
    if balance and not _is_http_url(balance):
        errors.append("余额接口必须以 http:// 或 https:// 开头")
    return errors


def upsert_provider(config: dict, data: dict) -> dict:
    """新增或更新供应商；返回归一化后的 provider（含明文 api_key，调用方自行脱敏）。

    - data 带 id 且已存在 → 合并更新；空 api_key 表示「不修改已保存的 Key」；
    - 新增时若当前没有 active，自动设为当前。
    """
    if not isinstance(data, dict):
        raise LLMError("供应商数据格式错误")
    llm_cfg, _ = normalize_config(config)
    providers = llm_cfg.get("providers") or []
    pid = str(data.get("id") or "").strip()
    existing = None
    if pid:
        existing = next((p for p in providers if p.get("id") == pid), None)
    merged = copy.deepcopy(existing or {})
    for key, value in data.items():
        if key in ("created_at", "updated_at"):
            continue
        if key == "api_key" and existing is not None and not str(value or "").strip():
            continue  # 留空 = 保留旧 Key
        merged[key] = value
    if existing:
        merged["id"] = pid
    else:
        merged["id"] = pid or _new_id(merged.get("name") or "",
                                      [p.get("id") for p in providers])
    merged.setdefault("enabled", True)
    norm = _normalize_provider(merged, [p.get("id") for p in providers if p.get("id") != merged["id"]])
    errors = validate_provider(norm)
    if errors:
        raise LLMError("；".join(errors))
    if existing:
        norm["created_at"] = existing.get("created_at") or _now_iso()
        for i, p in enumerate(providers):
            if p.get("id") == pid:
                providers[i] = norm
                break
    else:
        norm["created_at"] = _now_iso()
        providers.append(norm)
    norm["updated_at"] = _now_iso()
    # 自动设为当前：只在没有 active 且该供应商确实有可用 Key 时发生，
    # 避免「刚保存但没填 Key」的供应商把 AI 快报 / 翻译从 CLI Agent 抢走。
    if (not llm_cfg.get("active") and norm.get("enabled", True)
            and resolve_api_key(norm)):
        llm_cfg["active"] = norm["id"]
    llm_cfg["providers"] = providers
    llm_cfg[_MIGRATION_FLAG] = True       # 用户已手动配置过，不再走 api_monitor 迁移
    config["llm"] = llm_cfg
    return copy.deepcopy(norm)


def delete_provider(config: dict, provider_id: str) -> bool:
    pid = str(provider_id or "").strip()
    if not pid:
        return False
    llm_cfg, _ = normalize_config(config)
    providers = llm_cfg.get("providers") or []
    left = [p for p in providers if p.get("id") != pid]
    if len(left) == len(providers):
        return False
    llm_cfg["providers"] = left
    if llm_cfg.get("active") == pid:
        llm_cfg["active"] = next((p["id"] for p in left if p.get("enabled", True)), "")
    # 记住删除过的 id，并关闭迁移：否则下一次 normalize 会从 api_monitor 派生回来
    deleted = [str(x) for x in (llm_cfg.get(_DELETED_IDS_KEY) or []) if str(x or "").strip()]
    if pid not in deleted:
        deleted.append(pid)
    llm_cfg[_DELETED_IDS_KEY] = deleted[-_MAX_DELETED_IDS:]
    llm_cfg[_MIGRATION_FLAG] = True
    config["llm"] = llm_cfg
    return True


def activate_provider(config: dict, provider_id: str) -> dict:
    pid = str(provider_id or "").strip()
    llm_cfg, _ = normalize_config(config)
    provider = next((p for p in (llm_cfg.get("providers") or []) if p.get("id") == pid), None)
    if provider is None:
        raise LLMError("供应商不存在：%s" % (pid or "(空)"))
    if not provider.get("enabled", True):
        raise LLMError("供应商已停用，启用后才能设为当前")
    llm_cfg["active"] = pid
    config["llm"] = llm_cfg
    return copy.deepcopy(provider)


def resolve_provider_key(provider: dict) -> str:
    """供应商实际生效的 Key：显式 Key 优先，订阅型回退 OPENCODE_GO_API_KEY。"""
    key = resolve_api_key(provider or {})
    if not key and (str((provider or {}).get("preset") or "") == "opencode-go"
                    or str((provider or {}).get("kind") or "") == "sub"):
        key = resolve_api_key({"api_key": OPENCODE_GO_KEY_TEMPLATE})
    return key


def mask_provider(provider: dict) -> dict:
    """返回可安全放进 Web 响应的供应商（API Key 只给是否存在 + 尾号提示）。"""
    item = copy.deepcopy(provider or {})
    # 与 fetch_balance 相同的 env 回退，避免「环境变量能查到余额、页面却说未配置 Key」
    resolved = resolve_provider_key(item)
    item.pop("api_key", None)
    hint = ""
    if resolved:
        hint = ("…" + resolved[-4:]) if len(resolved) > 8 else "已保存"
    item["api_key_set"] = bool(resolved)
    item["api_key_hint"] = hint
    return item


def _is_http_url(url) -> bool:
    return bool(re.match(r"^https?://", str(url or "").strip(), re.I))


def _require_http_url(url) -> str:
    """只放行 http/https；file://、ftp:// 等一律拒绝（错误信息不回显地址内容）。"""
    value = str(url or "").strip()
    if not _is_http_url(value):
        raise LLMError("接口地址协议不受支持，仅允许 http:// 或 https://")
    return value


# ── HTTP 基础 ─────────────────────────────────────────────
def _friendly_net_error(err) -> str:
    msg = str(err or "").strip()
    low = msg.lower()
    if "handshake" in low or "timed out" in low or "timeout" in low:
        return "连接超时（检查网络或代理是否已开启）"
    if "refused" in low:
        return "连接被拒绝"
    if "getaddrinfo" in low or "name or service not known" in low:
        return "域名解析失败（DNS 或代理配置问题）"
    if "certificate" in low or "ssl" in low:
        return "证书校验失败：%s" % msg[:80]
    return msg[:160] or "未知网络错误"


def _http_json(method: str, url: str, headers: Optional[dict] = None,
               body: Optional[dict] = None, timeout: float = 30.0) -> Any:
    """单次 HTTP 请求 → JSON。测试通过 monkeypatch 本函数避免真实网络。"""
    url = _require_http_url(url)
    hdrs = {"Accept": "application/json", "User-Agent": OPENCODE_GO_UA}
    hdrs.update(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(str(url), data=data, headers=hdrs,
                                 method=str(method or "GET").upper())
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler())
        with opener.open(req, timeout=float(timeout or 30)) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        text = ""
        try:
            text = exc.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        raise LLMError("HTTP %s: %s%s" % (
            exc.code, exc.reason or "", ("\n" + text) if text else ""),
            status_code=exc.code) from exc
    except urllib.error.URLError as exc:
        raise LLMError("连接失败: %s" % _friendly_net_error(getattr(exc, "reason", exc))) from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMError("请求异常: %s" % _friendly_net_error(exc)) from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LLMError("响应不是 JSON（前 120 字符）：%s" % raw[:120]) from exc


def resolve_api_key(provider: dict) -> str:
    """解析 Key 模板（{{env:VAR}}）并去掉 Bearer 前缀；空值返回 ""。"""
    raw = str((provider or {}).get("api_key") or "").strip()
    if not raw:
        return ""
    value = resolve_template(raw).strip()
    value = re.sub(r"(?i)^bearer\s+", "", value).strip()
    if value.startswith("{{") and value.endswith("}}"):
        return ""       # 环境变量不存在，模板原样保留 → 视为未配置
    return value


def _auth_headers(provider: dict) -> dict:
    key = resolve_api_key(provider)
    if not key:
        return {}
    return {"Authorization": "Bearer %s" % key}


def _chat_url(base_url: str) -> str:
    base = _normalize_base_url(base_url)
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


# ── Token 估算 / 用量记录 ─────────────────────────────────
def estimate_tokens(text) -> int:
    """响应无 usage 时的粗略估算：按字符数 / 4（至少 1）。"""
    if text is None:
        return 1
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            text = str(text)
    return max(1, int(math.ceil(len(text) / 4.0)))


def usage_path() -> str:
    """用量 JSONL 路径；AGENTFLOAT_LLM_USAGE 可覆盖（测试/便携模式）。"""
    override = os.environ.get("AGENTFLOAT_LLM_USAGE", "").strip()
    if override:
        return override
    return os.path.join(config_dir(), "llm_usage.jsonl")


def _message_text(messages) -> str:
    parts = []
    for msg in messages or []:
        if isinstance(msg, dict):
            content = msg.get("content")
        else:
            content = msg
        if isinstance(content, list):
            for chunk in content:
                if isinstance(chunk, dict):
                    parts.append(str(chunk.get("text") or ""))
                else:
                    parts.append(str(chunk))
        else:
            parts.append(str(content or ""))
    return "\n".join(parts)


def record_usage(provider_id: str, model: str, prompt_tokens: int,
                 completion_tokens: int, purpose: str = "test",
                 estimated: bool = False, path: Optional[str] = None,
                 ts: Optional[str] = None) -> dict:
    """追加一条用量记录（JSONL，线程安全、失败不影响主调用）。"""
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    purpose = str(purpose or "test").strip().lower()
    if purpose not in PURPOSES:
        purpose = "test"
    record = {
        "ts": ts or _now_iso(),
        "provider_id": str(provider_id or ""),
        "model": str(model or ""),
        "purpose": purpose,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "estimated": bool(estimated),
    }
    target = path or usage_path()
    try:
        folder = os.path.dirname(os.path.abspath(target))
        if folder:
            os.makedirs(folder, exist_ok=True)
        with _LOCK:
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except (OSError, IOError) as exc:
        _log().warning("LLM 用量记录写入失败: %s", exc)
    return record


def read_usage(path: Optional[str] = None) -> List[dict]:
    """读取全部用量记录；坏行跳过，不抛异常。"""
    target = path or usage_path()
    if not os.path.isfile(target):
        return []
    out = []
    try:
        with open(target, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    out.append(item)
    except (OSError, IOError) as exc:
        _log().warning("LLM 用量记录读取失败: %s", exc)
    return out


def _empty_bucket() -> dict:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "calls": 0, "estimated_calls": 0}


def _add_to_bucket(bucket: dict, item: dict) -> None:
    bucket["prompt_tokens"] += int(item.get("prompt_tokens") or 0)
    bucket["completion_tokens"] += int(item.get("completion_tokens") or 0)
    bucket["total_tokens"] += int(item.get("total_tokens") or 0)
    bucket["calls"] += 1
    if item.get("estimated"):
        bucket["estimated_calls"] += 1


def summarize_usage(now: Optional[datetime] = None,
                    path: Optional[str] = None) -> dict:
    """今日 / 本月 / 分用途汇总 + 各供应商今日 tokens。"""
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    today_b = _empty_bucket()
    month_b = _empty_bucket()
    by_purpose: Dict[str, dict] = {p: _empty_bucket() for p in PURPOSES}
    by_provider_today: Dict[str, dict] = {}
    last_call_at = ""
    recent = []
    for item in read_usage(path):
        ts = str(item.get("ts") or "")
        purpose = str(item.get("purpose") or "test")
        if purpose not in by_purpose:
            by_purpose[purpose] = _empty_bucket()
        # by_purpose 是全量累计口径（前端标注「累计」）
        _add_to_bucket(by_purpose[purpose], item)
        if ts > last_call_at:
            last_call_at = ts
        if ts.startswith(month):
            _add_to_bucket(month_b, item)
        if ts.startswith(today):
            _add_to_bucket(today_b, item)
            pid = str(item.get("provider_id") or "")
            bucket = by_provider_today.setdefault(pid, _empty_bucket())
            _add_to_bucket(bucket, item)
        recent.append({
            "ts": ts,
            "provider_id": str(item.get("provider_id") or ""),
            "model": str(item.get("model") or ""),
            "purpose": purpose,
            "total_tokens": int(item.get("total_tokens") or 0),
            "estimated": bool(item.get("estimated")),
        })
    recent = sorted(recent, key=lambda x: x.get("ts") or "", reverse=True)[:8]
    return {
        "today": today_b,
        "month": month_b,
        "by_purpose": by_purpose,
        "by_provider_today": by_provider_today,
        "last_call_at": last_call_at,
        "recent": recent,
    }


# ── chat（OpenAI 兼容）────────────────────────────────────
def _content_of(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise LLMError("响应格式异常：期望 JSON 对象")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        # 部分兼容网关在错误时仍返回 200 + error
        err = payload.get("error")
        if isinstance(err, dict):
            raise LLMError(str(err.get("message") or err))
        raise LLMError("响应缺少 choices 字段")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")
    if content is None:
        content = first.get("text")
    if isinstance(content, list):
        bits = []
        for chunk in content:
            if isinstance(chunk, dict):
                bits.append(str(chunk.get("text") or ""))
            else:
                bits.append(str(chunk))
        content = "".join(bits)
    return str(content or "")


def chat(config: dict, messages: list, purpose: str = "test",
         provider_id: Optional[str] = None, timeout: float = 60.0,
         temperature: float = 0.3, max_tokens: Optional[int] = None,
         usage_path_override: Optional[str] = None) -> dict:
    """调用 active（或指定）供应商的 /chat/completions。

    返回 {ok, content, usage:{prompt_tokens,...}, estimated, provider_id,
          model, latency_ms}；失败抛 LLMError（可读中文）。
    """
    if provider_id:
        provider = get_provider(config, provider_id)
        if not provider:
            raise LLMError("供应商不存在：%s" % provider_id)
    else:
        provider = get_active_provider(config)
        if not provider:
            raise LLMError("尚未设置当前 AI 供应商，请先在「AI 接入」页添加并设为当前")
    errors = validate_provider(provider)
    if errors:
        raise LLMError("；".join(errors))
    key = resolve_api_key(provider)
    if not key:
        raise LLMError("供应商「%s」未配置 API Key" % provider.get("name"))
    url = _chat_url(provider.get("base_url"))
    payload = {
        "model": provider.get("model"),
        "messages": messages or [],
        "stream": False,
        "temperature": float(temperature if temperature is not None else 0.3),
    }
    if max_tokens:
        payload["max_tokens"] = int(max_tokens)
    started = time.time()
    data = _http_json("POST", url, headers=_auth_headers(provider),
                      body=payload, timeout=timeout)
    latency_ms = int((time.time() - started) * 1000)
    content = _content_of(data)
    usage = data.get("usage") if isinstance(data, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    estimated = False
    if prompt_tokens is None or completion_tokens is None:
        estimated = True
        prompt_tokens = estimate_tokens(_message_text(messages))
        completion_tokens = estimate_tokens(content)
    record = record_usage(
        provider.get("id") or "", provider.get("model") or "",
        int(prompt_tokens or 0), int(completion_tokens or 0),
        purpose=purpose, estimated=estimated, path=usage_path_override)
    return {
        "ok": True,
        "content": content,
        "usage": {
            "prompt_tokens": record["prompt_tokens"],
            "completion_tokens": record["completion_tokens"],
            "total_tokens": record["total_tokens"],
            "estimated": estimated,
        },
        "provider_id": provider.get("id") or "",
        "provider_name": provider.get("name") or "",
        "model": provider.get("model") or "",
        "latency_ms": latency_ms,
    }


def test_provider(config: dict, provider: Optional[dict] = None,
                  provider_id: str = "", timeout: float = 20.0) -> dict:
    """测试供应商可用性（发一条极短对话；会产生一条 purpose=test 用量）。"""
    candidate = copy.deepcopy(provider) if isinstance(provider, dict) else None
    pid = str((candidate or {}).get("id") or provider_id or "").strip()
    if candidate and pid:
        stored = get_provider(config, pid)
        if stored:
            merged = copy.deepcopy(stored)
            for key, value in candidate.items():
                if key == "api_key" and not str(value or "").strip():
                    continue
                merged[key] = value
            candidate = merged
    if candidate is None and pid:
        candidate = get_provider(config, pid)
    if candidate is None:
        candidate = get_active_provider(config)
    if not candidate:
        raise LLMError("没有可测试的供应商")
    # 未保存的草稿没有 id：先归一化补 id / 预设默认值，测试才不需要「先保存」
    candidate = _normalize_provider(
        candidate, [p.get("id") for p in list_providers(config)])
    # 用临时 config 承载候选（不落盘、不切 active）
    tmp_cfg = {"llm": {"providers": [candidate], "active": candidate.get("id") or ""}}
    result = chat(tmp_cfg, [{"role": "user", "content": "只回复 OK"}],
                  purpose="test", timeout=timeout, max_tokens=8)
    return {
        "ok": True,
        "reply": result.get("content") or "",
        "latency_ms": result.get("latency_ms"),
        "usage": result.get("usage"),
        "provider_id": candidate.get("id") or "",
        "model": candidate.get("model") or "",
    }


# ── 余额（金额 / 订阅）────────────────────────────────────
def _money_value(data: Any, provider: dict) -> Tuple[Optional[float], str, str]:
    """返回 (余额数值, 货币, 使用的字段)。支持 OpenRouter total_credits-total_usage。"""
    field = str(provider.get("balance_field") or "").strip()
    if not field:
        # 少量常见结构兜底，仍然只读一个明确字段
        for candidate in ("balance_infos[0].total_balance", "data.available_balance",
                          "data.totalBalance", "data.total_credits"):
            if jsonpath_get(data, candidate) is not None:
                field = candidate
                break
    value = jsonpath_get(data, field) if field else None
    if field == "data.total_credits":
        used = jsonpath_get(data, "data.total_usage")
        try:
            if used is not None and value is not None:
                value = float(value) - float(used)
        except (TypeError, ValueError):
            pass
    try:
        num = float(value) if value is not None else None
    except (TypeError, ValueError):
        num = None
    currency = str(provider.get("currency") or "").strip()
    if not currency:
        currency = str(jsonpath_get(data, "balance_infos[0].currency") or "").strip()
    if not currency:
        if field.startswith("data.total_credits"):
            currency = "USD"
        elif "balance" in field.lower() or "totalbalance" in field.lower():
            currency = "CNY"
    return num, currency, field


def _parse_sub_percent(data: Any) -> dict:
    periods = {}
    for name in ("rolling", "weekly", "monthly"):
        pct = None
        if isinstance(data, dict):
            node = (data.get("usage") or {}).get(name) if isinstance(data.get("usage"), dict) else None
            if not isinstance(node, dict):
                node = data.get(name) if isinstance(data.get(name), dict) else None
            if isinstance(node, dict):
                pct = node.get("percent")
        try:
            pct = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            pct = None
        periods[name] = pct
    return periods


def fetch_balance(provider: dict, timeout: float = 8.0) -> dict:
    """查询单个供应商余额/订阅用量；永远返回 dict，不抛异常。

    金额型：{"ok":true,"kind":"money","balance":12.4,"currency":"CNY","low":false}
    订阅型：{"ok":true,"kind":"sub","percent":78.0,"periods":{...}}（不计入总余额）
    """
    provider = provider or {}
    kind = str(provider.get("kind") or "money").lower()
    fetched_at = time.strftime("%H:%M:%S")
    try:
        if kind == "sub":
            url = _require_http_url(provider.get("balance_url") or OPENCODE_GO_USAGE_URL)
            key = resolve_provider_key(provider)
            if not key:
                return {"ok": False, "kind": "sub", "error": "未配置 OPENCODE_GO_API_KEY",
                        "fetched_at": fetched_at, "percent": None, "periods": {}}
            data = _http_json("GET", url,
                              headers={"Authorization": "Bearer %s" % key},
                              timeout=timeout)
            periods = _parse_sub_percent(data)
            rolling = periods.get("rolling")
            return {
                "ok": True,
                "kind": "sub",
                "percent": rolling,
                "periods": periods,
                "currency": "",
                "low": (rolling is not None and
                        rolling >= _float(provider.get("low_balance_warn"), 90.0)),
                "fetched_at": fetched_at,
            }
        url = str(provider.get("balance_url") or "").strip()
        if not url:
            return {"ok": False, "kind": "money", "skipped": True,
                    "error": "未配置余额接口", "fetched_at": fetched_at}
        url = _require_http_url(url)
        key = resolve_api_key(provider)
        if not key:
            return {"ok": False, "kind": "money", "error": "未配置 API Key",
                    "fetched_at": fetched_at}
        data = _http_json("GET", url, headers=_auth_headers(provider), timeout=timeout)
        value, currency, field = _money_value(data, provider)
        if value is None:
            return {"ok": False, "kind": "money", "currency": currency,
                    "error": "余额字段未命中：%s" % (field or "(未配置)"),
                    "field": field, "fetched_at": fetched_at}
        return {
            "ok": True,
            "kind": "money",
            "balance": round(float(value), 2),
            "currency": currency,
            "field": field,
            "low": float(value) < _float(provider.get("low_balance_warn"), 5.0),
            "fetched_at": fetched_at,
        }
    except LLMError as exc:
        return {"ok": False, "kind": kind, "error": str(exc)[:300],
                "status_code": getattr(exc, "status_code", None),
                "fetched_at": fetched_at}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "kind": kind, "error": "余额查询异常：%s" % str(exc)[:200],
                "fetched_at": fetched_at}


def _balance_cache_key(provider: dict) -> str:
    return "|".join([
        str(provider.get("id") or ""),
        str(provider.get("balance_url") or ""),
        str(provider.get("balance_field") or ""),
        str(provider.get("kind") or ""),
        str(provider.get("currency") or ""),
        resolve_provider_key(provider)[-4:],
    ])


def fetch_balance_cached(provider: dict, ttl: float = _DEFAULT_BALANCE_TTL,
                         force: bool = False, timeout: float = 8.0) -> dict:
    """60s 缓存版余额查询，避免每次打开页面都打网络。"""
    key = _balance_cache_key(provider)
    now = time.time()
    if not force:
        with _BALANCE_CACHE_LOCK:
            cached = _BALANCE_CACHE.get(key)
            if cached and now - float(cached.get("_ts") or 0) < ttl:
                out = copy.deepcopy(cached)
                out.pop("_ts", None)
                out["cached"] = True
                return out
    result = fetch_balance(provider, timeout=timeout)
    with _BALANCE_CACHE_LOCK:
        stored = copy.deepcopy(result)
        stored["_ts"] = now
        _BALANCE_CACHE[key] = stored
    return result


def clear_balance_cache() -> None:
    with _BALANCE_CACHE_LOCK:
        _BALANCE_CACHE.clear()


def balances_for(config: dict, force: bool = False, timeout: float = 8.0) -> Dict[str, dict]:
    """并行查询所有启用供应商的余额，返回 {provider_id: balance}。"""
    llm_cfg = _llm_of(config)
    providers = [p for p in (llm_cfg.get("providers") or []) if p.get("enabled", True)]
    out: Dict[str, dict] = {}
    if not providers:
        return out
    workers = min(4, len(providers))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {
            pool.submit(fetch_balance_cached, p, _DEFAULT_BALANCE_TTL, force, timeout): p
            for p in providers
        }
        for future in as_completed(future_map):
            provider = future_map[future]
            try:
                out[str(provider.get("id") or "")] = future.result()
            except Exception as exc:  # noqa: BLE001
                out[str(provider.get("id") or "")] = {
                    "ok": False, "kind": provider.get("kind") or "money",
                    "error": "余额查询异常：%s" % str(exc)[:180],
                }
    return out


def summarize_balances(providers: List[dict], balances: Dict[str, dict]) -> dict:
    """总余额（按币种分组，订阅型不计入）+ 订阅数量 + 低余额数量。"""
    money = {}
    subs = 0
    low = 0
    for provider in providers or []:
        pid = str(provider.get("id") or "")
        balance = (balances or {}).get(pid) or {}
        if not provider.get("enabled", True):
            continue
        if provider.get("kind") == "sub":
            subs += 1
            if balance.get("low"):
                low += 1
            continue
        if balance.get("ok") and balance.get("balance") is not None:
            # 币种未知时归到 OTHER，绝不默认当成人民币（避免把美元计入 CNY）
            currency = str(balance.get("currency") or provider.get("currency") or "").strip().upper()
            if not currency:
                currency = "OTHER"
            money[currency] = round(money.get(currency, 0.0) + float(balance["balance"]), 2)
            if balance.get("low"):
                low += 1
    return {
        "money": [{"currency": cur, "amount": amt} for cur, amt in sorted(money.items())],
        "subscriptions": subs,
        "low_count": low,
    }
