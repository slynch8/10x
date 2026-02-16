import json
import os
import tempfile
import time
import traceback

import N10X

try:
    import VimAI as Vim
except Exception:
    import Vim as Vim


g_OperationSleepDelay = 0
g_TestSuiteInstance = None


class SkipTest(Exception):
    pass


class Function:
    def __init__(self, fn):
        self.m_Function = fn
        self.m_Ran = False

    def Update(self):
        if not self.m_Ran:
            self.m_Ran = True
            self.m_Function()
        return True


class Sleep:
    def __init__(self, frames):
        self.m_Frames = max(0, int(frames))

    def Update(self):
        if self.m_Frames <= 0:
            return True
        self.m_Frames -= 1
        return self.m_Frames <= 0


class WaitUntil:
    def __init__(self, predicate, timeout_frames, description):
        self.m_Predicate = predicate
        self.m_TimeoutFrames = max(1, int(timeout_frames))
        self.m_Description = description
        self.m_Frame = 0

    def Update(self):
        if self.m_Predicate():
            return True
        self.m_Frame += 1
        if self.m_Frame >= self.m_TimeoutFrames:
            raise AssertionError("WaitUntil timeout: " + self.m_Description)
        return False


class MultiStageTest:
    def init(self):
        self.m_Operations = []
        self.m_Index = 0
        self.m_FirstUpdate = True

    def Add(self, operation):
        global g_OperationSleepDelay
        if g_OperationSleepDelay:
            self.m_Operations.append(Sleep(g_OperationSleepDelay))

        if callable(operation):
            operation = Function(operation)

        self.m_Operations.append(operation)

    def Update(self):
        if self.m_FirstUpdate:
            self.m_FirstUpdate = False
            return False

        if self.m_Operations and self.m_Operations[self.m_Index].Update():
            self.m_Index += 1

        return self.m_Index == len(self.m_Operations)


def _env_bool(name, default=False):
    value = os.environ.get(name, "")
    if value == "":
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _mode_name(mode):
    return mode.name if hasattr(mode, "name") else str(mode)


def _token(key, shift=False, control=False, alt=False):
    return (key, shift, control, alt)


