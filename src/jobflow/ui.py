from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from html import escape
from pathlib import Path
from typing import TypeAlias, cast
from zoneinfo import ZoneInfo

import gradio as gr
from pydantic import ValidationError

from jobflow.models import (
    AVAILABILITY_MAX_ITEMS,
    DEADLINE_TASKS_MAX_ITEMS,
    FIXED_EVENTS_MAX_ITEMS,
    RAW_INPUT_MAX_CHARS,
    RECURRING_ROUTINES_MAX_ITEMS,
    AvailabilityRule,
    CalendarEventView,
    CalendarMonthView,
    DeadlineTask,
    Diagnostic,
    ExtractionDraft,
    ExtractionMethod,
    FixedEvent,
    LocalTimeWindow,
    ParseContext,
    RecurringRoutine,
    ScheduleResult,
    ScheduleStats,
    SelectedMonth,
    Severity,
    SourceProvenance,
    ValidationReport,
    Weekday,
    month_bounds,
)
from jobflow.services import (
    InternalScheduleError,
    build_calendar_month_view,
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

WEEKDAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
WEEKDAY_ARIA_LABELS = [
    "월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"
]
CATEGORY_ICONS = {
    "deadline_task": "◆",
    "recurring_routine": "↻",
    "fixed_event": "■",
}

APP_CSS = """
:root {
  --jf-ink: #18181B; --jf-muted: #52525B; --jf-border: #D4D4D8;
  --jf-border-strong: #71717A; --jf-canvas: #F7F8FA; --jf-surface: #FFFFFF;
  --jf-surface-soft: #FAFAFA; --jf-primary: #2563EB; --jf-primary-hover: #1D4ED8;
  --jf-focus: #1D4ED8; --jf-deadline: #2563EB; --jf-deadline-bg: #EFF6FF;
  --jf-routine: #047857; --jf-routine-bg: #ECFDF5;
  --jf-fixed: #A16207; --jf-fixed-bg: #FFFBEB;
  --jf-warning: #92400E; --jf-warning-bg: #FFFBEB;
  --jf-danger: #B42318; --jf-danger-bg: #FEF3F2;
}
html, body { margin: 0; background: var(--jf-canvas); overflow-x: hidden; }
.gradio-container { max-width: none !important; padding: 0 !important; }
.jf-app, .jf-app button, .jf-app textarea, .jf-app input, .jf-app table {
  font-family: Pretendard, "Pretendard Variable", -apple-system, BlinkMacSystemFont,
    "Segoe UI", sans-serif;
}
#jf-page-content { width: calc(100% + 64px) !important; max-width: 1600px !important;
  margin: -16px -32px 0 !important;
  padding: 0 24px 24px !important; gap: 16px !important; color: var(--jf-ink) !important;
  background: var(--jf-canvas) !important; }
.jf-app .jf-button button, .jf-app button.jf-button { min-height: 40px; border-radius: 8px;
  white-space: nowrap; }
.jf-app button.primary { background: var(--jf-primary) !important; color: #FFF !important;
  border-color: var(--jf-primary) !important; }
.jf-app button.primary:hover { background: var(--jf-primary-hover) !important; }
.jf-app button:disabled { opacity: 1; color: var(--jf-muted); background: #F4F4F5;
  cursor: not-allowed; }
.jf-app :where(.jf-checkbox, .jf-radio) { min-height: 44px; display: flex;
  align-items: center; }
.jf-app :where(.jf-checkbox, .jf-radio) input:is([type="checkbox"], [type="radio"]) {
  width: 18px; height: 18px; min-width: 18px; max-width: 18px;
  min-height: 18px; max-height: 18px; aspect-ratio: 1 / 1;
}
.jf-app :where(button, textarea, input:not([type="checkbox"]):not([type="radio"]),
  summary, .calendar-event):focus-visible {
  outline: 2px solid var(--jf-focus) !important; outline-offset: 2px;
}
#jf-skip-link { position: fixed; left: 12px; top: -80px; z-index: 1001; padding: 10px 14px;
  background: var(--jf-surface); color: var(--jf-primary); }
#jf-skip-link:focus { top: 8px; }
#jf-topbar { height: 64px; display: grid; grid-template-columns: 112px 176px 80px 1fr 112px;
  align-items: center; gap: 16px; border-bottom: 1px solid var(--jf-border);
  background: var(--jf-surface); }
#jf-topbar > * { min-width: 0 !important; margin: 0 !important; align-self: center; }
#jf-topbar > .block { height: 40px !important; padding: 0 !important; align-content: center; }
.jf-brand { margin: 0; font-size: 18px; font-weight: 700; }
.jf-month-controls { height: 40px !important; min-height: 40px !important; display: flex;
  flex-wrap: nowrap !important; align-items: center; gap: 8px; overflow: visible !important; }
#jf-month-prev, #jf-month-next { width: 40px; min-width: 40px; flex: 0 0 40px; }
#jf-month-current { width: 80px; min-width: 80px; flex: 0 0 80px; }
#jf-topbar > .form { grid-column: 3; height: 40px !important; min-width: 80px !important; }
#jf-selected-month { min-width: 80px; height: 40px; padding: 0 !important;
  font-variant-numeric: tabular-nums; }
#jf-selected-month label, #jf-selected-month .input-container { height: 40px !important; }
#jf-selected-month textarea { height: 40px !important; min-height: 40px !important;
  max-height: 40px !important; padding: 9px 4px !important; overflow: hidden !important;
  resize: none; white-space: nowrap; text-align: center; border: 0 !important;
  background: transparent !important; font-weight: 700; box-shadow: none !important; }
#jf-create-schedule { grid-column: 5; }
#jf-calendar-workspace { min-height: 824px; width: 100%; padding: 0 !important;
  gap: 0 !important; }
#jf-calendar-workspace > div { padding: 0 !important; margin: 0 !important; }
#jf-calendar-workspace .calendar-shell { width: calc(100% + 24px); margin: -10px -12px; }
.calendar-shell { height: 824px; min-height: 824px; display: flex; flex-direction: column;
  color: var(--jf-ink);
  background: var(--jf-surface); border: 1px solid var(--jf-border); border-radius: 12px;
  overflow: auto; }
.calendar-title { min-height: 56px; display: flex; align-items: center;
  justify-content: space-between; gap: 16px; padding: 0 16px;
  border-bottom: 1px solid var(--jf-border); }
.calendar-title h3, .calendar-title p { margin: 0; }
.calendar-title h3 { font-size: 24px; line-height: 1.25; }
.calendar-title p { color: var(--jf-muted); font-size: 13px; }
.calendar-grid { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }
.calendar-weekday { height: 36px; display: grid; place-items: center; font-size: 13px;
  font-weight: 600; color: var(--jf-muted); background: var(--jf-surface-soft);
  border-bottom: 1px solid var(--jf-border); }
.calendar-day { min-width: 0; min-height: 112px; padding: 8px;
  border-right: 1px solid var(--jf-border);
  border-bottom: 1px solid var(--jf-border); background: var(--jf-surface); }
.calendar-day:nth-child(7n) { border-right: 0; }
.calendar-day:hover { background: var(--jf-surface-soft); }
.calendar-day.outside-month { color: #71717A; background: var(--jf-surface-soft); }
.calendar-day.today { box-shadow: inset 0 0 0 2px #1E3A8A; background: #DBEAFE; }
.day-number { display: inline-flex; align-items: center; justify-content: center; min-width: 24px;
  min-height: 24px; font-size: 13px; font-weight: 600; }
.day-events { display: grid; gap: 6px; margin-top: 4px; }
.calendar-event { display: grid; min-width: 0; min-height: 24px; padding: 4px 6px;
  border-left: 3px solid; border-radius: 6px; line-height: 1.25; cursor: default; }
.calendar-event.deadline_task { border-color: var(--jf-deadline);
  background: var(--jf-deadline-bg); }
.calendar-event.recurring_routine { border-color: var(--jf-routine);
  background: var(--jf-routine-bg); }
.calendar-event.fixed_event { border-color: var(--jf-fixed); background: var(--jf-fixed-bg); }
.category-label { font-size: 11px; font-weight: 600; }
.event-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 12px; font-weight: 600; }
.calendar-event time { color: var(--jf-muted); font-size: 12px; }
.calendar-overflow summary { display: flex; align-items: center;
  min-height: 32px; color: var(--jf-primary); font-size: 12px; font-weight: 600; cursor: pointer; }
.calendar-empty, .calendar-loading { flex: 1; display: grid; place-items: center;
  align-content: center; gap: 8px; min-height: 730px; padding: 32px; color: var(--jf-muted);
  background: var(--jf-surface); text-align: center; }
.calendar-empty h4, .calendar-empty p { margin: 0; }
.calendar-empty h4 { color: var(--jf-ink); font-size: 18px; }
.calendar-loading { background: var(--jf-surface); }
.jf-secondary { margin-top: 12px; background: var(--jf-surface); border-radius: 8px; }
.jf-secondary > summary { min-height: 44px; display: flex; align-items: center; padding: 0 12px;
  color: var(--jf-ink); font-weight: 600; cursor: pointer; border-bottom: 1px solid transparent; }
.jf-secondary[open] > summary { border-bottom-color: var(--jf-border); }
.jf-details-body { max-height: 440px; overflow: auto; padding: 12px; }
.jf-details-body[hidden] { display: none !important; }
#jf-compose-panel { position: fixed !important; top: 0 !important; right: -440px !important;
  bottom: 0 !important; left: auto !important; width: 440px !important; max-width: 440px !important;
  height: 100dvh !important; z-index: 900 !important; background: var(--jf-surface) !important;
  box-shadow: -8px 0 24px rgba(24, 24, 27, .10); }
#jf-compose-panel.open { right: 0 !important; }
#jf-compose-panel:not(.open) { pointer-events: none; visibility: hidden; }
#jf-compose-panel > .toggle-button { display: none !important; }
#jf-compose-panel .sidebar-content { position: relative; height: 100%;
  padding: 0 16px 80px !important;
  overflow-y: auto; overflow-x: hidden; }
.jf-compose-header { position: sticky; top: 0; z-index: 2; min-height: 56px; display: grid;
  grid-template-columns: 1fr 40px; align-items: center; gap: 8px; background: var(--jf-surface);
  border-bottom: 1px solid var(--jf-border); }
.jf-compose-header > * { min-width: 0 !important; margin: 0 !important; }
#jf-compose-close { width: 40px !important; min-width: 40px !important;
  max-width: 40px !important; height: 40px; padding: 0; justify-self: end; }
#jf-compose-title h2, #jf-step-request h3, #jf-step-review h3, #jf-step-calendar h3 {
  margin: 0; color: var(--jf-ink); }
.jf-stepper { min-height: 40px; display: flex; align-items: center;
  justify-content: space-between; padding: 0 4px; color: var(--jf-muted); font-size: 12px;
  border-bottom: 1px solid var(--jf-border); }
.jf-step { padding: 16px 4px 80px; }
.jf-table-region { max-width: 100%; overflow-x: auto; }
.jf-panel-footer { position: fixed !important; right: 0; bottom: 0; z-index: 902;
  width: 440px !important; min-width: 440px !important; max-width: 440px !important;
  height: 64px; min-height: 64px;
  display: flex; flex-wrap: nowrap !important;
  align-items: center; gap: 8px; overflow: hidden;
  box-sizing: border-box;
  padding: 10px 16px; background: var(--jf-surface);
  border-top: 1px solid var(--jf-border); }
.jf-panel-footer > * { min-width: 0 !important; margin: 0 !important; flex: 1 1 0 !important; }
.jf-panel-footer .jf-checkbox { height: 44px !important; min-height: 44px !important;
  max-height: 44px !important; padding: 0 !important; overflow: visible !important; }
.jf-panel-footer .jf-checkbox label { min-height: 44px; align-items: center; }
.jf-error { color: var(--jf-danger); background: var(--jf-danger-bg); }
.jf-scrim { position: fixed; inset: 0; z-index: 899; background: rgba(24, 24, 27, .28); }
@media (max-width: 700px) {
  #jf-page-content { padding: 0 12px 12px !important; gap: 12px !important; }
  #jf-topbar { height: 104px; grid-template-columns: 1fr 92px 112px; grid-template-rows: 48px 48px;
    gap: 8px 6px; border: 0; }
  .jf-brand { font-size: 16px; }
  #jf-topbar > .block { grid-column: 1; grid-row: 1; }
  #jf-topbar > .form { grid-column: 2; grid-row: 1; min-width: 0 !important; }
  #jf-selected-month { grid-column: 2; grid-row: 1; }
  #jf-create-schedule { grid-column: 3; grid-row: 1; }
  .jf-month-controls { grid-column: 1 / -1; grid-row: 2; justify-content: center; }
  #jf-calendar-workspace { min-height: calc(100dvh - 116px); }
  .calendar-shell { height: calc(100dvh - 116px); min-height: calc(100dvh - 116px); }
  .calendar-title { min-height: 48px; padding: 0 12px; }
  .calendar-title h3 { font-size: 20px; }
  .calendar-title p { font-size: 12px; }
  .calendar-grid { display: block; }
  .calendar-weekday, .calendar-day.outside-month, .calendar-day.empty-day-cell {
    display: none;
  }
  .calendar-day { min-height: 76px; border-right: 0; padding: 8px 10px; }
  .calendar-day::before { content: attr(data-date); display: block; min-height: 32px;
    color: var(--jf-muted); font-size: 12px; font-weight: 600; }
  .day-number { display: none; }
  .calendar-event { min-height: 44px; align-content: center; }
  .event-title { display: -webkit-box; white-space: normal; overflow-wrap: anywhere;
    -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
  .calendar-empty, .calendar-loading { min-height: calc(100dvh - 166px); }
  #jf-compose-panel { inset: 0 -100dvw 0 auto !important; width: 100dvw !important;
    max-width: none !important;
    height: 100dvh !important; }
  #jf-compose-panel.open { inset: 0 !important; }
  .jf-panel-footer { width: 100dvw !important; min-width: 0 !important;
    max-width: none !important; }
}
@media (prefers-reduced-motion: reduce) {
  .jf-app *, .jf-app *::before, .jf-app *::after { scroll-behavior: auto !important;
    animation-duration: .01ms !important; transition-duration: .01ms !important; }
}
"""

APP_JS = r"""
() => {
  const SELECTOR = '#jf-compose-panel';
  const appRoot = document.querySelector('gradio-app')?.shadowRoot || document;
  const query = (selector) => appRoot.querySelector(selector);
  let opener = null;
  let focusCalendarOnClose = false;
  let wasOpen = false;
  let wasMobile = window.matchMedia('(max-width: 700px)').matches;
  let activeStep = null;
  const visible = (el) => !!el && getComputedStyle(el).display !== 'none' &&
    el.getBoundingClientRect().width > 0;
  const focusable = (panel) => [...panel.querySelectorAll(
    'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), '
      + 'summary, [tabindex="0"]'
  )].filter(visible);
  const setModal = (panel, mobile) => {
    const page = query('#jf-page-content');
    let scrim = query('.jf-scrim');
    panel.setAttribute('aria-labelledby', 'jf-compose-title');
    if (mobile) {
      panel.setAttribute('role', 'dialog');
      panel.setAttribute('aria-modal', 'true');
      if (page) { page.setAttribute('inert', ''); page.setAttribute('aria-hidden', 'true'); }
      document.documentElement.style.overflow = 'hidden';
      if (!scrim) {
        scrim = document.createElement('div'); scrim.className = 'jf-scrim';
        scrim.setAttribute('aria-hidden', 'true'); panel.before(scrim);
      }
    } else {
      panel.setAttribute('role', 'complementary'); panel.removeAttribute('aria-modal');
      if (page) { page.removeAttribute('inert'); page.removeAttribute('aria-hidden'); }
      document.documentElement.style.overflow = ''; if (scrim) scrim.remove();
    }
  };
  const sync = () => {
    const panel = query(SELECTOR); if (!panel) return;
    const portal = appRoot instanceof Document ? document.body : appRoot;
    if (panel.parentNode !== portal) portal.append(panel);
    query('#jf-page-content')?.setAttribute('role', 'main');
    query('#jf-topbar')?.setAttribute('role', 'banner');
    query('#jf-month-prev')?.setAttribute('aria-label', '이전 달');
    query('#jf-month-next')?.setAttribute('aria-label', '다음 달');
    query('#jf-compose-close')?.setAttribute('aria-label', '일정 만들기 닫기');
    query('#jf-selected-month textarea')?.setAttribute('aria-label', '선택한 달');
    ['schedule', 'unplaced'].forEach((kind) => {
      const details = query(`#jf-${kind}-details`);
      const body = query(`#jf-${kind}-details-body`);
      const summary = details?.querySelector('summary');
      if (details && body && summary) {
        details.setAttribute('aria-owns', body.id);
        summary.setAttribute('aria-controls', body.id);
        summary.setAttribute('aria-expanded', String(details.open));
        body.setAttribute('role', 'region');
        body.setAttribute('aria-labelledby', summary.id);
        body.toggleAttribute('hidden', !details.open);
      }
    });
    const open = panel.classList.contains('open');
    const mobile = window.matchMedia('(max-width: 700px)').matches;
    panel.style.setProperty('position', 'fixed', 'important');
    panel.style.setProperty('transform', 'none', 'important');
    panel.style.setProperty('top', '0', 'important');
    panel.style.setProperty('bottom', '0', 'important');
    panel.style.setProperty('height', '100dvh', 'important');
    panel.style.setProperty('width', mobile ? '100dvw' : '440px', 'important');
    panel.style.setProperty('max-width', mobile ? 'none' : '440px', 'important');
    panel.style.setProperty('left', 'auto', 'important');
    panel.style.setProperty('right', open ? '0' : (mobile ? '-100dvw' : '-440px'), 'important');
    panel.style.setProperty('visibility', open ? 'visible' : 'hidden', 'important');
    panel.style.setProperty('pointer-events', open ? 'auto' : 'none', 'important');
    panel.querySelectorAll('.jf-panel-footer').forEach((footer) => {
      footer.style.setProperty('width', mobile ? '100dvw' : '440px', 'important');
      footer.style.setProperty('min-width', mobile ? '0' : '440px', 'important');
      footer.style.setProperty('max-width', mobile ? 'none' : '440px', 'important');
    });
    query('#calendar-heading')?.setAttribute('tabindex', '-1');
    panel.querySelectorAll(
      '#jf-compose-title, #jf-request-error, #jf-step-request, #jf-step-review, '
        + '#jf-step-calendar'
    )
      .forEach((el) => el.setAttribute('tabindex', '-1'));
    query('#jf-request-error')?.setAttribute('role', 'alert');
    if (open) {
      setModal(panel, mobile);
      if (!wasOpen || (mobile && !wasMobile && !panel.contains(document.activeElement))) {
        requestAnimationFrame(() => query('#jf-compose-title')?.focus());
      }
      const step = ['#jf-step-calendar', '#jf-step-review', '#jf-step-request']
        .map((id) => query(id)).find(visible);
      const error = query('#jf-request-error');
      const focusTarget = error && visible(error) && error.textContent.trim() ? error : step;
      const focusKey = focusTarget === error
        ? `${error.id}:${error.textContent.trim()}`
        : focusTarget?.id || null;
      if (wasOpen && focusTarget && activeStep !== focusKey) {
        requestAnimationFrame(() => focusTarget.focus());
      }
      activeStep = focusKey;
    } else {
      setModal(panel, false);
      if (wasOpen) {
        requestAnimationFrame(() => {
          (focusCalendarOnClose ? query('#calendar-heading') : opener)?.focus();
          focusCalendarOnClose = false;
        });
      }
      activeStep = null;
    }
    wasOpen = open; wasMobile = mobile;
  };
  appRoot.addEventListener('click', (event) => {
    if (event.target.closest('#jf-create-schedule')) {
      opener = event.target.closest('button') || event.target;
    }
    if (event.target.closest('#jf-calendar-view')) focusCalendarOnClose = true;
  });
  appRoot.addEventListener('keydown', (event) => {
    const panel = query(SELECTOR);
    if (!panel?.classList.contains('open')) return;
    if (event.key === 'Escape') {
      event.preventDefault(); query('#jf-compose-close')?.click();
    }
    if (event.key === 'Tab' && window.matchMedia('(max-width: 700px)').matches) {
      const items = focusable(panel); if (!items.length) return;
      const first = items[0], last = items[items.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || !items.includes(active))) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && (active === last || !items.includes(active))) {
        event.preventDefault(); first.focus();
      }
    }
  });
  const observer = new MutationObserver(sync);
  observer.observe(appRoot, {
    subtree: true,
    attributes: true,
    attributeFilter: ['class', 'hidden', 'open'],
    childList: true,
  });
  window.matchMedia('(max-width: 700px)').addEventListener('change', sync);
  sync();
}
"""


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
    calendar_html: str


def _parse_selected_month(value: str) -> SelectedMonth:
    """Parse the UI's exact YYYY-MM adapter into the shared domain type."""
    if re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value.strip()) is None:
        raise ValueError("selected month must use YYYY-MM")
    year, month = (int(part) for part in value.strip().split("-"))
    return SelectedMonth(year=year, month=month)


