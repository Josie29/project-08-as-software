import { Wordmark } from "@/components/Wordmark";

/**
 * Portal chrome.
 *
 * Deliberately carries no authentication check. Layouts are not re-rendered on navigation
 * under Partial Rendering, so a layout cannot gate its children — the pages themselves
 * verify, and the API refuses anything they miss.
 */
export default function PortalLayout({ children }: LayoutProps<"/">) {
  return (
    <>
      <header className="sticky top-0 z-40 border-b border-line bg-panel">
        <div className="mx-auto flex max-w-[78rem] flex-wrap items-center gap-4 px-6 py-3.5">
          <Wordmark />
          <span className="rounded-pill bg-warn-bg px-2.5 py-1 text-[0.6875rem] font-bold uppercase tracking-[0.06em] text-warn">
            Demo data
          </span>
        </div>
      </header>

      <div className="mx-auto grid max-w-[78rem] gap-8 px-6 pt-8 pb-16 lg:grid-cols-[15rem_1fr] lg:items-start">
        {children}
      </div>

      <footer className="mx-auto grid max-w-[78rem] gap-2 border-t border-line px-6 pt-6 pb-14 text-[0.8125rem] text-ink-3">
        <p>
          <strong className="text-ink-2">Synthetic data only.</strong> Every patient, image and
          report in this build is generated. No real protected health information is present.
        </p>
      </footer>
    </>
  );
}
