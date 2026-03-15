"""Bu dosya request başına bir correlation/request ID üretmek için var."""

# Observability altyapısının ilk adımı bu.

import uuid
from collections.abc import Callable

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """RequestIdMiddleware

        Bu sınıf her request için şunu yapıyor:
        request header’da X-Request-ID var mı bakıyor
        varsa onu kullanıyor
        yoksa uuid.uuid4() ile yeni ID üretiyor
        bunu request.state.request_id içine koyuyor
        response header’a da aynı ID’yi geri yazıyor


    Bu sayede loglarda ve istemci tarafında aynı isteği takip edebiliriz.
    Özellikle production debugging için çok değerlidir.
    """

    def __init__(self, app, header_name: str = "X-Request-ID"):
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get or generate request ID
        request_id = request.headers.get(self.header_name)
        if not request_id:
            request_id = str(uuid.uuid4())

        # Inject into request state for downstream access
        request.state.request_id = request_id

        # Process the request
        response = await call_next(request)

        # Add request ID to response headers
        response.headers[self.header_name] = request_id

        return response
