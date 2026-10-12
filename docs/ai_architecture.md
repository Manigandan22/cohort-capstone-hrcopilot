# PeopleOps AI Copilot: Architecture

> Status: Policy RAG, the permission layer and audit logging are implemented. The SQL agent,
> action agent, router and frontend are planned and will be documented here as they land.

## Request flow

```text
Next.js /ai-copilot (planned)
        │  Authorization: Bearer <JWT>
        ▼
POST /api/v1/chat/policy
        │
        ├─ get_current_user (existing JWT auth)
        ├─ load_user_context → UserContext(id, role, team_ids)
        ├─ permission check (permissions.PERMISSION_MATRIX)
        ├─ PolicyRAGService.answer
        │     ├─ sync_index: re-embed only policies whose version changed
        │     ├─ retrieve: top-k cosine search in the local vector store
        │     ├─ relevance gate: no chunk ≥ min score → refuse, LLM is NOT called
        │     ├─ LLM (JSON mode): answer only from <policy_excerpts>, cite excerpt ids
        │     └─ validate: sufficient + non-empty + citations that exist, else refuse
        ├─ sources built from our own chunk metadata (title, category, filename)
        └─ write_audit_log (message redacted)
```

## Components

| File | Responsibility |
|---|---|
| `app/services/ai/permissions.py` | Permission matrix, `UserContext`, refusal messages, forbidden columns |
| `app/services/ai/audit.py` | Redaction and one audit row per AI request |
| `app/services/ai/llm.py` | OpenAI-compatible client (Groq, Gemini, Ollama, OpenAI) |
| `app/services/ai/embeddings.py` | Local `fastembed` model; offline `hash` fallback for tests |
| `app/services/ai/vector_store.py` | SQLite-backed vector store with exact cosine search |
| `app/services/ai/policy_rag.py` | Ingestion, chunking, indexing, retrieval, grounded answering |
| `app/services/ai/warmup.py` | Loads the model and builds the index when the API starts |
| `app/api/v1/endpoints/chat.py` | `/chat/policy`, `/chat/policy/reindex` |
| `app/models/ai_audit_log.py` + migration `0017` | `ai_audit_logs` table |

## Policy RAG details

- **Ingestion.** Text comes from `hr_policies.content` when present, otherwise from the stored
  `.md`, `.txt` or `.pdf` file. Files are only read from inside `POLICY_UPLOAD_DIR`.
- **Chunking.** Markdown-heading aware. Each chunk is prefixed with `Policy title > Section` so
  retrieval and the LLM both see where the text came from. Default 900 characters.
- **Incremental indexing.** Each policy has a version hash (title, category, checksum, path,
  content). Only changed policies are re-embedded; deleted policies are removed. The index
  syncs on startup, before each question, and on `POST /chat/policy/reindex` (admin only).
- **Grounding.**
  - A relevance threshold blocks the LLM from answering out-of-scope questions from memory.
  - The model must return `{"sufficient", "answer", "citations"}`.
  - Answers without valid citations are replaced with a fixed refusal.
  - Sources are taken from our metadata, never from model output, so they cannot be invented.
- **Prompt-injection defence.**
  - Excerpts are wrapped in `<policy_excerpts>` and HTML-escaped, so a document cannot close the delimiter.
  - The system prompt declares excerpt text as untrusted data.
  - Covered by `tests/test_policy_chat.py::test_injected_instructions_in_policy_are_escaped_as_data`.

## Key design decisions

| Decision | Alternative | Why |
|---|---|---|
| Local vector store (SQLite + NumPy) | ChromaDB | Chroma pulls in Kubernetes, gRPC and OpenTelemetry and conflicts with the app's pinned pydantic. A few hundred chunks search in microseconds with brute force, and it fits free hosting tiers. |
| Local open-source embeddings (`bge-small-en-v1.5` via fastembed) | Embedding API | Free, offline, no torch; quality is plenty for a policy library. |
| One OpenAI-compatible client | Provider SDKs | Switching Groq, Gemini or Ollama is a configuration change only. |
| Relevance gate before the LLM | Always call the LLM | Out-of-scope questions are refused deterministically and cost nothing. |
| Audit write never raises | Fail the request | A logging failure must not break the user's request; it is logged instead. |

## Configuration

See `backend/.env.example`. The key variables are `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`,
`EMBEDDING_BACKEND`, `EMBEDDING_MODEL`, `RAG_MIN_SCORE` and `CORS_ORIGINS`.

## Known limitations (so far)

- `RAG_MIN_SCORE` defaults to 0.55 for `bge-small`. Calibrate it on the evaluation set; the
  offline `hash` backend uses 0.12.
- The existing leave-approval API lets any manager approve any pending leave. The AI layer will
  restrict managers to their direct reports (see the permissions matrix).
