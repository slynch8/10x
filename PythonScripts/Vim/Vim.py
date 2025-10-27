#------------------------------------------------------------------------
import os
import N10X
import re
import win32clipboard
import time

#------------------------------------------------------------------------
# Vim style editing
#
# To enable Vim editing set Vim to true in the 10x settings file
#
#------------------------------------------------------------------------
g_VimEnabled = False

# Commandline mode uses 10x's command panel for commands. 
# E.g. :w :q 
# Enable in settings with VimUse10xCommandPanel.  
g_Use10xCommandPanel = False

# Search with '/' uses 10x's find panel
# Enable in settings with VimUse10xFindPanel
g_Use10xFindPanel = False

# Whether the commandline history is filtered on what's currently typed - same behaviour as NeoVim.
g_UseFilteredCommandlineHistory = True

# Whether to show the current scope name in the status bar in normal/command mode
g_DisplayCurrentScopeName = True

#------------------------------------------------------------------------
class Mode:
    INSERT       = 0
    COMMAND      = 1
    COMMANDLINE  = 2
    VISUAL       = 3
    VISUAL_LINE  = 4
    VISUAL_BLOCK = 5
    SUSPENDED    = 6 # Vim is enabled but all vim bindings are disabled except for vim command panel commands

#------------------------------------------------------------------------
g_Mode = Mode.INSERT

# For implementing keystroke in order to exit command mode
g_ExitInsertTimer = 0
g_VimExitInsertModeCharSequence = None
g_ExitInsertCharBuffer = None

# position of the cursor when visual mode was entered
g_VisualModeStartPos = None

# position of the cursor end on visual block mode 
g_VisualBlockModeEndPos = None
g_VisualBlockModeEnabled = True

# guard to stop infinite recursion in key handling
g_HandlingKey = False

# the current command for command mode
g_Command = ""

class CommandlineContext:
    def __init__(self):
        # the current command for commandline mode
        self.text = ""
        # Character to display as cursor position
        self.cursorChar = '_'
        # if using to index directly into g_CommandLineText be sure to clamp to len(g_CommandlineText)-1
        # slicing is fine as this handled by python, i.e. it will return "" if sliced out of bounds.
        self.cursorPos = 0
        # Stores history of commands in commandline mode, most recent is last
        self.commandHistory = []
        # Stores history of search strings in commandline mode, most recent is last
        self.searchHistory = []
        # When in commandline mode points to the currently selected item in either g_Commandline.commandHistory or g_Commandline.searchHistory
        self.historyIndex = 0 
        # Maximum size of the history buffers
        self.historyLength = 100 
        # Text displayed in status bar after submitting command. e.g. Error: Not an editor command, File <filepath> written.
        self.result = ""

g_Commandline = CommandlineContext()

# flag to enable/disable whether we handle key intercepts
g_HandleKeyIntercepts = True
g_HandleCharKeyIntercepts = True

# the last line search performed
g_LastCharSearch = None
g_ReverseCharSearch = False
g_ReverseSearch = False

# regex for getting the repeat count for a command
g_RepeatMatch = "([1-9][0-9]*)?"

# regex for getting the block tag
g_BlockMatch = "([{}[\]<>\(\)])"

# 'Ctrl+w` motions
g_PaneSwap = False

# 'r' and 'R' insert modes (respectively)
g_SingleReplace = False
g_MultiReplace = False

# position of the cursor before a significant "jump", allowing '' to target back
g_LastJumpPoint = None
# positions of explicitly set jump points (map of string to position)
g_JumpMap = {}

g_SneakEnabled = False

g_HorizontalTarget = 0
g_PrevCursorY = 0
g_PrevCursorX = 0

# smart case when searching - e.g. if one upper case letter is present, searching is case sensitive.
g_SmartCaseEnabled = True 

class UserHandledResult:
    """
    Return value for user calls, e.g. handle key/char callbacks
    """
    UNHANDLED       = 0  # Not handled, pass back to caller.
    HANDLED         = 1  # Handled, do not pass back to caller.
    PASS_TO_10X     = 2  # Not handled and don't pass back to caller, pass back to 10x.

class Key:
    """
    Key + modifiers
    """
    def __init__(self, key, shift=False, control=False, alt=False):
        self.key = key
        self.shift = bool(shift)
        # In 10x AltGr will come through with the following set 
        self.alt_gr = bool(key == "Alt" and control and alt)
        # We need to make sure we mask these out if alt_gr is True
        self.control = bool(control) and not self.alt_gr
        self.alt = bool(alt) and not self.alt_gr 

    def __eq__(self, rhs):
        return self.key == rhs.key and self.shift == rhs.shift and self.control == rhs.control and self.alt == rhs.alt 

    def __ne__(self, rhs):
        return not self.__eq__(rhs)

    def __str__(self):
        return f"Key: Key={self.key} Shift={self.shift} Control={self.control} Alt={self.alt} AltGr={self.alt_gr}"

class RecordedKey:
    KEY = 0
    CHAR_KEY = 1

    type = KEY
    char = ""
    key = Key("")


g_LastCommand = ""
g_InsertBuffer = []
g_PerformingDot = False

g_RecordingName = ""
g_NamedBuffers = {}

# Vim user bindings
import VimUser

#------------------------------------------------------------------------
def GetSetting(setting, default_value):
    value = N10X.Editor.GetSetting(setting)
    return default_value if value == "" else value 

#------------------------------------------------------------------------
def GetSettingBool(setting, default_value):
    return GetSetting(setting, default_value) == "true"

#------------------------------------------------------------------------
def InVisualMode():
    global g_Mode
    return g_Mode == Mode.VISUAL or g_Mode == Mode.VISUAL_LINE or g_Mode == Mode.VISUAL_BLOCK

#------------------------------------------------------------------------
def SetFindText(text, case=False, word=False, regex=False, start_pos=(-1,-1)):
    N10X.Editor.SetFindText(text, case, word, regex, start_pos)

#------------------------------------------------------------------------
def Clamp(min_val, max_val, n):
   return max(min(n, max_val), min_val)

#------------------------------------------------------------------------
def GetLine(y=None):
    if y is None:
        x, y = N10X.Editor.GetCursorPos()
    return N10X.Editor.GetLine(y)

#------------------------------------------------------------------------
def GetLineLength(y=None):
    line = GetLine(y)
    line = line.rstrip("\r\n")
    return len(line)

#------------------------------------------------------------------------
def GetMaxY():
    return max(0, N10X.Editor.GetLineCount() - 1)

#------------------------------------------------------------------------
def Unhilight():
    N10X.Editor.SetCursorPos(N10X.Editor.GetCursorPos())

#------------------------------------------------------------------------
def SetCursorPos(x=None, y=None, max_offset=1, override_horizontal_target=True):

    # If the program moved our cursor then always override the horizontal target
    global g_PrevCursorX
    global g_PrevCursorY
    CurrentX, CurrentY = N10X.Editor.GetCursorPos()
    if CurrentX != g_PrevCursorX or CurrentY != g_PrevCursorY:
        override_horizontal_target=True
        
    if x is None:
      x = CurrentX
    if y is None:
      y = CurrentY

    y = Clamp(0, GetMaxY(), y)
    
    # This is to keep the horizontal target when we are moving vertically  
    global g_HorizontalTarget
    if override_horizontal_target:
        g_HorizontalTarget = x;
    else:
        line_start_x, line_start_y = GetFirstNonWhitespace(y)
        x = max(g_HorizontalTarget, line_start_x)

    if g_Mode != Mode.VISUAL_BLOCK:
        x = min(GetLineLength(y) - max_offset, x)

    N10X.Editor.SetCursorPos((x, y))
    g_PrevCursorX, g_PrevCursorY = N10X.Editor.GetCursorPos()

    if N10X.Editor.GetSetting("HideMouseCursorWhileTyping"):
        N10X.Editor.HideMouseCursor()

#------------------------------------------------------------------------
def MoveCursorPos(x_delta=0, y_delta=0, max_offset=1, override_horizontal_target=True):

    if not x_delta:
        if y_delta == -1:
            N10X.Editor.ExecuteCommand("MoveCursorUp")
            return
        elif y_delta == 1:
            N10X.Editor.ExecuteCommand("MoveCursorDown")
            return

    x, y = N10X.Editor.GetCursorPos()
    x += x_delta
    y += y_delta
    
    SetCursorPos(x, y, max_offset, override_horizontal_target)

#------------------------------------------------------------------------
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

#------------------------------------------------------------------------
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
    
#------------------------------------------------------------------------
def FindNextOccurrenceBackward2(c):
    if len(c) == 1:
       return None, None
    x, y = N10X.Editor.GetCursorPos()
    line = N10X.Editor.GetLine(y)

    while y >= 0:
        if x >= 0:
            line = line[:x + 1]
            index = line.rfind(c)
            if index >= 0:
                    return index, y
        y -= 1
        line = N10X.Editor.GetLine(y)
        x = len(line) - 1
    return None, None


#------------------------------------------------------------------------
def FindNextOccurrenceForward2(c):
    if len(c) == 1:
       return None, None
    x, y = N10X.Editor.GetCursorPos()
    x += 1
    lineCount = N10X.Editor.GetLineCount()
    while y < lineCount:
        line = N10X.Editor.GetLine(y)
        if x < len(line) - 1:
            line = line[x:]
            index = line.find(c)
            if index >= 0:
                    return x + index, y
        x = 0
        y += 1
    return None, None
    
#------------------------------------------------------------------------
def MoveToLineText(action, search):
    global g_LastCharSearch
    global g_ReverseCharSearch

    if g_LastCharSearch:
        if action == ';':
            if g_ReverseCharSearch:
                MoveToLineText(g_LastCharSearch[0].upper(), g_LastCharSearch[1:])
            else:
                MoveToLineText(g_LastCharSearch[0].lower(), g_LastCharSearch[1:])
            return True
        elif action == ',':
            if g_ReverseCharSearch:
                MoveToLineText(g_LastCharSearch[0].lower(), g_LastCharSearch[1:])
            else:
                MoveToLineText(g_LastCharSearch[0].upper(), g_LastCharSearch[1:])
            return True
    
    if not search:
        return False

    if len(search) == 1:
        if action == 'f':
            x = FindNextOccurrenceForward(search)
            if x != None:
                SetCursorPos(x=x)
            g_ReverseCharSearch = False
        elif action == 'F':
            x = FindNextOccurrenceBackward(search)
            if x != None:
                SetCursorPos(x=x)
            g_ReverseCharSearch = True
        elif action == 't':
            x = FindNextOccurrenceForward(search)
            if x != None:
                SetCursorPos(x=x-1)
            g_ReverseCharSearch = False
        elif action == 'T':
            x = FindNextOccurrenceBackward(search)
            if x != None:
                SetCursorPos(x=x+1)
            g_ReverseCharSearch = True
        else:
           return False
    
        g_LastCharSearch = action + search
        return True
    elif len(search) == 2 and g_SneakEnabled:
        if action == 's':
            x,y = FindNextOccurrenceForward2(search)
            if x != None:
                SetCursorPos(x=x, y=y)
        elif action == 'S':
            x,y = FindNextOccurrenceBackward2(search)
            if x != None:
                SetCursorPos(x=x, y=y)
        else:
            return False
 
        g_LastCharSearch = action + search
        return True
    else:
       return False 
            
#------------------------------------------------------------------------
def GetClipboardValue():
    for i in range(50):
        try:
            win32clipboard.OpenClipboard()
            data = str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT))
            win32clipboard.CloseClipboard()
            return data
        except TypeError as te: #clipboard is non-unicode.
            win32clipboard.CloseClipboard()
            break
        except Exception as ex:
            if ex.winerror == 5:  # access denied
                time.sleep( 0.01 )
            elif ex.winerror == 1418:  # doesn't have board open
                pass
            else:
                pass

    print("[vim] Failed to get clipboard of non-unicode text!")
    return None

#------------------------------------------------------------------------
def AddNewlineToClipboard():
    for i in range(50):
        try:
            win32clipboard.OpenClipboard()
            data = str(win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT))
            win32clipboard.SetClipboardText(data + "\n", win32clipboard.CF_UNICODETEXT)
            win32clipboard.CloseClipboard()
            return
        except TypeError as te: #clipboard is non-unicode.
            win32clipboard.CloseClipboard()
            break
        except Exception as ex:
            if ex.winerror == 5:  # access denied
                time.sleep( 0.01 )
            elif ex.winerror == 1418:  # doesn't have board open
                pass
            else:
                pass

    print("[vim] Failed add newline to clipboard text!")

#------------------------------------------------------------------------
def SendKey(key, shift=None, control=None, alt=None):
    global g_HandleKeyIntercepts
    g_HandleKeyIntercepts = False
    N10X.Editor.SendKey(key, shift, control, alt)
    g_HandleKeyIntercepts = True

def SendCharKey(char):
    global g_HandleCharKeyIntercepts
    g_HandleCharKeyIntercepts = False
    N10X.Editor.SendCharKey(char)
    g_HandleCharKeyIntercepts = True

#------------------------------------------------------------------------
def EnterInsertMode():
    global g_Mode
    global g_PerformingDot
    global g_InsertBuffer

    assert g_Mode != Mode.INSERT

    g_Mode = Mode.INSERT
    N10X.Editor.ResetCursorBlink()
    UpdateCursorMode()

    N10X.Editor.PushUndoGroup()
    if g_PerformingDot:
        PlaybackBuffer(g_InsertBuffer)
        EnterCommandMode()
    else:
        g_InsertBuffer = []

#------------------------------------------------------------------------
def ClearCommandStr(save=False):
    global g_Command
    global g_LastCommand

    if save:
        g_LastCommand = g_Command
    g_Command = ""

#------------------------------------------------------------------------
def EnterCommandMode(pop_undo_group=True):
    global g_Mode
    global g_Command
    global g_SingleReplace
    global g_MultiReplace
    global g_PaneSwap
    global g_Commandline
    
    if g_Mode != Mode.COMMANDLINE:
        g_Commandline.result = ""

    g_PaneSwap = False
    ClearCommandStr(False)

    if g_Mode != Mode.COMMAND:
        # Don't clear selection as we might have been searching
        if g_Mode != Mode.COMMANDLINE:
            N10X.Editor.ClearSelection()
        g_SingleReplace = False
        g_MultiReplace = False

        was_visual = InVisualMode()
        N10X.Editor.ResetCursorBlink()

        if not was_visual and not g_Mode == Mode.COMMANDLINE:
            if pop_undo_group:
                N10X.Editor.PopUndoGroup()
            MoveCursorPos(x_delta=-1, override_horizontal_target=True)

    g_Mode = Mode.COMMAND
    UpdateCursorMode()

