---
name: edl-agent
description: Local studio for automated video montage.
colors:
  surround: "#211a14"
  surround-light: "#f6f0e3"
  panel: "#2d241c"
  panel-light: "#fffdf6"
  panel-raised: "#3b2f23"
  panel-raised-light: "#f2e9d6"
  panel-sunken: "#181209"
  panel-sunken-light: "#e9dcc3"
  rule: "#4e4133"
  rule-light: "#ddcfb6"
  ink: "#f6ecdc"
  ink-light: "#2b2118"
  ink-dim: "#c9b6a0"
  ink-dim-light: "#6f6050"
  signal: "#61d7b6"
  signal-light: "#0b7a68"
  signal-dim: "#23473d"
  signal-dim-light: "#cde9dd"
  fail: "#ef7d6c"
  fail-light: "#b23029"
  fail-dim: "#59221d"
  fail-dim-light: "#f3c9c3"
  clay: "#e2a458"
  clay-light: "#a86a1e"
typography:
  display:
    fontFamily: "Fraunces Variable, Georgia, serif"
    fontSize: "2rem"
    fontWeight: 560
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Fraunces Variable, Georgia, serif"
    fontSize: "1.375rem"
    fontWeight: 560
    letterSpacing: "-0.01em"
  title:
    fontFamily: "DM Sans Variable, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    letterSpacing: "0em"
  body:
    fontFamily: "DM Sans Variable, system-ui, sans-serif"
    fontSize: "1rem"
    lineHeight: 1.55
  label:
    fontFamily: "DM Sans Variable, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.5
  mono:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
    fontSize: "0.875rem"
rounded:
  sm: "8px"
  base: "12px"
  lg: "16px"
  pill: "999px"
elevation:
  card: "0 1px 2px rgb(18 11 5 / 0.45), 0 10px 28px rgb(18 11 5 / 0.35)"
  pop: "0 20px 56px rgb(18 11 5 / 0.55)"
components:
  button:
    backgroundColor: "{colors.panel-raised}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0.5rem 1rem"
  button-primary:
    backgroundColor: "{colors.signal-dim}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "0.5rem 1rem"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "0.5rem 0.75rem"
---

# Design System: edl-agent

## Overview

**Creative North Star: "The Warm Studio"**

This is a craft room with the lights left warm, not a console in a dark
booth. Every screen still shows its working state — stage progress,
candidate frames, render checks, regenerate history — but the chrome
around it feels made by hand: paper and espresso panels, soft serif
headings, pill steps, cards that lift off the bench with warm shadows.
Footage and music lead; the room holds them like a light-table holds
stills.

The voice is welcoming but exact. Prose, headings, and labels set in a
friendly sans under a soft serif display; machine data — timecode, frame
counts, EDL/JSON, costs — stays in mono with tabular numerals, never
prose type. Boldness is spent in three places: the contact sheet, the
stage rail, and the reel payoff card.

**Key Characteristics:**
- Studio warmth: espresso/paper chrome, clay accents, soft shadows.
- Footage first: neutral black wells keep thumbnails color-true.
- Serif display + sans body, mono reserved for machine data.
- Crafted depth: tonal steps plus warm shadows, hairline rules.
- Status hues with fixed jobs: jade signal for go/progress, brick fail
  for error, clay only for brand and decoration.

## Colors

A warm neutral stack with one go hue, one error hue, and one decorative
amber, in dark (default) and light themes.

