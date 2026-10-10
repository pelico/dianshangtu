"""三段质检（PLAN_v2 §3 M4 / §6 质检 Job）。

1. 确定性检查（本地，零成本）：尺寸/格式；白底、占比、最小边长——阈值来自预设 qa 配置。
2. VLM 商品一致性：参考图 + 成品图给 VLM，输出
   {score, color_ok, shape_ok, logo_ok, details_ok, issues[]}，score < 阈值判不通过。
3. VLM 文字校验：成品图 + 期望文案比对；blank_then_overlay 模式要求无文字。

不依赖 VLM 也可运行（qa_vlm 角色未配置时只跑确定性检查，结果里标注 skipped）。
JSON 解析容错与 planner 相同（去围栏）。
"""
import io
import json
import logging

from PIL import Image

from ..db.database import connect
from ..providers.openai_compat import Gateway
from . import settings_store
from .planner import parse_plan_json

log = logging.getLogger("qa")

CONSISTENCY_PROMPT = (
    "You are a strict e-commerce image QA inspector. You see reference photos of a product "
    "and one generated marketing banner. Compare them and answer in JSON ONLY:\n"
    '{"score": 1-5, "color_ok": true/false, "shape_ok": true/false, '
    '"logo_ok": true/false, "details_ok": true/false, "issues": ["...", ...]}\n'
    "score=5 means the product in the banner is unmistakably the same product as the "
    "references (color, shape, proportions, logo position, all visible details). "
    "List every mismatch in issues (in English). No markdown fences.")

TEXT_CHECK_PROMPT = (
    "You are a text proofreader for e-commerce banners. Look at the image and answer in JSON ONLY:\n"
    '{"found_text": ["every word/letter sequence you can see"], "issues": ["..."]}\n'
    "Transcribe ALL visible text exactly as rendered (including misspellings). "
    "If the image contains no text at all, found_text must be an empty array. No markdown fences.")


# ---------- 第 1 段：确定性检查 ----------

def _corner_white(img: Image.Image, max_dev: int) -> bool:
    """四角均为近白色（阈值 max_dev 为与 255 的最大通道差）。"""
    w, h = img.size
    rgb = img.convert("RGB")
    for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        r, g, b = rgb.getpixel((x, y))
        if any(255 - v > max_dev for v in (r, g, b)):
            return False
    return True


def _product_ratio(img: Image.Image) -> float:
    """非白色内容包围盒面积占全图比例（主图占比规则的度量）。"""
    rgb = img.convert("RGB").resize((256, 256))
    px = rgb.load()
    xs, ys = [], []
    for y in range(256):
        for x in range(256):
            r, g, b = px[x, y]
            if not (r > 240 and g > 240 and b > 240):
                xs.append(x)
                ys.append(y)
    if not xs:
        return 0.0
    bw = max(xs) - min(xs) + 1
    bh = max(ys) - min(ys) + 1
    return round(bw * bh / (256 * 256), 4)


def deterministic_checks(img_path: str, target: tuple[int, int],
                         qa_cfg: dict) -> tuple[bool, list[str], dict]:
    """返回 (ok, issues, details)。规则集由预设 qa.checks 驱动（主图规则做成预设阈值）。"""
    checks = qa_cfg.get("checks") or ["size"]
    issues, details = [], {}
    img = Image.open(img_path)
    img.load()

    if "size" in checks:
        ok = img.size == tuple(target)
        details["size"] = {"got": list(img.size), "want": list(target)}
        if not ok:
            issues.append(f"size mismatch: got {img.size}, want {target}")

    if "format" in checks and (img.format or "").upper() not in ("PNG", "JPEG", "WEBP"):
        issues.append(f"unexpected format: {img.format}")

    if "white_bg" in checks:
        dev = int(qa_cfg.get("white_bg_dev", 12))
        ok = _corner_white(img, dev)
        details["white_bg"] = {"corner_max_dev": dev}
        if not ok:
            issues.append(f"background is not near-white at corners (dev>{dev})")

    if "product_ratio" in checks:
        ratio = _product_ratio(img)
        lo = float(qa_cfg.get("product_ratio_min", 0.15))
        hi = float(qa_cfg.get("product_ratio_max", 0.85))
        details["product_ratio"] = {"got": ratio, "min": lo, "max": hi}
        if not (lo <= ratio <= hi):
            issues.append(f"product ratio {ratio} outside [{lo}, {hi}]")

    if "min_edge" in checks:
        min_edge = int(qa_cfg.get("min_edge_px", target[1]))
        got = min(img.size)
        details["min_edge"] = {"got": got, "want": min_edge}
        if got < min_edge:
            issues.append(f"min edge {got} < required {min_edge}")

    return (not issues), issues, details


# ---------- 第 2/3 段：VLM 检查 ----------

def _qa_gateway():
    gw = settings_store.get_gateway("qa_vlm")
    if gw is None:
        return None, None
    return gw, settings_store.get_role("qa_vlm")["model"]


