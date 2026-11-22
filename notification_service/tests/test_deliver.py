"""How delivery to one recipient retries, and when it gives up."""

import unittest
from unittest.mock import call, patch

from notification_service import config
from notification_service.channels.base import Channel, Message, PermanentDeliveryError
from notification_service.dispatcher import deliver
from notification_service.models import Recipient

RECIPIENT = Recipient(recipient_id="r1", team_name="LEGAL", channel="fake", address="x")
MESSAGE = Message(subject="s", body="b", claim_url="https://example.com/claim")


class FakeChannel(Channel):
    """Raises each of `errors` in turn, then succeeds."""

    name = "fake"

    def __init__(self, *errors: Exception):
        self.errors = list(errors)
        self.calls = 0

    def send(self, recipient: Recipient, message: Message) -> None:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)


def deliver_via(channel: FakeChannel):
    # No real backoff waits
    with patch.dict("notification_service.dispatcher.CHANNELS", {"fake": channel}):
        with patch("notification_service.dispatcher.time.sleep"):
            return deliver(RECIPIENT, MESSAGE)


class Deliver(unittest.TestCase):
    def test_temporary_error_is_retried(self):
        channel = FakeChannel(ConnectionError("timeout"))
        result = deliver_via(channel)
        self.assertEqual((result.status, result.attempts, channel.calls), ("delivered", 2, 2))
        self.assertIsNotNone(result.delivered_at)

    def test_permanent_error_is_not_retried(self):
        channel = FakeChannel(PermanentDeliveryError("bad address"))
        result = deliver_via(channel)
        self.assertEqual((result.status, result.attempts, channel.calls), ("failed", 1, 1))
        self.assertEqual(result.error, "bad address")

    def test_gives_up_after_max_attempts_with_the_last_error(self):
        errors = [ConnectionError(f"try {n}") for n in range(1, config.MAX_ATTEMPTS + 2)]
        channel = FakeChannel(*errors)
        with patch.dict("notification_service.dispatcher.CHANNELS", {"fake": channel}):
            with patch("notification_service.dispatcher.time.sleep") as sleep:
                result = deliver(RECIPIENT, MESSAGE)
        # The backoff the docs promise: 2 s, 4 s, ...
        waits = [call(2**n) for n in range(1, config.MAX_ATTEMPTS)]
        self.assertEqual(sleep.call_args_list, waits)
        self.assertEqual(result.status, "failed")
        self.assertEqual((result.attempts, channel.calls), (config.MAX_ATTEMPTS,) * 2)
        self.assertEqual(result.error, f"try {config.MAX_ATTEMPTS}")
        self.assertIsNone(result.delivered_at)

    def test_unknown_channel_fails_without_trying(self):
        result = deliver(RECIPIENT.model_copy(update={"channel": "pigeon"}), MESSAGE)
        self.assertEqual((result.status, result.attempts), ("failed", 0))
        self.assertIn("pigeon", result.error)
