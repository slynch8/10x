# Vim emulation layer for 10x Editor
# 10x Python API Reference: https://www.10xeditor.com/10xDocumentation/PythonFunctions.htm
# 10x Command API Reference: https://www.10xeditor.com/10xDocumentation/Commands.htm

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
        # Use duck typing to handle module reloading creating different Key classes
        if not hasattr(other, 'key') or not hasattr(other, 'shift') or not hasattr(other, 'control') or not hasattr(other, 'alt'):
            return False
        # Case-insensitive comparison for single-character keys
        self_key = self.key.lower() if len(self.key) == 1 else self.key
        other_key = other.key.lower() if len(other.key) == 1 else other.key
        return (self_key == other_key and
                self.shift == other.shift and
                self.control == other.control and
                self.alt == other.alt)

    def __hash__(self):
        # Use lowercase for single-character keys to match __eq__
        key = self.key.lower() if len(self.key) == 1 else self.key
        return hash((key, self.shift, self.control, self.alt))

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
g_command_line_type = ""  # ":"
g_registers = {"\"": "", "0": ""}  # Default and yank registers
g_registers_linewise = {"\"": False, "0": False}
g_current_register = "\""
g_marks = {}
g_last_edit = None  # For . repeat: {'op', 'motion', 'motion_arg', 'count', 'linewise', 'text_obj', 'text_obj_arg'}
g_last_insert_text = ""
g_current_edit = None  # Track the edit being built for dot repeat
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
g_pre_insert_pos = (0, 0)  # Position before any cursor movement for insert (e.g., before 'a' moves right)
g_exit_sequence = ""
g_exit_sequence_chars = ""
g_initialized = False
g_filtered_history = True
g_use_10x_find_panel = True
g_command_history = []
g_command_history_index = -1
g_last_visual_start = (0, 0)
g_last_visual_end = (0, 0)
g_last_visual_mode = Mode.VISUAL
g_debug = False
g_suppress_next_char = False  # Suppress char after operator enters insert mode
g_change_undo_group = False   # Track if we're in a change operation undo group
g_undo_cursor_stacks = {}     # Per-file stacks of cursor positions for undo (keyed by filename)
g_redo_cursor_stacks = {}     # Per-file stacks of cursor positions for redo (keyed by filename)
g_pending_undo_before = None  # Temporary storage for "before" position during edits
g_find_panel_was_open = False  # Track find panel state for cursor positioning
g_mouse_visual_suppress_frames = 0  # Suppress mouse->visual conversion for a few updates
g_mouse_visual_active = False  # True when visual mode was entered via mouse selection
g_clear_selection_once = False  # Clear selection once (e.g., after goto definition)
g_pending_window_cmd = False  # Ctrl+W prefix for window commands

# =============================================================================
# Utility Functions
# =============================================================================

# Map of special key names to actual characters
SPECIAL_KEY_MAP = {
    'Space': ' ',
    'Tab': '\t',
    'Slash': '/',
    'OemQuestion': '/',
    'Oem2': '/',
    'Divide': '/',
    'Oem1': ';',
    'Oem7': "'",
    'OemComma': ',',
    'OemPeriod': '.',
    'OemMinus': '-',
    'OemPlus': '=',
    'Oem3': '`',
    'Oem4': '[',
    'Oem5': '\\',
    'Oem6': ']',
}

# Map of shifted characters (US keyboard layout)
SHIFT_CHAR_MAP = {
    '1': '!', '2': '@', '3': '#', '4': '$', '5': '%',
    '6': '^', '7': '&', '8': '*', '9': '(', '0': ')',
    '-': '_', '=': '+', '[': '{', ']': '}', '\\': '|',
    ';': ':', "'": '"', ',': '<', '.': '>', '/': '?', '`': '~',
}

# Command aliases - map short forms to canonical names
COMMAND_ALIASES = {
    'x': 'wq',
    'sp': 'split',
    'vs': 'vsplit',
    'vsp': 'vsplit',
    'bn': 'bnext',
    'bp': 'bprev',
    'bd': 'bdelete',
    'noh': 'nohlsearch',
    'reg': 'registers',
    'tabn': 'tabnext',
    'tabp': 'tabprev',
}

# =============================================================================
# Helper Functions
# =============================================================================

def in_visual_mode():
    """Check if currently in any visual mode."""
    return g_mode in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK)

def _get_current_filename():
    """Get current filename for per-file stack tracking."""
    try:
        return N10X.Editor.GetCurrentFilename() or ""
    except Exception:
        return ""

def save_undo_cursor():
    """Save current cursor position as the 'before' position for an edit."""
    global g_pending_undo_before, g_redo_cursor_stacks
    pos = safe_call(N10X.Editor.GetCursorPos, 0, default=(0, 0))
    if pos:
        g_pending_undo_before = (pos[0], pos[1])
        # Clear redo stack for this file since new edits invalidate redo history
        filename = _get_current_filename()
        g_redo_cursor_stacks[filename] = []

def finalize_undo_cursor():
    """Save the 'after' position and commit (before, after) pair to undo stack."""
    global g_undo_cursor_stacks, g_pending_undo_before
    if g_pending_undo_before is None:
        return
    after_pos = safe_call(N10X.Editor.GetCursorPos, 0, default=(0, 0))
    if after_pos:
        filename = _get_current_filename()
        if filename not in g_undo_cursor_stacks:
            g_undo_cursor_stacks[filename] = []
        g_undo_cursor_stacks[filename].append((g_pending_undo_before, (after_pos[0], after_pos[1])))
        # Limit stack size to prevent memory issues
        if len(g_undo_cursor_stacks[filename]) > 1000:
            g_undo_cursor_stacks[filename] = g_undo_cursor_stacks[filename][-500:]
    g_pending_undo_before = None

def pop_undo_cursor():
    """Pop (before, after) for undo, push full pair to redo stack, return 'before'."""
    global g_undo_cursor_stacks, g_redo_cursor_stacks
    filename = _get_current_filename()
    if filename in g_undo_cursor_stacks and g_undo_cursor_stacks[filename]:
        before_pos, after_pos = g_undo_cursor_stacks[filename].pop()
        # Push full (before, after) to redo stack for this file
        if filename not in g_redo_cursor_stacks:
            g_redo_cursor_stacks[filename] = []
        g_redo_cursor_stacks[filename].append((before_pos, after_pos))
        return before_pos
    return None

def pop_redo_cursor():
    """Pop (before, after) for redo, push back to undo stack, return 'after'."""
    global g_undo_cursor_stacks, g_redo_cursor_stacks
    filename = _get_current_filename()
    if filename in g_redo_cursor_stacks and g_redo_cursor_stacks[filename]:
        before_pos, after_pos = g_redo_cursor_stacks[filename].pop()
        # Push same (before, after) back to undo stack for this file
        if filename not in g_undo_cursor_stacks:
            g_undo_cursor_stacks[filename] = []
        g_undo_cursor_stacks[filename].append((before_pos, after_pos))
        return after_pos
    return None

def safe_call(func, *args, default=None, **kwargs):
    """Call a function safely, returning default on any exception."""
    try:
        result = func(*args, **kwargs)
        return result if result is not None else default
    except Exception:
        return default

def get_setting_bool(name, default=False):
    """Get a boolean setting value."""
    try:
        val = N10X.Editor.GetSetting(name)
        if not val:
            return default
        return val.lower() in ("true", "1", "yes")
    except Exception:
        return default

def get_setting_str(name, default=""):
    """Get a string setting value."""
    try:
        return N10X.Editor.GetSetting(name) or default
    except Exception:
        return default

def get_char_from_key(key):
    """Convert a Key object to the actual character it represents.

    Handles special keys like Space, and shifted characters like : (Shift+;).
    Returns None if the key doesn't represent a printable character.
    """
    key_str = key.key

    # Handle special key names
    if key_str in SPECIAL_KEY_MAP:
        char = SPECIAL_KEY_MAP[key_str]
        if key.shift and char in SHIFT_CHAR_MAP:
            return SHIFT_CHAR_MAP[char]
        return char

    # Handle single character keys
    if len(key_str) == 1:
        if key.shift:
            # Check if it's a character that produces a different symbol when shifted
            if key_str.lower() in SHIFT_CHAR_MAP:
                return SHIFT_CHAR_MAP[key_str.lower()]
            # For letters, return uppercase
            return key_str.upper()
        else:
            return key_str.lower()

    return None

def normalize_key_char(key):
    """Normalize a key to a comparison-friendly character or key name."""
    actual_char = get_char_from_key(key)
    if actual_char and len(actual_char) == 1:
        return actual_char.lower() if actual_char.isalpha() else actual_char
    return key.key.lower() if len(key.key) == 1 else key.key

def is_function_key(key):
    """Return True if key is an F-key (F1..F24 style)."""
    return key.key.startswith('F') and key.key[1:].isdigit()

def is_escape_key(key, char):
    """Return True if this key should exit to normal mode."""
    return char == 'Escape' or (key.control and char == '[')

def get_line(y):
    return safe_call(N10X.Editor.GetLine, y, default="") or ""

def get_line_count():
    return safe_call(N10X.Editor.GetLineCount, default=1) or 1

def get_cursor_pos():
    pos = safe_call(N10X.Editor.GetCursorPos, 0, default=(0, 0))
    return (pos[0], pos[1]) if pos else (0, 0)

def ordered_range(start, end):
    """Return (start, end) ordered top-left to bottom-right."""
    if start[1] > end[1] or (start[1] == end[1] and start[0] > end[0]):
        return end, start
    return start, end

def get_count(default=1):
    """Parse the current count prefix or return default."""
    return int(g_count) if g_count else default

def clear_count():
    """Clear the current count prefix."""
    global g_count
    g_count = ""

def clear_pending_motion(clear_count_flag=True):
    """Clear any pending motion (and optionally the count)."""
    global g_pending_motion
    g_pending_motion = ""
    if clear_count_flag:
        clear_count()

def reset_operator_state(clear_count_flag=True):
    """Clear operator and pending motion (and optionally the count)."""
    global g_operator
    g_operator = ""
    clear_pending_motion(clear_count_flag)

def set_cursor_pos(x, y, extend_selection=False):
    line_count = get_line_count()
    y = max(0, min(y, line_count - 1))
    line = get_line(y)
    line_len = len(line.rstrip('\n\r'))
    if g_mode == Mode.NORMAL and line_len > 0:
        x = max(0, min(x, line_len - 1))
    else:
        x = max(0, min(x, line_len))
    if extend_selection:
        safe_call(N10X.Editor.SetCursorPosSelect, (x, y))
    else:
        safe_call(N10X.Editor.SetCursorPos, (x, y), 0)

def get_selection():
    return safe_call(N10X.Editor.GetSelection, default="") or ""

def set_selection(start, end):
    global g_mouse_visual_suppress_frames
    # Internal selection updates in normal mode should not trigger mouse-visual.
    if g_mode == Mode.NORMAL:
        g_mouse_visual_suppress_frames = 2
    safe_call(N10X.Editor.SetSelection, start, end, 0)

def clear_selection():
    safe_call(N10X.Editor.ClearSelection)

def insert_text(text):
    safe_call(N10X.Editor.InsertText, text)

def delete_selection():
    """Delete the currently selected text and return what was deleted."""
    sel = get_selection()
    if not sel:
        return ""

    try:
        start = N10X.Editor.GetSelectionStart()
        end = N10X.Editor.GetSelectionEnd()
    except Exception:
        return ""

    if start is None or end is None:
        return ""

    start_x, start_y = start
    end_x, end_y = end

    (start_x, start_y), (end_x, end_y) = ordered_range((start_x, start_y), (end_x, end_y))

    clear_selection()

    if start_y == end_y:
        # Single line selection - just modify the line
        line = get_line(start_y)
        new_line = line[:start_x] + line[end_x:]
        N10X.Editor.SetLine(start_y, new_line)
    else:
        # Multi-line selection
        first_line = get_line(start_y)
        last_line = get_line(end_y)

        # Merge: keep part before selection on first line + part after selection on last line
        new_line = first_line[:start_x] + last_line[end_x:]

        N10X.Editor.PushUndoGroup()

        # Set the first line to the merged content
        N10X.Editor.SetLine(start_y, new_line)

        # Delete the extra lines (from start_y+1 to end_y)
        # Position cursor on each line and delete it
        for _ in range(end_y - start_y):
            set_cursor_pos(0, start_y + 1)
            N10X.Editor.ExecuteCommand("DeleteLine")

        N10X.Editor.PopUndoGroup()

    # Position cursor at start of deleted region
    # Use API directly to avoid normal mode clamping (line may now be shorter)
    safe_call(N10X.Editor.SetCursorPos, (start_x, start_y), 0)

    return sel

