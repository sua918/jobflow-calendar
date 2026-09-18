---
version: alpha
name: JobFlow Calendar First
description: Restrained Korean productivity UI in which the selected-month calendar is the primary workspace.
colors:
  primary: "#2563EB"
  primaryHover: "#1D4ED8"
  primarySoft: "#EFF6FF"
  canvas: "#F7F8FA"
  surface: "#FFFFFF"
  surfaceSubtle: "#FAFAFA"
  text: "#18181B"
  textMuted: "#52525B"
  border: "#D4D4D8"
  borderStrong: "#71717A"
  focus: "#1D4ED8"
  disabled: "#F4F4F5"
  disabledText: "#52525B"
  warning: "#92400E"
  warningSoft: "#FFFBEB"
  today: "#1E3A8A"
  todaySoft: "#DBEAFE"
  outsideMonth: "#71717A"
  loading: "#E4E4E7"
  danger: "#B42318"
  dangerSoft: "#FEF3F2"
  deadline: "#2563EB"
  deadlineSoft: "#EFF6FF"
  routine: "#047857"
  routineSoft: "#ECFDF5"
  fixed: "#A16207"
  fixedSoft: "#FFFBEB"
typography:
  display:
    fontFamily: 'Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 24px
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  heading:
    fontFamily: 'Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 18px
    fontWeight: 700
    lineHeight: 1.4
    letterSpacing: "-0.01em"
  title:
    fontFamily: 'Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 16px
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "-0.01em"
  body:
    fontFamily: 'Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 14px
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "-0.005em"
  label:
    fontFamily: 'Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 13px
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "-0.005em"
  meta:
    fontFamily: 'Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "0em"
spacing:
  xxs: 4px
  xs: 8px
  sm: 12px
  md: 16px
  lg: 24px
  xl: 32px
  xxl: 48px
rounded:
  sm: 6px
  md: 8px
  lg: 12px
  pill: 999px
components:
  app-canvas:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
  topbar-desktop:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    height: 64px
    padding: 16px
  topbar-mobile:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    height: 104px
    padding: 0px
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#FFFFFF"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: 12px
    height: 40px
  button-primary-hover:
    backgroundColor: "{colors.primaryHover}"
    textColor: "#FFFFFF"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: 12px
    height: 40px
  button-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    padding: 12px
    height: 40px
  calendar:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.lg}"
    padding: 0px
  calendar-event-deadline:
    backgroundColor: "{colors.deadlineSoft}"
    textColor: "{colors.text}"
    typography: "{typography.meta}"
    rounded: "{rounded.sm}"
    padding: 6px
  calendar-event-routine:
    backgroundColor: "{colors.routineSoft}"
    textColor: "{colors.text}"
    typography: "{typography.meta}"
    rounded: "{rounded.sm}"
    padding: 6px
  calendar-event-fixed:
    backgroundColor: "{colors.fixedSoft}"
    textColor: "{colors.text}"
    typography: "{typography.meta}"
    rounded: "{rounded.sm}"
    padding: 6px
  status-error:
    backgroundColor: "{colors.dangerSoft}"
    textColor: "{colors.danger}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 12px
  interaction-soft:
    backgroundColor: "{colors.primarySoft}"
  surface-subtle:
    backgroundColor: "{colors.surfaceSubtle}"
  text-muted:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.textMuted}"
  border-default:
    backgroundColor: "{colors.border}"
  border-strong:
    backgroundColor: "{colors.borderStrong}"
  focus-ring:
    backgroundColor: "{colors.focus}"
  deadline-marker:
    backgroundColor: "{colors.deadline}"
  routine-marker:
    backgroundColor: "{colors.routine}"
  fixed-marker:
    backgroundColor: "{colors.fixed}"
  button-disabled:
    backgroundColor: "{colors.disabled}"
    textColor: "{colors.disabledText}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    height: 40px
  status-warning:
    backgroundColor: "{colors.warningSoft}"
    textColor: "{colors.warning}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 12px
  calendar-today:
    backgroundColor: "{colors.todaySoft}"
    textColor: "{colors.today}"
  calendar-outside-month:
    backgroundColor: "{colors.surfaceSubtle}"
    textColor: "{colors.outsideMonth}"
  loading-placeholder:
    backgroundColor: "{colors.loading}"
---

## Overview

JobFlow is a calendar workspace, not a form dashboard. The selected month is visible immediately, occupies the dominant surface, and remains in place while a compact right-side composition panel handles `요청 입력 → 일정 확인 → 캘린더`. The visual reference is restrained Cal.com/Notion-style productivity software: neutral surfaces, dense-but-readable controls, and one calm blue interaction accent. Do not use gradients, purple AI styling, oversized hero cards, or repeated status boxes.

The root font stack is local-first and must be applied to `.gradio-container` and all form controls:

`Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`

Pretendard is preferred when installed; core usability must not depend on a remote font request. The browser may resolve to a system Korean sans fallback without layout failure.

## Colors

