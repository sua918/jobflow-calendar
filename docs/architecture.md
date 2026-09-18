# JobFlow MVP architecture and shared contracts

Status: architecture gate for `feature/jobflow-mvp`
Scope: a 1.5-day course MVP; this document is normative for backend and frontend work.

## 1. Product boundary and architectural decision

JobFlow accepts Korean free text describing job-search preparation work, extracts an editable structured draft, validates the user's confirmed values, and produces a conflict-free plan for one user-selected Seoul calendar month in a Gradio UI. It supports hard-deadline tasks and recurring routines and always exposes work it could not schedule.

The selected month is a product boundary, not a duration shortcut. Every layer represents it as a year/month value and derives the same half-open horizon: `[selected month day 1 00:00 Asia/Seoul, next month day 1 00:00 Asia/Seoul)`. A rolling start date, an arbitrary day count, and multi-month planning are not supported.

The application is a single Python process with four boundaries:

1. Gradio presents input, review/edit, schedule, and diagnostics views.
2. A single LangChain LCEL structured-output call converts Korean text into a typed `ExtractionDraft`.
3. Pydantic and deterministic validation convert confirmed draft rows into a `ScheduleRequest`.
4. A pure deterministic Python scheduler returns a `ScheduleResult`.

The LLM is never trusted for overlap, recurrence, capacity, deadline, duration, or timezone correctness. It may parse text and optionally rephrase an already-computed result. Pydantic validation and the scheduler are the source of truth.

Non-goals: Google Calendar authentication or sync, scraping, user accounts, a database, notifications, RAG/vector storage, multi-agent reasoning, drag-and-drop editing, optimization services, and production deployment. ICS export is also excluded from this MVP.

## 2. Repository and module contract

All files, environments, caches, and generated artifacts stay under `/mnt/hermes-data/jobflow-calendar`.

```text
jobflow-calendar/
├── .env.example
├── .gitignore
├── DESIGN.md               # downstream frontend-owned token source
├── README.md
├── pyproject.toml
├── docs/
│   └── architecture.md
├── src/jobflow/
│   ├── __init__.py
│   ├── models.py          # all shared Pydantic models and enums below
│   ├── extraction.py      # LangChain boundary only
│   ├── validation.py      # deterministic cross-model validation/normalization
│   ├── scheduler.py       # pure deterministic scheduling; no LLM or Gradio imports
│   ├── services.py        # parse/review/schedule orchestration
│   ├── ui.py              # Gradio Blocks and view-model conversion
│   └── app.py             # construction and launch entry point
└── tests/
    ├── fixtures/
    │   └── canonical_demo.json
    ├── test_models.py
    ├── test_validation.py
    ├── test_scheduler.py
    ├── test_extraction.py
    ├── test_services.py
    └── test_ui_smoke.py
```

`models.py` is the only definition site for shared types. `scheduler.py` depends only on the standard library and `models.py`. `extraction.py` must not import the scheduler. `ui.py` calls `services.py`, never private scheduler/extraction helpers. `app.py` exposes `build_app() -> gr.Blocks` and `main() -> None`.

Likely collision hotspots for the migration are `models.py`, `validation.py`, `scheduler.py`, `extraction.py`, `services.py`, `ui.py`, `tests/fixtures/canonical_demo.json`, `tests/test_scheduler.py`, `tests/test_ui_smoke.py`, `README.md`, and the new root `DESIGN.md`; assign exactly one implementation owner for each phase. Do not duplicate domain models in UI code.

## 3. Time and identity rules

- The sole MVP timezone is the IANA zone `Asia/Seoul`, represented with `zoneinfo.ZoneInfo`. Do not use a fixed `+09:00` object as the canonical zone.
- All persisted/inter-module datetimes are timezone-aware and normalized to `Asia/Seoul`. Naive datetimes are rejected at the confirmed-data boundary.
- UI date/time inputs are interpreted as Seoul local time, displayed with the `KST` label, and combined with `ZoneInfo("Asia/Seoul")` before model construction.
- Intervals are half-open: `[start, end)`. Therefore one block ending when another begins does not overlap.
- `SelectedMonth(year, month)` is the sole planning-period representation. `year` is `1..9998` and `month` is `1..12`; the upper year bound ensures the next-month boundary is representable. JSON is `{"year": 2026, "month": 3}`. UI month controls may emit `YYYY-MM`, but must parse it immediately into `SelectedMonth`; free-form dates are not accepted as month selection.
- `month_bounds(selected_month)` constructs `horizon_start = datetime(year, month, 1, 00:00, tzinfo=ZoneInfo("Asia/Seoul"))`. `horizon_end` is the first day of the following month at `00:00` in the same IANA zone, using explicit December rollover. Do not derive it with a fixed number of days. Examples: `2024-02` is `[2024-02-01, 2024-03-01)` with 29 days; `2025-02` has 28 days; `2026-04` has 30 days; `2026-03` has 31 days.
- `slot_minutes` remains exactly 30. Starts, ends, deadlines, durations, and time-window boundaries must align to the grid. The only exception is raw LLM draft text, which cannot enter the scheduler until corrected/normalized and confirmed.
- IDs are stable, UI-safe strings. All IDs use the character rule `^[A-Za-z0-9][A-Za-z0-9_-]*$`. `DeadlineTask.id` and `RecurringRoutine.id` are work-item IDs and must contain at most 48 characters because they are embedded verbatim in generated block IDs. Every other ID contains at most 64 characters. Extraction creates deterministic IDs in input order (`task-01`, `routine-01`, `fixed-01`); edits preserve them.
- A generated schedule-block ID is exactly `block-{work_id}-{sequence:02d}`: `sequence` is decimal, starts at 1 independently for each work item, has a minimum width of two digits (`01` through `99`) and expands normally at `100` and `1000`; neither `work_id` nor the ID may be truncated, hashed, or rewritten. A 31-day month contains `31 * 48 = 1,488` grid slots. Because generated blocks cannot overlap, the entire result and any one work item can contain at most 1,488 blocks. The largest sequence is therefore `1488` (four digits). A 48-character work-item ID yields at most `6 + 48 + 1 + 4 = 59` characters (`block-` is six characters), within the global 64-character ceiling. Tests must exercise the four-digit sequence boundary even if normal daily caps produce fewer blocks.

