# Performance benchmarks

Measured with the committed k6 script ([`k6/portal.js`](../k6/portal.js)) at the brief's
stated load: 20 → 50 concurrent virtual users for 60 seconds against the seeded dataset.
Booking and share-link creation run sequentially (25 iterations), which is the method the
brief states for those two rows.

**These targets are not currently met.** The numbers below are the real ones, and the
analysis of why is in the second half.

## Results

Run 2026-08-13. `local` is the API on a laptop; `deployed` is Railway. Both talk to the
same Supabase project (Postgres + Storage).

| Target | Brief | Local p95 | Deployed p95 |
|---|---|---|---|
| Single image load | < 1.0 s | 7.86 s | 20.71 s |
| Cine time-to-first-frame (100 frames) | < 1.0 s | 13.20 s | 30.31 s |
| Cine fully loaded (100 frames) | < 5.0 s | 26.83 s | 37.22 s |
| Share-link generation | < 1.0 s | 4.61 s | 5.31 s |
| Slot-availability query | < 1.0 s | 6.45 s | 19.42 s |
| Booking action | < 1.0 s | 5.02 s | 1.40 s |

Correctness held throughout: 687/687 checks passed on the local run, and no request
returned a 5xx. The failure is latency, not behaviour.

## The same endpoints with no concurrency at all

This is the diagnostic that matters, because it separates queueing from per-request cost.
Single sequential `curl`s, nothing else running:

| Endpoint | Local | Deployed |
|---|---|---|
| Slot availability (30 days) | 0.34 s | 0.71 – 0.85 s |
| Single image (21 KB) | 0.64 – 0.74 s | 1.05 – 1.20 s |

A 21 KB image takes over a second on the deployed API **with one user**. The p95 target is
already missed before any load is applied, so this is not primarily a concurrency problem.

## Why

Two compounding causes, in order of size.

**Every PHI request makes three sequential round trips to Supabase.** Serving one image
means an authorisation query, an audit-log insert and commit, and then downloading the
object from Storage — each a separate network hop to a managed service, none overlapping.
For a 21 KB payload the bytes are irrelevant; the request is three latencies in a trench
coat. This is the direct cost of the delivery decision recorded in
[tech-stack.md](tech-stack.md): bytes are proxied through the API precisely so that every
read is audited, and signed URLs straight to Storage were rejected because the audit log
would never see the read.

**Under load, a five-connection pool serialises fifty users.** `DB_POOL_SIZE=3` and
`DB_MAX_OVERFLOW=2` are not arbitrary — Supabase's session pooler caps the project at 15
concurrent clients, and a rolling deploy runs two containers, so the per-instance budget is
genuinely small. Fifty virtual users against five connections queue, which is what turns a
0.7 s slot query into 19 s. The cine rows are worst because one iteration pulls a whole
100-frame clip through that same pool.

## What was changed, and what it bought

**The HTTP client to Supabase Storage is now pooled** (`app/services/storage.py`). It was
constructed per call, so every object fetch paid a fresh TCP and TLS handshake — a
100-frame cine clip meant 100 handshakes.

Measured as an interleaved A/B — the two clients alternating over the same objects in the
same process, so network drift hits both arms equally:

| Run | Per-call (before) | Pooled (after) | Improvement |
|---|---|---|---|
| 1 | 422 ms | 288 ms | 134 ms (32%) |
| 2 | 920 ms | 374 ms | 546 ms (59%) |
| 3 | 488 ms | 376 ms | 113 ms (23%) |

The saving is the handshake, so it scales with round-trip time — which is why the absolute
figure moves with conditions while the direction never does.

**Why the end-to-end k6 numbers are not quoted as a before/after.** Network latency to
Supabase varied by more than 2× during the session this was measured in: identical per-call
code cost 422 ms per object in one run and 920 ms in another. Against that drift, k6 runs
taken an hour apart cannot attribute a difference to a code change, and presenting them as
before/after would be measuring the weather. The interleaved comparison above is the honest
one. A trustworthy end-to-end comparison needs both builds running side by side against the
same Supabase project at the same moment.

**The audit commit was left synchronous**, though it costs ~260 ms on every PHI read. The
obvious optimisation is to write it behind the response, but `open_image` documents the
opposite choice deliberately: recording a read that later fails mid-transfer is safer than
missing one that succeeded. Security carries 20 rubric points and Performance 10, so
inverting a documented compliance decision to win latency is the wrong trade for this brief.
It is a real option, just not a free one.

## What would fix it

Ordered by measured return. These are untried — the honest list, not a changelog.

Component costs for one image request, measured directly against the same Supabase project:

| Component | Median |
|---|---|
| Storage download (21 KB object) | 584 ms |
| Audit insert and commit | 260 ms |
| Ownership query | 46 ms |
| Identity-verification query | 46 ms |

1. **Serve image and frame bytes by short-lived signed URL.** The largest cost by far, and
   it also removes the API as a bandwidth bottleneck — 99 MB flowed through it during one
   local run. The browser fetches from Storage directly; the API still authorises first.
   This reopens the tension [tech-stack.md](tech-stack.md) settled: the audit row would
   record the *grant* rather than the read. That is the decision to revisit first, and it
   should be revisited deliberately rather than slipped in for a latency win.
2. **Write the audit log behind the response** — worth ~260 ms, against the compliance
   trade described above.
3. **Move to the transaction pooler** (port 6543, asyncpg statement cache disabled) for a
   larger connection budget than the session pooler's 15-client cap allows. This one is
   audit-neutral and is the next thing to try.
4. **Fold the identity-verification check into the scope's own queries** so the two become
   one round trip. Worth ~46 ms. Note this is *not* the same as caching the check, which
   would let a revoked verification keep working — measured, it is also the smallest win of
   the four, so the risky version of it is not worth considering.

Items 1 and 2 are what Stretch #16 asks for. They are not built, and this document exists
so that is visible rather than implied.

## Reproducing

```bash
k6 run \
  -e API=http://localhost:8000 \
  -e SUPABASE_URL=... -e SUPABASE_ANON_KEY=... \
  -e EMAIL=patient@demo.test -e PASSWORD=... \
  -e ACCOUNT_ID=AS-100241 -e DOB=1991-06-24 \
  k6/portal.js
```

Thresholds match the brief's targets, so the run exits non-zero while they are missed.
There is also a floor on iteration count: a percentile over zero samples reports as
passing, and a run that collected nothing should not look like a fast one.

The script books and cancels real appointments and mints real share links. Each iteration
cleans up after itself, and `teardown` releases anything still held when a cancel loses its
race for the connection pool. Prefer running it against a local stack.

Nothing is left holding a slot, but cancelled and revoked rows do accumulate, because the
script can only reach the API and the API has no delete. Both are tagged, so clearing them
from the demo database before recording a demo is one statement each:

```sql
DELETE FROM appointments WHERE idempotency_key LIKE 'k6-%';
DELETE FROM share_links  WHERE recipient_email = 'benchmark@example.com';
```
