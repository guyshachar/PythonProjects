"""
IChannelClient – the Strategy interface every outbound channel must implement.

Adding a new provider means:
  1. Subclass IChannelClient in a new module under app/clients/
  2. Implement send_text() and health_check()
  3. Register the instance in RouterService

No existing code changes (Open/Closed Principle).
"""

from abc import ABC, abstractmethod


class BanDetectedError(Exception):
    """
    Raised by a client when it determines the channel is banned/suspended.

    RouterService catches this to trigger automatic failover and state change.
    The `message` attribute should contain raw provider error context for logging.
    """


class ProviderError(Exception):
    """
    Raised for non-ban provider failures (network timeout, 5xx, malformed
    response, etc.) that should NOT trigger a failover.
    """


class IChannelClient(ABC):
    """Abstract base for WAHA, Meta Cloud API, or any future provider."""

    @abstractmethod
    async def send_text(self, to: str, body: str, session_id: str = "default") -> str:
        """
        Send a plain-text WhatsApp message.

        Returns:
            The provider-assigned message ID string.

        Raises:
            BanDetectedError: if the provider signals the channel is banned.
            ProviderError: for any other delivery failure.
        """

    @abstractmethod
    async def send_template(
        self,
        to: str,
        template_name: str,
        language_code: str,
        components: list | None = None,
    ) -> str:
        """
        Send a pre-approved Meta template message.

        Returns:
            The provider-assigned message ID string.

        Raises:
            ProviderError: for delivery failures.
        """

    @abstractmethod
    async def health_check(self, session_id: str = "default") -> bool:
        """
        Probe the channel to confirm it is live and not banned.

        Returns:
            True  → channel is working.
            False → channel appears down or banned.
        """
