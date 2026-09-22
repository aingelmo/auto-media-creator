---
name: edl-agent
description: Local console for automated video montage.
colors:
  surround: "#1c1c1c"
  surround-light: "#f4f2ee"
  panel: "#262626"
  panel-light: "#ffffff"
  panel-raised: "#2d2d2d"
  panel-raised-light: "#ececea"
  rule: "#363636"
  rule-light: "#d8d5cf"
  ink: "#e6e3dd"
  ink-light: "#1c1c1c"
  ink-dim: "#8f8b84"
  ink-dim-light: "#6b665c"
  signal: "#35c2c8"
  signal-light: "#0f8a90"
  signal-dim: "#1f7276"
  signal-dim-light: "#cfeceb"
  fail: "#d0413b"
  fail-light: "#b23029"
  fail-dim: "#7a2a27"
  fail-dim-light: "#f6dcda"
typography:
  display:
    fontFamily: "Martian Mono Variable, ui-monospace, monospace"
    fontSize: "1.75rem"
    fontWeight: 500
    letterSpacing: "0.01em"
  headline:
    fontFamily: "Martian Mono Variable, ui-monospace, monospace"
    fontSize: "1.3125rem"
    fontWeight: 500
    letterSpacing: "0.01em"
  title:
    fontFamily: "Martian Mono Variable, ui-monospace, monospace"
    fontSize: "1rem"
    fontWeight: 500
    letterSpacing: "0.01em"
  body:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "1rem"
    lineHeight: 1.5
  label:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "0.875rem"
    lineHeight: 1.5
rounded:
  base: "4px"
spacing:
  space-1: "0.25rem"
  space-2: "0.5rem"
  space-3: "0.75rem"
  space-4: "1rem"
  space-6: "1.5rem"
  space-8: "2rem"
components:
  button:
    backgroundColor: "{colors.panel-raised}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.base}"
    padding: "0.5rem 1rem"
  button-primary:
    backgroundColor: "{colors.signal-dim}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.base}"
    padding: "0.5rem 1rem"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.base}"
    padding: "0.5rem 0.75rem"
---

# Design System: edl-agent

## Overview

**Creative North Star: "The Cutting Bench"**

This is an instrument, not a brochure. Every screen is a dense console of
tables, rails, checks, and contact sheets, and everything inspectable stays
visible: stage progress, candidate frames, render checks, regenerate history.
The room stays dark and quiet so the footage stays bright — chrome recedes
into neutral panels and hairline rules while video, thumbnails, and status
hues do the talking.

The voice is technical and exact. Content genuinely is timecode, frame counts,
and JSON, so the interface sets it in monospace without apology and reaches
for tabular numerals wherever numbers compare. Boldness is spent in exactly
two places, the contact sheet and the stage rail; everywhere else the system
holds back.

**Key Characteristics:**
- Console density: rails, tables, and checks over hero space.
- Footage first: neutral surround keeps thumbnails color-true.
- Monospace throughout: display and body are both mono faces.
- Flat and restrained: tonal steps and 1px rules, never shadows.
- Two hues only: signal teal for go/progress, brick fail for error.

## Colors

One working accent plus one error hue on an untinted neutral stack, in dark
(default) and light themes.

