"""规划服务测试：JSON 解析容错、schema 校验、带错误重试一次。"""
import json

import pytest

from app.services.planner import parse_plan_json, validate_plan

PLAN_OK = {
    "product": {"name": "包", "category": "bag", "anchor": "red sleeve, black zipper", "selling_points": []},
    "design_spec": {"style": "minimal", "palette": "red/black", "copy_language": "English",
                    "canvas": "1464x600", "lighting": "soft studio"},
    "modules": [{
        "id": "m1", "title_cn": "主视觉", "role": "hero", "scene": "desk",
        "product_pose": "flat", "photo_goal": "show shape",
        "visual_description": "red bag on desk", "composition": "center",
        "text_side": "right", "headline": "SLEEK", "subline": "everyday",
    }],
}


def test_parse_plan_json_strips_fences():
    raw = "```json\n" + json.dumps(PLAN_OK) + "\n```"
    assert parse_plan_json(raw) == PLAN_OK
    assert parse_plan_json(json.dumps(PLAN_OK)) == PLAN_OK


def test_parse_plan_json_gateway_quirks():
    good = json.dumps(PLAN_OK, ensure_ascii=False)
    # 双重编码：部分网关把 JSON 再包一层字符串
    assert parse_plan_json(json.dumps(good)) == PLAN_OK
    # 前后缀说明文字
    assert parse_plan_json("Here is your plan:\n" + good + "\nHope this helps!") == PLAN_OK
    # 非 dict JSON 仍要报错
    with pytest.raises(ValueError, match="not a JSON object"):
        parse_plan_json(json.dumps([PLAN_OK]))


def test_validate_plan_ok():
    validate_plan(PLAN_OK)  # 不抛


def test_validate_plan_missing_top_key():
    bad = {k: v for k, v in PLAN_OK.items() if k != "design_spec"}
    with pytest.raises(ValueError, match="design_spec"):
        validate_plan(bad)


def test_validate_plan_bad_module_field():
    bad = json.loads(json.dumps(PLAN_OK))
    del bad["modules"][0]["headline"]
    with pytest.raises(ValueError, match="headline"):
        validate_plan(bad)


def test_validate_plan_duplicate_module_id():
    bad = json.loads(json.dumps(PLAN_OK))
    bad["modules"].append(dict(bad["modules"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        validate_plan(bad)


def test_validate_plan_empty_modules():
    bad = json.loads(json.dumps(PLAN_OK))
    bad["modules"] = []
    with pytest.raises(ValueError, match="non-empty"):
        validate_plan(bad)
