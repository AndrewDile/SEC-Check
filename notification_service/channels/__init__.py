"""Every available channel, keyed by the name the Core API uses in Recipient.channel."""

from notification_service.channels.base import Channel
from notification_service.channels.email import EmailChannel
from notification_service.channels.log import LogChannel
from notification_service.channels.slack import SlackChannel
from notification_service.channels.teams import TeamsChannel

CHANNELS: dict[str, Channel] = {
    channel.name: channel
    for channel in [LogChannel(), EmailChannel(), SlackChannel(), TeamsChannel()]
}
