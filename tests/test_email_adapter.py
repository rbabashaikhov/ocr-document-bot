"""Mock-only tests for the IMAP/SMTP transport boundary."""

from __future__ import annotations

from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path
import imaplib
import smtplib

import pytest

from ocr_document_bot.adapters.email import EmailAdapter, EmailConfig, EmailStateStore, InboundMail, ProcessedDocument, normalize_address
from ocr_document_bot.document_model import Document, OCRProvenance, Page, Paragraph, Table
from ocr_document_bot.output_policy import OutputDecision, OutputFormat


class FakeMailbox:
    def __init__(self, messages: list[InboundMail] | None = None, *, abort: bool = False) -> None:
        self.messages, self.abort, self.seen, self.reconnects = messages or [], abort, [], 0

    def list_unseen_uids(self):
        return [message.uid for message in self.messages]

    def fetch_unseen(self, *, after_uid=None):
        if self.abort:
            raise imaplib.IMAP4.abort("lost connection")
        return [message for message in self.messages if after_uid is None or int(message.uid) > after_uid]

    def mark_seen(self, uid: str) -> None:
        self.seen.append(uid)

    def reconnect(self) -> None:
        self.reconnects += 1


class FakeMailer:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.sent = error, []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)
        if self.error:
            raise self.error


class FakeProcessor:
    def __init__(self, *, docx_for: set[str] = frozenset(), fail_for: set[str] = frozenset()) -> None:
        self.docx_for, self.fail_for, self.received = docx_for, fail_for, []

    def process(self, input_file):
        self.received.append(input_file)
        if input_file.filename in self.fail_for:
            raise ValueError("broken")
        provenance = OCRProvenance(provider="test", source_page_number=0, source_order=0, source_type="test")
        elements = [Paragraph(id="p", text=f"text:{input_file.filename}", provenance=provenance)]
        if input_file.filename in self.docx_for:
            elements = [Table(id="t", row_count=0, column_count=0, provenance=provenance)]
        document = Document(source_provider="test", pages=[Page(number=0, elements=elements)])
        decision = OutputDecision(OutputFormat.DOCX, reason="table") if input_file.filename in self.docx_for else OutputDecision(OutputFormat.INLINE_TEXT, text=f"text:{input_file.filename}")
        return ProcessedDocument(document, decision)

    def render_docx(self, document):
        return b"PK fake docx"


def _config(tmp_path: Path) -> EmailConfig:
    return EmailConfig("imap.invalid", 993, True, "smtp.invalid", 465, True, False, "user", "password", "bot@example.test", frozenset({"allowed@example.test"}), state_path=tmp_path / "state.sqlite3")


def _mail(*, sender: str = "Allowed <allowed@example.test>", reply_to: str | None = None, attachments: list[tuple[str, bytes]] = [], automatic: bool = False) -> bytes:
    message = EmailMessage()
    message["From"], message["To"], message["Subject"], message["Message-ID"] = sender, "bot@example.test", "scan", "<source@example.test>"
    if reply_to:
        message["Reply-To"] = reply_to
    if automatic:
        message["Auto-Submitted"] = "auto-replied"
    message.set_content("please process")
    for filename, content in attachments:
        message.add_attachment(content, maintype="image", subtype="jpeg", filename=filename)
    return message.as_bytes()


def _adapter(tmp_path: Path, mail: bytes, *, processor: FakeProcessor | None = None, mailer: FakeMailer | None = None) -> tuple[EmailAdapter, FakeMailbox, FakeMailer, FakeProcessor, EmailStateStore]:
    mailbox, outbound, service = FakeMailbox([InboundMail("1", mail)]), mailer or FakeMailer(), processor or FakeProcessor()
    state = EmailStateStore(tmp_path / "state.sqlite3")
    return EmailAdapter(_config(tmp_path), mailbox, outbound, service, state), mailbox, outbound, service, state


