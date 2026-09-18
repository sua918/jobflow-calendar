# JobFlow calendar-first UX contract

Status: build-ready visual/interaction contract for `feature/jobflow-mvp`
Baseline inspected: `b40649392b390d784e9c17bf8ef155c2be195aa6`
Normative visual tokens: [`../DESIGN.md`](../DESIGN.md)

This document changes presentation only. The selected-month domain model, deterministic scheduler, editable confirmation, canonical keyless demo, exact diagnostics, accessibility guarantees, input bounds, escaping, and no-provider test path remain normative in `architecture.md`.

## 1. Baseline evidence and problem statement

The current application was exercised through the complete keyless flow in Gradio 6.27.0 and captured at 1440×1000 and 390×844. The generated evidence is local under `.qa-artifacts/` and intentionally ignored by Git:

- `current-desktop-initial.png`
- `current-desktop-scheduled.png`
- `current-mobile-scheduled.png`
- `current-visual-measurements.json`

Observed baseline measurements:

| State | Viewport | Document height | Calendar top in document | Calendar height | Root/computed app font | Horizontal overflow |
|---|---:|---:|---:|---:|---|---|
| Initial | 1440×1000 | 2287 px | empty calendar at 1981 px | 220 px | body Arial; app Source Sans Pro | none |
| Scheduled | 1440×1000 | 3244 px | 2120 px before automatic scroll; 1026 px tall | 1026 px | body Arial; app Source Sans Pro | none |
| Scheduled | 390×844 | 4131 px | about 2617 px before automatic scroll | 1412 px agenda | body Arial; app Source Sans Pro | none |

The browser probe also measured native checkbox boxes at 16×44 px because the global `button, input, textarea { min-height: 44px; }` rule stretches every input. The visible result is an elongated checkbox instead of a square control.

The baseline hierarchy is form-first: 158 px hero, request textarea, two context fields, repeated context prose, privacy prose, two actions, four full editable tables, diagnostics, confirmation, schedule action, separate summary/status boxes, result tabs, and finally the calendar. This contradicts the claim that the calendar comes first. The first screen contains many weakly differentiated white cards and borders, while the useful monthly result sits several viewport heights below them.

## 2. Architecture decision

Adopt a persistent calendar workspace plus a right-side composition drawer.

- The calendar is mounted immediately after the top bar and never moves behind the entire input/review flow.
- `일정 만들기` opens a progressive drawer with exactly three steps: `요청 입력 → 일정 확인 → 캘린더`.
- Use Gradio 6.27's available `gr.Sidebar(position="right", width=440, open=False)` primitive with `elem_id="jf-compose-panel"`; do not emulate a modal with an always-visible column.
- The drawer is non-modal on desktop and a modal overlay sheet on mobile. Desktop renders no scrim: users may inspect and operate the visible calendar by pointer or keyboard while editing. Mobile uses a dimming scrim, makes the background inert, and locks underlying document scroll while the sheet is open.
- Detailed schedule and unplaced diagnostics become independent collapsed disclosures below the calendar, not sibling primary tabs.

Reasoning: the installed Gradio version provides a native collapsible Sidebar with expand/collapse events and a right position. It is more reliable than a custom dialog layered over Gradio portals. Its public API does not promise overlay/no-reflow or product focus restoration, so those are JobFlow-owned requirements rather than assumed framework behavior. On desktop, the rendered `#jf-compose-panel` root must be fixed to `top: 0; right: 0; bottom: 0`, width 440 px, and a product z-index above the workspace. It has `role="complementary"`, `aria-labelledby` pointing to its heading, no `aria-modal`, no scrim, and no background `inert`/`aria-hidden`; opening it must change the calendar bounding-box width and x-position by no more than 2 px. On mobile (`max-width: 700px`) it becomes modal, is fixed at `inset: 0`, and uses `width: 100dvw; max-width: none; height: 100dvh`; its scrim intercepts background pointer input while inertness/focus containment block keyboard access. Use the Sidebar `open` state/events for visibility; target no generated hash class. The implementation must add focus behavior through the owned IDs in section 8 and prove all geometry in section 12.

## 3. Information architecture

