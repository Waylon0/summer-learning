FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        curl \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv 包管理器
RUN pip install uv --quiet

# 先复制依赖文件（利用 Docker 缓存层）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || uv sync --no-dev

# 复制应用代码
COPY . .

# 创建运行时目录
RUN mkdir -p data/uploads data/chroma logs

# 入口脚本可执行
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/bin/bash", "/app/entrypoint.sh"]