#------------------------------------------------------------------------
def EnterCommandlineMode(char):
    global g_Mode, g_Commandline

    g_Mode = Mode.COMMANDLINE
    g_Commandline.result = ""
    g_Commandline.text = char 
    g_Commandline.cursorPos = 1

    # Create entry in history buffer and update index
    history_buffer = GetHistoryBuffer() 
    g_Commandline.historyIndex = len(history_buffer)
    # Make sure we don't grow too large
    if len(history_buffer) >= g_Commandline.historyLength:
        history_buffer.pop(0)
    history_buffer.append("")

    UpdateCursorMode()

#------------------------------------------------------------------------
def EnterVisualMode(mode):
    global g_Mode
    global g_VisualModeStartPos

    if g_Mode != mode:
        g_Mode = mode
        g_VisualModeStartPos = N10X.Editor.GetCursorPos()

    UpdateVisualModeSelection()

#------------------------------------------------------------------------
def EnterSuspendedMode():
    global g_Mode
    g_Mode = Mode.SUSPENDED
    UpdateCursorMode()

#------------------------------------------------------------------------
def SetSelection(start, end, cursor_index=0):
    if end[1] < start[1] or (end[1] == start[1] and end[0] < start[0]):
        end, start = start, end

    N10X.Editor.SetSelection(start, (end[0] + 1, end[1]), cursor_index=cursor_index)

#------------------------------------------------------------------------
def SetLineSelection(start, end, cursor_index=0):
    start_line = min(start, end)
    end_line = max(start, end)
    sel_start = (0, start_line)
    if end == GetMaxY():
        sel_end = (GetLineLength(end), end)
    else:
        sel_end = (0, end_line + 1)
    N10X.Editor.SetSelection(sel_start, sel_end, cursor_index=cursor_index)

#------------------------------------------------------------------------
def SetVisualModeSelection(start, end):
    global g_VisualModeStartPos

    g_VisualModeStartPos = start
    SetCursorPos(end[0], end[1])

#------------------------------------------------------------------------
def AddVisualModeSelection(start, end):
    global g_VisualModeStartPos

    curr_start = g_VisualModeStartPos
    curr_end = N10X.Editor.GetCursorPos()
    if curr_start == curr_end:
        SetVisualModeSelection(start, end)
        return

    a = (0,0)
    b = (0,0)
    if start[1] < end[1]:
        a = start
        b = end
    elif start[1] > end[1]:
        a = end
        b = start
    else:
        a = (min(start[0], end[0]), start[1]) 
        b = (max(start[0], end[0]), start[1])

    if curr_start[1] < curr_end[1]:
        curr_end = b 
    elif curr_start[1] > curr_end[1]:
        curr_end = a
    elif curr_start[0] < curr_end[0]:
        curr_end = b
    else:
        curr_end = a

    SetVisualModeSelection(curr_start, curr_end)

#------------------------------------------------------------------------
def UpdateVisualModeSelection():
    global g_Mode
    global g_VisualModeStartPos
    global g_VisualBlockModeEndPos

    end = N10X.Editor.GetCursorPos()

    start = g_VisualModeStartPos
    if g_Mode == Mode.VISUAL:
        SetSelection(start, end, cursor_index=1)
    elif g_Mode == Mode.VISUAL_LINE:
        SetLineSelection(start[1], end[1], cursor_index=1)
    elif g_Mode == Mode.VISUAL_BLOCK:
        g_VisualBlockModeEndPos = end
        N10X.Editor.SetCursorRectSelect(start, end)
                             
    N10X.Editor.SetCursorVisible(1, False)

#------------------------------------------------------------------------
def SubmitVisualModeSelection():
    if g_Mode == Mode.VISUAL_BLOCK:
        start_pos = g_VisualModeStartPos
        end_pos = g_VisualBlockModeEndPos
    
        if g_VisualModeStartPos[0] > g_VisualBlockModeEndPos[0]:
            start_pos = (start_pos[0] + 1, start_pos[1])
        else:
            end_pos = (end_pos[0] + 1, end_pos[1])
            
        EnterCommandMode()
        N10X.Editor.SetCursorRectSelect(start_pos, end_pos)

        if g_VisualModeStartPos[0] > g_VisualBlockModeEndPos[0]:
            start_pos = g_VisualBlockModeEndPos
            end_pos = g_VisualModeStartPos

    else:
        start_pos, end_pos = N10X.Editor.GetCursorSelection(cursor_index=1)
            
        EnterCommandMode()
        N10X.Editor.SetSelection(start_pos, end_pos)

    return start_pos, end_pos

#------------------------------------------------------------------------
def IsWhitespaceChar(c):
    return c == ' ' or c == '\t' or c == '\r' or c == '\n'

#------------------------------------------------------------------------
def IsWhitespace(x, y):
    line = GetLine(y)
    return x >= len(line) or IsWhitespaceChar(line[x])

#------------------------------------------------------------------------
def IsWordChar(c):
    return \
        (c >= 'a' and c <= 'z') or \
        (c >= 'A' and c <= 'Z') or \
        (c >= '0' and c <= '9') or \
        c == '_'

#------------------------------------------------------------------------
def IsWord(x, y):
    line = GetLine(y)
    return IsWordChar(line[x])

#------------------------------------------------------------------------
class CharacterClass:
    WHITESPACE  = 0
    DEFAULT     = 1
    WORD        = 2

#------------------------------------------------------------------------
def GetCharacterClass(c):
    if IsWordChar(c):
        return CharacterClass.WORD
    if IsWhitespaceChar(c):
        return CharacterClass.WHITESPACE
    return CharacterClass.DEFAULT

#------------------------------------------------------------------------
def GetCharacterClassAtPos(x, y):
    line = GetLine(y)
    return GetCharacterClass(line[x]) if x < len(line)  else CharacterClass.WHITESPACE

#------------------------------------------------------------------------
def GetPrevCharPos(x, y):
    if x:
        x -= 1
    elif y:
        y -= 1
        x = max(0, GetLineLength(y) - 1)
    else:
        x = 0
        y = 0
    return x, y

#------------------------------------------------------------------------
def GetPrevNonWhitespaceCharPos(x, y):
    while y and IsWhitespace(x, y):
        if x == 0:
            y -= 1
            x = GetLineLength(y)
            if x:
                x -= 1
        else:
            x -= 1
    return x, y
    
#------------------------------------------------------------------------
def GetFirstNonWhitespace(y):
    line = N10X.Editor.GetLine(y)
    x = 0
    
    while x < len(line):
         first_character = GetCharacterClass(line[x]) != CharacterClass.WHITESPACE
         if first_character:
            break;
         x +=1;
    
    return x, y

#------------------------------------------------------------------------
def MoveToFirstNonWhitespace():
    x, y = N10X.Editor.GetCursorPos()
    new_x, new_y = GetFirstNonWhitespace(y)
    SetCursorPos(new_x, new_y)

#------------------------------------------------------------------------
def GetWordStart():
    x, y = N10X.Editor.GetCursorPos()

    x, y = GetPrevCharPos(x, y)
    x, y = GetPrevNonWhitespaceCharPos(x, y)

    line = N10X.Editor.GetLine(y)

    if x < len(line):
        character_class = GetCharacterClass(line[x])
        while x > 0:
            if GetCharacterClass(line[x - 1]) != character_class:
                break
            x -= 1

    return x, y

#------------------------------------------------------------------------
def MoveToWordStart():
    new_x, new_y = GetWordStart()
    SetCursorPos(new_x, new_y)

#------------------------------------------------------------------------
def GetTokenStart():
    x, y = N10X.Editor.GetCursorPos()

    x, y = GetPrevCharPos(x, y)
    x, y = GetPrevNonWhitespaceCharPos(x, y)

    line = N10X.Editor.GetLine(y)

    if x < len(line):
        is_whitespace = GetCharacterClass(line[x]) == CharacterClass.WHITESPACE
        while x > 0:
            is_whitespace_iter = GetCharacterClass(line[x - 1]) == CharacterClass.WHITESPACE
            if is_whitespace_iter != is_whitespace:
                break
            x -= 1

    return x, y

#------------------------------------------------------------------------
def MoveToTokenStart():
    new_x, new_y = GetTokenStart()
    SetCursorPos(new_x, new_y)

#------------------------------------------------------------------------
def GetNextCharPos(x, y, wrap=True):
    if x < GetLineLength(y):
        x += 1
    if wrap and x >= GetLineLength(y) and y < GetMaxY():
        x = 0
        y += 1
    return x, y

#------------------------------------------------------------------------
def AtEndOfFile(x, y):
    return y > GetMaxY() or (y == GetMaxY() and x >= GetLineLength(GetMaxY()))

#------------------------------------------------------------------------
def GetNextNonWhitespaceCharPos(x, y, wrap=True):
    while not AtEndOfFile(x, y) and IsWhitespace(x, y):
        if x >= GetLineLength(y):
            if wrap and y < GetMaxY():
                x = 0
                y += 1
            else:
                break
        else:
            x += 1
    return x, y

#------------------------------------------------------------------------
def MoveToNextNonWhitespaceChar(wrap=True):
    x, y = N10X.Editor.GetCursorPos()
    end_x, end_y = GetNextNonWhitespaceCharPos(x, y, wrap)
    SetCursorPos(end_x, end_y)

#------------------------------------------------------------------------
def GetWordEndPos(x, y, wrap=True):
    x, y = N10X.Editor.GetCursorPos()

    x, y = GetNextCharPos(x, y, wrap)
    x, y = GetNextNonWhitespaceCharPos(x, y, wrap)

    line = N10X.Editor.GetLine(y)

    if x < len(line):
        character_class = GetCharacterClass(line[x])
        while x < len(line):
            if GetCharacterClass(line[x]) != character_class:
                break
            x += 1
    if x:
        x -= 1
    return x, y

#------------------------------------------------------------------------
def MoveToWordEnd():
    x, y = N10X.Editor.GetCursorPos()
    new_x, new_y = GetWordEndPos(x, y)
    SetCursorPos(new_x, new_y)

#------------------------------------------------------------------------
def GetTokenEndPos(x, y, wrap=True):
    x, y = N10X.Editor.GetCursorPos()

    x, y = GetNextCharPos(x, y, wrap)
    x, y = GetNextNonWhitespaceCharPos(x, y, wrap)

    line = N10X.Editor.GetLine(y)

    if x < len(line):
        is_whitespace = GetCharacterClass(line[x]) == CharacterClass.WHITESPACE
        while x < len(line):
            is_whitespace_iter = GetCharacterClass(line[x]) == CharacterClass.WHITESPACE
            if is_whitespace_iter != is_whitespace:
                break
            x += 1
    if x:
        x -= 1
    return x, y

#------------------------------------------------------------------------
def MoveToTokenEnd():
    x, y = N10X.Editor.GetCursorPos()
    new_x, new_y = GetTokenEndPos(x, y)
    SetCursorPos(new_x, new_y)

#------------------------------------------------------------------------
def MoveToNextWordStart(wrap=True):
    x, y = N10X.Editor.GetCursorPos()

    line_y = y

    character_class = GetCharacterClassAtPos(x, y)
    while not AtEndOfFile(x, y) and y == line_y and GetCharacterClassAtPos(x, y) == character_class:
        x, y = GetNextCharPos(x, y, wrap)

    x, y = GetNextNonWhitespaceCharPos(x, y, wrap)

    SetCursorPos(x, y)

    return x < GetLineLength(y)

#------------------------------------------------------------------------
def MoveToNextTokenStart(wrap=True):
    x, y = N10X.Editor.GetCursorPos()

    line_y = y

    while y == line_y and not IsWhitespace(x, y):
        x, y = GetNextCharPos(x, y, wrap)

    x, y = GetNextNonWhitespaceCharPos(x, y, wrap)

    SetCursorPos(x, y)

#------------------------------------------------------------------------
def MoveToStartOfFile():
    SetCursorPos(y=0)

#------------------------------------------------------------------------
def MoveToEndOfFile():
    SetCursorPos(GetLineLength(GetMaxY()), GetMaxY())

#------------------------------------------------------------------------
def MoveToStartOfLine():
    SetCursorPos(x=0)

#------------------------------------------------------------------------
def MoveToEndOfLine():
    SetCursorPos(x=GetLineLength() - 1)
    
#------------------------------------------------------------------------
def FindPreviousParagraphBegin():
    x, y = N10X.Editor.GetCursorPos()

    while y > 0 and N10X.Editor.GetLine(y).isspace():
      y -= 1

    while y > 0 :
      y -= 1
      text = N10X.Editor.GetLine(y)
      if text.isspace():
        return y
    return 0

#------------------------------------------------------------------------
def FindNextParagraphEnd():
    line_count = N10X.Editor.GetLineCount()
    x, y = N10X.Editor.GetCursorPos()

    while y < line_count - 1 and N10X.Editor.GetLine(y + 1).isspace():
      y += 1

    while y < line_count - 1:
      text = N10X.Editor.GetLine(y + 1)
      if not text or text.isspace():
        return y
      y += 1
    return y

#------------------------------------------------------------------------
def FindPreviousEmptyLine():
    x, y = N10X.Editor.GetCursorPos()
    while y > 0 :
      y -= 1
      text = N10X.Editor.GetLine(y)
      if text.isspace():
        return y
    return 0

#------------------------------------------------------------------------
def FindNextEmptyLine():
    line_count = N10X.Editor.GetLineCount()
    x, y = N10X.Editor.GetCursorPos()

    while y < line_count - 1:
      text = N10X.Editor.GetLine(y + 1)
      if not text or text.isspace():
        return y
      y += 1
    return y

#------------------------------------------------------------------------
def MoveToPreviousParagraphBegin():
    SetCursorPos(0, FindPreviousParagraphBegin())

#------------------------------------------------------------------------
def MoveToNextParagraphEnd():
    line_count = N10X.Editor.GetLineCount()
    y = FindNextParagraphEnd()
    if y != line_count:
        SetCursorPos(0, y + 1)
    else:
        SetCursorPos(GetLineLength(line_count - 1) - 1, line_count)

   
