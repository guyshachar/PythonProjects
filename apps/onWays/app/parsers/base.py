"""
IWebhookParser – the Strategy interface every provider parser must implement.

New providers (e.g. Twilio, 360Dialog) are added by:
  1. Creating a new module under app/parsers/
  2. Subclassing IWebhookParser
  3. Registering the class in app/routers/webhooks.py

No existing code needs to change (Open/Closed Principle).
"""

from abc import ABC, abstractmethod
from typing import Union

from app.models.unified import UnifiedMessage, UnifiedReadReceipt

# The return type of every parser: either a normalised message or a receipt.
ParsedEvent = Union[UnifiedMessage, UnifiedReadReceipt]


class IWebhookParser(ABC):
    """Abstract base class (interface) for all webhook payload parsers."""

    @abstractmethod
    def can_parse(self, payload: dict) -> bool:
        """
        Return True if this parser recognises the given raw payload.

        The router calls this on each registered parser in order and uses
        the first one that returns True.  Keeps the router decoupled from
        individual provider signatures.
        """

    @abstractmethod
    def parse(self, payload: dict) -> ParsedEvent:
        """
        Transform the raw provider payload into a UnifiedMessage or
        UnifiedReadReceipt.

        Raises:
            ValueError: if the payload is structurally valid JSON but
                        missing required fields.
            NotImplementedError: if the payload type is valid but not yet
                                 handled (e.g. an unsupported media type).
        """
