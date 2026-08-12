import { PortalFrame } from "@/components/PortalFrame";
import { PreviewNotice } from "@/components/PreviewNotice";
import { Card, CardHead, EmptyState, Eyebrow, Pill } from "@/components/ui";
import { MOCK_AUDIT } from "@/lib/mock";

export const fetchCache = "only-no-store";

/** The patient's own access log — who touched their record, and whether it was allowed. */
export default function ActivityPage() {
  const rows = MOCK_AUDIT;

  return (
    <PortalFrame>
      <div className="grid gap-1.5">
        <Eyebrow>Compliance</Eyebrow>
        <h1 className="text-2xl">Access log</h1>
        <p className="max-w-[44rem] text-[0.9375rem] text-ink-2">
          Every time your images or report are opened, it is written here — including attempts that
          were refused. Entries can only be added, never edited or removed.
        </p>
      </div>

      <PreviewNotice>
        The access-log API is not built yet, so these entries are examples. The real log is already
        being written server-side on every access.
      </PreviewNotice>

      <Card>
        <CardHead>
          <h3 className="mr-auto text-base">Recent activity</h3>
        </CardHead>
        {rows.length === 0 ? (
          <div className="p-5">
            <EmptyState>
              Nothing yet. Activity appears here the first time your record is opened.
            </EmptyState>
          </div>
        ) : (
          /* The table scrolls inside its own container so a phone never scrolls the page
             sideways. The container is focusable and labelled as a region because a scroll
             box that only responds to a pointer is content a keyboard user cannot reach the
             right-hand end of. */
          <div
            className="overflow-x-auto"
            tabIndex={0}
            role="region"
            aria-label="Access log entries, scrollable"
          >
            <table className="w-full border-collapse text-[0.8125rem]">
              <thead>
                <tr>
                  {["When", "Who", "Action", "Target", "Result"].map((head) => (
                    <th
                      key={head}
                      scope="col"
                      className="whitespace-nowrap border-b border-line-soft px-5 py-2.5 text-left text-[0.6875rem] font-bold uppercase tracking-[0.08em] text-ink-3"
                    >
                      {head}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.when}-${row.target}`}>
                    <td className="whitespace-nowrap border-b border-line-soft px-5 py-2.5 font-mono tabular-nums text-ink-2">
                      {row.when}
                    </td>
                    <td className="whitespace-nowrap border-b border-line-soft px-5 py-2.5">
                      {row.who}
                    </td>
                    <td className="whitespace-nowrap border-b border-line-soft px-5 py-2.5">
                      {row.action}
                    </td>
                    <td className="whitespace-nowrap border-b border-line-soft px-5 py-2.5 font-mono text-ink-2">
                      {row.target}
                    </td>
                    <td className="whitespace-nowrap border-b border-line-soft px-5 py-2.5">
                      {/* Word as well as colour: a refused access must be legible to someone
                          who cannot distinguish the two hues. */}
                      <Pill tone={row.allowed ? "ok" : "crit"}>
                        {row.allowed ? "Allowed" : "Denied"}
                      </Pill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </PortalFrame>
  );
}
