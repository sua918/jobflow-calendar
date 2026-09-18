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

SafeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
WorkId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
KST = ZoneInfo("Asia/Seoul")


def _with_default_assumptions(
    provenance: SourceProvenance,
    assumptions: list[str],
) -> SourceProvenance:
    if not assumptions:
        return provenance
    return provenance.model_copy(
        update={
            "extraction_method": ExtractionMethod.DEFAULT,
            "assumptions": [*provenance.assumptions, *assumptions],
        },
        deep=True,
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
    source_text: NonBlank
    extraction_method: ExtractionMethod
    confidence: float = Field(ge=0.0, le=1.0)
    uncertain_fields: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


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
    preferred_windows: list[LocalTimeWindow] = Field(default_factory=list)
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


class ParseContext(StrictModel):
    reference_datetime: datetime
    planning_start: date
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"

    @field_validator("reference_datetime")
    @classmethod
    def canonical_seoul(cls, value: datetime) -> datetime:
        return _to_seoul(value)


class ExtractionDraft(StrictModel):
    deadline_tasks: list[DeadlineTask] = Field(default_factory=list)
    recurring_routines: list[RecurringRoutine] = Field(default_factory=list)
    availability: list[AvailabilityRule] = Field(default_factory=list)
    fixed_events: list[FixedEvent] = Field(default_factory=list)


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
    planning_start: date
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"
    horizon_days: Literal[14] = 14
    slot_minutes: Literal[30] = 30
    daily_work_cap_minutes: int = Field(default=240, gt=0, multiple_of=30)
    deadline_tasks: list[DeadlineTask] = Field(default_factory=list)
    recurring_routines: list[RecurringRoutine] = Field(default_factory=list)
    availability: list[AvailabilityRule] = Field(min_length=1)
    fixed_events: list[FixedEvent] = Field(default_factory=list)


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