### 3.1 Closed/default workspace

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ JobFlow   [‹] [이번 달] [›]   2026-03                    [일정 만들기]       │ 64
├──────────────────────────────────────────────────────────────────────────────┤
│ 2026년 3월                         요청 960 · 배치 960 · 미배치 0분          │ 56
│ 월  화  수  목  금  토  일                                                   │ 36
│ ┌────────┬────────┬────────┬────────┬────────┬────────┬────────┐            │
│ │ date + compact events                                               │       │
│ ├────────┼────────┼────────┼────────┼────────┼────────┼────────┤ 5–6 rows   │
│ │                         monthly calendar                            │       │
│ └────────┴────────┴────────┴────────┴────────┴────────┴────────┘            │
├──────────────────────────────────────────────────────────────────────────────┤
│ ▸ 상세 일정 (13)       ▸ 미배치 및 진단 (0)                                │
└──────────────────────────────────────────────────────────────────────────────┘
```

The calendar is visible even before a schedule exists. Its body shows an empty-state action and a short explanation, not a 220 px placeholder after the form.

### 3.2 Open composition drawer

```text
calendar remains mounted       ┌──────────────────────────┐
(and is dimmed on mobile)       │ 일정 만들기          [×] │ sticky 56
                                │ 1 요청  2 확인  3 완료  │ stepper 40
                                ├──────────────────────────┤
                                │ one step body only       │ scrollable
                                │                          │
                                │ input OR review OR done  │
                                ├──────────────────────────┤
                                │ [secondary] [primary]    │ sticky 64
                                └──────────────────────────┘
