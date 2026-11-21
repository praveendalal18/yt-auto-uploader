from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.security import csrf_token
from app.timeutil import fmt_ist

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["ist"] = fmt_ist


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200):
    ctx = {
        "user": request.session.get("user"),
        "csrf_token": csrf_token(request),
        "settings": request.app.state.settings,
        **(context or {}),
    }
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
