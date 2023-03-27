#------------------------------------------------------------------------
import os
import N10X
import re
import win32clipboard

#------------------------------------------------------------------------
# Vim style editing
#
# To enable Vim editing set Vim to true in the 10x settings file
#
#------------------------------------------------------------------------
g_VimEnabled = False

class Mode:
    INSERT      = 0
    NORMAL      = 1
    VISUAL      = 2
    VISUAL_LINE = 3



g_Mode = Mode.INSERT
g_VisualModeStartPos = None

g_HandingKey = False

def IsVisual():
    global g_Mode
    return g_Mode == Mode.VISUAL or g_Mode == Mode.VISUAL_LINE


g_CommandStr = ''
g_HandleIntercepts = True
g_LastSearch = None


#------------------------------------------------------------------------
# Helpers

#------------------------------------------------------------------------
def clamp(min_val, max_val, n):
   return max(min(n, max_val), min_val)

def MaxLineX(y=None):
    if y is None:
      _, y = N10X.Editor.GetCursorPos()

    return len(N10X.Editor.GetLine(y)) - 2

def MaxY():
    return max(0, N10X.Editor.GetLineCount() - 1)

def MoveCursorWithinRange(x=None, y=None, max_offset=1):
    if x is None:
      x, _ = N10X.Editor.GetCursorPos()
    if y is None:
      _, y = N10X.Editor.GetCursorPos()

    y = clamp(0, MaxY(), y)
    x = clamp(0, MaxLineX(y) - max_offset, x)

    N10X.Editor.SetCursorPos((x, y))

def MoveCursorWithinRangeDelta(x_delta=0, y_delta=0, max_offset=1):
    x, y = N10X.Editor.GetCursorPos()
    x += x_delta
    y += y_delta
    MoveCursorWithinRange(x, y, max_offset)

def MoveCursorXOrWrap(x):
    _, y = N10X.Editor.GetCursorPos()

    if x > MaxLineX(y):
      x = 0
      y += 1

    if y >= MaxY():
      y = MaxY()
      N10X.Editor.SetCursorPos((MaxLineX(y), y))
    else:
      N10X.Editor.SetCursorPos((x, y))

def MoveCursorXOrWrapDelta(x_delta):
    if x_delta == 0:
      return

    x, y = N10X.Editor.GetCursorPos()

    # NOTE(Brandon): We max the line length with 1
    # because on empty lines we don't want to skip.
    def MaxLineMin1(y):
      return max(MaxLineX(y), 1)

    x += x_delta
    if x_delta > 0:
        while y <= MaxY() and x > MaxLineMin1(y) - 1:
            x = x - MaxLineMin1(y)
            y += 1

        if y > MaxY():
            y = MaxY()
            N10X.Editor.SetCursorPos((MaxLineX(y), y))
            return
    else:
        while y >= 0 and x < 0:
            y -= 1
            if y < 0:
                x = 0
            else:
                x = MaxLineMin1(y) + x
 
        if y < 0:
            N10X.Editor.SetCursorPos((0, 0))
            return

    N10X.Editor.SetCursorPos((x, y))
 
def FindNextOccurrenceForward(c):
    x, y = N10X.Editor.GetCursorPos()

    x += 1

    line = N10X.Editor.GetLine(y)
    if x >= len(line):
        return None

    line = line[x:]
    index = line.find(c)
    if index < 0:
        return None

    return x + index

def FindNextOccurrenceBackward(c):
    x, y = N10X.Editor.GetCursorPos()

    line = N10X.Editor.GetLine(y)
    if x < 0:
        return None

    line = line[:x]
    index = line.rfind(c)
    if index < 0:
        return None

    return index

def FindToNextOccurrenceForward(c):
    x, y = N10X.Editor.GetCursorPos()

    x += 1

    line = N10X.Editor.GetLine(y)
    if x >= len(line):
        return None

    line = line[x:]
    index = line.find(c)
    if index < 0:
        return None

    index -= 1

    return x + index

def FindToNextOccurrenceBackward(c):
    x, y = N10X.Editor.GetCursorPos()

    line = N10X.Editor.GetLine(y)
    if x < 0:
        return None

    line = line[:x]
    index = line.rfind(c)
    if index < 0:
        return None

    index += 1

    return index

def PerformLineSearch(action, search):
    global g_LastSearch
    if action == ';' and g_LastSearch:
        PerformLineSearch(g_LastSearch[0], g_LastSearch[1])
        return True
        
    if not search:
        return False

    if action == 'f':
        MoveCursorWithinRange(x=FindNextOccurrenceForward(search))
    elif action == 'F':
        MoveCursorWithinRange(x=FindNextOccurrenceBackward(search))
    elif action == 't':
        MoveCursorWithinRange(x=FindToNextOccurrenceForward(search))
    elif action == 'T':
        MoveCursorWithinRange(x=FindToNextOccurrenceBackward(search))
    else:
        return False

    g_LastSearch = action + search
    return True
            

