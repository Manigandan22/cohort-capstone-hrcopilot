# Deployment Guide (free tier)

The whole stack runs on free tiers. Every component is open source except the hosted LLM, and
that can be swapped for a local Ollama model (option B).

| Layer | Free option used here | Notes |
|---|---|---|
| Backend (FastAPI + SQLite) | **Hugging Face Docker Space**, free CPU tier | Container disk is ephemeral; demo data is re-seeded on every cold start (about 10 s) |
| Frontend (Next.js) | **Vercel Hobby** | Root directory `frontend` |
| LLM | **Gemini API** free tier (or Groq) | Any OpenAI-compatible endpoint; set by environment variables |
| Embeddings | `BAAI/bge-small-en-v1.5` via fastembed, **inside the backend** | Downloaded once per cold start (about 130 MB) |
| Vector store | SQLite + NumPy, inside the backend | No extra service |

```text
Browser ──> Vercel (Next.js /ai-copilot) ──HTTPS──> HF Space (FastAPI :7860) ──> Gemini API
                                                        └─ SQLite + local embeddings + vector index
```

---

## Option A: Hugging Face Spaces + Vercel

### 1. Backend on Hugging Face Spaces

1. Create a free account at <https://huggingface.co>, then go to **New Space**:
   - Name: e.g. `cbnest-copilot-api`
   - SDK: **Docker** (blank template)
   - Hardware: **CPU basic (free)**
   - Visibility: Public, or Private if you only share the frontend
2. Clone the empty Space next to this repository. When git asks for a password, use a Hugging
   Face **access token** with *write* permission (Settings → Access Tokens).
   ```bash
   git clone https://huggingface.co/spaces/<your-username>/cbnest-copilot-api
   ```
3. Copy the backend into it and push. The script works on Windows, macOS and Linux:
   ```bash
   cd cohort-capstone-hrcopilot
   python deploy/huggingface/prepare_space.py ../cbnest-copilot-api
   cd ../cbnest-copilot-api
   git add -A && git commit -m "Deploy CB Nest AI Copilot API" && git push
   ```
   The script copies `backend/`, adds the Space `Dockerfile` (port 7860, non-root user) and the
   Space `README.md`. It leaves out tests, local data, `.env` and binary files.
4. In the Space go to **Settings → Variables and secrets** and add:

   | Type | Name | Value |
   |---|---|---|
   | Secret | `LLM_API_KEY` | your Gemini (or Groq) API key |
   | Secret | `JWT_SECRET_KEY` | a long random string, e.g. `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
   | Variable | `LLM_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` |
   | Variable | `LLM_MODEL` | `gemini-3.5-flash-lite` |
   | Variable | `CORS_ORIGINS` | your Vercel URL, e.g. `https://cbnest-copilot.vercel.app` (fill in after step 2) |
   | Variable | `CORS_ORIGIN_REGEX` | optional, e.g. `https://cbnest-copilot-.*\.vercel\.app` for Vercel previews |

5. The Space builds and starts automatically (first build about 5 minutes). Check
   `https://<your-username>-cbnest-copilot-api.hf.space/health` → `{"success": true, ...}` and
   open `/docs` on the same host.

### 2. Frontend on Vercel

1. Sign in at <https://vercel.com> with GitHub and click **Add New → Project**, then import
   this repository.
2. Set **Root Directory** to `frontend`. The framework (Next.js) is detected automatically.
3. Add the environment variable
   `NEXT_PUBLIC_API_BASE_URL = https://<your-username>-cbnest-copilot-api.hf.space`
   with no trailing slash.
4. Deploy. If you change the variable later, **redeploy**: `NEXT_PUBLIC_*` values are built into
   the bundle.
5. Put the final Vercel URL in the Space's `CORS_ORIGINS` (step 1.4); the Space restarts by itself.

### 3. Smoke test

1. Open the Vercel URL and log in as `employee@mock-hrms.dev` / `password123`.
2. Open **AI Copilot** and ask "How many sick leaves do I get?". You should get an answer with
   **Leave Policy** as the source.
3. Log in as `manager@mock-hrms.dev` and ask "Approve Employee User's pending leave request.".
   You should get a **Confirm** card.

### Free-tier behaviour to know

- **Spaces sleep** after a period of inactivity. The first request after that wakes the
  container: allow about 1 minute for start, seed and model download. Open the Space URL a few
  minutes before a live demo.
- **Data resets on every restart** (ephemeral disk). That suits a demo; for persistence, attach
  paid persistent storage or switch `DATABASE_URL` to a hosted Postgres.
- **Gemini free-tier quotas are small** (e.g. `gemini-3.5-flash` allows 20 requests/day). Use a
  `flash-lite` model, enable billing, or use Groq (`LLM_BASE_URL=https://api.groq.com/openai/v1`,
  `LLM_MODEL=llama-3.3-70b-versatile`). Rate limits show in the UI as "The AI service is busy…".
- Access tokens last 60 minutes in the Space image (`ACCESS_TOKEN_EXPIRE_MINUTES`); log in again
  after that.

---

## Option B: fully local and fully open source (Docker Compose + Ollama)

No API keys and nothing leaves your machine. Needs about 8 GB of free RAM for the model.

1. Install [Ollama](https://ollama.com) and pull a model that supports tool calling:
   ```bash
   ollama pull qwen2.5:7b
   ```
2. In `backend/.env`:
   ```
   LLM_BASE_URL=http://host.docker.internal:11434/v1
   LLM_MODEL=qwen2.5:7b
   LLM_API_KEY=
   ```
   No key is needed for local endpoints. Use `http://localhost:11434/v1` when running without
   Docker.
3. Start the stack as in the README:
   ```bash
   docker-compose up -d --build
   docker-compose exec api alembic -c alembic.ini upgrade head
   docker-compose exec api python scripts/seed.py
   ```

Smaller local models are noticeably weaker at tool calling than hosted models. The safety layers
(permissions, SQL guardrails, confirmations) do not depend on model quality.

---

## Production checklist

- [ ] `JWT_SECRET_KEY` is a long random secret, never committed.
- [ ] `LLM_API_KEY` is set only as a host secret.
- [ ] `CORS_ORIGINS` lists only your frontend URL(s).
- [ ] `/health` responds and `/docs` loads.
- [ ] The smoke test above passes for employee and manager.
