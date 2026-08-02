from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .file_loader import read_text_file


_COUNTRY_TAG_RE = re.compile(r"(?m)^\s*([A-Z0-9]{3})\s*=")
_NAME_ASSIGNMENT_RE = re.compile(
    r'^\s*name\s*=\s*(?:"((?:\\.|[^"])*)"|([^\s#}]+))'
)
_FACTION_REFERENCE_RE = re.compile(
    r'(?mi)^\s*#?\s*(?:create_faction|set_faction_name)\s*=\s*'
    r'(?:"((?:\\.|[^"])*)"|([^\s#}]+))'
)
_IDEOLOGY_PARTY_RE = re.compile(
    r"^([A-Z0-9]{3})_"
    r"(?:fascism|communism|democratic|neutrality)_party(?:_long)?$",
    re.IGNORECASE,
)
_LOCATION_KEY_RE = re.compile(
    r"^(?:STATE|VICTORY_POINTS|STRATEGICREGION)_\d+$"
)
_CAPITAL_KEY_RE = re.compile(r"^VICTORY_POINTS_\d+$")


@dataclass(frozen=True, slots=True)
class AutomaticVariants:
    name: str
    values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _LanguagePools:
    country_names: tuple[str, ...]
    country_definite_names: tuple[str, ...]
    country_adjectives: tuple[str, ...]
    country_names_by_tag: dict[str, tuple[str, ...]]
    country_definite_names_by_tag: dict[str, tuple[str, ...]]
    country_adjectives_by_tag: dict[str, tuple[str, ...]]
    leaders: tuple[str, ...]
    locations: tuple[str, ...]
    capitals: tuple[str, ...]
    factions: tuple[str, ...]
    parties: tuple[str, ...]
    ideologies: tuple[str, ...]


def _unique(values) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


