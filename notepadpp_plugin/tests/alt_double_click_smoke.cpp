#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cwchar>


namespace {

constexpr UINT SCI_GETLINEENDPOSITION = 2136;
constexpr UINT SCI_POSITIONFROMLINE = 2167;

struct WindowSearch {
    HWND result = nullptr;
};

BOOL CALLBACK find_test_window(HWND window, LPARAM parameter) {
    if (!IsWindowVisible(window)) {
        return TRUE;
    }
    wchar_t class_name[64]{};
    wchar_t title[1024]{};
    GetClassNameW(window, class_name, 64);
    GetWindowTextW(window, title, 1024);
    if (
        std::wcscmp(class_name, L"Notepad++") == 0
        && std::wcsstr(title, L"notepad_bridge_sample.yml") != nullptr
    ) {
        reinterpret_cast<WindowSearch*>(parameter)->result = window;
        return FALSE;
    }
    return TRUE;
}

bool send_mouse_button() {
    INPUT inputs[2]{};
    inputs[0].type = INPUT_MOUSE;
    inputs[0].mi.dwFlags = MOUSEEVENTF_LEFTDOWN;
    inputs[1].type = INPUT_MOUSE;
    inputs[1].mi.dwFlags = MOUSEEVENTF_LEFTUP;
    return SendInput(2, inputs, sizeof(INPUT)) == 2;
}

bool send_alt(bool down) {
    INPUT input{};
    input.type = INPUT_KEYBOARD;
    input.ki.wVk = VK_MENU;
    input.ki.dwFlags = down ? 0 : KEYEVENTF_KEYUP;
    return SendInput(1, &input, sizeof(INPUT)) == 1;
}

bool send_escape() {
    INPUT inputs[2]{};
    inputs[0].type = INPUT_KEYBOARD;
    inputs[0].ki.wVk = VK_ESCAPE;
    inputs[1].type = INPUT_KEYBOARD;
    inputs[1].ki.wVk = VK_ESCAPE;
    inputs[1].ki.dwFlags = KEYEVENTF_KEYUP;
    return SendInput(2, inputs, sizeof(INPUT)) == 2;
}

bool move_mouse_to(POINT point) {
    const int left = GetSystemMetrics(SM_XVIRTUALSCREEN);
    const int top = GetSystemMetrics(SM_YVIRTUALSCREEN);
    const int width = GetSystemMetrics(SM_CXVIRTUALSCREEN);
    const int height = GetSystemMetrics(SM_CYVIRTUALSCREEN);
    if (width <= 1 || height <= 1) {
        return false;
    }

    INPUT input{};
    input.type = INPUT_MOUSE;
    input.mi.dx = MulDiv(point.x - left, 65535, width - 1);
    input.mi.dy = MulDiv(point.y - top, 65535, height - 1);
    input.mi.dwFlags =
        MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK;
    return SendInput(1, &input, sizeof(INPUT)) == 1;
}

}  // namespace


int wmain(int argc, wchar_t** argv) {
    const bool with_alt = !(argc > 1 && std::wcscmp(argv[1], L"--without-alt") == 0);

    WindowSearch search;
    EnumWindows(find_test_window, reinterpret_cast<LPARAM>(&search));
    if (search.result == nullptr) {
        return 2;
    }

    const HWND scintilla = FindWindowExW(search.result, nullptr, L"Scintilla", nullptr);
    if (scintilla == nullptr) {
        return 3;
    }

    const LRESULT line_start = SendMessageW(
        scintilla,
        SCI_POSITIONFROMLINE,
        1,
        0
    );
    const LRESULT line_end = SendMessageW(
        scintilla,
        SCI_GETLINEENDPOSITION,
        1,
        0
    );
    if (line_start < 0 || line_end <= line_start) {
        return 4;
    }

    // Две трети тестовой строки гарантированно лежат внутри двойных кавычек.
    const LRESULT position = line_start + ((line_end - line_start) * 2 / 3);
    POINT point{
        static_cast<LONG>(SendMessageW(scintilla, 2164, 0, position)),
        static_cast<LONG>(SendMessageW(scintilla, 2165, 0, position)),
    };
    if (!ClientToScreen(scintilla, &point)) {
        return 5;
    }

    ShowWindow(search.result, SW_RESTORE);
    SetForegroundWindow(search.result);
    send_escape();
    Sleep(150);
    if (!move_mouse_to(point)) {
        return 6;
    }
    Sleep(50);

    if (with_alt && !send_alt(true)) {
        return 7;
    }
    const bool first = send_mouse_button();
    Sleep(60);
    const bool second = send_mouse_button();
    if (with_alt) {
        send_alt(false);
    }
    return first && second ? 0 : 8;
}