## 4. Normative shared models

Use Pydantic v2 with `ConfigDict(extra="forbid")` on every model. Enums subclass `str, Enum`. Fields shown as `= value` have that default; all other fields are required. JSON serialization uses ISO-8601 dates/times and timezone-aware datetime strings.

```python
class Weekday(str, Enum):
    MON = "MON"; TUE = "TUE"; WED = "WED"; THU = "THU"
    FRI = "FRI"; SAT = "SAT"; SUN = "SUN"

class ExtractionMethod(str, Enum):
    LLM = "llm"; USER = "user"; DEFAULT = "default"

class Severity(str, Enum):
    INFO = "info"; WARNING = "warning"; ERROR = "error"

class WorkKind(str, Enum):
    DEADLINE_TASK = "deadline_task"; RECURRING_ROUTINE = "recurring_routine"

class BlockKind(str, Enum):
    TASK = "task"; ROUTINE = "routine"

class UnscheduledReason(str, Enum):
    CONFIRMATION_REQUIRED = "confirmation_required"
    OUTSIDE_HORIZON = "outside_horizon"
    NO_AVAILABILITY = "no_availability"
    NO_CAPACITY_BEFORE_DEADLINE = "no_capacity_before_deadline"
    NO_MATCHING_ROUTINE_WINDOW = "no_matching_routine_window"
    DAILY_CAP_EXCEEDED = "daily_cap_exceeded"
    FIXED_EVENT_CONFLICT = "fixed_event_conflict"

class SourceProvenance(BaseModel):
    source_text: str
    extraction_method: ExtractionMethod
    confidence: float                 # inclusive 0.0..1.0
    uncertain_fields: list[str] = []  # field paths on the owning model
    assumptions: list[str] = []

class LocalTimeWindow(BaseModel):
    start: time
    end: time                         # start < end; no overnight window in MVP

class AvailabilityRule(BaseModel):
    id: str
    weekdays: set[Weekday]
    window: LocalTimeWindow
    valid_from: date | None = None
    valid_through: date | None = None # inclusive local date
    provenance: SourceProvenance

class FixedEvent(BaseModel):
    id: str
    title: str
    start: datetime
    end: datetime
    provenance: SourceProvenance

class DeadlineTask(BaseModel):
    kind: Literal["deadline_task"] = "deadline_task"
    id: str                           # work-item ID; 1..48 characters
    title: str
    duration_minutes: int
    deadline: datetime
    earliest_start: datetime | None = None
    priority: int = 3                 # 1 lowest, 5 highest
    splittable: bool = True
    min_block_minutes: int = 30
    max_block_minutes: int = 120
    daily_cap_minutes: int = 240
    preferred_windows: list[LocalTimeWindow] = [] # soft preference
    provenance: SourceProvenance

class RecurringRoutine(BaseModel):
    kind: Literal["recurring_routine"] = "recurring_routine"
    id: str                           # work-item ID; 1..48 characters
    title: str
    duration_minutes: int             # per occurrence
    weekdays: set[Weekday]
    window: LocalTimeWindow           # hard allowed window for each occurrence
    start_date: date | None = None
    end_date: date | None = None      # inclusive
    priority: int = 3                 # 1 lowest, 5 highest; tie-break only
    required: bool = True
    provenance: SourceProvenance

class SelectedMonth(BaseModel):
    year: int = Field(ge=1, le=9998)
    month: int = Field(ge=1, le=12)

class ParseContext(BaseModel):
    reference_datetime: datetime      # aware Asia/Seoul; resolves relative Korean dates
    selected_month: SelectedMonth
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"

class ExtractionDraft(BaseModel):
    deadline_tasks: list[DeadlineTask] = []
    recurring_routines: list[RecurringRoutine] = []
    availability: list[AvailabilityRule] = []
    fixed_events: list[FixedEvent] = []

class Diagnostic(BaseModel):
    code: str                         # stable SCREAMING_SNAKE_CASE code
    severity: Severity
    message_ko: str
    entity_id: str | None = None
    field: str | None = None
    details: dict[str, str | int | float | bool | None] = {}

class ValidationReport(BaseModel):
    normalized: ExtractionDraft | None
    diagnostics: list[Diagnostic]
    ready_to_schedule: bool
    context: ParseContext              # required, public, JSON-serializable

class ScheduleRequest(BaseModel):
    selected_month: SelectedMonth
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    slot_minutes: Literal[30] = 30
    daily_work_cap_minutes: int = 240 # task/routine blocks only; fixed events excluded
    deadline_tasks: list[DeadlineTask] = []
    recurring_routines: list[RecurringRoutine] = []
    availability: list[AvailabilityRule]
    fixed_events: list[FixedEvent] = []

class ScheduleBlock(BaseModel):
    id: str                           # exact block-{work_id}-{sequence:02d}
    work_id: str                      # verbatim DeadlineTask/RecurringRoutine ID
    title: str
    kind: BlockKind
    start: datetime
    end: datetime
    occurrence_date: date | None = None # set only for routine blocks

class UnscheduledWork(BaseModel):
    work_id: str
    title: str
    kind: WorkKind
    reason: UnscheduledReason
    requested_minutes: int
    scheduled_minutes: int
    remaining_minutes: int
    occurrence_date: date | None = None
    message_ko: str
    details: dict[str, str | int | float | bool | None] = {}

class ScheduleStats(BaseModel):
    requested_minutes: int
    scheduled_minutes: int
    unscheduled_minutes: int

class ScheduleResult(BaseModel):
    blocks: list[ScheduleBlock]
    unscheduled: list[UnscheduledWork]
    diagnostics: list[Diagnostic]
    stats: ScheduleStats
    is_fully_scheduled: bool
```

