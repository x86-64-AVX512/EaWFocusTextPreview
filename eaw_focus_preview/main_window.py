from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QCloseEvent, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
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
from .file_loader import (
    FocusLocalisationEntry,
    FocusLocalisationFile,
    load_contextual_focus_file,
    load_focus_localisation_file,
    load_text_payload,
)
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


class BatchResultsDialog(QDialog):
    def __init__(
        self,
        batch: FocusLocalisationFile,
        response: dict[str, Any],
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.batch = batch
        self.response = response
        self.selected_entry: FocusLocalisationEntry | None = None
        self._row_entries: list[FocusLocalisationEntry | None] = []
        self._row_levels: list[str] = []
        self.setWindowTitle(f"Пакетная проверка — {batch.path.name}")
        self.resize(930, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(9)
        summary = response.get("summary", {})
        red_count = (
            int(summary.get("red", 0))
            + int(summary.get("errors", 0))
            + len(batch.errors)
        )
        self.summary_label = QLabel(
            f"Проверено описаний: {len(batch.entries)} · "
            f"зелёных: {int(summary.get('green', 0))} · "
            f"жёлтых: {int(summary.get('yellow', 0))} · "
            f"красных/ошибок: {red_count}"
        )
        self.summary_label.setObjectName("batchSummary")
        layout.addWidget(self.summary_label)

        mode_description = {
            "contextual": (
                f"Контекстный режим: найдено ID фокусов в моде — "
                f"{batch.known_focus_ids}; посторонних локализационных "
                f"значений пропущено — {batch.ignored_values}."
            ),
            "localisation": "Обычный режим: распознаны пары ключей фокусов.",
            "keyed": (
                "Обычный режим: каждая строка KEY: \"Текст\" или "
                "KEY:0 \"Текст\" проверена отдельно."
            ),
            "plain": "Обычный режим: каждая непустая строка проверена как отдельный фокус.",
        }.get(batch.source_format, "")
        mode_label = QLabel(
            mode_description
            + " По умолчанию таблица показывает только красные и ошибочные строки."
        )
        mode_label.setObjectName("hintLabel")
        mode_label.setWordWrap(True)
        layout.addWidget(mode_label)

        self.show_yellow_checkbox = QCheckBox(
            "Показывать жёлтые строки выше формального maxHeight"
        )
        self.show_yellow_checkbox.setChecked(False)
        layout.addWidget(self.show_yellow_checkbox)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            (
                "Статус",
                "Ключ",
                "Строка файла",
                "Строк в окне",
                "Высота",
                "Выход",
                "Причина",
            )
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        for error in batch.errors:
            self._add_row(
                entry=None,
                values=(
                    "КРАСНЫЙ: ОШИБКА",
                    f"Строка {error.line_number}",
                    str(error.line_number),
                    "—",
                    "—",
                    "—",
                    f"{error.message}: {error.text}",
                ),
                level="red",
            )

        results = response.get("results", [])
        for entry, wrapped in zip(batch.entries, results, strict=False):
            if not isinstance(wrapped, dict) or wrapped.get("ok") is not True:
                message = "Ошибка проверки"
                if isinstance(wrapped, dict):
                    error = wrapped.get("error")
                    if isinstance(error, dict):
                        message = str(error.get("message", message))
                self._add_row(
                    entry=entry,
                    values=(
                        "КРАСНЫЙ: ОШИБКА",
                        entry.key,
                        str(entry.line_number),
                        "—",
                        "—",
                        "—",
                        message,
                    ),
                    level="red",
                )
                continue
            result = wrapped.get("result", {})
            status = str(result.get("status", "red"))
            if status == "green":
                continue
            description = result.get("description", {})
            if not isinstance(description, dict):
                description = {}
            if status == "yellow":
                overflow = int(description.get("formal_overflow_px", 0))
                status_text = "ЖЁЛТЫЙ"
                reason = f"Выше формального maxHeight на {overflow} px"
            else:
                overflow = int(description.get("panel_overlap_px", 0))
                status_text = "КРАСНЫЙ"
                reason = f"Заходит под панель «Эффект» на {overflow} px"
            self._add_row(
                entry=entry,
                values=(
                    status_text,
                    entry.key,
                    str(entry.line_number),
                    str(description.get("lines", "—")),
                    f"{description.get('height_px', '—')} px",
                    f"{overflow} px",
                    reason,
                ),
                level=status,
            )

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.open_button = QPushButton("Открыть выбранный фокус")
        self.open_button.setEnabled(False)
        close_button = QPushButton("Закрыть")
        close_button.setObjectName("ghostButton")
        button_row.addWidget(self.open_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.table.currentCellChanged.connect(self._selection_changed)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.show_yellow_checkbox.toggled.connect(
            self._yellow_visibility_changed
        )
        self.open_button.clicked.connect(self._open_selected)
        close_button.clicked.connect(self.reject)
        for row, entry in enumerate(self._row_entries):
            if entry is not None and not self.table.isRowHidden(row):
                self.table.selectRow(row)
                break

    def _add_row(
        self,
        *,
        entry: FocusLocalisationEntry | None,
        values: tuple[str, ...],
        level: str,
    ) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._row_entries.append(entry)
        self._row_levels.append(level)
        background = QColor(80, 34, 32) if level == "red" else QColor(88, 72, 25)
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setBackground(background)
            self.table.setItem(row, column, item)
        if level == "yellow":
            self.table.setRowHidden(row, True)

    def _yellow_visibility_changed(self, visible: bool) -> None:
        for row, level in enumerate(self._row_levels):
            if level == "yellow":
                self.table.setRowHidden(row, not visible)
        current_row = self.table.currentRow()
        if current_row >= 0 and self.table.isRowHidden(current_row):
            self.table.clearSelection()
            self.table.setCurrentCell(-1, -1)
            self.open_button.setEnabled(False)
        if self.table.currentRow() < 0:
            for row, entry in enumerate(self._row_entries):
                if entry is not None and not self.table.isRowHidden(row):
                    self.table.selectRow(row)
                    break

    def _selection_changed(self, row: int, *_args: int) -> None:
        self.open_button.setEnabled(
            0 <= row < len(self._row_entries)
            and self._row_entries[row] is not None
        )

    def _open_row(self, row: int, _column: int) -> None:
        if 0 <= row < len(self._row_entries) and self._row_entries[row] is not None:
            self.table.selectRow(row)
            self._open_selected()

    def _open_selected(self) -> None:
        row = self.table.currentRow()
        if not 0 <= row < len(self._row_entries):
            return
        entry = self._row_entries[row]
        if entry is None:
            return
        self.selected_entry = entry
        self.accept()


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

        self.game_font_warning_label = QLabel(self._game_font_warning_text())
        self.game_font_warning_label.setObjectName("gameFontWarning")
        self.game_font_warning_label.setWordWrap(True)
        self.game_font_warning_label.setVisible(
            not self.repository.original_game_fonts_available
        )
        editor_layout.addWidget(self.game_font_warning_label)

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

        editor_layout.addWidget(self._field_label("Пакетная проверка файла"))
        batch_actions = QHBoxLayout()
        batch_actions.setSpacing(8)
        self.ordinary_batch_button = QPushButton("Обычный режим…")
        self.context_batch_button = QPushButton("Контекстный режим…")
        self.context_batch_button.setEnabled(self.mod_localisation is not None)
        self.context_batch_button.setToolTip(
            "Сначала выберите папку мода"
            if self.mod_localisation is None
            else "Сверить ключи с ID фокусов выбранного мода"
        )
        batch_actions.addWidget(self.ordinary_batch_button)
        batch_actions.addWidget(self.context_batch_button)
        editor_layout.addLayout(batch_actions)
        self.batch_warning_label = self._hint_label(
            "Обычный режим: файл должен содержать только фокусы, иначе "
            "возможны ложные срабатывания. Принимаются голые строки и "
            "KEY: \"Текст\" / KEY:0 \"Текст\". Контекстный режим читает "
            "ID из папки мода "
            "и требует ключ с кавычками в каждой строке."
        )
        self.batch_warning_label.setObjectName("batchWarning")
        editor_layout.addWidget(self.batch_warning_label)

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

    def _game_font_warning_text(self) -> str:
        if self.repository.game_fonts_directory is not None:
            details = (
                f" Причина: {self.repository.game_fonts_load_error}"
                if self.repository.game_fonts_load_error
                else ""
            )
            return (
                "⚠ Оригинальные шрифты HOI4 найдены, но их не удалось "
                "загрузить. Используется встроенный fallback, поэтому текст "
                f"может выглядеть более пиксельным.{details}"
            )
        return (
            "⚠ Не удалось найти оригинальные шрифты HOI4. Используется "
            "встроенный fallback, поэтому текст может выглядеть более "
            "пиксельным. Установите игру через Steam или задайте переменную "
            "HOI4_INSTALL_DIR."
        )

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
        self.ordinary_batch_button.clicked.connect(
            lambda: self.check_focus_file(contextual=False)
        )
        self.context_batch_button.clicked.connect(
            lambda: self.check_focus_file(contextual=True)
        )

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
                return
        if enabled:
            self._ensure_clausewitz_base_loaded()
        self.refresh_preview()

    def _ensure_clausewitz_base_loaded(self) -> None:
        if (
            self.mod_localisation is None
            or self.mod_localisation.base_game_root is not None
            or self.repository.game_root is None
        ):
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        load_error: str | None = None
        try:
            upgraded = ModLocalisation.load(
                self.mod_localisation.root,
                base_game_root=self.repository.game_root,
            )
            self.set_mod_localisation(upgraded)
        except (OSError, ModLocalisationError) as error:
            load_error = str(error)
        finally:
            QApplication.restoreOverrideCursor()
        if load_error is not None:
            QMessageBox.warning(
                self,
                "Не удалось загрузить данные HOI4",
                "Символический интерпретатор продолжит работу только с "
                f"файлами мода.\n\n{load_error}",
            )

    def set_mod_localisation(
        self,
        mod_localisation: ModLocalisation,
    ) -> None:
        selected_language = self.current_language
        remember_mod_directory(mod_localisation.root)
        self.mod_localisation = mod_localisation
        self.mod_path_edit.setText(str(mod_localisation.root))
        self.context_batch_button.setEnabled(True)
        self.context_batch_button.setToolTip(
            "Сверить ключи с ID фокусов выбранного мода"
        )
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

    def _apply_batch_language(self, language: str | None) -> None:
        if language is None:
            return
        language_index = self.language_combo.findData(language)
        if language_index >= 0:
            self.language_combo.setCurrentIndex(language_index)
        priority = {"russian": "ru", "english": "en"}.get(language)
        if priority is not None:
            priority_index = self.priority_combo.findData(priority)
            if priority_index >= 0:
                self.priority_combo.setCurrentIndex(priority_index)

    def check_focus_file(self, *, contextual: bool) -> None:
        if contextual and self.mod_localisation is None:
            QMessageBox.warning(
                self,
                "Сначала выберите папку мода",
                "Контекстный режим читает ID из common/national_focus и "
                "не может работать без выбранной папки мода.",
            )
            return

        initial_directory = (
            str(self.mod_localisation.root / "localisation")
            if contextual and self.mod_localisation is not None
            else ""
        )
        filename, _ = QFileDialog.getOpenFileName(
            self,
            (
                "Контекстная проверка файла фокусов"
                if contextual
                else "Обычная проверка файла фокусов"
            ),
            initial_directory,
            "Текст и локализация (*.txt *.yml *.yaml);;Все файлы (*)",
        )
        if not filename:
            return

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        try:
            path = Path(filename)
            batch = (
                load_contextual_focus_file(
                    path,
                    self.mod_localisation.root,
                )
                if contextual and self.mod_localisation is not None
                else load_focus_localisation_file(path)
            )
            self._apply_batch_language(batch.language)
            self.integration_engine.default_language = self.current_language
            response = self.integration_engine.process_document(
                {
                    "items": [
                        {
                            "id": entry.line_number,
                            "key": entry.key,
                            "title": entry.title,
                            "description": entry.description,
                            "effect": "",
                        }
                        for entry in batch.entries
                    ],
                    "glyph_priority": self.priority_combo.currentData() or "ru",
                    "language": self.current_language,
                    "policy": "visual",
                    "dynamic_localisation": self.dynamic_checkbox.isChecked(),
                }
            )
        except (OSError, ValueError) as error:
            QMessageBox.critical(
                self,
                "Не удалось проверить файл",
                str(error),
            )
            return
        finally:
            QApplication.restoreOverrideCursor()

        if not batch.entries and not batch.errors:
            details = (
                f" ID фокусов в моде: {batch.known_focus_ids}; "
                f"посторонних значений пропущено: {batch.ignored_values}."
                if contextual
                else ""
            )
            QMessageBox.warning(
                self,
                "Тексты фокусов не найдены",
                "В выбранном файле не найдено ни одного текста для проверки."
                + details,
            )
            return

        dialog = BatchResultsDialog(batch, response, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        entry = dialog.selected_entry
        if entry is None:
            return
        self.title_edit.setText(entry.title)
        self.description_edit.setPlainText(entry.description)
        self.effect_edit.clear()
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
        confidence_labels = {
            "exact": "точный символический перебор",
            "conservative": "консервативная оценка",
            "partial": "частичная оценка",
        }
        details += " · " + confidence_labels.get(
            str(report.get("confidence", "conservative")),
            "консервативная оценка",
        )
        rejected = int(report.get("incompatible_combinations", 0))
        if rejected:
            details += f" · отброшено несовместимых вариантов: {rejected}"
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
QLabel#batchWarning {
    color: #b8c2ba;
    font-size: 10px;
}
QLabel#dynamicWarning {
    color: #d7ad45;
    font-size: 10px;
}
QLabel#gameFontWarning {
    color: #f1d27a;
    background: #352d17;
    border: 1px solid #8b7131;
    border-left: 4px solid #d7ad45;
    border-radius: 6px;
    padding: 9px 10px;
    font-size: 11px;
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
