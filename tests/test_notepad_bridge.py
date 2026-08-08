from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtNetwork import QLocalSocket

from eaw_focus_preview.notepad_bridge import (
    NotepadBridge,
    encode_description_message,
)
from eaw_focus_preview.bmfont import FontRepository
from eaw_focus_preview.main_window import MainWindow
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
