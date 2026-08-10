#include "npp_api.h"
#include "quote_extract.h"

#include <shellapi.h>

#include <cstdint>
#include <string>
#include <string_view>
#include <vector>


namespace {

constexpr wchar_t PLUGIN_NAME[] = L"EaW Focus Bridge";
constexpr wchar_t PIPE_PATH[] = L"\\\\.\\pipe\\EaWFocusTextPreview";
constexpr std::uint32_t MAX_MESSAGE_BYTES = 8u * 1024u * 1024u;

HINSTANCE module_instance = nullptr;
NppData notepad_data{};
bool error_was_shown = false;

void show_usage() {
    MessageBoxW(
        notepad_data._nppHandle,
        L"Чтобы отправить текст в поле описания:\n\n"
        L"зажмите Alt и дважды щёлкните левой кнопкой мыши "
        L"внутри текста в двойных кавычках.\n\n"
        L"Других способов отправки плагин не добавляет.",
        L"EaW Focus Bridge 0.7.7F1",
        MB_OK | MB_ICONINFORMATION
    );
}

FuncItem commands[1]{
    {L"Как отправить описание…", show_usage, 0, false, nullptr}
};


std::wstring module_path() {
    std::vector<wchar_t> buffer(32768);
    const DWORD length = GetModuleFileNameW(
        module_instance,
        buffer.data(),
        static_cast<DWORD>(buffer.size())
    );
    if (length == 0 || length >= buffer.size()) {
        return {};
    }
    return std::wstring(buffer.data(), length);
}


std::wstring directory_of(const std::wstring& path) {
    const std::size_t separator = path.find_last_of(L"\\/");
    return separator == std::wstring::npos ? std::wstring{} : path.substr(0, separator);
}


std::wstring configured_executable() {
    const std::wstring plugin_directory = directory_of(module_path());
    if (plugin_directory.empty()) {
        return {};
    }
    const std::wstring ini_path = plugin_directory + L"\\EaWFocusBridge.ini";
    std::vector<wchar_t> value(32768);
    const DWORD length = GetPrivateProfileStringW(
        L"Bridge",
        L"ExePath",
        L"",
        value.data(),
        static_cast<DWORD>(value.size()),
        ini_path.c_str()
    );
    if (length == 0 || length >= value.size() - 1) {
        return {};
    }
    return std::wstring(value.data(), length);
}


void show_error_once(const wchar_t* message) {
    if (error_was_shown) {
        return;
    }
    error_was_shown = true;
    MessageBoxW(
        notepad_data._nppHandle,
        message,
        L"EaW Focus Bridge 0.7.7F1",
        MB_OK | MB_ICONERROR
    );
}


bool launch_preview() {
    const std::wstring executable = configured_executable();
    if (
        executable.empty()
        || GetFileAttributesW(executable.c_str()) == INVALID_FILE_ATTRIBUTES
    ) {
        show_error_once(
            L"Не найден EaWFocusTextPreview.exe.\n"
            L"Повторно запустите Install_NotepadPP_Integration.bat "
            L"из папки программы."
        );
        return false;
    }
    const std::wstring working_directory = directory_of(executable);
    const HINSTANCE result = ShellExecuteW(
        notepad_data._nppHandle,
        L"open",
        executable.c_str(),
        nullptr,
        working_directory.c_str(),
        SW_SHOWNORMAL
    );
    if (reinterpret_cast<std::intptr_t>(result) <= 32) {
        show_error_once(L"Не удалось запустить EaW Focus Text Preview.");
        return false;
    }
    return true;
}


HANDLE open_pipe() {
    return CreateFileW(
        PIPE_PATH,
        GENERIC_WRITE,
        0,
        nullptr,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        nullptr
    );
}


bool write_all(HANDLE pipe, const void* source, DWORD size) {
    const auto* bytes = static_cast<const unsigned char*>(source);
    DWORD written_total = 0;
    while (written_total < size) {
        DWORD written = 0;
        if (
            !WriteFile(
                pipe,
                bytes + written_total,
                size - written_total,
                &written,
                nullptr
            )
            || written == 0
        ) {
            return false;
        }
        written_total += written;
    }
    return true;
}


bool send_description(std::string_view text) {
    if (text.size() > MAX_MESSAGE_BYTES) {
        show_error_once(L"Описание слишком велико для передачи.");
        return false;
    }

    HANDLE pipe = open_pipe();
    if (pipe == INVALID_HANDLE_VALUE) {
        if (!launch_preview()) {
            return false;
        }
        if (!WaitNamedPipeW(PIPE_PATH, 120000)) {
            show_error_once(L"Программа запущена, но канал передачи не открылся.");
            return false;
        }
        pipe = open_pipe();
    }
    if (pipe == INVALID_HANDLE_VALUE) {
        show_error_once(L"Не удалось подключиться к EaW Focus Text Preview.");
        return false;
    }

    const std::uint32_t length = static_cast<std::uint32_t>(text.size());
    const bool sent = write_all(pipe, &length, sizeof(length))
        && (length == 0 || write_all(pipe, text.data(), length));
    CloseHandle(pipe);
    if (!sent) {
        show_error_once(L"Не удалось передать описание в программу.");
    }
    return sent;
}


bool alt_is_the_only_modifier(const SCNotification& notification) {
    const bool alt_down =
        (notification.modifiers & SCMOD_ALT) != 0
        || (GetAsyncKeyState(VK_MENU) & 0x8000) != 0;
    const bool ctrl_down =
        (notification.modifiers & SCMOD_CTRL) != 0
        || (GetAsyncKeyState(VK_CONTROL) & 0x8000) != 0;
    const bool shift_down =
        (notification.modifiers & SCMOD_SHIFT) != 0
        || (GetAsyncKeyState(VK_SHIFT) & 0x8000) != 0;
    return alt_down && !ctrl_down && !shift_down;
}


void handle_double_click(const SCNotification& notification) {
    if (!alt_is_the_only_modifier(notification) || notification.position < 0) {
        return;
    }

    const HWND scintilla = static_cast<HWND>(notification.nmhdr.hwndFrom);
    if (
        scintilla != notepad_data._scintillaMainHandle
        && scintilla != notepad_data._scintillaSecondHandle
    ) {
        return;
    }

    const auto position = notification.position;
    const auto line = static_cast<Sci_Position>(
        SendMessageW(scintilla, SCI_LINEFROMPOSITION, position, 0)
    );
    const auto line_start = static_cast<Sci_Position>(
        SendMessageW(scintilla, SCI_POSITIONFROMLINE, line, 0)
    );
    const auto line_end = static_cast<Sci_Position>(
        SendMessageW(scintilla, SCI_GETLINEENDPOSITION, line, 0)
    );
    if (line_start < 0 || line_end < line_start || position < line_start) {
        return;
    }

    const auto byte_count = static_cast<std::size_t>(line_end - line_start);
    if (byte_count > MAX_MESSAGE_BYTES) {
        return;
    }
    std::vector<char> buffer(byte_count + 1, '\0');
    Sci_TextRangeFull range{{line_start, line_end}, buffer.data()};
    SendMessageW(
        scintilla,
        SCI_GETTEXTRANGEFULL,
        0,
        reinterpret_cast<LPARAM>(&range)
    );

    std::string extracted;
    const auto relative_position = static_cast<std::size_t>(position - line_start);
    if (
        eaw_extract_quoted_value(
            std::string_view(buffer.data(), byte_count),
            relative_position,
            extracted
        )
    ) {
        send_description(extracted);
    }
}

}  // namespace


BOOL APIENTRY DllMain(HINSTANCE instance, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        module_instance = instance;
        DisableThreadLibraryCalls(instance);
    }
    return TRUE;
}


extern "C" __declspec(dllexport) void setInfo(NppData data) {
    notepad_data = data;
}


extern "C" __declspec(dllexport) const wchar_t* getName() {
    return PLUGIN_NAME;
}


extern "C" __declspec(dllexport) FuncItem* getFuncsArray(int* count) {
    if (count != nullptr) {
        *count = 1;
    }
    return commands;
}


extern "C" __declspec(dllexport) void beNotified(SCNotification* notification) {
    if (notification != nullptr && notification->nmhdr.code == SCN_DOUBLECLICK) {
        handle_double_click(*notification);
    }
}


extern "C" __declspec(dllexport) LRESULT messageProc(UINT, WPARAM, LPARAM) {
    return TRUE;
}


extern "C" __declspec(dllexport) BOOL isUnicode() {
    return TRUE;
}
