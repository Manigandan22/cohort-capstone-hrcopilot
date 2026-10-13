<img width="2866" height="1274" alt="image" src="https://github.com/user-attachments/assets/4b4defd5-663f-45d1-b9e3-f9adbcfabbae" />

# CB Nest

**CB Nest** is a full-stack HR Management System built for hands-on learning. It covers real-world business workflows — employee lifecycle, attendance, leave approvals, payroll, ticketing, and more — using a modern stack (FastAPI + Next.js + Docker). Use it to understand how production-grade HRMS platforms work, and extend it with your own AI features.

> 📖 **New here?** Start with the [Learner Guide](docs/Learner_Guide.md) for a complete walkthrough of the project architecture, database, and how to explore the code.

## Overview

This project provides a working HRMS platform with authentication, employee operations, attendance, leave management, communication features, finance data views, and ticketing workflows.

It is designed as a practical base for AI feature integration (RAG, assistants, agent workflows) without rebuilding core HR modules from scratch.


## PeopleOps AI Copilot (capstone extension)

This fork extends CB Nest with AI features: **Policy RAG**, a **read-only SQL agent**, an
**HR action agent** that calls the existing APIs, and **role-based access control** for all of them.
Every AI request is written to the `ai_audit_logs` table.

| Feature | Endpoint | Status |
|---|---|---|
| Policy RAG Assistant | `POST /api/v1/chat/policy` | ✅ Done |
| Policy re-index (admin) | `POST /api/v1/chat/policy/reindex` | ✅ Done |
| AI audit logging | `ai_audit_logs` table | ✅ Done |
| Permission matrix | `app/services/ai/permissions.py` | ✅ Done |
| SQL Agent | `POST /api/v1/chat/sql` | 🚧 Planned |
| HR Action Agent | `POST /api/v1/chat/actions` | 🚧 Planned |
| AI Router | `POST /api/v1/chat/router` | 🚧 Planned |
| Frontend `/ai-copilot` page | — | 🚧 Planned |

- Architecture and design decisions: [`docs/ai_architecture.md`](docs/ai_architecture.md)
- Permissions matrix: [`docs/ai_permissions_matrix.md`](docs/ai_permissions_matrix.md)

### AI setup

1. Get a free API key from any OpenAI-compatible provider, for example [Groq](https://console.groq.com/keys).
   You can also run fully locally with [Ollama](https://ollama.com).
2. In `backend/.env` set `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY` (see `backend/.env.example`).
3. Start the app, run the migrations and the seed as described in Quick Start below.

The embedding model (`BAAI/bge-small-en-v1.5`, about 130 MB) is downloaded once on first start
into `backend/storage/ai/models`, and the policy index is built in the background.

Try it:

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login -H 'content-type: application/json' \
  -d '{"email":"employee@mock-hrms.dev","password":"password123"}' | python -c 'import sys,json;print(json.load(sys.stdin)["data"]["access_token"])')
curl -s -X POST localhost:8000/api/v1/chat/policy -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"message":"How many sick leaves do I get?"}'
```

### Running without Docker

Requires **Python 3.11 or 3.12**. Python 3.10 lacks `datetime.UTC`, and 3.14 has no prebuilt
wheels for the pinned `pydantic-core`. Add these lines to `backend/.env`, because the defaults
point at Docker paths:

```
POLICY_UPLOAD_DIR=./storage/hr-policies
PROFILE_PHOTO_UPLOAD_DIR=./storage/profile-photos
EMPLOYEE_DOCUMENT_UPLOAD_DIR=./storage/employee-documents
```

macOS/Linux:

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
export PYTHONPATH=.
alembic upgrade head && python scripts/seed.py
uvicorn app.main:app --reload --port 8000
```

Windows PowerShell:

```powershell
cd backend
py -3.12 -m venv .venv; .venv\Scripts\activate
pip install -r requirements-dev.txt
$env:PYTHONPATH = "."
alembic upgrade head; python scripts/seed.py
uvicorn app.main:app --reload --port 8000
```

Frontend: `cd frontend && npm install && npm run dev`.

### Running the AI tests

