import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import error_response, success_response
from app.db.session import get_db
from app.models.employee import Employee
from app.schemas.ai import (
    ActionChatData,
    ActionConfirmRequest,
    AIActionRequest,
    AIChatRequest,
    PolicyChatData,
    PolicyIndexStatsOut,
    PolicySourceOut,
    SQLChatData,
)
from app.services.ai.action_agent import ActionResult, confirm_pending_action, run_action_agent
from app.schemas.chat import ChatMessageCreate, ChatSessionCreate
from app.services.ai.audit import AuditEvent, write_audit_log
from app.services.ai.errors import AIRequestError
from app.services.ai.llm import LLMClient, LLMError, LLMNotConfigured, LLMRateLimited, get_llm_client
from app.services.ai.permissions import Capability, PermissionDenied, UserContext, load_user_context
from app.services.ai.policy_rag import PolicyRAGService, get_policy_rag_service
from app.services.ai.sql_agent import answer_sql_question
from app.services.auth import get_current_user, oauth2_scheme

router = APIRouter()
logger = structlog.get_logger(__name__)


async def get_policy_rag() -> PolicyRAGService:
    # Loading the embedding model is slow and blocking on first use; keep it off the event loop.
    return await asyncio.to_thread(get_policy_rag_service)


def get_llm() -> LLMClient | None:
    """Resolve the LLM lazily so a missing API key becomes a clean 503 instead of a crash."""
    try:
        return get_llm_client()
    except LLMNotConfigured:
        return None


def _require_llm(llm: LLMClient | None) -> LLMClient:
    if llm is None:
        raise LLMNotConfigured()
    return llm


async def _run_ai_request(
    db: AsyncSession,
    user: UserContext,
    event: AuditEvent,
    work: Callable[[], Awaitable[dict[str, Any]]],
):
    """Run one AI request: map every failure to a safe response and always write one audit row.

    ``work`` returns the response data and may update ``event`` (status, records accessed).
    """
    started = time.perf_counter()
    status_code, code, message = 200, None, None
    try:
        data = await work()
    except PermissionDenied as exc:
        event.action_status, status_code, code, message = "DENIED", 403, "FORBIDDEN", exc.message
    except AIRequestError as exc:
        event.action_status, status_code, code, message = exc.audit_status, exc.status_code, exc.code, exc.message
    except LLMNotConfigured:
        event.action_status, status_code, code = "ERROR", 503, "AI_NOT_CONFIGURED"
        message = "The AI assistant is not configured on this server."
    except LLMRateLimited:
        logger.warning("ai_rate_limited", user_id=user.id, intent=event.intent)
        event.action_status, status_code, code = "ERROR", 429, "AI_RATE_LIMITED"
        message = "The AI service is busy right now. Please wait a few seconds and try again."
    except LLMError as exc:
        logger.warning("ai_upstream_error", user_id=user.id, intent=event.intent, error=str(exc), cause=repr(exc.__cause__)[:300])
        event.action_status, status_code, code = "ERROR", 502, "AI_UPSTREAM_ERROR"
        message = "The AI assistant is temporarily unavailable. Please try again."
    except Exception:  # noqa: BLE001 - never leak internals; always audit
        logger.exception("ai_request_failed", user_id=user.id, intent=event.intent)
        event.action_status, status_code, code = "ERROR", 500, "AI_INTERNAL_ERROR"
        message = "Something went wrong while answering. Please try again."

    event.error_code = code
    event.latency_ms = int((time.perf_counter() - started) * 1000)
    await write_audit_log(db, user, event)
    if code is not None:
        return JSONResponse(status_code=status_code, content=error_response(code, message or ""))
    return success_response(data)


@router.post("/policy")
async def chat_policy(
    payload: AIChatRequest,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    rag: PolicyRAGService = Depends(get_policy_rag),
    llm: LLMClient | None = Depends(get_llm),
):
    user = await load_user_context(db, current_user)
    event = AuditEvent(message=payload.message, intent="POLICY_QA", agent="policy_rag", tool_name="policy_vector_search")

    async def work() -> dict[str, Any]:
        user.require(Capability.POLICY_QA)
        result = await rag.answer(db, _require_llm(llm), payload.message)
        event.action_status = "ANSWERED" if result.grounded else "NO_ANSWER"
        event.records_accessed = result.chunk_ids
        return PolicyChatData(
            answer=result.answer,
            grounded=result.grounded,
            sources=[PolicySourceOut(title=s.title, category=s.category, filename=s.filename) for s in result.sources],
        ).model_dump()

    return await _run_ai_request(db, user, event, work)


