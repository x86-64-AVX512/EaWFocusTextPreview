from __future__ import annotations

import json
from pathlib import Path

import pytest

import cli_main
import eaw_focus_preview.mod_settings as mod_settings
from eaw_focus_preview.mod_settings import (
    ModSettingsError,
    remember_mod_directory,
    remembered_mod_directory,
    required_mod_directory,
    settings_file_path,
)


def test_settings_json_is_portable_and_next_to_application(
    tmp_path: Path,
) -> None:
    mod = tmp_path / "mod"
    mod.mkdir()

    assert remembered_mod_directory(directory=tmp_path) is None
    remember_mod_directory(mod, directory=tmp_path)

    path = settings_file_path(directory=tmp_path)
    assert path == tmp_path / "settings.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "mod_path": str(mod.resolve())
    }
    assert remembered_mod_directory(directory=tmp_path) == mod.resolve()
    assert required_mod_directory(directory=tmp_path) == mod.resolve()


def test_required_mod_directory_rejects_missing_setting(
    tmp_path: Path,
) -> None:
    with pytest.raises(ModSettingsError, match="Сначала запустите"):
        required_mod_directory(directory=tmp_path)


def test_cli_requires_settings_only_for_dynamic_localisation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        mod_settings,
        "application_directory",
        lambda: tmp_path,
    )

    with pytest.raises(SystemExit) as version_exit:
        cli_main.main(["--version"])
    assert version_exit.value.code == 0
    assert "0.7.6" in capsys.readouterr().out

    assert cli_main.main(["check", "--description", "Коротко."]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is True
    assert output["result"]["dynamic_localisation"]["enabled"] is False

    assert cli_main.main(
        [
            "check",
            "--description",
            "[Root.GetName]",
            "--dynamic-localisation",
        ]
    ) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert "settings.json" in output["error"]["message"]