### Primary
- **Signal** (#35c2c8; light #0f8a90): links, running status, progress bars,
  focus rings, the active wizard step, the stage rail's running mark. The only
  hue that means "go".
- **Signal dim** (#1f7276; light #cfeceb): primary-button fill, wizard-step
  active fill, button hover border. Carries the accent at rest so Signal itself
  stays rare.

### Secondary
- **Fail** (#d0413b; light #b23029): failed status, error accents. The only
  hue that means "broken".
- **Fail dim** (#7a2a27; light #f6dcda): reserved fills behind the fail hue;
  never a third accent.

### Neutral
- **Surround** (#1c1c1c; light #f4f2ee): app background. Deliberately
  untinted so video and thumbnails read true.
- **Panel** (#262626; light #ffffff): inputs, code blocks, notices, modal
  surface, wizard steps at rest.
- **Panel raised** (#2d2d2d; light #ececea): default button fill, one step up
  from Panel.
- **Rule** (#363636; light #d8d5cf): every border, divider, and hairline.
- **Ink** (#e6e3dd; light #1c1c1c): body text, warm off-white in dark mode.
- **Ink dim** (#8f8b84; light #6b665c): labels, captions, secondary detail,
  idle status.

### Named Rules
**The Two-Hue Rule.** Only Signal teal and Fail brick carry hue. Everything
else is neutral gray or warm paper; saturation anywhere else is a bug.
**The True-Surround Rule.** The app background stays untinted in both themes
so footage color is judged against gray, never against a tinted chrome.

## Typography

**Display Font:** Martian Mono Variable (with ui-monospace, monospace)
**Body Font:** IBM Plex Mono (with ui-monospace, monospace)

**Character:** Both faces are monospace — display for headings and the stage
rail's step names, body for everything else — because the content is
timecode, counts, and JSON rather than prose. Utilitarian, exact, unhurried.

### Hierarchy
- **Display** (500, 1.75rem/28px, 0.01em tracking): page titles (`h1`) and the
  modal close glyph scale.
- **Headline** (500, 1.3125rem/21px, 0.01em tracking): section headings
  (`h2`).
- **Title** (500, 1rem/16px, dim ink): sub-headings (`h3`), always in Ink dim.
- **Body** (400, 1rem/16px, 1.5 line-height): form fields, table cells,
  paragraphs capped at 72ch (`--measure`).
- **Label** (400, 0.875rem/14px): field labels (dim), buttons, table headers,
  captions; 0.75rem/12px for fine meta such as history cells and check output.

### Named Rules
**The Monospace Rule.** No proportional face enters the system; numbers,
labels, and headings all set in mono.
**The Tabular Numerals Rule.** Anywhere numbers compare — table cells, counts,
cost badges — use tabular figures so columns hold still.

## Layout

A full-width flex column shell: a baseline-split header (title left, actions
right) over a body padded 1.5rem and capped at 1600px. Content flows in repaid
vertical rhythm on a 0.25/0.5/0.75/1/1.5/2rem spacing scale, with forms paired
two-per-row through an auto-fitting grid (min 260px per column) while
fieldsets, details, and actions span the full width.

Media lays out in contact sheets — auto-filling grids at 190px cells (110px
compact) — and results sit side by side: video beside checks beside the
regenerate form, with portrait reels capped at 60vh so controls never fall
below the fold. Below 640px everything collapses to a single column, the
wizard steps stack, and the result un-flexes to a plain block.

## Elevation & Depth

Flat by default, dimmed only for overlays. No `box-shadow` exists anywhere in
the system; depth is conveyed by tonal steps (Surround to Panel to Raised)
and 1px Rule hairlines, with the single exception of full-surface dims —
`rgb(0 0 0 / 0.6)` behind modals and over reel-preview placeholders.

### Named Rules
**The Flat-By-Default Rule.** Surfaces are flat at rest. The only permitted
depth cue is the overlay dim, and it appears solely as a response to state
(modal open, preview pending).

## Shapes

Gently squared utility geometry: a single 4px corner radius on every
surfaced element — buttons, inputs, fieldsets, code blocks, rails, notices,
video frames — over 1px solid Rule borders. Emphasis bars run thicker, never
rounder: the 3px Signal/Fail status mark in the stage rail and the 3px accent
edge on warning notices. Video always sits on a pure black field (`#000`).

### Named Rules
**The 4px Rule.** One radius everywhere; nothing rounds further and nothing
goes fully square except text buttons and dividers.

## Components

### Buttons
- **Shape:** gently squared (4px radius), 0.5rem vertical by 1rem horizontal
  padding, 0.875rem mono label.
- **Primary:** Signal-dim fill with a Signal border — the one filled button,
  reserved for the session's forward action.
- **Hover / Focus:** border shifts to Signal-dim on hover; every interactive
  element takes a 2px Signal outline offset 2px on focus-visible; disabled
  buttons fade to half opacity.
- **Secondary:** Raised-panel fill with a Rule border for all other actions;
  a borderless underlined text-button variant exists for inline links.

### Stage Rail (signature)
- **Style:** a bordered 4px list where each row pairs a mono step name
  (8rem column) with a 3px status mark, dim detail text, and an optional
  Signal progress bar.
- **State:** the running row's mark turns Signal, a failed row's mark turns
  Fail; idle rows rest on Rule gray. The single boldest chrome in the system
  alongside the contact sheet.

### Contact Sheet (signature)
- **Style:** auto-filling thumbnail grid (190px cells, 110px compact) with
  4px media corners on black and small mono captions.
- **State:** neutral container throughout; selection and status live in the
  caption text and the footage itself, never in decorative chrome.

### Inputs / Fields
- **Style:** Panel fill, 1px Rule stroke, 4px radius, full width, body-size
  mono text; dim small labels sit above each field and related fields group
  in bordered fieldsets with dim legends.
- **Focus:** 2px Signal outline, same as buttons.
- **Error / Disabled:** errors surface as Fail-hued notices beside the form,
  not as restyled fields; no bespoke disabled field treatment exists.

### Navigation
- **Style:** a lean header (title link left, actions right) plus a per-page
  wizard strip: a bordered 4px row of equal step buttons in Panel, dim mono
  labels, current step filled Signal-dim.
- **States:** steps brighten to full ink on hover and when done; the current
  step alone holds the Signal-dim fill.

### Notices
- **Style:** Panel fill with a 4px radius, Rule border, and a 3px Signal left
  edge for pauses and warnings.
- **Error variant:** the edge turns Fail (`.is-error`); the pattern is
  otherwise identical.

### Modal
- **Style:** Panel surface, Rule border, padding 1.5rem, width capped at the
  smaller of 900px and 90vw (media previews shrink to fit content up to
  92vw), scrolled internally past 85vh, over the standard overlay dim.
- **Close:** a borderless dim glyph pinned top-right of the scroll frame.

### Tables
- **Style:** small 0.875rem mono rows on hairline Rule dividers, dim
  sentence-case headers, no outer box.
- **Numerals:** numeric columns right-align in tabular figures.

### Form Steps
- **Style:** a bordered 4px strip of equal step buttons in Panel, dim mono
  labels set in the Display face, Rule dividers between steps.
- **States:** the current step alone holds the Signal-dim fill
  (`aria-current="step"`); done steps render in full ink; hover brightens
  the label. Below 640px the strip stacks vertically with left-aligned
  labels.

### Render Checks
- **Style:** a collapsed `details` block with a dim small summary; grouped
  `pre` outputs in Panel with a Rule border at 0.75rem mono, capped at
  240px with internal scroll.
- **Headings:** group titles at 0.75rem in the Title voice.

## Do's and Don'ts

### Do:
- **Do** keep the surround neutral so footage and thumbnails read true.
- **Do** spend boldness only on the contact sheet and the stage rail.
- **Do** give every interactive element the 2px Signal focus-visible ring
  (2px offset).
- **Do** right-align numeric columns and set them in tabular figures.
- **Do** cap portrait video at 60vh so its controls stay above the fold.
- **Do** honor `prefers-reduced-motion` — transitions collapse to near-zero.

### Don't:
- **Don't** introduce a hue beyond Signal teal and Fail brick.
- **Don't** round beyond (or below) the 4px radius.
- **Don't** shadow a surface; step the tone or draw a rule instead.
- **Don't** decorate around footage — captions and status text carry meaning,
  chrome does not.
- **Don't** set anything in a proportional font; the system is mono throughout.
