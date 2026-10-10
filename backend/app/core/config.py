"""全局配置。敏感决策见 PLAN_v2.md：单镜像 Docker 部署时 APP_SECRET 必须由环境变量提供。"""
import os
import pathlib

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]   # backend/
PROJECT_ROOT = BACKEND_DIR.parent                           # 仓库根
DATA_DIR = pathlib.Path(os.environ.get("APP_DATA_DIR", str(PROJECT_ROOT / "data")))
FRONTEND_DIST = pathlib.Path(os.environ.get(
    "FRONTEND_DIST", str(PROJECT_ROOT / "frontend" / "dist")))

# 开发环境缺省值仅用于本地跑通；生产（Docker）必须显式设置，否则加密可被预测。
APP_SECRET = os.environ.get("APP_SECRET", "dev-insecure-secret-change-me")

# 访问密码（可选）。设置后启用简单登录门；为空则无鉴权（自用默认）。
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")

# 角色→模型映射的默认值（PLAN_v2 §5）。模型名留空表示未配置，调用前必须先在设置页填好。
ROLE_ORDER = ["planner", "qa_vlm", "image_main", "image_alt", "video"]
ROLE_LABELS = {
    "planner": "规划器（多模态 LLM）",
    "qa_vlm": "质检 VLM",
    "image_main": "出图主模型",
    "image_alt": "出图备选模型",
    "video": "视频（后期）",
}
DEFAULT_ROLES = {
    "planner":    {"model": "", "mode": "chat",        "size": "",          "timeout_s": 300, "concurrency": 2, "unit_price": 0.0},
    "qa_vlm":     {"model": "", "mode": "chat",        "size": "",          "timeout_s": 120, "concurrency": 2, "unit_price": 0.0},
    "image_main": {"model": "", "mode": "edits",       "size": "1536x1024", "timeout_s": 300, "concurrency": 2, "unit_price": 0.0},
    "image_alt":  {"model": "", "mode": "edits",       "size": "",          "timeout_s": 300, "concurrency": 2, "unit_price": 0.0},
    "video":      {"model": "", "mode": "generations", "size": "",          "timeout_s": 600, "concurrency": 1, "unit_price": 0.0},
}
