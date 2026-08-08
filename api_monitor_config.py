"""
API 用量监控 — 配置 schema、模板引擎、JSONPath 解析
"""
import os
import re
import json
from datetime import date, datetime


# ── 默认配置 ──────────────────────────────────────────
DEFAULTS = {
    "enabled": False,
    "poll_interval_seconds": 60,
    "low_balance_warn": 5.0,
    "endpoints": [],
}

SAMPLE_ENDPOINT = {
    "name": "My API",
    "url": "https://api.example.com/v1/usage?date={{today}}",
    "platform_url": "https://platform.example.com/usage",
    "method": "GET",
    "headers": {
        "Authorization": "Bearer {{env:API_KEY}}",
        "Content-Type": "application/json",
    },
    "body": None,
    "fields": [
        {"label": "已用量", "jsonpath": "$.usage.used", "unit": "tokens", "display": "number"},
        {"label": "限额",   "jsonpath": "$.usage.limit", "unit": "tokens", "display": "number"},
    ],
    "progress_field": {"used": "$.usage.used", "total": "$.usage.limit"},
}


# ── 模板引擎 ──────────────────────────────────────────
# ---- Windows registry fallback for env vars (frozen exe compatibility) ----
def _get_env(key: str) -> str:
    """Get env var with Windows registry fallback for User-level vars."""
    val = os.environ.get(key)
    if val:
        return val
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as regkey:
            val, _ = winreg.QueryValueEx(regkey, key)
            return val or ""
    except Exception:
        pass
    return ""

_TEMPLATE_RE = re.compile(r"\{\{(.+?)\}\}")

def resolve_template(text: str) -> str:
    """解析 {{env:VAR}} / {{today}} / {{now_iso}} / {{timestamp}}"""
    def _replacer(m):
        key = m.group(1).strip()
        if key.startswith("env:"):
            return _get_env(key[4:])
        if key == "today":
            return date.today().isoformat()
        if key == "now_iso":
            return datetime.now().isoformat(timespec="seconds")
        if key == "timestamp":
            return str(int(datetime.now().timestamp()))
        return m.group(0)
    return _TEMPLATE_RE.sub(_replacer, text)


def resolve_headers(headers: dict) -> dict:
    """解析 headers 中所有模板变量"""
    return {k: resolve_template(v) for k, v in headers.items()}


def resolve_url(url: str) -> str:
    return resolve_template(url)


# ── JSONPath 解析（精简子集）─────────────────────────
def jsonpath_get(data, path: str):
    """
    支持的语法：
      $.key.subkey       → data["key"]["subkey"]
      $.key[0].sub       → data["key"][0]["sub"]
      $.key[*].sub       → [item["sub"] for item in data["key"]]
    返回单个值或列表
    """
    if not path.startswith("$."):
        path = "$." + path.lstrip("$.")
    segments = path[2:]  # 去掉 "$."
    current = data

    # 手动解析路径：处理 .key 和 [index]
    tokens = re.findall(r'([^.[]+)|\[(\*|\d+)\]', segments)
    for dot_part, bracket_part in tokens:
        if dot_part:
            if isinstance(current, dict):
                current = current.get(dot_part)
            else:
                return None
        elif bracket_part:
            if bracket_part == "*":
                if isinstance(current, list):
                    return current
                return None
            else:
                idx = int(bracket_part)
                if isinstance(current, list) and 0 <= idx < len(current):
                    current = current[idx]
                else:
                    return None
        if current is None:
            return None
    return current


# ── 配置校验 ──────────────────────────────────────────
def validate_endpoint(endpoint: dict) -> list:
    """返回错误列表，空列表表示合法"""
    errors = []
    if not endpoint.get("name", "").strip():
        errors.append("名称不能为空")
    if not endpoint.get("url", "").strip():
        errors.append("URL 不能为空")
    method = endpoint.get("method", "GET").upper()
    if method not in ("GET", "POST", "PUT"):
        errors.append(f"不支持的 HTTP 方法: {method}")
    fields = endpoint.get("fields", [])
    if not fields:
        errors.append("至少需要定义一个显示字段")
    for i, f in enumerate(fields):
        if not f.get("label"):
            errors.append(f"字段 {i+1}: 标签不能为空")
        if not f.get("jsonpath"):
            errors.append(f"字段 '{f.get("label", i+1)}': jsonpath 不能为空")
    return errors


def validate_api_monitor_config(config: dict) -> list:
    """返回错误列表"""
    errors = []
    for i, ep in enumerate(config.get("endpoints", [])):
        ep_errors = validate_endpoint(ep)
        for e in ep_errors:
            errors.append(f"端点 {i+1} ({ep.get('name', '未命名')}): {e}")
    return errors
