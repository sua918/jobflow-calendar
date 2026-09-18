# JobFlow MVP architecture and shared contracts

Status: architecture gate for `feature/jobflow-mvp`
Scope: a 1.5-day course MVP; this document is normative for backend and frontend work.

## 1. Product boundary and architectural decision

JobFlow accepts Korean free text describing job-search preparation work, extracts an editable structured draft, validates the user's confirmed values, and produces a conflict-free two-week plan in a Gradio UI. It supports hard-deadline tasks and recurring routines and always exposes work it could not schedule.

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

Likely collision hotspots are `models.py`, `services.py`, `ui.py`, `pyproject.toml`, and `README.md`; assign exactly one implementation owner for each. Do not duplicate models in UI code.

## 3. Time and identity rules

- The sole MVP timezone is the IANA zone `Asia/Seoul`, represented with `zoneinfo.ZoneInfo`. Do not use a fixed `+09:00` object as the canonical zone.
- All persisted/inter-module datetimes are timezone-aware and normalized to `Asia/Seoul`. Naive datetimes are rejected at the confirmed-data boundary.
- UI date/time inputs are interpreted as Seoul local time, displayed with the `KST` label, and combined with `ZoneInfo("Asia/Seoul")` before model construction.
- Intervals are half-open: `[start, end)`. Therefore one block ending when another begins does not overlap.
- `planning_start` is a Seoul local `date`. The horizon is `[planning_start 00:00, planning_start + 14 days 00:00)`.
- `horizon_days` is exactly 14 and `slot_minutes` is exactly 30 in the MVP. Starts, ends, deadlines, durations, and time-window boundaries must align to a 30-minute grid. The only exception is raw LLM draft text, which cannot enter the scheduler until corrected/normalized and confirmed.
- IDs are stable, UI-safe strings matching `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`. Extraction creates deterministic IDs in input order (`task-01`, `routine-01`, `fixed-01`); edits preserve them.

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
    id: str
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
    id: str
    title: str
    duration_minutes: int             # per occurrence
    weekdays: set[Weekday]
    window: LocalTimeWindow           # hard allowed window for each occurrence
    start_date: date | None = None
    end_date: date | None = None      # inclusive
    priority: int = 3                 # 1 lowest, 5 highest; tie-break only
    required: bool = True
    provenance: SourceProvenance

class ParseContext(BaseModel):
    reference_datetime: datetime      # aware Asia/Seoul; resolves relative Korean dates
    planning_start: date
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

class ScheduleRequest(BaseModel):
    planning_start: date
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    horizon_days: Literal[14] = 14
    slot_minutes: Literal[30] = 30
    daily_work_cap_minutes: int = 240 # task/routine blocks only; fixed events excluded
    deadline_tasks: list[DeadlineTask] = []
    recurring_routines: list[RecurringRoutine] = []
    availability: list[AvailabilityRule]
    fixed_events: list[FixedEvent] = []

class ScheduleBlock(BaseModel):
    id: str                           # block-{work_id}-{01-based sequence}
    work_id: str
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

`to_schedule_request` raises `ConfirmationRequiredError` if `ready_to_schedule` is false. `schedule_confirmed` must run `validate_schedule` and treat any error-severity diagnostic as an internal correctness failure rather than showing an apparently valid plan.

## 5. Deterministic validation invariants

Validation returns diagnostics for expected input problems; it does not silently repair meaning.

1. IDs are unique across tasks, routines, availability, and fixed events.
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
13. Work wholly outside the horizon is not dropped: it produces `UnscheduledWork(OUTSIDE_HORIZON)`.
14. A valid result has blocks entirely inside the horizon and availability union; no block overlaps a fixed event or another block; every task block ends no later than its deadline; every routine block has the required weekday/occurrence date and lies within its hard routine window; per-work and global daily caps hold; total durations and stats reconcile exactly.

Stable diagnostic codes include `EXTRACTION_FAILED`, `SCHEMA_INVALID`, `CONFIRMATION_REQUIRED`, `NO_AVAILABILITY`, `OUTSIDE_HORIZON`, `INVALID_TIMEZONE`, `MISALIGNED_TIME`, `OVERLAPPING_FIXED_EVENTS`, `NO_CAPACITY_BEFORE_DEADLINE`, `NO_MATCHING_ROUTINE_WINDOW`, `DAILY_CAP_EXCEEDED`, and `INTERNAL_SCHEDULE_INVALID`.

## 6. LangChain boundary and ambiguity policy

Use a small LCEL chain equivalent to:

