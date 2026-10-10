"""视频相关 API（M6）：镜头脚本规划/获取、按镜头生成视频。"""
import json

from fastapi import APIRouter, HTTPException

from ..db.database import connect
from ..services import jobs
from ..services.generator import get_project_and_refs, get_plan_revision
from ..services.presets import get_version_by_id
from ..services.video import latest_script

router = APIRouter(prefix="/api/projects")


def _project_or_404(project_id: str) -> dict:
    project, _ = get_project_and_refs(project_id)
    return project


@router.post("/{project_id}/video/plan")
def plan_video(project_id: str):
    _project_or_404(project_id)
    try:
        job_id = jobs.enqueue(project_id, "video_script")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"job_id": job_id}


@router.get("/{project_id}/video/script")
def get_video_script(project_id: str):
    _project_or_404(project_id)
    s = latest_script(project_id)
    if s is None:
        raise HTTPException(404, "还没有镜头脚本，请先生成")
    return s


@router.post("/{project_id}/video/generate")
def generate_video(project_id: str, body: dict | None = None):
    """body: {module_id, shot_index?, asset_id?}。用该模块最新通过质检的图作首帧。"""
    project = _project_or_404(project_id)
    body = body or {}
    module_id = body.get("module_id")
    if not module_id:
        raise HTTPException(400, "缺少 module_id")
    pv = get_version_by_id(project["preset_version_id"])
    plan_rev = get_plan_revision(project_id)

    shot = None
    if body.get("use_script", True):
        script = latest_script(project_id)
        shots = (script or {}).get("body", {}).get("shots") or []
        idx = body.get("shot_index")
        shot = next((s for s in shots if s.get("index") == idx), None) if idx is not None \
            else (shots[0] if shots else None)

    payload = {
        "module_id": module_id,
        "preset_version_id": pv["id"] if pv else None,
        "plan_revision": plan_rev["revision"],
        "role": "video",
        "shot": shot or {"index": body.get("shot_index", 1),
                         "description": body.get("description", ""),
                         "prompt": body.get("prompt", ""), "duration_s": 5},
    }
    if body.get("asset_id"):
        payload["asset_id"] = int(body["asset_id"])
    try:
        job_id = jobs.enqueue(project_id, "video", target_id=module_id, payload=payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"job_id": job_id}


video_scripts_router = APIRouter(prefix="/api/video-scripts")


@video_scripts_router.get("")
def list_scripts(project_id: str):
    with connect() as conn:
        rows = conn.execute("SELECT id, body_json, created_at FROM script "
                            "WHERE project_id=? ORDER BY id DESC LIMIT 20",
                            (project_id,)).fetchall()
    return [{"id": r["id"], "created_at": r["created_at"],
             "body": json.loads(r["body_json"])} for r in rows]
