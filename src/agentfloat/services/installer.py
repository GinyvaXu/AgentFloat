# -*- mode: python ; coding: utf-8 -*-
"""AgentFloat — Agent 下载安装服务（设置页「Agent 安装」模块后端）

支持在 Web 设置中安装 / 升级 / 卸载内置 Agent：
- claude : @anthropic-ai/claude-code      （npm 全局安装）
- codex  : @openai/codex                  （npm 全局安装）
- pi     : @earendil-works/pi-coding-agent（npm 全局安装）
- dsh    : @deepseek-ai/dsh               （npm 全局安装）

特性：
- 状态检测：命令是否在 PATH、是否已安装、已安装版本（优先用 `npm list -g`）
- 后台安装线程：不阻塞 Web API，进度日志逐行收集，可轮询 / 订阅
- 国内镜像优先：registry.npmmirror.com，失败自动回退官方 registry.npmjs.org
- 卸载：npm uninstall -g，清理 PATH 残留检测
"""
from __future__ import annotations

import copy
import logging
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("AgentFloat.AgentInstaller")

# ── 内置 Agent 安装清单 ──────────────────────────────
# 每个条目：agent id / 显示名 / npm 包名 / 安装后 PATH 命令 / 描述 / 官网
AGENT_INSTALLERS = [
    {
        "id": "claude",
        "name": "Claude Code",
        "package": "@anthropic-ai/claude-code",
        "command": "claude",
        "icon_color": "#D97757",
        "icon_char": "C",
        "description": "Anthropic 官方终端编程智能体，与 Claude 深度集成",
        "homepage": "https://docs.anthropic.com/en/docs/claude-code",
    },
    {
        "id": "codex",
        "name": "Codex CLI",
        "package": "@openai/codex",
        "command": "codex",
        "icon_color": "#10A37F",
        "icon_char": "X",
        "description": "OpenAI 官方终端编程智能体（支持 GPT 系列模型）",
        "homepage": "https://developers.openai.com/codex/",
    },
    {
        "id": "pi",
        "name": "Pi Coding Agent",
        "package": "@earendil-works/pi-coding-agent",
        "command": "pi",
        "icon_color": "#7C3AED",
        "icon_char": "P",
        "description": "pi.dev 多模型终端编码智能体（Anthropic / OpenAI / Gemini / DeepSeek）",
        "homepage": "https://pi.dev",
    },
    {
        "id": "dsh",
        "name": "DeepSeek Harness",
        "package": "@deepseek-ai/dsh",
        "command": "dsh",
        "icon_color": "#4D6BFE",
        "icon_char": "D",
        "description": "DeepSeek 官方开源全栈 AI 智能体（Web UI 模式）",
        "homepage": "https://github.com/deepseek-ai/DeepSeek-Harness",
    },
]

# npm 镜像候选（按优先级）
NPM_REGISTRIES = [
    "https://registry.npmmirror.com",
    "https://registry.npmjs.org",
]

# ── 状态存储（进程内单例）────────────────────────────
# status[id] = {"phase": idle/running/done/error, "action": install/uninstall/upgrade,
#               "message": str, "logs": [str], "installed": bool, "version": str,
#               "started_at": float}
_STATUS = {}
_LOCK = threading.Lock()


def _get_status(aid):
    with _LOCK:
        return dict(_STATUS.get(aid) or {"phase": "idle", "action": "", "message": "", "logs": [],
                                         "installed": False, "version": "", "started_at": 0.0})


def _set_status(aid, **kw):
    with _LOCK:
        s = _STATUS.setdefault(aid, {"phase": "idle", "action": "", "message": "", "logs": [],
                                     "installed": False, "version": "", "started_at": 0.0})
        s.update(kw)
        return dict(s)


def _append_log(aid, line):
    with _LOCK:
        s = _STATUS.setdefault(aid, {"phase": "idle", "action": "", "message": "", "logs": [],
                                     "installed": False, "version": "", "started_at": 0.0})
        s["logs"].append(line)
        if len(s["logs"]) > 400:
            s["logs"] = s["logs"][-400:]


# ── 工具函数 ─────────────────────────────────────────
def _which(cmd):
    try:
        return shutil.which(cmd)
    except Exception:  # noqa: BLE001
        return None


def _npm_bin():
    """返回可用的 npm 可执行文件（npm 或 npm.cmd）。"""
    for name in ("npm", "npm.cmd"):
        p = _which(name)
        if p:
            return p
    return None