```

The drawer owns the workflow; the calendar owns the result. The stepper reports progress and is not free navigation to a step whose prerequisites are missing. This diagram has no desktop scrim: the visible calendar region to the left remains pointer- and keyboard-operable. Only the mobile sheet adds an intercepting dim scrim and modal background inertness.

## 4. Before/after component mapping

| Current component | Decision | Calendar-first destination |
|---|---|---|
| `.jf-hero` title and explanatory card | Remove | Product name moves to compact top bar; no intro prose/card |
| Request textarea | Move | Drawer step 1 |
| Reference datetime field | Move, retain | Drawer step 1 under `고급 설정`, expanded only when changed/invalid |
| Plan-month textbox | Merge | Read-only `YYYY-MM` in top bar; editable month control in drawer step 1 uses the same state |
| Repeated context Markdown | Remove as standalone box | One metadata line in step 1; exact context remains accessible |
| Privacy/cost Markdown | Move, shorten | Step 1 disclosure beside AI parse action; full copy in expandable help |
| `Parse — AI로 구조화` | Rename/move | Step 1 primary `요청 분석하기` |
| Keyless demo button | Retain/move | Step 1 secondary `예시 불러오기`; no API key required |
| `구조화 검토` heading | Merge | Drawer step 2 heading `일정 확인` |
| Four always-visible Dataframes | Move/progressively disclose | Step 2 sections: 마감 작업, 반복 일정, 가능 시간, 고정 일정; first error section auto-opens |
| Per-row `사용자 확인` booleans and provenance | Retain/move | Stay editable in their corresponding step 2 section; confirmation continues to update user provenance and clear only confirmed uncertainty |
| Field diagnostics textbox | Merge | Inline/section diagnostics in step 2; complete diagnostic list at end of step |
| `검토 완료` checkbox | Retain/fix geometry | Step 2 sticky footer, native 18×18 px checkbox inside 44 px label target |
| `규칙 기반 일정 만들기` | Rename/move | Step 2 primary `캘린더에 반영` |
| `규칙 기반 일정` heading | Remove | Calendar is already the page workspace |
| `결정적 요약` box | Remove (first unexplained top result box) | One sentence in calendar toolbar live region |
| `통계` box | Remove (second unexplained top result box) | Compact `요청 · 배치 · 미배치` toolbar text |
| Month/detail/diagnostic tabs | Remove tab chrome | Calendar always visible; two closed `details` disclosures below it |
| Monthly calendar HTML | Promote | Main surface directly below top bar |
| Detailed schedule table | Retain/collapse | `상세 일정 (N)` disclosure, closed by default |
| Unscheduled table and schedule diagnostics | Retain/collapse | `미배치 및 진단 (N)` disclosure, closed by default; auto-open only after explicit user action, never automatically on result |
| Gradio footer | De-emphasize | Keep functional framework footer below all product content; it is outside the first viewport |

No domain data or failure path is removed. “Remove” above means remove duplicate presentation, not remove the underlying result, stats, context, or diagnostics from state.

## 5. Desktop contract — 1440×1000

### 5.1 Frame and density budget

- `.jf-app`: width `100%`, max-width `1600px`, margin auto, 24 px horizontal padding.
- Top bar: fixed visual height 64 px; one 1 px bottom border; no card radius or shadow.
- Main starts 16 px below the top bar.
- Calendar shell at this target: width 1392 px and minimum height 824 px. It occupies at least 70% of the area between the top bar and viewport bottom.
- Calendar toolbar: 56 px. Weekday heading: 36 px.
- Six-row month: each day cell at least 112 px. Five-row months use `minmax(112px, 1fr)` and grow to consume the same calendar body height.
- The calendar heading and at least five full week rows must be visible in the first viewport at 100% zoom. For a six-row month, the last row may meet the fold but must not require traversing input/review content.
- Secondary disclosure summaries may begin below the fold. Neither is open by default.
- Maximum simultaneous bordered regions in the closed first viewport: top-bar bottom edge, one calendar shell, event chip boundaries. No nested card borders around toolbar, totals, or empty state.

### 5.2 Top bar

Desktop row order and dimensions:

1. product identity, minimum width 112 px;
2. 16 px spacer;
3. previous, `이번 달`, next buttons at 40 px height; icon-only previous/next are 40×40 with accessible Korean names;
4. selected month `YYYY-MM`, 80 px minimum, tabular numerals;
5. flexible spacer;
6. one blue `일정 만들기` button, 112×40 px minimum.

No other high-emphasis action appears while the drawer is closed.

### 5.3 Calendar event density

- Day padding: 8 px; date header: 24 px.
- Event chip: minimum 24 px high, 6 px vertical gap, 3 px left category border.
- Up to three chips before `+N개 더 보기`.
- Desktop event title is one line with ellipsis; time may remain on the same or a second metadata line according to available width.
- Fixed-event continuation arrows remain visible.
- Empty days show no `일정 없음` repetition. Only the date remains; the month-level empty state is used when the whole result is empty.

## 6. Mobile contract — 390×844

### 6.1 Closed workspace

- Root and document `scrollWidth` must equal `clientWidth` (390 px at the target).
- Outer gutter: 12 px; usable width: 366 px.
- Compact top bar uses at most 104 px over two rows:
  - row 1, 48 px: identity, selected `YYYY-MM`, 40×40 `일정 만들기` icon/text control;
  - row 2, 48 px: previous, `이번 달`, next, and visible month title.
- Calendar agenda begins no lower than y=116 px.
- Do not render a seven-column grid. At `max-width: 700px`, render selected-month dates chronologically and omit adjacent-month and event-free dates.
- Each date group has a sticky-or-static 32 px date label followed by event rows of at least 44 px touch height.
- Event titles wrap to at most two lines; then ellipsize. Full content remains in the accessible name and detail disclosure.
- The first 844 px shows the top controls and multiple scheduled dates or a complete empty/loading/error state. It must not show request/review tables before the calendar.

### 6.2 Open drawer/sheet

- At every viewport up to and including 700 px: `position: fixed; inset: 0; width: 100dvw; max-width: none; height: 100dvh`. The sheet therefore measures 390±2 px at the 390 px target and exactly follows viewport widths from 391 through 700 px.
- Header: 56 px; stepper: 40 px; footer: 64 px; body owns the remaining scroll area.
- Underlying document is inert for pointer/keyboard interaction and its scroll position is preserved.
- All controls have 44×44 px minimum target areas; the visual checkbox/radio itself remains 18×18 px.
- Dataframes may use internal horizontal scrolling. Their scroll container must be labeled, and the page itself must not gain horizontal overflow.
- On-screen keyboard must not cover the sticky primary action; use dynamic viewport units and scroll the focused field into view.

## 7. Progressive workflow and state transitions

### Step 1 — 요청 입력

Content order:

1. heading and one sentence of instruction;
2. request textarea (minimum 160 px, maximum 40dvh);
3. selected month control (`YYYY-MM`) with previous/next affordances;
4. `고급 설정` disclosure containing reference datetime and exact context;
5. concise privacy/cost disclosure;
6. secondary `예시 불러오기` and primary `요청 분석하기` actions.

`예시 불러오기` transitions directly to step 2 with the canonical validated draft. `요청 분석하기` enters an in-panel loading state and performs the existing one provider call. Empty, over-limit, malformed month, missing key, provider, and schema failures remain on step 1 with a focused error summary and field-specific message. Raw user text is not reflected in diagnostics.

### Step 2 — 일정 확인

Content order:

1. compact context/month metadata;
2. status summary (`확인 필요 N`, errors/warnings);
3. four editable sections in this order: deadline tasks, routines, availability, fixed events;
4. complete deterministic diagnostics;
5. sticky footer with `검토 완료` and `캘린더에 반영`.

Each section summary shows item count and error count. Sections are collapsed initially except the first section containing an error; if there is no error, deadline tasks opens first. Editing any table preserves the existing invalidation rule: clear confirmation, disable scheduling, clear stale result, revalidate, and keep the edited invalid value visible.

The checkbox is never used to hide errors. `캘린더에 반영` is enabled only when `ready_to_schedule` and explicit confirmation are both true.

### Step 3 — 캘린더

During scheduling, preserve the calendar's dimensions and show a centered progress status inside its body. On success or partial placement:

- render the calendar first;
- update the toolbar sentence/totals in one polite live region;
- retain all exact unplaced entries and diagnostics in the closed disclosure;
- show step 3 completion copy and `캘린더에서 보기`;
- close the drawer and focus the calendar heading when the user activates that action.

Scheduling invariant failures show a generic safe error inside the calendar and keep the drawer at step 2 so the user can inspect diagnostics. No stack trace or raw provider payload is shown.

### Month navigation

Previous/next/`이번 달` update the selected month through the existing `SelectedMonth` adapter. Any month change clears stale review, confirmation, and result before rendering the new empty month. The month controls must not silently reuse a result from another month. Year 1 and year 9998 boundaries disable the unavailable direction rather than emitting an invalid year.

## 8. Keyboard, focus, and announcements

Closed workspace focus order:

1. skip link to calendar;
2. JobFlow/home identity only if interactive;
3. previous month;
4. `이번 달`;
5. next month;
6. selected month control if editable;
7. `일정 만들기`;
8. calendar overflow/event controls in chronological DOM order;
9. `상세 일정` summary;
10. `미배치 및 진단` summary.

Drawer behavior:

- Opening stores the trigger and moves focus to the drawer heading, then the first invalid control if reopening after validation.
- Desktop Sidebar is non-modal: it has `role="complementary"` and `aria-labelledby`, but no `aria-modal`, scrim, background `inert`, or background `aria-hidden`. Focus may leave it for the calendar, and visible calendar controls remain pointer-operable; the close control is always first inside.
- Mobile sheet is modal in behavior: a dim scrim intercepts background pointer input, the background receives `inert` and `aria-hidden="true"`, and Tab/Shift+Tab remain within the sheet.
- Escape closes the drawer unless an owned nested disclosure/editor is consuming Escape. Closing returns focus to the original `일정 만들기` trigger.
- Step changes move focus to the new step heading, not the first table cell.
- Scheduling completion is announced once through `aria-live="polite"`; errors use `role="alert"`. Do not duplicate announcements in separate summary and stats inputs.
- Focus ring: 2 px `#1D4ED8`, 2 px offset. It must not be clipped by calendar, drawer, dataframe, or details containers.