Mutable collection defaults above are safe under Pydantic v2's copying behavior, but `Field(default_factory=list/set/dict)` is preferred in implementation.

Exact public APIs:

```python
# models.py
def month_bounds(selected_month: SelectedMonth) -> tuple[datetime, datetime]: ...

# extraction.py
async def extract_draft(text: str, context: ParseContext) -> ExtractionDraft: ...

# validation.py
def validate_draft(draft: ExtractionDraft, context: ParseContext) -> ValidationReport: ...
def to_schedule_request(report: ValidationReport, *, daily_work_cap_minutes: int = 240) -> ScheduleRequest: ...

# scheduler.py
def build_schedule(request: ScheduleRequest) -> ScheduleResult: ...
def validate_schedule(request: ScheduleRequest, result: ScheduleResult) -> list[Diagnostic]: ...

# services.py
async def parse_for_review(text: str, context: ParseContext) -> ValidationReport: ...
def schedule_confirmed(request: ScheduleRequest) -> ScheduleResult: ...
def explain_result_ko(result: ScheduleResult) -> str: ...
```

`validate_draft(draft, context)` deep-copies the supplied `ParseContext` into the required public `ValidationReport.context` field. The report, including `selected_month`, must survive a Pydantic `model_dump_json()` / `model_validate_json()` round trip. `to_schedule_request` raises `ConfirmationRequiredError` if `ready_to_schedule` is false and obtains `ScheduleRequest.selected_month` solely from `report.context.selected_month`; private attributes, module globals, closure state, or another in-process context cache are not valid sources. `schedule_confirmed` must run `validate_schedule` and treat any error-severity diagnostic as an internal correctness failure rather than showing an apparently valid plan.

## 5. Deterministic validation invariants

Validation returns diagnostics for expected input problems; it does not silently repair meaning.

1. IDs are unique across tasks, routines, availability, and fixed events. Validation deterministically rejects a `DeadlineTask.id` or `RecurringRoutine.id` longer than 48 characters at model construction, before scheduling, and rejects every other ID longer than 64 characters. Generated block IDs retain the exact `block-{work_id}-{sequence:02d}` form and are also validated against the 64-character ceiling.
2. Titles and provenance `source_text` are nonblank.
3. Confidence is in `[0, 1]`; priority is 1..5.
4. Every duration/cap/block bound is positive and divisible by 30. `min_block_minutes <= max_block_minutes <= daily_cap_minutes`. For non-splittable work, duration must fit both `max_block_minutes` and `daily_cap_minutes`.
5. Datetimes are aware, normalized to `Asia/Seoul`, and aligned to the slot grid. `start < end`; task `earliest_start < deadline` when supplied.
6. Local windows are same-day with `start < end` and 30-minute boundaries. Overnight windows are invalid in this MVP and must be split into two rules by the user.
7. Availability date bounds are ordered. Duplicate/overlapping availability rules are unioned during slot generation, not double-counted.
8. Fixed events may overlap one another in user input, but their occupied-time union is used; emit warning `OVERLAPPING_FIXED_EVENTS`.
9. Critical uncertain fields prevent scheduling. For a deadline task they are `title`, `duration_minutes`, and `deadline`; for a routine they are `title`, `duration_minutes`, `weekdays`, and `window`; at least one availability rule is mandatory. Any critical field in `uncertain_fields`, or confidence below 0.70, emits `CONFIRMATION_REQUIRED` until the UI records user confirmation.
10. User confirmation changes provenance to `extraction_method="user"`, clears confirmed field names from `uncertain_fields`, and may retain the original text/assumptions for audit. It must not merely hide the warning.
11. Relative expressions such as “다음 주 화요일” are resolved only against `ParseContext.reference_datetime`, whose value is visible in the UI. If more than one interpretation remains, leave the field uncertain.
12. Defaults may be applied without confirmation only for documented policy fields: priority 3, task splitting true, min block 30, max block 120, task daily cap 240, request daily cap 240. Each default is recorded in `assumptions` with method `default` at draft construction time.
13. The selected-month relationship is explicit for every item type; no item is silently dropped:
    - A deadline task is schedulable in `[max(earliest_start or horizon_start, horizon_start), min(deadline, horizon_end))`. A deadline after month end is not by itself outside the horizon: work may be placed in the selected month, but never after `horizon_end`. If `deadline <= horizon_start` or `earliest_start >= horizon_end`, emit exactly one `UnscheduledWork(OUTSIDE_HORIZON)` for the full task. Otherwise normal capacity reasons apply to any remainder.
    - A routine materializes occurrences only on matching dates inside both its optional inclusive date range and the selected month. A date range wholly disjoint from the month emits warning diagnostic `OUTSIDE_HORIZON`, creates no occurrence, no `UnscheduledWork`, and contributes zero requested minutes. An intersecting range with no matching weekday emits informational `NO_OCCURRENCE_IN_SELECTED_MONTH` and also contributes zero. Every materialized but unplaced occurrence still receives its own exact `UnscheduledWork`.
    - An availability rule is intersected with selected-month dates. A wholly disjoint bounded rule emits warning `OUTSIDE_HORIZON`; a partial intersection emits informational `AVAILABILITY_CLIPPED_TO_HORIZON`. Rules remain in normalized review data. If the resulting union has no in-month slot, `NO_AVAILABILITY` is an error and scheduling is blocked.
    - A fixed event is retained in normalized review data. A wholly disjoint event emits warning `OUTSIDE_HORIZON` and removes no capacity. A partially intersecting event emits informational `FIXED_EVENT_CLIPPED_TO_HORIZON`; only its intersection with the month removes capacity and appears in the month view. Fixed events are constraints, not generated work, so they never create `UnscheduledWork` or affect requested/scheduled minute totals.
