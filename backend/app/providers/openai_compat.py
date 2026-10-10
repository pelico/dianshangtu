"""OpenAI 兼容网关客户端。

从 poc/poc.py 重构而来（PLAN_v2 §5 要求行为保持一致、不重写逻辑）：
- post()            保留 2 次尝试、3 秒间隔的重试语义；超时改为可配置
- data_url()        不变
- extract_image()   必须原样保留对 4 类响应形态的兼容（有测试锁定）：
    1) images API: data[0].b64_json / data[0].url
    2) OpenRouter 风格: choices[0].message.images[].image_url.url
    3) 聊天内容中的 data:image/...;base64
    4) 聊天内容中的 http(s) 图片链接
- gen_image()       edits（multipart image[] 多参考图）与 chat 两模式；generations 预留
"""
import base64
import mimetypes
import pathlib
import re
import time

import requests


class GatewayError(RuntimeError):
    pass


class Gateway:
    def __init__(self, base_url: str, api_key: str, timeout: int = 300,
                 retries: int = 2, retry_wait: float = 3.0):
        self.base = base_url.rstrip("/")
        self.headers = {"Authorization": "Bearer " + api_key}
        self.timeout = timeout
        self.retries = retries
        self.retry_wait = retry_wait

    # ---- 基础请求（对应 poc.post，行为一致） -------------------------------
    def post(self, path: str, **kw) -> dict:
        last_err = ""
        for _ in range(self.retries):
            r = requests.post(self.base + path, headers=self.headers, timeout=self.timeout, **kw)
            if r.ok:
                return r.json()
            last_err = f"{path} HTTP {r.status_code}: {r.text[:300]}"
            time.sleep(self.retry_wait)
        raise GatewayError(last_err)

    @staticmethod
    def data_url(path: str) -> str:
        mime = mimetypes.guess_type(path)[0] or "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(pathlib.Path(path).read_bytes()).decode()

    # ---- 规划（对应 poc.make_plan 的请求部分） -----------------------------
    def chat(self, model: str, messages: list, temperature: float | None = None,
             response_format: dict | None = None) -> dict:
        body = {"model": model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if response_format is not None:
            body["response_format"] = response_format
        return self.post("/chat/completions", json=body)

    # ---- 出图（对应 poc.gen_image） ----------------------------------------
    def gen_image(self, model: str, mode: str, size: str, prompt: str, refs: list[str]) -> bytes:
        if mode == "edits":
            files = [("image[]", (pathlib.Path(p).name, pathlib.Path(p).read_bytes(),
                                  mimetypes.guess_type(p)[0] or "image/jpeg")) for p in refs]
            data = {"model": model, "prompt": prompt, "n": "1"}
            if size:
                data["size"] = size
            return self.extract_image(self.post("/images/edits", files=files, data=data))
        if mode == "generations":
            data = {"model": model, "prompt": prompt, "n": "1"}
            if size:
                data["size"] = size
            return self.extract_image(self.post("/images/generations", json=data))
        content = [{"type": "text", "text": prompt}] + \
                  [{"type": "image_url", "image_url": {"url": self.data_url(p)}} for p in refs]
        return self.extract_image(self.post("/chat/completions", json={
            "model": model, "messages": [{"role": "user", "content": content}]}))

    # ---- 视频图生视频（M6：提交 → 轮询 → 下载） ------------------------------
    def submit_video(self, model: str, prompt: str, first_frame_path: str | None = None,
                     size: str = "", seconds: int = 5) -> dict:
        """提交图生视频任务。网关实现各异，走最通用的 POST /videos 形态。"""
        body = {"model": model, "prompt": prompt, "seconds": int(seconds)}
        if size:
            body["size"] = size
        if first_frame_path:
            body["first_frame_image"] = self.data_url(first_frame_path)
        return self.post("/videos", json=body)

    def poll_video(self, job_ref: str) -> dict:
        r = requests.get(f"{self.base}/videos/{job_ref}", headers=self.headers,
                         timeout=min(self.timeout, 60))
        if r.ok:
            return r.json()
        raise GatewayError(f"poll video HTTP {r.status_code}: {r.text[:300]}")

    # ---- 响应解析（对应 poc.extract_image / fetch_any，勿改动兼容面） -------
    def fetch_any(self, u: str) -> bytes:
        if u.startswith("data:"):
            return base64.b64decode(u.split(",", 1)[1])
        return requests.get(u, timeout=120).content

    def extract_image(self, res: dict) -> bytes:
        """Return PNG/JPEG bytes from an images-API or chat-style response (best effort)."""
        if "data" in res and res["data"]:
            d = res["data"][0]
            if d.get("b64_json"):
                return base64.b64decode(d["b64_json"])
            if d.get("url"):
                return requests.get(d["url"], timeout=120).content
        msg = res["choices"][0]["message"]
        for im in msg.get("images") or []:                      # OpenRouter-style
            u = im.get("image_url", {}).get("url") or im.get("url")
            if u:
                return self.fetch_any(u)
        content = msg.get("content")
        if isinstance(content, list):
            content = " ".join(c.get("text", "") or c.get("image_url", {}).get("url", "") for c in content)
        m = re.search(r"data:image/[a-z]+;base64,([A-Za-z0-9+/=]+)", content or "")
        if m:
            return base64.b64decode(m.group(1))
        m = re.search(r"https?://[^\s)\"']+", content or "")
        if m:
            return requests.get(m.group(0), timeout=120).content
        raise RuntimeError("no image found in response")