def _normalize_buffer_text(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def _resolve_typed_char(ch):
    if "A" <= ch <= "Z":
        return (ch.lower(), True)
    shifted_symbol_map = {
        "!": "1",
        "@": "2",
        "#": "3",
        "$": "4",
        "%": "5",
        "^": "6",
        "&": "7",
        "*": "8",
        "(": "9",
        ")": "0",
        "_": "-",
        "+": "=",
        "{": "[",
        "}": "]",
        "|": "\\",
        ":": ";",
        "\"": "'",
        "<": ",",
        ">": ".",
        "?": "/",
        "~": "`",
    }
    if ch in shifted_symbol_map:
        return (shifted_symbol_map[ch], True)
    return (ch, False)


class VimTestContext:
    def __init__(self, suite):
        self.suite = suite

    def _safe_clear_multicursors(self):
        try:
            N10X.Editor.ClearMultiCursors()
        except Exception:
            pass

    def reset_vim_state(self):
        Vim.g_mode = Vim.Mode.NORMAL
        Vim.g_count = ""
        Vim.g_operator = ""
        Vim.g_pending_motion = ""
        Vim.g_command_line = ""
        Vim.g_command_line_type = ""
        Vim.g_current_register = "\""
        Vim.g_marks = {}
        Vim.g_last_edit = None
        Vim.g_last_insert_text = ""
        Vim.g_current_edit = None
        Vim.g_visual_start = (0, 0)
        Vim.g_recording_macro = ""
        Vim.g_macros = {}
        Vim.g_macro_keys = []
        Vim.g_jump_list = []
        Vim.g_jump_index = -1
        Vim.g_last_f_char = ""
        Vim.g_last_f_direction = 1
        Vim.g_last_t_mode = False
        Vim.g_insert_start_pos = (0, 0)
        Vim.g_pre_insert_pos = (0, 0)
        Vim.g_exit_sequence = ""
        Vim.g_command_history = []
        Vim.g_command_history_index = -1
        Vim.g_last_visual_start = (0, 0)
        Vim.g_last_visual_end = (0, 0)
        Vim.g_last_visual_mode = Vim.Mode.VISUAL
        Vim.g_suppress_next_char = False
        Vim.g_change_undo_group = False
        Vim.g_pending_undo_before = None
        Vim.g_undo_cursor_stacks = {}
        Vim.g_redo_cursor_stacks = {}
        Vim.g_find_panel_was_open = False
        Vim.g_mouse_visual_suppress_frames = 0
        Vim.g_mouse_visual_active = False
        Vim.g_clear_selection_once = False
        Vim.g_pending_window_cmd = False
        Vim.g_desired_col = None
        Vim.g_command_visual_range = None
        Vim.g_registers = {"\"": "", "0": ""}
        Vim.g_registers_linewise = {"\"": False, "0": False}
        Vim.g_registers_blockwise = {"\"": False, "0": False}
        Vim.enter_normal_mode()
        Vim.clear_selection()
        self._safe_clear_multicursors()

    def _buffer_end_pos(self):
        line_count = max(1, Vim.get_line_count())
        end_y = line_count - 1
        end_line = Vim.get_line(end_y)
        return (len(end_line), end_y)

    def set_buffer_text(self, text):
        Vim.enter_normal_mode()
        Vim.clear_selection()
        self._safe_clear_multicursors()

        try:
            N10X.Editor.SetFileText(text)
            Vim.set_cursor_pos_raw((0, 0), update_desired=False)
            Vim.enter_normal_mode()
            Vim.clear_selection()
            self._safe_clear_multicursors()
            return
        except Exception:
            pass

        try:
            N10X.Editor.SetSelection((0, 0), self._buffer_end_pos(), 0)
            Vim.delete_selection()
        except Exception:
            # Fallback: best effort clear.
            try:
                N10X.Editor.SetLine(0, "")
            except Exception:
                pass

        Vim.set_cursor_pos_raw((0, 0), update_desired=False)
        if text:
            Vim.insert_text(text)
            Vim.set_cursor_pos_raw((0, 0), update_desired=False)

        Vim.enter_normal_mode()
        Vim.clear_selection()
        self._safe_clear_multicursors()

    def reset(self, text, cursor=(0, 0)):
        N10X.Editor.OpenFile(self.suite.m_TestFilePath)
        self.reset_vim_state()
        self.set_buffer_text(text)
        Vim.set_cursor_pos_raw(cursor, update_desired=True)
        Vim.enter_normal_mode()
        Vim.on_update()

    def key(self, key, shift=False, control=False, alt=False, repeat=1):
        handled = False
        for _ in range(max(1, int(repeat))):
            handled = Vim.on_key(key, shift, control, alt)
            if not handled:
                handled = Vim.dispatch_key(Vim.Key(key, shift=shift, control=control, alt=alt))
            Vim.on_update()
        return handled

    def run_tokens(self, tokens):
        for token in tokens:
            if isinstance(token, tuple):
                if len(token) == 1:
                    self.key(token[0])
                else:
                    key = token[0]
                    shift = bool(token[1]) if len(token) > 1 else False
                    control = bool(token[2]) if len(token) > 2 else False
                    alt = bool(token[3]) if len(token) > 3 else False
                    repeat = int(token[4]) if len(token) > 4 else 1
                    self.key(key, shift=shift, control=control, alt=alt, repeat=repeat)
            else:
                self.key(str(token))

    def esc(self):
        self.key("Escape")

    def type_text(self, text):
        for ch in text:
            if ch == "\n":
                self.key("Return")
            elif ch == "\t":
                self.key("Tab")
            else:
                base_key, shifted = _resolve_typed_char(ch)
                self.key(base_key, shift=shifted)

    def command(self, command_text):
        self.key(";", shift=True)  # :
        self.assert_mode(Vim.Mode.COMMAND_LINE, "Expected command-line mode after ':'")
        self.type_text(command_text)
        self.key("Return")
        Vim.on_update()

    def get_cursor(self):
        return Vim.get_cursor_pos()

    def get_mode(self):
        return Vim.g_mode

    def get_buffer_text(self):
        line_count = max(1, Vim.get_line_count())
        parts = []
        for y in range(line_count):
            parts.append(Vim.get_line(y))
        return "".join(parts)

    def assert_true(self, condition, message):
        if not condition:
            raise AssertionError(message)

    def assert_equal(self, actual, expected, message):
        if actual != expected:
            raise AssertionError(message + "\nActual:   " + repr(actual) + "\nExpected: " + repr(expected))

    def assert_cursor(self, expected, message="Unexpected cursor position"):
        self.assert_equal(self.get_cursor(), expected, message)

    def assert_mode(self, expected, message="Unexpected mode"):
        actual = self.get_mode()
        if actual != expected:
            raise AssertionError(
                message + "\nActual:   " + _mode_name(actual) + "\nExpected: " + _mode_name(expected)
            )

    def assert_buffer(self, expected, message="Unexpected buffer text"):
        actual_norm = _normalize_buffer_text(self.get_buffer_text())
        expected_norm = _normalize_buffer_text(expected)
        self.assert_equal(actual_norm, expected_norm, message)


def test_basic_motions(ctx):
    ctx.reset("abc\ndef\nghi", cursor=(1, 1))
    ctx.key("h")
    ctx.assert_cursor((0, 1))
    ctx.key("j")
    ctx.assert_cursor((0, 2))
    ctx.key("k")
    ctx.assert_cursor((0, 1))
    ctx.key("l")
    ctx.assert_cursor((1, 1))
    ctx.key("3")
    ctx.key("l")
    ctx.assert_cursor((2, 1))
    ctx.key("Left")
    ctx.assert_cursor((1, 1))
    ctx.key("Right")
    ctx.assert_cursor((2, 1))
    ctx.key("Up")
    ctx.assert_cursor((2, 0))
    ctx.key("Down")
    ctx.assert_cursor((2, 1))


def test_word_motions(ctx):
    ctx.reset("one two three four", cursor=(0, 0))
    ctx.key("w")
    ctx.assert_cursor((4, 0))
    ctx.key("w")
    ctx.assert_cursor((8, 0))
    ctx.key("b")
    ctx.assert_cursor((4, 0))
    ctx.key("e")
    ctx.assert_cursor((6, 0))

    ctx.reset("one,two three", cursor=(0, 0))
    ctx.key("w", shift=True)  # W
    ctx.assert_cursor((8, 0))
    ctx.key("b", shift=True)  # B
    ctx.assert_cursor((0, 0))
    ctx.key("e", shift=True)  # E
    ctx.assert_cursor((6, 0))


def test_line_motions(ctx):
    ctx.reset("   alpha beta\ngamma delta", cursor=(8, 0))
    ctx.key("0")
    ctx.assert_cursor((0, 0))
    ctx.key("^")
    ctx.assert_cursor((3, 0))
    ctx.key("$")
    ctx.assert_cursor((12, 0))
    ctx.key("4")
    ctx.key("|")
    ctx.assert_cursor((3, 0))
    ctx.key("+")
    ctx.assert_cursor((0, 1))
    ctx.key("-")
    ctx.assert_cursor((3, 0))
    ctx.key("_")
    ctx.assert_cursor((3, 0))


def test_find_motions(ctx):
    ctx.reset("a b c b d b", cursor=(0, 0))
    ctx.run_tokens(["f", "b"])
    ctx.assert_cursor((2, 0))
    ctx.key(";")
    ctx.assert_cursor((6, 0))
    ctx.key(",")
    ctx.assert_cursor((2, 0))
    ctx.run_tokens(["t", "d"])
    ctx.assert_cursor((7, 0))
    ctx.run_tokens([_token("f", shift=True), "a"])  # F a
    ctx.assert_cursor((0, 0))


def test_delete_change_yank(ctx):
    ctx.reset("one two three", cursor=(0, 0))
    ctx.run_tokens(["d", "w"])
    ctx.assert_buffer("two three")

    ctx.reset("one two", cursor=(0, 0))
    ctx.run_tokens(["c", "w"])
    ctx.assert_mode(Vim.Mode.INSERT)
    ctx.type_text("ONE")
    ctx.esc()
    ctx.assert_mode(Vim.Mode.NORMAL)
    ctx.assert_buffer("ONE two")

    ctx.reset("one\ntwo\nthree", cursor=(0, 0))
    ctx.run_tokens(["y", "y", "j", "p"])
    ctx.assert_buffer("one\ntwo\none\nthree")

    ctx.reset("one\ntwo\nthree", cursor=(0, 1))
    ctx.run_tokens(["d", "d"])
    ctx.assert_buffer("one\nthree")


def test_insert_append_commands(ctx):
    ctx.reset("abc", cursor=(1, 0))
    ctx.key("i")
    ctx.type_text("X")
    ctx.esc()
    ctx.assert_buffer("aXbc")
    ctx.key("a")
    ctx.type_text("Y")
    ctx.esc()
    ctx.assert_buffer("aXYbc")
    ctx.key("i", shift=True)  # I
    ctx.type_text("Z")
    ctx.esc()
    ctx.assert_buffer("ZaXYbc")
    ctx.key("a", shift=True)  # A
    ctx.type_text("Q")
    ctx.esc()
    ctx.assert_buffer("ZaXYbcQ")


def test_open_line_commands(ctx):
    ctx.reset("  one\n  two", cursor=(0, 0))
    ctx.key("o")
    ctx.type_text("mid")
    ctx.esc()
    ctx.assert_buffer("  one\n  mid\n  two")

    ctx.reset("  one\n  two", cursor=(0, 1))
    ctx.key("o", shift=True)  # O
    ctx.type_text("top")
    ctx.esc()
    ctx.assert_buffer("  one\n  top\n  two")


def test_replace_substitute_and_char_delete(ctx):
    ctx.reset("abcde", cursor=(2, 0))
    ctx.run_tokens(["r", "z"])
    ctx.assert_buffer("abzde")
    ctx.assert_cursor((2, 0))

    ctx.reset("abcde", cursor=(1, 0))
    ctx.key("s")
    ctx.assert_mode(Vim.Mode.INSERT)
    ctx.type_text("XY")
    ctx.esc()
    ctx.assert_buffer("aXYcde")

    ctx.reset("abcde", cursor=(1, 0))
    ctx.key("r", shift=True)  # R
    ctx.assert_mode(Vim.Mode.REPLACE)
    ctx.type_text("XYZ")
    ctx.esc()
    ctx.assert_buffer("aXYZe")

    ctx.reset("abcde", cursor=(2, 0))
    ctx.key("x")
    ctx.assert_buffer("abde")
    ctx.key("x", shift=True)  # X
    ctx.assert_buffer("ade")


def test_undo_redo_and_dot_repeat(ctx):
    ctx.reset("abcd", cursor=(0, 0))
    ctx.key("x")
    ctx.assert_buffer("bcd")
    ctx.key(".")
    ctx.assert_buffer("cd")
    ctx.key("u")
    ctx.assert_buffer("bcd")
    ctx.run_tokens([_token("r", control=True)])
    ctx.assert_buffer("cd")


def test_named_registers_and_paste(ctx):
    ctx.reset("one two", cursor=(0, 0))
    ctx.run_tokens(["\"", "a", "y", "i", "w", "$", "\"", "a", "p"])
    ctx.assert_buffer("one twoone")


def test_text_objects(ctx):
    ctx.reset("one two", cursor=(1, 0))
    ctx.run_tokens(["c", "i", "w"])
    ctx.type_text("ONE")
    ctx.esc()
    ctx.assert_buffer("ONE two")

    ctx.reset("say \"hello\" now", cursor=(6, 0))
    ctx.run_tokens(["d", "i", "\""])
    ctx.assert_buffer("say \"\" now")

    ctx.reset("fn(arg) + 1", cursor=(3, 0))
    ctx.run_tokens(["d", "a", "("])
    ctx.assert_buffer("fn + 1")


def test_case_operations(ctx):
    ctx.reset("abc DEF", cursor=(0, 0))
    ctx.key("~")
    ctx.assert_buffer("Abc DEF")

    ctx.reset("abc DEF", cursor=(4, 0))
    ctx.run_tokens(["g", "u", "e"])
    ctx.assert_buffer("abc def")

    ctx.reset("abc def", cursor=(0, 0))
    ctx.run_tokens(["g", _token("u", shift=True), "e"])  # gUe
    ctx.assert_buffer("ABC def")

    ctx.reset("AbC deF", cursor=(0, 0))
    ctx.run_tokens(["g", "~", "e"])
    ctx.assert_buffer("aBc deF")


def test_visual_char_and_line(ctx):
    ctx.reset("abcdef", cursor=(0, 0))
    ctx.run_tokens(["v", ("l", False, False, False, 2), "d"])
    ctx.assert_buffer("def")

    ctx.reset("one\ntwo\nthree", cursor=(0, 0))
    ctx.run_tokens([_token("v", shift=True), "j", "y", "p"])  # V j y p
    ctx.assert_buffer("one\none\ntwo\ntwo\nthree")


def test_visual_block_delete(ctx):
    ctx.reset("abcd\nABCD\nwxyz", cursor=(0, 0))
    ctx.run_tokens([_token("v", False, True), "j", "l", "d"])  # Ctrl+v j l d
    ctx.assert_buffer("cd\nCD\nwxyz")


def test_marks(ctx):
    ctx.reset("aa\nbb\ncc", cursor=(1, 0))
    ctx.run_tokens(["m", "a"])
    ctx.run_tokens([_token("g", shift=True)])  # G
    ctx.run_tokens(["'", "a"])
    ctx.assert_cursor((0, 0))
    ctx.run_tokens(["`", "a"])
    ctx.assert_cursor((1, 0))


def test_macros(ctx):
    ctx.reset("abc", cursor=(0, 0))
    ctx.run_tokens(["q", "a", "i"])
    ctx.type_text("#")
    ctx.esc()
    ctx.run_tokens(["q", "@", "a"])
    ctx.assert_buffer("##abc")


def test_command_line_substitute(ctx):
    ctx.reset("one one\ntwo one", cursor=(0, 0))
    ctx.command("s/one/ONE/")
    ctx.assert_buffer("ONE one\ntwo one")
    ctx.command("%s/one/x/g")
    ctx.assert_buffer("ONE x\ntwo x")
    ctx.command("2")
    ctx.assert_cursor((0, 1))


def test_command_line_range_delete(ctx):
    ctx.reset("a\nb\nc\nd", cursor=(0, 0))
    ctx.command("2,3d")
    ctx.assert_buffer("a\nd")


def test_ctrl_number_increment_decrement(ctx):
    ctx.reset("value 009", cursor=(6, 0))
    ctx.run_tokens([_token("a", False, True)])  # Ctrl+a
    ctx.assert_buffer("value 10")
    ctx.run_tokens([_token("x", False, True)])  # Ctrl+x
    ctx.assert_buffer("value 9")


def test_ctrl_mode_switches(ctx):
    ctx.reset("abc", cursor=(1, 0))
    ctx.key("i")
    ctx.type_text("z")
    ctx.run_tokens([_token("[", False, True)])  # Ctrl+[
    ctx.assert_mode(Vim.Mode.NORMAL)
    ctx.run_tokens([_token("v", False, True)])  # Ctrl+v
    ctx.assert_mode(Vim.Mode.VISUAL_BLOCK)
    ctx.esc()
    ctx.assert_mode(Vim.Mode.NORMAL)


def test_search_smoke(ctx):
    ctx.reset("alpha beta alpha beta alpha", cursor=(0, 0))
    # Search integration depends on 10x find-panel internals. This is smoke-only.
    ctx.run_tokens(["*", "n", _token("n", shift=True), "#"])


def test_smoke_remaining_normal_bindings(ctx):
    scenarios = [
        ("g-pending", "one two\nthree four", ["g", "g"]),
        ("g-ge", "one two\nthree four", ["g", "e"]),
        ("g-gE", "one two\nthree four", ["g", _token("e", shift=True)]),
        ("g-v", "one two\nthree four", ["v", "l", "y", "g", "v"]),
        ("g-i", "one two\nthree four", ["i", "x", "Escape", "g", "i", "Escape"]),
        ("gJ", "one\ntwo", ["g", _token("j", shift=True)]),
        ("z-commands", "one\ntwo\nthree", ["z", "z", "z", "t", "z", "b", "z", "c", "z", "o", "z", "a"]),
        ("z-fold-shift", "one\ntwo", ["z", _token("m", shift=True), "z", _token("r", shift=True)]),
        ("ZZ-save-close", "one", ["z", _token("z", shift=True)]),
        ("ZQ-discard-close", "one", ["z", _token("q", shift=True)]),
        ("section-nav", "{\na\n}\n\n{\nb\n}\n", ["[", "[", "]", "]", "[", "]", "]", "["]),
        ("repeat-find", "a b c b d b", ["f", "b", ";", ","]),
        ("operators-shift", "one two three", [_token("d", shift=True)]),  # D
        ("operators-shift-c", "one two three", [_token("c", shift=True), "x", "Escape"]),  # C
        ("operators-shift-y", "one\ntwo", [_token("y", shift=True), "p"]),  # Y
        ("indent-ops", "one\ntwo", [">", ">", "<", "<", "=", "="]),
        ("ctrl-scroll", "one\ntwo\nthree\nfour\nfive\nsix\nseven", [_token("d", False, True), _token("u", False, True), _token("f", False, True), _token("b", False, True), _token("e", False, True), _token("y", False, True)]),
        ("ctrl-info", "one", [_token("g", False, True)]),
        ("ctrl-window-prefix", "one", [_token("w", False, True), "h"]),
        ("register-prefix", "one two", ["\"", "a", "y", "i", "w"]),
        ("misc-u", "one", ["u"]),
        ("misc-tilde", "one", ["~"]),
        ("misc-r", "one", ["r", "x"]),
        ("misc-s", "one", ["s", "x", "Escape"]),
        ("misc-p-shift", "one", ["y", "y", _token("p", shift=True)]),
        ("ctrl-jump", "one\ntwo\nthree", [_token("o", False, True), _token("i", False, True)]),
    ]

    for name, text, tokens in scenarios:
        ctx.reset(text, cursor=(0, 0))
        try:
            ctx.run_tokens(tokens)
        except Exception as ex:
            raise AssertionError("Smoke scenario failed: " + name + " :: " + str(ex))


def test_smoke_remaining_visual_bindings(ctx):
    scenarios = [
        ("visual-motions", "one two three", ["v", "w", "b", "e", "$", "0", "^", "_", "+", "-", "|", "%", "{", "}"]),
        ("visual-find", "a b c b d b", ["v", "f", "b", ";", ",", "t", "d"]),
        ("visual-ops", "abcdef", ["v", "l", "x"]),
        ("visual-indent", "one\ntwo\nthree", ["v", "j", ">", "v", "j", "<", "v", "j", "="]),
        ("visual-case", "AbC deF", ["v", "w", "u", "v", "w", _token("u", shift=True), "v", "w", "~"]),
        ("visual-line-toggle", "one\ntwo", [_token("v", shift=True), "v", _token("v", shift=True)]),
        ("visual-commandline", "one\ntwo", ["v", "j", _token(";", shift=True), "n", "o", "h", "l", "s", "e", "a", "r", "c", "h", "Escape"]),
        ("visual-block-I", "abc\ndef\nghi", [_token("v", False, True), "j", _token("i", shift=True), "x", "Escape"]),
        ("visual-block-A", "abc\ndef\nghi", [_token("v", False, True), "j", _token("a", shift=True), "x", "Escape"]),
        ("visual-join", "a\nb\nc", [_token("v", shift=True), "j", _token("j", shift=True)]),
    ]

    for name, text, tokens in scenarios:
        ctx.reset(text, cursor=(0, 0))
        try:
            ctx.run_tokens(tokens)
        except Exception as ex:
            raise AssertionError("Visual smoke scenario failed: " + name + " :: " + str(ex))


class VimFunctionalitySuite(MultiStageTest):
    def __init__(self):
        self.init()
        self.m_Context = VimTestContext(self)
        self.m_TestFilePath = ""
        self.m_Results = []
        self.m_Total = 0
        self.m_Passed = 0
        self.m_Failed = 0
        self.m_Skipped = 0
        self.m_ResultsPath = os.environ.get(
            "VIM_TEST_RESULTS_PATH",
            os.path.join(tempfile.gettempdir(), "vim_test_results.txt"),
        )
        self.m_AutoExit = _env_bool("VIM_TEST_AUTO_EXIT", True)

        tests = [
            ("basic_motions", test_basic_motions),
            ("word_motions", test_word_motions),
            ("line_motions", test_line_motions),
            ("find_motions", test_find_motions),
            ("delete_change_yank", test_delete_change_yank),
            ("insert_append", test_insert_append_commands),
            ("open_line", test_open_line_commands),
            ("replace_substitute_char_delete", test_replace_substitute_and_char_delete),
            ("undo_redo_dot_repeat", test_undo_redo_and_dot_repeat),
            ("named_registers_paste", test_named_registers_and_paste),
            ("text_objects", test_text_objects),
            ("case_operations", test_case_operations),
            ("visual_char_line", test_visual_char_and_line),
            ("visual_block_delete", test_visual_block_delete),
            ("marks", test_marks),
            ("macros", test_macros),
            ("command_line_substitute", test_command_line_substitute),
            ("command_line_range_delete", test_command_line_range_delete),
            ("ctrl_number_increment_decrement", test_ctrl_number_increment_decrement),
            ("ctrl_mode_switches", test_ctrl_mode_switches),
            ("search_smoke", test_search_smoke),
            ("smoke_remaining_normal_bindings", test_smoke_remaining_normal_bindings),
            ("smoke_remaining_visual_bindings", test_smoke_remaining_visual_bindings),
        ]

        self.Add(self._setup_suite)
        self.Add(WaitUntil(self._is_test_file_open, 300, "Wait for test file to open"))
        for test_name, test_fn in tests:
            self.Add(lambda n=test_name, fn=test_fn: self._run_test(n, fn))
        self.Add(self._finish_suite)

    def _is_test_file_open(self):
        current = ""
        try:
            current = N10X.Editor.GetCurrentFilename() or ""
        except Exception:
            current = ""
        try:
            current_norm = os.path.normcase(os.path.abspath(current))
            target_norm = os.path.normcase(os.path.abspath(self.m_TestFilePath))
            return current_norm == target_norm
        except Exception:
            return current.lower() == self.m_TestFilePath.lower()

    def _setup_suite(self):
        try:
            tests_dir = os.path.join(tempfile.gettempdir(), "10x_vim_tests")
            os.makedirs(tests_dir, exist_ok=True)
            self.m_TestFilePath = os.path.join(tests_dir, "vim_suite_buffer.txt")
            with open(self.m_TestFilePath, "w", encoding="utf-8", newline="\n") as f:
                f.write("bootstrap\n")
        except Exception as ex:
            raise AssertionError("Failed to create test file: " + str(ex))

        try:
            N10X.Editor.InitialiseTestEnvironment("VimFunctionalitySuite")
        except Exception:
            pass

        try:
            N10X.Editor.SetUseLocalClipboard(True)
        except Exception:
            pass

        try:
            N10X.Editor.SetSetting("Vim", "true")
            N10X.Editor.SetSetting("VimUse10xFindPanel", "false")
            N10X.Editor.SetSetting("VimCommandlineFilteredHistory", "false")
        except Exception:
            pass

        try:
            Vim.load_settings()
        except Exception:
            pass

        try:
            Vim.initialize()
        except Exception:
            # If already initialized this is fine.
            pass

        N10X.Editor.OpenFile(self.m_TestFilePath)
        self.m_Context.reset("bootstrap\n", cursor=(0, 0))
        print("Vim tests setup complete. Test file: " + self.m_TestFilePath)

    def _run_test(self, test_name, test_fn):
        start = time.time()
        result = {
            "name": test_name,
            "status": "PASS",
            "duration_ms": 0,
            "details": "",
        }

        self.m_Total += 1
        try:
            test_fn(self.m_Context)
            self.m_Passed += 1
        except SkipTest as ex:
            result["status"] = "SKIP"
            result["details"] = str(ex)
            self.m_Skipped += 1
        except Exception:
            result["status"] = "FAIL"
            result["details"] = traceback.format_exc()
            self.m_Failed += 1
        finally:
            result["duration_ms"] = int((time.time() - start) * 1000)
            self.m_Results.append(result)
            print("[{0}] {1} ({2} ms)".format(result["status"], test_name, result["duration_ms"]))
            if result["status"] == "FAIL":
                print(result["details"])

    def _write_results(self):
        os.makedirs(os.path.dirname(self.m_ResultsPath), exist_ok=True)

        summary = {
            "total": self.m_Total,
            "passed": self.m_Passed,
            "failed": self.m_Failed,
            "skipped": self.m_Skipped,
            "results_path": self.m_ResultsPath,
            "test_file": self.m_TestFilePath,
            "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        text_lines = []
        text_lines.append("Vim Functionality Test Suite")
        text_lines.append("Total: {0}  Passed: {1}  Failed: {2}  Skipped: {3}".format(
            self.m_Total, self.m_Passed, self.m_Failed, self.m_Skipped
        ))
        text_lines.append("Test file: " + self.m_TestFilePath)
        text_lines.append("")
        for result in self.m_Results:
            text_lines.append("[{0}] {1} ({2} ms)".format(
                result["status"], result["name"], result["duration_ms"]
            ))
            if result["details"]:
                text_lines.append(result["details"].rstrip())
            text_lines.append("")

        with open(self.m_ResultsPath, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(text_lines).rstrip() + "\n")

        json_path = self.m_ResultsPath + ".json"
        with open(json_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"summary": summary, "results": self.m_Results}, f, indent=2)

        print("Wrote Vim test results to: " + self.m_ResultsPath)
        print("Wrote Vim test JSON to: " + json_path)

    def _finish_suite(self):
        self._write_results()
        title = "Vim Tests"
        if self.m_Failed == 0:
            msg = "SUCCESS: {0}/{1} tests passed".format(self.m_Passed, self.m_Total)
        else:
            msg = "FAIL: {0} failed, {1} passed, {2} skipped".format(self.m_Failed, self.m_Passed, self.m_Skipped)

        try:
            N10X.Editor.ShowMessageBox(title, msg)
        except Exception:
            pass

        if self.m_AutoExit:
            try:
                N10X.Editor.DiscardUnsavedChanges()
            except Exception:
                pass
            try:
                N10X.Editor.ExecuteCommand("Exit")
            except Exception:
                pass

    def UpdateRunner(self):
        done = False
        try:
            done = self.Update()
        except Exception:
            self.m_Total += 1
            self.m_Failed += 1
            self.m_Results.append({
                "name": "fatal_suite_error",
                "status": "FAIL",
                "duration_ms": 0,
                "details": traceback.format_exc(),
            })
            done = True

        if done:
            try:
                N10X.Editor.RemoveUpdateFunction(self.UpdateRunner)
            except Exception:
                pass
        return done


def RunVimTests():
    global g_TestSuiteInstance
    if g_TestSuiteInstance is not None:
        return
    g_TestSuiteInstance = VimFunctionalitySuite()
    N10X.Editor.AddUpdateFunction(g_TestSuiteInstance.UpdateRunner)
    print("Started Vim functionality test suite")


def RunTests():
    RunVimTests()
