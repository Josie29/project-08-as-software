"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui";
import {
  DEFAULT_FPS,
  FPS_OPTIONS,
  FRAME_COUNT,
  drawFrame,
  missingRange,
  nextPresentFrame,
} from "@/lib/cineMock";

const STAGE_WIDTH = 640;
const STAGE_HEIGHT = 480;

/**
 * Cine viewer with frame transport.
 *
 * Playback is driven by requestAnimationFrame with an explicit time accumulator rather
 * than setInterval, so the requested rate is honoured on a busy tab instead of drifting
 * with timer backlog.
 */
export function CinePlayer({ onClose }: { onClose: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [fps, setFps] = useState<number>(DEFAULT_FPS);

  const gap = missingRange(frame);

  // Refs mirror the animation inputs so the rAF loop reads current values without being
  // torn down and restarted on every frame change. Synced in effects rather than assigned
  // during render, which is unsafe under concurrent rendering.
  const fpsRef = useRef(fps);
  const playingRef = useRef(playing);
  useEffect(() => {
    fpsRef.current = fps;
  }, [fps]);
  useEffect(() => {
    playingRef.current = playing;
  }, [playing]);

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
          setFrame((current) => nextPresentFrame(current));
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
    if (gap) {
      // Clear rather than leave the previous frame on screen. A stale image behind the
      // gap notice reads as though the missing frame has content, which misrepresents
      // the study — the whole point of surfacing the gap.
      context.fillStyle = "#0b0614";
      context.fillRect(0, 0, context.canvas.width, context.canvas.height);
      return;
    }
    drawFrame(context, frame);
  }, [frame, gap]);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  const step = useCallback((delta: number) => {
    // Stepping is a deliberate act, so it pauses rather than fighting playback.
    setPlaying(false);
    setFrame((current) => (current + delta + FRAME_COUNT) % FRAME_COUNT);
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (event.key === " ") {
        event.preventDefault();
        setPlaying((value) => !value);
      }
      if (event.key === "ArrowRight") step(1);
      if (event.key === "ArrowLeft") step(-1);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, step]);

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
        aria-label="Cine clip viewer"
        className="max-h-[92dvh] w-[min(60rem,100%)] overflow-auto rounded-lg bg-scan-chrome text-scan-ink shadow-float"
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-scan-line px-4 py-3">
          <h2 className="mr-auto text-sm font-bold text-white">CINE-0001 · sample clip</h2>
          <span className="rounded-pill bg-warn-bg px-2.5 py-1 text-[0.6875rem] font-bold uppercase tracking-[0.06em] text-warn">
            Placeholder
          </span>
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
            {String(frame + 1).padStart(3, "0")} / {FRAME_COUNT}
          </div>

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
                Frames {gap.start + 1}–{gap.end + 1} are missing from this clip. Playback picks
                up at frame {gap.end + 2}.
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
            max={FRAME_COUNT - 1}
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
          <Button tone="scan" size="sm" disabled title="Available once secure sharing ships">
            Share
          </Button>
        </div>
      </div>
    </div>
  );
}
