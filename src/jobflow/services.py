from __future__ import annotations

from jobflow.extraction import ExtractionError, extract_draft
from jobflow.models import (
    Diagnostic,
    ParseContext,
    ScheduleRequest,
    ScheduleResult,
    Severity,
    ValidationReport,
)
from jobflow.scheduler import build_schedule, validate_schedule
from jobflow.validation import validate_draft


class InternalScheduleError(RuntimeError):
    """Raised when deterministic post-validation detects an internal defect."""


async def parse_for_review(text: str, context: ParseContext) -> ValidationReport:
    """Extract once, then run deterministic draft validation for user review."""
    try:
        draft = await extract_draft(text, context)
    except Exception:
        return ValidationReport(
            normalized=None,
            diagnostics=[
                Diagnostic(
                    code="EXTRACTION_FAILED",
                    severity=Severity.ERROR,
                    message_ko="AI 추출을 사용할 수 없어요. 설정을 확인하거나 다시 시도해 주세요.",
                )
            ],
            ready_to_schedule=False,
            context=context.model_copy(deep=True),
        )
    return validate_draft(draft, context)


def schedule_confirmed(request: ScheduleRequest) -> ScheduleResult:
    """Schedule confirmed data and fail closed on post-schedule invariant errors."""
    result = build_schedule(request)
    diagnostics = validate_schedule(request, result)
    if any(item.severity == Severity.ERROR for item in diagnostics):
        raise InternalScheduleError("생성된 일정을 안전하게 검증하지 못했어요.")
    if any(item.severity == Severity.ERROR for item in result.diagnostics):
        raise InternalScheduleError("생성된 일정을 안전하게 검증하지 못했어요.")
    return result


def explain_result_ko(result: ScheduleResult) -> str:
    """Explain only computed result facts with a deterministic Korean template."""
    status = (
        "모든 작업을 배치했어요." if result.is_fully_scheduled else "배치하지 못한 작업이 있어요."
    )
    return (
        f"규칙 기반 일정이에요. 요청 {result.stats.requested_minutes}분 중 "
        f"{result.stats.scheduled_minutes}분을 배치했고 "
        f"{result.stats.unscheduled_minutes}분이 남았어요. {status}"
    )


__all__ = [
    "ExtractionError",
    "InternalScheduleError",
    "explain_result_ko",
    "parse_for_review",
    "schedule_confirmed",
]
