from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

RAW_INPUT_MAX_CHARS = 10_000
HUMAN_TEXT_MAX_CHARS = 200
SOURCE_TEXT_MAX_CHARS = 1_000
PROVENANCE_ITEMS_MAX = 32
UNCERTAIN_FIELD_MAX_CHARS = 64
ASSUMPTION_MAX_CHARS = 200
PREFERRED_WINDOWS_MAX_ITEMS = 16
DEADLINE_TASKS_MAX_ITEMS = 50
RECURRING_ROUTINES_MAX_ITEMS = 50
AVAILABILITY_MAX_ITEMS = 50
FIXED_EVENTS_MAX_ITEMS = 100

SafeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
WorkId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")]
NonBlank = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=HUMAN_TEXT_MAX_CHARS,
    ),
]
SourceText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=SOURCE_TEXT_MAX_CHARS),
]
UncertainField = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=UNCERTAIN_FIELD_MAX_CHARS),
]
Assumption = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=ASSUMPTION_MAX_CHARS),
]
KST = ZoneInfo("Asia/Seoul")


def _with_default_assumptions(
    provenance: SourceProvenance,
    assumptions: list[str],
) -> SourceProvenance:
    if not assumptions:
        return provenance
    combined_assumptions = [*provenance.assumptions]
    combined_assumptions.extend(
        assumption for assumption in assumptions if assumption not in combined_assumptions
    )
    return SourceProvenance.model_validate(
        {
            **provenance.model_dump(),
            "extraction_method": ExtractionMethod.DEFAULT,
            "assumptions": combined_assumptions,
        }
    )


