import { redirect } from "next/navigation";

import { PortalFrame } from "@/components/PortalFrame";
import { ReportArticle } from "@/components/ReportArticle";
import { Alert, Card, CardBody, CardHead, EmptyState, Eyebrow, Pill } from "@/components/ui";
import { getReport, getReports } from "@/lib/api";

export const fetchCache = "only-no-store";

/** The patient's reports. The API returns signed reports only. */
export default async function ReportsPage() {
  const summaries = await getReports();
  if (summaries === null) redirect("/verify");

  const reports = await Promise.all(summaries.map((summary) => getReport(summary.id)));

  return (
    <PortalFrame counts={{ "/reports": reports.length }}>
      <div className="grid gap-1.5">
        <Eyebrow>Your reports</Eyebrow>
        <h1 className="text-2xl">Reports</h1>
        <p className="max-w-[44rem] text-[0.9375rem] text-ink-2">
          A report reaches you once your radiologist signs it. Preliminary reads stay with
          your care team until then.
        </p>
      </div>

      {reports.length === 0 ? (
        <EmptyState>
          You have no signed reports yet. One appears here as soon as your radiologist signs
          it.
        </EmptyState>
      ) : (
        reports.map((report) => (
          <Card key={report.id}>
            <CardHead>
              <h3 className="mr-auto text-base">{report.title}</h3>
              <Pill tone="ok">{report.status === "amended" ? "Amended" : "Signed"}</Pill>
            </CardHead>
            <ReportArticle report={report} />
          </Card>
        ))
      )}

      {/* The API never returns an unsigned report, so the patient is told why one they are
          expecting is absent rather than being left to wonder. */}
      <Card>
        <CardHead>
          <h3 className="mr-auto text-base">Still being reviewed</h3>
          <Pill tone="warn">Preliminary</Pill>
        </CardHead>
        <CardBody>
          <Alert tone="warn">
            <span>
              A study whose report your radiologist has not yet signed does not appear above.
              The signed report shows up here automatically, usually within one business day.
              For anything urgent, please call the clinic.
            </span>
          </Alert>
        </CardBody>
      </Card>
    </PortalFrame>
  );
}
