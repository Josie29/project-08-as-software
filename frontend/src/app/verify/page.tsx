"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Wordmark } from "@/components/Wordmark";
import { Alert, Button, Card, Eyebrow, Field, TextInput } from "@/components/ui";
import { createClient } from "@/lib/supabase/client";

/** The one message shown for every failure, mirroring the API. */
const GENERIC_FAILURE =
  "We couldn't match those details. Check your visit summary and try again.";

/**
 * Identity gate.
 *
 * Signing in is not enough to open images: the patient must also match the account ID and
 * date of birth on their paperwork against the record the clinic already holds.
 */
export default function VerifyPage() {
  const router = useRouter();
  const [accountId, setAccountId] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [lockedFor, setLockedFor] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setLockedFor(null);

    const {
      data: { session },
    } = await createClient().auth.getSession();
    if (!session) {
      router.push("/login");
      return;
    }

    const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/identity/verify`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({ account_id: accountId, date_of_birth: dateOfBirth }),
    });

    if (response.status === 429) {
      setLockedFor(Number(response.headers.get("Retry-After") ?? 0));
      setBusy(false);
      return;
    }
    if (!response.ok) {
      setError(GENERIC_FAILURE);
      setBusy(false);
      return;
    }

    router.push("/studies");
    router.refresh();
  }

  return (
    <main className="mx-auto mt-14 mb-24 max-w-[31rem] px-6">
      <div className="mb-8">
        <Wordmark />
      </div>
      <Card className="shadow-raised">
        <form onSubmit={handleSubmit} className="grid gap-[1.125rem] p-8">
          <div>
            <Eyebrow>Step 2 of 2</Eyebrow>
            <h1 className="text-2xl">Confirm it&rsquo;s you</h1>
          </div>
          <p className="text-[0.9375rem] text-ink-2">
            Signing in isn&rsquo;t enough to open your images. Enter the Patient ID from your
            visit summary along with your date of birth. Both have to match the record on file.
          </p>

          {error ? <Alert tone="crit">{error}</Alert> : null}
          {lockedFor !== null ? (
            <Alert tone="warn">
              Too many attempts. Try again in about {Math.ceil(lockedFor / 60)} minutes.
            </Alert>
          ) : null}

          <Field label="Patient ID" htmlFor="accountId" hint="Printed on your visit summary.">
            <TextInput
              id="accountId"
              autoComplete="off"
              placeholder="AS-00000"
              required
              value={accountId}
              onChange={(e) => setAccountId(e.target.value)}
            />
          </Field>
          <Field label="Date of birth" htmlFor="dob">
            <TextInput
              id="dob"
              type="date"
              autoComplete="off"
              required
              value={dateOfBirth}
              onChange={(e) => setDateOfBirth(e.target.value)}
            />
          </Field>

          <Button tone="primary" block type="submit" disabled={busy}>
            {busy ? "Checking…" : "Continue"}
          </Button>

          <p className="text-xs text-ink-3">
            Repeated failed attempts lock this step temporarily. Every attempt is written to
            the access log.
          </p>
        </form>
      </Card>
    </main>
  );
}
