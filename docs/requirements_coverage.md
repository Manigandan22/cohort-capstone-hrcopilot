# Requirements Coverage

How each requirement in the assignment brief (*AI-Powered HR Operations Copilot*) is met, and
where the evidence is.

**Evidence key**
- **Eval Pxx/Sxx/Axx/Rxx/Xxx/Mxx/Uxx:** cases in `backend/eval/ai_eval_cases.json`, results in
  [`ai_eval_results.md`](ai_eval_results.md). These run against the live deployment.
- **`test_*`:** automated tests in `backend/tests/` (offline, fake LLM). Run with `python -m pytest -q`.
- **Live:** verified on the deployed app, <https://cbnest-ai-copilot.vercel.app>.

Status legend: ✅ done · 🟡 partial · ❌ not done.

---

## 1. Core AI capabilities

| Capability (brief) | Status | Implementation | Evidence |
|---|---|---|---|
| Policy RAG Assistant | ✅ | `services/ai/policy_rag.py`, `embeddings.py`, `vector_store.py` | Eval P01–P10; `test_policy_chat.py` (10 tests) |
| SQL Agent for HR Intelligence | ✅ | `services/ai/sql_agent.py`, `sql_guardrails.py` | Eval S01–S10; `test_sql_agent.py` (21 tests) |
| HR Task Automation Agent | ✅ | `services/ai/action_agent.py`, `api_tools.py` | Eval A01–A07, R01–R03; `test_action_agent.py` (13 tests) |
| Role-Based Access Control for AI | ✅ | `services/ai/permissions.py` + per-agent enforcement | Eval R01–R03, S08–S10, X01–X09; `test_ai_foundations.py` |

## 2. Architecture and required AI flow

| Brief requirement | Status | How |
|---|---|---|
| Authenticated chat endpoint (JWT) | ✅ | Every `/chat/*` route uses the existing `get_current_user`; `test_requires_authentication` |
| Load current user context | ✅ | `load_user_context` → `UserContext(id, role, team_ids)` |
| Classify intent → route to the right component | ✅ | LangGraph router (`router.py`); `test_rules_route_brief_prompts`, `test_ambiguous_message_uses_llm_classifier` |
| Apply permission guardrails | ✅ | Permission matrix, team scope and screening before any data or tool access |
| Execute RAG, safe SQL or API tool call | ✅ | The three agents |
| Return answer + sources, rows or action result | ✅ | `PolicyChatData`, `SQLChatData`, `ActionChatData` (`schemas/ai.py`) |
| Write AI audit log | ✅ | `_run_ai_request` writes exactly one row per request, including failures |
| **Critical rule: agents never mutate the DB directly** | ✅ | Every write goes Agent → existing API → service → DB; `test_ai_layer_never_writes_business_tables_directly` scans the code |

## 3. Policy RAG Assistant

| Brief requirement | Status | How / evidence |
|---|---|---|
| Load policies from the DB and/or stored files | ✅ | `extract_policy_text`: DB `content`, else `.md`, `.txt` or `.pdf` file (path-restricted) |
| Chunk into retrieval-friendly sections | ✅ | Heading-aware chunks prefixed `Title > Section`; `test_chunking_keeps_section_labels_and_respects_size` |
| Generate embeddings | ✅ | `bge-small` (local), Gemini `gemini-embedding-001` (deployed), `hash` (tests) |
| Store embeddings (local store / Chroma / FAISS / Qdrant) | ✅ | Local SQLite + NumPy vector store, incrementally re-indexed |
| Retrieve relevant chunks | ✅ | Top-k cosine search with a calibrated relevance threshold |
| Grounded answer from retrieved context only | ✅ | JSON answer with citations; invented citations rejected (`test_answer_with_invented_citation_is_rejected`) |
| Return source references | ✅ | Built from our own metadata (`title`, `category`, `filename`), never from model output; Eval P01–P08 |
| Refuse on insufficient context | ✅ | Relevance gate (no LLM call) plus model sufficiency check; Eval P09, P10; `test_unrelated_question_is_refused_without_calling_llm` |
| Treat retrieved content as data, not instructions | ✅ | Escaped `<policy_excerpts>`; `test_injected_instructions_in_policy_are_escaped_as_data` |
| `POST /api/v1/chat/policy` | ✅ | `endpoints/chat.py` |
| Guardrails: no model memory, no invented rules, no hidden metadata, no obeying documents | ✅ | All four above; only title, category and filename are exposed |

## 4. SQL Agent

