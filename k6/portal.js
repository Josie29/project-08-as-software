import { check, fail } from "k6";
import http from "k6/http";
import { Trend } from "k6/metrics";

/**
 * Load test for the brief's Performance Benchmarks table.
 *
 * Every row in that table has a Trend below and a threshold matching its stated target, so
 * a regression fails the run rather than needing someone to read the numbers.
 *
 * Read-heavy PHI endpoints run under the brief's stated load: 20-50 concurrent virtual
 * users for 60 seconds. Booking and share-link creation run sequentially instead, because
 * both mutate state — the brief specifies "20+ runs" and "request to link issued" for
 * those two rather than sustained concurrency, and 50 VUs booking for a minute would
 * consume every slot in the diary before it measured anything.
 *
 * Usage:
 *   k6 run -e API=http://localhost:8000 \
 *          -e SUPABASE_URL=... -e SUPABASE_ANON_KEY=... \
 *          -e EMAIL=patient@demo.test -e PASSWORD=... \
 *          -e ACCOUNT_ID=AS-100241 -e DOB=1991-06-24 \
 *          k6/portal.js
 */

const API = __ENV.API || "http://localhost:8000";

/** One Trend per row of the brief's table, named to match it. */
const imageLoad = new Trend("brief_single_image_load", true);
const cineFirstFrame = new Trend("brief_cine_time_to_first_frame", true);
const cineFullyLoaded = new Trend("brief_cine_fully_loaded", true);
const shareGeneration = new Trend("brief_share_link_generation", true);
const slotQuery = new Trend("brief_slot_availability_query", true);
const bookingAction = new Trend("brief_booking_action", true);

export const options = {
  scenarios: {
    // Ramps across the brief's stated 20-50 concurrent users and holds for 60 seconds.
    browse: {
      executor: "ramping-vus",
      startVUs: 20,
      stages: [
        { duration: "10s", target: 20 },
        { duration: "10s", target: 50 },
        { duration: "60s", target: 50 },
      ],
      exec: "browse",
      gracefulStop: "10s",
    },
    // Sequential and bounded: these two write, and each booking is cancelled immediately
    // so the run leaves the diary as it found it.
    mutate: {
      executor: "per-vu-iterations",
      vus: 1,
      iterations: 25,
      exec: "mutate",
      startTime: "5s",
      maxDuration: "5m",
    },
  },
  thresholds: {
    brief_single_image_load: ["p(95)<1000"],
    brief_cine_time_to_first_frame: ["p(95)<1000"],
    brief_cine_fully_loaded: ["p(95)<5000"],
    brief_share_link_generation: ["p(95)<1000"],
    brief_slot_availability_query: ["p(95)<1000"],
    brief_booking_action: ["p(95)<1000"],
    // A run full of 500s could otherwise post excellent latency numbers.
    checks: ["rate>0.99"],
    // A percentile over zero samples reports as passing, so a run that collected nothing
    // looks identical to a fast one. This is the floor that tells the two apart.
    iterations: ["count>100"],
  },
};

/**
 * Sign in and clear the identity gate, then discover the ids the scenarios exercise.
 *
 * Runs once. The identity check is deliberately rate-limited, so it must not be part of
 * the per-iteration path.
 *
 * @returns Auth header plus the resource ids under test.
 */
export function setup() {
  const supabaseUrl = __ENV.SUPABASE_URL;
  const anonKey = __ENV.SUPABASE_ANON_KEY;
  if (!supabaseUrl || !anonKey) fail("SUPABASE_URL and SUPABASE_ANON_KEY are required");

  const signIn = http.post(
    `${supabaseUrl}/auth/v1/token?grant_type=password`,
    JSON.stringify({
      email: __ENV.EMAIL || "patient@demo.test",
      password: __ENV.PASSWORD,
    }),
    { headers: { apikey: anonKey, "Content-Type": "application/json" } },
  );
  if (signIn.status !== 200) fail(`sign-in failed: ${signIn.status} ${signIn.body}`);
  const headers = {
    Authorization: `Bearer ${signIn.json("access_token")}`,
    "Content-Type": "application/json",
  };

  const verified = http.post(
    `${API}/identity/verify`,
    JSON.stringify({
      account_id: __ENV.ACCOUNT_ID || "AS-100241",
      date_of_birth: __ENV.DOB || "1991-06-24",
    }),
    { headers },
  );
  if (verified.status !== 200) fail(`identity check failed: ${verified.status} ${verified.body}`);

  const studies = http.get(`${API}/studies`, { headers }).json();
  if (!studies.length) fail("no completed studies in the seeded dataset");

  // The largest clip, so the cine rows measure the brief's 100-frame case rather than
  // whichever clip happened to sort first.
  let clip = null;
  let image = null;
  for (const study of studies) {
    const clips = http.get(`${API}/studies/${study.id}/cine`, { headers }).json();
    for (const candidate of clips) {
      if (!clip || candidate.frame_count > clip.frame_count) clip = candidate;
    }
    if (!image) {
      const images = http.get(`${API}/studies/${study.id}/images`, { headers }).json();
      if (images.length) image = images[0];
    }
  }
  if (!clip || !image) fail("seeded dataset has no cine clip or no image");

  const providers = http.get(`${API}/providers`, { headers }).json();
  if (!providers.length) fail("no providers in the seeded dataset");

  return {
    headers,
    imageId: image.id,
    clipId: clip.id,
    frameCount: clip.frame_count,
    providerId: providers[0].id,
    reportId: (http.get(`${API}/reports`, { headers }).json()[0] || {}).id || null,
    // Everything booked after this instant belongs to the run, and only that is cleaned up.
    startedAt: new Date().toISOString(),
  };
}

