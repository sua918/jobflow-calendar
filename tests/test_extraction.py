import asyncio
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from jobflow import extraction
from jobflow.models import (
    AvailabilityRule,
    ExtractionDraft,
    ExtractionMethod,
    LocalTimeWindow,
    ParseContext,
    SourceProvenance,
    Weekday,
)

KST = ZoneInfo("Asia/Seoul")
CONTEXT = ParseContext(
    reference_datetime=datetime(2026, 3, 2, 9, tzinfo=KST),
    planning_start=date(2026, 3, 2),
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
