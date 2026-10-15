"""Every available channel, keyed by the name the Core API uses in Recipient.channel."""

from notification_service.channels.base import Channel
from notification_service.channels.log import LogChannel

CHANNELS: dict[str, Channel] = {channel.name: channel for channel in [LogChannel()]}
