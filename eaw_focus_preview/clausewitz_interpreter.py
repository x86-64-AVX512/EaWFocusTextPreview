from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable, Literal, TypeAlias


ClausewitzValue: TypeAlias = str | tuple["ClausewitzEntry", ...]


@dataclass(frozen=True, slots=True)
class ClausewitzEntry:
    key: str
    operator: str
    value: ClausewitzValue


ClausewitzBlock: TypeAlias = tuple[ClausewitzEntry, ...]


@dataclass(frozen=True, slots=True)
class Predicate:
    scope: str
    key: str
    operator: str
    value: str
    exclusive_group: str | None = None
    known: bool = False

    @property
    def identity(self) -> str:
        return "\x1f".join(
            (self.scope, self.key, self.operator, self.value)
        )

    @property
    def label(self) -> str:
        scope = "" if self.scope == "root" else f"{self.scope}."
        return f"{scope}{self.key} {self.operator} {self.value}"


ExpressionKind: TypeAlias = Literal["constant", "predicate", "and", "or", "not"]


@dataclass(frozen=True, slots=True)
class ConditionExpression:
    kind: ExpressionKind
    value: bool | Predicate | None = None
    children: tuple["ConditionExpression", ...] = ()


TRUE_EXPRESSION = ConditionExpression("constant", True)
FALSE_EXPRESSION = ConditionExpression("constant", False)


@dataclass(frozen=True, slots=True)
class SatisfiabilityResult:
    possible: bool
    exact: bool
    predicate_count: int
    steps: int
    truncated: bool = False


_OPERATORS = ("!=", ">=", "<=", "?=", "=", ">", "<")
_BOOLEAN_BLOCKS = frozenset({"and", "or", "not", "nor"})
_SCOPE_BLOCKS = frozenset(
    {
        "root",
        "this",
        "from",
        "from.from",
        "prev",
        "owner",
        "controller",
        "overlord",
        "capital",
    }
)
_EXCLUSIVE_KEYS = frozenset(
    {
        "state",
        "tag",
        "original_tag",
        "has_government",
        "has_country_leader_ideology",
        "has_cosmetic_tag",
    }
)
_KNOWN_BOOLEAN_KEYS = frozenset(
    {
        "has_country_flag",
        "has_global_flag",
        "has_state_flag",
        "has_completed_focus",
        "has_idea",
        "has_tech",
        "has_variable",
        "owns_state",
        "exists",
        "is_subject",
        "is_in_faction",
    }
)
_TOKEN_PATTERN = re.compile(
    r'\s+|#[^\r\n]*|"(?:\\.|[^"\\])*"|!=|>=|<=|\?=|[=<>]|[{}]|'
    r'[^\s{}"=<>!#]+|.'
)


def tokenize_clausewitz(text: str) -> list[str]:
    """Tokenise the PDX-script subset used by scripted localisation.

    Comparison operators are kept, unlike the old permissive parser.  This is
    important for ``check_variable = { value > 4 }`` conditions.
    """

    tokens: list[str] = []
    for match in _TOKEN_PATTERN.finditer(text):
        token = match.group(0)
        if not token or token.isspace() or token.startswith("#"):
            continue
        if token.startswith('"') and token.endswith('"'):
            token = token[1:-1].replace(r'\"', '"').replace(r"\\", "\\")
        tokens.append(token)
    return tokens


def _parse_block(
    tokens: list[str],
    index: int = 0,
    *,
    nested: bool = False,
) -> tuple[ClausewitzBlock, int]:
    entries: list[ClausewitzEntry] = []
    while index < len(tokens):
        if tokens[index] == "}":
            return tuple(entries), index + 1
        key = tokens[index]
        index += 1
        if index >= len(tokens) or tokens[index] not in _OPERATORS:
            continue
        operator = tokens[index]
        index += 1
        if index >= len(tokens):
            entries.append(ClausewitzEntry(key, operator, ""))
            break
        if tokens[index] == "{":
            value, index = _parse_block(tokens, index + 1, nested=True)
        else:
            value = tokens[index]
            index += 1
        entries.append(ClausewitzEntry(key, operator, value))
    return tuple(entries), index


def parse_clausewitz(text: str) -> ClausewitzBlock:
    entries, _ = _parse_block(tokenize_clausewitz(text))
    return entries


def scalar_values(block: ClausewitzBlock, key: str) -> tuple[str, ...]:
    folded = key.casefold()
    return tuple(
        entry.value
        for entry in block
        if entry.key.casefold() == folded and isinstance(entry.value, str)
    )


def child_blocks(block: ClausewitzBlock, key: str) -> tuple[ClausewitzBlock, ...]:
    folded = key.casefold()
    return tuple(
        entry.value
        for entry in block
        if entry.key.casefold() == folded and isinstance(entry.value, tuple)
    )


