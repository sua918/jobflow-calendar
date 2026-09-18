from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from jobflow.models import (
    AvailabilityRule,
    DeadlineTask,
    Diagnostic,
    ExtractionDraft,
    ParseContext,
    RecurringRoutine,
    ScheduleRequest,
    Severity,
    SourceProvenance,
    ValidationReport,
)

KST = ZoneInfo("Asia/Seoul")
SLOT_MINUTES = 30


class ConfirmationRequiredError(ValueError):
    """Raised when an unconfirmed or invalid report is scheduled."""


def _diagnostic(
    code: str,
    message: str,
    *,
    entity_id: str | None = None,
    field: str | None = None,
    severity: Severity = Severity.ERROR,
    details: dict[str, str | int | float | bool | None] | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=severity,
        message_ko=message,
        entity_id=entity_id,
        field=field,
        details=details or {},
    )


def _is_seoul(value: datetime) -> bool:
    return value.tzinfo is not None and getattr(value.tzinfo, "key", None) == "Asia/Seoul"


def _datetime_diagnostics(
    value: datetime,
    entity_id: str,
    field: str,
) -> list[Diagnostic]:
    result: list[Diagnostic] = []
    if not _is_seoul(value):
        result.append(
            _diagnostic(
                "INVALID_TIMEZONE",
                "날짜와 시간은 Asia/Seoul 시간대로 확인해 주세요.",
                entity_id=entity_id,
                field=field,
            )
        )
    if value.minute % SLOT_MINUTES or value.second or value.microsecond:
        result.append(
            _diagnostic(
                "MISALIGNED_TIME",
                "시간은 30분 단위에 맞춰 주세요.",
                entity_id=entity_id,
                field=field,
            )
        )
    return result


def _time_aligned(value: time) -> bool:
    return value.minute % SLOT_MINUTES == 0 and value.second == 0 and value.microsecond == 0


def _provenance_diagnostics(
    provenance: SourceProvenance,
    entity_id: str,
    critical_fields: set[str],
) -> list[Diagnostic]:
    uncertain = {
        field
        for path in provenance.uncertain_fields
        for field in critical_fields
        if field in path.split(".")
    }
    if provenance.confidence >= 0.70 and not uncertain:
        return []
    return [
        _diagnostic(
            "CONFIRMATION_REQUIRED",
            "중요한 항목을 사용자가 확인해야 일정을 만들 수 있어요.",
            entity_id=entity_id,
            field=",".join(sorted(uncertain)) or None,
            details={"confidence": provenance.confidence},
        )
    ]


def _window_diagnostics(
    rule: AvailabilityRule | RecurringRoutine | DeadlineTask,
) -> list[Diagnostic]:
    windows = rule.preferred_windows if isinstance(rule, DeadlineTask) else [rule.window]
    diagnostics: list[Diagnostic] = []
    for index, window in enumerate(windows):
        if not _time_aligned(window.start) or not _time_aligned(window.end):
            diagnostics.append(
                _diagnostic(
                    "MISALIGNED_TIME",
                    "시간 구간은 30분 단위에 맞춰 주세요.",
                    entity_id=rule.id,
                    field=f"window[{index}]",
                )
            )
    return diagnostics


def _duration_diagnostics(task: DeadlineTask | RecurringRoutine) -> list[Diagnostic]:
    values: list[tuple[str, int]] = [("duration_minutes", task.duration_minutes)]
    if isinstance(task, DeadlineTask):
        values.extend(
            [
                ("min_block_minutes", task.min_block_minutes),
                ("max_block_minutes", task.max_block_minutes),
                ("daily_cap_minutes", task.daily_cap_minutes),
            ]
        )
    return [
        _diagnostic(
            "MISALIGNED_TIME",
            "작업 시간과 제한은 30분 단위여야 해요.",
            entity_id=task.id,
            field=field,
        )
        for field, value in values
        if value % SLOT_MINUTES
    ]


