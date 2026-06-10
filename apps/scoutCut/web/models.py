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

    id         = Column(String,  primary_key=True, default=lambda: str(uuid.uuid4()))
    status     = Column(String,  default="pending")  # pending|processing|completed|failed
    payload    = Column(JSON)
    price      = Column(Float)
    output_links = Column(JSON,  nullable=True)
    progress   = Column(Text,    nullable=True)
    error      = Column(Text,    nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ── Pydantic API models ────────────────────────────────────────────────────────

class VideoRow(BaseModel):
    url: str
    title: str = ""
    timecodes: List[str] = Field(default_factory=list)


class ProcessingConfig(BaseModel):
    pad_before: int = Field(default=5, ge=0, le=120)
    pad_after:  int = Field(default=5, ge=0, le=120)
    output_strategy: Literal["single", "multiple"] = "single"


class DeliveryInfo(BaseModel):
    method:  Literal["email", "whatsapp"]
    contact: str


class JobQuoteRequest(BaseModel):
    video_rows: List[VideoRow]
    config:     ProcessingConfig


class JobQuoteResponse(BaseModel):
    total_clips:            int
    unique_urls:            int
    estimated_duration_mins: float
    price:                  float
    breakdown:              Dict[str, float]


class JobCreateRequest(BaseModel):
    video_rows:    List[VideoRow]
    config:        ProcessingConfig
    delivery:      DeliveryInfo
    payment_token: str


class JobCreateResponse(BaseModel):
    job_id:  str
    status:  str
    message: str


class JobStatusResponse(BaseModel):
    job_id:       str
    status:       str
    progress:     Optional[str]   = None
    output_links: Optional[List[str]] = None
    error:        Optional[str]   = None


class PaymentVerifyRequest(BaseModel):
    method:   str
    amount:   float
    metadata: Dict = Field(default_factory=dict)


class PaymentVerifyResponse(BaseModel):
    success:       bool
    payment_token: str
    message:       str
