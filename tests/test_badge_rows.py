# -*- coding: utf-8 -*-
"""余额显示框（PATCH 3.5.1）：模块化行构建 + 小框尺寸/位置"""

from types import SimpleNamespace


def _result(name="OpenCode Go", fields=None, progress=None):
    return SimpleNamespace(endpoint_name=name, fields=fields or [], progress=progress)


_GO_PROG = {"used": 8.0, "total": 100.0, "pct": 8.0, "remain": 92.0}


def test_modular_rows_progress_and_field():
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    res = [_result(
        fields=[{"label": "每周已用", "value": "14.0%", "unit": ""}],
        progress=_GO_PROG)]
    cfg = {"badge_rows": [
        {"title": "5h", "source": "progress:remain_pct", "decimals": 0},
        {"title": "周", "source": "field:每周已用"},
    ], "low_balance_warn": 20}
    rows, low, err = build_badge_rows(res, cfg)
    assert rows == [("5h", "92%"), ("周", "14.0%")]
    assert low is False and err is False


def test_modular_rows_low_warning():
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    res = [_result(progress={"used": 90.0, "total": 100.0, "pct": 90.0, "remain": 10.0})]
    cfg = {"badge_rows": [{"title": "5h", "source": "progress:remain_pct", "decimals": 0}]}
    rows, low, err = build_badge_rows(res, cfg)
    assert rows == [("5h", "10%")] and low is True


def test_modular_rows_balance_uses_unit():
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    res = [_result(fields=[{"label": "剩余额度", "value": 12.3456, "unit": "¥"}])]
    rows, _low, _err = build_badge_rows(res, {"badge_rows": [{"title": "余额", "source": "balance"}]})
    assert rows == [("余额", "12.35¥")]
    rows2, _low2, _err2 = build_badge_rows(
        res, {"badge_rows": [{"title": "余额", "source": "balance", "prefix": "$", "decimals": 1}]})
    assert rows2 == [("余额", "$12.3")]


def test_modular_rows_multi_endpoint_select():
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    a = _result("A", fields=[{"label": "剩余额度", "value": 5, "unit": "元"}])
    b = _result("B", fields=[{"label": "剩余额度", "value": 9, "unit": "元"}])
    cfg = {"badge_rows": [
        {"title": "A", "source": "balance", "endpoint": "A"},
        {"title": "B", "source": "balance", "endpoint": 1},
    ]}
    rows, _low, _err = build_badge_rows([a, b], cfg)
    assert rows == [("A", "5.00元"), ("B", "9.00元")]


def test_error_result_passthrough():
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    res = [_result(fields=[{"label": "错误", "value": "HTTP 401"}])]
    rows, low, err = build_badge_rows(res, {"badge_rows": [{"title": "x", "source": "balance"}]})
    assert rows == [("", "HTTP 401")] and err is True and low is False


def test_compat_single_line_modes():
    from agentfloat.services.api_monitor.badge_rows import build_badge_rows
    res = [_result(progress=_GO_PROG)]
    # 端点覆盖（OpenCode Go 预设 badge_mode=remaining）
    cfg = {"endpoints": [{"name": "OpenCode Go", "badge_mode": "remaining"}], "badge_mode": "balance"}
    assert build_badge_rows(res, cfg)[0] == [("", "92%")]
    # 金额模式
    res2 = [_result(fields=[{"label": "剩余额度", "value": 8.5, "unit": "元"}])]
    assert build_badge_rows(res2, {"badge_mode": "balance"})[0] == [("", "8.50元")]


def test_badge_widget_rows_and_position(qapp):
    from PyQt5.QtWidgets import QWidget
    from agentfloat.services.api_monitor.badge import ApiBalanceBadge
    pf = QWidget()
    pf.setGeometry(500, 400, 52, 52)
    badge = ApiBalanceBadge(parent_float=pf)
    badge.set_rows([("5h", "92%"), ("周", "14.0%")])
    assert badge.width() >= 60 and badge.height() >= 30
    badge.set_position_mode("top")
    badge.sync_position()
    assert badge.y() < pf.y()
    badge.set_position_mode("bottom")
    badge.sync_position()
    assert badge.y() >= pf.y() + pf.height()
    badge.set_offset(12, 8)
    assert badge.offset() == (12, 8)
    badge.deleteLater()


def test_badge_update_balance_compat(qapp):
    from agentfloat.services.api_monitor.badge import ApiBalanceBadge
    badge = ApiBalanceBadge(parent_float=None)
    badge.set_warn_threshold(5.0)
    badge.update_balance("3.20元", value=3.2)
    assert badge._is_low is True
    badge.update_balance("20.00元", value=20.0)
    assert badge._is_low is False
    badge.deleteLater()
