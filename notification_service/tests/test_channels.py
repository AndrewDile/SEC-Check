"""What each channel sends, and which failures it gives up on (PermanentDeliveryError) or retries."""

import json
import smtplib
import unittest
from unittest.mock import MagicMock, patch

import httpx

from notification_service import config
from notification_service.channels.base import Message, PermanentDeliveryError
from notification_service.channels.email import EmailChannel
from notification_service.channels.slack import SlackChannel
from notification_service.channels.teams import TeamsChannel
from notification_service.models import Recipient

SLACK = "https://hooks.slack.com/services/T0/B0/secret"
TEAMS = "https://prod-01.westus.logic.azure.com:443/workflows/abc/triggers/manual/paths/invoke"
MESSAGE = Message(
    subject="[HIGH] Possible cybersecurity incident: CVE-1: A <bug> & more",
    body="CVE-1: A bug\n\nA summary.\n\nDependencies that may be affected:\n  - Acme Widget",
    claim_url="https://example.com/claim",
)


def to(channel: str, address: str) -> Recipient:
    return Recipient(
        recipient_id="team:LEGAL:1", team_name="LEGAL", channel=channel, address=address
    )


def fake(cls, status: int = 200):
    """The channel, posting to a fake server that answers `status`, and the requests it got."""
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, text="no_service" if status >= 400 else "ok")

    return cls(httpx.Client(transport=httpx.MockTransport(answer))), requests


class Slack(unittest.TestCase):
    def test_posts_a_header_the_escaped_body_and_a_claim_button(self):
        channel, requests = fake(SlackChannel)
        channel.send(to("slack", SLACK), MESSAGE)
        self.assertEqual(str(requests[0].url), SLACK)
        body = json.loads(requests[0].content)
        self.assertEqual(body["text"], MESSAGE.subject)
        header, section, actions = body["blocks"]
        self.assertEqual(header["text"]["text"], MESSAGE.subject)  # plain_text: no escaping
        self.assertIn("Acme Widget", section["text"]["text"])
        self.assertEqual(actions["elements"][0]["url"], "https://example.com/claim")

    def test_escapes_markup_and_keeps_to_block_limits(self):
        long = Message(subject="S" * 200, body="<b> & " * 1000, claim_url="https://e.com/c")
        channel, requests = fake(SlackChannel)
        channel.send(to("slack", SLACK), long)
        header, section, _ = json.loads(requests[0].content)["blocks"]
        self.assertEqual(len(header["text"]["text"]), 150)
        self.assertEqual(len(section["text"]["text"]), 3000)
        self.assertNotIn("<b>", section["text"]["text"])
        self.assertIn("&lt;b&gt; &amp;", section["text"]["text"])

    def test_gives_up_on_a_removed_webhook_or_bad_payload(self):
        for status in (400, 403, 404, 410, 302):
            with self.subTest(status=status):
                channel, _ = fake(SlackChannel, status)
                with self.assertRaises(PermanentDeliveryError):
                    channel.send(to("slack", SLACK), MESSAGE)

    def test_retries_when_rate_limited_or_down(self):
        for status in (429, 500, 503):
            with self.subTest(status=status):
                channel, _ = fake(SlackChannel, status)
                with self.assertRaises(Exception) as caught:
                    channel.send(to("slack", SLACK), MESSAGE)
                self.assertNotIsInstance(caught.exception, PermanentDeliveryError)

    def test_never_posts_to_another_host(self):
        for address in (
            "http://hooks.slack.com/services/x",
            "https://hooks.slack.com.evil.com/services/x",
            "https://user@hooks.slack.com/services/x",
            "http://api:3001/system/reset",
        ):
            with self.subTest(address=address):
                channel, requests = fake(SlackChannel)
                with self.assertRaises(PermanentDeliveryError):
                    channel.send(to("slack", address), MESSAGE)
                self.assertEqual(requests, [])


