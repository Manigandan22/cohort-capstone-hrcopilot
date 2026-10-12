import asyncio
import time

import structlog
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import error_response, success_response
from app.db.session import get_db
from app.models.employee import Employee
from app.schemas.ai import AIChatRequest, PolicyChatData, PolicyIndexStatsOut, PolicySourceOut
from app.schemas.chat import ChatMessageCreate, ChatSessionCreate
from app.services.ai.audit import AuditEvent, write_audit_log
from app.services.ai.llm import LLMClient, LLMError, LLMNotConfigured, get_llm_client
from app.services.ai.permissions import Capability, PermissionDenied, load_user_context
from app.services.ai.policy_rag import PolicyRAGService, get_policy_rag_service
from app.services.auth import get_current_user

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


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


@router.post("/policy")
async def chat_policy(
    payload: AIChatRequest,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    rag: PolicyRAGService = Depends(get_policy_rag),
    llm: LLMClient | None = Depends(get_llm),
):
    started = time.perf_counter()
    user = await load_user_context(db, current_user)
    event = AuditEvent(message=payload.message, intent="POLICY_QA", agent="policy_rag", tool_name="policy_vector_search")

    try:
        user.require(Capability.POLICY_QA)
        if llm is None:
            raise LLMNotConfigured()
        result = await rag.answer(db, llm, payload.message)
    except PermissionDenied as exc:
        event.action_status, event.error_code = "DENIED", "FORBIDDEN"
        event.latency_ms = _elapsed_ms(started)
        await write_audit_log(db, user, event)
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=error_response("FORBIDDEN", exc.message))
    except LLMNotConfigured:
        event.action_status, event.error_code = "ERROR", "AI_NOT_CONFIGURED"
        event.latency_ms = _elapsed_ms(started)
        await write_audit_log(db, user, event)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=error_response("AI_NOT_CONFIGURED", "The AI assistant is not configured on this server."),
        )
    except LLMError:
        event.action_status, event.error_code = "ERROR", "AI_UPSTREAM_ERROR"
        event.latency_ms = _elapsed_ms(started)
        await write_audit_log(db, user, event)
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=error_response("AI_UPSTREAM_ERROR", "The AI assistant is temporarily unavailable. Please try again."),
        )
    except Exception:  # noqa: BLE001 - never leak internals; always audit
        logger.exception("policy_chat_failed", user_id=user.id)
        event.action_status, event.error_code = "ERROR", "AI_INTERNAL_ERROR"
        event.latency_ms = _elapsed_ms(started)
        await write_audit_log(db, user, event)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response("AI_INTERNAL_ERROR", "Something went wrong while answering. Please try again."),
        )

    event.action_status = "ANSWERED" if result.grounded else "NO_ANSWER"
    event.records_accessed = result.chunk_ids
    event.latency_ms = _elapsed_ms(started)
    await write_audit_log(db, user, event)
    data = PolicyChatData(
        answer=result.answer,
        grounded=result.grounded,
        sources=[PolicySourceOut(title=s.title, category=s.category, filename=s.filename) for s in result.sources],
    )
    return success_response(data.model_dump())


@router.post("/policy/reindex")
async def reindex_policies(
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    rag: PolicyRAGService = Depends(get_policy_rag),
):
    started = time.perf_counter()
    user = await load_user_context(db, current_user)
    event = AuditEvent(message="[reindex policies]", intent="ADMIN", agent="policy_rag", tool_name="policy_reindex")
    try:
        user.require(Capability.REINDEX_POLICIES)
    except PermissionDenied as exc:
        event.action_status, event.error_code = "DENIED", "FORBIDDEN"
        event.latency_ms = _elapsed_ms(started)
        await write_audit_log(db, user, event)
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=error_response("FORBIDDEN", exc.message))

    stats = await rag.sync_index(db, force=True)
    event.action_status = "SUCCESS"
    event.latency_ms = _elapsed_ms(started)
    await write_audit_log(db, user, event)
    return success_response(PolicyIndexStatsOut(**stats.__dict__).model_dump())


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
