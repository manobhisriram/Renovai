"""Notification abstraction (e-mail). Defaults to structured logging when SMTP is not configured."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.config import Settings

log = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, to: str, subject: str, body: str) -> bool: ...


class LogNotifier:
    def send(self, to: str, subject: str, body: str) -> bool:
        log.info("notification (log-only; SMTP not configured): to=%s subject=%s", to, subject)
        return True


class SmtpNotifier:
    def __init__(self, settings: Settings):
        self.s = settings

    def send(self, to: str, subject: str, body: str) -> bool:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.smtp_from, to, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.s.smtp_host or "", self.s.smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if self.s.smtp_username and self.s.smtp_password:
                    smtp.login(self.s.smtp_username, self.s.smtp_password.get_secret_value())
                smtp.send_message(msg)
            return True
        except Exception as exc:
            log.warning("smtp send failed: %s", type(exc).__name__)
            return False


def build_notifier(settings: Settings) -> Notifier:
    return SmtpNotifier(settings) if settings.smtp_host else LogNotifier()
