"""项目 API + 预设种子化 + 规划任务端到端（假网关）测试。"""
import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.providers.openai_compat import Gateway

PNG_1PX = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01" \
          b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01" \
          b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

PLAN_OK = {
    "product": {"name": "内胆包", "category": "laptop sleeve", "anchor": "red nylon sleeve, black zipper, UNBEGUN logo bottom-right", "selling_points": ["slim"]},
    "design_spec": {"style": "minimal tech", "palette": "#E02424/#111111/#007185", "copy_language": "English",
                    "canvas": "1464x600", "lighting": "soft studio, consistent"},
    "modules": [
        {"id": f"m{i}", "title_cn": f"模块{i}", "role": "hero", "scene": "desk",
         "product_pose": "flat", "photo_goal": "g", "visual_description": "d",
         "composition": "c", "text_side": "right", "headline": f"H{i}", "subline": "s"}
        for i in range(1, 4)
    ],
}


@pytest.fixture
def client():
    return TestClient(app)


def _png_file():
    return ("files", ("a.png", PNG_1PX, "image/png"))


def test_builtin_preset_seeded(client):
    presets = client.get("/api/presets").json()
    aplus = [p for p in presets if p["id"] == "aplus_banner"]
    assert aplus and aplus[0]["latest_version"] >= 1


def test_create_project_multipart(client):
    r = client.post("/api/projects", data={
        "name": "测试项目", "brief": "红色内胆包，强调防震",
        "params_json": json.dumps({"copy_language": "English", "n_modules": 3}),
    }, files=[_png_file(), _png_file()])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "测试项目"
    assert len(d["refs"]) == 2
    assert d["refs"][0]["order_no"] == 0 and d["refs"][0]["url"].startswith("/files/uploads/")
    assert d["latest_plan"] is None
    return d["id"]


def test_create_project_rejects_bad_image(client):
    r = client.post("/api/projects", data={}, files=[("files", ("x.png", b"not-an-image", "image/png"))])
    assert r.status_code == 400


def test_plan_job_end_to_end(client, monkeypatch):
    # 配置 planner 角色
    client.put("/api/settings", json={
        "connection": {"base_url": "https://gw.test/v1", "api_key": "sk-t"},
        "roles": {"planner": {"model": "planner-x"}},
    })

    calls = {"n": 0}

    def fake_chat(self, model, messages, temperature=None, response_format=None):
        calls["n"] += 1
        if calls["n"] == 1:
            # 第一次故意返回带围栏的内容（应被剥离并成功）
            return {"choices": [{"message": {"content": "```json\n" + json.dumps(PLAN_OK) + "\n```"}}]}
        return {"choices": [{"message": {"content": json.dumps(PLAN_OK)}}]}

    monkeypatch.setattr(Gateway, "chat", fake_chat)

    # 建项目
    pid = client.post("/api/projects", data={"brief": "test brief"}, files=[_png_file()]).json()["id"]

    # 触发规划
    r = client.post(f"/api/projects/{pid}/plan")
    assert r.status_code == 200, r.text

    # 等待后台线程完成
    deadline = time.time() + 10
    plan = None
    while time.time() < deadline:
        resp = client.get(f"/api/projects/{pid}/plan")
        if resp.status_code == 200:
            plan = resp.json()
            break
        time.sleep(0.2)
    assert plan, "plan job did not finish in time"
    assert plan["source"] == "ai"
    assert plan["revision"] == 1
    assert len(plan["plan"]["modules"]) == 3
    assert calls["n"] == 1  # 围栏剥离成功，未走重试

    # 项目状态与详情
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["status"] == "planned"
    assert detail["latest_plan"]["revision"] == 1
    assert any(j["kind"] == "plan" and j["status"] == "done" for j in detail["jobs"])

    # 再次触发 → 新 revision
    client.post(f"/api/projects/{pid}/plan")
    deadline = time.time() + 10
    while time.time() < deadline:
        p2 = client.get(f"/api/projects/{pid}/plan").json()
        if p2.get("revision") == 2:
            break
        time.sleep(0.2)
    assert p2["revision"] == 2

    # 项目列表
    lst = client.get("/api/projects").json()
    assert any(p["id"] == pid for p in lst)


def test_plan_without_config_fails_gracefully(client, monkeypatch):
    # 清掉 planner 配置 → 任务应 failed 且错误可读
    client.put("/api/settings", json={"connection": {"base_url": "", "roles": {"planner": {"model": ""}}}})
    pid = client.post("/api/projects", data={}, files=[_png_file()]).json()["id"]
    client.post(f"/api/projects/{pid}/plan")
    deadline = time.time() + 10
    detail = None
    while time.time() < deadline:
        detail = client.get(f"/api/projects/{pid}").json()
        if any(j["status"] in ("failed", "done") for j in detail["jobs"]):
            break
        time.sleep(0.2)
    job = next(j for j in detail["jobs"] if j["kind"] == "plan")
    assert job["status"] == "failed"
    assert "未配置" in (job["error"] or "")
