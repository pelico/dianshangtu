"""成品图处理：fit（居中裁剪+缩放，保留 _raw）——与 poc/poc.py 的 fit 行为一致。"""
import io
import pathlib

from PIL import Image


def fit(img_bytes: bytes, out_path, target: tuple[int, int]) -> dict:
    """Center-crop to target ratio, then resize. Raw output is kept next to it."""
    out_path = pathlib.Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    raw_path = out_path.with_name(out_path.stem + "_raw.png")
    im.save(raw_path)
    tw, th = target
    w, h = im.size
    if w / h > tw / th:
        nw = int(h * tw / th)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w * th / tw)
        im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    im.resize((tw, th), Image.LANCZOS).save(out_path)
    return {"path": str(out_path), "raw_path": str(raw_path), "width": tw, "height": th}
