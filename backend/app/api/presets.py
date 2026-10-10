"""预设 API：列表、版本历史、保存新版本、回滚、样例试跑（M3）。"""
import json
import pathlib
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..core.config import DATA_DIR
from ..db.database import connect
from ..services import jobs
from ..services.presets import get_latest_version, list_presets

router = APIRouter(prefix="/api/presets")

REQUIRED_BODY_KEYS = {"canvas": dict, "planner": dict, "image": dict}


@router.get("")
def get_presets():
    return list_presets()


def _validate_body(body: dict) -> None:
    for k, t in REQUIRED_BODY_KEYS.items():
        if not isinstance(body.get(k), t):
            raise HTTPException(400, f"预设 body 缺少或类型错误: {k}")
    if not body["planner"].get("system_prompt"):
        raise HTTPException(400, "planner.system_prompt 不能为空")
    if not body["image"].get("template"):
        raise HTTPException(400, "image.template 不能为空")
    try:
        int(body["canvas"]["width"]), int(body["canvas"]["height"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, "canvas.width/height 必须是整数")


class PresetBodyIn(BaseModel):
    body: dict


class RollbackIn(BaseModel):
    version: int


@router.get("/{preset_id}/versions")
def get_versions(preset_id: str):
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, version, created_at, length(body_json) AS size "
            "FROM preset_version WHERE preset_id=? ORDER BY version DESC", (preset_id,)).fetchall()
    return [dict(r) for r in rows]


@router.get("/{preset_id}/versions/{version}")
def get_version_body(preset_id: str, version: int):
    with connect() as conn:
        row = conn.execute(
            "SELECT id, version, body_json, created_at FROM preset_version "
            "WHERE preset_id=? AND version=?", (preset_id, version)).fetchone()
    if not row:
        raise HTTPException(404, "版本不存在")
    return {"id": row["id"], "version": row["version"], "created_at": row["created_at"],
            "body": json.loads(row["body_json"])}


@router.post("/{preset_id}/versions")
def save_new_version(preset_id: str, p: PresetBodyIn):
    latest = get_latest_version(preset_id)
    if latest is None:
        raise HTTPException(404, "预设不存在")
    _validate_body(p.body)
    new_version = latest["version"] + 1
    with connect() as conn:
        conn.execute(
            "INSERT INTO preset_version(preset_id, version, body_json) VALUES (?, ?, ?)",
            (preset_id, new_version, json.dumps(p.body, ensure_ascii=False)))
        conn.commit()
    return {"version": new_version}


@router.post("/{preset_id}/rollback")
def rollback(preset_id: str, p: RollbackIn):
    """回滚 = 以旧版本内容创建新版本（旧版本只读保留，PLAN_v2 §4）。"""
    if get_latest_version(preset_id) is None:
        raise HTTPException(404, "预设不存在")
    with connect() as conn:
        row = conn.execute(
            "SELECT body_json FROM preset_version WHERE preset_id=? AND version=?",
            (preset_id, p.version)).fetchone()
    if not row:
        raise HTTPException(404, f"版本 {p.version} 不存在")
    return save_new_version(preset_id, PresetBodyIn(body=json.loads(row["body_json"])))


@router.post("/{preset_id}/test-run")
async def test_run(preset_id: str, file: UploadFile = File(...),
                   brief: str = Form(""), text_mode: str = Form("")):
    """用样例商品试跑一张：规划 → 编译第一个模块 → 出图。异步 Job，前端轮询 /api/jobs/{id}。"""
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(400, "请上传一张样例商品图")
    data = await file.read()
    run_id = uuid.uuid4().hex[:10]
    d = DATA_DIR / "test_runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    suffix = pathlib.Path(file.filename or "x.png").suffix.lower() or ".png"
    img_path = d / f"ref{suffix}"
    img_path.write_bytes(data)
    try:
        job_id = jobs.enqueue("__testrun__", "preset_test_run", payload={
            "preset_id": preset_id,
            "ref_path": str(img_path),
            "brief": brief,
            "text_mode": text_mode or None,
        })
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"job_id": job_id}