### Primary
- **Signal** (#61d7b6; light #0b7a68): links, running status, progress
  bars, focus rings, the active wizard step, the stage rail's running
  wash. The only hue that means "go".
- **Signal dim** (#23473d; light #cde9dd): primary-button fill, wizard-step
  active fill, picked-card fill. Carries the accent at rest so Signal
  itself stays rare.

### Secondary
- **Fail** (#ef7d6c; light #b23029): failed status, error accents,
  destructive fills. The only hue that means "broken".
- **Fail dim** (#59221d; light #f3c9c3): filled destructive buttons and
  failed-row washes; never a third status.

### Decorative
- **Clay** (#e2a458; light #a86a1e): brand dot, never status. The warm
  accent that makes the room feel crafted; it must never mark progress,
  success, or error.

### Neutral
- **Surround** (#211a14; light #f6f0e3): app background, warmed espresso
  (dark) or paper (light), with a faint radial glow in the body.
- **Panel** (#2d241c; light #fffdf6): cards, inputs, notices, modal
  surface, wizard steps.
- **Panel raised** (#3b2f23; light #f2e9d6): default button fill, one step
  up from Panel.
- **Panel sunken** (#181209; light #e9dcc3): code blocks, waveform bands,
  media placeholders — recessed, never raised.
- **Rule** (#4e4133; light #ddcfb6): every border, divider, and hairline.
- **Ink** (#f6ecdc; light #2b2118): body text, warm cream in dark mode.
- **Ink dim** (#c9b6a0; light #6f6050): labels, captions, secondary detail,
  idle status.

### Named Rules
**The Status-Hue Rule.** Only Signal jade and Fail brick carry status
meaning. Clay is decoration and brand; saturation anywhere else is a bug.
**The True-Well Rule.** Video and thumbnails always sit on neutral black
(`#000`), never on a tinted chrome, so footage color judges true.

## Typography

**Display Font:** Fraunces Variable (with Georgia, serif)
**Body Font:** DM Sans Variable (with system-ui, sans-serif)
**Mono Font:** IBM Plex Mono (with ui-monospace, monospace)
**Brand Font:** Martian Mono Variable (wordmark only)

**Character:** Soft serif headings over a friendly sans body — the room
talks like a person. Mono appears only where the content is machine data:
timecode, counts, EDL/JSON, costs, badges, checks. Utilitarian where it
counts, warm everywhere else.

### Hierarchy
- **Display** (560, 2rem/32px, -0.01em tracking): page titles (`h2`) and
  modal headers, in the serif face.
- **Headline** (560, 1.375rem/22px): section headings, serif.
- **Title** (600, 1rem/16px, sans): sub-headings and card titles.
- **Body** (400–500, 1rem/16px, 1.55 line-height): form fields, table
  cells, paragraphs capped at 72ch (`--measure`).
- **Label** (500–700, 0.875rem/14px): field labels, buttons, uppercase
  micro-headers (0.75rem/12px, 0.06–0.08em tracking) for library sections,
  review terms, and timeline roles.
- **Mono** (400, 0.875rem/14px, tabular numerals): `pre`, `code`,
  stage details, cost badges, track times, timeline positions,
  dashboard/library summaries, coverage meters, render-check output.

### Named Rules
**The Mono-Reservation Rule.** Prose never sets in mono; data never sets
in prose type. If it came from a machine (timecode, count, hash, dollar
figure), it is IBM Plex Mono.
**The Tabular Numerals Rule.** Anywhere numbers compare — table cells,
counts, cost badges — use tabular figures so columns hold still.

## Layout

A full-width flex column shell: a warm header (brand wordmark left,
actions right) over a body padded 1.5rem and capped at 1600px. Content
flows in relaxed vertical rhythm on a 0.25/0.5/0.75/1/1.5/2rem spacing
scale, with forms paired two-per-row through an auto-fitting grid (min
260px per column) while fieldsets, details, and actions span the full
width. The `/new` form sits in its own card beside a sticky summary rail.

Media lays out in light-tables — contact sheets as matted cards (190px
cells, 110px compact) on a recessed bed — and results sit side by side:
video beside checks beside the regenerate form, with portrait reels
capped at 60–65vh so controls never fall below the fold. Below 640px
everything collapses to a single column, the wizard steps stack, and the
result un-flexes to a plain block.

## Elevation & Depth

Crafted, not flat: cards lift on warm shadows over tonal steps, with
1px hairlines keeping edges crisp. Overlay dims are warm-tinted
(`rgb(24 14 6 / 0.6)`) behind modals and over reel-preview placeholders.

### Named Rules
**The Lift Rule.** Cards, rails, tables, notices, and modals rest on
`--shadow-card`; dialogs and popovers rise to `--shadow-pop`. Depth is
never decoration alone — it groups what belongs together.
**The Sunken-Data Rule.** Code blocks, waveforms, and placeholders recess
into Panel-sunken; they never cast shadows.

## Shapes

Friendly crafted geometry: 8px on inputs and buttons, 12px on cards and
rails, 16px on large panels and modals, pills for steps, chips, badges,
and the dashboard stat strip. Emphasis bars run thicker, never rounder:
the 4px Signal/Fail status mark in the stage rail and the 4px accent edge
on warning notices. Video always sits on a pure black field (`#000`).

### Named Rules
**The Radius-Scale Rule.** 8 → 12 → 16 by surface size; pills only for
steps, chips, badges, and stat strips. Nothing goes fully square except
text buttons and dividers.

## Components

### Buttons
- **Shape:** 8px radius, 0.5rem vertical by 1rem horizontal padding,
  600-weight sans label, soft shadow, lifts 1px on hover.
- **Primary:** Signal-dim fill with a Signal border — the one go button,
  reserved for the session's forward action.
- **Hover / Focus:** border shifts to Signal-border on hover; every
  interactive element takes a 2px Signal outline offset 2px on
  focus-visible; disabled buttons fade to half opacity.
- **Secondary:** Raised-panel fill with a Rule border for all other
  actions; a borderless underlined text-button variant exists for inline
  links; `danger` fills Fail-dim with a Fail border.

### Stage Rail (signature)
- **Style:** a crafted card (16px radius, shadow) where each row pairs a
  semibold capitalized step name (8rem column) with a 4px pill status
  mark, mono detail text, and an optional Signal progress bar.
- **State:** the running row rests on a Signal wash with a Signal mark; a
  failed row rests on a Fail wash with a Fail mark; idle rows rest plain.
  The boldest chrome in the system alongside the contact sheet and reel.
- **Never shrinks** (`flex-shrink: 0`): as a clipped flex item in a column
  shell its automatic minimum size is zero, so page overflow would
  otherwise crush it and clip its rows.

### Contact Sheet (signature)
- **Style:** a matted light-table bed holding framed thumbnail cards
  (190px cells, 110px compact) with 8px media corners on black and small
  sans captions with mono duration badges.
- **State:** selection and status live in the caption text and the footage
  itself, plus a 2px Signal outline on tile hover; chrome never outshines
  the stills.

### Inputs / Fields
- **Style:** Panel fill, 1px Rule stroke, 8px radius, full width,
  sans body text; semibold small labels sit above each field and related
  fields group in bordered fieldsets with dim legends.
- **Focus:** 2px Signal outline, same as buttons; hover warms the border.
- **Error / Disabled:** errors surface as Fail-hued notices beside the
  form, not as restyled fields; no bespoke disabled field treatment
  exists.

### Navigation
- **Style:** a warm header (mono lowercase wordmark with a clay dot left,
  actions right) plus a per-page wizard strip: a pill card of equal step
  buttons, dim sans labels, current step filled Signal-dim with a Signal
  border.
- **States:** steps warm to Raised on hover and render in full ink when
  done; the current step alone holds the Signal-dim fill.

### Notices
- **Style:** Panel card with 12px radius, soft shadow, Rule border, and a
  4px Signal left edge for pauses and warnings; titles set in serif.
- **Error variant:** the edge turns Fail (`.is-error`); the pattern is
  otherwise identical.

### Modal
- **Style:** Panel surface, 16px radius, Rule border, padding 1.5rem,
  width capped at the smaller of 900px and 90vw (media previews shrink to
  fit content up to 92vw), scrolled internally past 85vh, over the warm
  overlay dim, lifted on `--shadow-pop`.

### Tables
- **Style:** sessions and ledgers sit in 16px cards (scroll wrapper carries
  the border and shadow); small 0.875rem sans rows on soft hairlines, dim
  uppercase micro-headers, row hover warms faintly.
- **Numerals:** numeric columns right-align in mono tabular figures; cost
  badges are pill chips in mono.

### Form Steps
- **Style:** a pill card strip of equal step buttons, sans semibold
  labels, no dividers — spacing does the separating.
- **States:** the current step alone holds the Signal-dim fill
  (`aria-current="step"`); done steps render in full ink; hover warms the
  label. Below 640px the strip stacks vertically with left-aligned
  labels.
- **Never shrinks** (`flex-shrink: 0`), same trap as the stage rail.

### Render Checks
- **Style:** a card with a semibold summary; grouped `pre` outputs recess
  into Panel-sunken at 0.75rem mono, capped at 240px with internal
  scroll; group titles are uppercase micro-headers.
- **Rule:** checks are never removed or hidden behind decoration — the
  card stays on-screen beside the reel.

## Do's and Don'ts

### Do:
- **Do** keep video wells neutral black so footage reads true.
- **Do** spend boldness only on the contact sheet, the stage rail, and
  the reel card.
- **Do** set machine data in mono tabular figures and prose in sans.
- **Do** give every interactive element the 2px Signal focus-visible ring
  (2px offset).
- **Do** cap portrait video at 60–65vh so its controls stay above the
  fold.
- **Do** honor `prefers-reduced-motion` — transitions collapse to near-zero.

### Don't:
- **Don't** use Clay for status — it is brand and decoration only.
- **Don't** set prose in mono or data in the sans/serif faces.
- **Don't** hide errors, costs, or checks behind decoration or collapsed
  chrome that obscures state.
- **Don't** tint the surround so far it judges footage color — wells stay
  black, beds stay near-neutral.
- **Don't** invent radii beyond the 8/12/16/pill scale.
