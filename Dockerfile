# syntax=docker/dockerfile:1

# ---------- 前端构建（纯标准库打包，无需联网装 npm 包） ----------
FROM python:3.11-slim AS webbuild
WORKDIR /build
COPY web ./web
COPY scripts ./scripts
RUN python scripts/build_web.py

# ---------- 业务 API ----------
FROM python:3.11-slim AS api
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
EXPOSE 8000
HEALTHCHECK --interval=5s --timeout=3s --start-period=8s --retries=12 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status==200 else 1)"
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]

# ---------- 前端站点 ----------
FROM nginx:1.27-alpine AS web
RUN rm -f /etc/nginx/conf.d/default.conf
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY --from=webbuild /build/web/dist /app/web/dist
EXPOSE 8080
HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=12 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1

# ---------- 一次性验证服务（代码测试 + 前端构建 + 接口烟测） ----------
FROM python:3.11-slim AS verify
WORKDIR /workspace
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY . .
CMD ["bash", "-lc", "python -m pytest && python scripts/build_web.py && python scripts/smoke.py"]
