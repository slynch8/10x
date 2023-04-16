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

#------------------------------------------------------------------------
class Mode:
    INSERT      = 0
    COMMAND     = 1
    VISUAL      = 2
    VISUAL_LINE = 3
    PANE        = 4

#------------------------------------------------------------------------
g_Mode = Mode.INSERT

# position of the cursor when visual mode was entered
g_VisualModeStartPos = None

# guard to stop infinite recursion in key handling
g_HandingKey = False

# the current command for command mode
g_Command = ""

# flag to enable/disable whether we handle key intercepts
g_HandleKeyIntercepts = True

# the last line search performed
g_LastSearch = None
g_ReverseSearch = False

# regex for getting the repeat count for a command
g_RepeatMatch = "([1-9][0-9]*)?"

# regex for getting the block tag
g_BlockMatch = "([{}[\]<>\(\)])"

g_StartedRecordingMacro = False

# 'r' and 'R' insert modes (respectively)
g_SingleReplace = False
g_MultiReplace = False

# position of the cursor before a significant "jump", allowing '' to target back
g_LastJumpPoint = None
# positions of explicitly set jump points (map of string to position)
g_JumpMap = {}

g_SneakEnabled = False

#------------------------------------------------------------------------
def InVisualMode():
    global g_Mode
    return g_Mode == Mode.VISUAL or g_Mode == Mode.VISUAL_LINE

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
def SetCursorPos(x=None, y=None, max_offset=1):
    if x is None:
      x, _ = N10X.Editor.GetCursorPos()
    if y is None:
      _, y = N10X.Editor.GetCursorPos()

    y = Clamp(0, GetMaxY(), y)
    x = Clamp(0, GetLineLength(y) - max_offset, x)

    N10X.Editor.SetCursorPos((x, y))

#------------------------------------------------------------------------
def MoveCursorPos(x_delta=0, y_delta=0, max_offset=1):
    x, y = N10X.Editor.GetCursorPos()
    x += x_delta
    y += y_delta
    
    SetCursorPos(x, y, max_offset)

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

    while y >= 0 :
        if x >= 0:
            line = line[:x + 2]
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
            line = line[x - 1:]
            index = line.find(c)
            if index >= 0:
                    return x + index - 1, y
        x = 0
        y += 1
    return None, None

#------------------------------------------------------------------------
def MoveToLineText(action, search):
    global g_LastSearch
    if action == ';' and g_LastSearch:
        MoveToLineText(g_LastSearch[0], g_LastSearch[1])
        return True
    
    if not search:
        return False

    if len(search) == 1:
        if action == 'f':
            x = FindNextOccurrenceForward(search)
            if x:
                    SetCursorPos(x=x)
        elif action == 'F':
            x = FindNextOccurrenceBackward(search)
            if x:
                SetCursorPos(x=x)
        elif action == 't':
            x = FindNextOccurrenceForward(search)
            if x:
                SetCursorPos(x=x-1)
        elif action == 'T':
            x = FindNextOccurrenceBackward(search)
            if x:
                SetCursorPos(x=x+1)
        else:
           return False
    
        g_LastSearch = action + search
        return True
    elif len(search) == 2 and g_SneakEnabled:
        if action == 's':
            x,y = FindNextOccurrenceForward2(search)
            if x:
                SetCursorPos(x=x, y=y)
        elif action == 'S':
            x,y = FindNextOccurrenceBackward2(search)
            if x:
                SetCursorPos(x=x, y=y)
            else:
                return False
 
        g_LastSearch = action + search
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
            if err.winerror == 5:  # access denied
                time.sleep( 0.01 )
            elif err.winerror == 1418:  # doesn't have board open
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
            if err.winerror == 5:  # access denied
                time.sleep( 0.01 )
            elif err.winerror == 1418:  # doesn't have board open
                pass
            else:
                pass

    print("[vim] Failed add newline to clipboard text!")

#------------------------------------------------------------------------
def SendKey(key):
    global g_HandleKeyIntercepts
    g_HandleKeyIntercepts = False
    N10X.Editor.SendKey(key)
    g_HandleKeyIntercepts = True

