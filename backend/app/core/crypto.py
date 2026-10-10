"""对称加密：用于 SQLite 中 API Key 等敏感设置的静态加密。

主密钥来自环境变量 APP_SECRET（PLAN_v2 §5），通过 SHA-256 派生 Fernet 密钥。
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import APP_SECRET


def _fernet() -> Fernet:
    key = hashlib.sha256(APP_SECRET.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(text: str) -> str:
    return _fernet().encrypt(text.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


__all__ = ["encrypt", "decrypt", "InvalidToken"]
