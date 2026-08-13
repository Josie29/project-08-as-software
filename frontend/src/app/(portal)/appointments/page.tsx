import { redirect } from "next/navigation";

import { AppointmentBooker } from "@/components/AppointmentBooker";
import { PortalFrame } from "@/components/PortalFrame";
import { Eyebrow } from "@/components/ui";
import { getAppointments, getOpenSlots, getProviders } from "@/lib/api";

export const fetchCache = "only-no-store";

/** Upcoming visits and open times, every instant shown in both zones. */
export default async function AppointmentsPage() {
  const [appointments, providers] = await Promise.all([getAppointments(), getProviders()]);
  if (appointments === null || providers === null) redirect("/verify");

  // Slots for the first clinician are fetched here so the grid is populated on first paint;
  // switching clinician re-fetches from the browser.
  const initialProviderId = providers[0]?.id ?? null;
  const initialSlots = initialProviderId ? await getOpenSlots(initialProviderId, 14) : [];

  const upcoming = appointments.filter(
    (appointment) => appointment.status === "requested" || appointment.status === "confirmed",
  ).length;

  return (
    <PortalFrame counts={{ "/appointments": upcoming }}>
      <div className="grid gap-1.5">
        <Eyebrow>Scheduling</Eyebrow>
        <h1 className="text-2xl">Appointments</h1>
        <p className="max-w-[44rem] text-[0.9375rem] text-ink-2">
          Times show in your zone, with the clinic&rsquo;s zone beside them whenever the two differ,
          so there is never a question about which hour you are booking.
        </p>
      </div>

      <AppointmentBooker
        initialAppointments={appointments}
        providers={providers}
        initialSlots={initialSlots}
        initialProviderId={initialProviderId}
      />
    </PortalFrame>
  );
}