| Brief requirement | Status | How / evidence |
|---|---|---|
| Read-only, safe SELECT only | ✅ | sqlglot validation + `mode=ro` connection + `PRAGMA query_only` + SQLite authorizer |
| Uses the recommended tables only | ✅ | Allowlist of the 10 tables from the brief |
| Forbidden columns never exposed | ✅ | Absent from role views and denied by the authorizer; `test_forbidden_columns_do_not_exist_in_views`, Eval X07, X08 |
| Payroll blocked | ✅ | `payroll_records` is never queryable, not even row counts; `test_payroll_row_counts_are_not_readable`, Eval X09 |
| Block INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/REPLACE/TRUNCATE/PRAGMA/ATTACH/DETACH | ✅ | Token-level blocklist; `test_validator_blocks_unsafe_sql`, `test_writes_are_impossible`, Eval X06 |
| Parse or inspect SQL before execution | ✅ | sqlglot AST checks |
| One statement per request | ✅ | `MULTIPLE_STATEMENTS` check |
| Enforce row limits | ✅ | Wrapped `LIMIT`, truncation reported honestly; `test_results_are_capped` |
| Role-based filters (employee: own; manager: team; admin: broad) | ✅ | Role-scoped TEMP VIEWs; `test_rows_are_scoped_by_role`, Eval S08–S10 |
| Never pass raw DB errors to the user | ✅ | Errors go to the LLM retry only; users get a generic message |
| `POST /api/v1/chat/sql` with answer, sql and rows | ✅ | SQL is shown to managers and admins only (`VIEW_RAW_SQL`); Eval S05, S06 |

## 5. HR Task Automation Agent

**Supported actions in the brief:**

| Role | Action | Status | Tool → existing API | Evidence |
|---|---|---|---|---|
| Employee | Apply for leave | ✅ | `apply_leave` → `POST /leaves/requests` | Eval A01; `test_employee_applies_for_leave_through_existing_api` |
| Employee | Check leave balance | ✅ | `get_my_leave_balance`, or the SQL agent | `test_read_tool_result_is_given_to_the_model`, Eval S06 |
| Employee | Create a ticket | ✅ | `create_ticket` → `POST /tickets` | Eval A02; `test_ticket_creation` |
| Employee | Check ticket status | ✅ | `get_my_tickets` → `GET /tickets?mine=true` | |
| Employee | View own projects | ✅ | SQL agent | Eval S04 |
| Employee | Ask policy questions | ✅ | Policy RAG | Eval P01–P10 |
| Manager | Approve / reject leave | ✅ | `approve_leave` / `reject_leave` → `POST /leaves/requests/{id}/approve` or `/reject` (with confirmation) | Eval A03; `test_manager_approval_requires_confirmation_then_runs_backend_logic` |
| Manager | Assign / update tickets | ✅ | `assign_ticket`, `update_ticket_status` (with confirmation) | |
| Manager | View team leave information | ✅ | SQL agent, team-scoped | Eval S10 |
| Manager | Search employees by skill | ✅ | SQL agent | Eval S02, S05 |
| Manager | Check project assignments | ✅ | SQL agent | Eval S03 |
| Manager / Admin | Create announcements | ✅ | `create_announcement` (with confirmation) | Eval A05 |
| Admin | Create projects | ✅ | `create_project` (with confirmation) | |
| Admin | Assign employees to projects | ✅ | `assign_employee_to_project` (with confirmation) | Eval A04 |
| Admin | View broader HRMS analytics | ✅ | SQL agent, admin scope | Eval S07 |
| Admin | Upload or summarize HR policies | 🟡 | Upload exists on the HR Policies page; re-index via `/chat/policy/reindex`; no "summarize this policy" tool | `test_reindex_is_admin_only` |
| Admin | Employee lifecycle actions (deactivate/reactivate) | ❌ | Not implemented as an AI tool | |

| Brief requirement | Status | How / evidence |
|---|---|---|
| Calls existing APIs with the **current user's token** | ✅ | `HRApiClient` forwards the user's bearer token |
| Intent extraction, structured tool schemas, wrappers, permission checks, error handling, summaries | ✅ | Pydantic-validated tools; deterministic summaries; backend errors surfaced (`test_backend_business_rules_are_surfaced`) |
| Unauthorized example: employee approving leave is refused | ✅ | Exact message from the brief; Eval R01; `test_employee_cannot_approve_leave_and_nothing_changes` |
| `POST /api/v1/chat/actions` | ✅ | Plus `/chat/actions/confirm` |

## 6. AI Router (optional in the brief)

| Brief requirement | Status | How / evidence |
|---|---|---|
| Unified router `POST /api/v1/chat/router` | ✅ | LangGraph `StateGraph` |
| Example routing table | ✅ | All 19 brief prompts routed correctly; `test_rules_route_brief_prompts` |
| Intent schema `{intent, confidence, reason}` | ✅ | Plus `routed_by` and `interpreted_as` |

