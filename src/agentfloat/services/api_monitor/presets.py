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


def deepseek_endpoint():
    """DeepSeek 余额（官方接口，返回余额字符串，单位元）"""
    return {
        "name": "DeepSeek",
        "url": "https://api.deepseek.com/user/balance",
        "platform_url": "https://platform.deepseek.com/usage",
        "method": "GET",
        "headers": {
            "Authorization": "Bearer {{env:DEEPSEEK_API_KEY}}",
            "Content-Type": "application/json",
        },
        "body": None,
        "fields": [
            {"label": "剩余额度", "jsonpath": "$.balance_infos[0].total_balance", "unit": "元", "display": "number"},
            {"label": "赠送余额", "jsonpath": "$.balance_infos[0].granted_balance", "unit": "元", "display": "number"},
            {"label": "充值余额", "jsonpath": "$.balance_infos[0].topped_up_balance", "unit": "元", "display": "number"},
        ],
        "progress_field": None,
        "preset": "deepseek",
    }


def moonshot_endpoint():
    """Moonshot（Kimi）余额（官方接口）"""
    return {
        "name": "Moonshot",
        "url": "https://api.moonshot.cn/v1/users/me/balance",
        "platform_url": "https://platform.moonshot.cn/console/info",
        "method": "GET",
        "headers": {
            "Authorization": "Bearer {{env:MOONSHOT_API_KEY}}",
            "Content-Type": "application/json",
        },
        "body": None,
        "fields": [
            {"label": "剩余额度", "jsonpath": "$.data.available_balance", "unit": "元", "display": "number"},
            {"label": "代金券", "jsonpath": "$.data.voucher_balance", "unit": "元", "display": "number"},
            {"label": "现金余额", "jsonpath": "$.data.cash_balance", "unit": "元", "display": "number"},
        ],
        "progress_field": None,
        "preset": "moonshot",
    }


def siliconflow_endpoint():
    """SiliconFlow（硅基流动）余额（官方接口）"""
    return {
        "name": "SiliconFlow",
        "url": "https://api.siliconflow.cn/v1/user/info",
        "platform_url": "https://cloud.siliconflow.cn/account/ak",
        "method": "GET",
        "headers": {
            "Authorization": "Bearer {{env:SILICONFLOW_API_KEY}}",
            "Content-Type": "application/json",
        },
        "body": None,
        "fields": [
            {"label": "剩余额度", "jsonpath": "$.data.totalBalance", "unit": "元", "display": "number"},
            {"label": "赠送余额", "jsonpath": "$.data.balance", "unit": "元", "display": "number"},
            {"label": "充值余额", "jsonpath": "$.data.chargeBalance", "unit": "元", "display": "number"},
        ],
        "progress_field": None,
        "preset": "siliconflow",
    }


def openrouter_endpoint():
    """OpenRouter 信用额度（credits 接口；余额 = total_credits - total_usage，用进度表示）"""
    return {
        "name": "OpenRouter",
        "url": "https://openrouter.ai/api/v1/credits",
        "platform_url": "https://openrouter.ai/settings/credits",
        "method": "GET",
        "headers": {
            "Authorization": "Bearer {{env:OPENROUTER_API_KEY}}",
            "Content-Type": "application/json",
        },
        "body": None,
        "fields": [
            {"label": "总额度", "jsonpath": "$.data.total_credits", "unit": "$", "display": "number"},
            {"label": "已用额度", "jsonpath": "$.data.total_usage", "unit": "$", "display": "number"},
        ],
        "progress_field": {"used": "$.data.total_usage", "total": "$.data.total_credits"},
        "preset": "openrouter",
    }


PRESETS = [
    {
        "id": "opencode-go",
        "name": "OpenCode Go（订阅用量）",
        "description": "滚动 5 小时 / 每周 / 每月用量（官方接口，查询不消耗额度；Key 取环境变量 OPENCODE_GO_API_KEY）",
        "endpoint": opencode_go_endpoint(),
    },
    {
        "id": "deepseek",
        "name": "DeepSeek（余额）",
        "description": "官方余额接口（Key 取环境变量 DEEPSEEK_API_KEY）",
        "endpoint": deepseek_endpoint(),
    },
    {
        "id": "moonshot",
        "name": "Kimi / Moonshot（余额）",
        "description": "官方余额接口（Key 取环境变量 MOONSHOT_API_KEY）",
        "endpoint": moonshot_endpoint(),
    },
    {
        "id": "siliconflow",
        "name": "SiliconFlow（余额）",
        "description": "官方账户信息接口（Key 取环境变量 SILICONFLOW_API_KEY）",
        "endpoint": siliconflow_endpoint(),
    },
    {
        "id": "openrouter",
        "name": "OpenRouter（额度）",
        "description": "credits 接口：总额度/已用额度（Key 取环境变量 OPENROUTER_API_KEY）",
        "endpoint": openrouter_endpoint(),
    },
]


# ── 余额显示行预设（PATCH 3.5.2：一键为显示框添加平台行）──────────
ROW_PRESETS = [
    {
        "id": "opencode-go",
        "name": "OpenCode Go",
        "endpoint": "OpenCode Go",
        "rows": [
            {"title": "5h", "source": "progress:remain_pct", "decimals": 0, "suffix": "%"},
            {"title": "周", "source": "field_remain:每周已用", "decimals": 0, "suffix": "%"},
            {"title": "月", "source": "field_remain:每月已用", "decimals": 0, "suffix": "%"},
        ],
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "endpoint": "DeepSeek",
        "rows": [
            {"title": "余额", "source": "balance"},
        ],
    },
    {
        "id": "moonshot",
        "name": "Kimi",
        "endpoint": "Moonshot",
        "rows": [
            {"title": "余额", "source": "balance"},
        ],
    },
    {
        "id": "siliconflow",
        "name": "SiliconFlow",
        "endpoint": "SiliconFlow",
        "rows": [
            {"title": "余额", "source": "balance"},
        ],
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "endpoint": "OpenRouter",
        "rows": [
            {"title": "余额", "source": "progress:remain_value", "decimals": 2, "prefix": "$"},
            {"title": "已用", "source": "progress:used_pct", "decimals": 1, "suffix": "%"},
        ],
    },
    {
        "id": "generic",
        "name": "通用（余额 + 已用%）",
        "endpoint": None,
        "rows": [
            {"title": "余额", "source": "balance"},
            {"title": "已用", "source": "progress:used_pct", "decimals": 1, "suffix": "%"},
        ],
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
