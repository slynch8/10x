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

g_LineVisualMode = False
g_LineVisualModeStartPos = None

g_HandingKey = False

#------------------------------------------------------------------------
def EnableInsertMode():
	ExitAllVisualModes()
	global g_CommandMode
	if g_CommandMode:
		g_CommandMode = False
		N10X.Editor.SetCursorMode("Underscore")
		N10X.Editor.ResetCursorBlink()

#------------------------------------------------------------------------
def EnableCommandMode():
	global g_CommandMode
	if not g_CommandMode:
		g_CommandMode = True
		N10X.Editor.SetCursorMode("Block")
		N10X.Editor.ResetCursorBlink()

#------------------------------------------------------------------------
def EnterVisualMode():
	global g_VisualMode
	if not g_VisualMode:
		ExitAllVisualModes()
		g_VisualMode = True

#------------------------------------------------------------------------
def ExitVisualMode():
	global g_VisualMode
	if g_VisualMode:
		g_VisualMode = False
		N10X.Editor.ClearSelection()

#------------------------------------------------------------------------
def EnterLineVisualMode():
	ExitVisualMode()
	global g_LineVisualMode
	g_LineVisualMode = True
	global g_LineVisualModeStartPos
	g_LineVisualModeStartPos = N10X.Editor.GetCursorPos()
	UpdateLineVisualModeSelection()

#------------------------------------------------------------------------
def ExitLineVisualMode():
	global g_LineVisualMode
	if g_LineVisualMode:
		ClearLineVisualModeSelection()
		g_LineVisualMode = False

#------------------------------------------------------------------------
def ExitAllVisualModes():
	ExitVisualMode()
	ExitLineVisualMode()

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
	if g_CommandMode and g_PrevCommand != c:
		g_PrevCommand = c
		if c:
			N10X.Editor.SetCursorMode("HalfBlock")
		else:
			N10X.Editor.SetCursorMode("Block")

#------------------------------------------------------------------------
def RepeatedCommand(command, exit_visual_mode=True):
	
	global g_RepeatCount
	if g_RepeatCount == None:
		g_RepeatCount = 1
	
	while g_RepeatCount:

		g_RepeatCount -= 1
		
		if callable(command):
			command()
		else:
			N10X.Editor.ExecuteCommand(command)
			
	g_RepeatCount = None

	if exit_visual_mode:
		global g_VisualMode
		g_VisualMode = False
		global g_LineVisualMode
		g_LineVisualMode = False

#------------------------------------------------------------------------
def RepeatedEditCommand(command):
	N10X.Editor.PushUndoGroup()
	RepeatedCommand(command)
	N10X.Editor.PopUndoGroup()

#------------------------------------------------------------------------
def ClearLineVisualModeSelection(moving_down=False):
	global g_LineVisualModeStartPos
	cursor_pos = N10X.Editor.GetCursorPos()
	cursor_pos = (g_LineVisualModeStartPos[0], cursor_pos[1])
	if cursor_pos[1] > g_LineVisualModeStartPos[1]:
		cursor_pos = (cursor_pos[0], cursor_pos[1] - 1)
	if moving_down:
		cursor_pos = (cursor_pos[0], cursor_pos[1] + 1)
	N10X.Editor.SetCursorPos(cursor_pos)

