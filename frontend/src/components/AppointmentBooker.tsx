"use client";

import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { Button, Card, CardBody, CardHead, EmptyState, Field, Pill, Select } from "@/components/ui";
import type { AppointmentRecord, AppointmentStatus, ProviderSummary, SlotOffer } from "@/lib/api";

/** Statuses that still hold their slot, and so can be moved or cancelled. */
const LIVE: AppointmentStatus[] = ["requested", "confirmed"];

/** How each status reads to a patient. Never colour alone — the label carries the meaning. */
const STATUS_DISPLAY: Record<AppointmentStatus, { label: string; tone: "ok" | "mute" | "crit" }> = {
  requested: { label: "Requested", tone: "mute" },
  confirmed: { label: "Confirmed", tone: "ok" },
  completed: { label: "Completed", tone: "mute" },
  cancelled: { label: "Cancelled", tone: "crit" },
  no_show: { label: "Missed", tone: "crit" },
};

/**
 * Render an instant in a named zone, carrying the zone's abbreviation.
 *
 * @param iso - The absolute instant.
 * @param timeZone - IANA zone to render in.
 * @returns A readable local time, e.g. "Thu, Sep 3, 2:30 PM EDT".
 */
function formatIn(iso: string, timeZone: string): string {
  return new Date(iso).toLocaleString("en-US", {
    timeZone,
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

/**
 * Render just the clock time in a named zone.
 *
 * @param iso - The absolute instant.
 * @param timeZone - IANA zone to render in.
 * @returns A short time, e.g. "2:30 PM".
 */
function timeIn(iso: string, timeZone: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    timeZone,
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Group slots by their calendar day in the viewer's zone.
 *
 * Grouped in the patient's own zone rather than the clinic's: it is the day they will think
 * of the appointment as being on, and near midnight the two genuinely disagree.
 *
 * @param slots - Open slots in chronological order.
 * @param timeZone - The viewer's zone.
 * @returns Day labels in order, each with its slots.
 */
function groupByDay(slots: SlotOffer[], timeZone: string): { day: string; slots: SlotOffer[] }[] {
  const days = new Map<string, SlotOffer[]>();
  for (const slot of slots) {
    const day = new Date(slot.start_utc).toLocaleDateString("en-US", {
      timeZone,
      weekday: "long",
      month: "short",
      day: "numeric",
    });
    const existing = days.get(day);
    if (existing) existing.push(slot);
    else days.set(day, [slot]);
  }
  return [...days].map(([day, daySlots]) => ({ day, slots: daySlots }));
}

interface Props {
  initialAppointments: AppointmentRecord[];
  providers: ProviderSummary[];
  initialSlots: SlotOffer[];
  initialProviderId: string | null;
}

/** Booking, rescheduling and cancelling, against the live scheduling API. */
export function AppointmentBooker({
  initialAppointments,
  providers,
  initialSlots,
  initialProviderId,
}: Props) {
  const router = useRouter();
  const [appointments, setAppointments] = useState(initialAppointments);
  const [providerId, setProviderId] = useState(initialProviderId);
  const [slots, setSlots] = useState(initialSlots);
  const [movingId, setMovingId] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ text: string; bad: boolean } | null>(null);

  // The server and the browser sit in different zones, and rendering one then the other is
  // a hydration mismatch. Rendering UTC on the server and the real zone on the client is a
  // legitimate difference instead. Matches PatientCard.
  const viewerZone = useSyncExternalStore(
    () => () => {},
    () => Intl.DateTimeFormat().resolvedOptions().timeZone,
    () => "UTC",
  );

  const provider = providers.find((candidate) => candidate.id === providerId) ?? null;
  const clinicZone = provider?.timezone ?? "UTC";
  const zonesDiffer = clinicZone !== viewerZone;

  function announce(text: string, bad = false) {
    setNotice({ text, bad });
    window.setTimeout(() => setNotice(null), 6000);
  }

  /**
   * Read the API's refusal message, falling back to something a patient can act on.
   *
   * @param response - The failed response.
   * @returns A sentence to show.
   */
  async function refusalText(response: Response): Promise<string> {
    const body = await response.json().catch(() => null);
    const detail = body?.detail;
    if (typeof detail?.message === "string") return detail.message;
    return "Something went wrong. Please try again.";
  }

  async function loadSlots(forProvider: string) {
    const response = await fetch(`/api/phi/providers/${forProvider}/slots?days=14`);
    if (response.ok) setSlots((await response.json()) as SlotOffer[]);
  }

  async function chooseProvider(next: string) {
    setProviderId(next);
    setSlots([]);
    await loadSlots(next);
  }

  async function book(slot: SlotOffer) {
    setBusy(slot.id);
    const response = await fetch("/api/phi/appointments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slot_id: slot.id,
        // Generated per submission so a double-click or a retry replays the same key and
        // returns the original appointment rather than booking twice (edge case #10).
        idempotency_key: crypto.randomUUID(),
      }),
    });
    setBusy(null);

    if (!response.ok) {
      announce(await refusalText(response), true);
      // Most likely someone else took it. Re-read so the grid stops offering it.
      if (providerId) await loadSlots(providerId);
      return;
    }

    const created = (await response.json()) as AppointmentRecord;
    setAppointments((current) => [created, ...current]);
    if (providerId) await loadSlots(providerId);
    announce(`Booked for ${formatIn(created.start_utc, viewerZone)}.`);
    router.refresh();
  }

  async function move(slot: SlotOffer) {
    if (!movingId) return;
    setBusy(slot.id);
    const response = await fetch(`/api/phi/appointments/${movingId}/reschedule`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot_id: slot.id }),
    });
    setBusy(null);

    if (!response.ok) {
      announce(await refusalText(response), true);
      if (providerId) await loadSlots(providerId);
      return;
    }

    const moved = (await response.json()) as AppointmentRecord;
    setAppointments((current) =>
      current.map((appointment) => (appointment.id === moved.id ? moved : appointment)),
    );
    setMovingId(null);
    if (providerId) await loadSlots(providerId);
    announce(`Moved to ${formatIn(moved.start_utc, viewerZone)}.`);
    router.refresh();
  }

  async function cancel(appointment: AppointmentRecord) {
    setBusy(appointment.id);
    const response = await fetch(`/api/phi/appointments/${appointment.id}/cancel`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    setBusy(null);

    if (!response.ok) {
      announce(await refusalText(response), true);
      return;
    }

    const cancelled = (await response.json()) as AppointmentRecord;
    setAppointments((current) =>
      current.map((item) => (item.id === cancelled.id ? cancelled : item)),
    );
    if (movingId === cancelled.id) setMovingId(null);
    if (providerId) await loadSlots(providerId);
    announce("Appointment cancelled. The time is available to book again.");
    router.refresh();
  }

  const live = appointments.filter((appointment) => LIVE.includes(appointment.status));
  const past = appointments.filter((appointment) => !LIVE.includes(appointment.status));
  const grouped = groupByDay(slots, viewerZone);

  return (
    <>
      <Card>
        <CardHead>
          <h3 className="mr-auto text-base">Your appointments</h3>
          <Pill tone={live.length > 0 ? "ok" : "mute"}>{live.length} upcoming</Pill>
        </CardHead>
        <CardBody>
          {live.length === 0 ? (
            <EmptyState>
              You have no upcoming appointments. Choose a time below to book one.
            </EmptyState>
          ) : (
            <div className="grid gap-2.5">
              {live.map((appointment) => {
                const display = STATUS_DISPLAY[appointment.status];
                const moving = movingId === appointment.id;
                return (
                  <div
                    key={appointment.id}
                    // Stable hooks for the end-to-end suite: class names here are Tailwind
                    // utilities that change whenever the design does.
                    data-testid="appointment-row"
                    data-status={appointment.status}
                    className={[
                      "grid items-center gap-3 rounded-md border p-4 sm:grid-cols-[1fr_auto]",
                      moving ? "border-brand bg-brand-tint" : "border-line",
                    ].join(" ")}
                  >
                    <div className="grid min-w-0 gap-0.5">
                      <div className="text-[0.9375rem] font-semibold">
                        {appointment.provider_name}
                      </div>
                      <div className="text-[0.8125rem] text-ink-3">
                        {formatIn(appointment.start_utc, viewerZone)}
                        {appointment.provider_timezone !== viewerZone ? (
                          <>
                            {" · clinic time "}
                            {formatIn(appointment.start_utc, appointment.provider_timezone)}
                          </>
                        ) : null}
                      </div>
                      {moving ? (
                        <div className="text-[0.8125rem] font-semibold text-brand-dark">
                          Pick a new time below, or press Stop moving.
                        </div>
                      ) : null}
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <Pill tone={display.tone}>{display.label}</Pill>
                      <Button
                        size="sm"
                        onClick={() => setMovingId(moving ? null : appointment.id)}
                        aria-pressed={moving}
                      >
                        {moving ? "Stop moving" : "Reschedule"}
                      </Button>
                      <Button
                        tone="danger"
                        size="sm"
                        disabled={busy === appointment.id}
                        onClick={() => cancel(appointment)}
                      >
                        {busy === appointment.id ? "Cancelling…" : "Cancel"}
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          <p className="text-xs text-ink-3">
            Changes close 24 hours before a visit. After that, please call the clinic.
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHead>
          <h3 className="mr-auto text-base">{movingId ? "Pick a new time" : "Book a time"}</h3>
          {zonesDiffer ? (
            <Pill tone="mute" dot={false}>
              Clinic in {clinicZone}
            </Pill>
          ) : null}
        </CardHead>
        <CardBody>
          {providers.length === 0 ? (
            <EmptyState>No clinicians are taking bookings right now.</EmptyState>
          ) : (
            <Field label="Clinician" htmlFor="provider">
              <Select
                id="provider"
                value={providerId ?? ""}
                onChange={(event) => chooseProvider(event.target.value)}
              >
                {providers.map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    {candidate.display_name}
                    {candidate.specialty ? ` · ${candidate.specialty}` : ""}
                  </option>
                ))}
              </Select>
            </Field>
          )}

          {grouped.length === 0 ? (
            <EmptyState>No open times in the next two weeks for this clinician.</EmptyState>
          ) : (
            <div className="grid gap-4">
              {grouped.map(({ day, slots: daySlots }) => (
                <div key={day} className="grid gap-2">
                  <h4 className="text-[0.8125rem] font-semibold text-ink-2">{day}</h4>
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-2.5">
                    {daySlots.map((slot) => (
                      <button
                        key={slot.id}
                        type="button"
                        disabled={busy === slot.id}
                        onClick={() => (movingId ? move(slot) : book(slot))}
                        className={[
                          "grid min-h-[3.5rem] gap-0.5 rounded-md border border-line p-2.5 text-left",
                          "bg-panel transition-colors enabled:hover:border-brand",
                          "enabled:hover:bg-brand-tint disabled:cursor-not-allowed disabled:opacity-40",
                        ].join(" ")}
                      >
                        <span className="text-[0.9375rem] font-bold tabular-nums">
                          {busy === slot.id ? "…" : timeIn(slot.start_utc, viewerZone)}
                        </span>
                        {/* Both zones on every instant a patient might act on: with a clinic
                            in another zone, one clock alone is an invitation to arrive an
                            hour out (edge case #6). */}
                        <span className="text-xs text-ink-3">
                          {zonesDiffer
                            ? `${timeIn(slot.start_utc, clinicZone)} clinic`
                            : `${Math.round(
                                (new Date(slot.end_utc).getTime() -
                                  new Date(slot.start_utc).getTime()) /
                                  60000,
                              )} min`}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      {past.length > 0 ? (
        <Card>
          <CardHead>
            <h3 className="mr-auto text-base">Past and cancelled</h3>
          </CardHead>
          <CardBody>
            <div className="grid gap-2.5">
              {past.map((appointment) => {
                const display = STATUS_DISPLAY[appointment.status];
                return (
                  <div
                    key={appointment.id}
                    className="grid items-center gap-3 rounded-md border border-line p-4 sm:grid-cols-[1fr_auto]"
                  >
                    <div className="grid min-w-0 gap-0.5">
                      <div className="text-[0.9375rem] font-semibold">
                        {appointment.provider_name}
                      </div>
                      <div className="text-[0.8125rem] text-ink-3">
                        {formatIn(appointment.start_utc, viewerZone)}
                      </div>
                    </div>
                    <Pill tone={display.tone}>{display.label}</Pill>
                  </div>
                );
              })}
            </div>
          </CardBody>
        </Card>
      ) : null}

      {notice ? (
        <div
          // A refusal is assertive: the patient just pressed a time and did not get it, so
          // it must interrupt rather than wait to be read.
          role={notice.bad ? "alert" : "status"}
          className={[
            "fixed bottom-6 left-1/2 z-80 max-w-[calc(100vw-2rem)] -translate-x-1/2",
            "rounded-pill px-5 py-3 text-sm font-semibold shadow-float",
            // The crit/crit-bg pairing is defined for both themes; plain `bg-crit` with
            // white text would drop to roughly 2:1 in dark mode, where crit is a light pink.
            notice.bad ? "border border-crit bg-crit-bg text-crit" : "bg-brand-dark text-white",
          ].join(" ")}
        >
          {notice.text}
        </div>
      ) : null}
    </>
  );
}
