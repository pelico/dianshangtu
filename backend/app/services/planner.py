"""规划服务：商品图 → 结构化 Plan(JSON)。

从 poc/poc.py 的 make_plan 重构（行为一致），叠加：
- 输出校验（schema 以 poc/prompts/planner.system.md 为准）
- JSON 解析失败时带错误信息重试一次（PLAN_v2 §5）
- 作为 job handler 运行，产出写入 plan 表（新 revision）
"""
import json
import re

from ..db.database import connect
from ..providers.openai_compat import GatewayError
from . import jobs
from . import settings_store
from .presets import get_version_by_id

MODULE_REQUIRED = ["id", "title_cn", "role", "scene", "product_pose", "photo_goal",
                   "visual_description", "composition", "headline", "subline"]


# ---------- 解析与校验（对应 poc 的去围栏 + json.loads，加了校验） ----------

def parse_plan_json(text: str) -> dict:
    txt = re.sub(r"^```(?:json)?|```$", "", text.strip()).strip()
    return json.loads(txt)


def validate_plan(plan: dict) -> None:
    """不合法时抛 ValueError，错误信息用于带错误重试与任务落库。"""
    if not isinstance(plan, dict):
        raise ValueError("plan is not a JSON object")
    for key in ("product", "design_spec", "modules"):
        if key not in plan:
            raise ValueError(f"missing top-level key: {key}")
    product, spec, modules = plan["product"], plan["design_spec"], plan["modules"]
    if not isinstance(product, dict) or not product.get("anchor"):
        raise ValueError("product.anchor is required (pasted into every image prompt)")
    if not isinstance(spec, dict):
        raise ValueError("design_spec must be an object")
    if not isinstance(modules, list) or not modules:
        raise ValueError("modules must be a non-empty array")
    ids = set()
    for i, m in enumerate(modules):
        for f in MODULE_REQUIRED:
            if not m.get(f):
                raise ValueError(f"modules[{i}] missing field: {f}")
        if m["id"] in ids:
            raise ValueError(f"duplicate module id: {m['id']}")
        ids.add(m["id"])


def build_user_content(lang: str, n_modules: int, canvas: dict, brief: str,
                       ref_paths: list[str]) -> list[dict]:
    """对应 poc.make_plan 的用户消息构造。"""
    from ..providers.openai_compat import Gateway

    user = [{"type": "text", "text": (
        f"Copy language: {lang}\nNumber of modules: {n_modules}\n"
        f"Canvas: wide banner {canvas['width']}x{canvas['height']}\n"
        f"User brief: {brief or '(none)'}"
    )}]
    user += [{"type": "image_url", "image_url": {"url": Gateway.data_url(p)}} for p in ref_paths]
    return user


# ---------- 规划主流程 ----------

def make_plan(preset_version: dict, ref_paths: list[str], brief: str, params: dict) -> dict:
    """调用规划模型并返回校验通过的 plan dict。失败抛 GatewayError/ValueError。"""
    body = preset_version["body"]
    planner_cfg = body["planner"]
    role_ref = planner_cfg.get("model_ref", "planner")
    gw = settings_store.get_gateway(role_ref)
    if gw is None:
        raise GatewayError("planner 角色未配置 base_url / API Key / 模型名，请先到设置页配置")

    mc = planner_cfg.get("module_count", {})
    n_default = mc.get("default", 5)
    n = int(params.get("n_modules") or n_default)
    n = max(mc.get("min", 1), min(mc.get("max", 12), n))
    lang = params.get("copy_language") or body.get("inputs", {}).get("copy_language") or "English"

    messages = [
        {"role": "system", "content": planner_cfg["system_prompt"]},
        {"role": "user", "content": build_user_content(
            lang, n, body["canvas"], brief, ref_paths)},
    ]
    model = settings_store.get_role(role_ref)["model"]

    res = gw.chat(model, messages, temperature=0.7, response_format={"type": "json_object"})
    text = res["choices"][0]["message"]["content"]
    try:
        plan = parse_plan_json(text)
        validate_plan(plan)
        return plan
    except (json.JSONDecodeError, ValueError) as first_err:
        # 失败重试一次，并把错误带给模型（PLAN_v2 §5）
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": (
                f"Your previous output was invalid: {first_err}. "
                "Output ONLY one valid JSON object that follows the schema. No markdown fences.")},
        ]
        res = gw.chat(model, messages, temperature=0.7, response_format={"type": "json_object"})
        plan = parse_plan_json(res["choices"][0]["message"]["content"])
        validate_plan(plan)  # 二次失败直接抛，落库为任务错误
        return plan


# ---------- 数据访问 ----------

def _project_and_refs(project_id: str) -> tuple[dict, list[str]]:
    with connect() as conn:
        project = conn.execute("SELECT * FROM project WHERE id = ?", (project_id,)).fetchone()
        refs = conn.execute(
            "SELECT path FROM project_ref WHERE project_id = ? ORDER BY order_no",
            (project_id,)).fetchall()
    if project is None:
        raise ValueError(f"project not found: {project_id}")
    return dict(project), [r["path"] for r in refs]


def insert_plan(project_id: str, plan: dict, source: str = "ai") -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(revision), 0) AS r FROM plan WHERE project_id = ?",
            (project_id,)).fetchone()
        revision = row["r"] + 1
        conn.execute(
            "INSERT INTO plan(project_id, revision, body_json, source) VALUES (?, ?, ?, ?)",
            (project_id, revision, json.dumps(plan, ensure_ascii=False), source))
        conn.execute("UPDATE project SET status='planned' WHERE id=?", (project_id,))
        conn.commit()
    return revision


# ---------- Job handler ----------

@jobs.handler("plan")
def run_plan_job(job_id: int) -> None:
    job = jobs.get_job(job_id)
    project_id = job["project_id"]
    project, refs = _project_and_refs(project_id)
    if not refs:
        raise ValueError("项目没有参考图，无法规划")
    pv = get_version_by_id(project["preset_version_id"])
    if pv is None:
        raise ValueError(f"preset_version not found: {project['preset_version_id']}")
    with connect() as conn:
        conn.execute("UPDATE project SET status='planning' WHERE id=?", (project_id,))
        conn.commit()
    params = json.loads(project["params_json"] or "{}")
    plan = make_plan(pv, refs, project["brief"], params)
    insert_plan(project_id, plan, source="ai")
