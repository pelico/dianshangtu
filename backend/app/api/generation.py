"""出图相关 API：提示词预览、批量生成、资产列表/下载、zip 导出。"""
import io
import json
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse, FileResponse

from ..db.database import connect
from ..services import generator
from ..services import jobs
from ..services.compiler import compile_prompt
from ..services.generator import (get_asset, get_plan_revision, get_project_and_refs,
                                  list_assets)
from ..services.presets import get_version_by_id

router = APIRouter(prefix="/api/projects")


def _preset_and_plan(project_id: str):
    project, refs = get_project_and_refs(project_id)
    pv = get_version_by_id(project["preset_version_id"])
    if pv is None:
        raise HTTPException(400, "项目的预设版本不存在")
    try:
        plan_rev = get_plan_revision(project_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return project, refs, pv, plan_rev


@router.get("/{project_id}/prompts")
def preview_prompts(project_id: str):
    """每个模块编译后的出图提示词预览。"""
    _, _, pv, plan_rev = _preset_and_plan(project_id)
    out = []
    for m in plan_rev["plan"]["modules"]:
        try:
            prompt = compile_prompt(plan_rev["plan"], m, pv["body"])
        except ValueError as e:
            raise HTTPException(400, str(e))
        out.append({"module_id": m["id"], "title_cn": m["title_cn"], "headline": m["headline"],
                    "prompt": prompt})
    return out


@router.post("/{project_id}/generate")
def generate(project_id: str, body: dict | None = None):
    """按选定模块批量出图（异步）。body: {module_ids?, overrides?: {module_id: prompt_text}}"""
    project, refs, pv, plan_rev = _preset_and_plan(project_id)
    if not refs:
        raise HTTPException(400, "项目没有参考图")
    body = body or {}
    module_ids = body.get("module_ids") or [m["id"] for m in plan_rev["plan"]["modules"]]
    overrides = body.get("overrides") or {}
    modules = {m["id"]: m for m in plan_rev["plan"]["modules"]}

    job_ids = []
    for mid in module_ids:
        if mid not in modules:
            raise HTTPException(400, f"未知模块: {mid}")
        payload = {
            "module_id": mid,
            "preset_version_id": pv["id"],
            "plan_revision": plan_rev["revision"],
            "role": pv["body"]["image"].get("model_ref", "image_main"),
        }
        if mid in overrides:
            payload["prompt_text"] = str(overrides[mid])
        try:
            job_ids.append(jobs.enqueue(project_id, "image", target_id=mid, payload=payload))
        except ValueError as e:
            raise HTTPException(400, str(e))
    with connect() as conn:
        conn.execute("UPDATE project SET status='generating' WHERE id=?", (project_id,))
        conn.commit()
    return {"job_ids": job_ids, "plan_revision": plan_rev["revision"]}


@router.get("/{project_id}/export.zip")
def export_zip(project_id: str):
    """批量下载：每个模块取最新一张，按模块命名。"""
    get_project_and_refs(project_id)
    assets = list_assets(project_id)
    if not assets:
        raise HTTPException(404, "项目还没有产出图片")
    latest = {}
    for a in assets:
        latest[a["module_id"]] = a  # ORDER BY id，后写覆盖前写即最新
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for mid, a in sorted(latest.items()):
            z.write(a["path"], f"{mid}.png")
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={project_id}_export.zip"})


assets_router = APIRouter(prefix="/api/assets")


@assets_router.get("")
def get_assets(project_id: str, kind: str = "image"):
    from .projects import file_url
    out = []
    for a in generator.list_assets(project_id, kind=kind):
        a["url"] = file_url(a["path"])
        if a.get("raw_path"):
            a["raw_url"] = file_url(a["raw_path"])
        out.append(a)
    return out


@assets_router.post("/{asset_id}/approve")
def approve_asset(asset_id: int, body: dict | None = None):
    """人工放行（M4）：QA 未通过标红的图经人工确认后放行导出。"""
    from ..services.qa import approve
    if not approve(asset_id, (body or {}).get("note", "")):
        raise HTTPException(404, "asset not found")
    return {"id": asset_id, "qa_status": "approved"}


@assets_router.get("/{asset_id}/download")
def download_asset(asset_id: int, raw: int = 0):
    a = get_asset(asset_id)
    if not a:
        raise HTTPException(404, "asset not found")
    path = a["raw_path"] if raw and a.get("raw_path") else a["path"]
    try:
        return FileResponse(path, media_type="image/png", filename=pathlib_name(path))
    except Exception:
        raise HTTPException(404, "文件不存在")


@assets_router.post("/{asset_id}/regenerate")
def regenerate_asset(asset_id: int, body: dict | None = None):
    """单图重出（M3）：改提示词 / 换模型角色。产生新 asset，parent_asset_id 指向旧图，不覆盖。"""
    a = get_asset(asset_id)
    if not a:
        raise HTTPException(404, "asset not found")
    body = body or {}
    payload = {
        "module_id": a["module_id"],
        "preset_version_id": a["preset_version_id"],
        "plan_revision": a["plan_revision"],
        "parent_asset_id": asset_id,
        "role": body.get("model_ref") or "image_main",
        "params": body.get("params") or {},
    }
    if body.get("prompt_text"):
        payload["prompt_text"] = str(body["prompt_text"])
    try:
        job_id = jobs.enqueue(a["project_id"], "image", target_id=a["module_id"], payload=payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    with connect() as conn:
        conn.execute("UPDATE project SET status='generating' WHERE id=?", (a["project_id"],))
        conn.commit()
    return {"job_id": job_id, "parent_asset_id": asset_id}


jobs_router = APIRouter(prefix="/api/jobs")


@jobs_router.get("/{job_id}")
def get_job(job_id: int):
    from ..services.jobs import get_job as fetch
    j = fetch(job_id)
    if not j:
        raise HTTPException(404, "job not found")
    if j.get("payload_json"):
        j["payload"] = json.loads(j.pop("payload_json"))
    return j


def pathlib_name(p: str) -> str:
    import pathlib
    return pathlib.Path(p).name
