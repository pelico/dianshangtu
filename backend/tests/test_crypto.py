import pytest
from cryptography.fernet import InvalidToken

import app.core.crypto as crypto


def test_roundtrip():
    secret = "sk-gateway-key-123"
    token = crypto.encrypt(secret)
    assert token != secret
    assert crypto.decrypt(token) == secret


def test_wrong_secret_fails():
    token = crypto.encrypt("data")
    original = crypto.APP_SECRET
    try:
        crypto.APP_SECRET = "another-secret"  # 模拟 APP_SECRET 变化后旧密文不可解
        with pytest.raises(InvalidToken):
            crypto.decrypt(token)
    finally:
        crypto.APP_SECRET = original
    assert crypto.decrypt(token) == "data"
