"""FastAPI entry point:  uvicorn app.main:app --reload"""
import json
import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings
from app.routers import auth, channels, pages
from app.security import LoginRequired, csrf_protect
from app.services.firestore import get_db
from app.services.repo import FirestoreRepo
from app.services.seed import load_expected
from app.templating import render


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "message": record.getMessage(), "logger": record.name}
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def create_app(settings: Settings | None = None, repo=None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="YouTube Studio Scheduler", docs_url=None, redoc_url=None, openapi_url=None,
                  dependencies=[Depends(csrf_protect)])
    app.state.settings = settings
    app.state.repo = repo or FirestoreRepo(get_db)
    app.state.expected = load_expected()
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="yts_session",
        max_age=7 * 24 * 3600,
        same_site="lax",  # lax lets the cookie survive the redirect back from Google
        https_only=settings.secure_cookies,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.exception_handler(LoginRequired)
    async def to_login(request: Request, exc: LoginRequired):
        if request.headers.get("hx-request"):
            return JSONResponse({"detail": "Signed out"}, status_code=401, headers={"HX-Redirect": "/login"})
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        wants_html = "text/html" in request.headers.get("accept", "") and not request.headers.get("hx-request")
        if wants_html and exc.status_code in (400, 403, 404, 503):
            return render(request, "error.html", {"status": exc.status_code, "message": exc.detail},
                          status_code=exc.status_code)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        logging.getLogger("app").exception("unhandled error on %s", request.url.path)
        message = ("Something went wrong. If you're running locally, check that the database is reachable "
                   "(gcloud auth application-default login) and try again.")
        if "text/html" in request.headers.get("accept", ""):
            return render(request, "error.html", {"status": 500, "message": message}, status_code=500)
        return JSONResponse({"detail": message}, status_code=500)

    app.include_router(auth.router)
    app.include_router(pages.router)
    app.include_router(channels.router)
    return app


_setup_logging()
app = create_app()
