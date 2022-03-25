#------------------------------------------------------------------------
import os
import N10X

#------------------------------------------------------------------------
# Vim style editing
#
# To enable Vim editing set Vim to true oin the 10x settings file
#
#------------------------------------------------------------------------
g_CommandMode = False

g_PrevCommand = None

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
# Command Functions

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

	if command == "i":
		EnableInsertMode()
	
	elif command == "dd":
		N10X.Editor.ExecuteCommand("Cut")

	elif command == "yy":
		N10X.Editor.ExecuteCommand("Copy")

	elif command == "p":
		N10X.Editor.ExecuteCommand("Paste")

	elif \
		command == "c" or \
		command == "d" or \
		command == "y":
		g_PrevCommand = command

	elif command == "h":
		N10X.Editor.ExecuteCommand("MoveCursorLeft")
	
	elif command == "l":
		N10X.Editor.ExecuteCommand("MoveCursorRight")
	
	elif command == "k":
		N10X.Editor.ExecuteCommand("MoveCursorUp")
	
	elif command == "j":
		N10X.Editor.ExecuteCommand("MoveCursorDown")

	if command == "0":
		MoveToStartOfLine()
		
	elif command == "$":
		MoveToEndOfLine()

	elif command == "b":
		N10X.Editor.ExecuteCommand("MoveCursorPrevWord")

	elif command == "w":
		N10X.Editor.ExecuteCommand("MoveCursorNextWord")
	
	elif command == "cw":
		CutToEndOfWordAndInsert()

#------------------------------------------------------------------------
def HandleCommandModeKey(key, shift, control, alt):

	if key == "Left":
		N10X.Editor.ExecuteCommand("MoveCursorLeft")
	
	elif key == "Right":
		N10X.Editor.ExecuteCommand("MoveCursorRight")
	
	elif key == "Up":
		N10X.Editor.ExecuteCommand("MoveCursorUp")
	
	elif key == "Down":
		N10X.Editor.ExecuteCommand("MoveCursorDown")

#------------------------------------------------------------------------
def HandleInsertModeKey(key, shift, control, alt):
	print("HandleInsertModeKey key:" + str(key))
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
	global g_CommandMode
	if g_CommandMode:
		HandleCommandModeKey(key, shift, control, alt)
	else:
		HandleInsertModeKey(key, shift, control, alt)
	return g_CommandMode

#------------------------------------------------------------------------
# Called when a char is to be inserted into the text editor.
# Return true to surpress the char key.
# If we are in command mode surpress all char keys
def OnInterceptCharKey(c):
	global g_CommandMode
	if g_CommandMode:
		HandleCommandModeChar(c)
		return True
	
#------------------------------------------------------------------------
def EnableVim():
	global g_CommandMode
	enable_vim = N10X.Editor.GetSetting("Vim") == "true"
	
	if g_CommandMode != enable_vim:
	
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
N10X.Editor.CallOnMainThread(InitialiseVim)

