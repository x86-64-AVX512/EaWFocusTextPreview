from __future__ import annotations

import json
from pathlib import Path

from eaw_focus_preview.bmfont import FontRepository
from eaw_focus_preview.focus_canvas import (
    DESCRIPTION_CYRILLIC_VISUAL_METRICS,
    DESCRIPTION_ENGLISH_LAYOUT_WIDTH,
    DESCRIPTION_LATIN_LAYOUT_WIDTH,
    DESCRIPTION_WIDTH,
    FocusCanvas,
    preview_target_geometry,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _layout_lines(canvas: FocusCanvas) -> list[str]:
    return [
        "".join(glyph.character for glyph in line.glyphs)
        for line in canvas._description_layout.lines
    ]


def test_preview_keeps_one_to_one_physical_pixels_at_common_dpi() -> None:
    for device_pixel_ratio in (1.0, 1.25, 1.5, 2.0, 10.0):
        target, physical_scale = preview_target_geometry(
            700,
            650,
            device_pixel_ratio,
        )

        assert target.width() * device_pixel_ratio == 550
        assert target.height() * device_pixel_ratio == 550
        assert target.left() * device_pixel_ratio == round(
            target.left() * device_pixel_ratio
        )
        assert target.top() * device_pixel_ratio == round(
            target.top() * device_pixel_ratio
        )
        assert physical_scale == 1.0


def test_preview_only_downscales_when_physical_space_is_too_small() -> None:
    target, physical_scale = preview_target_geometry(330, 300, 1.25)

    assert target.width() * 1.25 == 375
    assert target.height() * 1.25 == 375
    assert physical_scale == 375 / 550


def test_preview_target_handles_invalid_or_extreme_dpi() -> None:
    invalid_target, invalid_scale = preview_target_geometry(550, 550, 0.0)
    huge_target, huge_scale = preview_target_geometry(330, 330, 1000.0)

    assert invalid_target == preview_target_geometry(550, 550, 1.0)[0]
    assert invalid_scale == 1.0
    assert huge_target.width() == 0.55
    assert huge_target.height() == 0.55
    assert huge_target.width() * 1000 == 550
    assert huge_scale == 1.0


def test_game_visual_atlas_cannot_change_russian_wrapping(qapp) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    fallback_repository = FontRepository(repository.fonts)
    text = (
        "съешь ещё этих мягких французских булок, да выпей чаю. "
        "Восстания будут продолжаться бесконечно, если мирное население "
        "нам не радо. Хотя мы не можем изменить сердца и умы в одночасье."
    )

    game_atlas_canvas = FocusCanvas(repository)
    game_atlas_canvas.set_content(
        title="",
        description=text,
        effect="",
        priority="ru",
    )
    fallback_canvas = FocusCanvas(fallback_repository)
    fallback_canvas.set_content(
        title="",
        description=text,
        effect="",
        priority="ru",
    )

    lines_before_render = _layout_lines(game_atlas_canvas)
    widths_before_render = [
        line.width for line in game_atlas_canvas._description_layout.lines
    ]
    image = game_atlas_canvas.render_preview()

    assert not image.isNull()
    assert lines_before_render == _layout_lines(game_atlas_canvas)
    assert lines_before_render == _layout_lines(fallback_canvas)
    assert widths_before_render == [
        line.width for line in fallback_canvas._description_layout.lines
    ]
    assert "будут продолжаться" in text
    assert all(
        not character.isalpha()
        or not ("а" <= character.casefold() <= "я" or character.casefold() == "ё")
        or character in DESCRIPTION_CYRILLIC_VISUAL_METRICS
        for character in text
    )


def test_long_description_crosses_panel_and_effect_scrolls(qapp) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository)
    canvas.set_content(
        title="ДЛИННАЯ ПРОВЕРКА",
        description=("Очень длинное описание национального фокуса. " * 40),
        effect=("Армия: §G+5%§! Attack\\n" * 18),
        priority="ru",
    )
    diagnostics = canvas.diagnostics
    assert diagnostics.description_panel_overlap > 0
    assert diagnostics.description_level == "red"
    assert diagnostics.effect_overflow > 0
    assert diagnostics.effect_level == "red"
    image = canvas.render_preview()
    assert image.width() == 550
    assert image.height() == 550
    assert not image.isNull()


