# -*- coding: utf-8 -*-
"""AgentFloat 账户与密钥保险箱 — 加密原语（v3.6.0）

- 口令派生：PBKDF2-HMAC-SHA256（默认 600k 次迭代，可用环境变量覆盖）
- 对称加密：AES-256-GCM（cryptography）；密文格式 ``AFV1`` + nonce(12) + ct+tag
- 本机快速登录：Windows DPAPI（CryptProtectData/CryptUnprotectData，绑定当前用户+机器）
- 随机：secrets.token_bytes

设计原则：只有「加密/解密/派生/DPAPI」四类原语，不含业务逻辑，便于单测。
"""
import base64
import ctypes
import hashlib
import os
import secrets
from ctypes import wintypes

MAGIC = b"AFV1"
NONCE_LEN = 12
SALT_LEN = 16
DEFAULT_ITERATIONS = 600_000

try:  # cryptography 为 3.6.0 起随包携带（此前构建被裁剪）
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAVE_CRYPTO = True
except Exception:  # noqa: BLE001
    AESGCM = None
    HAVE_CRYPTO = False


class VaultCryptoError(Exception):
    """加密/解密相关错误（口令错误、数据损坏、缺少 cryptography 等）"""


# ── 口令派生 ──────────────────────────────────────────────
def iterations_default():
    try:
        return max(50_000, int(os.environ.get("AGENTFLOAT_KDF_ITERATIONS", DEFAULT_ITERATIONS)))
    except (TypeError, ValueError):
        return DEFAULT_ITERATIONS


def new_salt():
    return secrets.token_bytes(SALT_LEN)


def derive_key(password, salt, iterations=None):
    """PBKDF2-HMAC-SHA256 → 32 字节密钥"""
    if not password:
        raise VaultCryptoError("口令不能为空")
    if not salt:
        raise VaultCryptoError("盐不能为空")
    it = int(iterations or iterations_default())
    return hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), bytes(salt), it, dklen=32)


def hash_password(password, salt, iterations=None):
    """口令校验用的哈希（与派生密钥同参数，便于单测对比）"""
    return derive_key(password, salt, iterations)


# ── 对称加密 ──────────────────────────────────────────────
def encrypt(data, key, aad=None):
    """AES-256-GCM 加密 → MAGIC + nonce + ciphertext(含 tag)"""
    if not HAVE_CRYPTO:
        raise VaultCryptoError("缺少 cryptography 组件，无法加密（请使用完整构建）")
    if not isinstance(data, (bytes, bytearray)):
        raise VaultCryptoError("待加密数据必须是 bytes")
    key = bytes(key)
    if len(key) != 32:
        raise VaultCryptoError("密钥长度必须为 32 字节")
    nonce = secrets.token_bytes(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, bytes(data), aad)
    return MAGIC + nonce + ct


def decrypt(blob, key, aad=None):
    """解密 encrypt() 的产物；口令错误/数据损坏抛 VaultCryptoError"""
    if not HAVE_CRYPTO:
        raise VaultCryptoError("缺少 cryptography 组件，无法解密（请使用完整构建）")
    blob = bytes(blob or b"")
    if len(blob) < len(MAGIC) + NONCE_LEN + 16 or not blob.startswith(MAGIC):
        raise VaultCryptoError("数据格式不正确或已损坏")
    nonce = blob[len(MAGIC):len(MAGIC) + NONCE_LEN]
    ct = blob[len(MAGIC) + NONCE_LEN:]
    try:
        return AESGCM(bytes(key)).decrypt(nonce, ct, aad)
    except Exception as exc:  # noqa: BLE001
        raise VaultCryptoError("解密失败：口令错误或数据已损坏") from exc


def encrypt_json(obj, key, aad=None):
    import json
    return encrypt(json.dumps(obj, ensure_ascii=False).encode("utf-8"), key, aad)


def decrypt_json(blob, key, aad=None):
    import json
    return json.loads(decrypt(blob, key, aad).decode("utf-8"))


# ── Windows DPAPI（本机快速登录）────────────────────────────
class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi_available():
    return hasattr(ctypes, "windll") and hasattr(ctypes.windll, "crypt32")


def dpapi_protect(data, entropy=None):
    """用当前 Windows 用户凭据保护数据（可在同机同事解密）"""
    if not dpapi_available():
        raise VaultCryptoError("当前系统不支持 DPAPI")
    blob_in = _DataBlob(len(data), ctypes.cast(ctypes.create_string_buffer(bytes(data)),
                                               ctypes.POINTER(ctypes.c_char)))
    blob_ent = None
    if entropy:
        blob_ent = _DataBlob(len(entropy), ctypes.cast(ctypes.create_string_buffer(bytes(entropy)),
                                                       ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, ctypes.byref(blob_ent) if blob_ent else None,
        None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise VaultCryptoError("DPAPI 加密失败")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def dpapi_unprotect(blob, entropy=None):
    """解密 dpapi_protect() 的产物（换机/换用户后失败）"""
    if not dpapi_available():
        raise VaultCryptoError("当前系统不支持 DPAPI")
    blob = bytes(blob or b"")
    if not blob:
        raise VaultCryptoError("DPAPI 数据为空")
    blob_in = _DataBlob(len(blob), ctypes.cast(ctypes.create_string_buffer(blob),
                                               ctypes.POINTER(ctypes.c_char)))
    blob_ent = None
    if entropy:
        blob_ent = _DataBlob(len(entropy), ctypes.cast(ctypes.create_string_buffer(bytes(entropy)),
                                                       ctypes.POINTER(ctypes.c_char)))
    blob_out = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, ctypes.byref(blob_ent) if blob_ent else None,
        None, None, 0, ctypes.byref(blob_out))
    if not ok:
        raise VaultCryptoError("DPAPI 解密失败（可能换机/换用户，或数据被修改）")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


# ── base64 便捷函数（文件/JSON 友好）──────────────────────
def b64e(data):
    return base64.b64encode(bytes(data)).decode("ascii")


def b64d(text):
    return base64.b64decode(str(text or "").encode("ascii"))
