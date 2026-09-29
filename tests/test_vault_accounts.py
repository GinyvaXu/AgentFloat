# -*- coding: utf-8 -*-
"""v3.6.0 账户与密钥保险箱：加密原语 + 账户存储测试"""

import json
import os

import pytest

from agentfloat.services.vault import crypto
from agentfloat.services.vault.accounts import AccountStore, VaultError, mask_value


# ── 加密原语 ──────────────────────────────────────────────
def test_derive_key_stable_and_distinct():
    salt = b"0123456789abcdef"
    k1 = crypto.derive_key("pw-123456", salt, 1000)
    k2 = crypto.derive_key("pw-123456", salt, 1000)
    k3 = crypto.derive_key("pw-123457", salt, 1000)
    assert k1 == k2 and len(k1) == 32
    assert k1 != k3
    k4 = crypto.derive_key("pw-123456", b"fedcba9876543210", 1000)
    assert k4 != k1


def test_derive_key_rejects_empty():
    with pytest.raises(crypto.VaultCryptoError):
        crypto.derive_key("", b"0123456789abcdef")
    with pytest.raises(crypto.VaultCryptoError):
        crypto.derive_key("x", b"")


@pytest.mark.skipif(not crypto.HAVE_CRYPTO, reason="需要 cryptography")
def test_encrypt_decrypt_roundtrip_and_tamper():
    key = crypto.derive_key("pw-123456", b"0123456789abcdef", 1000)
    blob = crypto.encrypt_json({"a": 1, "b": "中文"}, key)
    assert blob.startswith(crypto.MAGIC)
    assert crypto.decrypt_json(blob, key) == {"a": 1, "b": "中文"}
    # 篡改 → 报错
    bad = bytearray(blob)
    bad[-1] ^= 0x01
    with pytest.raises(crypto.VaultCryptoError):
        crypto.decrypt(bytes(bad), key)
    # 错误密钥 → 报错
    other = crypto.derive_key("pw-999999", b"0123456789abcdef", 1000)
    with pytest.raises(crypto.VaultCryptoError):
        crypto.decrypt(blob, other)
    # 数据损坏
    with pytest.raises(crypto.VaultCryptoError):
        crypto.decrypt(b"AFV1short", key)


@pytest.mark.skipif(not crypto.dpapi_available(), reason="需要 Windows DPAPI")
def test_dpapi_roundtrip():
    token = crypto.dpapi_protect(b"secret-key-32-bytes-abcdefghijkl", b"pepper")
    assert crypto.dpapi_unprotect(token, b"pepper") == b"secret-key-32-bytes-abcdefghijkl"
    with pytest.raises(crypto.VaultCryptoError):
        crypto.dpapi_unprotect(token, b"other-pepper")


def test_mask_value():
    assert mask_value("") == ""
    assert mask_value("short") == "*****"
    assert mask_value("sk-1234567890abcdef") == "sk-1" + "*" * 11 + "cdef"


# ── 账户存储 ──────────────────────────────────────────────
@pytest.fixture()
def store(tmp_path):
    return AccountStore(path=str(tmp_path / "accounts.json"))


@pytest.mark.skipif(not crypto.HAVE_CRYPTO, reason="需要 cryptography")
def test_create_login_and_keys(store):
    with pytest.raises(VaultError):
        store.create_account("", "pw-123456")
    with pytest.raises(VaultError):
        store.create_account("a", "123")
    store.create_account("alice", "pw-123456")
    with pytest.raises(VaultError):
        store.create_account("alice", "pw-123456")
    with pytest.raises(VaultError):
        store.login("alice", "wrong-pw")
    store.login("alice", "pw-123456")
    assert store.unlocked()

    store.set_key("OPENCODE_GO_API_KEY", "sk-abcdefghijklmnop", "用于余额监控")
    store.set_key("DEEPSEEK_API_KEY", "sk-0123456789abcdef")
    names = [k["name"] for k in store.list_keys()]
    assert names == ["OPENCODE_GO_API_KEY", "DEEPSEEK_API_KEY"]
    masked = {k["name"]: k["value"] for k in store.list_keys()}
    assert masked["OPENCODE_GO_API_KEY"].startswith("sk-a") and "*" in masked["OPENCODE_GO_API_KEY"]
    assert store.get_key("DEEPSEEK_API_KEY") == "sk-0123456789abcdef"
    assert store.get_key("NOPE") is None

    # 覆盖同名 + 删除
    store.set_key("DEEPSEEK_API_KEY", "sk-updated-000000")
    assert store.get_key("DEEPSEEK_API_KEY") == "sk-updated-000000"
    store.delete_key("DEEPSEEK_API_KEY")
    with pytest.raises(VaultError):
        store.delete_key("DEEPSEEK_API_KEY")

    # 注入环境变量
    env = store.env_for_launch(base_env={})
    assert env["OPENCODE_GO_API_KEY"] == "sk-abcdefghijklmnop"

    # 落盘内容不含明文
    raw = open(store.path, encoding="utf-8").read()
    assert "sk-abcdefghijklmnop" not in raw
    assert "pw-123456" not in raw
    data = json.loads(raw)
    acc = data["accounts"][0]
    assert set(acc) >= {"id", "name", "salt", "hash", "secrets"}


