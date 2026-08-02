from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from typing import Any


SETTINGS_FILENAME = "settings.json"
MOD_PATH_KEY = "mod_path"


class ModSettingsError(ValueError):
    pass


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def settings_file_path(*, directory: Path | None = None) -> Path:
    return (directory or application_directory()) / SETTINGS_FILENAME


def _read_settings(*, directory: Path | None = None) -> dict[str, Any]:
    path = settings_file_path(directory=directory)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModSettingsError(
            f"Не удалось прочитать {path.name}: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise ModSettingsError(
            f"Корень {path.name} должен быть JSON-объектом"
        )
    return payload


def remembered_mod_directory(
    *,
    directory: Path | None = None,
) -> Path | None:
    value = _read_settings(directory=directory).get(MOD_PATH_KEY)
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser()


def required_mod_directory(
    *,
    directory: Path | None = None,
) -> Path:
    settings_path = settings_file_path(directory=directory)
    path = remembered_mod_directory(directory=directory)
    if path is None:
        raise ModSettingsError(
            f"В {settings_path} не выбрана папка мода. "
            "Сначала запустите EaWFocusTextPreview.exe."
        )
    resolved = path.resolve()
    if not resolved.is_dir():
        raise ModSettingsError(
            f"Папка мода из {settings_path.name} не найдена: {resolved}. "
            "Снова выберите её в EaWFocusTextPreview.exe."
        )
    return resolved


def remember_mod_directory(
    path: Path,
    *,
    directory: Path | None = None,
) -> None:
    settings_path = settings_file_path(directory=directory)
    try:
        payload = _read_settings(directory=directory)
    except ModSettingsError:
        payload = {}
    payload[MOD_PATH_KEY] = str(path.expanduser().resolve())
    temporary = settings_path.with_suffix(f"{settings_path.suffix}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, settings_path)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ModSettingsError(
            f"Не удалось сохранить {settings_path}: {error}"
        ) from error
