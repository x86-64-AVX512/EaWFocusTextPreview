from __future__ import annotations

from pathlib import Path

from eaw_focus_preview.bmfont import FontRepository
from eaw_focus_preview.clausewitz_interpreter import (
    child_blocks,
    condition_from_trigger,
    expression_predicates,
    parse_clausewitz,
)
from eaw_focus_preview.dynamic_localisation import (
    ModLocalisation,
    parse_localisation_text,
    parse_scripted_localisation,
)
from eaw_focus_preview.focus_canvas import FocusCanvas
from eaw_focus_preview.validation_api import FocusValidationEngine


PROJECT_ROOT = Path(__file__).resolve().parent.parent


SCRIPTED_LOCALISATION = """
defined_text = {
    name = TEST_royal_nocap
    text = {
        trigger = { has_country_flag = empire }
        localization_key = TEST_IMPERIAL
    }
    text = { localization_key = TEST_ROYAL }
}
defined_text = {
    name = TEST_nested
    text = { localization_key = TEST_NESTED }
}
"""


LOCALISATION = '''l_russian:
 TEST_IMPERIAL:0 "имперск"
 TEST_ROYAL:0 "королевск"
 TEST_NESTED:0 "[Root.TEST_royal_nocap]ий"
 TEST_FALSE_QUOTES:0 "Казна, которая "финансирует" короля."
 AAA:0 "А"
 AAA_DEF:0 "А"
 AAA_ADJ:0 "Альфийск"
 AAA_empire:0 "Альфийская империя"
 AAA_empire_DEF:0 "Альфийская империя"
 AAA_empire_ADJ:0 "Имперско-альфийск"
 BBB:0 "Очень длинная республика Бета"
 BBB_DEF:0 "Очень длинная республика Бета"
 BBB_ADJ:0 "Очень-длинно-бетск"
 STATE_1:0 "Длинная Северная провинция"
 VICTORY_POINTS_1:0 "Невероятно длинная столица"
 AAA_LONG_LEADER:0 "Александр Длинноимённый"
 AAA_fascism_party:0 "Партия с очень длинным названием"
 TEST_LONG_FACTION:0 "Международный оборонительный союз"
l_english:
 TEST_IMPERIAL:0 "imperial"
 TEST_ROYAL:0 "royal"
 TEST_NESTED:0 "[Root.TEST_royal_nocap]"
'''


def _create_mod(tmp_path: Path) -> ModLocalisation:
    scripted = tmp_path / "common" / "scripted_localisation"
    tags = tmp_path / "common" / "country_tags"
    characters = tmp_path / "common" / "characters"
    factions = tmp_path / "common" / "factions"
    russian = tmp_path / "localisation" / "russian"
    scripted.mkdir(parents=True)
    tags.mkdir(parents=True)
    characters.mkdir(parents=True)
    factions.mkdir(parents=True)
    russian.mkdir(parents=True)
    (scripted / "test.txt").write_text(
        SCRIPTED_LOCALISATION,
        encoding="utf-8",
    )
    (russian / "test_l_russian.yml").write_text(
        LOCALISATION,
        encoding="utf-8-sig",
    )
    (tags / "test.txt").write_text(
        'AAA = "countries/AAA.txt"\nBBB = "countries/BBB.txt"\n',
        encoding="utf-8",
    )
    (characters / "test.txt").write_text(
        "characters = {\n AAA_leader = {\n  name = AAA_LONG_LEADER\n"
        "  country_leader = { ideology = neutrality }\n }\n}",
        encoding="utf-8",
    )
    (factions / "test.txt").write_text(
        "#create_faction = TEST_LONG_FACTION\n",
        encoding="utf-8",
    )
    return ModLocalisation.load(tmp_path)


def test_scripted_and_localisation_parsers_keep_all_variants() -> None:
    definitions = parse_scripted_localisation(SCRIPTED_LOCALISATION)
    values = parse_localisation_text(LOCALISATION)

    assert definitions["TEST_royal_nocap"] == (
        "TEST_IMPERIAL",
        "TEST_ROYAL",
    )
    assert (
        values["russian"]["TEST_FALSE_QUOTES"]
        == 'Казна, которая "финансирует" короля.'
    )


def test_resolution_uses_worst_variant_and_keeps_repeated_tokens_consistent(
    tmp_path: Path,
) -> None:
    mod = _create_mod(tmp_path)
    token = "[Root.TEST_royal_nocap]"
    source = f"{token}ая казна и {token}ий двор"

    resolution = mod.resolve_worst_case(
        source,
        "russian",
        lambda candidate: (len(candidate),),
    )

    assert resolution.text == "королевская казна и королевский двор"
    assert resolution.combinations_evaluated == 2
    assert len(resolution.replacements) == 1
    assert resolution.replacements[0].variants == ("имперск", "королевск")
    assert resolution.unresolved_tokens == ()