def get_visual_range(include_cursor=True, linewise=None):
    """Return (start, end, linewise) for current visual selection."""
    start = g_visual_start
    end = get_cursor_pos()
    start, end = ordered_range(start, end)
    if linewise is None:
        linewise = g_mode == Mode.VISUAL_LINE
    if linewise:
        start = (0, start[1])
        end_line = get_line(end[1])
        end = (len(end_line), end[1])
    elif include_cursor:
        end = (end[0] + 1, end[1])
    return start, end, linewise

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
    safe_call(N10X.Editor.SetStatusBarText, text)

def set_cursor_style():
    cursor_modes = {
        Mode.NORMAL: "Block",
        Mode.INSERT: "Line",
        Mode.REPLACE: "Underscore",
        Mode.VISUAL: "Block",
        Mode.VISUAL_LINE: "Block",
        Mode.VISUAL_BLOCK: "Block",
        Mode.COMMAND_LINE: "Block",
    }
    mode = cursor_modes.get(g_mode, "Block")
    safe_call(N10X.Editor.SetCursorMode, mode)

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
        # Truncate any forward history when making a new jump
        if g_jump_index < len(g_jump_list):
            g_jump_list = g_jump_list[:g_jump_index + 1]
        g_jump_list.append((filename, pos))
        if len(g_jump_list) > 100:
            g_jump_list = g_jump_list[-100:]
        # Point past the end - we're at a new position not in the list
        g_jump_index = len(g_jump_list)

def yank_to_register(text, linewise=False):
    global g_registers, g_registers_linewise, g_current_register
    reg = g_current_register
    if linewise and not text.endswith('\n'):
        text = text + '\n'
    g_registers[reg] = text
    g_registers["0"] = text
    g_registers["\""] = text
    g_registers_linewise[reg] = linewise
    g_registers_linewise["0"] = linewise
    g_registers_linewise["\""] = linewise
    # Note: System clipboard (+/*) is handled in apply_operator_to_range
    # by calling Copy command while text is selected
    # Reset register selection after use
    g_current_register = "\""

def get_register(reg=None):
    global g_current_register
    if reg is None:
        reg = g_current_register
    # Reset register selection after use
    g_current_register = "\""
    if reg == "+" or reg == "*":
        # System clipboard - try to get from clipboard via 10x
        try:
            # Use a workaround: save cursor, paste, get selection, undo
            # This is a hack but 10x doesn't expose clipboard API directly
            x, y = get_cursor_pos()
            N10X.Editor.ExecuteCommand("Paste")
            # Get the pasted text
            new_x, new_y = get_cursor_pos()
            if new_y == y:
                line = get_line(y)
                text = line[x:new_x]
            else:
                # Multi-line paste
                lines = []
                for i in range(y, new_y + 1):
                    if i == y:
                        lines.append(get_line(i)[x:])
                    elif i == new_y:
                        lines.append(get_line(i)[:new_x])
                    else:
                        lines.append(get_line(i))
                text = ''.join(lines)
            N10X.Editor.Undo()
            return text
        except Exception:
            pass
        return g_registers.get("\"", "")
    return g_registers.get(reg, "")

def get_register_linewise(reg=None):
    if reg is None:
        reg = g_current_register
    # Default to stored flag; fallback to newline heuristic for unknown regs.
    if reg in g_registers_linewise:
        return g_registers_linewise.get(reg, False)
    text = get_register(reg)
    return text.endswith('\n') if text else False

# =============================================================================
# Mode Management
# =============================================================================

def enter_mode(mode):
    global g_mode, g_visual_start, g_insert_start_pos, g_last_insert_text
    global g_count, g_operator, g_pending_motion, g_current_register, g_exit_sequence
    global g_last_visual_start, g_last_visual_end, g_last_visual_mode
    global g_change_undo_group, g_current_edit, g_last_edit, g_mouse_visual_active, g_pending_window_cmd

    old_mode = g_mode
    g_mode = mode
    if mode != Mode.VISUAL:
        g_mouse_visual_active = False
    if mode != Mode.NORMAL:
        g_pending_window_cmd = False
    g_count = ""
    g_operator = ""
    g_pending_motion = ""
    g_current_register = "\""
    g_exit_sequence = ""

    if mode == Mode.INSERT:
        g_insert_start_pos = get_cursor_pos()
        g_last_insert_text = ""
    elif mode == Mode.REPLACE:
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
        # Clear any multi-cursors when returning to normal mode
        try:
            N10X.Editor.ClearMultiCursors()
        except Exception:
            pass
        # Adjust cursor if coming from insert or replace mode
        if old_mode == Mode.INSERT:
            # Close undo group if we were in a change operation
            if g_change_undo_group:
                N10X.Editor.PopUndoGroup()
                g_change_undo_group = False
            # Finalize the edit for dot repeat
            if g_current_edit is not None:
                g_current_edit['insert_text'] = g_last_insert_text
                g_last_edit = g_current_edit
                g_current_edit = None
            x, y = get_cursor_pos()
            line = get_line(y)
            line_len = len(line.rstrip('\n\r'))
            # If nothing was typed, restore to pre-insert position
            if not g_last_insert_text and g_pre_insert_pos[1] == y:
                set_cursor_pos(g_pre_insert_pos[0], g_pre_insert_pos[1])
            # Otherwise, ensure cursor isn't past end of line
            elif x > 0 and x >= line_len:
                set_cursor_pos(max(0, line_len - 1), y)
            # Finalize undo cursor position (after position adjustment)
            finalize_undo_cursor()
        elif old_mode == Mode.REPLACE:
            # Close undo group from replace mode
            if g_change_undo_group:
                N10X.Editor.PopUndoGroup()
                g_change_undo_group = False
            # Finalize the edit for dot repeat
            if g_current_edit is not None:
                g_current_edit['insert_text'] = g_last_insert_text
                if g_current_edit.get('motion') == 's':
                    g_current_edit['count'] = len(g_last_insert_text)
                g_last_edit = g_current_edit
                g_current_edit = None
            # Finalize undo cursor position
            finalize_undo_cursor()

    set_cursor_style()
    update_status()

def enter_normal_mode():
    enter_mode(Mode.NORMAL)

def enter_insert_mode(skip_undo_save=False):
    if not skip_undo_save:
        save_undo_cursor()
    enter_mode(Mode.INSERT)

def enter_visual_mode():
    enter_mode(Mode.VISUAL)
    update_visual_selection()

def enter_visual_line_mode():
    enter_mode(Mode.VISUAL_LINE)
    update_visual_selection()

def enter_visual_block_mode():
    enter_mode(Mode.VISUAL_BLOCK)
    update_visual_selection()

def enter_command_line_mode(char):
    global g_mode, g_command_line, g_command_line_type, g_command_history_index
    g_mode = Mode.COMMAND_LINE
    g_command_line = ""
    g_command_line_type = char
    g_command_history_index = -1
    set_status(char)
    set_cursor_style()

# =============================================================================
# Motions
# =============================================================================

def motion_h(count=1):
    x, y = get_cursor_pos()
    set_cursor_pos(x - count, y, in_visual_mode())

def motion_l(count=1):
    x, y = get_cursor_pos()
    set_cursor_pos(x + count, y, in_visual_mode())

def motion_j(count=1):
    x, y = get_cursor_pos()
    set_cursor_pos(x, y + count, in_visual_mode())

def motion_k(count=1):
    x, y = get_cursor_pos()
    set_cursor_pos(x, y - count, in_visual_mode())

def motion_0():
    x, y = get_cursor_pos()
    set_cursor_pos(0, y, in_visual_mode())

def motion_caret():
    x, y = get_cursor_pos()
    line = get_line(y)
    for i, c in enumerate(line):
        if not is_whitespace(c):
            set_cursor_pos(i, y, in_visual_mode())
            return
    set_cursor_pos(0, y, in_visual_mode())

def motion_dollar(count=1):
    x, y = get_cursor_pos()
    target_y = y + count - 1
    line = get_line(target_y)
    line_len = len(line.rstrip('\n\r'))
    pos = max(0, line_len - 1) if g_mode == Mode.NORMAL else line_len
    set_cursor_pos(pos, target_y, in_visual_mode())

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

    set_cursor_pos(x, y, in_visual_mode())

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

    set_cursor_pos(x, y, in_visual_mode())

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

    set_cursor_pos(x, y, in_visual_mode())

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

    set_cursor_pos(x, y, in_visual_mode())

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

    set_cursor_pos(x, y, in_visual_mode())

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

    set_cursor_pos(x, y, in_visual_mode())

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

    set_cursor_pos(x, y, in_visual_mode())

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

    set_cursor_pos(x, y, in_visual_mode())

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
    set_cursor_pos(0, y, in_visual_mode())

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
    set_cursor_pos(0, y, in_visual_mode())

def motion_section_forward(count=1, end=False):
    """Move forward to next section (line starting with { or })
    If end=False, look for '{' at start of line (]])
    If end=True, look for '}' at start of line (][)
    """
    x, y = get_cursor_pos()
    line_count = get_line_count()
    target_char = '}' if end else '{'

    for _ in range(count):
        y += 1
        while y < line_count:
            line = get_line(y)
            stripped = line.lstrip()
            if stripped.startswith(target_char):
                break
            y += 1

    y = min(y, line_count - 1)
    set_cursor_pos(0, y, in_visual_mode())

def motion_section_backward(count=1, end=False):
    """Move backward to previous section
    If end=False, look for '{' at start of line ([[)
    If end=True, look for '}' at start of line ([])
    """
    x, y = get_cursor_pos()
    target_char = '}' if end else '{'

    for _ in range(count):
        y -= 1
        while y >= 0:
            line = get_line(y)
            stripped = line.lstrip()
            if stripped.startswith(target_char):
                break
            y -= 1

    y = max(0, y)
    set_cursor_pos(0, y, in_visual_mode())

def motion_gg(count=None):
    push_jump()
    if count is None:
        count = 1
    target_y = count - 1
    set_cursor_pos(0, target_y, in_visual_mode())
    motion_caret()

def motion_G(count=None):
    push_jump()
    if count is None:
        target_y = get_line_count() - 1
    else:
        target_y = count - 1
    set_cursor_pos(0, target_y, in_visual_mode())
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
    set_cursor_pos(curr_x, curr_y, in_visual_mode())

def _find_char_on_line(char, count, forward, offset=0):
    """Core logic for f/F/t/T motions. Returns target x position or None."""
    x, y = get_cursor_pos()
    line = get_line(y)
    found = 0
    if forward:
        for i in range(x + 1, len(line)):
            if line[i] == char:
                found += 1
                if found == count:
                    return i + offset, y
    else:
        for i in range(x - 1, -1, -1):
            if line[i] == char:
                found += 1
                if found == count:
                    return i - offset, y
    return None

def motion_f(char, count=1, update_state=True):
    """Move forward to character. Set update_state=False for ; and , repeats."""
    if update_state:
        global g_last_f_char, g_last_f_direction, g_last_t_mode
        g_last_f_char = char
        g_last_f_direction = 1
        g_last_t_mode = False
    result = _find_char_on_line(char, count, forward=True, offset=0)
    if result:
        set_cursor_pos(result[0], result[1], in_visual_mode())
        return True
    return False

def motion_F(char, count=1, update_state=True):
    """Move backward to character. Set update_state=False for ; and , repeats."""
    if update_state:
        global g_last_f_char, g_last_f_direction, g_last_t_mode
        g_last_f_char = char
        g_last_f_direction = -1
        g_last_t_mode = False
    result = _find_char_on_line(char, count, forward=False, offset=0)
    if result:
        set_cursor_pos(result[0], result[1], in_visual_mode())
        return True
    return False

def motion_t(char, count=1, update_state=True):
    """Move forward to before character. Set update_state=False for ; and , repeats."""
    if update_state:
        global g_last_f_char, g_last_f_direction, g_last_t_mode
        g_last_f_char = char
        g_last_f_direction = 1
        g_last_t_mode = True
    result = _find_char_on_line(char, count, forward=True, offset=-1)
    if result:
        set_cursor_pos(result[0], result[1], in_visual_mode())
        return True
    return False

def motion_T(char, count=1, update_state=True):
    """Move backward to after character. Set update_state=False for ; and , repeats."""
    if update_state:
        global g_last_f_char, g_last_f_direction, g_last_t_mode
        g_last_f_char = char
        g_last_f_direction = -1
        g_last_t_mode = True
    result = _find_char_on_line(char, count, forward=False, offset=-1)
    if result:
        set_cursor_pos(result[0], result[1], in_visual_mode())
        return True
    return False

def motion_semicolon(count=1):
    """Repeat last f/F/t/T in same direction"""
    if not g_last_f_char:
        return
    motion_func = (motion_t if g_last_t_mode else motion_f) if g_last_f_direction == 1 else (motion_T if g_last_t_mode else motion_F)
    motion_func(g_last_f_char, count, update_state=False)

def motion_comma(count=1):
    """Repeat last f/F/t/T in opposite direction without changing stored state"""
    if not g_last_f_char:
        return
    # Opposite direction: if last was forward (1), go backward, and vice versa
    motion_func = (motion_T if g_last_t_mode else motion_F) if g_last_f_direction == 1 else (motion_t if g_last_t_mode else motion_f)
    motion_func(g_last_f_char, count, update_state=False)

