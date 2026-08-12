"use client";

import { useEffect, useRef, useState } from "react";

import { Alert, Button, Field, TextInput } from "@/components/ui";
import type { CreatedShare } from "@/lib/api";

const TTL_OPTIONS = [24, 48, 72] as const;

/**
 * Share dialog for one image or report.
 *
 * Two phases: the form, then the result carrying the link. The link is shown even when the
 * email fails, because losing it would mean the patient has to mint another — and every
 * extra live link is another way in.
 */
export function ShareModal({
  resourceType,
  resourceId,
  label,
  onClose,
  onCreated,
}: {
  resourceType: "image" | "report";
  resourceId: string;
  label: string;
  onClose: () => void;
  onCreated?: () => void;
}) {
  const [recipient, setRecipient] = useState("");
  const [ttl, setTtl] = useState<number>(48);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CreatedShare | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const response = await fetch("/api/phi/shares", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resource_type: resourceType,
        resource_id: resourceId,
        recipient_email: recipient,
        ttl_hours: ttl,
      }),
    });

    if (!response.ok) {
      setError(
        response.status === 422
          ? "That email address does not look right. Please check it."
          : "We could not create the link. Please try again.",
      );
      setBusy(false);
      return;
    }

    setResult(await response.json());
    setBusy(false);
    onCreated?.();
  }

  return (
    <div
      className="fixed inset-0 z-60 grid place-items-center bg-[rgb(20_10_34/0.74)] p-4 backdrop-blur-sm"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Share ${label}`}
        className="max-h-[92dvh] w-[min(31rem,100%)] overflow-auto rounded-lg bg-panel shadow-float"
      >
        <div className="flex items-center gap-3 border-b border-line-soft p-5">
          <h2 className="mr-auto text-lg">Share {resourceType === "image" ? "image" : "report"}</h2>
          <Button ref={closeRef} tone="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>

        {result ? (
          <div className="grid gap-4 p-5">
            <Alert tone={result.email_sent ? "ok" : "warn"}>
              <span>
                {result.email_sent
                  ? `Link sent. It expires in ${ttl} hours.`
                  : (result.email_error ?? "The email did not send, but the link below works.")}
              </span>
            </Alert>
            <Field label="The link" htmlFor="share-link" hint="Anyone with this link can open the file until it expires or you switch it off.">
              <div
                id="share-link"
                className="rounded-md bg-brand-tint p-3 font-mono text-xs break-all text-brand"
              >
                {result.link}
              </div>
            </Field>
            <div className="flex justify-end gap-2.5">
              <Button
                onClick={() => navigator.clipboard?.writeText(result.link)}
                title="Copy the link"
              >
                Copy link
              </Button>
              <Button tone="primary" onClick={onClose}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <form onSubmit={submit} className="grid gap-4 p-5">
            {error ? <Alert tone="crit">{error}</Alert> : null}

            <Field
              label="Send to"
              htmlFor="recipient"
              hint="They get a short notice and the link. Nothing clinical travels in the email."
            >
              <TextInput
                id="recipient"
                type="email"
                required
                autoComplete="off"
                placeholder="name@example.com"
                value={recipient}
                onChange={(event) => setRecipient(event.target.value)}
              />
            </Field>

            <fieldset className="grid gap-1.5">
              <legend className="text-[0.8125rem] font-semibold text-ink-2">Expires after</legend>
              <div className="flex flex-wrap gap-2">
                {TTL_OPTIONS.map((option) => (
                  <label
                    key={option}
                    className={[
                      "cursor-pointer rounded-pill border px-4 py-2 text-[0.8125rem] font-semibold",
                      ttl === option
                        ? "border-brand bg-brand-tint text-brand"
                        : "border-line text-ink",
                    ].join(" ")}
                  >
                    <input
                      type="radio"
                      name="ttl"
                      value={option}
                      checked={ttl === option}
                      onChange={() => setTtl(option)}
                      className="sr-only"
                    />
                    {option} hours
                  </label>
                ))}
              </div>
            </fieldset>

            <Alert tone="brand">
              <span>
                You can switch this link off at any time from Shared links. Every time it is
                opened is written to your access log.
              </span>
            </Alert>

            <div className="flex justify-end gap-2.5">
              <Button type="button" onClick={onClose}>
                Cancel
              </Button>
              <Button tone="primary" type="submit" disabled={busy}>
                {busy ? "Creating…" : "Create link"}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
