# -*- coding: utf-8 -*-
"""`af progress` 命令行：与 MCP / Qt 共用同一份进度状态。"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import store


def _session(args) -> str:
    return args.session or os.environ.get("AGENTFLOAT_PROGRESS_SESSION") or store.DEFAULT_SESSION


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(prog="af progress", description="AgentFloat 进度总线")
    parser.add_argument("--session", default="", help="会话 ID（默认 default）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="声明计划")
    p_plan.add_argument("--project", default="", help="项目名")
    p_plan.add_argument("--title", default="", help="任务标题")
    p_plan.add_argument("--steps", default="", help="步骤标题，逗号分隔")
    p_plan.add_argument("--window", default="", help="对应窗口标题（用于聚焦）")
    p_plan.add_argument("--source", default="cli")

    p_step = sub.add_parser("step", help="开始/更新当前步骤")
    p_step.add_argument("--title", default="", help="步骤标题")
    p_step.add_argument("--id", default="", help="步骤 ID")

    sub.add_parser("done", help="完成当前步骤并标记任务完成")
    sub.add_parser("next", help="完成当前步骤并进入下一步")

    p_fail = sub.add_parser("fail", help="标记失败")
    p_fail.add_argument("--error", default="", help="错误信息")

    p_need = sub.add_parser("need-input", help="等待用户输入")
    p_need.add_argument("--question", default="", help="需要确认的问题")

    sub.add_parser("cancel", help="取消任务")
    sub.add_parser("list", help="列出所有会话")
    p_show = sub.add_parser("show", help="查看当前会话")
    p_show.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    sid = _session(args)

    try:
        if args.command == "plan":
            steps = [x.strip() for x in str(args.steps or "").split(",") if x.strip()]
            data = store.update(sid, {"action": "plan", "project": args.project,
                                      "title": args.title, "steps": steps,
                                      "window": getattr(args, "window", ""),
                                      "source": args.source})
        elif args.command == "step":
            data = store.update(sid, {"action": "step", "title": args.title, "id": args.id})
        elif args.command == "done":
            data = store.update(sid, {"action": "done"})
        elif args.command == "next":
            data = store.update(sid, {"action": "next"})
        elif args.command == "fail":
            data = store.update(sid, {"action": "fail", "error": args.error})
        elif args.command == "need-input":
            data = store.update(sid, {"action": "need_input", "question": args.question})
        elif args.command == "cancel":
            data = store.update(sid, {"action": "cancel"})
        elif args.command == "list":
            data = store.list_sessions()
        else:
            data = store.load(sid) or {}
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    except OSError as exc:
        # 两个进程写同一 session 时可能短暂 PermissionError：给可读错误而不是 traceback
        print(json.dumps({"ok": False, "error": "进度写入失败：%s" % exc},
                         ensure_ascii=False))
        return 1

    print(json.dumps({"ok": True, "data": data}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