def motion_underscore(count=1):
    """Move to first non-blank of count-1 lines down"""
    x, y = get_cursor_pos()
    target_y = y + count - 1
    set_cursor_pos(0, target_y, in_visual_mode())
    motion_caret()

def motion_plus(count=1):
    """Move to first non-blank of next line"""
    x, y = get_cursor_pos()
    set_cursor_pos(0, y + count, in_visual_mode())
    motion_caret()

def motion_minus(count=1):
    """Move to first non-blank of previous line"""
    x, y = get_cursor_pos()
    set_cursor_pos(0, max(0, y - count), in_visual_mode())
    motion_caret()

def motion_pipe(count=1):
    """Move to column N (1-indexed)"""
    x, y = get_cursor_pos()
    set_cursor_pos(count - 1, y, in_visual_mode())

def motion_H():
    try:
        scroll_line = N10X.Editor.GetScrollLine()
        set_cursor_pos(0, scroll_line, in_visual_mode())
        motion_caret()
    except Exception:
        pass

def motion_M():
    try:
        scroll_line = N10X.Editor.GetScrollLine()
        visible = N10X.Editor.GetVisibleLineCount()
        mid = scroll_line + visible // 2
        set_cursor_pos(0, mid, in_visual_mode())
        motion_caret()
    except Exception:
        pass

def motion_L():
    try:
        scroll_line = N10X.Editor.GetScrollLine()
        visible = N10X.Editor.GetVisibleLineCount()
        bottom = scroll_line + visible - 1
        set_cursor_pos(0, bottom, in_visual_mode())
        motion_caret()
    except Exception:
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
            # Inner paragraph: don't include trailing blank line
            # end_y points to blank line after paragraph (or last non-blank if at end of file)
            actual_end_y = end_y - 1 if end_y > start_y and not get_line(end_y).strip() else end_y
            if actual_end_y < start_y:
                actual_end_y = start_y
            return ((0, start_y), (len(get_line(actual_end_y).rstrip('\n\r')), actual_end_y))
        else:
            # Outer paragraph: include trailing blank lines
            while end_y < get_line_count() - 1 and not get_line(end_y).strip():
                end_y += 1
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

def apply_operator_to_range(op, start, end, linewise=False, edit_info=None, skip_undo_save=False):
    global g_last_edit, g_current_edit

    # Save cursor for undo (except for yank which doesn't modify)
    if op != 'y' and not skip_undo_save:
        save_undo_cursor()

    if g_debug:
        N10X.Editor.LogTo10XOutput(f"DEBUG apply_operator_to_range: op='{op}' start={start} end={end} linewise={linewise}\n")

    start_x, start_y = start
    end_x, end_y = end

    (start_x, start_y), (end_x, end_y) = ordered_range((start_x, start_y), (end_x, end_y))

    # For yank, save the x position before linewise modification (for cursor restoration)
    yank_restore_x = start_x

    if linewise:
        start_x = 0
        end_line = get_line(end_y)
        end_x = len(end_line)

    set_selection((start_x, start_y), (end_x, end_y))
    text = get_selection()
    if g_debug:
        N10X.Editor.LogTo10XOutput(f"DEBUG apply_operator_to_range: selected text='{text}' len={len(text)}\n")

    # Build edit info for dot repeat
    if edit_info is None:
        edit_info = {}
    edit_info['op'] = op
    edit_info['linewise'] = linewise

    if op == 'd':  # delete
        if g_debug:
            N10X.Editor.LogTo10XOutput(f"DEBUG: Deleting text\n")
        yank_to_register(text, linewise)
        if linewise:
            # Delete entire lines, not just content
            clear_selection()
            N10X.Editor.PushUndoGroup()
            num_lines = end_y - start_y + 1
            set_cursor_pos(0, start_y)
            for _ in range(num_lines):
                N10X.Editor.ExecuteCommand("DeleteLine")
            N10X.Editor.PopUndoGroup()
            # Position cursor on the line that took the place of deleted lines
            new_y = min(start_y, get_line_count() - 1)
            set_cursor_pos(0, new_y)
            motion_caret()
        else:
            delete_selection()
        g_last_edit = edit_info

    elif op == 'c':  # change
        global g_suppress_next_char, g_change_undo_group
        yank_to_register(text, linewise)
        N10X.Editor.PushUndoGroup()  # Group deletion and insertion together
        g_change_undo_group = True
        delete_selection()
        # Reposition cursor using API directly to bypass normal mode clamping,
        # since we're about to enter insert mode and may need to be at end of line
        N10X.Editor.SetCursorPos((start_x, start_y), 0)
        g_suppress_next_char = True  # Don't insert the motion key
        # Skip undo save - cursor was already saved before the motion
        enter_insert_mode(skip_undo_save=True)
        # Store current edit, will be finalized when leaving insert mode
        g_current_edit = edit_info

    elif op == 'y':  # yank
        # If yanking to system clipboard, use 10x Copy command while text is selected
        if g_current_register in ("+", "*"):
            try:
                N10X.Editor.ExecuteCommand("Copy")
            except Exception:
                pass
        yank_to_register(text, linewise)
        clear_selection()
        # Restore cursor to original x position (before linewise modification set it to 0)
        set_cursor_pos(yank_restore_x, start_y)
        set_status(f"Yanked {len(text)} characters")
        # Yank is not repeatable with dot

    elif op == '>':  # indent
        clear_selection()
        # Select the lines to indent
        end_line = get_line(end_y)
        set_selection((0, start_y), (len(end_line), end_y))
        N10X.Editor.ExecuteCommand("IndentLine")
        clear_selection()
        # Move cursor to first non-whitespace of first line
        set_cursor_pos(0, start_y)
        motion_caret()

    elif op == '<':  # unindent
        clear_selection()
        # Select the lines to unindent
        end_line = get_line(end_y)
        set_selection((0, start_y), (len(end_line), end_y))
        N10X.Editor.ExecuteCommand("UnindentLine")
        clear_selection()
        # Move cursor to first non-whitespace of first line
        set_cursor_pos(0, start_y)
        motion_caret()

    elif op == 'gu':  # lowercase
        new_text = text.lower()
        # Selection is already set, delete it and insert the new text
        N10X.Editor.PushUndoGroup()
        delete_selection()
        insert_text(new_text)
        N10X.Editor.PopUndoGroup()
        set_cursor_pos(start_x, start_y)

    elif op == 'gU':  # uppercase
        new_text = text.upper()
        # Selection is already set, delete it and insert the new text
        N10X.Editor.PushUndoGroup()
        delete_selection()
        insert_text(new_text)
        N10X.Editor.PopUndoGroup()
        set_cursor_pos(start_x, start_y)

    elif op == '=':  # auto-indent
        clear_selection()
        set_cursor_pos(start_x, start_y)
        set_status("Auto-indent not supported")

    elif op == 'g~':  # toggle case
        new_text = text.swapcase()
        # Selection is already set, delete it and insert the new text
        N10X.Editor.PushUndoGroup()
        delete_selection()
        insert_text(new_text)
        N10X.Editor.PopUndoGroup()
        set_cursor_pos(start_x, start_y)

    # Finalize undo cursor for operations that don't enter insert mode
    # 'c' (change) finalizes when leaving insert mode, 'y' (yank) doesn't modify
    if op not in ('c', 'y'):
        finalize_undo_cursor()

def operator_dd(count=1):
    x, y = get_cursor_pos()
    end_y = min(y + count - 1, get_line_count() - 1)
    end_line = get_line(end_y)
    edit_info = {'motion': 'dd', 'count': count}
    apply_operator_to_range('d', (0, y), (len(end_line), end_y), linewise=True, edit_info=edit_info)

def operator_yy(count=1):
    x, y = get_cursor_pos()
    end_y = min(y + count - 1, get_line_count() - 1)
    end_line = get_line(end_y)
    # Pass (x, y) to preserve original cursor x position for restoration
    apply_operator_to_range('y', (x, y), (len(end_line), end_y), linewise=True)

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
    edit_info = {'motion': 'cc', 'count': count}
    apply_operator_to_range('c', (indent, y), (len(end_line.rstrip('\n\r')), end_y), linewise=False, edit_info=edit_info)
    # Note: apply_operator_to_range('c',...) already enters insert mode