def _installed_version(package):
    """用 `npm list -g <pkg>` 读取已安装版本；未安装返回 None。"""
    npm = _npm_bin()
    if not npm:
        return None
    try:
        out = subprocess.run(
            [npm, "list", "-g", package, "--depth=0"],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        for line in (out or "").splitlines():
            line = line.strip()
            if package in line and "@" in line.split(package)[-1]:
                ver = line.split("@")[-1].strip()
                if ver and ver[0].isdigit():
                    return ver
    except Exception:  # noqa: BLE001
        pass
    return None


def _command_version(cmd):
    """尝试运行 `<cmd> --version` 读取版本；失败返回 None。"""
    p = _which(cmd)
    if not p:
        return None
    try:
        out = subprocess.run(
            [cmd, "--version"], capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        txt = (out.stdout or out.stderr or "").strip().splitlines()
        return (txt[0].strip()[:40] if txt else None) or None
    except Exception:  # noqa: BLE001
        return None


def _detect_one(spec):
    """探测单个 Agent 的当前状态（供并行调用）"""
    aid = spec["id"]
    cmd = spec["command"]
    path = _which(cmd)
    ver = _command_version(cmd) or _installed_version(spec["package"]) or ""
    st = _get_status(aid)
    return {
        "id": aid,
        "name": spec["name"],
        "package": spec["package"],
        "command": cmd,
        "icon_color": spec["icon_color"],
        "icon_char": spec["icon_char"],
        "description": spec["description"],
        "homepage": spec["homepage"],
        "found": bool(path),
        "path": path or "",
        "version": ver,
        "phase": st.get("phase", "idle"),
        "action": st.get("action", ""),
        "message": st.get("message", ""),
        "logs": st.get("logs", []),
        "busy": st.get("phase") == "running",
    }


_DETECT_TTL_S = 5.0                       # 结果缓存窗口（Web 页 1.5s 轮询会被合并）
_detect_cache = {"ts": 0.0, "data": None}
_detect_lock = threading.Lock()


def invalidate_detect_cache():
    """安装/卸载动作开始后调用：让下一次探测立即反映最新状态"""
    with _detect_lock:
        _detect_cache["ts"] = 0.0
        _detect_cache["data"] = None


def detect_all(force=False):
    """返回所有 Agent 的当前状态。

    P3 优化：并行探测（4 个 CLI 版本查询并发）+ 5 秒 TTL 缓存，
    避免 Web 安装页轮询造成请求堆积（原先单次约 7-8 秒）。
    """
    now = time.time()
    with _detect_lock:
        if (not force) and _detect_cache["data"] is not None \
                and now - _detect_cache["ts"] < _DETECT_TTL_S:
            return copy.deepcopy(_detect_cache["data"])
    with ThreadPoolExecutor(max_workers=max(2, len(AGENT_INSTALLERS))) as ex:
        result = list(ex.map(_detect_one, AGENT_INSTALLERS))
    with _detect_lock:
        _detect_cache["ts"] = time.time()
        _detect_cache["data"] = result
    return copy.deepcopy(result)


def _registry_args():
    """按优先级探测可用的 npm registry，返回 [--registry=url] 列表（失败回退官方）。"""
    for reg in NPM_REGISTRIES:
        try:
            r = subprocess.run(
                ["npm", "ping", "--registry", reg],
                capture_output=True, text=True, timeout=12,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode == 0:
                return ["--registry", reg]
        except Exception:  # noqa: BLE001
            continue
    # 全部失败：不传 --registry，用 npm 默认配置
    return []


def install_agent(aid, action="install"):
    """后台安装 / 升级 Agent。action: install / upgrade。"""
    spec = next((s for s in AGENT_INSTALLERS if s["id"] == aid), None)
    if spec is None:
        return False, "未知 Agent: %s" % aid
    with _LOCK:
        cur = _STATUS.get(aid)
        if cur and cur.get("phase") == "running":
            return False, "该 Agent 正在安装中，请稍候"
    npm = _npm_bin()
    if not npm:
        _set_status(aid, phase="error", action=action, message="未检测到 npm，请先安装 Node.js",
                    logs=["错误: 未检测到 npm / Node.js"])
        return False, "未检测到 npm"

    def _run():
        _set_status(aid, phase="running", action=action,
                    message="正在安装 %s…" % spec["name"], started_at=time.time())
        _append_log(aid, "> npm %s -g %s" % ("install" if action != "upgrade" else "install -g --force", spec["package"]))
        args = [npm, "install", "-g", spec["package"]]
        if action == "upgrade":
            args = [npm, "install", "-g", "--force", spec["package"]]
        args += _registry_args()
        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in iter(proc.stdout.readline, ""):
                line = line.rstrip()
                if line:
                    _append_log(aid, line)
            proc.wait(timeout=600)
        except Exception as e:  # noqa: BLE001
            _set_status(aid, phase="error", action=action,
                        message="安装失败：%s" % e, logs=_get_status(aid)["logs"])
            _append_log(aid, "错误: %s" % e)
            return
        ok = proc.returncode == 0
        ver = _installed_version(spec["package"]) or _command_version(spec["command"]) or ""
        if ok:
            _set_status(aid, phase="done", action=action,
                        message="%s 已安装（v%s）" % (spec["name"], ver or "?"),
                        installed=True, version=ver)
            _append_log(aid, "完成: %s 安装成功%s" % (spec["name"], (" v" + ver) if ver else ""))
        else:
            _set_status(aid, phase="error", action=action,
                        message="安装失败（退出码 %s），请查看日志" % proc.returncode,
                        installed=False, version="")
            _append_log(aid, "错误: npm 退出码 %s" % proc.returncode)

    threading.Thread(target=_run, daemon=True, name="agent-install-%s" % aid).start()
    invalidate_detect_cache()          # 让安装页下一次轮询立即看到 running 状态
    return True, "已开始安装"


def uninstall_agent(aid):
    """后台卸载 Agent。"""
    spec = next((s for s in AGENT_INSTALLERS if s["id"] == aid), None)
    if spec is None:
        return False, "未知 Agent: %s" % aid
    with _LOCK:
        cur = _STATUS.get(aid)
        if cur and cur.get("phase") == "running":
            return False, "该 Agent 正在处理中，请稍候"
    npm = _npm_bin()
    if not npm:
        _set_status(aid, phase="error", action="uninstall", message="未检测到 npm",
                    logs=["错误: 未检测到 npm / Node.js"])
        return False, "未检测到 npm"

    def _run():
        _set_status(aid, phase="running", action="uninstall",
                    message="正在卸载 %s…" % spec["name"], started_at=time.time())
        _append_log(aid, "> npm uninstall -g %s" % spec["package"])
        try:
            proc = subprocess.Popen(
                [npm, "uninstall", "-g", spec["package"]],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in iter(proc.stdout.readline, ""):
                line = line.rstrip()
                if line:
                    _append_log(aid, line)
            proc.wait(timeout=300)
        except Exception as e:  # noqa: BLE001
            _set_status(aid, phase="error", action="uninstall",
                        message="卸载失败：%s" % e, logs=_get_status(aid)["logs"])
            _append_log(aid, "错误: %s" % e)
            return
        if proc.returncode == 0:
            _set_status(aid, phase="done", action="uninstall",
                        message="%s 已卸载" % spec["name"], installed=False, version="")
            _append_log(aid, "完成: %s 卸载成功" % spec["name"])
        else:
            _set_status(aid, phase="error", action="uninstall",
                        message="卸载失败（退出码 %s）" % proc.returncode, installed=False, version="")
            _append_log(aid, "错误: npm 退出码 %s" % proc.returncode)

    threading.Thread(target=_run, daemon=True, name="agent-uninstall-%s" % aid).start()
    invalidate_detect_cache()          # 让安装页下一次轮询立即看到 running 状态
    return True, "已开始卸载"


def status_of(aid):
    """单个 Agent 的实时状态（含日志）。"""
    spec = next((s for s in AGENT_INSTALLERS if s["id"] == aid), None)
    if spec is None:
        return None
    st = _get_status(aid)
    return {
        "id": aid,
        "name": spec["name"],
        "package": spec["package"],
        "command": spec["command"],
        "found": bool(_which(spec["command"])),
        "version": _command_version(spec["command"]) or _installed_version(spec["package"]) or "",
        "phase": st.get("phase", "idle"),
        "action": st.get("action", ""),
        "message": st.get("message", ""),
        "logs": st.get("logs", []),
        "busy": st.get("phase") == "running",
    }
