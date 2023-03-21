#------------------------------------------------------------------------
import os
import N10X

#------------------------------------------------------------------------
# Vim style editing
#
# To enable Vim editing set Vim to true in the 10x settings file
#
#------------------------------------------------------------------------
g_VimEnabled = False

g_CommandMode = "insert"

g_PrevCommand = None
g_RepeatCount = None

g_VisualMode = "none"                # "none", "standard", "line"
g_VisualModeStartPos = None

g_HandingKey = False

#------------------------------------------------------------------------
# Helpers

#------------------------------------------------------------------------
def clamp(min_val, max_val, n):
   return max(min(n, max_val), min_val)

def MaxLineX(y=None):
    if y is None:
      _, y = N10X.Editor.GetCursorPos()

    return len(N10X.Editor.GetLine(y)) - 1

#------------------------------------------------------------------------
def MaxY():
    return N10X.Editor.GetLineCount()

#------------------------------------------------------------------------
def XInRange(x, y=None):
    return clamp(0, MaxLineX(y), x)

#------------------------------------------------------------------------
def YInRange(y):
    return clamp(0, MaxY(), y)

#------------------------------------------------------------------------
def MoveCursorWithinRange(x=None, y=None):
    if x is None:
      x, _ = N10X.Editor.GetCursorPos()
    if y is None:
      _, y = N10X.Editor.GetCursorPos()

    y = YInRange(y)

    N10X.Editor.SetCursorPos((XInRange(x, y), y))

#------------------------------------------------------------------------
# Modes

#------------------------------------------------------------------------
def EnterInsertMode():
    ExitVisualMode()
    global g_CommandMode
    if g_CommandMode != "insert":
        g_CommandMode = "insert"
        N10X.Editor.SetCursorMode("Line")
        N10X.Editor.ResetCursorBlink()

#------------------------------------------------------------------------
def EnterCommandMode():
    global g_CommandMode
    if g_CommandMode != "normal":
        g_CommandMode = "normal"
        SetPrevCommand(None)
        N10X.Editor.SetCursorMode("Block")
        N10X.Editor.ResetCursorBlink()
        x, y = N10X.Editor.GetCursorPos()

        MoveCursorWithinRange(x - 1, y)

#------------------------------------------------------------------------
def EnterVisualMode(mode):
    global g_VisualMode
    global g_VisualModeStartPos
    if g_VisualMode == "none":
        g_VisualModeStartPos = N10X.Editor.GetCursorPos()
    g_VisualMode = mode
    UpdateVisualModeSelection()

#------------------------------------------------------------------------
def ExitVisualMode():
    global g_VisualMode
    if g_VisualMode != "none":
        g_VisualMode = "none"
        N10X.Editor.RemoveCursor(1)

#------------------------------------------------------------------------
# Misc

#------------------------------------------------------------------------
def IsCommandPrefix(c):
    return \
        c == "c" or \
        c == "d" or \
        c == "g" or \
        c == ">" or \
        c == "<" or \
        c == "y"

#------------------------------------------------------------------------
def SetPrevCommand(c):
    global g_PrevCommand
    if g_CommandMode == "normal" and g_PrevCommand != c:
        g_PrevCommand = c
        if c:
            N10X.Editor.SetCursorMode("HalfBlock")
        else:
            N10X.Editor.SetCursorMode("Block")

#------------------------------------------------------------------------
def GetAndClearRepeatCount():
    global g_RepeatCount
    repeat_count = 1
    if g_RepeatCount != None:
        repeat_count = g_RepeatCount
        g_RepeatCount = None
    return repeat_count

#------------------------------------------------------------------------
def RepeatedCommand(command):
    repeat_count = GetAndClearRepeatCount()
    for i in range(repeat_count):
        if callable(command):
            command()
        else:
            N10X.Editor.ExecuteCommand(command)
            
#------------------------------------------------------------------------
def RepeatedEditCommand(command):
    N10X.Editor.PushUndoGroup()
    RepeatedCommand(command)
    N10X.Editor.PopUndoGroup()

#------------------------------------------------------------------------
def UpdateVisualModeSelection():
    global g_VisualMode
    global g_VisualModeStartPos
    
    cursor_pos = N10X.Editor.GetCursorPos()

    if g_VisualMode == "standard":
        N10X.Editor.SetSelection(g_VisualModeStartPos, cursor_pos, cursor_index=1)
        
    elif g_VisualMode == "line":
        start_line = min(g_VisualModeStartPos[1], cursor_pos[1])
        end_line = max(g_VisualModeStartPos[1], cursor_pos[1])
        N10X.Editor.SetSelection((0, start_line), (0, end_line + 1), cursor_index=1)

    N10X.Editor.SetCursorVisible(1, False)

