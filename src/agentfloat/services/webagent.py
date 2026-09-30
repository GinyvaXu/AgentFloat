# -*- coding: utf-8 -*-
"""Web 模式 Agent 通用管理（PATCH 3.1.0）

从 agents 配置中取 ``launcher == "web"`` 的条目（``web`` 字段含 command / port / url），
统一提供：状态查询 / 启动（后台 + 等端口就绪 + 打开浏览器）/ 终止（结束进程树 + 校验端口释放）。

- dsh 走其专用启动逻辑（含插件自愈与加载指示状态机）与专用停止；
- 其余（如 ``opencode serve``）走通用实现；
- 终止后按端口兜底清理，即使 AgentFloat 重启过也能正确停止。
"""
import os
import socket
import subprocess
import time

from agentfloat.core.logging_setup import _log
from agentfloat.core.paths import config_dir
from agentfloat.core.sysutil import _open_url

_PROC = {}     # agent_id -> Popen（本次进程内启动的）
_LAST = {}     # agent_id -> {"pid": int, "started_at": float}

_READY_TIMEOUT_S = 40


def _port_open(port, host="127.0.0.1", timeout=0.6):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def web_spec(agent):
    """解析 agent 的 web 规格；无效返回 None

    返回 {"command": [...], "port": int, "url": str, "log_prefix": str}
    """
    web = agent.get("web") if isinstance(agent, dict) else None
    if not isinstance(web, dict):
        return None
    try:
        port = int(web.get("port"))
    except (TypeError, ValueError):
        return None
    command = [str(x) for x in (web.get("command") or []) if str(x).strip()]
    if not command:
        return None
    return {
        "command": command,
        "port": port,
        "url": str(web.get("url") or ("http://127.0.0.1:%d" % port)),
        "log_prefix": str(web.get("log_prefix") or (agent.get("id") or "web")),
    }


def list_web_agents(agents):
    """返回 [(agent, spec), ...]，仅含 launcher=web 且规格有效的条目"""
    out = []
    for a in agents or []:
        if (a.get("launcher") or "terminal") != "web":
            continue
        spec = web_spec(a)
        if spec:
            out.append((a, spec))
    return out


def status(agent):
    """运行状态：{"running": bool, "port": int, "url": str, "pid": int|None}"""
    spec = web_spec(agent) or {}
    aid = (agent or {}).get("id") or ""
    info = _LAST.get(aid) or {}
    running = bool(spec) and _port_open(spec["port"])
    return {
        "running": running,
        "port": spec.get("port"),
        "url": spec.get("url"),
        "pid": info.get("pid"),
    }


def _wrap_cmd(cmd_path, rest):
    """批处理 shim（npm 生成的 .cmd/.bat）需要经 cmd.exe 执行"""
    if cmd_path.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", cmd_path] + list(rest)
    return [cmd_path] + list(rest)


def start(agent, config=None):
    """启动 Web Agent：后台运行 + 等端口就绪 + 打开浏览器；返回是否成功"""
    spec = web_spec(agent)
    aid = (agent or {}).get("id") or ""
    name = (agent or {}).get("name") or aid
    if spec is None:
        _log().warning("Web Agent 缺少 web 规格: %s", name)
        return False
    if _port_open(spec["port"]):
        _log().info("Web Agent 已在运行: %s (%s)", name, spec["url"])
        _open_url(spec["url"])
        return True
    if aid == "dsh":
        from agentfloat.services.dsh import launch_dsh_web
        return bool(launch_dsh_web(agent, config))

    from agentfloat.core.registry import resolve_command
    cmd_path, err = resolve_command({"command": spec["command"][0]})
    if cmd_path is None:
        _log().warning("Web Agent 不可用: %s (%s)", name, err)
        return False

    args = _wrap_cmd(cmd_path, spec["command"][1:])
    log_path = os.path.join(
        config_dir(), "logs",
        "%s_%s.log" % (spec["log_prefix"], time.strftime("%Y%m%d_%H%M%S")))
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    _log().info("启动 Web Agent: %s 命令=%s 日志=%s", name, " ".join(args), log_path)
    try:
        logf = open(log_path, "a", encoding="utf-8", errors="replace")
        env = None
        try:  # v3.6.0：注入密钥保险箱环境变量（未解锁则为 None → 继承当前环境）
            from agentfloat.services.vault.accounts import launch_env
            env = launch_env()
        except Exception:  # noqa: BLE001
            env = None
        proc = subprocess.Popen(
            args, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            cwd=os.environ.get("USERPROFILE") or config_dir())
    except Exception as e:  # noqa: BLE001
        _log().error("Web Agent 启动失败: %s (%s)", name, e)
        return False

    _PROC[aid] = proc
    _LAST[aid] = {"pid": proc.pid, "started_at": time.time()}
    deadline = time.time() + _READY_TIMEOUT_S
    while time.time() < deadline:
        if _port_open(spec["port"]):
            _log().info("Web Agent 已就绪: %s %s", name, spec["url"])
            _open_url(spec["url"])
            return True
        if proc.poll() is not None:
            _log().warning("Web Agent 进程已退出: %s (code=%s, 详见 %s)",
                           name, proc.returncode, log_path)
            return False
        time.sleep(0.4)
    _log().warning("Web Agent 等待端口超时（%ds）: %s", _READY_TIMEOUT_S, name)
    return False


def _kill_pid_tree(pid):
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    except Exception:  # noqa: BLE001
        return False


def _kill_by_port(port):
    """兜底：按监听端口找进程并结束（跨 AgentFloat 重启场景）"""
    killed = False
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                             text=True, encoding="utf-8", errors="replace",
                             creationflags=subprocess.CREATE_NO_WINDOW).stdout
        for line in (out or "").splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[3].upper() == "LISTENING" and parts[1].endswith(":%d" % port):
                killed = _kill_pid_tree(parts[4]) or killed
    except Exception:  # noqa: BLE001
        pass
    return killed


def stop(agent):
    """终止 Web Agent：结束进程树 + 端口兜底清理，校验端口已释放"""
    spec = web_spec(agent)
    aid = (agent or {}).get("id") or ""
    name = (agent or {}).get("name") or aid
    if aid == "dsh":
        from agentfloat.services import dsh
        return bool(dsh.stop())

    proc = _PROC.get(aid)
    pid = proc.pid if (proc is not None and proc.poll() is None) else (_LAST.get(aid) or {}).get("pid")
    killed = _kill_pid_tree(pid) if pid else False
    if spec and _port_open(spec["port"]):
        killed = _kill_by_port(spec["port"]) or killed

    released = True
    if spec:
        deadline = time.time() + 6
        while time.time() < deadline and _port_open(spec["port"]):
            time.sleep(0.3)
        released = not _port_open(spec["port"])
    _PROC.pop(aid, None)
    _LAST.pop(aid, None)
    _log().info("Web Agent 终止: %s (killed=%s, 端口已释放=%s)", name, killed, released)
    return released
