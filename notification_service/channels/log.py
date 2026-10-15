import logging

from notification_service.channels.base import Channel, Message
from notification_service.models import Recipient

log = logging.getLogger(__name__)


class LogChannel(Channel):
    """For development: writes the message to the log instead of sending it anywhere."""

    name = "log"

    def send(self, recipient: Recipient, message: Message) -> None:
        log.info(
            "To %s <%s>: %s\n%s",
            recipient.team_name,
            recipient.address,
            message.subject,
            message.body,
        )