def test_nested_scripted_localisation_and_unknown_token(
    tmp_path: Path,
) -> None:
    mod = _create_mod(tmp_path)

    variants = mod.variants_for("TEST_nested", "russian")
    resolution = mod.resolve_worst_case(
        "[Root.TEST_nested] [Root.UnknownFunction]",
        "russian",
        lambda candidate: (len(candidate),),
    )

    assert variants == ("имперский", "королевский")
    assert resolution.text == "королевский [Root.UnknownFunction]"
    assert resolution.unresolved_tokens == ("[Root.UnknownFunction]",)


def test_canvas_and_api_render_resolved_worst_case(
    qapp,
    tmp_path: Path,
) -> None:
    del qapp
    mod = _create_mod(tmp_path)
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    canvas = FocusCanvas(repository, mod_localisation=mod)
    source = "[Root.TEST_royal_nocap]ая казна"

    canvas.set_content(
        title="",
        description=source,
        effect="",
        priority="ru",
        language="russian",
    )

    assert canvas.resolved_description == source
    assert canvas.dynamic_localisation_report["available"] is True
    assert canvas.dynamic_localisation_report["enabled"] is False
    assert canvas.dynamic_localisation_report["replacement_count"] == 0

    canvas.set_content(
        title="",
        description=source,
        effect="",
        priority="ru",
        language="russian",
        dynamic_localisation_enabled=True,
    )

    assert canvas.resolved_description == "королевская казна"
    assert canvas.dynamic_localisation_report["replacement_count"] == 1

    engine = FocusValidationEngine(repository, mod)
    disabled = engine.process_document({"description": source})
    assert disabled["result"]["dynamic_localisation"]["enabled"] is False
    assert disabled["result"]["dynamic_localisation"]["fields"][
        "description"
    ]["resolved_text"] == source

    response = engine.process_document(
        {
            "description": source,
            "dynamic_localisation": True,
        }
    )
    dynamic = response["result"]["dynamic_localisation"]
    assert response["ok"] is True
    assert dynamic["fields"]["description"]["resolved_text"] == (
        "королевская казна"
    )


def test_automatic_getters_use_finite_mod_values_and_leave_variables(
    tmp_path: Path,
) -> None:
    mod = _create_mod(tmp_path)

    country = mod.resolve_worst_case(
        "[Root.GetName]",
        "russian",
        lambda candidate: (len(candidate),),
    )
    fixed_country = mod.resolve_worst_case(
        "[AAA.GetName]",
        "russian",
        lambda candidate: (len(candidate),),
    )
    leader = mod.resolve_worst_case(
        "[Root.GetLeader]",
        "russian",
        lambda candidate: (len(candidate),),
    )
    capital = mod.resolve_worst_case(
        "[Root.Capital.GetName]",
        "russian",
        lambda candidate: (len(candidate),),
    )
    runtime_variable = mod.resolve_worst_case(
        "[?treasury]",
        "russian",
        lambda candidate: (len(candidate),),
    )

    assert country.text == "Очень длинная республика Бета"
    assert fixed_country.text == "Альфийская империя"
    assert leader.text == "Александр Длинноимённый"
    assert capital.text == "Невероятно длинная столица"
    assert runtime_variable.text == "[?treasury]"
    assert runtime_variable.unresolved_tokens == ("[?treasury]",)


def test_clausewitz_parser_preserves_variable_comparison_operators() -> None:
    parsed = parse_clausewitz(
        "trigger = { check_variable = { var = treasury value > 4 } }"
    )
    trigger = child_blocks(parsed, "trigger")[0]
    expression = condition_from_trigger(trigger)
    predicates = expression_predicates(expression)

    assert len(predicates) == 1
    assert predicates[0].key == "variable:treasury"
    assert predicates[0].operator == ">"
    assert predicates[0].value == "4"


