"""可恢复的进程内任务系统（PLAN_v2 §6 的 M1 子集）。

- 每种任务类型注册一个 handler；入队即写 job 表并提交线程池。
- 启动时 recover()：把 running/queued 任务重置为 queued 并重新提交（容器重启可续）。
- 每角色并发上限、SSE 事件广播在 M2 出图阶段补齐；当前全局线程池 max_workers=2。
"""
import json
import logging
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

from ..db.database import connect

log = logging.getLogger("jobs")

_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="job")
_handlers: dict[str, callable] = {}

# 每角色并发上限（PLAN_v2 §6：默认 2，设置页可调；改动只对新任务生效）
_sems: dict[str, tuple[int, threading.Semaphore]] = {}
_sem_lock = threading.Lock()


def _role_semaphore(role: str | None):
    if not role:
        return None
    with _sem_lock:
        from ..services import settings_store
        try:
            n = max(1, int(settings_store.get_role(role)["concurrency"]))
        except Exception:
            n = 2
        cur = _sems.get(role)
        if cur is None or cur[0] != n:
            cur = (n, threading.Semaphore(n))
            _sems[role] = cur
        return cur[1]


def handler(kind: str):
    def deco(fn):
        _handlers[kind] = fn
        return fn
    return deco


def enqueue(project_id: str, kind: str, target_id: str | None = None,
            payload: dict | None = None) -> int:
    if kind not in _handlers:
        raise ValueError(f"no handler for job kind: {kind}")
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO job(project_id, kind, target_id, status, payload_json) "
            "VALUES (?, ?, ?, 'queued', ?)",
            (project_id, kind, target_id, json.dumps(payload or {}, ensure_ascii=False)),
        )
        conn.commit()
        job_id = cur.lastrowid
    _executor.submit(_run, job_id)
    return job_id


def _run(job_id: int) -> None:
    with connect() as conn:
        job = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    if job is None or job["status"] in ("canceled", "done"):
        return
    try:
        payload = json.loads(job["payload_json"] or "{}")
    except json.JSONDecodeError:
        payload = {}
    sem = _role_semaphore(payload.get("role"))
    if sem:
        sem.acquire()
    try:
        _transition(job_id, "running")
        _handlers[job["kind"]](job_id)
        _transition(job_id, "done")
    except Exception as e:  # noqa: BLE001 —— 任务失败是常态，原文入库（PLAN_v2 §2.4）
        err = f"{type(e).__name__}: {e}"[:1000]
        log.error("job %s failed: %s\n%s", job_id, err, traceback.format_exc())
        _transition(job_id, "failed", error=err)
    finally:
        if sem:
            sem.release()


def _transition(job_id: int, status: str, error: str | None = None) -> None:
    with connect() as conn:
        if status == "running":
            conn.execute("UPDATE job SET status='running', started_at=datetime('now') WHERE id=?", (job_id,))
        elif status == "done":
            conn.execute("UPDATE job SET status='done', finished_at=datetime('now') WHERE id=?", (job_id,))
        elif status == "failed":
            conn.execute(
                "UPDATE job SET status='failed', error=?, finished_at=datetime('now'), "
                "attempt=attempt+1 WHERE id=?", (error, job_id))
        conn.commit()


def get_job(job_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM job WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def set_result(job_id: int, result: dict) -> None:
    """把结果信息合并进 payload_json（试跑等无 asset 落库的任务用）。"""
    with connect() as conn:
        row = conn.execute("SELECT payload_json FROM job WHERE id = ?", (job_id,)).fetchone()
        payload = json.loads(row["payload_json"] or "{}") if row else {}
        payload["result"] = result
        conn.execute("UPDATE job SET payload_json=? WHERE id=?",
                     (json.dumps(payload, ensure_ascii=False), job_id))
        conn.commit()


def recover() -> None:
    """启动恢复：running → queued（进程中断视为未完成），并把未完成任务重新提交。"""
    with connect() as conn:
        conn.execute("UPDATE job SET status='queued' WHERE status IN ('queued','running')")
        rows = conn.execute(
            "SELECT id, kind FROM job WHERE status='queued' ORDER BY id").fetchall()
        conn.commit()
    for row in rows:
        if row["kind"] in _handlers:
            _executor.submit(_run, row["id"])
            log.info("recovered job %s (%s)", row["id"], row["kind"])
