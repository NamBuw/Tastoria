"""Outgoing mail (A09). SMTP in deployment (dev: Mailpit on 127.0.0.1:1025); `log` writes to the log only."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from tastoria.core.config import Settings

log = logging.getLogger("tastoria.mail")


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.s.mail_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=10) as smtp:
            if self.s.smtp_starttls:
                smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password or "")
            smtp.send_message(msg)


class LogMailer:
    """Records that a mail would be sent, without its body (the body holds a reset token)."""

    def send(self, to: str, subject: str, body: str) -> None:
        log.info("mail not sent (mailer=log)", extra={"mail_subject": subject})


def make_mailer(settings: Settings) -> Mailer:
    return SmtpMailer(settings) if settings.mailer == "smtp" else LogMailer()
