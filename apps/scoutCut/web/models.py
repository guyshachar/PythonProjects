"""
Pydantic API models and SQLAlchemy ORM models for ScoutCut web app.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field
from sqlalchemy import JSON, Column, DateTime, Float, String, Text
from sqlalchemy.orm import DeclarativeBase


# ── SQLAlchemy base ────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "jobs"

    id           = Column(String,  primary_key=True, default=lambda: str(uuid.uuid4()))
    status       = Column(String,  default="pending")  # pending|processing|completed|failed
    payload      = Column(JSON)
    price        = Column(Float)
    output_links = Column(JSON,    nullable=True)
    progress     = Column(Text,    nullable=True)
    error        = Column(Text,    nullable=True)
    report       = Column(Text,    nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Shared sub-models ──────────────────────────────────────────────────────────

class VideoRow(BaseModel):
    url:       str
    title:     str = ""
    timecodes: List[str] = Field(default_factory=list)


class ProcessingConfig(BaseModel):
    pad_before:       int     = Field(default=5, ge=0, le=120)
    pad_after:        int     = Field(default=5, ge=0, le=120)
    output_strategy:  Literal["single", "multiple"] = "single"


class DeliveryInfo(BaseModel):
    method:  Literal["email", "whatsapp"]
    contact: str


# ── Quote / Pricing ────────────────────────────────────────────────────────────

class JobQuoteRequest(BaseModel):
    video_rows: List[VideoRow]
    config:     ProcessingConfig
    currency:   Literal["USD", "NIS"] = "USD"
    language:   str = "en"   # "en" | "he" — passed through for context


class JobQuoteResponse(BaseModel):
    # Input counts
    number_of_links: int
    total_clips:     int

    # Localisation metadata
    currency:        str   # "USD" | "NIS"
    currency_symbol: str   # "$" | "₪"

    # Volume discount on the ScoutCut processing fee
    volume_discount_pct:    int   # e.g. 30  (number_of_links × 10, capped)
    volume_discount_amount: int   # absolute amount saved, display currency

    # Financial breakdown — all values are whole integers in the requested currency
    gross_app_revenue:    int   # processing fee before discount
    pure_app_revenue:     int   # processing fee after discount
    fixed_final_edit_fee: int
    hybrid_total_cost:    int   # app + editorial (shown on comparison card)
    app_charge:           int   # app only (charged via payment)
    traditional_cost:     int
    client_savings:       int
    savings_percentage:   float  # e.g. 43.1

    # Config snapshot for formula display in the UI
    rate_per_link:    int
    rate_per_clip:    int
    traditional_rate: int


# ── Job lifecycle ──────────────────────────────────────────────────────────────

class SkippedVideoRow(BaseModel):
    """A video row excluded from processing due to a failed URL validation."""
    url:         str
    title:       str = ""
    timecodes:   List[str] = Field(default_factory=list)
    skip_reason: str = ""


class JobCreateRequest(BaseModel):
    job_title:     str = ""               # user-set project name / header
    video_rows:    List[VideoRow]
    skipped_rows:  List[SkippedVideoRow] = Field(default_factory=list)
    config:        ProcessingConfig
    delivery:      DeliveryInfo
    payment_token: str
    currency:      Literal["USD", "NIS"] = "USD"
    language:      str = "en"


class JobCreateResponse(BaseModel):
    job_id:     str
    status:     str
    status_url: str   # shareable URL: /jobs/{job_id}
    message:    str


class JobStatusResponse(BaseModel):
    job_id:       str
    status:       str
    progress:     Optional[str]       = None
    output_links: Optional[List[str]] = None
    error:        Optional[str]       = None
    report:       Optional[str]       = None


# ── URL validation ────────────────────────────────────────────────────────────

class UrlValidationRequest(BaseModel):
    urls: List[str]


class UrlValidationResult(BaseModel):
    url:      str
    valid:    bool
    status:   str           # "valid" | "warning" | "invalid"
    message:  str
    platform: Optional[str] = None   # "Pixellot" | "Veo" | None


class UrlValidationResponse(BaseModel):
    results: List[UrlValidationResult]


# ── Payments ───────────────────────────────────────────────────────────────────

class PaymentVerifyRequest(BaseModel):
    method:   str
    amount:   float
    currency: str = "USD"
    metadata: Dict = Field(default_factory=dict)


class PaymentVerifyResponse(BaseModel):
    success:       bool
    payment_token: str
    message:       str
