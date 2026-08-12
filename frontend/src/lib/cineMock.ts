/**
 * A stand-in cine clip, drawn in the browser.
 *
 * The cine API does not exist yet, so frames are generated on a canvas rather than
 * fetched. That is enough to exercise everything the transport has to get right —
 * playback rate, scrubbing, stepping, and the gap behaviour — before any endpoint lands.
 * Issue #14 replaces this with real frames.
 */

/** Frames the mock manifest references but cannot supply, mirroring a damaged clip. */
export const MISSING_FRAMES = new Set([57, 58, 59]);

/** Total frames the mock manifest declares. */
export const FRAME_COUNT = 100;

/** Playback rates offered in the transport. */
export const FPS_OPTIONS = [10, 15, 24] as const;

/** Default playback rate, stated in the README alongside the performance targets. */
export const DEFAULT_FPS = 15;

/**
 * Return the contiguous run of missing frames containing `frame`, if any.
 *
 * @param frame - Zero-based frame index.
 * @returns The inclusive range, or null when the frame is present.
 */
export function missingRange(frame: number): { start: number; end: number } | null {
  if (!MISSING_FRAMES.has(frame)) return null;
  let start = frame;
  let end = frame;
  while (MISSING_FRAMES.has(start - 1)) start -= 1;
  while (MISSING_FRAMES.has(end + 1)) end += 1;
  return { start, end };
}

/**
 * Return the next frame that actually exists, wrapping at the end of the clip.
 *
 * Playback steps over a gap rather than stalling on it: a damaged clip should keep
 * playing with a visible break, not freeze (edge case #2).
 *
 * @param frame - Current zero-based frame index.
 * @returns The next present frame.
 */
export function nextPresentFrame(frame: number): number {
  let candidate = (frame + 1) % FRAME_COUNT;
  let guard = 0;
  while (MISSING_FRAMES.has(candidate) && guard < FRAME_COUNT) {
    candidate = (candidate + 1) % FRAME_COUNT;
    guard += 1;
  }
  return candidate;
}

const SECTOR_HALF_ANGLE = (40 * Math.PI) / 180;

/**
 * Draw one frame of the mock clip.
 *
 * Deterministic in `frame`, so scrubbing back and forth shows the same image each time
 * rather than reshuffling the speckle.
 *
 * @param context - Target 2D context.
 * @param frame - Zero-based frame index.
 */
export function drawFrame(context: CanvasRenderingContext2D, frame: number): void {
  const { width, height } = context.canvas;
  context.fillStyle = "#0b0614";
  context.fillRect(0, 0, width, height);

  const image = context.createImageData(width, height);
  const data = image.data;
  const apexX = width / 2;
  const maxRadius = height * 0.98;

  const phase = (2 * Math.PI * frame) / FRAME_COUNT;
  const lesionX = apexX + Math.sin(phase) * width * 0.16;
  const lesionY = height * 0.52 + Math.cos(phase) * height * 0.12;
  const lesionR = height * 0.06 + Math.sin(phase * 2) * height * 0.02;

  // A cheap deterministic hash stands in for a seeded RNG so a given frame always renders
  // identically, which is what makes scrubbing stable.
  const noise = (x: number, y: number) => {
    const n = Math.sin(x * 12.9898 + y * 78.233 + frame * 0.37) * 43758.5453;
    return n - Math.floor(n);
  };

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const dx = x - apexX;
      const dy = y + 1;
      const radius = Math.hypot(dx, dy);
      const angle = Math.atan2(dx, dy);
      const index = (y * width + x) * 4;

      let value = 0;
      const inside =
        Math.abs(angle) <= SECTOR_HALF_ANGLE && radius <= maxRadius && radius >= height * 0.05;

      if (inside) {
        const depth = Math.min(radius / maxRadius, 1);
        const attenuation = Math.exp(-2.1 * depth) * 0.82 + 0.06;
        // Coarse speckle: sampling the hash on a 4px lattice gives grain rather than the
        // per-pixel static that reads as a broken signal.
        const grain = noise(Math.floor(x / 4), Math.floor(y / 4));
        value = attenuation * (0.55 + grain * 1.5) * 255;

        const lesionDistance = Math.hypot(x - lesionX, y - lesionY);
        if (lesionDistance < lesionR) value *= 0.07;
        else if (lesionDistance < lesionR + 2) value = Math.min(value * 2.4, 255);
      }

      const level = Math.max(0, Math.min(255, value));
      data[index] = level;
      data[index + 1] = level;
      data[index + 2] = level;
      data[index + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);
}
