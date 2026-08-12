import { PortalFrame } from "@/components/PortalFrame";
import { PreviewNotice } from "@/components/PreviewNotice";
import { Button, Card, CardBody, CardHead, Eyebrow, Pill } from "@/components/ui";
import { MOCK_APPOINTMENT, MOCK_SLOTS } from "@/lib/mock";

export const fetchCache = "only-no-store";

/** Upcoming visit and open times, every instant shown in both zones. */
export default function AppointmentsPage() {
  const appointment = MOCK_APPOINTMENT;

  return (
    <PortalFrame>
      <div className="grid gap-1.5">
        <Eyebrow>Scheduling</Eyebrow>
        <h1 className="text-2xl">Appointments</h1>
        <p className="max-w-[44rem] text-[0.9375rem] text-ink-2">
          Times show in your zone with the clinic&rsquo;s zone beside them, so there is never a
          question about which hour you are booking.
        </p>
      </div>

      <PreviewNotice>
        The scheduling API is not built yet. This visit and these open times are examples, and
        Reschedule, Cancel and the slot buttons do nothing.
      </PreviewNotice>

      <Card>
        <CardHead>
          <h3 className="mr-auto text-base">Upcoming</h3>
          <Pill tone="ok">Confirmed</Pill>
        </CardHead>
        <CardBody>
          <div className="grid items-center gap-3 rounded-md border border-line p-4 sm:grid-cols-[1fr_auto]">
            <div className="grid min-w-0 gap-0.5">
              <div className="text-[0.9375rem] font-semibold">{appointment.title}</div>
              {/* Both zones on every instant: a patient and a clinic in different zones must
                  never have to work out whose clock a time refers to (edge case #6). */}
              <div className="text-[0.8125rem] text-ink-3">
                {appointment.whenPatient} / {appointment.whenClinic} · {appointment.duration} ·{" "}
                {appointment.location}
              </div>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <Button size="sm" disabled title="Available once scheduling ships">
                Reschedule
              </Button>
              <Button tone="danger" size="sm" disabled title="Available once scheduling ships">
                Cancel
              </Button>
            </div>
          </div>
          <p className="text-xs text-ink-3">
            You can change this until 24 hours before the visit — by {appointment.changeBy}.
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHead>
          <h3 className="mr-auto text-base">Open times · Dr Amara Lee, Thu Sep 3</h3>
          <Pill tone="mute" dot={false}>
            30 min
          </Pill>
        </CardHead>
        <CardBody>
          <div className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-2.5">
            {MOCK_SLOTS.map((slot) => (
              <button
                key={slot.patientTime}
                type="button"
                disabled={slot.booked}
                title={slot.booked ? "Already booked" : "Available once scheduling ships"}
                className={[
                  "grid min-h-[3.5rem] gap-0.5 rounded-md border p-2.5 text-left transition-colors",
                  "disabled:cursor-not-allowed disabled:line-through disabled:opacity-40",
                  slot.last ? "border-warn" : "border-line",
                  "bg-panel enabled:hover:border-brand enabled:hover:bg-brand-tint",
                ].join(" ")}
              >
                <span className="text-[0.9375rem] font-bold tabular-nums">{slot.patientTime}</span>
                <span className="text-xs text-ink-3">{slot.clinicTime}</span>
              </button>
            ))}
          </div>
          <p className="text-xs text-ink-3">
            Struck-through times are already taken. The last remaining time of the day is outlined
            so it is obvious before you commit.
          </p>
        </CardBody>
      </Card>
    </PortalFrame>
  );
}
