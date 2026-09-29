# -*- coding: utf-8 -*-
"""AgentFloat 本地多账户 + API Key 保险箱（v3.6.0）

文件：``%APPDATA%\\AgentFloat\\accounts.json``（原子写入）

    {
      "version": 1,
      "active": "u_xxx",
      "accounts": [{
        "id": "u_xxx", "name": "zhenl", "created": ts, "last_login": ts,
        "iter": 600000, "salt": b64, "hash": "sha256(pepper+key)",
        "quick": {"token": b64(dpapi(key)), "expires": ts} | null,
        "secrets": {"blob": b64(AES-GCM(payload))} | null
      }]
    }

安全要点：
- 校验哈希与加密密钥分离（hash = SHA256(pepper + derived_key)），避免持有文件即可解密
- 保险箱载荷用 AES-256-GCM 加密，密钥由账户口令 PBKDF2 派生（每账户独立随机盐）
- 「快速登录」= DPAPI 保护派生密钥（仅本机本用户可用，可设有效期）；登出即清除会话
- 会话密钥只存在内存（``_session``），不落盘
"""
import copy
import json
import os
import secrets
import time

from agentfloat.core.paths import config_dir
from agentfloat.services.vault import crypto

VERIFY_PEPPER = b"AgentFloat/verify/v1"
DEFAULT_QUICK_DAYS = 14
MIN_PASSWORD_LEN = 6


class VaultError(Exception):
    """账户/保险箱业务错误（面向界面提示）"""


def _now():
    return time.time()


def _accounts_path():
    return os.path.join(config_dir(), "accounts.json")


def mask_value(value):
    """密钥掩码显示：保留首尾各 4 位"""
    text = str(value or "")
    if len(text) <= 10:
        return "*" * len(text)
    return text[:4] + "*" * (len(text) - 8) + text[-4:]


