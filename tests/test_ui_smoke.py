from __future__ import annotations

import asyncio
import os
from typing import Any

import gradio as gr

from jobflow.app import build_app, main
from jobflow.models import (
    RAW_INPUT_MAX_CHARS,
    Diagnostic,
    ExtractionMethod,
    Severity,
    UnscheduledReason,
)
from jobflow.services import build_calendar_month_view
from jobflow.ui import (
    APP_JS,
    _begin_parse,
    _begin_schedule,
    _details_markup,
    _month_button_updates,
    _move_month,
    _navigate_current_month,
    _navigate_month,
    _parse_selected_month,
    _render_calendar_view,
    _review_outputs,
    _review_section_updates,
    apply_table_edits,
    invalidate_input,
    load_canonical_demo,
    parse_input,
    render_calendar_month,
    schedule_review,
)
from jobflow.validation import to_schedule_request, validate_draft


def test_build_app_constructs_without_openai_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    app = build_app()

    assert isinstance(app, gr.Blocks)
    assert app.analytics_enabled is False


def test_calendar_first_component_tree_uses_owned_roots_and_native_sidebar() -> None:
    app = build_app()
    components = app.config["components"]
    by_elem_id = {
        component["props"].get("elem_id"): component
        for component in components
        if component["props"].get("elem_id")
    }

    required_component_ids = {
        "jf-page-content",
        "jf-topbar",
        "jf-calendar-workspace",
        "jf-month-prev",
        "jf-month-current",
        "jf-month-next",
        "jf-selected-month",
        "jf-create-schedule",
        "jf-compose-panel",
        "jf-compose-title",
        "jf-compose-close",
        "jf-step-request",
        "jf-step-review",
        "jf-step-calendar",
    }
    assert required_component_ids <= by_elem_id.keys()
    html_config = "\n".join(
        str(component["props"].get("html_template", ""))
        + str(component["props"].get("value", ""))
        for component in components
    )
    for semantic_id in ("jf-schedule-details", "jf-unplaced-details"):
        assert f'id="{semantic_id}"' in html_config
    sidebar = by_elem_id["jf-compose-panel"]
    assert sidebar["type"] == "sidebar"
    assert sidebar["props"]["position"] == "right"
    assert sidebar["props"]["width"] == 440
    assert sidebar["props"]["open"] is False

    component_text = [
        component["props"].get("elem_id")
        or component["props"].get("html_template", "")
        for component in components
    ]
    topbar_index = next(i for i, value in enumerate(component_text) if "jf-topbar" in value)
    calendar_index = next(
        i for i, value in enumerate(component_text) if "jf-calendar-workspace" in value
    )
    assert topbar_index < calendar_index < component_text.index("jf-compose-panel")


def test_calendar_first_removes_hero_summary_boxes_and_starts_details_closed() -> None:
    app = build_app()
    components = app.config["components"]
    labels = {component["props"].get("label") for component in components}
    classes = {
        class_name
        for component in components
        for class_name in component["props"].get("elem_classes", [])
    }
    html_config = "\n".join(
        str(component["props"].get("html_template", ""))
        + str(component["props"].get("value", ""))
        for component in components
    )

    assert "jf-hero" not in classes
    assert "결정적 요약" not in labels
    assert "통계" not in labels
    assert '<details id="jf-schedule-details" class="jf-secondary">' in html_config
    assert '<details id="jf-unplaced-details" class="jf-secondary">' in html_config
    assert '<details id="jf-schedule-details" class="jf-secondary" open' not in html_config
    assert '<details id="jf-unplaced-details" class="jf-secondary" open' not in html_config


def test_raw_input_config_exposes_authoritative_max_length() -> None:
    app = build_app()
    raw_input = next(
        component
        for component in app.config["components"]
        if component["props"].get("label") == "한국어 일정 요청"
    )

    assert raw_input["props"]["max_length"] == RAW_INPUT_MAX_CHARS


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
    assert components["캘린더에 반영"] in begin_parse["outputs"]
    assert components["상세 일정"] in begin_parse["outputs"]
    assert components["월간 달력"] in begin_parse["outputs"]


def test_raw_input_invalidation_clears_stale_review_and_result() -> None:
    invalidated = invalidate_input("2026-03-03 10:00", "2026-03")

    assert invalidated.report_json == ""
    assert invalidated.task_rows == []
    assert invalidated.routine_rows == []
    assert invalidated.availability_rows == []
    assert invalidated.fixed_event_rows == []
    assert "2026-03-03 10:00" in invalidated.context
    assert "입력이 바뀌어" in invalidated.diagnostics