def serialize_block(block: ClausewitzBlock) -> str:
    parts: list[str] = []
    for entry in block:
        if isinstance(entry.value, tuple):
            value = "{ " + serialize_block(entry.value) + " }"
        else:
            value = entry.value
        parts.append(f"{entry.key} {entry.operator} {value}")
    return " ".join(parts)


def _constant(value: bool) -> ConditionExpression:
    return TRUE_EXPRESSION if value else FALSE_EXPRESSION


def condition_not(expression: ConditionExpression) -> ConditionExpression:
    if expression.kind == "constant":
        return _constant(not bool(expression.value))
    if expression.kind == "not":
        return expression.children[0]
    return ConditionExpression("not", children=(expression,))


def condition_and(
    expressions: Iterable[ConditionExpression],
) -> ConditionExpression:
    children: list[ConditionExpression] = []
    for expression in expressions:
        if expression.kind == "constant":
            if expression.value is False:
                return FALSE_EXPRESSION
            continue
        if expression.kind == "and":
            children.extend(expression.children)
        else:
            children.append(expression)
    if not children:
        return TRUE_EXPRESSION
    if len(children) == 1:
        return children[0]
    return ConditionExpression("and", children=tuple(children))


def condition_or(
    expressions: Iterable[ConditionExpression],
) -> ConditionExpression:
    children: list[ConditionExpression] = []
    for expression in expressions:
        if expression.kind == "constant":
            if expression.value is True:
                return TRUE_EXPRESSION
            continue
        if expression.kind == "or":
            children.extend(expression.children)
        else:
            children.append(expression)
    if not children:
        return FALSE_EXPRESSION
    if len(children) == 1:
        return children[0]
    return ConditionExpression("or", children=tuple(children))


def _normalise_scope(current: str, root: str, key: str) -> str:
    folded = key.casefold()
    if folded == "root":
        return root
    if folded == "this":
        return current
    if len(key) == 3 and key.isalnum() and key.upper() == key:
        return f"country:{key}"
    return f"{current}.{folded}"


def _check_variable_predicate(
    block: ClausewitzBlock,
    scope: str,
) -> Predicate:
    variable_entry = next(
        (
            entry
            for entry in block
            if entry.key.casefold() == "var" and isinstance(entry.value, str)
        ),
        None,
    )
    if variable_entry is not None:
        comparison = next(
            (
                entry
                for entry in block
                if entry.key.casefold() in {"value", "compare"}
                and isinstance(entry.value, str)
            ),
            ClausewitzEntry("value", "=", "unknown"),
        )
        variable = str(variable_entry.value).casefold()
        value = str(comparison.value).casefold()
        operator = comparison.operator
        group = f"{scope}:variable:{variable}" if operator == "=" else None
        return Predicate(
            scope,
            f"variable:{variable}",
            operator,
            value,
            group,
            operator == "=",
        )
    comparison = next(
        (
            entry
            for entry in block
            if isinstance(entry.value, str)
            and entry.key.casefold() not in {"compare", "value", "var"}
        ),
        None,
    )
    if comparison is None:
        comparison = next(
            (entry for entry in block if isinstance(entry.value, str)),
            ClausewitzEntry("unknown", "=", serialize_block(block)),
        )
    variable = comparison.key.casefold()
    value = comparison.value if isinstance(comparison.value, str) else ""
    operator = comparison.operator
    group = f"{scope}:variable:{variable}" if operator == "=" else None
    return Predicate(
        scope,
        f"variable:{variable}",
        operator,
        value.casefold(),
        group,
        operator == "=",
    )


def _entry_condition(
    entry: ClausewitzEntry,
    *,
    scope: str,
    root_scope: str,
) -> ConditionExpression:
    key = entry.key.casefold()
    value = entry.value
    if key == "always" and isinstance(value, str):
        return _constant(value.casefold() not in {"no", "false", "0"})

    if key in _BOOLEAN_BLOCKS and isinstance(value, tuple):
        compiled = tuple(
            _entry_condition(child, scope=scope, root_scope=root_scope)
            for child in value
        )
        if key == "and":
            return condition_and(compiled)
        if key == "or":
            return condition_or(compiled)
        if key == "not":
            return condition_not(condition_and(compiled))
        return condition_not(condition_or(compiled))

    is_named_scope = (
        len(entry.key) == 3
        and entry.key.isalnum()
        and entry.key.upper() == entry.key
    )
    is_dynamic_scope = key.startswith(("var:", "event_target:"))
    if (
        isinstance(value, tuple)
        and (key in _SCOPE_BLOCKS or is_named_scope or is_dynamic_scope)
    ):
        nested_scope = _normalise_scope(scope, root_scope, entry.key)
        return condition_from_trigger(
            value,
            root_scope=root_scope,
            current_scope=nested_scope,
        )

    if key == "check_variable" and isinstance(value, tuple):
        predicate = _check_variable_predicate(value, scope)
        return ConditionExpression("predicate", predicate)

    if isinstance(value, tuple):
        predicate = Predicate(
            scope,
            key,
            entry.operator,
            serialize_block(value).casefold(),
            None,
            False,
        )
        return ConditionExpression("predicate", predicate)

    scalar = value.casefold()
    if scalar in {"no", "false"}:
        positive = Predicate(
            scope,
            key,
            entry.operator,
            "yes",
            None,
            key in _KNOWN_BOOLEAN_KEYS,
        )
        return condition_not(ConditionExpression("predicate", positive))

    exclusive_group = (
        f"{scope}:{key}" if key in _EXCLUSIVE_KEYS and entry.operator == "=" else None
    )
    predicate = Predicate(
        scope,
        key,
        entry.operator,
        scalar,
        exclusive_group,
        key in _EXCLUSIVE_KEYS or key in _KNOWN_BOOLEAN_KEYS,
    )
    return ConditionExpression("predicate", predicate)


