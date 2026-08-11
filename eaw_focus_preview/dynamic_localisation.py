from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from pathlib import Path
import re
from typing import Callable, Iterable, TypeAlias

from .automatic_localisation import AutomaticLocalisationCatalog
from .clausewitz_interpreter import (
    ClausewitzBlock,
    ConditionExpression,
    TRUE_EXPRESSION,
    child_blocks,
    condition_and,
    condition_from_trigger,
    condition_not,
    conditions_satisfiable,
    describe_condition,
    expression_predicates,
    parse_clausewitz,
    scalar_values,
)


DYNAMIC_LOCALISATION_WARNING = (
    "Экспериментальная функция: динамическая локализация очень нестабильна "
    "и может заметно увеличить нагрузку на компьютер."
)
from .file_loader import parse_localisation_value_line, read_text_file


MAX_VARIANTS_PER_DEFINITION = 256
MAX_COMBINATIONS = 4096
MAX_RECURSION_DEPTH = 30
MAX_REPORTED_VARIANTS = 64
SUPPORTED_LOCALISATION_LANGUAGES = frozenset({"russian", "english"})

_DYNAMIC_TOKEN_RE = re.compile(r"\[([^\[\]\r\n]+)\]")
_LANGUAGE_HEADER_RE = re.compile(r"^\s*l_([A-Za-z0-9_]+)\s*:\s*$")
_STATIC_REFERENCE_RE = re.compile(
    r"\$([A-Za-z0-9_.-]+)(?:\|[^$]+)?\$"
)
_SCRIPTED_NAME_RE = re.compile(
    r'(?i)\bname\s*=\s*(?:"([^"\r\n]+)"|([^\s#}]+))'
)

Score: TypeAlias = tuple[float | int, ...]


class ModLocalisationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DynamicReplacement:
    token: str
    name: str
    selected: str
    variants: tuple[str, ...]
    localisation_key: str | None = None
    source: str | None = None
    condition: str | None = None
    condition_exact: bool = False


@dataclass(frozen=True, slots=True)
class DynamicResolution:
    source_text: str
    text: str
    replacements: tuple[DynamicReplacement, ...] = ()
    unresolved_tokens: tuple[str, ...] = ()
    combinations_evaluated: int = 0
    truncated: bool = False
    incompatible_combinations: int = 0
    symbolic_checks: int = 0
    confidence: str = "exact"

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
                "localisation_key": replacement.localisation_key,
                "source": replacement.source,
                "condition": replacement.condition,
                "condition_exact": replacement.condition_exact,
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
            "incompatible_combinations": self.incompatible_combinations,
            "symbolic_checks": self.symbolic_checks,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class ScriptedLocalisationBranch:
    localisation_key: str
    trigger: ClausewitzBlock | None
    source: str | None
    ordinal: int


