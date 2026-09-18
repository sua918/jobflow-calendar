from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from jobflow.models import (
    AvailabilityRule,
    DeadlineTask,
    ExtractionDraft,
    ExtractionMethod,
    FixedEvent,
    LocalTimeWindow,
    ParseContext,
    RecurringRoutine,
    ScheduleRequest,
    SelectedMonth,
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


def test_policy_default_assumptions_remain_idempotent_at_collection_boundary() -> None:
    item = DeadlineTask(
        id="task-01",
        title="작업",
        duration_minutes=30,
        deadline=datetime(2026, 3, 3, 20, tzinfo=KST),
        provenance=provenance(extraction_method=ExtractionMethod.LLM),
    )

    draft = ExtractionDraft(deadline_tasks=[item] * 50)

    assert len(draft.deadline_tasks) == 50
    assert len(item.provenance.assumptions) == 5


def test_parse_context_requires_canonical_seoul_aware_datetime() -> None:
    with pytest.raises(ValidationError):
        ParseContext(
            reference_datetime=datetime(2026, 3, 2, 9),
            selected_month=SelectedMonth(year=2026, month=3),
        )
    context = ParseContext(
        reference_datetime=datetime.fromisoformat("2026-03-02T09:00:00+09:00"),
        selected_month=SelectedMonth(year=2026, month=3),
    )
    assert getattr(context.reference_datetime.tzinfo, "key", None) == "Asia/Seoul"
    context = ParseContext(
        reference_datetime=datetime(2026, 3, 2, 9, tzinfo=KST),
        selected_month=SelectedMonth(year=2026, month=3),
    )
    assert context.reference_datetime.tzinfo is KST


def test_schedule_request_rejects_misaligned_global_cap() -> None:
    with pytest.raises(ValidationError):
        ScheduleRequest(
            selected_month=SelectedMonth(year=2026, month=3),
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


def test_human_text_and_provenance_boundaries_accept_max_and_reject_max_plus_one() -> None:
    task_values = {
        "id": "task-01",
        "duration_minutes": 30,
        "deadline": datetime(2026, 3, 3, 20, tzinfo=KST),
        "provenance": provenance(),
    }
    assert DeadlineTask(title=f"  {'가' * 200}  ", **task_values).title == "가" * 200
    with pytest.raises(ValidationError):
        DeadlineTask.model_validate({**task_values, "title": "가" * 201})

    assert len(provenance(source_text=f"  {'나' * 1000}  ").source_text) == 1000
    with pytest.raises(ValidationError):
        SourceProvenance.model_validate(
            {
                "source_text": "나" * 1001,
                "extraction_method": "user",
                "confidence": 1,
            }
        )

    accepted = provenance(
        uncertain_fields=["f" * 64] * 32,
        assumptions=["가" * 200] * 32,
    )
    assert len(accepted.uncertain_fields) == 32
    assert len(accepted.assumptions) == 32
    for field, value in (
        ("uncertain_fields", ["f"] * 33),
        ("uncertain_fields", ["f" * 65]),
        ("assumptions", ["가"] * 33),
        ("assumptions", ["가" * 201]),
    ):
        with pytest.raises(ValidationError):
            provenance(**{field: value})


def test_deadline_preferred_windows_accepts_sixteen_and_rejects_seventeen() -> None:
    values = {
        "id": "task-01",
        "title": "작업",
        "duration_minutes": 30,
        "deadline": datetime(2026, 3, 3, 20, tzinfo=KST),
        "provenance": provenance(),
    }
    windows = [{"start": "09:00", "end": "10:00"}] * 16
    accepted = DeadlineTask.model_validate({**values, "preferred_windows": windows})
    assert len(accepted.preferred_windows) == 16
    with pytest.raises(ValidationError):
        DeadlineTask.model_validate({**values, "preferred_windows": [*windows, windows[0]]})


@pytest.mark.parametrize(
    ("field", "maximum"),
    [
        ("deadline_tasks", 50),
        ("recurring_routines", 50),
        ("availability", 50),
        ("fixed_events", 100),
    ],
)
@pytest.mark.parametrize("model_type", [ExtractionDraft, ScheduleRequest])
def test_draft_and_request_collection_boundaries(
    field: str,
    maximum: int,
    model_type: type[ExtractionDraft] | type[ScheduleRequest],
) -> None:
    window = LocalTimeWindow(start=time(19), end=time(20))
    items = {
        "deadline_tasks": DeadlineTask(
            id="task-01",
            title="작업",
            duration_minutes=30,
            deadline=datetime(2026, 3, 3, 20, tzinfo=KST),
            priority=3,
            splittable=True,
            min_block_minutes=30,
            max_block_minutes=120,
            daily_cap_minutes=240,
            provenance=provenance(),
        ),
        "recurring_routines": RecurringRoutine(
            id="routine-01",
            title="반복",
            duration_minutes=30,
            weekdays={Weekday.MON},
            window=window,
            priority=3,
            provenance=provenance(),
        ),
        "availability": AvailabilityRule(
            id="availability-01",
            weekdays={Weekday.MON},
            window=window,
            provenance=provenance(),
        ),
        "fixed_events": FixedEvent(
            id="fixed-01",
            title="고정",
            start=datetime(2026, 3, 3, 19, tzinfo=KST),
            end=datetime(2026, 3, 3, 20, tzinfo=KST),
            provenance=provenance(),
        ),
    }
    values: dict[str, object] = {field: [items[field]] * maximum}
    if model_type is ScheduleRequest:
        values["selected_month"] = SelectedMonth(year=2026, month=3)
        values.setdefault("availability", [items["availability"]])

    assert len(getattr(model_type(**values), field)) == maximum  # type: ignore[arg-type]
    serialized = {
        key: [item.model_dump(mode="json") for item in value]
        if isinstance(value, list)
        else value.model_dump(mode="json")
        if isinstance(value, SelectedMonth)
        else value
        for key, value in values.items()
    }
    serialized[field] = [items[field].model_dump(mode="json")] * (maximum + 1)
    with pytest.raises(ValidationError):
        model_type(**{**values, field: [items[field]] * (maximum + 1)})  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        model_type.model_validate(serialized)
