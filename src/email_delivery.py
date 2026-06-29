from __future__ import annotations

import base64
import logging
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path

import httpx

from src.config import EmailSettings

logger = logging.getLogger(__name__)

_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"


def _build_daily_subject(log_date: date, settings: EmailSettings) -> str:
    return settings.daily_subject.format(date=log_date.isoformat())


def _build_monthly_subject(year: int, month: int, settings: EmailSettings) -> str:
    return settings.monthly_subject.format(year=year, month=month)


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".md":
        return "text/markdown"
    if suffix == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/octet-stream"


def _format_from_address(settings: EmailSettings) -> str:
    if settings.from_name:
        return f"{settings.from_name} <{settings.from_address}>"
    return settings.from_address


def _send_via_sendgrid(
    *,
    settings: EmailSettings,
    subject: str,
    body: str,
    attachments: list[Path],
) -> dict:
    payload: dict = {
        "personalizations": [{"to": [{"email": address} for address in settings.to_addresses]}],
        "from": {"email": settings.from_address},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }
    if settings.from_name:
        payload["from"]["name"] = settings.from_name

    payload["attachments"] = [
        {
            "content": base64.b64encode(path.read_bytes()).decode("ascii"),
            "filename": path.name,
            "type": _guess_mime_type(path),
            "disposition": "attachment",
        }
        for path in attachments
    ]

    try:
        response = httpx.post(
            _SENDGRID_URL,
            headers={
                "Authorization": f"Bearer {settings.sendgrid_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text.strip() or str(exc)
        logger.error("SendGrid API error: %s", detail)
        return {"sent": False, "reason": "sendgrid_error", "error": detail}
    except Exception as exc:
        logger.error("Failed to send report email via SendGrid: %s", exc)
        return {"sent": False, "reason": "sendgrid_error", "error": str(exc)}

    logger.info(
        "Report email sent via SendGrid to %s (%d attachment(s))",
        ", ".join(settings.to_addresses),
        len(attachments),
    )
    return {
        "sent": True,
        "provider": "sendgrid",
        "recipients": settings.to_addresses,
        "attachments": [path.name for path in attachments],
    }


def _send_via_smtp(
    *,
    settings: EmailSettings,
    subject: str,
    body: str,
    attachments: list[Path],
) -> dict:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _format_from_address(settings)
    message["To"] = ", ".join(settings.to_addresses)
    message.set_content(body)

    for path in attachments:
        message.add_attachment(
            path.read_bytes(),
            maintype="application",
            subtype="octet-stream",
            filename=path.name,
        )

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
            if settings.use_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    except Exception as exc:
        logger.error("Failed to send report email via SMTP: %s", exc)
        return {"sent": False, "reason": "smtp_error", "error": str(exc)}

    logger.info(
        "Report email sent via SMTP to %s (%d attachment(s))",
        ", ".join(settings.to_addresses),
        len(attachments),
    )
    return {
        "sent": True,
        "provider": "smtp",
        "recipients": settings.to_addresses,
        "attachments": [path.name for path in attachments],
    }


def send_report_email(
    *,
    settings: EmailSettings,
    subject: str,
    body: str,
    attachments: list[Path],
) -> dict:
    """Send a report email with optional file attachments."""
    if not settings.enabled:
        return {"sent": False, "reason": "email_disabled"}

    existing = [path for path in attachments if path.exists()]
    missing = [str(path) for path in attachments if not path.exists()]
    if missing:
        logger.warning("Skipping missing attachment(s): %s", ", ".join(missing))

    if not existing:
        return {"sent": False, "reason": "no_attachments"}

    if settings.provider == "sendgrid":
        return _send_via_sendgrid(
            settings=settings,
            subject=subject,
            body=body,
            attachments=existing,
        )

    return _send_via_smtp(
        settings=settings,
        subject=subject,
        body=body,
        attachments=existing,
    )


def send_daily_report_email(
    report_path: Path,
    log_date: date,
    settings: EmailSettings,
    article_count: int | None = None,
) -> dict:
    """Email a newly generated daily markdown report."""
    count_line = (
        f"총 {article_count}건의 기사/논문이 포함되어 있습니다.\n"
        if article_count is not None
        else ""
    )
    body = (
        f"Tech Market Monitor 데일리 리서치 로그 ({log_date.isoformat()})\n\n"
        f"{count_line}"
        "첨부된 Markdown 파일을 확인해 주세요.\n"
    )
    return send_report_email(
        settings=settings,
        subject=_build_daily_subject(log_date, settings),
        body=body,
        attachments=[report_path],
    )


def send_monthly_report_email(
    report_path_en: Path,
    report_path_ko: Path,
    year: int,
    month: int,
    settings: EmailSettings,
    entry_count: int | None = None,
) -> dict:
    """Email newly generated monthly Word reports (English + Korean)."""
    period = f"{year}-{month:02d}"
    count_line = (
        f"데일리 로그 {entry_count}건을 집계했습니다.\n"
        if entry_count is not None
        else ""
    )
    body = (
        f"Tech Market Monitor 월간 보고서 ({period})\n\n"
        f"{count_line}"
        "첨부: 영문·한국어 Word 보고서(.docx)\n"
    )
    return send_report_email(
        settings=settings,
        subject=_build_monthly_subject(year, month, settings),
        body=body,
        attachments=[report_path_en, report_path_ko],
    )