The tests need no network or API key: they use an offline embedder and a fake LLM.

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest -q
```

## Tech Stack

- Frontend: Next.js 15, React 19, Tailwind CSS
- Backend: FastAPI, SQLAlchemy (async), Pydantic v2
- Database: SQLite
- Migrations: Alembic
- Orchestration: Docker Compose

## Features

- JWT auth with role-aware access (ADMIN, MANAGER, EMPLOYEE)
- Employee directory with search, filters, and pagination
- Attendance clock in/clock out with status and mode tracking
- Leave balances and leave request workflow
- Announcements and polls
- Team calendar (leaves, WFH, holidays, birthdays)
- My Profile edits, profile photo upload, job history, documents
- Finance views (salary, statutory, payroll history)
- Tickets with assignment, status updates, onboarding tasks
- HR policy upload/download library
- Admin/Manager employee document upload flow (APPOINTMENT, TAX, PAYSLIP, OTHER)
- My Documents with search, view, and download; delete is allowed only for `OTHER` document type
- Password-protected PDF payslips (DOB in `DD-MM-YY`) for generated and uploaded payslips
- Notification bell for announcements, polls, ticket assignment, ticket status, leave decision, and employee-document uploads by others (not self-uploads)
- AI contract stubs (`/api/v1/chat/*`) returning `501` for future implementation

## Repository Structure

```text
.
|-- backend/
|   |-- alembic/
|   |   |-- versions/
|   |   `-- env.py
|   |-- app/
|   |   |-- api/v1/endpoints/
|   |   |-- core/
|   |   |-- db/
|   |   |-- models/
|   |   |-- schemas/
|   |   `-- services/
|   |-- scripts/
|   |   `-- seed.py
|   |-- storage/
|   |   |-- hr-policies/
|   |   `-- profile-photos/
|   |-- .env.example
|   |-- alembic.ini
|   |-- Dockerfile
|   `-- requirements.txt
|-- frontend/
|   |-- app/
|   |   |-- announcements/
|   |   |-- attendance/
|   |   |-- dashboard/
|   |   |-- employees/
|   |   |-- finance/
|   |   |-- hr-policies/
|   |   |-- leaves/
|   |   |-- login/
|   |   |-- me/
|   |   |-- organization/
|   |   |-- polls/
|   |   |-- team-calendar/
|   |   `-- tickets/
|   |-- components/
|   |   |-- layout/
|   |   `-- ui/
|   |-- lib/
|   |   `-- api.ts
|   |-- Dockerfile
|   |-- middleware.ts
|   `-- package.json
|-- docs/
|   |-- api/
|   |-- Learner_Guide.md
|   |-- PRD.md
|   `-- db_tables_samples.md
|-- docker-compose.yml
`-- README.md
```

## Prerequisites

- **Docker Desktop** (or Docker Engine + Compose v2)
  - On Windows: install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and ensure the **WSL 2 backend** is enabled
- **Git**


## Quick Start

First-time setup:

```bash
git clone <repo-url>
cd HRMS
cp backend/.env.example backend/.env
```


For PowerShell on Windows:

```powershell
Copy-Item backend/.env.example backend/.env
```

Then run from repository root:

```bash
docker-compose up -d --build
docker-compose exec api alembic -c alembic.ini upgrade head
docker-compose exec api python scripts/seed.py
```

Open:

- App: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- API redoc: `http://localhost:8000/redoc`

Verify everything is working:

```bash
docker-compose ps
```

## Default Credentials

- Admin: `admin@mock-hrms.dev` / `password123`
- Manager: `manager@mock-hrms.dev` / `password123`
- Employee: `employee@mock-hrms.dev` / `password123`

## Configuration

Backend environment file: `backend/.env`

Use `backend/.env.example` as reference. Current key settings:

- `DATABASE_URL=sqlite+aiosqlite:///./storage/hrms.db`
- `APP_TIMEZONE=Asia/Kolkata`
- JWT settings (`JWT_SECRET_KEY`, expiry values)
- `CORS_ORIGINS`: comma-separated browser origins allowed to call the API
- AI settings (`LLM_*`, `EMBEDDING_*`, `RAG_*`): see `backend/.env.example`

## Common Commands

Start services:

```bash
docker-compose up -d
```

Restart API + Web after code changes:

```bash
docker compose restart api web
```

Stop services:

```bash
docker-compose down
```

Run migrations:

```bash
docker-compose exec api alembic -c alembic.ini upgrade head
```

Reseed data:

```bash
docker-compose exec api python scripts/seed.py
```

Optional one-time migration (legacy payslip files to DOB-password-protected PDFs):

```bash
docker compose exec api python scripts/migrate_payslips_to_encrypted_pdf.py
```

Check containers:

```bash
docker-compose ps
```

## Reset Database

On macOS/Linux:

```bash
docker-compose down
rm -f backend/storage/hrms.db
docker-compose up -d --build
docker-compose exec api alembic -c alembic.ini upgrade head
docker-compose exec api python scripts/seed.py
```

On PowerShell:

```powershell
docker-compose down
Remove-Item backend\storage\hrms.db -Force -ErrorAction SilentlyContinue
docker-compose up -d --build
docker-compose exec api alembic -c alembic.ini upgrade head
docker-compose exec api python scripts/seed.py
```

## API Notes

- API base path: `/api/v1`
- Health checks:
  - `/health`
  - `/api/v1/health`
- Standard response envelope:
  - Success: `{ "success": true, "data": ..., "error": null }`
  - Error: `{ "success": false, "data": null, "error": { "code": "...", "message": "..." } }`
- Document uploads:
  - Employee self-upload: `POST /api/v1/employees/me/documents`
  - Employee self-delete: `DELETE /api/v1/employees/me/documents/{document_id}` (`OTHER` type only)
  - Admin/Manager upload for any employee: `POST /api/v1/employees/{employee_id}/documents`
  - Admin/Manager payslip upload: `POST /api/v1/employees/{employee_id}/documents/payslip`

## Troubleshooting

- If frontend shows stale build/runtime issues:
  - `docker-compose restart web`
- If API changes are not reflected:
  - `docker-compose restart api`
- If migration or seed fails:
  - reset DB using the commands above, then migrate and seed again

## Documentation

- Learner guide: [`Learner_Guide.md`](docs/Learner_Guide.md) — full project walkthrough, architecture, database schema, learning path
- Product requirements: [`PRD.md`](docs/PRD.md)
- Database schema reference: [`db_tables_samples.md`](docs/db_tables_samples.md)
- AI chat endpoint contracts: `docs/api/`


Copyright (c) Codebasics. All rights reserved.


