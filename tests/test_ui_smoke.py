from __future__ import annotations

import asyncio
import os

import gradio as gr

from jobflow.app import build_app, main
from jobflow.models import ExtractionMethod, UnscheduledReason
from jobflow.ui import (
    apply_table_edits,
    invalidate_input,
    load_canonical_demo,
    parse_input,
    schedule_review,
)
from jobflow.validation import validate_draft


def test_build_app_constructs_without_openai_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    app = build_app()

    assert isinstance(app, gr.Blocks)
    assert app.analytics_enabled is False


def test_main_disables_run_history_and_uses_loopback(monkeypatch) -> None:
    launch_options: dict[str, object] = {}
    monkeypatch.delenv("GRADIO_RUN_HISTORY", raising=False)

    def fake_launch(self, **kwargs):  # type: ignore[no-untyped-def]
        launch_options.update(kwargs)

    monkeypatch.setattr(gr.Blocks, "launch", fake_launch)

    main()

    assert launch_options["server_name"] == "127.0.0.1"
    assert "run_history" not in launch_options
    assert os.environ["GRADIO_RUN_HISTORY"] == "False"


def test_input_events_cancel_in_flight_parse() -> None:
    app = build_app()

    dependencies = app.config["dependencies"]
    parse_index = next(
        index
        for index, dependency in enumerate(dependencies)
        if dependency.get("api_name") == "_parse_callback"
    )
    schedule_index = next(
        index
        for index, dependency in enumerate(dependencies)
        if dependency.get("api_name") == "_schedule_callback"
    )
    cancellation_targets = {
        target
        for dependency in dependencies
        for target in dependency.get("cancels", [])
    }

    assert parse_index in cancellation_targets
    assert schedule_index in cancellation_targets


def test_parse_start_immediately_disables_confirmation_and_schedule() -> None:
    app = build_app()
    components = {
        component["props"].get("label") or component["props"].get("value"): component["id"]
        for component in app.config["components"]
    }
    begin_parse = next(
        dependency
        for dependency in app.config["dependencies"]
        if dependency.get("api_name") == "_begin_parse"
    )

    assert components["검토 완료"] in begin_parse["outputs"]
    assert components["규칙 기반 일정 만들기"] in begin_parse["outputs"]
    assert components["2주 날짜별 일정"] in begin_parse["outputs"]


def test_raw_input_invalidation_clears_stale_review_and_result() -> None:
    invalidated = invalidate_input("2026-03-03 10:00", "2026-03-03")

    assert invalidated.report_json == ""
    assert invalidated.task_rows == []
    assert invalidated.routine_rows == []
    assert invalidated.availability_rows == []
    assert invalidated.fixed_event_rows == []
    assert "2026-03-03 10:00" in invalidated.context
    assert "입력이 바뀌어" in invalidated.diagnostics


