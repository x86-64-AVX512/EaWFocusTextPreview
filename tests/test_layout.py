from __future__ import annotations

from eaw_focus_preview.bmfont import FontFamily
from eaw_focus_preview.layout import (
    GAME_COLORS,
    Newline,
    StyledCharacter,
    layout_text,
    parse_game_text,
)


def _plain(layout) -> list[str]:
    return ["".join(item.character for item in line.glyphs) for line in layout.lines]


def test_color_codes_change_style_but_not_visible_text() -> None:
    parsed = parse_game_text("Белый §Yжёлтый§! §Ggreen§!")
    visible = "".join(
        item.character for item in parsed if isinstance(item, StyledCharacter)
    )
    assert visible == "Белый жёлтый green"
    yellow = next(
        item for item in parsed if isinstance(item, StyledCharacter) and item.character == "ж"
    )
    green = next(
        item for item in parsed if isinstance(item, StyledCharacter) and item.character == "g"
    )
    assert yellow.color == GAME_COLORS["Y"]
    assert green.color == GAME_COLORS["G"]


def test_literal_and_real_newlines_are_equivalent() -> None:
    literal = parse_game_text(r"one\ntwo")
    real = parse_game_text("one\ntwo")
    assert literal == real
    assert sum(isinstance(item, Newline) for item in literal) == 1


def test_word_wrap_and_character_wrap(make_font) -> None:
    font = make_font("mono", " abcdef", advance=10)
    family = FontFamily((font,))
    words = layout_text("aa bb", family, 25)
    long_word = layout_text("abcdef", family, 25)
    assert _plain(words) == ["aa", "bb"]
    assert _plain(long_word) == ["ab", "cd", "ef"]


def test_standalone_en_dash_stays_with_following_word(make_font) -> None:
    font = make_font("mono", "ab –—", advance=10)
    family = FontFamily((font,))

    assert _plain(layout_text("aaa – bb", family, 50)) == ["aaa", "– bb"]
    assert _plain(layout_text("aaa — bb", family, 50)) == ["aaa —", "bb"]


def test_separated_ellipsis_hangs_past_wrap_edge(make_font) -> None:
    font = make_font("mono", "a .…", advance=10)
    family = FontFamily((font,))

    three_dots = layout_text("aaa ...", family, 40)
    ellipsis = layout_text("aaa …", family, 40)

    assert _plain(three_dots) == ["aaa ..."]
    assert three_dots.lines[0].width == 70
    assert _plain(ellipsis) == ["aaa …"]
    assert ellipsis.lines[0].width == 50


def test_color_codes_have_zero_width(make_font) -> None:
    font = make_font("mono", "Attack", advance=10)
    family = FontFamily((font,))
    colored = layout_text("§YAttack§!", family, 200)
    plain = layout_text("Attack", family, 200)
    assert colored.lines[0].width == plain.lines[0].width == 60


def test_fractional_advances_can_snap_to_clausewitz_pixels(make_font) -> None:
    font = make_font("pixel", "A", advance=4)
    family = FontFamily((font,))

    fractional = layout_text("A", family, 100, scale=18 / 16)
    snapped = layout_text(
        "A",
        family,
        100,
        scale=18 / 16,
        snap_advances=True,
    )

    assert fractional.lines[0].width == 4.5
    assert snapped.lines[0].width == 5


def test_advance_adjustments_apply_after_pixel_snapping(make_font) -> None:
    font = make_font("pixel", "о", advance=7)
    family = FontFamily((font,))
    adjusted = layout_text(
        "оо",
        family,
        100,
        scale=18 / 16,
        snap_advances=True,
        advance_adjustments={"о": 1},
    )

    assert adjusted.lines[0].width == 18


def test_pair_adjustments_apply_only_to_adjacent_glyphs(make_font) -> None:
    font = make_font("pixel", "о", advance=7)
    family = FontFamily((font,))
    adjacent = layout_text(
        "оо",
        family,
        100,
        scale=18 / 16,
        snap_advances=True,
        advance_pair_adjustments={"оо": -0.5},
    )
    separated = layout_text(
        "о\nо",
        family,
        100,
        scale=18 / 16,
        snap_advances=True,
        advance_pair_adjustments={"оо": -0.5},
    )

    assert adjacent.lines[0].width == 15.5
    assert [line.width for line in separated.lines] == [8, 8]


def test_ru_to_english_fallback_on_mixed_text(make_font) -> None:
    russian = make_font("body_ru", "Армия", advance=9)
    english = make_font("body_en", "ArmyAttack: +5%", advance=8)
    family = FontFamily((russian, english))
    layout = layout_text("Армия: +5% Attack", family, 500)
    sources = {
        item.character: item.font.name
        for item in layout.lines[0].glyphs
        if item.font is not None and not item.character.isspace()
    }
    assert sources["А"] == "body_ru"
    assert sources["A"] == "body_en"
    assert sources[":"] == "body_en"
    assert layout.missing_glyphs == ()


def test_priority_order_is_respected(make_font) -> None:
    russian = make_font("ru", "AА")
    english = make_font("en", "AА")
    assert FontFamily((russian, english)).find("A").font.name == "ru"
    assert FontFamily((english, russian)).find("A").font.name == "en"


def test_long_description_reaches_reward_panel(make_font) -> None:
    font = make_font(
        "body",
        "Очень длинное описание ",
        advance=8,
        line_height=16,
    )
    family = FontFamily((font,))
    text = ("Очень длинное описание " * 35).strip()
    layout = layout_text(
        text,
        family,
        485,
        scale=18 / 16,
        line_height=18,
    )
    assert layout.content_height > 70
    assert layout.content_height > 363 - 250


def test_missing_glyph_is_reported(make_font) -> None:
    font = make_font("limited", "abc ")
    layout = layout_text("abc 🦄", FontFamily((font,)), 200)
    assert layout.missing_glyphs == ("🦄",)
