#!/bin/bash
# ReimburseAgent 数据层管理脚本
# 优先使用 Docker Compose，无 Docker 时回退到本地二进制
# 用法: bash manage-infra.sh {start|stop|restart|status} [--docker|--local]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$SCRIPT_DIR/infra"
PID_DIR="$INFRA_DIR/pids"
mkdir -p "$PID_DIR" "$INFRA_DIR/redis/data" "$INFRA_DIR/minio/data"

# 检测运行模式
MODE="auto"
case "${2:-auto}" in
    --docker) MODE="docker" ;;
    --local)  MODE="local" ;;
    *)        MODE="auto" ;;
esac

use_docker() {
    if [ "$MODE" = "local" ]; then return 1; fi
    if [ "$MODE" = "docker" ]; then return 0; fi
    command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1
}

start_redis() {
    if [ -f "$PID_DIR/redis.pid" ] && kill -0 $(cat "$PID_DIR/redis.pid") 2>/dev/null; then
        echo "Redis already running (PID $(cat $PID_DIR/redis.pid))"
        return
    fi
    echo -n "Starting Redis... "
    "$INFRA_DIR/redis/redis-server" --daemonize yes --port 6379 \
        --dir /tmp \
        --pidfile "$PID_DIR/redis.pid" \
        --logfile /tmp/redis.log 2>/dev/null
    sleep 1
    if "$INFRA_DIR/redis/redis-cli" -p 6379 ping >/dev/null 2>&1; then
        echo "OK (port 6379)"
    else
        echo "FAILED"
    fi
}

start_minio() {
    if pgrep -f "minio server" >/dev/null 2>&1; then
        echo "MinIO already running"
        return
    fi
    echo -n "Starting MinIO... "
    MINIO_ROOT_USER=minioadmin MINIO_ROOT_PASSWORD=minioadmin123 \
        nohup "$INFRA_DIR/minio/minio" server "$INFRA_DIR/minio/data" \
        --console-address ":9001" --address ":9000" > /tmp/minio.log 2>&1 &
    echo $! > "$PID_DIR/minio.pid"
    sleep 2
    echo "OK (API:9000 Console:9001)"
}

stop_redis() {
    if [ -f "$PID_DIR/redis.pid" ]; then
        PID=$(cat "$PID_DIR/redis.pid")
        "$INFRA_DIR/redis/redis-cli" -p 6379 shutdown 2>/dev/null || kill $PID 2>/dev/null
        rm -f "$PID_DIR/redis.pid"
        echo "Redis stopped"
    fi
}

stop_minio() {
    if [ -f "$PID_DIR/minio.pid" ]; then
        kill $(cat "$PID_DIR/minio.pid") 2>/dev/null
        rm -f "$PID_DIR/minio.pid"
        echo "MinIO stopped"
    else
        pkill -f "minio server" 2>/dev/null && echo "MinIO stopped"
    fi
}

status() {
    echo "=== Infrastructure Status ==="
    if [ -f "$PID_DIR/redis.pid" ] && kill -0 $(cat "$PID_DIR/redis.pid") 2>/dev/null; then
        echo "Redis:   RUNNING (port 6379, local)"
    elif command -v docker >/dev/null 2>&1 && docker compose ps redis 2>/dev/null | grep -q healthy; then
        echo "Redis:   RUNNING (port 6379, Docker)"
    else
        echo "Redis:   STOPPED"
    fi
    if pgrep -f "minio server" >/dev/null 2>&1; then
        echo "MinIO:   RUNNING (API:9000 Console:9001, local)"
    elif command -v docker >/dev/null 2>&1 && docker compose ps minio 2>/dev/null | grep -q running; then
        echo "MinIO:   RUNNING (API:9000 Console:9001, Docker)"
    else
        echo "MinIO:   STOPPED"
    fi
    echo "DB:      SQLite (backend/data/reimburse.db) or PostgreSQL via Docker"
    echo "  Docker 数据层: ${SCRIPT_DIR}/docker compose up -d postgres redis minio"
}

case "${1:-status}" in
    start)
        if use_docker; then
            echo ">>> 使用 Docker Compose 启动数据层..."
            cd "$SCRIPT_DIR" && docker compose up -d postgres redis minio minio-init
            echo ">>> 等待健康检查..."
            sleep 3
            docker compose ps postgres redis minio
        else
            echo ">>> 使用本地二进制启动..."
            start_redis
            start_minio
        fi
        ;;
    stop)
        if use_docker; then
            cd "$SCRIPT_DIR" && docker compose stop postgres redis minio
        else
            stop_redis
            stop_minio
        fi
        ;;
    restart)
        if use_docker; then
            cd "$SCRIPT_DIR" && docker compose restart postgres redis minio
        else
            stop_redis; stop_minio
            sleep 1
            start_redis; start_minio
        fi
        ;;
    status) status ;;
    *)
        echo "Usage: $0 {start|stop|restart|status} [--docker|--local]"
        exit 1
        ;;
esac
