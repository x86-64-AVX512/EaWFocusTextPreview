from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QWheelEvent,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from .bmfont import FontRepository
from .dynamic_localisation import (
    DYNAMIC_LOCALISATION_WARNING,
    DynamicResolution,
    ModLocalisation,
)
from .layout import TextLayout, layout_text
from .renderer import BitmapTextRenderer


CANVAS_SIZE = 550
TITLE_RECT = QRectF(30, 12, 450, 30)
DESCRIPTION_X = 34
DESCRIPTION_Y = 250
DESCRIPTION_WIDTH = 485
DESCRIPTION_BORDER_X = 5
# instantTextboxType uses a one-pixel internal edge in addition to borderSize.
DESCRIPTION_LAYOUT_WIDTH = DESCRIPTION_WIDTH - (2 * DESCRIPTION_BORDER_X) - 1
# Keep the public aliases used by tests and integrations.
DESCRIPTION_LATIN_LAYOUT_WIDTH = DESCRIPTION_LAYOUT_WIDTH
DESCRIPTION_ENGLISH_LAYOUT_WIDTH = DESCRIPTION_LAYOUT_WIDTH

# The bundled EaW atlas is 16 px, while nationalfocusview.gui requests the
# base-game hoi_18mbs bitmap font. These integer corrections are the exact
# xadvance differences between the bundled 16 px fonts scaled to 18/16 and
# HoI4 1.19.2's hoi_18mbs / hoi_18mbs_cryllic metrics. They replace the old
# corpus-fitted character and pair tables.
_DESCRIPTION_ADVANCE_GROUPS = (
    ("yуљҵ", -2.0),
    (
        "AIJTVWY^ijlv{}ÀÁÂÃÄÅÌÍÎÏÝìíîïĀĂĄĨĩĪīĬĭĮįİıĺļœŢŤŦŴŶŸ"
        "ІЇАТдтцыіїџѴґҒҖҬҭҮҰӀӊӏӐӒӹ",
        -1.0,
    ),
    (
        "!#%',-=KMZ`o|¡¦§¨\xad°²³´òóôõöøďĦĲĵĶōŏőŹŻŽ"
        "ЄЋЌЍДЗИЙКМЧЪЫЭЯжмофюјѳҊҏҘҤҩүұҸҹӂӅӋӎӝӞӠӢӤ"
        "ӧөӫӬӴӸ‘’‚",
        1.0,
    ),
    (".:;·", 2.0),
)
DESCRIPTION_GAME_ADVANCE_ADJUSTMENTS = {
    character: adjustment
    for characters, adjustment in _DESCRIPTION_ADVANCE_GROUPS
    for character in characters
}

# Target bitmap rectangles from HoI4's 18 px body font: width, height,
# xoffset and yoffset relative to the top of an 18 px line. The permitted
# EaW atlas still supplies the pixels; exact geometry keeps individual
# Russian glyphs (notably й and б) on the baseline and out of neighbours.
_DESCRIPTION_CYRILLIC_VISUAL_GROUPS = (
    ("Ё", (12, 17, -2, 1)),
    ("Й", (15, 17, -2, 1)),
    ("б", (12, 15, -2, 3)),
    ("ф", (16, 18, -2, 3)),
    ("ГЕё", (12, 14, -2, 4)),
    ("БВЗРСТУЬй", (13, 14, -2, 4)),
    ("КНПЧЭЯ", (14, 14, -2, 4)),
    ("Х", (14, 14, -3, 4)),
    ("А", (15, 14, -3, 4)),
    ("ИЛОЪ", (15, 14, -2, 4)),
    ("Ф", (16, 14, -2, 4)),
    ("МЫ", (17, 14, -2, 4)),
    ("ЖШ", (18, 14, -2, 4)),
    ("Ю", (19, 14, -2, 4)),
    ("Ц", (15, 17, -2, 4)),
    ("Д", (16, 17, -2, 4)),
    ("Щ", (19, 17, -2, 4)),
    ("гзстэ", (11, 11, -2, 7)),
    ("авекнпхчья", (12, 11, -2, 7)),
    ("иоъ", (13, 11, -2, 7)),
    ("л", (14, 11, -3, 7)),
    ("мы", (15, 11, -2, 7)),
    ("ш", (16, 11, -2, 7)),
    ("жю", (17, 11, -2, 7)),
    ("ц", (13, 13, -2, 7)),
    ("д", (15, 13, -3, 7)),
    ("щ", (17, 13, -2, 7)),
    ("р", (12, 14, -2, 7)),
    ("у", (13, 14, -3, 7)),
)
DESCRIPTION_CYRILLIC_VISUAL_METRICS = {
    character: metrics
    for characters, metrics in _DESCRIPTION_CYRILLIC_VISUAL_GROUPS
    for character in characters
}

