from __future__ import annotations

import os
from typing import Any, Protocol, cast

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from jobflow.models import RAW_INPUT_MAX_CHARS, ExtractionDraft, ParseContext, month_bounds


class ExtractionError(RuntimeError):
    """Safe extraction-boundary failure without provider or user payloads."""


class InputLimitError(ExtractionError):
    """Raised before provider construction when raw input exceeds the fixed limit."""


class ExtractionRunnable(Protocol):
    async def ainvoke(self, values: dict[str, object]) -> object: ...


_SYSTEM_PROMPT = """당신은 한국어 일정 입력을 구조화하는 파서예요.
반드시 지정된 ExtractionDraft 스키마만 반환하세요. 원문에서 확인되지 않은 마감,
소요 시간, 반복 요일, 가능 시간을 만들지 마세요. 입력 순서대로 task-01,
routine-01, availability-01, fixed-01 형식의 결정적 ID를 부여하세요.
각 항목의 provenance.source_text에는 근거 구절을 인용하고 extraction_method는 llm,
confidence는 0과 1 사이로 기록하세요. 불확실한 중요 필드는 uncertain_fields에 넣으세요.
정책 기본값은 priority=3, splittable=true, min_block_minutes=30,
max_block_minutes=120, daily_cap_minutes=240이며 적용 시 assumptions에 기록하고
extraction_method를 default로 기록하세요. 모든 날짜는 제공된 기준 시각만 사용해
Asia/Seoul로 해석하며, 의미가 여러 가지면 추측하지 말고 불확실로 표시하세요.
"""


def _build_runnable() -> ExtractionRunnable:
    if not os.environ.get("OPENAI_API_KEY"):
        raise ExtractionError("현재 AI 추출을 사용할 수 없어요. API 키를 확인해 주세요.")
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", _SYSTEM_PROMPT),
            (
                "human",
                "기준 시각: {reference_datetime}\n선택 월: {selected_month}\n"
                "계획 시작: {horizon_start}\n계획 종료(미포함): {horizon_end}\n"
                "시간대: {timezone}\n입력:\n{text}",
            ),
        ]
    )
    model = ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        temperature=0,
    )
    return cast(ExtractionRunnable, prompt | model.with_structured_output(ExtractionDraft))


def _assign_deterministic_ids(draft: ExtractionDraft) -> ExtractionDraft:
    return draft.model_copy(
        update={
            "deadline_tasks": [
                item.model_copy(update={"id": f"task-{index:02d}"}, deep=True)
                for index, item in enumerate(draft.deadline_tasks, start=1)
            ],
            "recurring_routines": [
                item.model_copy(update={"id": f"routine-{index:02d}"}, deep=True)
                for index, item in enumerate(draft.recurring_routines, start=1)
            ],
            "availability": [
                item.model_copy(update={"id": f"availability-{index:02d}"}, deep=True)
                for index, item in enumerate(draft.availability, start=1)
            ],
            "fixed_events": [
                item.model_copy(update={"id": f"fixed-{index:02d}"}, deep=True)
                for index, item in enumerate(draft.fixed_events, start=1)
            ],
        },
        deep=True,
    )


async def extract_draft(text: str, context: ParseContext) -> ExtractionDraft:
    """Perform exactly one structured model call and return a typed draft."""
    if not text.strip():
        raise ExtractionError("일정으로 바꿀 내용을 입력해 주세요.")
    if len(text) > RAW_INPUT_MAX_CHARS:
        raise InputLimitError("입력은 10,000자 이하로 작성해 주세요.")
    try:
        runnable = _build_runnable()
        horizon_start, horizon_end = month_bounds(context.selected_month)
        raw = await runnable.ainvoke(
            {
                "text": text,
                "reference_datetime": context.reference_datetime.isoformat(),
                "selected_month": context.selected_month.model_dump(mode="json"),
                "horizon_start": horizon_start.isoformat(),
                "horizon_end": horizon_end.isoformat(),
                "timezone": context.timezone,
            }
        )
        draft = (
            raw
            if isinstance(raw, ExtractionDraft)
            else ExtractionDraft.model_validate(cast(Any, raw))
        )
        return _assign_deterministic_ids(draft)
    except ExtractionError:
        raise
    except Exception:
        raise ExtractionError("AI 추출에 실패했어요. 잠시 후 다시 시도해 주세요.") from None