- Canvas is `#F7F8FA`; primary surfaces are white; structural lines use `#D4D4D8`.
- `border` (`#D4D4D8`) is decorative only: use it for separators, the calendar shell, and non-interactive table rules where a visible component boundary is not required. `borderStrong` (`#71717A`) is the interactive/component-boundary token and is required for unfilled inputs, secondary buttons, checkboxes/radios, and other controls whose shape is otherwise not identifiable. On its permitted adjacent surfaces (`surface`, `surfaceSubtle`, and `canvas`) it meets at least 3:1. Do not place `borderStrong` on a semantic soft surface without rechecking contrast.
- Main text is charcoal `#18181B`; secondary text is `#52525B`. Never use low-opacity gray for essential text.
- `#2563EB` is the only general interaction accent. Reserve it for the primary action, selected/focus states, links, and today/selection emphasis.
- Schedule category color is semantic and subdued. Deadline, routine, and fixed events use pale surfaces plus a 3 px left border, visible icon, and Korean category text. Never use a large saturated fill and never encode category by color alone.
- Error and unplaced states use `#B42318` text or border on `#FEF3F2`, always with an icon/label and deterministic message.
- Warning/partial states use `#92400E` on `#FFFBEB`; today uses `#1E3A8A` on `#DBEAFE`; outside-month text uses `#71717A` on the subtle surface; disabled controls use `#52525B` on `#F4F4F5`; loading placeholders use solid `#E4E4E7` without a gradient.
- Text/background pairs must meet WCAG 2.1 AA: 4.5:1 for normal text and 3:1 for large text. The `focus` token must meet 3:1 against every surface on which it is normatively used. Required control boundaries use `borderStrong` and must meet 3:1 against their adjacent `surface`, `surfaceSubtle`, or `canvas`; low-contrast `border` lines are decorative and must never be the sole visual boundary of a control or state.

## Typography

- Product identity: 18 px/700 on desktop, 16 px/700 on mobile. It is not a marketing H1.
- Selected month: 24 px/700 desktop, 20 px/700 mobile.
- Panel/section heading: 18 px/700.
- Calendar date and event title: 13 px/600 and 12 px/600 respectively.
- Body/control copy: 14 px/400; labels 13 px/600; metadata 12 px/400.
- Use tabular numbers for dates, times, month values, and minute totals.
- Korean labels wrap only in the side panel. Top-bar labels and event titles truncate to one line with the full accessible name preserved.

## Layout

Use an 8 px primary rhythm with 4 px only for tight icon/text relationships. Standard gaps are 8, 12, 16, 24, 32, and 48 px.

At 1440×1000:

- viewport gutters: 24 px; workspace maximum: 1600 px; calendar expands full-width within those gutters;
- top bar: 64 px high;
- gap below top bar: 16 px;
- calendar workspace: at least 824 px high and at least 70% of visible workspace area;
- calendar toolbar: 56 px; weekday row: 36 px; six-row month cells: at least 112 px high; five-row months grow to use available height;
- closed right panel consumes no layout width; open panel is 440 px wide and overlays the calendar without a scrim and without shrinking it. The desktop calendar remains available to pointer and keyboard users.

At 390×844:

- viewport gutters: 12 px; the top bar outer box is exactly 104 px high, overriding the 64 px desktop `topbar-desktop` token with `topbar-mobile`;
- within that 104 px box, product identity, selected month, and primary action occupy a 48 px first row; previous/current/next controls and the visible month title occupy a 48 px second row; the rows have an 8 px gap and no additional vertical padding;
- a 12 px gap follows the top bar, so the calendar/agenda starts at y = 116 px and uses the remaining viewport;
- month grid becomes a chronological selected-month agenda below 700 px; event-free dates and adjacent-month dates are omitted;
- open composition panel is a full-viewport sheet (`position: fixed; inset: 0; width: 100dvw; max-width: none; height: 100dvh`) throughout the `max-width: 700px` breakpoint, with its own vertical scroll; underlying calendar scroll is locked. At the 390 px acceptance viewport its measured width is 390±2 px; at 391–700 px it continues to equal the viewport width rather than remaining capped at 390 px.

The document itself must never scroll horizontally. Data tables may scroll inside their own panel region, but the default calendar/result surface must not.

## Elevation & Depth

Use borders before shadows. The top bar has a 1 px decorative `border` bottom edge. The calendar has one 1 px decorative `border` and no card-within-card treatment. Interactive controls that need a visible boundary use `borderStrong`. The open side panel may use `-8px 0 24px rgba(24, 24, 27, 0.10)`; no other large shadow is allowed. Event chips and collapsed disclosures have no shadow.

## Shapes

- Buttons, inputs, and disclosures: 8 px radius.
- Calendar shell: 12 px radius; day cells have no individual radius.
- Event chips: 6 px radius with a 3 px semantic left border.
- Status badge only: 999 px pill.
- Borders are 1 px. Decorative separators use `border`; control boundaries use `borderStrong`. Do not surround every section with a card border.

Exact component states: secondary hover uses `surfaceSubtle`; selected uses `primarySoft` plus a blue structural marker; today, outside-month, disabled, warning, error, and loading use the named token pairs above. Focus-visible always uses `focus`. Disabled and outside-month content remains readable and is additionally communicated by native state or structure.