def test_missing_key_parse_returns_safe_korean_diagnostic(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    view = asyncio.run(parse_input("비밀 원문", "2026-03-02 09:00", "2026-03-02"))

    assert not view.ready
    assert "AI 추출을 사용할 수 없어요" in view.diagnostics
    assert "비밀 원문" not in view.diagnostics


def test_canonical_demo_schedules_without_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    review = load_canonical_demo()

    assert review.ready
    result = schedule_review(review.report_json, confirmed=True)

    assert result.result is not None
    assert result.result.is_fully_scheduled
    assert result.result.stats.requested_minutes == 960
    assert result.result.stats.scheduled_minutes == 960
    assert result.result.stats.unscheduled_minutes == 0
    routine_blocks = [block for block in result.result.blocks if block.kind.value == "routine"]
    assert len(routine_blocks) == 6
    assert not result.result.unscheduled
    assert "규칙 기반 일정" in result.summary


def test_table_edit_records_user_provenance_and_invalidates_confirmation() -> None:
    review = load_canonical_demo()
    task_rows = [row.copy() for row in review.task_rows]
    task_rows[0][1] = "포트폴리오 최종 수정"

    edited = apply_table_edits(
        review.report_json,
        task_rows,
        review.routine_rows,
        review.availability_rows,
        review.fixed_event_rows,
    )

    assert edited.ready
    assert not edited.confirmed
    assert not edited.schedule_enabled
    assert edited.report is not None
    task = edited.report.normalized.deadline_tasks[0]  # type: ignore[union-attr]
    assert task.title == "포트폴리오 최종 수정"
    assert task.provenance.extraction_method == ExtractionMethod.USER
    assert "title" not in task.provenance.uncertain_fields


def test_row_confirmation_clears_uncertainty_in_provenance() -> None:
    review = load_canonical_demo()
    assert review.report is not None and review.report.normalized is not None
    draft = review.report.normalized.model_copy(deep=True)
    task = draft.deadline_tasks[0]
    task.provenance = task.provenance.model_copy(
        update={
            "extraction_method": ExtractionMethod.LLM,
            "confidence": 0.4,
            "uncertain_fields": ["title"],
        }
    )
    uncertain_report = validate_draft(draft, review.report.context)
    task_rows = [row.copy() for row in review.task_rows]
    task_rows[0][-1] = True

    confirmed = apply_table_edits(
        uncertain_report.model_dump_json(),
        task_rows,
        review.routine_rows,
        review.availability_rows,
        review.fixed_event_rows,
    )

    assert confirmed.ready
    assert confirmed.report is not None and confirmed.report.normalized is not None
    provenance = confirmed.report.normalized.deadline_tasks[0].provenance
    assert provenance.extraction_method == ExtractionMethod.USER
    assert provenance.confidence == 1.0
    assert provenance.uncertain_fields == []


def test_edit_does_not_silently_clear_low_confidence_gate() -> None:
    review = load_canonical_demo()
    assert review.report is not None and review.report.normalized is not None
    draft = review.report.normalized.model_copy(deep=True)
    task = draft.deadline_tasks[0]
    task.provenance = task.provenance.model_copy(
        update={"extraction_method": ExtractionMethod.LLM, "confidence": 0.4}
    )
    uncertain_report = validate_draft(draft, review.report.context)
    task_rows = [row.copy() for row in review.task_rows]
    task_rows[0][1] = "제목만 수정"
    task_rows[0][-1] = False

    edited = apply_table_edits(
        uncertain_report.model_dump_json(),
        task_rows,
        review.routine_rows,
        review.availability_rows,
        review.fixed_event_rows,
    )

    assert not edited.ready
    assert edited.report is not None and edited.report.normalized is not None
    provenance = edited.report.normalized.deadline_tasks[0].provenance
    assert provenance.extraction_method == ExtractionMethod.USER
    assert provenance.confidence == 0.4
    assert "CONFIRMATION_REQUIRED" in edited.diagnostics


def test_invalid_table_value_stays_visible_and_cannot_schedule() -> None:
    review = load_canonical_demo()
    task_rows = [row.copy() for row in review.task_rows]
    task_rows[0][2] = "잘못된 값"

    edited = apply_table_edits(
        review.report_json,
        task_rows,
        review.routine_rows,
        review.availability_rows,
        review.fixed_event_rows,
    )
    result = schedule_review(edited.report_json, confirmed=True)

    assert edited.task_rows[0][2] == "잘못된 값"
    assert not edited.ready
    assert "SCHEMA_INVALID" in edited.diagnostics
    assert edited.report is not None and edited.report.normalized is not None
    assert result.result is None
    assert "CONFIRMATION_REQUIRED" in result.diagnostics


def test_infeasible_demo_shows_exact_routine_reason_and_remaining_minutes() -> None:
    review = load_canonical_demo()
    fixed_rows = [row.copy() for row in review.fixed_event_rows]
    fixed_rows.append(
        [
            "fixed-02",
            "면접 시간 전체 충돌",
            "2026-03-02 19:00",
            "2026-03-02 21:00",
            True,
        ]
    )
    edited = apply_table_edits(
        review.report_json,
        review.task_rows,
        review.routine_rows,
        review.availability_rows,
        fixed_rows,
    )

    result = schedule_review(edited.report_json, confirmed=True)

    assert result.result is not None
    missed = [
        item
        for item in result.result.unscheduled
        if item.reason == UnscheduledReason.NO_MATCHING_ROUTINE_WINDOW
    ]
    assert missed
    assert missed[0].remaining_minutes == 60
    assert "no_matching_routine_window" in result.unscheduled_rows[0]


def test_infeasible_demo_shows_deadline_capacity_details() -> None:
    review = load_canonical_demo()
    fixed_rows = [row.copy() for row in review.fixed_event_rows]
    for index, day in enumerate(
        ["2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06", "2026-03-09"],
        start=2,
    ):
        fixed_rows.append(
            [
                f"fixed-{index:02d}",
                "마감 전 가능 시간 차단",
                f"{day} 19:00",
                f"{day} 22:00",
                True,
            ]
        )
    edited = apply_table_edits(
        review.report_json,
        review.task_rows,
        review.routine_rows,
        review.availability_rows,
        fixed_rows,
    )

    result = schedule_review(edited.report_json, confirmed=True)

    assert result.result is not None
    missed = [
        item
        for item in result.result.unscheduled
        if item.work_id == "task-02"
        and item.reason == UnscheduledReason.NO_CAPACITY_BEFORE_DEADLINE
    ]
    assert missed
    assert missed[0].remaining_minutes > 0
    assert "available_minutes_before_deadline" in missed[0].details
