from __future__ import annotations

from pathlib import Path

from eaw_focus_preview.file_loader import load_text_payload


def test_sectioned_txt_populates_all_fields(tmp_path: Path) -> None:
    path = tmp_path / "focus.txt"
    path.write_text(
        "[title]\nНазвание\n[description]\nОписание\n[effect]\n§G+5%§!",
        encoding="utf-8",
    )
    payload = load_text_payload(path)
    assert payload.title == "Название"
    assert payload.description == "Описание"
    assert payload.effect == "§G+5%§!"


def test_localisation_yaml_uses_suffixes(tmp_path: Path) -> None:
    path = tmp_path / "focus_l_russian.yml"
    path.write_text(
        'l_russian:\n key_name:0 "Имя"\n key_desc:0 "Описание"\n'
        ' key_effect:0 "§YЭффект§!"\n',
        encoding="utf-8-sig",
    )
    payload = load_text_payload(path)
    assert payload.title == "Имя"
    assert payload.description == "Описание"
    assert payload.effect == "§YЭффект§!"


def test_localisation_yaml_keeps_unescaped_inner_quotes(tmp_path: Path) -> None:
    path = tmp_path / "focus_l_russian.yml"
    description = (
        'Казна, которая "финансирует" [Root.ABY_royal_loc_nocap]ая знать.'
    )
    path.write_text(
        f'l_russian:\n key_desc:0 "{description}"\n',
        encoding="utf-8-sig",
    )

    payload = load_text_payload(path)

    assert payload.description == description


def test_localisation_yaml_ignores_quotes_inside_trailing_comment(
    tmp_path: Path,
) -> None:
    path = tmp_path / "focus_l_russian.yml"
    path.write_text(
        'l_russian:\n key_desc:0 "Труза Уиндмастер" '
        '# не писать "Трусах"\n',
        encoding="utf-8-sig",
    )

    payload = load_text_payload(path)

    assert payload.description == "Труза Уиндмастер"
