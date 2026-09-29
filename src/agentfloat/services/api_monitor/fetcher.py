"""
API 用量监控 — HTTP 请求 + 响应解析
使用标准库 urllib，无需额外依赖
"""
import time
import json
import urllib.request
import urllib.error
import ssl
from agentfloat.services.api_monitor.config import resolve_url, resolve_headers, resolve_template, jsonpath_get


# 禁用 SSL 验证（用户可选 — 用于自签名代理等场景）
_SSL_CONTEXT_VERIFY = ssl.create_default_context()
_SSL_CONTEXT_NO_VERIFY = ssl._create_unverified_context()


class FetchError(Exception):
    """HTTP 请求或解析错误"""
    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code


class FetchResult:
    """单次 fetch 的结果"""
    def __init__(self, endpoint_name: str, fields: list, progress: dict = None,
                 raw_response: str = ""):
        self.endpoint_name = endpoint_name
        self.fields = fields  # [{"label": "已用量", "value": 1234, "unit": "tokens"}, ...]
        self.progress = progress  # {"used": 1234, "total": 10000, "pct": 12.3}
        self.raw_response = raw_response


def fetch_endpoint(endpoint: dict, verify_ssl: bool = True) -> FetchResult:
    """
    对单个端点发起 HTTP 请求，解析 JSON 并提取字段。

    参数:
        endpoint: 端点配置 dict（name, url, method, headers, body, fields, progress_field）
        verify_ssl: 是否验证 SSL 证书

    返回:
        FetchResult: 包含解析后的字段和进度信息

    异常:
        FetchError: 请求失败、JSON 解析失败、字段提取失败
    """
    name = endpoint.get("name", "Unknown")
    url = resolve_url(endpoint["url"])
    method = endpoint.get("method", "GET").upper()
    headers = resolve_headers(endpoint.get("headers", {}))
    # PATCH 3.4.0：默认浏览器 UA（未显式设置时）——部分平台（如 opencode.ai）会被
    # Cloudflare 按 UA 拦截（error 1010），带浏览器 UA 才可正常访问
    if not any(k.lower() == "user-agent" for k in headers):
        headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
    headers.setdefault("Accept", "application/json")
    body = endpoint.get("body")
    verify = verify_ssl

    # 构建请求
    data = None
    if body:
        data = resolve_template(json.dumps(body) if isinstance(body, dict) else body)
        data = data.encode("utf-8")

    ssl_ctx = _SSL_CONTEXT_VERIFY if verify else _SSL_CONTEXT_NO_VERIFY

    try:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8")[:500]
        except Exception:
            pass
        raise FetchError(
            f"HTTP {e.code}: {e.reason}\n{body_text}",
            status_code=e.code
        )
    except urllib.error.URLError as e:
        raise FetchError(f"连接失败: {e.reason}")
    except Exception as e:
        raise FetchError(f"请求异常: {e}")

    # 解析 JSON
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise FetchError(f"JSON 解析失败: {e}\n原始响应 (前200字符): {raw[:200]}")

    # 提取字段
    field_defs = endpoint.get("fields", [])
    fields = []
    for fd in field_defs:
        label = fd.get("label", "?")
        jp = fd.get("jsonpath", "")
        unit = fd.get("unit", "")
        display = fd.get("display", "number")

        value = jsonpath_get(parsed, jp)
        if display == "percent" and isinstance(value, (int, float)):
            value = f"{value:.1f}%"
        elif display == "number" and isinstance(value, float):
            value = round(value, 2)

        fields.append({
            "label": label,
            "value": value,
            "unit": unit,
            "display": display,
        })

    # 进度信息（PATCH 3.4.0：支持数值型 total + 已用/剩余双百分比）
    progress = None
    pf = endpoint.get("progress_field")
    if pf:
        used = jsonpath_get(parsed, pf.get("used", "")) if isinstance(pf.get("used"), str) else pf.get("used")
        total = jsonpath_get(parsed, pf.get("total", "")) if isinstance(pf.get("total"), str) else pf.get("total")
        try:
            used_num = float(used) if used is not None else None
            total_num = float(total) if total is not None else None
        except (ValueError, TypeError):
            used_num = total_num = None
        if used_num is not None and total_num is not None and total_num > 0:
            pct = round(used_num / total_num * 100, 1)
            progress = {
                "used": used_num,
                "total": total_num,
                "pct": pct,                     # 已用百分比（兼容旧字段/网页进度条）
                "remain": round(max(0.0, 100.0 - pct), 1),   # 剩余百分比
            }

    return FetchResult(
        endpoint_name=name,
        fields=fields,
        progress=progress,
        raw_response=raw,
    )


def serialize_results(results):
    """把 ApiMonitorWorker 的 FetchResult 列表转成 Web 友好的 dict。"""
    out = []
    for i, r in enumerate(results or []):
        is_err = bool(r.fields and r.fields[0].get("label") == "错误")
        out.append({
            "index": i,
            "name": r.endpoint_name,
            "ok": not is_err,
            "error": r.fields[0].get("value") if is_err else "",
            "fields": r.fields,
            "progress": r.progress,
            "raw_response": (r.raw_response or "")[:400],
            "ts": time.strftime("%H:%M:%S"),
        })
    return out
