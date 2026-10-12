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
