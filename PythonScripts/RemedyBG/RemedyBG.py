'''
RemedyBG debugger integration for 10x (10xeditor.com) 
RemedyBG: https://remedybg.handmade.network/ (should be above 0.3.8)
Version: 0.5.3
Original Script author: septag@discord

Options:
	- RemedyBG.Path: Path to remedybg.exe. If not set, the script will assume remedybg.exe is in PATH or current dir
	- RemedyBG.OutputDebugText: (default=true) receives and output debug text to 10x output

Commands:
	- RDBG_StartDebugging: Same behavior as default StartDebugging. Launches remedybg if not opened before and runs the 
						   executable in the debugger. 
						   If "BuildBeforeStartDebugging" option is set, it builds it before running the session
						   If debugger is already running, it does nothing
						   If debugger is in suspend/pause state, it continues the debugger
	- RDBG_StopDebugging: Stops if debugger is running

Experimental:
	- RDBG_RunToCursor: Run up to selected cursor. User should already started a debugging session before calling this
	- RDBG_GoToCursor: Goes to selected cursor in remedybg and bring it to foreground
	- RDBG_AddSelectionToWatch: Adds selected text to remedybg's watch window #1

History:
  0.5.3
    - Fixed debug working directory being invalid or relative path

  0.5.2
	- Fixed a regression bug for remedybg filepaths introduced in the previous version

  0.5.1
	- Fix for breakpoint filepath inconsistencies between slash and backslash

  0.5.0
	- Added support for new RemedyBG events and breakpoint syncing
	- Added breakpoint fixing/resolving by RemedyBG

  0.4.3
	- Fixed/Improved opening connection to remedybg for the first time

  0.4.2
	- Fixed current directory path being empty issue
	- Improved error handling when openning a session
	
  0.4.1
	- Added BREAKPOINT_HIT handling. Now when breakpoint hits it moves 10x editor to it's position
	- Adding breakpoints also makes remedybg to go to that position as well
	- Two sided breakpoint data (breakpoint_rdbg dictionary)
	- Fixed GetBreakpoints when opening a new session

  0.3.0
	- Added event receiver in update function 
	- Added output debug text to 10x output and a new option 'RemedyBG.OutputDebugText'
  0.2.0
	- Added new AddBreakpointUpdatedFunction and implemented proper breakpoint syncing from 10x to remedybg
	- Changed from GetSelectionStart/End API to new GetSelection function in AddWatch
  0.1.0
	- First release
'''

from enum import Enum, IntEnum
from optparse import Option
import win32file, win32pipe, pywintypes, win32api
import io, os, ctypes, time, typing, subprocess

from N10X import Editor

HANDLE = typing.Any
PREFIX:str = '\\\\.\\pipe\\'
TITLE:str = 'RemedyBG'
PROCESS_POLL_INTERVAL:float = 1.0

class Options():
	executable:str
	output_debug_text:bool
	build_before_debug:bool

	def __init__(self):
		self.executable = Editor.GetSetting("RemedyBG.Path").strip()
		if not self.executable:
			self.executable = 'remedybg.exe'

		self.output_debug_text = True
		output_debug_text = Editor.GetSetting("RemedyBG.OutputDebugText") 
		if output_debug_text and output_debug_text == 'false':
			self.output_debug_text = False

		if  Editor.GetSetting("BuildBeforeStartDebugging") and Editor.GetSetting("BuildBeforeStartDebugging") == 'true':
			self.build_before_debug = True
		else:
			self.build_before_debug = False

class TargetState(IntEnum):
	NONE = 1
	SUSPENDED = 2
	EXECUTING = 3

