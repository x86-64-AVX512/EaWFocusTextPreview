from __future__ import annotations

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter, QPen

from .bmfont import FontFamily
from .layout import TextLayout


class BitmapTextRenderer:
    """Рисует BMFont-глифы без участия системных шрифтов."""

    def draw_layout(
        self,
        painter: QPainter,
        layout: TextLayout,
        x: float,
        y: float,
        width: float,
        *,
        align: str = "left",
        visual_family: FontFamily | None = None,
    ) -> None:
        painter.save()
        scale = layout.scale
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        for line_index, line in enumerate(layout.lines):
            cursor_x = (
                x + (width - line.width) / 2.0
                if align == "center"
                else x
            )
            line_top = y + line_index * layout.line_height
            for item in line.glyphs:
                if item.font is not None and item.glyph is not None:
                    glyph = item.glyph
                    visual = layout.visual_metrics.get(item.character)
                    render_font = item.font
                    render_glyph = glyph
                    render_primary = layout.primary_font
                    render_scale = scale
                    if visual_family is not None:
                        visual_match = visual_family.find(item.character)
                        if visual_match is not None:
                            render_font = visual_match.font
                            render_glyph = visual_match.glyph
                            render_primary = visual_family.primary
                            render_scale = 1.0
                            visual = None
                    primary_top = max(
                        0.0,
                        (
                            layout.line_height
                            - render_primary.line_height * render_scale
                        ) / 2.0,
                    )
                    image = render_font.glyph_image(
                        render_glyph,
                        item.color,
                        scale=render_scale,
                        target_size=(visual[0], visual[1]) if visual else None,
                    )
                    if (
                        not image.isNull()
                        and render_glyph.width
                        and render_glyph.height
                    ):
                        draw_x = cursor_x + (
                            visual[2]
                            if visual
                            else render_glyph.xoffset * render_scale
                        )
                        # Некоторые EaW .fnt (в особенности cryllic) содержат
                        # общий положительный сдвиг всех yoffset. Строим
                        # baseline через base, затем компенсируем найденный
                        # верхний сдвиг конкретного атласа.
                        font_baseline = (
                            line_top
                            + primary_top
                            + (
                                render_font.base - render_font.top_offset
                            ) * render_scale
                        )
                        draw_y = (
                            line_top + visual[3]
                            if visual
                            else (
                                font_baseline
                                - render_font.base * render_scale
                                + render_glyph.yoffset * render_scale
                            )
                        )
                        target = QRectF(
                            round(draw_x),
                            round(draw_y),
                            image.width(),
                            image.height(),
                        )
                        painter.drawImage(target, image)
                elif not item.character.isspace():
                    placeholder = QRectF(
                        round(cursor_x),
                        round(line_top + 2),
                        max(6, round(item.advance - 1)),
                        max(8, round(layout.line_height - 4)),
                    )
                    painter.setPen(QPen(QColor(255, 54, 54), 1.4))
                    painter.setBrush(QColor(90, 0, 0, 150))
                    painter.drawRect(placeholder)
                    painter.drawLine(placeholder.topLeft(), placeholder.bottomRight())
                    painter.drawLine(placeholder.topRight(), placeholder.bottomLeft())
                cursor_x += item.advance
        painter.restore()
