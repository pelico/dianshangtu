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


def test_role_level_gateway_override():
    """角色可配置独立 Base URL / API Key；get_gateway 按角色优先取用。"""
    c = client()
    r = c.put("/api/settings", json={
        "connection": {"base_url": "http://global-gw/v1", "api_key": "sk-global"},
        "roles": {"image_main": {"model": "img-model", "base_url": "http://role-gw/v1",
                                 "api_key": "sk-role"}},
    })
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["roles"]["image_main"]["base_url"] == "http://role-gw/v1"
    assert s["roles"]["image_main"]["has_api_key"] is True   # 独立 Key 已存（不回传明文）
    assert "api_key" not in s["roles"]["image_main"]

    gw = settings_store.get_gateway("image_main")
    assert gw is not None
    assert gw.base == "http://role-gw/v1"                    # 用了角色级 base_url
    assert gw.headers["Authorization"] == "Bearer sk-role"   # 用了角色级 Key

    # 未配置独立连接的角色回退全局
    gw2 = settings_store.get_gateway("qa_vlm")
    assert gw2 is None  # 无模型名 → 不可用
    c.put("/api/settings", json={"roles": {"qa_vlm": {"model": "vlm-model"}}})
    gw3 = settings_store.get_gateway("qa_vlm")
    assert gw3.base == "http://global-gw/v1"
    assert gw3.headers["Authorization"] == "Bearer sk-global"

    # 清除独立 Key → 回退全局
    c.put("/api/settings", json={"roles": {"image_main": {"clear_api_key": True}}})
    gw4 = settings_store.get_gateway("image_main")
    assert gw4.base == "http://role-gw/v1"                   # base_url 仍是角色级
    assert gw4.headers["Authorization"] == "Bearer sk-global"
