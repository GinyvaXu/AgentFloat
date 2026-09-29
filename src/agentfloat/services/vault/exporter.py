# -*- coding: utf-8 -*-
"""AgentFloat 配置与密钥整体导出/导入（v3.6.0）

导出文件（``.afpack``）结构::

    MAGIC("AFB1") | salt(16) | nonce(12) | AES-256-GCM( gzip( JSON ) )

JSON 内容::

    {
      "format": "agentfloat-bundle", "version": 1,
      "exported": ts, "app_version": "3.6.0",
      "account": {"name": "..."},
      "config": { ...脱敏后的配置... },
      "secrets": {"keys": [{"name": ..., "value": ..., "note": ...}]}
    }

口令派生：PBKDF2-HMAC-SHA256（300k 次，可被环境变量覆盖）→ 32B 密钥；AES-256-GCM 带 AAD。
跨设备导入：只需文件 + 口令；不依赖本机 DPAPI。
"""
import gzip
import json
import os
import time

from agentfloat.services.vault import crypto

BUNDLE_MAGIC = b"AFB1"
BUNDLE_FORMAT = "agentfloat-bundle"
BUNDLE_VERSION = 1
BUNDLE_AAD = b"AgentFloat/bundle/v1"
BUNDLE_ITERATIONS = 300_000

# 导入时不写入的「机器相关」配置键
LOCAL_ONLY_KEYS = ("window_x", "window_y", "snap_edge")


class BundleError(Exception):
    """导出/导入错误（面向界面提示）"""


def sanitize_config(config, keep_local=False):
    """导出前处理：深拷贝并移除机器相关键（keep_local=True 时保留）"""
    data = json.loads(json.dumps(config or {}, ensure_ascii=False))
    if not keep_local:
        for key in LOCAL_ONLY_KEYS:
            data.pop(key, None)
    return data


def build_payload(config, keys, account_name="", app_version="", include_secrets=True,
                  keep_local=False):
    """组装明文载荷（纯函数，便于测试）"""
    payload = {
        "format": BUNDLE_FORMAT,
        "version": BUNDLE_VERSION,
        "exported": time.time(),
        "app_version": str(app_version or ""),
        "account": {"name": str(account_name or "")},
        "config": sanitize_config(config, keep_local=keep_local),
        "secrets": {"keys": []},
    }
    if include_secrets:
        payload["secrets"]["keys"] = [
            {"name": str((k or {}).get("name") or ""),
             "value": str((k or {}).get("value") or ""),
             "note": str((k or {}).get("note") or "")}
            for k in (keys or []) if str((k or {}).get("name") or "").strip()
        ]
    return payload


def export_bundle(config, keys, password, account_name="", app_version="",
                  include_secrets=True, keep_local=False):
    """导出为加密字节串（.afpack 内容）"""
    if not password:
        raise BundleError("请设置导出密码（用于在新设备解密）")
    if len(str(password)) < 6:
        raise BundleError("导出密码至少 6 位")
    payload = build_payload(config, keys, account_name=account_name,
                            app_version=app_version, include_secrets=include_secrets,
                            keep_local=keep_local)
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    salt = crypto.new_salt()
    key = crypto.derive_key(password, salt, BUNDLE_ITERATIONS)
    blob = crypto.encrypt(gzip.compress(raw, 6), key, BUNDLE_AAD)
    return BUNDLE_MAGIC + salt + blob


def import_bundle(data, password):
    """解密并校验导出文件 → payload dict"""
    data = bytes(data or b"")
    if len(data) < len(BUNDLE_MAGIC) + crypto.SALT_LEN + 16 or not data.startswith(BUNDLE_MAGIC):
        raise BundleError("文件格式不正确（不是 AgentFloat 配置文件）")
    salt = data[len(BUNDLE_MAGIC):len(BUNDLE_MAGIC) + crypto.SALT_LEN]
    blob = data[len(BUNDLE_MAGIC) + crypto.SALT_LEN:]
    key = crypto.derive_key(password, salt, BUNDLE_ITERATIONS)
    try:
        raw = gzip.decompress(crypto.decrypt(blob, key, BUNDLE_AAD))
    except crypto.VaultCryptoError as exc:
        raise BundleError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise BundleError("文件已损坏或不完整") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise BundleError("内容解析失败：%s" % exc) from exc
    if not isinstance(payload, dict) or payload.get("format") != BUNDLE_FORMAT:
        raise BundleError("不是 AgentFloat 导出文件")
    payload.setdefault("config", {})
    payload.setdefault("secrets", {"keys": []})
    return payload


def describe_bundle(payload):
    """导入前预览信息（界面用）"""
    cfg = payload.get("config") or {}
    keys = ((payload.get("secrets") or {}).get("keys")) or []
    return {
        "account": ((payload.get("account") or {}).get("name") or ""),
        "app_version": payload.get("app_version") or "",
        "exported": payload.get("exported") or 0,
        "agents": len(cfg.get("agents") or []),
        "endpoints": len((cfg.get("api_monitor") or {}).get("endpoints") or []),
        "keys": [k.get("name") for k in keys],
        "theme": cfg.get("theme"),
    }


def write_bundle(path, data):
    folder = os.path.dirname(os.path.abspath(path))
    if folder:
        os.makedirs(folder, exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes(data))
    return path


def read_bundle(path):
    with open(path, "rb") as f:
        return f.read()
