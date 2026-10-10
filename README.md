# 电商 AI 出图工作台

商品图 → AI 规划 → 批量出图 → 三段质检 → 人工放行 的自用工作台。
对标"AI 详情图"类产品，但用你自己的 OpenAI 兼容网关，提示词 / 模型 / 流程全部可配置。

## 功能

- **预设**：`aplus_banner`（1464×600 A+ 横幅，模型出图）、`master_image`（1:1 白底主图，rembg 确定性合成）
- **AI 规划**：多模态 LLM 输出结构化方案（商品锚点 + 设计规范 + 模块），可编辑、版本化
- **批量出图**：多参考图图像编辑模型，提示词分层编译，每张图元数据完整可复现
- **三段质检**：确定性检查（尺寸/白底/占比）→ VLM 商品一致性 → VLM 文字校验；不通过自动重试（问题追加进 AVOID），仍失败标红人工放行
- **单图重出**：改提示词 / 换模型，版本链并排对比
- **视频**：镜头脚本规划 → 已确认图作首帧 → 图生视频长任务
- **成本统计**：按角色 / 项目 / 日期估算成本
- 一切可复现：asset 记录提示词 / 模型 / 参数 / 参考图哈希 / 预设版本

## 部署（Docker，推荐 NAS）

```bash
docker run -d --name aizuotu \
  -p 8000:8000 \
  -e APP_SECRET=换成一串长随机字符 \
  -v ./data:/data \
  ghcr.io/<你的GitHub用户名>/aizuotu:latest
```

或用 compose：

```bash
# 先把 docker-compose.yml 里的 OWNER 换成你的 GitHub 用户名
docker compose up -d
```

打开 `http://<主机>:8000`：

1. **设置页**：填网关 `BASE_URL` 与 API Key（AES 加密落库），配置 角色→模型 映射（planner / qa_vlm / image_main / image_alt / video，含单价、并发），点「测试连接」
2. **新建项目**：上传多角度商品图（首张为主参考）→ 选预设 → 触发 AI 规划
3. **方案页**：检查/编辑方案 → 提示词预览 → 确认生成
4. **结果页**：看图、QA 徽标、人工放行、单图重出、zip 导出、镜头脚本与视频

主图预设需要抠图时，用带 rembg 的镜像（体积更大）：

```bash
docker build --build-arg WITH_REMBG=1 -t aizuotu-rembg .
```

未装 rembg 时主图自动降级为"原图贴白底"，适合本来就是白底的素材。

## 环境变量

| 变量 | 说明 |
|---|---|
| `APP_SECRET` | **必设**。API Key 加密主密钥；不设则用不安全的开发默认值 |
| `APP_PASSWORD` | 可选。设置后网页需输入访问密码 |
| `APP_DATA_DIR` | 数据目录（默认 `/data`），SQLite 与图片都在这里，挂卷持久化 |
| `FRONTEND_DIST` | 前端产物路径（镜像内已配好，本地开发不用管） |

## 本地开发

```bash
# 后端（端口 8000）
cd backend
pip install -r requirements.txt
APP_SECRET=dev python -m uvicorn app.main:app --port 8000

# 前端（端口 5173，已代理到 8000）
cd frontend
npm install
npm run dev

# 测试
cd backend && python -m pytest tests -q
```

## CI

推送到 `main` 或打 `v*` tag 时，GitHub Actions 自动构建镜像并推送 `ghcr.io/<owner>/<repo>:latest`（及版本 tag）。

## 技术栈

FastAPI + SQLite（进程内 worker + SSE）· Vue 3 + Vite + Element Plus（纯 JS）· OpenAI 兼容网关 · Docker 单镜像
