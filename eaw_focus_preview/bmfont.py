from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Iterable

from PIL import Image, ImageChops
from PySide6.QtGui import QImage


_ATTRIBUTE_RE = re.compile(r'(\w+)=((?:"[^"]*")|[^\s]+)')
GLYPH_RESAMPLING = Image.Resampling.NEAREST


def parse_attributes(line: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2).strip('"')
        for match in _ATTRIBUTE_RE.finditer(line)
    }


@dataclass(frozen=True, slots=True)
class Glyph:
    id: int
    x: int
    y: int
    width: int
    height: int
    xoffset: int
    yoffset: int
    xadvance: int
    page: int = 0


@dataclass(frozen=True, slots=True)
class ParsedBMFont:
    line_height: int
    base: int
    scale_width: int
    scale_height: int
    padding: tuple[int, int, int, int]
    pages: dict[int, str]
    glyphs: dict[int, Glyph]


def parse_fnt_text(text: str) -> ParsedBMFont:
    """Разбирает текстовый формат AngelCode BMFont."""
    line_height = 16
    base = 13
    scale_width = 0
    scale_height = 0
    padding = (0, 0, 0, 0)
    pages: dict[int, str] = {}
    glyphs: dict[int, Glyph] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("info "):
            values = parse_attributes(line)
            raw_padding = values.get("padding", "")
            try:
                parsed_padding = tuple(
                    int(value) for value in raw_padding.split(",")
                )
            except ValueError:
                parsed_padding = ()
            if len(parsed_padding) == 4:
                # AngelCode BMFont stores padding as up,right,down,left.
                padding = parsed_padding
        elif line.startswith("common "):
            values = parse_attributes(line)
            line_height = int(values.get("lineHeight", line_height))
            base = int(values.get("base", base))
            scale_width = int(values.get("scaleW", scale_width))
            scale_height = int(values.get("scaleH", scale_height))
        elif line.startswith("page "):
            values = parse_attributes(line)
            pages[int(values.get("id", 0))] = values.get("file", "")
        elif line.startswith("char "):
            values = parse_attributes(line)
            required = (
                "id",
                "x",
                "y",
                "width",
                "height",
                "xoffset",
                "yoffset",
                "xadvance",
            )
            if not all(key in values for key in required):
                continue
            glyph = Glyph(
                id=int(values["id"]),
                x=int(values["x"]),
                y=int(values["y"]),
                width=int(values["width"]),
                height=int(values["height"]),
                xoffset=int(values["xoffset"]),
                yoffset=int(values["yoffset"]),
                xadvance=int(values["xadvance"]),
                page=int(values.get("page", 0)),
            )
            glyphs[glyph.id] = glyph

    if not glyphs:
        raise ValueError("BMFont не содержит ни одного глифа")
    return ParsedBMFont(
        line_height=line_height,
        base=base,
        scale_width=scale_width,
        scale_height=scale_height,
        padding=padding,
        pages=pages,
        glyphs=glyphs,
    )


def _case_insensitive_file(directory: Path, filename: str) -> Path | None:
    wanted = filename.casefold()
    try:
        return next(
            path for path in directory.iterdir() if path.name.casefold() == wanted
        )
    except (StopIteration, FileNotFoundError):
        return None


def resolve_atlas_path(fnt_path: Path, page_filename: str) -> Path:
    """Учитывает ошибочные ссылки вида name_0.dds внутри .fnt."""
    candidates = []
    if page_filename:
        candidates.append(fnt_path.parent / page_filename)
    candidates.append(fnt_path.with_suffix(".dds"))
    if page_filename:
        page_path = Path(page_filename)
        if page_path.stem.endswith("_0"):
            candidates.append(
                fnt_path.parent / f"{page_path.stem[:-2]}{page_path.suffix}"
            )

    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).casefold()
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate
        match = _case_insensitive_file(candidate.parent, candidate.name)
        if match is not None:
            return match
    names = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"DDS-атлас для {fnt_path.name} не найден: {names}")


def pil_image_to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    raw = rgba.tobytes("raw", "RGBA")
    return QImage(
        raw,
        rgba.width,
        rgba.height,
        rgba.width * 4,
        QImage.Format.Format_RGBA8888,
    ).copy()