class Command(IntEnum):
	BRING_DEBUGGER_TO_FOREGROUND = 50
	COMMAND_EXIT_DEBUGGER = 75
	GET_IS_SESSION_MODIFIED = 100
	GET_SESSION_FILENAME = 101
	NEW_SESSION = 102
	OPEN_SESSION = 103
	SAVE_SESSION = 104
	SAVE_AS_SESSION = 105
	GOTO_FILE_AT_LINE = 200
	CLOSE_FILE = 201
	CLOSE_ALL_FILES = 202
	GET_CURRENT_FILE = 203
	GET_TARGET_STATE = 300
	START_DEBUGGING = 301
	STOP_DEBUGGING = 302
	RESTART_DEBUGGING = 303
	CONTINUE_EXECUTION = 312
	RUN_TO_FILE_AT_LINE = 313
	GET_BREAKPOINT_LOCATIONS = 601
	ADD_BREAKPOINT_AT_FILENAME_LINE = 604
	UPDATE_BREAKPOINT_LINE = 608
	DELETE_BREAKPOINT = 610
	DELETE_ALL_BREAKPOINTS = 611
	ADD_WATCH = 701

class BreakpointKind(IntEnum):
	FUNCTION_NAME = 1
	FILENAME_LINE = 2
	ADDRESS = 3
	PROCESSOR = 4

class CommandResult(IntEnum):
	UNKNOWN = 0
	OK = 1
	FAIL = 2
	ABORTED = 3
	INVALID_COMMAND = 4
	BUFFER_TOO_SMALL = 5
	FAILED_OPENING_FILE = 6
	FAILED_SAVING_SESSION = 7
	INVALID_ID = 8
	INVALID_TARGET_STATE = 9
	FAILED_NO_ACTIVE_CONFIG = 10
	INVALID_BREAKPOINT_KIND = 11

class EventType(IntEnum):
	KIND_EXIT_PROCESS = 100,
	KIND_BREAKPOINT_HIT = 600,
	KIND_BREAKPOINT_RESOLVED = 601
	OUTPUT_DEBUG_STRING = 800
	BREAKPOINT_ADDED = 602
	BREAKPOINT_MODIFIED = 603
	BREAKPOINT_REMOVED = 604

