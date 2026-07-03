#!/bin/bash
# ============================================================================
# ReimburseAgent — UV 一键启动
# ============================================================================
# 依赖 uv 包管理器，自动处理数据层 + 数据库 + 后端启动。
#
# 用法:
#   bash run-backend.sh          # 完整启动 (数据层 + 迁移 + 后端)
#   bash run-backend.sh --dev    # 开发模式 (DEBUG + 热重载)
#   bash run-backend.sh --data-only  # 仅启动数据层
#
# 等价于:
#   cd backend && uv run reimburse start
# ============================================================================
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/backend"

echo ""
echo "============================================"
echo " ReimburseAgent — UV 一键启动"
echo "============================================"
echo ""

# 确保依赖已安装
uv sync 2>/dev/null || uv sync

case "${1:-start}" in
    --dev|dev)
        uv run reimburse dev
        ;;
    --data-only)
        uv run reimburse data start
        ;;
    start|*)
        uv run reimburse start
        ;;
esac
