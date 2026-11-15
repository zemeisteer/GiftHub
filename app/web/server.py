import os
import subprocess
import time
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.logging import get_logger
from app.web.auth import get_current_admin, get_current_user, require_permission
from app.web.routes import register_routes
from app.web.security_headers import add_security_headers
from app.web.state import bot_instance, bot_username, get_bot, get_bot_username, set_bot

logger = get_logger("GiftHubAPI")


def _compute_asset_version() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=settings.BASE_DIR,
        )
        sha = out.stdout.strip()
        if out.returncode == 0 and sha:
            return sha
    except Exception:
        pass
    return str(int(time.time()))


ASSET_VERSION = _compute_asset_version()


def render_index(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read().replace("{{v}}", ASSET_VERSION)


def _cors_origins(web_app_url: str) -> list[str]:
    parsed = urlparse(web_app_url or "")
    if parsed.scheme and parsed.netloc:
        return [f"{parsed.scheme}://{parsed.netloc}"]
    return []


def build_app(environment: str) -> FastAPI:
    production = environment == "production"
    app = FastAPI(
        title="GiftHub Web App & API",
        description="Official API for GiftHub — Telegram Stars, Premium, Gifts & Services Platform",
        version="2.0.0",
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
    )

    # 1. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings.WEB_APP_URL),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Telegram-Init-Data", "Authorization", "X-Correlation-ID", "X-Request-ID"],
    )

    # 2. Correlation ID Middleware
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        from app.core.correlation import set_correlation_id

        incoming_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID")
        cid = set_correlation_id(incoming_id)
        response: Response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response


    # 3. Platform Maintenance Mode Middleware
    @app.middleware("http")
    async def maintenance_mode_middleware(request: Request, call_next):
        path = request.url.path
        exempt_prefixes = ("/health", "/ready", "/admin", "/webhook", "/static", "/docs", "/openapi.json")
        if not any(path.startswith(p) for p in exempt_prefixes):
            try:
                from app.services.feature_flags.service import feature_flag_service

                async with AsyncSessionLocal() as session:
                    if await feature_flag_service.is_maintenance_mode(session):
                        return JSONResponse(
                            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            content={
                                "success": False,
                                "maintenance": True,
                                "detail": "Platforma texnik ta'mirlash rejimida. Tez orada qayta ishga tushadi.",
                            },
                        )
            except Exception as e:
                logger.warning(f"Maintenance rejimi tekshiruvida xatolik: {e}")
        return await call_next(request)


    # 4. Include Versioned v1 Router
    app.include_router(v1_router, prefix="/api/v1")

    # 5. Register Modular Application Sub-Routers
    register_routes(app)


    # 6. Frontend HTML Serving
    @app.get("/app", response_class=HTMLResponse)
    async def serve_user_app():
        path = os.path.join(settings.BASE_DIR, "web", "user", "index.html")
        if os.path.exists(path):
            return HTMLResponse(render_index(path), headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<h2>GiftHub Web App fayli topilmadi.</h2>", status_code=404)


    @app.get("/admin", response_class=HTMLResponse)
    async def serve_admin_app():
        path = os.path.join(settings.BASE_DIR, "web", "admin", "index.html")
        if os.path.exists(path):
            return HTMLResponse(render_index(path), headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<h2>GiftHub Admin Panel fayli topilmadi.</h2>", status_code=404)


    @app.get("/")
    async def root_redirect():
        return HTMLResponse("""
        <!DOCTYPE html>
        <html lang="uz">
          <head>
            <meta charset="UTF-8">
            <title>GiftHub — Digital Commerce Platform</title>
            <style>
              body { background:#080C0A; color:#EFFBF4; font-family:-apple-system,BlinkMacSystemFont,sans-serif; text-align:center; padding:60px 20px; }
              .card { max-width:480px; margin:0 auto; background:#121A16; border:1px solid #22302A; border-radius:20px; padding:40px 30px; }
              h1 { color:#12E88B; margin-bottom:10px; font-size:28px; }
              p { color:#8AA69A; font-size:15px; margin-bottom:30px; }
              .btn { display:inline-block; padding:12px 24px; border-radius:12px; font-weight:600; text-decoration:none; margin:8px; font-size:14px; }
              .btn-primary { background:#12E88B; color:#0A100D; }
              .btn-secondary { background:#1D2A24; color:#BFFFDD; border:1px solid #2A3C34; }
            </style>
          </head>
          <body>
            <div class="card">
              <h1>⭐ GiftHub</h1>
              <p>Telegram Stars, Premium obuna va Raqamli sovg'alar platformasi</p>
              <div>
                <a href="/app" class="btn btn-primary">Foydalanuvchi Do'koni (Web App)</a>
                <a href="/admin" class="btn btn-secondary">Admin Boshqaruv Paneli</a>
              </div>
            </div>
          </body>
        </html>
        """)

    # 7. Static files (web/ directory) with caching
    app.mount("/static", StaticFiles(directory=os.path.join(settings.BASE_DIR, "web")), name="static")

    @app.middleware("http")
    async def static_cache_middleware(request: Request, call_next):
        response: Response = await call_next(request)
        if request.url.path.startswith("/static/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response

    # 8. Security headers (added last, so it is outermost and covers every response)
    add_security_headers(app)

    return app


app = build_app(settings.ENVIRONMENT)


__all__ = [
    "app",
    "get_bot",
    "get_bot_username",
    "get_current_admin",
    "get_current_user",
    "get_db",
    "require_permission",
    "set_bot",
]
