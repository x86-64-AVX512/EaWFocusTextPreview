from __future__ import annotations

import json
from pathlib import Path
import sys

from PySide6.QtCore import QCoreApplication, QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eaw_focus_preview.notepad_bridge import NotepadBridge


def main() -> int:
    app = QCoreApplication(sys.argv)
    bridge = NotepadBridge()
    if not bridge.available:
        print(json.dumps({"error": bridge.error}, ensure_ascii=False), flush=True)
        return 2

    result = {"exit_code": 3}

    def receive(text: str) -> None:
        print(json.dumps({"text": text}, ensure_ascii=True), flush=True)
        result["exit_code"] = 0
        app.quit()

    bridge.description_received.connect(receive)
    QTimer.singleShot(10_000, app.quit)
    app.exec()
    bridge.close()
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