def ClipboardNoTrailingNewline():
    win32clipboard.OpenClipboard()
    try:
        data = str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT))
        if data[-1:] == '\n':
            win32clipboard.SetClipboardText(data.rstrip(), win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return data
        else:
            win32clipboard.CloseClipboard()
            return None
    except:
        print("Failed to get clipboard of non-unicode text!")
        win32clipboard.CloseClipboard()
        return None
def RestoreClipboard(content):
    win32clipboard.OpenClipboard()
    win32clipboard.SetClipboardText(content, win32clipboard.CF_UNICODETEXT)
    win32clipboard.CloseClipboard()

def SendKey(k):
    global g_HandleIntercepts
    g_HandleIntercepts = False
    N10X.Editor.SendKey(k)
    g_HandleIntercepts = True


#------------------------------------------------------------------------
# Modes

#------------------------------------------------------------------------
def EnterInsertMode():
    global g_Mode
    if g_Mode != Mode.INSERT:
        g_Mode = Mode.INSERT
        N10X.Editor.ResetCursorBlink()

#------------------------------------------------------------------------
def EnterCommandMode():
    global g_Mode
    global g_CommandStr
    if g_Mode != Mode.NORMAL:
        N10X.Editor.ClearSelection()
        was_visual = IsVisual()
        g_Mode = Mode.NORMAL
        g_CommandStr = ""
        N10X.Editor.ResetCursorBlink()

        if not was_visual:
            MoveCursorWithinRangeDelta(x_delta=-1)

#------------------------------------------------------------------------
def EnterVisualMode(mode):
    global g_Mode
    global g_VisualModeStartPos
    if g_Mode != mode:
        g_Mode = mode
        g_VisualModeStartPos = N10X.Editor.GetCursorPos()

    UpdateVisualModeSelection()

#------------------------------------------------------------------------
def SetSelection(start, end, cursor_index=0):
    if end[1] < start[1] or (end[1] == start[1] and end[0] < start[0]):
        end, start = start, end

    N10X.Editor.SetSelection(start, (end[0] + 1, end[1]), cursor_index=cursor_index)

def SetLineSelection(start, end, cursor_index=0):
    start_line = min(start, end)
    end_line = max(start, end)
    N10X.Editor.SetSelection((0, start_line), (0, end_line + 1), cursor_index=cursor_index)

def UpdateVisualModeSelection():
    global g_Mode
    global g_VisualModeStartPos

    end = N10X.Editor.GetCursorPos()

    start = g_VisualModeStartPos
    if g_Mode == Mode.VISUAL:
        SetSelection(start, end, cursor_index=1)
    elif g_Mode == Mode.VISUAL_LINE:
        SetLineSelection(start[1], end[1], cursor_index=1)

    N10X.Editor.SetCursorVisible(1, False)

def SubmitVisualModeSelection():
    start_pos, end_pos = N10X.Editor.GetCursorSelection(cursor_index=1)
    EnterCommandMode()
    N10X.Editor.SetSelection(start_pos, end_pos)
    return start_pos, end_pos

def GetCharacterClass(c):
    # TODO: This is what is recommended for C files... No idea if it's correct
    if re.match('[a-zA-Z0-9_]', c):
        return 2
    if c.isspace(): 
        return 0
    return 1

def MoveNextWordStart(wrap=True):
    x, y = N10X.Editor.GetCursorPos()

    contents = N10X.Editor.GetLine(y)
    contents = contents[x:]
    i = 1

    if contents:
        character_class = GetCharacterClass(contents[0])
        while character_class > 0 and \
            i < len(contents) and \
            GetCharacterClass(contents[i]) == character_class:
                i += 1

    x += i
    if x >= MaxLineX(y):
        if not wrap:
            MoveCursorWithinRange(x=MaxLineX(y), y=y, max_offset=0)
            return False 
        y += 1
        x = 0
        if y > MaxY():
            y = MaxY()
            MoveCursorWithinRange(x=MaxLineX(y), y=y)
            return True

    contents = N10X.Editor.GetLine(y)
    while x < MaxLineX(y) and contents[x].isspace():
        x += 1

    MoveCursorWithinRange(x=x, y=y)
    return x < MaxLineX(y)

def MoveNextWordEnd(wrap=True):
    x, y = N10X.Editor.GetCursorPos()

    contents = N10X.Editor.GetLine(y)
    contents = contents[:x]
    i = 1

    if contents:
        character_class = GetCharacterClass(contents[0])
        while character_class > 0 and \
            i < len(contents) and \
            GetCharacterClass(contents[i]) == character_class:
                i += 1

    x += i
    if x >= MaxLineX(y):
        y += 1
        x = 0
        if y > MaxY():
            y = MaxY()
            MoveCursorWithinRange(x=MaxLineX(y) - 1, y=y)
            return

    contents = N10X.Editor.GetLine(y)
    while x < MaxLineX(y) and contents[x].isspace():
        x += 1

    MoveCursorWithinRange(x=x, y=y)
                

#------------------------------------------------------------------------
# Command Functions

#------------------------------------------------------------------------
def MoveToStartOfFile():
    MoveCursorWithinRange(y=0)

#------------------------------------------------------------------------
def MoveToEndOfFile():
    MoveCursorWithinRange(y=MaxY())

#------------------------------------------------------------------------
def MoveToStartOfLine():
    cursor_pos = N10X.Editor.GetCursorPos()
    N10X.Editor.SetCursorPos((0, cursor_pos[1]))

def MoveToEndOfLine():
    MoveCursorWithinRange(x=MaxLineX() - 1)

#------------------------------------------------------------------------
def IsWordChar(c):
    return \
        (c >= 'a' and c <= 'z') or \
        (c >= 'A' and c <= 'Z') or \
        (c >= '0' and c <= '9') or \
        c == '_'

#------------------------------------------------------------------------
def GetWordEnd():
    cursor_pos = N10X.Editor.GetCursorPos()
    line = N10X.Editor.GetLine(cursor_pos[1])
    i = cursor_pos[0]
    if i < len(line):
        is_word_char = IsWordChar(line[i])
        while i < len(line):
            if IsWordChar(line[i]) != is_word_char:
                break
            i += 1
    return i

#------------------------------------------------------------------------
# def JoinLine():
#     N10X.Editor.PushUndoGroup()
#     N10X.Editor.SendKey("Down")
#     DeleteLine()
#     N10X.Editor.SendKey("Up")
#     MoveCursorWithinRange(x=MaxLineX())
#     cursor_pos = N10X.Editor.GetCursorPos()
#     N10X.Editor.InsertText(" ")
#     N10X.Editor.ExecuteCommand("Paste")
#     N10X.Editor.SetCursorPos(cursor_pos) # Need to set the cursor pos to right before join
#     N10X.Editor.PopUndoGroup()

REPEAT_MATCH = "([1-9][0-9]*)?"

#------------------------------------------------------------------------
# Key Intercepting

#------------------------------------------------------------------------
def HandleCommandModeChar(ch):
    global g_Mode
    global g_CommandStr

    g_CommandStr += ch

    m = re.match(REPEAT_MATCH + "(.*)", g_CommandStr)
    if not m:
        return

    repeat_count = int(m.group(1)) if m.group(1) else 1
    c = m.group(2)
    if not c:
        return

    if c == "i":
        EnterInsertMode()
    elif c == "/":
        N10X.Editor.ExecuteCommand("FindInFile")
    elif c == ":":
        N10X.Editor.ExecuteCommand("ShowCommandPanel")
        N10X.Editor.SetCommandPanelText(":")
    elif c == "v":
        EnterVisualMode(Mode.VISUAL)
    elif c == "V":
        EnterVisualMode(Mode.VISUAL_LINE)
    elif c == "S":
        N10X.Editor.ExecuteCommand("SaveFile")
    elif c == "0":
        MoveToStartOfLine()
    elif c == "$":
        MoveToEndOfLine()
    elif c == "o":
        N10X.Editor.PushUndoGroup()
        MoveCursorWithinRange(x=MaxLineX(), max_offset=0)
        SendKey("Enter")
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()
    elif c == "O":
        N10X.Editor.ExecuteCommand("InsertLine");
        EnterInsertMode()
    elif c == "a":
        EnterInsertMode();
        MoveCursorWithinRangeDelta(x_delta=1, max_offset=0)
    elif c == "A":
        EnterInsertMode();
        MoveCursorWithinRange(x=MaxLineX(), max_offset=0)
    elif c == "K":
        N10X.Editor.ExecuteCommand("ShowSymbolInfo")
    elif c == "Q":
        N10X.Editor.ExecuteCommand("CloseFile")
    elif (m := re.match("g([gd]?)", c)):
        action = m.group(1)
        if not action:
            return
        if action == 'd':
            N10X.Editor.ExecuteCommand("GotoSymbolDefinition");
        elif action == 'g':
            MoveToStartOfFile();
    elif c == "G":
        MoveToEndOfFile();
    elif c == "x":
        start = N10X.Editor.GetCursorPos()
        N10X.Editor.SetSelection(start, (start[0] + repeat_count, start[1]))
        N10X.Editor.ExecuteCommand("Cut")
        MoveCursorWithinRange(x=start[0], y=start[1])
    elif c == 'n':
        N10X.Editor.ExecuteCommand("FindInFileNext")
    elif c == 'N':
        N10X.Editor.ExecuteCommand("FindInFilePrev")
    else:
        for i in range(repeat_count):
            if c == "h":
                MoveCursorXOrWrapDelta(-1)
            elif c == "l":
                MoveCursorXOrWrapDelta(1)
            elif c == "k":
                MoveCursorWithinRangeDelta(y_delta=-1)
            elif c == "j":
                MoveCursorWithinRangeDelta(y_delta=1)
            elif c == "w":
                # N10X.Editor.ExecuteCommand("MoveCursorNextWord")
                MoveNextWordStart()
            elif c == "b":
                N10X.Editor.ExecuteCommand("MoveCursorPrevWord")
            elif c == "%":
                N10X.Editor.ExecuteCommand("MoveToMatchingBracket")
            elif c == "u":
                N10X.Editor.ExecuteCommand("Undo")
                x, y = N10X.Editor.GetSelectionStart()
                N10X.Editor.ClearSelection()
                MoveCursorWithinRange(x=x, y=y)
            elif (m := re.match(">(>?)", c)):
                if not m.group(1):
                    return
                x, y = N10X.Editor.GetCursorPos()
                SetLineSelection(y, y)
                N10X.Editor.ExecuteCommand("IndentLine")
                N10X.Editor.ClearSelection()
                MoveCursorWithinRange(x=x, y=y)
            elif (m := re.match("<(<?)", c)):
                if not m.group(1):
                    return
                x, y = N10X.Editor.GetCursorPos()
                SetLineSelection(y, y)
                N10X.Editor.ExecuteCommand("UnindentLine")
                N10X.Editor.ClearSelection()
                MoveCursorWithinRange(x=x, y=y)
            elif c == "p":
                if i == 0:
                    N10X.Editor.PushUndoGroup()

                if (old := ClipboardNoTrailingNewline()):
                    start = N10X.Editor.GetCursorPos()
                    MoveCursorWithinRange(x=MaxLineX(), max_offset=0)
                    SendKey("Enter")
                    MoveToStartOfLine()

                    N10X.Editor.ExecuteCommand("Paste")

                    RestoreClipboard(old)
                    MoveCursorWithinRange(x=start[0], y=start[1] + 1)
                else:
                    MoveCursorWithinRangeDelta(x_delta=1, max_offset=0)
                    N10X.Editor.ExecuteCommand("Paste")
                    MoveCursorWithinRangeDelta(x_delta=-1, max_offset=0)

                if i == repeat_count - 1:
                    N10X.Editor.PopUndoGroup()
            elif c == "P":
                if i == 0:
                    N10X.Editor.PushUndoGroup()

                if (old := ClipboardNoTrailingNewline()):
                    start = N10X.Editor.GetCursorPos()
                    N10X.Editor.ExecuteCommand("InsertLine")
                    end = N10X.Editor.GetCursorPos()
                    MoveToStartOfLine()

                    N10X.Editor.ExecuteCommand("Paste")

                    RestoreClipboard(old)
                    MoveCursorWithinRange(x=start[0], y=end[1])
                else:
                    N10X.Editor.ExecuteCommand("Paste")
                    MoveCursorWithinRangeDelta(x_delta=-1, max_offset=0)

                if i == repeat_count - 1:
                    N10X.Editor.PopUndoGroup()

            elif (m := re.match("([fFtT;])(.?)", c)):
                action = m.group(1)
                search = m.group(2)
                if not PerformLineSearch(action, search):
                    return

            elif (m := re.match("d(.*)", c)):
                trailing = m.group(1)
                start = N10X.Editor.GetCursorPos()
                def PerformCut():
                    if i == 0:
                        N10X.Editor.PushUndoGroup()
                    N10X.Editor.ExecuteCommand("Cut")
                    if i == repeat_count - 1:
                        N10X.Editor.PopUndoGroup()
                if not trailing or re.match("[1-9][0-9]*$", trailing):
                    return

                if trailing == 'd':
                    SetLineSelection(start[1], start[1])
                    PerformCut()
                    MoveCursorWithinRange(x=start[0], y=start[1])
                elif (m := re.match("g(g?)", trailing)):
                    if not m.group(1):
                        return
                    SetLineSelection(start[1], 0)
                    PerformCut()

                    MoveCursorWithinRange(x=start[0], y=0)
                elif trailing == 'G':
                    SetLineSelection(start[1], MaxY())
                    PerformCut()

                    MoveCursorWithinRange(x=start[0], y=start[0])
                elif trailing == 'w':
                    if MoveNextWordStart(wrap=False):
                        MoveCursorWithinRangeDelta(x_delta=-1)
                    end = N10X.Editor.GetCursorPos()

                    SetSelection(start, end)
                    PerformCut()

                    # Reset cursor position
                    MoveCursorWithinRange(x=min(start[0], end[0]))
                elif (m := re.match(REPEAT_MATCH + "([hl0$])", trailing)):
                    count = int(m.group(1)) if m.group(1) else 1
                    action = m.group(2)
                    if action == 'l' or action == 'h':
                        delta = 1 if m.group(2) == 'l' else -1
                        MoveCursorWithinRangeDelta(x_delta=delta*count)
                    elif action == '0':
                        MoveToStartOfLine()
                    elif action == '$':
                        MoveToEndOfLine()

                    end = N10X.Editor.GetCursorPos()

                    SetSelection(start, end)
                    PerformCut()

                    # Reset cursor position
                    MoveCursorWithinRange(x=min(start[0], end[0]))
                elif (m := re.match(REPEAT_MATCH + "([jk])", trailing)):
                    count = int(m.group(1)) if m.group(1) else 1
                    delta = 1 if m.group(2) == 'j' else -1
                    MoveCursorWithinRangeDelta(y_delta=delta*count)
                    end = N10X.Editor.GetCursorPos()

                    SetLineSelection(start[1], end[1])
                    PerformCut()

                    # Reset cursor position
                    MoveCursorWithinRange(x=start[0], y=min(start[1], end[1]))
                elif (m := re.match(REPEAT_MATCH + "([fFtT;])(.?)", trailing)):
                    count = int(m.group(1)) if m.group(1) else 1
                    action = m.group(2)
                    search = m.group(3)
                    for _ in range(count):
                        if not PerformLineSearch(action, search):
                            return

                    end = N10X.Editor.GetCursorPos()
                    SetSelection(start, end)
                    PerformCut()

                    # Reset cursor position
                    MoveCursorWithinRange(x=min(start[0], end[0]))
                else:
                    print("Invalid delete command!")


            elif (m := re.match("y(.*)", c)):
                # TODO(Brandon): This is a lot of copypasta
                trailing = m.group(1)
                start = N10X.Editor.GetCursorPos()
                def PerformCopy():
                    N10X.Editor.ExecuteCommand("Copy")
                    N10X.Editor.ClearSelection()

                if not trailing or re.match("[1-9][0-9]*$", trailing):
                    return

                if trailing == 'y':
                    SetLineSelection(start[1], start[1])
                    PerformCopy()
                    MoveCursorWithinRange(x=start[0], y=start[1])
                elif (m := re.match("g(g?)", trailing)):
                    if not m.group(1):
                        return
                    SetLineSelection(start[1], 0)
                    PerformCopy()

                    MoveCursorWithinRange(x=start[0], y=0)
                elif trailing == 'G':
                    SetLineSelection(start[1], MaxY())
                    PerformCopy()

                    MoveCursorWithinRange(x=start[0], y=start[0])
                elif trailing == 'w':
                    if MoveNextWordStart(wrap=False):
                        MoveCursorWithinRangeDelta(x_delta=-1)
                    end = N10X.Editor.GetCursorPos()

                    SetSelection(start, end)
                    PerformCopy()

                    # Reset cursor position
                    MoveCursorWithinRange(x=min(start[0], end[0]))
                elif (m := re.match(REPEAT_MATCH + "([hl0$])", trailing)):
                    count = int(m.group(1)) if m.group(1) else 1
                    action = m.group(2)
                    if action == 'l' or action == 'h':
                        delta = 1 if m.group(2) == 'l' else -1
                        MoveCursorWithinRangeDelta(x_delta=delta*count)
                    elif action == '0':
                        MoveToStartOfLine()
                    elif action == '$':
                        MoveToEndOfLine()

                    end = N10X.Editor.GetCursorPos()

                    SetSelection(start, end)
                    PerformCopy()

                    # Reset cursor position
                    MoveCursorWithinRange(x=min(start[0], end[0]))
                elif (m := re.match(REPEAT_MATCH + "([jk])", trailing)):
                    count = int(m.group(1)) if m.group(1) else 1
                    delta = 1 if m.group(2) == 'j' else -1
                    MoveCursorWithinRangeDelta(y_delta=delta*count)
                    end = N10X.Editor.GetCursorPos()

                    SetLineSelection(start[1], end[1])
                    PerformCopy()

                    # Reset cursor position
                    MoveCursorWithinRange(x=start[0], y=min(start[1], end[1]))
                elif (m := re.match(REPEAT_MATCH + "([fFtT;])(.?)", trailing)):
                    count = int(m.group(1)) if m.group(1) else 1
                    action = m.group(2)
                    search = m.group(3)
                    for _ in range(count):
                        if not PerformLineSearch(action, search):
                            return

                    end = N10X.Editor.GetCursorPos()
                    SetSelection(start, end)
                    PerformCopy()

                    # Reset cursor position
                    MoveCursorWithinRange(x=min(start[0], end[0]))
                else:
                    print("Invalid copy command!")
            elif (m := re.match("c(.*)", c)):
                trailing = m.group(1)
                start = N10X.Editor.GetCursorPos()
                def PerformChange():
                    if i == 0:
                        N10X.Editor.PushUndoGroup()
                    N10X.Editor.ExecuteCommand("Cut")
                    if i == repeat_count - 1:
                        N10X.Editor.PopUndoGroup()
                        EnterInsertMode()

                if not trailing or re.match("[1-9][0-9]*$", trailing):
                    return

                if trailing == 'c':
                    SetLineSelection(start[1], start[1])
                    _, y = start
                    N10X.Editor.SetSelection((0, y), (MaxLineX(y), y))
                    PerformChange()
                    MoveCursorWithinRange(x=start[0], y=start[1], max_offset=0)
                elif (m := re.match("g(g?)", trailing)):
                    if not m.group(1):
                        return
                    SetLineSelection(start[1], 0)
                    PerformChange()

                    MoveCursorWithinRange(x=start[0], y=0, max_offset=0)
                elif trailing == 'G':
                    SetLineSelection(start[1], MaxY())
                    PerformChange()

                    MoveCursorWithinRange(x=start[0], y=start[0], max_offset=0)
                elif trailing == 'w':
                    prevent_wrap = not MoveNextWordStart(wrap=False)
                    if not prevent_wrap:
                        MoveCursorWithinRangeDelta(x_delta=-1)
                    end = N10X.Editor.GetCursorPos()

                    SetSelection(start, end)
                    PerformChange()

                    # Reset cursor position
                    if prevent_wrap:
                        MoveCursorWithinRange(x=MaxLineX(start[1]), y=start[1], max_offset=0)
                    else:
                        MoveCursorWithinRange(x=min(start[0], end[0]))
                elif (m := re.match(REPEAT_MATCH + "([hl0$])", trailing)):
                    count = int(m.group(1)) if m.group(1) else 1
                    action = m.group(2)
                    if action == 'l' or action == 'h':
                        delta = 1 if m.group(2) == 'l' else -1
                        MoveCursorWithinRangeDelta(x_delta=delta*count)
                    elif action == '0':
                        MoveToStartOfLine()
                    elif action == '$':
                        MoveToEndOfLine()

                    end = N10X.Editor.GetCursorPos()

                    SetSelection(start, end)
                    PerformChange()

                    # Reset cursor position
                    MoveCursorWithinRange(x=min(start[0], end[0]), max_offset=0)
                elif (m := re.match(REPEAT_MATCH + "j", trailing)):
                    count = int(m.group(1)) if m.group(1) else 1
                    end_y = clamp(0, MaxY(), start[1] + count)
                    N10X.Editor.SetSelection((0, start[1]), (MaxLineX(end_y), end_y))
                    PerformChange()

                    # Reset cursor position
                    MoveCursorWithinRange(x=start[0], y=min(start[1], end_y), max_offset=0)
                elif (m := re.match(REPEAT_MATCH + "k", trailing)):
                    count = int(m.group(1)) if m.group(1) else 1
                    end_y = clamp(0, MaxY(), start[1] - count)
                    N10X.Editor.SetSelection((0, end_y), (MaxLineX(start[1]), start[1]))
                    PerformChange()

                    # Reset cursor position
                    MoveCursorWithinRange(x=start[0], y=min(start[1], end_y), max_offset=0)
                elif (m := re.match(REPEAT_MATCH + "([fFtT;])(.?)", trailing)):
                    count = int(m.group(1)) if m.group(1) else 1
                    action = m.group(2)
                    search = m.group(3)
                    for _ in range(count):
                        if not PerformLineSearch(action, search):
                            return

                    end = N10X.Editor.GetCursorPos()
                    SetSelection(start, end)
                    PerformChange()

                    # Reset cursor position
                    MoveCursorWithinRange(x=min(start[0], end[0]), max_offset=0)
                else:
                    print("Invalid change command!")
            else:
                print("Unknown command!")

    g_CommandStr = ""

    # elif command == "b":
    #     RepeatedCommand("MoveCursorPrevWord")

    # elif command == "J":
    #     JoinLine()

    # elif command == "I":
    #     MoveToStartOfLine();
    #     N10X.Editor.ExecuteCommand("MoveCursorNextWord")
    #     EnterInsertMode();

    # elif command == "e":
    #     cursor_pos = N10X.Editor.GetCursorPos()
    #     MoveCursorXOrWrap(GetWordEnd())

#------------------------------------------------------------------------
def HandleCommandModeKey(key, shift, control, alt):
    global g_HandingKey
    global g_CommandStr
    if g_HandingKey:
        return
    g_HandingKey = True

    handled = True

    pass_through = False

    # if key == "Enter":
    #     print("Enter key!")

    if key == "Escape":
        EnterCommandMode()
    elif key == "O" and control:
        N10X.Editor.ExecuteCommand("PrevLocation")
    elif key == "/" and control:
        x, y = N10X.Editor.GetCursorPos()

        if IsVisual():
            SubmitVisualModeSelection()
            N10X.Editor.ExecuteCommand("ToggleComment")
            N10X.Editor.ClearSelection()
        else:
            SetLineSelection(y, y)
            N10X.Editor.ExecuteCommand("ToggleComment")
            N10X.Editor.ClearSelection()

        MoveCursorWithinRange(x=x, y=y)
    elif key == "Tab" and shift:
        N10X.Editor.ExecuteCommand("PrevPanelTab")
    elif key == "Tab":
        N10X.Editor.ExecuteCommand("NextPanelTab")
    elif key == "H" and control:
        N10X.Editor.ExecuteCommand("MovePanelFocusLeft")
    elif key == "L" and control:
        N10X.Editor.ExecuteCommand("MovePanelFocusRight")
    elif key == "J" and control:
        N10X.Editor.ExecuteCommand("MovePanelFocusDown")
    elif key == "K" and control:
        N10X.Editor.ExecuteCommand("MovePanelFocusUp")
    elif key == "R" and control:
        N10X.Editor.ExecuteCommand("Redo")
    elif key == "P" and control:
        N10X.Editor.ExecuteCommand("Search")
    elif key == "Up":
        N10X.Editor.SendKey("Up")
    elif key == "Down":
        N10X.Editor.SendKey("Down")
    elif key == "Left":
        N10X.Editor.SendKey("Left")
    elif key == "Right":
        N10X.Editor.SendKey("Right")
    elif key == "PageUp":
        N10X.Editor.SendKey("PageUp")
    elif key == "PageDown":
        N10X.Editor.SendKey("PageDown")
    elif key == "U" and control:
        N10X.Editor.SendKey("PageUp")
    elif key == "D" and control:
        N10X.Editor.SendKey("PageDown")
    elif key == "F" and control:
        N10X.Editor.ExecuteCommand("FindReplaceInFile")
    else:
        handled = False

        pass_through = \
            control or \
            alt or \
            key == "Escape" or \
            key == "Delete" or \
            key == "Backspace" or \
            key == "Up" or \
            key == "Down" or \
            key == "Left" or \
            key == "Right" or \
            key == "F1" or \
            key == "F2" or \
            key == "F3" or \
            key == "F4" or \
            key == "F5" or \
            key == "F6" or \
            key == "F7" or \
            key == "F8" or \
            key == "F9" or \
            key == "F10" or \
            key == "F11" or \
            key == "F12" or \
            key.startswith("Mouse")

    if handled or pass_through:
        g_CommandStr = ""

    g_HandingKey = False

    UpdateVisualModeSelection()

    return not pass_through

#------------------------------------------------------------------------
def HandleInsertModeKey(key, shift, control, alt):
    if key == "Escape":
        EnterCommandMode()
        return True

    if key == "C" and control:
        EnterCommandMode()
        return True


def HandleVisualModeChar(ch):
    global g_Mode
    global g_CommandStr

    g_CommandStr += ch

    m = re.match(REPEAT_MATCH + "(.*)", g_CommandStr)
    if not m:
        return

    repeat_count = int(m.group(1)) if m.group(1) else 1
    c = m.group(2)
    if not c:
        return

    if c == "v":
        if g_Mode == Mode.VISUAL:
            EnterCommandMode()
        else:
            g_Mode = Mode.VISUAL
    elif c == "V":
        if g_Mode == Mode.VISUAL_LINE:
            EnterCommandMode()
        else:
            g_Mode = Mode.VISUAL_LINE
    elif c == "y":
        start, _ = SubmitVisualModeSelection()
        N10X.Editor.ExecuteCommand("Copy")
        N10X.Editor.ClearSelection()

        EnterCommandMode()

        MoveCursorWithinRange(start[0], start[1])
    elif c == "d" or c == "x" or c == "c":
        start, _ = SubmitVisualModeSelection()
        N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.ClearSelection()

        MoveCursorWithinRange(start[0], start[1])
        if c == "c":
            EnterInsertMode()
        else:
            EnterCommandMode()
    elif c == "0":
        MoveToStartOfLine()
    elif c == "$":
        MoveToEndOfLine()
    elif c == "G":
        MoveToEndOfFile();
    elif (m := re.match("g(g?)", c)):
        action = m.group(1)
        if not action:
            return
        MoveToStartOfFile();
    else:
        for _ in range(repeat_count):
            if c == "h":
                MoveCursorXOrWrapDelta(-1)
            elif c == "l":
                MoveCursorXOrWrapDelta(1)
            elif c == "k":
                MoveCursorWithinRangeDelta(y_delta=-1)
            elif c == "j":
                MoveCursorWithinRangeDelta(y_delta=1)
            elif c == "w":
                N10X.Editor.ExecuteCommand("MoveCursorNextWord")
            elif c == "b":
                N10X.Editor.ExecuteCommand("MoveCursorPrevWord")
            elif (m := re.match("([fFtT;])(.?)", c)):
                action = m.group(1)
                search = m.group(2)
                if not PerformLineSearch(action, search):
                    return
            elif c == "%":
                N10X.Editor.ExecuteCommand("MoveToMatchingBracket")
            elif c == ">":
                N10X.Editor.ExecuteCommand("IndentLine")
            elif c == "<":
                N10X.Editor.ExecuteCommand("UnindentLine")
            else:
                print("Unknown command!")
    
    g_CommandStr = ""
    UpdateVisualModeSelection()

def UpdateCursorMode():
    if g_Mode == Mode.INSERT:
        N10X.Editor.SetCursorMode("Line")
        N10X.Editor.SetStatusBarText("")
    elif g_CommandStr:
        N10X.Editor.SetCursorMode("HalfBlock")
        N10X.Editor.SetStatusBarText(g_CommandStr)
    else:
        N10X.Editor.SetCursorMode("Block")
        N10X.Editor.SetStatusBarText("")

#------------------------------------------------------------------------
# 10X Callbacks

#------------------------------------------------------------------------
# Called when a key is pressed.
# Return true to surpress the key
def OnInterceptKey(key, shift, control, alt):
    global g_HandleIntercepts
    if not g_HandleIntercepts:
        return False

    if N10X.Editor.TextEditorHasFocus():
        global g_Mode
        if g_Mode != Mode.INSERT:
            ret = HandleCommandModeKey(key, shift, control, alt)
        else:
            ret = HandleInsertModeKey(key, shift, control, alt)
        UpdateCursorMode()
        return ret
    return False

#------------------------------------------------------------------------
# Called when a char is to be inserted into the text editor.
# Return true to surpress the char key.
# If we are in command mode surpress all char keys
def OnInterceptCharKey(c):
    if N10X.Editor.TextEditorHasFocus():
        global g_Mode
        ret = g_Mode != Mode.INSERT
        if g_Mode == Mode.VISUAL or g_Mode == Mode.VISUAL_LINE:
            HandleVisualModeChar(c)
            N10X.Editor.SetCursorMode("Block")
        elif g_Mode == Mode.NORMAL:
            HandleCommandModeChar(c)
        UpdateCursorMode()
        return ret
    return False

#------------------------------------------------------------------------
def HandleCommandPanelCommand(command):

    if command == ":w":
        N10X.Editor.ExecuteCommand("SaveFile")
        return True

    if command == ":wq":
        N10X.Editor.ExecuteCommand("SaveFile")
        N10X.Editor.ExecuteCommand("CloseFile")
        return True

    if command == ":q":
        N10X.Editor.ExecuteCommand("CloseFile")
        return True

    if command == ":q!":
        N10X.Editor.DiscardUnsavedChanges()
        N10X.Editor.ExecuteCommand("CloseFile")
        return True
    
    split = command.split(":")
    if len(split) == 2 and split[1].isdecimal(): 
        MoveCursorWithinRange(y=int(split[1]) - 1)
        return True

#------------------------------------------------------------------------
def EnableVim():
    global g_VimEnabled
    enable_vim = N10X.Editor.GetSetting("Vim") == "true"

    if g_VimEnabled != enable_vim:
        g_VimEnabled = enable_vim

        if enable_vim:
            print("[vim] Enabling Vim")
            N10X.Editor.AddOnInterceptCharKeyFunction(OnInterceptCharKey)
            N10X.Editor.AddOnInterceptKeyFunction(OnInterceptKey)
            EnterCommandMode()

        else:
            print("[vim] Disabling Vim")
            EnterInsertMode()
            N10X.Editor.ResetCursorMode()
            N10X.Editor.RemoveOnInterceptCharKeyFunction(OnInterceptCharKey)
            N10X.Editor.RemoveOnInterceptKeyFunction(OnInterceptKey)

#------------------------------------------------------------------------
# enable/disable Vim when it's changed in the settings file
def OnSettingsChanged():
    EnableVim()

#------------------------------------------------------------------------
def InitialiseVim():
    EnableVim()

#------------------------------------------------------------------------
N10X.Editor.AddOnSettingsChangedFunction(OnSettingsChanged)
N10X.Editor.AddCommandPanelHandlerFunction(HandleCommandPanelCommand)

N10X.Editor.CallOnMainThread(InitialiseVim)
