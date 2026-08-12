import type { CineManifest } from "@/lib/api";

/** Playback rates offered in the viewer. */
export const FPS_OPTIONS = [6, 12, 24, 30] as const;

// How many frames are fetched at once. Browsers cap an HTTP/1.1 origin at six connections,
// so this only pays off where the app is served over HTTP/2 — which is everywhere it is
// deployed, and not the local dev server.
const LOAD_CONCURRENCY = 12;

/** A contiguous run of frames the study is missing. */
export interface Gap {
  start: number;
  end: number;
}

/**
 * Collapse a manifest's unavailable frames into contiguous ranges.
 *
 * Ranges rather than individual numbers because that is how the gap reads to a patient:
 * "frames 10-11 are missing" is a fact about the study, where a list of ten separate
 * notices is noise.
 *
 * @param manifest - The clip manifest.
 * @returns The gaps, in playback order.
 */
export function findGaps(manifest: CineManifest): Gap[] {
  const gaps: Gap[] = [];
  for (const frame of manifest.frames) {
    if (frame.available) continue;
    const last = gaps.at(-1);
    if (last && last.end === frame.sequence - 1) {
      last.end = frame.sequence;
    } else {
      gaps.push({ start: frame.sequence, end: frame.sequence });
    }
  }
  return gaps;
}

/**
 * Return the gap containing a frame, if any.
 *
 * @param gaps - Known gaps.
 * @param sequence - The frame position.
 * @returns The gap, or null.
 */
export function gapAt(gaps: Gap[], sequence: number): Gap | null {
  return gaps.find((gap) => sequence >= gap.start && sequence <= gap.end) ?? null;
}

/** One decoded frame, or a known hole in the clip. */
export type LoadedFrame = HTMLImageElement | null;

/**
 * Fetch and decode a clip's frames in playback order.
 *
 * Order matters more than raw throughput here: the first frame a patient sees is the one
 * they wait for, so frames are requested in the order they will be played, a few at a
 * time. Unavailable frames are skipped rather than requested — the manifest already says
 * the bytes are not there, and asking anyway would turn a known gap into a failed request.
 *
 * @param manifest - The clip manifest.
 * @param onFrame - Called as each frame decodes, with its position.
 * @param signal - Aborts loading when the viewer closes.
 * @returns A promise resolving once every available frame has settled.
 */
export async function loadFrames(
  manifest: CineManifest,
  onFrame: (sequence: number, image: LoadedFrame) => void,
  signal: AbortSignal,
): Promise<void> {
  const pending = manifest.frames.filter((frame) => frame.available).map((frame) => frame.sequence);
  let cursor = 0;

  async function worker(): Promise<void> {
    while (cursor < pending.length && !signal.aborted) {
      const sequence = pending[cursor++]!;
      const image = new Image();
      image.src = `/api/phi/cine/${manifest.id}/frames/${sequence}`;
      try {
        await image.decode();
        if (!signal.aborted) onFrame(sequence, image);
      } catch {
        // A frame the manifest promised but storage could not produce. Treated exactly
        // like a declared gap so playback degrades the same way instead of stalling.
        if (!signal.aborted) onFrame(sequence, null);
      }
    }
  }

  await Promise.all(
    Array.from({ length: Math.min(LOAD_CONCURRENCY, pending.length) }, () => worker()),
  );
}
