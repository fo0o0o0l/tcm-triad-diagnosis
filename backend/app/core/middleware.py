"""trace_id 中间件（M0-1）。

使用**纯 ASGI 中间件**而非 `BaseHTTPMiddleware`，以避免 Starlette 在子任务中
执行下游应用导致 `contextvars` 不传播，从而保证 trace_id 能被路由处理器读取。
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .logging import new_trace_id, reset_trace_id, set_trace_id

TRACE_ID_HEADER = "x-trace-id"


class TraceIdMiddleware:
    """为每个请求生成/透传 trace_id，写入上下文与响应头 `X-Trace-Id`。

    实现 ASGI3 协议，满足 `starlette.types.ASGIApp` 类型约束，
    因此可直接传给 `app.add_middleware(TraceIdMiddleware)`。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope.get("headers") or []).get(TRACE_ID_HEADER.encode())
        trace_id = incoming.decode() if incoming else new_trace_id()
        token = set_trace_id(trace_id)

        async def send_with_trace_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"].append((TRACE_ID_HEADER.encode(), trace_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_trace_id)
        finally:
            reset_trace_id(token)