Native checkbox and radio controls are exactly 18×18 px, with `min-width`, `max-width`, `min-height`, and `max-height` all 18 px and `aspect-ratio: 1 / 1`. The 44 px touch target belongs to the wrapping label, not the native input.

Never use global selectors such as `input { min-height: 44px; }` or `button, input, textarea { ... }`. Scope form CSS through owned component IDs/classes. The allowed control selector is:

`.jf-app :where(.jf-checkbox, .jf-radio) input:is([type="checkbox"], [type="radio"])`

A Gradio-specific fallback may additionally target `[data-testid="checkbox"] input[type="checkbox"]` only inside `.jf-app`. Textbox, file, hidden, and dataframe inputs must not inherit checkbox geometry.

## Components

### Top bar

One compact `header` contains, in focus/DOM order: JobFlow identity; previous month; current month; next month; read-only selected `YYYY-MM`; and one primary `일정 만들기` action. “Today” uses the visible label `이번 달`. Do not render a hero, introductory paragraph, context card, summary card, or statistics card above the calendar.

### Calendar workspace

The calendar is first in DOM order after the top bar and is present in empty, loading, success, partial, and error states. Empty/loading/error messages render inside the calendar body without changing its outer dimensions. A single compact status line in the calendar toolbar may show `요청 · 배치 · 미배치` totals after scheduling; it is not a separate box.

Desktop uses a Monday-first seven-column month grid with 35 or 42 cells. Show at most three events per day before the existing keyboard-operable `+N개 더 보기` disclosure. Mobile uses chronological date groups. Titles truncate on desktop and wrap to two lines on mobile; full text remains in `aria-label`/accessible content.

### Composition panel

Use Gradio 6.27's native `gr.Sidebar(position="right", width=440, open=False)` as the sole approved composition primitive, with owned ID `jf-compose-panel`. An inline collapsible panel, permanent second column, or custom replacement modal is not an approved implementation outcome; failing a required Sidebar browser check is an implementation defect to correct, not permission to change patterns. The Sidebar is closed on first load and is labelled by the persistent `#jf-compose-title` heading (`일정 만들기`). Above 700 px it is a non-modal region with `role="complementary"`, `aria-labelledby="jf-compose-title"`, and no `aria-modal` attribute: render no scrim, do not make the calendar inert, and keep the visible calendar available to pointer and keyboard users. At 700 px and below it is a modal sheet with `role="dialog"`, `aria-modal="true"`, and the same `aria-labelledby`; an intercepting scrim, background `inert`/`aria-hidden="true"`, scroll lock, and a focus trap are required. While the panel is open, crossing the breakpoint updates these attributes and behaviors without closing it, resetting its active step, or losing entered data. Desktop-to-mobile moves focus to `#jf-compose-title` only when focus was outside the panel; mobile-to-desktop preserves focus and removes the trap, scrim, inertness, and background `aria-hidden`. The explicit close button and Escape dismiss the panel and restore the opening trigger.

Successful or partially successful scheduling does not close the panel. It updates the calendar, advances to step 3, moves focus to `#jf-step-calendar`, and announces completion once. Step 3 remains observable until the user activates `캘린더에서 보기` (close and focus `#calendar-heading`), the explicit close button, or Escape; the latter two restore the opening trigger. Do not invent a second desktop form column.

The panel has a sticky 56 px header, explicit close button, stepper, one scrollable body, and sticky 64 px footer. Only one step's primary content is expanded:

1. `요청 입력`: request textarea, selected month, reference time, privacy/cost disclosure, AI parse action, and keyless demo action.
2. `일정 확인`: editable task/routine/availability/fixed-event regions, field diagnostics adjacent to affected content, and explicit `검토 완료` checkbox.
3. `캘린더`: scheduling progress/result, compact totals, and `캘린더에서 보기` close/focus action.

Review tables may use collapsed subsections inside step 2, but the subsection containing the first error opens automatically. Existing edit, confirmation, invalidation, keyless demo, bounds, and no-provider behavior remain unchanged.

### Secondary details

`상세 일정` and `미배치 및 진단` are two independent native `details` disclosures below the calendar, both closed by default. Their summaries show counts; unplaced/error count may use a subdued semantic badge. Opening either must not alter the calendar's dimensions. Tables scroll inside a bounded region with sticky headers.

## Do's and Don'ts

Do:

- keep the calendar mounted and visually stable across all states;
- keep one high-emphasis action per viewport;
- use native buttons, labels, checkbox/radio semantics, and `details/summary` where practical;
- preserve exact scheduling, diagnostics, source IDs, and escaped content;
- test computed geometry and font stacks in a real browser at 1440×1000 and 390×844.

Don't:

- restore the hero or the separate “결정적 요약” and “통계” boxes;
- place all four editable tables in the initial document flow;
- use tabs as the primary calendar/detail hierarchy;
- apply `min-height` to every `input` or style Gradio internals outside `.jf-app`;
- rely on remote fonts, color alone, hover alone, or placeholder text for instructions;
- shrink a seven-column month grid onto a 390 px viewport;
- hide unplaced work, diagnostics, the keyless demo, or the privacy/cost disclosure.