@dataclass(frozen=True, slots=True)
class ScriptedLocalisationDefinition:
    name: str
    branches: tuple[ScriptedLocalisationBranch, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedVariant:
    text: str
    condition: ConditionExpression = TRUE_EXPRESSION
    localisation_key: str | None = None
    source: str | None = None
    condition_description: str | None = None
    condition_exact: bool = False


@dataclass(frozen=True, slots=True)
class _DynamicChoice:
    name: str
    tokens: tuple[str, ...]
    variants: tuple[_ResolvedVariant, ...]


def _recursive_scalar_values(
    block: ClausewitzBlock,
    wanted_key: str,
) -> list[str]:
    result: list[str] = []
    folded = wanted_key.casefold()
    for entry in block:
        if entry.key.casefold() == folded and isinstance(entry.value, str):
            result.append(entry.value)
        elif isinstance(entry.value, tuple):
            result.extend(_recursive_scalar_values(entry.value, wanted_key))
    return result


def parse_scripted_localisation_definitions(
    text: str,
    *,
    source: str | None = None,
) -> dict[str, ScriptedLocalisationDefinition]:
    parsed = parse_clausewitz(text)
    collected: dict[str, list[ScriptedLocalisationBranch]] = {}
    for definition_block in child_blocks(parsed, "defined_text"):
        names = scalar_values(definition_block, "name")
        if not names:
            continue
        name = names[0]
        output = collected.setdefault(name, [])
        for text_block in child_blocks(definition_block, "text"):
            trigger_blocks = child_blocks(text_block, "trigger")
            trigger = (
                tuple(
                    entry
                    for trigger_block in trigger_blocks
                    for entry in trigger_block
                )
                if trigger_blocks
                else None
            )
            for localisation_key in _recursive_scalar_values(
                text_block,
                "localization_key",
            ):
                output.append(
                    ScriptedLocalisationBranch(
                        localisation_key=localisation_key,
                        trigger=trigger,
                        source=source,
                        ordinal=len(output),
                    )
                )
    return {
        name: ScriptedLocalisationDefinition(name, tuple(branches))
        for name, branches in collected.items()
    }


def parse_scripted_localisation(
    text: str,
) -> dict[str, tuple[str, ...]]:
    return {
        name: tuple(
            dict.fromkeys(
                branch.localisation_key for branch in definition.branches
            )
        )
        for name, definition in parse_scripted_localisation_definitions(
            text
        ).items()
    }


def parse_localisation_text(
    text: str,
    *,
    wanted_languages: frozenset[str] | None = None,
) -> dict[str, dict[str, str]]:
    languages: dict[str, dict[str, str]] = {}
    current_language: str | None = None
    for line in text.splitlines():
        language_match = _LANGUAGE_HEADER_RE.match(line)
        if language_match:
            language = language_match.group(1).casefold()
            current_language = (
                language
                if wanted_languages is None or language in wanted_languages
                else None
            )
            if current_language is not None:
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


def _load_scripted_definition_layer(
    root: Path,
) -> dict[str, ScriptedLocalisationDefinition]:
    directory = root / "common" / "scripted_localisation"
    collected: dict[str, list[ScriptedLocalisationBranch]] = {}
    if not directory.is_dir():
        return {}
    for path in sorted(directory.rglob("*.txt")):
        try:
            source = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            source = str(path)
        parsed = parse_scripted_localisation_definitions(
            read_text_file(path),
            source=source,
        )
        for name, definition in parsed.items():
            collected.setdefault(name, []).extend(definition.branches)
    return {
        name: ScriptedLocalisationDefinition(
            name,
            tuple(
                ScriptedLocalisationBranch(
                    branch.localisation_key,
                    branch.trigger,
                    branch.source,
                    ordinal,
                )
                for ordinal, branch in enumerate(branches)
            ),
        )
        for name, branches in collected.items()
    }


def _index_scripted_definition_paths(root: Path) -> dict[str, tuple[Path, ...]]:
    directory = root / "common" / "scripted_localisation"
    if not directory.is_dir():
        return {}
    indexed: dict[str, list[Path]] = {}
    for path in sorted(directory.rglob("*.txt")):
        text = read_text_file(path)
        for match in _SCRIPTED_NAME_RE.finditer(text):
            name = match.group(1) or match.group(2)
            paths = indexed.setdefault(name.casefold(), [])
            if path not in paths:
                paths.append(path)
    return {name: tuple(paths) for name, paths in indexed.items()}


def _localisation_paths(root: Path) -> list[Path]:
    directory = root / "localisation"
    if not directory.is_dir():
        return []
    paths = sorted(
        directory.rglob("*.yml"),
        key=lambda path: (
            "replace" in {
                part.casefold() for part in path.relative_to(directory).parts
            },
            str(path).casefold(),
        ),
    )
    paths.extend(
        sorted(directory.rglob("*.yaml"), key=lambda path: str(path).casefold())
    )
    return paths


def _load_localisations(
    root: Path,
    *,
    wanted_languages: frozenset[str] | None = None,
) -> dict[str, dict[str, str]]:
    localisations: dict[str, dict[str, str]] = {}
    for path in _localisation_paths(root):
        parsed = parse_localisation_text(
            read_text_file(path),
            wanted_languages=wanted_languages,
        )
        for language, values in parsed.items():
            localisations.setdefault(language, {}).update(values)
    return localisations


class ModLocalisation:
    def __init__(
        self,
        root: Path,
        definitions: dict[str, tuple[str, ...]],
        localisations: dict[str, dict[str, str]],
        automatic_catalog: AutomaticLocalisationCatalog,
        *,
        structured_definitions: dict[
            str, ScriptedLocalisationDefinition
        ] | None = None,
        base_game_root: Path | None = None,
        base_definition_sources: dict[str, tuple[Path, ...]] | None = None,
    ):
        self.root = root
        self.definitions = definitions
        self.structured_definitions = structured_definitions or {
            name: ScriptedLocalisationDefinition(
                name,
                tuple(
                    ScriptedLocalisationBranch(key, None, None, ordinal)
                    for ordinal, key in enumerate(keys)
                ),
            )
            for name, keys in definitions.items()
        }
        self.base_game_root = base_game_root
        self._base_definition_sources = base_definition_sources or {}
        self._missing_base_definitions: set[str] = set()
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
        self._resolved_variant_cache: dict[
            tuple[str, str, str], tuple[_ResolvedVariant, ...]
        ] = {}
        self._automatic_variant_cache: dict[
            tuple[str, str, str],
            tuple[str, tuple[_ResolvedVariant, ...]] | None,
        ] = {}
        self._automatic_resolving: set[tuple[str, str, str]] = set()

    @classmethod
    def load(
        cls,
        root: Path,
        *,
        base_game_root: Path | None = None,
    ) -> "ModLocalisation":
        resolved = validate_mod_directory(root)
        resolved_base = None
        if base_game_root is not None:
            candidate = base_game_root.expanduser().resolve()
            if candidate != resolved and candidate.is_dir():
                resolved_base = candidate

        # Vanilla definitions are indexed cheaply and parsed on first use.
        # Mod definitions are authoritative when a name exists in both layers.
        structured_definitions = _load_scripted_definition_layer(resolved)
        base_definition_sources = (
            _index_scripted_definition_paths(resolved_base)
            if resolved_base is not None
            else {}
        )
        definitions = {
            name: tuple(
                dict.fromkeys(
                    branch.localisation_key for branch in definition.branches
                )
            )
            for name, definition in structured_definitions.items()
        }

        mod_localisations = _load_localisations(
            resolved,
            wanted_languages=SUPPORTED_LOCALISATION_LANGUAGES,
        )
        if resolved_base is not None:
            localisations = _load_localisations(
                resolved_base,
                wanted_languages=frozenset(mod_localisations),
            )
            for language, values in mod_localisations.items():
                localisations.setdefault(language, {}).update(values)
        else:
            localisations = mod_localisations

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
            source_roots=tuple(
                root
                for root in (resolved_base, resolved)
                if root is not None
            ),
        )
        return cls(
            resolved,
            definitions,
            localisations,
            automatic_catalog,
            structured_definitions=structured_definitions,
            base_game_root=resolved_base,
            base_definition_sources=base_definition_sources,
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
            if exact is None:
                self._load_base_definition(candidate)
                exact = self._definition_names.get(candidate.casefold())
            if exact is not None:
                return exact
        return None

    def _load_base_definition(self, requested_name: str) -> None:
        folded = requested_name.casefold()
        if (
            folded in self._missing_base_definitions
            or folded in self._definition_names
        ):
            return
        paths = self._base_definition_sources.get(folded, ())
        branches: list[ScriptedLocalisationBranch] = []
        actual_name: str | None = None
        for path in paths:
            assert self.base_game_root is not None
            try:
                source = str(path.relative_to(self.base_game_root)).replace(
                    "\\", "/"
                )
            except ValueError:
                source = str(path)
            parsed = parse_scripted_localisation_definitions(
                read_text_file(path),
                source=source,
            )
            for name, definition in parsed.items():
                if name.casefold() == folded:
                    actual_name = name
                    branches.extend(definition.branches)
        if actual_name is None or not branches:
            self._missing_base_definitions.add(folded)
            return
        definition = ScriptedLocalisationDefinition(
            actual_name,
            tuple(
                ScriptedLocalisationBranch(
                    branch.localisation_key,
                    branch.trigger,
                    branch.source,
                    ordinal,
                )
                for ordinal, branch in enumerate(branches)
            ),
        )
        self.structured_definitions[actual_name] = definition
        self.definitions[actual_name] = tuple(
            dict.fromkeys(
                branch.localisation_key for branch in definition.branches
            )
        )
        self._definition_names[folded] = actual_name

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
        cache_key = (normalized_language, name)
        if not _stack and cache_key in self._variant_cache:
            return self._variant_cache[cache_key]
        resolved = self._resolved_variants_for(
            name,
            normalized_language,
            root_scope="root",
            stack=_stack,
        )
        result = tuple(dict.fromkeys(variant.text for variant in resolved))
        if not _stack:
            self._variant_cache[cache_key] = result
        return result

    @staticmethod
    def _reference_scope(
        token_content: str,
        current_root_scope: str,
    ) -> str:
        parts = [part for part in token_content.strip().split(".") if part]
        prefix = parts[:-1]
        if not prefix:
            return current_root_scope
        first = prefix[0]
        folded = first.casefold()
        if folded in {"root", "this"}:
            scope = current_root_scope
        elif len(first) == 3 and first.isalnum() and first.upper() == first:
            scope = f"country:{first}"
        else:
            scope = f"scope:{folded}"
        for component in prefix[1:]:
            scope += f".{component.casefold()}"
        return scope

    def _selection_condition(
        self,
        definition: ScriptedLocalisationDefinition,
        branch: ScriptedLocalisationBranch,
        root_scope: str,
    ) -> ConditionExpression:
        current = condition_from_trigger(
            branch.trigger,
            root_scope=root_scope,
        )
        earlier = tuple(
            condition_from_trigger(
                previous.trigger,
                root_scope=root_scope,
            )
            for previous in definition.branches[: branch.ordinal]
        )
        return condition_and(
            (current, *(condition_not(expression) for expression in earlier))
        )

    def _resolved_variants_for(
        self,
        name: str,
        language: str,
        *,
        root_scope: str,
        stack: tuple[str, ...] = (),
    ) -> tuple[_ResolvedVariant, ...]:
        actual_name = self._definition_names.get(name.casefold())
        if actual_name is None:
            return ()
        folded_name = actual_name.casefold()
        if folded_name in stack or len(stack) >= MAX_RECURSION_DEPTH:
            return ()
        cache_key = (language, actual_name, root_scope)
        if cache_key in self._resolved_variant_cache:
            return self._resolved_variant_cache[cache_key]

        definition = self.structured_definitions[actual_name]
        variants: list[_ResolvedVariant] = []
        seen: set[tuple[str, ConditionExpression]] = set()
        for branch in definition.branches:
            branch_condition = self._selection_condition(
                definition,
                branch,
                root_scope,
            )
            branch_sat = conditions_satisfiable((branch_condition,))
            if not branch_sat.possible and not branch_sat.truncated:
                continue
            value = self._localisation_value(
                language,
                branch.localisation_key,
            )
            value = self._expand_static_references(value, language, ())
            nested_variants = self._expand_nested_dynamic(
                value,
                language,
                (*stack, folded_name),
                root_scope=root_scope,
            )
            branch_description = (
                "fallback"
                if branch.trigger is None
                else describe_condition(
                    condition_from_trigger(
                        branch.trigger,
                        root_scope=root_scope,
                    )
                )
            )
            for nested in nested_variants:
                combined = condition_and(
                    (branch_condition, nested.condition)
                )
                combined_sat = conditions_satisfiable((combined,))
                if not combined_sat.possible and not combined_sat.truncated:
                    continue
                item = _ResolvedVariant(
                    text=nested.text,
                    condition=combined,
                    localisation_key=branch.localisation_key,
                    source=branch.source,
                    condition_description=branch_description,
                    condition_exact=(
                        branch_sat.exact
                        and nested.condition_exact
                        and combined_sat.exact
                    ),
                )
                identity = (item.text, item.condition)
                if identity in seen:
                    continue
                seen.add(identity)
                variants.append(item)
                if len(variants) >= MAX_VARIANTS_PER_DEFINITION:
                    break
            if len(variants) >= MAX_VARIANTS_PER_DEFINITION:
                break

        result = tuple(variants)
        self._resolved_variant_cache[cache_key] = result
        return result

    def _expand_nested_dynamic(
        self,
        text: str,
        language: str,
        stack: tuple[str, ...],
        *,
        root_scope: str,
    ) -> tuple[_ResolvedVariant, ...]:
        if len(stack) >= MAX_RECURSION_DEPTH:
            return (_ResolvedVariant(text, condition_exact=False),)
        groups = self._token_choices(
            text,
            language,
            stack=stack,
            root_scope=root_scope,
        )
        if not groups:
            return (_ResolvedVariant(text, condition_exact=True),)

        states = (_ResolvedVariant(text, condition_exact=True),)
        for group in groups:
            expanded: list[_ResolvedVariant] = []
            seen: set[tuple[str, ConditionExpression]] = set()
            for state in states:
                for variant in group.variants:
                    condition = condition_and(
                        (state.condition, variant.condition)
                    )
                    sat = conditions_satisfiable((condition,))
                    if not sat.possible and not sat.truncated:
                        continue
                    candidate = state.text
                    for token in group.tokens:
                        candidate = candidate.replace(token, variant.text)
                    identity = (candidate, condition)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    expanded.append(
                        _ResolvedVariant(
                            candidate,
                            condition,
                            condition_exact=(
                                state.condition_exact
                                and variant.condition_exact
                                and sat.exact
                            ),
                        )
                    )
                    if len(expanded) >= MAX_VARIANTS_PER_DEFINITION:
                        break
                if len(expanded) >= MAX_VARIANTS_PER_DEFINITION:
                    break
            states = tuple(expanded)
            if not states:
                break
        return states or (_ResolvedVariant(text, condition_exact=False),)

    def _automatic_variants_for(
        self,
        token_content: str,
        language: str,
        *,
        root_scope: str,
    ) -> tuple[str, tuple[_ResolvedVariant, ...]] | None:
        cache_key = (language, token_content.casefold(), root_scope)
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
            expanded: list[_ResolvedVariant] = []
            for raw_value in automatic.values:
                value = self._expand_static_references(raw_value, language, ())
                expanded.extend(
                    self._expand_nested_dynamic(
                        value,
                        language,
                        (),
                        root_scope=root_scope,
                    )
                )
            unique: list[_ResolvedVariant] = []
            seen: set[tuple[str, ConditionExpression]] = set()
            for item in expanded:
                identity = (item.text, item.condition)
                if identity not in seen:
                    seen.add(identity)
                    unique.append(
                        _ResolvedVariant(
                            item.text,
                            item.condition,
                            condition_exact=False,
                        )
                    )
            result = (automatic.name, tuple(unique))
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
        root_scope: str = "root",
    ) -> list[_DynamicChoice]:
        choices: list[_DynamicChoice] = []
        seen_literals: set[str] = set()
        for match in _DYNAMIC_TOKEN_RE.finditer(text):
            literal = match.group(0)
            if literal in seen_literals:
                continue
            seen_literals.add(literal)
            content = match.group(1)
            name = self._definition_name(content)
            if name is not None and name.casefold() not in stack:
                reference_scope = self._reference_scope(
                    content,
                    root_scope,
                )
                variants = self._resolved_variants_for(
                    name,
                    language,
                    root_scope=reference_scope,
                    stack=stack,
                )
                if variants:
                    choices.append(_DynamicChoice(name, (literal,), variants))
                continue
            automatic = self._automatic_variants_for(
                content,
                language,
                root_scope=root_scope,
            )
            if automatic is not None:
                automatic_name, variants = automatic
                if variants:
                    choices.append(
                        _DynamicChoice(automatic_name, (literal,), variants)
                    )
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
        for choice in choices:
            combinations *= len(choice.variants)
        evaluated = 0
        truncated = combinations > MAX_COMBINATIONS
        selected_values: tuple[_ResolvedVariant, ...] = ()
        resolved_text = text
        incompatible = 0
        symbolic_checks = 0
        selected_conditions_exact = True

        if choices and not truncated:
            best_key: tuple[Score, str] | None = None
            for selected in product(*(choice.variants for choice in choices)):
                sat = conditions_satisfiable(
                    variant.condition for variant in selected
                )
                symbolic_checks += 1
                if not sat.possible and not sat.truncated:
                    incompatible += 1
                    continue
                candidate = _replace_selected(text, choices, selected)
                key = (score(candidate), candidate)
                evaluated += 1
                if best_key is None or key > best_key:
                    best_key = key
                    resolved_text = candidate
                    selected_values = tuple(selected)
                    selected_conditions_exact = sat.exact
        elif choices:
            current = text
            selected: list[_ResolvedVariant] = []
            selected_conditions: list[ConditionExpression] = []
            for choice in choices:
                possible: list[tuple[_ResolvedVariant, bool]] = []
                for variant in choice.variants:
                    sat = conditions_satisfiable(
                        (*selected_conditions, variant.condition)
                    )
                    symbolic_checks += 1
                    if sat.possible or sat.truncated:
                        possible.append((variant, sat.exact))
                    else:
                        incompatible += 1
                pool = possible or [
                    (variant, False) for variant in choice.variants
                ]
                best_value, exact = max(
                    pool,
                    key=lambda item: (
                        score(_replace_one_group(current, choice, item[0])),
                        item[0].text,
                    ),
                )
                evaluated += len(choice.variants)
                current = _replace_one_group(current, choice, best_value)
                selected.append(best_value)
                selected_conditions.append(best_value.condition)
                selected_conditions_exact = selected_conditions_exact and exact
            resolved_text = current
            selected_values = tuple(selected)

        replacements: list[DynamicReplacement] = []
        for choice, selected in zip(
            choices,
            selected_values,
        ):
            variant_texts = tuple(
                dict.fromkeys(variant.text for variant in choice.variants)
            )
            for token in choice.tokens:
                replacements.append(
                    DynamicReplacement(
                        token=token,
                        name=choice.name,
                        selected=selected.text,
                        variants=variant_texts,
                        localisation_key=selected.localisation_key,
                        source=selected.source,
                        condition=selected.condition_description,
                        condition_exact=selected.condition_exact,
                    )
                )

        unresolved = tuple(
            dict.fromkeys(
                match.group(0)
                for match in _DYNAMIC_TOKEN_RE.finditer(resolved_text)
            )
        )
        all_conditions_exact = all(
            variant.condition_exact
            for choice in choices
            for variant in choice.variants
        )
        confidence = (
            "partial"
            if unresolved
            else (
                "exact"
                if (
                    not truncated
                    and all_conditions_exact
                    and selected_conditions_exact
                )
                else "conservative"
            )
        )
        return DynamicResolution(
            source_text=text,
            text=resolved_text,
            replacements=tuple(replacements),
            unresolved_tokens=unresolved,
            combinations_evaluated=evaluated,
            truncated=truncated,
            incompatible_combinations=incompatible,
            symbolic_checks=symbolic_checks,
            confidence=confidence,
        )


def _replace_selected(
    text: str,
    choices: Iterable[_DynamicChoice],
    selected: Iterable[_ResolvedVariant],
) -> str:
    result = text
    for choice, value in zip(choices, selected):
        result = _replace_one_group(result, choice, value)
    return result


def _replace_one_group(
    text: str,
    choice: _DynamicChoice,
    value: _ResolvedVariant,
) -> str:
    result = text
    for token in choice.tokens:
        result = result.replace(token, value.text)
    return result
