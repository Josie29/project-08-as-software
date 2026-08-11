/**
 * Product wordmark.
 *
 * The glyph is a sector scan — the shape an ultrasound probe actually paints — with the
 * arcs fading to suggest depth attenuation.
 */
export function Wordmark({ clinic = "Northside Diagnostic Ultrasound" }: { clinic?: string }) {
  return (
    <div className="mr-auto flex items-center gap-3">
      <svg className="block size-8 shrink-0" viewBox="0 0 40 40" aria-hidden="true">
        <defs>
          <linearGradient id="beam" x1="8" y1="36" x2="30" y2="4" gradientUnits="userSpaceOnUse">
            <stop stopColor="#873FE0" />
            <stop offset="1" stopColor="#C39EEF" />
          </linearGradient>
        </defs>
        <path
          d="M20 3 L35 30 A17 17 0 0 1 5 30 Z"
          fill="none"
          stroke="url(#beam)"
          strokeWidth="2.5"
          strokeLinejoin="round"
        />
        <path
          d="M11.5 22 A10 10 0 0 0 28.5 22"
          fill="none"
          stroke="url(#beam)"
          strokeWidth="2"
          opacity=".55"
        />
        <path
          d="M15 14.5 A6 6 0 0 0 25 14.5"
          fill="none"
          stroke="url(#beam)"
          strokeWidth="2"
          opacity=".35"
        />
      </svg>
      <div>
        <div className="text-[1.0625rem] font-bold tracking-[-0.02em]">My Ultrasound Images</div>
        <div className="text-xs text-ink-3">{clinic}</div>
      </div>
    </div>
  );
}
