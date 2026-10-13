# PeopleOps AI Copilot: Architecture

> Status: Policy RAG, the read-only SQL agent, the permission layer and audit logging are
> implemented. The action agent, router and frontend are planned and will be documented here.

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
| `app/services/ai/sql_guardrails.py` | sqlglot-based validation of generated SQL |
| `app/services/ai/sql_agent.py` | Question screening, role-scoped views, read-only executor, SQL agent |
| `app/services/ai/errors.py` | `AIRequestError`: user-facing refusals and failures |
| `app/api/v1/endpoints/chat.py` | `/chat/policy`, `/chat/policy/reindex`, `/chat/sql`; shared error handling and audit |
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

## SQL agent details

```text
POST /api/v1/chat/sql
  ├─ screen_question     secrets / payroll → 403, data changes → 400   (no LLM call)
  ├─ LLM: question → {"sql", "explanation", "cannot_answer_reason"} using an allowlisted schema
  ├─ validate_select     one SELECT, allowlisted tables, no forbidden columns/functions,
  │                      no schema prefixes; wrapped in LIMIT SQL_MAX_ROWS + 1
  ├─ execute_scoped      read-only connection + role-scoped TEMP VIEWs + authorizer + timeout
  │     (one retry with the error fed back to the LLM; destructive SQL is never retried)
  ├─ LLM: rows → 1-3 sentence summary (rows treated as untrusted data; skipped when empty)
  └─ response: answer, columns, rows, row_count, truncated, sql (managers/admins only)
```

**Six layers of protection.** Each layer works on its own; none relies on the LLM behaving.

1. **Question screening.** Requests for passwords, bank details, PAN, date of birth or payroll,
   and requests to change data, are refused deterministically.
2. **Schema allowlist.** The model only sees 10 tables, without any sensitive column.
3. **SQL validation (sqlglot).**
   - Token-level keyword blocklist (so `LIKE '%update%'` is fine).
   - Exactly one statement, which must be a SELECT, UNION, INTERSECT or EXCEPT.
   - Allowlisted tables only, and no `main.` or `temp.` prefixes.
   - No forbidden columns, and no dangerous functions such as `load_extension`.
4. **Role-scoped views.** Each request opens a fresh `mode=ro` connection and creates TEMP VIEWs
   with the *same names* as the real tables. SQLite resolves unqualified names to `temp` first,
   so any query only sees the role's rows and columns:

   | Data | Employee | Manager | Admin |
   |---|---|---|---|
   | Directory: name, email, department, manager, role, skills | Everyone | Everyone | Everyone |
   | Phone, address, blood type | Self only | Self + team | Everyone |
   | Leave, project assignments, job history | Self only | Self + team | Everyone |
   | Tickets | Own or assigned | Team or assigned | Everyone |
   | Projects, departments, skills | Everyone | Everyone | Everyone |
   | Payroll, passwords, bank, PAN, DOB, salary | Never | Never | Never |

5. **SQLite authorizer.** A real table may only be read by an internal view whose name has a
   random per-request prefix, so a query or CTE cannot impersonate one. It also denies:
   - forbidden columns
   - row-only reads (`count(*)`, rowid) of tables outside the allowlist
   - PRAGMA, ATTACH and every write
6. **Resource limits.**
   - `PRAGMA query_only`.
   - A progress handler aborts queries after `SQL_TIMEOUT_SECONDS`.
   - Results are capped at `SQL_MAX_ROWS` and flagged as `truncated`.

The tests in `tests/test_sql_agent.py` attack layers 4–6 directly, bypassing the validator, to
prove they hold on their own.

## Key design decisions

| Decision | Alternative | Why |
|---|---|---|
| Local vector store (SQLite + NumPy) | ChromaDB | Chroma pulls in Kubernetes, gRPC and OpenTelemetry and conflicts with the app's pinned pydantic. A few hundred chunks search in microseconds with brute force, and it fits free hosting tiers. |
| Local open-source embeddings (`bge-small-en-v1.5` via fastembed) | Embedding API | Free, offline, no torch; quality is plenty for a policy library. |
| One OpenAI-compatible client | Provider SDKs | Switching Groq, Gemini or Ollama is a configuration change only. |
| Relevance gate before the LLM | Always call the LLM | Out-of-scope questions are refused deterministically and cost nothing. |
| Audit write never raises | Fail the request | A logging failure must not break the user's request; it is logged instead. |
| Role scoping with database views | Asking the LLM to add `WHERE` filters | A prompt can be talked out of a filter; a view cannot. |
| Screening sensitive questions before the LLM | Relying on the model to refuse | Deterministic, instant, free, and testable. |
| No LIMIT from the model; the app caps rows | Model-chosen LIMIT | The app knows when results were truncated and says so honestly. |

## Configuration

See `backend/.env.example`. The key variables are `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`,
`EMBEDDING_BACKEND`, `EMBEDDING_MODEL`, `RAG_MIN_SCORE` and `CORS_ORIGINS`.

## Known limitations (so far)

- Gemini's free tier has small daily quotas (`gemini-3.5-flash`: 20 requests/day). A SQL
  question uses 2 requests (generate + summarize). Use a `flash-lite` model, or another provider
  such as Groq, for development and evaluation. Rate limits return `429 AI_RATE_LIMITED`.
- The keyword blocklist rejects SQLite's `replace()` string function, because `REPLACE` is also a
  write statement. This is an acceptable trade-off for this use case.

- `RAG_MIN_SCORE` defaults to 0.55 for `bge-small`. Calibrate it on the evaluation set; the
  offline `hash` backend uses 0.12.
- The existing leave-approval API lets any manager approve any pending leave. The AI layer will
  restrict managers to their direct reports (see the permissions matrix).
