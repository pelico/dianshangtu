# 电商 AI 出图工作台（自用版）— 开发计划书 v2

> 本文档取代旧版《AI 电商营销图片生成系统 — 开发计划书 v1.0》。
> 旧版的"三明治合成（抠图＋背景＋贴字）"不再作为默认路线，原因见 §1.3。

---

## 0. 给开发 Agent 的阅读指引（先读这一节）

**项目意图（一句话）：** 用户是亚马逊运营，要做一个**自用**的"商品图 → AI 规划 → 批量出图"工作台，把"亚马逊主图 / A+ 图 / A+ 视频"这类平时靠人工问 AI 的流程**固化成可复用的软件**。参考对象是一类"AI 详情图"产品（上传商品图 → 生成"整体设计规范＋逐模块方案" → 用户确认 → 批量出横幅图），但要用**用户自己的 API**，并且**提示词、模型、流程全部可配置**。

**这个项目的价值排序（做取舍时按此判断）：**

1. **出图模型能力**：使用支持多张参考图的"图像编辑"类模型，保证商品一致。决定上限。
2. **提示词体系**：规划提示词 → 结构化方案 → 编译成出图提示词，并且分层、可编辑、可版本化。决定稳定性与复用。
3. **规划/质检用的多模态 LLM**：要求不高，能看图并稳定输出 JSON 即可。
4. **质检与局部重生成**：决定"可用率"，是 AI 出图从演示变成工具的关键。

**已定的决策（不要重新讨论）：**

- 所有模型调用**只走 OpenAI 兼容接口**（用户有自己的网关，已具备所需模型的 Key）。不写厂商原生 SDK 适配器，除非 M1 验证证明某能力必须。
- 部署目标是 **Docker（单镜像＋数据卷）**，优先在 NAS 上跑。不做 Windows exe（可在后期用 PyInstaller 补，非目标）。
- 自用、单用户。只需要可选的访问密码，不做多租户、不做注册登录。
- 后端 Python + FastAPI；前端 Vue 3 + Vite + TypeScript + Pinia + Element Plus；数据库 SQLite。
- **不引入 Celery / Redis / PostgreSQL。**
- **首个预设：A+ 横幅图**（默认画布 1464×600，可配置）。主图预设排第二，视频排第三。

**随本文档提供的资产（必须先读）——目录 `poc/`：**

| 文件 | 作用 | 你要怎么用 |
|---|---|---|
| `poc/poc.py` | 第 0 步验证脚本：商品图 → 规划 → 多模型出图 → 对比页 | 把其中的函数**重构进后端服务**（见 §5、§6），行为保持一致。不要重写逻辑。 |
| `poc/prompts/planner.system.md` | 规划提示词＋输出 JSON schema | 作为**内置预设的初始内容**导入数据库，之后以数据库为准。 |
| `poc/prompts/image.template.md` | 出图提示词模板（`{{变量}}`） | 同上。 |
| `poc/.env.example` | 环境变量与 `IMAGE_MODELS` 格式（`name|mode|size`） | 对应系统设置里的"模型清单"。 |

**第 0 步由用户自己执行**（用 `poc.py` 对比 2～3 个出图模型）。结果会决定 §13 中的开放项。**在用户给出 PoC 结果前，M1 可以先开发，但不要把任何一个具体模型名写死。**

**不要做的事：**

- 不要把提示词硬编码在 Python 里（除 §3.1 所列的"固定层"）。
- 不要依赖模型直接写出大量小字；小字/参数类文字走"留白＋后贴字"模式。
- 不要在没有记录"提示词、模型、参数、参考图"的情况下生成图片（必须可复现，见 §6）。
- 不要为了通用性提前做插件系统。扩展靠"预设＋能力配置"。

---

## 1. 目标、非目标与对旧计划的取舍

### 1.1 目标

- 上传商品图（多角度）＋可选卖点说明，选择预设，得到**可编辑的结构化方案**，确认后批量出图。
- 每张图都能：查看/修改最终提示词后重出、保留历史版本、显示质检结果、下载。
- 提示词、模块库、品牌档案、模型分配全部可在界面里调整，且有版本。
- 同一引擎通过不同预设支持：A+ 横幅、亚马逊主图套图、（后期）图生视频。

### 1.2 非目标

多用户、权限、计费、在线支付、平台上架 API 对接、前端 Canvas 在线精修（可在 M6 之后评估）。

### 1.3 对旧计划（v1.0）的取舍

