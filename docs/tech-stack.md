# Tech Stack — Patient Imaging, Reports & Scheduling Portal

Major decisions only. Library-level choices are deferred — see Open sub-decisions.

| Layer | Component | Choice | Reason |
|---|---|---|---|
| Backend | Language & framework | Python 3.12 + FastAPI | Async I/O suits fan-out cine frame delivery; Pydantic gives server-side validation of every PHI payload for free. |
| Backend | ORM & migrations | SQLAlchemy 2.0 (async) + Alembic | `SELECT … FOR UPDATE` is first-class, which is what backs the no-double-booking guard; Alembic gives the committed migrations the brief grades. |
| Backend | Architecture | Separate API service | Long-running process affords a real sub-hourly reminder job; k6 loads a stable API surface independent of the frontend host. |
| Frontend | Framework | Next.js (App Router) + TypeScript | Named in the brief; server components keep the image/cine viewer shell fast on mobile. |
| Data | Database | Supabase Postgres | Postgres row-locking is the concurrency primitive the brief requires, bundled free with auth and storage. |
| Data | Auth | Supabase Auth | Argon2 hashing, session expiry, and JWT issuance are solved out of the box; FastAPI verifies the JWT and enforces RBAC itself. |
| Data | Object storage | Supabase Storage | S3-compatible with time-limited signed URLs — the exact primitive secure share links need; 1 GB free covers mock frames. |
| Backend | Reminder scheduler | An `asyncio` task in the API process, plus a CLI entrypoint | Correctness already lives in the `reminder_sends` unique constraint, so the scheduler is chosen on operability: no new service to configure, and `python -m app.reminders` fires the same code path on demand for the demo and for graders. |
| Infra | Backend hosting | Railway | Free tier runs a persistent Python process, which is also what lets the reminder job poll in-process. |
| Infra | Frontend hosting | Vercel | Free tier, first-party Next.js support, preview deploys per push. |
| Infra | Email | Resend | Mandated by the brief; free tier covers reminders and share links. |

**Substitution note (brief §Tech Stack):** the brief specifies C# ASP.NET Core *or*
Node/Express and permits substitution "if justified and benchmarks met." Python/FastAPI
is chosen for async frame fan-out and Pydantic-enforced input validation on every PHI
route. It changes no architectural guarantee the brief asks for — Postgres transactional
row-locking, server-side RBAC, and audit logging are all unaffected. All performance
benchmarks in the brief still apply unchanged and will be reported from the same k6
scripts.

## Rejected alternatives

| Component | Option | Why not |
|---|---|---|
| Language & framework | C# / ASP.NET Core | Strong signaling fit if AS Software is a .NET shop, but a second toolchain to stand up costs more than it returns inside 3 days. |
| Language & framework | Node / Express | Would unify the language with the frontend, but loses Pydantic's validate-at-the-boundary story on PHI routes. |
| Language & framework | Django | Batteries-included admin and ORM are nice, but sync-first request handling fights the 100-frame cine fan-out. |
| Language & framework | Flask | Needs validation, async, and OpenAPI bolted on that FastAPI ships with. |
| ORM & migrations | SQLModel | Thin layer over SQLAlchemy with weaker async and locking ergonomics on the paths that matter most. |
| ORM & migrations | Raw asyncpg | Maximum control over the locking query, but hand-rolling migrations burns timebox on a graded requirement. |
| Architecture | Next.js route handlers only | One deploy and no CORS, but Vercel's free tier caps cron at once-daily, which makes reminder dispatch awkward. |
| Reminder scheduler | APScheduler | Built and then removed: two dependencies and three strict-mode suppressions (it ships no type stubs) to buy one feature a fifteen-line `asyncio` loop already provides. |
| Reminder scheduler | Separate Railway cron service | Survives an API restart and separates concerns, but adds a service and env vars a grader must configure before the reminder flow works. |
| Reminder scheduler | Supabase `pg_cron` | Fires even when the API is down, but needs `pg_net` or an Edge Function, moving the send path into SQL or Deno and outside the app's audit-writing and PHI log redaction. |
| Reminder scheduler | GitHub Actions scheduled workflow | Free with visible run logs, but puts a production trigger in CI and requires exposing a secret-protected dispatch endpoint on a PHI application. |
| Frontend framework | Vite + React SPA | Lighter, but forfeits server components and image optimization on the mobile-first viewer. |
| Database | Neon | Fine Postgres, but pairing it with separate auth and blob vendors adds two integrations for no gain. |
| Database | Railway Postgres | Colocated with the API, but no bundled auth or object storage. |
| Auth | Hand-rolled FastAPI auth (argon2 + JWT) | Fully controllable, but rebuilds hashing, session expiry, and reset flows the rubric treats as table stakes. |
| Auth | Auth0 / Clerk | Free tiers exist, but adds a third-party PHI-adjacent vendor needing a BAA for no capability gain. |
| Object storage | Vercel Blob / Netlify Blobs | Viable free blob stores, but split from the database vendor and weaker signed-URL expiry controls. |
| Object storage | Railway volume | Block disk, not object storage — no signed URLs, and the brief explicitly warns against it. |
| Backend hosting | Render | Comparable free tier, but cold starts on idle would distort the p95 benchmarks. |
| Backend hosting | Fly.io | Capable, but more infra configuration than a 3-day build justifies. |
| Frontend hosting | Netlify | Equivalent free tier; Vercel wins only on first-party Next.js integration. |
| Email | — | Uncontested — Resend is mandated by the brief. |

## Open sub-decisions

- ~~**Cine/image delivery path**~~ — resolved: proxied through FastAPI, not signed URLs
  handed to the browser. Signed URLs are faster but the audit log never sees the read, and
  the brief requires every PHI access recorded. The bandwidth cost that argued against
  proxying was answered instead by a bundle endpoint (`GET /cine/{id}/frames`) that
  returns a whole clip in one packed response rather than a hundred round trips.
- **Reminder outage tolerance** — the in-process scheduler pauses while the API container
  is down. At a 24-hour lead and a 15-minute poll that needs a roughly day-long outage to
  miss a send, which the ≥99% target absorbs. Revisit only if the deployed uptime check
  shows sustained gaps.