def condition_from_trigger(
    trigger: ClausewitzBlock | None,
    *,
    root_scope: str = "root",
    current_scope: str | None = None,
) -> ConditionExpression:
    if trigger is None:
        return TRUE_EXPRESSION
    scope = current_scope or root_scope
    return condition_and(
        _entry_condition(entry, scope=scope, root_scope=root_scope)
        for entry in trigger
    )


def expression_predicates(
    expression: ConditionExpression,
) -> tuple[Predicate, ...]:
    if expression.kind == "predicate":
        assert isinstance(expression.value, Predicate)
        return (expression.value,)
    predicates: list[Predicate] = []
    for child in expression.children:
        predicates.extend(expression_predicates(child))
    return tuple(dict.fromkeys(predicates))


def describe_condition(expression: ConditionExpression, limit: int = 160) -> str:
    def render(item: ConditionExpression) -> str:
        if item.kind == "constant":
            return "always" if item.value else "never"
        if item.kind == "predicate":
            assert isinstance(item.value, Predicate)
            return item.value.label
        if item.kind == "not":
            return f"NOT ({render(item.children[0])})"
        separator = " AND " if item.kind == "and" else " OR "
        return "(" + separator.join(render(child) for child in item.children) + ")"

    rendered = render(expression)
    return rendered if len(rendered) <= limit else rendered[: limit - 1] + "…"


def _evaluate(
    expression: ConditionExpression,
    assignments: dict[str, bool],
) -> bool | None:
    if expression.kind == "constant":
        return bool(expression.value)
    if expression.kind == "predicate":
        assert isinstance(expression.value, Predicate)
        return assignments.get(expression.value.identity)
    if expression.kind == "not":
        value = _evaluate(expression.children[0], assignments)
        return None if value is None else not value
    values = tuple(_evaluate(child, assignments) for child in expression.children)
    if expression.kind == "and":
        if False in values:
            return False
        return True if all(value is True for value in values) else None
    if True in values:
        return True
    return False if all(value is False for value in values) else None


def conditions_satisfiable(
    expressions: Iterable[ConditionExpression],
    *,
    max_steps: int = 4096,
) -> SatisfiabilityResult:
    combined = condition_and(expressions)
    predicates = expression_predicates(combined)
    by_identity = {predicate.identity: predicate for predicate in predicates}
    groups: dict[str, tuple[str, ...]] = {}
    for predicate in predicates:
        if predicate.exclusive_group is None:
            continue
        groups.setdefault(predicate.exclusive_group, ())
        groups[predicate.exclusive_group] = (
            *groups[predicate.exclusive_group],
            predicate.identity,
        )

    assignments: dict[str, bool] = {}
    steps = 0
    truncated = False

    def search() -> bool:
        nonlocal steps, truncated
        value = _evaluate(combined, assignments)
        if value is not None:
            return value
        if steps >= max_steps:
            truncated = True
            return True
        identity = next(
            key for key in by_identity if key not in assignments
        )
        predicate = by_identity[identity]
        for proposed in (True, False):
            steps += 1
            changed: list[str] = []
            conflict = False
            current = assignments.get(identity)
            if current is not None and current != proposed:
                continue
            if current is None:
                assignments[identity] = proposed
                changed.append(identity)
            if proposed and predicate.exclusive_group is not None:
                for sibling in groups[predicate.exclusive_group]:
                    if sibling == identity:
                        continue
                    sibling_value = assignments.get(sibling)
                    if sibling_value is True:
                        conflict = True
                        break
                    if sibling_value is None:
                        assignments[sibling] = False
                        changed.append(sibling)
            if not conflict and search():
                return True
            for changed_identity in reversed(changed):
                assignments.pop(changed_identity, None)
        return False

    possible = search()
    exact = not truncated and all(predicate.known for predicate in predicates)
    return SatisfiabilityResult(
        possible=possible,
        exact=exact,
        predicate_count=len(predicates),
        steps=steps,
        truncated=truncated,
    )