## 7. Role-Based Access Control

Every row of the brief's AI permissions matrix is encoded in `PERMISSION_MATRIX`
(`test_matrix_covers_every_capability_for_every_role`) and documented in
[`ai_permissions_matrix.md`](ai_permissions_matrix.md).

| Brief requirement | Status | Evidence |
|---|---|---|
| Never reveal or modify what the user cannot access in the normal app | ✅ | Role views, tool permission checks, and the backend's own 403s as the final gate |
| Good refusals that do not leak a record's existence | ✅ | Refusals are issued before lookups; a missing record gives the same refusal (`test_manager_scope_is_enforced_before_proposing`) |
| Authorization not only in the frontend | ✅ | All checks are server-side; the UI only adapts suggestions |

## 8. AI Audit Logging

| Brief requirement | Status | How / evidence |
|---|---|---|
| Table `ai_audit_logs` (model + migration) | ✅ | `models/ai_audit_log.py`, `alembic/versions/0017_ai_audit_logs.py` |
| Logs user, role, message, intent, agent, tool/API, status, records, timestamp | ✅ | Plus `error_code`, `latency_ms`, and `interpreted_as` for follow-ups |
| Never logs secrets, JWTs, passwords, bank, PAN or payroll | ✅ | `redact()`; `test_redact_removes_tokens_pan_ifsc_and_account_numbers`, `test_audit_log_redacts_sensitive_values` |

## 9. Frontend AI experience

| Brief requirement | Status | How |
|---|---|---|
| Dedicated `/ai-copilot` page | ✅ | Linked in the sidebar, protected by the auth middleware |
| Chat input, message history, loading state, error state | ✅ | `chat-panel.tsx`; refusals shown in amber, errors in red |
| Sources for RAG answers | ✅ | `source-list.tsx` |
| Table for SQL results | ✅ | `sql-result-table.tsx` (with "Show SQL" for managers and admins) |
| Action confirmation result | ✅ | `action-result-card.tsx` (Confirm / Cancel / Done) |
| Role-aware UI | ✅ | Suggestions per role; SQL visibility follows the API |
| Sections: Ask HR Policy / People & Projects / HR Task / Recent AI Actions | ✅ | All four on the page |

## 10. Deliverables (expected files)

| Expected file (brief) | Present |
|---|---|
| `services/ai/policy_rag.py`, `embeddings.py`, `vector_store.py` | ✅ |
| `services/ai/sql_agent.py`, `sql_guardrails.py` | ✅ |
| `services/ai/action_agent.py`, `api_tools.py`, `permissions.py` | ✅ |
| `api/v1/endpoints/chat.py` | ✅ |
| `frontend/app/ai-copilot/page.tsx`, `components/ai/{chat-panel,source-list,sql-result-table,action-result-card}.tsx`, `lib/api.ts` | ✅ |
| `models/ai_audit_log.py`, `services/ai/audit.py`, `alembic/versions/0017_ai_audit_logs.py` | ✅ |
| `docs/ai_architecture.md`, `docs/ai_permissions_matrix.md`, `docs/ai_eval_results.md`, README | ✅ |

Required doc topics (architecture diagram, model/provider, setup, environment variables, endpoint
contracts, limitations, security decisions, evaluation results) are covered by the README and
`docs/` ([`ai_endpoints.md`](ai_endpoints.md) has the contracts).

## 11. Evaluation criteria (brief)

| Criterion | Weight | Where it is demonstrated |
|---|---|---|
| Policy RAG quality | 20% | Eval P01–P10, M01–M02; sources on every answer |
| SQL agent correctness and safety | 20% | Eval S01–S10, X06–X09; 21 SQL tests including direct attacks on the sandbox |
| Backend API tool calling | 20% | Eval A01–A07; DB-scan test; confirmation flow running the real leave service |
| Role-based access control | 20% | Eval R01–R03, S08–S10, X01–X09; matrix test |
| Full-stack integration | 10% | Live app (Vercel → Render), crawl of 17 pages × 3 roles |
| Code quality and maintainability | 10% | Typed schemas, modular services, 123 tests, consistent error envelope |

## 12. Minimum passing requirements and automatic-failure conditions