def _repeat_last_edit(repeat_count=1):
    """Repeat the last edit operation (for dot command)."""
    global g_last_edit

    if not g_last_edit or not isinstance(g_last_edit, dict):
        return

    # Save cursor position for undo before repeating the edit
    save_undo_cursor()

    op = g_last_edit.get('op')
    motion = g_last_edit.get('motion')
    motion_arg = g_last_edit.get('motion_arg')
    edit_count = g_last_edit.get('count', 1)
    linewise = g_last_edit.get('linewise', False)
    insert_text_content = g_last_edit.get('insert_text', '')

    # Use repeat_count if provided, otherwise use original count
    use_count = repeat_count if repeat_count > 1 else edit_count

    if not op or not motion:
        return

    # Execute the motion and get the range
    start = get_cursor_pos()
    end = start

    # Handle different motion types
    if motion == 'w':
        if op == 'c':
            motion_e(use_count)  # cw acts like ce
        else:
            motion_w(use_count)
        end = get_cursor_pos()
        end = (end[0] + 1, end[1]) if op == 'c' else end
    elif motion == 'W':
        if op == 'c':
            motion_E(use_count)
        else:
            motion_W(use_count)
        end = get_cursor_pos()
        end = (end[0] + 1, end[1]) if op == 'c' else end
    elif motion == 'e':
        motion_e(use_count)
        end = get_cursor_pos()
        end = (end[0] + 1, end[1])
    elif motion == 'E':
        motion_E(use_count)
        end = get_cursor_pos()
        end = (end[0] + 1, end[1])
    elif motion == 'b':
        motion_b(use_count)
        end = get_cursor_pos()
        start, end = end, start  # b goes backward
    elif motion == 'B':
        motion_B(use_count)
        end = get_cursor_pos()
        start, end = end, start
    elif motion == '$':
        motion_dollar(use_count)
        end = get_cursor_pos()
        end = (end[0] + 1, end[1])
    elif motion == '0':
        motion_0()
        end = get_cursor_pos()
        start, end = end, start
    elif motion == '^':
        motion_caret()
        end = get_cursor_pos()
        start, end = end, start
    elif motion in ('h', 'j', 'k', 'l'):
        if motion == 'h':
            motion_h(use_count)
        elif motion == 'j':
            motion_j(use_count)
        elif motion == 'k':
            motion_k(use_count)
        elif motion == 'l':
            motion_l(use_count)
        end = get_cursor_pos()
        if motion == 'l':
            end = (end[0] + 1, end[1])
        linewise = motion in ('j', 'k')
    elif motion == 'f' and motion_arg:
        motion_f(motion_arg, use_count)
        end = get_cursor_pos()
        end = (end[0] + 1, end[1])
    elif motion == 'F' and motion_arg:
        motion_F(motion_arg, use_count)
        end = get_cursor_pos()
        start, end = end, start
    elif motion == 't' and motion_arg:
        motion_t(motion_arg, use_count)
        end = get_cursor_pos()
        end = (end[0] + 1, end[1])
    elif motion == 'T' and motion_arg:
        motion_T(motion_arg, use_count)
        end = get_cursor_pos()
        start, end = end, start
    elif len(motion) > 1 and (motion.startswith('i') or motion.startswith('a')):
        # Text object (e.g., 'iw', 'a"', etc.) - must be 2+ chars to distinguish from insert/append
        inner = motion.startswith('i')
        obj_char = motion[1]
        obj_range = get_text_object_range(obj_char, inner)
        if obj_range:
            start, end = obj_range
        else:
            return  # No matching text object found
    elif motion == 'gg':
        target = use_count - 1 if use_count else 0
        end = (0, target)
        linewise = True
    elif motion == 'G':
        motion_G(use_count if use_count > 1 else None)
        end = get_cursor_pos()
        end = (len(get_line(end[1])), end[1])
        linewise = True
    elif motion == 'dd':
        # Delete lines
        operator_dd(use_count)
        return  # operator_dd handles everything
    elif motion == 'cc':
        # Change lines - need to handle specially to insert the text
        x, y = get_cursor_pos()
        line = get_line(y)
        indent = 0
        for c in line:
            if c in ' \t':
                indent += 1
            else:
                break
        end_y = min(y + use_count - 1, get_line_count() - 1)
        end_line = get_line(end_y)
        set_selection((indent, y), (len(end_line.rstrip('\n\r')), end_y))
        text = get_selection()
        yank_to_register(text, False)
        delete_selection()
        if insert_text_content:
            insert_text(insert_text_content)
        return
    elif motion == 'x':
        # Delete character under cursor
        x, y = get_cursor_pos()
        line = get_line(y)
        line_len = len(line.rstrip('\n\r'))
        del_count = min(use_count, line_len - x)
        if del_count > 0:
            deleted = line[x:x + del_count]
            yank_to_register(deleted, False)
            N10X.Editor.SetLine(y, line[:x] + line[x + del_count:])
        return
    elif motion == 'X':
        # Delete character before cursor
        x, y = get_cursor_pos()
        if x > 0:
            line = get_line(y)
            del_count = min(use_count, x)
            deleted = line[x - del_count:x]
            yank_to_register(deleted, False)
            N10X.Editor.SetLine(y, line[:x - del_count] + line[x:])
            set_cursor_pos(x - del_count, y)
        return
    elif motion == 's':
        # Substitute character(s) under cursor
        N10X.Editor.PushUndoGroup()
        x, y = get_cursor_pos()
        line = get_line(y)
        line_len = len(line.rstrip('\n\r'))
        del_count = min(use_count, line_len - x)
        if del_count > 0:
            deleted = line[x:x + del_count]
            yank_to_register(deleted, False)
            N10X.Editor.SetLine(y, line[:x] + line[x + del_count:])
        if insert_text_content:
            insert_text(insert_text_content)
        N10X.Editor.PopUndoGroup()
        finalize_undo_cursor()
        return
    elif motion == 'r':
        # Replace character (from 'r' command) - cursor stays in place
        x, y = get_cursor_pos()
        line = get_line(y)
        if x < len(line.rstrip('\n\r')) and insert_text_content:
            new_line = line[:x] + insert_text_content + line[x+1:]
            N10X.Editor.SetLine(y, new_line)
            set_cursor_pos(x, y)
        finalize_undo_cursor()
        return
    elif motion == 'i':
        # Insert at cursor
        x, y = get_cursor_pos()
        line = get_line(y)
        if insert_text_content:
            new_line = line[:x] + insert_text_content + line[x:]
            N10X.Editor.SetLine(y, new_line)
            # Position cursor at end of inserted text - 1 (vim normal mode)
            set_cursor_pos(x + len(insert_text_content) - 1, y)
        finalize_undo_cursor()
        return
    elif motion == 'I':
        # Insert at first non-blank
        x, y = get_cursor_pos()
        line = get_line(y)
        indent = 0
        for c in line:
            if c in ' \t':
                indent += 1
            else:
                break
        if insert_text_content:
            new_line = line[:indent] + insert_text_content + line[indent:]
            N10X.Editor.SetLine(y, new_line)
            # Position cursor at end of inserted text - 1 (vim normal mode)
            set_cursor_pos(indent + len(insert_text_content) - 1, y)
        finalize_undo_cursor()
        return
    elif motion == 'a':
        # Append after cursor
        x, y = get_cursor_pos()
        line = get_line(y)
        line_len = len(line.rstrip('\n\r'))
        # Move cursor one position to the right (like 'a' does)
        insert_x = min(x + 1, line_len)
        if insert_text_content:
            new_line = line[:insert_x] + insert_text_content + line[insert_x:]
            N10X.Editor.SetLine(y, new_line)
            # Position cursor at end of inserted text - 1 (vim normal mode)
            set_cursor_pos(insert_x + len(insert_text_content) - 1, y)
        finalize_undo_cursor()
        return
    elif motion == 'A':
        # Append at end of line
        x, y = get_cursor_pos()
        line = get_line(y)
        line_len = len(line.rstrip('\n\r'))
        if insert_text_content:
            new_line = line[:line_len] + insert_text_content + line[line_len:]
            N10X.Editor.SetLine(y, new_line)
            # Position cursor at end of inserted text - 1 (vim normal mode)
            set_cursor_pos(line_len + len(insert_text_content) - 1, y)
        finalize_undo_cursor()
        return
    elif motion == 'o':
        # Open line below
        x, y = get_cursor_pos()
        line = get_line(y)
        # Get indentation from current line
        indent = ""
        for c in line:
            if c in ' \t':
                indent += c
            else:
                break
        line_len = len(line.rstrip('\n\r'))
        # Position at end of line and insert newline + indent + text
        N10X.Editor.SetCursorPos((line_len, y), 0)
        N10X.Editor.InsertText('\n' + indent + (insert_text_content or ''))
        # Position cursor at end of inserted text on new line
        new_y = y + 1
        if insert_text_content:
            set_cursor_pos(len(indent) + len(insert_text_content) - 1, new_y)
        else:
            set_cursor_pos(len(indent), new_y)
        finalize_undo_cursor()
        return
    elif motion == 'O':
        # Open line above
        x, y = get_cursor_pos()
        line = get_line(y)
        # Get indentation from current line
        indent = ""
        for c in line:
            if c in ' \t':
                indent += c
            else:
                break
        # Position at start of line and insert indent + text + newline
        N10X.Editor.SetCursorPos((0, y), 0)
        N10X.Editor.InsertText(indent + (insert_text_content or '') + '\n')
        # Position cursor at end of inserted text on the new line (which is at y)
        if insert_text_content:
            set_cursor_pos(len(indent) + len(insert_text_content) - 1, y)
        else:
            set_cursor_pos(len(indent), y)
        finalize_undo_cursor()
        return
    else:
        return  # Unknown motion

    # Apply the operator
    if op == 'd':
        set_cursor_pos(start[0], start[1])
        apply_operator_to_range('d', start, end, linewise, g_last_edit, skip_undo_save=True)
    elif op == 'c':
        set_cursor_pos(start[0], start[1])
        # For change, we need to delete and insert without entering insert mode
        # Group delete and insert as one undo operation
        N10X.Editor.PushUndoGroup()
        set_selection(start, end)
        text = get_selection()
        yank_to_register(text, linewise)
        delete_selection()
        if insert_text_content:
            insert_text(insert_text_content)
        N10X.Editor.PopUndoGroup()
        finalize_undo_cursor()
        # Don't update g_last_edit - keep the original

# =============================================================================
# Search
# =============================================================================

def move_cursor_to_selection_start():
    """Move cursor to the start of the current selection (for search results)."""
    try:
        start = N10X.Editor.GetSelectionStart()
        if start:
            start_x, start_y = start
            set_cursor_pos(start_x, start_y)
    except Exception:
        pass

def on_update():
    """Called every frame to check for find panel state changes."""
    global g_find_panel_was_open, g_mouse_visual_suppress_frames, g_mouse_visual_active, g_visual_start
    global g_clear_selection_once

    if not is_vim_enabled():
        return

    # Check if find panel just closed (search was performed)
    find_panel_open = safe_call(N10X.Editor.IsFindPanelOpen, default=False) or \
                      safe_call(N10X.Editor.IsFindReplacePanelOpen, default=False)

    if g_find_panel_was_open and not find_panel_open:
        # Find panel just closed - move cursor to start of found word
        move_cursor_to_selection_start()
        g_mouse_visual_suppress_frames = 2

    g_find_panel_was_open = find_panel_open

    if g_mouse_visual_suppress_frames > 0:
        g_mouse_visual_suppress_frames -= 1

    selection = _get_active_selection()
    if g_clear_selection_once and selection:
        start, end = selection
        clear_selection()
        # Place cursor at start of the would-have-been selection.
        set_cursor_pos(start[0], start[1])
        g_clear_selection_once = False
        g_mouse_visual_suppress_frames = 2
        selection = None
    if g_mode == Mode.NORMAL:
        if g_operator or g_pending_motion:
            return
        if g_mouse_visual_suppress_frames == 0 and selection and not find_panel_open:
            _enter_visual_from_selection(selection[0], selection[1])
    elif in_visual_mode() and g_mouse_visual_active:
        if not selection:
            enter_normal_mode()
            return
        # Keep visual anchors in sync if selection is adjusted via mouse.
        start, end = selection
        g_visual_start = start
        if get_cursor_pos() != end:
            safe_call(N10X.Editor.SetCursorPos, end, 0)
        update_visual_selection()

def search_word_under_cursor(direction=1):
    """Search for the word under cursor (* and # commands)."""
    word = get_word_at_cursor()
    if word:
        push_jump()
        reverse = (direction == -1)
        N10X.Editor.SetFindText(word, False, True, False, reverse)
        N10X.Editor.ExecuteCommand("FindInFileNext")
        move_cursor_to_selection_start()
        set_status(f"/{word}" if direction == 1 else f"?{word}")

# =============================================================================
# Commands
# =============================================================================

def _switch_buffer(direction):
    """Switch to next (direction=1) or previous (direction=-1) buffer."""
    files = safe_call(N10X.Editor.GetOpenFiles, default=[])
    current = safe_call(N10X.Editor.GetCurrentFilename, default="")
    if files and current in files:
        idx = files.index(current)
        new_idx = (idx + direction) % len(files)
        safe_call(N10X.Editor.FocusFile, files[new_idx])

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
    # Compare by name to handle module reloading creating different enum classes
    result_name = result.name if hasattr(result, 'name') else str(result)
    if result_name == 'HANDLED':
        return
    elif result_name == 'PASS_TO_10X':
        try:
            N10X.Editor.ExecuteCommand(cmd)
        except Exception:
            pass
        return

    # Parse command
    parts = cmd.split(None, 1)
    command = parts[0] if parts else ""
    args = parts[1] if len(parts) > 1 else ""

    # Normalize command aliases
    command = COMMAND_ALIASES.get(command, command)

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
            except Exception:
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

    elif command == 'wq':
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
        except Exception:
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

    elif command == 'vsplit':
        # Vertical split (side by side)
        if args:
            N10X.Editor.ExecuteCommand("DuplicatePanelRight")
            N10X.Editor.OpenFile(args)
        else:
            N10X.Editor.ExecuteCommand("DuplicatePanelRight")

    elif command == 'split':
        # Horizontal split - 10x doesn't have DuplicatePanelDown, so use DuplicatePanel
        # which duplicates in place, or fall back to column-based split
        if args:
            N10X.Editor.ExecuteCommand("DuplicatePanel")
            N10X.Editor.OpenFile(args)
        else:
            N10X.Editor.ExecuteCommand("DuplicatePanel")

    elif command == 'bnext':
        _switch_buffer(1)

    elif command == 'bprev':
        _switch_buffer(-1)

    elif command == 'bdelete':
        N10X.Editor.CloseFile()

    elif command == 'nohlsearch':
        set_status("")

    elif command in ('wrap', 'setwrap', 'nowrap', 'setnowrap'):
        N10X.Editor.ExecuteCommand("ToggleWordWrapForCurrentPanel")

    elif command == 'set':
        if args:
            if args == 'wrap':
                N10X.Editor.ExecuteCommand("ToggleWordWrapForCurrentPanel")
            elif args == 'nowrap':
                N10X.Editor.ExecuteCommand("ToggleWordWrapForCurrentPanel")
            elif '=' in args:
                name, value = args.split('=', 1)
                try:
                    N10X.Editor.SetSetting(name.strip(), value.strip())
                except Exception:
                    pass
            elif args.startswith('no'):
                try:
                    N10X.Editor.SetSetting(args[2:], "false")
                except Exception:
                    pass
            else:
                try:
                    val = N10X.Editor.GetSetting(args)
                    set_status(f"{args}={val}")
                except Exception:
                    pass

    elif command == 'registers':
        reg_info = [f'"{r}: {v[:30].replace(chr(10), "^J")}' for r, v in g_registers.items() if v]
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

    elif command in ('make', 'build'):
        safe_call(N10X.Editor.ExecuteCommand, "BuildActiveWorkspace")

    elif command == 'copen':
        safe_call(N10X.Editor.ShowBuildOutput)

    elif command == 'cclose':
        pass  # No direct way to close build panel

    elif command == 'only':
        safe_call(N10X.Editor.SetColumnCount, 1)

    elif command == 'tabnew':
        if args:
            N10X.Editor.OpenFile(args)

    elif command == 'tabnext':
        safe_call(N10X.Editor.ExecuteCommand, "NextPanelTab")

    elif command == 'tabprev':
        safe_call(N10X.Editor.ExecuteCommand, "PrevPanelTab")

    elif command == 'help':
        set_status("Vim mode - :w save, :q quit, :wq save+quit, :e file, /search, ?search")

    else:
        # Try as 10x command
        if not safe_call(N10X.Editor.ExecuteCommand, command):
            set_status(f"Unknown command: {command}")

# =============================================================================
# Visual Mode
# =============================================================================

def _get_active_selection():
    """Return (start, end) if there is an active selection, otherwise None."""
    try:
        start = N10X.Editor.GetSelectionStart()
        end = N10X.Editor.GetSelectionEnd()
    except Exception:
        return None

    if not start or not end:
        return None
    if start == end:
        return None
    return (start, end)

def _enter_visual_from_selection(start, end):
    """Enter visual mode using an existing (mouse) selection."""
    global g_visual_start, g_mouse_visual_active
    enter_mode(Mode.VISUAL)
    g_visual_start = start
    safe_call(N10X.Editor.SetCursorPos, end, 0)
    update_visual_selection()
    g_mouse_visual_active = True

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
        except Exception:
            pass

    set_selection(start, end)

