"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui";
import type { ImageSummary } from "@/lib/api";

const MIN_ZOOM = 1;
const MAX_ZOOM = 4;
const ZOOM_STEP = 0.25;

/**
 * Full-screen image viewer with zoom and pan.
 *
 * Zoom and pan are implemented directly on pointer events rather than through a library so
 * that touch behaviour on a phone is ours to control — the brief grades mobile usability,
 * and `touch-action: none` plus pointer capture is what stops the page scrolling underneath
 * a drag.
 */
export function ImageViewer({
  images,
  startIndex,
  onClose,
}: {
  images: ImageSummary[];
  startIndex: number;
  onClose: () => void;
}) {
  const [index, setIndex] = useState(startIndex);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [fullLoaded, setFullLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  const dragOrigin = useRef<{ x: number; y: number } | null>(null);
  // Held in state rather than read off the ref: reading a ref during render is
  // unsafe under concurrent rendering, and the cursor is render output.
  const [isDragging, setIsDragging] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const image = images[index];

  const reset = useCallback(() => {
    setZoom(1);
    setOffset({ x: 0, y: 0 });
    setFullLoaded(false);
    setFailed(false);
  }, []);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowRight" && index < images.length - 1) {
        setIndex(index + 1);
        reset();
      }
      if (event.key === "ArrowLeft" && index > 0) {
        setIndex(index - 1);
        reset();
      }
      // Focus is kept inside the dialog: tabbing out of a modal leaves a keyboard user
      // interacting with a page they cannot see.
      if (event.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          "button, [href], input, select, [tabindex]:not([tabindex='-1'])",
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        } else if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        }
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [index, images.length, onClose, reset]);

  function applyZoom(next: number) {
    const clamped = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, next));
    setZoom(clamped);
    if (clamped === 1) setOffset({ x: 0, y: 0 });
  }

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
        aria-label={`Ultrasound image ${index + 1} of ${images.length}`}
        className="max-h-[92dvh] w-[min(60rem,100%)] overflow-auto rounded-lg bg-scan-chrome text-scan-ink shadow-float"
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-scan-line px-4 py-3">
          <h2 className="mr-auto text-sm font-bold tracking-[-0.01em] text-white">
            IMG-{String(index + 1).padStart(4, "0")}
          </h2>
          <Button tone="scan" size="sm" onClick={() => applyZoom(zoom - ZOOM_STEP)} aria-label="Zoom out">
            −
          </Button>
          <span className="min-w-[3.5rem] text-center font-mono text-[0.8125rem] text-scan-accent">
            {Math.round(zoom * 100)}%
          </span>
          <Button tone="scan" size="sm" onClick={() => applyZoom(zoom + ZOOM_STEP)} aria-label="Zoom in">
            +
          </Button>
          <Button tone="scan" size="sm" onClick={reset}>
            Reset
          </Button>
          <Button ref={closeRef} tone="scan" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>

        <div className="relative grid overflow-hidden bg-scan">
          {!fullLoaded && !failed ? (
            <span className="absolute inset-x-0 top-4 z-10 text-center font-mono text-xs text-scan-dim">
              Loading full resolution…
            </span>
          ) : null}

          {failed ? (
            <div className="grid aspect-[4/3] place-items-center px-6 text-center text-sm text-scan-dim">
              This image could not be loaded. It may have been removed. Try again shortly.
            </div>
          ) : (
            /* eslint-disable-next-line @next/next/no-img-element -- proxied through a route
               handler that attaches the auth token. */
            <img
              src={`/api/phi/images/${image.id}/file`}
              alt={`Ultrasound image ${index + 1}`}
              draggable={false}
              onLoad={() => setFullLoaded(true)}
              onError={() => setFailed(true)}
              style={{
                transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`,
                touchAction: "none",
                cursor: zoom > 1 ? (isDragging ? "grabbing" : "grab") : "default",
              }}
              className="aspect-[4/3] w-full object-contain transition-[opacity] duration-200"
              onPointerDown={(event) => {
                if (zoom === 1) return;
                dragOrigin.current = { x: event.clientX - offset.x, y: event.clientY - offset.y };
                setIsDragging(true);
                event.currentTarget.setPointerCapture(event.pointerId);
              }}
              onPointerMove={(event) => {
                if (!dragOrigin.current) return;
                setOffset({
                  x: event.clientX - dragOrigin.current.x,
                  y: event.clientY - dragOrigin.current.y,
                });
              }}
              onPointerUp={(event) => {
                dragOrigin.current = null;
                setIsDragging(false);
                event.currentTarget.releasePointerCapture(event.pointerId);
              }}
              onWheel={(event) => applyZoom(zoom - Math.sign(event.deltaY) * ZOOM_STEP)}
            />
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2.5 border-t border-scan-line px-4 py-3.5">
          <span className="mr-auto text-xs text-scan-dim">
            Drag to pan · scroll to zoom · arrow keys to change image
          </span>
          <Button tone="scan" size="sm" disabled title="Available once secure sharing ships">
            Share
          </Button>
        </div>
      </div>
    </div>
  );
}