14. A valid result has blocks entirely inside the selected-month horizon and availability union; no block overlaps the in-month fixed-event union or another block; every task block ends no later than its deadline; every routine block has the required weekday/occurrence date and lies within its hard routine window; per-work and global daily caps hold; total durations and stats reconcile exactly.

Stable diagnostic codes include `EXTRACTION_FAILED`, `SCHEMA_INVALID`, `CONFIRMATION_REQUIRED`, `NO_AVAILABILITY`, `OUTSIDE_HORIZON`, `NO_OCCURRENCE_IN_SELECTED_MONTH`, `AVAILABILITY_CLIPPED_TO_HORIZON`, `FIXED_EVENT_CLIPPED_TO_HORIZON`, `INVALID_TIMEZONE`, `MISALIGNED_TIME`, `OVERLAPPING_FIXED_EVENTS`, `NO_CAPACITY_BEFORE_DEADLINE`, `NO_MATCHING_ROUTINE_WINDOW`, `DAILY_CAP_EXCEEDED`, and `INTERNAL_SCHEDULE_INVALID`.

## 6. LangChain boundary and ambiguity policy

LangChain/OpenAI is an optional runtime extraction adapter, not a build-time or test-time dependency on live credentials. When a user explicitly invokes Parse with their own project-local runtime key, use a small LCEL chain equivalent to:

```python
prompt | ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"), temperature=0).with_structured_output(ExtractionDraft)
```

The prompt receives the exact user text, `reference_datetime`, serialized `selected_month`, derived horizon dates, timezone, and the documented defaults. It must quote input evidence into each `SourceProvenance`, put uncertain field paths in `uncertain_fields`, and never fabricate missing deadlines, duration, recurrence days, or availability. There is no agent, tool loop, memory, or second model call on the scheduling path.

`extract_draft` catches provider/network/refusal/structured-output failures at the boundary and maps them to the service-level `EXTRACTION_FAILED` diagnostic; logs must not include the user's raw text or API key. Automated tests inject deterministic fake structured outputs and make no live provider or network calls. The canonical fixture and its complete parse/review/schedule path must work without any API key.

A deterministic Korean template in `explain_result_ko` is the required explanation path and is generated solely from `ScheduleResult`. A future optional LLM rephrase may receive only the already-computed summary, may not change facts, and must fall back to the deterministic text. It is not part of MVP acceptance.

If no `OPENAI_API_KEY` is configured, the UI remains launchable and shows a clear extraction-unavailable message; users may still load/edit the canonical structured demo. No key is embedded or sent to the browser. Implementation and testing must not use a class/shared OpenAI API key, and the repository, project environment, fixtures, and test harness must not receive, copy, or derive Hermes/Codex OAuth credentials.

## 7. Scheduling policy

Decision: retain the transparent greedy scheduler, not OR-Tools. The bounded problem is at most 31 days × 48 slots = 1,488 slots; a deterministic heuristic remains easy to test and explain, while OR-Tools adds package size, solver modeling, and debugging risk without an optimization requirement. If the greedy result is too restrictive in a later phase, preserve the same `build_schedule` contract and replace only `scheduler.py` with CP-SAT; `ScheduleResult` and validation remain unchanged.

Normative algorithm:

