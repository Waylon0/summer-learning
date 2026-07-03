#!/bin/bash
# ============================================================================
# ReimburseAgent — 一键本地开发初始化
# ============================================================================
# 用法:
#   bash init.sh              # 完整初始化 + 启动所有服务
#   bash init.sh --data-only  # 仅初始化数据层 (postgres+redis+minio)
#   bash init.sh --app-only   # 仅启动应用层 (backend+frontend)
# ============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-full}"

# ---- 颜色输出 ----
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
step()  { echo -e "${CYAN}[STEP]${NC}  $1"; }

# ---- 检查依赖 ----
check_dependency() {
    command -v "$1" >/dev/null 2>&1 || {
        warn "$1 未安装，请先安装"
        return 1
    }
}

# ============================================================================
# 步骤 1: 环境变量
# ============================================================================
setup_env() {
    step "检查环境变量..."
    if [ ! -f ".env" ]; then
        cp .env.example .env
        info ".env 已创建 — 请编辑填入 OPENAI_API_KEY"
    else
        info ".env 已存在"
    fi

    # 确保 backend 有 .env（从根 .env 继承）
    if [ ! -f "backend/.env" ]; then
        cp .env backend/.env
        info "backend/.env 已创建"
    fi
}

# ============================================================================
# 步骤 2: 启动数据层 (PostgreSQL + Redis + MinIO)
# ============================================================================
start_data_layer() {
    step "检查 Docker..."
    if ! check_dependency docker; then
        warn "Docker 不可用，尝试使用本地二进制..."
        # 尝试用 manage-infra.sh 启动本地服务
        if [ -f "manage-infra.sh" ]; then
            bash manage-infra.sh start
        fi
        return
    fi

    step "启动数据层容器 (postgres + redis + minio)..."
    docker compose up -d postgres redis minio minio-init

    step "等待数据层就绪..."
    for i in $(seq 1 15); do
        if docker compose ps | grep -q "healthy"; then
            info "数据层已就绪"
            break
        fi
        echo -n "."
        sleep 2
    done
    echo ""

    # 显示状态
    docker compose ps postgres redis minio 2>/dev/null | tail -n +2
}

# ============================================================================
# 步骤 3: 后端依赖 + 迁移 + 种子
# ============================================================================
setup_backend() {
    step "安装后端依赖..."
    cd backend

    if ! check_dependency uv; then
        warn "uv 未安装，尝试用 pip install uv"
        pip install uv 2>/dev/null || {
            warn "请手动安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
            cd ..
            return 1
        }
    fi

    uv sync 2>/dev/null || uv sync
    info "后端依赖就绪"

    step "初始化数据库..."
    uv run alembic upgrade head 2>/dev/null || {
        warn "Alembic 迁移失败，直接建表..."
        uv run python -c "
import asyncio
from app.core.database import engine, Base
async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
asyncio.run(init())
"
    }
    info "数据库表结构就绪"

    step "导入种子数据..."
    uv run python seed.py 2>/dev/null || {
        uv run python seed_data/seed.py 2>/dev/null || warn "种子数据可能已存在"
    }
    info "种子数据就绪"

    cd ..
}

# ============================================================================
# 步骤 4: 前端依赖
# ============================================================================
setup_frontend() {
    step "安装前端依赖..."
    cd frontend
    npm install 2>/dev/null || {
        warn "npm install 失败，请手动执行"
        cd ..
        return 1
    }
    info "前端依赖就绪"
    cd ..
}

# ============================================================================
# 步骤 5: 启动应用层
# ============================================================================
start_application() {
    step "启动应用层..."

    # 后端
    info "启动后端 (http://localhost:8000)..."
    cd backend
    nohup uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload \
        > ../logs/backend.log 2>&1 &
    BACKEND_PID=$!
    echo $BACKEND_PID > ../logs/backend.pid
    info "后端 PID: $BACKEND_PID (日志: logs/backend.log)"
    cd ..

    sleep 2

    # 前端
    info "启动前端 (http://localhost:3000)..."
    cd frontend
    nohup npm run dev -- --host 0.0.0.0 > ../logs/frontend.log 2>&1 &
    FRONTEND_PID=$!
    echo $FRONTEND_PID > ../logs/frontend.pid
    info "前端 PID: $FRONTEND_PID (日志: logs/frontend.log)"
    cd ..
}

# ============================================================================
# 入口
# ============================================================================
echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${CYAN} ReimburseAgent — 本地开发环境${NC}"
echo -e "${CYAN}============================================${NC}"
echo ""

mkdir -p logs

case "$MODE" in
    --data-only)
        setup_env
        start_data_layer
        ;;
    --app-only)
        setup_backend
        setup_frontend
        start_application
        ;;
    full|*)
        setup_env
        start_data_layer
        setup_backend
        setup_frontend
        start_application
        ;;
esac

echo ""
echo -e "${CYAN}============================================${NC}"
echo -e "${GREEN} ✅ 启动完成!${NC}"
echo ""
echo -e "  后端 API:  ${CYAN}http://localhost:8000${NC}"
echo -e "  Swagger:   ${CYAN}http://localhost:8000/docs${NC}"
echo -e "  健康检查:  ${CYAN}http://localhost:8000/health${NC}"
echo -e "  前端页面:  ${CYAN}http://localhost:3000${NC}"
echo -e "  MinIO:     ${CYAN}http://localhost:9001${NC} (minioadmin / minioadmin123)"
echo ""
echo -e "  停止服务:  ${YELLOW}pkill -f uvicorn; pkill -f 'vite'${NC}"
echo -e "${CYAN}============================================${NC}"
