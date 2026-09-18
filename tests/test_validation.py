from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from jobflow.models import (
    AvailabilityRule,
    DeadlineTask,
    ExtractionDraft,
    ExtractionMethod,
    FixedEvent,
    LocalTimeWindow,
    ParseContext,
    RecurringRoutine,
    SourceProvenance,
    Weekday,
)
from jobflow.validation import ConfirmationRequiredError, to_schedule_request, validate_draft

KST = ZoneInfo("Asia/Seoul")
CONTEXT = ParseContext(
    reference_datetime=datetime(2026, 3, 2, 9, tzinfo=KST),
    planning_start=date(2026, 3, 2),
)


def prov(confidence: float = 1, uncertain: list[str] | None = None) -> SourceProvenance:
    return SourceProvenance(
        source_text="사용자 입력",
        extraction_method=ExtractionMethod.USER,
        confidence=confidence,
        uncertain_fields=uncertain or [],
    )


def availability(identifier: str = "availability-01") -> AvailabilityRule:
    return AvailabilityRule(
        id=identifier,
        weekdays=set(Weekday),
        window=LocalTimeWindow(start=time(9), end=time(22)),
        provenance=prov(),
    )


def task(**overrides: object) -> DeadlineTask:
    values: dict[str, object] = {
        "id": "task-01",
        "title": "포트폴리오",
        "duration_minutes": 60,
        "deadline": datetime(2026, 3, 6, 22, tzinfo=KST),
        "provenance": prov(),
    }
    values.update(overrides)
    return DeadlineTask(**values)


def test_valid_draft_becomes_request_without_mutating_input() -> None:
    draft = ExtractionDraft(deadline_tasks=[task()], availability=[availability()])
    report = validate_draft(draft, CONTEXT)
    assert report.ready_to_schedule
    assert report.normalized == draft
    assert report.normalized is not draft
    assert report.context == CONTEXT
    assert report.context is not CONTEXT
    restored = type(report).model_validate_json(report.model_dump_json())
    assert restored.context == CONTEXT
    request = to_schedule_request(report, daily_work_cap_minutes=180)
    assert request.planning_start == CONTEXT.planning_start
    assert request.daily_work_cap_minutes == 180


def test_request_uses_only_public_serialized_report_context() -> None:
    report = validate_draft(
        ExtractionDraft(deadline_tasks=[task()], availability=[availability()]), CONTEXT
    )
    restored = type(report).model_validate_json(report.model_dump_json())
    assert to_schedule_request(restored).planning_start == CONTEXT.planning_start


def test_confirmation_and_missing_availability_block_scheduling() -> None:
    draft = ExtractionDraft(
        deadline_tasks=[task(provenance=prov(0.69, ["deadline"]))],
    )
    report = validate_draft(draft, CONTEXT)
    assert not report.ready_to_schedule
    codes = [diagnostic.code for diagnostic in report.diagnostics]
    assert "CONFIRMATION_REQUIRED" in codes
    assert "NO_AVAILABILITY" in codes
    assert all(diagnostic.message_ko for diagnostic in report.diagnostics)
    with pytest.raises(ConfirmationRequiredError):
        to_schedule_request(report)


def test_validation_reports_duplicate_ids_timezone_grid_and_fixed_overlap() -> None:
    offset_kst = timezone(timedelta(hours=9))
    fixed = [
        FixedEvent(
            id="fixed-01",
            title="일정 1",
            start=datetime(2026, 3, 3, 10, tzinfo=KST),
            end=datetime(2026, 3, 3, 11, tzinfo=KST),
            provenance=prov(),
        ),
        FixedEvent(
            id="fixed-02",
            title="일정 2",
            start=datetime(2026, 3, 3, 10, 30, tzinfo=KST),
            end=datetime(2026, 3, 3, 11, 30, tzinfo=KST),
            provenance=prov(),
        ),
    ]
    malformed_task = task(id="same-id", duration_minutes=45).model_copy(
        update={"deadline": datetime(2026, 3, 6, 22, 15, tzinfo=offset_kst)}
    )
    draft = ExtractionDraft(
        deadline_tasks=[malformed_task],
        availability=[availability("same-id")],
        fixed_events=fixed,
    )
    report = validate_draft(draft, CONTEXT)
    codes = {diagnostic.code for diagnostic in report.diagnostics}
    assert {"SCHEMA_INVALID", "INVALID_TIMEZONE", "MISALIGNED_TIME"} <= codes
    assert "OVERLAPPING_FIXED_EVENTS" in codes
    assert not report.ready_to_schedule


def test_only_critical_uncertainty_blocks() -> None:
    soft = task(provenance=prov(0.9, ["preferred_windows"]))
    assert validate_draft(
        ExtractionDraft(deadline_tasks=[soft], availability=[availability()]), CONTEXT
    ).ready_to_schedule


def test_nested_critical_uncertainty_blocks_scheduling() -> None:
    routine = RecurringRoutine(
        id="routine-01",
        title="연습",
        duration_minutes=60,
        weekdays={Weekday.MON},
        window=LocalTimeWindow(start=time(19), end=time(20)),
        provenance=prov(0.9, ["window.start"]),
    )
    report = validate_draft(
        ExtractionDraft(recurring_routines=[routine], availability=[availability()]), CONTEXT
    )
    assert not report.ready_to_schedule
    assert any(item.code == "CONFIRMATION_REQUIRED" for item in report.diagnostics)
