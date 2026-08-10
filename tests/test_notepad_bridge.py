from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtNetwork import QLocalSocket
from PySide6.QtWidgets import QDialog

import eaw_focus_preview.main_window as main_window_module
from eaw_focus_preview.notepad_bridge import (
    NotepadBridge,
    encode_description_message,
)
from eaw_focus_preview.bmfont import FontRepository
from eaw_focus_preview.file_loader import (
    FocusLocalisationEntry,
    FocusLocalisationFile,
)
from eaw_focus_preview.main_window import BatchResultsDialog, MainWindow
from eaw_focus_preview.paths import fonts_directory


def test_bridge_receives_unicode_description(qapp) -> None:
    server_name = f"EaWFocusTextPreview-test-{uuid4().hex}"
    bridge = NotepadBridge(server_name=server_name)
    received: list[str] = []
    bridge.description_received.connect(received.append)
    assert bridge.available
    assert bridge.full_server_name.endswith(server_name)

    client = QLocalSocket()
    client.connectToServer(server_name)
    assert client.waitForConnected(2000)
    expected = "Описание: §YАрмия§!\\nAttack +5%"
    assert client.write(encode_description_message(expected)) > 0
    client.flush()

    loop = QEventLoop()
    bridge.description_received.connect(loop.quit)
    QTimer.singleShot(2000, loop.quit)
    loop.exec()

    client.disconnectFromServer()
    bridge.close()
    assert received == [expected]


def test_main_window_places_bridge_text_in_description(qapp) -> None:
    window = MainWindow(FontRepository.load(fonts_directory()))
    expected = "Армия: §Y+5%§! Attack"
    window.receive_notepad_description(expected)

    assert window.description_edit.toPlainText() == expected
    assert window.dynamic_checkbox.isChecked() is False
    assert "нестабильна" in window.dynamic_warning_label.text()
    assert window.ordinary_batch_button.isEnabled()
    assert not window.context_batch_button.isEnabled()
    assert "только фокусы" in window.batch_warning_label.text()
    assert "KEY:" in window.batch_warning_label.text()
    window.batch_warning_label.ensurePolished()
    assert (
        window.batch_warning_label.palette().color(
            window.batch_warning_label.foregroundRole()
        ).name()
        == "#b8c2ba"
    )

    window.notepad_bridge.close()
    window.close()


def test_main_window_warns_when_original_game_fonts_are_unavailable(qapp) -> None:
    repository = FontRepository.load(fonts_directory())
    fallback_repository = FontRepository(repository.fonts)
    window = MainWindow(fallback_repository)

    assert not window.game_font_warning_label.isHidden()
    assert "Не удалось найти" in window.game_font_warning_label.text()
    assert "HOI4_INSTALL_DIR" in window.game_font_warning_label.text()

    window.notepad_bridge.close()
    window.close()


def test_main_window_hides_game_font_warning_when_atlas_is_loaded(qapp) -> None:
    repository = FontRepository.load(fonts_directory())
    visual_fonts = {
        "body_en": repository.fonts["body_en"],
        "body_ru": repository.fonts["body_ru"],
    }
    loaded_repository = FontRepository(
        repository.fonts,
        visual_fonts,
        game_fonts_directory=Path("game/gfx/fonts"),
    )
    window = MainWindow(loaded_repository)

    assert window.game_font_warning_label.isHidden()

    window.notepad_bridge.close()
    window.close()


def test_batch_report_hides_yellow_rows_until_requested(qapp, tmp_path) -> None:
    del qapp
    entries = (
        FocusLocalisationEntry("Y_desc", "Y", "", "yellow", 2),
        FocusLocalisationEntry("R_desc", "R", "", "red", 3),
    )
    batch = FocusLocalisationFile(
        path=tmp_path / "focuses.txt",
        language=None,
        source_format="plain",
        entries=entries,
    )
    response = {
        "summary": {"green": 0, "yellow": 1, "red": 1, "errors": 0},
        "results": [
            {
                "ok": True,
                "result": {
                    "status": "yellow",
                    "description": {
                        "lines": 5,
                        "height_px": 90,
                        "formal_overflow_px": 20,
                        "panel_overlap_px": 0,
                    },
                },
            },
            {
                "ok": True,
                "result": {
                    "status": "red",
                    "description": {
                        "lines": 7,
                        "height_px": 126,
                        "formal_overflow_px": 56,
                        "panel_overlap_px": 13,
                    },
                },
            },
        ],
    }

    dialog = BatchResultsDialog(batch, response)

    assert dialog.table.rowCount() == 2
    assert dialog.table.isRowHidden(0)
    assert not dialog.table.isRowHidden(1)
    dialog.show_yellow_checkbox.setChecked(True)
    assert not dialog.table.isRowHidden(0)
    dialog.close()


def test_main_window_runs_plain_batch_through_validation_engine(
    qapp,
    tmp_path,
    monkeypatch,
) -> None:
    del qapp
    path = tmp_path / "focuses.txt"
    path.write_text(
        "Короткое описание.\n" + ("Очень длинное описание фокуса. " * 80),
        encoding="utf-8",
    )
    captured: list[BatchResultsDialog] = []
    monkeypatch.setattr(
        main_window_module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(path), ""),
    )

    def reject_dialog(dialog: BatchResultsDialog) -> int:
        captured.append(dialog)
        return int(QDialog.DialogCode.Rejected)

    monkeypatch.setattr(BatchResultsDialog, "exec", reject_dialog)
    window = MainWindow(FontRepository.load(fonts_directory()))

    window.check_focus_file(contextual=False)

    assert len(captured) == 1
    assert captured[0].batch.source_format == "plain"
    assert captured[0].response["summary"]["total"] == 2
    assert captured[0].response["summary"]["red"] == 1
    window.notepad_bridge.close()
    window.close()
