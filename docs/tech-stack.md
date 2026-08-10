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
| Infra | Backend hosting | Railway | Free tier runs a persistent Python process plus a separate cron/worker service for reminders. |
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

- **Cine/image delivery path** — signed URLs straight from Supabase Storage to the
  browser (fast, but the audit log never sees the read) vs. proxying bytes through
  FastAPI (every PHI read logged, but the API becomes the bandwidth bottleneck against
  the <1 s time-to-first-frame target). Likely a hybrid; resolve when building Core #3/#4
  and revisit under Stretch #16.
- **Reminder scheduler** — in-process APScheduler vs. a separate Railway cron service vs.
  Supabase `pg_cron`. Resolve when building Core #15; idempotency is enforced by a
  persisted send record regardless of which wins.
- **Test & CI toolchain** — pytest + httpx assumed for backend, Playwright for E2E, k6
  for load. Pin versions and CI wiring at first commit.
- **Cine manifest schema** — frame ordering, per-frame URLs, and the missing-frame
  representation that Edge Case #2 needs. Resolve before Core #4.
