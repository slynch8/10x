# ------------------------------------------------------------------------
import sys
import N10X
import subprocess
import re
import os
import shutil
from pathlib import Path

"""
black python formatter for 10x (10xeditor.com)
Version: 0.1.0
Original Script author: https://github.com/andersama

To get started go to Settings.10x_settings, and enable the hooks, by adding these lines:
    Black.HookPostSave: true

This script assumes black.exe is in your path! To change this modify Black.Path

Black_Options:
    - Black.HookPostSave: (default=False) Hooks black into post save events
    - Black.Path:                         Path to black executable or directory
"""

try:
    import black
except ImportError:
    # NOTE: this silently fails if black is missing requirements!
    # If you want to save some time, install black and its requirements under
    # C:/Program Files/PureDevSoftware/10x/Lib/site-packages (this saves about .1 seconds per 10x launch)
    # pip install "--target=C:/Program Files/PureDevSoftware/10x/Lib/site-packages" black
    pass


def run_cmd(cmd_args, working_dir=None) -> str:
    if working_dir == None:
        process = subprocess.Popen(
            cmd_args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf8"
        )
    else:
        process = subprocess.Popen(
            cmd_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=working_dir,
            encoding="utf8",
        )

    returncode = process.wait()
    result = process.stdout.read()
    return result


def black_installed():
    black_exe = N10X.Editor.GetSetting("Black.Path").strip()
    if black_exe == None or not black_exe:
        black_exe = shutil.which("black")
    if black_exe == None or len(black_exe) <= 0:
        return False
    if os.path.isdir(black_exe):
        black_exe = os.path.join(black_exe, "black.exe")
    if not exists(black_exe):
        return False

    txt = run_cmd([black_exe, "--version"])
    r = re.search(r"black.+", txt)
    v = re.search(r"\\d+[.]\\d+[.]\\d+", txt)

    return r != None and len(r.group(0)) > 0 and v != None and len(v.group(0)) > 0


def black_python_installed():
    txt = run_cmd(["python", "-m", "black", "--version"])
    r = re.search(r"black.+", txt)
    v = re.search(r"[0-9]+[.][0-9]+[.][0-9]+.+", txt)
    return r != None and len(r.group(0)) > 0 and v != None and len(v.group(0)) > 0


def OnPythonSavedPY(filename: str):
    if filename.endswith(".py"):
        print("Formatting {0} using black".format(filename))
        stdtxt = run_cmd(["python", "-m", "black", filename])


def OnPythonSavedCMD(filename: str):
    if filename.endswith(".py"):
        print("Formatting {0} using black".format(filename))
        stdtxt = run_cmd([black_exe, filename])


def OnPythonSavedModule(filename: str):
    if filename.endswith(".py"):
        print("Formatting {0} using black".format(filename))

        black.format_file_in_place(
            Path(filename), fast=True, mode=black.Mode(), write_back=black.WriteBack.YES
        )


def InitializeBlack():
    module_available = "black" in sys.modules
    black_hooked_txt = N10X.Editor.GetSetting("Black.HookPostSave")
    black_hooked = black_hooked_txt and black_hooked_txt.lower() == "true"

    if not black_hooked:
        print("black disabled")
        return

    if module_available and black_hooked:
        print("black module enabled")
        N10X.Editor.AddPostFileSaveFunction(OnPythonSavedModule)
        return
    # NOTE: when imported this script runs WAY faster, commandline execution has pretty bad latency from using subprocess
    print(
        "black falling back to cmdline, be sure to install black package under: C:/Program Files/PureDevSoftware/10x/Lib/site-packages"
    )
    black_cmd_enabled = black_installed()
    black_py_enabled = False
    if not black_cmd_enabled:
        black_py_enabled = black_python_installed()

    print(
        "black {0}".format(
            "enabled"
            if (black_cmd_enabled or black_py_enabled) and black_hooked
            else "disabled"
        )
    )

    if black_cmd_enabled and black_hooked:
        N10X.Editor.AddPostFileSaveFunction(OnPythonSavedCMD)
    elif black_py_enabled and black_hooked:
        N10X.Editor.AddPostFileSaveFunction(OnPythonSavedPY)
    elif black_hooked:
        print("Could not verify black was installed configure Black.Path")


N10X.Editor.CallOnMainThread(InitializeBlack)
