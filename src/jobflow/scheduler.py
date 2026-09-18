from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from jobflow.models import (
    BlockKind,
    DeadlineTask,
    Diagnostic,
    RecurringRoutine,
    ScheduleBlock,
    ScheduleRequest,
    ScheduleResult,
    ScheduleStats,
    Severity,
    UnscheduledReason,
    UnscheduledWork,
    Weekday,
    WorkKind,
)

KST = ZoneInfo("Asia/Seoul")
WEEKDAYS = list(Weekday)
SLOT = timedelta(minutes=30)


def _block_id(work_id: str, sequence: int) -> str:
    return f"block-{work_id}-{sequence:02d}"


def _horizon(request: ScheduleRequest) -> tuple[datetime, datetime]:
    start = datetime.combine(request.planning_start, time.min, KST)
    return start, start + timedelta(days=request.horizon_days)


def _overlaps(start: datetime, end: datetime, other_start: datetime, other_end: datetime) -> bool:
    return start < other_end and other_start < end


def _availability_slots(request: ScheduleRequest, *, subtract_fixed: bool) -> set[datetime]:
    horizon_start, horizon_end = _horizon(request)
    slots: set[datetime] = set()
    for offset in range(request.horizon_days):
        day = request.planning_start + timedelta(days=offset)
        weekday = WEEKDAYS[day.weekday()]
        for rule in request.availability:
            if weekday not in rule.weekdays:
                continue
            if rule.valid_from and day < rule.valid_from:
                continue
            if rule.valid_through and day > rule.valid_through:
                continue
            current = datetime.combine(day, rule.window.start, KST)
            end = datetime.combine(day, rule.window.end, KST)
            while current + SLOT <= end and current < horizon_end and current >= horizon_start:
                if not subtract_fixed or not any(
                    _overlaps(current, current + SLOT, event.start, event.end)
                    for event in request.fixed_events
                ):
                    slots.add(current)
                current += SLOT
    return slots


