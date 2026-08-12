import { Wordmark } from "@/components/Wordmark";
import { Alert, Card, CardBody, CardHead, Eyebrow, Pill } from "@/components/ui";

/** Shared content must never be cached: a revoked link has to stop working immediately. */
export const fetchCache = "only-no-store";
export const dynamic = "force-dynamic";

/**
 * The page a shared link opens.
 *
 * Deliberately unauthenticated — the token is the credential. The bytes are fetched
 * server-side and inlined rather than pointing an `<img>` at the API, so opening the page
 * counts as exactly one access in the audit log instead of two.
 */
export default async function SharePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const upstream = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL}/s/${token}`, {
    cache: "no-store",
  });

  if (!upstream.ok) {
    return (
      <Shell>
        <Alert tone="crit">
          <span>
            <strong className="font-bold">This link is no longer available.</strong> It may have
            expired, or the person who sent it switched it off. Ask them to share it again.
          </span>
        </Alert>
      </Shell>
    );
  }

  const contentType = upstream.headers.get("content-type") ?? "";

  if (contentType.startsWith("image/")) {
    const buffer = Buffer.from(await upstream.arrayBuffer());
    return (
      <Shell>
        <Card>
          <CardHead>
            <h1 className="mr-auto text-base">Shared ultrasound image</h1>
            <Pill tone="ok">Link valid</Pill>
          </CardHead>
          <div className="bg-scan">
            {/* eslint-disable-next-line @next/next/no-img-element -- inlined so the page
                counts as one audited access rather than a second request. */}
            <img
              src={`data:image/jpeg;base64,${buffer.toString("base64")}`}
              alt="Shared ultrasound image"
              className="mx-auto block max-h-[70dvh] w-full object-contain"
            />
          </div>
        </Card>
      </Shell>
    );
  }

  const text = await upstream.text();
  return (
    <Shell>
      <Card>
        <CardHead>
          <h1 className="mr-auto text-base">Shared report</h1>
          <Pill tone="ok">Link valid</Pill>
        </CardHead>
        <CardBody>
          <pre className="whitespace-pre-wrap font-sans text-[0.9375rem] text-ink-2">{text}</pre>
        </CardBody>
      </Card>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto grid max-w-[48rem] gap-6 px-6 py-10">
      <Wordmark />
      <div className="grid gap-1.5">
        <Eyebrow>Shared with you</Eyebrow>
        <p className="text-[0.9375rem] text-ink-2">
          Someone shared this through their care provider&rsquo;s portal. The link expires on its
          own and can be switched off at any time.
        </p>
      </div>
      {children}
    </main>
  );
}
