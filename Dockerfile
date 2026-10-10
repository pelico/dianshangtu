# ---- 前端构建 ----
FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 后端运行 ----
FROM python:3.13-slim
ARG WITH_REMBG=0
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
 && if [ "$WITH_REMBG" = "1" ]; then pip install --no-cache-dir "rembg[cpu]"; fi

COPY backend/app ./app
COPY --from=frontend /fe/dist ./dist

ENV APP_DATA_DIR=/data \
    FRONTEND_DIST=/app/dist \
    PYTHONUNBUFFERED=1
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
