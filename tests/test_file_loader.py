from __future__ import annotations

from pathlib import Path

from eaw_focus_preview.file_loader import (
    load_contextual_focus_file,
    load_focus_localisation_file,
    load_text_payload,
    parse_focus_ids,
    parse_focus_localisation_entries,
)


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


def test_batch_localisation_pairs_every_description_with_its_title() -> None:
    entries = parse_focus_localisation_entries(
        'l_russian:\n'
        ' FIRST:0 "Первый фокус"\n'
        ' FIRST_desc:0 "Первое описание"\n'
        ' SECOND_name:0 "Второй фокус"\n'
        ' SECOND_description:0 "Второе описание с \"кавычками\""\n'
        ' UNUSED:0 "Не описание"\n'
    )

    assert [(entry.key, entry.title, entry.description) for entry in entries] == [
        ("FIRST_desc", "Первый фокус", "Первое описание"),
        (
            "SECOND_description",
            "Второй фокус",
            'Второе описание с "кавычками"',
        ),
    ]


def test_batch_file_accepts_arbitrary_keys_and_quoted_values(
    tmp_path: Path,
) -> None:
    path = tmp_path / "focuses_l_english.yml"
    path.write_text(
        'l_english:\n FOCUS_ONE:0 "First focus text."\n'
        ' FOCUS_TWO:0 "Second focus text."\n',
        encoding="utf-8-sig",
    )

    batch = load_focus_localisation_file(path)

    assert batch.language == "english"
    assert batch.source_format == "keyed"
    assert [entry.key for entry in batch.entries] == ["FOCUS_ONE", "FOCUS_TWO"]
    assert [entry.description for entry in batch.entries] == [
        "First focus text.",
        "Second focus text.",
    ]


def test_batch_file_accepts_one_plain_focus_per_nonempty_line(
    tmp_path: Path,
) -> None:
    path = tmp_path / "focuses.txt"
    path.write_text(
        "Первый голый текст.\n\n"
        "# комментарий не проверяется\n"
        '"Второй текст с \\"кавычками\\" и буквальным \\n."\n',
        encoding="utf-8",
    )

    batch = load_focus_localisation_file(path)

    assert batch.language is None
    assert batch.source_format == "plain"
    assert [entry.line_number for entry in batch.entries] == [1, 4]
    assert [entry.description for entry in batch.entries] == [
        "Первый голый текст.",
        'Второй текст с "кавычками" и буквальным \\n.',
    ]


def test_context_parser_collects_only_direct_focus_ids() -> None:
    assert parse_focus_ids(
        """
        focus_tree = {
            id = NOT_A_FOCUS
            focus = {
                id = FOCUS_ONE
                completion_reward = { id = NOT_DIRECT }
            }
            shared_focus = { id = "FOCUS_TWO" }
            joint_focus = { id = FOCUS_THREE }
        }
        # focus = { id = COMMENTED_OUT }
        """
    ) == frozenset({"FOCUS_ONE", "FOCUS_TWO", "FOCUS_THREE"})


def test_contextual_batch_filters_by_mod_ids_and_marks_raw_lines_red(
    tmp_path: Path,
) -> None:
    mod_root = tmp_path / "mod"
    focus_directory = mod_root / "common" / "national_focus"
    focus_directory.mkdir(parents=True)
    (focus_directory / "tree.txt").write_text(
        "focus_tree = {\n"
        " focus = { id = REAL_FOCUS }\n"
        " shared_focus = { id = SHARED_FOCUS }\n"
        "}\n",
        encoding="utf-8",
    )
    path = tmp_path / "focus_l_russian.yml"
    path.write_text(
        'l_russian:\n'
        ' REAL_FOCUS:0 "Название"\n'
        ' REAL_FOCUS_desc:0 "Описание"\n'
        ' EVENT_desc:0 "Не фокус"\n'
        "Голый текст запрещён в контекстном режиме\n",
        encoding="utf-8-sig",
    )

    batch = load_contextual_focus_file(path, mod_root)

    assert batch.source_format == "contextual"
    assert batch.known_focus_ids == 2
    assert batch.ignored_values == 1
    assert [(entry.key, entry.title) for entry in batch.entries] == [
        ("REAL_FOCUS_desc", "Название")
    ]
    assert len(batch.errors) == 1
    assert batch.errors[0].line_number == 5
    assert 'KEY: "Текст"' in batch.errors[0].message


def test_contextual_batch_accepts_key_without_version_number(
    tmp_path: Path,
) -> None:
    mod_root = tmp_path / "mod"
    focus_directory = mod_root / "common" / "national_focus"
    focus_directory.mkdir(parents=True)
    (focus_directory / "tree.txt").write_text(
        "focus = { id = REAL_FOCUS }",
        encoding="utf-8",
    )
    path = tmp_path / "focuses.yml"
    path.write_text(
        'REAL_FOCUS: "Название"\n'
        'REAL_FOCUS_desc: "Описание"\n',
        encoding="utf-8",
    )

    batch = load_contextual_focus_file(path, mod_root)

    assert not batch.errors
    assert len(batch.entries) == 1
    assert batch.entries[0].title == "Название"
    assert batch.entries[0].description == "Описание"
