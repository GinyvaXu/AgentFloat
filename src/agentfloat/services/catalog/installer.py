# -*- coding: utf-8 -*-
"""Agent 安装适配器（隔离前缀，v0.1）。

设计（基于 2026-10-26 全链路测试结论）：
- npm 走 ``npm install --prefix <app 管理的独立目录>``，不污染全局；
- pip 走独立 venv，并**先装 setuptools/wheel**（aider 的失败原因）；
- 检测优先看受管前缀，其次看 PATH；
- 卸载 = 删受管前缀（不触碰用户全局安装）；
- 所有子进程静默（CREATE_NO_WINDOW）且带超时。

本模块不依赖 Qt，便于单测与后台线程复用。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from typing import Callable, Dict, Optional

from .schema import AgentSpec

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
DEFAULT_INSTALL_TIMEOUT = 480
DEFAULT_CHECK_TIMEOUT = 40
DEFAULT_PROBE_TIMEOUT = 30

#: 已核实的 headless 参数（未列出的不做探测）
HEADLESS_ARGS = {
    "claude": ["-p", "hi"],
    "codex": ["exec", "--skip-git-repo-check", "hi"],
    "gemini": ["-p", "hi"],
}


def agents_dir() -> str:
    """受管安装根目录：%LOCALAPPDATA%/AgentFloat/catalog/agents"""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "AgentFloat", "catalog", "agents")


def managed_prefix(spec_or_id: str, base: Optional[str] = None) -> str:
    spec_id = spec_or_id if isinstance(spec_or_id, str) else spec_or_id.id
    return os.path.join(base or agents_dir(), spec_id)


def bin_path(spec: AgentSpec, prefix: Optional[str] = None) -> str:
    root = prefix or managed_prefix(spec)
    if install_type(spec) == "pip":
        return os.path.join(root, "Scripts", "%s.exe" % spec.launch.command)
    return os.path.join(root, "node_modules", ".bin", "%s.cmd" % spec.launch.command)


def install_type(spec: AgentSpec) -> str:
    return spec.install[0].type if spec.install else ""


def _run(cmd: str, timeout: int, cwd: Optional[str] = None) -> Dict:
    """静默执行；返回 rc/out/sec/timeout。"""
    t0 = time.time()
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout, cwd=cwd, creationflags=CREATE_NO_WINDOW,
                           env=dict(os.environ, CI="1", NO_COLOR="1"))
        return {"rc": p.returncode,
                "out": ((p.stdout or "") + (p.stderr or ""))[-600:],
                "sec": round(time.time() - t0, 1), "timeout": False}
    except subprocess.TimeoutExpired:
        return {"rc": None, "out": "timeout", "sec": round(time.time() - t0, 1), "timeout": True}
    except Exception as e:  # noqa: BLE001
        return {"rc": None, "out": str(e)[:200], "sec": round(time.time() - t0, 1), "timeout": False}


def install(spec: AgentSpec, base: Optional[str] = None,
            runner: Callable[..., Dict] = _run) -> Dict:
    """安装到受管前缀；返回 {ok, prefix, log[], seconds}。"""
    prefix = managed_prefix(spec, base)
    pkg = spec.install[0].package_or_url if spec.install else ""
    kind = install_type(spec)
    t0 = time.time()
    log = []
    if not pkg or kind not in ("npm", "pip"):
        return {"ok": False, "prefix": prefix, "reason": "unsupported install type: %s" % kind,
                "log": log, "seconds": 0}

    if kind == "npm":
        cmd = ('npm.cmd install --prefix "%s" --cache "%s" --no-audit --no-fund '
               '--loglevel=error %s' % (prefix, os.path.join(base or agents_dir(), ".npm-cache"), pkg))
        r = runner(cmd, DEFAULT_INSTALL_TIMEOUT)
        log.append(r)
        ok = r.get("rc") == 0
    else:
        venv_py = os.path.join(prefix, "Scripts", "python.exe")
        r1 = runner('"%s" -m venv "%s"' % (sys.executable, prefix), 120)
        log.append(r1)
        if r1.get("rc") != 0:
            return {"ok": False, "prefix": prefix, "reason": "venv 创建失败", "log": log,
                    "seconds": round(time.time() - t0, 1)}
        # aider 的失败根因：新 venv 缺 setuptools/wheel
        r2 = runner('"%s" -m pip install --disable-pip-version-check -q --upgrade pip setuptools wheel' % venv_py, 240)
        log.append(r2)
        r3 = runner('"%s" -m pip install --disable-pip-version-check -q %s' % (venv_py, pkg), DEFAULT_INSTALL_TIMEOUT)
        log.append(r3)
        ok = r2.get("rc") == 0 and r3.get("rc") == 0

    return {"ok": bool(ok), "prefix": prefix,
            "reason": "" if ok else (log[-1].get("out") or "")[-200:],
            "log": log, "seconds": round(time.time() - t0, 1)}


def check_version(spec: AgentSpec, prefix: Optional[str] = None,
                  runner: Callable[..., Dict] = _run) -> Dict:
    """在受管前缀里跑 --version，解析版本。"""
    exe = bin_path(spec, prefix)
    if not os.path.isfile(exe):
        return {"ok": False, "version": "", "reason": "未安装（受管前缀无 bin）"}
    r = runner('"%s" --version' % exe, DEFAULT_CHECK_TIMEOUT)
    import re
    pattern = getattr(spec.health, "version_pattern", "") or r"(\d+\.\d+\.\d+)"
    m = re.search(pattern, r.get("out") or "")
    return {"ok": bool(m), "version": m.group(1) if m else "", "raw": r.get("out", ""),
            "rc": r.get("rc")}


def detect(spec: AgentSpec, base: Optional[str] = None) -> Dict:
    """检测：受管前缀优先，其次 PATH。"""
    exe = bin_path(spec, managed_prefix(spec, base))
    if os.path.isfile(exe):
        return {"installed": True, "source": "managed", "path": exe}
    found = shutil.which(spec.launch.command)
    if found:
        return {"installed": True, "source": "path", "path": found}
    return {"installed": False, "source": "", "path": ""}


def classify_probe(rc: Optional[int], out: str, timed_out: bool = False) -> str:
    low = (out or "").lower()
    if timed_out:
        return "timeout"
    if rc == 0:
        return "ok"
    if any(k in low for k in ("401", "unauthorized", "login", "log in", "sign in", "api key", "apikey")):
        return "needs-login"
    return "error"


def auth_probe(spec: AgentSpec, base: Optional[str] = None,
               runner: Callable[..., Dict] = _run) -> str:
    """已装才探测：跑一条 headless，判断是否已登录。"""
    arts = HEADLESS_ARGS.get(spec.id)
    if not arts:
        return "unsupported"
    exe = bin_path(spec, managed_prefix(spec, base))
    if not os.path.isfile(exe):
        return "not-installed"
    r = runner('"%s" %s' % (exe, " ".join(arts)), DEFAULT_PROBE_TIMEOUT,
               cwd=base or agents_dir())
    return classify_probe(r.get("rc"), r.get("out", ""), bool(r.get("timeout")))


def uninstall(spec: AgentSpec, base: Optional[str] = None) -> Dict:
    """删除受管前缀（只动 app 自己的目录，不碰全局安装）。"""
    prefix = managed_prefix(spec, base)
    existed = os.path.isdir(prefix)
    shutil.rmtree(prefix, ignore_errors=True)
    return {"ok": not os.path.isdir(prefix), "removed": existed, "prefix": prefix}
