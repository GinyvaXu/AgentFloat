"""
自动更新 — 检查 GitHub Releases 最新版本并下载安装包

- 后台线程检查，不阻塞 UI
- 无第三方依赖（标准库 urllib）
- 仅访问 GitHub Releases API，不发送任何个人信息
"""
import hashlib
import json
import logging
import os
import re
import shutil
import urllib.request

from PyQt5.QtCore import QThread, pyqtSignal

_logger = logging.getLogger("AgentFloat")

# 仓库与 API 地址（发布到 GitHub 后生效）
REPO = "GinyvaXu/AgentFloat"
RELEASES_API = "https://api.github.com/repos/{repo}/releases/latest"
REQUEST_TIMEOUT = 10


# ── 版本比较 ──────────────────────────────────────────
def parse_version(version):
    """解析 'v2.0.0' / '2.0.0' → (2, 0, 0)；无法解析返回 None"""
    m = re.match(r"[vV]?(\d+)\.(\d+)\.(\d+)", str(version).strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def is_newer(a, b):
    """a > b（均为 parse_version 结果或 None）"""
    return a is not None and b is not None and a > b


# ── GitHub Releases 查询 ─────────────────────────────
def get_latest_release(current_version, repo=REPO):
    """查询最新 release。

    返回 dict（有新版本时）：version / name / body / assets / html_url
    返回 None：已是最新版本，或没有可用 release。
    网络/解析异常会抛出。
    """
    url = RELEASES_API.format(repo=repo)
    req = urllib.request.Request(url, headers={
        "User-Agent": f"AgentFloat-Updater/{current_version}",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    tag = data.get("tag_name") or ""
    latest = parse_version(tag)
    if latest is None:
        _logger.info("更新检查: release 无有效版本号 (%r)", tag)
        return None
    if not is_newer(latest, parse_version(current_version)):
        _logger.info("更新检查: 已是最新版本 (当前 v%s, 最新 %s)", current_version, tag)
        return None

    _logger.info("更新检查: 发现新版本 %s (当前 v%s)", tag, current_version)
    return {
        "version": tag,
        "name": data.get("name") or tag,
        "body": data.get("body") or "",
        "assets": data.get("assets") or [],
        "html_url": data.get("html_url") or "",
    }


def pick_setup_asset(assets):
    """优先选择 Setup 安装包，其次任意 .exe；没有返回 None"""
    exes = [a for a in assets if (a.get("name") or "").lower().endswith(".exe")]
    if not exes:
        return None
    for a in exes:
        if "setup" in a.get("name", "").lower():
            return a
    return exes[0]


def _sha256(path):
    """计算文件 sha256（分块读取，兼容大文件）"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download_asset(asset, dest_dir):
    """下载 release 资产到 dest_dir，返回保存路径。

    若资产声明了 sha256 digest，下载后校验，不匹配则删除并报错。
    """
    name = asset.get("name") or "update.exe"
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("资产缺少下载地址")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    req = urllib.request.Request(url, headers={"User-Agent": "AgentFloat-Updater"})
    _logger.info("下载更新: %s → %s (%s bytes)", name, dest, asset.get("size", "?"))
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        shutil.copyfileobj(resp, f)

    expected = asset.get("digest") or ""
    if expected.startswith("sha256:"):
        actual = _sha256(dest)
        if actual.lower() != expected[len("sha256:"):].lower():
            _logger.error("更新包校验失败: %s (期望 %s, 实际 %s)", name, expected, actual)
            try:
                os.remove(dest)
            except OSError:
                pass
            raise RuntimeError("下载文件校验失败（sha256 不匹配），已删除")
    _logger.info("下载完成: %s", dest)
    return dest


# ── 后台线程 ─────────────────────────────────────────
class UpdateWorker(QThread):
    """后台检查最新版本"""

    # 有新版本: dict；已是最新/无 release: None
    result_ready = pyqtSignal(object)
    # 检查失败: 错误信息
    check_failed = pyqtSignal(str)

    def __init__(self, current_version, parent=None):
        super().__init__(parent)
        self._current_version = current_version

    def run(self):
        try:
            info = get_latest_release(self._current_version)
            self.result_ready.emit(info)
        except Exception as e:
            _logger.warning("更新检查失败: %s", e)
            self.check_failed.emit(str(e))


class DownloadWorker(QThread):
    """后台下载安装包"""

    done = pyqtSignal(str)      # 保存路径
    failed = pyqtSignal(str)    # 错误信息

    def __init__(self, asset, dest_dir, parent=None):
        super().__init__(parent)
        self._asset = asset
        self._dest_dir = dest_dir

    def run(self):
        try:
            path = download_asset(self._asset, self._dest_dir)
            self.done.emit(path)
        except Exception as e:
            _logger.warning("更新下载失败: %s", e)
            self.failed.emit(str(e))
