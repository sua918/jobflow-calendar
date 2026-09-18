from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import TypeAlias, cast
from zoneinfo import ZoneInfo

import gradio as gr
from pydantic import ValidationError

from jobflow.models import (
    AvailabilityRule,
    DeadlineTask,
    Diagnostic,
    ExtractionDraft,
    ExtractionMethod,
    FixedEvent,
    LocalTimeWindow,
    ParseContext,
    RecurringRoutine,
    ScheduleResult,
    SelectedMonth,
    Severity,
    SourceProvenance,
    ValidationReport,
    Weekday,
    month_bounds,
)
from jobflow.services import (
    InternalScheduleError,
    explain_result_ko,
    parse_for_review,
    schedule_confirmed,
)
from jobflow.validation import ConfirmationRequiredError, to_schedule_request, validate_draft

KST = ZoneInfo("Asia/Seoul")
ROOT = Path(__file__).resolve().parents[2]
CANONICAL_FIXTURE = ROOT / "tests" / "fixtures" / "canonical_demo.json"
Cell: TypeAlias = str | int | float | bool | None
Rows: TypeAlias = list[list[Cell]]

TASK_HEADERS = [
    "ID",
    "제목",
    "소요(분)",
    "마감(KST)",
    "시작 가능(KST)",
    "우선순위",
    "분할",
    "최소 블록(분)",
    "최대 블록(분)",
    "일일 제한(분)",
    "선호 시간(HH:MM-HH:MM;...)",
    "사용자 확인",
]
ROUTINE_HEADERS = [
    "ID",
    "제목",
    "회당 소요(분)",
    "요일(MON,...)",
    "허용 시작",
    "허용 종료",
    "시작일",
    "종료일",
    "우선순위",
    "필수",
    "사용자 확인",
]
AVAILABILITY_HEADERS = [
    "ID",
    "요일(MON,...)",
    "가능 시작",
    "가능 종료",
    "유효 시작일",
    "유효 종료일",
    "사용자 확인",
]
FIXED_EVENT_HEADERS = ["ID", "제목", "시작(KST)", "종료(KST)", "사용자 확인"]
TIMELINE_HEADERS = ["날짜", "제목", "종류", "시작(KST)", "종료(KST)", "소요(분)"]
UNSCHEDULED_HEADERS = [
    "ID",
    "제목",
    "종류",
    "사유",
    "요청(분)",
    "배치(분)",
    "남은 시간(분)",
    "발생일",
    "설명",
    "상세",
]


@dataclass(frozen=True)
class ReviewView:
    report_json: str
    report: ValidationReport | None
    task_rows: Rows
    routine_rows: Rows
    availability_rows: Rows
    fixed_event_rows: Rows
    diagnostics: str
    context: str
    ready: bool
    confirmed: bool = False
    schedule_enabled: bool = False


@dataclass(frozen=True)
class ScheduleView:
    result: ScheduleResult | None
    result_json: str
    timeline_rows: Rows
    unscheduled_rows: Rows
    summary: str
    stats: str
    diagnostics: str


def _format_datetime(value: datetime | None) -> str:
    return "" if value is None else value.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def _format_date(value: date | None) -> str:
    return "" if value is None else value.isoformat()


def _format_time(value: time) -> str:
    return value.strftime("%H:%M")


def _parse_datetime(value: Cell) -> datetime:
    parsed = datetime.fromisoformat(str(value).strip().replace(" ", "T"))
    return parsed.replace(tzinfo=KST) if parsed.tzinfo is None else parsed.astimezone(KST)


def _parse_optional_datetime(value: Cell) -> datetime | None:
    return None if value is None or not str(value).strip() else _parse_datetime(value)


def _parse_date(value: Cell) -> date:
    return date.fromisoformat(str(value).strip())


def _parse_optional_date(value: Cell) -> date | None:
    return None if value is None or not str(value).strip() else _parse_date(value)


def _parse_time(value: Cell) -> time:
    return time.fromisoformat(str(value).strip())


def _parse_bool(value: Cell) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y", "예", "확인"}


def _parse_int(value: Cell) -> int:
    if value is None or isinstance(value, bool):
        raise ValueError("integer value is required")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError("integer value is required")
        return int(value)
    parsed = float(value.strip())
    if not parsed.is_integer():
        raise ValueError("integer value is required")
    return int(parsed)


