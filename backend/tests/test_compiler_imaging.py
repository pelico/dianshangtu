"""compiler / imaging 单元测试。"""
import io

import pytest
from PIL import Image

from app.services.compiler import compile_prompt, text_block_for
from app.services.imaging import fit

PLAN = {
    "product": {"name": "包", "category": "bag", "anchor": "RED-SLEEVE-ANCHOR", "selling_points": []},
    "design_spec": {"style": "STYLE-X", "palette": "PAL-X", "copy_language": "English",
                    "canvas": "1464x600", "lighting": "LIGHT-X"},
    "modules": [{"id": "m1", "title_cn": "主视觉", "role": "hero", "scene": "SCENE-X",
                 "product_pose": "POSE-X", "photo_goal": "GOAL-X",
                 "visual_description": "VIS-X", "composition": "COMP-X",
                 "text_side": "right", "headline": "HEAD-X", "subline": "SUB-X"}],
}

TEMPLATE = """Banner for {{product_anchor}}.
SCENE: {{scene}} POSE: {{product_pose}} GOAL: {{photo_goal}}
FRAME: {{visual_description}} COMP: {{composition}} side={{text_side}}
STYLE: {{style}} {{palette}} {{lighting}}
{{text_block}}
"""

PRESET = {
    "image": {"template": TEMPLATE, "negative": "no watermark", "gen_size": "1536x1024"},
    "text": {"mode": "model"},
    "canvas": {"width": 1464, "height": 600},
}


def test_compile_model_text_mode():
    out = compile_prompt(PLAN, PLAN["modules"][0], PRESET)
    assert "RED-SLEEVE-ANCHOR" in out and "SCENE-X" in out and "HEAD-X" in out
    assert "render exactly this text" in out
    assert "ALSO AVOID: no watermark" in out
    assert "{{" not in out


def test_compile_blank_text_mode():
    preset = {**PRESET, "text": {"mode": "blank_then_overlay"}}
    out = compile_prompt(PLAN, PLAN["modules"][0], preset)
    assert "do NOT render any text" in out
    assert "HEAD-X" not in out  # 留白模式不把标题给模型


def test_compile_brand_vars():
    out = compile_prompt(PLAN, PLAN["modules"][0], PRESET, brand={
        "brand_tone": "premium tech", "brand_colors": "#E02424",
        "forbidden_words": ["cheap", "best"]})
    assert "BRAND TONE: premium tech" in out
    assert "FORBIDDEN WORDS (never render): cheap, best" in out


def test_compile_unreplaced_variable_raises():
    bad = {**PRESET, "image": {**PRESET["image"], "template": "hello {{unknown_var}}"}}
    with pytest.raises(ValueError, match="未替换变量"):
        compile_prompt(PLAN, PLAN["modules"][0], bad)


def test_text_block_modes():
    m = PLAN["modules"][0]
    assert "HEAD-X" in text_block_for(m, "model")
    assert "do NOT render" in text_block_for(m, "blank_then_overlay")


def _png(w, h, color=(200, 30, 30)):
    img = Image.new("RGB", (w, h), color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), img.size


def test_fit_crops_and_keeps_raw(tmp_path):
    data, size = _png(1600, 800)  # 比例 2:1 > 1464:600
    out = tmp_path / "a.png"
    r = fit(data, out, (1464, 600))
    assert Image.open(r["path"]).size == (1464, 600)
    assert Image.open(r["raw_path"]).size == size  # 原始输出保留


def test_fit_taller_image_crops_height(tmp_path):
    data, size = _png(800, 1600)
    out = tmp_path / "b.png"
    r = fit(data, out, (1464, 600))
    assert Image.open(r["path"]).size == (1464, 600)
    assert Image.open(r["raw_path"]).size == size
