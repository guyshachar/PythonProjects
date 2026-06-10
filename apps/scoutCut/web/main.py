"""
ScoutCut — FastAPI application.

Routes:
    GET  /                       → serve frontend SPA
    POST /api/payments/verify    → mock payment gateway
    POST /api/jobs/quote         → price quote (no side-effects)
    POST /api/jobs/create        → create + enqueue job
    GET  /api/jobs/{id}/status   → poll job status
"""

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from web.database import JobRecord, SessionLocal, create_tables, get_db
from web.models import (
    JobCreateRequest,
    JobCreateResponse,
    JobQuoteRequest,
    JobQuoteResponse,
    JobStatusResponse,
    PaymentVerifyRequest,
    PaymentVerifyResponse,
)
from web.pricing import calculate_job_price

# ── Boot ───────────────────────────────────────────────────────────────────────
create_tables()

app = FastAPI(title="ScoutCut", version="1.0.0", docs_url="/api/docs")

_static = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static)), name="static")


# ── Frontend ───────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(str(_static / "index.html"))


# ── Payments (mock) ────────────────────────────────────────────────────────────

@app.post("/api/payments/verify", response_model=PaymentVerifyResponse, tags=["payments"])
def verify_payment(req: PaymentVerifyRequest):
    """
    Mock payment gateway.  Always approves in dev.

    Production: integrate Stripe, Apple Pay, Google Pay, or Bit here.
    """
    token = str(uuid.uuid4())
    return PaymentVerifyResponse(
        success=True,
        payment_token=token,
        message=f"Payment of ${req.amount:.2f} via {req.method} approved.",
    )


# ── Jobs ───────────────────────────────────────────────────────────────────────

@app.post("/api/jobs/quote", response_model=JobQuoteResponse, tags=["jobs"])
def quote_job(req: JobQuoteRequest):
    """Return a price estimate with a breakdown.  No DB writes."""
    if not req.video_rows:
        raise HTTPException(status_code=422, detail="At least one video row is required.")
    for row in req.video_rows:
        if not row.timecodes:
            raise HTTPException(
                status_code=422,
                detail=f"Row for URL '{row.url}' has no timecodes."
            )
    result = calculate_job_price(req)
    return JobQuoteResponse(**result)


@app.post("/api/jobs/create", response_model=JobCreateResponse, tags=["jobs"])
def create_job(req: JobCreateRequest, db: Session = Depends(get_db)):
    """
    Validate payment token, persist the job record, and enqueue the Celery task.
    """
    # Validate payment token is a UUID (mock check; real impl would call Stripe etc.)
    try:
        uuid.UUID(req.payment_token)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payment token.")

    # Compute price to store on record
    quote_req = JobQuoteRequest(video_rows=req.video_rows, config=req.config)
    price_data = calculate_job_price(quote_req)

    job_id = str(uuid.uuid4())
    job = JobRecord(
        id=job_id,
        status="pending",
        payload=req.model_dump(),
        price=price_data["price"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()

    # Enqueue — import here to avoid circular at module load
    from web.tasks import process_job
    process_job.apply_async(args=[job_id, req.model_dump()], task_id=job_id)

    return JobCreateResponse(
        job_id=job_id,
        status="pending",
        message="Job queued. You will be notified when processing is complete.",
    )


@app.get("/api/jobs/{job_id}/status", response_model=JobStatusResponse, tags=["jobs"])
def job_status(job_id: str, db: Session = Depends(get_db)):
    """Poll job status.  Frontend calls this every 3 s."""
    job: JobRecord | None = db.get(JobRecord, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        output_links=job.output_links,
        error=job.error,
    )