1. Derive month bounds once from `request.selected_month`. Expand availability into unique 30-minute slots for each selected-month local date, subtract the intersection of the fixed-event union with the month, and track global scheduled-work minutes per local day. Iteration is chronological and never uses an arbitrary day count supplied by a caller.
2. Before allocating deadline work, deterministically materialize one constrained routine occurrence for every matching weekday/local date intersecting each routine's inclusive date range and the selected month. Sort all materialized occurrences by `(occurrence_date ascending, priority descending, routine id ascending)`.
3. Allocate the sorted routine occurrences first. Each occurrence is one contiguous block entirely inside both its hard `window` and availability, respects the global daily cap, and uses the earliest feasible grid-aligned start. `required=false` changes message severity to warning but does not change materialization or placement order.
4. After routine allocation, schedule deadline tasks. Sort tasks by `(deadline ascending, priority descending, id ascending)`; priority never overrides an earlier deadline. For each task, consider slots at/after `earliest_start` (or horizon start), ending no later than its deadline, and inside availability. Preferred windows are soft: candidate free runs inside a preferred window sort before nonpreferred runs.
5. Non-splittable work requires one contiguous run for its full duration. Splittable work uses deterministic chunks no larger than `max_block_minutes`, no smaller than `min_block_minutes`, and never leaves a positive remainder smaller than `min_block_minutes`. Within each preferred-window status, choose the longest legal chunk, then the earliest start; these rules preserve deterministic earliest-deadline/start and ID tie-breakers inside the task phase. Enforce the task-specific and global daily caps before committing each chunk.
6. Never move/delete fixed events or already placed blocks to make a later item fit. Never place generated work outside availability, the selected month, a deadline, or a routine window.
7. For every partial/failed task or occurrence, append one `UnscheduledWork` with exact requested/scheduled/remaining minutes and the most specific reason. Use capacity calculations in `details` (for example available minutes before deadline and cap-limited minutes); do not claim only “failed”. A partially scheduled deadline task still makes `is_fully_scheduled=false`.
8. Sort final blocks by `(start, end, id)` and unscheduled entries by `(work_id, occurrence_date or date.min, reason)`. Compute stats from all requested task minutes and materialized routine occurrences plus actual blocks, then call `validate_schedule`.

Allocating constrained routine occurrences before deadline tasks is the normative constrained-first exception and refinement to the product's shorthand “deadline-first” description: deadline-first ordering applies inside the deadline-task phase, after hard-window routine capacity has been reserved. Preferred task times are soft and may be violated to meet a deadline; routine windows are hard. Fixed events and all generated blocks are hard non-overlap constraints. The overall daily cap counts only generated task/routine minutes; fixed events merely remove capacity.

This greedy policy is complete with respect to reporting, not globally optimal. The UI must say “규칙 기반 일정” rather than “최적 일정”. The known risk is that an alternative rearrangement could schedule more work; `UnscheduledWork` makes that limitation explicit.

## 8. Gradio event, calendar, and design-system contract

Use `gr.Blocks` with server-side Pydantic JSON in `gr.State`; Dataframes are editable projections, not the source of truth. Store and restore the complete `ValidationReport`, including its required public `context.selected_month`, through Pydantic JSON so a Gradio event round trip cannot lose the planning month.

1. **Select**: show a month selector whose value is `YYYY-MM`, defaulted from `datetime.now(ZoneInfo("Asia/Seoul"))`, and a separate visible reference datetime. Changing either value invalidates prior review, confirmation, and result. The selected month is editable before Parse or scheduling.
2. **Parse**: user text + visible reference datetime + parsed `SelectedMonth` -> `parse_for_review` -> editable task, routine, availability, and fixed-event tables plus diagnostics. Disable Schedule.
3. **Review/edit**: every table change rebuilds an `ExtractionDraft`, sets edited fields to user provenance, and calls `validate_draft`. Render field-level Korean diagnostics, including outside-month outcomes. Enable Schedule only when `ready_to_schedule=true` and the user checks an explicit “검토 완료” checkbox.
4. **Schedule**: confirmed report -> `to_schedule_request` -> `schedule_confirmed`. This event is deterministic and performs no model call.
5. **Render**: the default result tab is **Month**. Secondary tabs are **Detailed schedule** (the existing chronological timeline/table) and **Unscheduled & diagnostics** (always reachable, with exact reason, details, and remaining minutes). Show deterministic Korean summary and stats in every result state. No claim of optimality.
6. **Edit again**: any input, selected-month, or table edit invalidates the prior result, unchecks confirmation, and disables Schedule until revalidated.

Callbacks return explicit view-model tuples; they do not mutate module globals. One browser session uses its own `gr.State`. The app has no persistence: refresh/process exit clears user data.

### 8.1 Monthly calendar view model

The calendar is a UI projection built from the confirmed `ScheduleRequest` plus `ScheduleResult`; it is not a second scheduling source of truth. UI-only view types may live in `ui.py` and must not be imported by scheduler code.

```python
class CalendarEventView(BaseModel):
    view_id: str                       # stable UI ID; see rules below
    source_id: str                     # ScheduleBlock.id or FixedEvent.id
    work_id: str | None                # task/routine work ID; None for fixed event
    category: Literal["deadline_task", "recurring_routine", "fixed_event"]
    category_label_ko: str
    title: str
    segment_date: date
    segment_start: datetime            # clipped to this local day and month
    segment_end: datetime
    original_start: datetime
    original_end: datetime
    duration_minutes: int              # segment duration
    starts_before_segment: bool
    ends_after_segment: bool
    aria_label_ko: str                 # category + title + full local time range

class CalendarDayCell(BaseModel):
    date: date
    in_selected_month: bool
    is_today: bool
    weekday: Weekday
    events: list[CalendarEventView]

class CalendarMonthView(BaseModel):
    selected_month: SelectedMonth
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    horizon_start: datetime
    horizon_end: datetime
    week_starts_on: Literal["MON"] = "MON"
    row_count: Literal[5, 6]
    days: list[CalendarDayCell]          # exactly row_count * 7, row-major
```

