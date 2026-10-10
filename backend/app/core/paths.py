"""DATA_DIR 内文件路径 → /files 静态 URL。"""
import pathlib

from .config import DATA_DIR


def file_url(path: str) -> str:
    p = pathlib.Path(path).resolve()
    try:
        rel = p.relative_to(DATA_DIR.resolve())
    except ValueError:
        rel = pathlib.Path(p.name)
    return "/files/" + rel.as_posix()