/**
 * Release anything the run left holding a slot.
 *
 * Each iteration cancels its own booking, but under load those cancels compete for the
 * same connection pool as everything else and some fail. Without this, a run that saturates
 * the API leaves live appointments in the diary — which is exactly the run most likely to.
 *
 * Scoped by booking time so a pre-existing appointment is never touched.
 *
 * @param {object} data - Values returned by setup.
 */
export function teardown(data) {
  const { headers } = data;
  const appointments = http.get(`${API}/appointments`, { headers }).json();
  let released = 0;

  for (const appointment of appointments) {
    const live = appointment.status === "requested" || appointment.status === "confirmed";
    if (!live || appointment.booked_at < data.startedAt) continue;
    const response = http.post(`${API}/appointments/${appointment.id}/cancel`, "{}", { headers });
    if (response.status === 200) released += 1;
  }

  console.log(`teardown released ${released} benchmark booking(s)`);
}

/**
 * The read path a patient actually exercises: images, cine, reports, open slots.
 *
 * @param {object} data - Values returned by setup.
 */
export function browse(data) {
  const { headers } = data;

  const image = http.get(`${API}/images/${data.imageId}/file`, { headers });
  imageLoad.add(image.timings.duration);
  check(image, { "image served": (r) => r.status === 200 });

  // Time-to-first-frame is the manifest plus the first frame: what a viewer must have
  // before it can paint anything at all.
  const manifest = http.get(`${API}/cine/${data.clipId}/manifest`, { headers });
  const firstFrame = http.get(`${API}/cine/${data.clipId}/frames/1`, { headers });
  cineFirstFrame.add(manifest.timings.duration + firstFrame.timings.duration);
  check(manifest, { "manifest served": (r) => r.status === 200 });
  check(firstFrame, { "first frame served": (r) => r.status === 200 });

  // Fully loaded is the bundle endpoint: the whole clip in one response.
  const bundle = http.get(`${API}/cine/${data.clipId}/frames`, { headers });
  cineFullyLoaded.add(manifest.timings.duration + bundle.timings.duration);
  check(bundle, { "clip bundle served": (r) => r.status === 200 });

  const slots = http.get(`${API}/providers/${data.providerId}/slots?days=30`, { headers });
  slotQuery.add(slots.timings.duration);
  check(slots, { "slots listed": (r) => r.status === 200 });

  if (data.reportId) {
    const report = http.get(`${API}/reports/${data.reportId}`, { headers });
    check(report, { "report served": (r) => r.status === 200 });
  }
}

/**
 * The write path: mint a share link, then book and immediately release a slot.
 *
 * Each booking is cancelled in the same iteration, so the diary ends the run as it began.
 * A slot at least a day out is chosen because the clinic's minimum-notice rule correctly
 * refuses to cancel anything sooner.
 *
 * @param {object} data - Values returned by setup.
 */
export function mutate(data) {
  const { headers } = data;

  const share = http.post(
    `${API}/shares`,
    JSON.stringify({
      resource_type: "image",
      resource_id: data.imageId,
      // example.com, not example.test: the reserved .test TLD is rejected by the email
      // validator on the share endpoint, so a .test address measures a 422, not a share.
      recipient_email: "benchmark@example.com",
      ttl_hours: 24,
    }),
    { headers },
  );
  shareGeneration.add(share.timings.duration);
  check(share, { "share link issued": (r) => r.status === 201 });
  if (share.status === 201) {
    http.post(`${API}/shares/${share.json("share.id")}/revoke`, null, { headers });
  }

  const slots = http.get(`${API}/providers/${data.providerId}/slots?days=30`, { headers }).json();
  const target = slots[slots.length - 1];
  if (!target) return;

  const booked = http.post(
    `${API}/appointments`,
    JSON.stringify({ slot_id: target.id, idempotency_key: `k6-${__VU}-${__ITER}-${target.id}` }),
    { headers },
  );
  bookingAction.add(booked.timings.duration);
  check(booked, { "slot booked": (r) => r.status === 201 });

  if (booked.status === 201) {
    const released = http.post(
      `${API}/appointments/${booked.json("id")}/cancel`,
      JSON.stringify({ reason: "k6 benchmark" }),
      { headers },
    );
    check(released, { "booking released": (r) => r.status === 200 });
  }
}
