"""
=============================================================================
app/core/celery_app.py — 异步任务队列配置
=============================================================================
Celery 是一个"任务调度器"，用来在后台执行耗时操作（如发邮件、OCR 识别），
不阻塞用户请求的响应。

小白理解：
  用户提交报销 → 后端立即返回"已收到" → 后台 Celery 慢慢处理发邮件/生成PDF
  这样用户不用干等着，体验更好。

本文件只做两件事：
  1. 创建一个 Celery 应用实例
  2. 配置它连接 Redis 作为消息中间件
=============================================================================
"""
from celery import Celery
from app.core.config import get_settings

settings = get_settings()

# =============================================================================
# 创建 Celery 实例
# =============================================================================
# broker  = 消息代理 → Celery 通过 Redis 收发任务（"任务中转站"）
# backend = 结果后端 → 任务执行结果也存 Redis（"任务成绩单"）
celery_app = Celery(
    "reimburse_agent",                       # 应用名称，随便起
    broker=settings.CELERY_BROKER_URL,       # 从哪接收任务
    backend=settings.CELERY_RESULT_BACKEND,  # 任务结果存哪
)

# =============================================================================
# Celery 全局配置
# =============================================================================
celery_app.conf.update(
    task_serializer="json",           # 任务参数用 JSON 格式传输
    accept_content=["json"],          # 只接受 JSON 格式的任务
    result_serializer="json",         # 任务结果也用 JSON 格式
    timezone="Asia/Shanghai",         # 时区设为北京时间
    enable_utc=True,                  # 内部使用 UTC 时间（国际标准）
    task_track_started=True,          # 记录任务"已开始"状态
    task_acks_late=True,              # 任务执行完再确认（不会丢任务）
    worker_prefetch_multiplier=1,     # 每次只取一个任务（适合长任务）
)
