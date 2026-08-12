"use client";

import { useState } from "react";

import { Button, Card, CardBody, CardHead, EmptyState, Pill } from "@/components/ui";
import type { MockShare, ShareStatus } from "@/lib/mock";

const STATUS_LABEL: Record<ShareStatus, string> = {
  active: "Active",
  expired: "Expired",
  revoked: "Switched off",
};

const STATUS_TONE = { active: "ok", expired: "mute", revoked: "crit" } as const;

/**
 * The patient's share links.
 *
 * Revocation is local-only for now; the wiring issue replaces this state with the API.
 * The interaction is real so the flow — including the confirmation toast — can be reviewed
 * before any link can actually be minted.
 */
export function ShareList({ initial }: { initial: MockShare[] }) {
  const [shares, setShares] = useState(initial);
  const [toast, setToast] = useState<string | null>(null);

  function revoke(id: string) {
    setShares((current) =>
      current.map((share) => (share.id === id ? { ...share, status: "revoked" } : share)),
    );
    setToast("Link switched off. It will no longer open for anyone.");
    window.setTimeout(() => setToast(null), 4000);
  }

  const activeCount = shares.filter((share) => share.status === "active").length;

  return (
    <>
      <Card>
        <CardHead>
          <h3 className="mr-auto text-base">Active and past links</h3>
          <Pill tone={activeCount > 0 ? "ok" : "mute"}>{activeCount} active</Pill>
        </CardHead>
        <CardBody>
          {shares.length === 0 ? (
            <EmptyState>
              You haven&rsquo;t shared anything yet. Open an image or report and choose Share.
            </EmptyState>
          ) : (
            <div className="grid gap-2.5">
              {shares.map((share) => (
                <div
                  key={share.id}
                  className="grid items-center gap-3 rounded-md border border-line p-4 sm:grid-cols-[1fr_auto]"
                >
                  <div className="grid min-w-0 gap-0.5">
                    <div className="text-[0.9375rem] font-semibold">{share.resource}</div>
                    <div className="text-[0.8125rem] text-ink-3">
                      {share.recipient} · {share.expiresLabel}
                    </div>
                    <div className="truncate font-mono text-[0.6875rem] text-ink-3">
                      {share.token}
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-2">
                    <Pill tone={STATUS_TONE[share.status]}>{STATUS_LABEL[share.status]}</Pill>
                    {share.status === "active" ? (
                      <Button tone="danger" size="sm" onClick={() => revoke(share.id)}>
                        Switch off
                      </Button>
                    ) : null}
                  </div>
                </div>
              ))}
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
