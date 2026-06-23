# AI Coding Agent Guide (AGENTS.md)

Welcome! This guide helps AI coding agents (and developers) understand the layout, architectural conventions, database row-level security (RLS) patterns, and testing procedures of this repository to start contributing immediately.

---

## 1. Project Layout

The codebase is split into a Next.js frontend and a FastAPI backend:

```
├── docker-compose.yml          # Local multi-container development environment
├── .env.example                # Template env configuration
├── docs/                       # Domain, schema specifications, and design doc
├── data/                       # Ground-truth JSONs and sample PDFs
├── frontend/                   # Next.js web client & Better Auth server
│   ├── src/
│   │   ├── app/                # Next.js app pages (auth/login, auth/signup, dashboard)
│   │   ├── lib/                # Better Auth server configuration and client hooks
│   │   └── db/                 # Server-side Postgres database driver
│   ├── Dockerfile
│   └── package.json
└── backend/                    # FastAPI server & background worker
    ├── main.py / worker.py     # API and worker entrypoints
    ├── tests/                  # Backend unit/integration test suites
    ├── alembic/                # Database migrations
    ├── app/
    │   ├── api/                # FastAPI routers and dependency injection
    │   ├── dao/                # Data Access Object (DAO) pattern (SQLAlchemy ORM)
    │   ├── service/            # Core business logic (JobService, ExtractionService)
    │   ├── ai/                 # Agent pipelines (ExtractionOrchestrator, EchoAgent)
    │   └── core/               # App configuration, logging, and database context
    ├── Dockerfile
    └── pyproject.toml
```

---

## 2. Running & Testing

### Running the Stack Local / Docker
Spin up the entire stack (Postgres, Alembic migrations, FastAPI backend, background workers, Next.js frontend) with a single command:
```bash
docker compose up --build
```
- **Frontend URL:** [http://localhost:3000](http://localhost:3000)
- **API Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)

### Running Backend Tests
Execute the unit and integration tests inside the virtual environment using `uv`:
```bash
cd backend
uv run python -m unittest tests/test_jobs.py
```

---

## 3. Key Design Patterns

### Row-Level Security (RLS) & Role Topology
The database contains RLS policies to strictly isolate user data at the database layer:
1. **`billing_app` role:** Used by the FastAPI web server. Every query automatically restricts records based on the session variable `app.current_user_id`.
2. **`billing_worker` role:** Used by the background workers. Workers can query and update jobs whose status is `'pending'` or `'processing'`. When updating to a terminal status (like `'completed'`), the worker must adopt the owner's identity via `app.current_user_id` so the RLS update assertion passes.

### ContextVar & Session Context
To ensure that RLS propagates correctly across connection pools and async tasks, we use a `ContextVar` (`current_user_id_ctx` inside `backend/app/core/context_manager.py`). 
- On every API call, the auth dependency validates the Better Auth session token, extracts the `user_id`, and sets the ContextVar.
- The `ContextManager` session lifecycle wrapper automatically runs `SET LOCAL app.current_user_id = '<user_id>'` inside the database transaction.

### Content-Based Caching
- When a user uploads a PDF, the API calculates its SHA256 hash.
- The API checks if a completed job with the same hash exists **for the same user**.
- If a match is found, a new job is created in `completed` status and the cached results are instantly copied over, bypassing worker execution.

---

## 4. Tips for AI Coding Agents

- **Always verify RLS context:** When writing DAO methods or modifying routes, ensure that `current_user_id_ctx` is set. Never bypass RLS by querying as the schema owner.
- **Do not shadow Python keywords:** Note that the `JobDAO` has a method named `list`. To prevent type annotation issues, always include `from __future__ import annotations` at the top of the file so `list[dict]` evaluates correctly.
- **Mock dependency injection in tests:** FastAPI dependency overrides are set up in `tests/test_jobs.py`. Always override `get_current_user_id` and mock the service layer to keep tests fast and independent.
