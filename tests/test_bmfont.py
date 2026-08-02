from __future__ import annotations

from pathlib import Path

from eaw_focus_preview.bmfont import parse_fnt_text, resolve_atlas_path


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
