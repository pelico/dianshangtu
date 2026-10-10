import os
import pathlib
import sys
import tempfile

# 让 pytest 可以从 backend/ 目录直接导入 app 包
BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# 必须在导入 app 之前设置：config/db 在 import 时求值
os.environ["APP_SECRET"] = "test-secret-for-unit-tests"
os.environ["APP_DATA_DIR"] = tempfile.mkdtemp(prefix="aizuotu-test-data-")
