from __future__ import annotations

from pathlib import Path

from eaw_focus_preview.bmfont import FontRepository
from eaw_focus_preview.layout import DEFAULT_COLOR, layout_text


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_real_mod_fonts_render_mixed_russian_english_text() -> None:
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    family = repository.body_family("ru")
    layout = layout_text("Армия: +5% Attack", family, 455)
    assert layout.missing_glyphs == ()
    used_fonts = {
        item.font.name
        for line in layout.lines
        for item in line.glyphs
        if item.font is not None and not item.character.isspace()
    }
    assert "body_ru" in used_fonts
    assert "body_en" in used_fonts


def test_real_cyrillic_fnt_resolves_mismatched_page_name() -> None:
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    font = repository.fonts["body_ru"]
    assert font.pages[0].endswith("_0.dds")
    assert font.atlas_paths[0].name == "eaw_diplo_16mbs_cryllic.dds"


def test_fractionally_scaled_glyph_is_prefiltered_and_cached() -> None:
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    font = repository.fonts["body_ru"]
    glyph = font.glyphs[ord("А")]

    scaled = font.glyph_image(glyph, DEFAULT_COLOR, scale=18 / 16)
    cached = font.glyph_image(glyph, DEFAULT_COLOR, scale=18 / 16)

    top, right, bottom, left = font.padding
    assert font.padding == (2, 2, 2, 2)
    assert scaled.width() == round(
        (glyph.width - left - right) * 18 / 16 + left + right
    )
    assert scaled.height() == round(
        (glyph.height - top - bottom) * 18 / 16 + top + bottom
    )
    assert scaled.cacheKey() == cached.cacheKey()
