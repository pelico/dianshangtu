"""M3 测试：方案编辑、单图重出、品牌档案、预设版本/回滚/试跑。"""
import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.providers.openai_compat import Gateway


def _png_bytes(w=1536, h=1024, color=(224, 36, 36)):
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


REF_PNG = _png_bytes(800, 600, (180, 20, 20))

PLAN_OK = {
    "product": {"name": "内胆包", "category": "sleeve", "anchor": "ANCHOR-RED-SLEEVE", "selling_points": []},
    "design_spec": {"style": "minimal tech", "palette": "#E02424", "copy_language": "English",
                    "canvas": "1464x600", "lighting": "soft studio"},
    "modules": [
        {"id": "m1", "title_cn": "主视觉", "role": "hero", "scene": "desk",
         "product_pose": "flat", "photo_goal": "g", "visual_description": "d",
         "composition": "c", "text_side": "right", "headline": "SLEEK", "subline": "s"},
    ],
}


def _wait_for(fn, timeout=15, interval=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = fn()
        if v:
            return v
        time.sleep(interval)
    return None


@pytest.fixture
def client(monkeypatch):
    c = TestClient(app)
    c.put("/api/settings", json={
        "connection": {"base_url": "https://gw.test/v1", "api_key": "sk-t"},
        "roles": {"planner": {"model": "planner-x"},
                  "image_main": {"model": "img-main", "mode": "edits"},
                  "image_alt": {"model": "img-alt", "mode": "edits"}},
    })

    def fake_chat(self, model, messages, temperature=None, response_format=None):
        return {"choices": [{"message": {"content": json.dumps(PLAN_OK)}}]}

    def fake_gen_image(self, model, mode, size, prompt, refs):
        return _png_bytes()

    monkeypatch.setattr(Gateway, "chat", fake_chat)
    monkeypatch.setattr(Gateway, "gen_image", fake_gen_image)
    return c


def _make_planned_project(client, monkeypatch=None):
    pid = client.post("/api/projects", data={"brief": "b"},
                      files=[("files", ("a.png", REF_PNG, "image/png"))]).json()["id"]
    client.post(f"/api/projects/{pid}/plan")
    assert _wait_for(lambda: client.get(f"/api/projects/{pid}/plan").status_code == 200)
    return pid


def test_put_plan_creates_user_revision(client):
    pid = _make_planned_project(client)
    edited = json.loads(json.dumps(PLAN_OK))
    edited["modules"][0]["headline"] = "EDITED-HEADLINE"
    r = client.put(f"/api/projects/{pid}/plan", json={"plan": edited})
    assert r.status_code == 200, r.text
    assert r.json()["revision"] == 2 and r.json()["source"] == "user_edit"

    plan = client.get(f"/api/projects/{pid}/plan").json()
    assert plan["revision"] == 2 and plan["plan"]["modules"][0]["headline"] == "EDITED-HEADLINE"


def test_put_plan_rejects_invalid(client):
    pid = _make_planned_project(client)
    bad = {"modules": []}
    r = client.put(f"/api/projects/{pid}/plan", json={"plan": bad})
    assert r.status_code == 400


def test_regenerate_with_override_and_role(client):
    pid = _make_planned_project(client)
    client.post(f"/api/projects/{pid}/generate", json={"module_ids": ["m1"]})
    assets = _wait_for(lambda: (lambda a: a if len(a) >= 1 else None)(
        client.get(f"/api/assets?project_id={pid}").json()))
    old = assets[0]
    assert old["model"] == "img-main"

    # 改提示词 + 换备选模型重出
    r = client.post(f"/api/assets/{old['id']}/regenerate",
                    json={"prompt_text": "OVERRIDDEN PROMPT XYZ", "model_ref": "image_alt"})
    assert r.status_code == 200, r.text
    new = _wait_for(lambda: next(
        (a for a in client.get(f"/api/assets?project_id={pid}").json() if a["parent_asset_id"]),
        None))
    assert new["parent_asset_id"] == old["id"]
    assert new["prompt_edited"] == 1 and "OVERRIDDEN PROMPT XYZ" in new["prompt_text"]
    assert new["model"] == "img-alt"  # 换模型生效

    # 版本链：新旧并存，不覆盖
    lst = client.get(f"/api/assets?project_id={pid}").json()
    assert {a["id"] for a in lst} == {old["id"], new["id"]}


def test_brand_profile_crud_and_injection(client):
    # CRUD
    p = client.post("/api/brand-profiles", json={
        "name": "UNBEGUN", "body": {"brand_tone": "premium tech minimal",
                                    "brand_colors": "#E02424/#111111",
                                    "forbidden_words": ["cheap", "best"]}}).json()
    assert p["id"] and p["body"]["brand_tone"] == "premium tech minimal"
    upd = client.put(f"/api/brand-profiles/{p['id']}", json={
        "name": "UNBEGUN2", "body": {"brand_tone": "updated tone"}}).json()
    assert upd["name"] == "UNBEGUN2"
    lst = client.get("/api/brand-profiles").json()
    assert any(x["id"] == p["id"] for x in lst)

    # 绑定到项目后，出图提示词注入品牌变量
    pid = client.post("/api/projects", data={"brief": "b", "brand_profile_id": p["id"]},
                      files=[("files", ("a.png", REF_PNG, "image/png"))]).json()["id"]
    client.post(f"/api/projects/{pid}/plan")
    assert _wait_for(lambda: client.get(f"/api/projects/{pid}/plan").status_code == 200)
    client.post(f"/api/projects/{pid}/generate", json={})
    assets = _wait_for(lambda: (lambda a: a if len(a) >= 1 else None)(
        client.get(f"/api/assets?project_id={pid}").json()))
    # 建项目前档案已整体更新为 {"brand_tone": "updated tone"} → 注入更新后的 body
    assert "BRAND TONE: updated tone" in assets[0]["prompt_text"]
    assert "FORBIDDEN WORDS" not in assets[0]["prompt_text"]  # 更新时 body 被整体替换

    # 删除
    assert client.delete(f"/api/brand-profiles/{p['id']}").json()["ok"] is True
    assert client.delete(f"/api/brand-profiles/{p['id']}").status_code == 404


def test_preset_versions_rollback(client):
    versions = client.get("/api/presets/aplus_banner/versions").json()
    v1 = versions[-1]  # 最早版本
    assert v1["version"] == 1

    # 保存新版本（合法 body：取 v1 改名字）
    v1_body = client.get("/api/presets/aplus_banner/versions/1").json()["body"]
    v1_body["name"] = "改名测试"
    r = client.post("/api/presets/aplus_banner/versions", json={"body": v1_body})
    assert r.status_code == 200 and r.json()["version"] == 2

    # 非法 body 被拒
    r = client.post("/api/presets/aplus_banner/versions", json={"body": {"foo": 1}})
    assert r.status_code == 400

    # 回滚到 v1 → 产生 v3（内容同 v1），旧版本只读保留
    r = client.post("/api/presets/aplus_banner/rollback", json={"version": 1})
    assert r.status_code == 200 and r.json()["version"] == 3
    v3 = client.get("/api/presets/aplus_banner/versions/3").json()
    assert v3["body"]["planner"]["system_prompt"] == v1_body["planner"]["system_prompt"]
    assert v3["body"]["name"] == "亚马逊 A+ 横幅"


def test_preset_test_run(client):
    r = client.post("/api/presets/aplus_banner/test-run",
                    files=[("file", ("a.png", REF_PNG, "image/png"))],
                    data={"brief": "test"})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    def done():
        j = client.get(f"/api/jobs/{job_id}").json()
        return j if j["status"] in ("done", "failed") else None
    job = _wait_for(done)
    assert job["status"] == "done", job.get("error")
    res = job["payload"]["result"]
    assert res["image_url"].startswith("/files/test_runs/")
    assert res["plan"]["product"]["anchor"] == "ANCHOR-RED-SLEEVE"
    assert res["prompt"].startswith("Create a professional e-commerce banner")
    # 试跑不创建项目记录（__testrun__ 不入库 project 表）
