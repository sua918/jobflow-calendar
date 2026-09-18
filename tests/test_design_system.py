from __future__ import annotations

import re
from pathlib import Path

import yaml

from jobflow.ui import APP_CSS

ROOT = Path(__file__).resolve().parents[1]
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


def test_calendar_first_contract_requires_one_sidebar_path_without_layout_fallback() -> None:
    design = (ROOT / "DESIGN.md").read_text(encoding="utf-8")
    ux_contract = (ROOT / "docs" / "calendar-first-ui.md").read_text(
        encoding="utf-8"
    )

    for contract in (design, ux_contract):
        assert "sole approved composition primitive" in contract
        assert "60dvh" not in contract
        assert "only approved fallback" not in contract

    assert "There is no approved inline-panel or custom-modal fallback" in ux_contract


def test_implemented_css_uses_calendar_first_palette_and_font_stack() -> None:
    expected = {
        "--jf-ink": "#18181B",
        "--jf-muted": "#52525B",
        "--jf-border": "#D4D4D8",
        "--jf-border-strong": "#71717A",
        "--jf-canvas": "#F7F8FA",
        "--jf-primary": "#2563EB",
        "--jf-focus": "#1D4ED8",
    }
    for token, value in expected.items():
        assert re.search(rf"{re.escape(token)}:\s*{value}", APP_CSS, re.IGNORECASE)
    assert re.search(
        r"\.jf-app[^{}]*\{[^{}]*font-family:\s*Pretendard,\s*\"Pretendard Variable\"",
        APP_CSS,
        re.DOTALL,
    )


def test_css_scopes_square_choice_controls_without_global_input_sizing() -> None:
    selector = (
        '.jf-app :where(.jf-checkbox, .jf-radio) '
        'input:is([type="checkbox"], [type="radio"])'
    )
    assert selector in APP_CSS
    square_rule = re.search(rf"{re.escape(selector)}\s*\{{([^}}]+)\}}", APP_CSS)
    assert square_rule is not None
    declarations = square_rule.group(1)
    for declaration in (
        "width: 18px",
        "height: 18px",
        "min-width: 18px",
        "max-width: 18px",
        "min-height: 18px",
        "max-height: 18px",
        "aspect-ratio: 1 / 1",
    ):
        assert declaration in declarations
    assert re.search(r"(^|[},])\s*input\s*\{", APP_CSS) is None


def test_css_encodes_calendar_first_desktop_and_mobile_geometry() -> None:
    assert re.search(r"#jf-topbar\s*\{[^}]*height:\s*64px", APP_CSS, re.DOTALL)
    assert re.search(
        r"#jf-calendar-workspace\s*\{[^}]*min-height:\s*824px", APP_CSS, re.DOTALL
    )
    assert re.search(
        r"#jf-compose-panel\s*\{[^}]*position:\s*fixed[^}]*width:\s*440px",
        APP_CSS,
        re.DOTALL,
    )
    mobile = APP_CSS[APP_CSS.index("@media (max-width: 700px)") :]
    assert re.search(r"#jf-topbar\s*\{[^}]*height:\s*104px", mobile, re.DOTALL)
    assert re.search(
        r"#jf-compose-panel\s*\{[^}]*inset:\s*0[^}]*width:\s*100dvw",
        mobile,
        re.DOTALL,
    )
    mobile_calendar = re.search(r"\.calendar-shell\s*\{([^}]+)\}", mobile)
    assert mobile_calendar is not None
    assert "height: calc(100dvh - 116px)" in mobile_calendar.group(1)
    assert "height: auto" not in mobile_calendar.group(1)


def test_css_keeps_topbar_and_sticky_footer_controls_on_one_row() -> None:
    button_rule = re.search(
        r"\.jf-app \.jf-button button, \.jf-app button\.jf-button\s*\{([^}]+)\}",
        APP_CSS,
    )
    assert button_rule is not None
    assert "white-space: nowrap" in button_rule.group(1)
    assert re.search(
        r"\.jf-month-controls\s*\{[^}]*flex-wrap:\s*nowrap",
        APP_CSS,
        re.DOTALL,
    )
    footer = re.search(r"\.jf-panel-footer\s*\{([^}]+)\}", APP_CSS)
    assert footer is not None
    declarations = footer.group(1)
    assert "height: 64px" in declarations
    assert "flex-wrap: nowrap" in declarations
    assert re.search(
        r"#jf-compose-close\s*\{[^}]*width:\s*40px[^}]*min-width:\s*40px",
        APP_CSS,
        re.DOTALL,
    )


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
