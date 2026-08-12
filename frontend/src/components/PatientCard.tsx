"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui";
import { createClient } from "@/lib/supabase/client";

/** The caller's own details, as returned by the API. */
export interface PatientProfile {
  display_name: string;
  account_id: string;
  date_of_birth_masked: string;
}

/**
 * Identity card in the rail.
 *
 * The date of birth arrives already masked from the API. Masking in the UI instead would
 * mean the full value had travelled to the browser and sat in memory for no reason — it is
 * one of the two factors guarding this account.
 */
export function PatientCard({ profile }: { profile: PatientProfile }) {
  const router = useRouter();
  // Resolved after mount, never during render: the server's zone and the browser's differ,
  // and rendering one then the other is a hydration mismatch. React responds by discarding
  // the server HTML, which can leave event handlers unattached across the whole tree.
  const [timeZone, setTimeZone] = useState<string | null>(null);
  useEffect(() => {
    setTimeZone(Intl.DateTimeFormat().resolvedOptions().timeZone);
  }, []);

  async function endSession() {
    await createClient().auth.signOut();
    router.push("/login");
    router.refresh();
  }

  return (
    <aside className="grid gap-2 rounded-lg border border-line bg-panel p-[1.125rem] shadow-card">
      <div className="text-base font-bold">{profile.display_name}</div>
      <Row label="Patient ID" value={profile.account_id} />
      <Row label="Date of birth" value={profile.date_of_birth_masked} />
      <Row label="Time zone" value={timeZone ?? "—"} />
      <Button tone="ghost" size="sm" onClick={endSession}>
        End session
      </Button>
    </aside>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 text-xs text-ink-3">
      <span>{label}</span>
      <span className="font-mono text-ink-2">{value}</span>
    </div>
  );
}
