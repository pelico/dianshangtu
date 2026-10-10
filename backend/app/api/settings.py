"""设置相关 API：GET/PUT /api/settings、POST /api/settings/test。"""
import time

import requests as http
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from ..core.config import ROLE_ORDER
from ..services import settings_store
from ..services.settings_store import get_settings, update_settings

router = APIRouter(prefix="/api/settings")

CHAT_ROLES = {"planner", "qa_vlm"}


class ConnectionIn(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None  # 留空/缺省 = 不修改


class RoleCfgIn(BaseModel):
    model: Optional[str] = None
    mode: Optional[str] = None
    size: Optional[str] = None
    timeout_s: Optional[int] = None
    concurrency: Optional[int] = None
    unit_price: Optional[float] = None


class SettingsIn(BaseModel):
    connection: Optional[ConnectionIn] = None
    roles: Optional[dict[str, RoleCfgIn]] = None


@router.get("")
def read_settings():
    return get_settings()


@router.put("")
def save_settings(payload: SettingsIn):
    return update_settings(payload.model_dump(exclude_none=False))


@router.post("/test")
def test_connection(body: dict | None = None):
    """对各角色发一次最小请求（PLAN_v2 §5「测试连接」）。

    chat 角色（planner/qa_vlm）：1-token chat 请求，验证推理可用。
    图像/视频角色：GET /models 验证网关可达；能列出清单时检查模型是否在列（部分网关不列出，仅提示）。
    """
    requested = (body or {}).get("role")
    roles = [requested] if requested in ROLE_ORDER else list(ROLE_ORDER)
    results = []
    for role in roles:
        cfg = settings_store.get_role(role)
        t0 = time.time()
        gw = settings_store.get_gateway(role)
        if gw is None:
            results.append({"role": role, "ok": False, "elapsed_s": 0,
                            "detail": "未配置 base_url / API Key / 模型名"})
            continue
        try:
            if role in CHAT_ROLES:
                gw.post("/chat/completions", json={
                    "model": cfg["model"],
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                })
                ok, detail = True, "chat 请求正常"
            else:
                resp = http.get(gw.base + "/models", headers=gw.headers, timeout=30)
                if resp.ok:
                    ids = [m.get("id") for m in (resp.json().get("data") or [])]
                    if cfg["model"] in ids:
                        detail = "网关可达，模型在 /models 清单中"
                    else:
                        detail = "网关可达；/models 未列出该模型（部分网关不列出，仅供参考）"
                    ok = True
                else:
                    ok, detail = False, f"/models HTTP {resp.status_code}"
        except Exception as e:  # noqa: BLE001 —— 错误原文透出给前端
            ok, detail = False, str(e)[:300]
        results.append({"role": role, "ok": ok, "detail": detail,
                        "elapsed_s": round(time.time() - t0, 2)})
    return {"results": results}
