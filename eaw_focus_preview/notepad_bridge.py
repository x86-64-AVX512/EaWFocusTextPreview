from __future__ import annotations

from collections.abc import Callable
import struct

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


PIPE_NAME = "EaWFocusTextPreview"
MAX_MESSAGE_BYTES = 8 * 1024 * 1024
_LENGTH = struct.Struct("<I")


def encode_description_message(text: str) -> bytes:
    payload = text.encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ValueError("Текст слишком велик для Notepad++ bridge")
    return _LENGTH.pack(len(payload)) + payload


class NotepadBridge(QObject):
    """Принимает UTF-8 описания через Windows named pipe от Notepad++."""

    description_received = Signal(str)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        server_name: str = PIPE_NAME,
    ):
        super().__init__(parent)
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
            socket.abort()
            socket.deleteLater()
        self._buffers.clear()
        self.server.close()

    def _accept_connections(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(self._reader_for(socket))
            socket.disconnected.connect(self._disconnect_for(socket))

    def _reader_for(self, socket: QLocalSocket) -> Callable[[], None]:
        return lambda: self._read_socket(socket)

    def _disconnect_for(self, socket: QLocalSocket) -> Callable[[], None]:
        return lambda: self._drop_socket(socket)

    def _read_socket(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))

        while len(buffer) >= _LENGTH.size:
            payload_size = _LENGTH.unpack_from(buffer)[0]
            if payload_size > MAX_MESSAGE_BYTES:
                socket.abort()
                self._drop_socket(socket)
                return
            frame_size = _LENGTH.size + payload_size
            if len(buffer) < frame_size:
                return
            payload = bytes(buffer[_LENGTH.size:frame_size])
            del buffer[:frame_size]
            self.description_received.emit(payload.decode("utf-8", errors="replace"))

    def _drop_socket(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        socket.deleteLater()
