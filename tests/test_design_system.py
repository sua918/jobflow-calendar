from __future__ import annotations

import re
from pathlib import Path

from jobflow.ui import APP_CSS

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TOKENS = {
    "--jf-ink": "#0F172A",
    "--jf-primary": "#4F46E5",
    "--jf-deadline": "#0072B2",
    "--jf-routine": "#009E73",
    "--jf-warning": "#D55E00",
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


def test_design_spec_and_css_use_required_palette() -> None:
    spec = (ROOT / "DESIGN.md").read_text(encoding="utf-8")

    for token, value in REQUIRED_TOKENS.items():
        assert value in spec
        assert re.search(rf"{re.escape(token)}:\s*{value}", APP_CSS, re.IGNORECASE)


def test_required_text_and_surface_pairs_meet_wcag_aa() -> None:
    pairs = {
        "body": ("#0F172A", "#FFFFFF"),
        "primary-button": ("#FFFFFF", "#4F46E5"),
        "deadline-chip": ("#0F172A", "#E6F4FB"),
        "routine-chip": ("#0F172A", "#E7F6F1"),
        "fixed-chip": ("#0F172A", "#FFF4D6"),
        "warning": ("#0F172A", "#FDECE7"),
    }

    failures = {
        name: _contrast(*colors)
        for name, colors in pairs.items()
        if _contrast(*colors) < 4.5
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
