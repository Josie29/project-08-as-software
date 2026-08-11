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
| `docs/` | Stack decisions ([tech-stack.md](docs/tech-stack.md)) and data model ([schema.md](docs/schema.md)) |
| `docker-compose.yml` | Local Postgres used by the test suite only |
| `.github/workflows/ci.yml` | Lint, type check, tests (backend) and lint, build (frontend) |

## Live deployment

| | |
|---|---|
| Patient portal | https://as-software-portal.vercel.app |
| API | https://portal-api-production-ce88.up.railway.app |
| Health | https://portal-api-production-ce88.up.railway.app/health |

Both redeploy automatically on a push to `main` — Vercel from `frontend/`, Railway from
`backend/`. Sign in with the demo credentials below.

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

**Seed**

```bash
cd backend
uv run python -m app.seed                 # demo profile, ~12s
uv run python -m app.seed --reset         # replace existing seeded data
uv run python -m app.seed --profile full  # benchmark dataset (~11k assets, ~87 MB)
```

`--skip-assets` seeds rows only, `--dry-run` reports asset count and size without
writing anything. Re-runs skip objects already in storage, so an interrupted upload
resumes rather than starting over.

### Demo accounts

Password for all: `PortalDemo!2026`

| Login | Role | Identity check |
|---|---|---|
| `patient@demo.test` | patient | account `AS-100241`, DOB `1991-06-24` |
| `neighbour@demo.test` | patient | account `AS-100377`, DOB `1985-02-09` |
| `provider@demo.test` | provider | — |
| `admin@demo.test` | front-desk admin | — |

Patient logins start **unverified** on purpose: the account exists, but it is not linked
to a clinical record until the ID and date-of-birth check passes, so the identity flow is
exercised rather than skipped.

The demo patient carries a 100-frame cine clip, a clip with two frames deliberately
missing, a signed report and a preliminary one that must stay hidden, and cancelled and
future studies that must not appear in the patient's list.

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
`SUPABASE_SERVICE_ROLE_KEY` is a server-only secret and must never reach the browser;
only `NEXT_PUBLIC_*` values are exposed to the client. There is no JWT secret to
configure — the project signs tokens with an asymmetric key, so the API verifies them
against a JWKS URL derived from `SUPABASE_URL`.

## Status

Schema and seed complete. 17 tables in committed migrations, applied to local Postgres
and Supabase, with no-double-booking enforced by a partial unique index and proven by a
mutation-checked concurrency test. The demo profile seeds a working dataset in about
twelve seconds. Priority 1 feature work is next.

- [x] Repo scaffold, CI, health check, PHI-redacting logger
- [x] Schema + migrations (17 tables, [docs/schema.md](docs/schema.md))
- [x] Seed script with synthetic imaging assets (demo and full profiles)
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
