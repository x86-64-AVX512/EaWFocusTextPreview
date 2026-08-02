#pragma once

#define WIN32_LEAN_AND_MEAN
#include <windows.h>

#include <cstddef>
#include <cstdint>

// Минимальный ABI-срез актуальных официальных заголовков Notepad++ и
// Scintilla. Используются только типы и сообщения, необходимые bridge.
using Sci_Position = std::ptrdiff_t;
using uptr_t = std::uintptr_t;

constexpr unsigned int SCI_GETTEXTRANGEFULL = 2039;
constexpr unsigned int SCI_GETLINEENDPOSITION = 2136;
constexpr unsigned int SCI_LINEFROMPOSITION = 2166;
constexpr unsigned int SCI_POSITIONFROMLINE = 2167;
constexpr unsigned int SCN_DOUBLECLICK = 2006;

constexpr int SCMOD_SHIFT = 1;
constexpr int SCMOD_CTRL = 2;
constexpr int SCMOD_ALT = 4;

struct Sci_CharacterRangeFull {
    Sci_Position cpMin;
    Sci_Position cpMax;
};

struct Sci_TextRangeFull {
    Sci_CharacterRangeFull chrg;
    char* lpstrText;
};

struct Sci_NotifyHeader {
    void* hwndFrom;
    uptr_t idFrom;
    unsigned int code;
};

// Для SCN_DOUBLECLICK нужны только поля до modifiers включительно.
struct SCNotification {
    Sci_NotifyHeader nmhdr;
    Sci_Position position;
    int ch;
    int modifiers;
};

struct NppData {
    HWND _nppHandle;
    HWND _scintillaMainHandle;
    HWND _scintillaSecondHandle;
};

using PFUNCPLUGINCMD = void(__cdecl*)();

struct ShortcutKey {
    bool _isCtrl;
    bool _isAlt;
    bool _isShift;
    unsigned char _key;
};

constexpr int menuItemSize = 64;

struct FuncItem {
    wchar_t _itemName[menuItemSize];
    PFUNCPLUGINCMD _pFunc;
    int _cmdID;
    bool _init2Check;
    ShortcutKey* _pShKey;
};