#------------------------------------------------------------------------
def EnterInsertMode():
    global g_Mode
    if g_Mode != Mode.INSERT:
        g_Mode = Mode.INSERT
        N10X.Editor.ResetCursorBlink()
        UpdateCursorMode()

#------------------------------------------------------------------------
def EnterCommandMode():
    global g_Mode
    global g_Command
    global g_SingleReplace
    global g_MultiReplace

    if g_Mode != Mode.COMMAND:
        N10X.Editor.ClearSelection()
        g_SingleReplace = False
        g_MultiReplace = False
        was_visual = InVisualMode()
        g_Mode = Mode.COMMAND
        g_Command = ""
        N10X.Editor.ResetCursorBlink()

        if not was_visual:
            MoveCursorPos(x_delta=-1)

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
def EnterPaneMode():
    global g_Mode
    if g_Mode != Mode.PANE:
        g_Mode = Mode.PANE

    UpdateVisualModeSelection()

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

    if curr_start[1] < start[1]:
        min_start = curr_start
    elif curr_start[1] > start[1]:
        min_start = start
    else:
        min_start = (min(curr_start[0], start[0]), start[1])

    if curr_end[1] > end[1]:
        max_end = curr_end
    elif curr_end[1] < end[1]:
        max_end = end
    else:
        max_end = (max(curr_end[0], end[0]), end[1])

    SetVisualModeSelection(min_start, max_end)

#------------------------------------------------------------------------
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

#------------------------------------------------------------------------
def SubmitVisualModeSelection():
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
    return y >= GetMaxY() and x >= GetLineLength(GetMaxY())

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

    line_y = y;

    character_class = GetCharacterClassAtPos(x, y)
    while not AtEndOfFile(x, y) and y == line_y and GetCharacterClassAtPos(x, y) == character_class:
        x, y = GetNextCharPos(x, y, wrap)

    x, y = GetNextNonWhitespaceCharPos(x, y, wrap)

    SetCursorPos(x, y)

    return x < GetLineLength(y)

#------------------------------------------------------------------------
def MoveToNextTokenStart(wrap=True):
    x, y = N10X.Editor.GetCursorPos()

    line_y = y;

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
def MoveToPreviousEmptyLine():
    x, y = N10X.Editor.GetCursorPos()
    while y > 0 :
      y = y - 1
      text = N10X.Editor.GetLine(y)
      if text.isspace():
        N10X.Editor.SetCursorPos((0, y))
        break

#------------------------------------------------------------------------
def MoveToNextEmptyLine():
    line_count = N10X.Editor.GetLineCount()
    x, y = N10X.Editor.GetCursorPos()
    while y < line_count:
      text = N10X.Editor.GetLine(y + 1)
      if not text or text.isspace():
        N10X.Editor.SetCursorPos((0, y + 1))
        break
      y = y + 1
      
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
def GetBlockSelection(c, start, count=1):
    c = NormalizeBlockChar(c)
    x = FindNextOccurrenceForward(c)
    if x:
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
def GetAroundWordSelection(start, wrap=True):
    x, y = start

    start_x = x
    end_x = x

    line = GetLine(y)

    character_class = GetCharacterClass(line[end_x])
    alt_class = CharacterClass.WHITESPACE if character_class == CharacterClass.WORD else CharacterClass.WORD            

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
def GetQuoteSelection(c, start, whitespace=True):
    x, y = start

    line = GetLine(y)
    if matches := re.finditer('"(?:\\\\.|[^"\\\\])*"', line):
        for m in matches:
            if m.end() >= x:
                return (m.start(), y), (m.end() - 1, y)
    
    return None

#------------------------------------------------------------------------
def GetInsideQuoteSelection(c, start, whitespace=False):
    if sel := GetQuoteSelection(c, start, whitespace):
        start, end = sel
        return (start[0] + 1, start[1]), (end[0] - 1, end[1]),
    return None

#------------------------------------------------------------------------
def SelectQuote(c, whitespace=True):
    start = N10X.Editor.GetCursorPos()
    if sel := GetQuoteSelection(c, start):
        start, end = sel
        SetSelection(start, end)
        return start
    return False
    
