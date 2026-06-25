# Design Document

**Candidate:** pradumansingh
**Date submitted:** June 23, 2026
**Time spent:** ~24 hours (M1: 8h, M2: 6h, M3: 6h, M4: 4h)

---

## 1. System Overview

Our medical billing extraction platform comprises a Next.js web frontend, Better Auth for identity, a FastAPI API gateway, an asynchronous worker pool, and a Postgres database. 

1. **Identity & Session:** A user signs up/in via the Next.js frontend, establishing a session in Postgres managed by Better Auth.
2. **Document Upload:** The client uploads a PDF. The Next.js API route (or client direct request) calls the FastAPI backend, passing the session token.
3. **Queueing & RLS:** FastAPI validates the session, writes a `pending` job to the `jobs` table (enforced by RLS), and saves the PDF.
4. **Worker Loop:** Background workers running under the `billing_worker` role query the queue, claim a job atomically, parse the PDF using `pypdf`, run the AI extraction orchestration pipeline, and save the resulting records.
5. **Isolation-Correct View:** The client page polls the API and renders the extracted billing records and manual review flags in a premium dark-themed dashboard.

---

## 2. Authentication, Identity & Isolation

### 2.1 Topology
Session creation and validation are owned by the **Better Auth** layer integrated within Next.js. 
- The Next.js server handles credentials verification and issues a session token stored in client cookies.
- For client-side API requests, the frontend sends the token in the `Authorization: Bearer <token>` header.
- The Python FastAPI backend directly validates the session token against the shared Postgres `session` and `user` tables (using `better-auth.session_token`).
- **Trust Boundary:** The web server and API trust the database session table as the source of truth. Unauthenticated or invalid token requests are immediately rejected with a 401 Unauthorized response before hitting service handlers.

### 2.2 RLS Enforcement
- **Tables:** The `jobs` table has RLS enabled.
- **Policies:**
  - `job_app_policy` (applied to `billing_app` role):
    `USING (user_id = current_setting('app.current_user_id', true))`
    `WITH CHECK (user_id = current_setting('app.current_user_id', true))`
  - `job_worker_policy` (applied to `billing_worker` role):
    `USING (status = 'pending' OR status = 'processing' OR user_id = current_setting('app.current_user_id', true))`
    `WITH CHECK (status = 'pending' OR status = 'processing' OR user_id = current_setting('app.current_user_id', true))`
- **App Roles vs Owner:** The database migrations run under the admin `billing` user (schema owner, bypasses RLS). The FastAPI app runs under the `billing_app` role, and the worker runs under `billing_worker`. Both have SELECT/INSERT/UPDATE/DELETE grants, but are strictly subject to RLS. If the app connected as owner, RLS would not be active, and a single coding mistake could leak database rows.
- **Identity Propagation:** FastAPI's authentication middleware extracts the validated user ID and sets it in a thread/async-local `ContextVar` (`current_user_id_ctx`). When a connection is checked out by the `ContextManager`, it executes `SET LOCAL app.current_user_id = '<user_id>'` inside the transaction block.

### 2.3 Connection Pooling Interaction
Because the database connection is pooled, setting a session-level config could leak to subsequent requests if a connection is returned to the pool dirty. 
- In our design, we use `SET LOCAL app.current_user_id = '<user_id>'`.
- In PostgreSQL, the `LOCAL` modifier restricts the parameter setting to the lifetime of the **current transaction**. 
- Because every SQLAlchemy database session lifecycle is wrapped in a transaction block, committing or rolling back the transaction automatically clears the local configuration setting. When the connection is checked back into the pool, it has no residual `app.current_user_id` value, eliminating cross-request identity leaks.

### 2.4 The Worker's Identity
- The background worker runs outside HTTP requests. It connects using the `billing_worker` database role.
- The `job_worker_policy` policy permits `billing_worker` to SELECT and UPDATE jobs where `status = 'pending'` or `status = 'processing'`. This lets the worker fetch pending jobs without knowing user IDs in advance.
- When saving completed results, the worker must set `status = 'completed'`. Since `'completed'` is not `'pending'` or `'processing'`, the policy requires `user_id = current_setting('app.current_user_id', true)`.
- Before saving the results, the worker calls `current_user_id_ctx.set(job.user_id)`. The transaction executes `SET LOCAL app.current_user_id`, matching the job owner and allowing the worker to update the job to terminal state securely.

### 2.5 The Isolation Guarantee
If a `WHERE` clause is missing or incorrect in our application code, RLS prevents data exposure. A database connection acting as `billing_app` with `app.current_user_id = 'userA'` will only see rows belonging to `userA`; any select or update statement targeted at `userB`'s records will return 0 rows.

---

## 3. Agent Design

### 3.1 Tools
- **`save_extracted_records`:** The core extraction tool. It was modified to iteratively aggregate records using `list.extend()` so that when processing large documents across multiple chunks, all records are properly accumulated into a single final output.
- No high-level agent frameworks (like LangChain) are used; the tool calling and orchestrator logic is built directly in vanilla Python and Pydantic models.