def _event_chip(event: CalendarEventView) -> str:
    continuation = ""
    if event.starts_before_segment:
        continuation += '<span class="continuation" aria-label="이전 날부터 계속">←</span>'
    if event.ends_after_segment:
        continuation += '<span class="continuation" aria-label="다음 날까지 계속">→</span>'
    start = event.segment_start.strftime("%H:%M")
    end = event.segment_end.strftime("%H:%M")
    return (
        f'<article class="calendar-event {escape(event.category)}" tabindex="0" '
        f'data-view-id="{escape(event.view_id)}" data-source-id="{escape(event.source_id)}" '
        f'aria-label="{escape(event.aria_label_ko)}">'
        f'<span class="category-label"><span aria-hidden="true">'
        f'{CATEGORY_ICONS[event.category]}</span> {escape(event.category_label_ko)}</span>'
        f'<span class="event-title">{escape(event.title)}</span>'
        f'<time>{start}–{end}</time>{continuation}</article>'
    )


def _render_calendar_view(
    view: CalendarMonthView, status: str = "요청 0분 · 배치 0분 · 미배치 0분"
) -> str:
    month_label = f"{view.selected_month.year}년 {view.selected_month.month}월"
    header = "".join(
        f'<div class="calendar-weekday" role="columnheader" aria-label="{aria}">{label}</div>'
        for label, aria in zip(WEEKDAY_LABELS, WEEKDAY_ARIA_LABELS, strict=True)
    )
    cells: list[str] = []
    for cell in view.days:
        classes = ["calendar-day"]
        if not cell.in_selected_month:
            classes.append("outside-month")
        if cell.is_today:
            classes.append("today")
        if cell.in_selected_month and not cell.events:
            classes.append("empty-day-cell")
        visible = cell.events[:3]
        overflow = cell.events[3:]
        events = "".join(_event_chip(event) for event in visible)
        if overflow:
            hidden_events = "".join(_event_chip(event) for event in overflow)
            events += (
                '<details class="calendar-overflow">'
                f'<summary aria-label="{cell.date.isoformat()} 일정 {len(overflow)}개 더 보기">'
                f'+{len(overflow)}개 더 보기</summary>{hidden_events}</details>'
            )
        aria = f"{cell.date.isoformat()}, 일정 {len(cell.events)}개"
        cells.append(
            f'<div class="{" ".join(classes)}" role="gridcell" aria-label="{aria}" '
            f'data-date="{cell.date.isoformat()}">'
            f'<time class="day-number" datetime="{cell.date.isoformat()}">{cell.date.day}</time>'
            f'<div class="day-events">{events}</div></div>'
        )
    return (
        '<section class="calendar-shell" aria-labelledby="calendar-heading">'
        f'<div class="calendar-title"><h3 id="calendar-heading">{month_label}</h3>'
        f'<p id="jf-calendar-status" aria-live="polite">{escape(status)}</p></div>'
        f'<div class="calendar-grid" role="grid" aria-label="{month_label} 월간 달력" '
        f'aria-rowcount="{view.row_count + 1}" aria-colcount="7">'
        f'{header}{"".join(cells)}</div></section>'
    )


