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
from agentfloat.services.webagent import start as start_web_agent

# PATCH 3.5.1：记录「由本应用启动」的进程 PID（退出清理只针对这些进程）
LAUNCHED_PIDS = []


def launch_agent(agent, config=None):
    """通用 Agent 启动器：终端 / Web / 桌面应用 三通道

    - terminal：Windows Terminal（wt）启动，cmd 兜底
    - web     ：后台服务 + 自动打开浏览器（dsh web / opencode serve，可终止）
    - app     ：直接启动桌面 GUI 应用（如 OpenCode Desktop）
    """
    if config is None:
        config = load_config()
    if not agent:
        _log().warning("launch_agent: agent 为空")
        return

    name = agent.get("name") or "Agent"
    launcher = agent.get("launcher") or "terminal"

    # Web 启动器：后台服务 + 自动打开浏览器（PATCH 3.1.0 通用化）
    if launcher == "web":
        _log().info("以 Web UI 模式启动 Agent: %s", name)
        start_web_agent(agent, config)
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

    working_dir = (agent.get("working_directory") or config.get("working_directory") or "").strip()
    if not working_dir or not os.path.isdir(working_dir):
        working_dir = os.environ.get("USERPROFILE", WORKSPACE_DIR)

    # 桌面应用：无终端窗口，后台直接启动
    if launcher == "app":
        _log().info("启动桌面 Agent [%s] 命令=%s 工作目录=%s", name, cmd_path, working_dir)
        try:
            proc = subprocess.Popen(
                [cmd_path], cwd=working_dir,
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            LAUNCHED_PIDS.append(proc.pid)     # PATCH 3.5.1：仅记录本应用启动的 PID
        except Exception as e:  # noqa: BLE001
            _log().error("启动桌面 Agent [%s] 失败: %s", name, e)
        return

    mode = agent.get("launch_mode", "normal")
    args = build_agent_args(agent, mode)
    args[0] = cmd_path  # 使用解析后的真实路径

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
