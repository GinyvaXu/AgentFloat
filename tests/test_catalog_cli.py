# -*- coding: utf-8 -*-
"""catalog_cli.verify 纯逻辑测试（不联网）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

from catalog_cli import verify_rows  # noqa: E402
from agentfloat.services.catalog.builtin import builtin_specs  # noqa: E402
from agentfloat.services.catalog.merge import merge_layers  # noqa: E402


def specs():
    m = merge_layers(builtin_specs())
    return [m.get(s["id"]) for s in builtin_specs() if m.get(s["id"])]


def test_npm_rows_query_latest():
    def fake(cmd, timeout=10):
        assert cmd.startswith("npm view ")
        return "9.9.9"

    rows = verify_rows(specs(), runner=fake)
    npm_rows = [r for r in rows if r["type"] == "npm"]
    assert npm_rows and all(r["latest"] == "9.9.9" and r["note"] == "ok" for r in npm_rows)


def test_non_npm_rows_are_manual():
    rows = verify_rows(specs(), runner=lambda *a, **k: "1.0.0")
    others = [r for r in rows if r["type"] != "npm"]
    assert others and all("需人工核对" in r["note"] for r in others)


def test_npm_failure_note():
    rows = verify_rows(specs(), runner=lambda *a, **k: "")
    npm_rows = [r for r in rows if r["type"] == "npm"]
    assert npm_rows and all("npm 查询失败" in r["note"] for r in npm_rows)
