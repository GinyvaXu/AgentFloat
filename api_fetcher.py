"""
API 用量监控 — HTTP 请求 + 响应解析
使用标准库 urllib，无需额外依赖
"""
import json
import urllib.request
import urllib.error
import ssl
from api_monitor_config import resolve_url, resolve_headers, resolve_template, jsonpath_get


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

    # 进度信息
    progress = None
    pf = endpoint.get("progress_field")
    if pf:
        used = jsonpath_get(parsed, pf.get("used", ""))
        total = jsonpath_get(parsed, pf.get("total", ""))
        if used is not None and total is not None and total > 0:
            try:
                used_num = float(used)
                total_num = float(total)
                pct = round(used_num / total_num * 100, 1)
                progress = {"used": used_num, "total": total_num, "pct": pct}
            except (ValueError, TypeError):
                pass

    return FetchResult(
        endpoint_name=name,
        fields=fields,
        progress=progress,
        raw_response=raw,
    )
