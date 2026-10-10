"""品牌档案 API（M3）。"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import brand

router = APIRouter(prefix="/api/brand-profiles")


class ProfileIn(BaseModel):
    name: str
    body: dict = {}


def _coerce(p: ProfileIn) -> dict:
    body = dict(p.body)
    if body.get("forbidden_words") and not isinstance(body["forbidden_words"], list):
        raise HTTPException(400, "forbidden_words 必须是数组")
    return body


@router.get("")
def get_profiles():
    return brand.list_profiles()


@router.post("")
def create_profile(p: ProfileIn):
    return brand.save_profile(None, p.name, _coerce(p))


@router.put("/{profile_id}")
def update_profile(profile_id: str, p: ProfileIn):
    if not brand.get_profile(profile_id):
        raise HTTPException(404, "档案不存在")
    return brand.save_profile(profile_id, p.name, _coerce(p))


@router.delete("/{profile_id}")
def remove_profile(profile_id: str):
    if not brand.delete_profile(profile_id):
        raise HTTPException(404, "档案不存在")
    return {"ok": True}
