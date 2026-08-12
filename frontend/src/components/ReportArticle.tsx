import { Eyebrow } from "@/components/ui";
import type { ReportDetail } from "@/lib/api";

/**
 * Renders a signed report.
 *
 * The body arrives as plain text with named sections, so headings are derived from those
 * markers rather than the text being rendered as HTML — a report is clinical content, not
 * markup we should be executing.
 */
export function ReportArticle({ report }: { report: ReportDetail }) {
  const sections = parseSections(report.body);

  return (
    <article className="grid gap-5 p-7">
      <header className="grid gap-1.5 border-b-2 border-brand pb-4">
        <Eyebrow>Northside Diagnostic Ultrasound</Eyebrow>
        <h2 className="text-xl tracking-[-0.02em]">{report.title}</h2>
      </header>

      {sections.map((section) => (
        <section key={section.heading}>
          <h4 className="mb-1.5 text-[0.6875rem] font-bold uppercase tracking-[0.14em] text-brand">
            {section.heading}
          </h4>
          <p className="max-w-[42rem] whitespace-pre-line text-[0.9375rem] text-ink-2">
            {section.body}
          </p>
        </section>
      ))}

      {report.signed_at ? (
        <div className="grid gap-1 border-t border-line pt-4">
          <div className="font-mono text-[0.6875rem] text-ink-3">
            Electronically signed{" "}
            {new Date(report.signed_at).toLocaleString("en-US", { timeZone: "UTC" })} UTC
          </div>
        </div>
      ) : null}
    </article>
  );
}

/** One titled block of a report body. */
interface Section {
  heading: string;
  body: string;
}

/**
 * Split a report body into its titled sections.
 *
 * @param body - The stored report text.
 * @returns Sections in document order; the whole body as one block if unrecognised.
 */
function parseSections(body: string): Section[] {
  const parts = body.split(/\n(?=[A-Z][A-Z ]{3,}\n)/g);
  const sections = parts
    .map((part) => {
      const [first, ...rest] = part.split("\n");
      if (!/^[A-Z][A-Z ]{3,}$/.test(first.trim())) return null;
      return { heading: first.trim(), body: rest.join("\n").trim() };
    })
    .filter((section): section is Section => section !== null);

  return sections.length > 0 ? sections : [{ heading: "Report", body }];
}
