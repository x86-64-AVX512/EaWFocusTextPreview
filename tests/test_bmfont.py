from __future__ import annotations

from pathlib import Path

from eaw_focus_preview import bmfont
from eaw_focus_preview.bmfont import (
    find_game_fonts_directory,
    parse_fnt_text,
    resolve_atlas_path,
)


def _create_game_font_markers(game_root: Path) -> Path:
    fonts = game_root / "gfx" / "fonts"
    fonts.mkdir(parents=True)
    (fonts / "hoi_18mbs.fnt").write_text("font", encoding="utf-8")
    (fonts / "hoi_18mbs_cryllic.fnt").write_text("font", encoding="utf-8")
    return fonts


def test_parser_reads_required_metrics() -> None:
    parsed = parse_fnt_text(
        "\n".join(
            [
                'info face="Test Font" size=16 padding=2,3,4,5',
                "common lineHeight=18 base=14 scaleW=256 scaleH=128 pages=1",
                'page id=0 file="font_0.dds"',
                (
                    "char id=1040 x=10 y=20 width=11 height=13 "
                    "xoffset=-2 yoffset=3 xadvance=9 page=0 chnl=15"
                ),
            ]
        )
    )
    glyph = parsed.glyphs[1040]
    assert parsed.line_height == 18
    assert parsed.base == 14
    assert parsed.scale_width == 256
    assert parsed.scale_height == 128
    assert parsed.padding == (2, 3, 4, 5)
    assert parsed.pages == {0: "font_0.dds"}
    assert (
        glyph.id,
        glyph.x,
        glyph.y,
        glyph.width,
        glyph.height,
        glyph.xoffset,
        glyph.yoffset,
        glyph.xadvance,
    ) == (1040, 10, 20, 11, 13, -2, 3, 9)


def test_page_name_falls_back_to_fnt_name(tmp_path: Path) -> None:
    fnt_path = tmp_path / "eaw_diplo_16mbs_cryllic.fnt"
    actual_dds = tmp_path / "eaw_diplo_16mbs_cryllic.dds"
    fnt_path.write_text("placeholder", encoding="utf-8")
    actual_dds.write_bytes(b"DDS ")
    resolved = resolve_atlas_path(
        fnt_path,
        "eaw_diplo_16mbs_cryllic_0.dds",
    )
    assert resolved == actual_dds


def test_game_font_search_uses_steam_root_from_registry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    steam_root = tmp_path / "custom-steam"
    game_root = steam_root / "steamapps" / "common" / "Hearts of Iron IV"
    expected = _create_game_font_markers(game_root)
    monkeypatch.delenv("HOI4_INSTALL_DIR", raising=False)
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "missing-x86"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "missing-x64"))
    monkeypatch.setattr(bmfont, "_registry_steam_roots", lambda: [steam_root])
    monkeypatch.setattr(bmfont, "_registry_game_roots", lambda: [])

    assert find_game_fonts_directory() == expected


def test_game_font_search_uses_uninstall_location_from_registry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    game_root = tmp_path / "manually-registered-hoi4"
    expected = _create_game_font_markers(game_root)
    monkeypatch.delenv("HOI4_INSTALL_DIR", raising=False)
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "missing-x86"))
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "missing-x64"))
    monkeypatch.setattr(bmfont, "_registry_steam_roots", lambda: [])
    monkeypatch.setattr(bmfont, "_registry_game_roots", lambda: [game_root])

    assert find_game_fonts_directory() == expected