- Grid start is the Monday on or before month day 1. Grid end is the Sunday on or after the month's final day. If that natural range is only four weeks, append one full trailing week; therefore `row_count` is always 5 or 6 and `days` is 35 or 42 cells. `2026-03` is a six-row grid from `2026-02-23` through `2026-04-05`.
- Leading/trailing dates are `in_selected_month=false`, muted, and have `events=[]`. No generated block or fixed-event segment is rendered in adjacent-month cells.
- Each generated block becomes one event segment because generated blocks cannot cross local midnight. A fixed event that intersects the month is clipped to the month and split at local midnights into one segment per selected-month date. Its `view_id` is `fixed-view-{fixed_event_id}-{YYYYMMDD}`; a generated block uses `view_id=ScheduleBlock.id`.
- Within each day, sort by `(segment_start, segment_end, category order, source_id)`, where category order is fixed event, recurring routine, deadline task. Do not hide collisions or overflow silently; compact chips may wrap/stack, and an explicit “+N more” control must be keyboard operable and expose the same ordered events.
- Each visible event includes title, Korean category label or icon, and local `HH:MM–HH:MM`; continuation indicators are added for split fixed events. Tooltip/detail content may add duration and full date, but must not be the only way to obtain essential information.
- Unscheduled work is never rendered as a calendar event. It remains in the dedicated tab with `work_id`, title, kind, occurrence date, reason, requested/scheduled/remaining minutes, message, and deterministic details. The detailed schedule tab retains block ID, title, kind, start, end, and duration.

### 8.2 Visual system and accessibility gate

The downstream frontend phase must add one tracked root `DESIGN.md` (or an equivalent single-source token specification if the tool proves incompatible) before styling implementation. It defines palette, typography, spacing, radii, focus treatment, interaction states, and calendar components. Validate it with `npx -y @google/design.md lint DESIGN.md`; if that CLI is unavailable, use an automated equivalent that checks token references and WCAG 2.1 AA contrast, and record the substitution.

The visual direction is a calm, professional productivity/calendar interface inspired by established calendar and dashboard systems. It must not be a dark developer dashboard or use generic AI gradients. The normative accessible base is:

- neutral ink `#0F172A` on white (`17.85:1` stated contrast);
- primary indigo `#4F46E5` with white text (`6.29:1` stated contrast);
- deadline: Okabe–Ito blue border `#0072B2`, pale blue surface `#E6F4FB`, dark ink text;
- routine: Okabe–Ito green border `#009E73`, pale green surface `#E7F6F1`, dark ink text;
- fixed event: Okabe–Ito orange border `#E69F00`, pale amber surface `#FFF4D6`, and dark ink text; the border is decorative unless separately proven accessible for text/icon use;
- warning/unscheduled: vermillion border `#D55E00`, pale surface `#FDECE7`, dark ink text.

Dark ink on the specified pale surfaces has stated contrast `15.58:1..16.29:1`. The implementation must re-run automated contrast checks rather than trusting prose values. Category meaning never relies on color alone: every chip pairs color with a visible label, icon, or pattern; QA verifies grayscale and common color-vision simulations remain distinguishable.

Required states are default, hover, keyboard focus-visible, selected, today, outside-month, disabled, error, and warning. Focus indicators must remain visible against every surface. Controls and event targets meet WCAG target-size guidance, support keyboard-only operation, and preserve meaningful reading order. The month grid is responsive at desktop and mobile widths, has no horizontal clipping, and keeps event text/readability usable rather than shrinking seven columns beyond recognition; a responsive agenda treatment is permitted on narrow screens if month navigation and date grouping remain clear. Frontend acceptance includes screenshot/visual verification at representative desktop and mobile widths.

## 9. Error model, privacy, secrets, and cost

Expected user/provider errors become `Diagnostic` entries and Korean UI messages. Programming invariant failures raise an internal exception, are logged without raw user text, and become generic `INTERNAL_SCHEDULE_INVALID` at the UI boundary. Do not expose stack traces or provider payloads in Gradio.

`.env` is local-only and listed in `.gitignore`; commit only `.env.example` containing blank `OPENAI_API_KEY=` and `OPENAI_MODEL=gpt-4.1-mini`. Load an end user's project-local runtime key with `python-dotenv` in `app.py`; do not provision or borrow a class/shared key. Never import Hermes/Codex OAuth into the project, and never log, serialize to Gradio state, commit, or return any credential. Also ignore `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `htmlcov/`, `.coverage`, `__pycache__/`, and generated output.

The Korean task text is sent to the configured OpenAI API only when Parse is clicked. Display this disclosure beside the button. Nothing is stored by JobFlow. Keep to one extraction call per click; disable double submission while running. Scheduling and explanation incur no API cost. Tests always use fakes.

## 10. Dependencies and commands

Target Python `>=3.11,<3.13`. Declare runtime dependencies in `pyproject.toml`:

- `pydantic>=2.10,<3`
- `gradio>=5.20,<7`
- `langchain>=1.0,<2`
- `langchain-openai>=1.0,<2`
- `python-dotenv>=1.0,<2`
- `tzdata>=2025.1` (portable IANA database fallback)

Development extras:

