# -*- coding: utf-8 -*-
"""AgentFloat — Content Catalog / 本地缓存

目录缓存落在 ``%LOCALAPPDATA%/AgentFloat/catalog/``（可用环境变量
``AGENTFLOAT_CATALOG_DIR`` 覆盖，测试用）。设计要点：

- **原子写**：先写同目录临时文件，再 ``os.replace``，断电/杀进程不会留半份 JSON；
- **last-known-good**：每次覆盖前把上一份留成 ``*.bak``，新文件解析失败自动回退；
- **文件名白名单**：只接受 ``[A-Za-z0-9._-]+.json``，杜绝 ``../`` 路径穿越；
- **只增不删**：本模块不提供删除接口，坏缓存靠下一次覆盖收敛。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger("AgentFloat.Catalog.Store")

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.json$")
DEFAULT_TTL_HOURS = 24
ENV_DIR = "AGENTFLOAT_CATALOG_DIR"


def default_root() -> str:
    """缓存根目录：优先环境变量 → LOCALAPPDATA → 用户目录。"""
    override = os.environ.get(ENV_DIR)
    if override:
        return os.path.abspath(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return os.path.join(local, "AgentFloat", "catalog")
    return os.path.join(os.path.expanduser("~"), ".agentfloat", "catalog")


class CatalogStore:
    """目录缓存读写。所有方法都不抛异常，失败返回 None/False 并记日志。"""

    def __init__(self, root: Optional[str] = None):
        self.root = os.path.abspath(root or default_root())
        self.shard_dir = os.path.join(self.root, "shards")

    # ── 基础 ────────────────────────────────────
    def _path(self, name: str) -> Optional[str]:
        if not SAFE_NAME_RE.match(str(name or "")):
            logger.warning("拒绝非法缓存文件名：%r", name)
            return None
        return os.path.join(self.root, name)

    def _shard_path(self, name: str) -> Optional[str]:
        if not SAFE_NAME_RE.match(str(name or "")):
            logger.warning("拒绝非法分包文件名：%r", name)
            return None
        return os.path.join(self.shard_dir, name)

    @staticmethod
    def _read_file(path: str) -> Optional[Any]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError) as exc:
            logger.warning("缓存文件不可读 %s：%s", path, exc)
            return None

    def _atomic_write(self, path: str, text: str) -> bool:
        folder = os.path.dirname(path)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            logger.warning("创建缓存目录失败 %s：%s", folder, exc)
            return False
        backup = path + ".bak"
        if os.path.exists(path):
            try:
                os.replace(path, backup)      # 旧版本留成 last-known-good
            except OSError:
                pass
        tmp_fd = None
        tmp_path = ""
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=folder, text=True)
            with os.fdopen(tmp_fd, "w", encoding="utf-8", newline="\n") as fh:
                tmp_fd = None
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
            return True
        except OSError as exc:
            logger.warning("写缓存失败 %s：%s", path, exc)
            if tmp_fd is not None:
                try:
                    os.close(tmp_fd)
                except OSError:
                    pass
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return False

    # ── JSON 读写 ───────────────────────────────
    def read_json(self, name: str) -> Optional[Dict[str, Any]]:
        path = self._path(name)
        if not path:
            return None
        data = self._read_file(path)
        if isinstance(data, dict):
            return data
        # 主文件坏了 → 回退 last-known-good
        backup = self._read_file(path + ".bak")
        if isinstance(backup, dict):
            logger.warning("缓存 %s 损坏，已回退 last-known-good", name)
            return backup
        return None

    def write_json(self, name: str, data: Dict[str, Any]) -> bool:
        path = self._path(name)
        if not path:
            return False
        try:
            text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
        except (TypeError, ValueError) as exc:
            logger.warning("缓存内容无法序列化 %s：%s", name, exc)
            return False
        return self._atomic_write(path, text + "\n")

    # ── 分包（按字节存，哈希可校验）────────────────
    def read_shard(self, name: str, expect_sha256: str = "") -> Optional[Any]:
        """读分包 JSON；给了 expect_sha256 就先校验，不匹配视为不可用。"""
        path = self._shard_path(name)
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as fh:
                blob = fh.read()
        except OSError as exc:
            logger.warning("分包不可读 %s：%s", path, exc)
            return None
        if expect_sha256:
            digest = hashlib.sha256(blob).hexdigest()
            if digest.lower() != expect_sha256.lower():
                logger.warning("分包哈希不匹配 %s（期望 %s，实为 %s）", name, expect_sha256, digest)
                return None
        try:
            return json.loads(blob.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            logger.warning("分包解析失败 %s：%s", name, exc)
            return None

    def write_shard(self, name: str, blob: bytes) -> Optional[str]:
        """写分包，返回写入内容的 sha256（供 manifest 记录）。"""
        path = self._shard_path(name)
        if not path:
            return None
        folder = os.path.dirname(path)
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as exc:
            logger.warning("创建分包目录失败 %s：%s", folder, exc)
            return None
        tmp_fd = None
        tmp_path = ""
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", dir=folder)
            with os.fdopen(tmp_fd, "wb") as fh:
                tmp_fd = None
                fh.write(blob)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
        except OSError as exc:
            logger.warning("写分包失败 %s：%s", path, exc)
            if tmp_fd is not None:
                try:
                    os.close(tmp_fd)
                except OSError:
                    pass
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            return None
        return hashlib.sha256(blob).hexdigest()

    # ── 刷新状态（ETag / TTL）────────────────────
    def read_state(self) -> Dict[str, Any]:
        return self.read_json("state.json") or {}

    def save_state(self, *, etag: str = "", catalog_version: int = 0, ok: bool = True) -> bool:
        state = {
            "etag": etag,
            "catalogVersion": int(catalog_version or 0),
            "fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ok": bool(ok),
        }
        return self.write_json("state.json", state)

    def is_fresh(self, ttl_hours: int = DEFAULT_TTL_HOURS, now: Optional[float] = None) -> bool:
        """上次成功刷新是否还在 TTL 内（默认 24h）。时间戳坏掉按「不新鲜」处理。"""
        stamp = str(self.read_state().get("fetchedAt") or "")
        if not stamp:
            return False
        try:
            fetched = datetime.fromisoformat(stamp)
        except ValueError:
            return False
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        age = (now if now is not None else time.time()) - fetched.timestamp()
        return 0 <= age < ttl_hours * 3600
