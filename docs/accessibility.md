# Accessibility and responsive behaviour

What was checked, what was found, and how to re-run it.

## Running the checks

```bash
docker compose up -d                                   # not needed; the e2e suite uses the real stack
cd backend && uv run uvicorn app.main:app --port 8000  # terminal 1
cd frontend && npm run dev                             # terminal 2
cd frontend && npm run test:e2e                        # terminal 3
```

The suite lives in `frontend/src/__tests__/e2e/` and runs axe-core through Playwright:

| Spec | Covers |
|---|---|
| `accessibility.spec.ts` | axe on every screen — desktop, 375px, and dark theme — plus labelling of the viewer, cine transport and share dialog |
| `responsive.spec.ts` | horizontal overflow, tap-target size, rail stacking, dialog controls staying on screen at 375px |
| `dialogs.spec.ts` | focus trap, focus restoration, dialog stacking, keyboard shortcut conflicts, reduced motion |

It is deliberately **not** in CI. The seeded imaging assets live in Supabase Storage, so a
meaningful run needs the project's real credentials rather than the throwaway Postgres the
pytest suite uses. Everything CI can check without them already runs there.

## Bar

axe-core with `wcag2a`, `wcag2aa`, `wcag21a` and `wcag21aa`, failing on **serious** and
**critical** impact. Lower-impact findings depend on context axe cannot see and are not
treated as build failures.

## What was found and fixed

**Contrast (WCAG AA, 4.5:1).** Three token values failed and were corrected centrally
rather than patched per component:

| Token | Was | Now | Worst ratio before → after |
|---|---|---|---|
| `--ink-3` (light) | `#718096` | `#5f6c7f` | 3.65 → 4.85 on the page ground |
| `--warn` (light) | `#a35c00` | `#9a5600` | 4.49 → 4.95 on `--warn-bg` |
| `--scan-dim` | `#8272a3` | `#8b7bab` | 4.26 → 4.81 on `--scan-chrome` |

`--ink-3` is the one that mattered most: it is the muted tone used for hints and metadata at
10–12px, so the failure landed on the text that was already hardest to read.

The `scanPrimary` button hardcoded `text-white`, which failed twice — on the light violet
that `--brand` becomes in dark mode, and on the light hover fill in day mode. It now uses
`--brand-ink`, which flips with the surface.

**Keyboard.** Five defects, all confirmed by a failing test before the fix:

1. Escape inside the share dialog closed the image viewer underneath it as well.
2. Arrow keys changed the image behind an open share dialog, so the dialog said "image 1"
   while the viewer showed image 2.
3. Focus escaped the share dialog on Tab.
4. No dialog restored focus to the control that opened it.
5. In the cine player, Space toggled playback instead of activating the focused button,
   which made every control in the transport unusable by keyboard.

All three dialogs now share `useDialog` in `frontend/src/lib/useDialog.ts`, which owns
dismissal, the focus trap, initial focus and focus restoration. Its `active` flag is what
makes stacking work: a dialog with another open on top of it stops listening, so Escape
dismisses one layer at a time.

**Reduced motion.** The cine player autoplayed regardless of `prefers-reduced-motion`. It
now loads the clip but leaves it paused; the transport is unchanged.

**Scrollable region.** The access-log table scrolls inside its own container so the page
never scrolls sideways, but the container was pointer-only. It is now focusable and
labelled as a region.

**Layout.** At 375px the thumbnail grid fell one pixel short of two columns, turning an
eleven-image study into a single column and a page roughly 4,800px tall. The minimum track
is now 7.5rem.

## Keyboard-only walkthrough

Verified with no pointer, in both themes. Each step is covered by a test in the specs above
unless noted.

| Flow | Path |
|---|---|
| Sign in | Tab to Email → Tab to Password → Enter submits |
| Identity gate | Tab to Patient ID → Tab to date of birth → Enter submits |
| Navigate | Tab reaches every rail item; the current one carries `aria-current="page"` and a thicker tick, so the active section is legible without colour |
| Open an image | Tab to a thumbnail → Enter opens the viewer; focus lands on Close |
| Operate the viewer | Tab cycles Zoom out / Zoom in / Reset / Close / Share and never leaves the dialog; ← → change image; Escape closes and returns focus to the thumbnail |
| Share | Enter on Share → focus moves into the share dialog → Tab reaches Send to, the expiry radiogroup and Create link → Escape closes only the share dialog |
| Open a clip | Enter on a cine tile → focus lands on Close; Space toggles playback when no control has focus, and activates the focused control when one does; ← → step a frame; the scrubber is a labelled `range` |
| Reports | Tab reaches each report; status is a pill carrying the word as well as the colour |
| Access log | Tab reaches the table container, which then scrolls with the arrow keys; Allowed and Denied are words, not just hues |

## Status conveyed by more than colour

Every `Pill` renders a dot plus its text label, and no state anywhere is signalled by hue
alone: `Allowed`/`Denied`, `Completed`, `Final`/`Preliminary`, `Active`/`Expired`/`Switched
off`. The rail's active item thickens its tick in addition to changing colour.
