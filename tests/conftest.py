from __future__ import annotations

import os
from pathlib import Path

import pytest

from eaw_focus_preview.bmfont import BitmapFont, Glyph


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication([])
    return application


@pytest.fixture
def make_font():
    def factory(
        name: str,
        characters: str,
        *,
        advance: int = 10,
        line_height: int = 16,
        base: int = 13,
    ) -> BitmapFont:
        glyphs = {
            ord(character): Glyph(
                id=ord(character),
                x=0,
                y=0,
                width=max(1, advance),
                height=line_height,
                xoffset=0,
                yoffset=0,
                xadvance=advance,
                page=0,
            )
            for character in set(characters)
        }
        return BitmapFont(
            name=name,
            source_path=Path(f"{name}.fnt"),
            line_height=line_height,
            base=base,
            scale_width=256,
            scale_height=256,
            pages={0: f"{name}.dds"},
            glyphs=glyphs,
        )

    return factory
