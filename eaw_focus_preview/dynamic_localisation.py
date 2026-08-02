from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path
import re
from typing import Callable, Iterable, TypeAlias

from .automatic_localisation import AutomaticLocalisationCatalog


DYNAMIC_LOCALISATION_WARNING = (
    "Экспериментальная функция: динамическая локализация очень нестабильна "
    "и может заметно увеличить нагрузку на компьютер."
)
from .file_loader import parse_localisation_value_line, read_text_file


MAX_VARIANTS_PER_DEFINITION = 256
MAX_COMBINATIONS = 4096
MAX_RECURSION_DEPTH = 12
MAX_REPORTED_VARIANTS = 64

_DYNAMIC_TOKEN_RE = re.compile(r"\[([^\[\]\r\n]+)\]")
_LANGUAGE_HEADER_RE = re.compile(r"^\s*l_([A-Za-z0-9_]+)\s*:\s*$")
_STATIC_REFERENCE_RE = re.compile(
    r"\$([A-Za-z0-9_.-]+)(?:\|[^$]+)?\$"
)

ClausewitzValue: TypeAlias = str | list[tuple[str, "ClausewitzValue"]]
Score: TypeAlias = tuple[float | int, ...]


class ModLocalisationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DynamicReplacement:
    token: str
    name: str
    selected: str
    variants: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DynamicResolution:
    source_text: str
    text: str
    replacements: tuple[DynamicReplacement, ...] = ()
    unresolved_tokens: tuple[str, ...] = ()
    combinations_evaluated: int = 0
    truncated: bool = False

    def as_dict(self) -> dict[str, object]:
        def replacement_dict(
            replacement: DynamicReplacement,
        ) -> dict[str, object]:
            reported = list(
                replacement.variants[:MAX_REPORTED_VARIANTS]
            )
            if replacement.selected not in reported and reported:
                reported[-1] = replacement.selected
            return {
                "token": replacement.token,
                "name": replacement.name,
                "selected": replacement.selected,
                "variants": reported,
                "variant_count": len(replacement.variants),
                "variants_truncated": len(reported) < len(replacement.variants),
            }

        return {
            "source_text": self.source_text,
            "resolved_text": self.text,
            "replacements": [
                replacement_dict(replacement)
                for replacement in self.replacements
            ],
            "unresolved_tokens": list(self.unresolved_tokens),
            "combinations_evaluated": self.combinations_evaluated,
            "truncated": self.truncated,
        }


