"""项目 API：创建（multipart 多图）、列表、详情、规划触发/编辑、获取方案、SSE 事件。"""
import hashlib
import io
import json
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from PIL import Image

from ..core.config import DATA_DIR
from ..core.paths import file_url
from ..db.database import connect
from ..services import jobs
from ..services import planner as planner_svc
from ..services.presets import get_latest_version, get_version_by_id

router = APIRouter(prefix="/api/projects")

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}

_file_url = file_url  # 兼容旧名


@router.post("")
async def create_project(
    files: list[UploadFile] = File(...),
    name: str = Form(""),
    brief: str = Form(""),
    preset_id: str = Form("aplus_banner"),
    brand_profile_id: str = Form(""),
    params_json: str = Form("{}"),
):
    pv = get_latest_version(preset_id)
    if pv is None:
        raise HTTPException(400, f"未知预设: {preset_id}")
    try:
        params = json.loads(params_json or "{}")
    except json.JSONDecodeError:
        raise HTTPException(400, "params_json 不是合法 JSON")

    if not files:
        raise HTTPException(400, "至少上传一张商品参考图")

    pid = uuid.uuid4().hex[:12]
    ref_dir = DATA_DIR / "uploads" / pid
    ref_dir.mkdir(parents=True, exist_ok=True)

    refs = []
    for i, f in enumerate(files):
        ext = "." + f.filename.rsplit(".", 1)[-1].lower() if "." in (f.filename or "") else ".png"
        if ext not in ALLOWED_EXT:
            raise HTTPException(400, f"不支持的图片格式: {f.filename}")
        data = await f.read()
        try:
            img = Image.open(io.BytesIO(data))
            img.verify()
        except Exception:
            raise HTTPException(400, f"图片损坏或非图片文件: {f.filename}")
        path = ref_dir / f"ref_{i:02d}{ext}"
        path.write_bytes(data)
        refs.append({"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "order_no": i})
        await f.close()

    with connect() as conn:
        conn.execute(
            "INSERT INTO project(id, name, preset_version_id, brand_profile_id, brief, params_json, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'created')",
            (pid, name or f"项目-{pid[:6]}", pv["id"], brand_profile_id or None,
             brief, json.dumps(params, ensure_ascii=False)))
        for r in refs:
            conn.execute(
                "INSERT INTO project_ref(project_id, path, sha256, order_no) VALUES (?, ?, ?, ?)",
                (pid, r["path"], r["sha256"], r["order_no"]))
        conn.commit()
    return get_project_or_404(pid)


def _project_detail(row) -> dict:
    d = dict(row)
    with connect() as conn:
        refs = conn.execute(
            "SELECT id, path, sha256, order_no FROM project_ref "
            "WHERE project_id = ? ORDER BY order_no", (d["id"],)).fetchall()
        plan_row = conn.execute(
            "SELECT revision, source, created_at FROM plan WHERE project_id = ? "
            "ORDER BY revision DESC LIMIT 1", (d["id"],)).fetchone()
        jobs_rows = conn.execute(
            "SELECT id, kind, status, error, created_at FROM job "
            "WHERE project_id = ? ORDER BY id DESC LIMIT 10", (d["id"],)).fetchall()
    d["refs"] = [{**dict(r), "url": file_url(r["path"])} for r in refs]
    d["latest_plan"] = dict(plan_row) if plan_row else None
    d["jobs"] = [dict(j) for j in jobs_rows]
    if d.get("brand_profile_id"):
        from ..services import brand
        d["brand_profile"] = brand.get_profile(d["brand_profile_id"])
    return d


def get_project_or_404(project_id: str) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "项目不存在")
    return _project_detail(row)


@router.get("")
def list_projects():
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.*, (SELECT COUNT(*) FROM project_ref r WHERE r.project_id = p.id) AS ref_count "
            "FROM project p ORDER BY p.created_at DESC").fetchall()
    return [dict(r) for r in rows]


@router.get("/{project_id}")
def get_project(project_id: str):
    return get_project_or_404(project_id)


@router.post("/{project_id}/plan")
def trigger_plan(project_id: str):
    get_project_or_404(project_id)
    try:
        job_id = jobs.enqueue(project_id, "plan")
    except ValueError as e:
        raise HTTPException(400, str(e))
    with connect() as conn:
        conn.execute("UPDATE project SET status='planning' WHERE id=?", (project_id,))
        conn.commit()
    return {"job_id": job_id}


@router.get("/{project_id}/plan")
def get_plan(project_id: str):
    with connect() as conn:
        row = conn.execute(
            "SELECT revision, source, body_json, created_at FROM plan "
            "WHERE project_id = ? ORDER BY revision DESC LIMIT 1", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "尚未生成方案")
    return {"revision": row["revision"], "source": row["source"],
            "created_at": row["created_at"], "plan": json.loads(row["body_json"])}


@router.put("/{project_id}/plan")
def save_plan_edit(project_id: str, body: dict):
    """用户编辑方案：校验后存为新 revision（source=user_edit），不覆盖 AI 版本。"""
    from ..services.planner import validate_plan
    plan = body.get("plan") if isinstance(body, dict) and "plan" in body else body
    try:
        validate_plan(plan)
    except ValueError as e:
        raise HTTPException(400, f"方案不合法: {e}")
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(revision), 0) AS r FROM plan WHERE project_id = ?",
            (project_id,)).fetchone()
        revision = row["r"] + 1
        conn.execute(
            "INSERT INTO plan(project_id, revision, body_json, source) VALUES (?, ?, ?, 'user_edit')",
            (project_id, revision, json.dumps(plan, ensure_ascii=False)))
        conn.execute("UPDATE project SET status='planned' WHERE id=?", (project_id,))
        conn.commit()
    return {"revision": revision, "source": "user_edit"}


@router.get("/{project_id}/events")
async def project_events(project_id: str, request: Request):
    """SSE：任务状态 / 方案版本变化时推送快照（M1 用秒级轮询实现，M2 换事件广播）。"""
    async def gen():
        last = None
        yield "retry: 3000\n\n"
        while True:
            if await request.is_disconnected():
                return
            snap = _snapshot(project_id)
            if snap != last:
                yield f"data: {json.dumps(snap, ensure_ascii=False)}\n\n"
                last = snap
            import asyncio
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _snapshot(project_id: str) -> dict:
    with connect() as conn:
        project = conn.execute("SELECT status FROM project WHERE id=?", (project_id,)).fetchone()
        jobs_rows = conn.execute(
            "SELECT id, kind, status, error FROM job WHERE project_id=? ORDER BY id",
            (project_id,)).fetchall()
        plan_row = conn.execute(
            "SELECT revision FROM plan WHERE project_id=? ORDER BY revision DESC LIMIT 1",
            (project_id,)).fetchone()
    return {
        "project_status": project["status"] if project else None,
        "jobs": [dict(j) for j in jobs_rows],
        "plan_revision": plan_row["revision"] if plan_row else None,
    }


# 供 M3 前端下载参考图等使用：路径换算在 _file_url
def preset_version_for(project_id: str):
    project = get_project_or_404(project_id)
    return get_version_by_id(project["preset_version_id"])