| 旧计划内容 | 处理 | 原因 |
|---|---|---|
| FastAPI + Vue3 + SQLite | **保留** | 合理 |
| Provider 适配层 | **保留，改为按"能力"划分** | 便于换模型 |
| "三明治合成"为默认出图路线 | **取消默认**，仅保留给**白底主图**的确定性模式 | 抠图合成做不到视角变化、手持/交互、光影融合；A+ 场景图需要"参考图→图像编辑" |
| 一律用 Pillow 贴字 | **改为可切换的文字模式** | 短英文标题模型可直出；小字不可靠，需留白后贴字 |
| 规划只有"主题×场景×标语" | **扩展为"整体设计规范＋逐模块方案"** | 需要商品锚点、构图、文字位置等字段才能稳定出图 |
| 提示词写在 `analyzer.py` | **改为数据库中的分层、版本化预设** | 可调、可回滚、可复现 |
| Celery + Redis | **取消** | 自用过度；SQLite 任务表＋进程内 worker 足够 |
| PostgreSQL | **取消** | 同上 |
| WebSocket 推送 | **改为 SSE** | 单向推送足够，实现更简单 |
| 无质检 | **新增质检与自动重试** | 决定可用率 |
| 无工作流抽象 | **新增 Preset 工作流** | 支撑主图/A+/视频复用 |

---

## 2. 设计原则

1. **工作流即配置**：业务差异放在预设里，引擎代码不出现"主图/A+"分支。
2. **一切可复现**：每张产出都存下编译后的提示词、模型、参数、参考图哈希、预设版本。
3. **人在回路**：规划方案可编辑，出图提示词可编辑，质检失败可人工放行。
4. **失败是常态**：所有外部调用有超时、重试、可恢复；任务重启后能继续。
5. **单一依赖路径**：所有模型走 OpenAI 兼容接口；质检里的"看图"和"识别文字"也走 VLM，不引入 OCR 库。

---

## 3. 核心概念

### 3.1 提示词分层（最重要）

| 层 | 内容 | 谁能改 | 存放 |
|---|---|---|---|
| L0 固定层 | 输出 JSON schema 的解析与校验、安全约束、变量编译逻辑 | 不开放 | 代码 |
| L1 预设层 | 规划系统提示词、模块库、出图提示词模板、负面约束、文字模式、质检规则、尺寸 | 可编辑、**版本化**、可复制 | DB |
| L2 档案层 | 品牌/店铺档案：品牌调性、配色、字体偏好、禁用词、logo、固定语言 | 每店铺一份 | DB |
| L3 运行层 | 本次卖点说明、风格选择、方案中每个模块的字段 | 每次运行可改 | DB（随任务） |
| L4 单图层 | **编译后的最终出图提示词** | 重出前可直接改 | DB（随产出） |
| 参数 | 每步使用的模型、尺寸/质量、候选张数、温度 | 全局默认＋单次覆盖 | DB |

### 3.2 对象

- **Preset（预设）**：一个工作流的完整定义，含版本。见 §4。
- **Project（项目）**：一次生成任务，绑定商品图、预设版本、档案、用户输入。
- **Plan（方案）**：规划步骤输出的 JSON（`product` / `design_spec` / `modules[]`），**schema 以 `poc/prompts/planner.system.md` 为准**，可编辑、有修订历史。
- **Job（任务）**：一次可恢复的异步单元（规划 / 出图 / 质检 / 视频）。
- **Asset（产出）**：图片或视频及其全部生成元数据。

### 3.3 变量表（出图模板可用）

`product_anchor` `scene` `product_pose` `photo_goal` `visual_description` `composition` `text_side` `style` `palette` `lighting` `text_block` — 与 `poc.py` 的 `compile_prompt` 一致。
新增变量时同步更新：编译函数、预设编辑器的变量提示、本表。档案层追加：`brand_tone` `forbidden_words` `brand_colors`。

---

## 4. 预设（Preset）定义

以 YAML/JSON 存库，字段如下（示例为 A+ 横幅）：