class AccountStore(object):
    """本地账户与密钥保险箱（一个实例对应一个 accounts.json）"""

    def __init__(self, path=None):
        self.path = path or _accounts_path()
        self._data = {"version": 1, "active": None, "accounts": []}
        self._session = None      # {"id": str, "key": bytes}
        self._secrets_cache = None
        self.load()

    # ── 持久化 ────────────────────────────────────────
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("accounts"), list):
                self._data = data
                self._data.setdefault("version", 1)
        except FileNotFoundError:
            self._data = {"version": 1, "active": None, "accounts": []}
        except Exception:  # noqa: BLE001
            # 损坏时不覆盖：改名保留，重新开始
            try:
                os.replace(self.path, self.path + ".corrupt_" + time.strftime("%Y%m%d_%H%M%S") + ".bak")
            except Exception:  # noqa: BLE001
                pass
            self._data = {"version": 1, "active": None, "accounts": []}
        return self._data

    def save(self):
        folder = os.path.dirname(self.path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ── 账户查询 ──────────────────────────────────────
    def _find(self, name_or_id, by_id=False):
        key = str(name_or_id or "")
        for acc in self._data.get("accounts", []):
            if (acc.get("id") == key) if by_id else (acc.get("name") == key):
                return acc
        return None

    def list_accounts(self):
        active = self._data.get("active")
        return [{
            "id": a.get("id"),
            "name": a.get("name"),
            "active": a.get("id") == active,
            "created": a.get("created"),
            "last_login": a.get("last_login"),
            "has_keys": bool(a.get("secrets")),
            "quick": bool(a.get("quick")),
            "unlocked": bool(self._session and self._session.get("id") == a.get("id")),
        } for a in self._data.get("accounts", [])]

    def active_account(self):
        return self._find(self._data.get("active") or "", by_id=True)

    def has_quick_login(self):
        acc = self.active_account()
        if not acc or not acc.get("quick"):
            return False
        try:
            return float(acc["quick"].get("expires") or 0) > _now()
        except (TypeError, ValueError):
            return False

    # ── 账户管理 ──────────────────────────────────────
    def create_account(self, name, password):
        name = str(name or "").strip()
        if not name:
            raise VaultError("账户名不能为空")
        if self._find(name):
            raise VaultError("账户已存在：%s" % name)
        if len(str(password or "")) < MIN_PASSWORD_LEN:
            raise VaultError("口令至少 %d 位" % MIN_PASSWORD_LEN)
        salt = crypto.new_salt()
        it = crypto.iterations_default()
        key = crypto.derive_key(password, salt, it)
        acc = {
            "id": "u_" + secrets.token_hex(6),
            "name": name,
            "created": _now(),
            "last_login": None,
            "iter": it,
            "salt": crypto.b64e(salt),
            "hash": crypto.b64e(self._verify_hash(key)),
            "quick": None,
            "secrets": None,
        }
        self._data.setdefault("accounts", []).append(acc)
        self.save()
        return acc["id"]

    def _verify_hash(self, key):
        import hashlib
        return hashlib.sha256(VERIFY_PEPPER + bytes(key)).digest()

    def _check_password(self, acc, password):
        import hmac
        try:
            salt = crypto.b64d(acc.get("salt"))
            it = int(acc.get("iter") or crypto.iterations_default())
            stored = crypto.b64d(acc.get("hash"))
        except Exception as exc:  # noqa: BLE001
            raise VaultError("账户数据损坏：%s" % exc) from exc
        key = crypto.derive_key(password, salt, it)
        if not hmac.compare_digest(self._verify_hash(key), stored):
            raise VaultError("口令不正确")
        return key

    def login(self, name, password, quick=False, quick_days=DEFAULT_QUICK_DAYS):
        """校验口令并解锁保险箱；quick=True 时写入本机快速登录令牌"""
        acc = self._find(name)
        if not acc:
            raise VaultError("账户不存在：%s" % name)
        key = self._check_password(acc, password)
        self._unlock(acc, key)
        acc["last_login"] = _now()
        self._data["active"] = acc.get("id")
        if quick:
            try:
                acc["quick"] = {
                    "token": crypto.b64e(crypto.dpapi_protect(key, VERIFY_PEPPER)),
                    "expires": _now() + max(1, int(quick_days)) * 86400,
                }
            except crypto.VaultCryptoError:
                acc["quick"] = None      # 系统不支持 DPAPI 时静默降级
        self.save()
        return acc.get("id")

    def quick_login(self):
        """用本机快速登录令牌解锁（失败返回 False，不抛异常）"""
        acc = self.active_account()
        if not acc or not acc.get("quick"):
            return False
        try:
            if float(acc["quick"].get("expires") or 0) <= _now():
                acc["quick"] = None
                self.save()
                return False
            key = crypto.dpapi_unprotect(crypto.b64d(acc["quick"]["token"]), VERIFY_PEPPER)
            self._unlock(acc, key)
            acc["last_login"] = _now()
            self.save()
            return True
        except Exception:  # noqa: BLE001
            return False

    def logout(self):
        self._session = None
        self._secrets_cache = None

    def disable_quick(self, name=None):
        acc = self._find(name) if name else self.active_account()
        if acc:
            acc["quick"] = None
            self.save()

    def change_password(self, name, old_password, new_password):
        acc = self._find(name)
        if not acc:
            raise VaultError("账户不存在：%s" % name)
        if len(str(new_password or "")) < MIN_PASSWORD_LEN:
            raise VaultError("新口令至少 %d 位" % MIN_PASSWORD_LEN)
        old_key = self._check_password(acc, old_password)
        payload = self._decrypt_secrets(acc, old_key)
        salt = crypto.new_salt()
        it = crypto.iterations_default()
        new_key = crypto.derive_key(new_password, salt, it)
        acc["salt"] = crypto.b64e(salt)
        acc["iter"] = it
        acc["hash"] = crypto.b64e(self._verify_hash(new_key))
        acc["quick"] = None
        self._encrypt_secrets(acc, new_key, payload)
        self._unlock(acc, new_key)
        self.save()

    def delete_account(self, name, password):
        acc = self._find(name)
        if not acc:
            raise VaultError("账户不存在：%s" % name)
        self._check_password(acc, password)      # 需口令确认
        self._data["accounts"] = [a for a in self._data.get("accounts", []) if a is not acc]
        if self._data.get("active") == acc.get("id"):
            self._data["active"] = None
        self.logout()
        self.save()

    def set_active(self, account_id):
        acc = self._find(account_id, by_id=True)
        if not acc:
            raise VaultError("账户不存在")
        self._data["active"] = acc.get("id")
        self.save()
        return acc.get("name")

    # ── 保险箱解锁/加解密 ──────────────────────────────
    def _unlock(self, acc, key):
        self._session = {"id": acc.get("id"), "key": bytes(key)}
        self._secrets_cache = None

    def unlocked(self):
        return bool(self._session and self._session.get("key"))

    def _current(self):
        if not self.unlocked():
            raise VaultError("请先登录账户以解锁密钥保险箱")
        acc = self._find(self._session["id"], by_id=True)
        if not acc:
            raise VaultError("会话失效，请重新登录")
        return acc, self._session["key"]

    def _decrypt_secrets(self, acc, key):
        blob = (acc.get("secrets") or {}).get("blob")
        if not blob:
            return {"keys": []}
        try:
            data = crypto.decrypt_json(crypto.b64d(blob), key, VERIFY_PEPPER)
        except crypto.VaultCryptoError as exc:
            raise VaultError(str(exc)) from exc
        if not isinstance(data, dict):
            return {"keys": []}
        data.setdefault("keys", [])
        return data

    def _encrypt_secrets(self, acc, key, payload):
        blob = crypto.encrypt_json(payload, key, VERIFY_PEPPER)
        acc["secrets"] = {"blob": crypto.b64e(blob)}

    def _payload(self):
        acc, key = self._current()
        if self._secrets_cache is None:
            self._secrets_cache = self._decrypt_secrets(acc, key)
        return acc, key, self._secrets_cache

    # ── API Key 管理 ──────────────────────────────────
    def list_keys(self, reveal=False):
        """列出密钥；默认掩码，reveal=True 需已解锁"""
        _acc, _key, payload = self._payload()
        out = []
        for item in payload.get("keys", []):
            out.append({
                "name": item.get("name"),
                "value": item.get("value") if reveal else mask_value(item.get("value")),
                "note": item.get("note", ""),
                "updated": item.get("updated"),
            })
        return out

    def get_key(self, name):
        _acc, _key, payload = self._payload()
        for item in payload.get("keys", []):
            if item.get("name") == name:
                return item.get("value")
        return None

    def set_key(self, name, value, note=""):
        name = str(name or "").strip()
        if not name:
            raise VaultError("密钥名称不能为空")
        if not name.replace("_", "").replace("-", "").isalnum():
            raise VaultError("密钥名称只能用字母/数字/下划线/连字符（便于作为环境变量注入）")
        acc, key, payload = self._payload()
        for item in payload.get("keys", []):
            if item.get("name") == name:
                item["value"] = str(value or "")
                item["note"] = str(note or "")
                item["updated"] = _now()
                break
        else:
            payload.setdefault("keys", []).append({
                "name": name, "value": str(value or ""), "note": str(note or ""), "updated": _now(),
            })
        self._encrypt_secrets(acc, key, payload)
        self.save()

    def delete_key(self, name):
        acc, key, payload = self._payload()
        before = len(payload.get("keys", []))
        payload["keys"] = [i for i in payload.get("keys", []) if i.get("name") != name]
        if len(payload["keys"]) == before:
            raise VaultError("密钥不存在：%s" % name)
        self._encrypt_secrets(acc, key, payload)
        self.save()

    def env_for_launch(self, base_env=None):
        """返回注入给 Agent 子进程的环境变量（已解锁时含保险箱密钥）"""
        env = dict(base_env or os.environ)
        try:
            _acc, _key, payload = self._payload()
        except VaultError:
            return env
        for item in payload.get("keys", []):
            name = str(item.get("name") or "")
            if name:
                env[name] = str(item.get("value") or "")
        return env

    # ── 导出/导入（供 exporter 使用）────────────────────
    def snapshot_for_export(self, include_secrets=True, reveal_values=True):
        """导出用：账户信息 + 可选密钥明文（仅内存，落盘前由调用方加密）"""
        acc = self.active_account()
        data = {
            "account": {"name": (acc or {}).get("name"), "created": (acc or {}).get("created")},
            "keys": [],
        }
        if include_secrets and self.unlocked():
            data["keys"] = copy.deepcopy(self._payload()[2].get("keys", []))
            if not reveal_values:
                for item in data["keys"]:
                    item["value"] = mask_value(item.get("value"))
        return data

    def import_secrets(self, keys):
        """导入密钥（覆盖同名）"""
        acc, key, payload = self._payload()
        existing = {i.get("name"): i for i in payload.get("keys", [])}
        for item in keys or []:
            name = str((item or {}).get("name") or "").strip()
            if not name:
                continue
            existing[name] = {
                "name": name,
                "value": str(item.get("value") or ""),
                "note": str(item.get("note") or ""),
                "updated": _now(),
            }
        payload["keys"] = list(existing.values())
        self._encrypt_secrets(acc, key, payload)
        self.save()
        return len(payload["keys"])
