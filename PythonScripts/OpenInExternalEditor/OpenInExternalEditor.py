# By default, "OpenInExternalEditor" opens the current file with shell command, so whatever the default editor is for the file
# Unless you specify your preferred editor path with "ExternalEditor" Setting
from N10X import Editor

import os

SETTING_EditorPath:str = ""

def _OED_SettingsChanged():
    global SETTING_EditorPath
    SETTING_EditorPath = Editor.GetSetting("ExternalEditor")

def OpenInExternalEditor():
    if SETTING_EditorPath:
        os.system(SETTING_EditorPath + ' ' + Editor.GetCurrentFilename())
    else:
        os.system(Editor.GetCurrentFilename())

Editor.AddOnSettingsChangedFunction(_OED_SettingsChanged)
Editor.CallOnMainThread(_OED_SettingsChanged)