@pytest.mark.skipif(not crypto.HAVE_CRYPTO, reason="需要 cryptography")
def test_relogin_unlocks_same_keys(store):
    store.create_account("bob", "pw-123456")
    store.login("bob", "pw-123456")
    store.set_key("K", "v-1234567890")
    store.logout()
    assert not store.unlocked()
    with pytest.raises(VaultError):
        store.list_keys()
    store.login("bob", "pw-123456")
    assert store.get_key("K") == "v-1234567890"


@pytest.mark.skipif(not crypto.HAVE_CRYPTO, reason="需要 cryptography")
def test_change_password_and_delete(store):
    store.create_account("carol", "pw-123456")
    store.login("carol", "pw-123456")
    store.set_key("TOKEN", "abc123456789")
    store.change_password("carol", "pw-123456", "pw-654321")
    with pytest.raises(VaultError):
        store.login("carol", "pw-123456")
    store.login("carol", "pw-654321")
    assert store.get_key("TOKEN") == "abc123456789"
    with pytest.raises(VaultError):
        store.delete_account("carol", "wrong")
    store.delete_account("carol", "pw-654321")
    assert store.list_accounts() == []


@pytest.mark.skipif(not crypto.HAVE_CRYPTO, reason="需要 cryptography")
def test_multi_accounts_and_active_switch(store):
    store.create_account("u1", "pw-123456")
    store.create_account("u2", "pw-123456")
    assert len(store.list_accounts()) == 2
    store.login("u1", "pw-123456")
    store.set_key("K1", "111111111111")
    store.login("u2", "pw-123456")
    store.set_key("K2", "222222222222")
    assert store.get_key("K1") is None
    assert store.get_key("K2") == "222222222222"
    store.login("u1", "pw-123456")
    assert store.get_key("K1") == "111111111111"
    assert [a["active"] for a in store.list_accounts()].count(True) == 1


@pytest.mark.skipif(not crypto.dpapi_available() or not crypto.HAVE_CRYPTO, reason="需要 DPAPI")
def test_quick_login_token(store):
    store.create_account("quick", "pw-123456")
    store.login("quick", "pw-123456", quick=True)
    store.set_key("K", "value-1234567")
    store.logout()
    assert store.has_quick_login()
    assert store.quick_login() is True
    assert store.get_key("K") == "value-1234567"
    store.disable_quick()
    store.logout()
    assert store.quick_login() is False


@pytest.mark.skipif(not crypto.HAVE_CRYPTO, reason="需要 cryptography")
def test_import_secrets_merges(store):
    store.create_account("imp", "pw-123456")
    store.login("imp", "pw-123456")
    store.set_key("A", "aaaaaaaaaaaa")
    total = store.import_secrets([
        {"name": "A", "value": "bbbbbbbbbbbb"},
        {"name": "B", "value": "cccccccccccc", "note": "来自导入"},
        {"name": "", "value": "ignored"},
    ])
    assert total == 2
    assert store.get_key("A") == "bbbbbbbbbbbb"
    assert store.get_key("B") == "cccccccccccc"


def test_load_corrupt_file_recovers(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text("{not json", encoding="utf-8")
    store = AccountStore(path=str(path))
    assert store.list_accounts() == []
    backups = [p for p in os.listdir(tmp_path) if "corrupt" in p]
    assert backups