def render_calendar_month(
    report: ValidationReport, result: ScheduleResult | None
) -> str:
    """Render the approved backend calendar projection with escaped DOM content."""
    request = to_schedule_request(report)
    safe_result = result or ScheduleResult(
        blocks=[],
        unscheduled=[],
        diagnostics=[],
        stats=ScheduleStats(requested_minutes=0, scheduled_minutes=0, unscheduled_minutes=0),
        is_fully_scheduled=True,
    )
    stats = safe_result.stats
    status = (
        f"요청 {stats.requested_minutes}분 · 배치 {stats.scheduled_minutes}분 · "
        f"미배치 {stats.unscheduled_minutes}분"
    )
    return _render_calendar_view(
        build_calendar_month_view(request, safe_result, today=datetime.now(KST).date()), status
    )


def _empty_calendar(
    message: str = "일정을 만들면 월간 달력이 여기에 표시돼요.",
    selected_month: str | None = None,
) -> str:
    now = datetime.now(KST)
    month = selected_month or f"{now.year:04d}-{now.month:02d}"
    try:
        parsed = _parse_selected_month(month)
        month_label = f"{parsed.year}년 {parsed.month}월"
    except ValueError:
        month_label = "선택한 달"
    return (
        '<section class="calendar-shell" aria-labelledby="calendar-heading">'
        f'<div class="calendar-title"><h3 id="calendar-heading">{month_label}</h3>'
        '<p id="jf-calendar-status" aria-live="polite">요청 0분 · 배치 0분 · 미배치 0분</p>'
        '</div><div class="calendar-empty" role="status">'
        '<span aria-hidden="true">▦</span><h4>아직 일정이 없어요</h4>'
        f'<p>{escape(message)}</p></div></section>'
    )