#------------------------------------------------------------------------
# Returns start and end of selection
def SubmitVisualModeSelection():
    global g_VisualMode
    if g_VisualMode != "none":
        start_pos, end_pos = N10X.Editor.GetCursorSelection(cursor_index=1)
        ExitVisualMode()
        N10X.Editor.SetSelection(start_pos, end_pos)
        return [start_pos, end_pos]
            
#------------------------------------------------------------------------
# Command Functions

#------------------------------------------------------------------------
# NOTE: Vim tries to maintain the x position, but not sure of the exact rules.
# This screws up when the x coordinate does not exist, but is workable.
def MoveToStartOfFile():
    cursor_pos = N10X.Editor.GetCursorPos()
    N10X.Editor.SetCursorPos((cursor_pos[0], 0))

#------------------------------------------------------------------------
def MoveToEndOfFile():
    cursor_pos = N10X.Editor.GetCursorPos()
    line_count = N10X.Editor.GetLineCount()

    N10X.Editor.SetCursorPos((cursor_pos[0], line_count-1))

#------------------------------------------------------------------------
def MoveToStartOfLine():
    cursor_pos = N10X.Editor.GetCursorPos()
    N10X.Editor.SetCursorPos((0, cursor_pos[1]))

#------------------------------------------------------------------------
def MoveToEndOfLine():
    cursor_pos = N10X.Editor.GetCursorPos()
    line = N10X.Editor.GetLine(cursor_pos[1])
    N10X.Editor.SetCursorPos((len(line), cursor_pos[1]))

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
def CutToEndOfWordAndInsert():
    repeat_count = GetAndClearRepeatCount()
    cursor_pos = N10X.Editor.GetCursorPos()

    for i in range(repeat_count - 1):
        N10X.Editor.ExecuteCommand("MoveCursorNextWord")
    word_end_pos = GetWordEnd()
    N10X.Editor.SetSelection(cursor_pos, (word_end_pos, cursor_pos[1]))
    N10X.Editor.ExecuteCommand("Cut")

    EnterInsertMode()


#------------------------------------------------------------------------
def CutToEndOfLine():
    cursor_pos = N10X.Editor.GetCursorPos()

    line = N10X.Editor.GetLine(cursor_pos[1])
    line_end_pos = len(line)
    N10X.Editor.SetSelection(cursor_pos, (line_end_pos, cursor_pos[1]))
    N10X.Editor.ExecuteCommand("Cut")

#------------------------------------------------------------------------

def CutToEndOfLineAndInsert():
    CutToEndOfLine()
    EnterInsertMode()

#------------------------------------------------------------------------
def CutToEndOfWord():
    repeat_count = GetAndClearRepeatCount()
    cursor_pos = N10X.Editor.GetCursorPos()

    for i in range(repeat_count - 1):
        N10X.Editor.ExecuteCommand("MoveCursorNextWord")
    word_end_pos = GetWordEnd()
    N10X.Editor.SetSelection(cursor_pos, (word_end_pos, cursor_pos[1]))
    N10X.Editor.ExecuteCommand("Cut")
#------------------------------------------------------------------------
def DeleteLine():
    global g_VisualMode
    cursor_pos = N10X.Editor.GetCursorPos()
    repeat_count = GetAndClearRepeatCount()

    if g_VisualMode != "none":
        cursor_pos = SubmitVisualModeSelection()[0]
    else:
        cursor_pos = N10X.Editor.GetCursorPos()
        N10X.Editor.SetSelection((0, cursor_pos[1]), (0, cursor_pos[1] + repeat_count))
        
    N10X.Editor.ExecuteCommand("Cut")
    N10X.Editor.SetCursorPos(cursor_pos)

#------------------------------------------------------------------------
def JoinLine():
    N10X.Editor.SendKey("Down")
    DeleteLine()
    N10X.Editor.SendKey("Up")
    MoveToEndOfLine()
    cursor_pos = N10X.Editor.GetCursorPos()
    N10X.Editor.InsertText(" ")
    N10X.Editor.ExecuteCommand("Paste")
    N10X.Editor.SetCursorPos(cursor_pos) # Need to set the cursor pos to right before join

#------------------------------------------------------------------------
def Yank():
    global g_VisualMode
    cursor_pos = N10X.Editor.GetCursorPos()
    repeat_count = GetAndClearRepeatCount()

    if g_VisualMode != "none":
        SubmitVisualModeSelection()
    else:
        cursor_pos = N10X.Editor.GetCursorPos()
        N10X.Editor.SetSelection((0, cursor_pos[1]), (0, cursor_pos[1] + repeat_count))
        
    N10X.Editor.ExecuteCommand("Copy")
    N10X.Editor.SetCursorPos(cursor_pos)

