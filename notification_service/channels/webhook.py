"""Posting to chat webhooks (Slack, Microsoft Teams), and which of their errors are worth retrying."""

from urllib.parse import urlsplit

import httpx

from notification_service import config
from notification_service.channels.base import Channel, PermanentDeliveryError
from notification_service.models import Recipient


class WebhookChannel(Channel):
    """A channel whose address is a webhook URL on one of a few known hosts.

    The Core API only accepts such URLs, and this checks again before posting. Redirects aren't
    followed, so a webhook can't send the notifier to another host, such as one inside the stack.
    """

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=config.HTTP_TIMEOUT_S, follow_redirects=False)

    def allowed_host(self, host: str) -> bool:
        raise NotImplementedError

    def post(self, recipient: Recipient, payload: dict) -> None:
        url = urlsplit(recipient.address)
        if url.scheme != "https" or url.username or not self.allowed_host(url.hostname or ""):
            raise PermanentDeliveryError(f"not a {self.name} webhook URL")
        # Timeouts and connection errors propagate, and are retried
        response = self.client.post(recipient.address, json=payload)
        if response.is_success:
            return
        detail = f"{self.name} webhook answered {response.status_code}: {response.text[:200]}"
        if response.status_code == 429 or response.status_code >= 500:
            raise RuntimeError(detail)  # rate limited or down: may work next time
        # 3xx (not followed) and other 4xx: a removed webhook, a bad payload. Retrying can't help.
        raise PermanentDeliveryError(detail)
