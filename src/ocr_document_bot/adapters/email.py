"""IMAP/SMTP transport boundary for OCR Bot.

This module owns mail parsing, access control and durable delivery state only.
Recognition and rendering are supplied as a small application service, keeping
the email transport independent from Vision and Telegram.
"""

from __future__ import annotations

from dataclasses import dataclass
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses
from hashlib import sha256
import imaplib
from pathlib import Path
import os
import re
import smtplib
import sqlite3
from typing import Iterable, Protocol

from ocr_document_bot.document_model import Document
from ocr_document_bot.domain import InputFile
from ocr_document_bot.output_policy import OutputDecision, OutputFormat, OutputPolicy
from ocr_document_bot.renderers import DocxRenderer


_MIME_BY_EXTENSION = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff", ".pdf": "application/pdf"}
_MESSAGE_ID = re.compile(r"^<[^\r\n<>]+>$")


class EmailConfigurationError(ValueError):
    """Email adapter configuration is incomplete or unsafe."""


@dataclass(frozen=True)
class EmailConfig:
    imap_host: str
    imap_port: int
    imap_ssl: bool
    smtp_host: str
    smtp_port: int
    smtp_ssl: bool
    smtp_starttls: bool
    username: str
    password: str
    address: str
    allowed_senders: frozenset[str]
    poll_interval_seconds: int = 60
    imap_folder: str = "INBOX"
    max_attachments: int = 5
    max_attachment_bytes: int = 10 * 1024 * 1024
    state_path: Path = Path("local-state/email-adapter.sqlite3")

    @classmethod
    def from_env(cls) -> "EmailConfig":
        required = {name: os.getenv(name, "").strip() for name in ("OCR_EMAIL_IMAP_HOST", "OCR_EMAIL_SMTP_HOST", "OCR_EMAIL_USERNAME", "OCR_EMAIL_PASSWORD", "OCR_EMAIL_ADDRESS")}
        if missing := [name for name, value in required.items() if not value]:
            raise EmailConfigurationError(f"Missing email settings: {', '.join(missing)}")
        allowed = frozenset(normalized for raw in os.getenv("OCR_EMAIL_ALLOWED_SENDERS", "").split(",") if raw.strip() and (normalized := normalize_address(raw)))
        if not allowed:
            raise EmailConfigurationError("OCR_EMAIL_ALLOWED_SENDERS must contain at least one exact address")
        address = normalize_address(required["OCR_EMAIL_ADDRESS"])
        if not address:
            raise EmailConfigurationError("OCR_EMAIL_ADDRESS must be a single valid address")
        return cls(
            imap_host=required["OCR_EMAIL_IMAP_HOST"], imap_port=_positive_env("OCR_EMAIL_IMAP_PORT", 993), imap_ssl=_bool_env("OCR_EMAIL_IMAP_SSL", True),
            smtp_host=required["OCR_EMAIL_SMTP_HOST"], smtp_port=_positive_env("OCR_EMAIL_SMTP_PORT", 465), smtp_ssl=_bool_env("OCR_EMAIL_SMTP_SSL", True), smtp_starttls=_bool_env("OCR_EMAIL_SMTP_STARTTLS", False),
            username=required["OCR_EMAIL_USERNAME"], password=required["OCR_EMAIL_PASSWORD"], address=address, allowed_senders=allowed,
            poll_interval_seconds=_positive_env("OCR_EMAIL_POLL_INTERVAL_SECONDS", 60), imap_folder=os.getenv("OCR_EMAIL_IMAP_FOLDER", "INBOX"),
            max_attachments=_positive_env("OCR_EMAIL_MAX_ATTACHMENTS", 5), max_attachment_bytes=_positive_env("OCR_EMAIL_MAX_ATTACHMENT_BYTES", 10 * 1024 * 1024),
            state_path=Path(os.getenv("OCR_EMAIL_STATE_PATH", "local-state/email-adapter.sqlite3")),
        )


