# admin/auth.py
import base64
import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

class AdminAuthMiddleware(BaseHTTPMiddleware):
    """Простая HTTP Basic-авторизация на пути /admin/*."""
    def __init__(self, app):
        super().__init__(app)
        self.user = os.getenv("ADMIN_USER", "admin")
        self.password = os.getenv("ADMIN_PASS", "admin")

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path.startswith("/admin"):
            header = request.headers.get("Authorization")
            if not header or not header.startswith("Basic "):
                return PlainTextResponse(
                    "Unauthorized",
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="admin"'},
                )
            try:
                decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
                user, passwd = decoded.split(":", 1)
            except Exception:
                return PlainTextResponse(
                    "Unauthorized",
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="admin"'},
                )

            if user != self.user or passwd != self.password:
                return PlainTextResponse(
                    "Unauthorized",
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="admin"'},
                )

        return await call_next(request)
