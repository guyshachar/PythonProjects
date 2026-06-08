"""
Browser-facing monitor dashboard  –  GET /monitor

Serves app/static/monitor.html — a single-page dashboard that polls
GET /v1/admin/monitor every 10 seconds and renders a live table of
sessions, their sending numbers, and routing states.
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["monitor"])

_STATIC_DIR = Path(__file__).parent.parent / "static"


@router.get("/monitor", response_class=HTMLResponse, include_in_schema=False)
async def monitor_dashboard() -> HTMLResponse:
    """Serve the live browser monitor dashboard."""
    html = (_STATIC_DIR / "monitor.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)
