#------------------------------------------------------------------------
import N10X
import array

#------------------------------------------------------------------------
g_TabWidth = 0
g_OnSettingsChangedRegistered = False

#------------------------------------------------------------------------
def GetTabWidth():
     return int(N10X.Editor.GetSetting("TabWidth"))

#------------------------------------------------------------------------
def OnSettingsChanged():
    global g_TabWidth

    g_TabWidth = GetTabWidth()

#------------------------------------------------------------------------
def UntabifyLines(fn):
    global g_TabWidth
    global g_OnSettingsChangedRegistered

    if not g_OnSettingsChangedRegistered:
        g_TabWidth = GetTabWidth()

        N10X.Editor.AddOnSettingsChangedFunction(OnSettingsChanged)
        g_OnSettingsChangedRegistered = True

    N10X.Editor.PushUndoGroup()
    N10X.Editor.BeginTextUpdate()

    line_count = N10X.Editor.GetLineCount()

    sequence = [' '] * g_TabWidth
    width = ''.join(sequence)

    for i in range(line_count):
        line = N10X.Editor.GetLine(i)
        line  = line.replace('\t', width)
        N10X.Editor.SetLine(i, line)

    N10X.Editor.EndTextUpdate()
    N10X.Editor.PopUndoGroup()

#------------------------------------------------------------------------
# uncomment this line to replace all tabs with 'TabWidth' spaces on save
N10X.Editor.AddPreFileSaveFunction(UntabifyLines)