#------------------------------------------------------------------------
def GetAroundParagraphSelection():
    line_count = N10X.Editor.GetLineCount()
    start = (0, FindPreviousEmptyLine())
    y_end = FindNextEmptyLine()
    end = (0, 0) 
    if y_end != line_count:
        end = (0, y_end + 1)
    else:
        end = (GetLineLength(line_count - 1) - 1, line_count)
    return (start, end)

#------------------------------------------------------------------------
def GetInsideParagraphSelection():
    line_count = N10X.Editor.GetLineCount()
    start = (0, FindPreviousEmptyLine() + 1)
    y_end = FindNextEmptyLine()
    end = (GetLineLength(y_end) - 1, y_end)
    return (start, end)

#------------------------------------------------------------------------
def NormalizeBlockChar(c):
    match c:
        case ']':
            return '['
        case '}':
            return '{'
        case ')':
            return '('
        case '>':
            return '<'
    
    return c
#------------------------------------------------------------------------
def GetBlockClosedChar(c):
    match c:
        case '[':
            return ']'
        case '{':
            return '}'
        case '(':
            return ')'
        case '<':
            return '>'

    return None

#------------------------------------------------------------------------
def FindEnclosingBlockStartPos(c, start, count=1):
    open_char = NormalizeBlockChar(c)
    closed_char = GetBlockClosedChar(c)

    x, y = start
    balance = count - 1

    while y >= 0:
        line = GetLine(y)
        if open_char not in line and closed_char not in line:
            y -= 1
            x = GetLineLength(y) - 1
            continue
            
        if line[x] == open_char:
            balance -= 1
            if balance == -1:
                return (x, y)
        elif line[x] == closed_char:
            balance += 1

        x, y = GetPrevCharPos(x, y)
    
    return None

#------------------------------------------------------------------------
def FindEnclosingBlockEndPos(c, start, count=1):
    open_char = NormalizeBlockChar(c)
    closed_char = GetBlockClosedChar(c)

    x, y = start
    balance = count - 1

    while not AtEndOfFile(x, y):
        line = GetLine(y)
        if open_char not in line and closed_char not in line:
            x, y = 0, y + 1
            continue

        if line[x] == closed_char:
            balance -= 1
            if balance == -1:
                return (x, y)
        elif line[x] == open_char:
            balance += 1

        x, y = GetNextCharPos(x, y)
    
    return None

#------------------------------------------------------------------------
def FindNextBlock(c, start, count=1):
    open_char = NormalizeBlockChar(c)
    closed_char = GetBlockClosedChar(c)

    x, y = start

    start = None
    end = None

    balance = count - 1

    while not AtEndOfFile(x, y):
        line = GetLine(y)

        if open_char not in line and closed_char not in line:
            x, y = 0, y + 1
            continue

        if line[x] == closed_char:
            balance -= 1
            if balance == 0:
                end = x, y
                break
        elif line[x] == open_char:
            if balance == 0:
                start = x, y
            balance += 1

        if balance <= -1:
            break

        x, y = GetNextCharPos(x, y)
 
    if start is not None and end is not None:
        return start, end

    return None

#------------------------------------------------------------------------
def FindSameLineBlockStartPos(c, start):
    open_char = NormalizeBlockChar(c)
    closed_char = GetBlockClosedChar(c)
    
    x, y = start
    line = GetLine(y)

    if open_char not in line:
        return None

    while x < len(line):
        if not IsWhitespaceChar(line[x]):
            if line[x] == open_char:
                return x
            elif line[x] == closed_char:
                return None
            else:
                return None
        x += 1
    return None
    
#------------------------------------------------------------------------
def GetBlockSelection(c, start, count=1):
    c = NormalizeBlockChar(c)
    x = FindSameLineBlockStartPos(c, start)
    if x is not None:
        start = x, start[1]
    if enc_start := FindEnclosingBlockStartPos(c, start, count):
        if enc_end := FindEnclosingBlockEndPos(c, (enc_start[0] + 1, enc_start[1]), 1):
            return enc_start, enc_end
    elif (next_block := FindNextBlock(c, start, count)):
        start, end = next_block
        return start, end
    return None

#------------------------------------------------------------------------
def GetInsideBlockSelectionOrPos(c, start, count=1):
    if sel := GetBlockSelection(c, start, count):
        start, end = sel

        start = start[0] + 1, start[1]
        end = end[0], end[1]

        start_newline = False
        end_newline = False

        line = GetLine(end[1])[:end[0]]
        if not line or line.isspace():
            end_newline = True
            end = len(GetLine(end[1] - 1)) - 1, end[1] - 1

        line = GetLine(start[1])
        if line[start[0]] == "\r":
            start_newline = True
            start = 0, start[1] + 1
            line = GetLine(start[1])
            if line and not line.isspace():
               start = GetNextNonWhitespaceCharPos(start[0], start[1])

        if start[1] > end[1]:
            return start
        elif start[1] == end[1] and start[0] >= end[0]:
            return start

        if start_newline and end_newline:
            start = -1, start[1]
            if end[1] == GetMaxY():
                end = (GetLineLength(end[1]), end[1])
            else:
                end = 0, end[1] + 1
        return start, (end[0] - 1, end[1])
    return None
    
#------------------------------------------------------------------------
def SelectAroundBlock(c, count=1):
    start = N10X.Editor.GetCursorPos()
    if sel := GetBlockSelection(c, start, count):
        start, end = sel
        SetSelection(start, end)
        return start
    return False

#------------------------------------------------------------------------
def SelectOrMoveInsideBlock(c, count=1, insert_after_move=False):
    start = N10X.Editor.GetCursorPos()
    match GetInsideBlockSelectionOrPos(c, start, count):
        case None:
            return False
        case ((a, b), (c, d)):
            SetSelection((a, b), (c, d))
            return (a, b), (c, d)
        case (pos):
            SetCursorPos(pos[0], pos[1])
            if insert_after_move:
                EnterInsertMode()
            return False
            
    return False 

#------------------------------------------------------------------------
def GetAroundWordSelection(start):
    x, y = start

    start_x = x
    end_x = x

    line = GetLine(y)

    character_class = GetCharacterClass(line[end_x])

    line_len = len(line)

    while end_x < line_len - 1:
        curr_class = GetCharacterClass(line[end_x + 1])
        if end_x < line_len - 2:
            next_class = GetCharacterClass(line[end_x + 2])
            if curr_class != next_class and next_class == character_class:
                end_x += 1
                break
        end_x += 1

    while start_x > 0 and GetCharacterClass(line[start_x - 1]) == character_class:
        start_x -= 1

    return (start_x, y), (end_x, y)

#------------------------------------------------------------------------
def GetInsideWordSelection(start):
    x, y = start
    x = min(GetLineLength(y) - 1, x)

    start_x = x
    end_x = x

    line = GetLine(y)

    character_class = GetCharacterClass(line[end_x])

    while end_x < len(line) - 1 and GetCharacterClass(line[end_x + 1]) == character_class:
        end_x += 1

    while start_x > 0 and GetCharacterClass(line[start_x - 1]) == character_class:
        start_x -= 1

    return (start_x, y), (end_x, y)

#------------------------------------------------------------------------
def GetAroundWordSelectionWithPunctuation(start):
    x, y = start

    start_x = x
    end_x = x

    line = GetLine(y)

    line_len = len(line)

    is_start_whitespace = GetCharacterClass(line[end_x]) == CharacterClass.WHITESPACE

    while end_x < line_len - 1:
        curr_class = GetCharacterClass(line[end_x + 1])
        if end_x < line_len - 2:
            next_class = GetCharacterClass(line[end_x + 2])
            if is_start_whitespace:
                if curr_class != CharacterClass.WHITESPACE and next_class == CharacterClass.WHITESPACE:
                    end_x += 1
                    break
            else:
                if curr_class == CharacterClass.WHITESPACE and next_class != CharacterClass.WHITESPACE:
                    end_x += 1
                    break
        end_x += 1

    while start_x > 0 and     (is_start_whitespace and GetCharacterClass(line[start_x - 1]) == CharacterClass.WHITESPACE) or \
                          (not is_start_whitespace and GetCharacterClass(line[start_x - 1]) != CharacterClass.WHITESPACE):
        start_x -= 1

    return (start_x, y), (end_x, y)


#------------------------------------------------------------------------
def GetInsideWordSelectionWithPunctuation(start):
    x, y = start
    x = min(GetLineLength(y) - 1, x)

    start_x = x
    end_x = x

    line = GetLine(y)

    character_class = GetCharacterClass(line[end_x])
    if character_class != CharacterClass.WHITESPACE:
        while end_x < len(line) - 1 and GetCharacterClass(line[end_x + 1]) != CharacterClass.WHITESPACE:
            end_x += 1

        while start_x > 0 and GetCharacterClass(line[start_x - 1]) != CharacterClass.WHITESPACE:
            start_x -= 1
    else:
        while end_x < len(line) - 1 and GetCharacterClass(line[end_x + 1]) == CharacterClass.WHITESPACE:
            end_x += 1

        while start_x > 0 and GetCharacterClass(line[start_x - 1]) == CharacterClass.WHITESPACE:
            start_x -= 1
    return (start_x, y), (end_x, y)

#------------------------------------------------------------------------
def GetQuoteSelection(c, start, whitespace=True):
    x, y = start

    line = GetLine(y)
    if matches := re.finditer(c + '(?:\\\\.|[^' + c + '\\\\])*' + c, line):
        for m in matches:
            if m.end() >= x:
                return (m.start(), y), (m.end() - 1, y)
    
    return None

#------------------------------------------------------------------------
def GetInsideQuoteSelection(c, start, whitespace=False):
    if sel := GetQuoteSelection(c, start, whitespace):
        start, end = sel
        if end[0] - start[0] < 2 and start[1] == end[1]:
            return start[0] + 1, start[1]

        return (start[0] + 1, start[1]), (end[0] - 1, end[1]),
    return None

#------------------------------------------------------------------------
def SelectAroundQuote(c, whitespace=True):
    start = N10X.Editor.GetCursorPos()
    if sel := GetQuoteSelection(c, start):
        start, end = sel
        SetSelection(start, end)
        return start
    return False
    
#------------------------------------------------------------------------
def SelectOrMoveInsideQuote(c, insert_after_move=False, whitespace=False):
    start = N10X.Editor.GetCursorPos()
    match GetInsideQuoteSelection(c, start, whitespace):
        case None:
            return False
        case ((a, b), (c, d)):
            SetSelection((a, b), (c, d))
            return (a, b), (c, d)
        case (pos):
            SetCursorPos(pos[0], pos[1])
            if insert_after_move:
                EnterInsertMode()
            return False

#------------------------------------------------------------------------
def MergeLines():
    SetCursorPos(x=GetLineLength(), max_offset=0)
    N10X.Editor.InsertText(" ")
    N10X.Editor.ExecuteCommand("Delete")

#------------------------------------------------------------------------
def MergeLinesTrimIndentation():
    x, y = N10X.Editor.GetCursorPos()
    startx = x
    startlinelen = GetLineLength(y)
    line = GetLine(y)
    SetCursorPos(x=startlinelen, max_offset=0)
    N10X.Editor.ExecuteCommand("Delete")
    x = startlinelen
    while x > 0 and IsWhitespaceChar(line[x]):
        x -= 1
    if not IsWhitespaceChar(line[x]):
        x += 1
    clearx = x
    line = GetLine(y)
    newlinelen = GetLineLength(y)
    x = startlinelen
    while x < newlinelen and IsWhitespaceChar(line[x]):
        x += 1
    if clearx != x:
        x -= 1
        SetSelection((clearx,y), (x,y))
        N10X.Editor.ExecuteCommand("Delete")
    N10X.Editor.InsertText(" ")
    SetCursorPos(startx,y)

#------------------------------------------------------------------------
def IsSearching():
    if g_Mode != Mode.COMMANDLINE:
        return False

    # / forward search, ? reverse search
    return g_Commandline.text[:1] == "/" or g_Commandline.text[:1] == "?"

#------------------------------------------------------------------------
def UpdateSearchText(search_text):
    if g_Mode != Mode.COMMANDLINE:
        return
   
    case_sensitive = False

    # When smart case is enabled, case-sensitive search is turned on
    # if any char is upper case in the search string.
    if g_SmartCaseEnabled:
        for c in search_text:
            if c.isupper():
                case_sensitive = True
                break

    word = False
    regex = False
    reverse = g_ReverseSearch
    # This is required for reverse search to work correctly
    start_pos = g_LastJumpPoint
    N10X.Editor.SetFindText(search_text, case_sensitive, word, regex, reverse, start_pos)

#------------------------------------------------------------------------
def GetHistoryBuffer():
    global g_Commandline 

    is_command = g_Commandline.text[0] == ':'
    is_search  = IsSearching() 

    if is_command:
        return g_Commandline.commandHistory
    elif is_search:
        return g_Commandline.searchHistory
    else:
        return [] 

#------------------------------------------------------------------------
def GetFilteredHistoryBuffer():
    global g_Commandline 
    history_buffer = GetHistoryBuffer()
    if g_UseFilteredCommandlineHistory:
        filter = history_buffer[-1]
        history_buffer = [elem for elem in history_buffer if elem.startswith(filter)]
    return history_buffer

#------------------------------------------------------------------------
# Key Intercepting

