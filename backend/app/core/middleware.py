"""
=============================================================================
app/core/middleware.py — 请求/响应日志中间件
=============================================================================
拦截每一个 HTTP 请求和响应，在终端打印详细信息：

  [API] POST /api/v1/chat | 200 | 342ms | {"intent":"new_reimbursement",...}

输出格式:
  [API] 方法 路径 | 状态码 | 耗时 | 响应体摘要

为什么用自定义中间件而不是 FastAPI 的 middleware 装饰器？
  自定义中间件能精确记录"请求到达时刻"和"响应发出时刻"，
  从而计算真实的处理耗时。

同时添加请求追踪 ID（X-Request-ID），方便日志关联。
=============================================================================
"""
import time
import uuid
import json
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from loguru import logger


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    请求日志中间件：
      1. 为每个请求生成唯一追踪 ID
      2. 记录请求开始时间
      3. 请求处理完成后，打印一行摘要日志

    日志格式：
      09:21:03 | INFO | [API] POST /api/v1/chat → 200 (342ms)
      09:21:03 | INFO | [API]        ↳ intent=new_reimbursement amount=1500
    """

    async def dispatch(self, request: Request, call_next):
        # --- 1. 生成请求追踪 ID ---
        # 优先使用客户端传来的 X-Request-ID，没有则自动生成
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        request.state.request_id = request_id

        # --- 2. 记录请求开始时间 ---
        start_time = time.perf_counter()                   # 高精度计时

        # --- 3. 执行真正的请求处理 ---
        # call_next 会把请求传递给下一个中间件或路由处理函数
        response: Response = await call_next(request)

        # --- 4. 计算耗时 ---
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # --- 5. 提取响应体摘要 ---
        response_body_preview = self._extract_response_preview(response, request)

        # --- 6. 打印日志 ---
        log_msg = (
            f"[API] {request.method:<6s} {request.url.path} "
            f"→ {response.status_code} "
            f"({elapsed_ms:.0f}ms)"
        )
        logger.info(log_msg)

        # 如果有响应体摘要，再打印一行
        if response_body_preview:
            logger.info(f"[API]        ↳ {response_body_preview}")

        return response

    def _extract_response_preview(
        self, response: Response, request: Request
    ) -> str:
        """
        从响应中提取关键信息用于日志展示。

        对不同端点定制不同的摘要格式：
          - /chat → 意图 + 长度
          - /budget → 部门数量
          - /upload → 文件名 + 大小
          - 其他 → 响应体前 200 字符
        """
        # 只处理 JSON 响应
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return ""

        # 尝试读取响应体（注意：这通常需要特殊处理）
        path = request.url.path

        # 根据路径提供定制化摘要
        if "/chat" in path:
            body = self._get_body(response)
            if body:
                try:
                    data = json.loads(body)
                    intent = data.get("intent", "?")
                    reply_len = len(data.get("reply", ""))
                    return f"intent={intent} reply_len={reply_len}"
                except (json.JSONDecodeError, KeyError):
                    return f"len={len(body)}"
            return ""

        elif "/budget" in path:
            body = self._get_body(response)
            if body:
                try:
                    data = json.loads(body)
                    if isinstance(data, list):
                        return f"{len(data)} departments"
                except (json.JSONDecodeError, KeyError):
                    pass
            return ""

        elif "/upload" in path:
            body = self._get_body(response)
            if body:
                try:
                    data = json.loads(body)
                    return (
                        f"file={data.get('filename','?')} "
                        f"size={data.get('size',0)}B"
                    )
                except (json.JSONDecodeError, KeyError):
                    pass
            return ""

        elif "/health" in path:
            body = self._get_body(response)
            if body:
                try:
                    data = json.loads(body)
                    return f"status={data.get('status','?')}"
                except (json.JSONDecodeError, KeyError):
                    pass
            return ""

        # 默认：截取响应体前 200 字符
        body = self._get_body(response)
        if body:
            return body[:200]
        return ""

    def _get_body(self, response: Response) -> str | None:
        """
        安全地获取响应体内容。
        注意：StreamingResponse 没有 body，返回 None。
        """
        # StreamingResponse 没有 body 属性
        if hasattr(response, "body_iterator"):
            return None

        # 尝试从 body 获取
        body = getattr(response, "body", None)
        if body is None:
            # raw_body 在 Starlette >= 0.36 可用
            body = getattr(response, "raw_body", None)

        if body is None:
            return None

        if isinstance(body, bytes):
            return body.decode("utf-8", errors="replace")
        return str(body)


# =============================================================================
# 辅助函数：记录异常
# =============================================================================
def log_error(request: Request, exc: Exception, elapsed_ms: float):
    """
    记录异常请求的详细信息。

    在异常处理函数中调用，确保失败请求也有日志记录。
    """
    request_id = getattr(request.state, "request_id", "unknown")
    logger.error(
        f"[API] {request.method} {request.url.path} "
        f"→ ERROR | {elapsed_ms:.0f}ms | "
        f"req_id={request_id} | "
        f"{type(exc).__name__}: {exc}"
    )
