# By default, "OpenInExternalEditor" opens the current file with shell command, so whatever the default editor is for the file
# Unless you specify your preferred editor path with "ExternalEditor" Setting
from N10X import Editor

import subprocess

SETTING_EditorPath:str = ""

def _OED_SettingsChanged():
    global SETTING_EditorPath
    SETTING_EditorPath = Editor.GetSetting("ExternalEditor")

def OpenInExternalEditor():
    if SETTING_EditorPath:
        subprocess.Popen(SETTING_EditorPath + ' ' + Editor.GetCurrentFilename(), shell=True, stdin=None, stdout=None, stderr=None, close_fds=True)
    else:
        subprocess.Popen(Editor.GetCurrentFilename(), shell=True, stdin=None, stdout=None, stderr=None, close_fds=True)

Editor.AddOnSettingsChangedFunction(_OED_SettingsChanged)
Editor.CallOnMainThread(_OED_SettingsChanged)
