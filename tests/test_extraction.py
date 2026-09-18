import asyncio
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from jobflow import extraction
from jobflow.models import (
    RAW_INPUT_MAX_CHARS,
    AvailabilityRule,
    DeadlineTask,
    ExtractionDraft,
    ExtractionMethod,
    FixedEvent,
    LocalTimeWindow,
    ParseContext,
    RecurringRoutine,
    SelectedMonth,
    SourceProvenance,
    Weekday,
)

KST = ZoneInfo("Asia/Seoul")
CONTEXT = ParseContext(
    reference_datetime=datetime(2026, 3, 2, 9, tzinfo=KST),
    selected_month=SelectedMonth(year=2026, month=3),
)


class FakeRunnable:
    def __init__(self, result: object = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def ainvoke(self, values: dict[str, object]) -> object:
        self.calls.append(values)
        if self.error:
            raise self.error
        return self.result


def valid_draft() -> ExtractionDraft:
    return ExtractionDraft(
        availability=[
            AvailabilityRule(
                id="availability-01",
                weekdays={Weekday.MON},
                window=LocalTimeWindow(start=time(19), end=time(22)),
                provenance=SourceProvenance(
                    source_text="월요일 저녁",
                    extraction_method=ExtractionMethod.LLM,
                    confidence=0.9,
                ),
            )
        ]
    )


def test_extract_uses_exactly_one_injected_structured_call(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeRunnable(valid_draft())
    monkeypatch.setattr(extraction, "_build_runnable", lambda: fake)
    result = asyncio.run(extraction.extract_draft("월요일 저녁에 가능해", CONTEXT))
    assert result == valid_draft()
    assert len(fake.calls) == 1
    assert fake.calls[0]["text"] == "월요일 저녁에 가능해"
    assert "2026-03-02" in str(fake.calls[0]["reference_datetime"])


def test_extract_reassigns_provider_ids_deterministically_in_input_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provenance = SourceProvenance(
        source_text="원문",
        extraction_method=ExtractionMethod.LLM,
        confidence=0.9,
    )
    window = LocalTimeWindow(start=time(19), end=time(20))
    draft = ExtractionDraft(
        deadline_tasks=[
            DeadlineTask(
                id="provider-choice",
                title=title,
                duration_minutes=30,
                deadline=datetime(2026, 3, 3, 20, tzinfo=KST),
                provenance=provenance,
            )
            for title in ("첫 작업", "둘째 작업")
        ],
        recurring_routines=[
            RecurringRoutine(
                id="duplicate",
                title=title,
                duration_minutes=30,
                weekdays={Weekday.MON},
                window=window,
                provenance=provenance,
            )
            for title in ("첫 반복", "둘째 반복")
        ],
        availability=[
            AvailabilityRule(
                id="duplicate",
                weekdays={Weekday.MON},
                window=window,
                provenance=provenance,
            ),
            AvailabilityRule(
                id="provider-availability",
                weekdays={Weekday.TUE},
                window=window,
                provenance=provenance,
            ),
        ],
        fixed_events=[
            FixedEvent(
                id="duplicate",
                title=title,
                start=datetime(2026, 3, day, 19, tzinfo=KST),
                end=datetime(2026, 3, day, 20, tzinfo=KST),
                provenance=provenance,
            )
            for day, title in ((2, "첫 고정"), (3, "둘째 고정"))
        ],
    )
    fake = FakeRunnable(draft)
    monkeypatch.setattr(extraction, "_build_runnable", lambda: fake)

    result = asyncio.run(extraction.extract_draft("일정을 정리해 줘", CONTEXT))

    assert [item.id for item in result.deadline_tasks] == ["task-01", "task-02"]
    assert [item.id for item in result.recurring_routines] == [
        "routine-01",
        "routine-02",
    ]
    assert [item.id for item in result.availability] == [
        "availability-01",
        "availability-02",
    ]
    assert [item.id for item in result.fixed_events] == ["fixed-01", "fixed-02"]
    assert result.deadline_tasks[0].title == "첫 작업"
    assert result.deadline_tasks[0].provenance == draft.deadline_tasks[0].provenance
    assert len(fake.calls) == 1


def test_provider_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = "provider payload SECRET raw-user-text"
    fake = FakeRunnable(error=RuntimeError(raw))
    monkeypatch.setattr(extraction, "_build_runnable", lambda: fake)
    with pytest.raises(extraction.ExtractionError) as caught:
        asyncio.run(extraction.extract_draft("raw-user-text", CONTEXT))
    assert raw not in str(caught.value)
    assert "raw-user-text" not in str(caught.value)


def test_blank_text_and_missing_key_fail_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(extraction.ExtractionError):
        asyncio.run(extraction.extract_draft("  ", CONTEXT))
    with pytest.raises(extraction.ExtractionError):
        asyncio.run(extraction.extract_draft("일정을 만들어 줘", CONTEXT))


def test_raw_input_max_is_accepted_and_max_plus_one_never_builds_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted = FakeRunnable(valid_draft())
    builds = 0

    def build() -> FakeRunnable:
        nonlocal builds
        builds += 1
        return accepted

    monkeypatch.setattr(extraction, "_build_runnable", build)
    result = asyncio.run(extraction.extract_draft("가" * RAW_INPUT_MAX_CHARS, CONTEXT))
    assert result == valid_draft()
    assert builds == 1
    assert len(accepted.calls) == 1

    for rejected in ("가" * (RAW_INPUT_MAX_CHARS + 1), "가" * 1_000_000):
        with pytest.raises(extraction.ExtractionError) as caught:
            asyncio.run(extraction.extract_draft(rejected, CONTEXT))
        assert "10,000자" in str(caught.value)
        assert rejected not in str(caught.value)
    assert builds == 1
    assert len(accepted.calls) == 1
