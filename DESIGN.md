# JobFlow Design System

This file is the single source of truth for the JobFlow Gradio interface. The direction is calm, professional productivity software: light surfaces, restrained elevation, direct language, and no decorative AI gradients.

## Principles

1. Put the selected month and deterministic result first.
2. Keep review, detail, and failure information visible rather than optimistic.
3. Never communicate category, warning, selection, or status by color alone.
4. Preserve readable text and 44 px targets at narrow widths.
5. Escape all user-authored strings before they enter custom HTML.

## Color tokens

```css
--jf-ink: #0F172A;
--jf-muted: #475569;
--jf-border: #CBD5E1;
--jf-surface: #FFFFFF;
--jf-surface-soft: #F8FAFC;
--jf-primary: #4F46E5;
--jf-focus: #4F46E5;
--jf-deadline: #0072B2;
--jf-deadline-bg: #E6F4FB;
--jf-routine: #009E73;
--jf-routine-bg: #E7F6F1;
--jf-fixed: #9A6700;
--jf-fixed-bg: #FFF4D6;
--jf-warning: #D55E00;
--jf-warning-bg: #FDECE7;
```

Automated WCAG 2.1 AA checks cover ink on white, white on primary, and ink on every category/warning surface. Borders are reinforcement, not text. Warning/unplaced content uses the vermillion border plus an explicit warning label and deterministic reason text.

## Typography

Use Gradio's system sans stack. Body text is at least 1 rem. Headings use weight 700 and slightly tightened tracking. Supporting labels may use 0.72–0.8 rem only when the event title and time remain separately readable. Never place essential information only in a tooltip.

## Spacing and shape

Use a 4 px base rhythm. Common gaps are 8, 12, 16, and 24 px. Controls have at least 44 px height. Cards use 10–16 px radii and a 1 px neutral border. Shadows are reserved for the hero or major grouping and remain subtle.

## Interaction states

- Default: white surface, ink text, neutral border.
- Hover: neutral `#F1F5F9` surface; content and border remain visible.
- Focus: 3 px primary-indigo outline with 2 px offset on controls, tabs, overflow summaries, and calendar events.
- Selected: Gradio tab/field selection uses primary-indigo emphasis plus text or structure; not color alone.
- Today: inset primary ring and filled circular date marker, while the full date remains in accessible text.
- Outside month: muted neutral surface and date; no events.
- Disabled: native disabled semantics and Gradio state; buttons cannot be the sole indication that validation is blocked.
- Loading: live status text on a restrained neutral/indigo surface.
- Empty: explicit status text and outlined placeholder.
- Warning/error: deterministic label/code and message on a pale warning surface; color is supplemental.

## Calendar components

The desktop month grid is Monday-first with seven equal columns and exactly 35 or 42 date cells. Adjacent-month cells remain present, muted, and event-free. Each event chip includes:

- a visible icon and Korean category label (`◆ 마감 작업`, `↻ 반복 일정`, or `■ 고정 일정`),
- escaped title,
- local `HH:MM–HH:MM`,
- category border and pale surface,
- stable source/view IDs as data attributes for traceability,
- a Korean accessible name containing category, title, and complete interval.

Show at most three compact chips before a native keyboard-operable `details/summary` “+N개 더 보기” control. Titles ellipsize on desktop while focus/accessibility text retains the complete value. Split fixed events include visible and named continuation arrows.

At widths up to 700 px, switch to a vertical date agenda: hide event-free adjacent-month cells, keep selected-month date groups in chronological order, wrap long titles, and avoid horizontal scrolling. This is the approved responsive treatment rather than shrinking seven columns beyond legibility.

## Result hierarchy

The first/default tab is `월간 달력`. `상세 일정` retains chronological block data. `미배치 및 진단` retains exact reasons, details, remaining minutes, and diagnostics. Summary and minute totals stay above all tabs.

## Accessibility verification

Automated tests verify token presence, WCAG AA contrast, semantic grid labels, Monday-first headings, escaped event content, visible non-color category labels, focus CSS, 44 px targets, empty/loading states, overflow controls, ellipsis/wrapping, and the mobile breakpoint. Release verification additionally captures desktop and mobile screenshots and checks keyboard tab order, focus visibility, grayscale recognizability, and no horizontal clipping.
