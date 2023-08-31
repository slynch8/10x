import N10X
import os

SAVE_ON_FOCUS_LOST_SETTING = "SaveOnFocusLost"
FORMAT_ON_SAVE_SETTING = "FormatOnSave"

g_conf_save_on_focus_lost = False
g_conf_format_on_save = False

skip_next_update = False
prev_focused_file = 'empty'
focused_file = 'empty'

def OnFocusLost(file_path):
  if file_path == 'empty' or file_path == '':
    return
  N10X.Editor.SaveFile()

def InitSettings():
  global g_conf_save_on_focus_lost
  global g_conf_format_on_save

  g_conf_save_on_focus_lost = N10X.Editor.GetSetting(SAVE_ON_FOCUS_LOST_SETTING) == "true"
  g_conf_format_on_save =  N10X.Editor.GetSetting(FORMAT_ON_SAVE_SETTING) == "true"

def OnUpdate():
  global g_conf_save_on_focus_lost
  if not g_conf_save_on_focus_lost:
    return

  global skip_next_update
  global focused_file
  global prev_focused_file

  if skip_next_update:
    skip_next_update = False
    return

  if focused_file == N10X.Editor.GetCurrentFilename():
    return

  skip_next_update = True
  prev_focused_file = focused_file
  focused_file = N10X.Editor.GetCurrentFilename()
  if focused_file == 'empty' or focused_file == '':
    return

  if prev_focused_file == 'empty':
    return

  N10X.Editor.FocusFile(prev_focused_file)
  OnFocusLost(prev_focused_file)
  N10X.Editor.FocusFile(focused_file)
  return 

def OnPreSave(file_path):
  global g_conf_format_on_save
  if not g_conf_format_on_save:
    return
  N10X.Editor.ExecuteCommand("FormatFile")
  print('[saved]') 

N10X.Editor.AddOnSettingsChangedFunction(InitSettings)
N10X.Editor.CallOnMainThread(InitSettings)
N10X.Editor.AddUpdateFunction(OnUpdate)
N10X.Editor.AddPreFileSaveFunction(OnPreSave)