@dataclass(slots=True)
class BitmapFont:
    name: str
    source_path: Path
    line_height: int
    base: int
    scale_width: int
    scale_height: int
    pages: dict[int, str]
    glyphs: dict[int, Glyph]
    padding: tuple[int, int, int, int] = (0, 0, 0, 0)
    top_offset: int = 0
    atlas_paths: dict[int, Path] = field(default_factory=dict)
    atlas_images: dict[int, Image.Image] = field(default_factory=dict)
    atlas_qimages: dict[int, QImage] = field(default_factory=dict)
    _tinted_cache: dict[tuple[int, int, int, int, int, int], QImage] = field(
        default_factory=dict,
        repr=False,
    )

    def glyph_image(
        self,
        glyph: Glyph,
        color: tuple[int, int, int],
        *,
        scale: float = 1.0,
        target_size: tuple[int, int] | None = None,
    ) -> QImage:
        padding_top, padding_right, padding_bottom, padding_left = self.padding
        # Padding in the source and target BMFonts is a fixed two pixels. It
        # must not be enlarged together with the actual glyph. Scaling the
        # complete rectangle made the outline about one pixel too wide at
        # 18/16, so neighbouring letters and short word gaps touched.
        content_width = max(0, glyph.width - padding_left - padding_right)
        content_height = max(0, glyph.height - padding_top - padding_bottom)
        if target_size is None:
            target_width = max(
                1,
                round(content_width * scale + padding_left + padding_right),
            )
            target_height = max(
                1,
                round(content_height * scale + padding_top + padding_bottom),
            )
        else:
            target_width = max(1, target_size[0])
            target_height = max(1, target_size[1])
        key = (
            glyph.id,
            color[0],
            color[1],
            color[2],
            target_width,
            target_height,
        )
        cached = self._tinted_cache.get(key)
        if cached is not None:
            return cached

        atlas = self.atlas_images[glyph.page]
        crop = atlas.crop(
            (
                glyph.x,
                glyph.y,
                glyph.x + glyph.width,
                glyph.y + glyph.height,
            )
        ).convert("RGBA")
        if crop.width == 0 or crop.height == 0:
            result = QImage()
        else:
            # Умножение оставляет чёрную обводку чёрной, а белую заливку
            # превращает в требуемый цвет. Исходный alpha-канал не меняется.
            tinted_rgb = ImageChops.multiply(
                crop.convert("RGB"),
                Image.new("RGB", crop.size, color),
            )
            tinted = Image.merge("RGBA", (*tinted_rgb.split(), crop.getchannel("A")))
            if tinted.size != (target_width, target_height):
                # Bitmap-глиф 16 px приходится увеличивать до игрового
                # масштаба 18/16. Точечное масштабирование не размывает
                # обводку в соседний xadvance, поэтому буквы и пробелы не
                # слипаются. QPainter затем переносит уже готовый глиф 1:1.
                tinted = tinted.resize(
                    (target_width, target_height),
                    GLYPH_RESAMPLING,
                )
            result = pil_image_to_qimage(tinted)
        self._tinted_cache[key] = result
        return result


def load_bitmap_font(fnt_path: Path, name: str | None = None) -> BitmapFont:
    text = fnt_path.read_text(encoding="utf-8-sig")
    parsed = parse_fnt_text(text)
    page_names = parsed.pages or {0: fnt_path.with_suffix(".dds").name}
    atlas_paths: dict[int, Path] = {}
    atlas_images: dict[int, Image.Image] = {}
    atlas_qimages: dict[int, QImage] = {}

    for page_id, page_filename in page_names.items():
        atlas_path = resolve_atlas_path(fnt_path, page_filename)
        with Image.open(atlas_path) as source:
            rgba = source.convert("RGBA")
            rgba.load()
        atlas_paths[page_id] = atlas_path
        atlas_images[page_id] = rgba
        atlas_qimages[page_id] = pil_image_to_qimage(rgba)

    visible_offsets = [
        glyph.yoffset
        for glyph in parsed.glyphs.values()
        if glyph.id >= 33 and glyph.width > 0 and glyph.height > 0
    ]
    top_offset = min(visible_offsets, default=0)

    return BitmapFont(
        name=name or fnt_path.stem,
        source_path=fnt_path,
        line_height=parsed.line_height,
        base=parsed.base,
        scale_width=parsed.scale_width,
        scale_height=parsed.scale_height,
        padding=parsed.padding,
        pages=page_names,
        glyphs=parsed.glyphs,
        top_offset=top_offset,
        atlas_paths=atlas_paths,
        atlas_images=atlas_images,
        atlas_qimages=atlas_qimages,
    )


