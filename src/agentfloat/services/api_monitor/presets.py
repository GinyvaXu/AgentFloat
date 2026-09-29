# -*- coding: utf-8 -*-
"""API 监控内置预设（PATCH 3.4.0）

OpenCode Go：官方订阅用量接口 ``GET https://opencode.ai/zen/go/v1/usage``
- 鉴权：``Authorization: Bearer <OPENCODE_GO_API_KEY>``（环境变量，模板注入）
- Cloudflare 按 UA 拦截（error 1010）：必须携带浏览器 User-Agent
- 返回 ``usage.rolling/weekly/monthly.percent``（percent = 已用），查询不消耗套餐额度
- 角标默认显示「滚动窗口剩余%」（badge_mode=remaining）
"""
OPENCODE_GO_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


def opencode_go_endpoint():
    """OpenCode Go 订阅用量端点定义（深拷贝返回，避免被调用方修改）"""
    return {
        "name": "OpenCode Go",
        "url": "https://opencode.ai/zen/go/v1/usage",
        "platform_url": "https://opencode.ai/",
        "method": "GET",
        "headers": {
            "Authorization": "Bearer {{env:OPENCODE_GO_API_KEY}}",
            "User-Agent": OPENCODE_GO_UA,
            "Accept": "application/json",
        },
        "body": None,
        "fields": [
            {"label": "滚动 5h 已用", "jsonpath": "$.usage.rolling.percent",
             "unit": "%", "display": "percent"},
            {"label": "每周已用", "jsonpath": "$.usage.weekly.percent",
             "unit": "%", "display": "percent"},
            {"label": "每月已用", "jsonpath": "$.usage.monthly.percent",
             "unit": "%", "display": "percent"},
        ],
        "progress_field": {"used": "$.usage.rolling.percent", "total": 100},
        "badge_mode": "remaining",     # 角标：滚动窗口剩余%
        "preset": "opencode-go",
    }


PRESETS = [
    {
        "id": "opencode-go",
        "name": "OpenCode Go（订阅用量）",
        "description": "滚动 5 小时 / 每周 / 每月用量（官方接口，查询不消耗额度；Key 取环境变量 OPENCODE_GO_API_KEY）",
        "endpoint": opencode_go_endpoint(),
    },
]


def badge_mode_for(endpoint_name, api_cfg):
    """解析某端点的角标显示模式（端点覆盖 > 全局默认 > 金额模式）"""
    mode = (api_cfg or {}).get("badge_mode") or "balance"
    try:
        for ep in (api_cfg or {}).get("endpoints") or []:
            if ep.get("name") == endpoint_name and ep.get("badge_mode"):
                return str(ep["badge_mode"])
    except Exception:  # noqa: BLE001
        pass
    return str(mode)
