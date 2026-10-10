"""FastAPI 入口。M1 阶段：健康检查、设置、预设、项目、规划 Job、SSE。"""
import pathlib

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api.brand_profiles import router as brand_router
from .api.generation import assets_router, jobs_router, router as generation_router
from .api.presets import router as presets_router
from .api.projects import router as projects_router
from .api.settings import router as settings_router
from .api.stats import router as stats_router
from .api.video import router as video_router, video_scripts_router
from .core.config import DATA_DIR, FRONTEND_DIST
from .db.database import init_db
from .presets.builtin import ensure_builtin_presets
from .services import generator  # noqa: F401 —— 注册 image handler
from .services import jobs  # noqa: F401 —— 导入以注册 handler
from .services import planner  # noqa: F401 —— 注册 plan handler
from .services import preset_testing  # noqa: F401 —— 注册试跑 handler
from .services import video  # noqa: F401 —— 注册 video/video_script handler

app = FastAPI(title="电商 AI 出图工作台", version="0.1.0")

# 自用工具：开发期前端走 Vite 代理，这里放开 CORS 以便直连调试。
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

init_db()
ensure_builtin_presets()

app.include_router(settings_router)
app.include_router(presets_router)
app.include_router(projects_router)
app.include_router(generation_router)
app.include_router(assets_router)
app.include_router(jobs_router)
app.include_router(brand_router)
app.include_router(video_router)
app.include_router(video_scripts_router)
app.include_router(stats_router)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# 启动恢复：把中断的 queued/running 任务重新入队（PLAN_v2 §6）
jobs.recover()

# /files: 上传与产出的静态访问（uploads/、outputs/）
if DATA_DIR.is_dir():
    app.mount("/files", StaticFiles(directory=str(DATA_DIR)), name="files")

# 前端构建产物存在时由后端托管（对应 Docker 单镜像运行态；开发期走 Vite :5173）。
_dist = FRONTEND_DIST
if _dist.is_dir():
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """SPA history 路由回退：文件存在则返回文件，否则回 index.html。"""
        if full_path.startswith(("api/", "files/", "healthz")):
            from fastapi import HTTPException
            raise HTTPException(404, "Not Found")
        candidate = (_dist / full_path).resolve()
        if full_path and candidate.is_file() and str(candidate).startswith(str(_dist.resolve())):
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