@router.post("/policy/reindex")
async def reindex_policies(
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    rag: PolicyRAGService = Depends(get_policy_rag),
):
    user = await load_user_context(db, current_user)
    event = AuditEvent(message="[reindex policies]", intent="ADMIN", agent="policy_rag", tool_name="policy_reindex")

    async def work() -> dict[str, Any]:
        user.require(Capability.REINDEX_POLICIES)
        stats = await rag.sync_index(db, force=True)
        event.action_status = "SUCCESS"
        return PolicyIndexStatsOut(**stats.__dict__).model_dump()

    return await _run_ai_request(db, user, event, work)


@router.post("/sql")
async def chat_sql(
    payload: AIChatRequest,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: LLMClient | None = Depends(get_llm),
):
    user = await load_user_context(db, current_user)
    event = AuditEvent(message=payload.message, intent="SQL_QUERY", agent="sql_agent", tool_name="read_only_sql")

    async def work() -> dict[str, Any]:
        result = await answer_sql_question(_require_llm(llm), user, payload.message)
        event.action_status = "ANSWERED"
        event.records_accessed = [f"table:{t}" for t in result.tables] + [f"rows:{len(result.rows)}"]
        return SQLChatData(
            answer=result.answer,
            sql=result.sql if user.can(Capability.VIEW_RAW_SQL) else None,
            columns=result.columns,
            rows=result.rows,
            row_count=len(result.rows),
            truncated=result.truncated,
        ).model_dump()

    return await _run_ai_request(db, user, event, work)


def _action_data(result: ActionResult) -> dict[str, Any]:
    return ActionChatData(
        status=result.status,
        answer=result.answer,
        tool=result.tool,
        params=result.params,
        result=result.result,
        confirmation_id=result.confirmation_id,
    ).model_dump()


@router.post("/actions")
async def chat_actions(
    payload: AIActionRequest,
    access_token: str = Depends(oauth2_scheme),
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    llm: LLMClient | None = Depends(get_llm),
):
    user = await load_user_context(db, current_user)
    # Release this request's read transaction: the tools call other API routes that write.
    await db.commit()
    event = AuditEvent(message=payload.message, intent="HR_ACTION", agent="action_agent")

    async def work() -> dict[str, Any]:
        result = await run_action_agent(
            _require_llm(llm), user, db, access_token, payload.message, [t.model_dump() for t in payload.history]
        )
        event.action_status = result.status
        event.tool_name = ",".join(dict.fromkeys(result.tools_called)) or None
        event.records_accessed = result.records
        return _action_data(result)

    return await _run_ai_request(db, user, event, work)


@router.post("/actions/confirm")
async def confirm_action(
    payload: ActionConfirmRequest,
    access_token: str = Depends(oauth2_scheme),
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await load_user_context(db, current_user)
    await db.commit()
    event = AuditEvent(
        message=f"[{'confirm' if payload.approve else 'cancel'} action]", intent="HR_ACTION", agent="action_agent"
    )

    async def work() -> dict[str, Any]:
        result = await confirm_pending_action(user, db, access_token, payload.confirmation_id, payload.approve)
        event.action_status = result.status
        event.tool_name = result.tool
        event.records_accessed = result.records
        return _action_data(result)

    return await _run_ai_request(db, user, event, work)


@router.post("/sessions")
async def create_chat_session(
    payload: ChatSessionCreate,
    current_user: Employee = Depends(get_current_user),
):
    _ = payload
    _ = current_user
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=error_response("CHAT_NOT_IMPLEMENTED", "Chat session creation is a Phase-3 stub and not implemented yet"),
    )


@router.post("/sessions/{session_id}/messages")
async def post_chat_message(
    session_id: str,
    payload: ChatMessageCreate,
    current_user: Employee = Depends(get_current_user),
):
    _ = session_id
    _ = payload
    _ = current_user
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content=error_response("CHAT_NOT_IMPLEMENTED", "Chat messaging is a Phase-3 stub and not implemented yet"),
    )