def _ask_vlm_json(gw: Gateway, model: str, prompt: str, image_paths: list[str]) -> dict:
    content = [{"type": "text", "text": prompt}] + [
        {"type": "image_url", "image_url": {"url": Gateway.data_url(p)}} for p in image_paths]
    res = gw.chat(model, [{"role": "user", "content": content}], temperature=0,
                  response_format={"type": "json_object"})
    text = res["choices"][0]["message"]["content"]
    try:
        return parse_plan_json(text)
    except json.JSONDecodeError:
        return {"score": 0, "issues": [f"qa vlm returned unparseable JSON: {text[:200]}"]}


def vlm_consistency(gw: Gateway, model: str, ref_paths: list[str], out_path: str,
                    threshold: float) -> tuple[bool, list[str], dict]:
    res = _ask_vlm_json(gw, model, CONSISTENCY_PROMPT, ref_paths + [out_path])
    try:
        score = float(res.get("score", 0))
    except (TypeError, ValueError):
        score = 0.0
    issues = [str(i) for i in (res.get("issues") or [])]
    bools = {k: bool(res.get(k)) for k in ("color_ok", "shape_ok", "logo_ok", "details_ok")}
    bad = [k for k, v in bools.items() if not v]
    issues = [f"{k} mismatch: {i}" for k, i in zip(bad, issues)] + issues[len(bad):]
    ok = score >= threshold and not bad
    if score < threshold and not bad:
        issues.append(f"consistency score {score} < threshold {threshold}")
    return ok, issues, {"score": score, **bools}


def vlm_text_check(gw: Gateway, model: str, out_path: str, module: dict,
                   text_mode: str) -> tuple[bool, list[str], dict]:
    res = _ask_vlm_json(gw, model, TEXT_CHECK_PROMPT, [out_path])
    found = [str(t).strip() for t in (res.get("found_text") or []) if str(t).strip()]
    issues = [str(i) for i in (res.get("issues") or [])]
    if text_mode == "blank_then_overlay":
        ok = not found
        if found:
            issues.append(f"expected NO text but found: {found}")
        return ok, issues, {"found_text": found}
    expected = {w for w in (module.get("headline", "") + " " + module.get("subline", "")).split() if w}
    joined = " ".join(found).lower()
    missing = [w for w in expected if w.lower() not in joined]
    ok = bool(found) and not missing
    if missing:
        issues.append(f"expected words missing/garbled: {missing}")
    if not found:
        issues.append("no text found but headline was expected")
    return ok, issues, {"found_text": found}


# ---------- 汇总入口 ----------

def run_qa(out_path: str, target: tuple[int, int], qa_cfg: dict, ref_paths: list[str],
           module: dict, text_mode: str) -> dict:
    """执行三段质检，返回可直接落库的 qa dict：
    {status: pass|fail, issues[], deterministic{}, consistency{}, text{}, vlm: used|skipped}
    """
    det_ok, det_issues, det_details = deterministic_checks(out_path, target, qa_cfg)
    qa = {
        "issues": list(det_issues),
        "deterministic": {"ok": det_ok, "details": det_details},
        "consistency": None,
        "text": None,
        "vlm": "skipped",
    }
    gw, model = _qa_gateway()
    if gw is None:
        log.info("qa_vlm 未配置，跳过 VLM 质检")
        qa["status"] = "pass" if det_ok else "fail"
        return qa

    qa["vlm"] = "used"
    threshold = float(qa_cfg.get("consistency_threshold", 4))
    c_ok, c_issues, c_details = vlm_consistency(gw, model, ref_paths, out_path, threshold)
    qa["consistency"] = {"ok": c_ok, "details": c_details}
    qa["issues"] += c_issues

    t_ok, t_issues, t_details = (True, [], {})
    if det_ok and c_ok:  # 前两段已失败时不再浪费一次 VLM 调用
        t_ok, t_issues, t_details = vlm_text_check(gw, model, out_path, module, text_mode)
        qa["text"] = {"ok": t_ok, "details": t_details}
        qa["issues"] += t_issues

    qa["status"] = "pass" if (det_ok and c_ok and t_ok) else "fail"
    return qa


def save_qa(asset_id: int, qa: dict, extra_cost: float = 0.0) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE asset SET qa_status=?, qa_json=?, cost_estimate=cost_estimate+? WHERE id=?",
            (qa["status"], json.dumps(qa, ensure_ascii=False), extra_cost, asset_id))
        conn.commit()


def approve(asset_id: int, note: str = "") -> bool:
    """人工放行：needs_review → approved（记录覆盖结果，PLAN_v2 §3 M4）。"""
    with connect() as conn:
        row = conn.execute("SELECT qa_json FROM asset WHERE id=?", (asset_id,)).fetchone()
        if row is None:
            return False
        try:
            qa = json.loads(row["qa_json"] or "{}")
        except json.JSONDecodeError:
            qa = {}
        qa["manual"] = {"approved": True, "note": note}
        conn.execute("UPDATE asset SET qa_status='approved', qa_json=? WHERE id=?",
                     (json.dumps(qa, ensure_ascii=False), asset_id))
        conn.commit()
    return True


def cost_of_role(role: str, calls: int = 1) -> float:
    try:
        return round(float(settings_store.get_role(role)["unit_price"]) * calls, 6)
    except Exception:
        return 0.0
