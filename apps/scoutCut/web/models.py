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

    # Financial breakdown — all values are whole integers in the requested currency
    traditional_cost:     int
    pure_app_revenue:     int
    fixed_final_edit_fee: int
    hybrid_total_cost:    int
    client_savings:       int
    savings_percentage:   float   # still a float (e.g. 43.1%)

    # Config snapshot for formula display in the UI
    rate_per_link:    int
    rate_per_clip:    int
    traditional_rate: int


# ── Job lifecycle ──────────────────────────────────────────────────────────────

class JobCreateRequest(BaseModel):
    job_title:     str = ""               # user-set project name / header
    video_rows:    List[VideoRow]
    config:        ProcessingConfig
    delivery:      DeliveryInfo
    payment_token: str
    currency:      Literal["USD", "NIS"] = "USD"
    language:      str = "en"


class JobCreateResponse(BaseModel):
    job_id:  str
    status:  str
    message: str


class JobStatusResponse(BaseModel):
    job_id:       str
    status:       str
    progress:     Optional[str]       = None
    output_links: Optional[List[str]] = None
    error:        Optional[str]       = None


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
