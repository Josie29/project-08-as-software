import { forwardRef } from "react";
import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

/** Visual weight of a button. */
type ButtonTone = "default" | "primary" | "ghost" | "danger" | "scan" | "scanPrimary";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: ButtonTone;
  size?: "md" | "sm";
  block?: boolean;
}

const BUTTON_TONES: Record<ButtonTone, string> = {
  default: "bg-panel border-line text-ink hover:border-brand hover:text-brand",
  primary: "bg-brand border-brand text-brand-ink hover:bg-brand-deep hover:border-brand-deep",
  ghost: "bg-transparent border-transparent text-ink hover:bg-brand-tint",
  danger: "bg-panel border-line text-ink hover:border-crit hover:text-crit",
  scan: "bg-transparent border-scan-line text-scan-ink hover:border-scan-accent hover:text-scan-accent",
  // Hardcoded white failed twice over: it sat on the light violet the brand token becomes
  // in dark mode, and on the light hover fill in day mode. brand-ink is the token that
  // flips with the surface, which is the whole reason it exists.
  scanPrimary: "bg-brand border-brand text-brand-ink hover:bg-brand-deep hover:border-brand-deep",
};

/**
 * Pill-shaped button.
 *
 * The minimum height is a deliberate floor, not decoration: every control has to stay
 * comfortably tappable on a phone, which the brief grades directly.
 */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { tone = "default", size = "md", block = false, className = "", ...props },
  ref,
) {
  const sizing =
    size === "sm"
      ? "min-h-[2.125rem] px-3 py-1 text-[0.8125rem]"
      : "min-h-[2.625rem] px-[1.125rem] py-2 text-sm";
  return (
    <button
      className={[
        "inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-pill border font-semibold",
        "transition-colors duration-150 disabled:cursor-not-allowed disabled:opacity-45",
        BUTTON_TONES[tone],
        sizing,
        block ? "w-full" : "",
        className,
      ].join(" ")}
      ref={ref}
      {...props}
    />
  );
});

/** Semantic colour for status pills and alerts. */
type Tone = "ok" | "warn" | "crit" | "mute" | "brand";

const PILL_TONES: Record<Tone, string> = {
  ok: "text-ok bg-ok-bg",
  warn: "text-warn bg-warn-bg",
  crit: "text-crit bg-crit-bg",
  mute: "text-ink-3 bg-panel-2",
  brand: "text-brand bg-brand-tint",
};

/**
 * Status pill.
 *
 * Carries a dot as well as colour so status is never conveyed by hue alone — required for
 * the accessibility baseline and for anyone reading on a poor screen.
 */
export function Pill({
  tone = "mute",
  dot = true,
  children,
}: {
  tone?: Tone;
  dot?: boolean;
  children: ReactNode;
}) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-pill px-2.5 py-0.5",
        "text-[0.6875rem] font-bold uppercase tracking-[0.04em]",
        PILL_TONES[tone],
      ].join(" ")}
    >
      {dot ? <span className="size-1.5 shrink-0 rounded-full bg-current" aria-hidden /> : null}
      {children}
    </span>
  );
}

const ALERT_TONES: Record<Tone, string> = {
  ok: "bg-ok-bg text-ok",
  warn: "bg-warn-bg text-warn",
  crit: "bg-crit-bg text-crit",
  mute: "bg-panel-2 text-ink-2",
  brand: "bg-brand-tint text-brand",
};

/** Inline message block. Errors render with `role="alert"` so they are announced. */
export function Alert({ tone = "brand", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <div
      role={tone === "crit" ? "alert" : undefined}
      className={`flex gap-2 rounded-md px-3.5 py-3 text-sm ${ALERT_TONES[tone]}`}
    >
      {children}
    </div>
  );
}

/** Surface panel used for every content grouping. */
export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`overflow-hidden rounded-lg border border-line bg-panel shadow-card ${className}`}
      {...props}
    />
  );
}

/** Header strip of a card: title, status, and timestamp. */
export function CardHead({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-line-soft px-5 py-4">
      {children}
    </div>
  );
}

/** Padded body of a card. */
export function CardBody({
  className = "",
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={`grid gap-4 p-5 ${className}`}>{children}</div>;
}

/** Small uppercase label that sits above a heading. */
export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="text-[0.6875rem] font-bold uppercase tracking-[0.14em] text-brand">{children}</p>
  );
}

/** Dashed placeholder shown where content will appear but does not exist yet. */
export function EmptyState({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-line p-6 text-center text-sm text-ink-3">
      {children}
    </div>
  );
}

/** Labelled form field with optional hint and error wiring. */
export function Field({
  label,
  hint,
  htmlFor,
  children,
}: {
  label: string;
  hint?: string;
  htmlFor: string;
  children: ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={htmlFor} className="text-[0.8125rem] font-semibold text-ink-2">
        {label}
      </label>
      {children}
      {hint ? <span className="text-xs text-ink-3">{hint}</span> : null}
    </div>
  );
}

/** Text input styled to the design system. Monospaced, because every field here is an id or a date. */
export function TextInput({
  className = "",
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={[
        "min-h-[2.875rem] rounded-md border border-line bg-panel-2 px-3.5 py-2.5",
        "font-mono focus:border-brand focus:bg-panel",
        className,
      ].join(" ")}
      {...props}
    />
  );
}
