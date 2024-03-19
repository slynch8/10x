#------------------------------------------------------------------------
# From https://gitlab.com/bogez57/10x_editor/-/blob/main/PythonScripts/Utils.py
# (expired link)

import N10X

def SortLines(CaseInsensitive=True):

    N10X.Editor.PushUndoGroup()

    lines = []
    line_count = N10X.Editor.GetLineCount()

    for i in range(line_count):
        lines.append(N10X.Editor.GetLine(i))

    if CaseInsensitive == True:
        lines.sort(key=str.lower)
    else:
        lines.sort()


    for i in range(line_count):
        N10X.Editor.SetLine(i, lines[i])

    N10X.Editor.PopUndoGroup()

def SortSelectedLines(CaseInsensitive=True):

    N10X.Editor.PushUndoGroup()

    start_pos = N10X.Editor.GetSelectionStart()
    end_pos = N10X.Editor.GetSelectionEnd()
    
    # +1 due to indexing starting at 0
    line_count = end_pos[1] - start_pos[1] + 1

    # strange indexing causes strange behaviour
    # remove prior +1 to ignore to jank line
    if end_pos[0] == 0: 
        line_count -= 1

    # ignore if there are no lines to sort
    if line_count == 0:
        return

    lines = []

    for i in range(line_count):
        lines.append(N10X.Editor.GetLine(i + start_pos[1]))

    if CaseInsensitive == True:
        lines.sort(key=str.lower)
    else:
        lines.sort()

    for i in range(line_count):
        N10X.Editor.SetLine(i + start_pos[1], lines[i])

    N10X.Editor.PopUndoGroup()
