from __future__ import annotations

from dataclasses import dataclass, replace
from math import floor
from typing import Mapping

from .bmfont import BitmapFont, FontFamily, Glyph


Color = tuple[int, int, int]

GAME_COLORS: dict[str, Color] = {
    "!": (241, 242, 236),
    "T": (255, 255, 255),
    "Y": (238, 201, 35),
    "H": (238, 201, 35),
    "G": (86, 172, 91),
    "R": (222, 86, 70),
    "O": (238, 123, 35),
    "g": (175, 175, 175),
}
DEFAULT_COLOR = GAME_COLORS["!"]


@dataclass(frozen=True, slots=True)
class StyledCharacter:
    character: str
    color: Color


@dataclass(frozen=True, slots=True)
class Newline:
    pass


ParsedCharacter = StyledCharacter | Newline


def parse_game_text(text: str) -> list[ParsedCharacter]:
    """Нормализует переносы и убирает поддерживаемые цветовые коды из потока."""
    normalized = text.replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
    result: list[ParsedCharacter] = []
    color = DEFAULT_COLOR
    index = 0
    while index < len(normalized):
        character = normalized[index]
        if character == "§" and index + 1 < len(normalized):
            code = normalized[index + 1]
            if code in GAME_COLORS:
                color = GAME_COLORS[code]
                index += 2
                continue
        if character == "\n":
            result.append(Newline())
        elif character == "\t":
            result.extend(StyledCharacter(" ", color) for _ in range(4))
        else:
            result.append(StyledCharacter(character, color))
        index += 1
    return result


@dataclass(frozen=True, slots=True)
class LayoutGlyph:
    character: str
    color: Color
    font: BitmapFont | None
    glyph: Glyph | None
    advance: float


@dataclass(frozen=True, slots=True)
class TextLine:
    glyphs: tuple[LayoutGlyph, ...]
    width: float


@dataclass(frozen=True, slots=True)
class TextLayout:
    lines: tuple[TextLine, ...]
    content_height: float
    line_height: float
    scale: float
    max_width: float
    primary_font: BitmapFont
    missing_glyphs: tuple[str, ...]
    visual_metrics: Mapping[str, tuple[int, int, int, int]]


def _resolve_character(
    styled: StyledCharacter,
    family: FontFamily,
    scale: float,
    missing: set[str],
    snap_advances: bool,
    advance_adjustments: Mapping[str, float],
) -> LayoutGlyph:
    match = family.find(styled.character)
    if match is None:
        if not styled.character.isspace():
            missing.add(styled.character)
        advance = family.primary.line_height * 0.62 * scale
        return LayoutGlyph(
            styled.character,
            styled.color,
            None,
            None,
            float(floor(advance + 0.5)) if snap_advances else advance,
        )
    advance = match.glyph.xadvance * scale
    if snap_advances:
        advance = float(floor(advance + 0.5))
    advance += advance_adjustments.get(styled.character, 0.0)
    return LayoutGlyph(
        styled.character,
        styled.color,
        match.font,
        match.glyph,
        advance,
    )


def _finish_line(
    output: list[TextLine],
    glyphs: list[LayoutGlyph],
    width: float,
) -> tuple[list[LayoutGlyph], float]:
    output.append(TextLine(tuple(glyphs), width))
    return [], 0.0


