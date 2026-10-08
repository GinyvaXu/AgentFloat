# -*- coding: utf-8 -*-
"""
自动更新 - 多源检查 + 国内代理下载 + 静默重装并重启

参考 Sheriff of Nottingham 项目的更新链路设计：

- 检查：update.json 清单（raw.githubusercontent + jsDelivr CDN +
  多个国内加速代理 + GitHub Releases API 并行探测，取版本号最高者），
  大陆网络被墙/变慢时依然能拿到更新信息，返回友好错误码而非原始异常。
- 下载：GitHub 资产自动展开为 [直连 + 国内代理镜像] 候选列表，逐个尝试。
- 安装：静默重装 —— 退出本程序 -> 等待进程释放 exe -> 运行安装包
  （/VERYSILENT）-> 重新启动 -> 等待 boot 标记确认真正启动成功。
- 高级用户可自建镜像：%APPDATA%/AgentFloat/mirror.json
  （{"manifest": "...", "installer": "..."}，例如 Gitee 仓库）。
"""
import concurrent.futures
import hashlib
import io
import json
import logging
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

from PyQt5.QtCore import QThread, pyqtSignal

_logger = logging.getLogger("AgentFloat")

# 仓库与 API 地址
REPO = "GinyvaXu/AgentFloat"
RELEASE_PAGE_URL = "https://github.com/GinyvaXu/AgentFloat/releases"

# 大陆可用的 GitHub 加速代理（会随时间增减，保留多个做容错）
GITHUB_PROXIES = [
    "https://ghfast.top/",
    "https://gh-proxy.com/",
    "https://ghproxy.net/",
    "https://gh.llkk.cc/",
]

# 自有镜像（Cloudflare R2，国内直连快；v3.9.0 起作为首选更新源）
# 由 personal-website 的镜像管线生成：{project, tag, updatedAt, base, files:[{name,size,sha256}]}
R2_MANIFEST = "https://dl.ginyva.site/releases/agentfloat/latest.json"

_RAW_MANIFEST = ("https://raw.githubusercontent.com/GinyvaXu/"
                 "AgentFloat/main/update.json")
_JS_MANIFEST = ("https://cdn.jsdelivr.net/gh/GinyvaXu/"
                "AgentFloat@main/update.json")
# 顺序即优先级：同版本时取先出现者（R2 镜像最快且免代理）
MANIFEST_SOURCES = [
    ("r2", R2_MANIFEST),
    ("ghfast", "https://ghfast.top/" + _RAW_MANIFEST),
    ("raw", _RAW_MANIFEST),
    ("ghproxynet", "https://ghproxy.net/" + _RAW_MANIFEST),
    ("llkk", "https://gh.llkk.cc/" + _RAW_MANIFEST),
    ("ghproxycom", "https://gh-proxy.com/" + _RAW_MANIFEST),
    ("jsdelivr", _JS_MANIFEST),
    ("jsdelivr-fastly", _JS_MANIFEST.replace("cdn.jsdelivr.net",
                                             "fastly.jsdelivr.net")),
    ("jsdelivr-gcore", _JS_MANIFEST.replace("cdn.jsdelivr.net",
                                            "gcore.jsdelivr.net")),
    ("api", "https://api.github.com/repos/GinyvaXu/"
            "AgentFloat/releases/latest"),
]
_UA = "AgentFloat-Updater/1.0"
_DEFAULT_TIMEOUT = 12
_DOWNLOAD_TIMEOUT = 90
_DOWNLOAD_ATTEMPTS = 2


# ---- 版本比较 -------------------------------------------------
def parse_version(version):
    """'v1.2.2' / '1.2.2' / '1.2.2-rc1' -> (1, 2, 2)；无法解析返回 (0, 0, 0)"""
    parts = re.findall(r"\d+", str(version))[:3]
    return tuple(int(x) for x in (parts + ["0", "0", "0"])[:3])


def is_newer(latest, current):
    """latest > current（字符串或版本元组均可）"""
    return parse_version(latest) > parse_version(current)


def is_frozen():
    return bool(getattr(sys, "frozen", False))


