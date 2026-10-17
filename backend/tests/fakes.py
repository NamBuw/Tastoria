from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SentMail:
    to: str
    subject: str
    body: str


@dataclass
class FakeMailer:
    """Stands in for SMTP (A09) in tests: records messages instead of sending them."""

    sent: list[SentMail] = field(default_factory=list)

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append(SentMail(to, subject, body))
