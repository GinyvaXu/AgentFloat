# -*- coding: utf-8 -*-
"""目录核对 CLI（A-M1b，v0.1）

用法：
    python tools/catalog_cli.py verify            # 表格
    python tools/catalog_cli.py verify --json     # 机器可读

核对内容：npm 条目查询 registry 最新版；winget/pip/script/download 标注「需人工核对」。
只读，不修改任何数据。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from agentfloat.services.catalog.builtin import builtin_specs  # noqa: E402
from agentfloat.services.catalog.installer import install_type  # noqa: E402
from agentfloat.services.catalog.merge import merge_layers  # noqa: E402

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _run(cmd, timeout=10):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, creationflags=CREATE_NO_WINDOW)
        return (p.stdout or "").strip().splitlines()[-1] if p.stdout else ""
    except Exception:  # noqa: BLE001
        return ""


def verify_rows(specs, runner=_run):
    """返回 [{id, type, package, latest, note}]；runner 可注入（测试）。"""
    rows = []
    for spec in specs:
        kind = install_type(spec)
        pkg = spec.install[0].package_or_url if spec.install else ""
        latest, note = "", ""
        if kind == "npm":
            latest = runner("npm view %s version" % pkg)
            note = "ok" if latest else "npm 查询失败（网络或包名）"
        else:
            note = "需人工核对（%s）" % (kind or "无安装方式")
        rows.append({"id": spec.id, "name": spec.name, "type": kind,
                     "package": pkg, "latest": latest, "note": note})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(prog="catalog_cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_verify = sub.add_parser("verify", help="核对目录包名与最新版")
    p_verify.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    specs = merge_layers(builtin_specs())
    rows = verify_rows([specs.get(s["id"]) for s in builtin_specs() if specs.get(s["id"])])
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    print("%-14s %-9s %-32s %-10s %s" % ("id", "type", "package", "latest", "note"))
    for r in rows:
        print("%-14s %-9s %-32s %-10s %s" % (
            r["id"], r["type"], r["package"][:32], r["latest"] or "-", r["note"]))
    bad = [r for r in rows if r["type"] == "npm" and not r["latest"]]
    print("\n共 %d 条；npm 查询失败 %d 条；其余需人工核对 %d 条" % (
        len(rows), len(bad), len([r for r in rows if r["type"] != "npm"])))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
