"""Inbound transport boundaries."""

from .telegram import PollingSafetyError, TelegramAdapter, TelegramOCRService
from .email import EmailAdapter, EmailConfig, EmailOCRService, EmailStateStore

__all__ = ["EmailAdapter", "EmailConfig", "EmailOCRService", "EmailStateStore", "PollingSafetyError", "TelegramAdapter", "TelegramOCRService"]