def validate_draft(draft: ExtractionDraft, context: ParseContext) -> ValidationReport:
    """Validate cross-model scheduling invariants without repairing user meaning."""
    diagnostics: list[Diagnostic] = []
    entity_ids = [
        *[item.id for item in draft.deadline_tasks],
        *[item.id for item in draft.recurring_routines],
        *[item.id for item in draft.availability],
        *[item.id for item in draft.fixed_events],
    ]
    seen: set[str] = set()
    for entity_id in entity_ids:
        if entity_id in seen:
            diagnostics.append(
                _diagnostic(
                    "SCHEMA_INVALID",
                    "모든 항목의 ID는 서로 달라야 해요.",
                    entity_id=entity_id,
                    field="id",
                )
            )
        seen.add(entity_id)

    if not draft.availability:
        diagnostics.append(_diagnostic("NO_AVAILABILITY", "가능한 시간을 하나 이상 입력해 주세요."))

    for task in draft.deadline_tasks:
        diagnostics.extend(_duration_diagnostics(task))
        diagnostics.extend(_window_diagnostics(task))
        diagnostics.extend(_datetime_diagnostics(task.deadline, task.id, "deadline"))
        if task.earliest_start:
            diagnostics.extend(
                _datetime_diagnostics(task.earliest_start, task.id, "earliest_start")
            )
        diagnostics.extend(
            _provenance_diagnostics(
                task.provenance,
                task.id,
                {"title", "duration_minutes", "deadline"},
            )
        )

    for routine in draft.recurring_routines:
        diagnostics.extend(_duration_diagnostics(routine))
        diagnostics.extend(_window_diagnostics(routine))
        diagnostics.extend(
            _provenance_diagnostics(
                routine.provenance,
                routine.id,
                {"title", "duration_minutes", "weekdays", "window"},
            )
        )

    for rule in draft.availability:
        diagnostics.extend(_window_diagnostics(rule))
        diagnostics.extend(
            _provenance_diagnostics(rule.provenance, rule.id, {"weekdays", "window"})
        )

    for event in draft.fixed_events:
        diagnostics.extend(_datetime_diagnostics(event.start, event.id, "start"))
        diagnostics.extend(_datetime_diagnostics(event.end, event.id, "end"))
        diagnostics.extend(
            _provenance_diagnostics(event.provenance, event.id, {"title", "start", "end"})
        )

    ordered_events = sorted(
        draft.fixed_events, key=lambda event: (event.start, event.end, event.id)
    )
    for index, event in enumerate(ordered_events):
        for other in ordered_events[index + 1 :]:
            if other.start >= event.end:
                break
            if event.start < other.end and other.start < event.end:
                diagnostics.append(
                    _diagnostic(
                        "OVERLAPPING_FIXED_EVENTS",
                        "고정 일정끼리 겹쳐 있어요. 겹친 시간은 한 번만 차감해요.",
                        entity_id=event.id,
                        severity=Severity.WARNING,
                        details={"other_id": other.id},
                    )
                )

    ready = not any(item.severity == Severity.ERROR for item in diagnostics)
    report = ValidationReport(
        normalized=draft.model_copy(deep=True),
        diagnostics=diagnostics,
        ready_to_schedule=ready,
        context=context.model_copy(deep=True),
    )
    return report


def to_schedule_request(
    report: ValidationReport,
    *,
    daily_work_cap_minutes: int = 240,
) -> ScheduleRequest:
    """Convert a confirmed validation report into the immutable scheduler input."""
    if not report.ready_to_schedule or report.normalized is None:
        raise ConfirmationRequiredError("검토와 확인이 끝난 입력만 일정을 만들 수 있어요.")
    if daily_work_cap_minutes <= 0 or daily_work_cap_minutes % SLOT_MINUTES:
        raise ValueError("daily_work_cap_minutes must be a positive 30-minute multiple")
    draft = report.normalized
    return ScheduleRequest(
        planning_start=report.context.planning_start,
        daily_work_cap_minutes=daily_work_cap_minutes,
        deadline_tasks=draft.deadline_tasks,
        recurring_routines=draft.recurring_routines,
        availability=draft.availability,
        fixed_events=draft.fixed_events,
    )
