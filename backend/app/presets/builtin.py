"""内置预设的初始内容与种子化（PLAN_v2 §0、§4）。

提示词内容来自 poc/prompts（原样保留），之后以数据库为准——代码只在首次启动时种子化。
"""
import json
import pathlib

HERE = pathlib.Path(__file__).parent

PLANNER_SYSTEM = (HERE / "planner.system.md").read_text(encoding="utf-8")
IMAGE_TEMPLATE = (HERE / "image.template.md").read_text(encoding="utf-8")

BUILTIN_PRESET_ID = "aplus_banner"
MASTER_PRESET_ID = "master_image"


def _body(version: int) -> dict:
    return {
        "id": BUILTIN_PRESET_ID,
        "name": "亚马逊 A+ 横幅",
        "version": version,
        "inputs": {
            "required": ["product_images"],
            "optional": ["brief", "brand_profile_id", "copy_language"],
        },
        "canvas": {"width": 1464, "height": 600},
        "planner": {
            "model_ref": "planner",
            "system_prompt": PLANNER_SYSTEM,
            "module_count": {"default": 5, "min": 1, "max": 12},
        },
        "module_library": [
            {"role": "hero", "hint": "品牌/主视觉"},
            {"role": "feature", "hint": "核心功能"},
            {"role": "fit", "hint": "适配/防护"},
            {"role": "scene", "hint": "使用场景"},
            {"role": "lifestyle", "hint": "生活方式/桌面"},
        ],
        "image": {
            "model_ref": "image_main",
            "mode": "edits",
            "gen_size": "1536x1024",
            "fit": "center_crop",
            "candidates": 1,
            "template": IMAGE_TEMPLATE,
            "negative": "distorted product, extra logos, watermark, garbled text",
        },
        "text": {"mode": "model"},
        "qa": {
            "rules": ["size", "product_consistency", "text_match", "no_extra_logo"],
            "max_auto_retries": 2,
        },
    }


def _master_body(version: int) -> dict:
    """主图预设（M5）：确定性合成 + 平台规则阈值全部在预设里，不在代码写死。"""
    return {
        "id": MASTER_PRESET_ID,
        "name": "亚马逊主图（白底 1:1）",
        "version": version,
        "inputs": {
            "required": ["product_images"],
            "optional": ["brief", "brand_profile_id", "copy_language"],
        },
        "canvas": {"width": 1600, "height": 1600},
        "planner": {
            "model_ref": "planner",
            "system_prompt": PLANNER_SYSTEM,
            "module_count": {"default": 1, "min": 1, "max": 3},
        },
        "module_library": [
            {"role": "main", "hint": "主图（白底主体图）"},
        ],
        "image": {
            "model_ref": "image_main",
            "compose": "cutout_white_bg",       # 确定性合成，不走模型出图
            "product_ratio_min": 0.55,          # 合成时主体占比目标区间
            "product_ratio_max": 0.85,
            "gen_size": "",
            "fit": "none",
            "candidates": 1,
            "template": IMAGE_TEMPLATE,         # 保留：若改回模型出图模式可用
            "negative": "text, watermark, logo overlays, props, shadows on white",
        },
        "text": {"mode": "blank_then_overlay"},  # 主图不允许任何文字
        "qa": {
            "checks": ["size", "white_bg", "product_ratio", "min_edge"],
            "white_bg_dev": 8,
            "product_ratio_min": 0.5,
            "product_ratio_max": 0.9,
            "min_edge_px": 1600,
            "consistency_threshold": 4,
            "max_auto_retries": 1,
        },
    }


def _seed(conn, preset_id: str, name: str, kind: str, body: dict) -> None:
    row = conn.execute("SELECT id FROM preset WHERE id = ?", (preset_id,)).fetchone()
    if row:
        return
    conn.execute("INSERT INTO preset(id, name, kind) VALUES (?, ?, ?)", (preset_id, name, kind))
    conn.execute(
        "INSERT INTO preset_version(preset_id, version, body_json) VALUES (?, 1, ?)",
        (preset_id, json.dumps(body, ensure_ascii=False)))


def ensure_builtin_presets() -> None:
    """幂等：仅当预设不存在时写入 v1；已存在则以数据库为准，不覆盖。"""
    from ..db.database import connect

    with connect() as conn:
        _seed(conn, BUILTIN_PRESET_ID, _body(1)["name"], "aplus_banner", _body(1))
        _seed(conn, MASTER_PRESET_ID, _master_body(1)["name"], "master_image", _master_body(1))
        conn.commit()
