@echo off
rem ============================================================================
rem stop.bat — 强制停止后端（Windows）
rem ----------------------------------------------------------------------------
rem 为什么需要它：
rem   `uv run reimburse stop` 在 pyproject 变更后会先做一次 sync，而 sync 需要覆盖
rem   Scripts\reimburse.exe —— 该文件正被运行中的后端占用 → 报 os error 32，命令还没
rem   执行就中止了。本脚本【绕过 uv】，直接用虚拟环境的 python 运行停止逻辑，不触发 sync，
rem   因此后端运行时也能稳定停止。
rem
rem 用法：
rem   stop.bat            停止默认端口 8000 的后端
rem   stop.bat --port 8010   停止指定端口
rem ============================================================================
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" -m app.cli stop %*

endlocal
