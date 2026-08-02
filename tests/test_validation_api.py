from __future__ import annotations

from pathlib import Path

from eaw_focus_preview.bmfont import FontRepository
from eaw_focus_preview.validation_api import (
    FocusValidationEngine,
    response_exit_code,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _engine(qapp) -> FocusValidationEngine:
    del qapp
    return FocusValidationEngine(
        FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    )


def test_single_result_exposes_both_fit_policies(qapp) -> None:
    engine = _engine(qapp)
    payload = {
        "id": 7,
        "key": "yellow_desc",
        "description": "один\nдва\nтри\nчетыре",
        "policy": "visual",
    }
    response = engine.process_document(payload)

    assert response["ok"] is True
    result = response["result"]
    assert result["id"] == 7
    assert result["key"] == "yellow_desc"
    assert result["status"] == "yellow"
    assert result["fits"] is True
    assert result["fits_visual"] is True
    assert result["fits_strict"] is False
    assert result["description"]["lines"] == 4
    assert result["description"]["formal_overflow_px"] == 2
    assert result["description"]["intersects_effect_panel"] is False
    assert response_exit_code(response) == 0

    strict = engine.process_document({**payload, "policy": "strict"})
    assert strict["result"]["fits"] is False
    assert response_exit_code(strict) == 1


def test_red_description_and_effect_are_machine_readable(qapp) -> None:
    engine = _engine(qapp)
    response = engine.process_document(
        {
            "description": "\n".join(str(index) for index in range(7)),
            "effect": "\n".join(str(index) for index in range(10)),
        }
    )

    result = response["result"]
    assert result["status"] == "red"
    assert result["fits"] is False
    assert result["description"]["panel_overlap_px"] > 0
    assert result["description"]["intersects_effect_panel"] is True
    assert result["effect"]["overflow_px"] > 0
    assert result["effect"]["needs_scroll"] is True
    assert response_exit_code(response) == 1


def test_dynamic_localisation_is_off_and_requires_a_mod_when_enabled(
    qapp,
) -> None:
    engine = _engine(qapp)

    disabled = engine.process_document(
        {"description": "[Root.GetName]"}
    )
    assert disabled["ok"] is True
    assert disabled["result"]["dynamic_localisation"]["enabled"] is False

    enabled = engine.process_document(
        {
            "description": "[Root.GetName]",
            "dynamic_localisation": True,
        }
    )
    assert enabled["ok"] is False
    assert "папку мода" in enabled["error"]["message"]

    invalid = engine.process_document(
        {"dynamic_localisation": "yes"}
    )
    assert invalid["ok"] is False
    assert "true или false" in invalid["error"]["message"]


def test_batch_preserves_keys_and_reports_summary(qapp) -> None:
    engine = _engine(qapp)
    response = engine.process_document(
        {
            "policy": "strict",
            "glyph_priority": "ru",
            "items": [
                {"key": "short", "description": "Коротко."},
                {
                    "key": "long",
                    "description": "\n".join(
                        str(index) for index in range(7)
                    ),
                },
            ],
        }
    )

    assert response["ok"] is True
    assert response["summary"] == {
        "total": 2,
        "green": 1,
        "yellow": 0,
        "red": 1,
        "errors": 0,
        "failed_policy": 1,
    }
    assert response["results"][0]["result"]["key"] == "short"
    assert response["results"][1]["result"]["key"] == "long"
    assert response_exit_code(response) == 1