- `pytest>=8,<9`
- `pytest-cov>=6,<8`
- `ruff>=0.9,<1`
- `mypy>=1.14,<2`

No OR-Tools, database, calendar SDK, pandas, or web framework beyond Gradio. A resolved lock file may be added by implementation, but these major-version bounds are the contract.

Canonical commands, run from `/mnt/hermes-data/jobflow-calendar`:

```text
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest --cov=jobflow --cov-report=term-missing
.venv/bin/ruff check src tests
.venv/bin/mypy src/jobflow
.venv/bin/python -m jobflow.app
```

Use project-local cache variables during install/test when applicable, for example `PIP_CACHE_DIR=$PWD/.cache/pip` and `XDG_CACHE_HOME=$PWD/.cache`; `.cache/` is ignored.

## 11. Required backend, frontend, and QA test matrix

- **Backend models/month math**: reject malformed months, year 9999, legacy `planning_start`, and legacy `horizon_days`; accept/round-trip `SelectedMonth`; derive exact boundaries and day counts for leap February `2024-02` (29), non-leap February `2025-02` (28), `2026-04` (30), `2026-03` (31), and December rollover; preserve canonical `Asia/Seoul` tzinfo.
- **Backend validation**: relative-date context, confidence/uncertainty gating, defaults/provenance, overlapping availability union, fixed-event warnings, deterministic work-ID length rejection, and `ValidationReport` JSON round trips that preserve `context.selected_month`. Assert every fully outside and clipped task/routine/availability/fixed-event outcome and severity exactly; prove no item disappears without a diagnostic or `UnscheduledWork` where required.
- **Backend scheduler**: zero overlap; selected-month containment; availability containment; fixed-event intersection/exclusion; deadline compliance including deadlines after month end; routine occurrences only in month; routine-first ordering across a 31-day horizon; deterministic repeated output; split/min/max/daily caps; stable ordering; exact statistics; every infeasibility reason; 1,488-slot/block upper bound; four-digit sequence and 59-character maximum generated ID; malformed result fail-closed validation.
- **Extraction/service**: fake LCEL input receives selected month and exact derived bounds; malformed/refused/provider failure maps to a sanitized diagnostic; draft -> confirmation -> request -> result preserves the month; month/edit changes invalidate confirmation/result. No live API, class/shared key, or Hermes/Codex OAuth is used in tests or CI.
- **Frontend component/contract**: month input defaults from Seoul now and is editable; 28/29/30/31-day months render; Monday-first four-natural-week February is padded to five rows; `2026-03` renders 42 cells over six rows; adjacent cells are muted and event-free; fixed events split/clip correctly; deterministic event ordering/labels/ARIA text; Month is default and detailed/unscheduled tabs remain reachable; changing month clears stale output.
- **Frontend design/accessibility**: lint `DESIGN.md` with `npx -y @google/design.md lint DESIGN.md` or documented equivalent; automated WCAG AA contrast checks cover text, chips, controls, focus, error/warning states; keyboard-only month navigation, tabs, event overflow, and focus order; category recognition without color; no horizontal clipping. Capture desktop and mobile screenshots for visual review and check grayscale plus common color-vision simulations.
- **QA end to end**: clean keyless install; pytest, coverage, Ruff, mypy, and pip integrity; canonical fixture through real loopback Gradio; February leap/non-leap and 30/31-day probes; outside-horizon matrix; deterministic repeat; month change invalidation; responsive screenshots at representative desktop/mobile widths; DOM/config/accessibility inspection; no provider traffic, secret leakage, persistence, or unsupported optimality claim.

Tests assert invariants and totals directly rather than relying only on timestamp snapshots or screenshots. Coverage is informative; correctness of the listed properties and visual/accessibility gates is required.

## 12. Canonical Korean demo

Fixture context:

- `reference_datetime`: `2026-03-02T09:00:00+09:00` with the canonical `Asia/Seoul` zone
- `selected_month`: `{"year": 2026, "month": 3}`
- horizon: `[2026-03-01T00:00:00+09:00, 2026-04-01T00:00:00+09:00)` (31 days, 1,488 possible grid slots)
- Monday-first calendar: six rows, `2026-02-23` through `2026-04-05`; adjacent cells have no events

Canonical input:

```text
3월 13일 금요일 오후 10시까지 포트폴리오를 다듬는 데 총 6시간이 필요해. 30분 단위로 나눠도 되고 하루에는 최대 2시간만 해줘. 우선순위는 4야.
3월 10일 화요일 오후 6시까지 코딩 테스트 준비 4시간을 넣어줘. 1시간씩 나눌 수 있고 우선순위는 5야.
면접 연습은 3월 2일부터 3월 13일까지 매주 월·수·금 저녁 7시부터 9시 사이에 1시간씩 해야 해.
가능한 시간은 평일 저녁 7시부터 10시, 토요일 오전 9시부터 12시야.
3월 4일 수요일 저녁 7시부터 8시는 스터디가 이미 잡혀 있어.
```

Expected properties, deliberately not exact block timestamps:

