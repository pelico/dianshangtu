"""gen_image 请求构造测试：edits 多参考图 multipart、size 传参、chat 模式消息结构。"""
import base64
import json

import pytest

from app.providers.openai_compat import Gateway

PNG = b"\x89PNG-fake"
B64 = base64.b64encode(PNG).decode()


@pytest.fixture
def gw(tmp_path):
    g = Gateway("http://gw.test/v1", "sk-test")
    # 两张假参考图
    for i in (1, 2):
        p = tmp_path / f"ref{i}.png"
        p.write_bytes(PNG)
    return g, [str(tmp_path / "ref1.png"), str(tmp_path / "ref2.png")]


def test_edits_mode(gw, monkeypatch):
    g, refs = gw
    captured = {}

    def fake_post(path, **kw):
        captured["path"], captured["files"], captured["data"] = path, kw.get("files"), kw.get("data")
        return {"data": [{"b64_json": B64}]}

    monkeypatch.setattr(g, "post", fake_post)
    out = g.gen_image("m1", "edits", "1536x1024", "PROMPT", refs)
    assert out == PNG
    assert captured["path"] == "/images/edits"
    assert [name for name, *_ in captured["files"]] == ["image[]", "image[]"]
    assert captured["data"]["size"] == "1536x1024"
    assert captured["data"]["n"] == "1"


def test_edits_empty_size_omitted(gw, monkeypatch):
    g, refs = gw
    captured = {}

    def fake_post(path, **kw):
        captured["data"] = kw.get("data")
        return {"data": [{"b64_json": B64}]}

    monkeypatch.setattr(g, "post", fake_post)
    g.gen_image("m1", "edits", "", "PROMPT", refs[:1])
    assert "size" not in captured["data"]


def test_chat_mode(gw, monkeypatch):
    g, refs = gw
    captured = {}

    def fake_post(path, **kw):
        captured["path"], captured["body"] = path, kw.get("json")
        return {"choices": [{"message": {"content": f"data:image/png;base64,{B64}"}}]}

    monkeypatch.setattr(g, "post", fake_post)
    out = g.gen_image("m1", "chat", "", "PROMPT", refs[:1])
    assert out == PNG
    assert captured["path"] == "/chat/completions"
    content = captured["body"]["messages"][0]["content"]
    assert content[0]["type"] == "text" and content[0]["text"] == "PROMPT"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_post_retries_then_raises(gw, monkeypatch):
    g, _ = gw
    calls = {"n": 0}

    def fake_post(*a, **kw):
        calls["n"] += 1
        raise AssertionError("should not be called directly here")

    class FakeResp:
        ok = False
        status_code = 500
        text = "boom"

    def fake_requests_post(*a, **kw):
        calls["n"] += 1
        return FakeResp()

    monkeypatch.setattr("app.providers.openai_compat.requests.post", fake_requests_post)
    g.retry_wait = 0
    with pytest.raises(Exception):
        g.post("/chat/completions", json={})
    assert calls["n"] == 2  # 与 poc.py 一致：2 次尝试后失败
