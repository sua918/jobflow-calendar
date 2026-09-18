import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from jobflow.models import (
    AvailabilityRule,
    BlockKind,
    DeadlineTask,
    ExtractionDraft,
    ExtractionMethod,
    FixedEvent,
    LocalTimeWindow,
    ParseContext,
    RecurringRoutine,
    ScheduleBlock,
    ScheduleRequest,
    ScheduleResult,
    ScheduleStats,
    SelectedMonth,
    SourceProvenance,
    UnscheduledReason,
    UnscheduledWork,
    Weekday,
    WorkKind,
)
from jobflow.scheduler import build_schedule, validate_schedule
from jobflow.validation import to_schedule_request, validate_draft

KST = ZoneInfo("Asia/Seoul")


def prov(confidence: float = 1.0, uncertain: list[str] | None = None) -> SourceProvenance:
    return SourceProvenance(
        source_text="입력",
        extraction_method=ExtractionMethod.USER,
        confidence=confidence,
        uncertain_fields=uncertain or [],
    )


def available(
    weekdays: set[Weekday] | None = None,
    start: time = time(9),
    end: time = time(22),
) -> AvailabilityRule:
    return AvailabilityRule(
        id="availability-01",
        weekdays=weekdays or set(Weekday),
        window=LocalTimeWindow(start=start, end=end),
        provenance=prov(),
    )


def request(**changes: object) -> ScheduleRequest:
    values: dict[str, object] = {
        "selected_month": SelectedMonth(year=2026, month=3),
        "daily_work_cap_minutes": 240,
        "availability": [available()],
    }
    values.update(changes)
    return ScheduleRequest(**values)


def deadline_task(**changes: object) -> DeadlineTask:
    values: dict[str, object] = {
        "id": "task-01",
        "title": "작업",
        "duration_minutes": 120,
        "deadline": datetime(2026, 3, 3, 18, tzinfo=KST),
        "min_block_minutes": 30,
        "max_block_minutes": 60,
        "daily_cap_minutes": 120,
        "provenance": prov(),
    }
    values.update(changes)
    return DeadlineTask(**values)


def test_canonical_fixture_is_fully_schedulable_and_obeys_all_invariants() -> None:
    payload = json.loads(Path("tests/fixtures/canonical_demo.json").read_text())
    context = ParseContext.model_validate(payload["context"])
    draft = ExtractionDraft.model_validate(payload["draft"])
    report = validate_draft(draft, context)
    assert report.ready_to_schedule, report.diagnostics
    schedule_request = to_schedule_request(report)
    result = build_schedule(schedule_request)

    assert result.is_fully_scheduled
    assert result.unscheduled == []
    assert validate_schedule(schedule_request, result) == []
    assert result == build_schedule(schedule_request)
    routine_blocks = [block for block in result.blocks if block.work_id == "routine-01"]
    assert len(routine_blocks) == 6
    assert {block.start.weekday() for block in routine_blocks} == {0, 2, 4}
    assert all(
        time(19) <= block.start.time() and block.end.time() <= time(21) for block in routine_blocks
    )
    assert result.stats.requested_minutes == 960
    assert result.stats.scheduled_minutes == 960
    for left, right in zip(result.blocks, result.blocks[1:], strict=False):
        assert left.end <= right.start
    assert all(block.start.minute % 30 == block.end.minute % 30 == 0 for block in result.blocks)
    fixed = schedule_request.fixed_events[0]
    assert all(block.end <= fixed.start or fixed.end <= block.start for block in result.blocks)
    task_by_id = {task.id: task for task in schedule_request.deadline_tasks}
    assert all(
        block.end <= task_by_id[block.work_id].deadline
        for block in result.blocks
        if block.work_id in task_by_id
    )


