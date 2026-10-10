"""
Step-0 PoC: product images -> structured plan -> N image models -> contact sheet.
All calls use an OpenAI-compatible gateway.

samples/<product>/*.jpg|png   first image = main reference; extra = other angles
samples/<product>/brief.txt   optional: selling points / constraints (plain text)

Env (see .env.example):
  BASE_URL      e.g. https://your-gateway/v1
  API_KEY
  PLANNER_MODEL vision-capable chat model
  IMAGE_MODELS  comma list of  name|mode|size   (mode: edits | chat ; size may be empty)
  TEXT_MODE     model | blank
  TARGET_SIZE   1464x600
  COPY_LANG     English
  N_MODULES     5
"""
import base64, io, json, mimetypes, os, pathlib, re, sys, time
import requests
from PIL import Image

BASE = os.environ["BASE_URL"].rstrip("/")
HEAD = {"Authorization": "Bearer " + os.environ["API_KEY"]}
PLANNER = os.environ.get("PLANNER_MODEL", "gpt-4o")
IMAGE_MODELS = [m.strip().split("|") for m in os.environ["IMAGE_MODELS"].split(",") if m.strip()]
TEXT_MODE = os.environ.get("TEXT_MODE", "model")
TARGET = tuple(int(x) for x in os.environ.get("TARGET_SIZE", "1464x600").split("x"))
LANG = os.environ.get("COPY_LANG", "English")
N_MODULES = int(os.environ.get("N_MODULES", "5"))
HERE = pathlib.Path(__file__).parent
PLANNER_PROMPT = (HERE / "prompts/planner.system.md").read_text(encoding="utf-8")
IMAGE_TEMPLATE = (HERE / "prompts/image.template.md").read_text(encoding="utf-8")


def data_url(p):
    mime = mimetypes.guess_type(p)[0] or "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(pathlib.Path(p).read_bytes()).decode()


def post(path, **kw):
    for attempt in range(2):
        r = requests.post(BASE + path, headers=HEAD, timeout=300, **kw)
        if r.ok:
            return r.json()
        print(f"  ! {path} HTTP {r.status_code}: {r.text[:300]}")
        time.sleep(3)
    raise RuntimeError(f"{path} failed")


def make_plan(refs, brief):
    user = [{"type": "text", "text": f"Copy language: {LANG}\nNumber of modules: {N_MODULES}\n"
             f"Canvas: wide banner {TARGET[0]}x{TARGET[1]}\nUser brief: {brief or '(none)'}"}]
    user += [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in refs]
    res = post("/chat/completions", json={
        "model": PLANNER, "temperature": 0.7,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": PLANNER_PROMPT}, {"role": "user", "content": user}]})
    txt = res["choices"][0]["message"]["content"].strip()
    txt = re.sub(r"^```(?:json)?|```$", "", txt).strip()
    return json.loads(txt)


def compile_prompt(plan, m):
    ds, pr = plan["design_spec"], plan["product"]
    if TEXT_MODE == "model":
        tb = (f'TEXT: render exactly this text, spelled exactly, in a clean modern sans-serif. '
              f'Headline: "{m["headline"]}". Subline: "{m["subline"]}". '
              f'Render no other text, no small print, no icons with text.')
    else:
        tb = "TEXT: do NOT render any text, letters or numbers anywhere in the image."
    vals = {"product_anchor": pr["anchor"], "scene": m["scene"], "product_pose": m["product_pose"],
            "photo_goal": m["photo_goal"], "visual_description": m["visual_description"],
            "composition": m["composition"], "text_side": m.get("text_side", "right"),
            "style": ds["style"], "palette": ds["palette"], "lighting": ds["lighting"], "text_block": tb}
    out = IMAGE_TEMPLATE
    for k, v in vals.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def extract_image(res):
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
            return fetch_any(u)
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


def fetch_any(u):
    if u.startswith("data:"):
        return base64.b64decode(u.split(",", 1)[1])
    return requests.get(u, timeout=120).content


def gen_image(model, mode, size, prompt, refs):
    if mode == "edits":
        files = [("image[]", (pathlib.Path(p).name, pathlib.Path(p).read_bytes(),
                              mimetypes.guess_type(p)[0] or "image/jpeg")) for p in refs]
        data = {"model": model, "prompt": prompt, "n": "1"}
        if size:
            data["size"] = size
        return extract_image(post("/images/edits", files=files, data=data))
    content = [{"type": "text", "text": prompt}] + \
              [{"type": "image_url", "image_url": {"url": data_url(p)}} for p in refs]
    return extract_image(post("/chat/completions", json={
        "model": model, "messages": [{"role": "user", "content": content}]}))


def fit(img_bytes, out_path):
    """Center-crop to target ratio, then resize. Raw output is kept next to it."""
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    im.save(str(out_path).replace(".png", "_raw.png"))
    tw, th = TARGET
    w, h = im.size
    if w / h > tw / th:
        nw = int(h * tw / th); im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w * th / tw); im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    im.resize(TARGET, Image.LANCZOS).save(out_path)


def run_product(pdir):
    refs = sorted(str(p) for p in pdir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    if not refs:
        return
    brief_f = pdir / "brief.txt"
    brief = brief_f.read_text(encoding="utf-8") if brief_f.exists() else ""
    out = HERE / "out" / pdir.name
    out.mkdir(parents=True, exist_ok=True)
    plan_f = out / "plan.json"
    if plan_f.exists():                       # edit plan.json by hand and re-run to iterate on prompts
        plan = json.loads(plan_f.read_text(encoding="utf-8")); print(f"[{pdir.name}] reuse plan.json")
    else:
        print(f"[{pdir.name}] planning with {PLANNER} ...")
        plan = make_plan(refs, brief)
        plan_f.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    prompts = {m["id"]: compile_prompt(plan, m) for m in plan["modules"]}
    (out / "prompts.json").write_text(json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")

    meta = {}
    for name, mode, *rest in IMAGE_MODELS:
        size = rest[0] if rest else ""
        mdir = out / re.sub(r"[^\w.-]", "_", name); mdir.mkdir(exist_ok=True)
        for m in plan["modules"]:
            f = mdir / f"{m['id']}.png"
            if f.exists():
                continue
            t = time.time()
            try:
                fit(gen_image(name, mode, size, prompts[m["id"]], refs), f)
                meta[f"{name}/{m['id']}"] = round(time.time() - t, 1)
                print(f"  ok  {name} {m['id']} {meta[f'{name}/{m['id']}']}s")
            except Exception as e:
                print(f"  FAIL {name} {m['id']}: {e}")
    (out / "timing.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    sheet(out, plan)


def sheet(out, plan):
    """index.html: rows = modules, columns = models, for side-by-side judging."""
    models = [d.name for d in sorted(out.iterdir()) if d.is_dir()]
    rows = ""
    for m in plan["modules"]:
        cells = "".join(f'<td><img src="{d}/{m["id"]}.png" width="420"></td>' for d in models)
        rows += f'<tr><th>{m["id"]} {m["title_cn"]}<br><small>{m["headline"]}</small></th>{cells}</tr>'
    head = "".join(f"<th>{d}</th>" for d in models)
    (out / "index.html").write_text(
        f'<meta charset="utf-8"><body style="font-family:sans-serif"><table border=1 cellpadding=6>'
        f"<tr><th></th>{head}</tr>{rows}</table>", encoding="utf-8")


if __name__ == "__main__":
    root = HERE / "samples"
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for d in sorted(root.iterdir()):
        if d.is_dir() and (not only or d.name == only):
            run_product(d)