@dataclass(frozen=True)
class InboundMail:
    uid: str
    raw: bytes


@dataclass(frozen=True)
class ProcessedDocument:
    document: Document
    decision: OutputDecision


@dataclass(frozen=True)
class AttachmentResult:
    filename: str
    inline_text: str | None = None
    docx: bytes | None = None
    error: str | None = None


class Mailbox(Protocol):
    def list_unseen_uids(self) -> Iterable[str]: ...
    def fetch_unseen(self, *, after_uid: int | None = None) -> Iterable[InboundMail]: ...
    def mark_seen(self, uid: str) -> None: ...
    def reconnect(self) -> None: ...


class Mailer(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class DocumentProcessor(Protocol):
    def process(self, input_file: InputFile) -> ProcessedDocument: ...
    def render_docx(self, document: Document) -> bytes: ...


class EmailOCRService:
    """Thin use-case adapter over the shared OCR service and OutputPolicy."""

    def __init__(self, ocr_service, *, policy: OutputPolicy | None = None, renderer: DocxRenderer | None = None) -> None:
        self._ocr_service = ocr_service
        self._policy = policy or OutputPolicy()
        self._renderer = renderer or DocxRenderer()

    def process(self, input_file: InputFile) -> ProcessedDocument:
        document = self._ocr_service.process(input_file)
        return ProcessedDocument(document=document, decision=self._policy.decide(document))

    def render_docx(self, document: Document) -> bytes:
        from io import BytesIO
        output = BytesIO()
        self._renderer.render(document).save(output)
        return output.getvalue()


class EmailStateStore:
    """Conservative at-most-once delivery ledger persisted across restarts."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS email_delivery (key TEXT PRIMARY KEY, state TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS email_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def claim(self, key: str) -> bool:
        with self._connect() as db:
            try:
                db.execute("INSERT INTO email_delivery(key, state) VALUES (?, 'claimed')", (key,))
            except sqlite3.IntegrityError:
                return False
        return True

    def mark_sending(self, key: str) -> None:
        self._set(key, "sending")

    def mark_sent(self, key: str) -> None:
        self._set(key, "sent")

    def mark_uncertain(self, key: str) -> None:
        self._set(key, "uncertain")

    def state(self, key: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT state FROM email_delivery WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def baseline_uid(self) -> int | None:
        with self._connect() as db:
            row = db.execute("SELECT value FROM email_metadata WHERE key = 'imap_baseline_uid'").fetchone()
        return int(row[0]) if row else None

    def set_baseline_uid(self, uid: int) -> None:
        with self._connect() as db:
            db.execute("INSERT OR REPLACE INTO email_metadata(key, value) VALUES ('imap_baseline_uid', ?)", (str(uid),))

    def _set(self, key: str, state: str) -> None:
        with self._connect() as db:
            db.execute("UPDATE email_delivery SET state = ? WHERE key = ?", (state, key))

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)


class IMAPMailbox:
    """Small standard-library IMAP client; connects only when polling starts."""

    def __init__(self, config: EmailConfig) -> None:
        self._config = config
        self._client: imaplib.IMAP4 | None = None

    def reconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
        self._client = imaplib.IMAP4_SSL(self._config.imap_host, self._config.imap_port) if self._config.imap_ssl else imaplib.IMAP4(self._config.imap_host, self._config.imap_port)
        if not self._config.imap_ssl:
            self._client.starttls()
        self._client.login(self._config.username, self._config.password)

    def list_unseen_uids(self) -> Iterable[str]:
        client = self._require_client()
        status, _ = client.select(self._config.imap_folder)
        if status != "OK":
            raise imaplib.IMAP4.error("Cannot select IMAP folder")
        status, data = client.uid("search", None, "UNSEEN")
        if status != "OK":
            raise imaplib.IMAP4.error("Cannot search IMAP folder")
        return (uid.decode() for uid in data[0].split())

    def fetch_unseen(self, *, after_uid: int | None = None) -> Iterable[InboundMail]:
        client = self._require_client()
        status, _ = client.select(self._config.imap_folder)
        if status != "OK":
            raise imaplib.IMAP4.error("Cannot select IMAP folder")
        criterion = "UNSEEN" if after_uid is None else f"UID {after_uid + 1}:* UNSEEN"
        status, data = client.uid("search", None, criterion)
        if status != "OK":
            raise imaplib.IMAP4.error("Cannot search IMAP folder")
        for uid in data[0].split():
            status, response = client.uid("fetch", uid, "(RFC822)")
            if status == "OK" and response and isinstance(response[0], tuple):
                yield InboundMail(uid=uid.decode(), raw=response[0][1])

    def mark_seen(self, uid: str) -> None:
        status, _ = self._require_client().uid("store", uid, "+FLAGS", "(\\Seen)")
        if status != "OK":
            raise imaplib.IMAP4.error("Cannot mark message as seen")

    def _require_client(self) -> imaplib.IMAP4:
        if self._client is None:
            self.reconnect()
        assert self._client is not None
        return self._client


class SMTPMailer:
    def __init__(self, config: EmailConfig) -> None:
        self._config = config

    def send(self, message: EmailMessage) -> None:
        client = smtplib.SMTP_SSL(self._config.smtp_host, self._config.smtp_port, timeout=30) if self._config.smtp_ssl else smtplib.SMTP(self._config.smtp_host, self._config.smtp_port, timeout=30)
        try:
            if self._config.smtp_starttls and not self._config.smtp_ssl:
                client.starttls()
            client.login(self._config.username, self._config.password)
            client.send_message(message)
        finally:
            try:
                client.quit()
            except (smtplib.SMTPException, OSError):
                pass


class EmailAdapter:
    """Coordinates authenticated mail transport without embedding OCR logic."""

    def __init__(self, config: EmailConfig, mailbox: Mailbox, mailer: Mailer, processor: DocumentProcessor, state: EmailStateStore) -> None:
        self._config, self._mailbox, self._mailer, self._processor, self._state = config, mailbox, mailer, processor, state

    def poll_once(self) -> int:
        try:
            messages = list(self._mailbox.fetch_unseen(after_uid=self._state.baseline_uid()))
        except (imaplib.IMAP4.abort, OSError):
            self._mailbox.reconnect()
            return 0
        for inbound in messages:
            self._handle(inbound)
        return len(messages)

    def establish_baseline(self) -> int:
        """Persist the current UID watermark without fetching or changing mail."""
        current = self._state.baseline_uid()
        if current is not None:
            return current
        try:
            uids = [int(uid) for uid in self._mailbox.list_unseen_uids()]
        except (imaplib.IMAP4.abort, OSError):
            self._mailbox.reconnect()
            raise
        baseline = max(uids, default=0)
        self._state.set_baseline_uid(baseline)
        return baseline

    def _handle(self, inbound: InboundMail) -> None:
        message = BytesParser(policy=policy.default).parsebytes(inbound.raw)
        sender = normalize_address(message.get("From", ""))
        if self._is_automatic(message) or sender not in self._config.allowed_senders or sender == self._config.address:
            self._mailbox.mark_seen(inbound.uid)
            return
        key = _message_key(message, inbound.uid)
        if not self._state.claim(key):
            self._mailbox.mark_seen(inbound.uid)
            return
        results = self._process_attachments(message)
        reply = _build_reply(message, sender, self._config.address, results)
        self._state.mark_sending(key)
        try:
            self._mailer.send(reply)
        except (smtplib.SMTPException, OSError, TimeoutError):
            self._state.mark_uncertain(key)
            raise
        self._state.mark_sent(key)
        self._mailbox.mark_seen(inbound.uid)

    def _process_attachments(self, message: EmailMessage) -> list[AttachmentResult]:
        all_attachments = list(message.iter_attachments())
        attachments = all_attachments[:self._config.max_attachments]
        results: list[AttachmentResult] = []
        for attachment in attachments:
            filename = Path(attachment.get_filename() or "attachment").name
            mime_type = _MIME_BY_EXTENSION.get(Path(filename).suffix.lower())
            payload = attachment.get_payload(decode=True) or b""
            if not mime_type:
                results.append(AttachmentResult(filename, error="unsupported file type"))
            elif not payload or len(payload) > self._config.max_attachment_bytes:
                results.append(AttachmentResult(filename, error="attachment is empty or exceeds configured size"))
            else:
                try:
                    processed = self._processor.process(InputFile(filename, mime_type, payload, "email"))
                    if processed.decision.format is OutputFormat.INLINE_TEXT:
                        results.append(AttachmentResult(filename, inline_text=processed.decision.text or ""))
                    else:
                        results.append(AttachmentResult(filename, docx=self._processor.render_docx(processed.document)))
                except Exception:
                    results.append(AttachmentResult(filename, error="could not process attachment"))
        if not attachments:
            results.append(AttachmentResult("attachments", error="no supported attachments found"))
        elif len(all_attachments) > self._config.max_attachments:
            results.append(AttachmentResult("remaining attachments", error="attachment count exceeds configured limit"))
        return results

    @staticmethod
    def _is_automatic(message: EmailMessage) -> bool:
        return message.get("Auto-Submitted", "no").lower() != "no" or message.get("Precedence", "").lower() in {"bulk", "junk", "list"} or bool(message.get("X-OCR-Document-Bot"))


def normalize_address(value: str) -> str | None:
    parsed = getaddresses([value])
    if len(parsed) != 1:
        return None
    _, address = parsed[0]
    candidate = address.strip()
    if not candidate or "@" not in candidate or (candidate != value.strip() and "<" not in value):
        return None
    return candidate.casefold()


def _message_key(message: EmailMessage, uid: str) -> str:
    message_id = message.get("Message-ID", "")
    stable = message_id if _MESSAGE_ID.fullmatch(message_id.strip()) else f"uid:{uid}:{sha256(message.as_bytes()).hexdigest()}"
    return sha256(stable.encode()).hexdigest()


def _build_reply(source: EmailMessage, recipient: str, sender: str, results: list[AttachmentResult]) -> EmailMessage:
    reply = EmailMessage()
    reply["From"], reply["To"], reply["Subject"] = sender, recipient, f"Re: {source.get('Subject', 'OCR result')}"
    source_id = source.get("Message-ID", "").strip()
    if _MESSAGE_ID.fullmatch(source_id):
        reply["In-Reply-To"] = source_id
        reply["References"] = f"{source.get('References', '').strip()} {source_id}".strip()
    reply["X-OCR-Document-Bot"] = "1"
    lines = ["Результаты распознавания:", ""]
    attachments: list[tuple[str, bytes]] = []
    for index, result in enumerate(results, start=1):
        if result.inline_text is not None:
            lines.extend((f"{index}. {result.filename}", result.inline_text, ""))
        elif result.docx is not None:
            filename = f"{Path(result.filename).stem or 'document'}-ocr-{index}.docx"
            lines.extend((f"{index}. {result.filename}: результат приложен как {filename}", ""))
            attachments.append((filename, result.docx))
        else:
            lines.extend((f"{index}. {result.filename}: {result.error or 'not processed'}", ""))
    reply.set_content("\n".join(lines).rstrip() + "\n")
    for filename, content in attachments:
        reply.add_attachment(content, maintype="application", subtype="vnd.openxmlformats-officedocument.wordprocessingml.document", filename=filename)
    return reply


def _positive_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as error:
        raise EmailConfigurationError(f"{name} must be an integer") from error
    if value < 1:
        raise EmailConfigurationError(f"{name} must be positive")
    return value


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise EmailConfigurationError(f"{name} must be a boolean")