def _details_markup(kind: str, count: int) -> str:
    if kind == "schedule":
        element_id, label = "jf-schedule-details", "상세 일정"
    elif kind == "unplaced":
        element_id, label = "jf-unplaced-details", "미배치 및 진단"
    else:
        raise ValueError("unknown details kind")
    return (
        f'<details id="{element_id}" class="jf-secondary">'
        f'<summary id="{element_id}-summary" aria-controls="{element_id}-body">'
        f"{label} ({count})</summary></details>"
    )


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
    section: str | None = None,
) -> ReviewView:
    diagnostic = Diagnostic(
        code="SCHEMA_INVALID",
        severity=Severity.ERROR,
        message_ko=message,
        field=section,
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


def _changed_review_section(
    previous_report: ValidationReport,
    task_rows: Rows,
    routine_rows: Rows,
    availability_rows: Rows,
    fixed_event_rows: Rows,
) -> str:
    previous = _view_from_report(previous_report)
    sections = (
        ("deadline_tasks", task_rows, previous.task_rows),
        ("recurring_routines", routine_rows, previous.routine_rows),
        ("availability", availability_rows, previous.availability_rows),
        ("fixed_events", fixed_event_rows, previous.fixed_event_rows),
    )
    return next(
        (section for section, current, original in sections if current != original),
        "deadline_tasks",
    )


async def parse_input(text: str, reference_datetime: str, selected_month: str) -> ReviewView:
    try:
        context = ParseContext(
            reference_datetime=_parse_datetime(reference_datetime),
            selected_month=_parse_selected_month(selected_month),
        )
    except (ValueError, ValidationError):
        return _safe_error_view("기준 시각과 계획 월(YYYY-MM) 형식을 확인해 주세요.")
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
        table_limits = (
            ("deadline_tasks", "마감 작업", task_rows, DEADLINE_TASKS_MAX_ITEMS),
            ("recurring_routines", "반복 일정", routine_rows, RECURRING_ROUTINES_MAX_ITEMS),
            ("availability", "가능 시간", availability_rows, AVAILABILITY_MAX_ITEMS),
            ("fixed_events", "고정 일정", fixed_event_rows, FIXED_EVENTS_MAX_ITEMS),
        )
        for section, label, rows, maximum in table_limits:
            if len(rows) > maximum:
                return _invalid_edit_view(
                    previous_report,
                    task_rows,
                    routine_rows,
                    availability_rows,
                    fixed_event_rows,
                    f"{label}은 최대 {maximum}개까지 입력할 수 있어요.",
                    section,
                )
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
                _changed_review_section(
                    previous_report,
                    task_rows,
                    routine_rows,
                    availability_rows,
                    fixed_event_rows,
                ),
            )
        return _safe_error_view("표의 값과 날짜·시간 형식을 확인해 주세요.")
    except Exception:
        return _safe_error_view("검토 내용을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.")


