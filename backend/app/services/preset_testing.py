"""预设「试跑一张」：不建项目、不落 asset，结果挂在 job.payload.result 上。

链路：样例图 → 规划（用预设当前 body）→ 编译第一个模块 → 出图 → fit → 返回图与方案。
"""
import json
import time
import uuid

from ..core.config import DATA_DIR
from ..core.paths import file_url
from . import jobs
from . import settings_store
from .compiler import compile_prompt
from .imaging import fit
from .planner import make_plan
from .presets import get_latest_version


@jobs.handler("preset_test_run")
def run_test_job(job_id: int) -> None:
    job = jobs.get_job(job_id)
    payload = json.loads(job["payload_json"] or "{}")
    pv = get_latest_version(payload["preset_id"])
    if pv is None:
        raise ValueError("预设不存在")
    body = dict(pv["body"])
    if payload.get("text_mode"):
        body.setdefault("text", {})["mode"] = payload["text_mode"]

    ref_path = payload["ref_path"]
    t0 = time.time()
    plan = make_plan(pv, [ref_path], payload.get("brief", ""), {})
    plan_elapsed = round(time.time() - t0, 2)

    module = plan["modules"][0]
    prompt = compile_prompt(plan, module, body)
    role = body["image"].get("model_ref", "image_main")
    gw = settings_store.get_gateway(role)
    if gw is None:
        raise ValueError(f"角色 {role} 未配置 base_url / API Key / 模型名")
    cfg = settings_store.get_role(role)

    t1 = time.time()
    img_bytes = gw.gen_image(cfg["model"], cfg["mode"],
                             body["image"].get("gen_size") or cfg["size"], prompt, [ref_path])
    gen_elapsed = round(time.time() - t1, 2)

    target = (int(body["canvas"]["width"]), int(body["canvas"]["height"]))
    out_name = f"{uuid.uuid4().hex[:10]}.png"
    out_path = DATA_DIR / "test_runs" / out_name
    result = fit(img_bytes, out_path, target)

    jobs.set_result(job_id, {
        "plan": plan,
        "prompt": prompt,
        "image_url": file_url(result["path"]),
        "plan_elapsed_s": plan_elapsed,
        "gen_elapsed_s": gen_elapsed,
        "module": module,
    })
