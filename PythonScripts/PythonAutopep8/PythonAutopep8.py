# ------------------------------------------------------------------------
import sys
import N10X
import subprocess
import re
import os

"""
autopep8 python formatter for 10x (10xeditor.com)
Version: 0.1.0
Original Script author: https://github.com/andersama

To get started go to Settings.10x_settings, and enable the hooks, by adding these lines:
    Autopep8.HookPostSave: true

This script assumes autopep8.exe is in your path! To change this modify Autopep8.Path

Autopep8_Options:
    - Autopep8.HookPostSave: (default=False) Hooks autopep8 into post save events
    - Autopep8.Path:                         Path to autopep8 executable or directory
"""

try:
    import autopep8
except ImportError:
    # NOTE: this silently fails if autopep8 is missing requirements!
    # If you want to save some time, install autopep8.py and its requirements under
    # C:/Program Files/PureDevSoftware/10x/Lib/site-packages (this saves about .1 seconds per 10x launch)
    # pip install "--target=C:/Program Files/PureDevSoftware/10x/Lib/site-packages" autopep8
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


def autopep8_installed():
    autopep8_exe = N10X.Editor.GetSetting("Autopep8.Path").strip()
    if not autopep8_exe:
        autopep8_exe = "autopep8"
    if os.path.isdir(autopep8_exe):
        autopep8_exe = os.path.join(autopep8_exe, "autopep8.exe")

    txt = run_cmd([autopep8_exe, "--version"])
    r = re.search(r"autopep8 .+", txt)
    return r != None and len(r.group(0)) > 0


def autopep8_installed_py():
    txt = run_cmd(["python", "-m", "autopep8", "--version"])
    r = re.search(r"autopep8 .+", txt)
    return r != None and len(r.group(0)) > 0


def OnPythonSavedCMD(filename: str):
    if filename.endswith(".py"):
        print("Formatting {0} using autopep8".format(filename))
        stdtxt = run_cmd(["autopep8", "-i", filename])


def OnPythonSavedModule(filename: str):
    if filename.endswith(".py"):
        print("Formatting {0} using autopep8".format(filename))

        autopep8.fix_file(
            filename,
            options=autopep8.parse_args([filename, "--in-place"], apply_config=True),
        )


def OnPythonSavedPy(filename: str):
    if filename.endswith(".py"):
        print("Formatting {0} using autopep8".format(filename))
        stdtxt = run_cmd(["python", "-m", "autopep8", "-i", filename])


def InitializeAutopep8():
    module_available = "autopep8" in sys.modules
    autopep8_hooked_txt = N10X.Editor.GetSetting("Autopep8.HookPostSave")
    autopep8_hooked = autopep8_hooked_txt and autopep8_hooked_txt.lower() == "true"

    if not autopep8_hooked:
        print("autopep8 disabled")
        return

    if module_available and autopep8_hooked:
        print("autopep8 module enabled")
        N10X.Editor.AddPostFileSaveFunction(OnPythonSavedModule)
        return
    # NOTE: when imported this script runs WAY faster, commandline execution has pretty bad latency from using subprocess
    print(
        "autopep8 falling back to cmdline, be sure to install autopep8.py and pycodestyle.py packages under: C:/Program Files/PureDevSoftware/10x/Lib/site-packages"
    )
    autopep8_cmd_enabled = autopep8_installed()
    autopep8_py_enabled = False
    if not autopep8_cmd_enabled:
        autopep8_py_enabled = autopep8_installed_py()
    print(
        "autopep8 {0}".format(
            "enabled"
            if (autopep8_cmd_enabled or autopep8_py_enabled) and autopep8_hooked
            else "disabled"
        )
    )

    if autopep8_cmd_enabled and autopep8_hooked:
        N10X.Editor.AddPostFileSaveFunction(OnPythonSavedCMD)
    elif autopep8_py_enabled and autopep8_hooked:
        N10X.Editor.AddPostFileSaveFunction(OnPythonSavedPY)
    elif autopep8_hooked:
        print("Could not verify autopep8 was installed configure Autopep8.Path")


N10X.Editor.CallOnMainThread(InitializeAutopep8)
