"""
=============================================================================
tasks/ocr_task.py — 异步 OCR 识别任务
=============================================================================
Celery 任务：后台执行发票 OCR 文字识别。

当前为模拟实现（sleep 2 秒 + 返回固定数据）。
实际生产环境应接入 PaddleOCR 或大模型视觉 API。
=============================================================================
"""
import time                                              # 模拟耗时操作
from app.core.celery_app import celery_app
from loguru import logger


@celery_app.task(name="tasks.run_ocr")
def run_ocr_task(file_path: str):
    """
    Celery 异步任务：对上传的发票文件进行 OCR 识别。

    参数:
        file_path: MinIO 中存储的文件路径

    返回:
        识别结果（发票代码、号码、金额等）

    使用方式：
      run_ocr_task.delay("invoices/abc123.pdf")
    """
    # 模拟 OCR 处理耗时（真实场景可能 3-30 秒）
    time.sleep(2)

    logger.info(f"OCR completed for {file_path}")
    return {
        "file_path": file_path,
        "invoice_code": "044001900111",
        "invoice_number": "87654321",
        "amount": 1500.00,
        "status": "ocr_completed",
    }
