from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True, slots=True)
class LoadedText:
    title: str | None = None
    description: str | None = None
    effect: str | None = None


@dataclass(frozen=True, slots=True)
class FocusLocalisationEntry:
    key: str
    focus_key: str
    title: str
    description: str
    line_number: int


@dataclass(frozen=True, slots=True)
class FocusFileParseError:
    line_number: int
    text: str
    message: str


@dataclass(frozen=True, slots=True)
class FocusLocalisationFile:
    path: Path
    language: str | None
    source_format: str
    entries: tuple[FocusLocalisationEntry, ...]
    errors: tuple[FocusFileParseError, ...] = ()
    ignored_values: int = 0
    known_focus_ids: int = 0


_SECTION_NAMES = {
    "title": "title",
    "name": "title",
    "название": "title",
    "description": "description",
    "desc": "description",
    "описание": "description",
    "effect": "effect",
    "reward": "effect",
    "эффект": "effect",
}
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_YAML_VALUE_PREFIX_RE = re.compile(
    r'^\s*([A-Za-z0-9_.-]+)\s*:\s*\d*\s*"'
)
_LOCALISATION_LANGUAGE_RE = re.compile(
    r"^\s*l_([A-Za-z0-9_-]+)\s*:\s*(?:#.*)?$",
    re.MULTILINE,
)
_DESCRIPTION_SUFFIXES = ("_description", "_desc")
_FOCUS_BLOCK_NAMES = frozenset({"focus", "shared_focus", "joint_focus"})
_SCRIPT_TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|[A-Za-z0-9_@.$:-]+|[{}=]'
)