## 9. Form-control CSS contract

The existing global rule is forbidden:

```text
button, input, textarea, [role="tab"], summary { min-height: 44px; }
```

It makes checkboxes 16×44 px and contaminates hidden/file/dataframe inputs. Instead:

- place `elem_classes=["jf-app"]` on the owned application root;
- assign owned classes such as `jf-button`, `jf-text-field`, `jf-checkbox`, and `jf-radio` to JobFlow components;
- apply 40/44 px control or target height to the owned wrapper/button/label;
- apply 18×18 px dimensions only to checkbox/radio inputs;
- do not target bare `input`, `textarea`, `[type=checkbox]`, Gradio hash classes, or all elements under a generic `.gradio-container` selector.

Required computed values for every visible owned checkbox/radio at both target viewports:

```text
width: 18px
height: 18px
min-width: 18px
max-width: 18px
min-height: 18px
max-height: 18px
aspect-ratio: 1 / 1
```

Allowed primary selector:

```text
.jf-app :where(.jf-checkbox, .jf-radio) input:is([type="checkbox"], [type="radio"])
```

Allowed Gradio fallback, only if the owned class lands on an ancestor:

```text
.jf-app .jf-checkbox [data-testid="checkbox"] input[type="checkbox"]
```

The wrapping label/row must still measure at least 44×44 px for touch. Automated tests must assert that text, file, and hidden inputs do not receive the 18 px square constraint.