def test_selected_month_adapter_accepts_only_year_month() -> None:
    selected = _parse_selected_month("2026-12")

    assert (selected.year, selected.month) == (2026, 12)

    for invalid in ("2026-12-01", "2026-2", "9999-01", "2026-13"):
        try:
            _parse_selected_month(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid month accepted: {invalid}")


def test_review_and_loading_calendar_keep_the_requested_month_visible() -> None:
    review = load_canonical_demo()
    assert review.report is not None

    review_calendar = _review_outputs(review)[15]
    loading_calendar = _begin_parse("2026-03")[9]

    assert "2026년 3월" in review_calendar
    assert "2026년 3월" in loading_calendar


def test_review_opens_first_section_with_an_error_or_deadlines_by_default() -> None:
    review = load_canonical_demo()
    assert review.report is not None and review.report.normalized is not None

    defaults = _review_section_updates(review.report)
    assert [section.open for section in defaults] == [True, False, False, False]

    routine_id = review.report.normalized.recurring_routines[0].id
    routine_error = review.report.model_copy(
        update={
            "diagnostics": [
                Diagnostic(
                    code="TEST_ERROR",
                    severity=Severity.ERROR,
                    message_ko="반복 일정 오류",
                    entity_id=routine_id,
                )
            ]
        },
        deep=True,
    )
    sections = _review_section_updates(routine_error)
    assert [section.open for section in sections] == [False, True, False, False]

    routine_rows = [row.copy() for row in review.routine_rows]
    routine_rows[0][2] = "잘못된 값"
    malformed = apply_table_edits(
        review.report_json,
        review.task_rows,
        routine_rows,
        review.availability_rows,
        review.fixed_event_rows,
    )
    assert malformed.report is not None
    malformed_sections = _review_section_updates(malformed.report)
    assert [section.open for section in malformed_sections] == [False, True, False, False]


def test_schedule_enters_loading_state_before_synchronous_result() -> None:
    review = load_canonical_demo()

    button, calendar = _begin_schedule(review.report_json)

    assert isinstance(button, gr.Button)
    assert button.interactive is False
    assert "일정을 만들고 있어요" in calendar
    assert "calendar-loading" in calendar


def test_boundary_month_navigation_disables_unavailable_direction() -> None:
    first_previous, first_next = _month_button_updates("0001-01")
    last_previous, last_next = _month_button_updates("9998-12")

    assert first_previous.interactive is False
    assert first_next.interactive is True
    assert last_previous.interactive is True
    assert last_next.interactive is False


def test_close_button_receives_descriptive_accessible_name() -> None:
    assert "#jf-compose-close" in APP_JS
    assert "일정 만들기 닫기" in APP_JS


def test_parse_failure_stays_on_request_step_with_visible_error(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    failed = asyncio.run(parse_input("지원서 작성", "2026-03-02 09:00", "2026-03"))

    outputs = _review_outputs(failed)
    request_error: Any = outputs[18]
    request_step: Any
    review_step: Any
    calendar_step: Any
    request_step, review_step, calendar_step = outputs[20:23]

    assert failed.report is not None and failed.report.normalized is None
    assert isinstance(request_error, gr.Markdown)
    assert request_error.value == failed.diagnostics
    assert request_error.visible is True
    assert isinstance(request_step, gr.Column)
    assert isinstance(review_step, gr.Column)
    assert isinstance(calendar_step, gr.Column)
    assert request_step.visible is True
    assert review_step.visible is False
    assert calendar_step.visible is False


def test_month_navigation_clears_stale_outputs_and_syncs_both_month_controls() -> None:
    app = build_app()
    components = app.config["components"]
    by_elem_id = {
        component["props"].get("elem_id"): component["id"]
        for component in components
        if component["props"].get("elem_id")
    }
    calendar_id = next(
        component["id"]
        for component in components
        if component["props"].get("label") == "월간 달력"
    )
    month_dependencies = [
        dependency
        for dependency in app.config["dependencies"]
        if by_elem_id["jf-month-prev"]
        in [target[0] for target in dependency.get("targets", [])]
    ]

    assert len(month_dependencies) == 1
    outputs = month_dependencies[0]["outputs"]
    assert by_elem_id["jf-selected-month"] in outputs
    assert calendar_id in outputs
    assert len(outputs) > 10  # review/result state is invalidated, not only the textbox


def test_month_navigation_outputs_handle_rollover_boundaries_and_invalidation() -> None:
    assert _move_month("2026-12", 1) == "2027-01"
    assert _move_month("2026-01", -1) == "2025-12"
    assert _move_month("0001-01", -1) == "0001-01"
    assert _move_month("9998-12", 1) == "9998-12"

    moved = _navigate_month("2026-03-02 09:00", "2026-03", 1)
    current = _navigate_current_month("2026-03-02 09:00", "2026-03")

    assert moved[-4:-2] == ("2026-04", "2026-04")
    assert moved[0] == ""  # stale report state cleared
    assert current[-4] == current[-3]
    assert isinstance(current[-3], str)
    assert _parse_selected_month(current[-3])


def test_secondary_disclosure_markup_includes_result_counts_and_starts_closed() -> None:
    schedule = _details_markup("schedule", 13)
    unplaced = _details_markup("unplaced", 2)

    assert schedule == (
        '<details id="jf-schedule-details" class="jf-secondary">'
        "<summary>상세 일정 (13)</summary></details>"
    )
    assert unplaced == (
        '<details id="jf-unplaced-details" class="jf-secondary">'
        "<summary>미배치 및 진단 (2)</summary></details>"
    )
    assert " open" not in schedule
    assert " open" not in unplaced


def test_calendar_is_semantic_monday_first_and_escapes_titles() -> None:
    review = load_canonical_demo()
    assert review.report is not None
    result = schedule_review(review.report_json, confirmed=True)

    assert result.result is not None
    assert result.calendar_html.startswith('<section class="calendar-shell"')
    assert 'role="grid"' in result.calendar_html
    assert 'aria-label="월요일"' in result.calendar_html
    assert 'class="calendar-day outside-month"' in result.calendar_html
    assert 'data-source-id=' in result.calendar_html
    assert 'category-label' in result.calendar_html



def test_calendar_title_is_escaped_at_html_boundary() -> None:
    review = load_canonical_demo()
    task_rows = [row.copy() for row in review.task_rows]
    task_rows[0][1] = '<img src=x onerror="alert(1)">'
    edited = apply_table_edits(
        review.report_json,
        task_rows,
        review.routine_rows,
        review.availability_rows,
        review.fixed_event_rows,
    )

    result = schedule_review(edited.report_json, confirmed=True)

    assert "<img" not in result.calendar_html
    assert "&lt;img" in result.calendar_html


def test_max_length_titles_schedule_and_render_without_truncating_visible_title() -> None:
    review = load_canonical_demo()
    task_rows = [row.copy() for row in review.task_rows]
    fixed_rows = [row.copy() for row in review.fixed_event_rows]
    task_rows[0][1] = "가" * 200
    fixed_rows[0][1] = "나" * 200
    edited = apply_table_edits(
        review.report_json,
        task_rows,
        review.routine_rows,
        review.availability_rows,
        fixed_rows,
    )

    result = schedule_review(edited.report_json, confirmed=True)

    assert result.result is not None
    assert "가" * 200 in result.calendar_html
    assert "나" * 200 in result.calendar_html


def test_calendar_overflow_control_exposes_ordered_extra_events() -> None:
    review = load_canonical_demo()
    assert review.report is not None
    scheduled = schedule_review(review.report_json, confirmed=True)
    assert scheduled.result is not None
    month = build_calendar_month_view(
        to_schedule_request(review.report), scheduled.result
    ).model_copy(deep=True)
    busy_day = next(day for day in month.days if day.events)
    original = busy_day.events[0]
    busy_day.events = [
        original.model_copy(
            update={"starts_before_segment": True, "ends_after_segment": True}
        ),
        original.model_copy(update={"view_id": "test-overflow-2"}),
        original.model_copy(update={"view_id": "test-overflow-3"}),
        original.model_copy(update={"view_id": "test-overflow-4"}),
    ]

    rendered = _render_calendar_view(month)

    assert '<details class="calendar-overflow">' in rendered
    assert "+1개 더 보기" in rendered
    assert rendered.count('data-source-id=') >= 4
    assert 'aria-label="이전 날부터 계속">←' in rendered
    assert 'aria-label="다음 날까지 계속">→' in rendered


def test_month_render_handles_required_month_lengths_and_rollover() -> None:
    month_cases = (
        ("2024-02", 35),
        ("2025-02", 35),
        ("2026-04", 35),
        ("2026-03", 42),
        ("2026-12", 35),
    )
    for month, expected_cells in month_cases:
        selected = _parse_selected_month(month)
        review = load_canonical_demo()
        assert review.report is not None
        moved = review.report.model_copy(
            update={
                "context": review.report.context.model_copy(update={"selected_month": selected})
            },
            deep=True,
        )
        html = render_calendar_month(moved, None)

        assert html.count('role="gridcell"') == expected_cells
        assert f"{selected.year}년 {selected.month}월" in html
        if month == "2026-12":
            assert 'data-date="2027-01-' in html


def test_missing_key_parse_returns_safe_korean_diagnostic(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    view = asyncio.run(parse_input("비밀 원문", "2026-03-02 09:00", "2026-03"))

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
    assert "2026년 3월" in result.calendar_html


def test_editable_table_count_limits_accept_max_and_reject_max_plus_one() -> None:
    review = load_canonical_demo()
    cases = (
        ("task_rows", 50, "task-limit"),
        ("routine_rows", 50, "routine-limit"),
        ("availability_rows", 50, "availability-limit"),
        ("fixed_event_rows", 100, "fixed-limit"),
    )
    for attribute, maximum, prefix in cases:
        source = getattr(review, attribute)[0]
        rows = []
        for index in range(maximum):
            row = source.copy()
            row[0] = f"{prefix}-{index + 1:03d}"
            rows.append(row)
        table_values = {
            "task_rows": review.task_rows,
            "routine_rows": review.routine_rows,
            "availability_rows": review.availability_rows,
            "fixed_event_rows": review.fixed_event_rows,
            attribute: rows,
        }

        accepted = apply_table_edits(review.report_json, **table_values)
        assert f"최대 {maximum}개" not in accepted.diagnostics

        table_values[attribute] = [*rows, rows[0].copy()]
        rejected = apply_table_edits(review.report_json, **table_values)
        assert not rejected.ready
        assert f"최대 {maximum}개" in rejected.diagnostics
        assert len(getattr(rejected, attribute)) == maximum + 1


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
