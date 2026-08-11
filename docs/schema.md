# Data Model

17 tables in one initial migration. This document covers the decisions that are not
obvious from reading the DDL; the migration itself is the source of truth.

## Tables

| Domain | Tables |
|---|---|
| Identity | `patients`, `providers`, `staff`, `identity_verifications`, `identity_attempts` |
| Imaging (P1) | `studies`, `images`, `cine_clips`, `cine_frames` |
| Reports (P2) | `reports` |
| Sharing (P1/P2) | `share_links` |
| Scheduling (P3) | `availability_rules`, `blocked_ranges`, `appointment_slots`, `appointments` |
| Cross-cutting | `audit_log`, `reminder_sends` |

## Decisions

### Two identity entities, linked on verification

A `patients` row is a clinical record, seeded before anyone signs up. Core #2 has the
patient verify against a *pre-existing* account id and date of birth, which only makes
sense if that record predates the portal account. `patients.auth_user_id` is null until a
successful verification links the login to the record.

`auth_user_id` is a plain `uuid` with no foreign key into `auth.users`. That schema belongs
to Supabase; referencing it would couple our migrations to a platform-managed schema and
make the migration unrunnable against the plain Postgres used by CI.

### Random UUID primary keys on addressable tables

Core #6 and #9 are graded by an adversarial test that walks incrementing ids looking for
another patient's data. Sequential keys would be a designed-in enumeration vector, so
anything addressable from outside the API uses `gen_random_uuid()`. The index-locality cost
is irrelevant at this dataset's scale.

`audit_log` and `identity_attempts` keep `bigint identity`: they are append-only, never
appear in a URL, and benefit from the insert locality.

### No double-booking is a constraint, not application logic

Slots are materialised rows, so "this slot" is a real lockable object:

```sql
CREATE UNIQUE INDEX uq_appointments_slot_id_live
  ON appointments (slot_id)
  WHERE status IN ('requested', 'confirmed');
```

Scoped to live statuses deliberately. A plain `UNIQUE (slot_id)` would enforce concurrency
correctly but wedge the slot forever, breaking reschedule and cancel (Core #13). The
partial predicate gives both guarantees in one constraint.

`appointments.slot_id` is `ON DELETE RESTRICT`, so a provider shrinking their hours cannot
delete a slot out from under a booked patient (edge case #8) — the delete fails loudly.

### Row level security is a door closure, not authorization

Every table has RLS enabled with **no policies**. This is not row-level authorization.

Supabase publishes every table in `public` through PostgREST, reachable with the
publishable key that ships in the browser bundle. Without RLS, anyone who opened devtools
could read every patient, study, and report straight from the REST endpoint, bypassing this
API entirely. Verified before and after: with RLS off, an anon read of a populated table
returned rows; with RLS on, it returns `[]` and writes fail with `42501`.

RLS is **not** `FORCE`d. The API connects as a role with `BYPASSRLS`, so policies would
never fire for it — using RLS as the authorization mechanism would require a dedicated role
and per-transaction `SET LOCAL` plumbing, whose own failure mode is silent full bypass.
Ownership is therefore enforced server-side in application code, at a single query-scoping
chokepoint, and proven by adversarial tests against real endpoints.

Two tests guard this: one asserts every table has RLS enabled, the other asserts none is
`FORCE`d (which would lock the API out of its own data).

### Audit log is append-only in the database

A `BEFORE UPDATE OR DELETE` trigger raises on any mutation. An audit log that can be
rewritten is worthless for compliance review — someone who accessed the wrong patient's
chart could erase the evidence. The table carries actor, action, target reference and
timestamp only; recording names or findings would move PHI into a table read routinely by
operators.

### Times

Availability is local wall-clock in the provider's own IANA zone (`providers.timezone`);
slots are materialised into `timestamptz` UTC. "Mon–Fri 9–5" means nine o'clock locally on
both sides of a daylight-saving change, so a DST transition neither duplicates nor skips
slots (edge case #6).

### Share tokens are stored hashed

`share_links.token_hash` holds a SHA-256 digest; the token itself exists only in the emailed
URL. These URLs grant PHI access without a login, so a database dump must not contain
working links. `resource_id` is intentionally not a foreign key — it points at either an
image or a report depending on `resource_type`, which Postgres cannot express as a
conditional reference.

## What this schema does not do

Cross-patient isolation is **not** proven by this layer. Ownership columns exist, but the
guarantee lives in application code and will be proven by adversarial tests once the PHI
endpoints exist. Nothing here should be read as satisfying Core #6 or #9.

## Verification

```bash
docker compose up -d
cd backend && uv run pytest tests/schema/
```

The concurrency test is mutation-checked: dropping `uq_appointments_slot_id_live` makes all
20 concurrent bookings succeed, so the test is detecting the constraint rather than passing
incidentally.