class Session:
	def __init__(self, name:str):
		self.name:str = name
		self.process:subprocess.Popen = None
		self.cmd_pipe:HANDLE = None
		self.event_pipe:HANDLE = None
		self.run_after_build:bool = False
		self.last_poll_time:float = 0
		self.ignore_next_remove_breakpoint:bool = False
		self.breakpoints = {}
		self.breakpoints_rdbg = {}

	def get_breakpoint_locations(self, bp_id:int):
		if self.cmd_pipe is None:
			return 0		
		cmd_buffer = io.BytesIO()
		cmd_buffer.write(ctypes.c_uint16(Command.GET_BREAKPOINT_LOCATIONS))
		cmd_buffer.write(ctypes.c_uint32(bp_id))
		try:
			out_data = win32pipe.TransactNamedPipe(self.cmd_pipe, cmd_buffer.getvalue(), 8192, None)
		except pywintypes.error as pipe_error:
			print('RDBG', pipe_error)
			self.close(stop=False)
			return ('', 0)

		out_buffer = io.BytesIO(out_data[1])		
		result_code : CommandResult = int.from_bytes(out_buffer.read(2), 'little')
		if result_code == 1:
			num_locs:int = int.from_bytes(out_buffer.read(2), 'little')
			# TODO: do we have several locations for a single breakpoint ?
			if num_locs > 0:
				address:int = int.from_bytes(out_buffer.read(8), 'little')
				module_name:str = out_buffer.read(int.from_bytes(out_buffer.read(2), 'little')).decode('utf-8')
				filename:str = out_buffer.read(int.from_bytes(out_buffer.read(2), 'little')).decode('utf-8')
				line_num:int = int.from_bytes(out_buffer.read(4), 'little')
				return (filename, line_num)
			else:
				return ('', 0)
		else:
			return ('', 0)		

	def send_command(self, cmd:Command, **cmd_args)->int:
		if self.cmd_pipe is None:
			return 0

		cmd_buffer = io.BytesIO()
		cmd_buffer.write(ctypes.c_uint16(cmd))

		if cmd == Command.ADD_BREAKPOINT_AT_FILENAME_LINE:
			filepath:str = cmd_args['filename']
			cmd_buffer.write(ctypes.c_uint16(len(filepath)))
			cmd_buffer.write(bytes(filepath, 'utf-8'))
			cmd_buffer.write(ctypes.c_uint32(cmd_args['line']))
			cmd_buffer.write(ctypes.c_uint16(0))
		elif cmd == Command.DELETE_BREAKPOINT:
			if cmd_args['id'] in self.breakpoints:
				rdbg_id = self.breakpoints[cmd_args['id']]
				cmd_buffer.write(ctypes.c_uint32(rdbg_id))
				self.breakpoints.pop(cmd_args['id'])
				if rdbg_id in self.breakpoints_rdbg:
					self.breakpoints_rdbg.pop(rdbg_id)
			else:
				return 0
		elif cmd == Command.GOTO_FILE_AT_LINE:
			filepath:str = cmd_args['filename']
			cmd_buffer.write(ctypes.c_uint16(len(filepath)))
			cmd_buffer.write(bytes(filepath, 'utf-8'))
			cmd_buffer.write(ctypes.c_uint32(cmd_args['line']))
		elif cmd == Command.START_DEBUGGING:
			cmd_buffer.write(ctypes.c_uint8(0))
		elif cmd == Command.STOP_DEBUGGING:
			pass
		elif cmd == Command.CONTINUE_EXECUTION:
			pass
		elif cmd == Command.RUN_TO_FILE_AT_LINE:
			filepath:str = cmd_args['filename']
			cmd_buffer.write(ctypes.c_uint16(len(filepath)))
			cmd_buffer.write(bytes(filepath, 'utf-8'))
			cmd_buffer.write(ctypes.c_uint32(cmd_args['line']))
		elif cmd == Command.GET_TARGET_STATE:
			pass
		elif cmd == Command.ADD_WATCH:
			expr:str = cmd_args['expr']
			cmd_buffer.write(ctypes.c_uint8(1)) 	# watch window 1
			cmd_buffer.write(ctypes.c_uint16(len(expr)))
			cmd_buffer.write(bytes(expr, 'utf-8'))
			cmd_buffer.write(ctypes.c_uint16(0))	
		elif cmd == Command.UPDATE_BREAKPOINT_LINE:
			if cmd_args['id'] in self.breakpoints:
				rdbg_id = self.breakpoints[cmd_args['id']]
				cmd_buffer.write(ctypes.c_uint32(rdbg_id))
				cmd_buffer.write(ctypes.c_uint32(cmd_args['line']))
		else:
			assert 0
			return 0		# not implemented

		try:
			out_data = win32pipe.TransactNamedPipe(self.cmd_pipe, cmd_buffer.getvalue(), 8192, None)
		except pywintypes.error as pipe_error:
			print('RDBG', pipe_error)
			self.close(stop=False)
			return 0

		out_buffer = io.BytesIO(out_data[1])		
		result_code : CommandResult = int.from_bytes(out_buffer.read(2), 'little')
		if result_code == 1:
			if cmd == Command.ADD_BREAKPOINT_AT_FILENAME_LINE:
				bp_id = int.from_bytes(out_buffer.read(4), 'little')
				if bp_id not in self.breakpoints_rdbg:
					self.breakpoints[cmd_args['id']] = bp_id
					self.breakpoints_rdbg[bp_id] = (cmd_args['id'], cmd_args['filename'], cmd_args['line'])
				else:
					print('RDBG: Breakpoint (%i) %s@%i skipped, because it will not get triggered' % (cmd_args['id'], cmd_args['filename'], cmd_args['line']))
					self.ignore_next_remove_breakpoint = True
					Editor.RemoveBreakpointById(cmd_args['id'])
				return bp_id
			elif cmd == Command.GET_TARGET_STATE:
				return int.from_bytes(out_buffer.read(2), 'little')
			elif cmd == Command.ADD_WATCH:
				return int.from_bytes(out_buffer.read(4), 'little')
		else:
			print('RDBG: ' + str(cmd) + ' failed')
			return 0

		return 1

	def open(self)->bool:
		try:
			debug_cmd = Editor.GetDebugCommand().strip()
			debug_args = Editor.GetDebugCommandArgs().strip()
			debug_cwd = Editor.GetDebugCommandCwd().strip()

			if debug_cmd == '':
				Editor.ShowMessageBox(TITLE, 'Debug command is empty. Perhaps active project is not set in workspace tree?')
				return False
				
			full_path = os.path.dirname(os.path.abspath(Editor.GetWorkspaceFilename()))
			full_path = os.path.join(full_path, debug_cwd)
			if full_path != '' and not os.path.isdir(full_path):
				Editor.ShowMessageBox(TITLE, 'Debugger working directory is invalid: ' + full_path)

			args = _rdbg_options.executable + ' --servername ' + self.name + ' "' + debug_cmd + '" ' + debug_args
			self.process = subprocess.Popen(args, cwd=full_path)
			time.sleep(0.1)

			assert self.cmd_pipe == None
			name = PREFIX + self.name
			
			# for the first pipe:
			# we have to keep trying for some time, because depending on the machine, it might take a while until remedybg creates pipes
			pipe_success:bool = False
			wait_time:float = 0.1
			for retry in range(0, 5):
				try:
					self.cmd_pipe = win32file.CreateFile(name, win32file.GENERIC_READ|win32file.GENERIC_WRITE, \
						0, None, win32file.OPEN_EXISTING, 0, None)
				except pywintypes.error:
					time.sleep(wait_time)
					wait_time = wait_time*2.0
					continue
				except Exception as e:
					Editor.ShowMessageBox(TITLE, 'Pipe error:' +  str(e))
					return False
				pipe_success = True
				break

			if not pipe_success:
				Editor.ShowMessageBox(TITLE, 'Named pipe could not be opened to remedybg. Make sure remedybg version is above 0.3.8')
				return False
			
			win32pipe.SetNamedPipeHandleState(self.cmd_pipe, win32pipe.PIPE_READMODE_MESSAGE, None, None)

			assert self.event_pipe == None
			name = name + '-events'
			self.event_pipe = win32file.CreateFile(name, win32file.GENERIC_READ|256, \
				0, None, win32file.OPEN_EXISTING, 0, None)
			win32pipe.SetNamedPipeHandleState(self.event_pipe, win32pipe.PIPE_READMODE_MESSAGE, None, None)

			print("RDBG: Connection established")

			for bp in Editor.GetBreakpoints():
				self.send_command(Command.ADD_BREAKPOINT_AT_FILENAME_LINE, id=bp[0], filename=bp[1], line=bp[2])

		except FileNotFoundError as not_found:
			Editor.ShowMessageBox(TITLE, str(not_found) + ': ' + _rdbg_options.executable)
			return False
		except pywintypes.error as connection_error:
			Editor.ShowMessageBox(TITLE, str(connection_error))
			return False
		except OSError as os_error:
			Editor.ShowMessageBox(TITLE, str(os_error))
			return False
		
		return True

	def close(self, stop=True):
		if stop:
			self.stop()

		if self.cmd_pipe:
			win32file.CloseHandle(self.cmd_pipe)
			self.cmd_pipe = None

		if self.event_pipe is not None:
			win32file.CloseHandle(self.event_pipe)
			self.event_pipe = None

		if self.process is not None:
			self.process.kill()
			self.process = None

		print("RDBG: Connection closed")

	def run(self):
		global _rdbg_options
		
		if self.cmd_pipe is not None:
			state:TargetState = self.send_command(Command.GET_TARGET_STATE)
			if state == TargetState.NONE:
				self.send_command(Command.START_DEBUGGING)
			elif state == TargetState.SUSPENDED:
				self.send_command(Command.CONTINUE_EXECUTION)
			elif state == TargetState.EXECUTING:
				pass
			if _rdbg_options.output_debug_text:
				Editor.ShowOutput()

	def stop(self):
		if self.cmd_pipe is not None:
			state:TargetState = _rdbg_session.send_command(Command.GET_TARGET_STATE)
			if state == TargetState.SUSPENDED or state == TargetState.EXECUTING:
				_rdbg_session.send_command(Command.STOP_DEBUGGING)

	def next_breakpoint_ignored(self):
		if self.ignore_next_remove_breakpoint:
			self.ignore_next_remove_breakpoint = False
			return True
		return False

	def update(self)->bool:
		global _rdbg_options

		tm:float = time.time()
		if tm - self.last_poll_time >= 1.0:
			self.last_poll_time = tm

			if self.process is None:
				return False

			if self.process is not None and self.process.poll() is not None:
				print('RDBG: RemedyBG quit with code: %i' % (self.process.poll()))
				self.process = None
				self.close(stop=False)
				return False

		if self.process is not None and self.event_pipe is not None:
			try:
				buffer, nbytes, result = win32pipe.PeekNamedPipe(self.event_pipe, 0)
				if nbytes:
					hr, data = win32file.ReadFile(self.event_pipe, nbytes, None)
					event_buffer = io.BytesIO(data)
					event_type = int.from_bytes(event_buffer.read(2), 'little')
					if event_type == EventType.OUTPUT_DEBUG_STRING and _rdbg_options.output_debug_text:
						text = event_buffer.read(int.from_bytes(event_buffer.read(2), 'little')).decode('utf-8')
						print('RDBG:', text.strip())
					elif event_type == EventType.KIND_BREAKPOINT_HIT:
						bp_id = int.from_bytes(event_buffer.read(4), 'little')
						if bp_id in self.breakpoints_rdbg:
							id_10x, filename, line = self.breakpoints_rdbg[bp_id]
							filename = filename.replace('\\', '/')
							Editor.OpenFile(filename)
							Editor.SetCursorPos((0, line-1)) # convert to index-based
					elif event_type == EventType.KIND_BREAKPOINT_RESOLVED:
						bp_id = int.from_bytes(event_buffer.read(4), 'little')
						if bp_id in self.breakpoints_rdbg:
							filename, new_line = self.get_breakpoint_locations(bp_id)
							id_10x, filename_old, line = self.breakpoints_rdbg[bp_id]

							if filename != '':
								self.breakpoints_rdbg[bp_id] = (id_10x, filename_old, new_line)
								Editor.UpdateBreakpoint(id_10x, new_line)
							else:
								self.breakpoints_rdbg.pop(bp_id)
								self.breakpoints.pop(id_10x)
								self.ignore_next_remove_breakpoint = True
								Editor.RemoveBreakpointById(id_10x)
					elif event_type == EventType.BREAKPOINT_ADDED:
						bp_id = int.from_bytes(event_buffer.read(4), 'little')
						if bp_id not in self.breakpoints_rdbg:
							filename, line = self.get_breakpoint_locations(bp_id)
							if filename != '':
								filename = filename.replace('\\', '/')
								id_10x:int = Editor.AddBreakpoint(filename, line)
								self.breakpoints_rdbg[bp_id] = (id_10x, filename, line)
								self.breakpoints[id_10x] = bp_id
					elif event_type == EventType.BREAKPOINT_REMOVED:
						bp_id = int.from_bytes(event_buffer.read(4), 'little')
						if bp_id in self.breakpoints_rdbg:
							id_10x, filename, line = self.breakpoints_rdbg[bp_id]
							if id_10x in self.breakpoints:
								self.breakpoints.pop(id_10x)
							self.breakpoints_rdbg.pop(bp_id)
							self.ignore_next_remove_breakpoint = True
							Editor.RemoveBreakpointById(id_10x)
					elif event_type == EventType.BREAKPOINT_MODIFIED:
						# used for enabling/disabling breakpoints, we don't have that now
						pass

			except win32api.error as pipe_error:
				print('RDBG:', pipe_error)
				self.close(stop=False)
				return False
			
		return True

