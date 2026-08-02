from __future__ import annotations

from pathlib import Path

from eaw_focus_preview.bmfont import FontRepository
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