# Compatibility aliases for external imports. Clausewitz uses no contextual
# kerning table for this bitmap font.
DESCRIPTION_CYRILLIC_ADVANCE_ADJUSTMENTS = (
    DESCRIPTION_GAME_ADVANCE_ADJUSTMENTS
)
DESCRIPTION_CYRILLIC_PAIR_ADVANCE_ADJUSTMENTS: dict[str, float] = {}
DESCRIPTION_ENGLISH_PAIR_ADVANCE_ADJUSTMENTS: dict[str, float] = {}
DESCRIPTION_FORMAL_HEIGHT = 70
REWARD_PANEL_Y = 363
EFFECT_X = 50
EFFECT_Y = 397
EFFECT_WIDTH = 455
EFFECT_HEIGHT = 138


@dataclass(frozen=True, slots=True)
class PreviewDiagnostics:
    title_lines: int
    title_height: int
    description_lines: int
    description_height: int
    description_formal_overflow: int
    description_panel_overlap: int
    effect_lines: int
    effect_height: int
    effect_overflow: int
    missing_glyphs: tuple[str, ...]

    @property
    def description_level(self) -> str:
        if self.description_panel_overlap > 0:
            return "red"
        if self.description_formal_overflow > 0:
            return "yellow"
        return "green"

    @property
    def effect_level(self) -> str:
        return "red" if self.effect_overflow > 0 else "green"

    @property
    def overall_level(self) -> str:
        if self.description_level == "red" or self.effect_level == "red":
            return "red"
        if self.description_level == "yellow":
            return "yellow"
        return "green"