def _apply_visual_block_operation(op):
    """Apply an operator to a visual block selection."""
    global g_change_undo_group

    # Compute block bounds
    x1, y1 = g_visual_start
    x2, y2 = get_cursor_pos()
    top = min(y1, y2)
    bottom = max(y1, y2)
    left = min(x1, x2)
    right = max(x1, x2)
    right_exclusive = right + 1

    # Save cursor for undo (except for yank which doesn't modify)
    if op != 'y':
        save_undo_cursor()

    # Gather text for yank (block-wise)
    yanked_lines = []

    if op in ('d', 'c', 'gu', 'gU', 'g~'):
        N10X.Editor.PushUndoGroup()

    for y in range(top, bottom + 1):
        line = get_line(y)
        line_no_nl = line.rstrip('\n\r')
        line_suffix = line[len(line_no_nl):]
        line_len = len(line_no_nl)

        if left >= line_len:
            yanked_lines.append("")
            continue

        del_end = min(right_exclusive, line_len)
        segment = line_no_nl[left:del_end]
        yanked_lines.append(segment)

        if op in ('d', 'c'):
            new_line = line_no_nl[:left] + line_no_nl[del_end:] + line_suffix
            N10X.Editor.SetLine(y, new_line)
        elif op == 'gu':
            new_line = line_no_nl[:left] + segment.lower() + line_no_nl[del_end:] + line_suffix
            N10X.Editor.SetLine(y, new_line)
        elif op == 'gU':
            new_line = line_no_nl[:left] + segment.upper() + line_no_nl[del_end:] + line_suffix
            N10X.Editor.SetLine(y, new_line)
        elif op == 'g~':
            new_line = line_no_nl[:left] + segment.swapcase() + line_no_nl[del_end:] + line_suffix
            N10X.Editor.SetLine(y, new_line)

    if op in ('d', 'gu', 'gU', 'g~'):
        N10X.Editor.PopUndoGroup()

    # Yank result for d/c/y and case ops
    if op in ('d', 'c', 'y', 'gu', 'gU', 'g~'):
        yank_to_register('\n'.join(yanked_lines), linewise=False)

    # Position cursor at block start
    if op != 'y':
        line = get_line(top)
        line_len = len(line.rstrip('\n\r'))
        N10X.Editor.SetCursorPos((min(left, line_len), top), 0)

    if op == 'c':
        # Enter insert mode with a cursor on each line in the block
        clear_selection()
        try:
            N10X.Editor.ClearMultiCursors()
        except Exception:
            pass
        set_cursor_pos(min(left, len(get_line(top).rstrip('\n\r'))), top)
        for y in range(top + 1, bottom + 1):
            try:
                line_len = len(get_line(y).rstrip('\n\r'))
                N10X.Editor.AddCursor((min(left, line_len), y))
            except Exception:
                pass
        g_change_undo_group = True
        enter_insert_mode(skip_undo_save=True)
        return

    # Finalize undo cursor for operations that don't enter insert mode
    if op != 'y':
        finalize_undo_cursor()

def visual_operation(op):
    if g_mode not in (Mode.VISUAL, Mode.VISUAL_LINE, Mode.VISUAL_BLOCK):
        return
    if g_mode == Mode.VISUAL_BLOCK and op in ('d', 'c', 'y', 'gu', 'gU', 'g~'):
        _apply_visual_block_operation(op)
        if op == 'c':
            return
        enter_normal_mode()
        return

    start, end, linewise = get_visual_range()

    apply_operator_to_range(op, start, end, linewise)
    if op == 'c':
        # apply_operator_to_range('c', ...) already enters insert mode
        return
    enter_normal_mode()

# =============================================================================
# Key Dispatch Helper (for macro replay)
# =============================================================================

def dispatch_key(key):
    """Dispatch a key to the appropriate handler based on current mode."""
    global g_last_insert_text
    if g_mode == Mode.INSERT:
        # First check if it's a special key (Escape, Ctrl combos, etc.)
        result = handle_insert_mode_key(key, track_insert_text=False)
        if result:
            return True
        # For regular characters in insert mode, actually insert them
        char = get_char_from_key(key)
        if char and len(char) == 1 and not key.control and not key.alt:
            N10X.Editor.InsertText(char)
            g_last_insert_text += char
            return True
        # Handle special keys like Backspace, Enter
        if key.key in ('Backspace', 'Back'):
            x, y = get_cursor_pos()
            if x > 0:
                line = get_line(y)
                N10X.Editor.SetLine(y, line[:x-1] + line[x:])
                set_cursor_pos(x - 1, y)
                if g_last_insert_text:
                    g_last_insert_text = g_last_insert_text[:-1]
            return True
        if key.key in ('Return', 'Enter'):
            x, y = get_cursor_pos()
            line = get_line(y)
            N10X.Editor.SetLine(y, line[:x])
            # Insert new line below
            N10X.Editor.SetCursorPos((len(line[:x]), y), 0)
            N10X.Editor.InsertText('\n' + line[x:].rstrip('\n\r'))
            set_cursor_pos(0, y + 1)
            g_last_insert_text += '\n'
            return True
        return False
    elif g_mode == Mode.COMMAND_LINE:
        return handle_command_line_key(key)
    elif g_mode == Mode.REPLACE:
        return handle_replace_mode_key(key)
    elif in_visual_mode():
        return handle_visual_mode_key(key)
    else:
        return handle_normal_mode_key(key)

# =============================================================================
# Normal Mode Key Handler
# =============================================================================

