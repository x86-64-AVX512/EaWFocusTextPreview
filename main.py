from __future__ import annotations

import os
from pathlib import Path
import sys


def _automation_mode(arguments: list[str]) -> bool:
    return (
        "--smoke-test" in arguments
        or "--render-preview" in arguments
        or "--integration-smoke-test" in arguments
    )


def _option_value(arguments: list[str], name: str) -> str | None:
    if name not in arguments:
        return None
    index = arguments.index(name)
    if index + 1 >= len(arguments):
        return ""
    return arguments[index + 1]


def main(arguments: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if _automation_mode(arguments):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox

    from eaw_focus_preview.bmfont import FontRepository
    from eaw_focus_preview.dynamic_localisation import (
        ModLocalisation,
        ModLocalisationError,
    )
    from eaw_focus_preview.main_window import MainWindow, apply_dark_palette
    from eaw_focus_preview.mod_settings import (
        ModSettingsError,
        remembered_mod_directory,
        remember_mod_directory,
    )
    from eaw_focus_preview.paths import fonts_directory
    from eaw_focus_preview import __version__

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication([sys.argv[0]])
    app.setApplicationName("EaW Focus Text Preview")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("EaW Local Tools")
    app.setStyle("Fusion")

    try:
        repository = FontRepository.load(fonts_directory())
    except Exception as error:
        if _automation_mode(arguments):
            return 2
        QMessageBox.critical(
            None,
            "Не удалось загрузить bitmap-шрифты",
            f"{error}\n\nОжидалась папка: {fonts_directory()}",
        )
        return 2

    mod_localisation = None
    requested_mod_path = _option_value(arguments, "--mod-path")
    if requested_mod_path == "":
        if _automation_mode(arguments):
            return 8
        QMessageBox.critical(
            None,
            "Не указана папка мода",
            "После --mod-path нужно указать корневую папку мода.",
        )
        return 8

    if requested_mod_path is not None:
        try:
            mod_localisation = ModLocalisation.load(Path(requested_mod_path))
        except (OSError, ModLocalisationError) as error:
            if _automation_mode(arguments):
                return 8
            QMessageBox.critical(None, "Это не папка мода", str(error))
            return 8
        try:
            remember_mod_directory(mod_localisation.root)
        except ModSettingsError as error:
            if not _automation_mode(arguments):
                QMessageBox.critical(
                    None,
                    "Не удалось сохранить settings.json",
                    str(error),
                )
            return 8
    else:
        try:
            remembered = remembered_mod_directory()
        except ModSettingsError as error:
            remembered = None
            if not _automation_mode(arguments):
                QMessageBox.warning(None, "Ошибка settings.json", str(error))
        if remembered is not None:
            try:
                mod_localisation = ModLocalisation.load(remembered)
            except (OSError, ModLocalisationError) as error:
                if _automation_mode(arguments):
                    return 8
                QMessageBox.warning(
                    None,
                    "Папка мода недоступна",
                    f"{error}\n\nВыберите папку заново.",
                )

    window = MainWindow(repository, mod_localisation)
    apply_dark_palette(window)

    if "--render-preview" in arguments:
        index = arguments.index("--render-preview")
        if index + 1 >= len(arguments):
            return 3
        destination = Path(arguments[index + 1]).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        return 0 if window.canvas.render_preview().save(str(destination)) else 4

    if "--smoke-test" in arguments:
        preview = window.canvas.render_preview()
        return 0 if not preview.isNull() and preview.size().width() == 550 else 5

    if "--integration-smoke-test" in arguments:
        if not window.integration_server.available:
            return 6
        window.integration_server.response_sent.connect(
            lambda: QTimer.singleShot(100, app.quit)
        )
        QTimer.singleShot(15000, lambda: app.exit(7))
        return app.exec()

    screen = app.primaryScreen()
    if screen is not None:
        available = screen.availableGeometry()
        width = min(1320, max(900, available.width() - 60))
        height = min(850, max(610, available.height() - 70))
        window.resize(width, height)
        window.move(
            available.x() + max(0, (available.width() - width) // 2),
            available.y() + max(0, (available.height() - height) // 2),
        )
    else:
        window.resize(1200, 780)
    window.show()
    return app.exec()


if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "EaW.FocusTextPreview.1"
            )
        except (AttributeError, OSError):
            pass
    raise SystemExit(main())