## 10. Content and state contract

### Empty

Keep the full calendar shell. Center a calendar icon, `아직 일정이 없어요`, one sentence, and `일정 만들기`. Do not repeat `일정 없음` in every day cell. Secondary disclosures show count zero and remain closed.

### Loading

Keep the shell dimensions and header. Use a neutral skeleton or progress indicator with `일정을 만들고 있어요` in a polite live region. No animated gradient. Respect `prefers-reduced-motion`.

### Success

Show the month, events, compact toolbar sentence, and totals. Do not claim optimality; retain `규칙 기반 일정` wording in accessible detail/help where needed.

### Partial/unplaced

Calendar remains primary and shows placed events. Toolbar shows a visible warning icon/text and nonzero unplaced minutes. `미배치 및 진단 (N)` remains closed by default but has an accessible warning/count label. The user opens it deliberately; nothing is silently discarded.

### Error

Recoverable validation/provider errors stay in the drawer step where they can be fixed. Internal schedule error renders a safe calendar-body message and a retry action. Error color is never the sole signal.

### Overflow and truncation

- Calendar desktop: one-line title ellipsis; complete title in accessible name.
- Mobile event: two-line clamp; complete title accessible.
- Drawer section/table: internal scrolling; sticky header; no document overflow.
- Diagnostics: wrap codes/messages and break long safe identifiers; never clip remaining-minute values.
- Event overflow: preserve native keyboard-operable `details/summary` and deterministic order.

## 11. DOM ownership and stable selectors

Implementation and browser tests use explicit owned IDs/classes rather than generated Gradio classes:

| Element | Required selector/contract |
|---|---|
| Application root | `.jf-app` |
| Top bar | `#jf-topbar` (`header`) |
| Previous/current/next | `#jf-month-prev`, `#jf-month-current`, `#jf-month-next` |
| Selected month text/control | `#jf-selected-month` |
| Primary trigger | `#jf-create-schedule` |
| Calendar workspace | `#jf-calendar-workspace` |
| Calendar shell | `.calendar-shell` inside workspace |
| Calendar heading | `#calendar-heading` |
| Compact status/live region | `#jf-calendar-status` |
| Composition Sidebar | `#jf-compose-panel` |
| Drawer close | `#jf-compose-close` |
| Step headings | `#jf-step-request`, `#jf-step-review`, `#jf-step-calendar` |
| Confirmation wrapper | `.jf-checkbox` |
| Secondary details | `#jf-schedule-details`, `#jf-unplaced-details` |

IDs identify owned roots; implementation may keep existing event IDs (`data-view-id`, `data-source-id`) unchanged.

## 12. Visual acceptance matrix

Tests must inspect a real browser after the canonical keyless flow, not only search CSS strings.

