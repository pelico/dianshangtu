"""设置 API 与存储往返测试：加密存储、Key 不泄露、角色映射校验。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import settings_store


@pytest.fixture(autouse=True)
def _clean_settings_table():
    """与其他测试共用一个临时库：每个用例前清空设置，保证互不污染。"""
    from app.db.database import connect
    with connect() as conn:
        conn.execute("DELETE FROM setting")
        conn.commit()
    yield


def client():
    return TestClient(app)


def test_get_settings_defaults():
    s = client().get("/api/settings").json()
    assert s["connection"]["base_url"] == ""
    assert s["connection"]["has_api_key"] is False
    assert set(s["roles"].keys()) == {"planner", "qa_vlm", "image_main", "image_alt", "video"}
    assert s["roles"]["image_main"]["mode"] == "edits"


def test_put_settings_roundtrip_and_masking():
    c = client()
    r = c.put("/api/settings", json={
        "connection": {"base_url": "https://gw.example.com/v1/", "api_key": "sk-abc"},
        "roles": {"image_main": {"model": "gpt-image-1", "concurrency": 3}},
    }).json()
    assert r["connection"]["base_url"] == "https://gw.example.com/v1"  # 去尾斜杠
    assert r["connection"]["has_api_key"] is True
    assert "api_key" not in r["connection"]  # 绝不回传明文 Key
    assert r["roles"]["image_main"]["model"] == "gpt-image-1"
    assert r["roles"]["image_main"]["concurrency"] == 3
    assert r["roles"]["image_main"]["timeout_s"] == 300  # 未改字段保留默认

    # 落库的是密文
    raw = settings_store._get_json(settings_store.APIKEY_KEY, {})
    assert raw["enc"] != "sk-abc"
    assert settings_store.get_api_key() == "sk-abc"

    # 留空 api_key 不清空已存值
    c.put("/api/settings", json={"connection": {"base_url": "https://gw.example.com/v1"}})
    assert settings_store.get_api_key() == "sk-abc"


def test_put_settings_rejects_unknown_role():
    r = client().put("/api/settings", json={"roles": {"hacker": {"model": "x"}}}).json()
    assert "hacker" not in r["roles"]


def test_test_connection_unconfigured():
    body = {"role": "planner"}
    r = client().request("POST", "/api/settings/test", json=body).json()
    assert r["results"][0]["ok"] is False
    assert "未配置" in r["results"][0]["detail"]
