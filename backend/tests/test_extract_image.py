"""extract_image 兼容面测试：锁定 poc.py 的 4 类响应形态，重构不得改变行为。"""
import base64

import pytest
from requests import Response

from app.providers.openai_compat import Gateway

PNG = b"\x89PNG\r\n\x1a\nfakepng"
B64 = base64.b64encode(PNG).decode()


def fake_get(url, **kw):
    r = Response()
    r.status_code = 200
    r._content = PNG
    return r


@pytest.fixture
def gw():
    return Gateway("http://gw.test/v1", "sk-test")


def test_images_api_b64(gw):
    assert gw.extract_image({"data": [{"b64_json": B64}]}) == PNG


def test_images_api_url(gw, monkeypatch):
    monkeypatch.setattr("app.providers.openai_compat.requests.get", fake_get)
    assert gw.extract_image({"data": [{"url": "http://gw.test/img.png"}]}) == PNG


def test_openrouter_style(gw):
    res = {"choices": [{"message": {"images": [{"image_url": {"url": f"data:image/png;base64,{B64}"}}]}}]}
    assert gw.extract_image(res) == PNG


def test_content_data_url(gw):
    res = {"choices": [{"message": {"content": f"here you go data:image/png;base64,{B64} enjoy"}}]}
    assert gw.extract_image(res) == PNG


def test_content_http_url(gw, monkeypatch):
    monkeypatch.setattr("app.providers.openai_compat.requests.get", fake_get)
    res = {"choices": [{"message": {"content": "https://cdn.test/img.png"}}]}
    assert gw.extract_image(res) == PNG


def test_list_content(gw, monkeypatch):
    monkeypatch.setattr("app.providers.openai_compat.requests.get", fake_get)
    res = {"choices": [{"message": {"content": [
        {"type": "text", "text": "result:"},
        {"type": "image_url", "image_url": {"url": "https://cdn.test/a.png"}},
    ]}}]}
    assert gw.extract_image(res) == PNG


def test_no_image_raises(gw):
    with pytest.raises(RuntimeError, match="no image found"):
        gw.extract_image({"choices": [{"message": {"content": "sorry, no image"}}]})
