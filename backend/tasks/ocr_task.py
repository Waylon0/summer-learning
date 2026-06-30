import time
from app.core.celery_app import celery_app
from loguru import logger


@celery_app.task(name="tasks.run_ocr")
def run_ocr_task(file_path: str):
    time.sleep(2)
    logger.info(f"OCR completed for {file_path}")
    return {
        "file_path": file_path,
        "invoice_code": "044001900111",
        "invoice_number": "87654321",
        "amount": 1500.00,
        "status": "ocr_completed",
    }
