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

g_PrevCommand = ""
g_RepeatCount = None

class Mode:
    INSERT      = 0
    NORMAL      = 1
    VISUAL      = 2
    VISUAL_LINE = 3


g_Mode = Mode.INSERT
g_VisualModeStartPos = None

g_HandingKey = False


class Command:
    def __init__(self):
        pass

class EmptyCommand(Command):
    def __init__(self):
        self.command = None
    
    def Invoke(self, c):
        if self.command and self.command.Invoke(c):
            self.command = None
            return True

        return False
    

class CharacterInvocation(Command):
    def __init__(self, c):
        self.character = c

class RepeatInvocation(Command):
    def __init__(self, c):
        self.count = c
        self.command = None
    

class RepeatableInvocation(Command):
    def __init__(self):
        pass

class MovementInvocation(RepeatableInvocation):
    def __init__(self):
        pass

class DeleteInvocation(RepeatableInvocation):
    def __init__(self):
        pass
    
    def Invoke(self, c):
        pass
        
    
class MoveLeftInvocation(MovementInvocation):
    def __init__(self):
        pass
 
g_Command = EmptyCommand()



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

def XInRange(x, y=None):
    return clamp(0, MaxLineX(y), x)

def YInRange(y):
    return clamp(0, MaxY(), y)

def MoveCursorWithinRange(x=None, y=None):
    if x is None:
      x, _ = N10X.Editor.GetCursorPos()
    if y is None:
      _, y = N10X.Editor.GetCursorPos()

    y = YInRange(y)

    N10X.Editor.SetCursorPos((XInRange(x, y), y))

def MoveCursorWithinRangeDelta(x_delta=0, y_delta=0):
    x, y = N10X.Editor.GetCursorPos()
    x += x_delta
    y += y_delta
    MoveCursorWithinRange(x, y)

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

    x -= 1

    line = N10X.Editor.GetLine(y)
    if x < 0:
        return None
    
    line = line[:x]
    index = line.find(c)
    if index < 0:
        return None

    return index

#------------------------------------------------------------------------
# Modes

#------------------------------------------------------------------------
def EnterInsertMode():
    global g_Mode
    if g_Mode != Mode.INSERT:
        g_Mode = Mode.INSERT
        N10X.Editor.SetCursorMode("Line")
        N10X.Editor.ResetCursorBlink()

#------------------------------------------------------------------------
def EnterCommandMode():
    global g_Mode
    if g_Mode != Mode.NORMAL:
        N10X.Editor.ClearSelection()
        g_Mode = Mode.NORMAL
        ClearPrevCommand()
        N10X.Editor.SetCursorMode("Block")
        N10X.Editor.ResetCursorBlink()
        x, y = N10X.Editor.GetCursorPos()

        MoveCursorWithinRange(x - 1, y)

#------------------------------------------------------------------------
def EnterVisualMode(mode):
    global g_Mode
    global g_VisualModeStartPos
    if g_Mode != mode:
        g_Mode = mode
        g_VisualModeStartPos = N10X.Editor.GetCursorPos()

    UpdateVisualModeSelection()

#------------------------------------------------------------------------
# Misc

#------------------------------------------------------------------------
def IsCommandPrefix(c):
    global g_Mode
    if g_Mode == Mode.NORMAL:
        return c in "cdfFtTg<>y"
    else:
        return c in "gifFtT"

#------------------------------------------------------------------------
def ClearPrevCommand():
    global g_PrevCommand
    if g_PrevCommand:
        g_PrevCommand = ""
        # N10X.Editor.SetCursorMode("Block")

def SetPrevCommand(c):
    global g_PrevCommand
    global g_Mode
    if g_Mode == Mode.NORMAL:
        g_PrevCommand += c
        # N10X.Editor.SetCursorMode("HalfBlock")

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
    global g_Mode
    global g_VisualModeStartPos
    
    x, y = N10X.Editor.GetCursorPos()

    if g_Mode == Mode.VISUAL:
        start = g_VisualModeStartPos
        end = (x, y)
        if end[1] < start[1] or (end[1] == start[1] and end[0] < start[0]):
           end, start = start, end
        N10X.Editor.SetSelection(start, (end[0] + 1, end[1]), cursor_index=1)

    elif g_Mode == Mode.VISUAL_LINE:
        start_line = min(g_VisualModeStartPos[1], y)
        end_line = max(g_VisualModeStartPos[1], y)
        N10X.Editor.SetSelection((0, start_line), (0, end_line + 1), cursor_index=1)

    N10X.Editor.SetCursorVisible(1, False)

