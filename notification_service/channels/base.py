"""The interface every notification channel (email, SMS, Microsoft Teams, ...) implements."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core_api_contract import Recipient


@dataclass
class Message:
    """A rendered notification. It is the same for every channel; channels may reformat it."""

    subject: str
    body: str
    claim_url: str


class PermanentDeliveryError(Exception):
    """Raised by a channel when trying again cannot help, e.g. the address is invalid."""


class Channel(ABC):
    """A way to reach a team.

    To add a channel, subclass this, set `name` to the value the Core API uses in
    Recipient.channel, and add an instance to CHANNELS in channels/__init__.py.
    """

    name: str

    @abstractmethod
    def send(self, recipient: Recipient, message: Message) -> None:
        """Deliver `message` to `recipient.address`.

        Raise PermanentDeliveryError if trying again cannot help. Any other
        exception counts as temporary, and the send is retried.
        """