def _selected_month_from_report_json(report_json: str) -> str | None:
    try:
        selected = ValidationReport.model_validate_json(report_json).context.selected_month
    except (ValidationError, ValueError):
        return None
    return f"{selected.year:04d}-{selected.month:02d}"


def schedule_review(report_json: str, confirmed: bool) -> ScheduleView:
    selected_month = _selected_month_from_report_json(report_json)
    if not confirmed:
        return ScheduleView(
            result=None,
            result_json="",
            timeline_rows=[],
            unscheduled_rows=[],
            summary="검토 완료를 체크해야 일정을 만들 수 있어요.",
            stats="요청 0분 · 배치 0분 · 미배치 0분",
            diagnostics="[ERROR] CONFIRMATION_REQUIRED · 검토 완료를 확인해 주세요.",
            calendar_html=_empty_calendar(
                "검토 완료 후 일정을 만들어 주세요.", selected_month=selected_month
            ),
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
            calendar_html=_empty_calendar(
                "입력 진단을 먼저 확인해 주세요.", selected_month=selected_month
            ),
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
            calendar_html=_empty_calendar(
                "일정을 안전하게 만들지 못했어요.", selected_month=selected_month
            ),
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
            calendar_html=_empty_calendar(
                "일정을 처리하지 못했어요.", selected_month=selected_month
            ),
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
        calendar_html=render_calendar_month(report, result),
    )


def _review_outputs(view: ReviewView) -> tuple[object, ...]:
    selected_month = None
    failed = view.report is None or view.report.normalized is None
    if view.report is not None:
        selected = view.report.context.selected_month
        selected_month = f"{selected.year:04d}-{selected.month:02d}"
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
        _empty_calendar(selected_month=selected_month),
        _details_markup("schedule", 0),
        _details_markup("unplaced", 0),
        gr.Markdown(value=view.diagnostics if failed else "", visible=failed),
        gr.Sidebar(open=True),
        gr.Column(visible=failed),
        gr.Column(visible=not failed),
        gr.Column(visible=False),
        *_review_section_updates(view.report),
    )


def _edit_outputs(view: ReviewView) -> tuple[object, ...]:
    selected_month = None
    if view.report is not None:
        selected = view.report.context.selected_month
        selected_month = f"{selected.year:04d}-{selected.month:02d}"
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
        _empty_calendar(
            "입력이 바뀌어 이전 일정을 지웠어요.", selected_month=selected_month
        ),
        _details_markup("schedule", 0),
        _details_markup("unplaced", 0),
        gr.Markdown(value="", visible=False),
        gr.Sidebar(open=True),
        gr.Column(visible=False),
        gr.Column(visible=True),
        gr.Column(visible=False),
        *_review_section_updates(view.report),
    )


