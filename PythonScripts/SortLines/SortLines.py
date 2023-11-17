#------------------------------------------------------------------------
# From https://gitlab.com/bogez57/10x_editor/-/blob/main/PythonScripts/Utils.py
# (expired link)

def SortLines():

    N10X.Editor.PushUndoGroup()

    lines = []
    line_count = N10X.Editor.GetLineCount()

    for i in range(line_count):
        lines.append(N10X.Editor.GetLine(i))

    lines.sort()

    for i in range(line_count):
        N10X.Editor.SetLine(i, lines[i])

    N10X.Editor.PopUndoGroup()

