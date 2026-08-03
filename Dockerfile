# 宝妈指数 (Mom Index) — 容器镜像
# 默认命令启动前端看板；pipeline 通过 docker compose run 单独执行。
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 先复制依赖清单，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 非 root 运行（数据卷 /app/data 归 mom 所有，容器内可写）
RUN useradd --create-home --uid 1000 mom && chown -R mom:mom /app
USER mom

EXPOSE 8765

# 默认从 frontend/ 目录内启动前端看板；数据由 pipeline 同步到共享卷 /app/frontend/data
CMD ["sh", "-c", "cd frontend && python server.py 8765"]