def test_task_splitting_and_caps_are_enforced() -> None:
    result = build_schedule(
        request(
            deadline_tasks=[
                deadline_task(
                    duration_minutes=180,
                    daily_cap_minutes=60,
                    earliest_start=datetime(2026, 3, 2, 0, tzinfo=KST),
                )
            ]
        )
    )
    task_blocks = [block for block in result.blocks if block.work_id == "task-01"]
    assert [int((block.end - block.start).total_seconds() // 60) for block in task_blocks] == [
        60,
        60,
    ]
    assert result.unscheduled[0].reason == UnscheduledReason.DAILY_CAP_EXCEEDED
    assert result.unscheduled[0].remaining_minutes == 60


def test_non_splittable_task_is_one_contiguous_block_and_preference_is_used() -> None:
    task = deadline_task(
        duration_minutes=60,
        splittable=False,
        max_block_minutes=60,
        preferred_windows=[LocalTimeWindow(start=time(20), end=time(22))],
    )
    result = build_schedule(request(deadline_tasks=[task]))
    assert len(result.blocks) == 1
    assert result.blocks[0].start.time() == time(20)
    assert result.blocks[0].end - result.blocks[0].start == timedelta(minutes=60)


def test_long_valid_work_id_produces_safe_deterministic_block_id() -> None:
    long_id = "a" * 48
    result = build_schedule(
        request(deadline_tasks=[deadline_task(id=long_id, duration_minutes=60)])
    )
    assert result.blocks[0].id == f"block-{long_id}-01"
    assert len(result.blocks[0].id) == 57


def test_constrained_routine_is_allocated_before_deadline_task() -> None:
    routine = RecurringRoutine(
        id="routine-01",
        title="연습",
        duration_minutes=60,
        weekdays={Weekday.MON},
        window=LocalTimeWindow(start=time(19), end=time(20)),
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 2),
        provenance=prov(),
    )
    task = deadline_task(
        duration_minutes=60,
        deadline=datetime(2026, 3, 2, 20, tzinfo=KST),
        max_block_minutes=60,
    )
    result = build_schedule(
        request(
            deadline_tasks=[task],
            recurring_routines=[routine],
            availability=[available({Weekday.MON}, time(19), time(20))],
        )
    )
    assert [block.work_id for block in result.blocks] == ["routine-01"]
    assert result.unscheduled[0].work_id == "task-01"
    assert result.unscheduled[0].reason == UnscheduledReason.NO_CAPACITY_BEFORE_DEADLINE


def test_all_unscheduled_reasons_are_reported_deterministically() -> None:
    before_horizon = deadline_task(deadline=datetime(2026, 3, 1, 0, tzinfo=KST))
    no_availability = deadline_task(id="task-no-avail")
    fixed_conflict = deadline_task(
        id="task-fixed",
        duration_minutes=60,
        earliest_start=datetime(2026, 3, 2, 9, tzinfo=KST),
    )
    cap = deadline_task(
        id="task-cap",
        duration_minutes=60,
        min_block_minutes=60,
        max_block_minutes=60,
    )
    unconfirmed = deadline_task(id="task-confirm", provenance=prov(0.5, ["deadline"]))
    fixed = FixedEvent(
        id="fixed-01",
        title="막힘",
        start=datetime(2026, 3, 2, 9, tzinfo=KST),
        end=datetime(2026, 3, 3, 18, tzinfo=KST),
        provenance=prov(),
    )
    fragmented_task = deadline_task(
        id="task-fragmented",
        duration_minutes=120,
        splittable=False,
        max_block_minutes=120,
        earliest_start=datetime(2026, 3, 2, 9, tzinfo=KST),
    )
    fragmenting_fixed = FixedEvent(
        id="fixed-fragment",
        title="중간 고정 일정",
        start=datetime(2026, 3, 2, 10, tzinfo=KST),
        end=datetime(2026, 3, 2, 11, tzinfo=KST),
        provenance=prov(),
    )
    cases = [
        (request(deadline_tasks=[before_horizon]), UnscheduledReason.OUTSIDE_HORIZON),
        (
            request(
                deadline_tasks=[no_availability],
                availability=[available({Weekday.SAT}, time(9), time(10))],
            ),
            UnscheduledReason.NO_AVAILABILITY,
        ),
        (
            request(deadline_tasks=[fixed_conflict], fixed_events=[fixed]),
            UnscheduledReason.NO_CAPACITY_BEFORE_DEADLINE,
        ),
        (
            request(
                deadline_tasks=[fragmented_task],
                availability=[available({Weekday.MON}, time(9), time(12))],
                fixed_events=[fragmenting_fixed],
            ),
            UnscheduledReason.FIXED_EVENT_CONFLICT,
        ),
        (
            request(deadline_tasks=[cap], daily_work_cap_minutes=30),
            UnscheduledReason.DAILY_CAP_EXCEEDED,
        ),
        (request(deadline_tasks=[unconfirmed]), UnscheduledReason.CONFIRMATION_REQUIRED),
    ]
    for schedule_request, reason in cases:
        result = build_schedule(schedule_request)
        assert result.unscheduled[0].reason == reason
        assert result.unscheduled[0].details