#------------------------------------------------------------------------
def ReplaceLine():
    N10X.Editor.PushUndoGroup()
    DeleteLine()
    N10X.Editor.ExecuteCommand("InsertLine")
    EnterInsertMode()
    N10X.Editor.PopUndoGroup()
    
#------------------------------------------------------------------------
def ReplaceCharacters():   
    N10X.Editor.PushUndoGroup()
    DeleteCharacters()
    EnterInsertMode()
    N10X.Editor.PopUndoGroup()
    
#------------------------------------------------------------------------
def DeleteCharacters():
    global g_VisualMode
    repeat_count = GetAndClearRepeatCount()
    
    if g_VisualMode != "none":
        SubmitVisualModeSelection()
    else:
        cursor_pos = N10X.Editor.GetCursorPos()
        N10X.Editor.SetSelection(cursor_pos, (cursor_pos[0] + repeat_count, cursor_pos[1]))
        
    N10X.Editor.ExecuteCommand("Cut")

#------------------------------------------------------------------------
def AppendNewLineBelow():
    ExitVisualMode()
    EnterInsertMode()
    N10X.Editor.PushUndoGroup()
    MoveToEndOfLine()
    N10X.Editor.SendKey("Enter")
    N10X.Editor.PopUndoGroup()

#------------------------------------------------------------------------
# Key Intercepting

#------------------------------------------------------------------------
def HandleCommandModeChar(c):

    global g_PrevCommand
    command = c
    if g_PrevCommand:
        command = g_PrevCommand + c

    global g_RepeatCount
    is_repeat_key = False

    global g_VisualMode

    if command == "i":
        EnterInsertMode()

    elif g_VisualMode != "none" and command == "d":
        DeleteLine()

    elif g_VisualMode != "none" and command == "y":
        Yank()

    elif g_VisualMode != "none" and command == "c":
        if g_VisualMode == "line":
            ReplaceLine()
        else:
            ReplaceCharacters()

    elif IsCommandPrefix(command):
        SetPrevCommand(command)

    elif c >= '1' and c <= '9' or (c == '0' and g_RepeatCount != None):
        if g_RepeatCount == None:
            g_RepeatCount = int(c)
        else:
            g_RepeatCount = 10 * g_RepeatCount + int(c)
        is_repeat_key = True

    elif command == ":":
        N10X.Editor.ExecuteCommand("ShowCommandPanel")
        N10X.Editor.SetCommandPanelText(":")

    elif command == "v":
        if g_VisualMode == "standard":
            ExitVisualMode()
        else:
            EnterVisualMode("standard")

    elif command == "V":
        if g_VisualMode == "line":
            ExitVisualMode()
        else:
            EnterVisualMode("line")

    elif command == "dd":
        DeleteLine()

    elif command == "yy":
        Yank()

    elif command == "cc":
        ReplaceLine()

    elif command == "P":
        SubmitVisualModeSelection()
        RepeatedEditCommand("Paste")

    elif command == "h":
        RepeatedCommand(lambda:N10X.Editor.SendKey("Left"));
        UpdateVisualModeSelection()

    elif command == "l":
        RepeatedCommand(lambda:N10X.Editor.SendKey("Right"));
        UpdateVisualModeSelection()

    elif command == "k":
        RepeatedCommand(lambda:N10X.Editor.SendKey("Up"));
        UpdateVisualModeSelection()

    elif command == "j":
        RepeatedCommand(lambda:N10X.Editor.SendKey("Down"));
        UpdateVisualModeSelection()

    if command == "0":
        MoveToStartOfLine()

    elif command == "$":
        MoveToEndOfLine()

    elif command == "b":
        RepeatedCommand("MoveCursorPrevWord")
        UpdateVisualModeSelection()

    elif command == "w":
        RepeatedCommand("MoveCursorNextWord")
        UpdateVisualModeSelection()

    elif command == "dw":
        CutToEndOfWord()
    elif command == "cw":
        CutToEndOfWordAndInsert()

    elif command == "dW" or command == "D":
        CutToEndOfLine()
        
    elif command == "cW" or command == "C":
        CutToEndOfLineAndInsert()
        
    elif command == "J":
        JoinLine()

    elif command == "I":
        MoveToStartOfLine();
        N10X.Editor.ExecuteCommand("MoveCursorNextWord")
        EnterInsertMode();

    elif command == "a":
        # NOTE: this bugs when trying pressing it at the end of a line.
        # It shouldn't go to the next line, it should just go to the last possible position.
        # This might be a byproduct of not using a block cursor in insertmode, where you
        # actually can't go to the position after the last char.
        N10X.Editor.ExecuteCommand("MoveCursorRight");
        EnterInsertMode();

    elif command == "A":
        MoveToEndOfLine();
        EnterInsertMode();

    elif command == "e":
        cursor_pos = N10X.Editor.GetCursorPos()
        N10X.Editor.SetCursorPos((GetWordEnd(), cursor_pos[1]))
        UpdateVisualModeSelection()

    elif command == "p":
        # In vim, the cursor should "stay with the line."
        # Doing this for P seems to do some weird selection thing.
        SubmitVisualModeSelection()
        N10X.Editor.ExecuteCommand("MoveCursorDown");
        N10X.Editor.ExecuteCommand("Paste")
        N10X.Editor.ExecuteCommand("MoveCursorUp");

    elif command == "*":
        RepeatedCommand("FindInFileNextCurrentWord")

    elif command == "#":
        RepeatedCommand("FindInFilePrevCurrentWord")

    elif command == "O":
        ExitVisualMode()
        N10X.Editor.ExecuteCommand("InsertLine");
        EnterInsertMode();

    elif command == "o":
        AppendNewLineBelow()

    elif command == "gd":
        ExitVisualMode()
        N10X.Editor.ExecuteCommand("GotoSymbolDefinition");

    # NOTE: in vim, this loops.
    elif command == "gt":
        ExitVisualMode()
        N10X.Editor.ExecuteCommand("NextPanelTab");

    elif command == "gT":
        ExitVisualMode()
        N10X.Editor.ExecuteCommand("PrevPanelTab");

    elif command == "gg":
        MoveToStartOfFile();

    elif command == "G":
        MoveToEndOfFile();

    # NOTE: undo is pretty buggy with P/p stuff -- cursor position gets messed up.
    elif command == "u":
        ExitVisualMode()
        RepeatedCommand("Undo")

    elif command == ">>":
        SubmitVisualModeSelection()
        RepeatedCommand("IndentLine")

    elif command == "<<":
        SubmitVisualModeSelection()
        RepeatedCommand("UnindentLine")

    elif command == "x":
        DeleteCharacters()

    if not IsCommandPrefix(command):
        SetPrevCommand(None)

    # reset repeat count
    if (not is_repeat_key) and (not IsCommandPrefix(command)):
        g_RepeatCount = None

