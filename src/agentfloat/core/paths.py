# -*- coding: utf-8 -*-
"""AgentFloat — 路径与运行环境解析（源码 / PyInstaller 冻结双模式）

配置目录规则（与历史行为一致）：
- 打包运行：%APPDATA%/AgentFloat（用户数据与程序分离）
- 源码运行：项目根目录（便于开发调试）
"""
import os
import sys

_IS_FROZEN = getattr(sys, "frozen", False)
# Debug 版检测：PyInstaller --console 打包时 sys.stdout 可用（仅 debug 构建启用）
_IS_DEBUG = _IS_FROZEN and sys.stdout is not None

# 源码布局：<root>/src/agentfloat/core/paths.py → 项目根
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
SCRIPT_DIR = PROJECT_DIR            # 兼容旧命名（旧代码以脚本目录为项目根）
WORKSPACE_DIR = os.path.dirname(PROJECT_DIR)


def _resolve_path(*parts):
    """解析随包资源路径（assets / VERSION / web），兼容冻结模式。

    修复历史问题：旧实现开发模式回退到「项目根上一级」，导致 dev 下
    icon 资源永远解析不到而走降级绘制；现统一回退到项目根。
    """
    if _IS_FROZEN:
        base = sys._MEIPASS
    else:
        base = PROJECT_DIR
    return os.path.join(base, *parts)


ICO_PATH = _resolve_path("assets", "agent_float_icon.ico")
PNG_PATH = _resolve_path("assets", "agent_float_icon.png")


def config_dir():
    """配置/数据目录（冻结 → %APPDATA%/AgentFloat；源码 → 项目根）"""
    if _IS_FROZEN:
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "AgentFloat")
    return PROJECT_DIR


def config_path():
    d = config_dir()
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "config.json")


CONFIG_PATH = config_path()
# 旧配置路径（用于自动迁移）
_OLD_CONFIG_PATH = os.path.join(PROJECT_DIR, "launcher_config.json")


def version_path():
    """VERSION 文件路径（唯一版本号来源，随包分发）"""
    return _resolve_path("VERSION")


def web_dir():
    """定位前端目录 web/：兼容源码运行与 PyInstaller 冻结模式。"""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "web"))
    candidates.append(os.path.join(os.path.dirname(sys.executable), "web"))
    candidates.append(os.path.join(PROJECT_DIR, "web"))
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, "index.html")):
            return cand
    return candidates[-1]
