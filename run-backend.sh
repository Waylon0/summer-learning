#!/bin/bash
# ReimburseAgent 后端启动脚本
# 用法: bash run-backend.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 1. 确保数据层运行
echo ">>> 检查基础设施..."
bash manage-infra.sh start 2>/dev/null || true

# 2. 确保依赖安装
echo ">>> 检查依赖..."
cd backend
uv sync 2>/dev/null || uv sync
echo ""

# 3. 启动后端
echo ">>> 启动 FastAPI 后端: http://localhost:8000"
echo "    API 文档: http://localhost:8000/docs"
echo "    Health:   http://localhost:8000/health"
echo ""
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
