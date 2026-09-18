from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta

from jobflow.extraction import ExtractionError, extract_draft
from jobflow.models import (
    BlockKind,
    CalendarDayCell,
    CalendarEventView,
    CalendarMonthView,
    Diagnostic,
    ParseContext,
    ScheduleRequest,
    ScheduleResult,
    Severity,
    ValidationReport,
    Weekday,
    month_bounds,
)
from jobflow.scheduler import build_schedule, validate_schedule
from jobflow.validation import validate_draft


class InternalScheduleError(RuntimeError):
    """Raised when deterministic post-validation detects an internal defect."""


_WEEKDAYS = list(Weekday)
_CATEGORY_ORDER = {"fixed_event": 0, "recurring_routine": 1, "deadline_task": 2}
_CATEGORY_LABELS = {
    "deadline_task": "마감 작업",
    "recurring_routine": "반복 일정",
    "fixed_event": "고정 일정",
}


def _aria_label(
    category: str, title: str, original_start: datetime, original_end: datetime
) -> str:
    return (
        f"{_CATEGORY_LABELS[category]} {title}, "
        f"{original_start:%Y-%m-%d %H:%M}부터 {original_end:%Y-%m-%d %H:%M}까지 KST"
    )


def build_calendar_month_view(
    request: ScheduleRequest,
    result: ScheduleResult,
    *,
    today: date | None = None,
) -> CalendarMonthView:
    """Project a confirmed schedule into a stable Monday-first month grid."""
    horizon_start, horizon_end = month_bounds(request.selected_month)
    first_day = horizon_start.date()
    last_day = horizon_end.date() - timedelta(days=1)
    grid_start = first_day - timedelta(days=first_day.weekday())
    grid_end = last_day + timedelta(days=6 - last_day.weekday())
    natural_days = (grid_end - grid_start).days + 1
    if natural_days == 28:
        grid_end += timedelta(days=7)
    row_count = ((grid_end - grid_start).days + 1) // 7
    if row_count not in (5, 6):
        raise InternalScheduleError("월간 달력 범위를 안전하게 만들지 못했어요.")

    events_by_day: dict[date, list[CalendarEventView]] = defaultdict(list)
    for block in result.blocks:
        if block.start < horizon_start or block.end > horizon_end:
            raise InternalScheduleError("선택한 달 밖의 일정 블록을 표시할 수 없어요.")
        category = (
            "recurring_routine" if block.kind == BlockKind.ROUTINE else "deadline_task"
        )
        events_by_day[block.start.date()].append(
            CalendarEventView(
                view_id=block.id,
                source_id=block.id,
                work_id=block.work_id,
                category=category,
                category_label_ko=_CATEGORY_LABELS[category],
                title=block.title,
                segment_date=block.start.date(),
                segment_start=block.start,
                segment_end=block.end,
                original_start=block.start,
                original_end=block.end,
                duration_minutes=int((block.end - block.start).total_seconds() // 60),
                starts_before_segment=False,
                ends_after_segment=False,
                aria_label_ko=_aria_label(category, block.title, block.start, block.end),
            )
        )

    for event in request.fixed_events:
        clipped_start = max(event.start, horizon_start)
        clipped_end = min(event.end, horizon_end)
        if clipped_start >= clipped_end:
            continue
        segment_start = clipped_start
        while segment_start < clipped_end:
            next_midnight = datetime.combine(
                segment_start.date() + timedelta(days=1), time.min, segment_start.tzinfo
            )
            segment_end = min(clipped_end, next_midnight)
            events_by_day[segment_start.date()].append(
                CalendarEventView(
                    view_id=f"fixed-view-{event.id}-{segment_start:%Y%m%d}",
                    source_id=event.id,
                    work_id=None,
                    category="fixed_event",
                    category_label_ko=_CATEGORY_LABELS["fixed_event"],
                    title=event.title,
                    segment_date=segment_start.date(),
                    segment_start=segment_start,
                    segment_end=segment_end,
                    original_start=event.start,
                    original_end=event.end,
                    duration_minutes=int((segment_end - segment_start).total_seconds() // 60),
                    starts_before_segment=event.start < segment_start,
                    ends_after_segment=segment_end < event.end,
                    aria_label_ko=_aria_label(
                        "fixed_event", event.title, event.start, event.end
                    ),
                )
            )
            segment_start = segment_end

    view_ids = [event.view_id for events in events_by_day.values() for event in events]
    if len(view_ids) != len(set(view_ids)):
        raise InternalScheduleError("월간 달력 이벤트 ID가 중복됐어요.")

    cells: list[CalendarDayCell] = []
    current = grid_start
    while current <= grid_end:
        in_month = first_day <= current <= last_day
        events = events_by_day[current] if in_month else []
        events.sort(
            key=lambda event: (
                event.segment_start,
                event.segment_end,
                _CATEGORY_ORDER[event.category],
                event.source_id,
            )
        )
        cells.append(
            CalendarDayCell(
                date=current,
                in_selected_month=in_month,
                is_today=current == today,
                weekday=_WEEKDAYS[current.weekday()],
                events=events,
            )
        )
        current += timedelta(days=1)
    return CalendarMonthView(
        selected_month=request.selected_month,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        row_count=row_count,
        days=cells,
    )


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
    "build_calendar_month_view",
    "explain_result_ko",
    "parse_for_review",
    "schedule_confirmed",
]