def read_text_file(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _parse_sections(text: str) -> LoadedText | None:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    found_header = False
    for line in text.splitlines():
        match = _SECTION_RE.match(line)
        if match:
            key = _SECTION_NAMES.get(match.group(1).strip().casefold())
            current = key
            found_header = found_header or key is not None
            if key is not None:
                sections.setdefault(key, [])
            continue
        if current is not None:
            sections[current].append(line)
    if not found_header:
        return None
    return LoadedText(
        title="\n".join(sections["title"]).strip()
        if "title" in sections
        else None,
        description="\n".join(sections["description"]).strip()
        if "description" in sections
        else None,
        effect="\n".join(sections["effect"]).strip()
        if "effect" in sections
        else None,
    )


def _unescape_localisation_value(value: str) -> str:
    # Последовательность \n оставляем текстовой: её понимает layout-движок.
    return value.replace(r"\"", '"').replace(r"\\", "\\")


def parse_localisation_value_line(line: str) -> tuple[str, str] | None:
    """Читает значение до внешней кавычки, не ломаясь на кавычках внутри."""
    match = _YAML_VALUE_PREFIX_RE.match(line)
    if match is None:
        return None

    value_start = match.end()
    for index in range(value_start, len(line)):
        if line[index] != '"':
            continue
        backslashes = 0
        cursor = index
        while cursor > value_start and line[cursor - 1] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2:
            continue

        suffix = line[index + 1:].lstrip(" \t")
        if suffix and not suffix.startswith("#"):
            continue
        return (
            match.group(1),
            _unescape_localisation_value(line[value_start:index]),
        )
    return None


def _parse_localisation_yaml(text: str) -> LoadedText | None:
    values: list[tuple[str, str]] = []
    for line in text.splitlines():
        parsed = parse_localisation_value_line(line)
        if parsed is not None:
            values.append(parsed)
    if not values:
        return None

    title = None
    description = None
    effect = None
    for key, value in values:
        folded = key.casefold()
        if title is None and (
            folded.endswith("_name")
            or folded.endswith("_title")
            or folded.endswith("_focus")
        ):
            title = value
        elif description is None and folded.endswith(("_desc", "_description")):
            description = value
        elif effect is None and folded.endswith(("_effect", "_reward")):
            effect = value

    raw_values = [value for _, value in values]
    if title is None and description is None and effect is None:
        if len(raw_values) >= 3:
            title, description, effect = raw_values[:3]
        elif len(raw_values) == 2:
            title, description = raw_values
        else:
            effect = raw_values[0]
    return LoadedText(title, description, effect)


def load_text_payload(path: Path) -> LoadedText:
    text = read_text_file(path)
    sections = _parse_sections(text)
    if sections is not None:
        return sections
    if path.suffix.casefold() in {".yml", ".yaml"}:
        parsed_yaml = _parse_localisation_yaml(text)
        if parsed_yaml is not None:
            return parsed_yaml
    return LoadedText(effect=text)


def parse_focus_localisation_entries(
    text: str,
) -> tuple[FocusLocalisationEntry, ...]:
    """Extract every focus description and its matching title from YAML.

    The convention used by HoI4 localization is ``focus_key`` for the title
    and ``focus_key_desc`` for the description.  ``_description`` as well as
    title keys ending in ``_name``/``_title`` are accepted for mod files that
    use a more explicit naming scheme.  Duplicate keys follow localization
    behavior within one file: the last parsed value wins.
    """
    values_by_key: dict[str, tuple[str, str, int]] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        parsed = parse_localisation_value_line(line)
        if parsed is None:
            continue
        key, value = parsed
        values_by_key[key.casefold()] = (key, value, line_number)

    entries: list[FocusLocalisationEntry] = []
    for folded_key, (key, description, line_number) in values_by_key.items():
        suffix = next(
            (
                candidate
                for candidate in _DESCRIPTION_SUFFIXES
                if folded_key.endswith(candidate)
            ),
            None,
        )
        if suffix is None:
            continue

        focus_key = key[: -len(suffix)]
        folded_focus_key = folded_key[: -len(suffix)]
        title = ""
        for title_key in (
            folded_focus_key,
            f"{folded_focus_key}_name",
            f"{folded_focus_key}_title",
        ):
            title_match = values_by_key.get(title_key)
            if title_match is not None:
                title = title_match[1]
                break
        entries.append(
            FocusLocalisationEntry(
                key=key,
                focus_key=focus_key,
                title=title,
                description=description,
                line_number=line_number,
            )
        )

    entries.sort(key=lambda entry: entry.line_number)
    return tuple(entries)


def _parse_keyed_focus_entries(
    text: str,
) -> tuple[FocusLocalisationEntry, ...]:
    entries: list[FocusLocalisationEntry] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        parsed = parse_localisation_value_line(line)
        if parsed is None:
            continue
        key, value = parsed
        entries.append(
            FocusLocalisationEntry(
                key=key,
                focus_key=key,
                title="",
                description=value,
                line_number=line_number,
            )
        )
    return tuple(entries)


def _parse_plain_focus_entries(
    text: str,
) -> tuple[FocusLocalisationEntry, ...]:
    entries: list[FocusLocalisationEntry] = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if (
            not line
            or line.startswith("#")
            or _LOCALISATION_LANGUAGE_RE.fullmatch(line) is not None
        ):
            continue
        if len(line) >= 2 and line.startswith('"') and line.endswith('"'):
            line = _unescape_localisation_value(line[1:-1])
        entries.append(
            FocusLocalisationEntry(
                key=f"Строка {line_number}",
                focus_key=f"Строка {line_number}",
                title="",
                description=line,
                line_number=line_number,
            )
        )
    return tuple(entries)


def load_focus_localisation_file(path: Path) -> FocusLocalisationFile:
    text = read_text_file(path)
    language_match = _LOCALISATION_LANGUAGE_RE.search(text)
    entries = parse_focus_localisation_entries(text)
    source_format = "localisation"
    if not entries:
        entries = _parse_keyed_focus_entries(text)
        source_format = "keyed"
    if not entries:
        entries = _parse_plain_focus_entries(text)
        source_format = "plain"
    return FocusLocalisationFile(
        path=path,
        language=(
            language_match.group(1).casefold()
            if language_match is not None
            else None
        ),
        source_format=source_format,
        entries=entries,
    )


def _script_tokens(text: str) -> list[str]:
    uncommented: list[str] = []
    for line in text.splitlines():
        quoted = False
        escaped = False
        kept: list[str] = []
        for character in line:
            if character == "#" and not quoted:
                break
            kept.append(character)
            if escaped:
                escaped = False
            elif character == "\\" and quoted:
                escaped = True
            elif character == '"':
                quoted = not quoted
        uncommented.append("".join(kept))
    return _SCRIPT_TOKEN_RE.findall("\n".join(uncommented))


def parse_focus_ids(text: str) -> frozenset[str]:
    """Collect direct ``id`` values from focus-like Clausewitz blocks."""
    tokens = _script_tokens(text)
    block_stack: list[str] = []
    focus_ids: set[str] = set()
    for index, token in enumerate(tokens):
        if token == "{":
            block_name = (
                tokens[index - 2].casefold()
                if index >= 2 and tokens[index - 1] == "="
                else ""
            )
            block_stack.append(block_name)
            continue
        if token == "}":
            if block_stack:
                block_stack.pop()
            continue
        if (
            token.casefold() == "id"
            and block_stack
            and block_stack[-1] in _FOCUS_BLOCK_NAMES
            and index + 2 < len(tokens)
            and tokens[index + 1] == "="
        ):
            value = tokens[index + 2]
            if value not in {"{", "}", "="}:
                focus_ids.add(value.strip('"'))
    return frozenset(focus_ids)


def load_mod_focus_ids(mod_root: Path) -> frozenset[str]:
    focus_directory = mod_root / "common" / "national_focus"
    if not focus_directory.is_dir():
        raise FileNotFoundError(
            f"В выбранном моде нет папки {focus_directory}"
        )
    focus_ids: set[str] = set()
    for script_path in focus_directory.rglob("*.txt"):
        focus_ids.update(parse_focus_ids(read_text_file(script_path)))
    return frozenset(focus_ids)


def _is_context_ignored_line(line: str) -> bool:
    stripped = line.strip()
    return (
        not stripped
        or stripped.startswith("#")
        or _LOCALISATION_LANGUAGE_RE.fullmatch(stripped) is not None
    )


def load_contextual_focus_file(
    path: Path,
    mod_root: Path,
) -> FocusLocalisationFile:
    """Read a strict localization file and retain real mod focus IDs only."""
    text = read_text_file(path)
    focus_ids = load_mod_focus_ids(mod_root)
    folded_focus_ids = {focus_id.casefold() for focus_id in focus_ids}
    language_match = _LOCALISATION_LANGUAGE_RE.search(text)

    errors: list[FocusFileParseError] = []
    parsed_value_count = 0
    associated_value_count = 0
    for line_number, line in enumerate(text.splitlines(), 1):
        if _is_context_ignored_line(line):
            continue
        parsed = parse_localisation_value_line(line)
        if parsed is None:
            errors.append(
                FocusFileParseError(
                    line_number=line_number,
                    text=line.strip(),
                    message=(
                        'Ожидалась строка KEY: "Текст" или '
                        'KEY:0 "Текст"'
                    ),
                )
            )
            continue
        parsed_value_count += 1
        folded_key = parsed[0].casefold()
        if folded_key in folded_focus_ids:
            associated_value_count += 1
            continue
        if any(
            folded_key.endswith(suffix)
            and folded_key[: -len(suffix)] in folded_focus_ids
            for suffix in (*_DESCRIPTION_SUFFIXES, "_name", "_title")
        ):
            associated_value_count += 1

    entries = tuple(
        entry
        for entry in parse_focus_localisation_entries(text)
        if entry.focus_key.casefold() in folded_focus_ids
    )
    return FocusLocalisationFile(
        path=path,
        language=(
            language_match.group(1).casefold()
            if language_match is not None
            else None
        ),
        source_format="contextual",
        entries=entries,
        errors=tuple(errors),
        ignored_values=max(0, parsed_value_count - associated_value_count),
        known_focus_ids=len(focus_ids),
    )
