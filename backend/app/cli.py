"""
===========================================================================
app/cli.py — ReimburseAgent 一键启动命令行工具 (跨平台)
===========================================================================
用法:
  cd backend
  uv run reimburse start           # 启动数据层 + 后端
  uv run reimburse dev             # 开发模式 (DEBUG + hot reload)
  uv run reimburse data start      # 仅启动数据层
  uv run reimburse data stop       # 停止数据层
  uv run reimburse data status     # 查看数据层状态
  uv run reimburse db init         # 初始化数据库 (迁移 + 种子数据)
===========================================================================
"""
import os
import sys
import time
import platform
import shutil
import subprocess
import argparse
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
IS_WINDOWS = platform.system() == "Windows"


def _sh(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """运行命令，自动处理 shell 和 cwd（跨平台兼容）"""
    target_dir = str(cwd or BACKEND_DIR)
    proc = subprocess.run(
        cmd,
        cwd=target_dir,
        capture_output=not sys.stdout.isatty(),
        text=True,
        shell=False if shutil.which(cmd[0]) else True,
    )
    return proc


def _has_docker() -> bool:
    """检测 docker compose 是否可用"""
    try:
        r = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True, text=True,
        )
        return r.returncode == 0
    except (FileNotFoundError, OSError):
        return False


def _has_wsl() -> bool:
    """检测 WSL 是否可用（Windows 下跑 bash 脚本）"""
    try:
        r = subprocess.run(["wsl", "--version"], capture_output=True, text=True)
        return r.returncode == 0
    except (FileNotFoundError, OSError):
        return False


# ============================================================================
# 数据层管理
# ============================================================================
def data_start():
    """启动数据层 (PostgreSQL + Redis + MinIO)"""
    print("📦 启动数据层...")
    if _has_docker():
        print("   使用 Docker Compose...")
        r = _sh(
            ["docker", "compose", "up", "-d", "postgres", "redis", "minio", "minio-init"],
            cwd=PROJECT_DIR,
        )
        if r.returncode != 0:
            print(f"⚠️  Docker 启动失败:\n{r.stderr}")
        else:
            print("   等待健康检查...")
            time.sleep(4)
            _sh(["docker", "compose", "ps", "postgres", "redis", "minio"], cwd=PROJECT_DIR)
    elif IS_WINDOWS and _has_wsl():
        print("   使用 WSL 启动本地服务...")
        _sh(["wsl", "bash", str(PROJECT_DIR / "manage-infra.sh").replace("\\", "/"), "start", "--local"])
    else:
        print("⚠️  未检测到 Docker/WSL，跳过数据层启动")
        print("   (后端将使用 SQLite，不影响基本功能)")


def data_stop():
    """停止数据层"""
    print("🛑 停止数据层...")
    if _has_docker():
        _sh(["docker", "compose", "stop", "postgres", "redis", "minio"], cwd=PROJECT_DIR)
    elif IS_WINDOWS and _has_wsl():
        _sh(["wsl", "bash", str(PROJECT_DIR / "manage-infra.sh").replace("\\", "/"), "stop"])


def data_status():
    """查看数据层状态"""
    if _has_docker():
        _sh(["docker", "compose", "ps", "postgres", "redis", "minio"], cwd=PROJECT_DIR)
    elif IS_WINDOWS and _has_wsl():
        _sh(["wsl", "bash", str(PROJECT_DIR / "manage-infra.sh").replace("\\", "/"), "status"])
    else:
        print("数据层状态: 未运行 (无 Docker/WSL)")
        print("后端使用 SQLite — 可直接启动")


# ============================================================================
# 数据库初始化
# ============================================================================
def db_init():
    """初始化数据库：建表 + 迁移 + 种子数据"""
    print("🗄️  初始化数据库...")

    print("   [1/3] 创建表结构...")
    r = _sh(["uv", "run", "alembic", "upgrade", "head"], cwd=BACKEND_DIR)
    if r.returncode != 0:
        # Alembic 失败则直接 SQLAlchemy create_all
        code = (
            "import asyncio;"
            "from app.core.database import engine, Base;"
            "async def _i():"
            "  async with engine.begin() as c: await c.run_sync(Base.metadata.create_all);"
            "  await engine.dispose();"
            "asyncio.run(_i());"
            "print('   ✅ 表已创建')"
        )
        _sh(["uv", "run", "python", "-c", code], cwd=BACKEND_DIR)

    print("   [2/3] 导入种子数据...")
    _sh(["uv", "run", "python", "seed.py"], cwd=BACKEND_DIR)

    print("   [3/3] ✅ 数据库就绪")


# ============================================================================
# 应用启动
# ============================================================================
def start_backend(reload: bool = True, port: int = 8000, host: str = "0.0.0.0"):
    """启动 FastAPI 后端（前台运行，Ctrl+C 停止）"""
    cmd = ["uv", "run", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]
    if reload:
        cmd.append("--reload")

    print(f"\n🚀 启动 FastAPI: http://{host}:{port}")
    print(f"   API 文档: http://{host}:{port}/docs")
    print(f"   健康检查: http://{host}:{port}/health")
    print("   Ctrl+C 停止\n")

    # 前台运行，让用户能看到日志和 Ctrl+C 退出
    subprocess.run(cmd, cwd=str(BACKEND_DIR))


# ============================================================================
# 命令处理
# ============================================================================
def cmd_start(args):
    data_start()
    db_init()
    start_backend(reload=args.reload, port=args.port, host=args.host)


def cmd_dev(args):
    os.environ["LOG_LEVEL"] = "DEBUG"
    data_start()
    db_init()
    start_backend(reload=True, port=args.port, host=args.host)


def cmd_data(args):
    {"start": data_start, "stop": data_stop, "status": data_status}[args.action]()


def cmd_db(args):
    db_init()


# ============================================================================
# CLI 入口
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        prog="reimburse",
        description="ReimburseAgent 一键启动工具",
    )
    sub = parser.add_subparsers(dest="command", help="可用命令")

    p_start = sub.add_parser("start", help="启动全部服务 (数据层 + 后端)")
    p_start.add_argument("--reload", action="store_true", default=True)
    p_start.add_argument("--no-reload", dest="reload", action="store_false")
    p_start.add_argument("--port", type=int, default=8000)
    p_start.add_argument("--host", default="0.0.0.0")
    p_start.set_defaults(func=cmd_start)

    p_dev = sub.add_parser("dev", help="开发模式 (DEBUG + 热重载)")
    p_dev.add_argument("--port", type=int, default=8000)
    p_dev.add_argument("--host", default="0.0.0.0")
    p_dev.set_defaults(func=cmd_dev)

    p_data = sub.add_parser("data", help="数据层管理")
    p_data.add_argument("action", choices=["start", "stop", "status"])
    p_data.set_defaults(func=cmd_data)

    p_db = sub.add_parser("db", help="数据库管理")
    p_db.add_argument("action", choices=["init"], default="init", nargs="?")
    p_db.set_defaults(func=cmd_db)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\n👋 已停止")
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