def _wrap_paragraph(items: list[LayoutGlyph], max_width: float) -> list[TextLine]:
    if not items:
        return [TextLine((), 0.0)]

    lines: list[TextLine] = []
    line: list[LayoutGlyph] = []
    line_width = 0.0
    pending_spaces: list[LayoutGlyph] = []
    index = 0

    while index < len(items):
        if items[index].character.isspace():
            pending_spaces.append(items[index])
            index += 1
            continue

        word: list[LayoutGlyph] = []
        word_width = 0.0
        while index < len(items) and not items[index].character.isspace():
            word.append(items[index])
            word_width += items[index].advance
            index += 1

        # Clausewitz keeps a standalone en dash together with the word that
        # follows it. An em dash remains ordinary closing punctuation.
        word_text = "".join(item.character for item in word)
        if word_text == "–":
            internal_spaces: list[LayoutGlyph] = []
            while index < len(items) and items[index].character.isspace():
                internal_spaces.append(items[index])
                index += 1
            following: list[LayoutGlyph] = []
            while index < len(items) and not items[index].character.isspace():
                following.append(items[index])
                index += 1
            if following:
                word.extend(internal_spaces)
                word.extend(following)
                word_width += sum(item.advance for item in internal_spaces)
                word_width += sum(item.advance for item in following)

        # A separated ellipsis is closing punctuation in the game renderer:
        # no line break is allowed immediately before it. Clausewitz lets the
        # punctuation hang a few pixels past maxWidth when necessary.
        if line and word_text in {"...", "…"}:
            if pending_spaces:
                line.extend(pending_spaces)
                line_width += sum(item.advance for item in pending_spaces)
            pending_spaces = []
            line.extend(word)
            line_width += word_width
            continue

        spaces_width = (
            sum(item.advance for item in pending_spaces) if line else 0.0
        )
        if line and line_width + spaces_width + word_width > max_width:
            line, line_width = _finish_line(lines, line, line_width)
            pending_spaces = []
            spaces_width = 0.0

        if word_width <= max_width:
            if line and pending_spaces:
                line.extend(pending_spaces)
                line_width += spaces_width
            pending_spaces = []
            line.extend(word)
            line_width += word_width
            continue

        # Слово само шире поля: переносим его по символам.
        if line:
            line, line_width = _finish_line(lines, line, line_width)
        pending_spaces = []
        for item in word:
            if line and line_width + item.advance > max_width:
                line, line_width = _finish_line(lines, line, line_width)
            line.append(item)
            line_width += item.advance
            if item.advance > max_width:
                line, line_width = _finish_line(lines, line, line_width)

    if line or not lines:
        lines.append(TextLine(tuple(line), line_width))
    return lines


def layout_text(
    text: str,
    family: FontFamily,
    max_width: float,
    *,
    scale: float = 1.0,
    line_height: float | None = None,
    snap_advances: bool = False,
    advance_adjustments: Mapping[str, float] | None = None,
    advance_pair_adjustments: Mapping[str, float] | None = None,
    visual_metrics: Mapping[str, tuple[int, int, int, int]] | None = None,
) -> TextLayout:
    parsed = parse_game_text(text)
    effective_line_height = (
        float(line_height)
        if line_height is not None
        else family.primary.line_height * scale
    )
    if not parsed:
        return TextLayout(
            (),
            0.0,
            effective_line_height,
            scale,
            max_width,
            family.primary,
            (),
            visual_metrics or {},
        )

    missing: set[str] = set()
    effective_adjustments = advance_adjustments or {}
    effective_pair_adjustments = advance_pair_adjustments or {}
    paragraphs: list[list[LayoutGlyph]] = [[]]
    for item in parsed:
        if isinstance(item, Newline):
            paragraphs.append([])
        else:
            resolved = _resolve_character(
                item,
                family,
                scale,
                missing,
                snap_advances,
                effective_adjustments,
            )
            if paragraphs[-1]:
                previous = paragraphs[-1][-1]
                pair_adjustment = effective_pair_adjustments.get(
                    previous.character + resolved.character,
                    0.0,
                )
                if pair_adjustment:
                    resolved = replace(
                        resolved,
                        advance=resolved.advance + pair_adjustment,
                    )
            paragraphs[-1].append(resolved)

    lines: list[TextLine] = []
    for paragraph in paragraphs:
        lines.extend(_wrap_paragraph(paragraph, max_width))

    return TextLayout(
        lines=tuple(lines),
        content_height=len(lines) * effective_line_height,
        line_height=effective_line_height,
        scale=scale,
        max_width=max_width,
        primary_font=family.primary,
        missing_glyphs=tuple(sorted(missing)),
        visual_metrics=visual_metrics or {},
    )
