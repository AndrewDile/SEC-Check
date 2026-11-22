"""Microsoft Teams, through a Workflows webhook ("When a Teams webhook request is received").

The old Office 365 connector webhooks are retired. A Workflows webhook takes a message with an
Adaptive Card attachment and answers 202.
"""

from notification_service.channels.base import Message
from notification_service.channels.webhook import WebhookChannel
from notification_service.models import Recipient

WORKFLOWS_HOSTS = (".logic.azure.com", ".api.powerplatform.com")


class TeamsChannel(WebhookChannel):
    name = "ms_teams"

    def allowed_host(self, host: str) -> bool:
        return host.endswith(WORKFLOWS_HOSTS)

    def send(self, recipient: Recipient, message: Message) -> None:
        self.post(recipient, payload(message))


def payload(message: Message) -> dict:
    # One TextBlock per line: how Teams renders newlines inside one block varies by client
    lines = []
    blank = False
    for line in message.body.splitlines():
        if not line.strip():
            blank = True
            continue
        lines.append(
            {
                "type": "TextBlock",
                "text": line,
                "wrap": True,
                "spacing": "Medium" if blank else "None",
            }
        )
        blank = False
    card = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": message.subject,
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
            },
            *lines,
        ],
        "actions": [
            {"type": "Action.OpenUrl", "title": "Claim this incident", "url": message.claim_url}
        ],
    }
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": card,
            }
        ],
    }