```python
prompt | ChatOpenAI(model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"), temperature=0).with_structured_output(ExtractionDraft)
```

The prompt receives the exact user text, `reference_datetime`, horizon dates, timezone, and the documented defaults. It must quote input evidence into each `SourceProvenance`, put uncertain field paths in `uncertain_fields`, and never fabricate missing deadlines, duration, recurrence days, or availability. There is no agent, tool loop, memory, or second model call on the scheduling path.

`extract_draft` catches provider/network/refusal/structured-output failures at the boundary and maps them to the service-level `EXTRACTION_FAILED` diagnostic; logs must not include the user's raw text or API key. Tests inject a fake runnable and make no network calls.

A deterministic Korean template in `explain_result_ko` is the required explanation path and is generated solely from `ScheduleResult`. A future optional LLM rephrase may receive only the already-computed summary, may not change facts, and must fall back to the deterministic text. It is not part of MVP acceptance.

If no `OPENAI_API_KEY` is configured, the UI remains launchable and shows a clear extraction-unavailable message; users may still load/edit the canonical structured demo. No key is embedded or sent to the browser.

## 7. Scheduling policy

Decision: implement a transparent greedy scheduler, not OR-Tools, for the 1.5-day MVP. The problem is small (14 days × 48 slots), a deterministic heuristic is easy to test and explain, and OR-Tools adds package size, solver modeling, and debugging risk without an optimization requirement. If the greedy result is too restrictive in a later phase, preserve the same `build_schedule` contract and replace only `scheduler.py` with CP-SAT; `ScheduleResult` and validation remain unchanged.

Normative algorithm:

1. Expand availability into unique 30-minute slots within the horizon. Subtract the union of fixed-event intervals. Track the global scheduled-work minutes per local day.
2. Schedule deadline tasks first because their deadlines are hard. Sort by `(deadline ascending, priority descending, id ascending)`.
3. For each task, consider slots at/after `earliest_start` (or horizon start), strictly before/equal to its deadline, and inside availability. Preferred windows are soft: candidate free runs inside a preferred window sort before nonpreferred runs; ties sort by start datetime ascending.
4. Non-splittable work requires one contiguous run for its full duration. Splittable work uses deterministic chunks no larger than `max_block_minutes`, no smaller than `min_block_minutes`, and never leaves a positive remainder smaller than `min_block_minutes`. Among equal candidates, choose the longest legal chunk, then the earliest start. Enforce the task-specific and global daily caps before committing each chunk.
5. Generate one routine occurrence for every matching weekday/local date intersecting the routine date range and horizon. After task placement, sort occurrences by `(occurrence_date ascending, priority descending, routine id ascending)`. An occurrence must be one contiguous block entirely inside both its hard `window` and availability and must respect the global daily cap. Pick the earliest legal start. `required=false` changes message severity to warning but does not change placement order.
6. Never move/delete fixed events or already placed blocks to make a later item fit. Never place work outside availability, the horizon, a deadline, or a routine window.
7. For every partial/failed task or occurrence, append one `UnscheduledWork` with exact requested/scheduled/remaining minutes and the most specific reason. Use capacity calculations in `details` (for example available minutes before deadline and cap-limited minutes); do not claim only “failed”. A partially scheduled deadline task still makes `is_fully_scheduled=false`.
8. Sort final blocks by `(start, end, id)` and unscheduled entries by `(work_id, occurrence_date or date.min, reason)`. Compute stats from requested occurrences and actual blocks, then call `validate_schedule`.

Priority never overrides an earlier hard deadline. Preferred task times are soft and may be violated to meet a deadline; routine windows are hard. Fixed events and all generated blocks are hard non-overlap constraints. The overall daily cap counts only generated task/routine minutes; fixed events merely remove capacity.

This greedy policy is complete with respect to reporting, not globally optimal. The UI must say “규칙 기반 일정” rather than “최적 일정”. The known risk is that an alternative rearrangement could schedule more work; `UnscheduledWork` makes that limitation explicit.

## 8. Gradio event and data flow

Use `gr.Blocks` with server-side Pydantic JSON in `gr.State`; Dataframes are editable projections, not the source of truth.

