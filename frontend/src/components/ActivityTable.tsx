"use client";

import { useSyncExternalStore } from "react";

import { Card, CardHead, EmptyState, Pill } from "@/components/ui";
import type { ActivityEntry, AuditActorType } from "@/lib/api";

/**
 * How each recorded action reads to a patient.
 *
 * The server stores action names as text so the set can grow without a migration; anything
 * not listed here falls back to a readable form of the raw name rather than disappearing,
 * so a new action is never silently invisible in the log.
 */
const ACTION_LABELS: Record<string, string> = {
  identity_verified: "Identity verified",
  identity_failed: "Identity check failed",
  image_viewed: "Viewed image",
  image_access_denied: "Image access refused",
  study_access_denied: "Study access refused",
  cine_viewed: "Played cine clip",
  cine_access_denied: "Cine access refused",
  report_viewed: "Viewed report",
  report_access_denied: "Report access refused",
  share_link_created: "Created share link",
  share_link_used: "Shared link opened",
  share_link_revoked: "Switched off share link",
  share_link_denied: "Share link refused",
  appointment_booked: "Booked appointment",
  appointment_rescheduled: "Moved appointment",
  appointment_cancelled: "Cancelled appointment",
  appointment_status_changed: "Appointment status changed",
  availability_changed: "Clinic availability changed",
  reminder_dispatched: "Reminder emailed to you",
};

/** Who the entry is attributed to, in the patient's terms. */
const ACTOR_LABELS: Record<AuditActorType, string> = {
  patient: "You",
  staff: "Clinic staff",
  share_link: "Share link recipient",
  system: "Automated",
};

/**
 * Turn a stored action name into a readable phrase.
 *
 * @param action - The stored action.
 * @returns A phrase for the table.
 */
function label(action: string): string {
  return ACTION_LABELS[action] ?? action.replaceAll("_", " ");
}

/**
 * Shorten a resource id to something scannable.
 *
 * The full identifier is never useful to a patient and a column of 36-character strings
 * forces the table to scroll on a phone.
 *
 * @param entry - The log entry.
 * @returns A short reference.
 */
function target(entry: ActivityEntry): string {
  if (!entry.resource_id) return entry.resource_type;
  return `${entry.resource_type} ${entry.resource_id.slice(0, 8)}`;
}

/** The patient's access log, rendered in their own time zone. */
export function ActivityTable({ entries }: { entries: ActivityEntry[] }) {
  // Rendered UTC on the server and the viewer's zone on the client, which is a legitimate
  // difference rather than a hydration mismatch. Matches PatientCard.
  const timeZone = useSyncExternalStore(
    () => () => {},
    () => Intl.DateTimeFormat().resolvedOptions().timeZone,
    () => "UTC",
  );

  return (
    <Card>
      <CardHead>
        <h3 className="mr-auto text-base">Recent activity</h3>
        <Pill tone="mute" dot={false}>
          {entries.length} {entries.length === 1 ? "entry" : "entries"}
        </Pill>
      </CardHead>
      {entries.length === 0 ? (
        <div className="p-5">
          <EmptyState>
            Nothing yet. Activity appears here the first time your record is opened.
          </EmptyState>
        </div>
      ) : (
        /* The table scrolls inside its own container so a phone never scrolls the page
           sideways. The container is focusable and labelled as a region because a scroll
           box that only responds to a pointer is content a keyboard user cannot reach the
           right-hand end of. */
        <div
          className="overflow-x-auto"
          tabIndex={0}
          role="region"
          aria-label="Access log entries, scrollable"
        >
          <table className="w-full border-collapse text-[0.8125rem]">
            <thead>
              <tr>
                {["When", "Who", "Action", "Target", "Result"].map((head) => (
                  <th
                    key={head}
                    scope="col"
                    className="whitespace-nowrap border-b border-line-soft px-5 py-2.5 text-left text-[0.6875rem] font-bold uppercase tracking-[0.08em] text-ink-3"
                  >
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id}>
                  <td className="whitespace-nowrap border-b border-line-soft px-5 py-2.5 font-mono tabular-nums text-ink-2">
                    {new Date(entry.occurred_at).toLocaleString("en-US", {
                      timeZone,
                      year: "numeric",
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td className="whitespace-nowrap border-b border-line-soft px-5 py-2.5">
                    {ACTOR_LABELS[entry.actor_type]}
                  </td>
                  <td className="whitespace-nowrap border-b border-line-soft px-5 py-2.5">
                    {label(entry.action)}
                  </td>
                  <td className="whitespace-nowrap border-b border-line-soft px-5 py-2.5 font-mono text-ink-2">
                    {target(entry)}
                  </td>
                  <td className="whitespace-nowrap border-b border-line-soft px-5 py-2.5">
                    {/* Word as well as colour: a refused access must be legible to someone
                        who cannot distinguish the two hues. */}
                    <Pill tone={entry.allowed ? "ok" : "crit"}>
                      {entry.allowed ? "Allowed" : "Denied"}
                    </Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
