"""预设读取服务（完整的管理 CRUD 在 M3）。"""
import json

from ..db.database import connect


def list_presets() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.kind, MAX(v.version) AS latest_version, p.created_at
            FROM preset p JOIN preset_version v ON v.preset_id = p.id
            GROUP BY p.id ORDER BY p.created_at
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_latest_version(preset_id: str) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT v.id, v.preset_id, v.version, v.body_json
            FROM preset_version v
            WHERE v.preset_id = ? AND v.version = (
                SELECT MAX(version) FROM preset_version WHERE preset_id = ?)
            """,
            (preset_id, preset_id),
        ).fetchone()
    if not row:
        return None
    return {"id": row["id"], "preset_id": row["preset_id"], "version": row["version"],
            "body": json.loads(row["body_json"])}


def get_version_by_id(version_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, preset_id, version, body_json FROM preset_version WHERE id = ?",
            (version_id,),
        ).fetchone()
    if not row:
        return None
    return {"id": row["id"], "preset_id": row["preset_id"], "version": row["version"],
            "body": json.loads(row["body_json"])}
