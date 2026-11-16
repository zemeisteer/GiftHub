from fastapi import FastAPI, Request, Response

CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://telegram.org; "
    "style-src 'self' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'self' https: data:; "
    "connect-src 'self'; "
    "frame-ancestors https://web.telegram.org https://*.telegram.org"
)


def add_security_headers(app: FastAPI) -> None:
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = CSP_POLICY
        return response
