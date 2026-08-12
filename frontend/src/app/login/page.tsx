"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Wordmark } from "@/components/Wordmark";
import { Alert, Button, Card, Eyebrow, Field, TextInput } from "@/components/ui";
import { createClient } from "@/lib/supabase/client";

/** Sign-in screen. Signing in is only the first of two steps before any image is visible. */
export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const { error: signInError } = await createClient().auth.signInWithPassword({
      email,
      password,
    });

    if (signInError) {
      // Deliberately generic: distinguishing "no such account" from "wrong password" would
      // confirm which email addresses are registered patients.
      setError("We could not sign you in. Check your email and password and try again.");
      setBusy(false);
      return;
    }
    router.push("/verify");
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
            <Eyebrow>Step 1 of 2</Eyebrow>
            <h1 className="text-2xl">Sign in</h1>
          </div>
          <p className="text-[0.9375rem] text-ink-2">
            Use the email address your clinic has on file. After signing in you will confirm your
            identity before any images open.
          </p>

          {error ? <Alert tone="crit">{error}</Alert> : null}

          <Field label="Email" htmlFor="email">
            <TextInput
              id="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
          <Field label="Password" htmlFor="password">
            <TextInput
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>

          <Button tone="primary" block type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Continue"}
          </Button>
        </form>
      </Card>
    </main>
  );
}