def _parse_weekdays(value: Cell) -> set[Weekday]:
    return {Weekday(item.strip().upper()) for item in str(value).split(",") if item.strip()}


def _parse_windows(value: Cell) -> list[LocalTimeWindow]:
    if value is None or not str(value).strip():
        return []
    windows: list[LocalTimeWindow] = []
    for raw in str(value).split(";"):
        start, end = raw.strip().split("-", maxsplit=1)
        windows.append(LocalTimeWindow(start=_parse_time(start), end=_parse_time(end)))
    return windows


def _confirmed(provenance: SourceProvenance) -> bool:
    return (
        provenance.extraction_method == ExtractionMethod.USER
        and provenance.confidence >= 0.70
        and not provenance.uncertain_fields
    )


def _task_row(task: DeadlineTask) -> list[Cell]:
    preferred = ";".join(
        f"{_format_time(window.start)}-{_format_time(window.end)}"
        for window in task.preferred_windows
    )
    return [
        task.id,
        task.title,
        task.duration_minutes,
        _format_datetime(task.deadline),
        _format_datetime(task.earliest_start),
        task.priority,
        task.splittable,
        task.min_block_minutes,
        task.max_block_minutes,
        task.daily_cap_minutes,
        preferred,
        _confirmed(task.provenance),
    ]


def _routine_row(routine: RecurringRoutine) -> list[Cell]:
    return [
        routine.id,
        routine.title,
        routine.duration_minutes,
        ",".join(sorted(day.value for day in routine.weekdays)),
        _format_time(routine.window.start),
        _format_time(routine.window.end),
        _format_date(routine.start_date),
        _format_date(routine.end_date),
        routine.priority,
        routine.required,
        _confirmed(routine.provenance),
    ]


def _availability_row(rule: AvailabilityRule) -> list[Cell]:
    return [
        rule.id,
        ",".join(sorted(day.value for day in rule.weekdays)),
        _format_time(rule.window.start),
        _format_time(rule.window.end),
        _format_date(rule.valid_from),
        _format_date(rule.valid_through),
        _confirmed(rule.provenance),
    ]


def _fixed_event_row(event: FixedEvent) -> list[Cell]:
    return [
        event.id,
        event.title,
        _format_datetime(event.start),
        _format_datetime(event.end),
        _confirmed(event.provenance),
    ]


def _diagnostics_text(diagnostics: list[Diagnostic]) -> str:
    if not diagnostics:
        return "진단 없음 — 결정적 검증을 통과했어요."
    return "\n".join(
        " · ".join(
            part
            for part in [
                f"[{item.severity.value.upper()}] {item.code}",
                item.entity_id,
                item.field,
                item.message_ko,
            ]
            if part
        )
        for item in diagnostics
    )


def _context_text(context: ParseContext) -> str:
    horizon_start, horizon_end = month_bounds(context.selected_month)
    return (
        f"기준 시각: {_format_datetime(context.reference_datetime)} KST\n\n"
        f"계획 범위: {horizon_start.date().isoformat()} ~ {horizon_end.date().isoformat()} 미만\n\n"
        "시간대: Asia/Seoul · 30분 격자 · 선택한 달"
    )


def _view_from_report(report: ValidationReport) -> ReviewView:
    draft = report.normalized or ExtractionDraft()
    return ReviewView(
        report_json=report.model_dump_json(),
        report=report,
        task_rows=[_task_row(item) for item in draft.deadline_tasks],
        routine_rows=[_routine_row(item) for item in draft.recurring_routines],
        availability_rows=[_availability_row(item) for item in draft.availability],
        fixed_event_rows=[_fixed_event_row(item) for item in draft.fixed_events],
        diagnostics=_diagnostics_text(report.diagnostics),
        context=_context_text(report.context),
        ready=report.ready_to_schedule,
    )


def _safe_error_view(message: str, context: ParseContext | None = None) -> ReviewView:
    now = datetime.now(KST).replace(second=0, microsecond=0)
    visible_context = context or ParseContext(
        reference_datetime=now,
        selected_month=SelectedMonth(year=now.year, month=now.month),
    )
    return ReviewView(
        report_json="",
        report=None,
        task_rows=[],
        routine_rows=[],
        availability_rows=[],
        fixed_event_rows=[],
        diagnostics=f"[ERROR] SCHEMA_INVALID · {message}",
        context=_context_text(visible_context),
        ready=False,
    )