| Requirement | Status | Evidence |
|---|---|---|
| Policy RAG answers ≥ 5 common questions correctly | ✅ | Eval P01–P08 (8 answered correctly with sources) |
| SQL agent executes only read-only queries | ✅ | `test_writes_are_impossible`, `test_authorizer_blocks_bypasses_even_without_validator` |
| HR action agent uses backend APIs for all mutations | ✅ | `test_ai_layer_never_writes_business_tables_directly` |
| Employee cannot access another employee's sensitive data | ✅ | Eval S08, X01, X02 |
| Employee cannot approve leave or assign projects | ✅ | Eval R01, R02 |
| No direct DB writes by AI agents | ✅ | Same scan test |
| Usable frontend AI flow | ✅ | Live app; screenshots in the README |
| *Auto-fail:* direct writes to business tables | Not triggered | Scan test |
| *Auto-fail:* destructive SQL allowed | Not triggered | Eval X06; validator and authorizer tests |
| *Auto-fail:* reveals passwords, bank, PAN or unauthorized payroll | Not triggered | Eval X01, X02, X07–X09, M04 |
| *Auto-fail:* authorization only in the frontend | Not triggered | All checks server-side |
| *Auto-fail:* breaks existing HRMS functionality | Not triggered | Crawl of all 17 pages × 3 roles, locally and live |
| *Auto-fail:* secrets committed | Not triggered | `.env` gitignored; keys only in host secrets |

Every **suggested evaluation prompt** from the brief (policy, SQL, HR action and security
prompts) is a case in the evaluation set.

## 13. Bonuses (optional in the brief)

| Bonus | Status | Notes |
|---|---|---|
| 1. LangGraph multi-agent orchestration | ✅ | `contextualize → classify → {policy_rag, sql_agent, action_agent, fallback}`. Context loading and audit run in the endpoint wrapper rather than as graph nodes. |
| 2. Human-in-the-loop confirmation | ✅ | Approve/reject leave, assign project, create announcement, ticket assign/status, create project. *Deactivate employee* has no tool (see §5). |
| 3. Streaming chat responses | ❌ | Not implemented; a loading state is shown instead |
| 4. LangSmith / OpenTelemetry tracing | ❌ | Not implemented; structured logs and audit rows (with latency) instead |
| 5. Evaluation dataset | ✅ | 44 cases in the brief's `{input, role, expected_route, expected_behavior}` format, with a runner and report: **44/44 on the live deployment** |
| 6. Prompt-injection defense | ✅ | Escaped policy excerpts plus a poisoned-document test; injection phrases refused by the router (Eval X05) |
| 7. Role-specific copilot modes | 🟡 | Role-aware suggestions and "Employee/Manager/Admin copilot" labels; no separate modes |
| 8. AI usage dashboard | ❌ | Data is in `ai_audit_logs`; no dashboard page |

---

## 14. Beyond the brief

Features and engineering that the brief did not ask for:

| Addition | Why it matters |
|---|---|
| **Conversational memory** (follow-up rewriting, `interpreted_as` shown in the UI) | "What about casual leave?" and "What skills does that person have?" work; clarification answers complete pending tasks. Eval M01–M04. |
| **Six-layer SQL sandbox** with a random-prefix authorizer | Role scoping holds even if validation is bypassed; tests attack it directly (CTE impersonation, payroll row counts) |
| **Manager team scope and no self-approval** | Stricter than the original API, which lets any manager approve any leave |
| **Deterministic security screening before the LLM** | Sensitive, destructive and injection requests are refused instantly, for free, and testably |
| **Rules-first routing** | Most brief prompts are routed with zero LLM calls; saves quota and is predictable |
| **One-time, user-bound, expiring confirmation tokens** | A stolen or reused confirmation cannot run an action |
| **Deterministic action summaries** | The LLM never describes a write that did not happen |
| **Provider-agnostic LLM layer** | Gemini, Groq, OpenAI or local Ollama by environment variable; handles Gemini 3 thought signatures and rate limits (friendly 429) |
| **Pluggable embeddings** (local bge-small / Gemini API / offline hash) with calibrated thresholds | Runs offline locally and within 512 MB in production |
| **Free deployment, live** | Vercel + Render via `render.yaml`; seed time cut from 5 min to 9 s |
| **Fixes to the base app** | Production build blockers (Polls type error, missing Suspense), a Next.js security upgrade, and the `.gitignore` that dropped all docs |
| **123 offline tests and a 44/44 evaluation run against the live deployment** | Reproducible evidence for every requirement above |
| **Personal AI history** (`GET /chat/history`, Recent AI Actions panel) | Users can see what the assistant did for them |

## 15. Known gaps (honest)

- Admin **employee lifecycle actions** (deactivate/reactivate) and **policy summarization** are not
  AI tools yet.
- Bonuses **3 (streaming)**, **4 (tracing)** and **8 (usage dashboard)** are not implemented;
  **7 (role modes)** is partial.
- Free-tier limits: Gemini quotas and Render cold starts (see the README's *Known limitations*).
