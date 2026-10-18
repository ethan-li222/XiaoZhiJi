"""Access gate for a private, shared workspace. This is not multi-tenant auth."""

import hashlib
import secrets
import sqlite3
import threading
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse


class AccessGate:
    def __init__(self, settings):
        self.settings = settings
        self.token = settings.access_token.get_secret_value()
        if self.token and len(self.token) < 32:
            raise ValueError("私有访问令牌至少需要 32 个字符")
        self.path = settings.data_dir / "access.sqlite3"
        self.key_id = hashlib.sha256(self.token.encode()).hexdigest()
        self.attempts = defaultdict(list)
        self.lock = threading.Lock()
        if self.token:
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, key_id TEXT, expires REAL)"
                )

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def authenticated(self, request):
        if not self.token:
            return True, False
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer ") and secrets.compare_digest(auth[7:], self.token):
            return True, False
        cookie = request.cookies.get("research_session")
        if not cookie:
            return False, False
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute(
                "SELECT key_id,expires FROM sessions WHERE id=?", (self.digest(cookie),)
            ).fetchone()
        return bool(row and row[0] == self.key_id and row[1] > time.time()), True

    def login(self, request, token):
        ip = request.client.host if request.client else "unknown"
        current = time.time()
        with self.lock:
            self.attempts[ip] = [t for t in self.attempts[ip] if current - t < 300]
            if len(self.attempts[ip]) >= 8:
                return JSONResponse({"detail": "登录尝试过多，请五分钟后重试"}, status_code=429)
            if not secrets.compare_digest(token, self.token):
                self.attempts[ip].append(current)
                return JSONResponse({"detail": "访问令牌不正确"}, status_code=401)
            self.attempts.pop(ip, None)
        session = secrets.token_urlsafe(32)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM sessions WHERE expires<? OR key_id!=?", (current, self.key_id))
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?)",
                (self.digest(session), self.key_id, current + 8 * 3600),
            )
        response = JSONResponse({"authenticated": True})
        response.set_cookie(
            "research_session",
            session,
            max_age=8 * 3600,
            httponly=True,
            secure=self.settings.secure_cookies,
            samesite="strict",
        )
        return response

    def logout(self, request):
        cookie = request.cookies.get("research_session")
        if cookie and self.path.exists():
            with closing(sqlite3.connect(self.path)) as db, db:
                db.execute("DELETE FROM sessions WHERE id=?", (self.digest(cookie),))
        response = JSONResponse({"authenticated": False})
        response.delete_cookie("research_session")
        return response

    def install(self, app):
        @app.middleware("http")
        async def protect(request, call_next):
            path = request.url.path
            public = path in {
                "/health",
                "/info",
                "/login",
                "/auth/status",
                "/auth/login",
            } or path.startswith("/static/")
            allowed, cookie = self.authenticated(request)
            if not public and not allowed:
                if path in {"/", "/docs", "/redoc"}:
                    return RedirectResponse("/login", status_code=303)
                return JSONResponse({"detail": "请先登录私有工作空间"}, status_code=401)
            if cookie and allowed and request.method not in {"GET", "HEAD", "OPTIONS"}:
                origin = request.headers.get("origin")
                if origin != str(request.base_url).rstrip("/"):
                    return JSONResponse(
                        {"detail": "请求来源不匹配，请从工作台页面操作"}, status_code=403
                    )
            if request.method in {"POST", "PUT", "PATCH"}:
                maximum = (
                    self.settings.max_upload_bytes
                    if path == "/workspace/uploads"
                    else self.settings.max_request_bytes
                )
                total, chunks = 0, []
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > maximum:
                        return JSONResponse(
                            {"detail": "提交内容超过大小限制，请拆分材料"}, status_code=413
                        )
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Cache-Control"] = (
                "no-store" if not path.startswith("/static/") else "no-cache"
            )
            script = "'self' 'unsafe-inline'" if path.endswith("/graph.html") else "'self'"
            response.headers["Content-Security-Policy"] = (
                f"default-src 'self'; script-src {script}; worker-src 'self' blob:; font-src 'self' blob: data:; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; frame-src 'self'; object-src 'self'; frame-ancestors 'self'; base-uri 'self'"
            )
            return response

        @app.get("/auth/status")
        def status(request: Request):
            return {
                "required": bool(self.token),
                "authenticated": self.authenticated(request)[0],
                "scope": "private_shared_workspace",
            }

        @app.get("/login", include_in_schema=False)
        def login_page():
            from fastapi.responses import FileResponse

            return FileResponse(Path(__file__).with_name("static") / "login.html")

        @app.post("/auth/login")
        async def login(request: Request):
            if not self.token:
                return {"authenticated": True}
            try:
                body = await request.json()
            except ValueError:
                return JSONResponse({"detail": "登录请求格式无效"}, status_code=422)
            if not isinstance(body, dict):
                return JSONResponse({"detail": "登录请求格式无效"}, status_code=422)
            token = body.get("token")
            if not isinstance(token, str):
                return JSONResponse({"detail": "请输入访问令牌"}, status_code=422)
            return self.login(request, token)

        @app.post("/auth/logout")
        def logout(request: Request):
            return self.logout(request)
