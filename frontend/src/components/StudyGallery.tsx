"use client";

import { useState } from "react";

import { CinePlayer } from "@/components/CinePlayer";
import { ImageViewer } from "@/components/ImageViewer";
import { Card, CardBody, CardHead, EmptyState, Pill } from "@/components/ui";
import type { CineClipSummary, ImageSummary, StudySummary } from "@/lib/api";

/** A study together with the imaging metadata already fetched for it. */
export interface StudyWithImages {
  study: StudySummary;
  images: ImageSummary[];
  clips: CineClipSummary[];
}

/**
 * The patient's completed studies and their thumbnails.
 *
 * The server has already filtered to completed visits owned by this patient. The UI
 * renders what it is given and never infers additional studies — anything it invented
 * here would be showing a patient something the access check never approved.
 */
export function StudyGallery({ studies }: { studies: StudyWithImages[] }) {
  const [open, setOpen] = useState<{
    images: ImageSummary[];
    index: number;
  } | null>(null);
  const [cine, setCine] = useState<{
    clip: CineClipSummary;
    label: string;
  } | null>(null);

  if (studies.length === 0) {
    return (
      <EmptyState>
        Your completed visits will appear here once your clinic has finished uploading them.
      </EmptyState>
    );
  }

  return (
    <>
      {studies.map(({ study, images, clips }) => (
        <Card key={study.id}>
          <CardHead>
            <h3 className="mr-auto text-base">{study.description ?? "Ultrasound study"}</h3>
            <Pill tone="ok">Completed</Pill>
            {/* Formatted with an explicit locale and zone: leaving them to the runtime
                gives one string on the server and another in the browser, which is a
                hydration mismatch (React error #418). */}
            <span className="text-[0.8125rem] text-ink-3">
              {new Date(study.performed_at).toLocaleDateString("en-US", {
                year: "numeric",
                month: "short",
                day: "numeric",
                timeZone: "UTC",
              })}
            </span>
          </CardHead>
          <CardBody>
            {images.length === 0 && clips.length === 0 ? (
              <EmptyState>Images appear here once this visit is complete.</EmptyState>
            ) : (
              /* 7.5rem rather than 9rem: at 375px the wider track fell one pixel short of
                 two columns, so a study of eleven images became a single column and a page
                 five thousand pixels tall. */
              <div className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-3.5">
                {images.map((image, index) => (
                  <Thumb
                    key={image.id}
                    image={image}
                    index={index}
                    onOpen={() => setOpen({ images, index })}
                  />
                ))}
                {clips.map((clip, index) => {
                  const label = `CINE-${String(index + 1).padStart(4, "0")}`;
                  return (
                    <CineTile
                      key={clip.id}
                      clip={clip}
                      label={label}
                      onOpen={() => setCine({ clip, label })}
                    />
                  );
                })}
              </div>
            )}
          </CardBody>
        </Card>
      ))}

      {cine ? (
        <CinePlayer clip={cine.clip} label={cine.label} onClose={() => setCine(null)} />
      ) : null}

      {open ? (
        <ImageViewer images={open.images} startIndex={open.index} onClose={() => setOpen(null)} />
      ) : null}
    </>
  );
}

function Thumb({
  image,
  index,
  onOpen,
}: {
  image: ImageSummary;
  index: number;
  onOpen: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  return (
    <button
      type="button"
      onClick={onOpen}
      className="grid overflow-hidden rounded-md border border-line bg-scan text-left transition hover:-translate-y-0.5 hover:border-brand"
    >
      <div className="relative aspect-[4/3] bg-scan">
        {failed ? (
          <span className="absolute inset-0 grid place-items-center px-2 text-center text-xs text-scan-dim">
            Preview unavailable
          </span>
        ) : (
          <>
            {/* A tile that is simply dark while bytes are in flight is indistinguishable
                from a broken one. The skeleton is what tells a patient on a slow
                connection that something is still coming (edge case #3). */}
            {!loaded ? (
              <span className="absolute inset-0 animate-pulse bg-scan-chrome" aria-hidden />
            ) : null}
            {/* eslint-disable-next-line @next/next/no-img-element -- bytes are proxied
                through a route handler that attaches the auth token; the optimizer
                cannot do that. */}
            <img
              src={`/api/phi/images/${image.id}/thumbnail`}
              alt={`Ultrasound image ${index + 1}`}
              loading="lazy"
              onLoad={() => setLoaded(true)}
              onError={() => setFailed(true)}
              className={`size-full object-cover transition-opacity duration-300 ${
                loaded ? "opacity-100" : "opacity-0"
              }`}
            />
          </>
        )}
      </div>
      <div className="flex items-center justify-between gap-1.5 bg-panel px-2.5 py-2">
        <span className="text-xs font-semibold text-ink-2">
          IMG-{String(index + 1).padStart(4, "0")}
        </span>
        <span className="font-mono text-[0.625rem] text-brand">still</span>
      </div>
    </button>
  );
}

function CineTile({
  clip,
  label,
  onOpen,
}: {
  clip: CineClipSummary;
  label: string;
  onOpen: () => void;
}) {
  // A clip with holes in it says so on the tile rather than only once the player is open,
  // so a patient is not surprised mid-playback by a study that was always incomplete.
  const damaged = clip.available_frame_count < clip.frame_count;

  return (
    <button
      type="button"
      onClick={onOpen}
      className="grid overflow-hidden rounded-md border border-brand bg-scan text-left transition hover:-translate-y-0.5"
    >
      <div className="grid aspect-[4/3] place-items-center bg-scan-chrome">
        <span className="font-mono text-xs text-scan-accent">▶ CINE</span>
      </div>
      <div className="flex items-center justify-between gap-1.5 bg-panel px-2.5 py-2">
        <span className="text-xs font-semibold text-ink-2">{label}</span>
        <span className="font-mono text-[0.625rem] text-brand">
          {damaged ? `${clip.available_frame_count}/${clip.frame_count}` : clip.frame_count} frames
        </span>
      </div>
    </button>
  );
}