def _review_section_updates(
    report: ValidationReport | None,
) -> tuple[gr.Accordion, gr.Accordion, gr.Accordion, gr.Accordion]:
    open_index = 0
    if report is not None and report.normalized is not None:
        section_indexes = {
            "deadline_tasks": 0,
            "recurring_routines": 1,
            "availability": 2,
            "fixed_events": 3,
        }
        entity_groups = (
            {item.id for item in report.normalized.deadline_tasks},
            {item.id for item in report.normalized.recurring_routines},
            {item.id for item in report.normalized.availability},
            {item.id for item in report.normalized.fixed_events},
        )
        for diagnostic in report.diagnostics:
            if diagnostic.severity != Severity.ERROR:
                continue
            if diagnostic.field in section_indexes:
                open_index = section_indexes[diagnostic.field]
                break
            if diagnostic.entity_id is None:
                continue
            matched = next(
                (
                    index
                    for index, entity_ids in enumerate(entity_groups)
                    if diagnostic.entity_id in entity_ids
                ),
                None,
            )
            if matched is not None:
                open_index = matched
                break
    return cast(
        tuple[gr.Accordion, gr.Accordion, gr.Accordion, gr.Accordion],
        tuple(gr.Accordion(open=index == open_index) for index in range(4)),
    )


def _confirmation_button(confirmed: bool, report_json: str) -> gr.Button:
    try:
        ready = ValidationReport.model_validate_json(report_json).ready_to_schedule
    except (ValidationError, ValueError):
        ready = False
    return gr.Button(interactive=bool(confirmed and ready))


def _schedule_outputs(view: ScheduleView) -> tuple[object, ...]:
    completed = view.result is not None
    return (
        view.result_json,
        view.timeline_rows,
        view.unscheduled_rows,
        view.summary,
        view.stats,
        view.diagnostics,
        view.calendar_html,
        _details_markup("schedule", len(view.timeline_rows)),
        _details_markup("unplaced", len(view.unscheduled_rows)),
        gr.Markdown(value="", visible=False),
        gr.Sidebar(open=True),
        gr.Column(visible=False),
        gr.Column(visible=not completed),
        gr.Column(visible=completed),
        gr.Button(interactive=not completed),
    )


def _schedule_callback(report_json: str, confirmed: bool) -> tuple[object, ...]:
    return _schedule_outputs(schedule_review(report_json, confirmed))


def _begin_parse(selected_month: str) -> tuple[object, ...]:
    loading_calendar = _empty_calendar("일정을 만들고 있어요.", selected_month=selected_month)
    loading_calendar = loading_calendar.replace(
        'class="calendar-empty" role="status"',
        'class="calendar-loading" role="status" aria-live="polite"',
    ).replace("요청 0분 · 배치 0분 · 미배치 0분", "분석 중")
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
        loading_calendar,
        _details_markup("schedule", 0),
        _details_markup("unplaced", 0),
        gr.Markdown(value="", visible=False),
        gr.Sidebar(open=True),
        gr.Column(visible=True),
        gr.Column(visible=False),
        gr.Column(visible=False),
    )


def _begin_schedule(report_json: str) -> tuple[object, ...]:
    selected_month = None
    try:
        report = ValidationReport.model_validate_json(report_json)
        selected = report.context.selected_month
        selected_month = f"{selected.year:04d}-{selected.month:02d}"
    except (ValidationError, ValueError):
        pass
    loading_calendar = _empty_calendar(
        "일정을 만들고 있어요.", selected_month=selected_month
    ).replace(
        'class="calendar-empty" role="status"',
        'class="calendar-loading" role="status" aria-live="polite"',
    )
    return gr.Button(interactive=False), loading_calendar


def invalidate_input(reference_datetime: str, selected_month: str) -> ReviewView:
    try:
        context = ParseContext(
            reference_datetime=_parse_datetime(reference_datetime),
            selected_month=_parse_selected_month(selected_month),
        )
        context_text = _context_text(context)
    except (ValueError, ValidationError):
        context_text = "기준 시각과 계획 월(YYYY-MM) 형식을 확인해 주세요."
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


def _clear_for_input(reference_datetime: str, selected_month: str) -> tuple[object, ...]:
    view = invalidate_input(reference_datetime, selected_month)
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
        _empty_calendar(selected_month=selected_month),
        _details_markup("schedule", 0),
        _details_markup("unplaced", 0),
        gr.Markdown(value="", visible=False),
        gr.Sidebar(open=True),
        gr.Column(visible=True),
        gr.Column(visible=False),
        gr.Column(visible=False),
        *_review_section_updates(None),
    )


async def _parse_callback(
    text: str, reference_datetime: str, selected_month: str
) -> tuple[object, ...]:
    return _review_outputs(await parse_input(text, reference_datetime, selected_month))


def _demo_callback() -> tuple[object, ...]:
    return _review_outputs(load_canonical_demo())


def _demo_and_enable_parse() -> tuple[object, ...]:
    view = load_canonical_demo()
    if view.report is None:
        now = datetime.now(KST).replace(second=0, microsecond=0)
        reference = _format_datetime(now)
        selected_month = f"{now.year:04d}-{now.month:02d}"
    else:
        context = view.report.context
        reference = _format_datetime(context.reference_datetime)
        selected_month = f"{context.selected_month.year:04d}-{context.selected_month.month:02d}"
    return (
        *_review_outputs(view),
        gr.Button(interactive=True),
        reference,
        selected_month,
        selected_month,
    )


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
    reference_datetime: str, selected_month: str
) -> tuple[object, ...]:
    return (
        *_clear_for_input(reference_datetime, selected_month),
        gr.Button(interactive=True),
    )


def _move_month(selected_month: str, delta: int) -> str:
    selected = _parse_selected_month(selected_month)
    absolute = selected.year * 12 + selected.month - 1 + delta
    year, zero_based_month = divmod(absolute, 12)
    if year < 1 or year > 9998:
        return selected_month
    return f"{year:04d}-{zero_based_month + 1:02d}"


def _month_button_updates(selected_month: str) -> tuple[gr.Button, gr.Button]:
    try:
        selected = _parse_selected_month(selected_month)
    except ValueError:
        return gr.Button(interactive=False), gr.Button(interactive=False)
    at_first_month = selected.year == 1 and selected.month == 1
    at_last_month = selected.year == 9998 and selected.month == 12
    return (
        gr.Button(interactive=not at_first_month),
        gr.Button(interactive=not at_last_month),
    )


