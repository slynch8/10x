import N10X
from enum import Enum, auto

# =============================================================================
# Enums and Constants
# =============================================================================

class UserHandledResult(Enum):
    UNHANDLED = auto()
    HANDLED = auto()
    PASS_TO_10X = auto()

class Mode(Enum):
    NORMAL = auto()
    INSERT = auto()
    VISUAL = auto()
    VISUAL_LINE = auto()
    VISUAL_BLOCK = auto()
    COMMAND_LINE = auto()
    REPLACE = auto()

# =============================================================================
# Key Class
# =============================================================================

class Key:
    def __init__(self, key, shift=False, control=False, alt=False):
        self.key = key  # Keep original case
        self.shift = shift
        self.control = control
        self.alt = alt

    def __eq__(self, other):
        if not isinstance(other, Key):
            return False
        return (self.key == other.key and
                self.shift == other.shift and
                self.control == other.control and
                self.alt == other.alt)

    def __hash__(self):
        return hash((self.key, self.shift, self.control, self.alt))

    def __repr__(self):
        mods = []
        if self.control:
            mods.append("C")
        if self.shift:
            mods.append("S")
        if self.alt:
            mods.append("A")
        if mods:
            return f"<{'-'.join(mods)}-{self.key}>"
        return f"<{self.key}>"

# Import VimUser for user customization hooks
import VimUser

# =============================================================================
# Global State
# =============================================================================

g_mode = Mode.NORMAL
g_count = ""
g_operator = ""
g_pending_motion = ""
g_command_line = ""
g_command_line_type = ""  # ":" or "/" or "?"
g_last_search = ""
g_last_search_direction = 1  # 1 = forward, -1 = backward
g_registers = {"\"": "", "0": ""}  # Default and yank registers
g_current_register = "\""
g_marks = {}
g_last_edit = None  # For . repeat
g_last_insert_text = ""
g_visual_start = (0, 0)
g_recording_macro = ""
g_macros = {}
g_macro_keys = []
g_jump_list = []
g_jump_index = -1
g_last_f_char = ""
g_last_f_direction = 1
g_last_t_mode = False  # True for t/T, False for f/F
g_insert_start_pos = (0, 0)
g_exit_sequence = ""
g_exit_sequence_chars = ""
g_initialized = False
g_sneak_enabled = False
g_use_10x_command_panel = False
g_use_10x_find_panel = False
g_filtered_history = True
g_show_scope_name = False
g_command_history = []
g_command_history_index = -1
g_search_history = []
g_search_history_index = -1
g_last_visual_start = (0, 0)
g_last_visual_end = (0, 0)
g_last_visual_mode = Mode.VISUAL
g_debug = False
g_suppress_next_char = False  # Suppress char after operator enters insert mode
g_change_undo_group = False   # Track if we're in a change operation undo group

# =============================================================================
# Utility Functions
# =============================================================================

def get_line(y):
    try:
        return N10X.Editor.GetLine(y) or ""
    except:
        return ""

def get_line_count():
    try:
        return N10X.Editor.GetLineCount() or 1
    except:
        return 1

def get_cursor_pos():
    try:
        pos = N10X.Editor.GetCursorPos(0)
        return (pos[0], pos[1])
    except:
        return (0, 0)

def set_cursor_pos(x, y, extend_selection=False):
    line_count = get_line_count()
    y = max(0, min(y, line_count - 1))
    line = get_line(y)
    line_len = len(line.rstrip('\n\r'))
    if g_mode == Mode.NORMAL and line_len > 0:
        x = max(0, min(x, line_len - 1))
    else:
        x = max(0, min(x, line_len))
    try:
        if extend_selection:
            N10X.Editor.SetCursorPosSelect((x, y))
        else:
            N10X.Editor.SetCursorPos((x, y), 0)
    except:
        pass

def get_selection():
    try:
        return N10X.Editor.GetSelection() or ""
    except:
        return ""

def set_selection(start, end):
    try:
        N10X.Editor.SetSelection(start, end, 0)
    except:
        pass

def clear_selection():
    try:
        N10X.Editor.ClearSelection()
    except:
        pass

def insert_text(text):
    try:
        N10X.Editor.InsertText(text)
    except:
        pass

def delete_selection():
    sel = get_selection()
    if sel:
        N10X.Editor.ExecuteCommand("Delete")
    return sel

def get_word_at_cursor():
    x, y = get_cursor_pos()
    line = get_line(y)
    if not line or x >= len(line):
        return ""
    start = x
    end = x
    while start > 0 and (line[start-1].isalnum() or line[start-1] == '_'):
        start -= 1
    while end < len(line) and (line[end].isalnum() or line[end] == '_'):
        end += 1
    return line[start:end]

def _change_number_under_cursor(delta):
    """Increment or decrement number under/after cursor"""
    x, y = get_cursor_pos()
    line = get_line(y)
    line_len = len(line.rstrip('\n\r'))

    # Find a number at or after cursor position
    num_start = -1
    num_end = -1
    is_hex = False
    is_negative = False

    # First check if we're inside a number
    i = x
    while i < line_len:
        c = line[i]
        if c.isdigit():
            # Found a digit, find the full number
            num_end = i
            while num_end < line_len and (line[num_end].isdigit() or
                  (is_hex and line[num_end] in 'abcdefABCDEF')):
                num_end += 1

            num_start = i
            # Check for hex prefix
            if num_start >= 2 and line[num_start-2:num_start] in ('0x', '0X'):
                num_start -= 2
                is_hex = True
            # Check for negative sign
            elif num_start > 0 and line[num_start-1] == '-':
                num_start -= 1
                is_negative = True
            break
        elif c in 'xX' and i > 0 and line[i-1] == '0' and i + 1 < line_len and line[i+1] in '0123456789abcdefABCDEF':
            # Hex number
            num_start = i - 1
            is_hex = True
            num_end = i + 1
            while num_end < line_len and line[num_end] in '0123456789abcdefABCDEF':
                num_end += 1
            break
        i += 1

    if num_start < 0:
        return

    # Extract and modify the number
    num_str = line[num_start:num_end]
    try:
        if is_hex:
            num = int(num_str, 16)
            new_num = num + delta
            if new_num < 0:
                new_num_str = '-' + hex(abs(new_num))[2:]
            else:
                new_num_str = hex(new_num)
                if num_str.startswith('0X'):
                    new_num_str = new_num_str.upper().replace('0X', '0x')
        else:
            num = int(num_str)
            new_num = num + delta
            new_num_str = str(new_num)

        # Replace in line
        new_line = line[:num_start] + new_num_str + line[num_end:]
        N10X.Editor.SetLine(y, new_line)
        # Position cursor at end of number
        set_cursor_pos(num_start + len(new_num_str) - 1, y)
    except ValueError:
        pass

def is_word_char(c):
    return c.isalnum() or c == '_'

def is_whitespace(c):
    return c in ' \t'

def is_big_word_char(c):
    return not is_whitespace(c) and c not in '\n\r'

def set_status(text):
    try:
        N10X.Editor.SetStatusBarText(text)
    except:
        pass

def set_cursor_style():
    try:
        if g_mode == Mode.NORMAL:
            N10X.Editor.SetCursorMode("Block")
        elif g_mode == Mode.INSERT:
            N10X.Editor.SetCursorMode("Line")
        elif g_mode == Mode.REPLACE:
            N10X.Editor.SetCursorMode("Underscore")
        elif g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK):
            N10X.Editor.SetCursorMode("Block")
        elif g_mode == Mode.COMMAND_LINE:
            N10X.Editor.SetCursorMode("Block")
    except:
        pass

def update_status():
    mode_names = {
        Mode.NORMAL: "NORMAL",
        Mode.INSERT: "INSERT",
        Mode.VISUAL: "VISUAL",
        Mode.VISUAL_LINE: "V-LINE",
        Mode.VISUAL_BLOCK: "V-BLOCK",
        Mode.COMMAND_LINE: "COMMAND",
        Mode.REPLACE: "REPLACE",
    }
    status = f"-- {mode_names.get(g_mode, 'UNKNOWN')} --"
    if g_count:
        status += f" {g_count}"
    if g_operator:
        status += f" {g_operator}"
    if g_recording_macro:
        status += f" recording @{g_recording_macro}"
    set_status(status)

def push_jump():
    global g_jump_list, g_jump_index
    pos = get_cursor_pos()
    filename = N10X.Editor.GetCurrentFilename()
    if filename:
        g_jump_list = g_jump_list[:g_jump_index + 1]
        g_jump_list.append((filename, pos))
        if len(g_jump_list) > 100:
            g_jump_list = g_jump_list[-100:]
        g_jump_index = len(g_jump_list) - 1

def yank_to_register(text, linewise=False):
    global g_registers
    reg = g_current_register
    if linewise and not text.endswith('\n'):
        text = text + '\n'
    g_registers[reg] = text
    g_registers["0"] = text
    g_registers["\""] = text

def get_register(reg=None):
    if reg is None:
        reg = g_current_register
    if reg == "+":
        # System clipboard - use 10x paste
        return g_registers.get("\"", "")
    return g_registers.get(reg, "")

# =============================================================================
# Mode Management
# =============================================================================

def enter_mode(mode):
    global g_mode, g_visual_start, g_insert_start_pos, g_last_insert_text
    global g_count, g_operator, g_pending_motion, g_current_register, g_exit_sequence
    global g_last_visual_start, g_last_visual_end, g_last_visual_mode

    old_mode = g_mode
    g_mode = mode
    g_count = ""
    g_operator = ""
    g_pending_motion = ""
    g_current_register = "\""
    g_exit_sequence = ""

    if mode == Mode.INSERT:
        g_insert_start_pos = get_cursor_pos()
        g_last_insert_text = ""
    elif mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK):
        g_visual_start = get_cursor_pos()
    elif mode == Mode.NORMAL:
        # Save last visual selection before clearing
        if old_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK):
            g_last_visual_start = g_visual_start
            g_last_visual_end = get_cursor_pos()
            g_last_visual_mode = old_mode
        clear_selection()
        # Adjust cursor if coming from insert mode
        if old_mode == Mode.INSERT:
            # Close undo group if we were in a change operation
            global g_change_undo_group
            if g_change_undo_group:
                N10X.Editor.PopUndoGroup()
                g_change_undo_group = False
            x, y = get_cursor_pos()
            line = get_line(y)
            if x > 0 and x >= len(line.rstrip('\n\r')):
                set_cursor_pos(x - 1, y)

    set_cursor_style()
    update_status()

def enter_normal_mode():
    enter_mode(Mode.NORMAL)

def enter_insert_mode():
    enter_mode(Mode.INSERT)

def enter_visual_mode():
    enter_mode(Mode.VISUAL)

def enter_visual_line_mode():
    enter_mode(Mode.VISUAL_LINE)

def enter_visual_block_mode():
    enter_mode(Mode.VISUAL_BLOCK)