def _duration(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() // 60)


def _has_contiguous_run(slots: set[datetime], duration_minutes: int) -> bool:
    required_slots = duration_minutes // 30
    for start in sorted(slots):
        if all(
            start + index * SLOT in slots
            and (start + index * SLOT).date() == start.date()
            for index in range(required_slots)
        ):
            return True
    return False


def _is_confirmed(task: DeadlineTask | RecurringRoutine) -> bool:
    critical = (
        {"title", "duration_minutes", "deadline"}
        if isinstance(task, DeadlineTask)
        else {"title", "duration_minutes", "weekdays", "window"}
    )
    uncertain = {
        field
        for path in task.provenance.uncertain_fields
        for field in critical
        if field in path.split(".")
    }
    return task.provenance.confidence >= 0.70 and not uncertain


def _unscheduled(
    *,
    work_id: str,
    title: str,
    kind: WorkKind,
    reason: UnscheduledReason,
    requested: int,
    scheduled: int,
    occurrence_date: date | None = None,
    details: dict[str, str | int | float | bool | None] | None = None,
) -> UnscheduledWork:
    messages = {
        UnscheduledReason.CONFIRMATION_REQUIRED: "중요한 항목의 사용자 확인이 필요해요.",
        UnscheduledReason.OUTSIDE_HORIZON: "작업이 2주 계획 범위 밖에 있어요.",
        UnscheduledReason.NO_AVAILABILITY: "조건에 맞는 가능한 시간이 없어요.",
        UnscheduledReason.NO_CAPACITY_BEFORE_DEADLINE: "마감 전 남은 시간이 부족해요.",
        UnscheduledReason.NO_MATCHING_ROUTINE_WINDOW: "반복 일정의 허용 시간에 빈 구간이 없어요.",
        UnscheduledReason.DAILY_CAP_EXCEEDED: "하루 작업 시간 제한 때문에 배치하지 못했어요.",
        UnscheduledReason.FIXED_EVENT_CONFLICT: "고정 일정과 충돌해 배치하지 못했어요.",
    }
    return UnscheduledWork(
        work_id=work_id,
        title=title,
        kind=kind,
        reason=reason,
        requested_minutes=requested,
        scheduled_minutes=scheduled,
        remaining_minutes=requested - scheduled,
        occurrence_date=occurrence_date,
        message_ko=messages[reason],
        details=details or {"remaining_minutes": requested - scheduled},
    )


def _optional_routine_diagnostic(
    routine: RecurringRoutine,
    reason: UnscheduledReason,
    occurrence_date: date | None,
) -> Diagnostic | None:
    if routine.required:
        return None
    return Diagnostic(
        code=reason.value.upper(),
        severity=Severity.WARNING,
        message_ko="선택 반복 일정을 배치하지 못했어요.",
        entity_id=routine.id,
        details={
            "occurrence_date": occurrence_date.isoformat() if occurrence_date else None,
        },
    )


def _inside_preference(task: DeadlineTask, start: datetime, end: datetime) -> bool:
    return any(
        window.start <= start.time() and end.time() <= window.end
        for window in task.preferred_windows
    )


def _task_candidates(
    task: DeadlineTask,
    remaining: int,
    slots: set[datetime],
    occupied: set[datetime],
    global_daily: dict[date, int],
    work_daily: dict[tuple[str, date], int],
    request: ScheduleRequest,
    latest: datetime,
) -> list[tuple[bool, int, datetime]]:
    candidates: list[tuple[bool, int, datetime]] = []
    earliest = task.earliest_start or _horizon(request)[0]
    for start in sorted(slots - occupied):
        if start < earliest or start + SLOT > latest:
            continue
        day = start.date()
        global_left = request.daily_work_cap_minutes - global_daily[day]
        work_left = task.daily_cap_minutes - work_daily[(task.id, day)]
        cap = min(global_left, work_left, task.max_block_minutes, remaining)
        max_slots = cap // request.slot_minutes
        run_slots = 0
        cursor = start
        while (
            run_slots < max_slots
            and cursor in slots
            and cursor not in occupied
            and cursor.date() == day
            and cursor + SLOT <= latest
        ):
            run_slots += 1
            cursor += SLOT
        chunk = run_slots * request.slot_minutes
        if not task.splittable and chunk < remaining:
            continue
        if task.splittable:
            chunk = min(chunk, remaining)
            leftover = remaining - chunk
            if 0 < leftover < task.min_block_minutes:
                chunk -= task.min_block_minutes - leftover
            if chunk < task.min_block_minutes:
                continue
        else:
            chunk = remaining
        end = start + timedelta(minutes=chunk)
        preferred = _inside_preference(task, start, end)
        if task.splittable and not preferred and task.preferred_windows:
            preferred_limits = [
                _duration(start, datetime.combine(day, window.end, KST))
                for window in task.preferred_windows
                if window.start <= start.time() < window.end
            ]
            if preferred_limits:
                preferred_chunk = min(chunk, max(preferred_limits))
                leftover = remaining - preferred_chunk
                if 0 < leftover < task.min_block_minutes:
                    preferred_chunk -= task.min_block_minutes - leftover
                if preferred_chunk >= task.min_block_minutes:
                    chunk = preferred_chunk
                    preferred = True
        candidates.append((preferred, chunk, start))
    candidates.sort(key=lambda item: (not item[0], -item[1], item[2]))
    return candidates


def _routine_occurrences(routine: RecurringRoutine, request: ScheduleRequest) -> list[date]:
    start = max(request.planning_start, routine.start_date or request.planning_start)
    horizon_last = request.planning_start + timedelta(days=request.horizon_days - 1)
    end = min(horizon_last, routine.end_date or horizon_last)
    if start > end:
        return []
    return [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if WEEKDAYS[(start + timedelta(days=offset)).weekday()] in routine.weekdays
    ]


def _routine_intersects_horizon(routine: RecurringRoutine, request: ScheduleRequest) -> bool:
    horizon_last = request.planning_start + timedelta(days=request.horizon_days - 1)
    start = max(request.planning_start, routine.start_date or request.planning_start)
    end = min(horizon_last, routine.end_date or horizon_last)
    return start <= end


def _allocate_routine_occurrences(
    request: ScheduleRequest,
    raw_slots: set[datetime],
    usable_slots: set[datetime],
    occupied: set[datetime],
    global_daily: dict[date, int],
    blocks: list[ScheduleBlock],
    unscheduled: list[UnscheduledWork],
    diagnostics: list[Diagnostic],
) -> None:
    occurrences = [
        (occurrence_date, routine)
        for routine in request.recurring_routines
        for occurrence_date in _routine_occurrences(routine, request)
    ]
    sequences: dict[str, int] = defaultdict(int)
    for occurrence_date, routine in sorted(
        occurrences,
        key=lambda item: (item[0], -item[1].priority, item[1].id),
    ):
        if not _is_confirmed(routine):
            unscheduled.append(
                _unscheduled(
                    work_id=routine.id,
                    title=routine.title,
                    kind=WorkKind.RECURRING_ROUTINE,
                    reason=UnscheduledReason.CONFIRMATION_REQUIRED,
                    requested=routine.duration_minutes,
                    scheduled=0,
                    occurrence_date=occurrence_date,
                    details={"confidence": routine.provenance.confidence},
                )
            )
            optional = _optional_routine_diagnostic(
                routine, UnscheduledReason.CONFIRMATION_REQUIRED, occurrence_date
            )
            if optional:
                diagnostics.append(optional)
            continue

        window_start = datetime.combine(occurrence_date, routine.window.start, KST)
        window_end = datetime.combine(occurrence_date, routine.window.end, KST)
        starts: list[datetime] = []
        for start in sorted(usable_slots - occupied):
            end = start + timedelta(minutes=routine.duration_minutes)
            if start < window_start or end > window_end:
                continue
            if (
                global_daily[occurrence_date] + routine.duration_minutes
                > request.daily_work_cap_minutes
            ):
                continue
            cursor = start
            valid = True
            while cursor < end:
                if cursor not in usable_slots or cursor in occupied:
                    valid = False
                    break
                cursor += SLOT
            if valid:
                starts.append(start)

        if not starts:
            raw_window_slots = {
                slot for slot in raw_slots if window_start <= slot and slot + SLOT <= window_end
            }
            cap_blocked = (
                global_daily[occurrence_date] + routine.duration_minutes
                > request.daily_work_cap_minutes
                and bool(raw_window_slots)
            )
            reason = (
                UnscheduledReason.DAILY_CAP_EXCEEDED
                if cap_blocked
                else UnscheduledReason.NO_MATCHING_ROUTINE_WINDOW
            )
            unscheduled.append(
                _unscheduled(
                    work_id=routine.id,
                    title=routine.title,
                    kind=WorkKind.RECURRING_ROUTINE,
                    reason=reason,
                    requested=routine.duration_minutes,
                    scheduled=0,
                    occurrence_date=occurrence_date,
                    details={
                        "window_start": window_start.isoformat(),
                        "window_end": window_end.isoformat(),
                        "available_minutes": len(raw_window_slots) * request.slot_minutes,
                    },
                )
            )
            optional = _optional_routine_diagnostic(routine, reason, occurrence_date)
            if optional:
                diagnostics.append(optional)
            continue

        start = starts[0]
        end = start + timedelta(minutes=routine.duration_minutes)
        sequences[routine.id] += 1
        blocks.append(
            ScheduleBlock(
                id=_block_id(routine.id, sequences[routine.id]),
                work_id=routine.id,
                title=routine.title,
                kind=BlockKind.ROUTINE,
                start=start,
                end=end,
                occurrence_date=occurrence_date,
            )
        )
        cursor = start
        while cursor < end:
            occupied.add(cursor)
            cursor += SLOT
        global_daily[occurrence_date] += routine.duration_minutes



def build_schedule(request: ScheduleRequest) -> ScheduleResult:
    """Build a pure, deterministic constrained-routine-first greedy schedule."""
    horizon_start, horizon_end = _horizon(request)
    raw_slots = _availability_slots(request, subtract_fixed=False)
    usable_slots = _availability_slots(request, subtract_fixed=True)
    occupied: set[datetime] = set()
    global_daily: dict[date, int] = defaultdict(int)
    work_daily: dict[tuple[str, date], int] = defaultdict(int)
    blocks: list[ScheduleBlock] = []
    unscheduled: list[UnscheduledWork] = []
    schedule_diagnostics: list[Diagnostic] = []
    requested_total = sum(task.duration_minutes for task in request.deadline_tasks)

    _allocate_routine_occurrences(
        request,
        raw_slots,
        usable_slots,
        occupied,
        global_daily,
        blocks,
        unscheduled,
        schedule_diagnostics,
    )

    for task in sorted(
        request.deadline_tasks, key=lambda item: (item.deadline, -item.priority, item.id)
    ):
        if not _is_confirmed(task):
            unscheduled.append(
                _unscheduled(
                    work_id=task.id,
                    title=task.title,
                    kind=WorkKind.DEADLINE_TASK,
                    reason=UnscheduledReason.CONFIRMATION_REQUIRED,
                    requested=task.duration_minutes,
                    scheduled=0,
                    details={"confidence": task.provenance.confidence},
                )
            )
            continue
        earliest = task.earliest_start or horizon_start
        latest = min(task.deadline, horizon_end)
        if task.deadline <= horizon_start or earliest >= horizon_end:
            unscheduled.append(
                _unscheduled(
                    work_id=task.id,
                    title=task.title,
                    kind=WorkKind.DEADLINE_TASK,
                    reason=UnscheduledReason.OUTSIDE_HORIZON,
                    requested=task.duration_minutes,
                    scheduled=0,
                    details={
                        "horizon_start": horizon_start.isoformat(),
                        "horizon_end": horizon_end.isoformat(),
                    },
                )
            )
            continue

        remaining = task.duration_minutes
        sequence = 1
        while remaining:
            candidates = _task_candidates(
                task,
                remaining,
                usable_slots,
                occupied,
                global_daily,
                work_daily,
                request,
                latest,
            )
            if not candidates:
                break
            _, chunk, start = candidates[0]
            end = start + timedelta(minutes=chunk)
            block = ScheduleBlock(
                id=_block_id(task.id, sequence),
                work_id=task.id,
                title=task.title,
                kind=BlockKind.TASK,
                start=start,
                end=end,
            )
            blocks.append(block)
            cursor = start
            while cursor < end:
                occupied.add(cursor)
                cursor += SLOT
            global_daily[start.date()] += chunk
            work_daily[(task.id, start.date())] += chunk
            remaining -= chunk
            sequence += 1

        if remaining:
            scheduled = task.duration_minutes - remaining
            raw_candidates = {
                slot for slot in raw_slots if slot >= earliest and slot + SLOT <= latest
            }
            usable_candidates = raw_candidates.intersection(usable_slots)
            if not raw_candidates:
                reason = UnscheduledReason.NO_AVAILABILITY
            elif request.daily_work_cap_minutes < task.min_block_minutes:
                reason = UnscheduledReason.DAILY_CAP_EXCEEDED
            elif usable_candidates and all(
                global_daily[slot.date()] + task.min_block_minutes
                > request.daily_work_cap_minutes
                for slot in usable_candidates
            ):
                reason = UnscheduledReason.DAILY_CAP_EXCEEDED
            elif usable_candidates and all(
                work_daily[(task.id, slot.date())] + task.min_block_minutes
                > task.daily_cap_minutes
                for slot in usable_candidates
            ):
                reason = UnscheduledReason.DAILY_CAP_EXCEEDED
            elif not usable_candidates:
                reason = UnscheduledReason.NO_CAPACITY_BEFORE_DEADLINE
            elif (
                not task.splittable
                and _has_contiguous_run(raw_candidates, remaining)
                and not _has_contiguous_run(usable_candidates, remaining)
            ):
                reason = UnscheduledReason.FIXED_EVENT_CONFLICT
            else:
                reason = UnscheduledReason.NO_CAPACITY_BEFORE_DEADLINE
            unscheduled.append(
                _unscheduled(
                    work_id=task.id,
                    title=task.title,
                    kind=WorkKind.DEADLINE_TASK,
                    reason=reason,
                    requested=task.duration_minutes,
                    scheduled=scheduled,
                    details={
                        "available_minutes_before_deadline": len(usable_candidates)
                        * request.slot_minutes,
                        "daily_cap_minutes": request.daily_work_cap_minutes,
                        "task_daily_cap_minutes": task.daily_cap_minutes,
                        "remaining_minutes": remaining,
                    },
                )
            )

    for routine in request.recurring_routines:
        dates = _routine_occurrences(routine, request)
        if not dates and not _routine_intersects_horizon(routine, request):
            requested_total += routine.duration_minutes
            unscheduled.append(
                _unscheduled(
                    work_id=routine.id,
                    title=routine.title,
                    kind=WorkKind.RECURRING_ROUTINE,
                    reason=UnscheduledReason.OUTSIDE_HORIZON,
                    requested=routine.duration_minutes,
                    scheduled=0,
                    details={
                        "horizon_start": horizon_start.isoformat(),
                        "horizon_end": horizon_end.isoformat(),
                    },
                )
            )
            optional = _optional_routine_diagnostic(
                routine, UnscheduledReason.OUTSIDE_HORIZON, None
            )
            if optional:
                schedule_diagnostics.append(optional)
        elif dates:
            requested_total += len(dates) * routine.duration_minutes

    blocks.sort(key=lambda block: (block.start, block.end, block.id))
    unscheduled.sort(
        key=lambda item: (item.work_id, item.occurrence_date or date.min, item.reason.value)
    )
    scheduled_total = sum(_duration(block.start, block.end) for block in blocks)
    result = ScheduleResult(
        blocks=blocks,
        unscheduled=unscheduled,
        diagnostics=schedule_diagnostics,
        stats=ScheduleStats(
            requested_minutes=requested_total,
            scheduled_minutes=scheduled_total,
            unscheduled_minutes=requested_total - scheduled_total,
        ),
        is_fully_scheduled=not unscheduled and scheduled_total == requested_total,
    )
    diagnostics = validate_schedule(request, result)
    if diagnostics:
        result = result.model_copy(
            update={
                "diagnostics": [*schedule_diagnostics, *diagnostics],
                "is_fully_scheduled": False,
            },
            deep=True,
        )
    return result


def _inside_availability(request: ScheduleRequest, block: ScheduleBlock) -> bool:
    slots = _availability_slots(request, subtract_fixed=False)
    cursor = block.start
    while cursor < block.end:
        if cursor not in slots:
            return False
        cursor += SLOT
    return True


def _error(message: str, **details: str | int | float | bool | None) -> Diagnostic:
    return Diagnostic(
        code="INTERNAL_SCHEDULE_INVALID",
        severity=Severity.ERROR,
        message_ko=message,
        details=details,
    )


def _expected_requested_minutes(request: ScheduleRequest) -> int:
    total = sum(task.duration_minutes for task in request.deadline_tasks)
    for routine in request.recurring_routines:
        occurrences = _routine_occurrences(routine, request)
        if occurrences:
            total += len(occurrences) * routine.duration_minutes
        elif not _routine_intersects_horizon(routine, request):
            total += routine.duration_minutes
    return total


def validate_schedule(request: ScheduleRequest, result: ScheduleResult) -> list[Diagnostic]:
    """Validate all post-schedule invariants independently of placement."""
    errors: list[Diagnostic] = []
    horizon_start, horizon_end = _horizon(request)
    tasks = {task.id: task for task in request.deadline_tasks}
    routines = {routine.id: routine for routine in request.recurring_routines}
    seen_ids: set[str] = set()
    ordered = sorted(result.blocks, key=lambda block: (block.start, block.end, block.id))
    if result.blocks != ordered:
        errors.append(_error("일정 블록 정렬이 올바르지 않아요."))
    ordered_unscheduled = sorted(
        result.unscheduled,
        key=lambda item: (item.work_id, item.occurrence_date or date.min, item.reason.value),
    )
    if result.unscheduled != ordered_unscheduled:
        errors.append(_error("미배치 항목 정렬이 올바르지 않아요."))

    global_daily: dict[date, int] = defaultdict(int)
    task_daily: dict[tuple[str, date], int] = defaultdict(int)
    for index, block in enumerate(result.blocks):
        if block.id in seen_ids:
            errors.append(_error("일정 블록 ID가 중복됐어요.", block_id=block.id))
        seen_ids.add(block.id)
        duration = _duration(block.start, block.end)
        if (
            block.start < horizon_start
            or block.end > horizon_end
            or duration <= 0
            or duration % request.slot_minutes
            or block.start.minute % request.slot_minutes
            or block.end.minute % request.slot_minutes
            or block.start.second
            or block.end.second
            or block.start.microsecond
            or block.end.microsecond
        ):
            errors.append(
                _error("일정 블록의 시간 범위나 격자가 올바르지 않아요.", block_id=block.id)
            )
        if (
            getattr(block.start.tzinfo, "key", None) != "Asia/Seoul"
            or getattr(block.end.tzinfo, "key", None) != "Asia/Seoul"
        ):
            errors.append(_error("일정 블록 시간대가 올바르지 않아요.", block_id=block.id))
        if not _inside_availability(request, block):
            errors.append(_error("일정 블록이 가능한 시간 밖에 있어요.", block_id=block.id))
        if any(
            _overlaps(block.start, block.end, event.start, event.end)
            for event in request.fixed_events
        ):
            errors.append(_error("일정 블록이 고정 일정과 겹쳐요.", block_id=block.id))
        for other in result.blocks[index + 1 :]:
            if _overlaps(block.start, block.end, other.start, other.end):
                errors.append(_error("일정 블록끼리 겹쳐요.", block_id=block.id, other_id=other.id))
        global_daily[block.start.date()] += duration
        if block.kind == BlockKind.TASK:
            task = tasks.get(block.work_id)
            if task is None or block.occurrence_date is not None:
                errors.append(_error("작업 블록의 연결 정보가 올바르지 않아요.", block_id=block.id))
            else:
                if block.end > task.deadline or (
                    task.earliest_start and block.start < task.earliest_start
                ):
                    errors.append(_error("작업 블록이 허용 범위를 벗어났어요.", block_id=block.id))
                if duration < task.min_block_minutes or duration > task.max_block_minutes:
                    errors.append(_error("작업 블록 길이가 제한을 벗어났어요.", block_id=block.id))
                task_daily[(task.id, block.start.date())] += duration
        else:
            routine = routines.get(block.work_id)
            if routine is None or block.occurrence_date != block.start.date():
                errors.append(_error("반복 블록의 연결 정보가 올바르지 않아요.", block_id=block.id))
            else:
                expected_weekday = WEEKDAYS[block.start.weekday()]
                if (
                    expected_weekday not in routine.weekdays
                    or block.start.time() < routine.window.start
                    or block.end.time() > routine.window.end
                    or duration != routine.duration_minutes
                ):
                    errors.append(_error("반복 블록이 반복 규칙을 벗어났어요.", block_id=block.id))

    for work_id in sorted(set(tasks) | set(routines)):
        work_blocks = [block for block in result.blocks if block.work_id == work_id]
        actual_ids = {block.id for block in work_blocks}
        expected_ids = {_block_id(work_id, index) for index in range(1, len(work_blocks) + 1)}
        if actual_ids != expected_ids:
            errors.append(_error("일정 블록 ID가 생성 규칙과 맞지 않아요.", work_id=work_id))

    for day, minutes in global_daily.items():
        if minutes > request.daily_work_cap_minutes:
            errors.append(_error("하루 전체 작업 제한을 초과했어요.", day=day.isoformat()))
    for (task_id, day), minutes in task_daily.items():
        if minutes > tasks[task_id].daily_cap_minutes:
            errors.append(
                _error("작업별 하루 제한을 초과했어요.", task_id=task_id, day=day.isoformat())
            )

    for task in request.deadline_tasks:
        task_blocks = [
            block
            for block in result.blocks
            if block.work_id == task.id and block.kind == BlockKind.TASK
        ]
        actual = sum(_duration(block.start, block.end) for block in task_blocks)
        if not task.splittable:
            if len(task_blocks) > 1:
                errors.append(
                    _error("나눌 수 없는 작업이 여러 블록으로 분할됐어요.", task_id=task.id)
                )
            if actual not in (0, task.duration_minutes):
                errors.append(_error("나눌 수 없는 작업이 일부만 배치됐어요.", task_id=task.id))
        entries = [
            item
            for item in result.unscheduled
            if item.work_id == task.id and item.occurrence_date is None
        ]
        if len(entries) > 1 or (
            entries
            and (
                entries[0].kind != WorkKind.DEADLINE_TASK
                or entries[0].requested_minutes != task.duration_minutes
                or entries[0].scheduled_minutes != actual
                or entries[0].remaining_minutes != task.duration_minutes - actual
            )
        ):
            errors.append(_error("작업별 미배치 통계가 실제 블록과 맞지 않아요.", task_id=task.id))
        if not entries and actual != task.duration_minutes:
            errors.append(_error("작업이 누락됐지만 미배치 항목이 없어요.", task_id=task.id))

    for routine in request.recurring_routines:
        occurrence_dates = _routine_occurrences(routine, request)
        expected_dates: list[date | None] = []
        expected_dates.extend(occurrence_dates)
        if not expected_dates and not _routine_intersects_horizon(routine, request):
            expected_dates.append(None)
        for occurrence_date in expected_dates:
            actual = sum(
                _duration(block.start, block.end)
                for block in result.blocks
                if block.work_id == routine.id
                and block.kind == BlockKind.ROUTINE
                and block.occurrence_date == occurrence_date
            )
            entries = [
                item
                for item in result.unscheduled
                if item.work_id == routine.id and item.occurrence_date == occurrence_date
            ]
            if len(entries) > 1 or (
                entries
                and (
                    entries[0].kind != WorkKind.RECURRING_ROUTINE
                    or entries[0].requested_minutes != routine.duration_minutes
                    or entries[0].scheduled_minutes != actual
                    or entries[0].remaining_minutes != routine.duration_minutes - actual
                )
            ):
                errors.append(
                    _error(
                        "반복 일정별 미배치 통계가 실제 블록과 맞지 않아요.",
                        routine_id=routine.id,
                    )
                )
            if not entries and actual != routine.duration_minutes:
                errors.append(_error("반복 일정 발생분이 누락됐어요.", routine_id=routine.id))

    known_work_ids = set(tasks) | set(routines)
    if any(item.work_id not in known_work_ids for item in result.unscheduled):
        errors.append(_error("알 수 없는 작업의 미배치 항목이 있어요."))

    scheduled = sum(_duration(block.start, block.end) for block in result.blocks)
    expected = _expected_requested_minutes(request)
    remaining = sum(item.remaining_minutes for item in result.unscheduled)
    if (
        result.stats.requested_minutes != expected
        or result.stats.scheduled_minutes != scheduled
        or result.stats.unscheduled_minutes != remaining
        or scheduled + remaining != expected
        or result.is_fully_scheduled != (remaining == 0 and not result.unscheduled)
    ):
        errors.append(_error("일정 통계가 실제 블록과 맞지 않아요."))
    return errors
