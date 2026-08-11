from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


def _configure_console() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _add_request_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="JSON-файл или - для stdin",
    )
    parser.add_argument("--title", help="Название; создаёт одиночный запрос")
    parser.add_argument("--description", help="Описание; создаёт одиночный запрос")
    parser.add_argument("--effect", help="Эффект; создаёт одиночный запрос")
    parser.add_argument(
        "--glyph-priority",
        choices=("ru", "en"),
        help="Приоритет атласов: ru или en",
    )
    parser.add_argument(
        "--language",
        help="Язык локализации мода, например russian или english",
    )
    dynamic_group = parser.add_mutually_exclusive_group()
    dynamic_group.add_argument(
        "--dynamic-localisation",
        dest="dynamic_localisation",
        action="store_const",
        const=True,
        default=None,
        help=(
            "Включить экспериментальную динамическую локализацию; "
            "требует settings.json с папкой мода"
        ),
    )
    dynamic_group.add_argument(
        "--no-dynamic-localisation",
        dest="dynamic_localisation",
        action="store_const",
        const=False,
        help="Явно отключить динамическую локализацию во входном JSON",
    )
    parser.add_argument(
        "--policy",
        choices=("visual", "strict"),
        help="visual: жёлтый допустим; strict: допустим только зелёный",
    )
    parser.add_argument(
        "--jsonl",
        action="store_true",
        help="Читать и писать по одному JSON-объекту на строку",
    )
    parser.add_argument("-o", "--output", help="Файл результата вместо stdout")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Форматировать обычный JSON с отступами",
    )


def _build_parser(version: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="EaWFocusTextPreviewCLI",
        description=(
            "Машиночитаемая проверка текста национального фокуса "
            "тем же bitmap-движком, что и GUI."
        ),
    )
    parser.add_argument("--version", action="version", version=version)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "check",
        help="Проверить локально, не запуская окно",
    )
    _add_request_options(check)

    send = subparsers.add_parser(
        "send",
        help="Проверить через API уже запущенного окна",
    )
    _add_request_options(send)
    send.add_argument(
        "--show",
        action="store_true",
        help="Также вставить одиночный запрос в видимый редактор",
    )
    send.add_argument(
        "--timeout-ms",
        type=int,
        default=5000,
        help="Тайм-аут подключения и ответа (по умолчанию 5000)",
    )
    send.add_argument(
        "--launch",
        action="store_true",
        help="Запустить GUI, если нужно, перед подключением",
    )
    return parser


def _read_documents(args: argparse.Namespace) -> list[Any]:
    direct = any(
        value is not None
        for value in (args.title, args.description, args.effect)
    )
    if direct:
        return [
            {
                "title": args.title or "",
                "description": args.description or "",
                "effect": args.effect or "",
            }
        ]

    if args.input == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.input).read_text(encoding="utf-8-sig")

    if args.jsonl:
        documents: list[Any] = []
        for line_number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                documents.append(json.loads(line))
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Некорректный JSONL в строке {line_number}: {error}"
                ) from error
        return documents

    try:
        return [json.loads(text)]
    except json.JSONDecodeError as error:
        raise ValueError(f"Некорректный JSON: {error}") from error


def _apply_overrides(document: Any, args: argparse.Namespace) -> Any:
    if isinstance(document, list):
        return [_apply_overrides(item, args) for item in document]
    if not isinstance(document, dict):
        return document

    result = dict(document)
    if args.policy is not None:
        result["policy"] = args.policy
    if args.glyph_priority is not None:
        result["glyph_priority"] = args.glyph_priority
    if args.language is not None:
        result["language"] = args.language
    if args.dynamic_localisation is not None:
        result["dynamic_localisation"] = args.dynamic_localisation
    if args.command == "send" and args.show:
        result["show"] = True
    return result


def _uses_dynamic_localisation(
    document: Any,
    inherited: bool = False,
) -> bool:
    if isinstance(document, list):
        return any(
            _uses_dynamic_localisation(item, inherited)
            for item in document
        )
    if not isinstance(document, dict):
        return False
    enabled = document.get("dynamic_localisation", inherited)
    items = document.get("items")
    if isinstance(items, list):
        return any(
            _uses_dynamic_localisation(item, enabled is True)
            for item in items
        )
    return enabled is True


