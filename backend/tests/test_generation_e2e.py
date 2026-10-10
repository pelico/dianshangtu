"""出图端到端测试（假网关）：规划→生成→资产元数据→下载→zip 导出。"""
import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.providers.openai_compat import Gateway

PNG_1PX = open(__file__, "rb").read(0) or None  # placeholder, replaced below


def _png_bytes(w=1536, h=1024, color=(224, 36, 36)):
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


REF_PNG = _png_bytes(800, 600, (180, 20, 20))

PLAN_OK = {
    "product": {"name": "内胆包", "category": "sleeve", "anchor": "ANCHOR-RED-SLEEVE", "selling_points": ["slim"]},
    "design_spec": {"style": "minimal tech", "palette": "#E02424", "copy_language": "English",
                    "canvas": "1464x600", "lighting": "soft studio"},
    "modules": [
        {"id": "m1", "title_cn": "主视觉", "role": "hero", "scene": "desk",
         "product_pose": "flat", "photo_goal": "g", "visual_description": "d",
         "composition": "c", "text_side": "right", "headline": "SLEEK", "subline": "s"},
        {"id": "m2", "title_cn": "功能", "role": "feature", "scene": "open",
         "product_pose": "open", "photo_goal": "g", "visual_description": "d",
         "composition": "c", "text_side": "right", "headline": "STORAGE", "subline": "s"},
    ],
}


@pytest.fixture
def client(monkeypatch):
    c = TestClient(app)
    c.put("/api/settings", json={
        "connection": {"base_url": "https://gw.test/v1", "api_key": "sk-t"},
        "roles": {"planner": {"model": "planner-x"}, "image_main": {"model": "img-x", "mode": "edits"}},
    })

    def fake_chat(self, model, messages, temperature=None, response_format=None):
        return {"choices": [{"message": {"content": json.dumps(PLAN_OK)}}]}

    gen_calls = {"n": 0, "last": None}

    def fake_gen_image(self, model, mode, size, prompt, refs):
        gen_calls["n"] += 1
        gen_calls["last"] = {"model": model, "mode": mode, "size": size,
                             "prompt": prompt, "n_refs": len(refs)}
        return _png_bytes()  # 1536x1024，需 fit 到 1464x600

    monkeypatch.setattr(Gateway, "chat", fake_chat)
    monkeypatch.setattr(Gateway, "gen_image", fake_gen_image)
    c.gen_calls = gen_calls
    return c


def _wait_for(fn, timeout=15, interval=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = fn()
        if v:
            return v
        time.sleep(interval)
    return None


def test_full_pipeline_generate_and_export(client):
    # 建项目 + 规划
    pid = client.post("/api/projects", data={"brief": "b"},
                      files=[("files", ("a.png", REF_PNG, "image/png")),
                             ("files", ("b.png", REF_PNG, "image/png"))]).json()["id"]
    client.post(f"/api/projects/{pid}/plan")
    assert _wait_for(lambda: client.get(f"/api/projects/{pid}/plan").status_code == 200)

    # 提示词预览：变量全部替换
    prompts = client.get(f"/api/projects/{pid}/prompts").json()
    assert len(prompts) == 2
    assert all("{{" not in p["prompt"] for p in prompts)
    assert all("ANCHOR-RED-SLEEVE" in p["prompt"] for p in prompts)

    # 批量出图（2 模块）
    r = client.post(f"/api/projects/{pid}/generate", json={})
    assert r.status_code == 200, r.text
    assert len(r.json()["job_ids"]) == 2

    assets = _wait_for(lambda: (lambda a: a if len(a) >= 2 else None)(
        client.get(f"/api/assets?project_id={pid}").json()))
    assert assets, "generation did not finish in time"

    # 元数据完整性（可复现性要求，PLAN_v2 §6）
    for a in assets:
        assert a["model"] == "img-x" and a["mode"] == "edits"
        assert a["prompt_text"] and "ANCHOR-RED-SLEEVE" in a["prompt_text"]
        assert json.loads(a["ref_hashes_json"]) and len(json.loads(a["ref_hashes_json"])) == 2
        assert a["preset_version_id"] and a["plan_revision"] == 1
        assert a["width"] == 1464 and a["height"] == 600  # fit 生效
        assert a["elapsed_s"] > 0
    # 出图调用参数
    gc = client.gen_calls
    assert gc["n"] == 2 and gc["last"]["model"] == "img-x" and gc["last"]["mode"] == "edits"
    assert gc["last"]["size"] == "1536x1024" and gc["last"]["n_refs"] == 2

    # 项目状态
    assert client.get(f"/api/projects/{pid}").json()["status"] == "generating"

    # 单张下载（成品与 raw）
    aid = assets[0]["id"]
    r = client.get(f"/api/assets/{aid}/download")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (1464, 600)
    r_raw = client.get(f"/api/assets/{aid}/download?raw=1")
    assert r_raw.status_code == 200
    assert Image.open(io.BytesIO(r_raw.content)).size == (1536, 1024)

    # zip 导出：每个模块一张，按模块命名
    r_zip = client.get(f"/api/projects/{pid}/export.zip")
    assert r_zip.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r_zip.content))
    assert sorted(z.namelist()) == ["m1.png", "m2.png"]

    # 带覆盖提示词重出 m1 → 新 asset，prompt_edited=1
    n_before = len(client.get(f"/api/assets?project_id={pid}").json())
    client.post(f"/api/projects/{pid}/generate",
                json={"module_ids": ["m1"], "overrides": {"m1": "OVERRIDE-MARK-PROMPT"}})
    assets2 = _wait_for(lambda: (lambda a: a if len(a) > n_before else None)(
        client.get(f"/api/assets?project_id={pid}").json()))
    assert assets2
    new = max(assets2, key=lambda a: a["id"])
    assert new["module_id"] == "m1" and new["prompt_edited"] == 1
    assert "OVERRIDE-MARK-PROMPT" in new["prompt_text"]


def test_generate_without_plan_fails(client):
    pid = client.post("/api/projects", data={},
                      files=[("files", ("a.png", REF_PNG, "image/png"))]).json()["id"]
    r = client.post(f"/api/projects/{pid}/generate", json={})
    assert r.status_code in (400, 500)
