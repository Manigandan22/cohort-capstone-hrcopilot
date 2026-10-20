# AI Endpoint Contracts

All endpoints are under `/api/v1/chat`. They require `Authorization: Bearer <access_token>`
(from `POST /api/v1/auth/login`) and use the app's standard response envelope:

```json
{ "success": true,  "data": { ... }, "error": null }
{ "success": false, "data": null,   "error": { "code": "FORBIDDEN", "message": "You do not have permission to ..." } }
```

Every call writes one row to `ai_audit_logs`, including refusals and failures.

## POST `/router`: unified entry point (used by the UI)

Request:
```json
{ "message": "Approve Employee User's pending leave request.",
  "history": [ { "role": "user", "content": "..." }, { "role": "assistant", "content": "..." } ] }
```
`history` is optional (at most 10 turns). It gives the assistant conversational memory:
follow-ups such as "What about casual leave?" are rewritten into standalone questions (see
`interpreted_as`), and answers to its own clarifying questions complete the pending request.

Response `data`:
```json
{ "intent": "HR_ACTION",           // POLICY_QA | SQL_QUERY | HR_ACTION | UNKNOWN
  "confidence": 0.9,
  "reason": "The message asks to perform an HR task.",
  "routed_by": "rules",             // rules | llm
  "interpreted_as": null,           // standalone rewrite of a follow-up, e.g. "How many casual leaves do I get?"
  "result": { ... }                 // same shape as /policy, /sql or /actions below; UNKNOWN → {"answer"}
}
```

## POST `/policy`: Policy RAG

Request `{ "message": "What is the sick leave policy?" }` → `data`:
```json
{ "answer": "You receive 10 days of sick leave per calendar year.",
  "grounded": true,
  "sources": [ { "title": "Leave Policy", "category": "LEAVE", "filename": "seed_policy_01.md" } ] }
```
When the library does not contain the answer: `grounded: false`, `sources: []` and a fixed
"I couldn't find this in the HR policy library…" answer.

## POST `/policy/reindex`: rebuild the policy index (Admin)

No body. `data`: `{ "policies": 23, "indexed": 23, "removed": 0, "skipped": 0, "chunks": 45 }`.

## POST `/sql`: read-only SQL agent

Request `{ "message": "Which employees know Python?" }` → `data`:
```json
{ "answer": "There are 50 employees who know Python ...",
  "sql": "SELECT e.name ... ",       // only for MANAGER and ADMIN; null for EMPLOYEE
  "columns": ["name", "level"],
  "rows": [ { "name": "Abigail Reynolds", "level": "BEGINNER" } ],
  "row_count": 50,
  "truncated": false }               // true when more than SQL_MAX_ROWS rows matched
```

## POST `/actions`: HR action agent

Request: same as `/router` (`message`, optional `history`). `data`:
```json
{ "status": "CONFIRMATION_REQUIRED",   // ANSWERED | CONFIRMATION_REQUIRED | COMPLETED | CANCELLED
  "answer": "Approve the pending casual leave request from Employee User for 2026-10-16 to 2026-10-17 (request #1)?",
  "tool": "approve_leave",
  "params": { "request_id": 1 },
  "result": null,                      // the existing API's response data when COMPLETED
  "confirmation_id": "Qb1x..." }       // only when CONFIRMATION_REQUIRED
```

| `status` | Meaning |
|---|---|
| `ANSWERED` | A read-only answer, or a clarifying question ("Which dates?") |
| `COMPLETED` | A low-impact action ran (apply leave, create ticket) |
| `CONFIRMATION_REQUIRED` | A high-impact action was proposed; nothing has changed yet |

## POST `/actions/confirm`: confirm or cancel a proposed action

Request: `{ "confirmation_id": "Qb1x...", "approve": true }` → the same shape as `/actions`, with
`status` `COMPLETED` or `CANCELLED`.

Confirmation ids are single-use, bound to the user who requested the action, and expire after
`AI_CONFIRMATION_TTL_SECONDS` (default 600). Permissions are checked again at execution.

## GET `/history?limit=20`: the caller's own recent AI interactions

`data`: a list of
`{ "id", "message", "intent", "agent", "tool_name", "action_status", "created_at" }`.
Messages are stored redacted.

## Error codes

| HTTP | `code` | When |
|---|---|---|
| 400 | `READ_ONLY` | The SQL agent was asked to change data |
| 400 | `ACTION_NOT_SUPPORTED` | Destructive request such as "delete all …" |
| 400 | `UNSAFE_REQUEST` | Prompt-injection attempt ("ignore all previous instructions …") |
| 400 | backend code, e.g. `LEAVE_OVERLAP` | The existing API rejected the action; its message is passed through |
| 403 | `FORBIDDEN` | Not allowed for this role, out of team scope, or sensitive data |
| 404 | `NOT_FOUND`, `CONFIRMATION_NOT_FOUND` | Record not found; confirmation expired or already used |
| 422 | `SQL_CANNOT_ANSWER`, `SQL_GENERATION_FAILED`, `ACTION_INCOMPLETE` | The request could not be answered safely |
| 429 | `AI_RATE_LIMITED` | LLM provider rate limit or quota |
| 502 | `AI_UPSTREAM_ERROR` | LLM provider error |
| 503 | `AI_NOT_CONFIGURED` | No LLM configured on the server |
| 500 | `AI_INTERNAL_ERROR` | Unexpected error (details are only in server logs) |
