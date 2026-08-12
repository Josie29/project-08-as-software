"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui";
import type { CineClipSummary, CineManifest } from "@/lib/api";
import { FPS_OPTIONS, type Gap, type LoadedFrame, findGaps, gapAt, loadFrames } from "@/lib/cine";
import { isFromFormControl, useDialog, usePrefersReducedMotion } from "@/lib/useDialog";

const STAGE_WIDTH = 640;
const STAGE_HEIGHT = 480;

/** Frames buffered before playback starts, so it does not stutter on the first pass. */
const START_THRESHOLD = 8;

/**
 * Cine viewer backed by the clip manifest.
 *
 * Playback is driven by requestAnimationFrame with an explicit time accumulator rather
 * than setInterval, so the requested rate is honoured on a busy tab instead of drifting
 * with timer backlog. Decoded frames are held in memory for the life of the viewer: frame
 * bytes are served `no-store`, so nothing is left on disk once it closes.
 */
export function CinePlayer({
  clip,
  label,
  onClose,
}: {
  clip: CineClipSummary;
  label: string;
  onClose: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  // A clip that starts looping on its own is exactly the motion this preference asks us
  // not to produce. The transport is untouched — playback is a keypress away.
  const reducedMotion = usePrefersReducedMotion();
  // Mirrored so the loader reads the current preference without listing it as a dependency
  // — a change mid-view would otherwise abort and refetch the whole clip.
  const reducedMotionRef = useRef(reducedMotion);

  const [manifest, setManifest] = useState<CineManifest | null>(null);
  const [gaps, setGaps] = useState<Gap[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [readyCount, setReadyCount] = useState(0);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [fps, setFps] = useState<number>(clip.default_fps);

  // Decoded frames live in a ref, not state: a hundred image elements in the render tree
  // would re-render the whole viewer on every decode for no visual benefit. `readyCount`
  // is the state that drives the UI.
  const framesRef = useRef<LoadedFrame[]>([]);
  const frameCount = manifest?.frame_count ?? clip.frame_count;
  const gap = gapAt(gaps, frame);
  const loading = readyCount < clip.available_frame_count;

  useEffect(() => {
    const controller = new AbortController();

    async function start() {
      const response = await fetch(`/api/phi/cine/${clip.id}/manifest`, {
        signal: controller.signal,
      });
      if (!response.ok) {
        setError("This clip could not be opened. Please try again.");
        return;
      }
      const loaded: CineManifest = await response.json();
      if (controller.signal.aborted) return;

      framesRef.current = new Array<LoadedFrame>(loaded.frame_count).fill(null);
      setManifest(loaded);
      setGaps(findGaps(loaded));
      // Start on the first frame that actually exists, so a clip whose opening frames are
      // missing does not greet the patient with a gap notice.
      setFrame(loaded.frames.find((entry) => entry.available)?.sequence ?? 0);

      // Playback starts from the loader callback rather than from an effect watching the
      // count: an effect that flips playing on would cascade a render for every one of a
      // hundred decodes, and only the first crossing of the threshold matters.
      const threshold = Math.min(START_THRESHOLD, clip.available_frame_count);
      let ready = 0;

      await loadFrames(
        loaded,
        (sequence, image) => {
          framesRef.current[sequence] = image;
          ready += 1;
          setReadyCount(ready);
          if (ready >= threshold && !reducedMotionRef.current) setPlaying(true);
        },
        controller.signal,
      );
    }

    start().catch(() => {
      if (!controller.signal.aborted) setError("This clip could not be opened.");
    });

    return () => {
      controller.abort();
      // Bitmaps hold decoded pixel buffers the garbage collector does not account for —
      // a hundred frames left open is memory the tab keeps until it is reloaded.
      for (const bitmap of framesRef.current) bitmap?.close();
      framesRef.current = [];
    };
  }, [clip.id, clip.available_frame_count]);

  // Refs mirror the animation inputs so the rAF loop reads current values without being
  // torn down and restarted on every frame change. Synced in effects rather than assigned
  // during render, which is unsafe under concurrent rendering.
  const fpsRef = useRef(fps);
  const playingRef = useRef(playing);
  const countRef = useRef(frameCount);
  useEffect(() => {
    reducedMotionRef.current = reducedMotion;
  }, [reducedMotion]);
  useEffect(() => {
    fpsRef.current = fps;
  }, [fps]);
  useEffect(() => {
    playingRef.current = playing;
  }, [playing]);
  useEffect(() => {
    countRef.current = frameCount;
  }, [frameCount]);

  useEffect(() => {
    let raf = 0;
    let last = performance.now();
    let accumulator = 0;

    const tick = (now: number) => {
      const elapsed = now - last;
      last = now;
      if (playingRef.current) {
        accumulator += elapsed;
        const interval = 1000 / fpsRef.current;
        if (accumulator >= interval) {
          // Drop whole intervals rather than replaying them, so a stall does not cause a
          // burst of catch-up frames.
          accumulator %= interval;
          setFrame((current) => (current + 1) % countRef.current);
        }
      }
      raf = requestAnimationFrame(tick);
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    const context = canvasRef.current?.getContext("2d");
    if (!context) return;
    const image = framesRef.current[frame];
    if (!image) {
      // Clear rather than leave the previous frame on screen. A stale image behind the gap
      // notice reads as though the missing frame has content, which misrepresents the
      // study — the whole point of surfacing the gap.
      context.fillStyle = "#0b0614";
      context.fillRect(0, 0, context.canvas.width, context.canvas.height);
      return;
    }
    context.drawImage(image, 0, 0, context.canvas.width, context.canvas.height);
  }, [frame, readyCount]);

  const step = useCallback((delta: number) => {
    // Stepping is a deliberate act, so it pauses rather than fighting playback.
    setPlaying(false);
    setFrame((current) => (current + delta + countRef.current) % countRef.current);
  }, []);

  useDialog(dialogRef, onClose, true, closeRef);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      // Space and the arrows belong to whatever control has focus. Claiming them for the
      // transport makes every button and the scrubber unusable by keyboard.
      if (isFromFormControl(event)) return;
      if (event.key === " ") {
        event.preventDefault();
        setPlaying((value) => !value);
      }
      if (event.key === "ArrowRight") step(1);
      if (event.key === "ArrowLeft") step(-1);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [step]);

  return (
    <div
      className="fixed inset-0 z-60 grid place-items-center bg-[rgb(20_10_34/0.74)] p-4 backdrop-blur-sm"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Cine clip viewer, ${label}`}
        className="max-h-[92dvh] w-[min(60rem,100%)] overflow-auto rounded-lg bg-scan-chrome text-scan-ink shadow-float"
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-scan-line px-4 py-3">
          <h2 className="mr-auto text-sm font-bold text-white">
            {label} · {frameCount} frames
          </h2>
          {loading && !error ? (
            <span
              role="status"
              className="rounded-pill bg-scan px-2.5 py-1 font-mono text-[0.6875rem] text-scan-accent"
            >
              {readyCount}/{clip.available_frame_count} loaded
            </span>
          ) : null}
          <Button ref={closeRef} tone="scan" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>

        {/* The stage is capped so the transport is always on screen. Controls that need
            scrolling to reach are controls a patient will not find. */}
        <div className="relative grid max-h-[52dvh] place-items-center overflow-hidden bg-scan">
          <canvas
            ref={canvasRef}
            width={STAGE_WIDTH}
            height={STAGE_HEIGHT}
            className="block max-h-[52dvh] w-full max-w-full object-contain"
          />

          {/* Overlay mirrors the readout on a real ultrasound console. */}
          <div className="pointer-events-none absolute left-4 top-3 font-mono text-xs text-scan-accent">
            {playing ? "▶ CINE" : "❚❚ FROZEN"}
          </div>
          <div className="pointer-events-none absolute right-4 top-3 font-mono text-xs text-scan-dim">
            {String(frame + 1).padStart(3, "0")} / {frameCount}
          </div>

          {error ? (
            <div className="absolute inset-0 grid place-items-center px-6 text-center">
              <span className="text-sm text-scan-ink">{error}</span>
            </div>
          ) : null}

          {gap ? (
            <>
              <div className="absolute inset-0 grid place-items-center px-6 text-center">
                <span className="font-mono text-sm text-scan-ink">
                  Frame {String(frame + 1).padStart(3, "0")} unavailable
                </span>
              </div>
              {/* The clip keeps playing through the gap; the break is shown rather than
                  hidden, because a silently skipped frame would misrepresent the study. */}
              <div className="absolute inset-x-0 bottom-0 border-t-2 border-[#f0788c] bg-[rgb(192_40_64/0.28)] px-3.5 py-2.5 text-center text-[0.8125rem] text-[#ffd9df]">
                Frames {gap.start + 1}–{gap.end + 1} are missing from this clip. Playback picks up
                at frame {gap.end + 2}.
              </div>
            </>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2.5 border-t border-scan-line px-4 py-3.5">
          <Button tone="scan" size="sm" onClick={() => step(-1)} aria-label="Previous frame">
            ◀◀
          </Button>
          <Button
            tone="scanPrimary"
            size="sm"
            aria-pressed={playing}
            onClick={() => setPlaying((value) => !value)}
          >
            {playing ? "Pause" : "Play"}
          </Button>
          <Button tone="scan" size="sm" onClick={() => step(1)} aria-label="Next frame">
            ▶▶
          </Button>

          <label htmlFor="scrub" className="sr-only">
            Frame
          </label>
          <input
            id="scrub"
            type="range"
            min={0}
            max={Math.max(frameCount - 1, 0)}
            value={frame}
            onChange={(event) => {
              setPlaying(false);
              setFrame(Number(event.target.value));
            }}
            className="h-8 min-w-40 flex-1 accent-[var(--scan-accent)]"
          />

          <label
            htmlFor="fps"
            className="text-[0.6875rem] font-bold uppercase tracking-[0.1em] text-scan-dim"
          >
            FPS
          </label>
          <select
            id="fps"
            value={fps}
            onChange={(event) => setFps(Number(event.target.value))}
            className="min-h-9 rounded-md border border-scan-line bg-transparent px-2 py-1.5 font-mono text-[0.8125rem] text-scan-ink"
          >
            {FPS_OPTIONS.map((option) => (
              <option key={option} value={option} className="bg-scan-chrome">
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-wrap items-center gap-2.5 border-t border-scan-line px-4 py-3.5">
          <span className="mr-auto text-xs text-scan-dim">
            Space plays and pauses · arrow keys step a frame · drag the slider to scrub
          </span>
          <Button
            tone="scan"
            size="sm"
            disabled
            title="Clips cannot be shared yet — share a still image from this study instead"
          >
            Share
          </Button>
        </div>
      </div>
    </div>
  );
}
