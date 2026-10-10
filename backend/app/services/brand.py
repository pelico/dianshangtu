"""品牌/店铺档案（L2 档案层，PLAN_v2 §3.1）。

每店铺一份：品牌调性、配色、禁用词、固定语言等。编译出图提示词时注入。
"""
import json
import uuid

from ..db.database import connect

DEFAULT_FIELDS = ["brand_tone", "brand_colors", "forbidden_words", "logo_text", "copy_language"]


def list_profiles() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, name, body_json FROM brand_profile ORDER BY name").fetchall()
    return [{"id": r["id"], "name": r["name"], "body": json.loads(r["body_json"])} for r in rows]


def get_profile(profile_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT id, name, body_json FROM brand_profile WHERE id=?",
                           (profile_id,)).fetchone()
    if not row:
        return None
    return {"id": row["id"], "name": row["name"], "body": json.loads(row["body_json"])}


def save_profile(profile_id: str | None, name: str, body: dict) -> dict:
    pid = profile_id or uuid.uuid4().hex[:10]
    with connect() as conn:
        if profile_id:
            conn.execute("UPDATE brand_profile SET name=?, body_json=? WHERE id=?",
                         (name, json.dumps(body, ensure_ascii=False), pid))
        else:
            conn.execute("INSERT INTO brand_profile(id, name, body_json) VALUES (?, ?, ?)",
                         (pid, name, json.dumps(body, ensure_ascii=False)))
        conn.commit()
    return get_profile(pid)


def delete_profile(profile_id: str) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM brand_profile WHERE id=?", (profile_id,))
        conn.commit()
    return cur.rowcount > 0
