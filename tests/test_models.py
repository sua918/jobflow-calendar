from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from jobflow.models import (
    AvailabilityRule,
    DeadlineTask,
    ExtractionDraft,
    ExtractionMethod,
    LocalTimeWindow,
    ParseContext,
    RecurringRoutine,
    ScheduleRequest,
    SourceProvenance,
    Weekday,
)

KST = ZoneInfo("Asia/Seoul")


def provenance(**overrides: object) -> SourceProvenance:
    values = {
        "source_text": "원문",
        "extraction_method": ExtractionMethod.USER,
        "confidence": 1.0,
    }
    values.update(overrides)
    return SourceProvenance(**values)


def test_models_forbid_extra_and_use_independent_collection_defaults() -> None:
    with pytest.raises(ValidationError):
        SourceProvenance(
            source_text="원문",
            extraction_method="user",
            confidence=1,
            unexpected=True,
        )
    first = ExtractionDraft()
    second = ExtractionDraft()
    first.deadline_tasks.append(
        DeadlineTask(
            id="task-01",
            title="작업",
            duration_minutes=30,
            deadline=datetime(2026, 3, 3, 20, tzinfo=KST),
            provenance=provenance(),
        )
    )
    assert second.deadline_tasks == []


@pytest.mark.parametrize("bad_id", ["", "space id", "한글", "a" * 65, "_starts_wrong"])
def test_entity_ids_are_ui_safe(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        AvailabilityRule(
            id=bad_id,
            weekdays={Weekday.MON},
            window=LocalTimeWindow(start=time(19), end=time(20)),
            provenance=provenance(),
        )


def test_work_item_ids_are_limited_to_48_characters() -> None:
    accepted = "a" * 48
    DeadlineTask(
        id=accepted,
        title="작업",
        duration_minutes=30,
        deadline=datetime(2026, 3, 3, 20, tzinfo=KST),
        provenance=provenance(),
    )
    RecurringRoutine(
        id=accepted,
        title="반복",
        duration_minutes=30,
        weekdays={Weekday.MON},
        window=LocalTimeWindow(start=time(19), end=time(20)),
        provenance=provenance(),
    )
    for model, values in (
        (
            DeadlineTask,
            {
                "title": "작업",
                "duration_minutes": 30,
                "deadline": datetime(2026, 3, 3, 20, tzinfo=KST),
            },
        ),
        (
            RecurringRoutine,
            {
                "title": "반복",
                "duration_minutes": 30,
                "weekdays": {Weekday.MON},
                "window": LocalTimeWindow(start=time(19), end=time(20)),
            },
        ),
    ):
        with pytest.raises(ValidationError):
            model(id="a" * 49, provenance=provenance(), **values)


def test_model_boundaries_reject_invalid_time_and_work_values() -> None:
    with pytest.raises(ValidationError):
        LocalTimeWindow(start=time(20), end=time(19))
    with pytest.raises(ValidationError):
        DeadlineTask(
            id="task-01",
            title="작업",
            duration_minutes=0,
            deadline=datetime(2026, 3, 3, 20, tzinfo=KST),
            priority=6,
            provenance=provenance(),
        )
    with pytest.raises(ValidationError):
        provenance(confidence=1.1)


def test_policy_defaults_are_recorded_in_provenance() -> None:
    item = DeadlineTask(
        id="task-01",
        title="작업",
        duration_minutes=30,
        deadline=datetime(2026, 3, 3, 20, tzinfo=KST),
        provenance=provenance(extraction_method=ExtractionMethod.LLM),
    )
    assert item.provenance.extraction_method == ExtractionMethod.DEFAULT
    assert {
        "priority=3",
        "splittable=true",
        "min_block_minutes=30",
        "max_block_minutes=120",
        "daily_cap_minutes=240",
    } <= set(item.provenance.assumptions)


def test_parse_context_requires_canonical_seoul_aware_datetime() -> None:
    with pytest.raises(ValidationError):
        ParseContext(reference_datetime=datetime(2026, 3, 2, 9), planning_start=date(2026, 3, 2))
    context = ParseContext(
        reference_datetime=datetime.fromisoformat("2026-03-02T09:00:00+09:00"),
        planning_start=date(2026, 3, 2),
    )
    assert getattr(context.reference_datetime.tzinfo, "key", None) == "Asia/Seoul"
    context = ParseContext(
        reference_datetime=datetime(2026, 3, 2, 9, tzinfo=KST),
        planning_start=date(2026, 3, 2),
    )
    assert context.reference_datetime.tzinfo is KST


def test_schedule_request_rejects_misaligned_global_cap() -> None:
    with pytest.raises(ValidationError):
        ScheduleRequest(
            planning_start=date(2026, 3, 2),
            daily_work_cap_minutes=45,
            availability=[
                AvailabilityRule(
                    id="availability-01",
                    weekdays={Weekday.MON},
                    window=LocalTimeWindow(start=time(19), end=time(20)),
                    provenance=provenance(),
                )
            ],
        )