```yaml
id: aplus_banner
name: 亚马逊 A+ 横幅
version: 1            # 每次保存自增，旧版本只读保留
inputs:
  required: [product_images]
  optional: [brief, brand_profile_id, copy_language]
canvas: {width: 1464, height: 600}          # 可在运行时覆盖
planner:
  model_ref: planner                         # 指向系统设置里的"角色→模型"
  system_prompt: "<planner.system.md 内容>"
  module_count: {default: 5, min: 1, max: 12}
module_library:                               # 规划器可选的模块角色
  - {role: hero, hint: "品牌/主视觉"}
  - {role: feature, hint: "核心功能"}
  - {role: fit, hint: "适配/防护"}
  - {role: scene, hint: "使用场景"}
  - {role: lifestyle, hint: "生活方式/桌面"}
image:
  model_ref: image_main
  mode: edits                                 # edits | chat | generations
  gen_size: "1536x1024"                       # 模型原生尺寸
  fit: center_crop                            # 然后缩放到 canvas
  candidates: 1
  template: "<image.template.md 内容>"
  negative: "distorted product, extra logos, watermark, garbled text"
text:
  mode: model                                 # model | blank_then_overlay
qa:
  rules: [size, product_consistency, text_match, no_extra_logo]
  max_auto_retries: 2
```

**预设管理要求：** 新建/复制/编辑/保存新版本/回滚；编辑页提供"用样例商品试跑一张"。

**预设清单与阶段：**

| 预设 | 路线 | 阶段 |
|---|---|---|
| `aplus_banner` | 参考图→图像编辑，文字模式可选 | M1–M3 |
| `main_image_set` | 主图：**确定性模式**（抠图→白底画布→校验）；副图：信息图/场景图（同 A+ 引擎） | M5 |
| `aplus_video` / `main_video` | 规划出镜头脚本→已确认图片作首帧→图生视频（长任务轮询） | M6 |

主图的平台规则（纯白背景、产品占比、无文字/水印、最小边长等）**以亚马逊后台当前规则为准**，写成预设里的可配置阈值，不要写死在代码里。

---

## 5. 流水线与服务

```
上传 → [规划 Job] → Plan(JSON) → 用户编辑/确认
      → 对每个 module: 编译提示词 → [出图 Job] → fit(裁剪/缩放) → [质检 Job]
      → 通过: 入库 / 不通过: 自动重试(≤N) → 仍失败: 标红待人工
```

**服务拆分（Python）：**

- `providers/openai_compat.py`：封装 `chat_completions`、`images_edits`、`images_generations`、`chat_image`（从聊天响应中提取图片：`data[].b64_json|url`、`message.images[]`、内容中的 data URL / 图片链接）。**直接复用 `poc.py` 的 `post` / `extract_image` / `gen_image`。**
- `services/planner.py`：调用规划模型，JSON 解析（去围栏、失败重试一次并带错误信息）、schema 校验。
- `services/compiler.py`：`compile_prompt`（=`poc.py`），支持档案变量与单图覆盖。
- `services/imaging.py`：`fit`（居中裁剪＋缩放，同时保存 `_raw`）；后期加白底校验、叠字（Pillow）。
- `services/qa.py`：见 §7。
- `services/jobs.py`：任务队列与 worker，见 §6。
- `services/cost.py`：成本统计。

**Provider 配置（系统设置）：**

- 连接：`base_url`、`api_key`（加密存储，主密钥来自环境变量 `APP_SECRET`）。
- **角色→模型映射**：`planner`、`qa_vlm`、`image_main`、`image_alt`、`video`（后期）。每个映射含 `model`、`mode`（edits/chat/generations）、`size`、超时、并发上限、单价（用于成本估算）。
- "测试连接"按钮：对每个角色发一次最小请求并显示结果与耗时。

---

## 6. 数据模型与任务系统（SQLite）

```
preset(id, name, kind, created_at)
preset_version(id, preset_id, version, body_json, created_at)
brand_profile(id, name, body_json)
project(id, name, preset_version_id, brand_profile_id, brief, params_json, status, created_at)
project_ref(id, project_id, path, sha256, order_no)             -- 商品参考图
plan(id, project_id, revision, body_json, source)               -- source: ai | user_edit
job(id, project_id, kind, target_id, status, attempt, error, payload_json,
    created_at, started_at, finished_at)                        -- status: queued|running|done|failed|canceled
asset(id, project_id, module_id, kind, path, raw_path, width, height,
      model, mode, params_json, prompt_text, prompt_edited, ref_hashes_json,
      preset_version_id, plan_revision, parent_asset_id, attempt,
      qa_status, qa_json, tokens_json, cost_estimate, elapsed_s, created_at)
setting(key, value_json)                                         -- 敏感值加密
```

**任务系统要求：**

- 进程内 worker 池；每个"角色→模型"有独立并发上限（默认 2）。
- 启动时把 `running` 的任务重置为 `queued`（可恢复）。
- 外部调用：超时 300s，失败重试 1 次（指数退避），记录原始错误文本。
- 进度通过 **SSE**（`/api/projects/{id}/events`）推送：任务状态变化、产出入库、质检结果。
- 取消：`queued` 立即取消；`running` 标记取消、结果丢弃。

