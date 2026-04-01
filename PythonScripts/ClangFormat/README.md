## clang-format plugin for 10x

### Settings
- **ClangFormat.Path**: Path to clang-format executable, default: "clang-format.exe"
- **ClangFormat.Style**: One of 'LLVM', 'GNU', 'Google', 'Chromium', 'Microsoft', 'Mozilla', 'WebKit' values, or 'file' if you are providing a .clang-format file in your project
- **ClangFormat.OnSave**: 'true' or 'false'. When true, clang-format is called on every file save
- **ClangFormat.OnSaveExtensions**: Comma-separated list of file extensions to auto-format on save. Defaults to C and C++ source and header extensions
