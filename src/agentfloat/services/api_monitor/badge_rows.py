# -*- coding: utf-8 -*-
"""余额显示框：模块化行构建（PATCH 3.5.1）

设置中 ``api_monitor.badge_rows`` 定义行（固定几行、每行显示内容与方式）：

    [
      {"title": "5h",  "source": "progress:remain_pct", "decimals": 0, "suffix": "%"},
      {"title": "周",  "source": "field:每周已用"},
      {"title": "余额", "source": "balance", "decimals": 2, "prefix": "¥"}
    ]

source 取值：
- ``balance``                该端点余额字段（优先「剩余额度」，否则首字段）
- ``progress:used_pct``      已用百分比
- ``progress:remain_pct``    剩余百分比
- ``progress:used`` / ``progress:total``
- ``field:<标签>``           按字段标签精确/包含匹配

未配置 ``badge_rows`` 时回退到单行兼容模式（``badge_mode``：balance / remaining / used）。
"""
import logging

_logger = logging.getLogger("AgentFloat")

_PCT_SOURCES = {"progress:used_pct", "progress:remain_pct"}


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value, decimals, prefix, suffix):
    """数值 → 文本（decimals 为 None 时保持原样）"""
    if value is None:
        return None
    num = _num(value)
    if num is None or decimals is None:
        return "%s%s%s" % (prefix, value, suffix)
    return "%s%.*f%s" % (prefix, int(decimals), num, suffix)


def _find_field(fields, label):
    if not label:
        return None
    for f in fields:
        if str(f.get("label")) == label:
            return f
    for f in fields:
        if label in str(f.get("label")):
            return f
    return None


def _balance_field(fields):
    return _find_field(fields, "剩余额度") or (fields[0] if fields else None)


def _result_for(spec_endpoint, results, names):
    if spec_endpoint is None:
        return results[0] if results else None
    if isinstance(spec_endpoint, int):
        return results[spec_endpoint] if 0 <= spec_endpoint < len(results) else None
    key = str(spec_endpoint)
    for i, name in enumerate(names):
        if name == key:
            return results[i]
    for i, name in enumerate(names):
        if key and key in str(name):
            return results[i]
    return results[0] if results else None


def _progress_value(prog, source):
    if not prog:
        return None
    if source == "progress:used_pct":
        return prog.get("pct")
    if source == "progress:remain_pct":
        return prog.get("remain")
    if source == "progress:used":
        return prog.get("used")
    if source == "progress:total":
        return prog.get("total")
    if source == "progress:remain_value":
        used, total = _num(prog.get("used")), _num(prog.get("total"))
        if used is None or total is None:
            return None
        return total - used
    return None


def _row_value(spec, result):
    """单行取值 → 文本（无法取值返回 None）"""
    source = str(spec.get("source") or "balance")
    decimals = spec.get("decimals", None)
    prefix = str(spec.get("prefix") or "")
    is_pct = source in _PCT_SOURCES or source.startswith("field_remain:")
    suffix = spec.get("suffix")
    if suffix is None:
        suffix = "%" if is_pct else ""
    suffix = str(suffix)

    if source == "balance":
        field = _balance_field(result.fields or [])
        if field is None:
            return None
        raw = field.get("value")
        if raw is None:
            return None
        user_prefix = str(spec.get("prefix") or "")
        user_suffix = spec.get("suffix", None)
        if decimals is None:
            decimals = 2
        if user_suffix is None and not user_prefix:
            suffix = str(field.get("unit", "") or "")     # 未自定义 → 沿用字段单位
        else:
            suffix = "" if user_suffix is None else str(user_suffix)
        return _fmt(raw, decimals, user_prefix, suffix)

    if source.startswith("progress:"):
        value = _progress_value(getattr(result, "progress", None), source)
        if value is None:
            return None
        if decimals is None:
            decimals = 0 if source in _PCT_SOURCES else 2
        return _fmt(value, decimals, prefix, suffix)

    if source.startswith("field_remain:"):
        field = _find_field(result.fields or [], source.split(":", 1)[1])
        if field is None:
            return None
        num = _num(str(field.get("value", "")).replace("%", "").strip())
        if num is None:
            return None
        if decimals is None:
            decimals = 0
        return _fmt(100.0 - num, decimals, prefix, suffix)

    if source.startswith("field:"):
        field = _find_field(result.fields or [], source.split(":", 1)[1])
        if field is None:
            return None
        raw = field.get("value")
        if raw is None:
            return None
        if decimals is None and _num(raw) is not None:
            decimals = 2
        return _fmt(raw, decimals, prefix, suffix)
    return None


def build_badge_rows(results, api_cfg):
    """构建余额显示框行：返回 (rows, is_low, is_error)

    rows: [(标题, 文本)]；无可用数据时返回 ``[("", "--")]``。
    """
    results = list(results or [])
    api_cfg = api_cfg or {}
    if not results:
        return [("", "--")], False, False

    first_fields = results[0].fields or []
    if first_fields and first_fields[0].get("label") == "错误":
        err = str(first_fields[0].get("value") or "查询失败")
        return [("", err)], False, True

    names = [getattr(r, "endpoint_name", None) for r in results]
    rows_cfg = api_cfg.get("badge_rows") or []

    if rows_cfg:
        rows = []
        low = False
        warn = _num(api_cfg.get("low_balance_warn", 5.0)) or 0.0
        for spec in rows_cfg:
            if not isinstance(spec, dict):
                continue
            result = _result_for(spec.get("endpoint"), results, names)
            if result is None:
                text = "--"
            else:
                text = _row_value(spec, result)
            text = "--" if text is None else str(text)
            rows.append((str(spec.get("title") or ""), text))
            value = _num(text.replace("%", "").replace(",", "").strip())
            if warn > 0 and value is not None and str(spec.get("source") or "").startswith("progress:remain"):
                low = low or value < 20.0
        return (rows or [("", "--")]), low, False

    # 兼容模式：单行（badge_mode：balance / remaining / used）——端点可覆盖全局
    r = results[0]
    from agentfloat.services.api_monitor.presets import badge_mode_for
    mode = badge_mode_for(getattr(r, "endpoint_name", None), api_cfg)
    prog = getattr(r, "progress", None)
    if mode in ("remaining", "used") and prog:
        pct = _num(prog.get("remain" if mode == "remaining" else "pct"))
        if pct is not None:
            low = bool(mode == "remaining" and pct < 20.0)
            return [("", "%d%%" % round(pct))], low, False
    field = _balance_field(r.fields or [])
    if field is None:
        return [("", "--")], False, False
    raw = field.get("value")
    unit = field.get("unit", "") or ""
    if raw is None:
        _logger.warning("[API] 字段 %r 返回 None", field.get("label", "?"))
        return [("", "N/A")], False, True
    num = _num(raw)
    if num is None:
        return [("", str(raw)[:24] + unit)], False, False
    return [("", "%.2f%s" % (num, unit))], (num < (api_cfg.get("low_balance_warn") or 5.0)), False
