// App-local CPython entry point. No Python code or native inference code is changed.
// An UTF-8 process manifest also covers static C runtimes inside native libraries.
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>
#include <string>

int wmain(int argc, wchar_t** argv) {
    wchar_t path[32768];
    DWORD length = GetModuleFileNameW(nullptr, path, 32768);
    if (!length || length >= 32768) return 110;
    std::wstring executable(path, length);
    const auto separator = executable.find_last_of(L"\\/");
    if (separator == std::wstring::npos) return 111;
    const std::wstring directory = executable.substr(0, separator + 1);
    // Store the directory as a wide-character DLL-directory entry rather than
    // relying on a semicolon-delimited search string derived from the app path.
    SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    AddDllDirectory(directory.c_str());
    // _ctypes is used before Python-side bootstrap. Preload its app-local
    // dependency by its exact path, including literal semicolons and percent signs.
    LoadLibraryExW((directory + L"libffi-8.dll").c_str(), nullptr,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    std::wstring dll = directory + L"python312.dll";
    HMODULE python = LoadLibraryExW(dll.c_str(), nullptr,
        LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!python) {
        std::fwprintf(stderr, L"Cannot load bundled python312.dll (%lu).\n", GetLastError());
        return 112;
    }
    using PythonMain = int (__cdecl*)(int, wchar_t**);
    const auto main = reinterpret_cast<PythonMain>(GetProcAddress(python, "Py_Main"));
    if (!main) return 113;
    return main(argc, argv);
}