def _current_month() -> str:
    now = datetime.now(KST)
    return f"{now.year:04d}-{now.month:02d}"


def _topbar_month_outputs(reference_datetime: str, selected_month: str) -> tuple[object, ...]:
    cleared = list(_clear_and_enable_parse(reference_datetime, selected_month))
    cleared[-9] = gr.Sidebar(open=False)
    return (
        *cleared,
        selected_month,
        selected_month,
        *_month_button_updates(selected_month),
    )


def _navigate_month(
    reference_datetime: str, selected_month: str, delta: int
) -> tuple[object, ...]:
    return _topbar_month_outputs(
        reference_datetime, _move_month(selected_month, delta)
    )


def _navigate_current_month(
    reference_datetime: str, _selected_month: str
) -> tuple[object, ...]:
    return _topbar_month_outputs(reference_datetime, _current_month())


def build_blocks() -> gr.Blocks:
    now = datetime.now(KST).replace(second=0, microsecond=0)
    month_value = f"{now.year:04d}-{now.month:02d}"
    context_value = _context_text(
        ParseContext(
            reference_datetime=now,
            selected_month=SelectedMonth(year=now.year, month=now.month),
        )
    )
    with gr.Blocks(
        title="JobFlow — 월간 규칙 기반 일정",
        analytics_enabled=False,
        fill_width=True,
        elem_classes=["jf-app"],
    ) as app:
        report_state = gr.State("")
        result_state = gr.State("")
        summary_state = gr.State("아직 일정이 없어요.")
        stats_state = gr.State("요청 0분 · 배치 0분 · 미배치 0분")

        with gr.Column(elem_id="jf-page-content", elem_classes=["jf-app"]):
            with gr.Row(elem_id="jf-topbar"):
                gr.HTML(
                    '<a id="jf-skip-link" href="#calendar-heading">달력으로 건너뛰기</a>'
                    '<p class="jf-brand">JobFlow</p>',
                    apply_default_css=False,
                    js_on_load=None,
                )
                with gr.Row(elem_classes=["jf-month-controls"]):
                    previous_month = gr.Button(
                        "‹",
                        elem_id="jf-month-prev",
                        elem_classes=["jf-button"],
                    )
                    current_month = gr.Button(
                        "이번 달",
                        elem_id="jf-month-current",
                        elem_classes=["jf-button"],
                    )
                    next_month = gr.Button(
                        "›",
                        elem_id="jf-month-next",
                        elem_classes=["jf-button"],
                    )
                selected_month_display = gr.Textbox(
                    value=month_value,
                    show_label=False,
                    interactive=False,
                    elem_id="jf-selected-month",
                )
                create_button = gr.Button(
                    "일정 만들기",
                    variant="primary",
                    elem_id="jf-create-schedule",
                    elem_classes=["jf-button"],
                )

            with gr.Column(elem_id="jf-calendar-workspace"):
                calendar_html = gr.HTML(
                    _empty_calendar(selected_month=month_value),
                    label="월간 달력",
                    apply_default_css=False,
                    js_on_load=None,
                )

            schedule_details = gr.HTML(
                _details_markup("schedule", 0),
                apply_default_css=False,
                js_on_load=None,
            )
            with gr.Column(elem_id="jf-schedule-details-body", elem_classes=["jf-details-body"]):
                timeline_table = gr.Dataframe(
                    headers=TIMELINE_HEADERS,
                    datatype=["str", "str", "str", "str", "str", "number"],
                    value=[],
                    label="상세 일정",
                    interactive=False,
                    type="array",
                )
            unplaced_details = gr.HTML(
                _details_markup("unplaced", 0),
                apply_default_css=False,
                js_on_load=None,
            )
            with gr.Column(elem_id="jf-unplaced-details-body", elem_classes=["jf-details-body"]):
                unscheduled_table = gr.Dataframe(
                    headers=UNSCHEDULED_HEADERS,
                    datatype=[
                        "str",
                        "str",
                        "str",
                        "str",
                        "number",
                        "number",
                        "number",
                        "str",
                        "str",
                        "str",
                    ],
                    value=[],
                    label="미배치 작업",
                    interactive=False,
                    type="array",
                )
                schedule_diagnostics = gr.Textbox(
                    label="일정 진단",
                    value="진단 없음",
                    lines=4,
                    interactive=False,
                )

        with gr.Sidebar(
            label="일정 만들기",
            position="right",
            width=440,
            open=False,
            elem_id="jf-compose-panel",
            elem_classes=["jf-app"],
        ) as compose_panel:
            with gr.Row(elem_classes=["jf-compose-header"]):
                gr.Markdown("## 일정 만들기", elem_id="jf-compose-title")
                close_button = gr.Button(
                    "×",
                    elem_id="jf-compose-close",
                    elem_classes=["jf-button"],
                )
            gr.HTML(
                '<div class="jf-stepper" aria-label="진행 단계">'
                '<span>1 요청</span><span>2 확인</span><span>3 캘린더</span></div>',
                apply_default_css=False,
                js_on_load=None,
            )
            with gr.Column(visible=True, elem_classes=["jf-step"]) as request_step:
                gr.Markdown("### 요청 입력", elem_id="jf-step-request")
                request_error = gr.Markdown(
                    "",
                    visible=False,
                    elem_id="jf-request-error",
                    elem_classes=["jf-error"],
                )
                gr.Markdown("일정으로 바꿀 작업과 반복 습관을 한국어로 적어 주세요.")
                text_input = gr.Textbox(
                    label="한국어 일정 요청",
                    lines=8,
                    max_length=RAW_INPUT_MAX_CHARS,
                    placeholder="마감 작업, 반복 일정, 가능한 시간, 고정 일정을 입력하세요.",
                    elem_classes=["jf-text-field"],
                )
                planning_input = gr.Textbox(
                    label="계획 월 (KST, YYYY-MM)",
                    value=month_value,
                    placeholder="2026-03",
                    max_lines=1,
                    elem_classes=["jf-text-field"],
                )
                with gr.Accordion("고급 설정", open=False):
                    reference_input = gr.Textbox(
                        label="기준 시각 (KST, YYYY-MM-DD HH:MM)",
                        value=_format_datetime(now),
                        elem_classes=["jf-text-field"],
                    )
                    context_box = gr.Markdown(context_value, label="기준 컨텍스트")
                gr.Markdown(
                    "**개인정보·비용:** 요청 분석 시에만 로컬 `.env`의 OpenAI API로 "
                    "원문을 한 번 전송해요. 일정 생성은 모델을 호출하지 않고 저장하지 않아요."
                )
                with gr.Row(elem_classes=["jf-panel-footer"]):
                    demo_button = gr.Button("예시 불러오기", elem_classes=["jf-button"])
                    parse_button = gr.Button(
                        "요청 분석하기",
                        variant="primary",
                        elem_classes=["jf-button"],
                    )

            with gr.Column(visible=False, elem_classes=["jf-step"]) as review_step:
                gr.Markdown("### 일정 확인", elem_id="jf-step-review")
                diagnostics_box = gr.Textbox(
                    label="필드·항목 진단",
                    value="진단 없음",
                    lines=4,
                    interactive=False,
                )
                with gr.Accordion("마감 작업", open=True) as task_section:
                    task_table = gr.Dataframe(
                        headers=TASK_HEADERS,
                        datatype=[
                            "str",
                            "str",
                            "number",
                            "str",
                            "str",
                            "number",
                            "bool",
                            "number",
                            "number",
                            "number",
                            "str",
                            "bool",
                        ],
                        value=[],
                        label="마감 작업",
                        interactive=True,
                        type="array",
                        elem_classes=["jf-table-region"],
                    )
                with gr.Accordion("반복 일정", open=False) as routine_section:
                    routine_table = gr.Dataframe(
                        headers=ROUTINE_HEADERS,
                        datatype=[
                            "str",
                            "str",
                            "number",
                            "str",
                            "str",
                            "str",
                            "str",
                            "str",
                            "number",
                            "bool",
                            "bool",
                        ],
                        value=[],
                        label="반복 일정",
                        interactive=True,
                        type="array",
                        elem_classes=["jf-table-region"],
                    )
                with gr.Accordion("가능 시간", open=False) as availability_section:
                    availability_table = gr.Dataframe(
                        headers=AVAILABILITY_HEADERS,
                        datatype=["str", "str", "str", "str", "str", "str", "bool"],
                        value=[],
                        label="가능 시간",
                        interactive=True,
                        type="array",
                        elem_classes=["jf-table-region"],
                    )
                with gr.Accordion("고정 일정", open=False) as fixed_event_section:
                    fixed_event_table = gr.Dataframe(
                        headers=FIXED_EVENT_HEADERS,
                        datatype=["str", "str", "str", "str", "bool"],
                        value=[],
                        label="고정 일정",
                        interactive=True,
                        type="array",
                        elem_classes=["jf-table-region"],
                    )
                with gr.Row(elem_classes=["jf-panel-footer"]):
                    confirmed_box = gr.Checkbox(
                        label="검토 완료",
                        value=False,
                        elem_classes=["jf-checkbox"],
                    )
                    schedule_button = gr.Button(
                        "캘린더에 반영",
                        interactive=False,
                        variant="primary",
                        elem_classes=["jf-button"],
                    )

            with gr.Column(visible=False, elem_classes=["jf-step"]) as calendar_step:
                gr.Markdown("### 캘린더", elem_id="jf-step-calendar")
                gr.Markdown(
                    "일정이 캘린더에 반영됐어요. 상세 일정과 진단은 달력 아래에서 확인해요."
                )
                calendar_view_button = gr.Button(
                    "캘린더에서 보기",
                    variant="primary",
                    elem_id="jf-calendar-view",
                    elem_classes=["jf-button"],
                )

        workflow_outputs = [compose_panel, request_step, review_step, calendar_step]
        review_section_outputs = [
            task_section,
            routine_section,
            availability_section,
            fixed_event_section,
        ]
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
            summary_state,
            stats_state,
            schedule_diagnostics,
            calendar_html,
            schedule_details,
            unplaced_details,
            request_error,
            *workflow_outputs,
            *review_section_outputs,
        ]
        schedule_outputs = [
            result_state,
            timeline_table,
            unscheduled_table,
            summary_state,
            stats_state,
            schedule_diagnostics,
            calendar_html,
            schedule_details,
            unplaced_details,
            request_error,
            *workflow_outputs,
            schedule_button,
        ]
        confirmation_event = confirmed_box.change(
            _confirmation_button,
            inputs=[confirmed_box, report_state],
            outputs=schedule_button,
        )
        schedule_event = schedule_button.click(
            _begin_schedule,
            inputs=report_state,
            outputs=[schedule_button, calendar_html],
            queue=False,
            trigger_mode="once",
        )
        schedule_response = schedule_event.then(
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
            inputs=planning_input,
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
            lambda: gr.Button(interactive=True),
            outputs=parse_button,
            queue=False,
        )
        review_and_parse_outputs = [*review_outputs, parse_button]
        demo_button.click(
            _demo_and_enable_parse,
            outputs=[
                *review_and_parse_outputs,
                reference_input,
                planning_input,
                selected_month_display,
            ],
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

        create_button.click(
            lambda: (
                gr.Sidebar(open=True),
                gr.Column(visible=True),
                gr.Column(visible=False),
                gr.Column(visible=False),
            ),
            outputs=workflow_outputs,
            queue=False,
        )
        close_button.click(
            lambda: gr.Sidebar(open=False),
            outputs=compose_panel,
            queue=False,
        )
        calendar_view_button.click(
            lambda: gr.Sidebar(open=False),
            outputs=compose_panel,
            queue=False,
        )
        topbar_month_outputs = [
            *review_and_parse_outputs,
            planning_input,
            selected_month_display,
            previous_month,
            next_month,
        ]
        previous_month.click(
            lambda reference, month: _navigate_month(reference, month, -1),
            inputs=[reference_input, planning_input],
            outputs=topbar_month_outputs,
            queue=False,
        )
        next_month.click(
            lambda reference, month: _navigate_month(reference, month, 1),
            inputs=[reference_input, planning_input],
            outputs=topbar_month_outputs,
            queue=False,
        )
        current_month.click(
            _navigate_current_month,
            inputs=[reference_input, planning_input],
            outputs=topbar_month_outputs,
            queue=False,
        )
        planning_input.input(
            lambda month: month,
            inputs=planning_input,
            outputs=selected_month_display,
            queue=False,
        )
        planning_input.input(
            _month_button_updates,
            inputs=planning_input,
            outputs=[previous_month, next_month],
            queue=False,
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