def test_routine_window_failure_is_specific() -> None:
    routine = RecurringRoutine(
        id="routine-01",
        title="연습",
        duration_minutes=60,
        weekdays={Weekday.MON},
        window=LocalTimeWindow(start=time(19), end=time(20)),
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 2),
        provenance=prov(),
    )
    fixed = FixedEvent(
        id="fixed-01",
        title="고정",
        start=datetime(2026, 3, 2, 19, tzinfo=KST),
        end=datetime(2026, 3, 2, 20, tzinfo=KST),
        provenance=prov(),
    )
    result = build_schedule(
        request(
            recurring_routines=[routine],
            availability=[available({Weekday.MON}, time(19), time(20))],
            fixed_events=[fixed],
        )
    )
    assert result.unscheduled[0].reason == UnscheduledReason.NO_MATCHING_ROUTINE_WINDOW


def test_optional_routine_failure_emits_warning_diagnostic() -> None:
    routine = RecurringRoutine(
        id="routine-01",
        title="선택 연습",
        duration_minutes=60,
        weekdays={Weekday.MON},
        window=LocalTimeWindow(start=time(19), end=time(20)),
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 2),
        required=False,
        provenance=prov(),
    )
    result = build_schedule(
        request(
            recurring_routines=[routine],
            availability=[available({Weekday.MON}, time(9), time(10))],
        )
    )
    assert result.diagnostics[0].code == "NO_MATCHING_ROUTINE_WINDOW"
    assert result.diagnostics[0].severity == "warning"


def test_validate_schedule_catches_overlap_and_bad_stats() -> None:
    schedule_request = request(deadline_tasks=[deadline_task(duration_minutes=60)])
    block = ScheduleBlock(
        id="block-task-01-01",
        work_id="task-01",
        title="작업",
        kind="task",
        start=datetime(2026, 3, 2, 9, tzinfo=KST),
        end=datetime(2026, 3, 2, 10, tzinfo=KST),
    )
    malformed = ScheduleResult(
        blocks=[block, block.model_copy(update={"id": "block-task-01-02"})],
        stats=ScheduleStats(requested_minutes=120, scheduled_minutes=120, unscheduled_minutes=0),
        is_fully_scheduled=True,
    )
    diagnostics = validate_schedule(schedule_request, malformed)
    assert any(item.code == "INTERNAL_SCHEDULE_INVALID" for item in diagnostics)


def test_validate_schedule_reconciles_each_work_not_only_global_totals() -> None:
    first = deadline_task(id="task-01", duration_minutes=60)
    second = deadline_task(id="task-02", duration_minutes=60)
    schedule_request = request(deadline_tasks=[first, second])
    block = ScheduleBlock(
        id="block-task-01-01",
        work_id="task-01",
        title="작업",
        kind="task",
        start=datetime(2026, 3, 2, 9, tzinfo=KST),
        end=datetime(2026, 3, 2, 10, tzinfo=KST),
    )
    false_attribution = UnscheduledWork(
        work_id="task-01",
        title="작업",
        kind="deadline_task",
        reason="no_capacity_before_deadline",
        requested_minutes=60,
        scheduled_minutes=0,
        remaining_minutes=60,
        message_ko="남음",
    )
    malformed = ScheduleResult(
        blocks=[block],
        unscheduled=[false_attribution],
        stats=ScheduleStats(requested_minutes=120, scheduled_minutes=60, unscheduled_minutes=60),
        is_fully_scheduled=False,
    )
    assert validate_schedule(schedule_request, malformed)


def test_validate_schedule_rejects_split_blocks_for_non_splittable_task() -> None:
    task = deadline_task(
        duration_minutes=60,
        splittable=False,
        max_block_minutes=60,
    )
    schedule_request = request(deadline_tasks=[task])
    blocks = [
        ScheduleBlock(
            id=f"block-task-01-0{index + 1}",
            work_id="task-01",
            title="작업",
            kind=BlockKind.TASK,
            start=datetime(2026, 3, 2, 9, tzinfo=KST) + timedelta(minutes=30 * index),
            end=datetime(2026, 3, 2, 9, 30, tzinfo=KST) + timedelta(minutes=30 * index),
        )
        for index in range(2)
    ]
    malformed = ScheduleResult(
        blocks=blocks,
        stats=ScheduleStats(requested_minutes=60, scheduled_minutes=60, unscheduled_minutes=0),
        is_fully_scheduled=True,
    )
    assert validate_schedule(schedule_request, malformed)


