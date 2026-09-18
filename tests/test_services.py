import asyncio
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from jobflow import services
from jobflow.models import (
    AvailabilityRule,
    Diagnostic,
    ExtractionDraft,
    ExtractionMethod,
    LocalTimeWindow,
    ParseContext,
    ScheduleRequest,
    ScheduleResult,
    ScheduleStats,
    SelectedMonth,
    Severity,
    SourceProvenance,
    Weekday,
)

KST = ZoneInfo("Asia/Seoul")
CONTEXT = ParseContext(
    reference_datetime=datetime(2026, 3, 2, 9, tzinfo=KST),
    selected_month=SelectedMonth(year=2026, month=3),
)


def draft() -> ExtractionDraft:
    return ExtractionDraft(
        availability=[
            AvailabilityRule(
                id="availability-01",
                weekdays={Weekday.MON},
                window=LocalTimeWindow(start=time(19), end=time(22)),
                provenance=SourceProvenance(
                    source_text="월요일 저녁",
                    extraction_method=ExtractionMethod.USER,
                    confidence=1,
                ),
            )
        ]
    )


def test_parse_for_review_validates_extracted_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_extract(text: str, context: ParseContext) -> ExtractionDraft:
        assert text == "입력"
        assert context == CONTEXT
        return draft()

    monkeypatch.setattr(services, "extract_draft", fake_extract)
    report = asyncio.run(services.parse_for_review("입력", CONTEXT))
    assert report.ready_to_schedule
    assert report.normalized == draft()
    assert report.context == CONTEXT


def test_parse_failure_returns_only_safe_korean_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failed(text: str, context: ParseContext) -> ExtractionDraft:
        raise services.ExtractionError("safe")

    monkeypatch.setattr(services, "extract_draft", failed)
    report = asyncio.run(services.parse_for_review("민감한 원문", CONTEXT))
    assert not report.ready_to_schedule
    assert report.normalized is None
    assert report.context == CONTEXT
    assert [item.code for item in report.diagnostics] == ["EXTRACTION_FAILED"]
    assert "민감한 원문" not in report.model_dump_json()


def test_schedule_confirmed_validates_result_and_explains_in_korean() -> None:
    request = ScheduleRequest(
        selected_month=CONTEXT.selected_month, availability=draft().availability
    )
    result = services.schedule_confirmed(request)
    assert result.is_fully_scheduled
    explanation = services.explain_result_ko(result)
    assert "요청" in explanation
    assert "배치" in explanation
    assert str(result.stats.scheduled_minutes) in explanation


def test_schedule_confirmed_rejects_internal_invalid_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = ScheduleRequest(
        selected_month=CONTEXT.selected_month, availability=draft().availability
    )
    malformed = ScheduleResult(
        stats=ScheduleStats(requested_minutes=0, scheduled_minutes=0, unscheduled_minutes=0),
        is_fully_scheduled=True,
    )
    diagnostic = Diagnostic(
        code="INTERNAL_SCHEDULE_INVALID",
        severity=Severity.ERROR,
        message_ko="내부 오류",
    )
    monkeypatch.setattr(services, "build_schedule", lambda _: malformed)
    monkeypatch.setattr(services, "validate_schedule", lambda _request, _result: [diagnostic])
    with pytest.raises(services.InternalScheduleError):
        services.schedule_confirmed(request)