@dataclass(frozen=True, slots=True)
class GlyphMatch:
    font: BitmapFont
    glyph: Glyph


@dataclass(frozen=True, slots=True)
class FontFamily:
    fonts: tuple[BitmapFont, ...]

    @property
    def primary(self) -> BitmapFont:
        if not self.fonts:
            raise RuntimeError("Каскад bitmap-шрифтов пуст")
        return self.fonts[0]

    def find(self, character: str) -> GlyphMatch | None:
        codepoint = ord(character)
        for font in self.fonts:
            glyph = font.glyphs.get(codepoint)
            if glyph is not None:
                return GlyphMatch(font, glyph)
        return None


def _registry_values(
    locations: Iterable[tuple[object, str]],
    value_names: Iterable[str],
) -> list[str]:
    """Читает строковые значения реестра Windows без записи в него."""
    try:
        import winreg
    except ImportError:
        return []

    views = (0, winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY)
    values: list[str] = []
    seen: set[tuple[int, str, int]] = set()
    for root, key_name in locations:
        for view in views:
            lookup = (int(root), key_name.casefold(), view)
            if lookup in seen:
                continue
            seen.add(lookup)
            try:
                with winreg.OpenKey(
                    root,
                    key_name,
                    0,
                    winreg.KEY_READ | view,
                ) as key:
                    for value_name in value_names:
                        try:
                            value, _ = winreg.QueryValueEx(key, value_name)
                        except OSError:
                            continue
                        if isinstance(value, str) and value.strip():
                            values.append(value.strip())
            except OSError:
                continue
    return values


def _deduplicate_paths(paths: Iterable[Path]) -> list[Path]:
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path).replace("/", "\\").rstrip("\\").casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _registry_steam_roots() -> list[Path]:
    """Возвращает корни Steam из стандартных read-only ключей реестра."""
    try:
        import winreg
    except ImportError:
        return []

    locations = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Valve\Steam"),
    )
    roots: list[Path] = []
    for raw_value in _registry_values(
        locations,
        ("SteamPath", "InstallPath", "SteamExe"),
    ):
        path = Path(raw_value.replace("/", "\\")).expanduser()
        roots.append(path.parent if path.suffix.casefold() == ".exe" else path)
    return _deduplicate_paths(roots)


def _registry_game_roots() -> list[Path]:
    """Читает InstallLocation Steam App 394360, если он зарегистрирован."""
    try:
        import winreg
    except ImportError:
        return []

    uninstall_key = (
        r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
        r"\Steam App 394360"
    )
    wow_uninstall_key = (
        r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
        r"\Steam App 394360"
    )
    locations = (
        (winreg.HKEY_CURRENT_USER, uninstall_key),
        (winreg.HKEY_LOCAL_MACHINE, uninstall_key),
        (winreg.HKEY_LOCAL_MACHINE, wow_uninstall_key),
    )
    return _deduplicate_paths(
        Path(value).expanduser()
        for value in _registry_values(locations, ("InstallLocation",))
    )


