from typing import Any, Literal

from pydantic import BaseModel, Field


class AIChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class PolicySourceOut(BaseModel):
    title: str
    category: str
    filename: str | None = None


class PolicyChatData(BaseModel):
    answer: str
    grounded: bool
    sources: list[PolicySourceOut]


class PolicyIndexStatsOut(BaseModel):
    policies: int
    indexed: int
    removed: int
    skipped: int
    chunks: int


class SQLChatData(BaseModel):
    answer: str
    # Only returned to roles allowed to see raw SQL (managers and admins).
    sql: str | None = None
    columns: list[str]
    rows: list[dict]
    row_count: int
    truncated: bool


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class AIActionRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Optional recent turns, so the assistant can follow up on its own clarifying question.
    history: list[ChatTurn] = Field(default_factory=list, max_length=10)


class ActionConfirmRequest(BaseModel):
    confirmation_id: str = Field(min_length=8, max_length=64)
    approve: bool = True


class ActionChatData(BaseModel):
    # ANSWERED | CONFIRMATION_REQUIRED | COMPLETED | CANCELLED
    status: str
    answer: str
    tool: str | None = None
    params: dict | None = None
    result: Any = None
    confirmation_id: str | None = None


class RouterChatData(BaseModel):
    intent: str
    confidence: float
    reason: str
    # "rules" (deterministic) or "llm"
    routed_by: str
    # The standalone question a follow-up was rewritten into (conversational memory); null if unchanged.
    interpreted_as: str | None = None
    # Same shape as the matching endpoint: PolicyChatData, SQLChatData, ActionChatData, or {"answer"}.
    result: dict


class AIHistoryItem(BaseModel):
    id: int
    message: str
    intent: str | None
    agent: str | None
    tool_name: str | None
    action_status: str
    created_at: str