#------------------------------------------------------------------------
def SelectOrMoveInsideQuote(c, whitespace=False):
    start = N10X.Editor.GetCursorPos()
    if sel := GetInsideQuoteSelection(c, start, whitespace):
        start, end = sel
        if start == end:
            SetCursorPos(start[0], start[1])
            return False
        SetSelection(start, end)
        return start
    return False

#------------------------------------------------------------------------
# Key Intercepting

#------------------------------------------------------------------------
def HandleCommandModeChar(char):
    global g_Mode
    global g_Command
    global g_ReverseSearch
    global g_StartedRecordingMacro
    global g_LastJumpPoint
    global g_JumpMap
    global g_SingleReplace
    global g_MultiReplace
    global g_SneakEnabled

    g_Command += char

    m = re.match(g_RepeatMatch + "(.*)", g_Command)
    if not m:
        return

    repeat_count = int(m.group(1)) if m.group(1) else 1
    has_repeat_count = m.group(1) != None
    c = m.group(2)
    if not c:
        return

    # moving

    if c == "h":
        for i in range(repeat_count):
            MoveCursorPos(x_delta=-1)

    elif c == "j":
        for i in range(repeat_count):
            MoveCursorPos(y_delta=1)

    elif c == "k":
        for i in range(repeat_count):
            MoveCursorPos(y_delta=-1)

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

    elif c == "0":
        MoveToStartOfLine()

    elif c == "$":
        MoveToEndOfLine()

    elif c == "{":
       MoveToPreviousEmptyLine()

    elif c == "}":
        MoveToNextEmptyLine()

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
        N10X.Editor.ExecuteCommand("NextPanelTab")

    elif c == "gT":
        N10X.Editor.ExecuteCommand("PrevPanelTab")

    elif c == "G":
        g_LastJumpPoint = N10X.Editor.GetCursorPos()
        x, _ = N10X.Editor.GetCursorPos()
        if has_repeat_count:
            SetCursorPos(x, max(0, repeat_count - 1))
        else:
            MoveToEndOfFile();

    elif c == "g":
        return

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
    
    # Deleting

    elif c == "dd":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(y, y + repeat_count - 1)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(x, y)
        N10X.Editor.PopUndoGroup()

    elif c == "dw":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        for i in range(repeat_count):
            MoveToNextWordStart()
        end = N10X.Editor.GetCursorPos()
        if start != end:
            end = (max(0, end[0] - 1), end[1])
            SetSelection(start, end)
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()

    elif c == "diw":
        N10X.Editor.PushUndoGroup() 
        start, end = GetInsideWordSelection(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        N10X.Editor.PopUndoGroup()

    elif c == "daw":
        N10X.Editor.PushUndoGroup()
        start, end = GetAroundWordSelection(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        N10X.Editor.PopUndoGroup()

    elif (m := re.match("d" + g_RepeatMatch + "i" + g_BlockMatch, c)):
        N10X.Editor.PushUndoGroup()
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        if sel := SelectOrMoveInsideBlock(action, count):
            start, _ = sel
            N10X.Editor.ExecuteCommand("Cut")
            SetCursorPos(start[0], start[1])
        N10X.Editor.PopUndoGroup()

    elif (m := re.match("d" + g_RepeatMatch + "a" + g_BlockMatch, c)):
        N10X.Editor.PushUndoGroup()
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        if pos := SelectAroundBlock(action, count):
            N10X.Editor.ExecuteCommand("Cut")
            SetCursorPos(pos[0], pos[1])
        N10X.Editor.PopUndoGroup()
    
    elif (m := re.match("di([`'\"])", c)):
        action = m.group(1)
        if pos := SelectOrMoveInsideQuote(m.group(1)):
            N10X.Editor.PushUndoGroup()
            N10X.Editor.ExecuteCommand("Cut")
            SetCursorPos(pos[0], pos[1])
            N10X.Editor.PopUndoGroup()
    
    elif (m := re.match("da([`'\"])", c)):
        action = m.group(1)
        if pos := SelectOrMoveInsideQuote(m.group(1)):
            N10X.Editor.PushUndoGroup()
            N10X.Editor.ExecuteCommand("Copy")
            SetCursorPos(pos[0], pos[1])
            N10X.Editor.PopUndoGroup()

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

    elif (m := re.match("d" + g_RepeatMatch + "j", c)):
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            x, y = N10X.Editor.GetCursorPos()
            count = int(m.group(1)) if m.group(1) else 1
            end_y = min(y + count, GetMaxY())
            SetLineSelection(y, end_y)
            N10X.Editor.ExecuteCommand("Cut")
            SetCursorPos(0, y - 1)
        N10X.Editor.PopUndoGroup()

    elif (m := re.match("d" + g_RepeatMatch + "k", c)):
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            x, y = N10X.Editor.GetCursorPos()
            count = int(m.group(1)) if m.group(1) else 1
            end_y = min(y - count, GetMaxY())
            SetLineSelection(y, end_y)
            N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()

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

    elif (m := re.match("d" + g_RepeatMatch + "([fFtT;])(.?)", c)):
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

    elif c == "dgg":
        x, y = N10X.Editor.GetCursorPos()
        SetLineSelection(y, 0)
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(x, 0)

    elif c == "dG":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        if y:
            sel_start = (GetLineLength(y - 1), y - 1)
        else:
            sel_start = GetLineLength(0)
        sel_end = (GetLineLength(GetMaxY()), GetMaxY())
        SetSelection(sel_start, sel_end)
        N10X.Editor.ExecuteCommand("Cut")
        end_x, end_y = GetNextNonWhitespaceCharPos(0, GetMaxY(), False)
        SetCursorPos(end_x, end_y)
        N10X.Editor.PopUndoGroup()

    elif c == "d0":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        end_x = max(0, x - 1)
        SetSelection((0, y), (end_x, y))
        N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()

    elif c == "D" or c == "d$":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetSelection((x, y), (GetLineLength(), y))
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(x - 1, y)
        N10X.Editor.PopUndoGroup()

    elif (m := re.match("d" + g_RepeatMatch, c)) or c == "dg":
        return

    elif c == "x":
        x, y = N10X.Editor.GetCursorPos()
        N10X.Editor.PushUndoGroup()
        SetSelection((x, y), (x + repeat_count-1, y))
        N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()

    elif not g_SneakEnabled and c == "s":
        x, y = N10X.Editor.GetCursorPos()
        N10X.Editor.PushUndoGroup()
        SetSelection((x, y), (x + repeat_count-1, y))
        N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()
        # NOTE- incomplete. if you "s" and type some stuff, a single "undo" should remove the typed stuff AND the deleted character

    # Searching

    elif c == "*":
        for i in range(repeat_count):
            SendKey("Right")
            N10X.Editor.ExecuteCommand("FindInFileNextCurrentWord")
            SendKey("Left")

    elif c == "#":
        for i in range(repeat_count):
            SendKey("Right")
            N10X.Editor.ExecuteCommand("FindInFilePrevCurrentWord")
            SendKey("Left")

    elif c == "/":
        g_LastJumpPoint = N10X.Editor.GetCursorPos()
        g_ReverseSearch = False
        N10X.Editor.ExecuteCommand("FindInFile")

    elif c == "?":
        print("[vim] "+c+" (reverse search) unimplemented- regular searching")
        g_ReverseSearch = True
        g_LastJumpPoint = N10X.Editor.GetCursorPos()
        N10X.Editor.ExecuteCommand("FindInFile")

    elif g_SneakEnabled and (m := re.match("([fFtTsS;])(.{0,2})", c)):
        for i in range(repeat_count):
            action = m.group(1)
            search = m.group(2)
            if not MoveToLineText(action, search):
                return

    elif not g_SneakEnabled and (m := re.match("([fFtT;])(.?)", c)):
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
        EnterInsertMode()

    elif c == "r":
        EnterInsertMode()
        g_SingleReplace = True

    elif c == "R":
        EnterInsertMode()
        g_MultiReplace = True
        
    elif c == "I":
        MoveToStartOfLine();
        MoveToNextNonWhitespaceChar(wrap=False)
        EnterInsertMode();

    elif c == "a":
        EnterInsertMode();
        MoveCursorPos(x_delta=1, max_offset=0)

    elif c == "A":
        EnterInsertMode();
        SetCursorPos(x=GetLineLength(), max_offset=0)

    elif c == "o":
        N10X.Editor.PushUndoGroup()
        SetCursorPos(x=GetLineLength(), max_offset=0)
        SendKey("Enter")
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()

    elif c == "O":
        N10X.Editor.ExecuteCommand("InsertLine");
        EnterInsertMode()

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

    elif c == "cgg":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        SetLineSelection(0, start[1])
        N10X.Editor.ExecuteCommand("Cut")
        AddNewlineToClipboard()
        N10X.Editor.ExecuteCommand("InsertLine")
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()

    elif c == "cg":
        return

    elif c == "cG":
        N10X.Editor.PushUndoGroup()
        start = N10X.Editor.GetCursorPos()
        SetLineSelection(start[1], GetMaxY())
        N10X.Editor.ExecuteCommand("Cut")
        AddNewlineToClipboard()
        N10X.Editor.ExecuteCommand("InsertLine")
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()

    elif c == "cw":
        x, y = N10X.Editor.GetCursorPos()
        x = min(GetLineLength(y) - 1, x)
        end_x = x
        line = GetLine(y)
        character_class = GetCharacterClass(line[end_x])
        while end_x < len(line) - 1 and GetCharacterClass(line[end_x + 1]) == character_class:
            end_x += 1
        SetSelection((x, y), (end_x, y))
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()

    elif c == "ciw":
        start, end = GetInsideWordSelection(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()

    elif c == "caw":
        start, end = GetAroundWordSelection(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Cut")
        EnterInsertMode()

    elif (m := re.match("c" + g_RepeatMatch + "i" + g_BlockMatch, c)):
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        if sel := SelectOrMoveInsideBlock(action, count, True):
            start, end = sel
            N10X.Editor.PushUndoGroup()
            N10X.Editor.ExecuteCommand("Cut")
            if end[1] - start[1] > 0:
                N10X.Editor.ExecuteCommand("InsertLine")
            EnterInsertMode()
            N10X.Editor.PopUndoGroup()

    elif (m := re.match("c" + g_RepeatMatch + "a" + g_BlockMatch, c)):
        count = int(m.group(1)) if m.group(1) else 1
        action = m.group(2)
        if pos := SelectAroundBlock(action, count):
            N10X.Editor.PushUndoGroup()
            N10X.Editor.ExecuteCommand("Cut")
            EnterInsertMode()
            N10X.Editor.PopUndoGroup()
    
    elif (m := re.match("ci([`'\"])", c)):
        action = m.group(1)
        if SelectOrMoveInsideQuote(action):
            N10X.Editor.PushUndoGroup()
            N10X.Editor.ExecuteCommand("Cut")
            N10X.Editor.PopUndoGroup()
            EnterInsertMode()
    
    elif (m := re.match("ca([`'\"])", c)):
        action = m.group(1)
        if SelectQuote(action):
            N10X.Editor.PushUndoGroup()
            N10X.Editor.ExecuteCommand("Cut")
            N10X.Editor.PopUndoGroup()
            EnterInsertMode()

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

    elif c == "c0":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetSelection((0, y), (max(0, x - 1), y))
        N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()

    elif c == "C" or c == "c$":
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        SetSelection((x, y), (GetLineLength(y), y))
        N10X.Editor.ExecuteCommand("Cut")
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()

    elif (m := re.match("c" + g_RepeatMatch + "j", c)):
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        count = int(m.group(1)) if m.group(1) else 1
        end_y = min(y + count, GetMaxY())
        N10X.Editor.SetSelection((0, y), (GetLineLength(end_y), end_y))
        N10X.Editor.ExecuteCommand("Cut")
        AddNewlineToClipboard()
        SetCursorPos(x, min(y, end_y), max_offset=0)
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()

    elif (m := re.match("c" + g_RepeatMatch + "k", c)):
        N10X.Editor.PushUndoGroup()
        x, y = N10X.Editor.GetCursorPos()
        count = int(m.group(1)) if m.group(1) else 1
        end_y = max(0, y - count)
        N10X.Editor.SetSelection((GetLineLength(y), y), (0, end_y))
        N10X.Editor.ExecuteCommand("Cut")
        AddNewlineToClipboard()
        SetCursorPos(x, min(y, end_y), max_offset=0)
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()

    elif (m := re.match("c" + g_RepeatMatch + "([fFtT;])(.?)", c)):
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
        N10X.Editor.PopUndoGroup()
        EnterInsertMode()

    elif (m := re.match("c" + g_RepeatMatch, c)):
        return

    elif c == "J":
        N10X.Editor.PushUndoGroup()
        SetCursorPos(x=GetLineLength(), max_offset=0)
        N10X.Editor.InsertText(" ")
        N10X.Editor.ExecuteCommand("Delete")
        N10X.Editor.PopUndoGroup()

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

    # Undo/Redo

    elif c == "u":
        for i in range(repeat_count):
            N10X.Editor.ExecuteCommand("Undo")
            x, y = N10X.Editor.GetSelectionStart()
            N10X.Editor.ClearSelection()
            SetCursorPos(x, y)

    # Copying

    elif c == "yy":
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
            if not MoveToNextWordStart(wrap=False):
                return
        MoveCursorPos(x_delta=-1)
        end = N10X.Editor.GetCursorPos()
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(x=min(start[0], end[0]))

    elif c == "yiw":
        start, end = GetInsideWordSelection(N10X.Editor.GetCursorPos())
        SetSelection(start, end)
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(start[0], start[1])

    elif c == "yaw":
        start, end = GetAroundWordSelection(N10X.Editor.GetCursorPos())
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
        if pos := SelectAroundBlock(action, N10X.Editor.GetCursorPos(), count):
            N10X.Editor.ExecuteCommand("Copy")
            SetCursorPos(pos[0], pos[1])
    
    elif (m := re.match("yi([`'\"])", c)):
        action = m.group(1)
        if pos := SelectOrMoveInsideQuote(m.group(1)):
            N10X.Editor.ExecuteCommand("Copy")
            SetCursorPos(pos[0], pos[1])
    
    elif (m := re.match("ya([`'\"])", c)):
        action = m.group(1)
        if pos := SelectAroundQuotes(m.group(1), N10X.Editor.GetCursorPos()):
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
        SetCursorPos(x=min(start[0], end[0]-1))

    elif c == "y0":
        x, y = N10X.Editor.GetCursorPos()
        SetSelection((0, y), (max(0, x - 1), y))
        N10X.Editor.ExecuteCommand("Copy")
        SetCursorPos(0, y)

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

    elif (m := re.match("y" + g_RepeatMatch + "([fFtT;])(.?)", c)):
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

    elif c == "P":
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            clipboard_value = GetClipboardValue()
            if clipboard_value and clipboard_value[-1:] == "\n":
                SetCursorPos(x=GetLineLength(), max_offset=0)
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

    # Marcos

    elif c == "qa":
        if not g_StartedRecordingMacro:
            N10X.Editor.ExecuteCommand("RecordKeySequence")
            g_StartedRecordingMacro = True

    elif c == "q":
        if g_StartedRecordingMacro:
            N10X.Editor.ExecuteCommand("RecordKeySequence")
            g_StartedRecordingMacro = False
        else:
            return

    elif c == "@":
        return

    elif c == "@a" or c == "@@":
        N10X.Editor.PushUndoGroup()
        for i in range(repeat_count):
            N10X.Editor.ExecuteCommand("PlaybackKeySequence")
        N10X.Editor.PopUndoGroup()

    # Command Panel

    elif c == ":":
        N10X.Editor.ExecuteCommand("ShowCommandPanel")
        N10X.Editor.SetCommandPanelText(":")

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
        N10X.Editor.ExecuteCommand("GotoSymbolDefinition");

    else:
        print("[vim] Unknown command!")

    g_Command = ""

#------------------------------------------------------------------------
def HandlePaneModeChar(char):
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

    UpdateVisualModeSelection()
    EnterCommandMode()

#------------------------------------------------------------------------
def HandleCommandModeKey(key, shift, control, alt):
    global g_HandingKey
    global g_Command

    if g_HandingKey:
        return
    g_HandingKey = True

    handled = True

    pass_through = False

    if key == "Escape":
        EnterCommandMode()

    elif key == "/" and control:
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

    elif key == "Tab" and shift:
        N10X.Editor.ExecuteCommand("PrevPanelTab")

    elif key == "Tab":
        N10X.Editor.ExecuteCommand("NextPanelTab")
   
    elif key == "W" and control:
        EnterPaneMode()

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

    elif key == "U" and control:
        MoveCursorPos(y_delta=int(-N10X.Editor.GetVisibleLineCount()/2))
        N10X.Editor.ScrollCursorIntoView()

    elif key == "D" and control:
        MoveCursorPos(y_delta=int(N10X.Editor.GetVisibleLineCount()/2))
        N10X.Editor.ScrollCursorIntoView()

    elif key == "B" and control:
        N10X.Editor.SendKey("PageUp")

    elif key == "F" and control:
        N10X.Editor.SendKey("PageDown")

    elif key == "Y" and control:
        scroll_line = N10X.Editor.GetScrollLine()
        MoveCursorPos(y_delta=-1)
        N10X.Editor.SetScrollLine(scroll_line - 1)

    elif key == "E" and control:
        scroll_line = N10X.Editor.GetScrollLine()
        MoveCursorPos(y_delta=1)
        N10X.Editor.SetScrollLine(scroll_line + 1)

    elif key == "O" and control:
        N10X.Editor.ExecuteCommand("PrevLocation")

    elif key == "I" and control:
        N10X.Editor.ExecuteCommand("NextLocation")

    else:
        handled = False

        pass_through = \
            control or \
            alt or \
            key == "Delete" or \
            key == "Backspace" or \
            key == "Up" or \
            key == "Down" or \
            key == "Left" or \
            key == "Right" or \
            key == "PageUp" or \
            key == "PageDown" or \
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
        g_Command = ""

    g_HandingKey = False

    UpdateVisualModeSelection()

    return not pass_through

#------------------------------------------------------------------------
def HandleInsertModeKey(key, shift, control, alt):
    if key == "Escape" and not N10X.Editor.IsShowingAutocomplete():
        EnterCommandMode()
        return True

    if key == "C" and control:
        EnterCommandMode()
        return True

#------------------------------------------------------------------------
def HandleInsertModeChar(char):
    global g_SingleReplace
    global g_MultiReplace

    if g_SingleReplace or g_MultiReplace:
        x, y = N10X.Editor.GetCursorPos()
        SetSelection((x, y), (x, y))
        N10X.Editor.ExecuteCommand("Cut")
    
    if g_SingleReplace:
        MoveCursorPos(x_delta=1, max_offset=0)
        EnterCommandMode()

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
        SetCursorPos(start[0], start[1])

    elif c == "d" or c == "x":
        start, _ = SubmitVisualModeSelection()
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        EnterCommandMode()

    elif c == "c":
        start, _ = SubmitVisualModeSelection()
        N10X.Editor.ExecuteCommand("Cut")
        SetCursorPos(start[0], start[1])
        EnterInsertMode()

    elif c == "0":
        MoveToStartOfLine()

    elif c == "$":
        MoveToEndOfLine()

    elif c == "G":
        MoveToEndOfFile();

    elif c == "g":
        return

    elif c == "gg":
        MoveToStartOfFile();

    elif c == "h":
        for _ in range(repeat_count):
            MoveCursorPos(x_delta=-1)

    elif c == "l":
        for _ in range(repeat_count):
            MoveCursorPos(x_delta=1)

    elif c == "k":
        for _ in range(repeat_count):
            MoveCursorPos(y_delta=-1)

    elif c == "j":
        for _ in range(repeat_count):
            MoveCursorPos(y_delta=1)

    elif c == "w":
        for _ in range(repeat_count):
            MoveToNextWordStart()

    elif c == "e":
        for _ in range(repeat_count):
            MoveToWordEnd()

    elif c == "b":
        for _ in range(repeat_count):
            MoveToWordStart()

    elif (m := re.match("([fFtT;])(.?)", c)):
        for _ in range(repeat_count):
            action = m.group(1)
            search = m.group(2)
            if not MoveToLineText(action, search):
                return

    elif c == "%":
        N10X.Editor.ExecuteCommand("MoveToMatchingBracket")

    elif c == ">":
        for _ in range(repeat_count):
            N10X.Editor.ExecuteCommand("IndentLine")

    elif c == "<":
        for _ in range(repeat_count):
            N10X.Editor.ExecuteCommand("UnindentLine")
    
    elif c == "i" or c == "a":
        # Stub for text-object motions.
        return

    # Following commands are visual char mode only, and will switch your mode.
    elif c == "iw":
        g_Mode = Mode.VISUAL
        start, end = GetInsideWordSelection(N10X.Editor.GetCursorPos())
        AddVisualModeSelection(start, end)

    elif c == "aw":
        g_Mode = Mode.VISUAL
        start, end = GetAroundWordSelection(N10X.Editor.GetCursorPos())
        AddVisualModeSelection(start, end)

    elif (m := re.match("i" + g_BlockMatch, c)):
        g_Mode = Mode.VISUAL
        action = m.group(1)
        if sel := GetInsideBlockSelectionOrPos(m.group(1), N10X.Editor.GetCursorPos()):
            start, end = sel
            AddVisualModeSelection(start, end)
    
    elif (m := re.match("a" + g_BlockMatch, c)):
        g_Mode = Mode.VISUAL
        action = m.group(1)
        if sel := GetAroundBlockSelection(m.group(1), N10X.Editor.GetCursorPos()):
            start, end = sel
            AddVisualModeSelection(start, end)
    
    elif (m := re.match("i([`'\"])", c)):
        g_Mode = Mode.VISUAL
        action = m.group(1)
        if sel := GetInsideQuoteSelection(m.group(1), N10X.Editor.GetCursorPos()):
            start, end = sel
            AddVisualModeSelection(start, end)
    
    elif (m := re.match("a([`'\"])", c)):
        g_Mode = Mode.VISUAL
        action = m.group(1)
        if sel := GetAroundQuoteSelection(m.group(1), N10X.Editor.GetCursorPos()):
            start, end = sel
            AddVisualModeSelection(start, end)

    else:
        print("[vim] Unknown command!")
    
    g_Command = ""
    UpdateVisualModeSelection()

#------------------------------------------------------------------------
def UpdateCursorMode():
    if g_Command or g_SingleReplace:
        N10X.Editor.SetCursorMode("HalfBlock")
        N10X.Editor.SetStatusBarText(g_Command)
    elif g_Mode == Mode.INSERT:
        N10X.Editor.SetCursorMode("Line")
        N10X.Editor.SetStatusBarText("-- INSERT --")
    elif g_Mode == Mode.VISUAL:
        N10X.Editor.SetCursorMode("Block")
        N10X.Editor.SetStatusBarText("-- VISUAL --")
    elif g_Mode == Mode.VISUAL_LINE:
        N10X.Editor.SetCursorMode("Block")
        N10X.Editor.SetStatusBarText("-- VISUAL LINE --")
    else:
        N10X.Editor.SetCursorMode("Block")
        N10X.Editor.SetStatusBarText("")

#------------------------------------------------------------------------
# 10X Callbacks

#------------------------------------------------------------------------
# Called when a key is pressed.
# Return true to surpress the key
def OnInterceptKey(key, shift, control, alt):
    global g_HandleKeyIntercepts
    if not g_HandleKeyIntercepts:
        return False

    if N10X.Editor.TextEditorHasFocus():
        global g_Mode
        if g_Mode == Mode.PANE:
            ret = True
        elif g_Mode != Mode.INSERT:
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
        if g_Mode == Mode.INSERT:
            HandleInsertModeChar(c)
        elif g_Mode == Mode.VISUAL or g_Mode == Mode.VISUAL_LINE:
            HandleVisualModeChar(c)
            N10X.Editor.SetCursorMode("Block")
        elif g_Mode == Mode.PANE:
            HandlePaneModeChar(c)
        elif g_Mode == Mode.COMMAND:
            HandleCommandModeChar(c)
        UpdateCursorMode()
        return ret
    return False

#------------------------------------------------------------------------
def HandleCommandPanelCommand(command):

    if command == ":sp":
        print("[vim] "+command+" (split) unimplemented")
        return True
    
    if command == ":vsp":
        print("[vim] "+command+" (vertical split) unimplemented")
        return True

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
        SetCursorPos(y=int(split[1]) - 1)
        return True

#------------------------------------------------------------------------
def EnableVim():
    global g_VimEnabled
    global g_SneakEnabled

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

    g_SneakEnabled = N10X.Editor.GetSetting("VimSneakEnabled") == "true"

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
