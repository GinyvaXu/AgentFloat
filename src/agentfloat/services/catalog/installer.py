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
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Dict, Optional, Tuple

from .schema import AgentSpec, semver_key

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CREATE_NEW_CONSOLE = 0x00000010 if os.name == "nt" else 0
DEFAULT_INSTALL_TIMEOUT = 480
DEFAULT_CHECK_TIMEOUT = 40
DEFAULT_PROBE_TIMEOUT = 30

#: 版本查询超时：npm view 偶发卡住，不能让 /api/catalog 跟着卡住
DEFAULT_VERSION_TIMEOUT = 8
_NPM_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-]+)?)")

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
            runner: Callable[..., Dict] = _run, target: str = "managed") -> Dict:
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
        if target == "global":
            # 与旧安装器一致：装到全局，CLI 进 PATH（便于其它程序复用）
            cmd = ('npm.cmd install -g --registry https://registry.npmmirror.com '
                   '--no-audit --no-fund --loglevel=error %s' % pkg)
        else:
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


def _version_pattern(spec: AgentSpec) -> str:
    return getattr(spec.health, "version_pattern", "") or r"(\d+\.\d+\.\d+)"


def check_version(spec: AgentSpec, prefix: Optional[str] = None,
                  runner: Callable[..., Dict] = _run) -> Dict:
    """在受管前缀里跑 --version，解析版本。"""
    exe = bin_path(spec, prefix)
    if not os.path.isfile(exe):
        return {"ok": False, "version": "", "reason": "未安装（受管前缀无 bin）"}
    r = runner('"%s" --version' % exe, DEFAULT_CHECK_TIMEOUT)
    m = re.search(_version_pattern(spec), r.get("out") or "")
    return {"ok": bool(m), "version": m.group(1) if m else "", "raw": r.get("out", ""),
            "rc": r.get("rc")}


def latest_version(spec: AgentSpec, runner: Callable[..., Dict] = _run) -> str:
    """查询 npm registry 上的最新版；失败 / 非 npm 条目返回空串。

    只做只读查询（``npm view``），静默执行且 8 秒超时；任何异常都收敛为空串，
    避免目录页因为网络问题整块报错。
    """
    if install_type(spec) != "npm" or not spec.install:
        return ""
    pkg = spec.install[0].package_or_url
    if not pkg:
        return ""
    npm = "npm.cmd" if os.name == "nt" else "npm"
    try:
        r = runner("%s view %s version" % (npm, pkg), DEFAULT_VERSION_TIMEOUT)
    except Exception:  # noqa: BLE001
        return ""
    if r.get("rc") not in (0, None):
        return ""
    m = _NPM_VERSION_RE.search(r.get("out") or "")
    return m.group(1) if m else ""


def current_version(spec: AgentSpec, base: Optional[str] = None,
                    runner: Callable[..., Dict] = _run) -> str:
    """读取本机已安装版本；未安装 / 执行失败返回空串。"""
    try:
        det = detect(spec, base=base)
        if not det.get("installed"):
            return ""
        if det.get("source") == "managed":
            exe = bin_path(spec, managed_prefix(spec, base))
        else:
            exe = det.get("path") or spec.launch.command
        if not exe:
            return ""
        r = runner('"%s" --version' % exe, DEFAULT_CHECK_TIMEOUT)
        m = re.search(_version_pattern(spec), r.get("out") or "")
        return m.group(1) if m else ""
    except Exception:  # noqa: BLE001
        return ""


def update_info(spec: AgentSpec, base: Optional[str] = None,
                runner: Callable[..., Dict] = _run,
                latest: Optional[str] = None) -> Dict:
    """返回 ``{current, latest, updateAvailable}``。

    - 有版本号时用 :func:`schema.semver_key` 比较（预发布后缀按基础版本比较）；
    - 任一侧无法解析为 semver 时退化为「字符串不等即视为有更新」，绝不抛异常；
    - ``latest`` 可由调用方传入，便于上层做 TTL 缓存。
    """
    current = current_version(spec, base=base, runner=runner)
    if latest is None:
        latest = latest_version(spec, runner=runner)
    latest = str(latest or "").strip()
    current = str(current or "").strip()

    available = False
    if current and latest:
        cur_key = semver_key(current)
        new_key = semver_key(latest)
        if cur_key is not None and new_key is not None:
            available = new_key > cur_key
        else:
            available = current != latest
    return {
        "current": current,
        "latest": latest,
        "updateAvailable": bool(available),
    }