def _tokenize_clausewitz(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character.isspace():
            index += 1
            continue
        if character == "#":
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline + 1
            continue
        if character in "{}=":
            tokens.append(character)
            index += 1
            continue
        if character == '"':
            index += 1
            value: list[str] = []
            while index < len(text):
                current = text[index]
                if current == "\\" and index + 1 < len(text):
                    following = text[index + 1]
                    if following in {'"', "\\"}:
                        value.append(following)
                        index += 2
                        continue
                if current == '"':
                    index += 1
                    break
                value.append(current)
                index += 1
            tokens.append("".join(value))
            continue

        end = index
        while (
            end < len(text)
            and not text[end].isspace()
            and text[end] not in '{}="#'
        ):
            end += 1
        if end == index:
            index += 1
            continue
        tokens.append(text[index:end])
        index = end
    return tokens


def _parse_clausewitz_entries(
    tokens: list[str],
    index: int = 0,
    *,
    nested: bool = False,
) -> tuple[list[tuple[str, ClausewitzValue]], int]:
    entries: list[tuple[str, ClausewitzValue]] = []
    while index < len(tokens):
        if tokens[index] == "}":
            return entries, index + 1
        key = tokens[index]
        index += 1
        if index >= len(tokens) or tokens[index] != "=":
            continue
        index += 1
        if index >= len(tokens):
            entries.append((key, ""))
            break
        if tokens[index] == "{":
            value, index = _parse_clausewitz_entries(
                tokens,
                index + 1,
                nested=True,
            )
            entries.append((key, value))
        else:
            entries.append((key, tokens[index]))
            index += 1
    if nested:
        return entries, index
    return entries, index


def parse_scripted_localisation(
    text: str,
) -> dict[str, tuple[str, ...]]:
    tokens = _tokenize_clausewitz(text)
    entries, _ = _parse_clausewitz_entries(tokens)
    definitions: dict[str, list[str]] = {}

    for key, value in entries:
        if key != "defined_text" or not isinstance(value, list):
            continue
        names = [
            entry_value
            for entry_key, entry_value in value
            if entry_key == "name" and isinstance(entry_value, str)
        ]
        if not names:
            continue
        name = names[0]
        keys: list[str] = []
        for entry_key, entry_value in value:
            if entry_key != "text" or not isinstance(entry_value, list):
                continue
            keys.extend(_recursive_scalar_values(entry_value, "localization_key"))
        definitions.setdefault(name, []).extend(keys)

    return {
        name: tuple(dict.fromkeys(keys))
        for name, keys in definitions.items()
    }


def _recursive_scalar_values(
    entries: list[tuple[str, ClausewitzValue]],
    wanted_key: str,
) -> list[str]:
    result: list[str] = []
    for key, value in entries:
        if key == wanted_key and isinstance(value, str):
            result.append(value)
        elif isinstance(value, list):
            result.extend(_recursive_scalar_values(value, wanted_key))
    return result


def parse_localisation_text(
    text: str,
) -> dict[str, dict[str, str]]:
    languages: dict[str, dict[str, str]] = {}
    current_language: str | None = None
    for line in text.splitlines():
        language_match = _LANGUAGE_HEADER_RE.match(line)
        if language_match:
            current_language = language_match.group(1).casefold()
            languages.setdefault(current_language, {})
            continue
        if current_language is None:
            continue
        parsed = parse_localisation_value_line(line)
        if parsed is not None:
            key, value = parsed
            languages[current_language][key] = value
    return languages


def validate_mod_directory(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    scripted = resolved / "common" / "scripted_localisation"
    localisation = resolved / "localisation"
    if not resolved.is_dir():
        raise ModLocalisationError(f"Папка мода не найдена: {resolved}")
    if not scripted.is_dir():
        raise ModLocalisationError(
            "В папке мода отсутствует common/scripted_localisation"
        )
    if not localisation.is_dir():
        raise ModLocalisationError(
            "В папке мода отсутствует localisation"
        )
    return resolved


class ModLocalisation:
    def __init__(
        self,
        root: Path,
        definitions: dict[str, tuple[str, ...]],
        localisations: dict[str, dict[str, str]],
        automatic_catalog: AutomaticLocalisationCatalog,
    ):
        self.root = root
        self.definitions = definitions
        self.localisations = localisations
        self.automatic_catalog = automatic_catalog
        self._definition_names = {
            name.casefold(): name for name in self.definitions
        }
        self._localisation_names = {
            language: {
                key.casefold(): key for key in values
            }
            for language, values in self.localisations.items()
        }
        self._variant_cache: dict[tuple[str, str], tuple[str, ...]] = {}
        self._automatic_variant_cache: dict[
            tuple[str, str], tuple[str, tuple[str, ...]] | None
        ] = {}
        self._automatic_resolving: set[tuple[str, str]] = set()

    @classmethod
    def load(cls, root: Path) -> "ModLocalisation":
        resolved = validate_mod_directory(root)
        definitions: dict[str, list[str]] = {}
        scripted_directory = resolved / "common" / "scripted_localisation"
        for path in sorted(scripted_directory.rglob("*.txt")):
            parsed = parse_scripted_localisation(read_text_file(path))
            for name, keys in parsed.items():
                definitions.setdefault(name, []).extend(keys)

        localisations: dict[str, dict[str, str]] = {}
        localisation_directory = resolved / "localisation"
        paths = sorted(
            localisation_directory.rglob("*.yml"),
            key=lambda path: (
                "replace" in {
                    part.casefold() for part in path.relative_to(
                        localisation_directory
                    ).parts
                },
                str(path).casefold(),
            ),
        )
        paths.extend(
            sorted(
                localisation_directory.rglob("*.yaml"),
                key=lambda path: str(path).casefold(),
            )
        )
        for path in paths:
            parsed = parse_localisation_text(read_text_file(path))
            for language, values in parsed.items():
                localisations.setdefault(language, {}).update(values)

        if not definitions:
            raise ModLocalisationError(
                "В common/scripted_localisation не найдено ни одного defined_text"
            )
        if not localisations:
            raise ModLocalisationError(
                "В localisation не найдено локализационных значений"
            )
        automatic_catalog = AutomaticLocalisationCatalog.load(
            resolved,
            localisations,
        )
        return cls(
            resolved,
            {
                name: tuple(dict.fromkeys(keys))
                for name, keys in definitions.items()
            },
            localisations,
            automatic_catalog,
        )

    @property
    def available_languages(self) -> tuple[str, ...]:
        preferred = ("russian", "english")
        languages = sorted(self.localisations)
        return tuple(
            language for language in preferred if language in languages
        ) + tuple(
            language for language in languages if language not in preferred
        )

    def has_language(self, language: str) -> bool:
        return self.normalize_language(language) in self.localisations

    @staticmethod
    def normalize_language(language: str) -> str:
        folded = language.strip().casefold()
        return folded[2:] if folded.startswith("l_") else folded

    def _definition_name(self, token_content: str) -> str | None:
        stripped = token_content.strip()
        if not stripped or stripped.startswith("?"):
            return None
        candidates = [stripped]
        if "." in stripped:
            candidates.append(stripped.rsplit(".", 1)[-1])
        for candidate in candidates:
            exact = self._definition_names.get(candidate.casefold())
            if exact is not None:
                return exact
        return None

    def _localisation_value(self, language: str, key: str) -> str:
        values = self.localisations[language]
        actual_key = self._localisation_names[language].get(key.casefold())
        if actual_key is None:
            return key
        return values[actual_key]

    def _expand_static_references(
        self,
        text: str,
        language: str,
        stack: tuple[str, ...],
    ) -> str:
        if len(stack) >= MAX_RECURSION_DEPTH:
            return text

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            folded = key.casefold()
            if folded in stack:
                return match.group(0)
            value = self._localisation_value(language, key)
            if value == key:
                return match.group(0)
            return self._expand_static_references(
                value,
                language,
                (*stack, folded),
            )

        return _STATIC_REFERENCE_RE.sub(replace, text)

    def variants_for(
        self,
        name: str,
        language: str,
        *,
        _stack: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        normalized_language = self.normalize_language(language)
        if normalized_language not in self.localisations:
            raise ModLocalisationError(
                f"В моде нет локализации языка {language!r}"
            )
        actual_name = self._definition_names.get(name.casefold())
        if actual_name is None:
            return ()
        folded_name = actual_name.casefold()
        if folded_name in _stack or len(_stack) >= MAX_RECURSION_DEPTH:
            return ()
        cache_key = (normalized_language, actual_name)
        if not _stack and cache_key in self._variant_cache:
            return self._variant_cache[cache_key]

        variants: list[str] = []
        for localisation_key in self.definitions[actual_name]:
            value = self._localisation_value(
                normalized_language,
                localisation_key,
            )
            value = self._expand_static_references(
                value,
                normalized_language,
                (),
            )
            variants.extend(
                self._expand_nested_dynamic(
                    value,
                    normalized_language,
                    (*_stack, folded_name),
                )
            )
            if len(variants) >= MAX_VARIANTS_PER_DEFINITION:
                break

        result = tuple(dict.fromkeys(variants))[:MAX_VARIANTS_PER_DEFINITION]
        if not _stack:
            self._variant_cache[cache_key] = result
        return result

    def _expand_nested_dynamic(
        self,
        text: str,
        language: str,
        stack: tuple[str, ...],
    ) -> tuple[str, ...]:
        if len(stack) >= MAX_RECURSION_DEPTH:
            return (text,)
        groups = self._token_choices(text, language, stack=stack)
        if not groups:
            return (text,)

        combinations = 1
        selected_groups: list[
            tuple[str, tuple[str, ...], tuple[str, ...]]
        ] = []
        for group in groups:
            selected_groups.append(group)
            variants = group[2]
            combinations *= len(variants)
            if combinations > MAX_VARIANTS_PER_DEFINITION:
                break
        if not selected_groups:
            return (text,)

        output: list[str] = []
        for selected in product(*(group[2] for group in selected_groups)):
            candidate = text
            for (_, tokens, _), value in zip(selected_groups, selected):
                for token in tokens:
                    candidate = candidate.replace(token, value)
            output.append(candidate)
            if len(output) >= MAX_VARIANTS_PER_DEFINITION:
                break
        return tuple(dict.fromkeys(output))

    def _automatic_variants_for(
        self,
        token_content: str,
        language: str,
    ) -> tuple[str, tuple[str, ...]] | None:
        cache_key = (language, token_content.casefold())
        if cache_key in self._automatic_variant_cache:
            return self._automatic_variant_cache[cache_key]
        if cache_key in self._automatic_resolving:
            return None
        automatic = self.automatic_catalog.variants_for(
            token_content,
            language,
        )
        if automatic is None or not automatic.values:
            self._automatic_variant_cache[cache_key] = None
            return None

        self._automatic_resolving.add(cache_key)
        try:
            expanded: list[str] = []
            for raw_value in automatic.values:
                value = self._expand_static_references(raw_value, language, ())
                expanded.extend(
                    self._expand_nested_dynamic(value, language, ())
                )
            result = (automatic.name, tuple(dict.fromkeys(expanded)))
        finally:
            self._automatic_resolving.discard(cache_key)
        self._automatic_variant_cache[cache_key] = result
        return result

    def _token_choices(
        self,
        text: str,
        language: str,
        *,
        stack: tuple[str, ...] = (),
    ) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
        choices: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
        seen_literals: set[str] = set()
        for match in _DYNAMIC_TOKEN_RE.finditer(text):
            literal = match.group(0)
            if literal in seen_literals:
                continue
            seen_literals.add(literal)
            content = match.group(1)
            name = self._definition_name(content)
            if name is not None and name.casefold() not in stack:
                variants = self.variants_for(name, language, _stack=stack)
                if variants:
                    choices.append((name, (literal,), variants))
                continue
            automatic = self._automatic_variants_for(content, language)
            if automatic is not None:
                automatic_name, variants = automatic
                if variants:
                    choices.append((automatic_name, (literal,), variants))
        return choices

    def resolve_worst_case(
        self,
        text: str,
        language: str,
        score: Callable[[str], Score],
    ) -> DynamicResolution:
        normalized_language = self.normalize_language(language)
        if normalized_language not in self.localisations:
            raise ModLocalisationError(
                f"В моде нет локализации языка {language!r}"
            )
        choices = self._token_choices(text, normalized_language)

        combinations = 1
        for _, _, variants in choices:
            combinations *= len(variants)
        evaluated = 0
        truncated = combinations > MAX_COMBINATIONS
        selected_values: tuple[str, ...] = ()
        resolved_text = text

        if choices and not truncated:
            best_key: tuple[Score, str] | None = None
            for selected in product(*(choice[2] for choice in choices)):
                candidate = _replace_selected(text, choices, selected)
                key = (score(candidate), candidate)
                evaluated += 1
                if best_key is None or key > best_key:
                    best_key = key
                    resolved_text = candidate
                    selected_values = tuple(selected)
        elif choices:
            current = text
            selected: list[str] = []
            for choice in choices:
                best_value = max(
                    choice[2],
                    key=lambda value: (
                        score(_replace_one_group(current, choice, value)),
                        value,
                    ),
                )
                evaluated += len(choice[2])
                current = _replace_one_group(current, choice, best_value)
                selected.append(best_value)
            resolved_text = current
            selected_values = tuple(selected)

        replacements: list[DynamicReplacement] = []
        for (name, tokens, variants), selected in zip(
            choices,
            selected_values,
        ):
            for token in tokens:
                replacements.append(
                    DynamicReplacement(
                        token=token,
                        name=name,
                        selected=selected,
                        variants=variants,
                    )
                )

        unresolved = tuple(
            dict.fromkeys(
                match.group(0)
                for match in _DYNAMIC_TOKEN_RE.finditer(resolved_text)
            )
        )
        return DynamicResolution(
            source_text=text,
            text=resolved_text,
            replacements=tuple(replacements),
            unresolved_tokens=unresolved,
            combinations_evaluated=evaluated,
            truncated=truncated,
        )


def _replace_selected(
    text: str,
    choices: Iterable[tuple[str, tuple[str, ...], tuple[str, ...]]],
    selected: Iterable[str],
) -> str:
    result = text
    for choice, value in zip(choices, selected):
        result = _replace_one_group(result, choice, value)
    return result


def _replace_one_group(
    text: str,
    choice: tuple[str, tuple[str, ...], tuple[str, ...]],
    value: str,
) -> str:
    result = text
    for token in choice[1]:
        result = result.replace(token, value)
    return result