class AutomaticLocalisationCatalog:
    """Конечные варианты встроенных Get… из данных выбранного мода."""

    def __init__(
        self,
        root: Path,
        localisations: dict[str, dict[str, str]],
        country_tags: frozenset[str],
        character_name_keys: tuple[str, ...],
        faction_name_keys: tuple[str, ...],
    ):
        self.root = root
        self.localisations = localisations
        self.country_tags = country_tags
        self.character_name_keys = character_name_keys
        self.faction_name_keys = faction_name_keys
        self._pool_cache: dict[str, _LanguagePools] = {}

    @classmethod
    def load(
        cls,
        root: Path,
        localisations: dict[str, dict[str, str]],
    ) -> "AutomaticLocalisationCatalog":
        country_tags: set[str] = set()
        tags_directory = root / "common" / "country_tags"
        if tags_directory.is_dir():
            for path in sorted(tags_directory.rglob("*.txt")):
                country_tags.update(
                    _COUNTRY_TAG_RE.findall(read_text_file(path))
                )

        character_names: list[str] = []
        characters_directory = root / "common" / "characters"
        if characters_directory.is_dir():
            for path in sorted(characters_directory.rglob("*.txt")):
                character_names.extend(
                    _country_leader_names(read_text_file(path))
                )

        faction_names: list[str] = []
        for factions_directory in (root / "common", root / "events"):
            if not factions_directory.is_dir():
                continue
            for path in sorted(factions_directory.rglob("*.txt")):
                for match in _FACTION_REFERENCE_RE.finditer(read_text_file(path)):
                    key = match.group(1) or match.group(2)
                    if "[" not in key:
                        faction_names.append(key)

        return cls(
            root,
            localisations,
            frozenset(country_tags),
            _unique(character_names),
            _unique(faction_names),
        )

    def variants_for(
        self,
        token_content: str,
        language: str,
    ) -> AutomaticVariants | None:
        parts = [part for part in token_content.strip().split(".") if part]
        if not parts or parts[0].startswith("?"):
            return None
        method = parts[-1].casefold()
        pools = self._pools(language)
        tag = parts[0].upper() if parts[0].upper() in self.country_tags else None

        if method in {
            "getname",
            "getnamewithflag",
            "getname_gen",
            "getcountry",
        }:
            location_scope = (
                parts[0].isdigit()
                or any(part.casefold() == "capital" for part in parts[:-1])
            )
            if location_scope:
                return AutomaticVariants("GetName(location)", pools.locations)
            values = (
                pools.country_names_by_tag.get(tag, ())
                if tag is not None
                else pools.country_names
            )
            return AutomaticVariants("GetName(country)", values)

        if method in {"getnamedef", "getnamedefcap"}:
            values = (
                pools.country_definite_names_by_tag.get(tag, ())
                if tag is not None
                else pools.country_definite_names
            )
            return AutomaticVariants("GetNameDef", values)

        if method in {"getadjective", "getadjectivecap"}:
            values = (
                pools.country_adjectives_by_tag.get(tag, ())
                if tag is not None
                else pools.country_adjectives
            )
            return AutomaticVariants("GetAdjective", values)

        if method == "getleader":
            return AutomaticVariants("GetLeader", pools.leaders)
        if method in {"getcapitalvictorypointname", "getcapitalname"}:
            return AutomaticVariants("GetCapitalName", pools.capitals)
        if method == "getfactionname":
            return AutomaticVariants("GetFactionName", pools.factions)
        if method in {
            "getrulingparty",
            "getrulingpartylong",
            "getfascistparty",
            "getdemocraticparty",
            "getcommunistparty",
            "getneutralparty",
        }:
            return AutomaticVariants("GetPartyName", pools.parties)
        if method == "getrulingideology":
            return AutomaticVariants("GetRulingIdeology", pools.ideologies)

        date_values = self._date_variants(method, language)
        if date_values:
            return AutomaticVariants(parts[-1], date_values)
        pronouns = self._pronoun_variants(method, language)
        if pronouns:
            return AutomaticVariants(parts[-1], pronouns)
        return None

    def _pools(self, language: str) -> _LanguagePools:
        if language in self._pool_cache:
            return self._pool_cache[language]
        values = self.localisations[language]
        keys = set(values)
        bases = sorted(
            key
            for key in keys
            if f"{key}_DEF" in keys and f"{key}_ADJ" in keys
        )

        names_by_tag: dict[str, tuple[str, ...]] = {}
        definite_by_tag: dict[str, tuple[str, ...]] = {}
        adjectives_by_tag: dict[str, tuple[str, ...]] = {}
        for tag in self.country_tags:
            tag_bases = [
                base
                for base in bases
                if base == tag or base.startswith(f"{tag}_")
            ]
            names_by_tag[tag] = _unique(values[base] for base in tag_bases)
            definite_by_tag[tag] = _unique(
                values[f"{base}_DEF"] for base in tag_bases
            )
            adjectives_by_tag[tag] = _unique(
                values[f"{base}_ADJ"] for base in tag_bases
            )

        locations = _unique(
            value
            for key, value in values.items()
            if _LOCATION_KEY_RE.fullmatch(key)
        )
        capitals = _unique(
            value
            for key, value in values.items()
            if _CAPITAL_KEY_RE.fullmatch(key)
        ) or locations
        leaders = _unique(
            values.get(key, key) for key in self.character_name_keys
        )
        faction_keys = set(self.faction_name_keys)
        factions = _unique(values.get(key, key) for key in faction_keys)
        parties = _unique(
            value
            for key, value in values.items()
            if (
                (match := _IDEOLOGY_PARTY_RE.fullmatch(key)) is not None
                and match.group(1).upper() in self.country_tags
            )
        )
        ideology_keys = (
            "fascism",
            "communism",
            "democratic",
            "neutrality",
            "non_aligned",
        )
        ideologies = _unique(values.get(key, key) for key in ideology_keys)

        pools = _LanguagePools(
            country_names=_unique(values[base] for base in bases),
            country_definite_names=_unique(
                values[f"{base}_DEF"] for base in bases
            ),
            country_adjectives=_unique(
                values[f"{base}_ADJ"] for base in bases
            ),
            country_names_by_tag=names_by_tag,
            country_definite_names_by_tag=definite_by_tag,
            country_adjectives_by_tag=adjectives_by_tag,
            leaders=leaders,
            locations=locations,
            capitals=capitals,
            factions=factions,
            parties=parties,
            ideologies=ideologies,
        )
        self._pool_cache[language] = pools
        return pools

    @staticmethod
    def _date_variants(method: str, language: str) -> tuple[str, ...]:
        if method == "getyear":
            return ("9999",)
        if method not in {"getmonth", "getdate", "getdatetext"}:
            return ()
        months = {
            "russian": (
                "январь", "февраль", "март", "апрель", "май", "июнь",
                "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
            ),
            "english": (
                "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December",
            ),
        }.get(language, ("September",))
        if method == "getmonth":
            return months
        return tuple(f"30 {month} 9999" for month in months)

    @staticmethod
    def _pronoun_variants(method: str, language: str) -> tuple[str, ...]:
        forms = {
            "russian": {
                "getshehe": ("она", "он"),
                "getshehecap": ("Она", "Он"),
                "getherhis": ("её", "его"),
                "getherhiscap": ("Её", "Его"),
                "getherhim": ("её", "его"),
                "getherhimcap": ("Её", "Его"),
            },
            "english": {
                "getshehe": ("she", "he"),
                "getshehecap": ("She", "He"),
                "getherhis": ("her", "his"),
                "getherhiscap": ("Her", "His"),
                "getherhim": ("her", "him"),
                "getherhimcap": ("Her", "Him"),
            },
        }
        return forms.get(language, {}).get(method, ())


def _strip_script_comment(line: str) -> str:
    inside_quotes = False
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\" and inside_quotes:
            escaped = True
            continue
        if character == '"':
            inside_quotes = not inside_quotes
        elif character == "#" and not inside_quotes:
            return line[:index]
    return line


def _country_leader_names(text: str) -> tuple[str, ...]:
    """Берёт name только у персонажей, способных быть главой страны."""
    depth = 0
    characters_depth: int | None = None
    character_depth: int | None = None
    current_name: str | None = None
    has_country_leader = False
    names: list[str] = []

    for raw_line in text.splitlines():
        line = _strip_script_comment(raw_line)
        depth_before = depth
        if characters_depth is None and re.match(
            r"^\s*characters\s*=\s*\{",
            line,
        ):
            characters_depth = depth_before + 1
        elif (
            characters_depth is not None
            and character_depth is None
            and depth_before == characters_depth
            and re.match(r"^\s*[^\s#={}]+\s*=\s*\{", line)
        ):
            character_depth = depth_before + 1
            current_name = None
            has_country_leader = False
        elif character_depth is not None:
            name_match = _NAME_ASSIGNMENT_RE.match(line)
            if name_match is not None and depth_before == character_depth:
                current_name = name_match.group(1) or name_match.group(2)
            if (
                depth_before == character_depth
                and re.match(r"^\s*country_leader\s*=\s*\{", line)
            ):
                has_country_leader = True

        depth += line.count("{") - line.count("}")
        if character_depth is not None and depth < character_depth:
            if current_name and has_country_leader:
                names.append(current_name)
            character_depth = None
            current_name = None
            has_country_leader = False
        if characters_depth is not None and depth < characters_depth:
            characters_depth = None
    return _unique(names)