def test_symbolic_interpreter_rejects_impossible_cross_token_state(
    tmp_path: Path,
) -> None:
    scripted = tmp_path / "common" / "scripted_localisation"
    localisation = tmp_path / "localisation" / "russian"
    scripted.mkdir(parents=True)
    localisation.mkdir(parents=True)
    (scripted / "states.txt").write_text(
        """
defined_text = {
 name = FIRST
 text = { trigger = { state = 1 } localization_key = FIRST_ONE }
 text = { trigger = { state = 2 } localization_key = FIRST_TWO }
 text = { localization_key = FIRST_DEFAULT }
}
defined_text = {
 name = SECOND
 text = { trigger = { state = 1 } localization_key = SECOND_ONE }
 text = { trigger = { state = 2 } localization_key = SECOND_TWO }
 text = { localization_key = SECOND_DEFAULT }
}
""",
        encoding="utf-8",
    )
    (localisation / "states_l_russian.yml").write_text(
        '''l_russian:
 FIRST_ONE:0 "AAAAAAAAAA"
 FIRST_TWO:0 "a"
 FIRST_DEFAULT:0 "f"
 SECOND_ONE:0 "b"
 SECOND_TWO:0 "BBBBBBBBBB"
 SECOND_DEFAULT:0 "g"
''',
        encoding="utf-8-sig",
    )
    mod = ModLocalisation.load(tmp_path)

    result = mod.resolve_worst_case(
        "[Root.FIRST]/[Root.SECOND]",
        "russian",
        lambda candidate: (len(candidate), candidate),
    )

    assert result.text in {"AAAAAAAAAA/b", "a/BBBBBBBBBB"}
    assert result.text != "AAAAAAAAAA/BBBBBBBBBB"
    assert result.incompatible_combinations > 0
    assert result.confidence == "exact"


def test_unknown_scripted_trigger_is_conservative_not_unresolved(
    tmp_path: Path,
) -> None:
    scripted = tmp_path / "common" / "scripted_localisation"
    localisation = tmp_path / "localisation" / "russian"
    scripted.mkdir(parents=True)
    localisation.mkdir(parents=True)
    (scripted / "unknown.txt").write_text(
        """
defined_text = {
 name = UNKNOWN_BRANCH
 text = {
  trigger = { custom_eaw_scripted_trigger = yes }
  localization_key = UNKNOWN_LONG
 }
 text = { localization_key = UNKNOWN_SHORT }
}
""",
        encoding="utf-8",
    )
    (localisation / "unknown_l_russian.yml").write_text(
        'l_russian:\n UNKNOWN_LONG:0 "очень длинный вариант"\n'
        ' UNKNOWN_SHORT:0 "короткий"\n',
        encoding="utf-8-sig",
    )
    mod = ModLocalisation.load(tmp_path)

    result = mod.resolve_worst_case(
        "[Root.UNKNOWN_BRANCH]",
        "russian",
        lambda candidate: (len(candidate),),
    )

    assert result.text == "очень длинный вариант"
    assert result.unresolved_tokens == ()
    assert result.confidence == "conservative"
    assert result.replacements[0].condition == (
        "custom_eaw_scripted_trigger = yes"
    )


def test_base_game_scripted_definition_is_loaded_lazily(
    tmp_path: Path,
) -> None:
    base = tmp_path / "game"
    mod_root = tmp_path / "mod"
    base_scripted = base / "common" / "scripted_localisation"
    base_loc = base / "localisation" / "russian"
    mod_scripted = mod_root / "common" / "scripted_localisation"
    mod_loc = mod_root / "localisation" / "russian"
    for directory in (base_scripted, base_loc, mod_scripted, mod_loc):
        directory.mkdir(parents=True)
    (base_scripted / "base.txt").write_text(
        "defined_text = { name = BASE_DYNAMIC "
        "text = { localization_key = BASE_TEXT } }",
        encoding="utf-8",
    )
    (base_loc / "base_l_russian.yml").write_text(
        'l_russian:\n BASE_TEXT:0 "текст из игры"\n',
        encoding="utf-8-sig",
    )
    (mod_scripted / "mod.txt").write_text(
        "defined_text = { name = MOD_DYNAMIC "
        "text = { localization_key = MOD_TEXT } }",
        encoding="utf-8",
    )
    (mod_loc / "mod_l_russian.yml").write_text(
        'l_russian:\n MOD_TEXT:0 "текст мода"\n',
        encoding="utf-8-sig",
    )

    mod = ModLocalisation.load(mod_root, base_game_root=base)
    assert "BASE_DYNAMIC" not in mod.definitions

    result = mod.resolve_worst_case(
        "[Root.BASE_DYNAMIC]",
        "russian",
        lambda candidate: (len(candidate),),
    )

    assert result.text == "текст из игры"
    assert "BASE_DYNAMIC" in mod.definitions
    assert result.replacements[0].source == (
        "common/scripted_localisation/base.txt"
    )
