#------------------------------------------------------------------------
import os
import N10X

#------------------------------------------------------------------------
# Vim style editing
#
# To enable Vim editing set Vim to true oin the 10x settings file
#
#------------------------------------------------------------------------
g_VimEnabled = False
g_CommandMode = False

g_PrevCommand = None
g_RepeatCount = None

g_VisualMode = False

#------------------------------------------------------------------------
def EnableInsertMode():
	global g_CommandMode
	if g_CommandMode:
		g_CommandMode = False
		N10X.Editor.ClearCursorColourOverride()
		N10X.Editor.ResetCursorBlink()

#------------------------------------------------------------------------
def EnableCommandMode():
	global g_CommandMode
	if not g_CommandMode:
		g_CommandMode = True
		N10X.Editor.SetCursorColourOverride((255, 0, 0))
		N10X.Editor.ResetCursorBlink()

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
def GetRepeatCount():
	global g_RepeatCount
	if g_RepeatCount == None:
		return 1
	else:
		return g_RepeatCount

#------------------------------------------------------------------------
def RepeatedCommand(command, reset_visial_mode=True):
	for i in range(GetRepeatCount()):
		if callable(command):
			command()
		else:
			N10X.Editor.ExecuteCommand(command)

	if reset_visial_mode:
		global g_VisualMode
		g_VisualMode = False

#------------------------------------------------------------------------
def RepeatedEditCommand(command):
	N10X.Editor.PushUndoGroup()
	RepeatedCommand(command)
	N10X.Editor.PopUndoGroup()

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
	end = GetWordEnd()
	cursor_pos = N10X.Editor.GetCursorPos()
	line = N10X.Editor.GetLine(cursor_pos[1])
	line = line[:cursor_pos[0]] + line[end:]
	N10X.Editor.SetLine(cursor_pos[1], line)
	EnableInsertMode()



#------------------------------------------------------------------------
# Key Intercepting

#------------------------------------------------------------------------
def HandleCommandModeChar(c):

	global g_PrevCommand
	command = c
	if g_PrevCommand:
		command = g_PrevCommand + c
		g_PrevCommand = None

	global g_RepeatCount
	is_repeat_key = False

	global g_VisualMode

	if command == "i":
		EnableInsertMode()

	elif IsCommandPrefix(command):
		g_PrevCommand = command

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
		if g_VisualMode:
			g_VisualMode = False
			N10X.Editor.ClearSelection()
		else:
			g_VisualMode = True

	elif command == "dd":
		RepeatedEditCommand("Cut")

	elif command == "yy":
		N10X.Editor.ExecuteCommand("Copy")

	elif command == "P":
		RepeatedEditCommand("Paste")

	elif command == "h":
		n10x_command = lambda:N10X.Editor.SendKey("Left", shift=g_VisualMode)
		RepeatedCommand(n10x_command, reset_visial_mode=False);

	elif command == "l":
		n10x_command = lambda:N10X.Editor.SendKey("Right", shift=g_VisualMode)
		RepeatedCommand(n10x_command, reset_visial_mode=False);

	elif command == "k":
		n10x_command = lambda:N10X.Editor.SendKey("Up", shift=g_VisualMode)
		RepeatedCommand(n10x_command, reset_visial_mode=False);

	elif command == "j":
		n10x_command = lambda:N10X.Editor.SendKey("Down", shift=g_VisualMode)
		RepeatedCommand(n10x_command, reset_visial_mode=False);

	if command == "0":
		MoveToStartOfLine()

	elif command == "$":
		MoveToEndOfLine()

	elif command == "b":
		RepeatedCommand("MoveCursorPrevWord")

	elif command == "w":
		RepeatedCommand("MoveCursorNextWord")

	elif command == "cw":
		CutToEndOfWordAndInsert()

	elif command == "I":
		MoveToStartOfLine();
		N10X.Editor.ExecuteCommand("MoveCursorNextWord")
		EnableInsertMode();

	elif command == "a":
		# NOTE: this bugs when trying pressing it at the end of a line.
		# It shouldn't go to the next line, it should just go to the last possible position.
		# This might be a byproduct of not using a block cursor in insertmode, where you
		# actually can't go to the position after the last char.
		N10X.Editor.ExecuteCommand("MoveCursorRight");
		EnableInsertMode();

	elif command == "A":
		MoveToEndOfLine();
		EnableInsertMode();

	elif command == "e":
		cursor_pos = N10X.Editor.GetCursorPos()
		N10X.Editor.SetCursorPos((GetWordEnd(), cursor_pos[1]))

	elif command == "p":
		# In vim, the cursor should "stay with the line."
		# Doing this for P seems to do some weird selection thing.
		N10X.Editor.ExecuteCommand("MoveCursorDown");
		N10X.Editor.ExecuteCommand("Paste")
		N10X.Editor.ExecuteCommand("MoveCursorUp");

	elif command == "*":
		RepeatedCommand("FindInFileNextCurrentWord")

	elif command == "#":
		RepeatedCommand("FindInFilePrevCurrentWord")

	elif command == "O":
		N10X.Editor.ExecuteCommand("InsertLine");
		EnableInsertMode();

	# NOTE: This changes the cursor position, so if you undo, the cursor returns to the wrong
	# place (1 down from where it should be).
	elif command == "o":
		N10X.Editor.ExecuteCommand("MoveCursorDown");
		N10X.Editor.ExecuteCommand("InsertLine");
		EnableInsertMode();

	elif command == "gd":
		N10X.Editor.ExecuteCommand("GotoSymbolDefinition");

	# NOTE: in vim, this loops.
	elif command == "gt":
		N10X.Editor.ExecuteCommand("NextPanelTab");

	elif command == "gT":
		N10X.Editor.ExecuteCommand("PrevPanelTab");

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
		RepeatedEditCommand("Delete")

	# reset repeat count
	if (not is_repeat_key) and (not IsCommandPrefix(command)):
		g_RepeatCount = None

#------------------------------------------------------------------------
def HandleCommandModeKey(key, shift, control, alt):

	handled = True

	if key == "H" and alt:
		N10X.Editor.ExecuteCommand("MovePanelFocusLeft")

	elif key == "L" and alt:
		N10X.Editor.ExecuteCommand("MovePanelFocusRight")

	elif key == "J" and alt:
		N10X.Editor.ExecuteCommand("MovePanelFocusDown")

	elif key == "K" and alt:
		N10X.Editor.ExecuteCommand("MovePanelFocusUp")

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
		key == "Right"

	if handled or pass_through:
		global g_RepeatCount
		g_RepeatCount = None

	return not pass_through

#------------------------------------------------------------------------
def HandleInsertModeKey(key, shift, control, alt):

	if key == "Escape":
		EnableCommandMode()
		return True

	if key == "C" and control:
		EnableCommandMode()
		return True

#------------------------------------------------------------------------
# 10X Callbacks

#------------------------------------------------------------------------
# Called when a key is pressed.
# Return true to surpress the key
def OnInterceptKey(key, shift, control, alt):
	if N10X.Editor.TextEditorHasFocus():
		global g_CommandMode
		if g_CommandMode:
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
		if g_CommandMode:
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
			EnableCommandMode()

		else:
			print("[vim] Disabling Vim")
			EnableInsertMode()
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

