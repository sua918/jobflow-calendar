from __future__ import annotations

import re
from pathlib import Path

import yaml

from jobflow.ui import APP_CSS

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTED_BASELINE_TOKENS = {
    "--jf-ink": "#0F172A",
    "--jf-primary": "#4F46E5",
    "--jf-deadline": "#0072B2",
    "--jf-routine": "#009E73",
    "--jf-warning": "#D55E00",
}
CALENDAR_FIRST_TOKENS = {
    "primary": "#2563EB",
    "canvas": "#F7F8FA",
    "surface": "#FFFFFF",
    "text": "#18181B",
    "textMuted": "#52525B",
    "border": "#D4D4D8",
    "borderStrong": "#71717A",
    "focus": "#1D4ED8",
    "deadlineSoft": "#EFF6FF",
    "routineSoft": "#ECFDF5",
    "fixedSoft": "#FFFBEB",
}


def _rgb(hex_color: str) -> tuple[float, float, float]:
    return tuple(int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5))  # type: ignore[return-value]


def _luminance(hex_color: str) -> float:
    channels = tuple(
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in _rgb(hex_color)
    )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast(first: str, second: str) -> float:
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_calendar_first_design_spec_defines_required_palette_and_font() -> None:
    spec = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(spec.split("---", maxsplit=2)[1])

    for token, value in CALENDAR_FIRST_TOKENS.items():
        assert frontmatter["colors"][token] == value
    assert frontmatter["typography"]["body"]["fontFamily"].startswith("Pretendard")
    assert frontmatter["components"]["topbar-desktop"]["height"] == "64px"
    assert frontmatter["components"]["topbar-mobile"]["height"] == "104px"


def test_calendar_first_contract_defines_responsive_modality_and_step_three() -> None:
    design = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
    ux_contract = (ROOT / "docs" / "calendar-first-ui.md").read_text(
        encoding="utf-8"
    )

    for contract in (design, ux_contract):
        assert 'role="complementary"' in contract
        assert 'role="dialog"' in contract
        assert 'aria-modal="true"' in contract
        assert 'aria-labelledby="jf-compose-title"' in contract

    assert "does not close the panel" in design
    assert "advances to step 3" in design
    assert "keep the drawer open, advance to step 3" in ux_contract
    assert "focus `#calendar-heading` only when" in ux_contract
    assert "test at 700/701 px without closing" in ux_contract


def test_current_css_palette_stays_guarded_until_redesign_implementation() -> None:
    for token, value in IMPLEMENTED_BASELINE_TOKENS.items():
        assert re.search(rf"{re.escape(token)}:\s*{value}", APP_CSS, re.IGNORECASE)


def test_required_text_and_surface_pairs_meet_wcag_aa() -> None:
    pairs = {
        "body": ("#18181B", "#FFFFFF"),
        "muted": ("#52525B", "#FFFFFF"),
        "primary-button": ("#FFFFFF", "#2563EB"),
        "primary-button-hover": ("#FFFFFF", "#1D4ED8"),
        "deadline-chip": ("#18181B", "#EFF6FF"),
        "routine-chip": ("#18181B", "#ECFDF5"),
        "fixed-chip": ("#18181B", "#FFFBEB"),
        "warning": ("#92400E", "#FFFBEB"),
        "error": ("#B42318", "#FEF3F2"),
        "today": ("#1E3A8A", "#DBEAFE"),
        "outside-month": ("#71717A", "#FAFAFA"),
        "disabled": ("#52525B", "#F4F4F5"),
    }

    failures = {
        name: _contrast(*colors)
        for name, colors in pairs.items()
        if _contrast(*colors) < 4.5
    }

    assert failures == {}


def test_required_focus_and_component_boundaries_meet_three_to_one() -> None:
    component_boundary_pairs = {
        "control-on-surface": ("#71717A", "#FFFFFF"),
        "control-on-subtle": ("#71717A", "#FAFAFA"),
        "control-on-canvas": ("#71717A", "#F7F8FA"),
    }
    focus_surfaces = {
        "surface": "#FFFFFF",
        "surface-subtle": "#FAFAFA",
        "canvas": "#F7F8FA",
        "interaction-soft": "#EFF6FF",
        "routine-soft": "#ECFDF5",
        "fixed-soft": "#FFFBEB",
        "danger-soft": "#FEF3F2",
        "today-soft": "#DBEAFE",
        "disabled": "#F4F4F5",
    }
    pairs = component_boundary_pairs | {
        f"focus-on-{name}": ("#1D4ED8", surface)
        for name, surface in focus_surfaces.items()
    }

    failures = {
        name: _contrast(*colors)
        for name, colors in pairs.items()
        if _contrast(*colors) < 3.0
    }

    assert failures == {}


def test_css_covers_focus_touch_overflow_and_mobile_states() -> None:
    required_fragments = (
        ":focus-visible",
        "min-height: 44px",
        ".calendar-day:hover",
        ".calendar-day.today",
        ".calendar-day.outside-month",
        ".calendar-empty",
        ".calendar-loading",
        ".calendar-overflow",
        "text-overflow: ellipsis",
        "@media (max-width: 700px)",
    )

    for fragment in required_fragments:
        assert fragment in APP_CSS
