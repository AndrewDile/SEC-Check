"""Email over SMTP, with the standard library. Works with any SMTP server: Gmail or Outlook with
an app password, a school account, SES's SMTP interface, or Mailpit in tests."""

import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from notification_service import config
from notification_service.channels.base import Channel, Message, PermanentDeliveryError
from notification_service.models import Recipient


class EmailChannel(Channel):
    name = "email"

    def send(self, recipient: Recipient, message: Message) -> None:
        if not config.SMTP_HOST or not config.SMTP_FROM:
            raise PermanentDeliveryError("email isn't set up: set SMTP_HOST and SMTP_FROM")
        email = EmailMessage()
        email["From"] = config.SMTP_FROM
        email["To"] = recipient.address
        email["Subject"] = message.subject
        email["Date"] = formatdate(localtime=False)
        email["Message-ID"] = make_msgid(domain=config.SMTP_FROM.rpartition("@")[2] or None)
        email.set_content(message.body)
        try:
            with connect() as smtp:
                if config.SMTP_USER:
                    smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
                smtp.send_message(email)
        except smtplib.SMTPNotSupportedError as e:
            raise PermanentDeliveryError(f"SMTP server doesn't support this: {e}") from e
        except smtplib.SMTPRecipientsRefused as e:
            raise PermanentDeliveryError(f"recipient refused: {e.recipients}") from e
        except smtplib.SMTPAuthenticationError as e:
            raise PermanentDeliveryError(f"SMTP login failed ({e.smtp_code})") from e
        except smtplib.SMTPResponseException as e:
            # 5xx is a permanent refusal; 4xx (and anything else) may work later
            if 500 <= e.smtp_code < 600:
                raise PermanentDeliveryError(f"SMTP server refused: {e.smtp_code}") from e
            raise
        # Connection errors and timeouts propagate, and are retried


def connect() -> smtplib.SMTP:
    """An SMTP connection, encrypted as SMTP_SECURITY says."""
    host, port, timeout = config.SMTP_HOST, config.SMTP_PORT, config.HTTP_TIMEOUT_S
    if config.SMTP_SECURITY == "ssl":
        return smtplib.SMTP_SSL(host, port, timeout=timeout)
    smtp = smtplib.SMTP(host, port, timeout=timeout)
    if config.SMTP_SECURITY == "starttls":
        try:
            smtp.starttls()
        except BaseException:
            smtp.close()
            raise
    return smtp
