"""
auto dark mode for 10x (10xeditor.com)
Version: 0.1.0
Original Script author: https://github.com/krupitskas

To get started go to Settings.10x_settings, and enable plugin, by adding these line:
    AutoDarkMode.Enabled: True

Then specify color schemes you like as example below:

    AutoDarkMode.Light: Light
    AutoDarkMode.Dark: Sunset
"""

import winreg

from N10X import Editor

class AutoDarkModePlugin():
    is_enabled = False
    last_theme = None
    light_theme = False
    dark_theme = False
    reg_key = None

autodark_plugin = None

def IntializeAutoDarkMode():
    global autodark_plugin

    autodark_plugin = AutoDarkModePlugin()

    autodark_plugin.is_enabled = Editor.GetSetting('AutoDarkMode.Enabled').strip().lower() == 'true'
    autodark_plugin.light_theme = Editor.GetSetting('AutoDarkMode.Light').strip()
    autodark_plugin.dark_theme = Editor.GetSetting('AutoDarkMode.Dark').strip()
    autodark_plugin.reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")

    CheckCurrentTheme()

def CheckCurrentTheme():
    global autodark_plugin

    if not autodark_plugin.is_enabled:
        return

    value, _ = winreg.QueryValueEx(autodark_plugin.reg_key, "AppsUseLightTheme")

    is_light = value == 1

    if autodark_plugin.last_theme != is_light:
        if is_light:
            Editor.SetSetting('ColorScheme', autodark_plugin.light_theme)
        else:
            Editor.SetSetting('ColorScheme', autodark_plugin.dark_theme)

    autodark_plugin.last_theme = is_light

Editor.CallOnMainThread(IntializeAutoDarkMode) 
Editor.AddUpdateFunction(CheckCurrentTheme)  
