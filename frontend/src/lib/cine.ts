import type { CineManifest } from "@/lib/api";

/** Playback rates offered in the viewer. */
export const FPS_OPTIONS = [6, 12, 24, 30] as const;

// How many frames are fetched at once on the fallback path. Browsers cap an HTTP/1.1
// origin at six connections, so this only pays off over HTTP/2.
const LOAD_CONCURRENCY = 12;

// How many bundled frames are decoded at once. Decoding is off the main thread, but each
// call still costs a task; an unbounded fan-out of a hundred makes the viewer unresponsive
// exactly while the patient is waiting to see it.
const DECODE_CONCURRENCY = 8;

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
export type LoadedFrame = ImageBitmap | null;

/** Called as each frame becomes drawable. */
type OnFrame = (sequence: number, image: LoadedFrame) => void;

/**
 * Decode one frame's bytes.
 *
 * `createImageBitmap` rather than `HTMLImageElement.decode()`: `decode()` waits on the
 * renderer, which Chrome suspends in a background tab, so the bytes arrive, `complete`
 * goes true, and the promise never settles. A patient who switches tabs mid-load would
 * come back to a clip stuck where they left it.
 *
 * @param bytes - The encoded frame.
 * @returns The decoded bitmap.
 */
function decodeFrame(bytes: BlobPart): Promise<ImageBitmap> {
  return createImageBitmap(new Blob([bytes], { type: "image/jpeg" }));
}

/**
 * Split a frame bundle into its constituent frames.
 *
 * Wire format, little-endian: a `uint32` frame count, then one `uint16` sequence and
 * `uint32` byte length per frame, then every frame's bytes concatenated in that order.
 *
 * @param buffer - The bundle body.
 * @returns Sequence numbers paired with their encoded bytes.
 * @throws Error If the bundle is truncated or its index does not match its payload.
 */
export function unpackFrames(buffer: ArrayBuffer): { sequence: number; bytes: ArrayBuffer }[] {
  const view = new DataView(buffer);
  const count = view.getUint32(0, true);
  const index: { sequence: number; length: number }[] = [];

  let cursor = 4;
  for (let i = 0; i < count; i += 1) {
    index.push({
      sequence: view.getUint16(cursor, true),
      length: view.getUint32(cursor + 2, true),
    });
    cursor += 6;
  }

  const frames = index.map(({ sequence, length }) => {
    const bytes = buffer.slice(cursor, cursor + length);
    if (bytes.byteLength !== length) throw new Error("cine bundle is truncated");
    cursor += length;
    return { sequence, bytes };
  });
  return frames;
}

/**
 * Run tasks a few at a time.
 *
 * @param items - Work items.
 * @param limit - How many run concurrently.
 * @param run - Handles one item.
 */
async function inBatches<T>(items: T[], limit: number, run: (item: T) => Promise<void>) {
  let cursor = 0;
  async function worker() {
    while (cursor < items.length) await run(items[cursor++]!);
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
}

/**
 * Fetch and decode a clip's frames.
 *
 * Two requests race deliberately. The bundle carries the whole clip in one round trip,
 * which is what makes a hundred-frame study load in seconds rather than a minute — but it
 * is only useful once all of it has arrived. The lead frame is fetched alongside it so
 * there is something on screen well before that.
 *
 * If the bundle fails, every frame is fetched individually instead. The per-frame route is
 * the authorisation unit either way, so the fallback is slower but not weaker.
 *
 * @param manifest - The clip manifest.
 * @param onFrame - Called as each frame becomes drawable.
 * @param signal - Aborts loading when the viewer closes.
 */
export async function loadFrames(
  manifest: CineManifest,
  onFrame: OnFrame,
  signal: AbortSignal,
): Promise<void> {
  const available = manifest.frames.filter((frame) => frame.available).map((f) => f.sequence);
  if (available.length === 0) return;

  const delivered = new Set<number>();
  const deliver = (sequence: number, image: LoadedFrame) => {
    // The lead frame arrives on both paths; the loser of that race must be discarded, or
    // its bitmap leaks and the progress count runs past the number of frames.
    if (signal.aborted || delivered.has(sequence)) {
      image?.close();
      return;
    }
    delivered.add(sequence);
    onFrame(sequence, image);
  };

  const lead = available[0]!;
  const leadFrame = fetchFrame(manifest.id, lead, signal)
    .then((image) => deliver(lead, image))
    .catch(() => {});

  try {
    const response = await fetch(`/api/phi/cine/${manifest.id}/frames`, { signal });
    if (!response.ok) throw new Error(`bundle returned ${response.status}`);
    const packed = unpackFrames(await response.arrayBuffer());

    await inBatches(packed, DECODE_CONCURRENCY, async ({ sequence, bytes }) => {
      if (signal.aborted || delivered.has(sequence)) return;
      try {
        deliver(sequence, await decodeFrame(bytes));
      } catch {
        deliver(sequence, null);
      }
    });
  } catch {
    if (signal.aborted) return;
    await inBatches(available, LOAD_CONCURRENCY, async (sequence) => {
      if (delivered.has(sequence)) return;
      deliver(sequence, await fetchFrame(manifest.id, sequence, signal).catch(() => null));
    });
  }

  await leadFrame;

  // Frames the bundle promised but could not carry are reported as gaps, so playback
  // degrades exactly as it does for a frame the study never had.
  for (const sequence of available) {
    if (!delivered.has(sequence)) deliver(sequence, null);
  }
}

/**
 * Fetch and decode one frame.
 *
 * @param clipId - The clip.
 * @param sequence - Zero-based frame position.
 * @param signal - Aborts the request.
 * @returns The decoded bitmap.
 * @throws Error If the frame cannot be fetched.
 */
async function fetchFrame(
  clipId: string,
  sequence: number,
  signal: AbortSignal,
): Promise<ImageBitmap> {
  const response = await fetch(`/api/phi/cine/${clipId}/frames/${sequence}`, { signal });
  if (!response.ok) throw new Error(`frame ${sequence} returned ${response.status}`);
  return decodeFrame(await response.blob());
}