#------------------------------------------------------------------------
def UpdateLineVisualModeSelection():
	global g_LineVisualMode
	global g_LineVisualModeStartPos
	
	if g_LineVisualMode:
		cursor_pos = N10X.Editor.GetCursorPos()
		
		if cursor_pos[1] == g_LineVisualModeStartPos[1]:
			N10X.Editor.SetCursorPos((0, cursor_pos[1]))
			N10X.Editor.SetCursorPosSelect((0, cursor_pos[1] + 1))
		elif cursor_pos[1] > g_LineVisualModeStartPos[1]:
			N10X.Editor.SetCursorPos((0, g_LineVisualModeStartPos[1]))
			N10X.Editor.SetCursorPosSelect((0, cursor_pos[1]))
		else:
			N10X.Editor.SetCursorPos((0, g_LineVisualModeStartPos[1] + 1))
			N10X.Editor.SetCursorPosSelect((0, cursor_pos[1]))
			
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
	global g_RepeatCount

	cursor_pos = N10X.Editor.GetCursorPos()

	if g_RepeatCount:
		N10X.Editor.ExecuteCommand("MoveCursorNextWord")
		end_cursor_pos = N10X.Editor.GetCursorPos()
		line = N10X.Editor.GetLine(cursor_pos[1])
		line = line[:cursor_pos[0]] + line[end_cursor_pos[0]:]
		N10X.Editor.SetLine(cursor_pos[1], line)
	else:
		end = GetWordEnd()
		line = N10X.Editor.GetLine(cursor_pos[1])
		line = line[:cursor_pos[0]] + line[end:]
		N10X.Editor.SetLine(cursor_pos[1], line)
	
	if not g_RepeatCount:
		EnableInsertMode()

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
	global g_LineVisualMode

	if command == "i":
		EnableInsertMode()

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
		ExitLineVisualMode()
		if g_VisualMode:
			ExitVisualMode()
		else:
			EnterVisualMode()

	elif command == "V":
		ExitVisualMode()
		if g_LineVisualMode:
			ExitLineVisualMode()
		else:
			EnterLineVisualMode()

	elif command == "dd":
		RepeatedEditCommand("Cut")

	elif command == "yy":
		MoveToStartOfLine()
		n10x_command = lambda:N10X.Editor.SendKey("Down", shift=True)
		RepeatedCommand(n10x_command, exit_visual_mode=False)
		N10X.Editor.ExecuteCommand("Copy")
		N10X.Editor.ClearSelection()

	elif command == "P":
		RepeatedEditCommand("Paste")

	elif command == "h":
		if not g_LineVisualMode:
			n10x_command = lambda:N10X.Editor.SendKey("Left", shift=g_VisualMode)
			RepeatedCommand(n10x_command, exit_visual_mode=False);

	elif command == "l":
		if not g_LineVisualMode:
			n10x_command = lambda:N10X.Editor.SendKey("Right", shift=g_VisualMode)
			RepeatedCommand(n10x_command, exit_visual_mode=False);

	elif command == "k":
		ClearLineVisualModeSelection()
		n10x_command = lambda:N10X.Editor.SendKey("Up", shift=g_VisualMode)
		RepeatedCommand(n10x_command, exit_visual_mode=False);
		UpdateLineVisualModeSelection()

	elif command == "j":
		ClearLineVisualModeSelection(moving_down=True)
		n10x_command = lambda:N10X.Editor.SendKey("Down", shift=g_VisualMode)
		RepeatedCommand(n10x_command, exit_visual_mode=False);
		UpdateLineVisualModeSelection()

	if command == "0":
		MoveToStartOfLine()

	elif command == "$":
		MoveToEndOfLine()

	elif command == "b":
		RepeatedCommand("MoveCursorPrevWord")

	elif command == "w":
		RepeatedCommand("MoveCursorNextWord")

	elif command == "cw":
		n10x_command = lambda:CutToEndOfWordAndInsert()
		RepeatedCommand(n10x_command);

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
		EnableInsertMode()
		MoveToEndOfLine()
		N10X.Editor.SendKey("Enter")

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
		ExitAllVisualModes()
		
	elif key == "H" and alt:
		N10X.Editor.ExecuteCommand("MovePanelFocusLeft")

	elif key == "L" and alt:
		N10X.Editor.ExecuteCommand("MovePanelFocusRight")

	elif key == "J" and alt:
		N10X.Editor.ExecuteCommand("MovePanelFocusDown")

	elif key == "K" and alt:
		N10X.Editor.ExecuteCommand("MovePanelFocusUp")

	elif key == "Up" and g_VisualMode and not shift:
		N10X.Editor.SendKey("Up", shift=True)
		UpdateLineVisualModeSelection()

	elif key == "Down" and g_VisualMode and not shift:
		N10X.Editor.SendKey("Down", shift=True)
		UpdateLineVisualModeSelection()

	elif key == "Left" and g_VisualMode and not shift:
		N10X.Editor.SendKey("Left", shift=True)

	elif key == "Right" and g_VisualMode and not shift:
		N10X.Editor.SendKey("Right", shift=True)

	elif key == "Up" and g_LineVisualMode:
		ClearLineVisualModeSelection()
		N10X.Editor.SendKey("Up")
		UpdateLineVisualModeSelection()

	elif key == "Down" and g_LineVisualMode:
		ClearLineVisualModeSelection(moving_down=True)
		N10X.Editor.SendKey("Down")
		UpdateLineVisualModeSelection()

	elif key == "Left" and g_LineVisualMode:
		handled = True

	elif key == "Right" and g_LineVisualMode:
		handled = True

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
			key == "Right"

	if handled or pass_through:
		global g_RepeatCount
		g_RepeatCount = None
		SetPrevCommand(None)

	g_HandingKey = False
	
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

