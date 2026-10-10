"""M4 质检/成本、M5 主图合成、M6 视频 的单元与端到端测试（假网关）。"""
import io
import json
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.providers.openai_compat import Gateway
from app.services.qa import deterministic_checks
from app.services.video import extract_video_url


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
    ],
}

SHOTS_OK = {"shots": [
    {"index": 1, "description": "hero orbit", "motion": "slow orbit", "duration_s": 5,
     "prompt": "slow orbit around the product, identical product"},
]}

QA_FAIL = {"score": 2, "color_ok": True, "shape_ok": False, "logo_ok": True,
           "details_ok": True, "issues": ["product shape drifted"]}
QA_PASS = {"score": 5, "color_ok": True, "shape_ok": True, "logo_ok": True,
           "details_ok": True, "issues": []}


def _wait_for(fn, timeout=20, interval=0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = fn()
        if v:
            return v
        time.sleep(interval)
    return None


# ---------- 第 1 段：确定性检查 ----------

def test_deterministic_size_check(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(_png_bytes(1464, 600))
    ok, issues, _ = deterministic_checks(str(p), (1464, 600), {"checks": ["size"]})
    assert ok and not issues

    p2 = tmp_path / "b.png"
    p2.write_bytes(_png_bytes(800, 600))
    ok, issues, _ = deterministic_checks(str(p2), (1464, 600), {"checks": ["size"]})
    assert not ok and any("size" in i for i in issues)


def test_deterministic_white_bg_rules(tmp_path):
    # 白底 + 居中暗块（占比 ~0.47）→ 通过；全红 → white_bg 失败
    img = Image.new("RGB", (1600, 1600), (255, 255, 255))
    for x in range(250, 1350):
        for y in range(250, 1350):
            img.putpixel((x, y), (180, 20, 20))
    p = tmp_path / "ok.png"
    img.save(p)
    ok, issues, details = deterministic_checks(
        str(p), (1600, 1600),
        {"checks": ["white_bg", "product_ratio", "min_edge"], "min_edge_px": 1600,
         "product_ratio_min": 0.4, "product_ratio_max": 0.9})
    assert ok, issues

    p2 = tmp_path / "bad.png"
    p2.write_bytes(_png_bytes(1600, 1600, (200, 30, 30)))
    ok, issues, _ = deterministic_checks(
        str(p2), (1600, 1600),
        {"checks": ["white_bg", "product_ratio", "min_edge"], "min_edge_px": 1600})
    assert not ok and any("white" in i for i in issues)


# ---------- M4 端到端：QA 失败 → 自动重试 → needs_review → 人工放行；成本统计 ----------

@pytest.fixture
def client(monkeypatch):
    c = TestClient(app)
    c.put("/api/settings", json={
        "connection": {"base_url": "https://gw.test/v1", "api_key": "sk-t"},
        "roles": {"planner": {"model": "planner-x", "unit_price": 0.01},
                  "image_main": {"model": "img-x", "mode": "edits", "unit_price": 0.5},
                  "qa_vlm": {"model": "qa-x", "unit_price": 0.02}},
    })

    state = {"qa_fail_times": 99, "gen_n": 0, "qa_found_text": ["SLEEK", "s"]}

    def fake_chat(self, model, messages, temperature=None, response_format=None):
        sys_text = json.dumps(messages[0]["content"], ensure_ascii=False)
        if "QA inspector" in sys_text:
            if state["gen_n"] <= state["qa_fail_times"]:
                return {"choices": [{"message": {"content": json.dumps(QA_FAIL)}}]}
            return {"choices": [{"message": {"content": json.dumps(QA_PASS)}}]}
        if "proofreader" in sys_text:
            return {"choices": [{"message": {"content": json.dumps(
                {"found_text": state["qa_found_text"], "issues": []})}}]}
        if "short-video director" in sys_text:
            return {"choices": [{"message": {"content": json.dumps(SHOTS_OK)}}]}
        return {"choices": [{"message": {"content": json.dumps(PLAN_OK)}}]}

    def fake_gen_image(self, model, mode, size, prompt, refs):
        state["gen_n"] += 1
        state["last_prompt"] = prompt
        return _png_bytes()

    monkeypatch.setattr(Gateway, "chat", fake_chat)
    monkeypatch.setattr(Gateway, "gen_image", fake_gen_image)
    c.state = state
    return c


def _make_project(client, preset_id="aplus_banner"):
    return client.post("/api/projects", data={"brief": "b", "preset_id": preset_id},
                       files=[("files", ("a.png", REF_PNG, "image/png"))]).json()["id"]


def _pin_aplus_v1(pid):
    """把项目钉回 aplus v1（避免前一个测试插入的 v2 white_bg 检查泄漏）。"""
    from app.db.database import connect
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM preset_version WHERE preset_id='aplus_banner' AND version=1").fetchone()
        conn.execute("UPDATE project SET preset_version_id=? WHERE id=?", (row["id"], pid))
        conn.commit()


def _force_white_bg_fail(client):
    """把 aplus 预设升到 v2：加 white_bg 确定性检查（红图必挂），逼出自动重试。"""
    from app.db.database import connect
    from app.presets.builtin import _body
    body = _body(2)
    body["version"] = 2
    body["qa"]["checks"] = ["size", "white_bg"]
    body["qa"]["white_bg_dev"] = 8
    with connect() as conn:
        conn.execute("DELETE FROM preset_version WHERE preset_id='aplus_banner' AND version=2")
        conn.execute("INSERT INTO preset_version(preset_id, version, body_json) "
                     "VALUES ('aplus_banner', 2, ?)",
                     (json.dumps(body, ensure_ascii=False),))
        conn.commit()


def test_m4_qa_retry_review_and_stats(client):
    _force_white_bg_fail(client)
    pid = _make_project(client)  # 取最新版本 → v2（含 white_bg 检查）
    client.post(f"/api/projects/{pid}/plan")
    assert _wait_for(lambda: client.get(f"/api/projects/{pid}/plan").status_code == 200)

    r = client.post(f"/api/projects/{pid}/generate", json={"module_ids": ["m1"]})
    assert r.status_code == 200, r.text

    # 预设 max_auto_retries=2 → 共 3 次生成（初次 + 2 次重试），最终 needs_review
    assets = _wait_for(lambda: (lambda a: a if len(a) >= 3 else None)(
        client.get(f"/api/assets?project_id={pid}").json()))
    assert assets, "qa retry loop did not finish"
    final = max(assets, key=lambda a: a["id"])
    assert client.state["gen_n"] == 3
    assert final["qa_status"] == "needs_review"
    qa = json.loads(final["qa_json"])
    assert qa["status"] == "fail" and qa["vlm"] == "used" and qa["issues"]
    # 重试时 issues 追加进了 AVOID
    assert "PREVIOUS ATTEMPT ISSUES" in final["prompt_text"]
    assert final["attempt"] == 2
    # 成本：出图 0.5×3 + qa_vlm 单价×调用次数（按资产求和）
    assets_all = client.get(f"/api/assets?project_id={pid}").json()
    total_cost = sum(a["cost_estimate"] for a in assets_all)
    assert total_cost >= 0.5 * 3

    # 人工放行
    r = client.post(f"/api/assets/{final['id']}/approve", json={"note": "可接受"})
    assert r.status_code == 200 and r.json()["qa_status"] == "approved"

    # 成本统计
    st = client.get("/api/stats/cost").json()
    assert st["total"]["assets"] >= 3
    roles = {r["role"]: r for r in st["by_role"]}
    assert roles.get("image_main", {}).get("n", 0) >= 3
    assert st["by_project"] and st["by_day"]


def test_m4_qa_pass_first_try(client):
    client.state["qa_fail_times"] = -1  # 一次性通过（gen_n 从 1 起 > 0 → 直接 PASS）
    pid = _make_project(client)
    _pin_aplus_v1(pid)
    client.post(f"/api/projects/{pid}/plan")
    assert _wait_for(lambda: client.get(f"/api/projects/{pid}/plan").status_code == 200)
    client.post(f"/api/projects/{pid}/generate", json={"module_ids": ["m1"]})
    assets = _wait_for(lambda: (lambda a: a if a and a[0]["qa_status"] else None)(
        client.get(f"/api/assets?project_id={pid}").json()))
    assert assets and assets[0]["qa_status"] == "pass", json.dumps(
        json.loads(assets[0]["qa_json"]), ensure_ascii=False)[:800] if assets else "no assets"
    assert client.state["gen_n"] == 1  # 不重试


# ---------- M5 主图预设 ----------

def test_m5_master_image_compose(client):
    client.state["qa_found_text"] = []   # 主图要求无文字
    client.state["qa_fail_times"] = -1   # VLM 一次通过
    pid = _make_project(client, preset_id="master_image")
    client.post(f"/api/projects/{pid}/plan")
    assert _wait_for(lambda: client.get(f"/api/projects/{pid}/plan").status_code == 200)
    r = client.post(f"/api/projects/{pid}/generate", json={"module_ids": ["m1"]})
    assert r.status_code == 200, r.text
    assets = _wait_for(lambda: (lambda a: a if a and a[0]["qa_status"] else None)(
        client.get(f"/api/assets?project_id={pid}").json()))
    assert assets, "master compose did not finish"
    a = assets[0]
    assert a["width"] == 1600 and a["height"] == 1600
    assert a["qa_status"] == "pass", json.dumps(
        json.loads(a["qa_json"]), ensure_ascii=False)[:900]
    assert json.loads(a["params_json"])["compose"] == "cutout_white_bg"
    assert a["mode"] == "compose" and a["model"] == ""  # 出图环节不花模型钱（qa 有少量成本）
    img = Image.open(io.BytesIO(client.get(f"/api/assets/{a['id']}/download").content))
    # 四角纯白
    for x, y in ((0, 0), (1599, 0), (0, 1599), (1599, 1599)):
        assert img.getpixel((x, y)) == (255, 255, 255)


# ---------- M6 视频 ----------

def test_m6_video_script_and_generate(client, monkeypatch):
    pid = _make_project(client)
    _pin_aplus_v1(pid)
    client.post(f"/api/projects/{pid}/plan")
    assert _wait_for(lambda: client.get(f"/api/projects/{pid}/plan").status_code == 200)

    # 先出一张通过质检的图作首帧（qa_fail_times=-1 → 一次过）
    client.state["qa_fail_times"] = -1
    client.post(f"/api/projects/{pid}/generate", json={"module_ids": ["m1"]})
    assert _wait_for(lambda: (lambda a: a if a and a[0]["qa_status"] == "pass" else None)(
        client.get(f"/api/assets?project_id={pid}").json()))

    # 镜头脚本
    r = client.post(f"/api/projects/{pid}/video/plan")
    assert r.status_code == 200, r.text
    assert _wait_for(lambda: client.get(f"/api/projects/{pid}/video/script").status_code == 200)
    script = client.get(f"/api/projects/{pid}/video/script").json()
    assert script["body"]["shots"][0]["index"] == 1

    # 图生视频：假提交/轮询/下载
    def fake_submit(self, model, prompt, first_frame_path=None, size="", seconds=5):
        assert first_frame_path and prompt
        return {"id": "vid-1"}

    def fake_poll(self, job_ref):
        assert job_ref == "vid-1"
        return {"status": "succeeded", "output": {"url": "http://cdn.test/v.mp4"}}

    import requests as _requests

    class _R:
        ok = True
        def __init__(self, b):
            self.content = b

    def fake_get(url, timeout=0, **kw):
        if url == "http://cdn.test/v.mp4":
            return _R(b"FAKE MP4 BYTES")
        raise AssertionError(f"unexpected GET {url}")

    monkeypatch.setattr(Gateway, "submit_video", fake_submit)
    monkeypatch.setattr(Gateway, "poll_video", fake_poll)
    monkeypatch.setattr("app.services.video.requests.get", fake_get)

    client.put("/api/settings", json={"roles": {"video": {"model": "vid-x", "unit_price": 0.9}}})
    r = client.post(f"/api/projects/{pid}/video/generate", json={"module_id": "m1"})
    assert r.status_code == 200, r.text
    vids = _wait_for(lambda: (lambda a: a if a else None)(
        client.get(f"/api/assets?project_id={pid}&kind=video").json()))
    assert vids, "video job did not finish"
    v = vids[0]
    assert v["kind"] == "video" and v["mode"] == "image_to_video"
    assert json.loads(v["params_json"])["first_frame_asset_id"]
    assert v["cost_estimate"] == 0.9
    dl = client.get(f"/api/assets/{v['id']}/download")
    assert dl.status_code == 200 and dl.content == b"FAKE MP4 BYTES"


def test_extract_video_url_shapes():
    assert extract_video_url({"url": "http://a/b.mp4"}) == "http://a/b.mp4"
    assert extract_video_url({"data": [{"video_url": "http://a/b.mov"}]}) == "http://a/b.mov"
    assert extract_video_url({"x": [{"link": "https://c.d/e.webm?token=1"}]}) == "https://c.d/e.webm?token=1"
    assert extract_video_url({"status": "ok"}) == ""