def find_game_fonts_directory() -> Path | None:
    """Находит базовые шрифты HoI4, читая пути Steam в том числе из реестра."""
    install_override = os.environ.get("HOI4_INSTALL_DIR")
    candidates: list[Path] = []
    if install_override:
        override = Path(install_override).expanduser()
        candidates.extend((override, override / "gfx" / "fonts"))

    for game_root in _registry_game_roots():
        candidates.extend((game_root, game_root / "gfx" / "fonts"))

    steam_roots: list[Path] = []
    for variable in ("ProgramFiles(x86)", "ProgramFiles"):
        value = os.environ.get(variable)
        if value:
            steam_roots.append(Path(value) / "Steam")
    steam_roots.extend(_registry_steam_roots())
    steam_roots = _deduplicate_paths(steam_roots)
    for steam_root in tuple(steam_roots):
        library_file = steam_root / "steamapps" / "libraryfolders.vdf"
        try:
            library_text = library_file.read_text(
                encoding="utf-8-sig",
                errors="ignore",
            )
        except OSError:
            continue
        for match in re.finditer(r'"path"\s+"([^"]+)"', library_text):
            steam_roots.append(Path(match.group(1).replace("\\\\", "\\")))

    steam_roots = _deduplicate_paths(steam_roots)

    for steam_root in steam_roots:
        candidates.append(
            steam_root
            / "steamapps"
            / "common"
            / "Hearts of Iron IV"
            / "gfx"
            / "fonts"
        )

    seen: set[str] = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve()).casefold()
        except OSError:
            key = str(candidate.absolute()).casefold()
        if key in seen:
            continue
        seen.add(key)
        if (
            (candidate / "hoi_18mbs.fnt").is_file()
            and (candidate / "hoi_18mbs_cryllic.fnt").is_file()
        ):
            return candidate
    return None


class FontRepository:
    """Загружает разрешённые EaW-шрифты и необязательный игровой растр."""

    def __init__(
        self,
        fonts: dict[str, BitmapFont],
        visual_fonts: dict[str, BitmapFont] | None = None,
        *,
        game_fonts_directory: Path | None = None,
        game_fonts_load_error: str | None = None,
    ):
        self.fonts = fonts
        self.visual_fonts = visual_fonts or {}
        self.game_fonts_directory = game_fonts_directory
        self.game_fonts_load_error = game_fonts_load_error

    @property
    def original_game_fonts_available(self) -> bool:
        return bool(self.visual_fonts)

    @classmethod
    def load(cls, fonts_dir: Path) -> "FontRepository":
        sources = {
            "body_en": "eaw_diplo_16mbs.fnt",
            "body_ru": "eaw_diplo_16mbs_cryllic.fnt",
            "title_en": "hoi_24header.fnt",
            "title_ru": "eaw_24header_cryllic.fnt",
        }
        fonts = {
            key: load_bitmap_font(fonts_dir / filename, key)
            for key, filename in sources.items()
        }
        visual_fonts: dict[str, BitmapFont] = {}
        game_fonts_dir = find_game_fonts_directory()
        game_fonts_load_error = None
        if game_fonts_dir is not None:
            try:
                visual_fonts = {
                    "body_en": load_bitmap_font(
                        game_fonts_dir / "hoi_18mbs.fnt",
                        "game_body_en",
                    ),
                    "body_ru": load_bitmap_font(
                        game_fonts_dir / "hoi_18mbs_cryllic.fnt",
                        "game_body_ru",
                    ),
                }
            except (OSError, ValueError) as error:
                visual_fonts = {}
                game_fonts_load_error = str(error)
        return cls(
            fonts,
            visual_fonts,
            game_fonts_directory=game_fonts_dir,
            game_fonts_load_error=game_fonts_load_error,
        )

    def body_family(self, priority: str = "ru") -> FontFamily:
        order = ("body_ru", "body_en") if priority == "ru" else ("body_en", "body_ru")
        return FontFamily(tuple(self.fonts[key] for key in order))

    def body_visual_family(self, priority: str = "ru") -> FontFamily | None:
        if not self.visual_fonts:
            return None
        order = (
            ("body_ru", "body_en")
            if priority == "ru"
            else ("body_en", "body_ru")
        )
        return FontFamily(tuple(self.visual_fonts[key] for key in order))

    def title_family(self, priority: str = "ru") -> FontFamily:
        order = (
            ("title_ru", "title_en")
            if priority == "ru"
            else ("title_en", "title_ru")
        )
        return FontFamily(tuple(self.fonts[key] for key in order))

    def all_fonts(self) -> Iterable[BitmapFont]:
        return (*self.fonts.values(), *self.visual_fonts.values())
