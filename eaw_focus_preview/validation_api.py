from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from . import __version__
from .bmfont import FontRepository
from .dynamic_localisation import ModLocalisation
from .focus_canvas import (
    DESCRIPTION_FORMAL_HEIGHT,
    EFFECT_HEIGHT,
    REWARD_PANEL_Y,
    DESCRIPTION_Y,
    TITLE_RECT,
    FocusCanvas,
    PreviewDiagnostics,
)


PROTOCOL_NAME = "eaw-focus-text-preview/1"
VALID_POLICIES = frozenset({"visual", "strict"})
VALID_PRIORITIES = frozenset({"ru", "en"})


class RequestValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FocusCheckRequest:
    title: str
    description: str
    effect: str
    glyph_priority: str
    language: str
    policy: str
    dynamic_localisation: bool
    show: bool
    request_id: Any = None
    key: Any = None


def _string_field(payload: Mapping[str, Any], name: str, default: str = "") -> str:
    value = payload.get(name, default)
    if not isinstance(value, str):
        raise RequestValidationError(f"Поле {name!r} должно быть строкой")
    return value


def normalize_request(
    payload: Mapping[str, Any],
    *,
    defaults: Mapping[str, Any] | None = None,
) -> FocusCheckRequest:
    if not isinstance(payload, Mapping):
        raise RequestValidationError("Элемент проверки должен быть JSON-объектом")

    defaults = defaults or {}
    priority = payload.get(
        "glyph_priority",
        payload.get(
            "priority",
            defaults.get("glyph_priority", defaults.get("priority", "ru")),
        ),
    )
    if priority not in VALID_PRIORITIES:
        raise RequestValidationError(
            "glyph_priority должен иметь значение 'ru' или 'en'"
        )

    policy = payload.get("policy", defaults.get("policy", "visual"))
    if policy not in VALID_POLICIES:
        raise RequestValidationError(
            "policy должен иметь значение 'visual' или 'strict'"
        )

    show = payload.get("show", defaults.get("show", False))
    if not isinstance(show, bool):
        raise RequestValidationError("Поле 'show' должно быть true или false")

    dynamic_localisation = payload.get(
        "dynamic_localisation",
        defaults.get("dynamic_localisation", False),
    )
    if not isinstance(dynamic_localisation, bool):
        raise RequestValidationError(
            "Поле 'dynamic_localisation' должно быть true или false"
        )

    language = payload.get("language", defaults.get("language", "russian"))
    if not isinstance(language, str) or not language.strip():
        raise RequestValidationError(
            "Поле 'language' должно быть непустой строкой"
        )

    return FocusCheckRequest(
        title=_string_field(payload, "title"),
        description=_string_field(payload, "description"),
        effect=_string_field(payload, "effect"),
        glyph_priority=priority,
        language=language.strip(),
        policy=policy,
        dynamic_localisation=dynamic_localisation,
        show=show,
        request_id=payload.get("id"),
        key=payload.get("key"),
    )


