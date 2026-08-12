"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, Card, CardBody, CardHead, EmptyState, Pill } from "@/components/ui";
import type { ShareRecord } from "@/lib/api";

/** How a link reads to the patient right now. */
type Display = { label: string; tone: "ok" | "mute" | "crit" };

/**
 * Describe a link's current state.
 *
 * Expiry is derived rather than stored as a status, so a link that lapses while the page is
 * open is not shown as still active.
 *
 * @param share - The link.
 * @returns Its label and tone.
 */
function describe(share: ShareRecord): Display {
  if (share.revoked_at) return { label: "Switched off", tone: "crit" };
  if (new Date(share.expires_at) <= new Date()) return { label: "Expired", tone: "mute" };
  return { label: "Active", tone: "ok" };
}

/** The patient's share links, with revocation. */
export function ShareList({ initial }: { initial: ShareRecord[] }) {
  const router = useRouter();
  const [shares, setShares] = useState(initial);
  const [toast, setToast] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function revoke(id: string) {
    setBusy(id);
    const response = await fetch(`/api/phi/shares/${id}/revoke`, { method: "POST" });
    setBusy(null);

    if (!response.ok) {
      setToast("We could not switch that link off. Please try again.");
      window.setTimeout(() => setToast(null), 4000);
      return;
    }

    setShares((current) =>
      current.map((share) =>
        share.id === id ? { ...share, revoked_at: new Date().toISOString() } : share,
      ),
    );
    setToast("Link switched off. It will no longer open for anyone.");
    window.setTimeout(() => setToast(null), 4000);
    // Refresh so the rail's count reflects the change rather than going stale.
    router.refresh();
  }

  const active = shares.filter((share) => describe(share).label === "Active").length;

  return (
    <>
      <Card>
        <CardHead>
          <h3 className="mr-auto text-base">Active and past links</h3>
          <Pill tone={active > 0 ? "ok" : "mute"}>{active} active</Pill>
        </CardHead>
        <CardBody>
          {shares.length === 0 ? (
            <EmptyState>
              You haven&rsquo;t shared anything yet. Open an image and choose Share.
            </EmptyState>
          ) : (
            <div className="grid gap-2.5">
              {shares.map((share) => {
                const state = describe(share);
                return (
                  <div
                    key={share.id}
                    className="grid items-center gap-3 rounded-md border border-line p-4 sm:grid-cols-[1fr_auto]"
                  >
                    <div className="grid min-w-0 gap-0.5">
                      <div className="text-[0.9375rem] font-semibold capitalize">
                        {share.resource_type}
                      </div>
                      <div className="text-[0.8125rem] text-ink-3">
                        {share.recipient_email} · expires{" "}
                        {new Date(share.expires_at).toLocaleString("en-US", { timeZone: "UTC" })}{" "}
                        UTC
                      </div>
                      <div className="text-[0.6875rem] text-ink-3">
                        Opened {share.access_count} {share.access_count === 1 ? "time" : "times"}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center justify-end gap-2">
                      <Pill tone={state.tone}>{state.label}</Pill>
                      {state.label === "Active" ? (
                        <Button
                          tone="danger"
                          size="sm"
                          disabled={busy === share.id}
                          onClick={() => revoke(share.id)}
                        >
                          {busy === share.id ? "Switching off…" : "Switch off"}
                        </Button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardBody>
      </Card>

      {toast ? (
        <div
          role="status"
          className="fixed bottom-6 left-1/2 z-80 max-w-[calc(100vw-2rem)] -translate-x-1/2 rounded-pill bg-brand-dark px-5 py-3 text-sm font-semibold text-white shadow-float"
        >
          {toast}
        </div>
      ) : null}
    </>
  );
}