def RDBG_StartDebugging():
	global _rdbg_session
	global _rdbg_options

	if _rdbg_session is not None:
		# poll for debugger state. if we are in the middle of debugging, then continue, otherwise run/build-run
		state:TargetState = _rdbg_session.send_command(Command.GET_TARGET_STATE)
		if state == TargetState.NONE:
			if _rdbg_options.build_before_debug:
				_rdbg_session.run_after_build = True
				Editor.ExecuteCommand('BuildActiveWorkspace')
			else:
				_rdbg_session.run()
		elif state == TargetState.SUSPENDED:
			_rdbg_session.run()
	else:
		if Editor.GetWorkspaceFilename() == '':
			Editor.ShowMessageBox(TITLE, 'No Workspace is opened for debugging')
			return

		print('RDBG: Workspace: ' + Editor.GetWorkspaceFilename())

		_rdbg_session = Session(os.path.basename(Editor.GetWorkspaceFilename()))
		if _rdbg_session.open():
			if _rdbg_options.build_before_debug:
				_rdbg_session.run_after_build = True
				Editor.ExecuteCommand('BuildActiveWorkspace')
			else:
				_rdbg_session.run()			
		else:
			_rdbg_session = None

def RDBG_StopDebugging():
	global _rdbg_session
	if _rdbg_session is not None:
		_rdbg_session.stop()