def test_one_short_attachment_returns_inline_text_and_correct_reply_headers(tmp_path: Path) -> None:
    adapter, mailbox, mailer, processor, _ = _adapter(tmp_path, _mail(reply_to="attacker@example.test", attachments=[("one.jpg", b"image")]))
    assert adapter.poll_once() == 1
    assert processor.received[0].source == "email"
    reply = mailer.sent[0]
    assert reply["To"] == "allowed@example.test" and reply["In-Reply-To"] == "<source@example.test>"
    assert reply["References"].endswith("<source@example.test>")
    assert "text:one.jpg" in reply.get_body(preferencelist=("plain",)).get_content()
    assert mailbox.seen == ["1"]


def test_multiple_attachments_keep_results_and_docx_mapping(tmp_path: Path) -> None:
    adapter, _, mailer, processor, _ = _adapter(tmp_path, _mail(attachments=[("short.png", b"a"), ("table.pdf", b"b"), ("script.exe", b"c")]), processor=FakeProcessor(docx_for={"table.pdf"}))
    adapter.poll_once()
    reply = mailer.sent[0]
    assert [item.filename for item in processor.received] == ["short.png", "table.pdf"]
    assert "script.exe: unsupported file type" in reply.get_body(preferencelist=("plain",)).get_content()
    attachment = next(reply.iter_attachments())
    assert attachment.get_filename() == "table-ocr-2.docx" and attachment.get_payload(decode=True) == b"PK fake docx"
    # The transport never writes inbound attachments or outbound DOCX to disk.
    assert sorted(path.name for path in tmp_path.iterdir()) == ["state.sqlite3"]


def test_forbidden_and_automatic_messages_are_not_processed_or_replied(tmp_path: Path) -> None:
    for mail in (_mail(sender="stranger@example.test", attachments=[("one.jpg", b"x")]), _mail(attachments=[("one.jpg", b"x")], automatic=True)):
        adapter, mailbox, mailer, processor, _ = _adapter(tmp_path, mail)
        adapter.poll_once()
        assert not processor.received and not mailer.sent and mailbox.seen == ["1"]


def test_duplicate_message_is_not_reprocessed_after_restart(tmp_path: Path) -> None:
    raw = _mail(attachments=[("one.jpg", b"x")])
    adapter, _, mailer, processor, _ = _adapter(tmp_path, raw)
    adapter.poll_once()
    restarted, _, another_mailer, another_processor, _ = _adapter(tmp_path, raw)
    restarted.poll_once()
    assert len(mailer.sent) == len(processor.received) == 1
    assert not another_mailer.sent and not another_processor.received


def test_smtp_timeout_is_recorded_as_uncertain_and_never_retried(tmp_path: Path) -> None:
    raw = _mail(attachments=[("one.jpg", b"x")])
    adapter, _, _, _, state = _adapter(tmp_path, raw, mailer=FakeMailer(TimeoutError("timeout")))
    with pytest.raises(TimeoutError):
        adapter.poll_once()
    assert state.state(__import__("ocr_document_bot.adapters.email", fromlist=["_message_key"])._message_key(BytesParser().parsebytes(raw), "1")) == "uncertain"
    restarted, _, mailer, processor, _ = _adapter(tmp_path, raw)
    restarted.poll_once()
    assert not mailer.sent and not processor.received


def test_imap_abort_reconnects_without_processing(tmp_path: Path) -> None:
    mailbox, mailer, processor = FakeMailbox(abort=True), FakeMailer(), FakeProcessor()
    adapter = EmailAdapter(_config(tmp_path), mailbox, mailer, processor, EmailStateStore(tmp_path / "state.sqlite3"))
    assert adapter.poll_once() == 0
    assert mailbox.reconnects == 1 and not mailer.sent


def test_baseline_skips_existing_unseen_mail_without_fetching_its_body(tmp_path: Path) -> None:
    raw = _mail(attachments=[("old.jpg", b"x")])
    adapter, mailbox, mailer, processor, state = _adapter(tmp_path, raw)
    assert adapter.establish_baseline() == 1
    assert state.baseline_uid() == 1
    assert adapter.poll_once() == 0
    assert not processor.received and not mailer.sent and mailbox.seen == []


def test_normalization_requires_an_exact_address() -> None:
    assert normalize_address("Allowed <ALLOWED@example.test>") == "allowed@example.test"
    assert normalize_address("not-allowed@example.test.evil") == "not-allowed@example.test.evil"
    assert normalize_address("bad address") is None
