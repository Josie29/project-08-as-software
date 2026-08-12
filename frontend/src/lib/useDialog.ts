"use client";

import { useEffect, useRef, useSyncExternalStore, type RefObject } from "react";

const FOCUSABLE =
  "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])";

/**
 * Shared modal behaviour: dismiss, focus trap, and focus restoration.
 *
 * Every dialog in the portal needs the same three things, and getting any of them slightly
 * different is how a keyboard user ends up interacting with a page they cannot see. The
 * `active` flag is what makes stacking work: a dialog with another one open on top of it
 * stops listening, so Escape dismisses only the top layer instead of the whole stack.
 *
 * Initial focus is moved here rather than by the caller so it happens after the opener has
 * been recorded. A component that focused its own close button first would overwrite the
 * very element restoration needs to return to.
 *
 * @param ref - The dialog element.
 * @param onClose - Called when the dialog should dismiss.
 * @param active - False while another dialog is layered above this one.
 * @param initialFocus - Control to focus on open; defaults to the first focusable one.
 */
export function useDialog(
  ref: RefObject<HTMLElement | null>,
  onClose: () => void,
  active = true,
  initialFocus?: RefObject<HTMLElement | null>,
): void {
  // Captured before the dialog steals focus, restored when it unmounts. Without this a
  // keyboard user is dropped at the top of the document and has to tab back to where they
  // were.
  const opener = useRef<HTMLElement | null>(null);
  useEffect(() => {
    opener.current = document.activeElement as HTMLElement | null;
    const target = initialFocus?.current ?? ref.current?.querySelector<HTMLElement>(FOCUSABLE);
    target?.focus();
    return () => opener.current?.focus?.();
    // Runs once: re-running would yank focus back to the top of the dialog mid-interaction.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!active) return;

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab" || !ref.current) return;

      const focusable = [...ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (focusable.length === 0) return;
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;

      // Tab from outside the dialog lands back inside it. This is the case that matters
      // when a dialog opens on top of another: focus may still be in the layer below.
      if (!ref.current.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
        return;
      }
      if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      }
    }

    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [ref, onClose, active]);
}

/**
 * Whether the keystroke came from a control that handles it itself.
 *
 * A dialog-wide Space or arrow shortcut that fires regardless of focus makes every button
 * and slider inside it unusable by keyboard — Space activates the shortcut instead of the
 * focused button.
 *
 * @param event - The keyboard event.
 * @returns True if the shortcut should stand down.
 */
export function isFromFormControl(event: KeyboardEvent): boolean {
  const target = event.target as HTMLElement | null;
  return !!target?.closest("button, input, select, textarea, a[href]");
}

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/**
 * Whether the visitor has asked for reduced motion.
 *
 * Read through `useSyncExternalStore` so the server renders the safe default and the
 * client's real preference is a legitimate difference rather than a hydration mismatch.
 *
 * @returns True if motion should be avoided.
 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia(REDUCED_MOTION);
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => window.matchMedia(REDUCED_MOTION).matches,
    () => false,
  );
}