1. **Parse**: user text + visible reference datetime/planning start -> `parse_for_review` -> editable task, routine, availability, and fixed-event tables plus diagnostics. Disable Schedule.
2. **Review/edit**: every table change rebuilds an `ExtractionDraft`, sets edited fields to user provenance, and calls `validate_draft`. Render field-level Korean diagnostics. Enable Schedule only when `ready_to_schedule=true` and the user checks an explicit “검토 완료” checkbox.
3. **Schedule**: confirmed report -> `to_schedule_request` -> `schedule_confirmed`. This event is deterministic and performs no model call.
4. **Render**: show blocks in a two-week day-grouped timeline/table with title, kind, start, end, and duration. Show unscheduled work in a separate always-visible table with exact reason and remaining minutes. Show deterministic Korean summary and stats. No claim of optimality.
5. **Edit again**: any input/table edit invalidates the prior result, unchecks confirmation, and disables Schedule until revalidated.

Callbacks return explicit view-model tuples; they do not mutate module globals. One browser session uses its own `gr.State`. The app has no persistence: refresh/process exit clears user data.

## 9. Error model, privacy, secrets, and cost

Expected user/provider errors become `Diagnostic` entries and Korean UI messages. Programming invariant failures raise an internal exception, are logged without raw user text, and become generic `INTERNAL_SCHEDULE_INVALID` at the UI boundary. Do not expose stack traces or provider payloads in Gradio.

`.env` is local-only and listed in `.gitignore`; commit only `.env.example` containing blank `OPENAI_API_KEY=` and `OPENAI_MODEL=gpt-4.1-mini`. Load with `python-dotenv` in `app.py`. Never log, serialize to Gradio state, commit, or return the key. Also ignore `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`, `htmlcov/`, `.coverage`, `__pycache__/`, and generated output.

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

## 11. Testing layers and acceptance properties

- **Models**: every boundary, timezone, grid, enum, uniqueness, and discriminated-kind rule; extra fields rejected.
- **Validation**: relative-date context, confidence/uncertainty gating, defaults/provenance, overlapping availability union, fixed-event warnings, and table round trips.
- **Scheduler unit/property tests**: zero overlap; availability containment; fixed-event exclusion; deadline compliance; recurrence day/window; deterministic output for identical input; split/min/max/daily caps; stable ordering; exact statistics; each infeasibility reason.
- **Extraction contract**: fake LCEL runnable returns structured Korean examples; malformed/refused/provider failure maps to a diagnostic; no live API in CI.
- **Service integration**: draft -> confirmation -> request -> result; edits invalidate confirmation; validator catches a deliberately malformed result.
- **UI smoke**: `build_app()` constructs without a key; canonical structured demo can schedule; missing-key Parse has a safe message. QA launches the app on loopback, verifies real HTTP readiness, and exercises the canonical and infeasible cases.

A scheduler test must assert every invariant directly rather than relying on snapshots of exact timestamps. Coverage is informative; correctness of the listed invariant tests is the gate.

## 12. Canonical Korean demo

Fixture context:

- `reference_datetime`: `2026-03-02T09:00:00+09:00` with the canonical `Asia/Seoul` zone
- `planning_start`: `2026-03-02` (Monday)
- horizon: through but excluding `2026-03-16T00:00:00+09:00`

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
2. The M/W/F interview routine creates six expected occurrences over the two weeks, each one hour within 19:00-21:00 on its occurrence date.
3. Availability contains weekday evenings and Saturday mornings. No generated block is outside those windows.
4. The Wednesday 2026-03-04 19:00-20:00 fixed event is preserved and no generated block overlaps it; that day's routine may use another legal hour in its window or is reported unscheduled with a specific reason.
5. All coding-test blocks end by its Tuesday deadline and all portfolio blocks end by its Friday deadline. Portfolio blocks obey its two-hour per-work daily cap. Splits align to 30 minutes.
6. Deadline work is placed before routine occurrences under the normative policy. With the stated capacity the fixture is expected to be fully schedulable, but tests assert invariants and requested minutes rather than fragile exact starts.
7. Adding enough fixed conflicts to remove pre-deadline capacity produces `NO_CAPACITY_BEFORE_DEADLINE`; blocking a routine's complete hard window produces `NO_MATCHING_ROUTINE_WINDOW`. Neither case creates overlaps or silently drops work.

## 13. Delivery risks and deferred options

- Korean date ambiguity and provider variance are contained by visible context, structured output, field provenance, explicit confirmation, and fake-based tests.
- The greedy scheduler is deterministic and explainable but not globally optimal. OR-Tools CP-SAT is the documented fallback behind the same API if later requirements demand maximizing scheduled minutes or rearrangement.
- Dependency APIs, especially Gradio and LangChain, may shift within allowed majors; implementation should pin a resolved environment after the first verified install without widening the contract casually.
- In-memory Gradio state means refresh loses work by design.
- The OpenAI provider receives user-entered text and can incur cost; disclosure, explicit click, one call, and no persistence are mandatory.
