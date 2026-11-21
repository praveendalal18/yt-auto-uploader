"""Signed-in pages, public legal pages and health checks."""
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.security import require_user
from app.services import firestore
from app.templating import render
from app.timeutil import fmt_ist, now_utc

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/")
def dashboard(request: Request, user: dict = Depends(require_user)):
    ctx = {"now_ist": fmt_ist(now_utc()), "db_error": False, "channels": [], "account": None}
    try:
        ctx["channels"] = request.app.state.repo.list_channels()
        ctx["account"] = request.app.state.repo.get_app_settings()
    except Exception:
        log.exception("dashboard: database not reachable")
        ctx["db_error"] = True
    ctx["expected_count"] = len(request.app.state.expected)
    return render(request, "dashboard.html", ctx)


@router.get("/privacy")
def privacy(request: Request):
    return render(request, "privacy.html")


@router.get("/terms")
def terms(request: Request):
    return render(request, "terms.html")


@router.get("/healthz")
def healthz():
    return {"ok": True}


@router.get("/healthz/db")
def healthz_db(request: Request):
    """Daily keep-alive: one small Firestore read + write. Needs the X-Ping-Token header."""
    expected = request.app.state.settings.ping_token
    sent = request.headers.get("x-ping-token", "")
    if not expected or not hmac.compare_digest(expected, sent):
        raise HTTPException(404)
    try:
        firestore.ping()
    except Exception:
        log.exception("firestore ping failed")
        raise HTTPException(503, "Database ping failed") from None
    return {"ok": True, "db": "ok"}
