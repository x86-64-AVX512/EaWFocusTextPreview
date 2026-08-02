from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import struct
import time
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .validation_api import error_response


PIPE_NAME = "EaWFocusTextPreview.API.v1"
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
_LENGTH = struct.Struct("<I")


class IntegrationConnectionError(RuntimeError):
    pass


def encode_json_frame(payload: Any) -> bytes:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ValueError("JSON-сообщение превышает допустимый размер 8 МБ")
    return _LENGTH.pack(len(encoded)) + encoded


class IntegrationServer(QObject):
    """Двусторонний локальный JSON API поверх Windows named pipe."""

    response_sent = Signal()

    def __init__(
        self,
        handler: Callable[[Any], Mapping[str, Any]],
        parent: QObject | None = None,
        *,
        server_name: str = PIPE_NAME,
    ):
        super().__init__(parent)
        self.handler = handler
        self.server_name = server_name
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._accept_connections)
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self.available = self.server.listen(server_name)
        self.error = "" if self.available else self.server.errorString()

    @property
    def full_server_name(self) -> str:
        return self.server.fullServerName()

    def close(self) -> None:
        for socket in tuple(self._buffers):
            self._buffers.pop(socket, None)
            try:
                socket.readyRead.disconnect()
                socket.disconnected.disconnect()
            except (RuntimeError, TypeError):
                pass
            socket.abort()
            socket.deleteLater()
        self.server.close()

    def _accept_connections(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda socket=socket: self._read_socket(socket))
            socket.disconnected.connect(
                lambda socket=socket: self._drop_socket(socket)
            )

    def _read_socket(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))

        while len(buffer) >= _LENGTH.size:
            payload_size = _LENGTH.unpack_from(buffer)[0]
            if payload_size > MAX_MESSAGE_BYTES:
                self._send_response(
                    socket,
                    error_response(
                        "JSON-сообщение превышает допустимый размер 8 МБ",
                        code="message_too_large",
                    ),
                )
                socket.disconnectFromServer()
                return

            frame_size = _LENGTH.size + payload_size
            if len(buffer) < frame_size:
                return
            raw_payload = bytes(buffer[_LENGTH.size:frame_size])
            del buffer[:frame_size]
            response = self._handle_payload(raw_payload)
            self._send_response(socket, response)

    def _handle_payload(self, raw_payload: bytes) -> Mapping[str, Any]:
        try:
            payload = json.loads(raw_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return error_response(
                f"Некорректный UTF-8 JSON: {error}",
                code="invalid_json",
            )

        try:
            return self.handler(payload)
        except Exception as error:
            return error_response(
                f"Внутренняя ошибка проверки: {error}",
                code="internal_error",
            )

    def _send_response(
        self,
        socket: QLocalSocket,
        response: Mapping[str, Any],
    ) -> None:
        try:
            frame = encode_json_frame(response)
        except (TypeError, ValueError) as error:
            frame = encode_json_frame(
                error_response(
                    f"Не удалось сериализовать ответ: {error}",
                    code="internal_error",
                )
            )
        socket.write(frame)
        socket.flush()
        self.response_sent.emit()

    def _drop_socket(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        socket.deleteLater()


def send_pipe_document(
    payload: Any,
    *,
    server_name: str = PIPE_NAME,
    timeout_ms: int = 5000,
) -> dict[str, Any]:
    """Синхронно отправляет один JSON-документ и получает один ответ."""

    deadline = time.monotonic() + max(timeout_ms, 1) / 1000
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(_remaining_ms(deadline)):
        raise IntegrationConnectionError(
            f"Не удалось подключиться к {server_name}: {socket.errorString()}"
        )

    try:
        socket.write(encode_json_frame(payload))
        if not socket.waitForBytesWritten(_remaining_ms(deadline)):
            raise IntegrationConnectionError(
                f"Не удалось отправить запрос: {socket.errorString()}"
            )

        header = _read_exact(socket, _LENGTH.size, deadline)
        payload_size = _LENGTH.unpack(header)[0]
        if payload_size > MAX_MESSAGE_BYTES:
            raise IntegrationConnectionError(
                "Ответ превышает допустимый размер 8 МБ"
            )
        raw_response = _read_exact(socket, payload_size, deadline)
        response = json.loads(raw_response.decode("utf-8"))
        if not isinstance(response, dict):
            raise IntegrationConnectionError("API вернул не JSON-объект")
        return response
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IntegrationConnectionError(
            f"API вернул некорректный JSON: {error}"
        ) from error
    finally:
        socket.disconnectFromServer()
        socket.waitForDisconnected(100)


def _remaining_ms(deadline: float) -> int:
    return max(1, int((deadline - time.monotonic()) * 1000))


def _read_exact(
    socket: QLocalSocket,
    size: int,
    deadline: float,
) -> bytes:
    result = bytearray()
    while len(result) < size:
        available = int(socket.bytesAvailable())
        if available:
            result.extend(bytes(socket.read(min(size - len(result), available))))
            continue
        remaining = _remaining_ms(deadline)
        if time.monotonic() >= deadline or not socket.waitForReadyRead(remaining):
            raise IntegrationConnectionError(
                f"Тайм-аут при чтении ответа: {socket.errorString()}"
            )
    return bytes(result)
