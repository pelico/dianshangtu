"""出图服务：编译提示词 → 调用图像编辑模型（带参考图）→ fit → 质检 → asset 落库。

可复现性（PLAN_v2 §6）：每个 asset 记录 prompt_text / model / mode / params_json /
ref_hashes_json / preset_version_id / plan_revision / role；重出产生新 asset（M3 regenerate）。

质检与自动重试（M4，PLAN_v2 §3）：
- 每次“生成→QA”为一轮；QA 不通过时把 issues 追加进提示词的 AVOID 段再生成，
  最多重试预设 qa.max_auto_retries 次；仍不通过则标 needs_review 等人工放行。
- 成本：出图按角色单价记 1 次，VLM 质检按 qa_vlm 单价记实际调用次数。
"""
import io
import json
import time
import uuid

from ..core.config import DATA_DIR
from ..db.database import connect
from ..providers.openai_compat import GatewayError
from . import jobs
from . import settings_store
from .compiler import compile_prompt
from .imaging import fit
from .presets import get_version_by_id
from .qa import cost_of_role, run_qa, save_qa


def get_project_and_refs(project_id: str) -> tuple[dict, list[dict]]:
    with connect() as conn:
        project = conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
        refs = conn.execute(
            "SELECT path, sha256, order_no FROM project_ref WHERE project_id = ? ORDER BY order_no",
            (project_id,)).fetchall()
    if project is None:
        raise ValueError(f"project not found: {project_id}")
    return dict(project), [dict(r) for r in refs]


def get_plan_revision(project_id: str, revision: int | None = None) -> dict:
    with connect() as conn:
        if revision is None:
            row = conn.execute(
                "SELECT revision, body_json FROM plan WHERE project_id=? "
                "ORDER BY revision DESC LIMIT 1", (project_id,)).fetchone()
        else:
            row = conn.execute(
                "SELECT revision, body_json FROM plan WHERE project_id=? AND revision=?",
                (project_id, revision)).fetchone()
    if row is None:
        raise ValueError("项目还没有方案，请先执行 AI 规划")
    return {"revision": row["revision"], "plan": json.loads(row["body_json"])}


def insert_asset(project_id: str, **kw) -> int:
    cols = {k: v for k, v in kw.items()}
    keys = ", ".join(cols.keys())
    marks = ", ".join("?" for _ in cols)
    with connect() as conn:
        cur = conn.execute(f"INSERT INTO asset(project_id, {keys}) VALUES (?, {marks})",
                           (project_id, *cols.values()))
        conn.commit()
        return cur.lastrowid


def get_asset(asset_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM asset WHERE id = ?", (asset_id,)).fetchone()
    return dict(row) if row else None


def list_assets(project_id: str, kind: str = "image") -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM asset WHERE project_id = ? AND kind=? ORDER BY id",
            (project_id, kind)).fetchall()
    return [dict(r) for r in rows]


def _brand_body(project: dict) -> dict | None:
    """项目绑定的品牌档案（L2 档案层），无绑定返回 None。"""
    if not project.get("brand_profile_id"):
        return None
    from . import brand
    p = brand.get_profile(project["brand_profile_id"])
    return p["body"] if p else None


def _generate_bytes(image_cfg: dict, role: str, gen_size: str, prompt: str,
                    ref_paths: list[str], target: tuple[int, int]) -> tuple[bytes, float, dict]:
    """产出图像字节。确定性合成（主图预设）不花模型钱；否则走网关。返回 (bytes, 成本, 出图元数据)。"""
    if image_cfg.get("compose") == "cutout_white_bg":  # M5 主图：确定性合成
        from .master import compose_product
        img_bytes, meta = compose_product(ref_paths[0], target, image_cfg)
        return img_bytes, 0.0, meta
    gw = settings_store.get_gateway(role)
    if gw is None:
        raise GatewayError(f"角色 {role} 未配置 base_url / API Key / 模型名，请先到设置页配置")
    cfg = settings_store.get_role(role)
    img_bytes = gw.gen_image(cfg["model"], cfg["mode"], gen_size, prompt, ref_paths)
    return img_bytes, cost_of_role(role), {"model": cfg["model"], "mode": cfg["mode"]}