**可复现性：** 每个 `asset` 必须存下上表中的 `prompt_text`、`model`、`mode`、`params_json`、`ref_hashes_json`、`preset_version_id`、`plan_revision`。"重新生成"产生**新 asset**（`parent_asset_id` 指向旧的），不覆盖。

---

## 7. 质检（QA）

三段，按预设里的 `qa.rules` 启用：

1. **确定性检查（无模型）**：成品尺寸与格式；（主图）背景像素是否纯白、产品包围盒占比、最小边长。
2. **商品一致性（VLM）**：把"参考图＋成品图"交给 `qa_vlm`，要求输出 JSON：
   `{"score": 1-5, "color_ok": bool, "shape_ok": bool, "logo_ok": bool, "details_ok": bool, "issues": ["..."]}`；`score ≥ 阈值（默认 4）` 且各项为真才通过。
3. **文字校验（VLM）**：让 `qa_vlm` 读出图中所有可见文字，与方案里的 `headline/subline` 比对（忽略大小写与标点）；出现方案外的文字或拼写不一致即不通过。`blank_then_overlay` 模式下要求"图中无文字"。

**自动重试：** 不通过时，把 `issues` 追加到出图提示词的 AVOID 段后重出，最多 `max_auto_retries` 次；每次尝试都保留为独立 asset。仍失败 → `qa_status=needs_review`，界面标红，允许用户"人工放行"。

**说明：** 质检阈值与提示词同样放在预设里可调；质检本身有误判，所以必须允许人工覆盖，并把人工覆盖结果记录下来（后续用于调阈值）。

---

## 8. 后端 API（REST + SSE）

```
POST   /api/projects                         创建（multipart: 参考图、brief、preset_id、brand_profile_id、params）
GET    /api/projects / GET /api/projects/{id}
POST   /api/projects/{id}/plan               触发规划（可带"重新规划"）
GET    /api/projects/{id}/plan               获取最新方案
PUT    /api/projects/{id}/plan               保存用户编辑（生成新 revision）
GET    /api/projects/{id}/prompts            返回每个 module 编译后的提示词（预览）
POST   /api/projects/{id}/generate           {module_ids?, overrides?: {module_id: prompt_text}}
POST   /api/assets/{id}/regenerate           {prompt_text?, model_ref?, params?}
POST   /api/assets/{id}/approve              人工放行
GET    /api/assets?project_id=               列表（含质检与元数据）
GET    /api/assets/{id}/download             原成品；?raw=1 下载未裁剪原图
GET    /api/projects/{id}/export.zip         批量下载（按模块命名）
GET    /api/projects/{id}/events             SSE
CRUD   /api/presets, /api/presets/{id}/versions, /api/brand-profiles
GET/PUT /api/settings ；POST /api/settings/test
GET    /api/stats/cost?from=&to=             成本汇总
```

---

## 9. 前端页面（Vue 3）

1. **新建**：上传（拖拽、多图、排序，第一张为主参考）、卖点说明、选预设/档案、语言、尺寸、模块数、"AI 规划"。
2. **方案**：左侧"整体设计规范"（可改）；模块列表（卡片，可增删、排序、改字段，字段与 schema 对应）；每个模块有"查看/编辑编译后提示词"抽屉；确认后"生成 N 张"。
3. **结果**：按模块分组的画廊；每张显示质检徽标、模型、耗时、版本；操作：放大、改提示词重出、换模型重出、放行、下载；顶部"批量下载 zip"。版本对比（同一模块多次产出并排）。
4. **预设**：列表、编辑器（分栏：提示词、模块库、尺寸、文字模式、质检）、版本历史与回滚、"试跑一张"。
5. **品牌档案**。
6. **设置**：连接、角色→模型映射、测试连接、并发、单价。
7. **历史与成本**。

界面中文；方案中的 `copy_language`（成品图文案语言）默认英语，可选。

---

## 10. 部署（Docker）

- **单镜像**：构建阶段先编译前端静态文件，运行阶段由 FastAPI 托管（端口 8000）。
- **数据卷**：`/data`（SQLite、`uploads/`、`outputs/`）。
- **环境变量**：`APP_SECRET`（必填，用于加密 Key）、`APP_PASSWORD`（可选，设置后启用 HTTP Basic 或简单登录）、`TZ`、`PORT`。
- **`docker-compose.yml`** 一个服务、一个卷即可；NAS 上反代时注意 SSE 需要关闭响应缓冲。
- **可选依赖**：`rembg`（仅主图确定性模式需要）通过构建参数 `WITH_REMBG=1` 安装，默认不装，保持镜像小。
- 日志写 stdout；`/healthz` 健康检查。

