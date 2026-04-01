# clang-format plugin for 10x
# Settings:
#     - "ClangFormat.Path": Path to clang-format executable, default: "clang-format.exe"
#     - "ClangFormat.Style": One of 'LLVM', 'GNU', 'Google', 'Chromium', 'Microsoft', 'Mozilla', 'WebKit' values
#                            Or 'file' if you are providing .clang-format file in your project
#     - "ClangFormat.OnSave": 'true' or 'false'. When true, clang-format is called on save
#     - "ClangFormat.OnSaveExtensions": comma-separated list of extensions allowed to auto-format on save
#
import subprocess
import os
import N10X
from typing import NamedTuple

CLANGFORMAT_EXE = "clang-format.exe"

class ClangFormatConfig(NamedTuple):
    bin_path : str
    style_name : str

def _ClangFormatReadSettings():
    bin_path = N10X.Editor.GetSetting("ClangFormat.Path")
    style_name = N10X.Editor.GetSetting("ClangFormat.Style")

    if not bin_path:
        bin_path = CLANGFORMAT_EXE

    if not style_name:
        style_name = "file"

    return ClangFormatConfig(bin_path, style_name)


def _ClangFormat(file, line_range=None):
    settings = _ClangFormatReadSettings()

    try:
        cwd = None
        if settings.style_name == 'file':
            cwd = os.path.dirname(file) or None

        command = [settings.bin_path,
                   '--style=' + settings.style_name,
                   '-i']

        if line_range is not None:
            start = line_range[0]
            end = line_range[1]
            if start != end:
                command.append('--lines=' + str(start) + ':' + str(end))

        command.append(file)

        process = subprocess.Popen(command,
                            shell=True, stdin=None, stdout=None, stderr=subprocess.PIPE,
                            close_fds=True, cwd=cwd,
                            creationflags=subprocess.CREATE_NO_WINDOW)
        _, stderr = process.communicate()
        if process.returncode != 0:
            print('[ClangFormat]: clang-format failed (exit code ' + str(process.returncode) + ')')
            if stderr:
                print('[ClangFormat]: ' + stderr.decode(errors='replace'))
    except FileNotFoundError:
        print('[ClangFormat]: clang-format executable "' + settings.bin_path + '" could not be found')


def ClangFormatSelection():
    start = N10X.Editor.GetSelectionStart()[1]
    end = N10X.Editor.GetSelectionEnd()[1]
    if start != end:
        N10X.Editor.SaveFile()
        _ClangFormat(N10X.Editor.GetCurrentFilename(), (start, end))


#------------------------------------------------------------------------
def ClangFormatFile():
    N10X.Editor.SaveFile()
    _ClangFormat(N10X.Editor.GetCurrentFilename())


#------------------------------------------------------------------------
def ClangFormatPostSave(file):
    if N10X.Editor.GetSetting("ClangFormat.OnSave") != "true":
        return

    EXTS = [
        ".c", ".cc", ".cpp", ".c++", ".cp", ".cxx",
        ".h", ".hh", ".hpp", ".h++",".hp",".hxx",
        ".inl",".ixx"
    ]
    extensions = N10X.Editor.GetSetting("ClangFormat.OnSaveExtensions")
    if not extensions:
        extensions = EXTS
    else:
        extensions = [e.strip() for e in extensions.split(",")]

    if any(file.endswith(ext) for ext in extensions):
        _ClangFormat(file)


N10X.Editor.AddPostFileSaveFunction(ClangFormatPostSave)
