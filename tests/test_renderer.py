from __future__ import annotations

from eaw_focus_preview.renderer import ellipsis_visual_offsets


def test_three_periods_are_spread_symmetrically() -> None:
    assert ellipsis_visual_offsets("текст...") == (0, 0, 0, 0, 0, -1, 0, 1)


def test_period_adjustment_does_not_touch_layout_punctuation() -> None:
    text = "а.б..в....г"
    assert ellipsis_visual_offsets(text) == (0,) * len(text)
