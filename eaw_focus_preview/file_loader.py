from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True, slots=True)
class LoadedText:
    title: str | None = None
    description: str | None = None
    effect: str | None = None


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