def _invalid_edit_view(
    previous_report: ValidationReport,
    task_rows: Rows,
    routine_rows: Rows,
    availability_rows: Rows,
    fixed_event_rows: Rows,
    message: str,
) -> ReviewView:
    diagnostic = Diagnostic(
        code="SCHEMA_INVALID",
        severity=Severity.ERROR,
        message_ko=message,
    )
    blocked = ValidationReport(
        normalized=(
            previous_report.normalized.model_copy(deep=True)
            if previous_report.normalized is not None
            else None
        ),
        diagnostics=[diagnostic],
        ready_to_schedule=False,
        context=previous_report.context.model_copy(deep=True),
    )
    return ReviewView(
        report_json=blocked.model_dump_json(),
        report=blocked,
        task_rows=task_rows,
        routine_rows=routine_rows,
        availability_rows=availability_rows,
        fixed_event_rows=fixed_event_rows,
        diagnostics=_diagnostics_text(blocked.diagnostics),
        context=_context_text(blocked.context),
        ready=False,
    )


async def parse_input(text: str, reference_datetime: str, planning_start: str) -> ReviewView:
    try:
        selected_date = _parse_date(planning_start)
        context = ParseContext(
            reference_datetime=_parse_datetime(reference_datetime),
            selected_month=SelectedMonth(year=selected_date.year, month=selected_date.month),
        )
    except (ValueError, ValidationError):
        return _safe_error_view("기준 시각과 계획 시작일 형식을 확인해 주세요.")
    try:
        return _view_from_report(await parse_for_review(text, context))
    except Exception:
        return _safe_error_view("입력을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.", context)


def load_canonical_demo() -> ReviewView:
    try:
        payload = json.loads(CANONICAL_FIXTURE.read_text(encoding="utf-8"))
        context = ParseContext.model_validate(payload["context"])
        draft = ExtractionDraft.model_validate(payload["draft"])
        return _view_from_report(validate_draft(draft, context))
    except Exception:
        return _safe_error_view("구조화 데모를 불러오지 못했어요.")


def _provenance_for_edit(
    previous: SourceProvenance | None,
    changed_fields: set[str],
    user_confirmed: bool,
) -> SourceProvenance:
    if previous is None:
        return SourceProvenance(
            source_text="사용자 입력",
            extraction_method=ExtractionMethod.USER,
            confidence=1.0,
        )
    if not changed_fields and not user_confirmed:
        return previous.model_copy(deep=True)
    uncertain = [] if user_confirmed else [
        path
        for path in previous.uncertain_fields
        if not any(field in path.split(".") for field in changed_fields)
    ]
    return previous.model_copy(
        update={
            "extraction_method": ExtractionMethod.USER,
            "confidence": 1.0 if user_confirmed else previous.confidence,
            "uncertain_fields": uncertain,
        },
        deep=True,
    )


def _changed_fields(previous: object | None, values: dict[str, object]) -> set[str]:
    if previous is None:
        return set(values)
    result: set[str] = set()
    for field, value in values.items():
        if getattr(previous, field) != value:
            result.add(field)
    return result


def _task_from_row(row: list[Cell], previous: DeadlineTask | None) -> DeadlineTask:
    values: dict[str, object] = {
        "id": str(row[0]).strip(),
        "title": str(row[1]).strip(),
        "duration_minutes": _parse_int(row[2]),
        "deadline": _parse_datetime(row[3]),
        "earliest_start": _parse_optional_datetime(row[4]),
        "priority": _parse_int(row[5]),
        "splittable": _parse_bool(row[6]),
        "min_block_minutes": _parse_int(row[7]),
        "max_block_minutes": _parse_int(row[8]),
        "daily_cap_minutes": _parse_int(row[9]),
        "preferred_windows": _parse_windows(row[10]),
    }
    provenance = _provenance_for_edit(
        previous.provenance if previous else None,
        _changed_fields(previous, values),
        _parse_bool(row[11]),
    )
    return DeadlineTask(**values, provenance=provenance)