1. Two deadline tasks are extracted: portfolio due Friday 2026-03-13 22:00 KST and coding-test preparation due Tuesday 2026-03-10 18:00 KST.
2. The explicitly bounded M/W/F interview routine creates six expected occurrences from March 2 through March 13, each one hour within 19:00-21:00 on its occurrence date; extending the planning month does not invent occurrences after its `end_date`.
3. Availability contains weekday evenings and Saturday mornings. No generated block is outside those windows.
4. The Wednesday 2026-03-04 19:00-20:00 fixed event is preserved and no generated block overlaps it; routine-first allocation places that day's occurrence in the other legal hour in its 19:00-21:00 window.
5. All coding-test blocks end by its Tuesday deadline and all portfolio blocks end by its Friday deadline. Portfolio blocks obey its two-hour per-work daily cap. Splits align to 30 minutes.
6. All six constrained routine occurrences are materialized and allocated first; deadline-task work is then ordered by the normative deadline-task rules. Reserving those six hard-window hours before using remaining capacity makes the fixture fully schedulable. Expected totals remain 13 blocks (six routine blocks plus seven task blocks), requested 960 minutes, scheduled 960 minutes, unscheduled 0 minutes, and `is_fully_scheduled=true`. Tests assert these totals and invariants rather than fragile exact starts.
7. Adding enough fixed conflicts to remove pre-deadline capacity produces `NO_CAPACITY_BEFORE_DEADLINE`; blocking a routine's complete hard window produces `NO_MATCHING_ROUTINE_WINDOW`. Neither case creates overlaps or silently drops work.

## 13. Migration and backward compatibility decision

This selected-month contract intentionally makes one clean, source-breaking schema migration. The reviewed implementation at baseline `767fc1ac4a4ae38351cfb925ec29eb91ef2162ef` used a rolling interface with `planning_start` and fixed `horizon_days=14`; those names and values are historical migration facts only and are not valid inputs after the backend migration.

- Replace `ParseContext.planning_start` with required `ParseContext.selected_month: SelectedMonth`.
- Replace `ScheduleRequest.planning_start` with required `ScheduleRequest.selected_month` and remove `horizon_days` entirely.
- Do not accept aliases, deprecation shims, inferred month-from-date behavior, or ignored legacy extras. `extra="forbid"` must reject both legacy fields so an arbitrary rolling start cannot be mistaken for a month.
- Update the canonical fixture context atomically to `"selected_month": {"year": 2026, "month": 3}`. Update all constructors, fake extraction assertions, serialized report/request fixtures, and UI state in the same backend/frontend sequence.
- Existing saved browser/session payloads are not migrated because persistence is out of scope; a refresh clears in-memory state by design. This avoids dual-schema complexity without breaking any durable user data.
- Until downstream implementation completes, current source, tests, and README describe the historical reviewed rolling baseline and are not the normative product contract. This document is the sole normative target for the migration.

## 14. Downstream ownership and serial delivery

Implementation is serial because the month schema is shared. No frontend or QA card should independently choose another representation.

1. **Backend phase — `backend-engineer`** owns `src/jobflow/models.py`, `src/jobflow/validation.py`, `src/jobflow/scheduler.py`, `src/jobflow/extraction.py`, `src/jobflow/services.py`, `tests/fixtures/canonical_demo.json`, `tests/test_models.py`, `tests/test_validation.py`, `tests/test_scheduler.py`, `tests/test_extraction.py`, and `tests/test_services.py`. It implements `SelectedMonth`, month-bound derivation, the outside-month contract, revised bounds/statistics/IDs, service propagation, and backend tests. It must not redesign the Gradio result UI.
2. **Frontend phase — `frontend-engineer`, parented by approved backend** owns root `DESIGN.md`, `README.md`, `src/jobflow/ui.py`, `src/jobflow/app.py` only if composition/launch wiring is required, `tests/test_ui_smoke.py`, and any narrowly scoped UI accessibility/visual test assets. It consumes the approved shared types, adds the month selector and calendar projection, preserves secondary views, applies the design system, runs design/WCAG lint, and records desktop/mobile screenshots. It must not redefine scheduler models or month semantics.
3. **QA/security phase — `qa-security-engineer`, parented by approved frontend** owns no product files. It independently runs the complete matrix in section 11, real keyless loopback UI behavior, responsive visual/accessibility checks, privacy/network/secret checks, and Git provenance/cleanliness. Defects route to the owning phase; QA does not patch them.

The serial dependency graph is `architecture approval -> backend implementation + same-card review -> frontend/design implementation + same-card review -> independent QA/security + review`. `models.py`, the canonical fixture, `ui.py`, `README.md`, and `DESIGN.md` are collision hotspots and must have only the owner named above during their phase.

## 15. Delivery risks and deferred options

- Korean date ambiguity and provider variance are contained by visible context, structured output, field provenance, explicit confirmation, and fake-based tests.
- The greedy scheduler is deterministic and explainable but not globally optimal. OR-Tools CP-SAT is the documented fallback behind the same API if later requirements demand maximizing scheduled minutes or rearrangement.
- Gradio may require custom CSS/HTML composition for an accessible responsive month grid. Framework convenience does not waive keyboard, contrast, clipping, or event-readability acceptance gates.
- The DESIGN.md specification/CLI is alpha and may change; pin or record the resolved CLI version and use the documented equivalent automated WCAG gate only if necessary.
- Dependency APIs, especially Gradio and LangChain, may shift within allowed majors; implementation should pin a resolved environment after the first verified install without widening the contract casually.
- In-memory Gradio state means refresh loses work by design.
- The OpenAI provider receives user-entered text and can incur cost; disclosure, explicit click, one call, and no persistence are mandatory.
