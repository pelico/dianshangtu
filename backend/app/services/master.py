"""主图确定性合成（PLAN_v2 §3 M5）：rembg 抠图 → 白底画布 → 平台规则校验。

- rembg 为可选依赖：Docker 构建时 `--build-arg WITH_REMBG=1` 安装；未安装时降级为
  “原图居中贴白底”（适用于本来就是白底的商品图），并回传降级标记。
- 平台规则（占比/最小边长/纯白阈值）全部在预设 qa 配置里，不在代码写死。
- 副图（多角度/场景）复用同一引擎：把参考图换成对应角度即可，本函数只负责单张合成。
"""
import io
import logging
import pathlib

from PIL import Image

log = logging.getLogger("master")


def _cutout(img_bytes: bytes) -> tuple[Image.Image, bool]:
    """rembg 抠图；不可用时返回原图（降级模式）。"""
    try:
        from rembg import remove  # 延迟导入：可选依赖
    except ImportError:
        log.warning("rembg 未安装，主图合成降级为原图贴白底（构建时 WITH_REMBG=1 可启用）")
        return Image.open(io.BytesIO(img_bytes)).convert("RGBA"), False
    out = remove(img_bytes)
    return Image.open(io.BytesIO(out)).convert("RGBA"), True


def compose_product(img_path: str, target: tuple[int, int], image_cfg: dict) -> tuple[bytes, dict]:
    """商品主体贴到纯白画布，按占比缩放居中。返回 (png bytes, meta)。"""
    img_bytes = pathlib.Path(img_path).read_bytes()
    tw, th = int(target[0]), int(target[1])
    ratio_lo = float(image_cfg.get("product_ratio_min", 0.55))
    ratio_hi = float(image_cfg.get("product_ratio_max", 0.85))
    canvas = Image.new("RGB", (tw, th), (255, 255, 255))

    subject, cut = _cutout(img_bytes)
    # 目标：主体包围盒面积占比落在 [ratio_lo, ratio_hi]，默认取区间中点
    alpha = subject.getchannel("A")
    bbox = alpha.getbbox()
    if bbox:
        sw, sh = bbox[2] - bbox[0], bbox[3] - bbox[1]
        want = ((ratio_lo + ratio_hi) / 2) * tw * th
        scale = min((want / (sw * sh)) ** 0.5, tw / sw * 0.98, th / sh * 0.98)
        new_size = (max(1, int(sw * scale)), max(1, int(sh * scale)))
        subject = subject.crop(bbox).resize(new_size, Image.LANCZOS)
    else:
        subject = subject.resize((tw // 2, th // 2), Image.LANCZOS)

    px = (tw - subject.width) // 2
    py = (th - subject.height) // 2
    canvas.paste(subject, (px, py), subject)

    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    return buf.getvalue(), {"compose": "cutout_white_bg", "rembg": cut,
                            "canvas": [tw, th], "paste": [px, py]}
