#!/bin/bash
# ReimburseAgent 本地开发初始化脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================"
echo " ReimburseAgent — 本地开发初始化"
echo "============================================"

# 1. 环境变量
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✅ .env 已创建 (请编辑填入 OPENAI_API_KEY)"
else
    echo "⏭️  .env 已存在"
fi

# 2. 启动基础设施 (PostgreSQL + Redis + MinIO)
echo ""
echo "📦 启动基础设施容器..."
docker compose up -d postgres redis minio 2>/dev/null || {
    echo "⚠️  Docker 不可用，请手动启动 PostgreSQL/Redis/MinIO"
}

# 3. Backend 依赖
echo ""
echo "🐍 安装后端依赖..."
cd backend
uv sync --no-install-project 2>/dev/null || uv sync
echo "✅ 后端依赖就绪"

# 4. 数据库迁移
echo ""
echo "🗄️  初始化数据库..."
uv run alembic upgrade head 2>/dev/null || {
    echo "⚠️  Alembic 迁移失败 (可能已是最新)"
}
uv run python seed_data/seed.py 2>/dev/null || {
    echo "⚠️  种子数据导入失败 (可能已存在)"
}

# 5. 前端依赖
echo ""
echo "📱 安装前端依赖..."
cd ../frontend
npm install 2>/dev/null || {
    echo "⚠️  npm install 失败，请手动执行: cd frontend && npm install"
}
echo "✅ 前端依赖就绪"

echo ""
echo "============================================"
echo " ✅ 初始化完成!"
echo ""
echo "启动后端: cd backend && uv run uvicorn app.main:app --reload"
echo "启动前端: cd frontend && npm run dev"
echo "API 文档: http://localhost:8000/docs"
echo "前端页面: http://localhost:3000"
echo "============================================"
