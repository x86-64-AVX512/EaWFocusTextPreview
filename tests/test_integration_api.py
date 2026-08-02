from __future__ import annotations

import json
import struct
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtNetwork import QLocalSocket

from eaw_focus_preview.bmfont import FontRepository
from eaw_focus_preview.integration_api import (
    IntegrationServer,
    encode_json_frame,
)
from eaw_focus_preview.main_window import MainWindow
from eaw_focus_preview.validation_api import FocusValidationEngine


PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LENGTH = struct.Struct("<I")


def _read_frame(client: QLocalSocket) -> dict:
    raw = bytes(client.readAll())
    assert len(raw) >= _LENGTH.size
    payload_size = _LENGTH.unpack_from(raw)[0]
    payload = raw[_LENGTH.size:_LENGTH.size + payload_size]
    assert len(payload) == payload_size
    return json.loads(payload.decode("utf-8"))


def test_named_pipe_api_returns_framed_json(qapp) -> None:
    repository = FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    engine = FocusValidationEngine(repository)
    server_name = f"EaWFocusTextPreview-API-test-{uuid4().hex}"
    server = IntegrationServer(
        engine.process_document,
        server_name=server_name,
    )
    assert server.available

    client = QLocalSocket()
    client.connectToServer(server_name)
    assert client.waitForConnected(2000)
    request = {
        "id": "pipe-1",
        "description": "Армия: §Y+5%§! Attack",
    }
    assert client.write(encode_json_frame(request)) > 0
    client.flush()

    loop = QEventLoop()
    client.readyRead.connect(loop.quit)
    QTimer.singleShot(2000, loop.quit)
    loop.exec()

    response = _read_frame(client)
    client.disconnectFromServer()
    client.waitForDisconnected(500)
    server.close()
    qapp.processEvents()

    assert response["ok"] is True
    assert response["result"]["id"] == "pipe-1"
    assert response["result"]["fits"] is True
    assert response["result"]["missing_glyphs"] == []


def test_show_request_updates_visible_editor(qapp) -> None:
    window = MainWindow(
        FontRepository.load(PROJECT_ROOT / "assets" / "fonts")
    )
    response = window._handle_integration_document(
        {
            "title": "ПИОНЕРЫ",
            "description": "Армия: +5% Attack",
            "effect": "Событие.",
            "glyph_priority": "en",
            "show": True,
        }
    )

    assert response["ok"] is True
    assert response["ui_updated"] is True
    assert window.title_edit.text() == "ПИОНЕРЫ"
    assert window.description_edit.toPlainText() == "Армия: +5% Attack"
    assert window.effect_edit.toPlainText() == "Событие."
    assert window.priority_combo.currentData() == "en"
    window.close()
