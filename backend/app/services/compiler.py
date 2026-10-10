"""出图提示词编译（PLAN_v2 §3.3 变量表）。

从 poc/poc.py 的 compile_prompt 重构：
- 文字模式由预设 text.mode 驱动（model 直出 | blank_then_overlay 留白后贴）
- negative 与品牌档案变量（M3 接入档案层，此处预留参数）
- 模板未替换的 {{变量}} 视为错误，抛 ValueError 防止静默出废图
"""
import logging

log = logging.getLogger("compiler")

VARIABLES = ["product_anchor", "scene", "product_pose", "photo_goal", "visual_description",
             "composition", "text_side", "style", "palette", "lighting", "text_block"]


def text_block_for(module: dict, mode: str) -> str:
    """与 poc.py 逐字一致，仅由参数驱动。"""
    if mode == "model":
        return (f'TEXT: render exactly this text, spelled exactly, in a clean modern sans-serif. '
                f'Headline: "{module["headline"]}". Subline: "{module["subline"]}". '
                f'Render no other text, no small print, no icons with text.')
    return "TEXT: do NOT render any text, letters or numbers anywhere in the image."


def compile_prompt(plan: dict, module: dict, preset_body: dict,
                   text_mode: str | None = None, brand: dict | None = None) -> str:
    image_cfg = preset_body["image"]
    template = image_cfg["template"]
    negative = image_cfg.get("negative", "")
    mode = text_mode or preset_body.get("text", {}).get("mode", "model")

    ds, pr = plan["design_spec"], plan["product"]
    vals = {
        "product_anchor": pr["anchor"],
        "scene": module["scene"],
        "product_pose": module["product_pose"],
        "photo_goal": module["photo_goal"],
        "visual_description": module["visual_description"],
        "composition": module["composition"],
        "text_side": module.get("text_side", "right"),
        "style": ds["style"],
        "palette": ds["palette"],
        "lighting": ds["lighting"],
        "text_block": text_block_for(module, mode),
    }
    out = template
    for k, v in vals.items():
        out = out.replace("{{" + k + "}}", str(v))

    if brand:  # L2 档案层（M3 提供界面）
        extra = []
        if brand.get("brand_tone"):
            extra.append(f"BRAND TONE: {brand['brand_tone']}")
        if brand.get("brand_colors"):
            extra.append(f"BRAND COLORS: {brand['brand_colors']}")
        if brand.get("forbidden_words"):
            words = ", ".join(brand["forbidden_words"])
            extra.append(f"FORBIDDEN WORDS (never render): {words}")
        if extra:
            out += "\n\n" + "\n".join(extra)

    if negative:
        out += f"\nALSO AVOID: {negative}"

    import re
    leftover = re.findall(r"\{\{(\w+)\}\}", out)
    if leftover:
        raise ValueError(f"提示词模板存在未替换变量: {leftover}")
    return out