#------------------------------------------------------------------------
# Returns start and end of selection
def SubmitVisualModeSelection():
    global g_Mode
    if g_Mode == Mode.VISUAL or g_Mode == Mode.VISUAL_LINE:
        start_pos, end_pos = N10X.Editor.GetCursorSelection(cursor_index=1)
        EnterCommandMode()
        N10X.Editor.SetSelection(start_pos, end_pos)
        return [start_pos, end_pos]
            
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
    global g_Mode
    cursor_pos = N10X.Editor.GetCursorPos()
    repeat_count = GetAndClearRepeatCount()

    if g_Mode == Mode.VISUAL or g_Mode == Mode.VISUAL_LINE:
        cursor_pos = SubmitVisualModeSelection()[0]
    else:
        cursor_pos = N10X.Editor.GetCursorPos()
        N10X.Editor.SetSelection((0, cursor_pos[1]), (0, cursor_pos[1] + repeat_count))
        
    N10X.Editor.ExecuteCommand("Cut")
    N10X.Editor.SetCursorPos(cursor_pos)

#------------------------------------------------------------------------
def JoinLine():
    N10X.Editor.PushUndoGroup()
    N10X.Editor.SendKey("Down")
    DeleteLine()
    N10X.Editor.SendKey("Up")
    MoveCursorWithinRange(x=MaxLineX())
    cursor_pos = N10X.Editor.GetCursorPos()
    N10X.Editor.InsertText(" ")
    N10X.Editor.ExecuteCommand("Paste")
    N10X.Editor.SetCursorPos(cursor_pos) # Need to set the cursor pos to right before join
    N10X.Editor.PopUndoGroup()


#------------------------------------------------------------------------
def Yank():
    global g_Mode
    cursor_pos = N10X.Editor.GetCursorPos()
    repeat_count = GetAndClearRepeatCount()

    if g_Mode == Mode.VISUAL or g_Mode == Mode.VISUAL_LINE:
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
    global g_Mode
    repeat_count = GetAndClearRepeatCount()
    
    if g_Mode == Mode.VISUAL or g_Mode == Mode.VISUAL_LINE:
        SubmitVisualModeSelection()
    else:
        cursor_pos = N10X.Editor.GetCursorPos()
        N10X.Editor.SetSelection(cursor_pos, (cursor_pos[0] + repeat_count, cursor_pos[1]))
        
    N10X.Editor.ExecuteCommand("Cut")

#------------------------------------------------------------------------
def AppendNewLineBelow():
    EnterInsertMode()
    N10X.Editor.PushUndoGroup()
    MoveCursorWithinRange(x=MaxLineX())
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

    global g_Mode

    consumed = True

    if command == "i":
        EnterInsertMode()

    elif g_PrevCommand == "f":
        MoveCursorWithinRange(x=FindNextOccurrenceForward(c))

    elif g_PrevCommand == "F":
        MoveCursorWithinRange(x=FindNextOccurrenceBackward(c))

    elif IsCommandPrefix(command):
        SetPrevCommand(command)
        consumed = False
     
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
        EnterVisualMode(Mode.VISUAL)

    elif command == "V":
        EnterVisualMode(Mode.VISUAL_LINE)

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
        RepeatedCommand(lambda:MoveCursorXOrWrapDelta(-1));

    elif command == "l":
        RepeatedCommand(lambda:MoveCursorXOrWrapDelta(1));

    elif command == "k":
        RepeatedCommand(lambda:N10X.Editor.SendKey("Up"));

    elif command == "j":
        RepeatedCommand(lambda:N10X.Editor.SendKey("Down"));

    elif command == "0":
        MoveToStartOfLine()

    elif command == "%":
        N10X.Editor.ExecuteCommand("MoveToMatchingBracket")

    elif command == "$":
        MoveCursorWithinRange(x=MaxLineX() - 1)

    elif command == "b":
        RepeatedCommand("MoveCursorPrevWord")

    elif command == "w":
        RepeatedCommand("MoveCursorNextWord")

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
        EnterInsertMode();
        MoveCursorWithinRangeDelta(x_delta=1)

    elif command == "A":
        EnterInsertMode();
        MoveCursorWithinRange(x=MaxLineX())
    
    elif command == "K":
        N10X.Editor.ExecuteCommand("ShowSymbolInfo")
    
    elif command == "Q":
        N10X.Editor.ExecuteCommand("CloseFile")

    elif command == "e":
        cursor_pos = N10X.Editor.GetCursorPos()
        MoveCursorXOrWrap(GetWordEnd())

    elif command == "p":
        # In vim, the cursor should "stay with the line."
        # Doing this for P seems to do some weird selection thing.
        SubmitVisualModeSelection()
        N10X.Editor.ExecuteCommand("MoveCursorDown");
        N10X.Editor.ExecuteCommand("Paste")
        N10X.Editor.ExecuteCommand("MoveCursorUp");

    elif command == "O":
        EnterCommandMode()
        N10X.Editor.ExecuteCommand("InsertLine");
        EnterInsertMode();

    elif command == "o":
        AppendNewLineBelow()

    elif command == "gd":
        N10X.Editor.ExecuteCommand("GotoSymbolDefinition");

    elif command == "gg":
        MoveToStartOfFile();

    elif command == "G":
        MoveToEndOfFile();

    # NOTE: undo is pretty buggy with P/p stuff -- cursor position gets messed up.
    elif command == "u":
        RepeatedCommand("Undo")

    elif command == ">>":
        RepeatedCommand("IndentLine")

    elif command == "<<":
        RepeatedCommand("UnindentLine")

    elif command == "x":
        DeleteCharacters()

    if consumed:
        ClearPrevCommand()

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

    pass_through = False

    if key == "Escape":
        EnterCommandMode()
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
    elif key == "S" and shift:
        N10X.Editor.ExecuteCommand("SaveFile")
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
        ClearPrevCommand()

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