def _routine_from_row(row: list[Cell], previous: RecurringRoutine | None) -> RecurringRoutine:
    values: dict[str, object] = {
        "id": str(row[0]).strip(),
        "title": str(row[1]).strip(),
        "duration_minutes": _parse_int(row[2]),
        "weekdays": _parse_weekdays(row[3]),
        "window": LocalTimeWindow(start=_parse_time(row[4]), end=_parse_time(row[5])),
        "start_date": _parse_optional_date(row[6]),
        "end_date": _parse_optional_date(row[7]),
        "priority": _parse_int(row[8]),
        "required": _parse_bool(row[9]),
    }
    provenance = _provenance_for_edit(
        previous.provenance if previous else None,
        _changed_fields(previous, values),
        _parse_bool(row[10]),
    )
    return RecurringRoutine(**values, provenance=provenance)


def _availability_from_row(
    row: list[Cell], previous: AvailabilityRule | None
) -> AvailabilityRule:
    values: dict[str, object] = {
        "id": str(row[0]).strip(),
        "weekdays": _parse_weekdays(row[1]),
        "window": LocalTimeWindow(start=_parse_time(row[2]), end=_parse_time(row[3])),
        "valid_from": _parse_optional_date(row[4]),
        "valid_through": _parse_optional_date(row[5]),
    }
    provenance = _provenance_for_edit(
        previous.provenance if previous else None,
        _changed_fields(previous, values),
        _parse_bool(row[6]),
    )
    return AvailabilityRule(**values, provenance=provenance)


def _fixed_event_from_row(row: list[Cell], previous: FixedEvent | None) -> FixedEvent:
    values: dict[str, object] = {
        "id": str(row[0]).strip(),
        "title": str(row[1]).strip(),
        "start": _parse_datetime(row[2]),
        "end": _parse_datetime(row[3]),
    }
    provenance = _provenance_for_edit(
        previous.provenance if previous else None,
        _changed_fields(previous, values),
        _parse_bool(row[4]),
    )
    return FixedEvent(**values, provenance=provenance)


def apply_table_edits(
    report_json: str,
    task_rows: Rows,
    routine_rows: Rows,
    availability_rows: Rows,
    fixed_event_rows: Rows,
) -> ReviewView:
    previous_report: ValidationReport | None = None
    try:
        previous_report = ValidationReport.model_validate_json(report_json)
        previous = previous_report.normalized or ExtractionDraft()
        tasks = {item.id: item for item in previous.deadline_tasks}
        routines = {item.id: item for item in previous.recurring_routines}
        availability = {item.id: item for item in previous.availability}
        fixed_events = {item.id: item for item in previous.fixed_events}
        draft = ExtractionDraft(
            deadline_tasks=[
                _task_from_row(row, tasks.get(str(row[0]).strip())) for row in task_rows
            ],
            recurring_routines=[
                _routine_from_row(row, routines.get(str(row[0]).strip()))
                for row in routine_rows
            ],
            availability=[
                _availability_from_row(row, availability.get(str(row[0]).strip()))
                for row in availability_rows
            ],
            fixed_events=[
                _fixed_event_from_row(row, fixed_events.get(str(row[0]).strip()))
                for row in fixed_event_rows
            ],
        )
        return _view_from_report(validate_draft(draft, previous_report.context))
    except (ValueError, TypeError, IndexError, ValidationError):
        if previous_report is not None:
            return _invalid_edit_view(
                previous_report,
                task_rows,
                routine_rows,
                availability_rows,
                fixed_event_rows,
                "표의 값과 날짜·시간 형식을 확인해 주세요.",
            )
        return _safe_error_view("표의 값과 날짜·시간 형식을 확인해 주세요.")
    except Exception:
        return _safe_error_view("검토 내용을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.")