class FocusCanvas(QWidget):
    def __init__(
        self,
        repository: FontRepository,
        parent: QWidget | None = None,
        *,
        mod_localisation: ModLocalisation | None = None,
        dynamic_localisation_enabled: bool = False,
    ):
        super().__init__(parent)
        self.repository = repository
        self.mod_localisation = mod_localisation
        self.dynamic_localisation_enabled = dynamic_localisation_enabled
        self.renderer = BitmapTextRenderer()
        self.priority = "ru"
        self.language = "russian"
        self.title = ""
        self.description = ""
        self.effect = ""
        self.resolved_title = ""
        self.resolved_description = ""
        self.resolved_effect = ""
        self.effect_scroll = 0.0
        self._target_rect = QRectF()
        self._title_layout: TextLayout
        self._description_layout: TextLayout
        self._effect_layout: TextLayout
        self._dynamic_resolutions: dict[str, DynamicResolution] = {}

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(330, 330)
        self.setMouseTracking(True)
        self._relayout()

    def sizeHint(self) -> QSize:
        return QSize(CANVAS_SIZE, CANVAS_SIZE)

    def set_content(
        self,
        *,
        title: str,
        description: str,
        effect: str,
        priority: str,
        language: str | None = None,
        dynamic_localisation_enabled: bool | None = None,
    ) -> None:
        effect_changed = effect != self.effect
        self.title = title
        self.description = description
        self.effect = effect
        self.priority = priority
        if language is not None:
            self.language = language
        if dynamic_localisation_enabled is not None:
            self.dynamic_localisation_enabled = dynamic_localisation_enabled
        self._relayout()
        if effect_changed:
            self.effect_scroll = min(self.effect_scroll, self.max_effect_scroll)
        self.update()

    def set_mod_localisation(
        self,
        mod_localisation: ModLocalisation | None,
    ) -> None:
        self.mod_localisation = mod_localisation
        if (
            mod_localisation is not None
            and not mod_localisation.has_language(self.language)
        ):
            self.language = mod_localisation.available_languages[0]
        self._relayout()
        self.update()

    def set_dynamic_localisation_enabled(self, enabled: bool) -> None:
        if enabled == self.dynamic_localisation_enabled:
            return
        self.dynamic_localisation_enabled = enabled
        self._relayout()
        self.update()

    @property
    def dynamic_localisation_report(self) -> dict[str, object]:
        replacements = sum(
            len(resolution.replacements)
            for resolution in self._dynamic_resolutions.values()
        )
        unresolved = tuple(
            dict.fromkeys(
                token
                for resolution in self._dynamic_resolutions.values()
                for token in resolution.unresolved_tokens
            )
        )
        return {
            "available": self.mod_localisation is not None,
            "enabled": (
                self.dynamic_localisation_enabled
                and self.mod_localisation is not None
            ),
            "mod_path": (
                str(self.mod_localisation.root)
                if self.mod_localisation is not None
                else None
            ),
            "language": self.language,
            "warning": DYNAMIC_LOCALISATION_WARNING,
            "replacement_count": replacements,
            "unresolved_tokens": list(unresolved),
            "fields": {
                field: resolution.as_dict()
                for field, resolution in self._dynamic_resolutions.items()
            },
        }

    @property
    def max_effect_scroll(self) -> float:
        return max(0.0, self._effect_layout.content_height - EFFECT_HEIGHT)

    @property
    def diagnostics(self) -> PreviewDiagnostics:
        missing = set(self._title_layout.missing_glyphs)
        missing.update(self._description_layout.missing_glyphs)
        missing.update(self._effect_layout.missing_glyphs)
        description_height = ceil(self._description_layout.content_height)
        effect_height = ceil(self._effect_layout.content_height)
        panel_distance = REWARD_PANEL_Y - DESCRIPTION_Y
        return PreviewDiagnostics(
            title_lines=len(self._title_layout.lines),
            title_height=ceil(self._title_layout.content_height),
            description_lines=len(self._description_layout.lines),
            description_height=description_height,
            description_formal_overflow=max(
                0,
                description_height - DESCRIPTION_FORMAL_HEIGHT,
            ),
            description_panel_overlap=max(
                0,
                description_height - panel_distance,
            ),
            effect_lines=len(self._effect_layout.lines),
            effect_height=effect_height,
            effect_overflow=max(0, effect_height - EFFECT_HEIGHT),
            missing_glyphs=tuple(sorted(missing)),
        )

    def _relayout(self) -> None:
        title_family = self.repository.title_family(self.priority)
        body_family = self.repository.body_family(self.priority)
        title_options = {
            "line_height": 24,
        }
        description_layout_width = DESCRIPTION_LAYOUT_WIDTH
        description_options = {
            "scale": 18 / 16,
            "line_height": 18,
            "snap_advances": True,
            "advance_adjustments": DESCRIPTION_GAME_ADVANCE_ADJUSTMENTS,
            "visual_metrics": DESCRIPTION_CYRILLIC_VISUAL_METRICS,
        }
        effect_options = {
            "line_height": 16,
        }
        title_resolution, self._title_layout = self._resolve_and_layout(
            self.title,
            title_family,
            TITLE_RECT.width(),
            title_options,
        )
        description_resolution, self._description_layout = (
            self._resolve_and_layout(
                self.description,
                body_family,
                description_layout_width,
                description_options,
            )
        )
        effect_resolution, self._effect_layout = self._resolve_and_layout(
            self.effect,
            body_family,
            EFFECT_WIDTH,
            effect_options,
        )
        self._dynamic_resolutions = {
            "title": title_resolution,
            "description": description_resolution,
            "effect": effect_resolution,
        }
        self.resolved_title = title_resolution.text
        self.resolved_description = description_resolution.text
        self.resolved_effect = effect_resolution.text
        self.effect_scroll = min(self.effect_scroll, self.max_effect_scroll)

    def _resolve_and_layout(
        self,
        text: str,
        family,
        max_width: float,
        options: dict[str, object],
    ) -> tuple[DynamicResolution, TextLayout]:
        def build(candidate: str) -> TextLayout:
            return layout_text(
                candidate,
                family,
                max_width,
                **options,
            )

        if (
            self.mod_localisation is None
            or not self.dynamic_localisation_enabled
        ):
            resolution = DynamicResolution(text, text)
        else:
            def score(candidate: str) -> tuple[float | int, ...]:
                layout = build(candidate)
                widths = [line.width for line in layout.lines]
                return (
                    len(layout.lines),
                    layout.content_height,
                    sum(widths),
                    max(widths, default=0.0),
                    len(candidate),
                )

            resolution = self.mod_localisation.resolve_worst_case(
                text,
                self.language,
                score,
            )
        return resolution, build(resolution.text)

    def paintEvent(self, event) -> None:  # noqa: N802 - имя Qt API
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(20, 23, 22))
        preview = self.render_preview()
        # При наличии места показываем честные 550×550 экранных пикселей.
        # На небольшом экране разрешено только уменьшение, внутренняя система
        # координат при этом всё равно остаётся 550×550.
        scale = min(
            1.0,
            self.width() / CANVAS_SIZE,
            self.height() / CANVAS_SIZE,
        )
        width = CANVAS_SIZE * scale
        height = CANVAS_SIZE * scale
        left = (self.width() - width) / 2
        top = (self.height() - height) / 2
        self._target_rect = QRectF(left, top, width, height)
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform,
            scale < 1.0,
        )
        painter.drawImage(self._target_rect, preview)
        painter.end()

    def render_preview(self) -> QImage:
        image = QImage(
            CANVAS_SIZE,
            CANVAS_SIZE,
            QImage.Format.Format_ARGB32_Premultiplied,
        )
        image.fill(QColor(7, 9, 8))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._draw_frame(painter)
        self._draw_upper_area(painter)
        self._draw_title_and_buttons(painter)
        self._draw_lower_panel(painter)

        # Описание намеренно не получает собственной маски: оно может уйти
        # ниже maxHeight и под последующие элементы, как в Clausewitz GUI.
        self.renderer.draw_layout(
            painter,
            self._description_layout,
            DESCRIPTION_X,
            DESCRIPTION_Y,
            DESCRIPTION_WIDTH,
            align="center",
            visual_family=self.repository.body_visual_family(self.priority),
        )

        self._draw_reward_heading(painter)
        self._draw_effect(painter)
        self._draw_outer_bevel(painter)
        painter.end()
        return image

    def _draw_frame(self, painter: QPainter) -> None:
        background = QLinearGradient(0, 0, 0, CANVAS_SIZE)
        background.setColorAt(0.0, QColor(29, 32, 30))
        background.setColorAt(0.38, QColor(11, 13, 12))
        background.setColorAt(1.0, QColor(6, 8, 7))
        painter.fillRect(QRectF(0, 0, CANVAS_SIZE, CANVAS_SIZE), background)

        top = QLinearGradient(0, 0, 0, 215)
        top.setColorAt(0.0, QColor(37, 41, 38))
        top.setColorAt(0.18, QColor(17, 20, 18))
        top.setColorAt(1.0, QColor(22, 26, 23))
        painter.fillRect(QRectF(2, 2, 546, 210), top)

        # Неброский металлический шум без текстур.
        painter.setPen(QPen(QColor(116, 124, 114, 24), 1))
        for y in range(7, 210, 9):
            painter.drawLine(4, y, 546, y)
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        painter.drawLine(1, 40, 548, 40)
        painter.drawLine(1, 210, 548, 210)
        painter.drawLine(1, 214, 548, 214)

        for point in ((8, 8), (542, 8), (8, 204), (542, 204), (8, 542), (542, 542)):
            painter.setBrush(QColor(9, 11, 10))
            painter.setPen(QPen(QColor(104, 111, 103), 1))
            painter.drawEllipse(QPointF(*point), 3, 3)
            painter.setBrush(QColor(105, 110, 102))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(point[0] - 0.7, point[1] - 0.7), 0.8, 0.8)

    def _draw_upper_area(self, painter: QPainter) -> None:
        close_rect = QRectF(502, 4, 31, 30)
        close_gradient = QLinearGradient(close_rect.topLeft(), close_rect.bottomRight())
        close_gradient.setColorAt(0.0, QColor(80, 84, 76))
        close_gradient.setColorAt(1.0, QColor(15, 17, 15))
        painter.setBrush(close_gradient)
        painter.setPen(QPen(QColor(119, 101, 68), 1.2))
        painter.drawRect(close_rect)
        painter.setPen(QPen(QColor(11, 12, 11), 4.5))
        painter.drawLine(509, 10, 527, 29)
        painter.drawLine(527, 10, 509, 29)
        painter.setPen(QPen(QColor(211, 151, 78), 2.5))
        painter.drawLine(509, 9, 527, 28)
        painter.drawLine(527, 9, 509, 28)

        self._draw_button(
            painter,
            QRectF(200, 53, 171, 27),
            QColor(36, 104, 54),
        )
        self._draw_button(
            painter,
            QRectF(386, 52, 116, 29),
            QColor(70, 72, 69),
        )

        prerequisite = QRectF(200, 87, 304, 111)
        panel = QLinearGradient(0, 87, 0, 198)
        panel.setColorAt(0.0, QColor(7, 9, 8))
        panel.setColorAt(1.0, QColor(3, 4, 4))
        painter.setBrush(panel)
        painter.setPen(QPen(QColor(93, 99, 91), 1.1))
        painter.drawRoundedRect(prerequisite, 4, 4)
        painter.setPen(QPen(QColor(0, 0, 0), 2))
        painter.drawRoundedRect(prerequisite.adjusted(2, 2, -2, -2), 3, 3)
        self._draw_focus_emblem(painter)

    def _draw_button(
        self,
        painter: QPainter,
        rect: QRectF,
        center_color: QColor,
    ) -> None:
        gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
        gradient.setColorAt(0.0, center_color.lighter(145))
        gradient.setColorAt(0.42, center_color)
        gradient.setColorAt(1.0, center_color.darker(175))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(105, 112, 104), 1.2))
        painter.drawRoundedRect(rect, 4, 4)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(5, 7, 6), 2))
        painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 3, 3)
        painter.setPen(QPen(QColor(210, 217, 207, 60), 1))
        painter.drawLine(
            QPointF(rect.left() + 5, rect.top() + 4),
            QPointF(rect.right() - 5, rect.top() + 4),
        )

    def _draw_focus_emblem(self, painter: QPainter) -> None:
        center = QPointF(92, 137)
        painter.save()
        painter.setPen(QPen(QColor(8, 9, 8, 180), 7))
        painter.drawArc(QRectF(48, 90, 88, 94), 67 * 16, 228 * 16)
        painter.setPen(QPen(QColor(190, 127, 54), 4))
        painter.drawArc(QRectF(47, 89, 88, 94), 67 * 16, 228 * 16)
        painter.setPen(QPen(QColor(222, 172, 91), 2))
        for index in range(7):
            y = 105 + index * 10
            painter.drawLine(55 + index % 2, y, 47, y - 5)
            painter.drawLine(129 - index % 2, y, 137, y - 5)

        outer = QRadialGradient(center, 45)
        outer.setColorAt(0.0, QColor(64, 67, 61))
        outer.setColorAt(0.7, QColor(24, 27, 24))
        outer.setColorAt(1.0, QColor(5, 6, 5))
        painter.setBrush(outer)
        painter.setPen(QPen(QColor(8, 9, 8), 5))
        painter.drawEllipse(center, 37, 37)
        painter.setPen(QPen(QColor(210, 146, 61), 3))
        painter.drawEllipse(center, 32, 32)

        core = QPainterPath()
        core.moveTo(92, 106)
        core.cubicTo(104, 120, 112, 137, 98, 162)
        core.cubicTo(91, 154, 84, 148, 73, 157)
        core.cubicTo(82, 138, 78, 125, 92, 106)
        painter.setBrush(QColor(220, 151, 37))
        painter.setPen(QPen(QColor(36, 24, 9), 3))
        painter.drawPath(core)
        painter.setBrush(QColor(245, 206, 94))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(92, 126), 4, 4)
        painter.restore()

    def _draw_title_and_buttons(self, painter: QPainter) -> None:
        painter.save()
        painter.setClipRect(TITLE_RECT)
        self.renderer.draw_layout(
            painter,
            self._title_layout,
            TITLE_RECT.x(),
            TITLE_RECT.y(),
            TITLE_RECT.width(),
            align="center",
        )
        painter.restore()

        body = self.repository.body_family(self.priority)
        completed = layout_text("ВЫПОЛНЕНО", body, 165, line_height=16)
        started = layout_text("Начать", body, 110, line_height=16)
        self.renderer.draw_layout(painter, completed, 203, 59, 165, align="center")
        self.renderer.draw_layout(painter, started, 389, 59, 110, align="center")

    def _draw_lower_panel(self, painter: QPainter) -> None:
        panel_rect = QRectF(15, 216, 510, 316)
        gradient = QLinearGradient(15, 216, 525, 532)
        gradient.setColorAt(0.0, QColor(15, 17, 16))
        gradient.setColorAt(0.48, QColor(40, 43, 40))
        gradient.setColorAt(1.0, QColor(21, 24, 22))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(2, 3, 2), 2))
        painter.drawRoundedRect(panel_rect, 6, 6)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(79, 84, 78), 1))
        painter.drawRoundedRect(panel_rect.adjusted(2, 2, -2, -2), 5, 5)

    def _draw_reward_heading(self, painter: QPainter) -> None:
        shadow_rect = QRectF(81, 360, 390, 31)
        painter.setBrush(QColor(0, 0, 0, 125))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(shadow_rect, 4, 4)

        rect = QRectF(84, REWARD_PANEL_Y, 384, 26)
        gradient = QLinearGradient(0, rect.top(), 0, rect.bottom())
        gradient.setColorAt(0.0, QColor(59, 64, 59))
        gradient.setColorAt(0.5, QColor(41, 45, 42))
        gradient.setColorAt(1.0, QColor(20, 23, 21))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(78, 84, 77), 1))
        painter.drawRoundedRect(rect, 3, 3)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(5, 6, 5), 2))
        painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 2, 2)

        label_layout = layout_text(
            "Эффект",
            self.repository.body_family(self.priority),
            485,
            scale=18 / 16,
            line_height=18,
        )
        self.renderer.draw_layout(
            painter,
            label_layout,
            34,
            368,
            485,
            align="center",
        )

    def _draw_effect(self, painter: QPainter) -> None:
        painter.save()
        painter.setClipRect(QRectF(EFFECT_X, EFFECT_Y, EFFECT_WIDTH, EFFECT_HEIGHT))
        self.renderer.draw_layout(
            painter,
            self._effect_layout,
            EFFECT_X,
            EFFECT_Y - self.effect_scroll,
            EFFECT_WIDTH,
            align="left",
        )
        painter.restore()
        if self.max_effect_scroll > 0:
            self._draw_scrollbar(painter)

    def _draw_scrollbar(self, painter: QPainter) -> None:
        x = 507.0
        top = float(EFFECT_Y)
        bottom = float(EFFECT_Y + EFFECT_HEIGHT)
        painter.setPen(QPen(QColor(7, 8, 7), 1))
        painter.setBrush(QColor(21, 24, 22))
        painter.drawRect(QRectF(x, top + 13, 10, EFFECT_HEIGHT - 26))

        painter.setBrush(QColor(107, 112, 105))
        painter.setPen(QPen(QColor(178, 182, 173), 1))
        up = QPainterPath()
        up.moveTo(x + 5, top)
        up.lineTo(x, top + 10)
        up.lineTo(x + 10, top + 10)
        up.closeSubpath()
        painter.drawPath(up)
        down = QPainterPath()
        down.moveTo(x + 5, bottom)
        down.lineTo(x, bottom - 10)
        down.lineTo(x + 10, bottom - 10)
        down.closeSubpath()
        painter.drawPath(down)

        track_top = top + 15
        track_height = EFFECT_HEIGHT - 30
        ratio = EFFECT_HEIGHT / max(EFFECT_HEIGHT, self._effect_layout.content_height)
        thumb_height = max(18.0, track_height * ratio)
        travel = track_height - thumb_height
        scroll_ratio = (
            self.effect_scroll / self.max_effect_scroll
            if self.max_effect_scroll
            else 0.0
        )
        thumb_y = track_top + travel * scroll_ratio
        thumb_gradient = QLinearGradient(x, 0, x + 10, 0)
        thumb_gradient.setColorAt(0.0, QColor(66, 72, 67))
        thumb_gradient.setColorAt(0.5, QColor(139, 144, 135))
        thumb_gradient.setColorAt(1.0, QColor(63, 68, 63))
        painter.setBrush(thumb_gradient)
        painter.setPen(QPen(QColor(173, 177, 168), 1))
        painter.drawRoundedRect(QRectF(x, thumb_y, 10, thumb_height), 5, 5)

    def _draw_outer_bevel(self, painter: QPainter) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0), 3))
        painter.drawRect(QRectF(1.5, 1.5, 547, 547))
        painter.setPen(QPen(QColor(92, 99, 91, 100), 1))
        painter.drawRect(QRectF(3.5, 3.5, 543, 543))

    def _logical_position(self, position: QPointF) -> QPointF | None:
        if self._target_rect.isEmpty() or not self._target_rect.contains(position):
            return None
        scale = self._target_rect.width() / CANVAS_SIZE
        return QPointF(
            (position.x() - self._target_rect.left()) / scale,
            (position.y() - self._target_rect.top()) / scale,
        )

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        logical = self._logical_position(event.position())
        effect_area = QRectF(EFFECT_X, EFFECT_Y, EFFECT_WIDTH + 15, EFFECT_HEIGHT)
        if (
            logical is not None
            and effect_area.contains(logical)
            and self.max_effect_scroll > 0
        ):
            steps = event.angleDelta().y() / 120.0
            self.effect_scroll = min(
                self.max_effect_scroll,
                max(0.0, self.effect_scroll - steps * 3 * 16),
            )
            self.update()
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # Зарезервировано для будущего перетаскивания ползунка; колесо уже
        # воспроизводит главное поведение игрового текстового слайдера.
        super().mousePressEvent(event)