def HandleVisualModeChar(c):
    global g_PrevCommand
    command = c
    if g_PrevCommand:
        command = g_PrevCommand + c

    global g_RepeatCount
    is_repeat_key = False

    global g_Mode

    if command == "v":
        if g_Mode == Mode.VISUAL:
            EnterCommandMode()
        else:
            g_Mode = Mode.VISUAL

    elif command == "V":
        if g_Mode == Mode.VISUAL_LINE:
            EnterCommandMode()
        else:
            g_Mode = Mode.VISUAL_LINE

    elif IsCommandPrefix(command):
        SetPrevCommand(command)

    elif command == "y":
        Yank()

    elif command == "d":
        start, end = N10X.Editor.GetCursorSelection(cursor_index=1)
        # NOTE: I'm not entirely sure why we need to do this...
        N10X.Editor.SetSelection(start, end)

        N10X.Editor.ExecuteCommand("Cut")
        MoveCursorWithinRange(start[0], start[1])

        EnterCommandMode()

    elif command == "x":
        DeleteCharacters()

    elif command == "c":
        if g_Mode == Mode.VISUAL_LINE:
            ReplaceLine()
        else:
            ReplaceCharacters()

    elif command == "h":
        RepeatedCommand(lambda:MoveCursorXOrWrapDelta(-1));

    elif command == "l":
        RepeatedCommand(lambda:MoveCursorXOrWrapDelta(1));

    elif command == "k":
        RepeatedCommand(lambda:N10X.Editor.SendKey("Up"));

    elif command == "j":
        RepeatedCommand(lambda:N10X.Editor.SendKey("Down"));

    elif command == "0":
        MoveToStartOfLine()

    elif command == "%":
        N10X.Editor.ExecuteCommand("MoveToMatchingBracket")

    elif command == "$":
        MoveCursorWithinRange(x=MaxLineX() - 1)

    elif command == "b":
        RepeatedCommand("MoveCursorPrevWord")

    elif command == "w":
        RepeatedCommand("MoveCursorNextWord")

    elif command == "gg":
        MoveToStartOfFile();

    elif command == "G":
        MoveToEndOfFile();

    elif command == ">":
        RepeatedCommand("IndentLine")

    elif command == "<":
        RepeatedCommand("UnindentLine")
    
    UpdateVisualModeSelection()

    if not IsCommandPrefix(command):
        ClearPrevCommand()

    # reset repeat count
    if (not is_repeat_key) and (not IsCommandPrefix(command)):
        g_RepeatCount = None


#------------------------------------------------------------------------
# 10X Callbacks

#------------------------------------------------------------------------
# Called when a key is pressed.
# Return true to surpress the key
def OnInterceptKey(key, shift, control, alt):
    if N10X.Editor.TextEditorHasFocus():
        global g_Mode
        if g_Mode != Mode.INSERT:
            return HandleCommandModeKey(key, shift, control, alt)
        else:
            HandleInsertModeKey(key, shift, control, alt)

#------------------------------------------------------------------------
# Called when a char is to be inserted into the text editor.
# Return true to surpress the char key.
# If we are in command mode surpress all char keys
def OnInterceptCharKey(c):
    if N10X.Editor.TextEditorHasFocus():
        global g_Mode
        if g_Mode == Mode.VISUAL or g_Mode == Mode.VISUAL_LINE:
            HandleVisualModeChar(c)
            return True
        elif g_Mode == Mode.NORMAL:
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