# ---- 本地路径 -------------------------------------------------
def app_dir():
    """程序数据目录：%APPDATA%/AgentFloat（与主程序一致）"""
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "AgentFloat")


def download_dir():
    d = os.path.join(tempfile.gettempdir(), "AgentFloatUpdate")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        d = tempfile.gettempdir()
    return d


# ---- 网络 -----------------------------------------------------
def _fetch(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": _UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def error_code(e):
    """把异常映射为友好错误码：'timeout' | 'network' | 'unknown'"""
    if isinstance(e, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(e, urllib.error.URLError):
        reason = getattr(e, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout"
        return "network"
    if isinstance(e, (ssl.SSLError, socket.gaierror, OSError)):
        return "network"
    return "unknown"


def fetch_manifest(url, timeout=_DEFAULT_TIMEOUT):
    """下载并解析 update.json；网络/JSON 问题一律抛异常"""
    data = _fetch(url, timeout)
    return json.loads(data.decode("utf-8"))


def _asset_sha256(asset):
    """从 GitHub 资产对象里取 SHA256（digest 形如 'sha256:abcd…'）"""
    digest = str(asset.get("digest", "") or "").strip().lower()
    if digest.startswith("sha256:"):
        return digest.split(":", 1)[1]
    return ""


def _from_release_api(data):
    """把 GitHub releases/latest API 响应转为 (version, url, notes, sha256)"""
    tag = str(data.get("tag_name", "") or "").strip().lstrip("vV")
    if not tag:
        raise ValueError("empty tag")
    asset = None
    for a in (data.get("assets") or []):
        if str(a.get("browser_download_url", "") or "").lower().endswith(".exe"):
            asset = a
            break
    if asset is None:
        raise ValueError("no installer asset")
    # 优先安装包（Setup），避免静默重装拿到独立 exe
    for a in (data.get("assets") or []):
        u = str(a.get("browser_download_url", "") or "")
        name = str(a.get("name", "") or "")
        if u.lower().endswith(".exe") and "setup" in name.lower():
            asset = a
            break
    url = str(asset.get("browser_download_url", "") or "")
    notes = str(data.get("body", "") or "")[:400].replace("\r", "")
    return tag, url, notes, _asset_sha256(asset)


def mirror_urls(url):
    """把 GitHub URL 展开为 [直连] + [国内代理镜像]；非 GitHub URL 原样返回"""
    if not url:
        return []
    if "github.com/" not in url:
        return [url]
    return [url] + [p + url for p in GITHUB_PROXIES]


_MIRROR_FILE = "mirror.json"


def resolve_latest_asset_url(timeout=_DEFAULT_TIMEOUT):
    """从 GitHub Releases API 获取最新正式版的安装包直链（用于 manifest 悬空/固定 URL 回退）"""
    try:
        data = _fetch("https://api.github.com/repos/%s/releases/latest" % REPO, timeout)
        _tag, url, _notes, _sha = _from_release_api(json.loads(data.decode("utf-8")))
        return url or ""
    except Exception:
        return ""


def custom_mirror():
    """读取用户自建镜像配置（%APPDATA%/AgentFloat/mirror.json）"""
    try:
        p = os.path.join(app_dir(), _MIRROR_FILE)
        with io.open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return {k: str(data.get(k, "") or "").strip()
                for k in ("manifest", "installer")}
    except Exception:
        return {}


def _result_from_r2_manifest(man, current):
    """把自有 R2 镜像的 latest.json 转成检查结果（v3.9.0 首选源）。

    格式：{project, tag, updatedAt, base, files:[{name, size, sha256}]}
    R2 走 Cloudflare 边缘（国内直连快），且自带 sha256 供下载校验。
    """
    latest = str(man.get("tag", "") or "").strip().lstrip("vV")
    if not latest:
        raise ValueError("empty r2 tag")
    base = str(man.get("base", "") or "")
    files = [f for f in (man.get("files") or []) if isinstance(f, dict)]
    if not files or not base:
        raise ValueError("r2 manifest missing files/base")
    # 优先安装包（Setup）；否则取第一个
    pick = files[0]
    for f in files:
        if "setup" in str(f.get("name", "")).lower():
            pick = f
            break
    name = str(pick.get("name", "") or "")
    if not name:
        raise ValueError("r2 manifest missing file name")
    return {"available": is_newer(latest, current),
            "version": latest, "current": current,
            "url": base.rstrip("/") + "/" + name,
            "sha256": str(pick.get("sha256", "") or "").strip().lower(),
            "notes": "", "notes_zh": "",
            "error": None, "detail": "", "source": "r2",
            "size": int(pick.get("size") or 0)}


def _result_from_manifest(man, current):
    latest = str(man.get("version", "") or "").strip()
    if not latest:
        raise ValueError("empty manifest")
    return {"available": is_newer(latest, current),
            "version": latest, "current": current,
            "url": str(man.get("url", "") or ""),
            "sha256": str(man.get("sha256", "") or "").strip().lower(),
            "notes": str(man.get("notes", "") or "").replace("\r", ""),
            "notes_zh": str(man.get("notes_zh", "") or "").replace("\r", ""),
            "error": None, "detail": ""}


def _probe_one(kind, url, per_timeout, current):
    """探测单个清单源；返回 (ok, result_or_error)"""
    try:
        if kind == "api":
            data = _fetch(url, per_timeout)
            latest, dl_url, notes, sha = _from_release_api(json.loads(data.decode("utf-8")))
            return True, {"available": is_newer(latest, current),
                          "version": latest, "current": current,
                          "url": dl_url, "sha256": sha, "notes": notes, "notes_zh": "",
                          "error": None, "detail": "", "source": "api"}
        man = fetch_manifest(url, per_timeout)
        if kind == "r2":
            return True, _result_from_r2_manifest(man, current)
        res = _result_from_manifest(man, current)
        res.setdefault("source", kind)
        return True, res
    except Exception as e:
        return False, e


def _merge_best(results):
    """取版本最高者；同版本时优先 R2（MANIFEST_SOURCES 顺序），
    并用其它同版本结果补齐缺失的 notes / sha256（v3.9.0）。"""
    best = max(results, key=lambda r: parse_version(r["version"]))
    same = [r for r in results if parse_version(r["version"]) == parse_version(best["version"])]
    merged = dict(best)
    for r in same:
        if r is best:
            continue
        if not merged.get("sha256") and r.get("sha256"):
            merged["sha256"] = r["sha256"]
        if not merged.get("notes") and r.get("notes"):
            merged["notes"] = r["notes"]
        if not merged.get("notes_zh") and r.get("notes_zh"):
            merged["notes_zh"] = r["notes_zh"]
    return merged


def _check_parallel(current, timeout):
    """并行探测所有内置源，取版本号最高者（防 CDN 缓存返回旧版）"""
    per = max(3.0, min(6.0, timeout / 2.0))
    ex = concurrent.futures.ThreadPoolExecutor(
        max_workers=min(10, len(MANIFEST_SOURCES)))
    futures = [ex.submit(_probe_one, kind, url, per, current)
               for kind, url in MANIFEST_SOURCES]
    results, errs = [], []
    try:
        for f in concurrent.futures.as_completed(futures, timeout=timeout):
            ok, payload = f.result()
            if ok:
                results.append(payload)
            else:
                errs.append(payload)
    except concurrent.futures.TimeoutError:
        pass
    ex.shutdown(wait=False)
    if results:
        return _merge_best(results)
    last = errs[-1] if errs else TimeoutError("all sources timed out")
    return {"available": False, "version": "", "current": current,
            "url": "", "sha256": "", "notes": "", "notes_zh": "",
            "error": error_code(last), "detail": str(last), "source": ""}

def check_for_update(current_version, timeout=_DEFAULT_TIMEOUT):
    """返回状态 dict，绝不抛异常。

    keys: available / version / current / url / sha256 / source(命中源) /
          notes / notes_zh / error（None 或 'timeout'/'network'/'unknown'）/ detail
    自建镜像 manifest 优先；否则并行探测全部内置源（R2 自有镜像优先），取最高版本。
    """
    custom = custom_mirror().get("manifest") or ""
    if custom:
        try:
            res = _result_from_manifest(fetch_manifest(custom, timeout),
                                        current_version)
            res.setdefault("source", "custom")
            return res
        except Exception:
            pass
    return _check_parallel(current_version, timeout)


# ---- 下载 -----------------------------------------------------
def _download_once(url, path, timeout, progress):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        total = int(r.headers.get("Content-Length") or 0)
        got = 0
        with io.open(path, "wb") as f:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress:
                    progress(got, total)


def sha256_file(path, chunk=1 << 20):
    """计算文件 SHA256（小写十六进制）"""
    h = hashlib.sha256()
    with io.open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def download_installer(url, dest_dir=None, progress=None, timeout=_DOWNLOAD_TIMEOUT,
                       attempts=_DOWNLOAD_ATTEMPTS, expected_sha256=""):
    """下载安装包到临时目录，返回本地路径。

    progress(got, total) 回调；GitHub 资产按 [直连 + 代理镜像] 逐个尝试。

    v3.8.0 安全加固：expected_sha256 非空时，下载完成必须校验通过才返回，
    否则删除文件并抛异常 —— 防止镜像/代理被投毒后静默安装恶意包。
    """
    dest_dir = dest_dir or download_dir()
    os.makedirs(dest_dir, exist_ok=True)
    custom = custom_mirror().get("installer") or ""
    candidates = mirror_urls(custom or url)
    if not candidates:
        raise ValueError("no download URL")
    fname = os.path.basename(candidates[0].split("?")[0]) or "AgentFloat_Setup.exe"
    path = os.path.join(dest_dir, fname)
    expect = str(expected_sha256 or "").strip().lower()
    last_err = None
    hash_err = None

    def _verified(p):
        """校验下载文件；返回 (ok, 错误信息)"""
        if not expect:
            _logger.warning("更新包未提供 SHA256，跳过完整性校验（来源: %s）", p)
            return True, ""
        actual = sha256_file(p)
        if actual == expect:
            return True, ""
        return False, "安装包校验失败（期望 %s… 实际 %s…）" % (expect[:12], actual[:12])

    for cand in candidates:
        cand_attempts = max(1, attempts) if len(candidates) == 1 else 1
        for _ in range(cand_attempts):
            try:
                _download_once(cand, path, timeout, progress)
                ok, why = _verified(path)
                if ok:
                    return path
                last_err = hash_err = ValueError(why)
                _logger.error("更新包校验未通过（%s）: %s", cand, why)
                try:
                    os.remove(path)
                except OSError:
                    pass
            except Exception as e:
                last_err = e
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass
    # manifest 悬空 / 固定 URL 已不存在（如 404）时，
    # 回退到 GitHub 最新正式版实际资产（过滤已试过的 URL）
    fallback = resolve_latest_asset_url(timeout)
    if fallback and fallback not in candidates and fallback not in [c.split("?")[0] for c in candidates]:
        try:
            _download_once(fallback, path, timeout, progress)
            ok, why = _verified(path)
            if ok:
                return path
            last_err = hash_err = ValueError(why)
            try:
                os.remove(path)
            except OSError:
                pass
        except Exception as e:
            last_err = e
    # 校验失败优先于后续网络错误上报（否则用户看到的是"连接被重置"而非"包被篡改"）
    raise hash_err or last_err


# ---- 静默重装并重启 -------------------------------------------
def _exe_path():
    """当前运行的可执行文件路径（仅打包版）"""
    return sys.executable if is_frozen() else None


def _launch_bat(bat_path, args=None):
    """隐藏、分离地启动 .bat，返回 Popen 句柄（失败返回 None）"""
    flags = 0x08000000  # CREATE_NO_WINDOW
    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        return subprocess.Popen(["cmd.exe", "/c", bat_path] + list(args or []),
                                creationflags=flags, close_fds=True, shell=False)
    except Exception:
        return None


_PENDING_FLAG = "update_pending.flag"
_FLAG_MAX_AGE = 600.0
_BOOT_FLAG = "boot_ok.flag"


def _pending_flag():
    return os.path.join(download_dir(), _PENDING_FLAG)


def _pid_alive(pid):
    """Windows 下检查进程是否仍在运行"""
    if not pid:
        return False
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    except Exception:
        return False


def _pending_flag_state():
    """返回 (pid, age_seconds)；无文件返回 (None, 0.0)"""
    flag = _pending_flag()
    if not os.path.exists(flag):
        return None, 0.0
    pid, ts = None, 0.0
    try:
        with io.open(flag, "r", encoding="ascii", errors="ignore") as f:
            for ln in f:
                if "=" not in ln:
                    continue
                k, v = ln.strip().split("=", 1)
                if k == "pid":
                    pid = int(v) or None
                elif k == "ts":
                    ts = float(v) or 0.0
    except Exception:
        return None, -1.0
    age = time.time() - ts if ts else -1.0
    return pid, age


def _flag_is_stale(pid, age):
    """flag 对应的批处理是否已不活动（可重新安排更新）"""
    if pid and _pid_alive(pid):
        return age > _FLAG_MAX_AGE
    return True


def boot_marker():
    """更新批处理监听的 boot-OK 标记路径"""
    return os.path.join(download_dir(), _BOOT_FLAG)


def mark_boot_ok():
    """程序 GUI 就绪后写入 boot 标记（更新批处理据此确认启动成功）"""
    try:
        p = boot_marker()
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with io.open(p, "w", encoding="ascii") as f:
            f.write("ts=%d\n" % int(time.time()))
        return True
    except Exception:
        return False


def apply_update(installer_path, exe_path=None):
    """安排静默重装 + 重启。返回 True 表示已成功安排（含已在进行中）。

    仅对打包版有意义。写入 %TEMP%/AgentFloatUpdate/run_update.bat：
    等待本程序退出 -> 静默运行安装包 -> 重新启动 -> 等待 boot 标记，
    连续几次启动失败则打开 Releases 页让用户手动处理。
    """
    exe_path = exe_path or _exe_path()
    if not exe_path:
        return False
    installer_path = os.path.abspath(installer_path)
    if not os.path.exists(installer_path):
        return False
    flag = _pending_flag()
    pid, age = _pending_flag_state()
    if pid is not None and not _flag_is_stale(pid, age):
        return True  # 已有批处理正在重装

    d = download_dir()
    bat = os.path.join(d, "run_update.bat")
    log = os.path.join(d, "update_log.txt")
    inno_log = os.path.join(d, "install_log.txt")
    exe_name = os.path.splitext(os.path.basename(exe_path))[0]

    lines = [
        '@echo off',
        'setlocal EnableDelayedExpansion',
        'set "EXE=%~1"',
        'set "INST=%~2"',
        'set "FLAG=%~3"',
        'set "BOOT=%~4"',
        'set "NAME=%EXE_NAME%"',
        'set "LOG=%LOG_PATH%"',
        'set "INNO=%INNO_PATH%"',
        'echo [%date% %time%] update batch started >> "%LOG%"',
        'rem wait for the app to exit so the installer can replace the exe',
        'set /a n=0',
        ':wait_exit',
        'powershell -NoProfile -WindowStyle Hidden -Command "if (Get-Process -Name \'%NAME%\' -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"',
        'if errorlevel 1 goto exit_done',
        'set /a n+=1',
        'if !n! lss 20 ( powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2" & goto wait_exit )',
        'echo [%date% %time%] app did not exit, forcing kill >> "%LOG%"',
        'powershell -NoProfile -WindowStyle Hidden -Command "Stop-Process -Name \'%NAME%\' -Force -ErrorAction SilentlyContinue"',
        'powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2"',
        ':exit_done',
        'rem silent install, retry while the exe is still locked',
        'set /a n=0',
        ':install',
        'echo [%date% %time%] running installer >> "%LOG%"',
        '"%INST%" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="%INNO%"',
        'set ec=!errorlevel!',
        'echo [%date% %time%] installer exit code=!ec! >> "%LOG%"',
        'if !ec! neq 0 (',
        '  set /a n+=1',
        '  if !n! lss 3 ( powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3" & goto install )',
        '  echo [%date% %time%] install failed after retries, opening releases page >> "%LOG%"',
        '  start "" "https://github.com/GinyvaXu/AgentFloat/releases"',
        ')',
        'rem launch the new app and watch for the boot marker',
        'set /a n=0',
        ':launch',
        'set /a n+=1',
        'if !n! gtr 6 (',
        '  echo [%date% %time%] could not boot new app after 6 tries >> "%LOG%"',
        '  start "" "https://github.com/GinyvaXu/AgentFloat/releases"',
        '  goto end',
        ')',
        'echo [%date% %time%] launch try !n! >> "%LOG%"',
        'powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 8"',
        'if exist "%BOOT%" del "%BOOT%" >nul 2>&1',
        'if exist "%EXE%" powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath \'%EXE%\' -WorkingDirectory \'%~dp1\'"',
        'set /a w=0',
        ':watch',
        'powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 3"',
        'if exist "%BOOT%" ( echo [%date% %time%] new app booted OK >> "%LOG%" & goto end )',
        'powershell -NoProfile -WindowStyle Hidden -Command "if (Get-Process -Name \'%NAME%\' -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"',
        'if errorlevel 1 ( echo [%date% %time%] boot failed on try !n! >> "%LOG%" & goto launch )',
        'set /a w+=3',
        'if !w! lss 45 goto watch',
        'echo [%date% %time%] alive but no boot marker, killing and retrying >> "%LOG%"',
        'powershell -NoProfile -WindowStyle Hidden -Command "Stop-Process -Name \'%NAME%\' -Force -ErrorAction SilentlyContinue"',
        'goto launch',
        ':end',
        'echo [%date% %time%] batch finished >> "%LOG%"',
        'del "%INST%" >nul 2>&1',
        'del "%FLAG%" >nul 2>&1',
        '(goto) 2>nul & del "%~f0"',
    ]
    text = "\r\n".join(lines) + "\r\n"
    text = text.replace("%EXE_NAME%", exe_name)
    text = text.replace("%LOG_PATH%", log.replace("%", "%%"))
    text = text.replace("%INNO_PATH%", inno_log.replace("%", "%%"))
    with io.open(bat, "w", encoding="ascii", errors="replace", newline="") as f:
        f.write(text)
    proc = _launch_bat(bat, [exe_path, installer_path, flag, boot_marker()])
    if proc is None:
        try:
            os.remove(flag)
        except OSError:
            pass
        return False
    with io.open(flag, "w", encoding="ascii") as f:
        f.write("pid=%d\nts=%d\n" % (proc.pid, int(time.time())))
    return True


def open_release_page():
    """在默认浏览器打开 GitHub Releases 页面"""
    import webbrowser
    webbrowser.open(RELEASE_PAGE_URL)


# ---- 后台线程（UI 兼容） ---------------------------------------
class UpdateWorker(QThread):
    """后台检查最新版本"""

    result_ready = pyqtSignal(object)
    check_failed = pyqtSignal(str)

    def __init__(self, current_version, parent=None):
        super().__init__(parent)
        self._current_version = current_version

    def run(self):
        try:
            info = check_for_update(self._current_version)
            self.result_ready.emit(info)
        except Exception as e:
            _logger.warning("更新检查失败: %s", e)
            self.check_failed.emit(str(e))


def _friendly_error(e):
    """把下载异常转为含 HTTP 状态码的友好信息"""
    if isinstance(e, urllib.error.HTTPError):
        return "HTTP %d %s" % (e.code, getattr(e, "reason", "") or "")
    if isinstance(e, urllib.error.URLError):
        return "网络错误：%s" % getattr(e, "reason", e)
    return str(e)


class DownloadWorker(QThread):
    """后台下载安装包（带进度 + SHA256 完整性校验）"""

    done = pyqtSignal(str)            # 保存路径
    failed = pyqtSignal(str)          # 错误信息
    progress = pyqtSignal(int, int)   # (已下载, 总大小)

    def __init__(self, url, sha256="", parent=None):
        super().__init__(parent)
        self._url = url
        self._sha256 = str(sha256 or "")

    def run(self):
        try:
            path = download_installer(self._url, progress=self._on_progress,
                                      expected_sha256=self._sha256)
            self.done.emit(path)
        except Exception as e:
            _logger.warning("更新下载失败: %s", e)
            self.failed.emit(_friendly_error(e))

    def _on_progress(self, got, total):
        self.progress.emit(got, total)