import asyncio

import structlog

from app.db.session import SessionLocal
from app.services.ai.policy_rag import get_policy_rag_service

logger = structlog.get_logger(__name__)


async def warm_up_policy_index() -> None:
    """Load the embedding model and index policies so the first question is fast. Best effort."""
    try:
        rag = await asyncio.to_thread(get_policy_rag_service)
        async with SessionLocal() as db:
            stats = await rag.sync_index(db)
        logger.info("policy_index_ready", chunks=stats.chunks, policies=stats.policies)
    except Exception:  # noqa: BLE001 - the API must start even if the model cannot be loaded yet
        logger.exception("policy_index_warmup_failed")