def RDBG_RunToCursor():
	global _rdbg_session
	if _rdbg_session is not None:
		filename:str = Editor.GetCurrentFilename()
		if filename != '':
			_rdbg_session.send_command(Command.RUN_TO_FILE_AT_LINE, filename=filename, line=Editor.GetCursorPos()[1])

def RDBG_GoToCursor():
	global _rdbg_session
	if _rdbg_session is not None:
		filename:str = Editor.GetCurrentFilename()
		if filename != '':
			_rdbg_session.send_command(Command.GOTO_FILE_AT_LINE, filename=filename, line=Editor.GetCursorPos()[1])

def RDBG_AddSelectionToWatch():
	global _rdbg_session
	if _rdbg_session is not None:
		selection:str = Editor.GetSelection()
		if selection != '':
			_rdbg_session.send_command(Command.ADD_WATCH, expr=selection)
		
def _RDBG_WorkspaceOpened():
	global _rdbg_session
	if _rdbg_session is not None:
		print('RDBG: Closing previous debug session "%s".' % (_rdbg_session.name))
		_rdbg_session.close()
		_rdbg_session = None

def _RDBG_AddBreakpoint(id, filename, line):
	global _rdbg_session
	if _rdbg_session is not None:
		_rdbg_session.send_command(Command.ADD_BREAKPOINT_AT_FILENAME_LINE, id=id, filename=filename, line=line)
		_rdbg_session.send_command(Command.GOTO_FILE_AT_LINE, filename=filename, line=line)

