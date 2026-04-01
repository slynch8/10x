# clang-format plugin for 10x
# Settings:
#     - "ClangFormat.Path": Path to clang-format executable, default: "clang-format.exe"
#     - "ClangFormat.Style": One of 'LLVM', 'GNU', 'Google', 'Chromium', 'Microsoft', 'Mozilla', 'WebKit' values
#                            Or 'file' if you are providing .clang-format file in your project
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
            cwd = os.path.dirname(settings.bin_path)

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
                            shell=True, stdin=None, stdout=None, stderr=None,
                            close_fds=True, cwd=cwd)
        process.communicate()
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