def test_preferred_window_considers_shorter_legal_chunk() -> None:
    task = deadline_task(
        duration_minutes=120,
        max_block_minutes=120,
        preferred_windows=[LocalTimeWindow(start=time(9), end=time(10))],
    )
    result = build_schedule(request(deadline_tasks=[task]))
    task_blocks = [block for block in result.blocks if block.work_id == task.id]
    assert task_blocks[0].start.time() == time(9)
    assert task_blocks[0].end.time() == time(10)


def test_non_splittable_task_does_not_shrink_to_preferred_window() -> None:
    task = deadline_task(
        duration_minutes=120,
        splittable=False,
        max_block_minutes=120,
        preferred_windows=[LocalTimeWindow(start=time(9), end=time(10))],
    )
    result = build_schedule(request(deadline_tasks=[task]))
    task_blocks = [block for block in result.blocks if block.work_id == task.id]
    assert len(task_blocks) == 1
    assert task_blocks[0].end - task_blocks[0].start == timedelta(minutes=120)


def test_routine_fragmentation_is_not_reported_as_fixed_event_conflict() -> None:
    routine = RecurringRoutine(
        id="routine-01",
        title="연습",
        duration_minutes=60,
        weekdays={Weekday.MON},
        window=LocalTimeWindow(start=time(10), end=time(11)),
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 2),
        provenance=prov(),
    )
    task = deadline_task(
        duration_minutes=120,
        splittable=False,
        max_block_minutes=120,
        deadline=datetime(2026, 3, 2, 12, tzinfo=KST),
    )
    result = build_schedule(
        request(
            deadline_tasks=[task],
            recurring_routines=[routine],
            availability=[available({Weekday.MON}, time(9), time(12))],
        )
    )
    task_unscheduled = next(item for item in result.unscheduled if item.work_id == task.id)
    assert task_unscheduled.reason == UnscheduledReason.NO_CAPACITY_BEFORE_DEADLINE


def test_in_horizon_routine_range_without_matching_weekday_requests_no_occurrence() -> None:
    routine = RecurringRoutine(
        id="routine-01",
        title="연습",
        duration_minutes=60,
        weekdays={Weekday.TUE},
        window=LocalTimeWindow(start=time(19), end=time(20)),
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 2),
        provenance=prov(),
    )
    result = build_schedule(request(recurring_routines=[routine]))
    assert result.is_fully_scheduled
    assert result.unscheduled == []
    assert result.stats.requested_minutes == 0


def test_task_daily_cap_exhaustion_has_specific_reason() -> None:
    task = deadline_task(
        duration_minutes=180,
        deadline=datetime(2026, 3, 2, 22, tzinfo=KST),
        daily_cap_minutes=60,
    )
    result = build_schedule(request(deadline_tasks=[task]))
    assert result.unscheduled[0].reason == UnscheduledReason.DAILY_CAP_EXCEEDED


def test_validate_schedule_rejects_bad_ids_partial_atomic_work_grid_and_order() -> None:
    first = deadline_task(id="task-01", duration_minutes=60, splittable=False)
    second = deadline_task(id="task-02", duration_minutes=60)
    schedule_request = request(deadline_tasks=[first, second])
    malformed_block = ScheduleBlock(
        id="not-the-generated-id",
        work_id="task-01",
        title="작업",
        kind=BlockKind.TASK,
        start=datetime(2026, 3, 2, 9, tzinfo=KST),
        end=datetime(2026, 3, 2, 9, 30, 1, tzinfo=KST),
    )
    unscheduled = [
        UnscheduledWork(
            work_id=work_id,
            title="작업",
            kind=WorkKind.DEADLINE_TASK,
            reason=UnscheduledReason.NO_CAPACITY_BEFORE_DEADLINE,
            requested_minutes=60,
            scheduled_minutes=30 if work_id == "task-01" else 0,
            remaining_minutes=30 if work_id == "task-01" else 60,
            message_ko="남음",
        )
        for work_id in ("task-02", "task-01")
    ]
    malformed = ScheduleResult(
        blocks=[malformed_block],
        unscheduled=unscheduled,
        stats=ScheduleStats(requested_minutes=120, scheduled_minutes=30, unscheduled_minutes=90),
        is_fully_scheduled=False,
    )
    diagnostics = validate_schedule(schedule_request, malformed)
    messages = {item.message_ko for item in diagnostics}
    assert "일정 블록 ID가 생성 규칙과 맞지 않아요." in messages
    assert "나눌 수 없는 작업이 일부만 배치됐어요." in messages
    assert "일정 블록의 시간 범위나 격자가 올바르지 않아요." in messages
    assert "미배치 항목 정렬이 올바르지 않아요." in messages