def _RDBG_RemoveBreakpoint(id, filename, line):
	global _rdbg_session
	if _rdbg_session is not None and not _rdbg_session.next_breakpoint_ignored():
		_rdbg_session.send_command(Command.DELETE_BREAKPOINT, id=id, filename=filename, line=line)

def _RDBG_UpdateBreakpoint(id, filename, line):
	global _rdbg_session
	if _rdbg_session is not None:
		_rdbg_session.send_command(Command.UPDATE_BREAKPOINT_LINE, id=id, line=line)

def _RDBG_BuildFinished(result):
	global _rdbg_session
	
	if _rdbg_session is not None:
		if _rdbg_session.run_after_build and result:
			_rdbg_session.run()	
		_rdbg_session.run_after_build = False

def _RDBG_Update():
	global _rdbg_session

	if _rdbg_session is not None:
		if not _rdbg_session.update():
			_rdbg_session = None

def _RDBG_SettingsChanged():
	global _rdbg_options
	_rdbg_options = Options()

_rdbg_session:Session = None
_rdbg_options:Options = Options()


Editor.AddBreakpointAddedFunction(_RDBG_AddBreakpoint)
Editor.AddBreakpointRemovedFunction(_RDBG_RemoveBreakpoint)
Editor.AddBreakpointUpdatedFunction(_RDBG_UpdateBreakpoint)

Editor.AddOnWorkspaceOpenedFunction(_RDBG_WorkspaceOpened)
Editor.AddBuildFinishedFunction(_RDBG_BuildFinished)
Editor.AddUpdateFunction(_RDBG_Update)
Editor.AddOnSettingsChangedFunction(_RDBG_SettingsChanged)
