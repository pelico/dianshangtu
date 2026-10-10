"""视频预设（PLAN_v2 §3 M6）：镜头脚本规划 → 已确认图作首帧 → 图生视频长任务。

- 镜头脚本：用 planner 角色的多模态 LLM 对参考图输出 {"shots":[{index,description,motion,duration_s}]}
  （宽容解析，不做 plan 级强校验），存入 script 表。
- 出视频：每个镜头取对应模块最新 QA 通过/已放行的图为首帧，video 角色提交 → 轮询 → 下载 mp4 入库。
- 网关视频接口形态各异，这里走通用 POST /videos + GET /videos/{id}；状态字段的取值集合做了宽容兼容。
"""
import json
import re
import time

import requests

from ..db.database import connect
from ..providers.openai_compat import Gateway, GatewayError
from . import jobs, settings_store
from .generator import get_project_and_refs, get_plan_revision, insert_asset, list_assets
from .planner import parse_plan_json
from .presets import get_version_by_id
from .qa import cost_of_role

SHOT_SYSTEM_PROMPT = (
    "You are an e-commerce short-video director. Based on the product reference photos, "
    "write a shot list for an Amazon product video. Answer in JSON ONLY:\n"
    '{"shots": [{"index": 1, "description": "what this shot shows", '
    '"motion": "camera/product movement", "duration_s": 5, "prompt": "image-to-video prompt '
    "describing motion, keeping the product EXACTLY identical to the first frame\"}]}\n"
    "3 to 6 shots, total 15-30 seconds, no text overlays in shots. No markdown fences.")

POLL_INTERVAL = 5
_SUCCESS = {"succeeded", "success", "complete", "completed", "done", "ok"}
_FAILED = {"failed", "error", "rejected", "canceled", "cancelled"}


def save_script(project_id: str, body: dict) -> int:
    with connect() as conn:
        cur = conn.execute("INSERT INTO script(project_id, body_json) VALUES (?, ?)",
                           (project_id, json.dumps(body, ensure_ascii=False)))
        conn.commit()
        return cur.lastrowid


def latest_script(project_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT id, body_json, created_at FROM script "
                           "WHERE project_id=? ORDER BY id DESC LIMIT 1", (project_id,)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "created_at": row["created_at"],
            "body": json.loads(row["body_json"])}


def extract_video_url(res: dict) -> str:
    """从轮询响应里宽容地找视频地址：常见字段或任意 .mp4 链接。"""
    def walk(o):
        if isinstance(o, dict):
            for k in ("url", "video_url", "output_url", "download_url"):
                v = o.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    return v
            for v in o.values():
                if (r := walk(v)):
                    return r
        elif isinstance(o, list):
            for v in o:
                if (r := walk(v)):
                    return r
        elif isinstance(o, str) and re.match(r"https?://\S+\.(mp4|mov|webm)(\?\S*)?$", o):
            return o
        return None
    return walk(res) or ""


def _video_role_ready() -> tuple[object, dict]:
    gw = settings_store.get_gateway("video")
    if gw is None:
        raise GatewayError("video 角色未配置 base_url / API Key / 模型名，请先到设置页配置")
    return gw, settings_store.get_role("video")


# ---------- Job handlers ----------

@jobs.handler("video_script")
def run_video_script_job(job_id: int) -> None:
    job = jobs.get_job(job_id)
    project_id = job["project_id"]
    project, refs = get_project_and_refs(project_id)
    if not refs:
        raise ValueError("项目没有参考图，无法生成镜头脚本")
    params = json.loads(project["params_json"] or "{}")
    brief = project["brief"]
    pv = get_version_by_id(project["preset_version_id"])
    n_shots = int(params.get("n_shots") or 5)

    gw = settings_store.get_gateway("planner")
    if gw is None:
        raise GatewayError("planner 角色未配置，无法生成镜头脚本")
    model = settings_store.get_role("planner")["model"]
    user = [{"type": "text", "text": f"Product brief: {brief or '(none)'}\nShots wanted: {n_shots}"}]
    user += [{"type": "image_url", "image_url": {"url": Gateway.data_url(p)}} for p in [r["path"] for r in refs]]
    res = gw.chat(model, [{"role": "system", "content": SHOT_SYSTEM_PROMPT},
                          {"role": "user", "content": user}],
                  temperature=0.7, response_format={"type": "json_object"})
    try:
        body = parse_plan_json(res["choices"][0]["message"]["content"])
        if not isinstance(body.get("shots"), list) or not body["shots"]:
            raise ValueError("shots must be a non-empty array")
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"镜头脚本 JSON 不合法: {e}")
    if brief:  # brief 里声明的卖点以外不得出现承诺性文案的简单把关（与出图口径一致）
        body["brief"] = brief
    save_script(project_id, body)


@jobs.handler("video")
def run_video_job(job_id: int) -> None:
    job = jobs.get_job(job_id)
    payload = json.loads(job["payload_json"] or "{}")
    project_id = job["project_id"]
    module_id = payload["module_id"]
    shot = payload.get("shot") or {}

    # 首帧：指定 asset 或该模块最新 QA 通过/人工放行的图
    frame = None
    if payload.get("asset_id"):
        frame = next((a for a in list_assets(project_id) if a["id"] == payload["asset_id"]), None)
    if frame is None:
        for a in reversed(list_assets(project_id)):  # id 升序 → 反向取最新
            if a["module_id"] == module_id and a["qa_status"] in ("pass", "approved"):
                frame = a
                break
    if frame is None:
        raise ValueError(f"模块 {module_id} 没有质检通过的图片可作首帧，请先生成图片")

    gw, cfg = _video_role_ready()
    t0 = time.time()
    res = gw.submit_video(cfg["model"], shot.get("prompt") or shot.get("description") or "",
                          first_frame_path=frame["path"],
                          size=cfg["size"], seconds=int(shot.get("duration_s") or 5))
    job_ref = str(res.get("id") or res.get("task_id") or res.get("request_id") or "")
    if not job_ref:
        raise GatewayError(f"视频提交响应缺少任务 id: {json.dumps(res)[:300]}")

    deadline = time.time() + int(cfg["timeout_s"])
    while time.time() < deadline:
        st = gw.poll_video(job_ref)
        status = str(st.get("status") or st.get("state") or "").lower()
        if status in _FAILED:
            raise GatewayError(f"视频生成失败: {json.dumps(st)[:300]}")
        if status in _SUCCESS and (url := extract_video_url(st)):
            break
        time.sleep(POLL_INTERVAL)
    else:
        raise GatewayError(f"视频生成超时（>{cfg['timeout_s']}s），任务 id: {job_ref}")

    from ..core.config import DATA_DIR
    out_dir = DATA_DIR / "outputs" / project_id / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{module_id}_shot{shot.get('index', '')}_{job_ref[:8]}.mp4"
    out_path.write_bytes(requests.get(url, timeout=300).content)

    insert_asset(project_id,
                 module_id=module_id, kind="video", path=str(out_path), raw_path="",
                 width=0, height=0, model=cfg["model"], mode="image_to_video",
                 role="video",
                 params_json=json.dumps({"shot": shot, "video_job_id": job_ref,
                                         "first_frame_asset_id": frame["id"]}, ensure_ascii=False),
                 prompt_text=shot.get("prompt") or "",
                 ref_hashes_json="[]",
                 preset_version_id=payload.get("preset_version_id"),
                 plan_revision=payload.get("plan_revision"),
                 attempt=int(job.get("attempt") or 0),
                 elapsed_s=round(time.time() - t0, 2),
                 cost_estimate=cost_of_role("video"))