#------------------------------------------------------------------------
def HandleCommandModeChar(char):
    global g_Mode
    global g_Command
    global g_LastCommand
    global g_ReverseSearch
    global g_LastJumpPoint
    global g_JumpMap
    global g_SingleReplace
    global g_MultiReplace
    global g_SneakEnabled
    global g_PaneSwap
    global g_PerformingDot
    global g_RecordingName
    global g_NamedBuffers

    g_Command += char

    if g_Command == "":
        return

    m = re.match(g_RepeatMatch + "(.*)", g_Command)
    if not m:
        return

    repeat_count = int(m.group(1)) if m.group(1) else 1
    has_repeat_count = m.group(1) != None
    c = m.group(2)
    if not c:
        return
    
    should_save = False

    # pane

    if g_PaneSwap:
      if char == "h":
          N10X.Editor.ExecuteCommand("MovePanelFocusLeft")

      elif char == "l":
          N10X.Editor.ExecuteCommand("MovePanelFocusRight")

      elif char == "j":
          N10X.Editor.ExecuteCommand("MovePanelFocusDown")

      elif char == "k":
          N10X.Editor.ExecuteCommand("MovePanelFocusUp")

      elif char == "H":
          N10X.Editor.ExecuteCommand("MovePanelLeft")

      elif char == "L":
          N10X.Editor.ExecuteCommand("MovePanelRight")

      elif char == "J":
          N10X.Editor.ExecuteCommand("MovePanelDown")

      elif char == "K":
          N10X.Editor.ExecuteCommand("MovePanelUp")

      elif char == "n":
        x, y = N10X.Editor.GetCursorPos()
        N10X.Editor.ExecuteCommand("DuplicatePanel")
        N10X.Editor.ExecuteCommand("MovePanelDown")
        SetCursorPos(x,y)
    
      elif char == "v":
        x, y = N10X.Editor.GetCursorPos()
        N10X.Editor.ExecuteCommand("DuplicatePanelRight")
        SetCursorPos(x,y)
    
      elif char == "q" or char == "c":
        # TODO: This should close the pane not the file
        N10X.Editor.ExecuteCommand("CloseFile")

      g_PaneSwap = False

    elif c == ".":
        global g_InsertBuffer
        last = g_LastCommand
        if last == ".":
            return

        g_PerformingDot = True
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            g_Command = last
            HandleCommandModeChar("")
        N10X.Editor.PopUndoGroup();

        g_PerformingDot = False
        g_LastCommand = last

    # moving

    elif c == "h":
        for i in range(repeat_count):
            MoveCursorPos(x_delta=-1)

    elif c == "j":
        override_horizontal_target = True if g_Mode == Mode.VISUAL_BLOCK else False
        for i in range(repeat_count):
            MoveCursorPos(y_delta=1, override_horizontal_target=override_horizontal_target)

    elif c == "k":
        override_horizontal_target = True if g_Mode == Mode.VISUAL_BLOCK else False
        for i in range(repeat_count):
            MoveCursorPos(y_delta=-1, override_horizontal_target=override_horizontal_target)

    elif c == "l":
        for i in range(repeat_count):
            MoveCursorPos(x_delta=1)

    elif c == "b":
        for i in range(repeat_count):
            MoveToWordStart()

    elif c == "B":
        for i in range(repeat_count):
            MoveToTokenStart()

    elif c == "w":
        for i in range(repeat_count):
            MoveToNextWordStart()

    elif c == "W":
        for i in range(repeat_count):
            MoveToNextTokenStart()

    elif c == "e":
        for i in range(repeat_count):
            MoveToWordEnd()

    elif c == "E":
        for i in range(repeat_count):
            MoveToTokenEnd()

    elif c == "_" or c == "^":
        MoveToFirstNonWhitespace()
        
    elif c == "0":
        MoveToStartOfLine()

    elif c == "$":
        MoveToEndOfLine()

    elif c == "{":
        MoveToPreviousParagraphBegin()

    elif c == "}":
        MoveToNextParagraphEnd()

    elif c == "''":
        if g_LastJumpPoint:
            SetCursorPos(g_LastJumpPoint[0], g_LastJumpPoint[1])
     
    elif c == "'":
        return

    elif len(c) > 1 and c[0] == "'":
        if c[1] in g_JumpMap:
            jump = g_JumpMap[c[1]]
            g_LastJumpPoint = N10X.Editor.GetCursorPos()
            SetCursorPos(jump[0], jump[1])
        
    elif c == "gg":
        g_LastJumpPoint = N10X.Editor.GetCursorPos()
        x, _ = N10X.Editor.GetCursorPos()
        SetCursorPos(x, max(0, repeat_count - 1))

    elif c == "gt":
        if has_repeat_count:
            N10X.Editor.SetFocusedTab(repeat_count)
        else:
            N10X.Editor.ExecuteCommand("NextPanelTab")

    elif c == "gT":
        for i in range(repeat_count):
            N10X.Editor.ExecuteCommand("PrevPanelTab")

    elif c == "G":
        g_LastJumpPoint = N10X.Editor.GetCursorPos()
        x, _ = N10X.Editor.GetCursorPos()
        if has_repeat_count:
            SetCursorPos(x, max(0, repeat_count - 1))
        else:
            MoveToEndOfFile()

    elif c == "g":
        return

    elif c == "H":
        scroll_line = N10X.Editor.GetScrollLine()
        SetCursorPos(y=scroll_line+1)

    elif c == "L":
        scroll_line = N10X.Editor.GetScrollLine()
        visible_line_count = N10X.Editor.GetVisibleLineCount()
        SetCursorPos(y=scroll_line + visible_line_count-2)

    elif c == "M":
        scroll_line = N10X.Editor.GetScrollLine()
        visible_line_count = N10X.Editor.GetVisibleLineCount()
        SetCursorPos(y=scroll_line + int(visible_line_count / 2))

    elif c == "%":
        N10X.Editor.ExecuteCommand("MoveToMatchingBracket")

    elif c == "m":
        return

    elif len(c) > 1 and c[0] == "m":
        g_JumpMap[c[1]] = N10X.Editor.GetCursorPos()

    # misc

    elif c == "~":
        x, y = N10X.Editor.GetCursorPos()
        line = GetLine()
        length = GetLineLength()
        if length > 0:
            N10X.Editor.PushUndoGroup()
            line = line[:x] + line[x].swapcase() + line[x + 1:]
            N10X.Editor.SetLine(y, line)
            N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "z":
        return

    elif c == "zt":
        # Apply offset so we don't set the current line as the first visible line but the one just after.
        # This is so we can smooth scroll up using k after zt because 10x prevents the cursor being
        # on the first visible line.
        offset = 1
        N10X.Editor.SetScrollLine(max(0, N10X.Editor.GetCursorPos()[1] - offset))

    elif c == "zz":
        N10X.Editor.CenterViewAtLinePos(N10X.Editor.GetCursorPos()[1])

    elif c == "zb":
        # Apply offset so we don't set the current line as last visible line but the one just before.
        # This is so we can smooth scroll down using j after zb because 10x prevents the cursor being
        # on the last visible line.
        offset = 1
        # Subtract 1 because ScrollLine is 0 indexed
        bottom = N10X.Editor.GetScrollLine() + N10X.Editor.GetVisibleLineCount() - 1 - offset
        scroll_delta = bottom - N10X.Editor.GetCursorPos()[1]
        N10X.Editor.SetScrollLine(max(0, N10X.Editor.GetScrollLine() - scroll_delta))

    elif c == " ":
        Unhilight()
    
    # Deleting

    elif c == "dd":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(y, y + repeat_count - 1)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(x, y)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "de":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        for _ in range(repeat_count):
            MoveToWordEnd()
        end = N10X.Editor.GetCursorPos()
        if start != end:
            end = (max(0, end[0]), end[1])
            SetSelection(start, end)
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "dE":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        for _ in range(repeat_count):
            MoveToTokenEnd()
        end = N10X.Editor.GetCursorPos()
        if start != end:
            end = (max(0, end[0]), end[1])
            SetSelection(start, end)
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "dw":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        for _ in range(repeat_count):
            MoveToNextWordStart()
        end = N10X.Editor.GetCursorPos()
        if start != end:
            end = (max(0, end[0] - 1), end[1])
            SetSelection(start, end)
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "dW":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        for _ in range(repeat_count):
            MoveToNextTokenStart()
        end = N10X.Editor.GetCursorPos()
        if start != end:
            end = (max(0, end[0] - 1), end[1])
            SetSelection(start, end)
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "db":
        N10X.Editor.PushUndoGroup()
        end = N10X.Editor.GetCursorPos()
        for _ in range(repeat_count):
            MoveToWordStart()
        start = N10X.Editor.GetCursorPos()
        if start != end:
            end = (max(0, end[0] - 1), end[1])
            SetSelection(start, end)
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "dB":
        N10X.Editor.PushUndoGroup()
        end = N10X.Editor.GetCursorPos()
        for _ in range(repeat_count):
            MoveToTokenStart()
        start = N10X.Editor.GetCursorPos()
        if start != end:
            end = (max(0, end[0] - 1), end[1])
            SetSelection(start, end)
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "diw":
        N10X.Editor.PushUndoGroup() 
        start, end = GetInsideWordSelection(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "diW":
        N10X.Editor.PushUndoGroup()
        start, end = GetInsideWordSelectionWithPunctuation(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "daw":
        N10X.Editor.PushUndoGroup()
        start, end = GetAroundWordSelection(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "daW":
        N10X.Editor.PushUndoGroup()
        start, end = GetAroundWordSelectionWithPunctuation(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "dip":
        N10X.Editor.PushUndoGroup() 
        start, end = GetInsideParagraphSelection()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "dap":
        N10X.Editor.PushUndoGroup()
        start, end = GetAroundParagraphSelection()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("d" + g_RepeatMatch + "i" + g_BlockMatch, c)):
        N10X.Editor.PushUndoGroup()
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        if sel := SelectOrMoveInsideBlock(action, count):
            start, _ = sel
            N10X.Editor.ExecuteCommand("Cut")
            SetCursorPos(start[0], start[1])
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("d" + g_RepeatMatch + "a" + g_BlockMatch, c)):
        N10X.Editor.PushUndoGroup()
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        if pos := SelectAroundBlock(action, count):
            N10X.Editor.ExecuteCommand("Cut")
            SetCursorPos(pos[0], pos[1])
        N10X.Editor.PopUndoGroup()
        should_save = True
    
    elif (m := re.match("di([`'\"])", c)):
        action = m.group(1)
        if sel := SelectOrMoveInsideQuote(m.group(1)):
            start, end = sel
            N10X.Editor.PushUndoGroup()
            N10X.Editor.ExecuteCommand("Cut")
            SetCursorPos(start[0], start[1])
            N10X.Editor.PopUndoGroup()
        should_save = True
    
    elif (m := re.match("da([`'\"])", c)):
        action = m.group(1)
        if pos := SelectAroundQuote(m.group(1)):
            N10X.Editor.PushUndoGroup()
            N10X.Editor.ExecuteCommand("Cut")
            SetCursorPos(pos[0], pos[1])
            N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("d" + g_RepeatMatch + "h", c)):
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            x, y = N10X.Editor.GetCursorPos()
            count = int(m.group(1)) if m.group(1) else 1
            start_x = max(0, x - count)
            end_x = max(0, x - 1)
            SetSelection((start_x, y), (end_x, y))
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("d" + g_RepeatMatch + "j", c)):
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            x, y = N10X.Editor.GetCursorPos()
            count = int(m.group(1)) if m.group(1) else 1
            end_y = min(y + count, GetMaxY())
            SetLineSelection(y, end_y)
            N10X.Editor.ExecuteCommand("Cut")
            SetCursorPos(0, y - 1)
        MoveCursorPos(y_delta=1, override_horizontal_target=False)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("d" + g_RepeatMatch + "k", c)):
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            x, y = N10X.Editor.GetCursorPos()
            count = int(m.group(1)) if m.group(1) else 1
            end_y = min(y - count, GetMaxY())
            SetLineSelection(y, end_y)
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("d" + g_RepeatMatch + "l", c)):
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            x, y = N10X.Editor.GetCursorPos()
            count = int(m.group(1)) if m.group(1) else 1
            end_x = x + count - 1
            max_x = max(0, GetLineLength(y) - 1)
            end_x = Clamp(0, max_x, end_x)
            SetSelection((x, y), (end_x, y))
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("d" + g_RepeatMatch + "{", c)):
        count = int(m.group(1)) if m.group(1) else 1
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            x, y = N10X.Editor.GetCursorPos()
            for i in range(count):
                MoveToPreviousParagraphBegin()
                x, end_y = N10X.Editor.GetCursorPos()
            SetLineSelection(y, end_y)
            N10X.Editor.ExecuteCommand("Cut")
            SetCursorPos(0, end_y - 1)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("d" + g_RepeatMatch + "}", c)):
        count = int(m.group(1)) if m.group(1) else 1
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            x, y = N10X.Editor.GetCursorPos()
            for i in range(count):
                MoveToNextParagraphEnd()
                x, end_y = N10X.Editor.GetCursorPos()
            SetLineSelection(y, end_y)
            N10X.Editor.ExecuteCommand("Cut")
            SetCursorPos(0, y - 1)
        MoveCursorPos(y_delta=1, override_horizontal_target=False)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("d" + g_RepeatMatch + "([fFtT;,])(.?)", c)):
        N10X.Editor.PushUndoGroup()
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        search = m.group(3)
        start = N10X.Editor.GetCursorPos()
        for i in range(repeat_count):
            for _ in range(count):
                if not MoveToLineText(action, search):
                    N10X.Editor.PopUndoGroup()
                    return
        end = N10X.Editor.GetCursorPos()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "d%":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        N10X.Editor.ExecuteCommand("MoveToMatchingBracket")
        end = N10X.Editor.GetCursorPos()
        if start != end:
            SetSelection(start, end)
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "dgg":
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(y, 0)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(x, 0)
        should_save = True

    elif c == "dG":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        if y:
            sel_start = (GetLineLength(y - 1), y - 1)
        else:
            sel_start = (0,0)
        sel_end = (GetLineLength(GetMaxY()), GetMaxY())
        SetSelection(sel_start, sel_end)
        N10X.Editor.ExecuteCommand("Cut")
        end_x, end_y = GetNextNonWhitespaceCharPos(0, GetMaxY(), False)
        SetCursorPos(end_x, end_y)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "d0":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        end_x = max(0, x - 1)
        SetSelection((0, y), (end_x, y))
        N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True
        
    elif c == "d_" or c == "d^":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        end_x = max(0, x - 1)
        first_x, first_y = GetFirstNonWhitespace(y) 
        SetSelection((first_x, y), (end_x, y))
        N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "D" or c == "d$":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetSelection((x, y), (GetLineLength(), y))
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(x - 1, y)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m:= re.match("d'([a-zA-Z])", c)):
        if m.group(1) in g_JumpMap:
            jump = g_JumpMap[m.group(1)]
            N10X.Editor.PushUndoGroup()
            x, y = N10X.Editor.GetCursorPos()
            SetSelection((x, y), jump)
            N10X.Editor.ExecuteCommand("Cut")
            N10X.Editor.PopUndoGroup()
            should_save = True

    elif (m := re.match("d" + g_RepeatMatch, c)) or c == "dg":
        return

    elif c == "x":
        x, y = N10X.Editor.GetCursorPos()
        N10X.Editor.PushUndoGroup()
        SetSelection((x, y), (x + repeat_count-1, y))
        N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "X":
        x, y = N10X.Editor.GetCursorPos()
        x -= 1
        N10X.Editor.PushUndoGroup()
        SetSelection((x - repeat_count +1, y), (x , y))
        N10X.Editor.ExecuteCommand("Delete")
        N10X.Editor.PopUndoGroup()

    elif not g_SneakEnabled and c == "s":
        x, y = N10X.Editor.GetCursorPos()
        N10X.Editor.PushUndoGroup()
        SetSelection((x, y), (x + repeat_count-1, y))
        N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()
        should_save = True
        # NOTE- incomplete. if you "s" and type some stuff, a single "undo" should remove the typed stuff AND the deleted character

    # Searching

    elif c == "*":
        for _ in range(repeat_count):
            cached_find_by_word = N10X.Editor.GetFindByWord()
            cached_case = N10X.Editor.GetFindByCase()
            cached_regex = N10X.Editor.GetFindByRegex()
            # Set word to stop partial matching, case off, regex off
            N10X.Editor.SetFindByWord(True)
            N10X.Editor.SetFindByCase(False)
            N10X.Editor.SetFindByRegex(False)
            N10X.Editor.ExecuteCommand("FindInFileNextCurrentWord")
            # Unset options
            N10X.Editor.SetFindByWord(cached_find_by_word)
            N10X.Editor.SetFindByCase(cached_case)
            N10X.Editor.SetFindByRegex(cached_regex)

    elif c == "#":
        for _ in range(repeat_count):
            cached_find_by_word = N10X.Editor.GetFindByWord()
            cached_case = N10X.Editor.GetFindByCase()
            cached_regex = N10X.Editor.GetFindByRegex()
            # Set word to stop partial matching, case off, regex off
            N10X.Editor.SetFindByWord(True)
            N10X.Editor.SetFindByCase(False)
            N10X.Editor.SetFindByRegex(False)
            N10X.Editor.ExecuteCommand("FindInFilePrevCurrentWord")
            # Unset options
            N10X.Editor.SetFindByWord(cached_find_by_word)
            N10X.Editor.SetFindByCase(cached_case)
            N10X.Editor.SetFindByRegex(cached_regex)

    elif c == "/":
        g_LastJumpPoint = N10X.Editor.GetCursorPos()
        g_ReverseSearch = False
        if g_Use10xFindPanel:
            N10X.Editor.ExecuteCommand("FindInFile")
        else:
            EnterCommandlineMode(c)

    elif c == "?":
        g_ReverseSearch = True
        g_LastJumpPoint = N10X.Editor.GetCursorPos()
        if g_Use10xFindPanel:
            N10X.Editor.ExecuteCommand("FindInFile")
        else:
            EnterCommandlineMode(c)

    elif g_SneakEnabled and (m := re.match("([fFtTsS;,])(.{0,2})", c)):
        for i in range(repeat_count):
            action = m.group(1)
            search = m.group(2)
            if not MoveToLineText(action, search):
                return

    elif not g_SneakEnabled and (m := re.match("([fFtT;,])(.?)", c)):
        for i in range(repeat_count):
            action = m.group(1)
            search = m.group(2)
            if not MoveToLineText(action, search):
                return

    elif c == "n":
        if g_ReverseSearch:
            N10X.Editor.ExecuteCommand("FindInFilePrev")
        else:
            N10X.Editor.ExecuteCommand("FindInFileNext")

    elif c == "N":
        if g_ReverseSearch:
            N10X.Editor.ExecuteCommand("FindInFileNext")
        else:
            N10X.Editor.ExecuteCommand("FindInFilePrev")

    # Inserting

    elif c == "i":
        Unhilight()
        EnterInsertMode()
        should_save = True

    elif c == "r":
        Unhilight()
        g_SingleReplace = True
        EnterInsertMode()
        should_save = True

    elif c == "R":
        Unhilight()
        g_MultiReplace = True
        EnterInsertMode()
        should_save = True
        
    elif c == "I":
        MoveToStartOfLine()
        MoveToNextNonWhitespaceChar(wrap=False)
        EnterInsertMode()
        should_save = True

    elif c == "a":
        MoveCursorPos(x_delta=1, max_offset=0)
        EnterInsertMode()
        should_save = True

    elif c == "A":
        SetCursorPos(x=GetLineLength(), max_offset=0)
        EnterInsertMode()
        should_save = True

    elif c == "o":
        N10X.Editor.PushUndoGroup()
        SetCursorPos(x=GetLineLength(), max_offset=0)
        SendKey("Enter")
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()
        should_save = True

    elif c == "O":
        N10X.Editor.ExecuteCommand("InsertLine")
        EnterInsertMode()
        should_save = True

    # Editing

    elif c == "cc":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        end_y = y + repeat_count - 1
        SetSelection((0, y), (GetLineLength(end_y), end_y))
        N10X.Editor.ExecuteCommand("Cut")
        AddNewlineToClipboard()
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "cgg":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        SetLineSelection(0, start[1])
        N10X.Editor.ExecuteCommand("Cut")
        AddNewlineToClipboard()
        N10X.Editor.ExecuteCommand("InsertLine")
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "cg":
        return

    elif c == "cG":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        SetLineSelection(start[1], GetMaxY())
        N10X.Editor.ExecuteCommand("Cut")
        AddNewlineToClipboard()
        N10X.Editor.ExecuteCommand("InsertLine")
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "ce":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        for i in range(repeat_count):
            MoveToWordEnd()
        end = N10X.Editor.GetCursorPos()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1], max_offset=0)
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "cE":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        for i in range(repeat_count):
            MoveToTokenEnd()
        end = N10X.Editor.GetCursorPos()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1], max_offset=0)
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "cw":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        for i in range(repeat_count):
            MoveToWordEnd()
        end = N10X.Editor.GetCursorPos()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1], max_offset=0)
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "cW":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        for i in range(repeat_count):
            MoveToTokenEnd()
        end = N10X.Editor.GetCursorPos()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1], max_offset=0)
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True
    
    elif c == "cb": 
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        for i in range(repeat_count):
            MoveToWordStart()
        end = N10X.Editor.GetCursorPos()
        if start[0] > 0:  
            SetSelection(end, (start[0] - 1, start[1]))
            N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(end[0], end[1], max_offset=0)
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "cB":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        for i in range(repeat_count):
            MoveToTokenStart()
        end = N10X.Editor.GetCursorPos()
        if start[0] > 0:  
            SetSelection(end, (start[0] - 1, start[1]))
            N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(end[0], end[1], max_offset=0)
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "ciw":
        start, end = GetInsideWordSelection(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()
        should_save = True

    elif c == "ciW":
        start, end = GetInsideWordSelectionWithPunctuation(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()
        should_save = True

    elif c == "caw":
        start, end = GetAroundWordSelection(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()
        should_save = True

    elif c == "caW":
        start, end = GetAroundWordSelectionWithPunctuation(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()
        should_save = True

    elif c == "cip":
        start, end = GetInsideParagraphSelection()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()
        should_save = True

    elif c == "cap":
        start, end = GetAroundParagraphSelection()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()
        should_save = True


    elif (m := re.match("c" + g_RepeatMatch + "i" + g_BlockMatch, c)):
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        if sel := SelectOrMoveInsideBlock(action, count, True):
            start, end = sel
            N10X.Editor.PushUndoGroup()
            insert_line = GetLine(start[1] - 1)[-3:-1] == action + "\r\n"
            N10X.Editor.ExecuteCommand("Cut")
            if insert_line:
                N10X.Editor.ExecuteCommand("InsertLine")
            EnterInsertMode()
            N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("c" + g_RepeatMatch + "a" + g_BlockMatch, c)):
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        if pos := SelectAroundBlock(action, count):
            N10X.Editor.PushUndoGroup()
            N10X.Editor.ExecuteCommand("")
            EnterInsertMode()
            N10X.Editor.PopUndoGroup()
        should_save = True
    
    elif (m := re.match("ci([`'\"])", c)):
        action = m.group(1)
        if SelectOrMoveInsideQuote(action, True):
            N10X.Editor.PushUndoGroup()
            N10X.Editor.ExecuteCommand("Cut")
            EnterInsertMode()
            N10X.Editor.PopUndoGroup()
        should_save = True
    
    elif (m := re.match("ca([`'\"])", c)):
        action = m.group(1)
        if SelectAroundQuote(action):
            N10X.Editor.PushUndoGroup()
            N10X.Editor.ExecuteCommand("Cut")
            EnterInsertMode()
            N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("c" + g_RepeatMatch + "([hl])", c)):
        x, y = N10X.Editor.GetCursorPos()
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        if m.group(2) == "l":
            SetSelection((x, y), (x + count - 1, y))
        else:
            SetSelection((max(0, x - 1), y), (max(0, x - count), y))
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()
        should_save = True

    elif c == "c0":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetSelection((0, y), (max(0, x - 1), y))
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True
        
    elif c == "c_" or c == "c^":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        first_x, first_y = GetFirstNonWhitespace(y) 
        SetSelection((first_x, y), (max(0, x - 1), y))
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "C" or c == "c$":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetSelection((x, y), (GetLineLength(y), y))
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("c" + g_RepeatMatch + "j", c)):
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        count = int(m.group(1)) if m.group(1) else 1
        end_y = min(y + count, GetMaxY())
        N10X.Editor.SetSelection((0, y), (GetLineLength(end_y), end_y))
        N10X.Editor.ExecuteCommand("Cut")
        AddNewlineToClipboard()
        SetCursorPos(x, min(y, end_y), max_offset=0)
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("c" + g_RepeatMatch + "k", c)):
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        count = int(m.group(1)) if m.group(1) else 1
        end_y = max(0, y - count)
        N10X.Editor.SetSelection((GetLineLength(y), y), (0, end_y))
        N10X.Editor.ExecuteCommand("Cut")
        AddNewlineToClipboard()
        SetCursorPos(x, min(y, end_y), max_offset=0)
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("c" + g_RepeatMatch + "([fFtT;,])(.?)", c)):
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        search = m.group(3)
        for _ in range(count):
            if not MoveToLineText(action, search):
                N10X.Editor.PopUndoGroup()
                return
        end = N10X.Editor.GetCursorPos()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(x=min(start[0], end[0]), max_offset=0)
        EnterInsertMode()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif (m := re.match("c" + g_RepeatMatch, c)):
        return

    elif c == "gJ":
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            MergeLines()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "J":
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            MergeLinesTrimIndentation()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == ">":
        return

    elif c == ">>":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(y, y + repeat_count - 1)
        N10X.Editor.ExecuteCommand("IndentLine")
        N10X.Editor.ClearSelection()
        SetCursorPos(x, y)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == ">j":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(y, y + repeat_count)
        N10X.Editor.ExecuteCommand("IndentLine")
        N10X.Editor.ClearSelection()
        SetCursorPos(x, y)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == ">k":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(y, y - repeat_count)
        N10X.Editor.ExecuteCommand("IndentLine")
        N10X.Editor.ClearSelection()
        SetCursorPos(x, y)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "<":
        return

    elif c == "<<":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(y, y + repeat_count - 1)
        N10X.Editor.ExecuteCommand("UnindentLine")
        N10X.Editor.ClearSelection()
        SetCursorPos(x, y)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "<j":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(y, y + repeat_count)
        N10X.Editor.ExecuteCommand("UnindentLine")
        N10X.Editor.ClearSelection()
        SetCursorPos(x, y)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "<k":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(y, y - repeat_count)
        N10X.Editor.ExecuteCommand("UnindentLine")
        N10X.Editor.ClearSelection()
        SetCursorPos(x, y)
        N10X.Editor.PopUndoGroup()
        should_save = True
    # Undo/Redo

    elif c == "u":
        for i in range(repeat_count):
            N10X.Editor.ExecuteCommand("Undo")
            x, y = N10X.Editor.GetSelectionStart()
            N10X.Editor.ClearSelection()
            SetCursorPos(x, y)

    # Copying

    elif c == "yy" or c == "Y":
        x, y = N10X.Editor.GetCursorPos()
        end_y = min(y + repeat_count - 1, GetMaxY())
        SetLineSelection(y, end_y)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(x, y)

    elif c == "yg":
        return

    elif c == "ygg":
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(0, y)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(x, 0)

    elif c == "yG":
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(y, GetMaxY())
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(x, y)

    elif c == "yw":
        start = N10X.Editor.GetCursorPos()
        for i in range(repeat_count):
            if MoveToNextWordStart(wrap=False):
                MoveCursorPos(x_delta=-1)
        end = N10X.Editor.GetCursorPos()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(start[0], start[1])

    elif c == "yiw":
        start, end = GetInsideWordSelection(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(start[0], start[1])

    elif c == "yiW":
        start, end = GetInsideWordSelectionWithPunctuation(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(start[0], start[1])

    elif c == "yaw":
        start, end = GetAroundWordSelection(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(start[0], start[1])

    elif c == "yaW":
        start, end = GetAroundWordSelectionWithPunctuation(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(start[0], start[1])

    elif c == "yip":
        start, end = GetInsideParagraphSelection()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(start[0], start[1])

    elif c == "yap":
        start, end = GetAroundParagraphSelection()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(start[0], start[1])

    elif (m := re.match("y" + g_RepeatMatch + "i" + g_BlockMatch, c)):
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        if sel := SelectOrMoveInsideBlock(action, count):
            start, end = sel
            N10X.Editor.ExecuteCommand("Copy")
            SetCursorPos(start[0], start[1])

    elif (m := re.match("y" + g_RepeatMatch + "a" + g_BlockMatch, c)):
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        if pos := SelectAroundBlock(action, count):
            N10X.Editor.ExecuteCommand("Copy")
            SetCursorPos(pos[0], pos[1])
    
    elif (m := re.match("yi([`'\"])", c)):
        action = m.group(1)
        if sel := SelectOrMoveInsideQuote(m.group(1)):
            start, end = sel
            N10X.Editor.ExecuteCommand("Copy")
            SetCursorPos(start[0], start[1])
    
    elif (m := re.match("ya([`'\"])", c)):
        action = m.group(1)
        if pos := SelectAroundQuote(m.group(1), N10X.Editor.GetCursorPos()):
            N10X.Editor.ExecuteCommand("Copy")
            SetCursorPos(pos[0], pos[1])

    elif (m := re.match("y" + g_RepeatMatch + "h", c)):
        start = N10X.Editor.GetCursorPos()
        count = int(m.group(1)) if m.group(1) else 1
        MoveCursorPos(x_delta=-count)
        end = N10X.Editor.GetCursorPos()
        start = (max(0, start[0] - 1), start[1])
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(end[0], end[1])

    elif (m := re.match("y" + g_RepeatMatch + "l", c)):
        start = N10X.Editor.GetCursorPos()
        count = int(m.group(1)) if m.group(1) else 1
        MoveCursorPos(x_delta=count-1)
        end = N10X.Editor.GetCursorPos()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(x = start[0])

    elif c == "y0":
        x, y = N10X.Editor.GetCursorPos()
        SetSelection((0, y), (max(0, x - 1), y))
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(0, y)
        
    elif c == "y_" or c == "y^":
        x, y = N10X.Editor.GetCursorPos()
        first_x, first_y = GetFirstNonWhitespace(y) 
        SetSelection((first_x, y), (max(0, x - 1), y))
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(first_x, y)

    elif c == "y$":
        x, y = N10X.Editor.GetCursorPos()
        SetSelection((x, y), (GetLineLength(y), y))
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(x, y)

    elif (m := re.match("y" + g_RepeatMatch + "([jk])", c)):
        start = N10X.Editor.GetCursorPos()
        count = int(m.group(1)) if m.group(1) else 1
        delta = 1 if m.group(2) == 'j' else -1
        MoveCursorPos(y_delta=delta*count)
        end = N10X.Editor.GetCursorPos()
        SetLineSelection(start[1], end[1])
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(x=start[0], y=min(start[1], end[1]))

    elif (m := re.match("y" + g_RepeatMatch + "([fFtT;,])(.?)", c)):
        start = N10X.Editor.GetCursorPos()
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        search = m.group(3)
        for _ in range(count):
            if not MoveToLineText(action, search):
                return
        end = N10X.Editor.GetCursorPos()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(x=min(start[0], end[0]))

    elif (m := re.match("y" + g_RepeatMatch, c)):
        return

    # Pasting

    elif c == "p":
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            clipboard_value = GetClipboardValue()
            if clipboard_value and clipboard_value[-1:] == "\n":
                SetCursorPos(x=GetLineLength(), max_offset=0)
                SendKey("Enter")
                MoveToStartOfLine()
                start = N10X.Editor.GetCursorPos()
                N10X.Editor.SetLine(start[1], "")
                N10X.Editor.InsertText(clipboard_value.rstrip())
                x, y = GetNextNonWhitespaceCharPos(start[0], start[1], False)
                SetCursorPos(x, y)
            else:
                MoveCursorPos(x_delta=1, max_offset=0)
                N10X.Editor.ExecuteCommand("Paste")
                MoveCursorPos(x_delta=-1, max_offset=0)
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "P":
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            clipboard_value = GetClipboardValue()
            if clipboard_value and clipboard_value[-1:] == "\n":
                SetCursorPos(x=GetLineLength(), max_offset=0)
                N10X.Editor.ExecuteCommand("InsertLine")
                MoveToStartOfLine()
                start = N10X.Editor.GetCursorPos()
                N10X.Editor.SetLine(start[1], "")
                N10X.Editor.InsertText(clipboard_value.rstrip())
                x, y = GetNextNonWhitespaceCharPos(start[0], start[1], False)
                SetCursorPos(x, y)
            else:
                N10X.Editor.ExecuteCommand("Paste")
                MoveCursorPos(x_delta=-1, max_offset=0)
        N10X.Editor.PopUndoGroup()
        should_save = True

    # Folding

    elif c == "zc":
        N10X.Editor.ExecuteCommand("CollapseRegion")
    elif c == "zo":
        N10X.Editor.ExecuteCommand("ExpandRegion")
    elif c == "za":
        N10X.Editor.ExecuteCommand("ToggleCollapseExpandRegion")
    elif c == "zR":
        N10X.Editor.ExecuteCommand("ExpandAllRegions")
    elif c == "zM":
        N10X.Editor.ExecuteCommand("CollapseAllRegions")

    # Macros

    elif (m := re.match("q(.)", c)):
        if g_RecordingName == "":
            N10X.Editor.ExecuteCommand("RecordKeySequence")
            g_RecordingName = m.group(1)
            print("[vim] recording to "+g_RecordingName)
            g_NamedBuffers[g_RecordingName] = []

    elif c == "q":
        if g_RecordingName != "":
            # Stop Recording
            N10X.Editor.ExecuteCommand("RecordKeySequence")
            TrimBuffer(g_NamedBuffers[g_RecordingName]) # KEY(Q)
            TrimBuffer(g_NamedBuffers[g_RecordingName]) # CHAR_KEY(q)
            g_RecordingName = ""
        else:
            return

    elif c == "@":
        return

    elif (m := re.match("@(.)", c)):
        if m.group(1) in g_NamedBuffers:
            g_Command = "" # MUST CLEAR BEFORE PLAYBACK!
            N10X.Editor.PushUndoGroup()
            for i in range(repeat_count):
                PlaybackBuffer(g_NamedBuffers[m.group(1)])
                # N10X.Editor.ExecuteCommand("PlaybackKeySequence") # editor PlaybackKeySequence would play most recent, need to play named
            N10X.Editor.PopUndoGroup()
            return
        else:
            print("[vim] no named buffer \""+m.group(1)+"\" recorded")

    # Command line Panel
    elif c == ":":
        if g_Use10xCommandPanel:
            N10X.Editor.ExecuteCommand("ShowCommandPanel")
            N10X.Editor.SetCommandPanelText(":")
        else:
            EnterCommandlineMode(c)


    # Visual Mode

    elif c == "v":
        EnterVisualMode(Mode.VISUAL)

    elif c == "V":
        EnterVisualMode(Mode.VISUAL_LINE)

    # File

    elif c == "S":
        N10X.Editor.ExecuteCommand("SaveFile")

    elif c == "Q":
        N10X.Editor.ExecuteCommand("CloseFile")

    # Symbols

    elif c == "K":
        N10X.Editor.ExecuteCommand("ShowSymbolInfo")

    elif c == "gd":
        N10X.Editor.ExecuteCommand("GotoSymbolDefinition")

    elif c == "gr":
        N10X.Editor.ExecuteCommand("FindSymbolReferences")

    else:
        print("[vim] Unknown command!")

    ClearCommandStr(should_save)


#------------------------------------------------------------------------
def HandleCommandModeKey(key: Key):
    global g_HandlingKey
    global g_Command
    global g_PaneSwap

    if g_HandlingKey:
        return
    g_HandlingKey = True

    # Call user bindings
    user_result = VimUser.UserHandleCommandModeKey(key)
    if user_result == UserHandledResult.HANDLED:
        g_HandlingKey = False
        return True
    elif user_result == UserHandledResult.PASS_TO_10X:
        g_HandlingKey = False
        return False

    handled = True

    pass_through = False

    if key == Key("Escape") or key == Key("C", control=True):
        EnterCommandMode()

    elif g_PaneSwap:
        pass

    # Turn Vim bindings off
    elif key == Key("F12", control=True, shift=True):
        print("[vim] vim bindings disabled")
        N10X.Editor.RemoveSettingOverride("ReverseFindSelection")
        EnterSuspendedMode()

    elif key == Key("/", control=True):
        x, y = N10X.Editor.GetCursorPos()
        if InVisualMode():
            SubmitVisualModeSelection()
            N10X.Editor.ExecuteCommand("ToggleComment")
            N10X.Editor.ClearSelection()
        else:
            SetLineSelection(y, y)
            N10X.Editor.ExecuteCommand("ToggleComment")
            N10X.Editor.ClearSelection()
        SetCursorPos(x=x, y=y)

    elif key == Key("Tab", shift=True):
        N10X.Editor.ExecuteCommand("PrevPanelTab")

    elif key == Key("Tab"):
        N10X.Editor.ExecuteCommand("NextPanelTab")
   
    elif key == Key("A", control=True):
        pass # todo
   
    elif key == Key("V", control=True):
        if g_VisualBlockModeEnabled: 
            EnterVisualMode(Mode.VISUAL_BLOCK)
   
    elif key == Key("Z", control=True):
        N10X.Editor.ExecuteCommand("Undo")

    elif key == Key("X", control=True):
        pass

    elif key == Key("W", control=True):
        g_PaneSwap = True

    elif key == Key("H", control=True):
        N10X.Editor.ExecuteCommand("MovePanelFocusLeft")

    elif key == Key("L", control=True):
        N10X.Editor.ExecuteCommand("MovePanelFocusRight")

    elif key == Key("J", control=True):
        N10X.Editor.ExecuteCommand("MovePanelFocusDown")

    elif key == Key("K", control=True):
        N10X.Editor.ExecuteCommand("MovePanelFocusUp")

    elif key == Key("R", control=True):
        N10X.Editor.ExecuteCommand("Redo")

    elif key == Key("P", control=True):
        SubmitVisualModeSelection()
        N10X.Editor.ExecuteCommand("Search")

    elif key == Key("U", control=True):
        MoveCursorPos(y_delta=int(-N10X.Editor.GetVisibleLineCount()/2))
        N10X.Editor.ScrollCursorIntoView()

    elif key == Key("D", control=True):
        MoveCursorPos(y_delta=int(N10X.Editor.GetVisibleLineCount()/2))
        N10X.Editor.ScrollCursorIntoView()

    elif key == Key("B", control=True):
        N10X.Editor.SendKey("PageUp")

    elif key == Key("F", control=True):
        N10X.Editor.SendKey("PageDown")

    elif key == Key("Y", control=True):
        scroll_line = N10X.Editor.GetScrollLine()
        N10X.Editor.SetScrollLine(scroll_line - 1)

    elif key == Key("E", control=True):
        scroll_line = N10X.Editor.GetScrollLine()
        N10X.Editor.SetScrollLine(scroll_line + 1)

    elif key == Key("O", control=True):
        N10X.Editor.ExecuteCommand("PrevLocation")

    elif key == Key("I", control=True):
        N10X.Editor.ExecuteCommand("NextLocation")

    elif key == Key("Delete"):
        N10X.Editor.ExecuteCommand("Delete")
        pos = N10X.Editor.GetCursorPos()
        SetCursorPos(pos[0],pos[1])

    else:
        handled = False

        # Note: Only pass through for control and alt when combinations are used, i.e. not when control or alt has been pressed by itself. This fixes issues where non ISO/ANSI keyboards need to use these keys for accessing other characters that ISO/ANSI access by pressing shift, .e.g { on German keyboards.
            
        pass_through = \
            (key.control and key.key != "Control") or \
            (key.alt and key.key != "Alt") or \
            key.key == "Backspace" or \
            key.key == "Up" or \
            key.key == "Down" or \
            key.key == "Left" or \
            key.key == "Right" or \
            key.key == "PageUp" or \
            key.key == "PageDown" or \
            key.key == "F1" or \
            key.key == "F2" or \
            key.key == "F3" or \
            key.key == "F4" or \
            key.key == "F5" or \
            key.key == "F6" or \
            key.key == "F7" or \
            key.key == "F8" or \
            key.key == "F9" or \
            key.key == "F10" or \
            key.key == "F11" or \
            key.key == "F12" or \
            key.key.startswith("Mouse")

    if handled or pass_through:
        ClearCommandStr(False)

    g_HandlingKey = False

    UpdateVisualModeSelection()

    return not pass_through

#------------------------------------------------------------------------
def HandleCommandlineModeKey(key: Key):
    global g_HandlingKey
    global g_Command
    global g_PaneSwap
    global g_Commandline

    handled = True

    is_command = g_Commandline.text[0] == ':'
    is_search  = IsSearching() 
    history_buffer = GetHistoryBuffer() 
    filtered_history_buffer = GetFilteredHistoryBuffer() 
    g_Commandline.historyIndex = Clamp(0, len(filtered_history_buffer)-1, g_Commandline.historyIndex) 

    # Exit 
    if key == Key("Escape") or key == Key("C", control=True):
        g_Commandline.text = ""
        if is_search and g_LastJumpPoint:
            SetCursorPos(g_LastJumpPoint[0], g_LastJumpPoint[1])
        EnterCommandMode()
    
    # Submit command
    elif key == Key("Enter"):
        if is_command:
            # TODO: Strip spaces between ':' and next alphanumeric character from g_Commandline.text
            valid_command = SubmitCommandline(g_Commandline.text)
            if not valid_command:
                g_Commandline.result = "Error: Not an editor command: " + g_Commandline.text[1:]
            g_Commandline.text = ""
        EnterCommandMode()

    # Delete operations

    elif key == Key("Backspace"):
        # When there's a character after the starting char, e.g. ':' and '/' you can't delete it so guard against that here
        # We can backspace/delete if we only have the starting char or the cursor pos is not after the starting char
        if len(g_Commandline.text) == 1 or g_Commandline.cursorPos > 1:
            # Move cursor back one
            prev_cursor_pos = g_Commandline.cursorPos
            g_Commandline.cursorPos = max(0, g_Commandline.cursorPos - 1)
            # Delete character between current and prev cursor pos
            g_Commandline.text = g_Commandline.text[:g_Commandline.cursorPos] + g_Commandline.text[prev_cursor_pos:] 
            # Update history buffer
            history_buffer[-1] = g_Commandline.text[1:]
            g_Commandline.historyIndex = len(history_buffer)-1 
            if len(g_Commandline.text) == 0:
                EnterCommandMode()
            elif is_search:
                UpdateSearchText(g_Commandline.text[1:])

    elif key == Key("Delete"):
            next_cursor_pos = min(len(g_Commandline.text), g_Commandline.cursorPos + 1)
            g_Commandline.text = g_Commandline.text[:g_Commandline.cursorPos] + g_Commandline.text[next_cursor_pos:] 
            # Update history buffer
            history_buffer[-1] = g_Commandline.text[1:]
            g_Commandline.historyIndex = len(history_buffer)-1 
            if is_search:
                UpdateSearchText(g_Commandline.text[1:])

    # Paste
    elif key == Key("V", control=True):
        clipboard_text = GetClipboardValue().strip()
        # Truncate if too big
        max_paste_length = 512 # characters
        clipboard_text = clipboard_text[:max_paste_length-len(clipboard_text)]
        # Insert clipboard at cursor pos
        g_Commandline.text = g_Commandline.text[:g_Commandline.cursorPos] + clipboard_text + g_Commandline.text[g_Commandline.cursorPos:]
        g_Commandline.cursorPos += len(clipboard_text)
        # Update history buffer
        history_buffer[-1] = g_Commandline.text[1:]               
        # Update search text if searching
        if IsSearching() and len(g_Commandline.text) > 1:
            UpdateSearchText(g_Commandline.text[1:])

    # Navigation

    elif key == Key("Left"):
        # max with 1 is intentional here as you can't move before the starting char
        g_Commandline.cursorPos = max(1, g_Commandline.cursorPos - 1)

    elif key == Key("Right"):
        g_Commandline.cursorPos = min(len(g_Commandline.text), g_Commandline.cursorPos + 1)
        
    elif key == Key("Home"):
        g_Commandline.cursorPos = 1

    elif key == Key("End"):
        g_Commandline.cursorPos = len(g_Commandline.text) 

    # History
    elif key == Key("Up"):
        g_Commandline.historyIndex = Clamp(0, len(filtered_history_buffer)-1, g_Commandline.historyIndex - 1) 
        g_Commandline.text = g_Commandline.text[0] + filtered_history_buffer[g_Commandline.historyIndex]
        g_Commandline.cursorPos = len(g_Commandline.text) 

    elif key == Key("Down"):
        g_Commandline.historyIndex = Clamp(0, len(filtered_history_buffer)-1, g_Commandline.historyIndex + 1) 
        g_Commandline.text = g_Commandline.text[0] + filtered_history_buffer[g_Commandline.historyIndex]
        g_Commandline.cursorPos = len(g_Commandline.text) 

    else:
        handled = False

    # On commandline mode exit
    if g_Mode != Mode.COMMANDLINE:
        # clean up empty entry
        if history_buffer[-1] == "":
            history_buffer.pop()
        # if entry is already in the history buffer, remove the old one
        else:
            # Remove last one so we don't remove it
            last = history_buffer.pop()
            try:
                # Remove existing entry if it exists, there should only be one or none
                history_buffer.remove(last)
            except ValueError:
                pass
            # Re-add to the end of the history buffer
            history_buffer.append(last)

    UpdateCursorMode()

    return handled

#------------------------------------------------------------------------
def SubmitCommandline(command):
    global g_Commandline
    
    # Call user bindings
    user_result = VimUser.UserHandleCommandline(command)
    if user_result == UserHandledResult.HANDLED:
        return True
    elif user_result == UserHandledResult.PASS_TO_10X:
        return False

    if command == ":sp":
        x, y = N10X.Editor.GetCursorPos()
        N10X.Editor.ExecuteCommand("DuplicatePanel")
        N10X.Editor.ExecuteCommand("MovePanelDown")
        SetCursorPos(x,y)
        return True
    
    if command == ":vsp":
        x, y = N10X.Editor.GetCursorPos()
        N10X.Editor.ExecuteCommand("DuplicatePanelRight")
        SetCursorPos(x,y)
        return True

    if command == ":w" or command == ":W":
        N10X.Editor.ExecuteCommand("SaveFile")
        g_Commandline.result = "Saved " + N10X.Editor.GetCurrentFilename()
        print(g_Commandline.result)
        return True

    if command == ":wa":
        N10X.Editor.ExecuteCommand("SaveAll")
        g_Commandline.result = "Saved file(s)"
        return True

    if command == ":wq":
        N10X.Editor.ExecuteCommand("SaveFile")
        g_Commandline.result = "Saved " + N10X.Editor.GetCurrentFilename()
        N10X.Editor.ExecuteCommand("CloseFile")
        return True

    if command == ":q" or command == ":Q" or command == ":x" or command == ":X":
        N10X.Editor.ExecuteCommand("CloseFile")
        return True

    if command == ":q!" or command == ":x!":
        N10X.Editor.DiscardUnsavedChanges()
        N10X.Editor.ExecuteCommand("CloseFile")
        return True
    
    split = command.split(":")
    if len(split) == 2 and split[1].isdecimal(): 
        SetCursorPos(y=int(split[1]) - 1)
        return True


#------------------------------------------------------------------------
def HandleCommandlineModeChar(char):
    global g_Mode
    global g_ReverseSearch
    global g_LastJumpPoint
    global g_CommandlineText
    global g_Commandline

    # Insert char at cursor pos
    g_Commandline.text = g_Commandline.text[:g_Commandline.cursorPos] + char + g_Commandline.text[g_Commandline.cursorPos:]
    g_Commandline.cursorPos += 1

    # Update last history buffer entry
    history_buffer = GetHistoryBuffer() 
    history_buffer[-1] = g_Commandline.text[1:]
    g_Commandline.historyIndex = len(history_buffer)-1 

    UpdateCursorMode()
   
    # searching
    if IsSearching() and len(g_Commandline.text) > 1:
        UpdateSearchText(g_Commandline.text[1:])

    return True


#------------------------------------------------------------------------
def HandleInsertModeKey(key: Key):
    global g_InsertBuffer
    global g_PerformingDot

    # Call user bindings
    user_result = VimUser.UserHandleInsertModeKey(key)
    if user_result == UserHandledResult.HANDLED:
        return True
    elif user_result == UserHandledResult.PASS_TO_10X:
        return False

    if key == Key("Escape"):
        EnterCommandMode()
        return False

    if key == Key("C", control=True):
        EnterCommandMode()
        MoveCursorPos(x_delta=1, max_offset=0)
        return True
    
    # disable keys that aren't implemented yet or shouldn't do anything
    if (key == Key("A", control=True)) or \
       (key == Key("X", control=True)) or \
       (key == Key("Y", control=True)) or \
       (key == Key("V", control=True)):
        return True

    if not g_PerformingDot:
        RecordKey(g_InsertBuffer, key)
    return False

def ExitInsertModeTimerCheck():
    global g_ExitInsertTimer;
    global g_ExitInsertCharBuffer;
     
    if time.time() - g_ExitInsertTimer > 1:
        HandleInsertModeChar(g_ExitInsertCharBuffer)
        N10X.Editor.RemoveUpdateFunction(ExitInsertModeTimerCheck)
    
#------------------------------------------------------------------------
def HandleInsertModeChar(char):
    global g_SingleReplace
    global g_MultiReplace
    global g_InsertBuffer
    global g_ExitInsertTimer;
    global g_ExitInsertCharBuffer;
    global g_VimExitInsertModeCharSequence;

    if not g_PerformingDot:
        RecordCharKey(g_InsertBuffer, char)

    # Check if we might exit insert mode based on the VimExitInsertModeCharSequence setting in the settings file
    if g_VimExitInsertModeCharSequence != None:
        if char == g_VimExitInsertModeCharSequence[0] and g_ExitInsertCharBuffer == None and g_ExitInsertTimer == 0:
            g_ExitInsertTimer = time.time()
            g_ExitInsertCharBuffer = char
            N10X.Editor.AddUpdateFunction(ExitInsertModeTimerCheck)
            return True
        elif g_ExitInsertCharBuffer != None and time.time() - g_ExitInsertTimer <= 1:
            g_ExitInsertCharBuffer += char
            if g_ExitInsertCharBuffer == g_VimExitInsertModeCharSequence:
                g_ExitInsertCharBuffer = None
                g_ExitInsertTimer = 0
                EnterCommandMode()
                N10X.Editor.RemoveUpdateFunction(ExitInsertModeTimerCheck)
            elif len(g_ExitInsertCharBuffer) >= len(g_VimExitInsertModeCharSequence):
                N10X.Editor.InsertText(g_ExitInsertCharBuffer)
                g_ExitInsertCharBuffer = None
                g_ExitInsertTimer = 0
                N10X.Editor.RemoveUpdateFunction(ExitInsertModeTimerCheck)
            return True
        elif time.time() - g_ExitInsertTimer > 1 and g_ExitInsertCharBuffer != None:
            N10X.Editor.InsertText(g_ExitInsertCharBuffer)
            g_ExitInsertTimer = 0
            g_ExitInsertCharBuffer = None
            return True
        elif char != g_VimExitInsertModeCharSequence[0]:
            g_ExitInsertTimer = 0
            g_ExitInsertCharBuffer = None

    if g_SingleReplace or g_MultiReplace:
        x, y = N10X.Editor.GetCursorPos()
        SetSelection((x, y), (x, y))
        N10X.Editor.ExecuteCommand("Cut")

    if g_SingleReplace:
        N10X.Editor.InsertText(char)
        EnterCommandMode() #will pop undo
        return True

    return False

#------------------------------------------------------------------------
def HandleVisualModeChar(char):
    global g_Mode
    global g_Command

    g_Command += char

    m = re.match(g_RepeatMatch + "(.*)", g_Command)
    if not m:
        return

    repeat_count = int(m.group(1)) if m.group(1) else 1
    c = m.group(2)
    if not c:
        return

    should_save = False

    if c == "v":
        if g_Mode == Mode.VISUAL or g_Mode == Mode.VISUAL_BLOCK:
            EnterCommandMode()
        else:
            g_Mode = Mode.VISUAL

    elif c == "V":
        if g_Mode == Mode.VISUAL_LINE or g_Mode == Mode.VISUAL_BLOCK:
            EnterCommandMode()
        else:
            g_Mode = Mode.VISUAL_LINE

    elif c == "y" or c == "Y":
        start, _ = SubmitVisualModeSelection()
        N10X.Editor.ExecuteCommand("Copy")
        N10X.Editor.ClearSelection()
        EnterCommandMode()
        SetCursorPos(start[0], start[1])

    elif c == "d" or c == "x":
        start, _ = SubmitVisualModeSelection()
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        EnterCommandMode()
        should_save = True

    elif c == "p":
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            clipboard_value = GetClipboardValue()
            if clipboard_value and clipboard_value[-1:] == "\n":
                SendKey("Enter")
                start = N10X.Editor.GetCursorPos()
                N10X.Editor.InsertText(clipboard_value)
                x, y = GetNextNonWhitespaceCharPos(start[0], start[1], False)
                SetCursorPos(x, y)
            else:
                N10X.Editor.ExecuteCommand("Paste")
                MoveCursorPos(x_delta=-1, max_offset=0)
        N10X.Editor.PopUndoGroup()
        EnterCommandMode()
        should_save = True

    elif c == "c":
        start, _ = SubmitVisualModeSelection()
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        EnterInsertMode()
        should_save = True
    
    elif c == "_" or c == "^":
        MoveToFirstNonWhitespace()


    elif c == "0":
        MoveToStartOfLine()

    elif c == "$":
        MoveToEndOfLine()

    elif c == "G":
        MoveToEndOfFile()

    elif c == "{":
        MoveToPreviousParagraphBegin()

    elif c == "}":
        MoveToNextParagraphEnd()

    elif c == "g":
        return

    elif c == "gg":
        MoveToStartOfFile()

    elif c == "h":
        for _ in range(repeat_count):
            MoveCursorPos(x_delta=-1)

    elif c == "l":
        for _ in range(repeat_count):
            MoveCursorPos(x_delta=1)

    elif c == "k":
        for _ in range(repeat_count):
            MoveCursorPos(y_delta=-1, override_horizontal_target=False)

    elif c == "j":
        for _ in range(repeat_count):
            MoveCursorPos(y_delta=1, override_horizontal_target=False)

    elif c == "w":
        for _ in range(repeat_count):
            MoveToNextWordStart()

    elif c == "W":
        for _ in range(repeat_count):
            MoveToNextTokenStart()

    elif c == "e":
        for _ in range(repeat_count):
            MoveToWordEnd()

    elif c == "E":
        for _ in range(repeat_count):
            MoveToTokenEnd()

    elif c == "b":
        for _ in range(repeat_count):
            MoveToWordStart()

    elif c == "B":
        for _ in range(repeat_count):
            MoveToTokenStart()

    elif (m := re.match("([fFtT;,])(.?)", c)):
        for _ in range(repeat_count):
            action = m.group(1)
            search = m.group(2)
            if not MoveToLineText(action, search):
                return

    elif c == "%":
        N10X.Editor.ExecuteCommand("MoveToMatchingBracket")

    elif c == "gJ":
        N10X.Editor.PushUndoGroup()
        start, end = SubmitVisualModeSelection()
        SetCursorPos(start[0], start[1])
        line_count = max(1, end[1] - start[1] - 1)
        for i in range(line_count):
            MergeLines()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == "J":
        N10X.Editor.PushUndoGroup()
        start, end = SubmitVisualModeSelection()
        SetCursorPos(start[0], start[1])
        line_count = max(1, end[1] - start[1] - 1)
        for i in range(line_count):
            MergeLinesTrimIndentation()
        N10X.Editor.PopUndoGroup()
        should_save = True

    elif c == ">":
        old_Mode = g_Mode
        start, end = SubmitVisualModeSelection()
        N10X.Editor.PushUndoGroup()
        for _ in range(repeat_count):
            N10X.Editor.ExecuteCommand("IndentLine")
        Unhilight()
        N10X.Editor.PopUndoGroup()
        g_Mode = old_Mode
        if g_Mode == Mode.VISUAL_LINE:
          y = end[1]-1
          x = GetLineLength(y)
          SetVisualModeSelection(start, (x,y))
        else:
          SetVisualModeSelection(start, end)
        should_save = True

    elif c == "<":
        old_Mode = g_Mode
        start, end = SubmitVisualModeSelection()
        N10X.Editor.PushUndoGroup()
        for _ in range(repeat_count):
            N10X.Editor.ExecuteCommand("UnindentLine")
        Unhilight()
        N10X.Editor.PopUndoGroup()
        g_Mode = old_Mode
        if g_Mode == Mode.VISUAL_LINE:
          y = end[1]-1
          x = GetLineLength(y)
          SetVisualModeSelection(start, (x,y))
        else:
          SetVisualModeSelection(start, end)
        should_save = True

    elif c == "i" or c == "a":
        # Stub for text-object motions.
        return
    
    elif c == "I" or c == "A":
        EnterInsertMode()

    elif c == "ip":
        start, end = GetInsideParagraphSelection()
        AddVisualModeSelection(start, end)

    elif c == "ap":
        start, end = GetAroundParagraphSelection()
        AddVisualModeSelection(start, end)

    # Following commands are visual char mode only, and will switch your mode.
    elif c == "iw":
        g_Mode = Mode.VISUAL
        start, end = GetInsideWordSelection(N10X.Editor.GetCursorPos())
        AddVisualModeSelection(start, end)

    elif c == "iW":
        g_Mode = Mode.VISUAL
        start, end = GetInsideWordSelectionWithPunctuation(N10X.Editor.GetCursorPos())
        AddVisualModeSelection(start, end)

    elif c == "aw":
        g_Mode = Mode.VISUAL
        start, end = GetAroundWordSelection(N10X.Editor.GetCursorPos())
        AddVisualModeSelection(start, end)

    elif c == "aW":
        g_Mode = Mode.VISUAL
        start, end = GetAroundWordSelectionWithPunctuation(N10X.Editor.GetCursorPos())
        AddVisualModeSelection(start, end)

    elif (m := re.match("i" + g_BlockMatch, c)):
        g_Mode = Mode.VISUAL
        action = m.group(1)
        if sel := GetInsideBlockSelectionOrPos(m.group(1), N10X.Editor.GetCursorPos()):
            start, end = sel
            SetVisualModeSelection(start, end)
    
    elif (m := re.match("a" + g_BlockMatch, c)):
        g_Mode = Mode.VISUAL
        action = m.group(1)
        if sel := GetBlockSelection(m.group(1), N10X.Editor.GetCursorPos()):
            start, end = sel
            SetVisualModeSelection(start, end)
    
    elif (m := re.match("i([`'\"])", c)):
        g_Mode = Mode.VISUAL
        action = m.group(1)
        if sel := GetInsideQuoteSelection(m.group(1), N10X.Editor.GetCursorPos()):
            start, end = sel
            SetVisualModeSelection(start, end)
    
    elif (m := re.match("a([`'\"])", c)):
        g_Mode = Mode.VISUAL
        action = m.group(1)
        if sel := GetQuoteSelection(m.group(1), N10X.Editor.GetCursorPos()):
            start, end = sel
            SetVisualModeSelection(start, end)

    elif c == "~":
        N10X.Editor.PushUndoGroup()
        start, end = N10X.Editor.GetCursorSelection(cursor_index=1)
        current_line_y = start[1]
        while current_line_y <= end[1]:
            line = GetLine(current_line_y)
            length = GetLineLength(current_line_y)
            if length > 0:
                begin_x = start[0] if current_line_y == start[1] else 0
                end_x = end[0] if current_line_y == end[1] else length - 1
                line = line[:begin_x] + line[begin_x:end_x].swapcase() + line[end_x:]
                N10X.Editor.SetLine(current_line_y, line)
            current_line_y += 1
        N10X.Editor.PopUndoGroup()
        SetCursorPos(start[0], start[1])
        EnterCommandMode()
        should_save = True

    elif c == "z":
        return

    elif c == "zt":
        # Apply offset so we don't set the current line as the first visible line but the one just after.
        # This is so we can smooth scroll up using k after zt because 10x prevents the cursor being
        # on the first visible line.
        offset = 1
        N10X.Editor.SetScrollLine(max(0, N10X.Editor.GetCursorPos()[1] - offset))

    elif c == "zz":
        N10X.Editor.CenterViewAtLinePos(N10X.Editor.GetCursorPos()[1])

    elif c == "zb":
        # Apply offset so we don't set the current line as last visible line but the one just before.
        # This is so we can smooth scroll down using j after zb because 10x prevents the cursor being
        # on the last visible line.
        offset = 1
        # Subtract 1 because ScrollLine is 0 indexed
        bottom = N10X.Editor.GetScrollLine() + N10X.Editor.GetVisibleLineCount() - 1 - offset
        scroll_delta = bottom - N10X.Editor.GetCursorPos()[1]
        N10X.Editor.SetScrollLine(max(0, N10X.Editor.GetScrollLine() - scroll_delta))

    elif c == "H":
        scroll_line = N10X.Editor.GetScrollLine()
        SetCursorPos(y=scroll_line+1)

    elif c == "L":
        scroll_line = N10X.Editor.GetScrollLine()
        visible_line_count = N10X.Editor.GetVisibleLineCount()
        SetCursorPos(y=scroll_line + visible_line_count-2)

    elif c == "M":
        scroll_line = N10X.Editor.GetScrollLine()
        visible_line_count = N10X.Editor.GetVisibleLineCount()
        SetCursorPos(y=scroll_line + int(visible_line_count / 2))
    else:
        print("[vim] Unknown command!")
    
    ClearCommandStr(should_save)
    UpdateVisualModeSelection()

#------------------------------------------------------------------------
def HandleSuspendedModeKey(key: Key):

    if key == Key("F12", control=True, shift=True):
        print("[vim] vim bindings enabled")
        N10X.Editor.OverrideSetting("ReverseFindSelection","true")
        EnterCommandMode()
        return True

    return False

#------------------------------------------------------------------------
def GetCurrentScopeName():
    return "Scope: " + (N10X.Editor.GetCurrentScopeName() or "(none)")

#------------------------------------------------------------------------
def GetCommandModeStatusBarText():
    text = ""

    if g_DisplayCurrentScopeName:
        text += GetCurrentScopeName()

    return text

#------------------------------------------------------------------------
def UpdateCursorMode():
    if g_Command or g_SingleReplace or g_MultiReplace:
        N10X.Editor.SetCursorVisible(0, True)
        N10X.Editor.SetCursorMode("HalfBlock")
        N10X.Editor.SetStatusBarText(g_Command)
    elif g_Mode == Mode.INSERT:
        N10X.Editor.SetCursorVisible(0, True)
        N10X.Editor.SetCursorMode("Line")
        N10X.Editor.SetStatusBarText("-- INSERT --")
    elif g_Mode == Mode.VISUAL:
        N10X.Editor.SetCursorVisible(0, True)
        N10X.Editor.SetCursorMode("Block")
        N10X.Editor.SetStatusBarText("-- VISUAL --")
    elif g_Mode == Mode.VISUAL_LINE:
        N10X.Editor.SetCursorVisible(0, True)
        N10X.Editor.SetCursorMode("Block")
        N10X.Editor.SetStatusBarText("-- VISUAL LINE --")
    elif g_Mode == Mode.VISUAL_BLOCK:
        N10X.Editor.SetCursorVisible(0, True)
        N10X.Editor.SetCursorMode("Block")
        N10X.Editor.SetStatusBarText("-- VISUAL BLOCK--")
    elif g_Mode == Mode.SUSPENDED:
        N10X.Editor.SetCursorVisible(0, True)
        N10X.Editor.SetCursorMode("Line")
        N10X.Editor.SetStatusBarText("-- VIM DISABLED --")
    elif g_Mode == Mode.COMMANDLINE:
        # Don't hide cursor when searching 
        if IsSearching():
            N10X.Editor.SetCursorVisible(0, True)
        else:
            N10X.Editor.SetCursorVisible(0, False)
        N10X.Editor.SetCursorMode("Block")
        # Insert cursor char into commandline text
        text = g_Commandline.text[:g_Commandline.cursorPos] + g_Commandline.cursorChar + g_Commandline.text[g_Commandline.cursorPos:]
        N10X.Editor.SetStatusBarText(text)
    elif g_Commandline.result:
        N10X.Editor.SetCursorVisible(0, True)
        N10X.Editor.SetStatusBarText(g_Commandline.result)
        N10X.Editor.SetCursorMode("Block")
    else:
        N10X.Editor.SetCursorVisible(0, True)
        N10X.Editor.SetCursorMode("Block")
        N10X.Editor.SetStatusBarText(GetCommandModeStatusBarText())

#------------------------------------------------------------------------
# Recording

#------------------------------------------------------------------------
def RecordKey(buffer, key: Key):
    r = RecordedKey()
    r.type = RecordedKey.KEY
    r.key = key
    buffer.append(r)

#------------------------------------------------------------------------
def RecordCharKey(buffer, char):
    r = RecordedKey()
    r.type = RecordedKey.CHAR_KEY
    r.char = char
    buffer.append(r)

#------------------------------------------------------------------------
def TrimBuffer(buffer):
    buffer.pop()

#------------------------------------------------------------------------
def PlaybackBuffer(buffer):
    global g_RecordingName
    for r in buffer:
        if r.type == RecordedKey.KEY:
            N10X.Editor.SendKey(r.key.key,r.key.shift,r.key.control,r.key.alt)
        elif r.type == RecordedKey.CHAR_KEY:
            N10X.Editor.SendCharKey(r.char)

#------------------------------------------------------------------------
# 10X Callbacks

#------------------------------------------------------------------------
# Called when a key is pressed.
# Return true to supress the key
def OnInterceptKey(key, shift, control, alt):
    global g_HandleKeyIntercepts
    if not g_HandleKeyIntercepts:
        return False

    key = Key(key, shift, control, alt) 

    supress = False
    if N10X.Editor.TextEditorHasFocus():
        global g_RecordingName
        global g_NamedBuffers
    
        if g_RecordingName != "":
            RecordKey(g_NamedBuffers[g_RecordingName],key)

        global g_Mode
        match g_Mode:
            case Mode.INSERT:
                supress = HandleInsertModeKey(key)
            case Mode.COMMAND:
                supress = HandleCommandModeKey(key)
            case Mode.COMMANDLINE:
                supress = HandleCommandlineModeKey(key)
            case Mode.VISUAL:
                supress = HandleCommandModeKey(key)
            case Mode.VISUAL_LINE:
                supress = HandleCommandModeKey(key)
            case Mode.VISUAL_BLOCK:
                supress = HandleCommandModeKey(key)
            case Mode.SUSPENDED:
                supress = HandleSuspendedModeKey(key)
        UpdateCursorMode()
        
    return supress

#------------------------------------------------------------------------
# Called when a char is to be inserted into the text editor.
# Return true to surpress the char key.
# If we are in command mode supress all char keys
def OnInterceptCharKey(c):
    global g_HandleCharKeyIntercepts
    if not g_HandleCharKeyIntercepts:
        return False

    supress = False
    if N10X.Editor.TextEditorHasFocus():
        global g_RecordingName
        global g_NamedBuffers
    
        if g_RecordingName != "":
            RecordCharKey(g_NamedBuffers[g_RecordingName],c)

        supress = True
        global g_Mode
        match g_Mode:
            case Mode.INSERT:
                supress = HandleInsertModeChar(c)
            case Mode.COMMAND:
                HandleCommandModeChar(c)
            case Mode.COMMANDLINE:
                HandleCommandlineModeChar(c)
            case Mode.VISUAL:
                HandleVisualModeChar(c)
            case Mode.VISUAL_LINE:
                HandleVisualModeChar(c)
            case Mode.VISUAL_BLOCK:
                HandleVisualModeChar(c)
            case Mode.SUSPENDED:
                supress = False

        UpdateCursorMode()
    return supress

#------------------------------------------------------------------------
def HandleCommandPanelCommand(command):
    return SubmitCommandline(command)

#------------------------------------------------------------------------
def OnFileLosingFocus():
    global g_ExitInsertTimer
    global g_ExitInsertCharBuffer;
    
    if g_Mode != Mode.SUSPENDED:
        EnterCommandMode()
    if g_ExitInsertCharBuffer != None:
        g_ExitInsertCharBuffer = None
        g_ExitInsertTimer = 0
        N10X.Editor.RemoveUpdateFunction(ExitInsertModeTimerCheck)

#------------------------------------------------------------------------
def EnableVim():
    global g_VimEnabled
    global g_Use10xCommandPanel
    global g_Use10xFindPanel
    global g_SneakEnabled
    global g_VimExitInsertModeCharSequence;
    global g_SmartCaseEnabled
    global g_UseFilteredCommandlineHistory
    global g_DisplayCurrentScopeName

    if N10X.Editor.GetSetting("VimExitInsertModeCharSequence"):
        g_VimExitInsertModeCharSequence = N10X.Editor.GetSetting("VimExitInsertModeCharSequence")
        if len(g_VimExitInsertModeCharSequence) == 1 or len(g_VimExitInsertModeCharSequence) > 3:
            g_VimExitInsertModeCharSequence = None
            print("Couldn't set VimExitInsertModeCharSequence, must be 2 or 3 characters in length only") 

    # Settings
    enable_vim                      = GetSettingBool("Vim",                                 default_value="false")
    g_SneakEnabled                  = GetSettingBool("VimSneakEnabled",                     default_value="false")
    g_SmartCaseEnabled              = GetSettingBool("VimSmartCaseEnabled",                 default_value="true") 
    g_Use10xCommandPanel            = GetSettingBool("VimUse10xCommandPanel",               default_value="false")
    g_Use10xFindPanel               = GetSettingBool("VimUse10xFindPanel",                  default_value="false")
    g_UseFilteredCommandlineHistory = GetSettingBool("VimCommandlineFilteredHistory",       default_value="true")
    g_DisplayCurrentScopeName       = GetSettingBool("VimDisplayCurrentScopeName",          default_value="true")

    if g_VimEnabled != enable_vim:
        g_VimEnabled = enable_vim

        if enable_vim:
            print("[vim] Enabling Vim")
            N10X.Editor.AddOnInterceptCharKeyFunction(OnInterceptCharKey)
            N10X.Editor.AddOnInterceptKeyFunction(OnInterceptKey)
            N10X.Editor.AddOnFileLosingFocusFunction(OnFileLosingFocus)
            N10X.Editor.OverrideSetting("ReverseFindSelection","true")
            EnterCommandMode(False)

        else:
            print("[vim] Disabling Vim")
            EnterInsertMode()
            N10X.Editor.ResetCursorMode()
            N10X.Editor.RemoveOnInterceptCharKeyFunction(OnInterceptCharKey)
            N10X.Editor.RemoveOnInterceptKeyFunction(OnInterceptKey)
            N10X.Editor.RemoveOnFileLosingFocusFunction(OnFileLosingFocus)
            N10X.Editor.RemoveSettingOverride("ReverseFindSelection")


#------------------------------------------------------------------------
# enable/disable Vim when it's changed in the settings file
def OnSettingsChanged():
    EnableVim()
    
#------------------------------------------------------------------------
def InitialiseVim():
    EnableVim()

#------------------------------------------------------------------------


# Prevent against being registered multiple times as VimUser.py imports Vim.py
if __name__ == "__main__":
    N10X.Editor.AddOnSettingsChangedFunction(OnSettingsChanged)
    N10X.Editor.AddCommandPanelHandlerFunction(HandleCommandPanelCommand)
    N10X.Editor.CallOnMainThread(InitialiseVim)
