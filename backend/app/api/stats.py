"""成本统计（PLAN_v2 §3 M4：/api/stats/cost，单价在角色映射中配置）。"""
from fastapi import APIRouter

from ..db.database import connect

router = APIRouter(prefix="/api/stats")


@router.get("/cost")
def cost_stats():
    with connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(cost_estimate),0) c FROM asset").fetchone()
        by_role = conn.execute(
            "SELECT COALESCE(NULLIF(role,''),'(未记录)') role, COUNT(*) n, "
            "COALESCE(SUM(cost_estimate),0) c FROM asset GROUP BY role ORDER BY c DESC").fetchall()
        by_day = conn.execute(
            "SELECT date(created_at) d, COUNT(*) n, COALESCE(SUM(cost_estimate),0) c "
            "FROM asset GROUP BY d ORDER BY d DESC LIMIT 30").fetchall()
        by_project = conn.execute(
            "SELECT a.project_id, COALESCE(p.name, a.project_id) name, COUNT(*) n, "
            "COALESCE(SUM(a.cost_estimate),0) c FROM asset a "
            "LEFT JOIN project p ON p.id = a.project_id "
            "GROUP BY a.project_id ORDER BY c DESC LIMIT 50").fetchall()
        qa = conn.execute(
            "SELECT qa_status, COUNT(*) n FROM asset WHERE kind='image' "
            "GROUP BY qa_status").fetchall()
    return {
        "total": {"assets": total["n"], "cost": round(total["c"], 4)},
        "by_role": [dict(r) for r in by_role],
        "by_day": [dict(r) for r in by_day],
        "by_project": [dict(r) for r in by_project],
        "qa_status": [dict(r) for r in qa],
    }
