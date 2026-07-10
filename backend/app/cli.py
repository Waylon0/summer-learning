"""
===========================================================================
app/cli.py — ReimburseAgent 一键启动命令行工具 (跨平台)
===========================================================================
用法:
  cd backend
  uv run reimburse start           # 启动数据层 + 后端
  uv run reimburse dev             # 开发模式 (DEBUG + hot reload)
  uv run reimburse stop            # 停止后端 (若报 os error 32：改用 stop.bat 或 uv run --no-sync reimburse stop)
  uv run reimburse data start      # 仅启动数据层
  uv run reimburse data stop       # 停止数据层
  uv run reimburse data status     # 查看数据层状态
  uv run reimburse db init         # 初始化数据库 (迁移 + 种子数据)
  uv run reimburse kb rebuild      # 重建 RAG 知识库向量索引
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

# Windows 控制台默认 GBK 编码，print emoji（🚀✅📦 等）会抛 UnicodeEncodeError。
# 在最早时机把标准输出/错误重配为 UTF-8，保证 CLI 与后续日志正常打印。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
IS_WINDOWS = platform.system() == "Windows"


def _sh(cmd: list[str], cwd: Path | None = None, *, check: bool = False) -> subprocess.CompletedProcess:
    """运行命令，跨平台兼容。check=True 时失败抛异常"""
    target_dir = str(cwd or BACKEND_DIR)
    use_shell = IS_WINDOWS  # Windows 上 docker/npm 等需要 shell
    proc = subprocess.run(
        cmd,
        cwd=target_dir,
        capture_output=True,
        text=True, encoding="utf-8", errors="ignore",
        shell=use_shell,
    )
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, proc.stdout, proc.stderr)
    return proc


def _docker_engine_ok() -> bool:
    """检测 Docker 引擎是否在运行（不只是 CLI 安装了）"""
    try:
        r = subprocess.run(
            ["docker", "ps"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            shell=IS_WINDOWS,
        )
        return r.returncode == 0
    except (FileNotFoundError, OSError):
        return False


def _has_wsl() -> bool:
    """检测 WSL 是否可用"""
    try:
        r = subprocess.run(["wsl", "--version"], capture_output=True, text=True, shell=IS_WINDOWS)
        return r.returncode == 0
    except (FileNotFoundError, OSError):
        return False


# ============================================================================
# 数据层管理
# ============================================================================
def data_start():
    """启动数据层 (PostgreSQL + Redis + MinIO)"""
    print("📦 启动数据层...")

    if not _docker_engine_ok():
        print("❌ Docker 引擎未运行！")
        print("   请先打开 Docker Desktop 桌面应用，等待鲸鱼图标变绿")
        print("   然后重新运行: uv run reimburse start")
        print("")
        print("   如果你不需要数据层，可以直接启动后端:")
        print("     uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload")
        sys.exit(1)

    print("   Docker 引擎已就绪，启动容器...")
    r = _sh(
        ["docker", "compose", "up", "-d", "postgres", "redis", "minio", "minio-init"],
        cwd=PROJECT_DIR,
    )
    if r.returncode != 0:
        print(f"❌ Docker Compose 启动失败:")
        print(f"   {r.stderr or r.stdout}")
        print("   请检查 Docker Desktop 是否正常运行，或手动执行:")
        print(f"     cd {PROJECT_DIR}")
        print("     docker compose up -d postgres redis minio minio-init")
        sys.exit(1)

    print("   等待健康检查...")
    time.sleep(4)
    _sh(["docker", "compose", "ps", "postgres", "redis", "minio"], cwd=PROJECT_DIR)


def data_stop():
    """停止数据层"""
    print("🛑 停止数据层...")
    if _docker_engine_ok():
        _sh(["docker", "compose", "stop", "postgres", "redis", "minio"], cwd=PROJECT_DIR)
    else:
        print("   Docker 引擎未运行，无需停止")


def data_status():
    """查看数据层状态"""
    if _docker_engine_ok():
        _sh(["docker", "compose", "ps", "postgres", "redis", "minio"], cwd=PROJECT_DIR)
    else:
        print("数据层状态: Docker 引擎未运行")


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
            "import asyncio\n"
            "from app.core.database import engine, Base\n"
            "async def _i():\n"
            "  async with engine.begin() as c:\n"
            "    await c.run_sync(Base.metadata.create_all)\n"
            "  await engine.dispose()\n"
            "asyncio.run(_i())\n"
            "print('   ✅ 表已创建')"
        )
        _sh(["uv", "run", "python", "-c", code], cwd=BACKEND_DIR)

    print("   [2/3] 导入种子数据...")
    r2 = _sh(["uv", "run", "python", "seed.py"], cwd=BACKEND_DIR)
    if r2.returncode != 0:
        err = (r2.stderr or "") + (r2.stdout or "")
        # 区分"依赖缺失"与"数据库未就绪"两类常见失败，避免误导排查方向
        if "ModuleNotFoundError" in err or "No module named" in err:
            print("   ❌ 种子数据导入失败 — 依赖未安装齐全（并非数据库问题）")
            print("      虚拟环境与 uv.lock 不同步，请先执行：  uv sync")
            print("      若仍缺失，可直接安装：              uv pip install python-dotenv")
        else:
            print("   ⚠️  种子数据导入失败 — 数据库可能未就绪")
        print(f"   详情: {err[-400:] if err else '(无错误详情)'}")

    print("   [3/3] ✅ 数据库初始化完成")


# ============================================================================
# 应用启动
# ============================================================================
def start_backend(reload: bool = True, port: int = 8000, host: str = "0.0.0.0"):
    """
    启动 FastAPI 后端（前台运行，Ctrl+C 停止）。

    关键：直接在【当前进程】内调用 uvicorn.run，而不是再 subprocess 一层
    `uv run uvicorn`。原因：
      1. 少一层嵌套子进程 → 终端日志由 uvicorn 直接继承标准输出，实时可见。
      2. Ctrl+C(SIGINT) 直接送达 uvicorn，由其原生信号处理器优雅停止，
         不会像多层 `uv run + subprocess` 那样吞掉信号导致退不出。
    """
    import uvicorn

    # 确保工作目录 + import 路径为 backend/（供 app.main 导入与 --reload 监听）
    os.chdir(str(BACKEND_DIR))
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    print(f"\n🚀 启动 FastAPI: http://{host}:{port}")
    print(f"   API 文档: http://{host}:{port}/docs")
    print(f"   健康检查: http://{host}:{port}/health")
    print("   Ctrl+C 停止\n")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=[str(BACKEND_DIR)] if reload else None,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
        access_log=True,
    )


# ============================================================================
# 停止后端（供 Ctrl+C 收不掉时，在新终端执行 `uv run reimburse stop`）
# ============================================================================
def _pids_on_port(port: int) -> set[str]:
    """返回监听指定端口的进程 PID（跨平台，不依赖第三方库）。"""
    pids: set[str] = set()
    try:
        if IS_WINDOWS:
            r = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, encoding="utf-8", errors="ignore", shell=True,
            )
            for line in r.stdout.splitlines():
                if f":{port} " in line and "LISTENING" in line.upper():
                    pid = line.split()[-1].strip()
                    if pid.isdigit():
                        pids.add(pid)
        else:
            r = subprocess.run(
                ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                capture_output=True, text=True,
            )
            pids.update(x.strip() for x in r.stdout.splitlines() if x.strip().isdigit())
    except Exception:
        pass
    return pids


def _pids_by_cmdline(port: int) -> set[str]:
    """按命令行匹配后端进程（reimburse start/dev 或 uvicorn app.main:app）。

    只匹配 start/dev 与 app.main:app，故【不会】匹配到本 `reimburse stop` 自身。
    """
    pids: set[str] = set()
    try:
        if IS_WINDOWS:
            ps = (
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                "Where-Object { $_.CommandLine -match 'reimburse.*(start|dev)' "
                "-or $_.CommandLine -match 'app\\.main:app' } | "
                "Select-Object -ExpandProperty ProcessId"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True, text=True, encoding="utf-8", errors="ignore", shell=True,
            )
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.isdigit():
                    pids.add(line)
        else:
            for pattern in ("reimburse start", "reimburse dev", "app.main:app"):
                r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
                pids.update(x.strip() for x in r.stdout.splitlines() if x.strip().isdigit())
    except Exception:
        pass
    return pids


def _kill_tree(pid: str) -> None:
    """结束指定 PID 及其整棵子进程树（Windows: taskkill /T /F）。"""
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                           capture_output=True, text=True, shell=True)
        else:
            subprocess.run(["pkill", "-TERM", "-P", pid], capture_output=True, text=True)
            subprocess.run(["kill", "-9", pid], capture_output=True, text=True)
    except Exception:
        pass


def stop_backend(port: int = 8000):
    """强制停止后端服务（不影响热重载运行逻辑，仅用于兜底停止）。

    综合"端口监听 + 命令行匹配"两种方式定位进程，再整棵树 /F 结束，
    最后校验端口是否释放；必要时二次清理，力求"百分百"停掉。
    """
    print(f"🛑 正在停止后端 (port={port})...")
    self_pid = str(os.getpid())

    targets = _pids_on_port(port) | _pids_by_cmdline(port)
    targets.discard(self_pid)  # 绝不杀自己

    if not targets:
        print("   未发现正在运行的后端进程（端口空闲）。")
        return

    for pid in sorted(targets, key=lambda x: int(x)):
        _kill_tree(pid)
        print(f"   已结束进程树 PID={pid}")

    # 校验 + 二次兜底清理
    time.sleep(1.5)
    remaining = _pids_on_port(port)
    remaining.discard(self_pid)
    if remaining:
        for pid in sorted(remaining, key=lambda x: int(x)):
            _kill_tree(pid)
        time.sleep(1.0)
        remaining = _pids_on_port(port)
        remaining.discard(self_pid)

    if remaining:
        print(f"   ⚠️  端口 {port} 仍被占用: {sorted(remaining)}，请稍后重试或手动结束。")
    else:
        print(f"   ✅ 后端已停止，端口 {port} 已释放。")


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


def cmd_stop(args):
    stop_backend(port=args.port)


def cmd_data(args):
    {"start": data_start, "stop": data_stop, "status": data_status}[args.action]()


def cmd_db(args):
    action = getattr(args, "action", "init") or "init"
    if action == "cleanup-drafts":
        import asyncio
        from app.core.database import AsyncSessionLocal
        from app.services.expense_sheet_svc import ExpenseSheetService

        days = getattr(args, "days", 30)

        async def _run():
            async with AsyncSessionLocal() as db:
                svc = ExpenseSheetService(db)
                return await svc.cleanup_stale_drafts(days=days)

        removed = asyncio.run(_run())
        print(f"✅ 已清理 {removed} 条过期空草稿（阈值 {days} 天）")
        return
    db_init()


def cmd_kb_rebuild(args):
    """重建 RAG 知识库向量索引"""
    print("🧠 重建知识库向量索引...")
    from app.agent.knowledge.loader import rebuild_index
    success = rebuild_index()
    if success:
        print("✅ 知识库索引已重建")
    else:
        print("⚠️  知识库索引重建失败 (可能 chromadb 未安装)")


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

    p_stop = sub.add_parser("stop", help="停止后端服务 (Ctrl+C 收不掉时执行；若 uv run 报 os error 32，请用 --no-sync 或 stop.bat)")
    p_stop.add_argument("--port", type=int, default=8000, help="后端端口，默认 8000")
    p_stop.set_defaults(func=cmd_stop)

    p_data = sub.add_parser("data", help="数据层管理")
    p_data.add_argument("action", choices=["start", "stop", "status"])
    p_data.set_defaults(func=cmd_data)

    p_db = sub.add_parser("db", help="数据库管理")
    p_db.add_argument("action", choices=["init", "cleanup-drafts"], default="init", nargs="?")
    p_db.add_argument("--days", type=int, default=30, help="清理多少天前的空草稿（cleanup-drafts 用）")
    p_db.set_defaults(func=cmd_db)

    p_kb = sub.add_parser("kb", help="知识库管理")
    p_kb.add_argument("action", choices=["rebuild"], default="rebuild", nargs="?")
    p_kb.set_defaults(func=cmd_kb_rebuild)

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
