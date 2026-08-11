"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/** One navigation destination, with the rubric tier it belongs to. */
interface RailItem {
  href: string;
  label: string;
  count?: number;
  tier?: string;
}

const ITEMS: RailItem[] = [
  { href: "/studies", label: "Images & cine", tier: "Priority 1" },
  { href: "/reports", label: "Reports", tier: "Priority 2" },
  { href: "/shares", label: "Shared links" },
  { href: "/appointments", label: "Appointments", tier: "Priority 3" },
  { href: "/activity", label: "Access log" },
];

/**
 * Sidebar navigation.
 *
 * The tick beside each item echoes the depth scale printed down the side of a sonogram —
 * it thickens and takes the brand colour on the active item, so the current section is
 * legible from the shape alone rather than from colour only.
 */
export function Rail({ counts = {} }: { counts?: Record<string, number> }) {
  const pathname = usePathname();

  return (
    <nav className="grid gap-0.5" aria-label="Portal sections">
      {ITEMS.map((item) => {
        const active = pathname.startsWith(item.href);
        const count = counts[item.href];
        return (
          <div key={item.href}>
            <Link
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={[
                "grid min-h-[2.75rem] grid-cols-[1.25rem_1fr_auto] items-center gap-2.5",
                "rounded-pill py-2 pr-3 text-[0.9375rem] transition-colors",
                active
                  ? "bg-brand-tint font-bold text-brand"
                  : "text-ink-2 hover:bg-panel hover:text-ink",
              ].join(" ")}
            >
              <span
                aria-hidden
                className={[
                  "ml-3 rounded-sm transition-all",
                  active ? "h-1 bg-brand" : "h-0.5 bg-line",
                ].join(" ")}
              />
              <span>{item.label}</span>
              {count !== undefined ? (
                <span
                  className={[
                    "rounded-pill px-1.5 py-px font-mono text-[0.6875rem]",
                    active ? "bg-panel text-brand" : "bg-panel-2 text-ink-3",
                  ].join(" ")}
                >
                  {count}
                </span>
              ) : (
                <span />
              )}
            </Link>
            {item.tier ? (
              <p className="py-1 pl-8 text-[0.625rem] font-bold uppercase tracking-[0.1em] text-ink-3">
                {item.tier}
              </p>
            ) : null}
          </div>
        );
      })}
    </nav>
  );
}
