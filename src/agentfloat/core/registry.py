# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Agent 注册表与通用启动数据模型

内置 claude / codex 预设 + 用户自定义命令模板。
每个 Agent 字段：
  id / name / command / args / skip_permissions_arg /
  working_directory / launch_mode / icon_color / icon_char /
  check / primary / builtin / launcher / description

launcher:
  terminal — 在 Windows Terminal（wt）中启动命令行 Agent（默认）
  web      — 以后台服务方式启动并自动打开浏览器（如 DeepSeek Harness `dsh web`、`opencode serve`）
  app      — 直接启动桌面 GUI 应用（如 OpenCode Desktop，无终端窗口）

web 字段（launcher=web 时）：
  {"command": [...], "port": 端口, "url": "浏览器地址", "log_prefix": "日志名前缀"}
"""
import copy
import os
import shutil

BUILTIN_PRESETS = [
    {
        "id": "claude",
        "name": "Claude Code",
        "command": "claude",
        "args": [],
        "skip_permissions_arg": "--dangerously-skip-permissions",
        "working_directory": "",
        "launch_mode": "normal",
        "icon_color": "#D97757",
        "icon_char": "C",
        "check": "claude",
        "primary": True,
        "builtin": True,
        "launcher": "terminal",
        "description": "Anthropic Claude Code — 终端里的 Claude 编程智能体",
    },
    {
        "id": "codex",
        "name": "Codex CLI",
        "command": "codex",
        "args": [],
        "skip_permissions_arg": "--dangerously-skip-permissions",
        "working_directory": "",
        "launch_mode": "normal",
        "icon_color": "#10A37F",
        "icon_char": "X",
        "check": "codex",
        "primary": False,
        "builtin": True,
        "launcher": "terminal",
        "description": "OpenAI Codex CLI — 终端里的 Codex 编程智能体",
    },
    {
        "id": "pi",
        "name": "Pi Coding Agent",
        "command": "pi",
        "args": [],
        "skip_permissions_arg": "",
        "working_directory": "",
        "launch_mode": "normal",
        "icon_color": "#7C3AED",
        "icon_char": "P",
        "check": "pi",
        "primary": False,
        "builtin": True,
        "launcher": "terminal",
        "description": "pi.dev 的 Pi Coding Agent — 多模型终端编码智能体（Anthropic/OpenAI/Gemini/DeepSeek），无跳过权限参数，始终使用内置交互确认",
    },
    {
        "id": "opencode",
        "name": "OpenCode CLI",
        "command": "opencode",
        "args": ["--continue"],
        "skip_permissions_arg": "--auto",
        "working_directory": "",
        "launch_mode": "normal",
        "icon_color": "#2563EB",
        "icon_char": "O",
        "check": "opencode",
        "primary": False,
        "builtin": True,
        "launcher": "terminal",
        "description": "OpenCode CLI（v2 终端 TUI；默认 --continue 续接上次会话，可在设置中调整参数）",
    },
    {
        "id": "opencode-desktop",
        "name": "OpenCode Desktop",
        "command": r"%LOCALAPPDATA%\Programs\@opencodedesktop\OpenCode.exe",
        "args": [],
        "skip_permissions_arg": "",
        "working_directory": "",
        "launch_mode": "normal",
        "icon_color": "#0EA5E9",
        "icon_char": "D",
        "check": r"%LOCALAPPDATA%\Programs\@opencodedesktop\OpenCode.exe",
        "primary": False,
        "builtin": True,
        "launcher": "app",
        "description": "OpenCode 桌面版（Electron GUI；在设置 → Agent 管理里可一键设为主 Agent）",
    },
    {
        "id": "opencode-web",
        "name": "OpenCode Web",
        "command": "opencode",
        "args": ["serve", "--port", "4096"],
        "skip_permissions_arg": "",
        "working_directory": "",
        "launch_mode": "normal",
        "icon_color": "#38BDF8",
        "icon_char": "W",
        "check": "opencode",
        "primary": False,
        "builtin": True,
        "launcher": "web",
        "description": "OpenCode 网页模式（后台运行 opencode serve，自动打开 http://127.0.0.1:4096；可在浮球右键菜单终止）",
        "web": {
            "command": ["opencode", "serve", "--port", "4096"],
            "port": 4096,
            "url": "http://127.0.0.1:4096",
            "log_prefix": "opencode_web",
        },
    },
    {
        "id": "dsh",
        "name": "DeepSeek Harness",
        "command": "dsh",
        "args": [],
        "skip_permissions_arg": "",
        "working_directory": "",
        "launch_mode": "normal",
        "icon_color": "#4D6BFE",
        "icon_char": "D",
        "check": "dsh",
        "primary": False,
        "builtin": True,
        "launcher": "web",
        "description": "DeepSeek Harness（dsh）— DeepSeek 官方开源的全栈 AI 智能体（Web UI 模式：后台启动 dsh web 并自动打开浏览器）",
        "web": {
            "command": ["dsh", "web"],
            "port": 3080,
            "url": "http://127.0.0.1:3080",
            "log_prefix": "dsh",
        },
    },
]

DEFAULT_RADIAL_MENU = {
    "enabled": True,
    "trigger_mode": "both",          # hover / both（悬停通道；轮盘由按住外滑触发）
    "hold_select": True,             # 按住选环（轮盘/长按弹出后滑到扇区松手即执行）
    "hover_delay_ms": 180,
    "long_press_delay_ms": 300,
    "hold_launch_ms": 2000,          # PATCH 3.3.0：按住不动 2s → 默认启动（环形进度条）
    "move_delay_ms": 350,            # PATCH 3.3.0：超过该时长后再拖动 = 移动浮窗
    "wheel_enabled": True,           # PATCH 3.3.0：按住外滑唤出轮盘（游戏式）
    "radius": 120,
    # 扇区功能模块化：每个元素是一个动作 id（可用：
    #   agent:<id> 启动某 Agent / skills / api / settings / news / quit）
    # 空列表 = 自动（所有 Agent + 固定 4 项）
    "slot_count": 6,
    "slots": [],
}

DEFAULT_SKILLS = {
    "roots": [],
    "ai_tool": "codex exec",         # codex exec / claude -p
    "max_description_len": 160,
    "auto_translate_new_skills": True,   # 装完新 skill 自动触发翻译
}


def default_agents():
    """返回内置预设的深拷贝"""
    return copy.deepcopy(BUILTIN_PRESETS)


def normalize_agents(raw):
    """校验/补全 agents 列表结构；非法项剔除；至少保留一个 agent"""
    if not isinstance(raw, list) or not raw:
        raw = default_agents()
    out = []
    seen = set()
    for i, a in enumerate(raw):
        if not isinstance(a, dict):
            continue
        aid = str(a.get("id") or "agent_%d" % i).strip()
        if not aid or aid in seen:
            aid = "agent_%d" % i
        seen.add(aid)
        command = str(a.get("command") or "").strip()
        if not command:
            continue
        name = str(a.get("name") or aid).strip() or aid
        mode = a.get("launch_mode")
        if mode not in ("normal", "skip_permissions"):
            mode = "normal"
        launcher = a.get("launcher")
        if launcher not in ("terminal", "web", "app"):
            launcher = "terminal"
        item = {
            "id": aid,
            "name": name,
            "command": command,
            "args": [str(x) for x in (a.get("args") or [])],
            "skip_permissions_arg": str(a.get("skip_permissions_arg") or "").strip(),
            "working_directory": str(a.get("working_directory") or "").strip(),
            "launch_mode": mode,
            "icon_color": str(a.get("icon_color") or "#5B8DEF"),
            "icon_char": (str(a.get("icon_char") or (name[0] if name else "A"))[:1]).upper(),
            "check": str(a.get("check") or command).strip(),
            "primary": bool(a.get("primary")),
            "builtin": bool(a.get("builtin", False)),
            "launcher": launcher,
            "description": str(a.get("description") or ""),
        }
        web = a.get("web")
        if isinstance(web, dict) and web:
            item["web"] = copy.deepcopy(web)
        out.append(item)
    if not out:
        out = default_agents()
    if not any(a["primary"] for a in out):
        out[0]["primary"] = True
    return out


def get_primary_agent(agents):
    for a in agents:
        if a.get("primary"):
            return a
    return agents[0] if agents else None


def find_agent(agents, aid):
    for a in agents:
        if a.get("id") == aid:
            return a
    return None


def _is_windows_apps_path(path):
    """WindowsApps 包目录受系统保护，其中的 exe 常无法被第三方进程直接启动"""
    try:
        p = str(path).replace("/", "\\").lower()
    except Exception:
        return False
    return p.startswith("c:\\program files\\windowsapps\\")


def _find_windows_apps_mirror(cmd):
    """为 WindowsApps 内置 CLI 在 %LOCALAPPDATA% 下查找可运行的镜像副本。

    Codex 桌面版会把可运行的 codex.exe 放到
    %LOCALAPPDATA%\\OpenAI\\Codex\\bin\\<hash>\\codex.exe，
    该路径不在受保护目录内，可被正常启动（直接运行 WindowsApps 包内 exe 会报拒绝访问）。
    """
    name = (cmd or "").strip().lower()
    if name not in ("codex", "codex.exe"):
        return None
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "OpenAI", "Codex", "bin")
    if not os.path.isdir(base):
        return None
    try:
        hashes = sorted(os.listdir(base), reverse=True)  # 新版本哈希目录优先
    except OSError:
        return None
    for h in hashes:
        p = os.path.join(base, h, "codex.exe")
        if os.path.isfile(p):
            return p
    return None


def resolve_command(agent):
    """解析可执行命令路径。

    返回 (path_or_None, error_msg)。支持直接路径与 PATH 查找。
    """
    cmd = os.path.expandvars((agent.get("command") or "").strip())
    if not cmd:
        return None, "未配置命令"
    # 含路径分隔符或明确 .exe → 当作完整路径处理
    if os.path.sep in cmd or (cmd.lower().endswith(".exe")):
        if os.path.exists(cmd):
            return os.path.abspath(cmd), None
        return None, "命令路径不存在: %s" % cmd
    found = shutil.which(cmd)
    if found:
        if _is_windows_apps_path(found):
            mirror = _find_windows_apps_mirror(cmd)
            if mirror:
                return os.path.abspath(mirror), None
        return found, None
    return None, "未在 PATH 中检测到「%s」，请安装后重试或在设置中填写完整路径" % cmd


def build_agent_args(agent, mode=None):
    """构造启动参数列表（首个元素为命令本身）"""
    mode = mode or agent.get("launch_mode", "normal")
    args = [(agent.get("command") or "").strip()]
    args += [str(x) for x in (agent.get("args") or [])]
    if mode == "skip_permissions" and agent.get("skip_permissions_arg"):
        args.append(agent["skip_permissions_arg"])
    return args


def primary_launch_mode(agents):
    """主 Agent 的启动模式（设置页快捷开关用）"""
    p = get_primary_agent(agents)
    return p.get("launch_mode", "normal") if p else "normal"