def schedule_review(report_json: str, confirmed: bool) -> ScheduleView:
    if not confirmed:
        return ScheduleView(
            result=None,
            result_json="",
            timeline_rows=[],
            unscheduled_rows=[],
            summary="검토 완료를 체크해야 일정을 만들 수 있어요.",
            stats="요청 0분 · 배치 0분 · 미배치 0분",
            diagnostics="[ERROR] CONFIRMATION_REQUIRED · 검토 완료를 확인해 주세요.",
        )
    try:
        report = ValidationReport.model_validate_json(report_json)
        result = schedule_confirmed(to_schedule_request(report))
    except (ConfirmationRequiredError, ValidationError, ValueError):
        return ScheduleView(
            result=None,
            result_json="",
            timeline_rows=[],
            unscheduled_rows=[],
            summary="검증을 통과한 입력만 일정을 만들 수 있어요.",
            stats="요청 0분 · 배치 0분 · 미배치 0분",
            diagnostics="[ERROR] CONFIRMATION_REQUIRED · 입력 진단을 확인해 주세요.",
        )
    except InternalScheduleError:
        return ScheduleView(
            result=None,
            result_json="",
            timeline_rows=[],
            unscheduled_rows=[],
            summary="일정을 안전하게 만들지 못했어요.",
            stats="요청 0분 · 배치 0분 · 미배치 0분",
            diagnostics="[ERROR] INTERNAL_SCHEDULE_INVALID · 잠시 후 다시 시도해 주세요.",
        )
    except Exception:
        return ScheduleView(
            result=None,
            result_json="",
            timeline_rows=[],
            unscheduled_rows=[],
            summary="일정을 처리하지 못했어요.",
            stats="요청 0분 · 배치 0분 · 미배치 0분",
            diagnostics="[ERROR] INTERNAL_SCHEDULE_INVALID · 잠시 후 다시 시도해 주세요.",
        )
    timeline: Rows = [
        [
            block.start.date().isoformat(),
            block.title,
            block.kind.value,
            _format_datetime(block.start),
            _format_datetime(block.end),
            int((block.end - block.start).total_seconds() // 60),
        ]
        for block in result.blocks
    ]
    unscheduled: Rows = [
        [
            item.work_id,
            item.title,
            item.kind.value,
            item.reason.value,
            item.requested_minutes,
            item.scheduled_minutes,
            item.remaining_minutes,
            _format_date(item.occurrence_date),
            item.message_ko,
            json.dumps(item.details, ensure_ascii=False, sort_keys=True),
        ]
        for item in result.unscheduled
    ]
    return ScheduleView(
        result=result,
        result_json=result.model_dump_json(),
        timeline_rows=timeline,
        unscheduled_rows=unscheduled,
        summary=explain_result_ko(result),
        stats=(
            f"요청 {result.stats.requested_minutes}분 · "
            f"배치 {result.stats.scheduled_minutes}분 · "
            f"미배치 {result.stats.unscheduled_minutes}분"
        ),
        diagnostics=_diagnostics_text(result.diagnostics),
    )


def _review_outputs(view: ReviewView) -> tuple[object, ...]:
    return (
        view.report_json,
        view.task_rows,
        view.routine_rows,
        view.availability_rows,
        view.fixed_event_rows,
        view.diagnostics,
        view.context,
        False,
        gr.Button(interactive=False),
        "",
        [],
        [],
        "아직 일정이 없어요.",
        "요청 0분 · 배치 0분 · 미배치 0분",
        "진단 없음",
    )


def _edit_outputs(view: ReviewView) -> tuple[object, ...]:
    return (
        view.report_json,
        view.task_rows,
        view.routine_rows,
        view.availability_rows,
        view.fixed_event_rows,
        view.diagnostics,
        view.context,
        False,
        gr.Button(interactive=False),
        "",
        [],
        [],
        "입력이 바뀌어 이전 일정을 지웠어요.",
        "요청 0분 · 배치 0분 · 미배치 0분",
        "진단 없음",
    )


def _confirmation_button(confirmed: bool, report_json: str) -> gr.Button:
    try:
        ready = ValidationReport.model_validate_json(report_json).ready_to_schedule
    except (ValidationError, ValueError):
        ready = False
    return gr.Button(interactive=bool(confirmed and ready))


def _schedule_outputs(view: ScheduleView) -> tuple[object, ...]:
    return (
        view.result_json,
        view.timeline_rows,
        view.unscheduled_rows,
        view.summary,
        view.stats,
        view.diagnostics,
    )


def _schedule_callback(report_json: str, confirmed: bool) -> tuple[object, ...]:
    return _schedule_outputs(schedule_review(report_json, confirmed))


def _begin_parse() -> tuple[object, ...]:
    return (
        gr.Button(interactive=False),
        False,
        gr.Button(interactive=False),
        "",
        [],
        [],
        "입력을 분석하고 있어요.",
        "요청 0분 · 배치 0분 · 미배치 0분",
        "진단 없음",
    )


def invalidate_input(reference_datetime: str, planning_start: str) -> ReviewView:
    try:
        selected_date = _parse_date(planning_start)
        context = ParseContext(
            reference_datetime=_parse_datetime(reference_datetime),
            selected_month=SelectedMonth(year=selected_date.year, month=selected_date.month),
        )
        context_text = _context_text(context)
    except (ValueError, ValidationError):
        context_text = "기준 시각과 계획 시작일 형식을 확인해 주세요."
    return ReviewView(
        report_json="",
        report=None,
        task_rows=[],
        routine_rows=[],
        availability_rows=[],
        fixed_event_rows=[],
        diagnostics="입력이 바뀌어 이전 검토와 일정을 지웠어요.",
        context=context_text,
        ready=False,
    )


def _clear_for_input(reference_datetime: str, planning_start: str) -> tuple[object, ...]:
    view = invalidate_input(reference_datetime, planning_start)
    return (
        view.report_json,
        view.task_rows,
        view.routine_rows,
        view.availability_rows,
        view.fixed_event_rows,
        view.diagnostics,
        view.context,
        False,
        gr.Button(interactive=False),
        "",
        [],
        [],
        "아직 일정이 없어요.",
        "요청 0분 · 배치 0분 · 미배치 0분",
        "진단 없음",
    )


async def _parse_callback(
    text: str, reference_datetime: str, planning_start: str
) -> tuple[object, ...]:
    return _review_outputs(await parse_input(text, reference_datetime, planning_start))


def _demo_callback() -> tuple[object, ...]:
    return _review_outputs(load_canonical_demo())


def _demo_and_enable_parse() -> tuple[object, ...]:
    return (*_demo_callback(), gr.Button(interactive=True))


def _edit_and_enable_parse(
    report: str,
    tasks: Rows,
    routines: Rows,
    availability: Rows,
    fixed: Rows,
) -> tuple[object, ...]:
    return (
        *_edit_outputs(apply_table_edits(report, tasks, routines, availability, fixed)),
        gr.Button(interactive=True),
    )


def _clear_and_enable_parse(
    reference_datetime: str, planning_start: str
) -> tuple[object, ...]:
    return (
        *_clear_for_input(reference_datetime, planning_start),
        gr.Button(interactive=True),
    )


def build_blocks() -> gr.Blocks:
    now = datetime.now(KST).replace(second=0, microsecond=0)
    with gr.Blocks(title="JobFlow — 규칙 기반 일정", analytics_enabled=False) as app:
        report_state = gr.State("")
        result_state = gr.State("")
        gr.Markdown(
            "# JobFlow\n"
            "한국어 작업을 검토한 뒤 결정적 2주 계획으로 배치하는 **규칙 기반 일정** 도구예요. "
            "전체 배치량을 최대화하지 않으며 새로고침하거나 프로세스를 종료하면 데이터가 사라져요."
        )
        with gr.Row():
            text_input = gr.Textbox(
                label="한국어 일정 요청",
                lines=8,
                placeholder="마감 작업, 반복 일정, 가능한 시간, 고정 일정을 입력하세요.",
            )
            with gr.Column():
                reference_input = gr.Textbox(
                    label="기준 시각 (KST, YYYY-MM-DD HH:MM)",
                    value=_format_datetime(now),
                )
                planning_input = gr.Textbox(
                    label="계획 시작일 (KST, YYYY-MM-DD)", value=now.date().isoformat()
                )
                context_box = gr.Markdown(
                    _context_text(
                        ParseContext(
                            reference_datetime=now,
                            selected_month=SelectedMonth(year=now.year, month=now.month),
                        )
                    ),
                    label="기준 컨텍스트",
                )
        gr.Markdown(
            "**개인정보·비용 안내:** 입력한 한국어 원문은 **Parse 버튼을 누를 때만** "
            "로컬 `.env`에 설정한 OpenAI API로 전송되며 API 비용이 발생할 수 있어요. "
            "일정 생성은 모델을 호출하지 않고 JobFlow는 입력과 결과를 저장하지 않아요."
        )
        with gr.Row():
            parse_button = gr.Button("Parse — AI로 구조화", variant="primary")
            demo_button = gr.Button("키 없이 구조화 데모 불러오기")

        gr.Markdown("## 구조화 검토")
        task_table = gr.Dataframe(
            headers=TASK_HEADERS,
            datatype=[
                "str", "str", "number", "str", "str", "number", "bool", "number",
                "number", "number", "str", "bool",
            ],
            value=[],
            label="마감 작업",
            interactive=True,
            type="array",
        )
        routine_table = gr.Dataframe(
            headers=ROUTINE_HEADERS,
            datatype=[
                "str", "str", "number", "str", "str", "str", "str", "str", "number",
                "bool", "bool",
            ],
            value=[],
            label="반복 일정",
            interactive=True,
            type="array",
        )
        availability_table = gr.Dataframe(
            headers=AVAILABILITY_HEADERS,
            datatype=["str", "str", "str", "str", "str", "str", "bool"],
            value=[],
            label="가능 시간",
            interactive=True,
            type="array",
        )
        fixed_event_table = gr.Dataframe(
            headers=FIXED_EVENT_HEADERS,
            datatype=["str", "str", "str", "str", "bool"],
            value=[],
            label="고정 일정",
            interactive=True,
            type="array",
        )
        diagnostics_box = gr.Textbox(label="필드·항목 진단", value="진단 없음", lines=5)
        with gr.Row():
            confirmed_box = gr.Checkbox(label="검토 완료", value=False)
            schedule_button = gr.Button("규칙 기반 일정 만들기", interactive=False)

        gr.Markdown("## 규칙 기반 일정")
        summary_box = gr.Textbox(label="결정적 요약", value="아직 일정이 없어요.")
        stats_box = gr.Textbox(
            label="통계", value="요청 0분 · 배치 0분 · 미배치 0분"
        )
        timeline_table = gr.Dataframe(
            headers=TIMELINE_HEADERS,
            datatype=["str", "str", "str", "str", "str", "number"],
            value=[],
            label="2주 날짜별 일정",
            interactive=False,
            type="array",
        )
        unscheduled_table = gr.Dataframe(
            headers=UNSCHEDULED_HEADERS,
            datatype=[
                "str", "str", "str", "str", "number", "number", "number", "str", "str",
                "str",
            ],
            value=[],
            label="미배치 작업 (항상 표시)",
            interactive=False,
            type="array",
        )
        schedule_diagnostics = gr.Textbox(label="일정 진단", value="진단 없음", lines=4)

        review_outputs = [
            report_state,
            task_table,
            routine_table,
            availability_table,
            fixed_event_table,
            diagnostics_box,
            context_box,
            confirmed_box,
            schedule_button,
            result_state,
            timeline_table,
            unscheduled_table,
            summary_box,
            stats_box,
            schedule_diagnostics,
        ]
        schedule_outputs = [
            result_state,
            timeline_table,
            unscheduled_table,
            summary_box,
            stats_box,
            schedule_diagnostics,
        ]
        confirmation_event = confirmed_box.change(
            _confirmation_button,
            inputs=[confirmed_box, report_state],
            outputs=schedule_button,
        )
        schedule_response = schedule_button.click(
            _schedule_callback,
            inputs=[report_state, confirmed_box],
            outputs=schedule_outputs,
            trigger_mode="once",
        )
        begin_parse_outputs = [
            parse_button,
            confirmed_box,
            schedule_button,
            *schedule_outputs,
        ]
        parse_event = parse_button.click(
            _begin_parse,
            outputs=begin_parse_outputs,
            queue=False,
            trigger_mode="once",
            cancels=[schedule_response, confirmation_event],
        )
        parse_response = parse_event.then(
            _parse_callback,
            inputs=[text_input, reference_input, planning_input],
            outputs=review_outputs,
            trigger_mode="once",
        )
        parse_response.then(
            lambda: gr.Button(interactive=True), outputs=parse_button, queue=False
        )
        review_and_parse_outputs = [*review_outputs, parse_button]
        demo_button.click(
            _demo_and_enable_parse,
            outputs=review_and_parse_outputs,
            cancels=[parse_response, schedule_response],
        )

        edit_inputs = [
            report_state,
            task_table,
            routine_table,
            availability_table,
            fixed_event_table,
        ]
        for table in [task_table, routine_table, availability_table, fixed_event_table]:
            table.input(
                _edit_and_enable_parse,
                inputs=edit_inputs,
                outputs=review_and_parse_outputs,
                trigger_mode="always_last",
                cancels=[parse_response, schedule_response],
            )

        for component in [text_input, reference_input, planning_input]:
            component.input(
                _clear_and_enable_parse,
                inputs=[reference_input, planning_input],
                outputs=review_and_parse_outputs,
                cancels=[parse_response, schedule_response],
            )
    return cast(gr.Blocks, app)


__all__ = [
    "ReviewView",
    "ScheduleView",
    "apply_table_edits",
    "build_blocks",
    "invalidate_input",
    "load_canonical_demo",
    "parse_input",
    "schedule_review",
]