---

## 11. 目录结构

```
app/
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ api/                # 路由
│  │  ├─ core/               # 配置、加密、SSE
│  │  ├─ db/                 # SQLite 与迁移
│  │  ├─ providers/openai_compat.py
│  │  ├─ services/{planner,compiler,imaging,qa,jobs,cost}.py
│  │  └─ presets/            # 内置预设初始内容（含 poc/prompts 的内容）
│  ├─ tests/
│  └─ requirements.txt
├─ frontend/                 # Vue3 + Vite + TS
├─ poc/                      # 原样保留，作为参考与回归用例
├─ data/                     # 运行时（挂载卷）
├─ Dockerfile
├─ docker-compose.yml
└─ .env.example
```

---

## 12. 里程碑与验收标准

| 阶段 | 内容 | 验收 |
|---|---|---|
| **M0（用户执行）** | 运行 `poc/poc.py`，对比 2～3 个出图模型，给出结论 | 用户提供对比结果与选型 |
| **M1 骨架与链路** | 脚手架、SQLite、设置页＋测试连接、Provider 封装、上传、规划（调用 planner）、方案展示 | 上传一款商品，得到与 `poc` 同结构的 Plan，页面可查看；"测试连接"对各角色通过 |
| **M2 出图与画廊** | 编译提示词、出图 Job、fit、SSE 进度、画廊、单张下载 | 5 个模块出图成功；刷新页面或重启容器后任务可继续；每张图元数据完整 |
| **M3 可调化** | 方案编辑、提示词预览与单图编辑重出、预设管理（版本/回滚/试跑）、品牌档案、换模型重出 | 修改任一提示词后重出产生新版本且可对比；回滚预设版本后结果可复现 |
| **M4 质检** | 三段质检、自动重试、人工放行、zip 导出、成本统计 | 构造一个"商品变色"的坏样例，系统能判为不通过并自动重试；成本页数字与记录一致 |
| **M5 主图预设** | 确定性模式（抠图→白底→校验）、副图复用引擎 | 一款商品生成一套主图＋副图；白底校验能识别不合格图 |
| **M6 视频预设** | `video` 角色、镜头脚本规划、图生视频长任务、轮询与下载 | 用已确认的图生成一条视频并入库 |

**单元/集成测试要求：** `compile_prompt`、`extract_image`（用多种响应样例）、`fit`、JSON 解析容错、任务恢复、质检解析，必须有测试；对外部模型调用使用录制的假响应。

---

## 13. 开放项（等 M0 结果或用户确认）

1. 出图主力模型与备选模型，及各自的 `mode / size`（edits 还是 chat；是否支持接近 1464×600 的原生尺寸）。
2. 文字模式默认值：`model` 直出还是 `blank_then_overlay`，取决于 M0 对标题与小字错误率的观察。
3. 质检 VLM 用哪个模型，以及一致性阈值。
4. 视频用哪个模型，及其在网关上的接口形态（异步提交＋轮询 vs 同步）。
5. 品牌档案需要保存哪些固定字段（由用户在 M3 前补充）。

---

## 14. 风险与对策

| 风险 | 对策 |
|---|---|
| 网关对不同模型的图像端点/字段不一致 | 能力在"角色→模型映射"中按模型配置 `mode`；`openai_compat.py` 单点处理差异；M1 先做"测试连接" |
| 商品细节（logo、拉链、接口）被改动 | 商品锚点写入每个提示词；质检一致性＋自动重试；允许多角度参考图 |
| 模型原生尺寸与 A+ 横幅比例不符，裁切丢内容 | 提示词要求关键内容在中间横带；保存 `_raw`；M0 观察各模型表现；支持原生宽图的模型优先 |
| 成品图出现错字或多余文字 | 文字模式可切换；VLM 文字校验；小字一律后贴 |
| 规划产生不实卖点（合规风险） | 规划提示词硬规则只允许来源于 brief 或图中可见内容；档案里的禁用词在编译前过滤；方案需用户确认 |
| 成本失控 | 默认候选 1；预览低质量/成品高质量分档（预设参数）；成本页与每任务估算 |
| 提示词调优耗时超预期 | M0 与 M3 专门留出；预设版本化支持快速试错 |
| 长任务（视频）超时 | 任务模型一开始就按"提交→轮询→入库"设计 |