| Requirement | Desktop 1440×1000 | Mobile 390×844 |
|---|---|---|
| No unexplained top boxes | `.jf-hero`, standalone `결정적 요약`, and standalone `통계` components absent; no sibling summary cards above calendar | same |
| Calendar first | calendar is the first main surface after `#jf-topbar`; top y ≤ 96 px | agenda top y ≤ 116 px |
| Calendar dominance | calendar width ≥ 95% of usable workspace; visible height ≥ 760 px; area ≥ 70% of post-topbar first viewport | calendar/agenda width = 366±2 px; occupies remainder under top controls |
| Secondary collapsed | both details elements have `open === false` after initial load and after scheduling | same |
| Checkbox geometry | every visible owned checkbox/radio width and height are each 16–20 px; `abs(width-height) ≤ 1`; computed aspect ratio is `1 / 1` or measured ratio 0.95–1.05 | same; wrapper target ≥44 px |
| Safe selector scope | text inputs retain ≥40 px height; file/hidden inputs are not forced to 18×18; no global `input` sizing rule | same |
| Font | computed `.jf-app` font family starts with `Pretendard` or `"Pretendard Variable"`; browser fallback list contains system options; no remote font required | same |
| Overflow | `documentElement.scrollWidth === documentElement.clientWidth`; calendar itself does not clip focus ring | same; drawer table may internally scroll |
| Primary action | exactly one visible primary/high-emphasis action while drawer closed | same |
| Drawer default/focus | closed at load; opening focuses heading; no scrim/`aria-modal`/background inertness; calendar remains pointer/keyboard available; Escape closes and restores trigger | full-width modal sheet; intercepting scrim; background inert; Tab contained |
| Drawer no-reflow | opening changes calendar x/width by ≤2 px; owned fixed panel is 440±2 px wide | at 390 px, sheet is 390±2 px wide and fixed to viewport; at every tested 391–700 px width, sheet width equals `documentElement.clientWidth` ±2 px |
| Calendar state stability | empty/loading/error/success outer shell dimensions differ by no more than 2 px at same viewport/month | same agenda container rule |
| Event semantics | visible category icon/text plus subdued left border; escaped title; stable source/view IDs | same |
| WCAG | all normative text/background pairs AA; focus/component indicators ≥3:1; keyboard order matches section 8 | same |

Required screenshots:

1. `calendar-first-desktop-empty-1440x1000.png`
2. `calendar-first-desktop-review-1440x1000.png` with drawer step 2 open
3. `calendar-first-desktop-scheduled-1440x1000.png`
4. `calendar-first-mobile-empty-390x844.png`
5. `calendar-first-mobile-review-390x844.png` with sheet open
6. `calendar-first-mobile-scheduled-390x844.png`

Each screenshot is paired with a JSON measurement record containing viewport, document/client widths, top-bar/calendar/panel bounding boxes, computed root font, checkbox/radio dimensions, open state of secondary disclosures, and visible primary-action count.

## 13. Preservation checklist

The redesign is not accepted unless all remain available and tested:

- exact `YYYY-MM` selected-month semantics and invalidation on change;
- visible reference datetime and Asia/Seoul context;
- one-call AI extraction with privacy/cost disclosure;
- keyless canonical demo and complete 960/960/0 schedule;
- editable task, routine, availability, and fixed-event data;
- per-row provenance confirmation and explicit overall confirmation;
- deterministic scheduling with no provider call;
- detail rows, exact unplaced reasons/details/remaining minutes, and diagnostics;
- input item/character bounds at all existing layers;
- escaped user text, stable source/view IDs, and safe missing-key/internal-error messages;
- keyboard navigation, focus visibility, reduced motion, and non-color category cues.

## 14. Known Gradio constraints

- `gr.Sidebar` exists in installed Gradio 6.27.0 and supports right positioning plus expand/collapse events, but product focus restoration and mobile inertness must be added and browser-tested.
- Gradio-generated class names are not stable contracts. Target only `elem_id`, `elem_classes`, semantic attributes, and owned calendar HTML classes.
- Dataframe internals create checkbox/file/hidden inputs. This is why bare input selectors are prohibited and why geometry tests must distinguish owned controls from internal ones.
- Custom calendar HTML remains appropriate for semantic month/agenda projection, but all user-authored strings must continue to be escaped before interpolation.
- The framework footer and API controls may exist below product content; they must not enter the first viewport or alter the product hierarchy.

If the native Sidebar cannot satisfy the fixed overlay, focus, or overflow checks in the supported Gradio range without targeting generated classes, the only approved fallback is one inline collapsible panel immediately after the top bar. It is closed by default, full-width with an inner 720 px content maximum, and at most `60dvh` tall when open; the calendar follows it rather than becoming a second column. Closed-state first-viewport budgets remain unchanged. The fallback must preserve the same three steps, sticky actions, Escape/restore behavior, and mobile focus containment. A permanently visible second form column or custom untrapped modal is not approved.