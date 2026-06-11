"""
ScoutCut — FastAPI application.

Routes:
    GET  /                         → serve frontend SPA
    GET  /jobs/{id}                → job status page (shareable URL)
    POST /api/payments/verify      → payment processor dispatcher
    POST /api/jobs/quote           → price quote (no side-effects)
    POST /api/calculate-price      → alias for /api/jobs/quote
    POST /api/jobs/create          → create + enqueue job
    GET  /api/jobs/{id}/status     → poll job status (JSON)
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from web.database import JobRecord, create_tables, get_db
from web.models import (
    JobCreateRequest,
    JobCreateResponse,
    JobQuoteRequest,
    JobQuoteResponse,
    JobStatusResponse,
    PaymentVerifyRequest,
    PaymentVerifyResponse,
    UrlValidationRequest,
    UrlValidationResponse,
)
from web.pricing import calculate_job_price
from web.payments import process_payment
from web.url_validator import validate_url

log = logging.getLogger(__name__)

# ── Boot ───────────────────────────────────────────────────────────────────────
create_tables()

app = FastAPI(title="ScoutCut", version="1.0.0", docs_url="/api/docs")

_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


# ── Frontend SPA ───────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(str(_static / "index.html"))


# ── Shareable job status page ──────────────────────────────────────────────────

@app.get("/jobs/{job_id}", include_in_schema=False)
def job_status_page(job_id: str, db: Session = Depends(get_db)):
    """
    Human-friendly shareable URL the user receives after submitting a job.
    Renders the SPA with the job_id pre-loaded so the status step opens directly.
    """
    job: JobRecord | None = db.get(JobRecord, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    # Read the SPA and inject the job_id so Alpine can pick it up on load.
    html = (_static / "index.html").read_text(encoding="utf-8")
    inject = f"""<script>window.__SCOUTCUT_JOB_ID__ = "{job_id}";</script>"""
    html = html.replace("</head>", inject + "\n</head>", 1)
    return HTMLResponse(content=html)


# ── URL validation ────────────────────────────────────────────────────────────

@app.post("/api/jobs/validate-urls", response_model=UrlValidationResponse, tags=["jobs"])
async def validate_urls(req: UrlValidationRequest):
    """
    Validate a list of URLs using scoutCut's classification logic.

    Uses _looks_like_url() and _PLATFORM_MARKERS from scoutCut.py for format
    and platform detection, then does a lightweight HTTP check per URL.
    The full Playwright scrapers are NOT invoked — this is a fast pre-flight check.
    """
    results = await asyncio.gather(*[validate_url(u) for u in req.urls])
    return {"results": list(results)}


# ── Payments ───────────────────────────────────────────────────────────────────

@app.post("/api/payments/verify", response_model=PaymentVerifyResponse, tags=["payments"])
def verify_payment(req: PaymentVerifyRequest):
    """
    Dispatch to the correct payment processor based on req.method.
    Returns a payment_token used to authorise job creation.
    """
    return process_payment(req)


# ── Pricing ────────────────────────────────────────────────────────────────────

def _validate_quote_request(req: JobQuoteRequest) -> None:
    if not req.video_rows:
        raise HTTPException(status_code=422, detail="At least one video row is required.")
    for row in req.video_rows:
        if not row.timecodes:
            raise HTTPException(
                status_code=422,
                detail=f"Row for URL '{row.url}' has no timecodes.",
            )


@app.post("/api/jobs/quote", response_model=JobQuoteResponse, tags=["jobs"])
def quote_job(req: JobQuoteRequest):
    """Full pricing breakdown in the requested currency. No DB writes."""
    _validate_quote_request(req)
    return JobQuoteResponse(**calculate_job_price(req))


@app.post("/api/calculate-price", response_model=JobQuoteResponse, tags=["pricing"])
def calculate_price(req: JobQuoteRequest):
    """Canonical pricing endpoint — alias of /api/jobs/quote."""
    _validate_quote_request(req)
    return JobQuoteResponse(**calculate_job_price(req))


# ── Jobs ───────────────────────────────────────────────────────────────────────

@app.post("/api/jobs/create", response_model=JobCreateResponse, tags=["jobs"])
def create_job(req: JobCreateRequest, db: Session = Depends(get_db)):
    """Validate payment token, persist the job record, and enqueue the Celery task."""
    try:
        uuid.UUID(req.payment_token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payment token.")

    quote_req  = JobQuoteRequest(video_rows=req.video_rows, config=req.config,
                                  currency=req.currency, language=req.language)
    price_data = calculate_job_price(quote_req)

    job_id = str(uuid.uuid4())
    job = JobRecord(
        id=job_id,
        status="pending",
        payload=req.model_dump(),
        price=price_data["hybrid_total_cost"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()

    from web.tasks import process_job   # late import avoids circular at module load
    process_job.apply_async(args=[job_id, req.model_dump()], task_id=job_id)

    status_url = f"/jobs/{job_id}"
    log.info("Job %s created — status URL: %s", job_id, status_url)

    return JobCreateResponse(
        job_id=job_id,
        status="pending",
        status_url=status_url,
        message="Job queued. Bookmark the status URL to check progress anytime.",
    )


@app.get("/api/jobs/{job_id}/status", response_model=JobStatusResponse, tags=["jobs"])
def job_status(job_id: str, db: Session = Depends(get_db)):
    """Poll job status. Frontend calls this every 3 s."""
    job: JobRecord | None = db.get(JobRecord, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    links = job.output_links
    if links:
        links = list(dict.fromkeys(links))  # dedup preserving order (worker may store duplicates)
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        output_links=links,
        error=job.error,
        report=job.report,
    )
