# -*- coding: utf-8 -*-
"""AgentFloat — Agent 启动器（终端 / Web 双通道）"""
import ctypes
import os
import subprocess

from agentfloat.core.config import load_config
from agentfloat.core.logging_setup import _log
from agentfloat.core.paths import WORKSPACE_DIR
from agentfloat.core.registry import (
    build_agent_args, default_agents, get_primary_agent, resolve_command,
)
from agentfloat.services.dsh import launch_dsh_web


def launch_agent(agent, config=None):
    """通用 Agent 启动器：检测命令 → wt 启动 → cmd fallback"""
    if config is None:
        config = load_config()
    if not agent:
        _log().warning("launch_agent: agent 为空")
        return

    name = agent.get("name") or "Agent"

    # Web 启动器（如 DeepSeek Harness dsh）：后台启动服务并自动打开浏览器
    if (agent.get("launcher") or "terminal") == "web":
        _log().info("以 Web UI 模式启动 Agent: %s", name)
        launch_dsh_web(agent, config)
        return

    cmd_path, err = resolve_command(agent)
    if cmd_path is None:
        _log().warning("Agent 不可用: %s (%s)", name, err)
        try:
            ctypes.windll.user32.MessageBoxW(
                0,
                "未检测到 %s。\n\n%s\n\n请安装对应 CLI，或在「设置 → Agent 管理」中填写完整路径。" % (name, err),
                "AgentFloat — 命令未找到",
                0x00000030  # MB_ICONWARNING | MB_OK
            )
        except Exception:
            pass
        return

    mode = agent.get("launch_mode", "normal")
    args = build_agent_args(agent, mode)
    args[0] = cmd_path  # 使用解析后的真实路径

    working_dir = (agent.get("working_directory") or config.get("working_directory") or "").strip()
    if not working_dir or not os.path.isdir(working_dir):
        working_dir = os.environ.get("USERPROFILE", WORKSPACE_DIR)

    _log().info("启动 Agent [%s] 模式=%s 命令=%s", name, mode, args)
    try:
        subprocess.Popen(
            ["wt", "-d", working_dir, "--"] + args,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
    except Exception:
        _log().info("wt 不可用，使用 cmd start fallback")
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", name] + args,
                cwd=working_dir, creationflags=subprocess.CREATE_NO_WINDOW
            )
        except Exception as e:
            _log().error("启动 Agent [%s] 失败: %s", name, e)

def launch_claude_code(config=None):
    """兼容入口：启动主 Agent（默认 Claude Code）"""
    if config is None:
        config = load_config()
    launch_agent(get_primary_agent(config.get("agents", default_agents())), config)
