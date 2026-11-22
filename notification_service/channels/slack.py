"""Slack, through an incoming webhook: https://api.slack.com/messaging/webhooks"""

from notification_service.channels.base import Message
from notification_service.channels.webhook import WebhookChannel
from notification_service.models import Recipient

# Block Kit limits: a header's text and a section's text
HEADER_MAX = 150
SECTION_MAX = 3000


def escape(text: str) -> str:
    """Slack's mrkdwn treats &, < and > as markup."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class SlackChannel(WebhookChannel):
    name = "slack"

    def allowed_host(self, host: str) -> bool:
        return host == "hooks.slack.com"

    def send(self, recipient: Recipient, message: Message) -> None:
        self.post(recipient, payload(message))


def payload(message: Message) -> dict:
    return {
        "text": message.subject,  # shown in notifications and where blocks can't be
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": clip(message.subject, HEADER_MAX)},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": clip(escape(message.body), SECTION_MAX)},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Claim this incident"},
                        "url": message.claim_url,
                        "style": "primary",
                    }
                ],
            },
        ],
    }
