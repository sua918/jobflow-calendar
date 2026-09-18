import asyncio
import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from jobflow import extraction
from jobflow.models import (
    AvailabilityRule,
    CalendarEventView,
    DeadlineTask,
    ExtractionDraft,
    ExtractionMethod,
    FixedEvent,
    LocalTimeWindow,
    ParseContext,
    RecurringRoutine,
    ScheduleBlock,
    ScheduleRequest,
    ScheduleResult,
    ScheduleStats,
    SelectedMonth,
    SourceProvenance,
    Weekday,
    month_bounds,
)
from jobflow.scheduler import _block_id, build_schedule
from jobflow.services import build_calendar_month_view
from jobflow.validation import to_schedule_request, validate_draft

KST = ZoneInfo("Asia/Seoul")
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def prov() -> SourceProvenance:
    return SourceProvenance(
        source_text="입력",
        extraction_method=ExtractionMethod.USER,
        confidence=1,
    )


def availability(**changes: object) -> AvailabilityRule:
    values: dict[str, object] = {
        "id": "availability-01",
        "weekdays": set(Weekday),
        "window": LocalTimeWindow(start=time(0), end=time(23, 30)),
        "provenance": prov(),
    }
    values.update(changes)
    return AvailabilityRule(**values)


@pytest.mark.parametrize(
    ("year", "month", "days", "next_year", "next_month"),
    [
        (2024, 2, 29, 2024, 3),
        (2025, 2, 28, 2025, 3),
        (2026, 4, 30, 2026, 5),
        (2026, 3, 31, 2026, 4),
        (2026, 12, 31, 2027, 1),
    ],
)
def test_month_bounds_are_exact_seoul_months(
    year: int, month: int, days: int, next_year: int, next_month: int
) -> None:
    start, end = month_bounds(SelectedMonth(year=year, month=month))
    assert start == datetime(year, month, 1, tzinfo=KST)
    assert end == datetime(next_year, next_month, 1, tzinfo=KST)
    assert (end - start).days == days
    assert int((end - start).total_seconds() // (30 * 60)) == days * 48
    assert start.tzinfo is KST and end.tzinfo is KST
    assert start.utcoffset() == end.utcoffset()


def test_selected_month_is_required_and_legacy_fields_fail_clearly() -> None:
    with pytest.raises(ValidationError, match="selected_month"):
        ParseContext.model_validate({"reference_datetime": "2026-03-02T09:00:00+09:00"})
    with pytest.raises(ValidationError, match="planning_start"):
        ParseContext.model_validate(
            {
                "reference_datetime": "2026-03-02T09:00:00+09:00",
                "selected_month": {"year": 2026, "month": 3},
                "planning_start": "2026-03-02",
            }
        )
    with pytest.raises(ValidationError, match="horizon_days"):
        ScheduleRequest.model_validate(
            {
                "selected_month": {"year": 2026, "month": 3},
                "horizon_days": 14,
                "availability": [availability().model_dump(mode="json")],
            }
        )
    invalid_months = (
        {"year": 2026, "month": 0},
        {"year": 2026, "month": 13},
        {"year": 9999, "month": 1},
    )
    for bad in invalid_months:
        with pytest.raises(ValidationError):
            SelectedMonth.model_validate(bad)


def test_validation_reports_outside_and_clipped_month_relationships() -> None:
    context = ParseContext(
        reference_datetime=datetime(2026, 3, 2, 9, tzinfo=KST),
        selected_month=SelectedMonth(year=2026, month=3),
    )
    draft = ExtractionDraft(
        recurring_routines=[
            RecurringRoutine(
                id="routine-outside",
                title="지난 반복",
                duration_minutes=60,
                weekdays={Weekday.MON},
                window=LocalTimeWindow(start=time(19), end=time(20)),
                start_date=date(2026, 2, 1),
                end_date=date(2026, 2, 28),
                provenance=prov(),
            ),
            RecurringRoutine(
                id="routine-none",
                title="발생 없음",
                duration_minutes=60,
                weekdays={Weekday.TUE},
                window=LocalTimeWindow(start=time(19), end=time(20)),
                start_date=date(2026, 3, 2),
                end_date=date(2026, 3, 2),
                provenance=prov(),
            ),
        ],
        availability=[
            availability(
                id="availability-clipped",
                valid_from=date(2026, 2, 20),
                valid_through=date(2026, 3, 2),
            )
        ],
        fixed_events=[
            FixedEvent(
                id="fixed-outside",
                title="다음 달 일정",
                start=datetime(2026, 4, 1, 9, tzinfo=KST),
                end=datetime(2026, 4, 1, 10, tzinfo=KST),
                provenance=prov(),
            ),
            FixedEvent(
                id="fixed-clipped",
                title="월 경계 일정",
                start=datetime(2026, 2, 28, 23, 30, tzinfo=KST),
                end=datetime(2026, 3, 1, 0, 30, tzinfo=KST),
                provenance=prov(),
            ),
        ],
    )
    report = validate_draft(draft, context)
    keyed = {(item.entity_id, item.code, item.severity.value) for item in report.diagnostics}
    assert ("routine-outside", "OUTSIDE_HORIZON", "warning") in keyed
    assert ("routine-none", "NO_OCCURRENCE_IN_SELECTED_MONTH", "info") in keyed
    assert ("availability-clipped", "AVAILABILITY_CLIPPED_TO_HORIZON", "info") in keyed
    assert ("fixed-outside", "OUTSIDE_HORIZON", "warning") in keyed
    assert ("fixed-clipped", "FIXED_EVENT_CLIPPED_TO_HORIZON", "info") in keyed
    assert report.ready_to_schedule
    restored = type(report).model_validate_json(report.model_dump_json())
    assert to_schedule_request(restored).selected_month == context.selected_month


def test_availability_without_a_matching_in_month_weekday_blocks_scheduling() -> None:
    context = ParseContext(
        reference_datetime=datetime(2026, 3, 2, 9, tzinfo=KST),
        selected_month=SelectedMonth(year=2026, month=3),
    )
    report = validate_draft(
        ExtractionDraft(
            availability=[
                availability(
                    weekdays={Weekday.TUE},
                    valid_from=date(2026, 3, 2),
                    valid_through=date(2026, 3, 2),
                )
            ]
        ),
        context,
    )
    assert not report.ready_to_schedule
    assert any(item.code == "NO_AVAILABILITY" for item in report.diagnostics)


def test_scheduler_uses_whole_month_and_zero_minutes_for_disjoint_routine() -> None:
    request = ScheduleRequest(
        selected_month=SelectedMonth(year=2026, month=3),
        availability=[availability()],
        deadline_tasks=[
            DeadlineTask(
                id="task-late",
                title="월말 작업",
                duration_minutes=30,
                earliest_start=datetime(2026, 3, 31, 22, 30, tzinfo=KST),
                deadline=datetime(2026, 4, 2, 0, tzinfo=KST),
                provenance=prov(),
            )
        ],
        recurring_routines=[
            RecurringRoutine(
                id="routine-outside",
                title="지난 반복",
                duration_minutes=60,
                weekdays={Weekday.MON},
                window=LocalTimeWindow(start=time(19), end=time(20)),
                start_date=date(2026, 2, 1),
                end_date=date(2026, 2, 28),
                provenance=prov(),
            )
        ],
    )
    result = build_schedule(request)
    assert result.blocks[0].start == datetime(2026, 3, 31, 22, 30, tzinfo=KST)
    assert result.stats.requested_minutes == 30
    assert result.unscheduled == []


class FakeRunnable:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def ainvoke(self, values: dict[str, object]) -> object:
        self.calls.append(values)
        return ExtractionDraft(availability=[availability()])


def test_extraction_receives_selected_month_and_exact_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRunnable()
    monkeypatch.setattr(extraction, "_build_runnable", lambda: fake)
    context = ParseContext(
        reference_datetime=datetime(2026, 3, 2, 9, tzinfo=KST),
        selected_month=SelectedMonth(year=2026, month=3),
    )
    asyncio.run(extraction.extract_draft("입력", context))
    assert len(fake.calls) == 1
    assert fake.calls[0]["selected_month"] == {"year": 2026, "month": 3}
    assert fake.calls[0]["horizon_start"] == "2026-03-01T00:00:00+09:00"
    assert fake.calls[0]["horizon_end"] == "2026-04-01T00:00:00+09:00"


def test_calendar_projection_is_stable_traceable_and_respects_id_bounds() -> None:
    month = SelectedMonth(year=2026, month=3)
    long_work_id = "w" * 48
    block_id = f"block-{long_work_id}-1488"
    fixed_id = "f" * 64
    request = ScheduleRequest(
        selected_month=month,
        availability=[availability()],
        fixed_events=[
            FixedEvent(
                id=fixed_id,
                title="여러 날 행사",
                start=datetime(2026, 2, 28, 23, tzinfo=KST),
                end=datetime(2026, 3, 2, 1, tzinfo=KST),
                provenance=prov(),
            )
        ],
    )
    result = ScheduleResult(
        blocks=[
            ScheduleBlock(
                id=block_id,
                work_id=long_work_id,
                title="작업",
                kind="task",
                start=datetime(2026, 3, 31, 23, tzinfo=KST),
                end=datetime(2026, 3, 31, 23, 30, tzinfo=KST),
            )
        ],
        stats=ScheduleStats(requested_minutes=30, scheduled_minutes=30, unscheduled_minutes=0),
        is_fully_scheduled=True,
    )
    view = build_calendar_month_view(request, result, today=date(2026, 3, 2))
    repeated = build_calendar_month_view(request, result, today=date(2026, 3, 2))
    assert view == repeated
    assert view.row_count == 6
    assert len(view.days) == 42
    assert view.days[0].date == date(2026, 2, 23)
    assert view.days[-1].date == date(2026, 4, 5)
    events: list[CalendarEventView] = [event for day in view.days for event in day.events]
    assert {event.source_id for event in events} == {block_id, fixed_id}
    assert len(block_id) == 59
    fixed_view_ids = [event.view_id for event in events if event.category == "fixed_event"]
    assert {len(value) for value in fixed_view_ids} == {84}
    assert len({event.view_id for event in events}) == len(events)
    assert all(ID_PATTERN.fullmatch(event.view_id) for event in events)
    assert all(day.events == [] for day in view.days if not day.in_selected_month)


def test_scheduler_block_id_generation_supports_four_digit_month_sequence() -> None:
    work_id = "w" * 48
    generated = _block_id(work_id, 1488)
    assert generated == f"block-{work_id}-1488"
    assert len(generated) == 59
    assert ID_PATTERN.fullmatch(generated)


@pytest.mark.parametrize(
    ("selected_month", "expected_start", "expected_end", "row_count"),
    [
        (SelectedMonth(year=2021, month=2), date(2021, 2, 1), date(2021, 3, 7), 5),
        (SelectedMonth(year=2026, month=12), date(2026, 11, 30), date(2027, 1, 3), 5),
    ],
)
def test_calendar_projection_pads_natural_four_week_month_and_rolls_year(
    selected_month: SelectedMonth,
    expected_start: date,
    expected_end: date,
    row_count: int,
) -> None:
    request = ScheduleRequest(selected_month=selected_month, availability=[availability()])
    result = ScheduleResult(
        stats=ScheduleStats(requested_minutes=0, scheduled_minutes=0, unscheduled_minutes=0),
        is_fully_scheduled=True,
    )
    view = build_calendar_month_view(request, result)
    assert view.days[0].date == expected_start
    assert view.days[-1].date == expected_end
    assert view.row_count == row_count