### 3.2 Navigation Strategy (Chunking)
- **File Text Extraction:** The worker uses `pypdf` to extract the plain-text content of each page.
- **Chunked Processing:** To strictly avoid LLM `Context Length Exceeded` errors on massive medical ledgers, the `ExtractorAgentExecutor` splits the document into batches of 10 pages. Each chunk is processed sequentially, and the agent's context is refreshed for the next chunk while accumulating the extracted records.
- **Schema Normalization:** The Pydantic output models (`BillingRecord`, `FlaggedRecord`) use `alias_generator=to_camel` and `model_dump(by_alias=True)`. This ensures that all extracted JSON perfectly matches the `camelCase` structure of the ground-truth downstream systems, completely decoupling the Python snake_case conventions from the API contract.

### 3.3 State Management
- Agent state is stored in the `RunContext` object. Executors append their metadata and output results to fields on `RunContext`, allowing downstream stages to inspect previous outputs.

### 3.4 Uncertainty and Flagging
- Extracted records and flagged items are isolated. If the confidence of a field is low, the pipeline populates a warning flag in the `flagged_records` list with the reason and page number rather than guessing, which prevents silent failures.

---

## 4. Job Queue & Reliability

### 4.1 Worker and Concurrency
To ensure that two concurrent workers never claim the same job, `claim_next_job` uses a transaction-locked query:
```sql
SELECT * FROM jobs 
WHERE status = 'pending' 
ORDER BY created_at ASC 
LIMIT 1 
FOR UPDATE SKIP LOCKED;
```
- `FOR UPDATE` locks the selected row.
- `SKIP LOCKED` causes concurrent workers to skip this row and look for the next pending job.
- Once claimed, the worker immediately updates the status to `processing` and commits the transaction, releasing the lock. Without this, workers would duplicate processing and double cost/tokens.

### 4.2 Crash Recovery
If a worker crashes mid-job, the job status remains `processing`. The worker loop includes a `recover_stalled` check that runs on every cycle:
- It queries for jobs in `processing` status where the `updated_at` timestamp is older than 5 minutes.
- It resets their status back to `pending`, clears the claiming worker ID, and increments a retry counter.

### 4.3 Status Transitions
- `pending -> processing`: Triggered by background worker claiming a job.
- `processing -> completed`: Triggered by successful worker completion.
- `processing -> failed`: Triggered by worker pipeline catching a fatal exception.
- `pending -> cancelled`: Triggered by API `DELETE /jobs/{id}` request from the owner.

### 4.4 Retry Policy
- If `ExtractionService` fails due to transient connection issues, the worker loop catches the error, increments retries, and leaves the status to be picked up again. Max retries is capped at 3, after which the job is marked `failed` with error details.

### 4.5 Cost and Latency Tracking
- **Latency:** Measured using Python's `time.perf_counter()` before and after the orchestrator run.
- **Cost & Tokens:** The token usage is aggregated from the LLM agent response metrics. Cost is calculated based on input/output pricing (e.g. $0.15/M tokens input, $0.60/M tokens output) and saved to `cost_usd`.

### 4.6 Result Caching
- **Deduplication:** When a file is uploaded, we compute its SHA256 `pdf_hash`.
- **RLS Safety:** The API checks for a completed job with that `pdf_hash` owned by the *current* user. Because `billing_app` is subject to RLS, the select query is automatically isolated to the current user's records. It is impossible to match or copy results from another user's job.
- **Bypass Flag:** Clients can supply a header to skip caching, forcing a new job creation and extraction.

---

## 5. Frontend

- **Structure:** Built with Next.js 16 (App Router), TypeScript, and Vanilla CSS.
- **Features:** Supports Sign-up, Login, and a full-featured Dashboard. Includes a drag-and-drop file zone, live job status polling, and a modal showing detailed grids of extracted records.
- **Styling & Theming:** Premium CSS-variable-based design system featuring glassmorphism, dynamic glowing status badges, and smooth micro-animations. It includes a fully functional Light/Dark mode toggle that persists user preference to `localStorage`.

---

## 6. Code Structure & Tooling

The application strictly separates database access (DAOs), business logic (Services), and routes (FastAPI controllers). The root `AGENTS.md` acts as an onboarding manual for AI coders, specifying running commands, configuration rules, and testing strategies.

---

## 7. Accuracy and Failure Analysis

- Tested extraction pipeline on provided sample PDFs in `/data`.
- Simple layout documents (e.g., direct tables) had high extraction precision. Multi-page ledger documents with mixed layouts required careful sequential page scanning.

---

## 8. AI Usage

- **Paxel report URL:** [None - Local Dev Session Profile]

---

## 9. Extending the Design

- **Tenant-Level Isolation:** Add an `org_id` column to the `user` and `jobs` tables. Change RLS policies to check: `org_id = current_setting('app.current_org_id', true)`. Propagate org context similarly via JWT or session.
- **Cross-Tenant Sharing:** Create a `job_shares` table mapping `job_id` to shared `org_id` / `user_id`. Update RLS policies to: `USING (user_id = current_setting(...) OR EXISTS (SELECT 1 FROM job_shares WHERE job_shares.job_id = jobs.id AND job_shares.shared_with = current_setting(...)))`.
- **Multi-worker Workflows:** Use a message queue (e.g. RabbitMQ or Celery) where user/tenant context is serialized into the message payload (e.g. a signed JWT). The detached worker validates the payload and adopts the user's RLS context before database operations.

---

## 10. Open Questions

- What are the production LLM token rate limits? High concurrency claims may trigger rate limit backoffs.
- Are PDFs OCR-preprocessed before upload, or should the worker support image OCR?