def test_description_wrap_uses_game_text_insets(qapp) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository)
    text = (
        PROJECT_ROOT / "tests" / "fixtures" / "wrap_reference.txt"
    ).read_text(encoding="utf-8").strip()
    canvas.set_content(
        title="",
        description=text,
        effect="",
        priority="ru",
    )

    lines = [
        "".join(glyph.character for glyph in line.glyphs)
        for line in canvas._description_layout.lines
    ]

    assert DESCRIPTION_WIDTH == 485
    assert canvas._description_layout.max_width == 474
    assert lines == [
        "Является ли кто-либо по-настоящему сильным, если он нелепо",
        "издевается над теми, кто ниже его? Странно, что нам потребовалось",
        "так много времени, чтобы осознать это, но на самом деле нет",
        "истинной силы в том, чтобы унижать слабых. Возможно, мы",
        "совершили великий проступок, действуя в соответствии с",
        "подобными импульсами раньше и позволяя кланам издеваться над",
    ]

    mixed_tail = text.removesuffix("издеваться над") + "иdsfdsfsdfsdfsd."
    canvas.set_content(
        title="",
        description=mixed_tail,
        effect="",
        priority="ru",
    )
    mixed_lines = [
        "".join(glyph.character for glyph in line.glyphs)
        for line in canvas._description_layout.lines
    ]
    assert canvas._description_layout.max_width == 474
    assert mixed_lines[:7] == [
        "Является ли кто-либо по-настоящему сильным, если он нелепо",
        "издевается над теми, кто ниже его? Странно, что нам потребовалось",
        "так много времени, чтобы осознать это, но на самом деле нет",
        "истинной силы в том, чтобы унижать слабых. Возможно, мы",
        "совершили великий проступок, действуя в соответствии с",
        "подобными импульсами раньше и позволяя кланам",
        "иdsfdsfsdfsdfsd.",
    ]


def test_second_russian_description_disambiguates_game_width(qapp) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository)
    text = (
        PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "wrap_reference_russian_magic.txt"
    ).read_text(encoding="utf-8").strip()
    canvas.set_content(
        title="",
        description=text,
        effect="",
        priority="ru",
    )

    lines = [
        "".join(glyph.character for glyph in line.glyphs)
        for line in canvas._description_layout.lines
    ]

    assert canvas._description_layout.max_width == 474
    assert lines[:6] == [
        "Материалистические догматы не единственный путь прогресса.",
        "Наши исследования также помогают нам понять наше прошлое,",
        "которое открывает нам новые горизонты древней грифоньей",
        "магии. Люши всегда было местом множества легенд и мифов.",
        "Магия здесь так сильна, что вы не найдете места в Грифонии, где",
        "магический фон был бы так высок. Благодаря тому что мы находим",
    ]


def test_third_russian_description_uses_calibrated_cyrillic_advances(qapp) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository)
    text = (
        PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "wrap_reference_russian_religion.txt"
    ).read_text(encoding="utf-8").strip()
    expected_lines = (
        PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "wrap_reference_russian_religion_game_lines.txt"
    ).read_text(encoding="utf-8").splitlines()
    canvas.set_content(
        title="",
        description=text,
        effect="",
        priority="ru",
    )

    lines = [
        "".join(glyph.character for glyph in line.glyphs)
        for line in canvas._description_layout.lines
    ]

    assert canvas._description_layout.max_width == 474
    assert lines[:6] == expected_lines


def test_fourth_russian_description_keeps_last_word_for_next_line(qapp) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository)
    text = (
        PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "wrap_reference_russian_agriculture.txt"
    ).read_text(encoding="utf-8").strip()
    expected_lines = (
        PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "wrap_reference_russian_agriculture_game_lines.txt"
    ).read_text(encoding="utf-8").splitlines()
    canvas.set_content(
        title="",
        description=text,
        effect="",
        priority="ru",
    )

    lines = [
        "".join(glyph.character for glyph in line.glyphs)
        for line in canvas._description_layout.lines
    ]

    assert canvas._description_layout.max_width == 474
    assert lines[:6] == expected_lines
    assert lines[6].startswith("Теперь ")


def test_terminal_period_keeps_engineers_on_the_game_line(qapp) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository)
    text = (
        PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "wrap_reference_russian_engineers.txt"
    ).read_text(encoding="utf-8").strip()
    expected_lines = (
        PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "wrap_reference_russian_engineers_game_lines.txt"
    ).read_text(encoding="utf-8").splitlines()
    canvas.set_content(
        title="",
        description=text,
        effect="",
        priority="ru",
    )

    lines = [
        "".join(glyph.character for glyph in line.glyphs)
        for line in canvas._description_layout.lines
    ]

    assert lines == expected_lines
    assert canvas._description_layout.lines[-1].width <= 474
    assert canvas.diagnostics.description_panel_overlap == 0


def test_english_description_wrap_matches_game_reference(qapp) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository)
    text = (
        PROJECT_ROOT / "tests" / "fixtures" / "wrap_reference_english.txt"
    ).read_text(encoding="utf-8").strip()
    canvas.set_content(
        title="",
        description=text,
        effect="",
        priority="ru",
    )

    lines = [
        "".join(glyph.character for glyph in line.glyphs)
        for line in canvas._description_layout.lines
    ]

    assert DESCRIPTION_LATIN_LAYOUT_WIDTH == 474
    assert canvas._description_layout.max_width == 474
    assert lines[:8] == [
        "Should Vedina find itself pulled into war on the continent, we make",
        "sure we are prepared. Our industry is not yet ready for a complete and",
        "total conversation to war-time production and for the absolute",
        "mobilization of the available workforce. If Vedina hopes to survive, it",
        "must make sure its people are ready to pour everything they have into",
        "pure, undeniable victory - not necessarily on the battlefield, but on the",
        "production front, in the fields and farms, in the laboratories, in the",
        "skies and on the seas. Vedina must prepare for the storm, or else be",
    ]