def handle_normal_mode_key(key):
    global g_count, g_operator, g_pending_motion, g_current_register
    global g_recording_macro, g_macro_keys, g_macros, g_mode
    global g_suppress_next_char, g_change_undo_group, g_current_edit, g_last_edit
    global g_jump_index, g_jump_list, g_pre_insert_pos, g_mouse_visual_suppress_frames, g_clear_selection_once
    global g_pending_window_cmd

    # Get the actual character including shift transformations (e.g., Shift+. = >)
    char = normalize_key_char(key)
    is_shifted = key.shift


    if g_debug:
        N10X.Editor.LogTo10XOutput(f"DEBUG handle_normal_mode_key: char='{char}' is_shifted={is_shifted} g_operator='{g_operator}' g_pending_motion='{g_pending_motion}'\n")

    if g_pending_window_cmd:
        g_pending_window_cmd = False
        if char in ('h', 'j', 'k', 'l'):
            cmd = {
                'h': "MovePanelFocusLeft",
                'j': "MovePanelFocusDown",
                'k': "MovePanelFocusUp",
                'l': "MovePanelFocusRight",
            }.get(char)
            if cmd:
                safe_call(N10X.Editor.ExecuteCommand, cmd)
                return True
        # If not a window command, fall through and handle as normal

    # Recording macros
    if g_recording_macro and char != 'q':
        g_macro_keys.append(key)

    # Try user handler first (skip when waiting for a pending motion target)
    if not g_pending_motion:
        result = VimUser.UserHandleCommandModeKey(key)
        # Compare by name to handle module reloading creating different enum classes
        result_name = result.name if hasattr(result, 'name') else str(result)
        if result_name == 'HANDLED':
            return True
        elif result_name == 'PASS_TO_10X':
            return False

    count = get_count()

    # Handle pending motion for operators
    if g_pending_motion:
        if g_pending_motion in ('f', 'F', 't', 'T'):
            target_char = get_char_from_key(key)
            if target_char is not None:
                # Save undo cursor BEFORE motion if there's an operator
                if g_operator and g_operator != 'y':
                    save_undo_cursor()
                start = get_cursor_pos()  # Save position BEFORE motion
                if g_pending_motion == 'f':
                    motion_f(target_char, count)
                elif g_pending_motion == 'F':
                    motion_F(target_char, count)
                elif g_pending_motion == 't':
                    motion_t(target_char, count)
                elif g_pending_motion == 'T':
                    motion_T(target_char, count)
                end = get_cursor_pos()  # Get position AFTER motion
                pending = g_pending_motion
                clear_pending_motion()
                if g_operator:
                    # Apply operator to the motion range
                    if pending in ('f', 't'):
                        apply_operator_to_range(g_operator, start, (end[0] + 1, end[1]), False, skip_undo_save=True)
                    else:  # F, T - backward motions
                        apply_operator_to_range(g_operator, end, start, False, skip_undo_save=True)
                    g_operator = ""
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
            elif char == '~':
                # g~ - toggle case operator
                g_operator = 'g~'
                g_pending_motion = ""
                return True
            elif char == 'd':
                # Go to definition
                try:
                    N10X.Editor.ExecuteCommand("GotoSymbolDefinition")
                except Exception:
                    pass
            elif char == 'f' and is_shifted:
                # Go to file under cursor (gF)
                try:
                    N10X.Editor.ExecuteCommand("FindFile")
                except Exception:
                    pass
            clear_pending_motion()
            return True

        elif g_pending_motion == 'r':
            # Replace character
            target_char = get_char_from_key(key)
            if target_char is not None:
                save_undo_cursor()
                x, y = get_cursor_pos()
                line = get_line(y)
                if x < len(line.rstrip('\n\r')):
                    new_line = line[:x] + target_char + line[x+1:]
                    N10X.Editor.SetLine(y, new_line)
                    # Vim keeps cursor on the replaced character.
                    set_cursor_pos(x, y)
                    # Record for dot-repeat as a replace operation.
                    g_last_edit = {'op': 'c', 'motion': 'r', 'count': 1, 'linewise': False, 'insert_text': target_char}
                finalize_undo_cursor()
            clear_pending_motion()
            return True

        elif g_pending_motion == "'":
            # Jump to mark
            if char == "'":
                # '' - jump to previous location (linewise)
                if g_jump_list:
                    if g_jump_index >= len(g_jump_list):
                        push_jump()
                        g_jump_index = len(g_jump_list) - 2
                    elif g_jump_index > 0:
                        g_jump_index -= 1
                    else:
                        clear_pending_motion()
                        return True

                    if 0 <= g_jump_index < len(g_jump_list):
                        filename, pos = g_jump_list[g_jump_index]
                        current_file = N10X.Editor.GetCurrentFilename()
                        if filename != current_file:
                            N10X.Editor.OpenFile(filename)
                        set_cursor_pos(pos[0], pos[1])
                        motion_caret()
                clear_pending_motion()
                return True
            if char in g_marks:
                filename, pos = g_marks[char]
                current_file = N10X.Editor.GetCurrentFilename()
                if filename != current_file:
                    N10X.Editor.OpenFile(filename)
                push_jump()
                set_cursor_pos(pos[0], pos[1])
                motion_caret()
            clear_pending_motion()
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
            clear_pending_motion()
            return True

        elif g_pending_motion == 'm':
            # Set mark
            if char.isalpha():
                filename = N10X.Editor.GetCurrentFilename()
                g_marks[char] = (filename, get_cursor_pos())
                set_status(f"Mark '{char}' set")
            clear_pending_motion()
            return True

        elif g_pending_motion == '"':
            # Select register - don't clear count, it applies to the next command
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
            # Folding commands (shifted versions first)
            elif char == 'c' and is_shifted:
                # zC - close all folds recursively at cursor
                N10X.Editor.ExecuteCommand("CollapseAllRegionsRecursive")
            elif char == 'o' and is_shifted:
                # zO - open all folds recursively at cursor
                N10X.Editor.ExecuteCommand("ExpandAllRegionsRecursive")
            elif char == 'm' and is_shifted:
                # zM - close all folds
                N10X.Editor.ExecuteCommand("CollapseAllRegions")
            elif char == 'r' and is_shifted:
                # zR - open all folds
                N10X.Editor.ExecuteCommand("ExpandAllRegions")
            elif char == 'c':
                # zc - close fold at cursor
                N10X.Editor.ExecuteCommand("CollapseRegion")
            elif char == 'o':
                # zo - open fold at cursor
                N10X.Editor.ExecuteCommand("ExpandRegion")
            elif char == 'a':
                # za - toggle fold at cursor
                N10X.Editor.ExecuteCommand("ToggleCollapseExpandRegion")
            clear_pending_motion()
            return True

        elif g_pending_motion == '[':
            if char == '[':
                push_jump()
                motion_section_backward(count, end=False)  # [[
                clear_pending_motion()
                return True
            elif char == ']':
                push_jump()
                motion_section_backward(count, end=True)   # []
                clear_pending_motion()
                return True
            else:
                # Not a valid sequence, cancel and re-process
                clear_pending_motion()
                # Fall through to handle the key normally

        elif g_pending_motion == ']':
            if char == ']':
                push_jump()
                motion_section_forward(count, end=False)   # ]]
                clear_pending_motion()
                return True
            elif char == '[':
                push_jump()
                motion_section_forward(count, end=True)    # ][
                clear_pending_motion()
                return True
            else:
                # Not a valid sequence, cancel and re-process
                clear_pending_motion()
                # Fall through to handle the key normally

        elif g_pending_motion == '@':
            # Execute macro
            register = char
            repeat_count = count  # Save count before clearing
            # Clear pending motion BEFORE replaying to avoid keys being misinterpreted
            clear_pending_motion()
            if register in g_macros:
                # Wrap entire macro replay in undo group
                N10X.Editor.PushUndoGroup()
                try:
                    for _ in range(repeat_count):
                        for k in g_macros[register]:
                            dispatch_key(k)
                finally:
                    N10X.Editor.PopUndoGroup()
            else:
                set_status(f"No macro recorded in @{register}")
            return True

        elif g_pending_motion == 'q_start':
            # Start recording macro
            if char.isalpha():
                g_recording_macro = char
                g_macro_keys = []
                set_status(f"Recording @{char}...")
            g_pending_motion = ""
            return True

        elif g_pending_motion in ('d', 'c', 'y', '>', '<', '=', 'gu', 'gU', 'g~'):
            # Text object or motion
            if g_debug:
                N10X.Editor.LogTo10XOutput(f"DEBUG: In operator pending motion, char='{char}', g_operator='{g_operator}'\n")

            # Save cursor position for undo BEFORE any motion (except yank)
            if g_operator != 'y':
                save_undo_cursor()

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
                if g_debug:
                    N10X.Editor.LogTo10XOutput(f"DEBUG: Word motion '{char}' with operator '{g_operator}'\n")
                start = get_cursor_pos()
                motion_char = char.upper() if is_shifted else char
                if char == 'w':
                    # Special case: cw behaves like ce when on a word char, but like w when on whitespace
                    if g_operator == 'c':
                        line = get_line(start[1])
                        char_at_cursor = line[start[0]] if start[0] < len(line.rstrip('\n\r')) else ' '
                        if is_whitespace(char_at_cursor):
                            # On whitespace: cw just clears whitespace up to the word
                            if is_shifted:
                                motion_W(count)
                            else:
                                motion_w(count)
                        else:
                            # On a word: cw acts like ce
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
                # For yank with w/W, avoid including the newline when motion crosses lines.
                if g_operator == 'y' and char in ('w', 'W') and end[1] > start[1]:
                    line = get_line(start[1])
                    end = (len(line.rstrip('\n\r')), start[1])
                # For 'e' motion and 'cw' when on a word char (which uses 'e'), include the character under cursor
                if char == 'e':
                    end = (end[0] + 1, end[1])
                elif char == 'w' and g_operator == 'c':
                    # Only add +1 if we used motion_e (cursor was on a word char, not whitespace)
                    line = get_line(start[1])
                    char_at_cursor = line[start[0]] if start[0] < len(line.rstrip('\n\r')) else ' '
                    if not is_whitespace(char_at_cursor):
                        end = (end[0] + 1, end[1])
                edit_info = {'motion': motion_char, 'count': count}
                apply_operator_to_range(g_operator, start, end, False, edit_info, skip_undo_save=True)
                reset_operator_state()
                return True
            elif char == '$':
                start = get_cursor_pos()
                motion_dollar(count)
                end = get_cursor_pos()
                edit_info = {'motion': '$', 'count': count}
                apply_operator_to_range(g_operator, start, (end[0] + 1, end[1]), False, edit_info, skip_undo_save=True)
                reset_operator_state()
                return True
            elif char == '0':
                start = get_cursor_pos()
                motion_0()
                end = get_cursor_pos()
                edit_info = {'motion': '0', 'count': count}
                apply_operator_to_range(g_operator, end, start, False, edit_info, skip_undo_save=True)
                reset_operator_state()
                return True
            elif char == '^':
                start = get_cursor_pos()
                motion_caret()
                end = get_cursor_pos()
                edit_info = {'motion': '^', 'count': count}
                apply_operator_to_range(g_operator, end, start, False, edit_info, skip_undo_save=True)
                reset_operator_state()
                return True
            elif char == 'g' and is_shifted:
                start = get_cursor_pos()
                motion_G(int(g_count) if g_count else None)
                end = get_cursor_pos()
                edit_info = {'motion': 'G', 'count': count}
                apply_operator_to_range(g_operator, start, (len(get_line(end[1])), end[1]), True, edit_info, skip_undo_save=True)
                reset_operator_state()
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
                edit_info = {'motion': char, 'count': count}
                apply_operator_to_range(g_operator, start, end, linewise, edit_info, skip_undo_save=True)
                reset_operator_state()
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
            elif (len(g_operator) == 1 and char == g_operator) or \
                 (g_operator == 'gu' and char == 'u' and not is_shifted) or \
                 (g_operator == 'gU' and char == 'u' and is_shifted) or \
                 (g_operator == 'g~' and char == '~'):  # dd, cc, yy, >>, <<, ==, gugu, gUgU, g~~
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
                elif g_operator == '=':
                    x, y = get_cursor_pos()
                    apply_operator_to_range('=', (0, y), (len(get_line(y)), y + count - 1), True)
                elif g_operator == 'gu':
                    x, y = get_cursor_pos()
                    apply_operator_to_range('gu', (0, y), (len(get_line(y)), y + count - 1), True)
                elif g_operator == 'gU':
                    x, y = get_cursor_pos()
                    apply_operator_to_range('gU', (0, y), (len(get_line(y)), y + count - 1), True)
                elif g_operator == 'g~':
                    x, y = get_cursor_pos()
                    apply_operator_to_range('g~', (0, y), (len(get_line(y)), y + count - 1), True)
                g_operator = ""
                clear_pending_motion()
                return True
            elif char.isdigit() and (g_count or char != '0'):
                # Accumulate count for motion (e.g., c2w, d3j, c2fe)
                g_count += char
                update_status()
                return True
            g_pending_motion = ""
            return True

        elif g_pending_motion.endswith('i') or g_pending_motion.endswith('a'):
            # Text object - use get_char_from_key for proper character (e.g., " from Shift+')
            inner = g_pending_motion.endswith('i')
            op = g_pending_motion[:-1]
            obj_char = get_char_from_key(key)
            if obj_char is not None:
                obj_range = get_text_object_range(obj_char, inner)
                if obj_range:
                    text_obj = ('i' if inner else 'a') + obj_char
                    edit_info = {'motion': text_obj, 'count': count}
                    apply_operator_to_range(op, obj_range[0], obj_range[1], False, edit_info, skip_undo_save=True)
            reset_operator_state()
            return True

        elif g_pending_motion.endswith('g'):
            # gg motion in operator
            op = g_pending_motion[:-1]
            if char == 'g':
                start = get_cursor_pos()
                target = int(g_count) - 1 if g_count else 0
                edit_info = {'motion': 'gg', 'count': count}
                apply_operator_to_range(op, (0, target), (0, start[1]), True, edit_info, skip_undo_save=True)
            reset_operator_state()
            return True

        elif g_pending_motion.endswith('f'):
            # f motion in operator
            target_char = get_char_from_key(key)
            if target_char is not None:
                op = g_pending_motion[:-1]
                if op != 'y':
                    save_undo_cursor()
                start = get_cursor_pos()
                motion_f(target_char, count)
                end = get_cursor_pos()
                edit_info = {'motion': 'f', 'motion_arg': target_char, 'count': count}
                apply_operator_to_range(op, start, (end[0] + 1, end[1]), False, edit_info, skip_undo_save=True)
                reset_operator_state()
            return True

        elif g_pending_motion.endswith('F'):
            target_char = get_char_from_key(key)
            if target_char is not None:
                op = g_pending_motion[:-1]
                if op != 'y':
                    save_undo_cursor()
                start = get_cursor_pos()
                motion_F(target_char, count)
                end = get_cursor_pos()
                edit_info = {'motion': 'F', 'motion_arg': target_char, 'count': count}
                apply_operator_to_range(op, end, start, False, edit_info, skip_undo_save=True)
                reset_operator_state()
            return True

        elif g_pending_motion.endswith('t'):
            target_char = get_char_from_key(key)
            if target_char is not None:
                op = g_pending_motion[:-1]
                if op != 'y':
                    save_undo_cursor()
                start = get_cursor_pos()
                motion_t(target_char, count)
                end = get_cursor_pos()
                edit_info = {'motion': 't', 'motion_arg': target_char, 'count': count}
                apply_operator_to_range(op, start, (end[0] + 1, end[1]), False, edit_info, skip_undo_save=True)
                reset_operator_state()
            return True

        elif g_pending_motion.endswith('T'):
            target_char = get_char_from_key(key)
            if target_char is not None:
                op = g_pending_motion[:-1]
                if op != 'y':
                    save_undo_cursor()
                start = get_cursor_pos()
                motion_T(target_char, count)
                end = get_cursor_pos()
                edit_info = {'motion': 'T', 'motion_arg': target_char, 'count': count}
                apply_operator_to_range(op, end, start, False, edit_info, skip_undo_save=True)
                reset_operator_state()
            return True

    # ===========================================
    # Handle keys with Control modifier first
    # ===========================================
    if key.control:
        if char == 'v':
            enter_visual_block_mode()
            return True

        if char == 'r':
            N10X.Editor.Redo()
            # Restore cursor position from redo stack
            pos = pop_redo_cursor()
            if pos:
                set_cursor_pos(pos[0], pos[1])
            clear_selection()
            return True

        if char == 'd':
            try:
                visible = N10X.Editor.GetVisibleLineCount()
                x, y = get_cursor_pos()
                motion_j(visible // 2)
                N10X.Editor.ScrollCursorIntoView()
            except Exception:
                pass
            return True

        if char == 'u':
            try:
                visible = N10X.Editor.GetVisibleLineCount()
                motion_k(visible // 2)
                N10X.Editor.ScrollCursorIntoView()
            except Exception:
                pass
            return True

        if char == 'f':
            try:
                visible = N10X.Editor.GetVisibleLineCount()
                motion_j(visible)
                N10X.Editor.ScrollCursorIntoView()
            except Exception:
                pass
            return True

        if char == 'b':
            try:
                visible = N10X.Editor.GetVisibleLineCount()
                motion_k(visible)
                N10X.Editor.ScrollCursorIntoView()
            except Exception:
                pass
            return True

        if char == 'e':
            try:
                scroll = N10X.Editor.GetScrollLine()
                N10X.Editor.SetScrollLine(scroll + count)
            except Exception:
                pass
            return True

        if char == 'a':
            # Increment number under cursor
            _change_number_under_cursor(count)
            return True

        if char == 'x':
            # Decrement number under cursor
            _change_number_under_cursor(-count)
            return True

        if char == 'y':
            try:
                scroll = N10X.Editor.GetScrollLine()
                N10X.Editor.SetScrollLine(max(0, scroll - count))
            except Exception:
                pass
            return True

        if char == 'g':
            # Show file info
            try:
                filename = N10X.Editor.GetCurrentFilename()
                x, y = get_cursor_pos()
                line_count = get_line_count()
                percent = int((y + 1) * 100 / line_count) if line_count > 0 else 0
                modified = " [Modified]" if N10X.Editor.IsModified() else ""
                set_status(f'"{filename}"{modified} line {y + 1} of {line_count} --{percent}%-- col {x + 1}')
            except Exception:
                pass
            return True

        if char == 'w':
            # Window prefix (Ctrl+W)
            g_pending_window_cmd = True
            return True

        if char == 'o':
            if g_jump_list:
                # If we're past the end (at a new position after a jump),
                # save current position first so Ctrl+I can return here
                if g_jump_index >= len(g_jump_list):
                    push_jump()
                    # Now index is past end again, set it to second-to-last
                    # so we jump to the entry before the one we just pushed
                    g_jump_index = len(g_jump_list) - 2
                elif g_jump_index > 0:
                    g_jump_index -= 1
                else:
                    # Already at the beginning, can't go back further
                    return True

                if g_jump_index >= 0 and g_jump_index < len(g_jump_list):
                    filename, pos = g_jump_list[g_jump_index]
                    current_file = N10X.Editor.GetCurrentFilename()
                    if filename != current_file:
                        N10X.Editor.OpenFile(filename)
                    set_cursor_pos(pos[0], pos[1])
                return True
            # No jump history - pass to 10x
            return False

        if char == 'i':
            if g_jump_index < len(g_jump_list) - 1:
                g_jump_index += 1
                filename, pos = g_jump_list[g_jump_index]
                current_file = N10X.Editor.GetCurrentFilename()
                if filename != current_file:
                    N10X.Editor.OpenFile(filename)
                set_cursor_pos(pos[0], pos[1])
                return True
            # No forward jump history - pass to 10x
            return False

        if char == ']':
            # Go to definition (like ctags jump)
            push_jump()
            try:
                N10X.Editor.ExecuteCommand("GotoSymbolDefinition")
            except Exception:
                pass
            g_mouse_visual_suppress_frames = 5
            g_clear_selection_once = True
            return True

        if char == 't':
            # Return from tag (go back in jump list)
            if g_jump_index > 0:
                g_jump_index -= 1
                filename, pos = g_jump_list[g_jump_index]
                current_file = N10X.Editor.GetCurrentFilename()
                if filename != current_file:
                    N10X.Editor.OpenFile(filename)
                set_cursor_pos(pos[0], pos[1])
                return True
            # No jump history - pass to 10x
            return False

        if char == '[':
            # Ctrl+[ is Escape
            enter_normal_mode()
            return True

        # Control key pressed but no handler matched - pass to 10x
        return False

    # ===========================================
    # Handle keys with Alt modifier
    # ===========================================
    if key.alt:
        # No explicit Alt bindings - pass to 10x
        return False

    # ===========================================
    # Handle plain keys (no Ctrl, no Alt)
    # Shift variants are handled within individual handlers
    # ===========================================

    # Count prefix (only unshifted digits - shifted digits are symbols like *, #, $, etc.)
    if char.isdigit() and not is_shifted and (g_count or char != '0'):
        g_count += char
        update_status()
        return True


    # Operators (shifted versions are shortcuts)
    if char == 'd':
        if g_debug:
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
            if g_debug:
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

    if char == '=':
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
            save_undo_cursor()
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
            finalize_undo_cursor()
        else:
            motion_j(count)
        return True

    if char == 'k':
        if is_shifted:
            # K - not supported (no documented command for showing documentation)
            pass
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
        clear_count()
        return True

    if char == '^':
        motion_caret()
        return True

    if char == '_':
        motion_underscore(count)
        return True

    if char == '+':
        motion_plus(count)
        return True

    if char == '-':
        motion_minus(count)
        return True

    if char == '|':
        motion_pipe(count)
        return True

    if char == '$':
        motion_dollar(count)
        return True

    if char == 'g':
        if is_shifted:
            motion_G(int(g_count) if g_count else None)
            clear_count()
        else:
            g_pending_motion = 'g'
        return True

    if char == '%':
        motion_percent()
        return True

    if char == '{' or (char == '[' and is_shifted):
        push_jump()
        motion_brace_backward(count)
        return True

    if char == '}' or (char == ']' and is_shifted):
        push_jump()
        motion_brace_forward(count)
        return True

    if char == '[' and not is_shifted:
        g_pending_motion = '['
        return True

    if char == ']' and not is_shifted:
        g_pending_motion = ']'
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

    if char == ';' and not is_shifted:
        motion_semicolon(count)
        return True

    if char == ':' or (char == ';' and is_shifted):
        enter_command_line_mode(':')
        return True

    if char == ',':
        motion_comma(count)
        return True

    # Mode changes
    if char == 'i':
        g_suppress_next_char = True
        g_pre_insert_pos = get_cursor_pos()
        if is_shifted:
            motion_caret()
            g_current_edit = {'op': 'i', 'motion': 'I', 'count': 1, 'linewise': False}
            enter_insert_mode()
        else:
            g_current_edit = {'op': 'i', 'motion': 'i', 'count': 1, 'linewise': False}
            enter_insert_mode()
        return True

    if char == 'a':
        g_suppress_next_char = True
        if is_shifted:
            # A - append at end of line, use API directly to bypass normal mode clamping
            y = get_cursor_pos()[1]
            line = get_line(y)
            line_len = len(line.rstrip('\n\r'))
            g_pre_insert_pos = (max(0, line_len - 1), y)
            N10X.Editor.SetCursorPos((line_len, y), 0)
            g_current_edit = {'op': 'i', 'motion': 'A', 'count': 1, 'linewise': False}
            enter_insert_mode()
        else:
            g_pre_insert_pos = get_cursor_pos()  # Save position BEFORE moving for append
            x, y = get_cursor_pos()
            line = get_line(y)
            line_len = len(line.rstrip('\n\r'))
            # Use API directly to bypass normal mode clamping (allows cursor past last char)
            N10X.Editor.SetCursorPos((min(x + 1, line_len), y), 0)
            g_current_edit = {'op': 'i', 'motion': 'a', 'count': 1, 'linewise': False}
            enter_insert_mode()
        return True

    if char == 'o':
        x, y = get_cursor_pos()
        line = get_line(y)
        # Get indentation from current line
        indent = ""
        for c in line:
            if c in ' \t':
                indent += c
            else:
                break
        # Save cursor position for undo BEFORE any edits
        save_undo_cursor()
        # Group the newline insertion and subsequent typing as one undo operation
        N10X.Editor.PushUndoGroup()
        g_change_undo_group = True
        if is_shifted:
            # O - open line above: move to start of line, insert indent + newline
            N10X.Editor.SetCursorPos((0, y), 0)
            N10X.Editor.InsertText(indent + '\n')
            N10X.Editor.SetCursorPos((len(indent), y), 0)
            g_suppress_next_char = True
            g_current_edit = {'op': 'i', 'motion': 'O', 'count': 1, 'linewise': False}
            enter_insert_mode(skip_undo_save=True)
        else:
            # o - open line below: move to actual end of line (past last char), insert newline + indent
            line_len = len(line.rstrip('\n\r'))
            N10X.Editor.SetCursorPos((line_len, y), 0)  # Use API directly to avoid normal mode clamping
            N10X.Editor.InsertText('\n' + indent)
            # Cursor should now be on the new line after the indent
            g_suppress_next_char = True
            g_current_edit = {'op': 'i', 'motion': 'o', 'count': 1, 'linewise': False}
            enter_insert_mode(skip_undo_save=True)
        return True

    if char == 'v':
        if is_shifted:
            enter_visual_line_mode()
        else:
            enter_visual_mode()
        return True

    if char == '/' and not is_shifted:
        # Forward search
        if g_use_10x_find_panel:
            N10X.Editor.SetReverseFind(False)
            N10X.Editor.ExecuteCommand("FindInFile")
        else:
            enter_command_line_mode('/')
        return True

    if char == '?' or (char == '/' and is_shifted):
        # Reverse search
        if g_use_10x_find_panel:
            N10X.Editor.SetReverseFind(True)
            N10X.Editor.ExecuteCommand("FindInFile")
        else:
            enter_command_line_mode('?')
        return True

    # Editing commands
    if char == 'x':
        save_undo_cursor()
        if is_shifted:
            # Delete char before cursor
            x, y = get_cursor_pos()
            if x > 0:
                line = get_line(y)
                deleted = line[x-1]
                N10X.Editor.SetLine(y, line[:x-1] + line[x:])
                yank_to_register(deleted)
                set_cursor_pos(x - 1, y)
                g_last_edit = {'op': 'd', 'motion': 'X', 'count': count}
        else:
            # Delete char under cursor
            x, y = get_cursor_pos()
            line = get_line(y)
            if x < len(line.rstrip('\n\r')):
                deleted = line[x]
                N10X.Editor.SetLine(y, line[:x] + line[x+1:])
                yank_to_register(deleted)
                g_last_edit = {'op': 'd', 'motion': 'x', 'count': count}
        finalize_undo_cursor()
        return True

    if char == 'r':
        if is_shifted:
            # R - enter replace mode with undo grouping
            save_undo_cursor()
            N10X.Editor.PushUndoGroup()
            g_change_undo_group = True
            g_current_edit = {'op': 'c', 'motion': 's', 'count': 0, 'linewise': False}
            enter_mode(Mode.REPLACE)
        else:
            g_pending_motion = 'r'
        return True

    if char == 's':
        if is_shifted:
            # Change entire line
            operator_cc(count)
        else:
            # Substitute character - delete and enter insert mode
            x, y = get_cursor_pos()
            line = get_line(y)
            # Save cursor position for undo BEFORE any edits
            save_undo_cursor()
            N10X.Editor.PushUndoGroup()
            g_change_undo_group = True
            if x < len(line.rstrip('\n\r')):
                deleted = line[x:x+count]
                N10X.Editor.SetLine(y, line[:x] + line[x+count:])
                yank_to_register(deleted)
            g_suppress_next_char = True
            g_current_edit = {'op': 'c', 'motion': 's', 'count': count, 'linewise': False}
            enter_insert_mode(skip_undo_save=True)
        return True

    if char == 'p':
        # Paste
        linewise = get_register_linewise()
        text = get_register()
        if text:
            save_undo_cursor()
            x, y = get_cursor_pos()
            if is_shifted:
                # Paste before (P)
                if linewise:
                    # Linewise paste - insert above current line
                    set_cursor_pos(0, y)
                    insert_text(text)
                    set_cursor_pos(0, y)
                    motion_caret()
                else:
                    insert_text(text)
            else:
                # Paste after (p)
                if linewise:
                    # Linewise paste - insert below current line
                    line = get_line(y)
                    line_len = len(line.rstrip('\n\r'))
                    # Move to end of line content (use API directly to avoid normal mode clamping)
                    N10X.Editor.SetCursorPos((line_len, y), 0)
                    # Insert newline + the text without its trailing newline
                    text_to_insert = text.rstrip('\n')
                    insert_text('\n' + text_to_insert)
                    set_cursor_pos(0, y + 1)
                    motion_caret()
                else:
                    line = get_line(y)
                    line_len = len(line.rstrip('\n\r'))
                    # Use API directly to bypass normal mode clamping
                    N10X.Editor.SetCursorPos((min(x + 1, line_len), y), 0)
                    insert_text(text)
            finalize_undo_cursor()
        return True

    # Undo
    if char == 'u':
        if is_shifted:
            # Undo line (just undo for now)
            N10X.Editor.Undo()
        else:
            N10X.Editor.Undo()
            # Restore cursor position from before the edit
            pos = pop_undo_cursor()
            if pos:
                set_cursor_pos(pos[0], pos[1])
        clear_selection()
        return True

    # Search
    if char == 'n':
        if is_shifted:
            # N - find previous match
            N10X.Editor.ExecuteCommand("FindInFilePrev")
        else:
            # n - find next match
            # Move cursor right first to avoid finding the same word
            x, y = get_cursor_pos()
            line = get_line(y)
            if x < len(line.rstrip('\n\r')):
                set_cursor_pos(x + 1, y)
            N10X.Editor.ExecuteCommand("FindInFileNext")
        move_cursor_to_selection_start()
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

    # Repeat last edit
    if char == '.':
        if g_last_edit and isinstance(g_last_edit, dict):
            _repeat_last_edit(count)
        return True

    # Macros
    if char == 'q':
        if g_recording_macro:
            g_macros[g_recording_macro] = list(g_macro_keys)  # q is already excluded by recording check
            set_status(f"Recorded macro @{g_recording_macro}")
            g_recording_macro = ""
            g_macro_keys = []
        else:
            g_pending_motion = 'q_start'
        return True

    if char == '@':
        g_pending_motion = '@'
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

    # Pass through function keys and other special keys to 10x
    if is_function_key(key):
        return False

    clear_count()
    return True

# =============================================================================
# Visual Mode Key Handler
# =============================================================================

def _visual_motion(motion_func, *args, clear_count_flag=True):
    """Execute a motion in visual mode and update selection."""
    motion_func(*args)
    update_visual_selection()
    if clear_count_flag:
        clear_count()
    return True

def handle_visual_mode_key(key):
    global g_count, g_operator, g_pending_motion, g_mode, g_visual_start, g_current_register

    # Recording macros - also capture visual mode keys
    if g_recording_macro:
        g_macro_keys.append(key)

    # Get the actual character including shift transformations (e.g., Shift+. = >)
    char = normalize_key_char(key)
    is_shifted = key.shift
    count = get_count()

    # Escape to normal mode
    if is_escape_key(key, char):
        g_pending_motion = ""
        enter_normal_mode()
        return True

    # Handle pending motions in visual mode
    if g_pending_motion == 'v[':
        motion_section_backward(count, end=(char == ']'))
        update_visual_selection()
        clear_pending_motion()
        return True

    if g_pending_motion == 'v]':
        motion_section_forward(count, end=(char == '['))
        update_visual_selection()
        clear_pending_motion()
        return True

    # Handle f/F/t/T pending motions in visual mode
    if g_pending_motion in ('vf', 'vF', 'vt', 'vT'):
        target_char = get_char_from_key(key)
        if target_char is not None:
            motion_map = {'f': motion_f, 'F': motion_F, 't': motion_t, 'T': motion_T}
            motion_map[g_pending_motion[1]](target_char, count)
            update_visual_selection()
        clear_pending_motion()
        return True

    # Handle register selection pending motion
    if g_pending_motion == '"':
        g_current_register = char
        clear_pending_motion(clear_count_flag=False)
        return True

    # Register selection
    if char == '"':
        g_pending_motion = '"'
        return True

    # Count (only unshifted digits)
    if char.isdigit() and not is_shifted and (g_count or char != '0'):
        g_count += char
        return True

    # Simple motions with count
    simple_motions = {'h': motion_h, 'j': motion_j, 'k': motion_k, 'l': motion_l,
                      '$': motion_dollar, '_': motion_underscore, '+': motion_plus,
                      '-': motion_minus, '|': motion_pipe}
    if char in simple_motions:
        return _visual_motion(simple_motions[char], count)

    # Motions without count argument
    if char == '0':
        return _visual_motion(motion_0)
    if char == '^':
        return _visual_motion(motion_caret, clear_count_flag=False)
    if char == '%':
        if g_mode == Mode.VISUAL_LINE:
            x, y = get_cursor_pos()
            line = get_line(y)
            brace_x = None
            for i, c in enumerate(line):
                if c == '{' or c == '}':
                    brace_x = i
                    break
            if brace_x is not None:
                set_cursor_pos(brace_x, y)
                motion_percent()
                update_visual_selection()
                clear_count()
                return True
            # Restore cursor if no brace found
            set_cursor_pos(x, y)
        return _visual_motion(motion_percent, clear_count_flag=False)

    # Shifted/unshifted motion pairs
    shift_motion_pairs = {
        'w': (motion_w, motion_W),
        'b': (motion_b, motion_B),
        'e': (motion_e, motion_E),
    }
    if char in shift_motion_pairs:
        motion = shift_motion_pairs[char][1] if is_shifted else shift_motion_pairs[char][0]
        return _visual_motion(motion, count)

    # g/G motions
    if char == 'g':
        motion = motion_G if is_shifted else motion_gg
        return _visual_motion(motion, int(g_count) if g_count else None)

    # f/F/t/T start pending motion
    if char == 'f':
        g_pending_motion = 'vF' if is_shifted else 'vf'
        return True
    if char == 't':
        g_pending_motion = 'vT' if is_shifted else 'vt'
        return True

    # Repeat motions
    if char == ';' and not is_shifted:
        return _visual_motion(motion_semicolon, count)
    if char == ',':
        return _visual_motion(motion_comma, count)

    # Brace/bracket motions
    if char == '{' or (char == '[' and is_shifted):
        return _visual_motion(motion_brace_backward, count)
    if char == '}' or (char == ']' and is_shifted):
        return _visual_motion(motion_brace_forward, count)

    if char == '[' and not is_shifted:
        g_pending_motion = 'v['
        return True

    if char == ']' and not is_shifted:
        g_pending_motion = 'v]'
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

    if char == '=':
        visual_operation('=')
        return True

    if char == 'u':
        if is_shifted:
            visual_operation('gU')
        else:
            visual_operation('gu')
        return True

    if char == '~':
        # Toggle case of selection
        start, end, _linewise = get_visual_range()
        set_selection(start, end)
        text = get_selection()
        if text:
            toggled = text.swapcase()
            delete_selection()
            insert_text(toggled)
        enter_normal_mode()
        return True

    # Visual block insert/append
    if g_mode == Mode.VISUAL_BLOCK:
        if char == 'i' and is_shifted:
            # I - Insert at start of block on all lines
            start = g_visual_start
            end = get_cursor_pos()
            start, end = ordered_range(start, end)
            col = min(start[0], end[0])

            # Add cursors at the start column for each line
            clear_selection()
            set_cursor_pos(col, start[1])
            for line_y in range(start[1] + 1, end[1] + 1):
                try:
                    N10X.Editor.AddCursor((col, line_y))
                except Exception:
                    pass
            enter_insert_mode()
            return True

        if char == 'a' and is_shifted:
            # A - Append at end of block on all lines
            start = g_visual_start
            end = get_cursor_pos()
            start, end = ordered_range(start, end)
            col = max(start[0], end[0]) + 1

            # Add cursors at the end column for each line
            clear_selection()
            set_cursor_pos(col, start[1])
            for line_y in range(start[1] + 1, end[1] + 1):
                try:
                    N10X.Editor.AddCursor((col, line_y))
                except Exception:
                    pass
            enter_insert_mode()
            return True

    # Join
    if char == 'j' and is_shifted:
        start = g_visual_start
        end = get_cursor_pos()
        start, end = ordered_range(start, end)
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

    # Pass through function keys and other special keys to 10x
    if is_function_key(key):
        return False

    clear_count()
    return True

# =============================================================================
# Insert Mode Key Handler
# =============================================================================

def handle_insert_mode_key(key, track_insert_text=True):
    global g_exit_sequence, g_last_insert_text

    # Use lowercase for single-char comparisons (consistent with handle_normal_mode_key)
    char = get_char_from_key(key)
    if char is None:
        char = key.key
    if len(char) == 1 and char.isalpha():
        char = char.lower()

    # Note: macro recording for insert mode is done in on_key before this is called

    # Try user handler first
    result = VimUser.UserHandleInsertModeKey(key)
    # Compare by name to handle module reloading creating different enum classes
    result_name = result.name if hasattr(result, 'name') else str(result)
    if result_name == 'HANDLED':
        return True
    elif result_name == 'PASS_TO_10X':
        return False

    # Escape
    if is_escape_key(key, char):
        enter_normal_mode()
        return True

    # Ctrl+W - delete word
    if key.control and char == 'w':
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
    if key.control and char == 'u':
        x, y = get_cursor_pos()
        line = get_line(y)
        N10X.Editor.SetLine(y, line[x:])
        set_cursor_pos(0, y)
        return True

    # Ctrl+H - backspace
    if key.control and char == 'h':
        return False  # Let 10x handle backspace

    # Ctrl+O - one normal mode command
    if key.control and char == 'o':
        # Not implemented - would need state tracking
        return True

    # Track inserted text for . repeat (only when requested)
    if track_insert_text and len(char) == 1 and not key.control and not key.alt:
        g_last_insert_text += char

    return False  # Let 10x handle normal typing

# =============================================================================
# Replace Mode Key Handler
# =============================================================================

def handle_replace_mode_key(key):
    global g_last_insert_text
    # Recording macros - also capture replace mode keys
    if g_recording_macro:
        g_macro_keys.append(key)

    # Use actual character including shift transformations (e.g., Shift+1 = !).
    # This also normalizes letter case based on shift state.
    char = get_char_from_key(key)
    if char is None:
        char = key.key

    if is_escape_key(key, char):
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
        g_last_insert_text += char
        return True

    return False

# =============================================================================
# Command Line Mode Key Handler
# =============================================================================

def handle_command_line_key(key):
    global g_command_line, g_command_history_index

    # Recording macros - also capture command line keys
    if g_recording_macro:
        g_macro_keys.append(key)

    # Get the actual character including shift transformations (e.g., Shift+1 = !)
    char = get_char_from_key(key)
    if char is None:
        char = key.key  # Fallback for special keys like Escape, Enter, etc.

    if is_escape_key(key, char):
        enter_normal_mode()
        return True

    if char == 'Return' or char == 'Enter':
        if g_command_line_type == ':':
            execute_command(g_command_line)
        elif g_command_line_type == '/':
            # Forward search
            if g_command_line:
                N10X.Editor.SetFindText(g_command_line, False, False, False, False)
                N10X.Editor.ExecuteCommand("FindInFileNext")
                move_cursor_to_selection_start()
        elif g_command_line_type == '?':
            # Reverse search
            if g_command_line:
                N10X.Editor.SetFindText(g_command_line, False, False, False, True)
                N10X.Editor.ExecuteCommand("FindInFilePrev")
                move_cursor_to_selection_start()
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
        # Command history navigation
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
        return True

    if char == 'Down':
        if g_command_history_index > 0:
            g_command_history_index -= 1
            g_command_line = g_command_history[-(g_command_history_index+1)]
            set_status(g_command_line_type + g_command_line)
        elif g_command_history_index == 0:
            g_command_history_index = -1
            g_command_line = ""
            set_status(g_command_line_type)
        return True

    # Ctrl+W - delete word
    if key.control and char == 'w':
        words = g_command_line.rsplit(None, 1)
        g_command_line = words[0] if len(words) > 1 else ""
        set_status(g_command_line_type + g_command_line)
        return True

    # Ctrl+U - clear line
    if key.control and char == 'u':
        g_command_line = ""
        set_status(g_command_line_type)
        return True

    # Regular character input - char already has correct case from on_char_key
    if len(char) == 1 and not key.control and not key.alt:
        g_command_line += char
        set_status(g_command_line_type + g_command_line)
        return True

    # Pass through function keys and other special keys to 10x
    if is_function_key(key):
        return False

    return True

# =============================================================================
# Main Key Handler
# =============================================================================

def on_key(key_str, shift, control, alt):
    if not is_vim_enabled():
        return False

    if not N10X.Editor.TextEditorHasFocus():
        return False

    # Ignore modifier-only key events (Shift, Control, Alt pressed alone)
    if key_str in ('Shift', 'Control', 'Alt', 'LeftShift', 'RightShift',
                   'LeftControl', 'RightControl', 'LeftAlt', 'RightAlt'):
        return True

    if g_debug:
        N10X.Editor.LogTo10XOutput(f"on_key: '{key_str}' shift={shift} ctrl={control} alt={alt}\n")

    # Escape always returns to normal mode
    if key_str == 'Escape':
        # Record Escape for macros when in insert/replace mode
        if g_recording_macro and g_mode in (Mode.INSERT, Mode.REPLACE):
            key = Key(key_str, shift, control, alt)
            g_macro_keys.append(key)
        enter_normal_mode()
        return True

    # In insert mode, only handle Escape and Ctrl combinations
    if g_mode == Mode.INSERT:
        global g_last_insert_text
        # Record keys for macro even in insert mode
        if g_recording_macro:
            key = Key(key_str, shift, control, alt)
            g_macro_keys.append(key)
        if control:
            key = Key(key_str, shift, control, alt)
            return handle_insert_mode_key(key)
        # Track backspace for dot repeat
        if key_str in ('Backspace', 'Back') and g_last_insert_text:
            g_last_insert_text = g_last_insert_text[:-1]
        # Track Enter/Return for dot repeat
        elif key_str in ('Return', 'Enter'):
            g_last_insert_text += '\n'
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
        elif in_visual_mode():
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
    elif in_visual_mode():
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

    # In insert mode, track text for dot repeat, then let 10x handle typing
    if g_mode == Mode.INSERT:
        global g_last_insert_text, g_exit_sequence
        # Check exit sequence (e.g., "jk") on actual typed characters.
        if g_exit_sequence_chars and len(char) == 1:
            g_exit_sequence += char
            if g_exit_sequence == g_exit_sequence_chars:
                # Current char is not inserted yet; remove prior sequence chars.
                chars_to_delete = len(g_exit_sequence_chars) - 1
                if chars_to_delete > 0:
                    x, y = get_cursor_pos()
                    line = get_line(y)
                    if x >= chars_to_delete:
                        new_line = line[:x - chars_to_delete] + line[x:]
                        N10X.Editor.SetLine(y, new_line)
                        set_cursor_pos(x - chars_to_delete, y)
                    if g_last_insert_text:
                        g_last_insert_text = g_last_insert_text[:-chars_to_delete]
                enter_normal_mode()
                return True
            if not g_exit_sequence_chars.startswith(g_exit_sequence):
                g_exit_sequence = char if g_exit_sequence_chars.startswith(char) else ""

        g_last_insert_text += char
        return False

    # For non-insert modes, on_key handles everything (it has shift info)
    # Return True here to prevent 10x from inserting characters
    # This is a fallback in case on_key didn't intercept the key
    return True

# =============================================================================
# Initialization
# =============================================================================

def is_vim_enabled():
    return get_setting_bool("Vim", False)

def load_settings():
    global g_exit_sequence_chars, g_filtered_history, g_use_10x_find_panel

    g_exit_sequence_chars = get_setting_str("VimExitInsertModeCharSequence", "")
    # Filtered history defaults to True - only disable if explicitly set to false
    val = get_setting_str("VimCommandlineFilteredHistory", "true")
    g_filtered_history = val.lower() not in ("false", "0", "no")
    # Use 10x find panel for / and ? searches (default True for backward compatibility)
    val = get_setting_str("VimUse10xFindPanel", "true")
    g_use_10x_find_panel = val.lower() not in ("false", "0", "no")

def on_settings_changed():
    load_settings()

def initialize():
    global g_initialized

    if not is_vim_enabled():
        return

    if g_initialized:
        return

    g_initialized = True
    load_settings()
    enter_normal_mode()

    # Remove any existing callbacks first (in case of script reload)
    try:
        N10X.Editor.RemoveOnInterceptKeyFunction(on_key)
    except Exception:
        pass
    try:
        N10X.Editor.RemoveOnInterceptCharKeyFunction(on_char_key)
    except Exception:
        pass
    try:
        N10X.Editor.RemoveUpdateFunction(on_update)
    except Exception:
        pass
    # Register callbacks
    N10X.Editor.AddOnInterceptCharKeyFunction(on_char_key)
    N10X.Editor.AddOnInterceptKeyFunction(on_key)
    N10X.Editor.AddOnSettingsChangedFunction(on_settings_changed)
    N10X.Editor.AddUpdateFunction(on_update)

# IMPORTANT: Do not remove this __name__ guard. It is required due to how 10x
# loads VimUser.py and Vim.py - VimUser.py imports Vim.py, and without this guard
# the callbacks would be registered multiple times.
# NOTE: We must use CallOnMainThread because GetSetting cannot be called from
# the script loading thread - it will raise "Error calling GetSetting from thread".
if __name__ == "__main__":
    N10X.Editor.CallOnMainThread(initialize)
