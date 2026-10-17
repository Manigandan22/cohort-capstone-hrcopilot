import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.services.ai.warmup import warm_up_policy_index


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    warmup = asyncio.create_task(warm_up_policy_index()) if settings.ai_warmup_on_startup else None
    yield
    if warmup and not warmup.done():
        warmup.cancel()


app = FastAPI(title="Mock HRMS API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")
@app.get("/health")
async def root_health():
    return {"success": True, "data": {"status": "ok"}, "error": None}
