# clang-format plugin for 10x
# Settings:
#     - "ClangFormat.Path": Path to clang-format executable, default: "clang-format.exe"
#     - "ClangFormat.Stlye": One of 'LLVM', 'GNU', 'Google', 'Chromium', 'Microsoft', 'Mozilla', 'WebKit' values
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

def ClangFormatSelection():
    settings = _ClangFormatReadSettings()

    start = N10X.Editor.GetSelectionStart()
    end = N10X.Editor.GetSelectionEnd()
    if start[1] != end[1]:
        N10X.Editor.SaveFile()
        cwd = None
        if settings.style_name == 'file':
            cwd = os.path.dirname(settings.bin_path)
        try:
            process = subprocess.Popen([settings.bin_path,
                                        '--style=' + settings.style_name,
                                        '--lines=' + str(start[1]) + ':' + str(end[1]),
                                        '-i',
                                        N10X.Editor.GetCurrentFilename()],
                            shell=True, stdin=None, stdout=None, stderr=None, 
                            close_fds=True, cwd=cwd)
            process.communicate()
        except FileNotFoundError:
            print('[ClangFormat]: clang-format executable "' + settings.bin_path + '" could not be found')    
        N10X.Editor.CheckForModifiedFiles()

#------------------------------------------------------------------------
def ClangFormatFile():
    settings = _ClangFormatReadSettings()

    N10X.Editor.SaveFile()
    try:
        cwd = None
        if settings.style_name == 'file':
            cwd = os.path.dirname(settings.bin_path)
        process = subprocess.Popen([settings.bin_path,
                                    '-style=' + settings.style_name,
                                    '-i',
                                    N10X.Editor.GetCurrentFilename()],
                            shell=True, stdin=None, stdout=None, stderr=None, 
                            close_fds=True, cwd=cwd)
        process.communicate()
    except FileNotFoundError:
         print('[ClangFormat]: clang-format executable "' + settings.bin_path + '" could not be found')
    N10X.Editor.CheckForModifiedFiles()