def _to_seoul(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(KST)


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class ExtractionMethod(str, Enum):
    LLM = "llm"
    USER = "user"
    DEFAULT = "default"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class WorkKind(str, Enum):
    DEADLINE_TASK = "deadline_task"
    RECURRING_ROUTINE = "recurring_routine"


class BlockKind(str, Enum):
    TASK = "task"
    ROUTINE = "routine"


class UnscheduledReason(str, Enum):
    CONFIRMATION_REQUIRED = "confirmation_required"
    OUTSIDE_HORIZON = "outside_horizon"
    NO_AVAILABILITY = "no_availability"
    NO_CAPACITY_BEFORE_DEADLINE = "no_capacity_before_deadline"
    NO_MATCHING_ROUTINE_WINDOW = "no_matching_routine_window"
    DAILY_CAP_EXCEEDED = "daily_cap_exceeded"
    FIXED_EVENT_CONFLICT = "fixed_event_conflict"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceProvenance(StrictModel):
    source_text: SourceText
    extraction_method: ExtractionMethod
    confidence: float = Field(ge=0.0, le=1.0)
    uncertain_fields: list[UncertainField] = Field(
        default_factory=list,
        max_length=PROVENANCE_ITEMS_MAX,
    )
    assumptions: list[Assumption] = Field(
        default_factory=list,
        max_length=PROVENANCE_ITEMS_MAX,
    )


class LocalTimeWindow(StrictModel):
    start: time
    end: time

    @model_validator(mode="after")
    def ordered(self) -> LocalTimeWindow:
        if self.start >= self.end:
            raise ValueError("time window must have start before end")
        return self


class AvailabilityRule(StrictModel):
    id: SafeId
    weekdays: set[Weekday] = Field(min_length=1)
    window: LocalTimeWindow
    valid_from: date | None = None
    valid_through: date | None = None
    provenance: SourceProvenance

    @model_validator(mode="after")
    def ordered_dates(self) -> AvailabilityRule:
        if self.valid_from and self.valid_through and self.valid_from > self.valid_through:
            raise ValueError("availability date bounds are reversed")
        return self


class FixedEvent(StrictModel):
    id: SafeId
    title: NonBlank
    start: datetime
    end: datetime
    provenance: SourceProvenance

    @field_validator("start", "end")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        return _to_seoul(value)

    @model_validator(mode="after")
    def ordered(self) -> FixedEvent:
        if self.start >= self.end:
            raise ValueError("fixed event must have start before end")
        return self


class DeadlineTask(StrictModel):
    kind: Literal["deadline_task"] = "deadline_task"
    id: WorkId
    title: NonBlank
    duration_minutes: int = Field(gt=0)
    deadline: datetime
    earliest_start: datetime | None = None
    priority: int = Field(default=3, ge=1, le=5)
    splittable: bool = True
    min_block_minutes: int = Field(default=30, gt=0)
    max_block_minutes: int = Field(default=120, gt=0)
    daily_cap_minutes: int = Field(default=240, gt=0)
    preferred_windows: list[LocalTimeWindow] = Field(
        default_factory=list,
        max_length=PREFERRED_WINDOWS_MAX_ITEMS,
    )
    provenance: SourceProvenance

    @field_validator("deadline", "earliest_start")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _to_seoul(value)

    @model_validator(mode="after")
    def work_bounds(self) -> DeadlineTask:
        defaults = {
            "priority": "priority=3",
            "splittable": "splittable=true",
            "min_block_minutes": "min_block_minutes=30",
            "max_block_minutes": "max_block_minutes=120",
            "daily_cap_minutes": "daily_cap_minutes=240",
        }
        self.provenance = _with_default_assumptions(
            self.provenance,
            [
                assumption
                for field, assumption in defaults.items()
                if field not in self.model_fields_set
            ],
        )
        if self.min_block_minutes > self.max_block_minutes:
            raise ValueError("min block exceeds max block")
        if self.max_block_minutes > self.daily_cap_minutes:
            raise ValueError("max block exceeds daily cap")
        if self.earliest_start and self.earliest_start >= self.deadline:
            raise ValueError("earliest start must precede deadline")
        if not self.splittable and (
            self.duration_minutes > self.max_block_minutes
            or self.duration_minutes > self.daily_cap_minutes
        ):
            raise ValueError("non-splittable work does not fit its limits")
        return self


class RecurringRoutine(StrictModel):
    kind: Literal["recurring_routine"] = "recurring_routine"
    id: WorkId
    title: NonBlank
    duration_minutes: int = Field(gt=0)
    weekdays: set[Weekday] = Field(min_length=1)
    window: LocalTimeWindow
    start_date: date | None = None
    end_date: date | None = None
    priority: int = Field(default=3, ge=1, le=5)
    required: bool = True
    provenance: SourceProvenance

    @model_validator(mode="after")
    def ordered_dates(self) -> RecurringRoutine:
        if "priority" not in self.model_fields_set:
            self.provenance = _with_default_assumptions(self.provenance, ["priority=3"])
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("routine date bounds are reversed")
        return self


class SelectedMonth(StrictModel):
    year: int = Field(ge=1, le=9998)
    month: int = Field(ge=1, le=12)


def month_bounds(selected_month: SelectedMonth) -> tuple[datetime, datetime]:
    """Return the exact half-open Asia/Seoul range for a selected month."""
    start = datetime(selected_month.year, selected_month.month, 1, tzinfo=KST)
    if selected_month.month == 12:
        end = datetime(selected_month.year + 1, 1, 1, tzinfo=KST)
    else:
        end = datetime(selected_month.year, selected_month.month + 1, 1, tzinfo=KST)
    return start, end


class ParseContext(StrictModel):
    reference_datetime: datetime
    selected_month: SelectedMonth
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"

    @field_validator("reference_datetime")
    @classmethod
    def canonical_seoul(cls, value: datetime) -> datetime:
        return _to_seoul(value)


class ExtractionDraft(StrictModel):
    deadline_tasks: list[DeadlineTask] = Field(
        default_factory=list,
        max_length=DEADLINE_TASKS_MAX_ITEMS,
    )
    recurring_routines: list[RecurringRoutine] = Field(
        default_factory=list,
        max_length=RECURRING_ROUTINES_MAX_ITEMS,
    )
    availability: list[AvailabilityRule] = Field(
        default_factory=list,
        max_length=AVAILABILITY_MAX_ITEMS,
    )
    fixed_events: list[FixedEvent] = Field(
        default_factory=list,
        max_length=FIXED_EVENTS_MAX_ITEMS,
    )


DetailValue = str | int | float | bool | None


class Diagnostic(StrictModel):
    code: Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]*$")]
    severity: Severity
    message_ko: NonBlank
    entity_id: str | None = None
    field: str | None = None
    details: dict[str, DetailValue] = Field(default_factory=dict)


class ValidationReport(StrictModel):
    normalized: ExtractionDraft | None
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    ready_to_schedule: bool
    context: ParseContext


