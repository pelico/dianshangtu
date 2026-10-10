"""设置读写服务（PLAN_v2 §5、§6 setting 表）。

- provider.connection: {base_url}
- provider.api_key:    {"enc": "<fernet token>"}（敏感，静态加密，读取时只回 has_api_key）
- roles.mapping:       角色→{model, mode, size, timeout_s, concurrency, unit_price}
"""
import json

from ..core.config import DEFAULT_ROLES, ROLE_ORDER
from ..core.crypto import decrypt, encrypt
from ..db.database import connect

CONN_KEY = "provider.connection"
APIKEY_KEY = "provider.api_key"
ROLES_KEY = "roles.mapping"


def _get_json(key: str, default):
    with connect() as conn:
        row = conn.execute("SELECT value_json FROM setting WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value_json"]) if row else default


def _set_json(key: str, value) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO setting(key, value_json) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
            (key, json.dumps(value, ensure_ascii=False)),
        )
        conn.commit()


def get_settings() -> dict:
    conn_cfg = _get_json(CONN_KEY, {})
    roles_raw = _get_json(ROLES_KEY, {})
    merged = {}
    for role in ROLE_ORDER:
        cfg = dict(DEFAULT_ROLES[role])
        stored = dict(roles_raw.get(role) or {})
        has_key = bool(stored.pop("api_key_enc", None))
        cfg.update({k: v for k, v in stored.items() if v is not None})
        cfg.setdefault("base_url", "")
        cfg["has_api_key"] = has_key
        merged[role] = cfg
    api_key_cfg = _get_json(APIKEY_KEY, {})
    return {
        "connection": {
            "base_url": conn_cfg.get("base_url", ""),
            "has_api_key": bool(api_key_cfg.get("enc")),
        },
        "roles": merged,
    }


def update_settings(payload: dict) -> dict:
    connection = payload.get("connection") or {}
    if "base_url" in connection:
        _set_json(CONN_KEY, {"base_url": str(connection["base_url"] or "").rstrip("/")})
    api_key = connection.get("api_key")
    if api_key:  # 只在提供了非空值时更新；留空表示保持不变
        _set_json(APIKEY_KEY, {"enc": encrypt(str(api_key))})
    roles = payload.get("roles") or {}
    if roles:
        raw = _get_json(ROLES_KEY, {})
        for role, cfg in roles.items():
            if role not in DEFAULT_ROLES:
                continue
            base = dict(raw.get(role) or {})
            for k in ("model", "mode", "size"):
                if cfg.get(k) is not None:  # None=未提供（部分更新不覆盖）；空串=显式清空
                    base[k] = str(cfg[k] or "").strip()
            # 角色级独立网关：base_url 留空 = 回退全局；api_key 非空 = 更新加密存储
            if cfg.get("base_url") is not None:
                base["base_url"] = str(cfg["base_url"]).strip()
            if cfg.get("api_key"):
                base["api_key_enc"] = encrypt(str(cfg["api_key"]))
            if cfg.get("clear_api_key"):
                base.pop("api_key_enc", None)
            for k in ("timeout_s", "concurrency"):
                if k in cfg:
                    try:
                        base[k] = max(1, int(cfg[k]))
                    except (TypeError, ValueError):
                        pass
            if "unit_price" in cfg:
                try:
                    base["unit_price"] = max(0.0, float(cfg["unit_price"]))
                except (TypeError, ValueError):
                    pass
            raw[role] = base
        _set_json(ROLES_KEY, raw)
    return get_settings()


def get_api_key() -> str:
    cfg = _get_json(APIKEY_KEY, {})
    return decrypt(cfg["enc"]) if cfg.get("enc") else ""


def get_role(role: str) -> dict:
    return get_settings()["roles"][role]


def get_gateway(role: str):
    """按角色构造 Gateway：角色级 base_url/api_key 优先，未设置时回退全局。未配置完整返回 None。"""
    from ..providers.openai_compat import Gateway

    cfg = get_role(role)
    stored = _get_json(ROLES_KEY, {}).get(role) or {}
    base_url = (cfg.get("base_url") or "").strip() or _get_json(CONN_KEY, {}).get("base_url", "")
    api_key = decrypt(stored["api_key_enc"]) if stored.get("api_key_enc") else get_api_key()
    if not (base_url and api_key and cfg["model"]):
        return None
    return Gateway(base_url, api_key, timeout=cfg["timeout_s"])