def test_russian_calibration_matches_one_hundred_sixty_eight_game_references(
    qapp,
) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository)
    references = []
    for fixture_name in (
        "calibration_2300_2308.json",
        "calibration_2309_2317.json",
        "calibration_2318_2326.json",
        "calibration_run_20260730_123849.json",
        "calibration_run_20260730_153123.json",
        "calibration_run_20260731_f3.json",
        "calibration_run_20260801_files_selected.json",
        "calibration_run_20260801_files_selected_f7_1.json",
        "calibration_run_20260801_files_selected_f7_2.json",
        "calibration_run_20260801_files_selected_f7_3.json",
        "calibration_run_20260801_files_selected_f7_4.json",
    ):
        references.extend(
            json.loads(
                (
                    PROJECT_ROOT
                    / "tests"
                    / "fixtures"
                    / fixture_name
                ).read_text(encoding="utf-8")
            )
        )

    assert len(references) == 168
    for reference in references:
        canvas.set_content(
            title="",
            description=reference["text"],
            effect="",
            priority="ru",
        )
        expected = reference["expected_lines"]
        actual = [
            "".join(glyph.character for glyph in line.glyphs)
            for line in canvas._description_layout.lines[:len(expected)]
        ]
        assert actual == expected, (
            f"{reference['id']} / "
            f"{reference.get('screenshot', reference.get('case_id', 'run'))}"
        )


def test_russian_calibration_preserves_all_ocr_confirmed_classifications(
    qapp,
) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository)
    references = []
    for part in range(1, 6):
        references.extend(
            json.loads(
                (
                    PROJECT_ROOT
                    / "tests"
                    / "fixtures"
                    / f"calibration_run_20260801_files_matches_{part}.json"
                ).read_text(encoding="utf-8")
            )
        )

    assert len(references) == 149
    assert sum(bool(item.get("expected_overflow")) for item in references) == 2
    for reference in references:
        canvas.set_content(
            title="",
            description=reference["text"],
            effect="",
            priority="ru",
        )
        line_count = len(canvas._description_layout.lines)
        if reference.get("expected_overflow"):
            assert line_count >= 7, reference["case_id"]
        else:
            assert line_count == reference["expected_line_count"], (
                reference["case_id"],
                line_count,
            )


def test_second_english_description_disambiguates_game_width(qapp) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository)
    text = (
        PROJECT_ROOT
        / "tests"
        / "fixtures"
        / "wrap_reference_english_doom.txt"
    ).read_text(encoding="utf-8").strip()
    canvas.set_content(
        title="",
        description=text,
        effect="",
        priority="ru",
    )

    lines = [
        "".join(glyph.character for glyph in line.glyphs)
        for line in canvas._description_layout.lines
    ]

    assert canvas._description_layout.max_width == 474
    assert lines[:6] == [
        "The resurgent Griffonian Empire grows like a tumour over the",
        "continent, driven by the urge to relive the bygone days of the old",
        "empire. As its soldiers storm its surrounding countries to restore glory",
        "which never truly existed, it's becoming clearer and clearer that, unless",
        "stopped, they will soon come knocking on Vedina's door. We must cut",
        "out this cancer before it spreads, and strike before they become",
    ]


def test_english_calibration_classifies_all_reliable_ocr_cases(qapp) -> None:
    del qapp
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository)
    references = json.loads(
        (
            PROJECT_ROOT
            / "tests"
            / "fixtures"
            / "calibration_run_20260801_english.json"
        ).read_text(encoding="utf-8")
    )

    assert len(references) == 100
    assert sum(item["expected_overflow"] for item in references) == 69
    assert sum(not item["expected_overflow"] for item in references) == 31
    assert DESCRIPTION_ENGLISH_LAYOUT_WIDTH == 474

    for reference in references:
        canvas.set_content(
            title="",
            description=reference["text"],
            effect="",
            priority="en",
        )
        actual_overflow = len(canvas._description_layout.lines) >= 7
        assert canvas._description_layout.max_width == 474
        assert actual_overflow == reference["expected_overflow"], (
            reference["case_id"],
            len(canvas._description_layout.lines),
        )
        if "expected_lines" in reference:
            actual_lines = [
                "".join(glyph.character for glyph in line.glyphs)
                for line in canvas._description_layout.lines
            ]
            assert actual_lines == reference["expected_lines"], (
                reference["case_id"],
                actual_lines,
            )
