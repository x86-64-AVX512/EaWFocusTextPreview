from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QCloseEvent, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .bmfont import FontRepository
from .dynamic_localisation import (
    DYNAMIC_LOCALISATION_WARNING,
    ModLocalisation,
    ModLocalisationError,
)
from .file_loader import load_text_payload
from .focus_canvas import FocusCanvas, PreviewDiagnostics
from .integration_api import IntegrationServer
from .mod_settings import ModSettingsError, remember_mod_directory
from .notepad_bridge import NotepadBridge
from .validation_api import (
    FocusCheckRequest,
    FocusValidationEngine,
    normalize_request,
)
from . import __version__


class DiagnosticCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("diagnosticCard")
        self.setProperty("level", "green")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(3)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("diagnosticTitle")
        self.summary_label = QLabel()
        self.summary_label.setObjectName("diagnosticSummary")
        self.details_label = QLabel()
        self.details_label.setObjectName("diagnosticDetails")
        self.details_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.details_label)

    def set_state(self, level: str, summary: str, details: str) -> None:
        self.setProperty("level", level)
        self.summary_label.setText(summary)
        self.details_label.setText(details)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class MainWindow(QMainWindow):
    def __init__(
        self,
        repository: FontRepository,
        mod_localisation: ModLocalisation | None = None,
    ):
        super().__init__()
        self.repository = repository
        self.mod_localisation = mod_localisation
        self.setWindowTitle(f"EaW Focus Text Preview {__version__}")
        self.setMinimumSize(900, 610)
        self._build_ui()
        self._connect_signals()
        self.notepad_bridge = NotepadBridge(self)
        self.notepad_bridge.description_received.connect(
            self.receive_notepad_description
        )
        self.integration_engine = FocusValidationEngine(
            repository,
            mod_localisation,
            default_language=self.current_language,
        )
        self.integration_server = IntegrationServer(
            self._handle_integration_document,
            self,
        )
        self.refresh_preview()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root_layout.addWidget(splitter)
        self.setCentralWidget(root)

        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor_scroll.setMinimumWidth(390)
        editor_widget = QWidget()
        editor_widget.setObjectName("editorPanel")
        editor_layout = QVBoxLayout(editor_widget)
        editor_layout.setContentsMargins(18, 14, 22, 18)
        editor_layout.setSpacing(10)

        heading = QLabel("Проверка текста фокуса")
        heading.setObjectName("heading")
        editor_layout.addWidget(heading)

        editor_layout.addWidget(self._field_label("Папка мода"))
        mod_row = QHBoxLayout()
        mod_row.setSpacing(8)
        self.mod_path_edit = QLineEdit()
        self.mod_path_edit.setReadOnly(True)
        self.mod_path_edit.setText(
            str(self.mod_localisation.root)
            if self.mod_localisation is not None
            else "Мод не выбран"
        )
        self.change_mod_button = QPushButton("Сменить…")
        mod_row.addWidget(self.mod_path_edit, 1)
        mod_row.addWidget(self.change_mod_button)
        editor_layout.addLayout(mod_row)

        editor_layout.addWidget(self._field_label("Название фокуса"))
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("Название")
        editor_layout.addWidget(self.title_edit)

        editor_layout.addWidget(self._field_label("Описание"))
        self.description_edit = QTextEdit()
        self.description_edit.setAcceptRichText(False)
        self.description_edit.setPlaceholderText("Текст описания фокуса")
        self.description_edit.setMinimumHeight(125)
        editor_layout.addWidget(self.description_edit)

        editor_layout.addWidget(self._field_label("Эффект"))
        self.effect_edit = QTextEdit()
        self.effect_edit.setAcceptRichText(False)
        self.effect_edit.setPlaceholderText("Эффекты и награды")
        self.effect_edit.setMinimumHeight(165)
        editor_layout.addWidget(self.effect_edit)
        editor_layout.addWidget(
            self._hint_label(
                r"Поддерживаются реальные переносы, \n и коды §Y §G §R §O §H §T §g §!."
            )
        )

        editor_layout.addWidget(self._field_label("Приоритет глифов"))
        self.priority_combo = QComboBox()
        self.priority_combo.addItem("Русский → English", "ru")
        self.priority_combo.addItem("English → Русский", "en")
        editor_layout.addWidget(self.priority_combo)

        editor_layout.addWidget(self._field_label("Язык локализации мода"))
        self.language_combo = QComboBox()
        self._populate_languages()
        editor_layout.addWidget(self.language_combo)

        self.dynamic_checkbox = QCheckBox(
            "Подставлять динамическую локализацию"
        )
        self.dynamic_checkbox.setChecked(False)
        editor_layout.addWidget(self.dynamic_checkbox)
        self.dynamic_warning_label = self._hint_label(
            DYNAMIC_LOCALISATION_WARNING
        )
        self.dynamic_warning_label.setObjectName("dynamicWarning")
        editor_layout.addWidget(self.dynamic_warning_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.load_button = QPushButton("Загрузить файл…")
        self.clear_button = QPushButton("Очистить")
        self.clear_button.setObjectName("ghostButton")
        actions.addWidget(self.load_button)
        actions.addWidget(self.clear_button)
        editor_layout.addLayout(actions)

        self.overall_card = DiagnosticCard("Общий результат")
        self.description_card = DiagnosticCard("Описание")
        self.effect_card = DiagnosticCard("Эффект")
        editor_layout.addWidget(self.overall_card)
        editor_layout.addWidget(self.description_card)
        editor_layout.addWidget(self.effect_card)

        self.missing_label = QLabel("Отсутствующие глифы: —")
        self.missing_label.setObjectName("missingLabel")
        self.missing_label.setWordWrap(True)
        editor_layout.addWidget(self.missing_label)
        self.dynamic_label = QLabel("Динамическая локализация: —")
        self.dynamic_label.setObjectName("missingLabel")
        self.dynamic_label.setWordWrap(True)
        editor_layout.addWidget(self.dynamic_label)
        editor_layout.addStretch(1)
        editor_scroll.setWidget(editor_widget)

        preview_widget = QWidget()
        preview_widget.setObjectName("previewPanel")
        preview_layout = QVBoxLayout(preview_widget)
        preview_layout.setContentsMargins(22, 14, 14, 14)
        preview_layout.setSpacing(0)
        self.canvas = FocusCanvas(
            self.repository,
            mod_localisation=self.mod_localisation,
        )
        self.canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        preview_layout.addWidget(self.canvas, 1)

        splitter.addWidget(editor_scroll)
        splitter.addWidget(preview_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([470, 650])
        self.setStyleSheet(APP_STYLE)

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _hint_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hintLabel")
        label.setWordWrap(True)
        return label

    def _connect_signals(self) -> None:
        self.title_edit.textChanged.connect(self.refresh_preview)
        self.description_edit.textChanged.connect(self.refresh_preview)
        self.effect_edit.textChanged.connect(self.refresh_preview)
        self.priority_combo.currentIndexChanged.connect(self.refresh_preview)
        self.language_combo.currentIndexChanged.connect(self.refresh_preview)
        self.dynamic_checkbox.toggled.connect(
            self._dynamic_localisation_toggled
        )
        self.clear_button.clicked.connect(self.clear_fields)
        self.load_button.clicked.connect(self.load_file)
        self.change_mod_button.clicked.connect(self.choose_mod_directory)

    @property
    def current_language(self) -> str:
        if hasattr(self, "language_combo"):
            return self.language_combo.currentData() or "russian"
        if (
            self.mod_localisation is not None
            and self.mod_localisation.available_languages
        ):
            return self.mod_localisation.available_languages[0]
        return "russian"

    def _populate_languages(self, selected: str | None = None) -> None:
        previous = selected or (
            self.language_combo.currentData()
            if self.language_combo.count()
            else None
        )
        self.language_combo.blockSignals(True)
        self.language_combo.clear()
        languages = (
            self.mod_localisation.available_languages
            if self.mod_localisation is not None
            else ("russian", "english")
        )
        labels = {
            "russian": "Русский",
            "english": "English",
        }
        for language in languages:
            self.language_combo.addItem(labels.get(language, language), language)
        target = previous or (
            "russian" if "russian" in languages else languages[0]
        )
        index = self.language_combo.findData(target)
        self.language_combo.setCurrentIndex(max(index, 0))
        self.language_combo.blockSignals(False)

    def choose_mod_directory(self) -> bool:
        initial = (
            str(self.mod_localisation.root)
            if self.mod_localisation is not None
            else ""
        )
        directory = QFileDialog.getExistingDirectory(
            self,
            "Выберите корневую папку мода Hearts of Iron IV",
            initial,
        )
        if not directory:
            return False
        try:
            mod_localisation = ModLocalisation.load(Path(directory))
        except (OSError, ModLocalisationError) as error:
            QMessageBox.warning(
                self,
                "Это не папка мода",
                str(error),
            )
            return False
        try:
            self.set_mod_localisation(mod_localisation)
        except ModSettingsError as error:
            QMessageBox.critical(
                self,
                "Не удалось сохранить settings.json",
                str(error),
            )
            return False
        return True

    def _dynamic_localisation_toggled(self, enabled: bool) -> None:
        if enabled and self.mod_localisation is None:
            if not self.choose_mod_directory():
                self.dynamic_checkbox.blockSignals(True)
                self.dynamic_checkbox.setChecked(False)
                self.dynamic_checkbox.blockSignals(False)
        self.refresh_preview()

    def set_mod_localisation(
        self,
        mod_localisation: ModLocalisation,
    ) -> None:
        selected_language = self.current_language
        remember_mod_directory(mod_localisation.root)
        self.mod_localisation = mod_localisation
        self.mod_path_edit.setText(str(mod_localisation.root))
        self._populate_languages(selected_language)
        self.canvas.set_mod_localisation(mod_localisation)
        self.integration_engine = FocusValidationEngine(
            self.repository,
            mod_localisation,
            default_language=self.current_language,
        )
        self.refresh_preview()

    def clear_fields(self) -> None:
        self.title_edit.clear()
        self.description_edit.clear()
        self.effect_edit.clear()
        self.refresh_preview()

    def receive_notepad_description(self, text: str) -> None:
        self.description_edit.setPlainText(text)

    def _handle_integration_document(self, payload: Any) -> dict[str, Any]:
        self.integration_engine.default_language = self.current_language
        response = self.integration_engine.process_document(payload)
        ui_updated = False
        if (
            isinstance(payload, dict)
            and "items" not in payload
            and response.get("ok") is True
        ):
            request = normalize_request(payload)
            if request.show:
                self.apply_external_request(request)
                ui_updated = True
        response["ui_updated"] = ui_updated
        return response

    def apply_external_request(self, request: FocusCheckRequest) -> None:
        self.title_edit.setText(request.title)
        self.description_edit.setPlainText(request.description)
        self.effect_edit.setPlainText(request.effect)
        index = self.priority_combo.findData(request.glyph_priority)
        if index >= 0:
            self.priority_combo.setCurrentIndex(index)
        language_index = self.language_combo.findData(request.language)
        if language_index >= 0:
            self.language_combo.setCurrentIndex(language_index)
        self.dynamic_checkbox.setChecked(request.dynamic_localisation)
        self.refresh_preview()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.notepad_bridge.close()
        self.integration_server.close()
        super().closeEvent(event)

    def load_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Загрузить текст",
            "",
            "Текст и локализация (*.txt *.yml *.yaml);;Все файлы (*)",
        )
        if not filename:
            return
        try:
            payload = load_text_payload(Path(filename))
        except OSError as error:
            QMessageBox.critical(
                self,
                "Не удалось открыть файл",
                str(error),
            )
            return
        if payload.title is not None:
            self.title_edit.setText(payload.title)
        if payload.description is not None:
            self.description_edit.setPlainText(payload.description)
        if payload.effect is not None:
            self.effect_edit.setPlainText(payload.effect)
        path_parts = {part.casefold() for part in Path(filename).parts}
        for language in (
            self.mod_localisation.available_languages
            if self.mod_localisation is not None
            else ()
        ):
            if language.casefold() in path_parts:
                index = self.language_combo.findData(language)
                if index >= 0:
                    self.language_combo.setCurrentIndex(index)
                break
        self.refresh_preview()

    def refresh_preview(self) -> None:
        priority = self.priority_combo.currentData() or "ru"
        language = self.current_language
        self.canvas.set_content(
            title=self.title_edit.text(),
            description=self.description_edit.toPlainText(),
            effect=self.effect_edit.toPlainText(),
            priority=priority,
            language=language,
            dynamic_localisation_enabled=self.dynamic_checkbox.isChecked(),
        )
        self.integration_engine.default_language = language
        self._update_diagnostics(self.canvas.diagnostics)
        self._update_dynamic_localisation()

    def _update_dynamic_localisation(self) -> None:
        report = self.canvas.dynamic_localisation_report
        replacements = int(report["replacement_count"])
        unresolved = report["unresolved_tokens"]
        if not report["enabled"]:
            suffix = (
                "папка мода не выбрана"
                if not report["available"]
                else "выключена"
            )
            self.dynamic_label.setText(f"Динамическая локализация: {suffix}")
            return
        details = (
            f"Динамическая локализация: подстановок {replacements}"
        )
        if unresolved:
            details += " · не разрешено: " + " ".join(unresolved)
        else:
            details += " · неразрешённых токенов нет"
        self.dynamic_label.setText(details)

    def _update_diagnostics(self, diagnostics: PreviewDiagnostics) -> None:
        if diagnostics.description_level == "green":
            description_summary = "Помещается"
        elif diagnostics.description_level == "yellow":
            description_summary = "Выше maxHeight, но до панели не дошло"
        else:
            description_summary = "Пересекает панель «Эффект»"
        description_details = (
            f"{diagnostics.description_lines} стр. · "
            f"{diagnostics.description_height} px · "
            f"выход за 70 px: {diagnostics.description_formal_overflow} px"
        )
        if diagnostics.description_panel_overlap:
            description_details += (
                f" · заход под панель: {diagnostics.description_panel_overlap} px"
            )
        self.description_card.set_state(
            diagnostics.description_level,
            description_summary,
            description_details,
        )

        effect_summary = (
            "Помещается"
            if diagnostics.effect_level == "green"
            else "Требуется вертикальная прокрутка"
        )
        effect_details = (
            f"{diagnostics.effect_lines} стр. · "
            f"{diagnostics.effect_height} px · "
            f"переполнение: {diagnostics.effect_overflow} px"
        )
        self.effect_card.set_state(
            diagnostics.effect_level,
            effect_summary,
            effect_details,
        )

        overall_text = {
            "green": "Весь текст помещается",
            "yellow": "Есть формальное переполнение описания",
            "red": "Есть визуальное пересечение или прокрутка",
        }[diagnostics.overall_level]
        self.overall_card.set_state(
            diagnostics.overall_level,
            overall_text,
            "Красный статус появляется при заходе описания под панель "
            "или при переполнении эффекта.",
        )
        missing = " ".join(diagnostics.missing_glyphs) or "—"
        self.missing_label.setText(f"Отсутствующие глифы: {missing}")


APP_STYLE = """
QWidget#appRoot {
    background: #151917;
    color: #e8ece7;
}
QWidget#editorPanel {
    background: #1b201d;
}
QWidget#previewPanel {
    background: #111513;
}
QScrollArea {
    background: #1b201d;
    border: none;
}
QSplitter::handle {
    width: 1px;
    background: #343b36;
}
QLabel#heading {
    color: #f0f3ee;
    font-size: 23px;
    font-weight: 700;
}
QLabel#fieldLabel {
    color: #cbd1cc;
    font-size: 11px;
    font-weight: 700;
}
QLabel#hintLabel {
    color: #7f8981;
    font-size: 10px;
}
QLabel#dynamicWarning {
    color: #d7ad45;
    font-size: 10px;
}
QLineEdit, QTextEdit, QComboBox {
    color: #eef1ed;
    background: #111512;
    border: 1px solid #39413b;
    border-radius: 5px;
    padding: 7px;
    selection-background-color: #587058;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: #70886f;
}
QComboBox {
    min-height: 20px;
}
QComboBox QAbstractItemView {
    color: #eef1ed;
    background: #171c19;
    selection-background-color: #425545;
}
QCheckBox {
    color: #bdc5bf;
    spacing: 6px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
}
QPushButton {
    color: #edf0ec;
    background: #38443a;
    border: 1px solid #56665a;
    border-radius: 5px;
    padding: 7px 11px;
    font-weight: 600;
}
QPushButton:hover {
    background: #465449;
}
QPushButton#ghostButton {
    color: #aeb6af;
    background: transparent;
    border-color: #3b433d;
}
QFrame#diagnosticCard {
    border: 1px solid #384039;
    border-left-width: 4px;
    border-radius: 6px;
    background: #171b18;
}
QFrame#diagnosticCard[level="green"] {
    border-left-color: #58ae61;
}
QFrame#diagnosticCard[level="yellow"] {
    border-left-color: #d7ad45;
}
QFrame#diagnosticCard[level="red"] {
    border-left-color: #d95e4d;
}
QLabel#diagnosticTitle {
    color: #aeb7b0;
    font-size: 10px;
    font-weight: 700;
}
QLabel#diagnosticSummary {
    color: #edf1ec;
    font-size: 12px;
    font-weight: 700;
}
QLabel#diagnosticDetails, QLabel#missingLabel {
    color: #8f9991;
    font-size: 10px;
}
QScrollBar:vertical {
    background: #101411;
    width: 11px;
}
QScrollBar::handle:vertical {
    background: #4e5951;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""


def apply_dark_palette(widget: QWidget) -> None:
    palette = widget.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(21, 25, 23))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(232, 236, 231))
    palette.setColor(QPalette.ColorRole.Base, QColor(17, 21, 18))
    palette.setColor(QPalette.ColorRole.Text, QColor(238, 241, 237))
    widget.setPalette(palette)