def _write_responses(
    responses: list[dict[str, Any]],
    args: argparse.Namespace,
) -> None:
    if args.jsonl:
        text = "\n".join(
            json.dumps(response, ensure_ascii=False, separators=(",", ":"))
            for response in responses
        )
        if responses:
            text += "\n"
    else:
        response: Any = responses[0] if len(responses) == 1 else responses
        text = json.dumps(
            response,
            ensure_ascii=False,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
        text += "\n"

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
        sys.stdout.flush()


def _local_check(
    documents: list[Any],
    selected_path: Path | None,
) -> list[dict[str, Any]]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from eaw_focus_preview.bmfont import FontRepository
    from eaw_focus_preview.dynamic_localisation import ModLocalisation
    from eaw_focus_preview.paths import fonts_directory
    from eaw_focus_preview.validation_api import FocusValidationEngine

    app = QApplication.instance()
    if app is None:
        app = QApplication([sys.argv[0]])
    repository = FontRepository.load(fonts_directory())
    mod_localisation = (
        ModLocalisation.load(
            selected_path,
            base_game_root=repository.game_root,
        )
        if selected_path is not None
        else None
    )
    engine = FocusValidationEngine(repository, mod_localisation)
    return [engine.process_document(document) for document in documents]


def _launch_gui() -> subprocess.Popen[bytes]:
    if getattr(sys, "frozen", False):
        executable = Path(sys.executable).with_name("EaWFocusTextPreview.exe")
        command = [str(executable)]
    else:
        executable = Path(__file__).with_name("main.py")
        command = [sys.executable, str(executable)]
    if not executable.exists():
        raise FileNotFoundError(f"GUI не найден: {executable}")

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        command,
        cwd=str(executable.parent),
        creationflags=creationflags,
    )


def _send_documents(
    documents: list[Any],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    from PySide6.QtCore import QCoreApplication

    from eaw_focus_preview.integration_api import (
        IntegrationConnectionError,
        send_pipe_document,
    )

    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([sys.argv[0]])

    if args.launch:
        _launch_gui()

    responses: list[dict[str, Any]] = []
    for document in documents:
        deadline = time.monotonic() + max(args.timeout_ms, 1) / 1000
        while True:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            try:
                response = send_pipe_document(
                    document,
                    timeout_ms=min(remaining_ms, 350),
                )
                responses.append(response)
                break
            except IntegrationConnectionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
    return responses


def _combined_exit_code(responses: list[dict[str, Any]]) -> int:
    from eaw_focus_preview.validation_api import response_exit_code

    codes = [response_exit_code(response) for response in responses]
    if 2 in codes:
        return 2
    if 1 in codes:
        return 1
    return 0


def main(arguments: list[str] | None = None) -> int:
    _configure_console()
    from eaw_focus_preview import __version__
    from eaw_focus_preview.dynamic_localisation import (
        DYNAMIC_LOCALISATION_WARNING,
    )
    from eaw_focus_preview.validation_api import error_response

    parser = _build_parser(__version__)
    args = parser.parse_args(arguments)

    try:
        documents = [
            _apply_overrides(document, args)
            for document in _read_documents(args)
        ]
        if not documents:
            raise ValueError("Вход не содержит ни одного запроса")
        dynamic_requested = any(
            _uses_dynamic_localisation(document)
            for document in documents
        )
        selected_mod_path = None
        if dynamic_requested:
            from eaw_focus_preview.mod_settings import required_mod_directory

            selected_mod_path = required_mod_directory()
            sys.stderr.write(f"Предупреждение: {DYNAMIC_LOCALISATION_WARNING}\n")
            sys.stderr.flush()
        if args.command == "check":
            responses = _local_check(documents, selected_mod_path)
        else:
            responses = _send_documents(documents, args)
        _write_responses(responses, args)
        return _combined_exit_code(responses)
    except Exception as error:
        response = error_response(str(error), code="cli_error")
        _write_responses([response], args)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