def detect(spec: AgentSpec, base: Optional[str] = None) -> Dict:
    """检测：受管前缀优先，其次 PATH。"""
    exe = bin_path(spec, managed_prefix(spec, base))
    if os.path.isfile(exe):
        return {"installed": True, "source": "managed", "path": exe}
    found = shutil.which(spec.launch.command)
    if found:
        return {"installed": True, "source": "path", "path": found}
    return {"installed": False, "source": "", "path": ""}


def _resolve_workdir(workdir: Optional[str]) -> Tuple[str, str]:
    """解析工作区：空 → 用户主目录；不存在 → 回退主目录并给出 warning。"""
    home = os.path.expanduser("~")
    raw = str(workdir or "").strip()
    if not raw:
        return home, ""
    path = os.path.expanduser(raw)
    if os.path.isdir(path):
        return path, ""
    return home, "工作区不存在，已回退用户主目录：%s" % raw


def launch(spec: AgentSpec, base: Optional[str] = None,
           popen: Optional[Callable[..., Any]] = None,
           mode: Optional[str] = None, workdir: Optional[str] = None) -> Dict:
    """启动已安装的 Agent CLI（默认新控制台窗口，不阻塞、不捕获输出）。

    - ``mode="window"``（默认）：``cmd /k "<exe>"`` + 新控制台；
    - ``mode="background"``：``cmd /c "<exe>"`` + CREATE_NO_WINDOW；
    - ``workdir`` 为空使用用户主目录；目录不存在则回退主目录并在 ``warning`` 说明。

    返回 ``{ok, pid, exe, method}``（回退工作区时额外带 ``warning``）；
    未安装返回 ``reason=not-installed``，启动异常统一收敛为 ``{ok: False, reason}``。
    """
    mode = str(mode or "window").strip().lower() or "window"
    if mode not in ("window", "background"):
        return {"ok": False, "reason": "invalid-mode: %s" % mode}

    try:
        det = detect(spec, base=base)
        if not det.get("installed"):
            return {"ok": False, "reason": "not-installed"}
        if det.get("source") == "managed":
            exe = bin_path(spec, managed_prefix(spec, base))
            method = "managed"
        else:
            # PATH 安装：优先用 which 解析出的真实路径，便于带空格的路径加引号
            exe = det.get("path") or spec.launch.command
            method = "path"
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": "detect-failed: %s" % str(exc)[:200]}

    cwd, warning = _resolve_workdir(workdir)
    spawn = popen or subprocess.Popen
    try:
        if os.name == "nt":
            if mode == "background":
                # /c：执行完即退出；CREATE_NO_WINDOW 不弹窗，也不阻塞调用方
                proc = spawn(
                    'cmd.exe /c "%s"' % exe,
                    cwd=cwd,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW),
                )
            else:
                # cmd /k：CLI 退出后窗口保留，用户能看到报错；不捕获交互输出
                proc = spawn(
                    'cmd.exe /k "%s"' % exe,
                    cwd=cwd,
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", CREATE_NEW_CONSOLE),
                )
        else:
            proc = spawn([exe], cwd=cwd)
        result = {"ok": True, "pid": int(getattr(proc, "pid", 0) or 0),
                  "exe": exe, "method": method}
        if warning:
            result["warning"] = warning
        return result
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)[:200] or "launch-failed"}


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


def uninstall(spec: AgentSpec, base: Optional[str] = None, target: str = "managed",
              runner: Callable[..., Dict] = _run) -> Dict:
    """卸载：managed 删受管前缀；global 走 npm uninstall -g。"""
    prefix = managed_prefix(spec, base)
    if target == "global" and install_type(spec) == "npm" and spec.install:
        r = runner('npm.cmd uninstall -g %s' % spec.install[0].package_or_url, 180)
        return {"ok": r.get("rc") == 0, "removed": r.get("rc") == 0,
                "prefix": "", "out": r.get("out", "")}
    existed = os.path.isdir(prefix)
    shutil.rmtree(prefix, ignore_errors=True)
    return {"ok": not os.path.isdir(prefix), "removed": existed, "prefix": prefix}