def _generate_and_insert(job: dict, payload: dict, project: dict, refs: list[dict],
                         pv: dict, plan_rev: dict, module: dict,
                         prompt: str, prompt_edited: int, attempt: int) -> tuple[int, float]:
    """一轮生成 + fit + asset 落库。返回 (asset_id, 出图成本)。"""
    project_id = job["project_id"]
    image_cfg = pv["body"]["image"]
    canvas = payload.get("canvas") or pv["body"]["canvas"]
    target = (int(canvas["width"]), int(canvas["height"]))
    role = payload.get("role") or image_cfg.get("model_ref", "image_main")
    gen_size = image_cfg.get("gen_size") or settings_store.get_role(role)["size"]

    img_bytes, gen_cost, gen_meta = _generate_bytes(
        image_cfg, role, gen_size, prompt, [r["path"] for r in refs], target)

    out_dir = DATA_DIR / "outputs" / project_id / payload["module_id"]
    name = f"{uuid.uuid4().hex[:10]}.png"
    result = fit(img_bytes, out_dir / name, target)

    asset_id = insert_asset(
        project_id,
        module_id=payload["module_id"],
        kind="image",
        path=result["path"],
        raw_path=result["raw_path"],
        width=result["width"],
        height=result["height"],
        model=gen_meta.get("model", ""),
        mode=gen_meta.get("mode", "compose"),
        role=role,
        params_json=json.dumps({
            "canvas": target, "gen_size": gen_size, "candidates": 1,
            "fit": image_cfg.get("fit", "center_crop"),
            "compose": image_cfg.get("compose") or "model",
        }, ensure_ascii=False),
        prompt_text=prompt,
        prompt_edited=prompt_edited,
        ref_hashes_json=json.dumps([r["sha256"] for r in refs]),
        preset_version_id=pv["id"],
        plan_revision=plan_rev["revision"],
        parent_asset_id=payload.get("parent_asset_id"),
        attempt=attempt,
        elapsed_s=round(time.time() - job["_t0"], 2),
        cost_estimate=gen_cost,
    )
    return asset_id, gen_cost


@jobs.handler("image")
def run_image_job(job_id: int) -> None:
    job = jobs.get_job(job_id)
    if not job:
        return
    job["_t0"] = time.time()
    payload = json.loads(job["payload_json"] or "{}")
    project, refs = get_project_and_refs(job["project_id"])
    pv = get_version_by_id(payload["preset_version_id"])
    if pv is None:
        raise ValueError("preset_version not found")
    plan_rev = get_plan_revision(project["id"], payload.get("plan_revision"))
    plan = plan_rev["plan"]
    module = next((m for m in plan["modules"] if m["id"] == payload["module_id"]), None)
    if module is None:
        raise ValueError(f"module not found: {payload['module_id']}")

    image_cfg = pv["body"]["image"]
    qa_cfg = pv["body"].get("qa", {})
    max_retries = int(qa_cfg.get("max_auto_retries", 0))
    text_mode = pv["body"].get("text", {}).get("mode", "model")

    base_prompt = payload.get("prompt_text") or compile_prompt(
        plan, module, pv["body"], brand=_brand_body(project))
    prompt_edited = 1 if payload.get("prompt_text") else 0

    asset_id, issues = None, []
    for attempt in range(max_retries + 1):
        prompt = base_prompt
        if issues:  # QA 失败原因追加进 AVOID（PLAN_v2 §3 M4 自动重试）
            prompt = base_prompt + "\nPREVIOUS ATTEMPT ISSUES (must fix, AVOID): " + \
                "; ".join(issues[:8])
        asset_id, gen_cost = _generate_and_insert(
            job, payload, project, refs, pv, plan_rev, module, prompt, prompt_edited, attempt)

        a = get_asset(asset_id)
        qa = run_qa(a["path"], (a["width"], a["height"]),
                    qa_cfg, [r["path"] for r in refs], module, text_mode)
        vlm_calls = 0 if qa["vlm"] == "skipped" else (1 if qa["text"] is None else 2)
        save_qa(asset_id, qa, extra_cost=cost_of_role("qa_vlm", vlm_calls))
        if qa["status"] == "pass":
            break
        issues = qa["issues"]
    else:
        # 用尽重试仍不通过 → 标红等人工放行（PLAN_v2 §3 M4）
        with connect() as conn:
            conn.execute("UPDATE asset SET qa_status='needs_review' WHERE id=?", (asset_id,))
            conn.commit()
