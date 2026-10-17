from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Mock HRMS API"
    environment: str = "dev"
    app_timezone: str = "Asia/Kolkata"
    database_url: str = "sqlite+aiosqlite:///./storage/hrms.db"

    jwt_secret_key: str = "change_me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    policy_upload_dir: str = "/app/storage/hr-policies"
    profile_photo_upload_dir: str = "/app/storage/profile-photos"
    employee_document_upload_dir: str = "/app/storage/employee-documents"

    # Comma-separated list of browser origins allowed to call the API.
    cors_origins: str = "http://localhost:3000"
    # Optional regex for extra origins, e.g. Vercel preview URLs: https://.*\.vercel\.app
    cors_origin_regex: str | None = None

    # LLM provider: any OpenAI-compatible Chat Completions API (Groq, Gemini, Ollama, OpenAI, ...).
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.0
    llm_timeout_seconds: float = 45.0
    # Retries (with back-off) on rate limits and transient provider errors.
    llm_max_retries: int = 3

    # Embeddings: "fastembed" runs a local open-source model; "hash" is an offline lexical fallback.
    embedding_backend: str = "fastembed"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_cache_dir: str = "./storage/ai/models"
    # Only for EMBEDDING_BACKEND=api; empty = reuse the LLM_* endpoint and key.
    embedding_base_url: str = ""
    embedding_api_key: str = ""

    # Policy RAG
    ai_index_path: str = "./storage/ai/policy_index.db"
    rag_top_k: int = 5
    # Minimum cosine similarity for a chunk to count as relevant. Empty = embedding backend default.
    rag_min_score: float | None = None
    rag_chunk_chars: int = 900
    # HR action agent. Empty = call the existing API in-process; or e.g. http://localhost:8000
    ai_internal_api_base_url: str = ""
    ai_max_tool_steps: int = 5
    ai_confirmation_ttl_seconds: int = 600

    # SQL agent
    sql_max_rows: int = 100
    sql_timeout_seconds: float = 5.0

    # Load the embedding model and index policies in the background when the API starts.
    ai_warmup_on_startup: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
