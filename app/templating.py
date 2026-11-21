from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.security import csrf_token
from app.timeutil import fmt_ist

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["ist"] = fmt_ist
WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
templates.env.filters["days"] = lambda days: ", ".join(WEEKDAY_NAMES[d] for d in days if 0 <= d <= 6)


def flash(request: Request, kind: str, message: str) -> None:
    """Queue a one-time message (kind: ok | warn | error) for the next page shown."""
    request.session.setdefault("flash", []).append([kind, message])
    request.session["flash"] = request.session["flash"]  # mark session as changed


def render(request: Request, name: str, context: dict | None = None, status_code: int = 200):
    ctx = {
        "user": request.session.get("user"),
        "csrf_token": csrf_token(request),
        "settings": request.app.state.settings,
        "flashes": request.session.pop("flash", []),
        **(context or {}),
    }
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)