def error_response(
    message: str,
    *,
    code: str = "invalid_request",
    request_id: Any = None,
    key: Any = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "protocol": PROTOCOL_NAME,
        "version": __version__,
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if request_id is not None:
        response["id"] = request_id
    if key is not None:
        response["key"] = key
    return response


def diagnostics_result(
    diagnostics: PreviewDiagnostics,
    request: FocusCheckRequest,
) -> dict[str, Any]:
    status = diagnostics.overall_level
    fits_visual = status != "red"
    fits_strict = status == "green"
    title_overflow = max(0, diagnostics.title_height - int(TITLE_RECT.height()))

    result: dict[str, Any] = {
        "status": status,
        "policy": request.policy,
        "fits": fits_visual if request.policy == "visual" else fits_strict,
        "fits_visual": fits_visual,
        "fits_strict": fits_strict,
        "glyph_priority": request.glyph_priority,
        "language": request.language,
        "title": {
            "lines": diagnostics.title_lines,
            "height_px": diagnostics.title_height,
            "viewport_height_px": int(TITLE_RECT.height()),
            "overflow_px": title_overflow,
            "clipped": title_overflow > 0,
            "included_in_overall_status": False,
        },
        "description": {
            "status": diagnostics.description_level,
            "lines": diagnostics.description_lines,
            "height_px": diagnostics.description_height,
            "formal_max_height_px": DESCRIPTION_FORMAL_HEIGHT,
            "formal_overflow_px": diagnostics.description_formal_overflow,
            "effect_panel_y": REWARD_PANEL_Y,
            "distance_to_effect_panel_px": REWARD_PANEL_Y - DESCRIPTION_Y,
            "panel_overlap_px": diagnostics.description_panel_overlap,
            "intersects_effect_panel": diagnostics.description_panel_overlap > 0,
        },
        "effect": {
            "status": diagnostics.effect_level,
            "lines": diagnostics.effect_lines,
            "height_px": diagnostics.effect_height,
            "viewport_height_px": EFFECT_HEIGHT,
            "overflow_px": diagnostics.effect_overflow,
            "needs_scroll": diagnostics.effect_overflow > 0,
        },
        "missing_glyphs": list(diagnostics.missing_glyphs),
    }
    if request.request_id is not None:
        result["id"] = request.request_id
    if request.key is not None:
        result["key"] = request.key
    return result


class FocusValidationEngine:
    """Проверяет текст тем же FocusCanvas, который используется в GUI."""

    def __init__(
        self,
        repository: FontRepository,
        mod_localisation: ModLocalisation | None = None,
        *,
        default_language: str = "russian",
    ):
        self.mod_localisation = mod_localisation
        self.default_language = default_language
        self.canvas = FocusCanvas(
            repository,
            mod_localisation=mod_localisation,
        )

    def check(self, request: FocusCheckRequest) -> dict[str, Any]:
        if request.dynamic_localisation and self.mod_localisation is None:
            raise RequestValidationError(
                "Для динамической локализации сначала выберите папку мода "
                "в GUI или укажите её в settings.json рядом с программой"
            )
        if (
            request.dynamic_localisation
            and self.mod_localisation is not None
            and not self.mod_localisation.has_language(request.language)
        ):
            raise RequestValidationError(
                f"В выбранном моде нет языка {request.language!r}"
            )
        self.canvas.set_content(
            title=request.title,
            description=request.description,
            effect=request.effect,
            priority=request.glyph_priority,
            language=request.language,
            dynamic_localisation_enabled=request.dynamic_localisation,
        )
        result = diagnostics_result(self.canvas.diagnostics, request)
        result["dynamic_localisation"] = (
            self.canvas.dynamic_localisation_report
        )
        return result

    def check_payload(
        self,
        payload: Mapping[str, Any],
        *,
        defaults: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        effective_defaults = {
            "language": self.default_language,
            **(defaults or {}),
        }
        request = normalize_request(payload, defaults=effective_defaults)
        return self.check(request)

    def process_document(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, list):
            return self._process_batch(payload, {})
        if not isinstance(payload, Mapping):
            return error_response("Корень запроса должен быть объектом или массивом")
        if "items" in payload:
            items = payload["items"]
            if not isinstance(items, list):
                return error_response("Поле 'items' должно быть массивом")
            return self._process_batch(items, payload)

        try:
            result = self.check_payload(payload)
        except RequestValidationError as error:
            return error_response(
                str(error),
                request_id=payload.get("id"),
                key=payload.get("key"),
            )
        return {
            "protocol": PROTOCOL_NAME,
            "version": __version__,
            "ok": True,
            "result": result,
        }

    def _process_batch(
        self,
        items: list[Any],
        defaults: Mapping[str, Any],
    ) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        counts = {"green": 0, "yellow": 0, "red": 0, "errors": 0}
        failed = 0

        for item in items:
            if not isinstance(item, Mapping):
                entries.append(
                    error_response(
                        "Элемент проверки должен быть JSON-объектом",
                    )
                )
                counts["errors"] += 1
                failed += 1
                continue
            try:
                result = self.check_payload(item, defaults=defaults)
            except RequestValidationError as error:
                entries.append(
                    error_response(
                        str(error),
                        request_id=item.get("id"),
                        key=item.get("key"),
                    )
                )
                counts["errors"] += 1
                failed += 1
                continue
            entries.append({"ok": True, "result": result})
            counts[result["status"]] += 1
            if not result["fits"]:
                failed += 1

        return {
            "protocol": PROTOCOL_NAME,
            "version": __version__,
            "ok": counts["errors"] == 0,
            "results": entries,
            "summary": {
                "total": len(items),
                "green": counts["green"],
                "yellow": counts["yellow"],
                "red": counts["red"],
                "errors": counts["errors"],
                "failed_policy": failed,
            },
        }


def response_exit_code(response: Mapping[str, Any]) -> int:
    if not response.get("ok", False):
        return 2
    if "result" in response:
        result = response.get("result")
        if isinstance(result, Mapping) and not result.get("fits", False):
            return 1
        return 0
    summary = response.get("summary")
    if isinstance(summary, Mapping):
        if int(summary.get("errors", 0)) > 0:
            return 2
        return 1 if int(summary.get("failed_policy", 0)) > 0 else 0
    return 2
