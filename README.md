# Patient Imaging, Reports & Scheduling Portal

Take-home assessment for **AS Software** (Healthcare — Diagnostic Ultrasound / Medical
Imaging). Full requirements: [BRIEF.md](BRIEF.md).

Secure patient portal for ultrasound image and cine (multi-frame) viewing, signed-report
delivery, time-limited secure sharing, and concurrency-safe appointment scheduling — all
under first-class Protected Health Information (PHI) handling.

## Stack

Python 3.12 / FastAPI API, Next.js 16 (App Router, TypeScript, Tailwind v4) frontend,
Supabase for Postgres + Auth + Storage, Resend for email. Rationale and rejected
alternatives: [docs/tech-stack.md](docs/tech-stack.md).

## Repository layout

| Path | Contents |
|------|----------|
| `backend/` | FastAPI service — API, ORM models, Alembic migrations, pytest suite |
| `frontend/` | Next.js patient/provider UI |
| `docs/` | Stack decisions and design notes |
| `docker-compose.yml` | Local Postgres used by the test suite only |
| `.github/workflows/ci.yml` | Lint, type check, tests (backend) and lint, build (frontend) |

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/), Node 22+, Docker.

```bash
cp .env.example .env          # then fill in the Supabase, database, and Resend values
```

**Backend**

```bash
cd backend
uv sync --all-groups
uv run alembic upgrade head           # applies migrations to DATABASE_URL
uv run uvicorn app.main:app --reload  # http://localhost:8000 (docs at /docs)
```

**Frontend**

```bash
cd frontend
npm install
npm run dev                           # http://localhost:3000
```

**Tests**

The suite runs against a local throwaway Postgres, never the hosted database:

```bash
docker compose up -d                  # Postgres on :5433
cd backend && uv run pytest           # coverage report included
```

**Health check**

`GET /health` reports app, database, and storage reachability, returning `503` if any
dependency is degraded so an uptime check can key off the status code alone.

## Environment variables

Every variable is documented with a placeholder in [`.env.example`](.env.example).
`SUPABASE_SERVICE_ROLE_KEY` and `SUPABASE_JWT_SECRET` are server-only secrets and must
never reach the browser; only `NEXT_PUBLIC_*` values are exposed to the client.

## Status

Scaffold complete — application skeleton, health check, structured PHI-safe logging,
migrations wiring, local test database, and CI all run green. Schema, seed data, and
feature work land next.

- [x] Repo scaffold, CI, health check, PHI-redacting logger
- [ ] Schema + migrations + seed script with synthetic imaging assets
- [ ] Priority 1 — identity verification, image viewing, cine playback, secure sharing
- [ ] Priority 2 — signed-report viewing and secure sharing
- [ ] Priority 3 — availability, booking, concurrency guard, reminders
- [ ] Performance benchmarks (k6), deployment, demo

## Priorities

| Tier | Scope |
|------|-------|
| Priority 1 | Image access, cine playback, secure sharing, no cross-patient leakage |
| Priority 2 | Signed-report viewing and secure sharing |
| Priority 3 | Scheduling: availability, booking, no double-booking, reminders |

## AI usage

Disclosed in [AI_USAGE.md](AI_USAGE.md) as the brief requires.
