import { PortalFrame } from "@/components/PortalFrame";
import { PreviewNotice } from "@/components/PreviewNotice";
import { Alert, Button, Card, CardBody, CardHead, Eyebrow, Pill } from "@/components/ui";
import { MOCK_SIGNED_REPORT } from "@/lib/mock";

export const fetchCache = "only-no-store";

/** The patient's reports. Signed reports render in full; preliminary ones never do. */
export default function ReportsPage() {
  const report = MOCK_SIGNED_REPORT;

  return (
    <PortalFrame>
      <div className="grid gap-1.5">
        <Eyebrow>Your reports</Eyebrow>
        <h1 className="text-2xl">Reports</h1>
        <p className="max-w-[44rem] text-[0.9375rem] text-ink-2">
          A report reaches you once your radiologist signs it. Preliminary reads stay with
          your care team until then.
        </p>
      </div>

      <PreviewNotice>
        The reports API is not built yet, so the report below is sample text and the Share and
        Download buttons do nothing.
      </PreviewNotice>

      <Card>
        <CardHead>
          <h3 className="mr-auto text-base">Anatomy survey report</h3>
          <Pill tone="ok">Signed</Pill>
          <Button size="sm" disabled title="Available once secure sharing ships">
            Share
          </Button>
          <Button size="sm" disabled title="Available once the reports API ships">
            Download PDF
          </Button>
        </CardHead>

        <article className="grid gap-5 p-7">
          <header className="grid gap-1.5 border-b-2 border-brand pb-4">
            <Eyebrow>{report.clinic}</Eyebrow>
            <h2 className="text-xl tracking-[-0.02em]">{report.title}</h2>
            <div className="grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-x-4 gap-y-2 text-xs text-ink-3">
              {report.meta.map((item) => (
                <span key={item.label}>
                  {item.label}
                  <b className="block font-mono text-[0.8125rem] font-normal text-ink-2">
                    {item.value}
                  </b>
                </span>
              ))}
            </div>
          </header>

          <Section title="Indication">
            <p className="max-w-[42rem] text-[0.9375rem] text-ink-2">{report.indication}</p>
          </Section>

          <Section title="Measurements">
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1.5 text-[0.9375rem]">
              {report.measurements.map((row) => (
                <div key={row.label} className="contents">
                  <dt className="text-sm text-ink-3">{row.label}</dt>
                  <dd className="m-0 font-mono tabular-nums">{row.value}</dd>
                </div>
              ))}
            </dl>
          </Section>

          <Section title="Findings">
            <p className="max-w-[42rem] text-[0.9375rem] text-ink-2">{report.findings}</p>
          </Section>

          <Section title="Impression">
            <p className="max-w-[42rem] text-[0.9375rem] text-ink-2">{report.impression}</p>
          </Section>

          <div className="grid gap-1 border-t border-line pt-4">
            <div className="text-base font-bold">{report.signedBy}</div>
            <div className="font-mono text-[0.6875rem] text-ink-3">{report.stamp}</div>
          </div>
        </article>
      </Card>

      <Card>
        <CardHead>
          <h3 className="mr-auto text-base">Growth follow-up report</h3>
          <Pill tone="warn">Preliminary</Pill>
        </CardHead>
        <CardBody>
          {/* No clinical content at all: Core #7 says a preliminary read is never shown to
              the patient, so this card must not leak findings, measurements, or an
              impression while it waits for a signature. */}
          <Alert tone="warn">
            <span>
              Your radiologist is still reviewing this study. The signed report appears here
              automatically, usually within one business day. For anything urgent, please call
              the clinic.
            </span>
          </Alert>
        </CardBody>
      </Card>
    </PortalFrame>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="mb-1.5 text-[0.6875rem] font-bold uppercase tracking-[0.14em] text-brand">
        {title}
      </h4>
      {children}
    </section>
  );
}
