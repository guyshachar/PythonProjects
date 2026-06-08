"""
Request/Response models for the outbound POST /v1/messages endpoint.

The CRM sends a SendMessageRequest; OnWays returns a SendMessageResponse
that tells the CRM which channel was used and whether failover occurred.
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.models.unified import ChannelProvider


class SendMessageRequest(BaseModel):
    """
    Payload the CRM sends to OnWays to deliver a WhatsApp message.
    OnWays decides which physical channel to use.
    """

    to: str = Field(
        ...,
        description="Customer's WhatsApp number in E.164 format (e.g. '15551234567').",
        examples=["15551234567"],
    )
    body: str = Field(..., description="Plain-text message body.")

    # WAHA supports multiple named sessions for multi-tenant setups.
    session_id: str = Field(
        "default",
        description="WAHA session name. Defaults to 'default'.",
    )

    # Optional: CRM can pin a specific Meta template name / language for this
    # message instead of the global default (useful for order-confirmation flows).
    template_name: Optional[str] = Field(
        None,
        description="Override the Meta template used during failover for this message.",
    )
    template_language: Optional[str] = Field(
        None,
        description="BCP-47 language code for the override template (e.g. 'en_US').",
    )


class SendMessageResponse(BaseModel):
    """
    What OnWays returns after successfully delivering (or queuing) a message.
    """

    message_id: str = Field(..., description="Provider-assigned ID of the sent message.")
    provider: ChannelProvider = Field(..., description="Which channel was used.")
    channel_state: str = Field(
        ...,
        description="Routing state at the time of send: 'normal' or 'banned'.",
    )
    failover_triggered: bool = Field(
        False,
        description=(
            "True when THIS specific request caused the ban to be detected "
            "and the failover to Meta was triggered automatically."
        ),
    )

    class Config:
        use_enum_values = True