#------------------------------------------------------------------------
def HandleCommandModeKey(key, shift, control, alt):

    global g_HandingKey
    if g_HandingKey:
        return
    g_HandingKey = True

    handled = True

    global g_VisualMode

    pass_through = False

    if key == "Escape":
        ExitVisualMode()
        
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
    
    elif key == "S" and shift:
        N10X.Editor.ExecuteCommand("SaveFile")

    elif key == "Up" and g_VisualMode != "none":
        N10X.Editor.SendKey("Up")
        UpdateVisualModeSelection()

    elif key == "Down" and g_VisualMode != "none":
        N10X.Editor.SendKey("Down")
        UpdateVisualModeSelection()

    elif key == "Left" and g_VisualMode != "none":
        N10X.Editor.SendKey("Left")
        UpdateVisualModeSelection()

    elif key == "Right" and g_VisualMode != "none":
        N10X.Editor.SendKey("Right")
        UpdateVisualModeSelection()
    elif key == "PageUp":
        N10X.Editor.SendKey("PageUp")
    elif key == "PageDown":
        N10X.Editor.SendKey("PageDown")

    elif key == "U" and control:
        N10X.Editor.SendKey("PageUp")
    elif key == "D" and control:
        N10X.Editor.SendKey("PageDown")

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
        global g_RepeatCount
        g_RepeatCount = None
        SetPrevCommand(None)

    g_HandingKey = False
    
    return not pass_through

#------------------------------------------------------------------------
def HandleInsertModeKey(key, shift, control, alt):

    if key == "Escape":
        EnterCommandMode()
        return True

    if key == "C" and control:
        EnterCommandMode()
        return True


def HandleVisualModeKey(key, shift, contro, alt):
    None

#------------------------------------------------------------------------
# 10X Callbacks

#------------------------------------------------------------------------
# Called when a key is pressed.
# Return true to surpress the key
def OnInterceptKey(key, shift, control, alt):
    if N10X.Editor.TextEditorHasFocus():
        global g_CommandMode
        if g_CommandMode == "normal":
            return HandleCommandModeKey(key, shift, control, alt)
        else:
            HandleInsertModeKey(key, shift, control, alt)

#------------------------------------------------------------------------
# Called when a char is to be inserted into the text editor.
# Return true to surpress the char key.
# If we are in command mode surpress all char keys
def OnInterceptCharKey(c):
    if N10X.Editor.TextEditorHasFocus():
        global g_CommandMode
        if g_CommandMode == "normal":
            HandleCommandModeChar(c)
            return True

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
    print(split)
    if len(split) == 2 and split[1].isdecimal(): 
        MoveCursorWithinRange(None, int(split[1]) - 1)
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

