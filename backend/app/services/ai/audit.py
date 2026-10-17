"""AI audit logging. Every AI request writes exactly one row, with secrets redacted."""

import re
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_audit_log import AIAuditLog
from app.services.ai.permissions import UserContext

logger = structlog.get_logger(__name__)

MAX_LOGGED_MESSAGE_CHARS = 2000

_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    # JWTs / bearer tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"), "[REDACTED_TOKEN]"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{16,}"), "Bearer [REDACTED_TOKEN]"),
    # Indian PAN (ABCDE1234F) and IFSC (ABCD0123456)
    (re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), "[REDACTED_PAN]"),
    (re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b"), "[REDACTED_IFSC]"),
    # Bank account / card-like digit runs
    (re.compile(r"\b\d{9,18}\b"), "[REDACTED_NUMBER]"),
    # "password: xyz", "pwd=xyz"
    (re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*\S+"), r"\1: [REDACTED]"),
]


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    if len(text) > MAX_LOGGED_MESSAGE_CHARS:
        text = text[:MAX_LOGGED_MESSAGE_CHARS] + "…"
    return text


@dataclass
class AuditEvent:
    message: str
    intent: str | None = None
    agent: str | None = None
    tool_name: str | None = None
    action_status: str = "SUCCESS"
    records_accessed: list[str] = field(default_factory=list)
    error_code: str | None = None
    latency_ms: int | None = None


async def write_audit_log(db: AsyncSession, user: UserContext, event: AuditEvent) -> None:
    """Persist an audit row. Never raises: a logging failure must not break the user's request."""
    try:
        db.add(
            AIAuditLog(
                user_id=user.id,
                role=user.role.value,
                message=redact(event.message),
                intent=event.intent,
                agent=event.agent,
                tool_name=event.tool_name,
                action_status=event.action_status,
                records_accessed=event.records_accessed or None,
                error_code=event.error_code,
                latency_ms=event.latency_ms,
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        logger.exception("ai_audit_log_write_failed", user_id=user.id, intent=event.intent)