class Teams(unittest.TestCase):
    def test_posts_an_adaptive_card_with_a_claim_action(self):
        channel, requests = fake(TeamsChannel, 202)
        channel.send(to("ms_teams", TEAMS), MESSAGE)
        body = json.loads(requests[0].content)
        self.assertEqual(body["type"], "message")
        attachment = body["attachments"][0]
        self.assertEqual(attachment["contentType"], "application/vnd.microsoft.card.adaptive")
        card = attachment["content"]
        texts = [block["text"] for block in card["body"]]
        self.assertEqual(texts[0], MESSAGE.subject)
        self.assertIn("  - Acme Widget", texts)
        self.assertNotIn("", texts)  # blank lines become spacing, not empty blocks
        self.assertEqual(card["actions"][0]["url"], "https://example.com/claim")

    def test_never_posts_to_another_host(self):
        for address in (SLACK, "https://evil.com/logic.azure.com", "http://x.logic.azure.com/w"):
            with self.subTest(address=address):
                channel, requests = fake(TeamsChannel, 202)
                with self.assertRaises(PermanentDeliveryError):
                    channel.send(to("ms_teams", address), MESSAGE)
                self.assertEqual(requests, [])

    def test_gives_up_on_a_removed_webhook(self):
        channel, _ = fake(TeamsChannel, 404)
        with self.assertRaises(PermanentDeliveryError):
            channel.send(to("ms_teams", TEAMS), MESSAGE)


SMTP_SETTINGS = {
    "SMTP_HOST": "smtp.example.com",
    "SMTP_PORT": 587,
    "SMTP_SECURITY": "starttls",
    "SMTP_USER": "alerts@example.com",
    "SMTP_PASSWORD": "app-password",
    "SMTP_FROM": "alerts@example.com",
}


class Email(unittest.TestCase):
    def setUp(self):
        for name, value in SMTP_SETTINGS.items():
            patcher = patch.object(config, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.smtp = MagicMock()
        self.smtp.__enter__.return_value = self.smtp
        patcher = patch("notification_service.channels.email.smtplib.SMTP", return_value=self.smtp)
        self.SMTP = patcher.start()
        self.addCleanup(patcher.stop)

    def send(self):
        EmailChannel().send(to("email", "legal@example.com"), MESSAGE)

    def test_sends_over_starttls_after_logging_in(self):
        self.send()
        self.SMTP.assert_called_once_with("smtp.example.com", 587, timeout=config.HTTP_TIMEOUT_S)
        self.smtp.starttls.assert_called_once()
        self.smtp.login.assert_called_once_with("alerts@example.com", "app-password")
        email = self.smtp.send_message.call_args.args[0]
        self.assertEqual(email["To"], "legal@example.com")
        self.assertEqual(email["From"], "alerts@example.com")
        self.assertEqual(email["Subject"], MESSAGE.subject)
        self.assertIn("Acme Widget", email.get_content())

    def test_without_a_login_or_encryption(self):
        with patch.object(config, "SMTP_USER", ""), patch.object(config, "SMTP_SECURITY", "none"):
            self.send()
        self.smtp.starttls.assert_not_called()
        self.smtp.login.assert_not_called()
        self.smtp.send_message.assert_called_once()

    def test_gives_up_when_not_set_up_or_refused(self):
        refusals = [
            smtplib.SMTPRecipientsRefused({"legal@example.com": (550, b"no such user")}),
            smtplib.SMTPAuthenticationError(535, b"bad credentials"),
            smtplib.SMTPDataError(554, b"rejected"),
        ]
        for error in refusals:
            with self.subTest(error=type(error).__name__):
                self.smtp.send_message.side_effect = error
                with self.assertRaises(PermanentDeliveryError):
                    self.send()
        with patch.object(config, "SMTP_HOST", ""):
            with self.assertRaises(PermanentDeliveryError):
                self.send()

    def test_retries_a_temporary_failure(self):
        for error in (smtplib.SMTPDataError(451, b"try later"), ConnectionRefusedError()):
            with self.subTest(error=type(error).__name__):
                self.smtp.send_message.side_effect = error
                with self.assertRaises(Exception) as caught:
                    self.send()
                self.assertNotIsInstance(caught.exception, PermanentDeliveryError)