def enter_command_line_mode(char):
    global g_mode, g_command_line, g_command_line_type
    global g_command_history_index, g_search_history_index
    g_mode = Mode.COMMAND_LINE
    g_command_line = ""
    g_command_line_type = char
    g_command_history_index = -1
    g_search_history_index = -1
    set_status(char)
    set_cursor_style()

# =============================================================================
# Motions
# =============================================================================

def motion_h(count=1):
    x, y = get_cursor_pos()
    set_cursor_pos(x - count, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_l(count=1):
    x, y = get_cursor_pos()
    set_cursor_pos(x + count, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_j(count=1):
    x, y = get_cursor_pos()
    set_cursor_pos(x, y + count, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_k(count=1):
    x, y = get_cursor_pos()
    set_cursor_pos(x, y - count, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_0():
    x, y = get_cursor_pos()
    set_cursor_pos(0, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_caret():
    x, y = get_cursor_pos()
    line = get_line(y)
    for i, c in enumerate(line):
        if not is_whitespace(c):
            set_cursor_pos(i, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))
            return
    set_cursor_pos(0, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_dollar(count=1):
    x, y = get_cursor_pos()
    target_y = y + count - 1
    line = get_line(target_y)
    line_len = len(line.rstrip('\n\r'))
    pos = max(0, line_len - 1) if g_mode == Mode.NORMAL else line_len
    set_cursor_pos(pos, target_y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_w(count=1):
    x, y = get_cursor_pos()
    for _ in range(count):
        line = get_line(y)
        line_len = len(line.rstrip('\n\r'))
        if x >= line_len:
            if y < get_line_count() - 1:
                y += 1
                x = 0
                line = get_line(y)
                while x < len(line) and is_whitespace(line[x]):
                    x += 1
            continue

        # Skip current word
        if x < len(line) and is_word_char(line[x]):
            while x < line_len and is_word_char(line[x]):
                x += 1
        elif x < len(line) and not is_whitespace(line[x]):
            while x < line_len and not is_whitespace(line[x]) and not is_word_char(line[x]):
                x += 1

        # Skip whitespace
        while x < line_len and is_whitespace(line[x]):
            x += 1

        # Move to next line if at end
        if x >= line_len and y < get_line_count() - 1:
            y += 1
            x = 0
            line = get_line(y)
            while x < len(line) and is_whitespace(line[x]):
                x += 1

    set_cursor_pos(x, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_W(count=1):
    x, y = get_cursor_pos()
    for _ in range(count):
        line = get_line(y)
        line_len = len(line.rstrip('\n\r'))

        # Skip current WORD
        while x < line_len and is_big_word_char(line[x]):
            x += 1

        # Skip whitespace
        while x < line_len and is_whitespace(line[x]):
            x += 1

        if x >= line_len and y < get_line_count() - 1:
            y += 1
            x = 0
            line = get_line(y)
            while x < len(line) and is_whitespace(line[x]):
                x += 1

    set_cursor_pos(x, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_b(count=1):
    x, y = get_cursor_pos()
    for _ in range(count):
        if x == 0:
            if y > 0:
                y -= 1
                line = get_line(y)
                x = len(line.rstrip('\n\r'))

        line = get_line(y)

        # Move back one
        if x > 0:
            x -= 1

        # Skip whitespace
        while x > 0 and is_whitespace(line[x]):
            x -= 1

        # Skip to start of word
        if x >= 0 and x < len(line) and is_word_char(line[x]):
            while x > 0 and is_word_char(line[x-1]):
                x -= 1
        elif x >= 0 and x < len(line) and not is_whitespace(line[x]):
            while x > 0 and not is_whitespace(line[x-1]) and not is_word_char(line[x-1]):
                x -= 1

    set_cursor_pos(x, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_B(count=1):
    x, y = get_cursor_pos()
    for _ in range(count):
        if x == 0 and y > 0:
            y -= 1
            line = get_line(y)
            x = len(line.rstrip('\n\r'))

        line = get_line(y)
        if x > 0:
            x -= 1

        while x > 0 and is_whitespace(line[x]):
            x -= 1

        while x > 0 and is_big_word_char(line[x-1]):
            x -= 1

    set_cursor_pos(x, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_e(count=1):
    x, y = get_cursor_pos()
    for _ in range(count):
        line = get_line(y)
        line_len = len(line.rstrip('\n\r'))

        if x < line_len - 1:
            x += 1
        elif y < get_line_count() - 1:
            y += 1
            x = 0
            line = get_line(y)
            line_len = len(line.rstrip('\n\r'))

        # Skip whitespace
        while x < line_len and is_whitespace(line[x]):
            x += 1
            if x >= line_len and y < get_line_count() - 1:
                y += 1
                x = 0
                line = get_line(y)
                line_len = len(line.rstrip('\n\r'))

        # Move to end of word
        if x < len(line) and is_word_char(line[x]):
            while x < line_len - 1 and is_word_char(line[x+1]):
                x += 1
        elif x < len(line) and not is_whitespace(line[x]):
            while x < line_len - 1 and not is_whitespace(line[x+1]) and not is_word_char(line[x+1]):
                x += 1

    set_cursor_pos(x, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_E(count=1):
    x, y = get_cursor_pos()
    for _ in range(count):
        line = get_line(y)
        line_len = len(line.rstrip('\n\r'))

        if x < line_len - 1:
            x += 1
        elif y < get_line_count() - 1:
            y += 1
            x = 0
            line = get_line(y)
            line_len = len(line.rstrip('\n\r'))

        while x < line_len and is_whitespace(line[x]):
            x += 1
            if x >= line_len and y < get_line_count() - 1:
                y += 1
                x = 0
                line = get_line(y)
                line_len = len(line.rstrip('\n\r'))

        while x < line_len - 1 and is_big_word_char(line[x+1]):
            x += 1

    set_cursor_pos(x, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_ge(count=1):
    """Move backward to end of previous word"""
    x, y = get_cursor_pos()
    for _ in range(count):
        line = get_line(y)

        # Move back one position first
        if x > 0:
            x -= 1
        elif y > 0:
            y -= 1
            line = get_line(y)
            x = len(line.rstrip('\n\r')) - 1
            if x < 0:
                x = 0

        # Skip whitespace
        while True:
            line = get_line(y)
            line_len = len(line.rstrip('\n\r'))
            while x >= 0 and x < line_len and is_whitespace(line[x]):
                x -= 1
            if x < 0:
                if y > 0:
                    y -= 1
                    line = get_line(y)
                    x = len(line.rstrip('\n\r')) - 1
                else:
                    x = 0
                    break
            else:
                break

        # Skip to start of word, then go to end
        line = get_line(y)
        if x >= 0 and x < len(line) and is_word_char(line[x]):
            # Already at word char - we're at the end
            pass
        elif x >= 0 and x < len(line) and not is_whitespace(line[x]):
            # At punctuation - we're at the end
            pass

    set_cursor_pos(x, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_gE(count=1):
    """Move backward to end of previous WORD"""
    x, y = get_cursor_pos()
    for _ in range(count):
        line = get_line(y)

        if x > 0:
            x -= 1
        elif y > 0:
            y -= 1
            line = get_line(y)
            x = len(line.rstrip('\n\r')) - 1
            if x < 0:
                x = 0

        # Skip whitespace
        while True:
            line = get_line(y)
            line_len = len(line.rstrip('\n\r'))
            while x >= 0 and x < line_len and is_whitespace(line[x]):
                x -= 1
            if x < 0:
                if y > 0:
                    y -= 1
                    line = get_line(y)
                    x = len(line.rstrip('\n\r')) - 1
                else:
                    x = 0
                    break
            else:
                break

    set_cursor_pos(x, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_brace_forward(count=1):
    """Move forward to next blank line"""
    x, y = get_cursor_pos()
    line_count = get_line_count()

    for _ in range(count):
        # Move forward at least one line
        y += 1
        # If we're in blank lines, skip past them first
        while y < line_count and not get_line(y).strip():
            y += 1
        # Now find the next blank line
        while y < line_count and get_line(y).strip():
            y += 1
        # y is now at a blank line or end of file

    y = min(y, line_count - 1)
    set_cursor_pos(0, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_brace_backward(count=1):
    """Move backward to previous blank line"""
    x, y = get_cursor_pos()

    for _ in range(count):
        # Move backward at least one line
        y -= 1
        # If we're in blank lines, skip past them first
        while y > 0 and not get_line(y).strip():
            y -= 1
        # Now find the previous blank line
        while y > 0 and get_line(y).strip():
            y -= 1
        # y is now at a blank line or start of file

    y = max(0, y)
    set_cursor_pos(0, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_gg(count=None):
    push_jump()
    if count is None:
        count = 1
    target_y = count - 1
    set_cursor_pos(0, target_y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))
    motion_caret()

def motion_G(count=None):
    push_jump()
    if count is None:
        target_y = get_line_count() - 1
    else:
        target_y = count - 1
    set_cursor_pos(0, target_y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))
    motion_caret()

def motion_percent():
    x, y = get_cursor_pos()
    line = get_line(y)
    brackets = {'(': ')', ')': '(', '[': ']', ']': '[', '{': '}', '}': '{'}

    # Find bracket at or after cursor
    start_x = x
    while start_x < len(line) and line[start_x] not in brackets:
        start_x += 1

    if start_x >= len(line):
        return

    bracket = line[start_x]
    match = brackets[bracket]
    direction = 1 if bracket in '([{' else -1
    depth = 1
    curr_x, curr_y = start_x, y

    while depth > 0:
        curr_x += direction
        curr_line = get_line(curr_y)

        if direction > 0 and curr_x >= len(curr_line):
            curr_y += 1
            if curr_y >= get_line_count():
                return
            curr_x = 0
            curr_line = get_line(curr_y)
        elif direction < 0 and curr_x < 0:
            curr_y -= 1
            if curr_y < 0:
                return
            curr_line = get_line(curr_y)
            curr_x = len(curr_line) - 1

        if curr_x >= 0 and curr_x < len(curr_line):
            c = curr_line[curr_x]
            if c == bracket:
                depth += 1
            elif c == match:
                depth -= 1

    push_jump()
    set_cursor_pos(curr_x, curr_y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))

def motion_f(char, count=1):
    global g_last_f_char, g_last_f_direction, g_last_t_mode
    g_last_f_char = char
    g_last_f_direction = 1
    g_last_t_mode = False

    x, y = get_cursor_pos()
    line = get_line(y)
    found = 0
    for i in range(x + 1, len(line)):
        if line[i] == char:
            found += 1
            if found == count:
                set_cursor_pos(i, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))
                return True
    return False

def motion_F(char, count=1):
    global g_last_f_char, g_last_f_direction, g_last_t_mode
    g_last_f_char = char
    g_last_f_direction = -1
    g_last_t_mode = False

    x, y = get_cursor_pos()
    line = get_line(y)
    found = 0
    for i in range(x - 1, -1, -1):
        if line[i] == char:
            found += 1
            if found == count:
                set_cursor_pos(i, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))
                return True
    return False

def motion_t(char, count=1):
    global g_last_f_char, g_last_f_direction, g_last_t_mode
    g_last_f_char = char
    g_last_f_direction = 1
    g_last_t_mode = True

    x, y = get_cursor_pos()
    line = get_line(y)
    found = 0
    for i in range(x + 1, len(line)):
        if line[i] == char:
            found += 1
            if found == count:
                set_cursor_pos(i - 1, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))
                return True
    return False

def motion_T(char, count=1):
    global g_last_f_char, g_last_f_direction, g_last_t_mode
    g_last_f_char = char
    g_last_f_direction = -1
    g_last_t_mode = True

    x, y = get_cursor_pos()
    line = get_line(y)
    found = 0
    for i in range(x - 1, -1, -1):
        if line[i] == char:
            found += 1
            if found == count:
                set_cursor_pos(i + 1, y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))
                return True
    return False

def motion_semicolon(count=1):
    if g_last_f_char:
        if g_last_f_direction == 1:
            if g_last_t_mode:
                motion_t(g_last_f_char, count)
            else:
                motion_f(g_last_f_char, count)
        else:
            if g_last_t_mode:
                motion_T(g_last_f_char, count)
            else:
                motion_F(g_last_f_char, count)

def motion_comma(count=1):
    if g_last_f_char:
        if g_last_f_direction == 1:
            if g_last_t_mode:
                motion_T(g_last_f_char, count)
            else:
                motion_F(g_last_f_char, count)
        else:
            if g_last_t_mode:
                motion_t(g_last_f_char, count)
            else:
                motion_f(g_last_f_char, count)

def motion_H():
    try:
        scroll_line = N10X.Editor.GetScrollLine()
        set_cursor_pos(0, scroll_line, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))
        motion_caret()
    except:
        pass

def motion_M():
    try:
        scroll_line = N10X.Editor.GetScrollLine()
        visible = N10X.Editor.GetVisibleLineCount()
        mid = scroll_line + visible // 2
        set_cursor_pos(0, mid, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))
        motion_caret()
    except:
        pass

def motion_L():
    try:
        scroll_line = N10X.Editor.GetScrollLine()
        visible = N10X.Editor.GetVisibleLineCount()
        bottom = scroll_line + visible - 1
        set_cursor_pos(0, bottom, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))
        motion_caret()
    except:
        pass

# =============================================================================
# Text Objects
# =============================================================================

def get_text_object_range(obj, inner):
    x, y = get_cursor_pos()
    line = get_line(y)

    if obj == 'w':  # word
        if x >= len(line) or is_whitespace(line[x]):
            return None
        start = x
        end = x
        while start > 0 and is_word_char(line[start-1]):
            start -= 1
        while end < len(line) and is_word_char(line[end]):
            end += 1
        if not inner:
            while end < len(line) and is_whitespace(line[end]):
                end += 1
        return ((start, y), (end, y))

    elif obj == 'W':  # WORD
        if x >= len(line) or is_whitespace(line[x]):
            return None
        start = x
        end = x
        while start > 0 and is_big_word_char(line[start-1]):
            start -= 1
        while end < len(line) and is_big_word_char(line[end]):
            end += 1
        if not inner:
            while end < len(line) and is_whitespace(line[end]):
                end += 1
        return ((start, y), (end, y))

    elif obj in '"\'`':  # quotes
        # Find surrounding quotes on current line
        start = -1
        end = -1
        in_quote = False
        quote_start = -1
        for i, c in enumerate(line):
            if c == obj:
                if not in_quote:
                    quote_start = i
                    in_quote = True
                else:
                    if x >= quote_start and x <= i:
                        start = quote_start
                        end = i
                        break
                    in_quote = False
        if start >= 0 and end >= 0:
            if inner:
                return ((start + 1, y), (end, y))
            else:
                return ((start, y), (end + 1, y))
        return None

    elif obj in '([{<':
        pairs = {'(': ')', '[': ']', '{': '}', '<': '>'}
        close = pairs[obj]
        return find_bracket_range(obj, close, x, y, inner)

    elif obj in ')]}>':
        pairs = {')': '(', ']': '[', '}': '{', '>': '<'}
        open_b = pairs[obj]
        return find_bracket_range(open_b, obj, x, y, inner)

    elif obj == 'b':  # () block
        return find_bracket_range('(', ')', x, y, inner)

    elif obj == 'B':  # {} block
        return find_bracket_range('{', '}', x, y, inner)

    elif obj == 'p':  # paragraph
        start_y = y
        end_y = y

        # Find start of paragraph
        while start_y > 0 and get_line(start_y - 1).strip():
            start_y -= 1

        # Find end of paragraph
        while end_y < get_line_count() - 1 and get_line(end_y).strip():
            end_y += 1

        if inner:
            end_y -= 1
            if end_y < start_y:
                end_y = start_y
            return ((0, start_y), (len(get_line(end_y)), end_y))
        else:
            return ((0, start_y), (len(get_line(end_y)), end_y))

    elif obj == 's':  # sentence
        # Sentence ends with . ! ? followed by space or newline
        sentence_ends = '.!?'

        # Get full text to work with (current line and surrounding context)
        def get_pos_in_text(text_y, text_x):
            pos = 0
            for i in range(text_y):
                pos += len(get_line(i))
            return pos + text_x

        def get_text_pos(pos):
            curr_pos = 0
            for text_y in range(get_line_count()):
                line = get_line(text_y)
                if curr_pos + len(line) > pos:
                    return (pos - curr_pos, text_y)
                curr_pos += len(line)
            return (0, get_line_count() - 1)

        # Find sentence start (after previous . ! ? or start of paragraph)
        start_y = y
        start_x = x
        found_start = False

        # Search backward for sentence boundary
        curr_y, curr_x = y, x
        while curr_y >= 0:
            line = get_line(curr_y)
            search_start = curr_x if curr_y == y else len(line) - 1
            for i in range(search_start, -1, -1):
                if i < len(line) and line[i] in sentence_ends:
                    # Found end of previous sentence
                    start_x = i + 1
                    start_y = curr_y
                    # Skip whitespace after sentence end
                    while start_y < get_line_count():
                        line = get_line(start_y)
                        while start_x < len(line) and line[start_x] in ' \t\n\r':
                            start_x += 1
                        if start_x < len(line.rstrip('\n\r')):
                            break
                        start_y += 1
                        start_x = 0
                    found_start = True
                    break
            if found_start:
                break
            # Check for blank line (paragraph boundary)
            if not line.strip():
                start_y = curr_y + 1
                start_x = 0
                found_start = True
                break
            curr_y -= 1

        if not found_start:
            start_y = 0
            start_x = 0

        # Find sentence end
        end_y = y
        end_x = x
        found_end = False

        curr_y, curr_x = y, x
        while curr_y < get_line_count():
            line = get_line(curr_y)
            search_start = curr_x if curr_y == y else 0
            for i in range(search_start, len(line)):
                if line[i] in sentence_ends:
                    end_y = curr_y
                    end_x = i + 1
                    found_end = True
                    break
            if found_end:
                break
            # Check for blank line (paragraph boundary)
            if not line.strip():
                end_y = curr_y
                end_x = 0
                found_end = True
                break
            curr_y += 1

        if not found_end:
            end_y = get_line_count() - 1
            end_x = len(get_line(end_y))

        if inner:
            return ((start_x, start_y), (end_x, end_y))
        else:
            # Include trailing whitespace
            while end_y < get_line_count():
                line = get_line(end_y)
                while end_x < len(line) and line[end_x] in ' \t':
                    end_x += 1
                if end_x < len(line.rstrip('\n\r')):
                    break
                end_y += 1
                end_x = 0
            return ((start_x, start_y), (end_x, end_y))

    return None

def find_bracket_range(open_b, close_b, x, y, inner):
    # Search backward for opening bracket
    depth = 0
    curr_x, curr_y = x, y
    found_open = False
    open_x, open_y = 0, 0

    while curr_y >= 0:
        line = get_line(curr_y)
        start_x = curr_x if curr_y == y else len(line) - 1
        for i in range(start_x, -1, -1):
            if i < len(line):
                c = line[i]
                if c == close_b:
                    depth += 1
                elif c == open_b:
                    if depth == 0:
                        open_x, open_y = i, curr_y
                        found_open = True
                        break
                    depth -= 1
        if found_open:
            break
        curr_y -= 1
        if curr_y >= 0:
            curr_x = len(get_line(curr_y)) - 1

    if not found_open:
        return None

    # Search forward for closing bracket
    depth = 0
    curr_x, curr_y = open_x, open_y
    close_x, close_y = 0, 0

    while curr_y < get_line_count():
        line = get_line(curr_y)
        start_x = curr_x if curr_y == open_y else 0
        for i in range(start_x, len(line)):
            c = line[i]
            if c == open_b:
                depth += 1
            elif c == close_b:
                depth -= 1
                if depth == 0:
                    close_x, close_y = i, curr_y
                    if inner:
                        return ((open_x + 1, open_y), (close_x, close_y))
                    else:
                        return ((open_x, open_y), (close_x + 1, close_y))
        curr_y += 1
        curr_x = 0

    return None

# =============================================================================
# Operators
# =============================================================================

def apply_operator_to_range(op, start, end, linewise=False):
    global g_last_edit

    N10X.Editor.LogTo10XOutput(f"DEBUG apply_operator_to_range: op='{op}' start={start} end={end} linewise={linewise}\n")

    start_x, start_y = start
    end_x, end_y = end

    # Ensure start is before end
    if start_y > end_y or (start_y == end_y and start_x > end_x):
        start_x, start_y, end_x, end_y = end_x, end_y, start_x, start_y

    if linewise:
        start_x = 0
        end_line = get_line(end_y)
        end_x = len(end_line)

    set_selection((start_x, start_y), (end_x, end_y))
    text = get_selection()
    N10X.Editor.LogTo10XOutput(f"DEBUG apply_operator_to_range: selected text='{text}' len={len(text)}\n")

    if op == 'd':  # delete
        N10X.Editor.LogTo10XOutput(f"DEBUG: Deleting text\n")
        yank_to_register(text, linewise)
        delete_selection()
        if linewise:
            x, y = get_cursor_pos()
            motion_caret()
        g_last_edit = ('d', text, linewise)

    elif op == 'c':  # change
        global g_suppress_next_char, g_change_undo_group
        yank_to_register(text, linewise)
        N10X.Editor.PushUndoGroup()  # Group deletion and insertion together
        g_change_undo_group = True
        delete_selection()
        g_suppress_next_char = True  # Don't insert the motion key
        enter_insert_mode()
        g_last_edit = ('c', text, linewise)

    elif op == 'y':  # yank
        yank_to_register(text, linewise)
        clear_selection()
        set_cursor_pos(start_x, start_y)
        set_status(f"Yanked {len(text)} characters")
        g_last_edit = ('y', text, linewise)

    elif op == '>':  # indent
        N10X.Editor.PushUndoGroup()
        clear_selection()
        for line_y in range(start_y, end_y + 1):
            line = get_line(line_y)
            N10X.Editor.SetLine(line_y, "\t" + line)
        N10X.Editor.PopUndoGroup()
        set_cursor_pos(start_x, start_y)

    elif op == '<':  # unindent
        N10X.Editor.PushUndoGroup()
        clear_selection()
        for line_y in range(start_y, end_y + 1):
            line = get_line(line_y)
            if line.startswith('\t'):
                N10X.Editor.SetLine(line_y, line[1:])
            elif line.startswith('    '):
                N10X.Editor.SetLine(line_y, line[4:])
        N10X.Editor.PopUndoGroup()
        set_cursor_pos(start_x, start_y)

    elif op == 'gu':  # lowercase
        clear_selection()
        new_text = text.lower()
        set_selection((start_x, start_y), (end_x, end_y))
        insert_text(new_text)
        set_cursor_pos(start_x, start_y)

    elif op == 'gU':  # uppercase
        clear_selection()
        new_text = text.upper()
        set_selection((start_x, start_y), (end_x, end_y))
        insert_text(new_text)
        set_cursor_pos(start_x, start_y)

def operator_dd(count=1):
    x, y = get_cursor_pos()
    end_y = min(y + count - 1, get_line_count() - 1)
    end_line = get_line(end_y)
    apply_operator_to_range('d', (0, y), (len(end_line), end_y), linewise=True)

def operator_yy(count=1):
    x, y = get_cursor_pos()
    end_y = min(y + count - 1, get_line_count() - 1)
    end_line = get_line(end_y)
    apply_operator_to_range('y', (0, y), (len(end_line), end_y), linewise=True)

def operator_cc(count=1):
    x, y = get_cursor_pos()
    line = get_line(y)
    # Find first non-whitespace
    indent = 0
    for c in line:
        if c in ' \t':
            indent += 1
        else:
            break
    end_y = min(y + count - 1, get_line_count() - 1)
    end_line = get_line(end_y)
    # Use 'c' operator so it gets proper undo grouping and suppress flag
    apply_operator_to_range('c', (indent, y), (len(end_line.rstrip('\n\r')), end_y), linewise=False)
    # Note: apply_operator_to_range('c',...) already enters insert mode

# =============================================================================
# Search
# =============================================================================

def do_search(pattern, direction=1, whole_word=False):
    global g_last_search, g_last_search_direction

    if not pattern:
        pattern = g_last_search
    if not pattern:
        return

    g_last_search = pattern
    g_last_search_direction = direction

    push_jump()

    x, y = get_cursor_pos()
    line_count = get_line_count()

    # Search from current position
    start_y = y
    start_x = x + direction

    def find_pattern(line, start_pos, reverse=False):
        """Find pattern in line, optionally checking word boundaries"""
        if not whole_word:
            if reverse:
                return line.rfind(pattern, 0, max(0, start_pos))
            else:
                return line.find(pattern, start_pos)

        # Search with word boundary checking
        search_start = start_pos if not reverse else 0
        search_end = len(line) if not reverse else start_pos

        if reverse:
            # Search backwards
            idx = search_end
            while idx >= search_start:
                idx = line.rfind(pattern, search_start, idx)
                if idx < 0:
                    break
                # Check word boundaries
                before_ok = (idx == 0 or not is_word_char(line[idx - 1]))
                after_idx = idx + len(pattern)
                after_ok = (after_idx >= len(line) or not is_word_char(line[after_idx]))
                if before_ok and after_ok:
                    return idx
                idx -= 1
            return -1
        else:
            # Search forwards
            idx = search_start
            while idx < len(line):
                idx = line.find(pattern, idx)
                if idx < 0:
                    break
                # Check word boundaries
                before_ok = (idx == 0 or not is_word_char(line[idx - 1]))
                after_idx = idx + len(pattern)
                after_ok = (after_idx >= len(line) or not is_word_char(line[after_idx]))
                if before_ok and after_ok:
                    return idx
                idx += 1
            return -1

    for i in range(line_count + 1):
        if direction == 1:
            curr_y = (start_y + i) % line_count
        else:
            curr_y = (start_y - i) % line_count

        line = get_line(curr_y)

        if direction == 1:
            if curr_y == start_y:
                idx = find_pattern(line, start_x, reverse=False)
            else:
                idx = find_pattern(line, 0, reverse=False)
        else:
            if curr_y == start_y:
                idx = find_pattern(line, start_x, reverse=True)
            else:
                idx = find_pattern(line, len(line), reverse=True)

        if idx >= 0:
            set_cursor_pos(idx, curr_y, g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK))
            try:
                N10X.Editor.CenterViewAtLinePos(curr_y)
            except:
                pass
            set_status(f"/{pattern}" if direction == 1 else f"?{pattern}")
            return True

    set_status(f"Pattern not found: {pattern}")
    return False

def search_word_under_cursor(direction=1):
    word = get_word_at_cursor()
    if word:
        # Search for whole word by adding word boundaries
        # Use \b for word boundary in regex-style search
        pattern = r'\b' + word + r'\b'
        # For simple search, just use the word itself but check boundaries manually
        do_search(word, direction, whole_word=True)

def search_next():
    do_search(g_last_search, g_last_search_direction)

def search_prev():
    do_search(g_last_search, -g_last_search_direction)

# =============================================================================
# Commands
# =============================================================================

def execute_command(cmd):
    global g_command_history

    if cmd.startswith(':'):
        cmd = cmd[1:]

    cmd = cmd.strip()
    if not cmd:
        return

    # Add to history
    if cmd and (not g_command_history or g_command_history[-1] != cmd):
        g_command_history.append(cmd)
        if len(g_command_history) > 100:
            g_command_history = g_command_history[-100:]

    # Try user handler first
    result = VimUser.UserHandleCommandline(":" + cmd)
    if result == UserHandledResult.HANDLED:
        return
    elif result == UserHandledResult.PASS_TO_10X:
        try:
            N10X.Editor.ExecuteCommand(cmd)
        except:
            pass
        return

    # Parse command
    parts = cmd.split(None, 1)
    command = parts[0] if parts else ""
    args = parts[1] if len(parts) > 1 else ""

    # Handle line number
    if command.isdigit():
        line_num = int(command)
        set_cursor_pos(0, line_num - 1)
        motion_caret()
        return

    # Handle range commands (e.g., :1,10d)
    if ',' in command:
        range_match = command.split(',')
        if len(range_match) == 2:
            try:
                start = int(range_match[0])
                end_part = range_match[1]
                # Extract command from end
                end_num = ""
                cmd_char = ""
                for i, c in enumerate(end_part):
                    if c.isdigit():
                        end_num += c
                    else:
                        cmd_char = end_part[i:]
                        break
                if end_num and cmd_char:
                    end = int(end_num)
                    # Execute command on range
                    if cmd_char == 'd':
                        N10X.Editor.PushUndoGroup()
                        for _ in range(end - start + 1):
                            set_cursor_pos(0, start - 1)
                            operator_dd(1)
                        N10X.Editor.PopUndoGroup()
                        return
            except:
                pass

    # Standard commands
    if command == 'w':
        if args:
            # Save as - not directly supported, just save current
            set_status(f"Save as not supported, saving current file")
        N10X.Editor.SaveFile()
        set_status("File saved")

    elif command == 'wa':
        N10X.Editor.SaveAll()
        set_status("All files saved")

    elif command == 'q':
        if N10X.Editor.IsModified():
            set_status("No write since last change (use :q! to override)")
        else:
            N10X.Editor.CloseFile()

    elif command == 'q!':
        N10X.Editor.DiscardUnsavedChanges()
        N10X.Editor.CloseFile()

    elif command == 'wq' or command == 'x':
        N10X.Editor.SaveFile()
        N10X.Editor.CloseFile()

    elif command == 'qa':
        # Check if any files are modified
        try:
            open_files = N10X.Editor.GetOpenFiles()
            has_modified = False
            for f in open_files:
                N10X.Editor.FocusFile(f)
                if N10X.Editor.IsModified():
                    has_modified = True
                    break
            if has_modified:
                set_status("No write since last change (use :qa! to override)")
                return
        except:
            pass
        N10X.Editor.Exit(False)

    elif command == 'qa!':
        N10X.Editor.DiscardAllUnsavedChanges()
        N10X.Editor.Exit(True)

    elif command == 'e':
        if args:
            N10X.Editor.OpenFile(args)
        else:
            N10X.Editor.CheckForModifiedFiles()

    elif command == 'sp' or command == 'split':
        # Horizontal split - increase row count
        try:
            cols = N10X.Editor.GetColumnCount()
            N10X.Editor.SetColumnCount(cols + 1)
        except:
            pass

    elif command == 'vs' or command == 'vsplit':
        # Vertical split
        try:
            cols = N10X.Editor.GetColumnCount()
            N10X.Editor.SetColumnCount(cols + 1)
        except:
            pass

    elif command == 'bn' or command == 'bnext':
        try:
            files = N10X.Editor.GetOpenFiles()
            current = N10X.Editor.GetCurrentFilename()
            if files and current in files:
                idx = files.index(current)
                next_idx = (idx + 1) % len(files)
                N10X.Editor.FocusFile(files[next_idx])
        except:
            pass

    elif command == 'bp' or command == 'bprev':
        try:
            files = N10X.Editor.GetOpenFiles()
            current = N10X.Editor.GetCurrentFilename()
            if files and current in files:
                idx = files.index(current)
                prev_idx = (idx - 1) % len(files)
                N10X.Editor.FocusFile(files[prev_idx])
        except:
            pass

    elif command == 'bd' or command == 'bdelete':
        N10X.Editor.CloseFile()

    elif command == 'noh' or command == 'nohlsearch':
        set_status("")

    elif command == 'set':
        if args:
            if '=' in args:
                name, value = args.split('=', 1)
                try:
                    N10X.Editor.SetSetting(name.strip(), value.strip())
                except:
                    pass
            elif args.startswith('no'):
                try:
                    N10X.Editor.SetSetting(args[2:], "false")
                except:
                    pass
            else:
                try:
                    val = N10X.Editor.GetSetting(args)
                    set_status(f"{args}={val}")
                except:
                    pass

    elif command == 'reg' or command == 'registers':
        reg_info = []
        for r, v in g_registers.items():
            if v:
                preview = v[:30].replace('\n', '^J')
                reg_info.append(f'"{r}: {preview}')
        set_status(" | ".join(reg_info) if reg_info else "Registers empty")

    elif command == 'marks':
        mark_info = []
        for m, (f, pos) in g_marks.items():
            mark_info.append(f"'{m}: {pos[1]+1}:{pos[0]}")
        set_status(" | ".join(mark_info) if mark_info else "No marks")

    elif command == '%':
        # Select all and apply next command
        pass

    elif command.startswith('s/') or command.startswith('%s/'):
        # Substitute command
        import re
        is_global_file = command.startswith('%')
        if is_global_file:
            cmd = command[1:]

        parts = cmd.split('/')
        if len(parts) >= 3:
            pattern = parts[1]
            replacement = parts[2]
            flags = parts[3] if len(parts) > 3 else ""

            replace_all = 'g' in flags
            case_insensitive = 'i' in flags

            N10X.Editor.PushUndoGroup()
            count_replaced = 0

            re_flags = re.IGNORECASE if case_insensitive else 0
            try:
                regex = re.compile(pattern, re_flags)
            except re.error:
                # Fall back to literal string replacement
                regex = None

            def do_replace(line):
                nonlocal count_replaced
                if regex:
                    if replace_all:
                        new_line, n = regex.subn(replacement, line)
                    else:
                        new_line, n = regex.subn(replacement, line, count=1)
                    count_replaced += n
                    return new_line
                else:
                    if case_insensitive:
                        # Manual case-insensitive replace
                        import re as re2
                        escaped = re2.escape(pattern)
                        if replace_all:
                            new_line, n = re2.subn(escaped, replacement, line, flags=re2.IGNORECASE)
                        else:
                            new_line, n = re2.subn(escaped, replacement, line, count=1, flags=re2.IGNORECASE)
                        count_replaced += n
                        return new_line
                    else:
                        old_line = line
                        if replace_all:
                            new_line = line.replace(pattern, replacement)
                        else:
                            new_line = line.replace(pattern, replacement, 1)
                        if new_line != old_line:
                            count_replaced += 1
                        return new_line

            if is_global_file:
                for line_y in range(get_line_count()):
                    line = get_line(line_y)
                    new_line = do_replace(line)
                    if new_line != line:
                        N10X.Editor.SetLine(line_y, new_line)
            else:
                x, y = get_cursor_pos()
                line = get_line(y)
                new_line = do_replace(line)
                if new_line != line:
                    N10X.Editor.SetLine(y, new_line)

            N10X.Editor.PopUndoGroup()
            set_status(f"Substituted {count_replaced} occurrence(s)")

    elif command == 'make' or command == 'build':
        try:
            N10X.Editor.ExecuteCommand("Build.Build")
        except:
            pass

    elif command == 'cn' or command == 'cnext':
        try:
            N10X.Editor.ExecuteCommand("Build.NextError")
        except:
            pass

    elif command == 'cp' or command == 'cprev':
        try:
            N10X.Editor.ExecuteCommand("Build.PrevError")
        except:
            pass

    elif command == 'copen':
        try:
            N10X.Editor.ShowBuildOutput()
        except:
            pass

    elif command == 'cclose':
        # No direct way to close build panel
        pass

    elif command == 'only':
        try:
            N10X.Editor.SetColumnCount(1)
        except:
            pass

    elif command == 'tabnew':
        if args:
            N10X.Editor.OpenFile(args)

    elif command == 'tabn' or command == 'tabnext':
        try:
            N10X.Editor.ExecuteCommand("Tab.NextTab")
        except:
            pass

    elif command == 'tabp' or command == 'tabprev':
        try:
            N10X.Editor.ExecuteCommand("Tab.PrevTab")
        except:
            pass

    elif command == 'help':
        set_status("Vim mode - :w save, :q quit, :wq save+quit, :e file, /search, ?search")

    else:
        # Try as 10x command
        try:
            N10X.Editor.ExecuteCommand(command)
        except:
            set_status(f"Unknown command: {command}")

# =============================================================================
# Visual Mode
# =============================================================================

def update_visual_selection():
    if g_mode not in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK):
        return

    start = g_visual_start
    end = get_cursor_pos()

    if g_mode == Mode.VISUAL_LINE:
        if start[1] <= end[1]:
            start = (0, start[1])
            end_line = get_line(end[1])
            end = (len(end_line), end[1])
        else:
            start_line = get_line(start[1])
            start = (len(start_line), start[1])
            end = (0, end[1])

    elif g_mode == Mode.VISUAL_BLOCK:
        try:
            N10X.Editor.SetCursorRectSelect(start, end)
            return
        except:
            pass

    set_selection(start, end)

def visual_operation(op):
    if g_mode not in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK):
        return

    start = g_visual_start
    end = get_cursor_pos()

    # Ensure start < end
    if start[1] > end[1] or (start[1] == end[1] and start[0] > end[0]):
        start, end = end, start

    linewise = g_mode == Mode.VISUAL_LINE

    if linewise:
        start = (0, start[1])
        end_line = get_line(end[1])
        end = (len(end_line), end[1])
    else:
        # Include character under cursor
        end = (end[0] + 1, end[1])

    apply_operator_to_range(op, start, end, linewise)
    enter_normal_mode()

# =============================================================================
# Normal Mode Key Handler
# =============================================================================

def handle_normal_mode_key(key):
    global g_count, g_operator, g_pending_motion, g_current_register
    global g_recording_macro, g_macro_keys, g_macros

    # Use lowercase for comparisons, detect shift from uppercase char or key.shift
    char = key.key.lower() if len(key.key) == 1 else key.key
    is_shifted = key.shift

    N10X.Editor.LogTo10XOutput(f"DEBUG handle_normal_mode_key: char='{char}' is_shifted={is_shifted} g_operator='{g_operator}' g_pending_motion='{g_pending_motion}'\n")

    # Recording macros
    if g_recording_macro and char != 'q':
        g_macro_keys.append(key)

    # Try user handler first
    result = VimUser.UserHandleCommandModeKey(key)
    if result == UserHandledResult.HANDLED:
        return True
    elif result == UserHandledResult.PASS_TO_10X:
        return False

    count = int(g_count) if g_count else 1

    # Handle pending motion for operators
    if g_pending_motion:
        if g_pending_motion in ('f', 'F', 't', 'T'):
            if len(char) == 1:
                if g_pending_motion == 'f':
                    motion_f(char, count)
                elif g_pending_motion == 'F':
                    motion_F(char, count)
                elif g_pending_motion == 't':
                    motion_t(char, count)
                elif g_pending_motion == 'T':
                    motion_T(char, count)
                g_pending_motion = ""
                if g_operator:
                    start = g_visual_start if g_mode in (Mode.VISUAL, Mode.VISUAL_LINE) else get_cursor_pos()
                    # Motion already moved cursor
                return True

        elif g_pending_motion == 'g':
            if char == 'g':
                motion_gg(count if g_count else None)
            elif char == 'e':
                if is_shifted:
                    motion_gE(count)
                else:
                    motion_ge(count)
            elif char == 'v':
                # Reselect last visual selection
                if g_last_visual_start != g_last_visual_end or g_last_visual_mode:
                    g_mode = g_last_visual_mode
                    g_visual_start = g_last_visual_start
                    set_cursor_pos(g_last_visual_end[0], g_last_visual_end[1])
                    update_visual_selection()
                    set_cursor_style()
                    update_status()
            elif char == 'i':
                # Go to last insert position and enter insert mode
                set_cursor_pos(g_insert_start_pos[0], g_insert_start_pos[1])
                enter_insert_mode()
            elif char == 'j' and is_shifted:
                # Join lines without spaces (gJ)
                x, y = get_cursor_pos()
                for _ in range(count):
                    line = get_line(y)
                    next_line = get_line(y + 1) if y < get_line_count() - 1 else ""
                    if next_line:
                        N10X.Editor.SetLine(y, line.rstrip('\n\r') + next_line.lstrip())
                        N10X.Editor.SetCursorPos((0, y + 1), 0)
                        operator_dd(1)
                        set_cursor_pos(len(line.rstrip('\n\r')), y)
            elif char == 'u' and is_shifted:
                # gU - uppercase operator
                g_operator = 'gU'
                g_pending_motion = ""
                return True
            elif char == 'u' and not is_shifted:
                # gu - lowercase operator
                g_operator = 'gu'
                g_pending_motion = ""
                return True
            elif char == 'd':
                # Go to definition
                try:
                    N10X.Editor.ExecuteCommand("Editor.GoToDefinition")
                except:
                    pass
            elif char == 'f' and is_shifted:
                # Go to file under cursor (gF)
                try:
                    N10X.Editor.ExecuteCommand("Editor.GoToFile")
                except:
                    pass
            g_pending_motion = ""
            return True

        elif g_pending_motion == 'r':
            # Replace character
            if len(char) == 1:
                x, y = get_cursor_pos()
                line = get_line(y)
                if x < len(line.rstrip('\n\r')):
                    new_line = line[:x] + char + line[x+1:]
                    N10X.Editor.SetLine(y, new_line)
            g_pending_motion = ""
            return True

        elif g_pending_motion == "'":
            # Jump to mark
            if char in g_marks:
                filename, pos = g_marks[char]
                current_file = N10X.Editor.GetCurrentFilename()
                if filename != current_file:
                    N10X.Editor.OpenFile(filename)
                push_jump()
                set_cursor_pos(pos[0], pos[1])
                motion_caret()
            g_pending_motion = ""
            return True

        elif g_pending_motion == '`':
            # Jump to mark (exact position)
            if char in g_marks:
                filename, pos = g_marks[char]
                current_file = N10X.Editor.GetCurrentFilename()
                if filename != current_file:
                    N10X.Editor.OpenFile(filename)
                push_jump()
                set_cursor_pos(pos[0], pos[1])
            g_pending_motion = ""
            return True

        elif g_pending_motion == 'm':
            # Set mark
            if char.isalpha():
                filename = N10X.Editor.GetCurrentFilename()
                g_marks[char] = (filename, get_cursor_pos())
                set_status(f"Mark '{char}' set")
            g_pending_motion = ""
            return True

        elif g_pending_motion == '"':
            # Select register
            g_current_register = char
            g_pending_motion = ""
            return True

        elif g_pending_motion == 'z':
            x, y = get_cursor_pos()
            if char == 'z':
                N10X.Editor.CenterViewAtLinePos(y)
            elif char == 't':
                N10X.Editor.SetScrollLine(y)
            elif char == 'b':
                visible = N10X.Editor.GetVisibleLineCount()
                N10X.Editor.SetScrollLine(max(0, y - visible + 1))
            g_pending_motion = ""
            return True

        elif g_pending_motion == '@':
            # Execute macro
            if char in g_macros:
                for k in g_macros[char]:
                    handle_normal_mode_key(k)
            g_pending_motion = ""
            return True

        elif g_pending_motion in ('d', 'c', 'y', '>', '<', 'gu', 'gU'):
            # Text object or motion
            N10X.Editor.LogTo10XOutput(f"DEBUG: In operator pending motion, char='{char}', g_operator='{g_operator}'\n")
            inner = False
            obj = None

            if char == 'i':
                g_pending_motion = g_operator + 'i'
                return True
            elif char == 'a':
                g_pending_motion = g_operator + 'a'
                return True
            elif char in 'web':
                # Word motion
                N10X.Editor.LogTo10XOutput(f"DEBUG: Word motion '{char}' with operator '{g_operator}'\n")
                start = get_cursor_pos()
                if char == 'w':
                    # Special case: cw behaves like ce in Vim (doesn't include trailing whitespace)
                    if g_operator == 'c':
                        if is_shifted:
                            motion_E(count)
                        else:
                            motion_e(count)
                    else:
                        if is_shifted:
                            motion_W(count)
                        else:
                            motion_w(count)
                elif char == 'e':
                    if is_shifted:
                        motion_E(count)
                    else:
                        motion_e(count)
                elif char == 'b':
                    if is_shifted:
                        motion_B(count)
                    else:
                        motion_b(count)
                end = get_cursor_pos()
                # For 'e' motion and 'cw' (which uses 'e'), include the character under cursor
                if char == 'e' or (char == 'w' and g_operator == 'c'):
                    end = (end[0] + 1, end[1])
                apply_operator_to_range(g_operator, start, end, False)
                g_operator = ""
                g_pending_motion = ""
                g_count = ""
                return True
            elif char == '$':
                start = get_cursor_pos()
                motion_dollar(count)
                end = get_cursor_pos()
                apply_operator_to_range(g_operator, start, (end[0] + 1, end[1]), False)
                g_operator = ""
                g_pending_motion = ""
                g_count = ""
                return True
            elif char == '0':
                start = get_cursor_pos()
                motion_0()
                end = get_cursor_pos()
                apply_operator_to_range(g_operator, end, start, False)
                g_operator = ""
                g_pending_motion = ""
                g_count = ""
                return True
            elif char == '^':
                start = get_cursor_pos()
                motion_caret()
                end = get_cursor_pos()
                apply_operator_to_range(g_operator, end, start, False)
                g_operator = ""
                g_pending_motion = ""
                g_count = ""
                return True
            elif char == 'g' and is_shifted:
                start = get_cursor_pos()
                motion_G(int(g_count) if g_count else None)
                end = get_cursor_pos()
                apply_operator_to_range(g_operator, start, (len(get_line(end[1])), end[1]), True)
                g_operator = ""
                g_pending_motion = ""
                g_count = ""
                return True
            elif char == 'g' and not is_shifted:
                g_pending_motion = g_operator + 'g'
                return True
            elif char in 'hjkl':
                start = get_cursor_pos()
                if char == 'h':
                    motion_h(count)
                elif char == 'j':
                    motion_j(count)
                elif char == 'k':
                    motion_k(count)
                elif char == 'l':
                    motion_l(count)
                end = get_cursor_pos()
                linewise = char in 'jk'
                if char == 'l':
                    end = (end[0] + 1, end[1])
                apply_operator_to_range(g_operator, start, end, linewise)
                g_operator = ""
                g_pending_motion = ""
                g_count = ""
                return True
            elif char == 'f':
                if is_shifted:
                    g_pending_motion = g_operator + 'F'
                else:
                    g_pending_motion = g_operator + 'f'
                return True
            elif char == 't':
                if is_shifted:
                    g_pending_motion = g_operator + 'T'
                else:
                    g_pending_motion = g_operator + 't'
                return True
            elif char == g_operator[-1]:  # dd, cc, yy, >>, <<
                if g_operator == 'd':
                    operator_dd(count)
                elif g_operator == 'c':
                    operator_cc(count)
                elif g_operator == 'y':
                    operator_yy(count)
                elif g_operator == '>':
                    x, y = get_cursor_pos()
                    apply_operator_to_range('>', (0, y), (0, y + count - 1), True)
                elif g_operator == '<':
                    x, y = get_cursor_pos()
                    apply_operator_to_range('<', (0, y), (0, y + count - 1), True)
                g_operator = ""
                g_pending_motion = ""
                g_count = ""
                return True
            g_pending_motion = ""
            return True

        elif g_pending_motion.endswith('i') or g_pending_motion.endswith('a'):
            # Text object
            inner = g_pending_motion.endswith('i')
            op = g_pending_motion[:-1]
            obj_range = get_text_object_range(char, inner)
            if obj_range:
                apply_operator_to_range(op, obj_range[0], obj_range[1], False)
            g_operator = ""
            g_pending_motion = ""
            g_count = ""
            return True

        elif g_pending_motion.endswith('g'):
            # gg motion in operator
            op = g_pending_motion[:-1]
            if char == 'g':
                start = get_cursor_pos()
                target = int(g_count) - 1 if g_count else 0
                apply_operator_to_range(op, (0, target), (0, start[1]), True)
            g_operator = ""
            g_pending_motion = ""
            g_count = ""
            return True

        elif g_pending_motion.endswith('f'):
            # f motion in operator
            op = g_pending_motion[:-1]
            start = get_cursor_pos()
            motion_f(char, count)
            end = get_cursor_pos()
            apply_operator_to_range(op, start, (end[0] + 1, end[1]), False)
            g_operator = ""
            g_pending_motion = ""
            g_count = ""
            return True

        elif g_pending_motion.endswith('F'):
            op = g_pending_motion[:-1]
            start = get_cursor_pos()
            motion_F(char, count)
            end = get_cursor_pos()
            apply_operator_to_range(op, end, start, False)
            g_operator = ""
            g_pending_motion = ""
            g_count = ""
            return True

        elif g_pending_motion.endswith('t'):
            op = g_pending_motion[:-1]
            start = get_cursor_pos()
            motion_t(char, count)
            end = get_cursor_pos()
            apply_operator_to_range(op, start, (end[0] + 1, end[1]), False)
            g_operator = ""
            g_pending_motion = ""
            g_count = ""
            return True

        elif g_pending_motion.endswith('T'):
            op = g_pending_motion[:-1]
            start = get_cursor_pos()
            motion_T(char, count)
            end = get_cursor_pos()
            apply_operator_to_range(op, end, start, False)
            g_operator = ""
            g_pending_motion = ""
            g_count = ""
            return True

    # Count prefix
    if char.isdigit() and (g_count or char != '0'):
        g_count += char
        update_status()
        return True

    # Operators (shifted versions are shortcuts)
    if char == 'd':
        N10X.Editor.LogTo10XOutput(f"DEBUG: 'd' pressed, is_shifted={is_shifted}, g_operator={g_operator}, g_pending_motion={g_pending_motion}\n")
        if is_shifted:
            # D = delete to end of line (d$)
            start = get_cursor_pos()
            motion_dollar(1)
            end = get_cursor_pos()
            apply_operator_to_range('d', start, (end[0] + 1, end[1]), False)
        else:
            g_operator = char
            g_pending_motion = char
            N10X.Editor.LogTo10XOutput(f"DEBUG: Set g_operator={g_operator}, g_pending_motion={g_pending_motion}\n")
            update_status()
        return True

    if char == 'c':
        if is_shifted:
            # C = change to end of line (c$)
            start = get_cursor_pos()
            motion_dollar(1)
            end = get_cursor_pos()
            apply_operator_to_range('c', start, (end[0] + 1, end[1]), False)
            # Note: apply_operator_to_range('c',...) already enters insert mode
        else:
            g_operator = char
            g_pending_motion = char
            update_status()
        return True

    if char == 'y':
        if is_shifted:
            # Y = yank line (like yy)
            operator_yy(count)
        else:
            g_operator = char
            g_pending_motion = char
            update_status()
        return True

    if char == '>' or char == '<':
        g_operator = char
        g_pending_motion = char
        update_status()
        return True

    # Simple motions
    if char == 'h':
        if is_shifted:
            motion_H()
        else:
            motion_h(count)
        return True

    if char == 'j':
        if is_shifted:
            # Join lines
            x, y = get_cursor_pos()
            N10X.Editor.PushUndoGroup()
            for _ in range(count):
                line = get_line(y)
                next_line = get_line(y + 1) if y < get_line_count() - 1 else ""
                if next_line:
                    new_line = line.rstrip('\n\r') + ' ' + next_line.lstrip()
                    N10X.Editor.SetLine(y, new_line)
                    set_cursor_pos(0, y + 1)
                    operator_dd(1)
                    set_cursor_pos(len(line.rstrip('\n\r')), y)
            N10X.Editor.PopUndoGroup()
        else:
            motion_j(count)
        return True

    if char == 'k':
        if is_shifted:
            motion_k(count)
        else:
            motion_k(count)
        return True

    if char == 'l':
        if is_shifted:
            motion_L()
        else:
            motion_l(count)
        return True

    if char == 'm':
        if is_shifted:
            motion_M()
        else:
            g_pending_motion = 'm'
        return True

    if char == 'w':
        if is_shifted:
            motion_W(count)
        else:
            motion_w(count)
        return True

    if char == 'b':
        if is_shifted:
            motion_B(count)
        else:
            motion_b(count)
        return True

    if char == 'e':
        if is_shifted:
            motion_E(count)
        else:
            motion_e(count)
        return True

    if char == '0':
        motion_0()
        g_count = ""
        return True

    if char == '^':
        motion_caret()
        return True

    if char == '$':
        motion_dollar(count)
        return True

    if char == 'g':
        if is_shifted:
            motion_G(int(g_count) if g_count else None)
            g_count = ""
        else:
            g_pending_motion = 'g'
        return True

    if char == '%':
        motion_percent()
        return True

    if char == '{':
        push_jump()
        motion_brace_backward(count)
        return True

    if char == '}':
        push_jump()
        motion_brace_forward(count)
        return True

    if char == 'f':
        if is_shifted:
            g_pending_motion = 'F'
        else:
            g_pending_motion = 'f'
        return True

    if char == 't':
        if is_shifted:
            g_pending_motion = 'T'
        else:
            g_pending_motion = 't'
        return True

    if char == ';':
        motion_semicolon(count)
        return True

    if char == ',':
        motion_comma(count)
        return True

    # Mode changes
    if char == 'i':
        if is_shifted:
            motion_caret()
            enter_insert_mode()
        else:
            enter_insert_mode()
        return True

    if char == 'a':
        if is_shifted:
            motion_dollar(1)
            x, y = get_cursor_pos()
            set_cursor_pos(x + 1, y)
            enter_insert_mode()
        else:
            x, y = get_cursor_pos()
            line = get_line(y)
            if x < len(line.rstrip('\n\r')):
                set_cursor_pos(x + 1, y)
            enter_insert_mode()
        return True

    if char == 'o':
        x, y = get_cursor_pos()
        if is_shifted:
            line = get_line(y)
            indent = ""
            for c in line:
                if c in ' \t':
                    indent += c
                else:
                    break
            N10X.Editor.SetLine(y, indent + '\n' + line)
            set_cursor_pos(len(indent), y)
            enter_insert_mode()
        else:
            line = get_line(y)
            indent = ""
            for c in line:
                if c in ' \t':
                    indent += c
                else:
                    break
            next_line = get_line(y + 1) if y < get_line_count() - 1 else ""
            N10X.Editor.SetLine(y, line.rstrip('\n\r') + '\n' + indent)
            set_cursor_pos(len(indent), y + 1)
            enter_insert_mode()
        return True

    if char == 'v':
        if is_shifted:
            enter_visual_line_mode()
        else:
            enter_visual_mode()
        return True

    if key.control and char == 'v':
        enter_visual_block_mode()
        return True

    if char == ':':
        if g_use_10x_command_panel:
            try:
                N10X.Editor.ExecuteCommand("CommandPanel.Show")
            except:
                enter_command_line_mode(':')
        else:
            enter_command_line_mode(':')
        return True

    if char == '/':
        if g_use_10x_find_panel:
            try:
                N10X.Editor.ExecuteCommand("Find.ShowFind")
            except:
                enter_command_line_mode('/')
        else:
            enter_command_line_mode('/')
        return True

    if char == '?':
        enter_command_line_mode('?')
        return True

    # Editing commands
    if char == 'x':
        if is_shifted:
            # Delete char before cursor
            x, y = get_cursor_pos()
            if x > 0:
                line = get_line(y)
                deleted = line[x-1]
                N10X.Editor.SetLine(y, line[:x-1] + line[x:])
                yank_to_register(deleted)
                set_cursor_pos(x - 1, y)
        else:
            # Delete char under cursor
            x, y = get_cursor_pos()
            line = get_line(y)
            if x < len(line.rstrip('\n\r')):
                deleted = line[x]
                N10X.Editor.SetLine(y, line[:x] + line[x+1:])
                yank_to_register(deleted)
        return True

    if char == 'r':
        if is_shifted:
            enter_mode(Mode.REPLACE)
        else:
            g_pending_motion = 'r'
        return True

    if char == 's':
        global g_suppress_next_char, g_change_undo_group
        if is_shifted:
            # Change entire line
            operator_cc(count)
        else:
            # Substitute character - delete and enter insert mode
            x, y = get_cursor_pos()
            line = get_line(y)
            N10X.Editor.PushUndoGroup()
            g_change_undo_group = True
            if x < len(line.rstrip('\n\r')):
                deleted = line[x:x+count]
                N10X.Editor.SetLine(y, line[:x] + line[x+count:])
                yank_to_register(deleted)
            g_suppress_next_char = True
            enter_insert_mode()
        return True

    if char == 'p':
        # Paste
        text = get_register()
        if text:
            x, y = get_cursor_pos()
            if is_shifted:
                # Paste before
                if text.endswith('\n'):
                    # Linewise paste
                    line = get_line(y)
                    N10X.Editor.SetLine(y, text + line)
                    motion_caret()
                else:
                    insert_text(text)
            else:
                # Paste after
                if text.endswith('\n'):
                    # Linewise paste
                    line = get_line(y)
                    N10X.Editor.SetLine(y, line.rstrip('\n\r') + '\n' + text)
                    set_cursor_pos(0, y + 1)
                    motion_caret()
                else:
                    line = get_line(y)
                    line_len = len(line.rstrip('\n\r'))
                    if x < line_len:
                        set_cursor_pos(x + 1, y)
                    insert_text(text)
        return True

    # Undo/Redo
    if char == 'u':
        if is_shifted:
            # Undo line (just undo for now)
            N10X.Editor.Undo()
        else:
            N10X.Editor.Undo()
        clear_selection()
        return True

    if key.control and char == 'r':
        N10X.Editor.Redo()
        clear_selection()
        return True

    # Search
    if char == 'n':
        if is_shifted:
            search_prev()
        else:
            search_next()
        return True

    if char == '*':
        search_word_under_cursor(1)
        return True

    if char == '#':
        search_word_under_cursor(-1)
        return True

    # Marks
    if char == "'":
        g_pending_motion = "'"
        return True

    if char == '`':
        g_pending_motion = '`'
        return True

    # Registers
    if char == '"':
        g_pending_motion = '"'
        return True

    # Repeat
    if char == '.':
        if g_last_edit:
            op, text, linewise = g_last_edit
            if op == 'd':
                operator_dd(count) if linewise else None
            elif op == 'c':
                operator_cc(count) if linewise else None
        return True

    # Macros
    if char == 'q':
        if g_recording_macro:
            g_macros[g_recording_macro] = g_macro_keys[:-1]  # Exclude the q that stopped
            set_status(f"Recorded macro @{g_recording_macro}")
            g_recording_macro = ""
            g_macro_keys = []
        else:
            g_pending_motion = 'q_start'
        return True

    if g_pending_motion == 'q_start':
        if char.isalpha():
            g_recording_macro = char
            g_macro_keys = []
            set_status(f"Recording @{char}...")
        g_pending_motion = ""
        return True

    if char == '@':
        g_pending_motion = '@'
        return True

    # Scroll
    if key.control and char == 'd':
        try:
            visible = N10X.Editor.GetVisibleLineCount()
            x, y = get_cursor_pos()
            motion_j(visible // 2)
            N10X.Editor.ScrollCursorIntoView()
        except:
            pass
        return True

    if key.control and char == 'u':
        try:
            visible = N10X.Editor.GetVisibleLineCount()
            motion_k(visible // 2)
            N10X.Editor.ScrollCursorIntoView()
        except:
            pass
        return True

    if key.control and char == 'f':
        try:
            visible = N10X.Editor.GetVisibleLineCount()
            motion_j(visible)
            N10X.Editor.ScrollCursorIntoView()
        except:
            pass
        return True

    if key.control and char == 'b':
        try:
            visible = N10X.Editor.GetVisibleLineCount()
            motion_k(visible)
            N10X.Editor.ScrollCursorIntoView()
        except:
            pass
        return True

    if key.control and char == 'e':
        try:
            scroll = N10X.Editor.GetScrollLine()
            N10X.Editor.SetScrollLine(scroll + count)
        except:
            pass
        return True

    if key.control and char == 'a':
        # Increment number under cursor
        _change_number_under_cursor(count)
        return True

    if key.control and char == 'x':
        # Decrement number under cursor
        _change_number_under_cursor(-count)
        return True

    if key.control and char == 'y':
        try:
            scroll = N10X.Editor.GetScrollLine()
            N10X.Editor.SetScrollLine(max(0, scroll - count))
        except:
            pass
        return True

    # Window commands
    if key.control and char == 'w':
        # Window prefix - for now just pass to 10x
        return False

    # Jump list
    if key.control and char == 'o':
        if g_jump_index > 0:
            g_jump_index -= 1
            filename, pos = g_jump_list[g_jump_index]
            current_file = N10X.Editor.GetCurrentFilename()
            if filename != current_file:
                N10X.Editor.OpenFile(filename)
            set_cursor_pos(pos[0], pos[1])
        return True

    if key.control and char == 'i':
        if g_jump_index < len(g_jump_list) - 1:
            g_jump_index += 1
            filename, pos = g_jump_list[g_jump_index]
            current_file = N10X.Editor.GetCurrentFilename()
            if filename != current_file:
                N10X.Editor.OpenFile(filename)
            set_cursor_pos(pos[0], pos[1])
        return True

    # Misc
    if char == 'z':
        if is_shifted:
            # Z prefix for ZZ, ZQ
            g_pending_motion = 'Z'
        else:
            g_pending_motion = 'z'
        return True

    if g_pending_motion == 'Z':
        if char == 'z' and is_shifted:
            # ZZ - save and quit
            N10X.Editor.SaveFile()
            N10X.Editor.CloseFile()
        elif char == 'q' and is_shifted:
            # ZQ - quit without saving
            N10X.Editor.DiscardUnsavedChanges()
            N10X.Editor.CloseFile()
        g_pending_motion = ""
        return True

    if char == '~':
        # Toggle case
        x, y = get_cursor_pos()
        line = get_line(y)
        if x < len(line.rstrip('\n\r')):
            c = line[x]
            if c.isupper():
                new_c = c.lower()
            else:
                new_c = c.upper()
            N10X.Editor.SetLine(y, line[:x] + new_c + line[x+1:])
            set_cursor_pos(x + 1, y)
        return True

    g_count = ""
    return True

# =============================================================================
# Visual Mode Key Handler
# =============================================================================

def handle_visual_mode_key(key):
    global g_count, g_operator

    char = key.key.lower() if len(key.key) == 1 else key.key
    is_shifted = key.shift
    count = int(g_count) if g_count else 1

    # Escape to normal mode
    if char == 'Escape' or (key.control and char == '['):
        enter_normal_mode()
        return True

    # Count
    if char.isdigit() and (g_count or char != '0'):
        g_count += char
        return True

    # Motions (same as normal mode)
    if char == 'h':
        motion_h(count)
        update_visual_selection()
        g_count = ""
        return True

    if char == 'j':
        motion_j(count)
        update_visual_selection()
        g_count = ""
        return True

    if char == 'k':
        motion_k(count)
        update_visual_selection()
        g_count = ""
        return True

    if char == 'l':
        motion_l(count)
        update_visual_selection()
        g_count = ""
        return True

    if char == 'w':
        if is_shifted:
            motion_W(count)
        else:
            motion_w(count)
        update_visual_selection()
        g_count = ""
        return True

    if char == 'b':
        if is_shifted:
            motion_B(count)
        else:
            motion_b(count)
        update_visual_selection()
        g_count = ""
        return True

    if char == 'e':
        if is_shifted:
            motion_E(count)
        else:
            motion_e(count)
        update_visual_selection()
        g_count = ""
        return True

    if char == '0':
        motion_0()
        update_visual_selection()
        g_count = ""
        return True

    if char == '$':
        motion_dollar(count)
        update_visual_selection()
        g_count = ""
        return True

    if char == '^':
        motion_caret()
        update_visual_selection()
        return True

    if char == 'g':
        if is_shifted:
            motion_G(int(g_count) if g_count else None)
        else:
            motion_gg(int(g_count) if g_count else None)
        update_visual_selection()
        g_count = ""
        return True

    if char == '%':
        motion_percent()
        update_visual_selection()
        return True

    if char == '{':
        motion_brace_backward(count)
        update_visual_selection()
        g_count = ""
        return True

    if char == '}':
        motion_brace_forward(count)
        update_visual_selection()
        g_count = ""
        return True

    # Mode switches
    if char == 'v':
        if is_shifted:
            if g_mode == Mode.VISUAL_LINE:
                enter_normal_mode()
            else:
                g_mode = Mode.VISUAL_LINE
                update_visual_selection()
        else:
            if g_mode == Mode.VISUAL:
                enter_normal_mode()
            else:
                g_mode = Mode.VISUAL
                update_visual_selection()
        return True

    if key.control and char == 'v':
        if g_mode == Mode.VISUAL_BLOCK:
            enter_normal_mode()
        else:
            g_mode = Mode.VISUAL_BLOCK
            update_visual_selection()
        return True

    # Swap selection anchor
    if char == 'o':
        if not is_shifted:
            curr = get_cursor_pos()
            set_cursor_pos(g_visual_start[0], g_visual_start[1])
            g_visual_start = curr
            update_visual_selection()
        return True

    # Operations
    if char == 'd':
        visual_operation('d')
        return True

    if char == 'c':
        visual_operation('c')
        return True

    if char == 'y':
        visual_operation('y')
        return True

    if char == 'x':
        visual_operation('d')
        return True

    if char == '>':
        visual_operation('>')
        return True

    if char == '<':
        visual_operation('<')
        return True

    if char == 'u':
        if is_shifted:
            visual_operation('gU')
        else:
            visual_operation('gu')
        return True

    # Join
    if char == 'j' and is_shifted:
        start = g_visual_start
        end = get_cursor_pos()
        if start[1] > end[1]:
            start, end = end, start
        N10X.Editor.PushUndoGroup()
        for _ in range(end[1] - start[1]):
            set_cursor_pos(0, start[1])
            line = get_line(start[1])
            next_line = get_line(start[1] + 1)
            if next_line:
                new_line = line.rstrip('\n\r') + ' ' + next_line.lstrip()
                N10X.Editor.SetLine(start[1], new_line)
                set_cursor_pos(0, start[1] + 1)
                operator_dd(1)
        N10X.Editor.PopUndoGroup()
        enter_normal_mode()
        return True

    g_count = ""
    return True

# =============================================================================
# Insert Mode Key Handler
# =============================================================================

def handle_insert_mode_key(key):
    global g_exit_sequence, g_last_insert_text

    char = key.key

    # Try user handler first
    result = VimUser.UserHandleInsertModeKey(key)
    if result == UserHandledResult.HANDLED:
        return True
    elif result == UserHandledResult.PASS_TO_10X:
        return False

    # Escape
    if char == 'Escape' or (key.control and char == '['):
        enter_normal_mode()
        return True

    # Check exit sequence (e.g., "jk")
    if g_exit_sequence_chars and len(char) == 1:
        g_exit_sequence += char
        if g_exit_sequence == g_exit_sequence_chars:
            # Delete the typed characters and exit
            for _ in range(len(g_exit_sequence_chars) - 1):
                N10X.Editor.Undo()
            enter_normal_mode()
            return True
        elif not g_exit_sequence_chars.startswith(g_exit_sequence):
            g_exit_sequence = char if g_exit_sequence_chars.startswith(char) else ""

    # Ctrl+W - delete word
    if key.control and char == 'W':
        x, y = get_cursor_pos()
        line = get_line(y)
        if x > 0:
            start = x - 1
            while start > 0 and is_whitespace(line[start]):
                start -= 1
            while start > 0 and is_word_char(line[start - 1]):
                start -= 1
            N10X.Editor.SetLine(y, line[:start] + line[x:])
            set_cursor_pos(start, y)
        return True

    # Ctrl+U - delete to start of line
    if key.control and char == 'U':
        x, y = get_cursor_pos()
        line = get_line(y)
        N10X.Editor.SetLine(y, line[x:])
        set_cursor_pos(0, y)
        return True

    # Ctrl+H - backspace
    if key.control and char == 'H':
        return False  # Let 10x handle backspace

    # Ctrl+O - one normal mode command
    if key.control and char == 'O':
        # Not implemented - would need state tracking
        return True

    # Track inserted text for . repeat
    if len(char) == 1 and not key.control and not key.alt:
        g_last_insert_text += char

    return False  # Let 10x handle normal typing

# =============================================================================
# Replace Mode Key Handler
# =============================================================================

def handle_replace_mode_key(key):
    char = key.key

    if char == 'Escape' or (key.control and char == '['):
        enter_normal_mode()
        return True

    if len(char) == 1 and not key.control and not key.alt:
        x, y = get_cursor_pos()
        line = get_line(y)
        if x < len(line.rstrip('\n\r')):
            N10X.Editor.SetLine(y, line[:x] + char + line[x+1:])
            set_cursor_pos(x + 1, y)
        else:
            insert_text(char)
        return True

    return False

# =============================================================================
# Command Line Mode Key Handler
# =============================================================================

def handle_command_line_key(key):
    global g_command_line, g_command_history_index, g_search_history_index
    global g_search_history

    char = key.key

    if char == 'Escape' or (key.control and char == '['):
        enter_normal_mode()
        return True

    if char == 'Return' or char == 'Enter':
        if g_command_line_type == ':':
            execute_command(g_command_line)
        elif g_command_line_type == '/':
            if g_command_line and (not g_search_history or g_search_history[-1] != g_command_line):
                g_search_history.append(g_command_line)
            do_search(g_command_line, 1)
        elif g_command_line_type == '?':
            if g_command_line and (not g_search_history or g_search_history[-1] != g_command_line):
                g_search_history.append(g_command_line)
            do_search(g_command_line, -1)
        enter_normal_mode()
        return True

    if char == 'Backspace' or char == 'Back':
        if g_command_line:
            g_command_line = g_command_line[:-1]
            set_status(g_command_line_type + g_command_line)
        else:
            enter_normal_mode()
        return True

    if char == 'Up':
        # History navigation
        if g_command_line_type == ':':
            history = g_command_history
            idx = g_command_history_index
            if history and idx < len(history) - 1:
                idx += 1
                # Filter if enabled
                if g_filtered_history and g_command_line:
                    while idx < len(history) and not history[-(idx+1)].startswith(g_command_line):
                        idx += 1
                if idx < len(history):
                    g_command_history_index = idx
                    g_command_line = history[-(idx+1)]
                    set_status(g_command_line_type + g_command_line)
        else:
            history = g_search_history
            idx = g_search_history_index
            if history and idx < len(history) - 1:
                idx += 1
                g_search_history_index = idx
                g_command_line = history[-(idx+1)]
                set_status(g_command_line_type + g_command_line)
        return True

    if char == 'Down':
        if g_command_line_type == ':':
            if g_command_history_index > 0:
                g_command_history_index -= 1
                g_command_line = g_command_history[-(g_command_history_index+1)]
                set_status(g_command_line_type + g_command_line)
            elif g_command_history_index == 0:
                g_command_history_index = -1
                g_command_line = ""
                set_status(g_command_line_type)
        else:
            if g_search_history_index > 0:
                g_search_history_index -= 1
                g_command_line = g_search_history[-(g_search_history_index+1)]
                set_status(g_command_line_type + g_command_line)
            elif g_search_history_index == 0:
                g_search_history_index = -1
                g_command_line = ""
                set_status(g_command_line_type)
        return True

    # Ctrl+W - delete word
    if key.control and char == 'W':
        words = g_command_line.rsplit(None, 1)
        g_command_line = words[0] if len(words) > 1 else ""
        set_status(g_command_line_type + g_command_line)
        return True

    # Ctrl+U - clear line
    if key.control and char == 'U':
        g_command_line = ""
        set_status(g_command_line_type)
        return True

    # Regular character input - char already has correct case from on_char_key
    if len(char) == 1 and not key.control and not key.alt:
        g_command_line += char
        set_status(g_command_line_type + g_command_line)
        return True

    return True

# =============================================================================
# Main Key Handler
# =============================================================================

def on_key(key_str, shift, control, alt):
    if not is_vim_enabled():
        return False

    if not N10X.Editor.TextEditorHasFocus():
        return False

    if g_debug:
        N10X.Editor.LogTo10XOutput(f"on_key: '{key_str}' shift={shift} ctrl={control} alt={alt}\n")

    # Escape always returns to normal mode
    if key_str == 'Escape':
        enter_normal_mode()
        return True

    # In insert mode, only handle Escape and Ctrl combinations
    if g_mode == Mode.INSERT:
        if control:
            key = Key(key_str, shift, control, alt)
            return handle_insert_mode_key(key)
        # Let on_char_key handle regular typing in insert mode
        return False

    # For non-insert modes, handle all keys here (we have shift info)
    key = Key(key_str, shift, control, alt)

    # Handle Enter/Return - move to next line first non-whitespace
    if key_str in ('Return', 'Enter'):
        if g_mode == Mode.NORMAL:
            x, y = get_cursor_pos()
            set_cursor_pos(0, y + 1)
            motion_caret()
            return True
        elif g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK):
            x, y = get_cursor_pos()
            set_cursor_pos(0, y + 1)
            motion_caret()
            update_visual_selection()
            return True

    if g_mode == Mode.NORMAL:
        return handle_normal_mode_key(key)
    elif g_mode == Mode.COMMAND_LINE:
        return handle_command_line_key(key)
    elif g_mode == Mode.REPLACE:
        return handle_replace_mode_key(key)
    elif g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK):
        return handle_visual_mode_key(key)

    return False

def on_char_key(char):
    global g_suppress_next_char

    if not is_vim_enabled():
        return False

    if not N10X.Editor.TextEditorHasFocus():
        return False

    if g_debug:
        N10X.Editor.LogTo10XOutput(f"on_char_key: '{char}'\n")

    # Suppress character if we just entered insert mode via an operator (e.g., cw)
    if g_suppress_next_char:
        g_suppress_next_char = False
        return True

    # In insert mode, let 10x handle typing
    if g_mode == Mode.INSERT:
        return False

    # For non-insert modes, on_key handles everything (it has shift info)
    # Return True here to prevent 10x from inserting characters
    # This is a fallback in case on_key didn't intercept the key
    return True

# =============================================================================
# Initialization
# =============================================================================

def is_vim_enabled():
    try:
        setting = N10X.Editor.GetSetting("Vim")
        return setting.lower() in ("true", "1", "yes")
    except:
        return False

def load_settings():
    global g_exit_sequence_chars, g_use_10x_command_panel, g_use_10x_find_panel
    global g_sneak_enabled, g_filtered_history, g_show_scope_name

    try:
        g_exit_sequence_chars = N10X.Editor.GetSetting("VimExitInsertModeCharSequence") or ""
    except:
        g_exit_sequence_chars = ""

    try:
        val = N10X.Editor.GetSetting("VimUse10xCommandPanel")
        g_use_10x_command_panel = val.lower() in ("true", "1", "yes")
    except:
        g_use_10x_command_panel = False

    try:
        val = N10X.Editor.GetSetting("VimUse10xFindPanel")
        g_use_10x_find_panel = val.lower() in ("true", "1", "yes")
    except:
        g_use_10x_find_panel = False

    try:
        val = N10X.Editor.GetSetting("VimSneakEnabled")
        g_sneak_enabled = val.lower() in ("true", "1", "yes")
    except:
        g_sneak_enabled = False

    try:
        val = N10X.Editor.GetSetting("VimCommandlineFilteredHistory")
        g_filtered_history = val.lower() not in ("false", "0", "no")
    except:
        g_filtered_history = True

    try:
        val = N10X.Editor.GetSetting("VimDisplayCurrentScopeName")
        g_show_scope_name = val.lower() in ("true", "1", "yes")
    except:
        g_show_scope_name = False

def on_settings_changed():
    load_settings()

def initialize():
    global g_initialized

    if g_initialized:
        return

    g_initialized = True
    load_settings()

    if is_vim_enabled():
        enter_normal_mode()

    # Remove any existing callbacks first (in case of script reload)
    try:
        N10X.Editor.RemoveOnInterceptKeyFunction(on_key)
    except:
        pass
    try:
        N10X.Editor.RemoveOnInterceptCharKeyFunction(on_char_key)
    except:
        pass
    try:
        N10X.Editor.RemoveOnSettingsChangedFunction(on_settings_changed)
    except:
        pass

    # Register callbacks
    try:
        N10X.Editor.AddOnInterceptCharKeyFunction(on_char_key)
        N10X.Editor.AddOnInterceptKeyFunction(on_key)
        N10X.Editor.AddOnSettingsChangedFunction(on_settings_changed)
    except Exception as e:
        print(f"Vim: Failed to register callbacks: {e}")

# Prevent being registered multiple times as VimUser.py imports Vim.py
if __name__ == "__main__":
    initialize()
