"use client";

import { useRouter } from "next/navigation";
import { useSyncExternalStore } from "react";

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
  // The server's zone and the browser's differ, and rendering one then the other is a
  // hydration mismatch — React discards the server HTML, which can leave event handlers
  // unattached across the tree. useSyncExternalStore renders the placeholder on the server
  // and the real zone on the client, which is a legitimate difference rather than a
  // mismatch. The value never changes, so the subscribe callback is a no-op.
  const timeZone = useSyncExternalStore(
    () => () => {},
    () => Intl.DateTimeFormat().resolvedOptions().timeZone,
    () => "—",
  );

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
      <Row label="Time zone" value={timeZone} />
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