class ScheduleRequest(StrictModel):
    selected_month: SelectedMonth
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    slot_minutes: Literal[30] = 30
    daily_work_cap_minutes: int = Field(default=240, gt=0, multiple_of=30)
    deadline_tasks: list[DeadlineTask] = Field(
        default_factory=list,
        max_length=DEADLINE_TASKS_MAX_ITEMS,
    )
    recurring_routines: list[RecurringRoutine] = Field(
        default_factory=list,
        max_length=RECURRING_ROUTINES_MAX_ITEMS,
    )
    availability: list[AvailabilityRule] = Field(
        min_length=1,
        max_length=AVAILABILITY_MAX_ITEMS,
    )
    fixed_events: list[FixedEvent] = Field(
        default_factory=list,
        max_length=FIXED_EVENTS_MAX_ITEMS,
    )


class ScheduleBlock(StrictModel):
    id: SafeId
    work_id: SafeId
    title: NonBlank
    kind: BlockKind
    start: datetime
    end: datetime
    occurrence_date: date | None = None

    @field_validator("start", "end")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        return _to_seoul(value)

    @model_validator(mode="after")
    def ordered(self) -> ScheduleBlock:
        if self.start >= self.end:
            raise ValueError("schedule block must have start before end")
        return self


class UnscheduledWork(StrictModel):
    work_id: SafeId
    title: NonBlank
    kind: WorkKind
    reason: UnscheduledReason
    requested_minutes: int = Field(gt=0)
    scheduled_minutes: int = Field(ge=0)
    remaining_minutes: int = Field(ge=0)
    occurrence_date: date | None = None
    message_ko: NonBlank
    details: dict[str, DetailValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reconciled(self) -> UnscheduledWork:
        if self.scheduled_minutes + self.remaining_minutes != self.requested_minutes:
            raise ValueError("unscheduled minute fields do not reconcile")
        if self.remaining_minutes == 0:
            raise ValueError("unscheduled work must have remaining minutes")
        return self


class ScheduleStats(StrictModel):
    requested_minutes: int = Field(ge=0)
    scheduled_minutes: int = Field(ge=0)
    unscheduled_minutes: int = Field(ge=0)

    @model_validator(mode="after")
    def reconciled(self) -> ScheduleStats:
        if self.scheduled_minutes + self.unscheduled_minutes != self.requested_minutes:
            raise ValueError("schedule stats do not reconcile")
        return self


class ScheduleResult(StrictModel):
    blocks: list[ScheduleBlock] = Field(default_factory=list)
    unscheduled: list[UnscheduledWork] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)
    stats: ScheduleStats
    is_fully_scheduled: bool


CalendarViewId = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,83}$"),
]


class CalendarEventView(StrictModel):
    view_id: CalendarViewId
    source_id: SafeId
    work_id: WorkId | None
    category: Literal["deadline_task", "recurring_routine", "fixed_event"]
    category_label_ko: NonBlank
    title: NonBlank
    segment_date: date
    segment_start: datetime
    segment_end: datetime
    original_start: datetime
    original_end: datetime
    duration_minutes: int = Field(gt=0)
    starts_before_segment: bool
    ends_after_segment: bool
    aria_label_ko: NonBlank

    @field_validator("segment_start", "segment_end", "original_start", "original_end")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        return _to_seoul(value)

    @model_validator(mode="after")
    def validate_segment(self) -> CalendarEventView:
        if self.segment_start >= self.segment_end:
            raise ValueError("calendar segment must have start before end")
        if self.segment_start.date() != self.segment_date:
            raise ValueError("calendar segment date must match its start")
        if self.original_start > self.segment_start or self.segment_end > self.original_end:
            raise ValueError("calendar segment must be inside its original interval")
        actual = int((self.segment_end - self.segment_start).total_seconds() // 60)
        if actual != self.duration_minutes:
            raise ValueError("calendar segment duration must match its interval")
        return self


class CalendarDayCell(StrictModel):
    date: date
    in_selected_month: bool
    is_today: bool
    weekday: Weekday
    events: list[CalendarEventView] = Field(default_factory=list)


class CalendarMonthView(StrictModel):
    selected_month: SelectedMonth
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    horizon_start: datetime
    horizon_end: datetime
    week_starts_on: Literal["MON"] = "MON"
    row_count: Literal[5, 6]
    days: list[CalendarDayCell]

    @field_validator("horizon_start", "horizon_end")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        return _to_seoul(value)

    @model_validator(mode="after")
    def validate_grid(self) -> CalendarMonthView:
        if len(self.days) != self.row_count * 7:
            raise ValueError("calendar grid size must match row count")
        return self
