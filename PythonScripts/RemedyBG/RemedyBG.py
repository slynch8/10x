'''
RemedyBG debugger integration for 10x (10xeditor.com) 
RemedyBG: https://remedybg.handmade.network/ (should be above 0.3.8)
Version: 0.10.1
Original Script author: septag@discord

RDBG_Options:
    - RemedyBG.Hook: (default=False) Hook RemedyBg into default Start/Stop/Restart debugging commands instead of the default msvc debugger integration
    - RemedyBG.Path: Path to remedybg.exe. If not set, the script will assume remedybg.exe is in PATH or current dir
    - RemedyBG.OutputDebugText: (default=True) receives and output debug text to 10x output
    - RemedyBG.WorkDir: Path that remedy will use as a working directory
    - RemedyBG.KeepSessionOnActiveChange: (default=False) when active project or config is changed, it leaves the previously opened RemedyBG session
                                           This is useful when you want to debug multiple binaries within a project like client/server apps
    - RemedyBG.StartProcessExtraCommand: Extra 10x command that will be executed after process is started in RemedyBG
    - RemedyBG.StopProcessExtraCommand: Extra 10x command that will be executed after process is stopped in RemedyBG
    - RemedyBG.SnapWindow: (default='') Automatically snaps remedybg window to the right or left of the 10x window when debugging starts
                                          Available options are 'top-right', 'top-left', 'bottom-right', 'bottom-left'

Commands:
    - RDBG_StartDebugging: Same behavior as default StartDebugging. Launches remedybg if not opened before and runs the 
                           executable in the debugger. 
                           If "BuildBeforeStartDebugging" option is set, it builds it before running the session
                           If debugger is already running, it does nothing
                           If debugger is in suspend/pause state, it continues the debugger
    - RDBG_StopDebugging: Stops if debugger is running
    - RDBG_RestartDebugging: Restart debugging 

Extras:
    - RDBG_RunToCursor: Run up to selected cursor. User should already started a debugging session before calling this
    - RDBG_GoToCursor: Goes to selected cursor in remedybg and bring it to foreground
    - RDBG_AddSelectionToWatch: Adds selected text to remedybg's watch window #1
    - RDBG_StepInto: Steps into line when debugging, also updates the cursor position in 10x according to position in remedybg
    - RDBG_StepOver: Steps over the line when debugging, also updates the cursor position in 10x according to position in remedybg
    - RDBG_StepOut: Steps out of the current line when debugging, also updates the cursor position in 10x according to position in remedybg

History:
  0.10.1:
    - Added the ability to retrieve unresolved breakpoints from remedybg

  0.10.0
    - Added Setting override for `VisualStudioSync` and `BuildBeforeStartDebugging`
    - Added support for `StopDebuggingOnBuild` setting

  0.9.1
    - Removed double quotes from debug_args (this might create regression bugs, we'll see)

  0.9.0
    - Added StartProcessExtraCommand, StopProcessExtraCommand settings to run commands on target start/stop
    - Snap window option to snap remedybg window to 10x window when debugging starts

  0.8.1
    - Prefix all types with RDBG_ to avoid global name collisions with other scripts

  0.8.0
    - Improved debugger session names, now debugging sessions are more immune to overlapping
    - Added `RemedyBG.KeepSessionOnActiveChange` that keeps the current debugging session when active project or config is changed

  0.7.0
    - Invalidates RemedyBG session if either active project/config/platform is changed

  0.6.3
    - Minor bug fixed on workspace paths with spaces

  0.6.2
    - Changed tabs to spaces :(
    - Fixed a minor bug in RemedyBG.Hook
    - Added target state tracking (not yet working as it should/unsupported by 10x)

  0.6.1
    - Added RemedyBG.Hook option to hook remedybg to default debugging functions instead of msvc integration

  0.6.0
    - Added new location sync events with RemedyBg
    - Added experimental StepInto/StepOver/StepOut functions

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
import win32file, win32pipe, pywintypes, win32api, win32gui
import io, os, ctypes, time, typing, subprocess

from N10X import Editor

RDBG_HANDLE = typing.Any
RDBG_PREFIX:str = '\\\\.\\pipe\\'
RDBG_TITLE:str = 'RemedyBG'
RDBG_PROCESS_POLL_INTERVAL:float = 1.0

class RDBG_Options():
    def __init__(self):
        global _rdbg_options_override

        self.executable = Editor.GetSetting("RemedyBG.Path").strip()
        if not self.executable:
            self.executable = 'remedybg.exe'

        self.output_debug_text = True
        output_debug_text = Editor.GetSetting("RemedyBG.OutputDebugText") 
        if output_debug_text and output_debug_text == 'false':
            self.output_debug_text = False
        else:
            self.output_debug_text = True

        hook_calls = Editor.GetSetting("RemedyBG.Hook")
        if hook_calls and hook_calls == 'true':
            self.hook_calls = True
        else:
            self.hook_calls = False

        _rdbg_options_override = True
        if self.hook_calls:
            Editor.OverrideSetting('VisualStudioSync', 'false')
        else:
            Editor.RemoveSettingOverride('VisualStudioSync')
        _rdbg_options_override = False

        keep_session = Editor.GetSetting("RemedyBG.KeepSessionOnActiveChange")
        if keep_session and keep_session == 'true':
            self.keep_session = True
        else:
            self.keep_session = False

        if  Editor.GetSetting("BuildBeforeStartDebugging") and Editor.GetSetting("BuildBeforeStartDebugging") == 'true':
            self.build_before_debug = True
        else:
            self.build_before_debug = False
        print('BuildBeforeStartDebugging =', self.build_before_debug)

        if  Editor.GetSetting("StopDebuggingOnBuild") and Editor.GetSetting("StopDebuggingOnBuild") == 'true':
            self.stop_debug_on_build = True
        else:
            self.stop_debug_on_build = False

        self.start_debug_command:str = Editor.GetSetting("RemedyBG.StartProcessExtraCommand").strip()
        self.stop_debug_command:str = Editor.GetSetting("RemedyBG.StopProcessExtraCommand").strip()
        self.snap_window:str = Editor.GetSetting("RemedyBG.SnapWindow").strip().lower()
        self.hwnd = win32gui.GetActiveWindow()

class RDBG_TargetState(IntEnum):
    NONE = 1
    SUSPENDED = 2
    EXECUTING = 3

class RDBG_Command(IntEnum):
    BRING_DEBUGGER_TO_FOREGROUND = 50
    SET_WINDOW_POS = 51
    GET_WINDOW_POS = 52
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
    STEP_INTO_BY_LINE = 307
    STEP_OVER_BY_LINE = 309
    STEP_OUT = 311,
    CONTINUE_EXECUTION = 312
    RUN_TO_FILE_AT_LINE = 313
    ADD_BREAKPOINT_AT_FILENAME_LINE = 604
    UPDATE_BREAKPOINT_LINE = 608
    DELETE_BREAKPOINT = 610
    GET_BREAKPOINT = 612
    DELETE_ALL_BREAKPOINTS = 611
    ADD_WATCH = 701

class RDBG_BreakpointKind(IntEnum):
    FUNCTION_NAME = 1
    FILENAME_LINE = 2
    ADDRESS = 3
    PROCESSOR = 4

class RDBG_CommandResult(IntEnum):
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

class RDBG_SourceLocChangedReason(IntEnum):
    UNSPECIFIED = 0
    COMMAND_LINE = 1
    DRIVER = 2
    BREAKPOINT_SELECTED = 3
    CURRENT_FRAME_CHANGED = 4
    THREAD_CHANGED = 5
    BREAKPOINT_HIT = 6
    EXCEPTION_HIT = 7
    STEP_OVER = 8
    STEP_IN = 9
    STEP_OUT = 10
    NON_USER_BREAKPOINT = 11
    DEBUG_BREAK = 12

class RDBG_EventType(IntEnum):
    EXIT_PROCESS = 100
    TARGET_STARTED = 101
    TARGET_ATTACHED = 102
    TARGET_DETACHED = 103
    TARGET_CONTINUED = 104
    KIND_BREAKPOINT_HIT = 600
    KIND_BREAKPOINT_RESOLVED = 601
    OUTPUT_DEBUG_STRING = 800
    BREAKPOINT_ADDED = 602
    BREAKPOINT_MODIFIED = 603
    BREAKPOINT_REMOVED = 604
    SOURCE_LOCATION_CHANGED = 200

class RDBG_Session:
    def __init__(self):
        self.process:subprocess.Popen = None
        self.cmd_pipe:RDBG_HANDLE = None
        self.event_pipe:RDBG_HANDLE = None
        self.run_after_build:bool = False
        self.last_poll_time:float = 0
        self.ignore_next_remove_breakpoint:bool = False
        self.breakpoints = {}
        self.breakpoints_rdbg = {}
        self.target_state:RDBG_TargetState = RDBG_TargetState.NONE
        self.active_project:str = ""    # project_path;config;platform

        workspace_name:str = os.path.basename(Editor.GetWorkspaceFilename())
        self.update_active_project()
        self.name = workspace_name + '_' + hex(hash(self.active_project))

    def get_breakpoint(self, bp_id:int):
        if self.cmd_pipe is None:
            return 0
        cmd_buffer = io.BytesIO()
        cmd_buffer.write(ctypes.c_uint16(RDBG_Command.GET_BREAKPOINT))
        cmd_buffer.write(ctypes.c_uint32(bp_id))
        try:
            out_data = win32pipe.TransactNamedPipe(self.cmd_pipe, cmd_buffer.getvalue(), 8192, None)
        except pywintypes.error as pipe_error:
            print('RDBG', pipe_error)
            self.close(stop=False)
            return ('', 0)

        out_buffer = io.BytesIO(out_data[1])
        result_code : RDBG_CommandResult = int.from_bytes(out_buffer.read(2), 'little')
        if result_code == 1:
            uid:int = int.from_bytes(out_buffer.read(4), 'little')
            enabled:bool = int.from_bytes(out_buffer.read(1), 'little')
            module_name:str = out_buffer.read(int.from_bytes(out_buffer.read(2), 'little')).decode('utf-8')
            condition_expr:str = out_buffer.read(int.from_bytes(out_buffer.read(2), 'little')).decode('utf-8')
            kind:int = int.from_bytes(out_buffer.read(1), 'little')
            match kind:
                case RDBG_BreakpointKind.FUNCTION_NAME:
                    function_name:str = out_buffer.read(int.from_bytes(out_buffer.read(2), 'little')).decode('utf-8')
                    overload_id:int = int.from_bytes(out_buffer.read(4), 'little')

                case RDBG_BreakpointKind.FILENAME_LINE:
                    filename:str = out_buffer.read(int.from_bytes(out_buffer.read(2), 'little')).decode('utf-8')
                    line_num:int = int.from_bytes(out_buffer.read(4), 'little')
                    return (filename, line_num)

                case RDBG_BreakpointKind.ADDRESS:
                    address:int = int.from_bytes(out_buffer.read(8), 'little')

                case RDBG_BreakpointKind.PROCESSOR:
                    address_expression:str = out_buffer.read(int.from_bytes(out_buffer.read(2), 'little')).decode('utf-8')
                    num_bytes:int = int.from_bytes(out_buffer.read(1), 'little')
                    access_kind:int = int.from_bytes(out_buffer.read(1), 'little')

        return ('', 0)

    def send_command(self, cmd:RDBG_Command, **cmd_args)->int:
        if self.cmd_pipe is None:
            return 0

        cmd_buffer = io.BytesIO()
        cmd_buffer.write(ctypes.c_uint16(cmd))

        if cmd == RDBG_Command.ADD_BREAKPOINT_AT_FILENAME_LINE:
            filepath:str = cmd_args['filename']
            cmd_buffer.write(ctypes.c_uint16(len(filepath)))
            cmd_buffer.write(bytes(filepath, 'utf-8'))
            cmd_buffer.write(ctypes.c_uint32(cmd_args['line']))
            cmd_buffer.write(ctypes.c_uint16(0))
        elif cmd == RDBG_Command.DELETE_BREAKPOINT:
            if cmd_args['id'] in self.breakpoints:
                rdbg_id = self.breakpoints[cmd_args['id']]
                cmd_buffer.write(ctypes.c_uint32(rdbg_id))
                self.breakpoints.pop(cmd_args['id'])
                if rdbg_id in self.breakpoints_rdbg:
                    self.breakpoints_rdbg.pop(rdbg_id)
            else:
                return 0
        elif cmd == RDBG_Command.GOTO_FILE_AT_LINE:
            filepath:str = cmd_args['filename']
            cmd_buffer.write(ctypes.c_uint16(len(filepath)))
            cmd_buffer.write(bytes(filepath, 'utf-8'))
            cmd_buffer.write(ctypes.c_uint32(cmd_args['line']))
        elif cmd == RDBG_Command.START_DEBUGGING:
            cmd_buffer.write(ctypes.c_uint8(0))
        elif cmd == RDBG_Command.STEP_INTO_BY_LINE:
            pass
        elif cmd == RDBG_Command.STEP_OVER_BY_LINE:
            pass
        elif cmd == RDBG_Command.STEP_OVER_BY_LINE:
            pass
        elif cmd == RDBG_Command.STOP_DEBUGGING:
            pass
        elif cmd == RDBG_Command.RESTART_DEBUGGING:
            pass
        elif cmd == RDBG_Command.CONTINUE_EXECUTION:
            pass
        elif cmd == RDBG_Command.RUN_TO_FILE_AT_LINE:
            filepath:str = cmd_args['filename']
            cmd_buffer.write(ctypes.c_uint16(len(filepath)))
            cmd_buffer.write(bytes(filepath, 'utf-8'))
            cmd_buffer.write(ctypes.c_uint32(cmd_args['line']))
        elif cmd == RDBG_Command.GET_TARGET_STATE:
            pass
        elif cmd == RDBG_Command.ADD_WATCH:
            expr:str = cmd_args['expr']
            cmd_buffer.write(ctypes.c_uint8(1)) 	# watch window 1
            cmd_buffer.write(ctypes.c_uint16(len(expr)))
            cmd_buffer.write(bytes(expr, 'utf-8'))
            cmd_buffer.write(ctypes.c_uint16(0))	
        elif cmd == RDBG_Command.UPDATE_BREAKPOINT_LINE:
            if cmd_args['id'] in self.breakpoints:
                rdbg_id = self.breakpoints[cmd_args['id']]
                cmd_buffer.write(ctypes.c_uint32(rdbg_id))
                cmd_buffer.write(ctypes.c_uint32(cmd_args['line']))
        elif cmd == RDBG_Command.SET_WINDOW_POS:
            cmd_buffer.write(ctypes.c_int32(cmd_args['x']))
            cmd_buffer.write(ctypes.c_int32(cmd_args['y']))
            cmd_buffer.write(ctypes.c_int32(cmd_args['w'])) 
            cmd_buffer.write(ctypes.c_int32(cmd_args['h'])) 
        elif cmd == RDBG_Command.GET_WINDOW_POS:
            pass
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
        result_code : RDBG_CommandResult = int.from_bytes(out_buffer.read(2), 'little')
        if result_code == 1:
            if cmd == RDBG_Command.ADD_BREAKPOINT_AT_FILENAME_LINE:
                bp_id = int.from_bytes(out_buffer.read(4), 'little')
                if bp_id not in self.breakpoints_rdbg:
                    self.breakpoints[cmd_args['id']] = bp_id
                    self.breakpoints_rdbg[bp_id] = (cmd_args['id'], cmd_args['filename'], cmd_args['line'])
                else:
                    print('RDBG: Breakpoint (%i) %s@%i skipped, because it will not get triggered' % (cmd_args['id'], cmd_args['filename'], cmd_args['line']))
                    self.ignore_next_remove_breakpoint = True
                    Editor.RemoveBreakpointById(cmd_args['id'])
                return bp_id
            elif cmd == RDBG_Command.GET_TARGET_STATE:
                return int.from_bytes(out_buffer.read(2), 'little')
            elif cmd == RDBG_Command.ADD_WATCH:
                return int.from_bytes(out_buffer.read(4), 'little')
            elif cmd == RDBG_Command.GET_WINDOW_POS:
                x = int.from_bytes(out_buffer.read(4), 'little')
                y = int.from_bytes(out_buffer.read(4), 'little')
                w = int.from_bytes(out_buffer.read(4), 'little')
                h = int.from_bytes(out_buffer.read(4), 'little')
                return (x, y, w, h)
        else:
            print('RDBG: ' + str(cmd) + ' failed')
            return 0

        return 1

    def snap_remedybg_window(self):
        snap_mode = _rdbg_options.snap_window
        if _rdbg_session is not None and snap_mode and snap_mode != '':
            rect = win32gui.GetWindowRect(_rdbg_options.hwnd)
            rx, ry, rw, rh = _rdbg_session.send_command(RDBG_Command.GET_WINDOW_POS)

            if snap_mode == 'top-right':
                _rdbg_session.send_command(RDBG_Command.SET_WINDOW_POS, x=rect[2], y=rect[1], w=rw, h=rh)
            elif snap_mode == 'bottom-right':
                _rdbg_session.send_command(RDBG_Command.SET_WINDOW_POS, x=rect[2], y=rect[3]-rh, w=rw, h=rh)
            elif snap_mode == 'top-left':
                _rdbg_session.send_command(RDBG_Command.SET_WINDOW_POS, x=rect[0]-rw, y=rect[1], w=rw, h=rh)
            elif snap_mode == 'bottom-left':
                _rdbg_session.send_command(RDBG_Command.SET_WINDOW_POS, x=rect[0]-rw, y=rect[3]-rh, w=rw, h=rh)
                

    def open(self)->bool:
        try:
            debug_cmd = Editor.GetDebugCommand().strip()
            debug_args = Editor.GetDebugCommandArgs().strip()
            debug_cwd = Editor.GetDebugCommandCwd().strip()

            if debug_cmd == '':
                Editor.ShowMessageBox(RDBG_TITLE, 'Debug command is empty. Perhaps active project is not set in workspace tree?')
                return False

            work_dir = Editor.GetSetting("RemedyBG.WorkDir")
            # if not working dir explicitly declared in the settings just use the workspace dir
            if work_dir == '':
                work_dir = os.path.dirname(os.path.abspath(Editor.GetWorkspaceFilename()))
                work_dir = os.path.join(work_dir, debug_cwd)

            if work_dir != '' and not os.path.isdir(work_dir):
                Editor.ShowMessageBox(RDBG_TITLE, 'Debugger working directory is invalid: ' + work_dir)

            args = _rdbg_options.executable + ' --servername ' + self.name + ' "' + debug_cmd + '"' + (' ' if debug_args!='' else '') + debug_args
            self.process = subprocess.Popen(args, cwd=work_dir)
            time.sleep(0.1)

            assert self.cmd_pipe == None
            name = RDBG_PREFIX + self.name
            
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
                    Editor.ShowMessageBox(RDBG_TITLE, 'Pipe error:' +  str(e))
                    return False
                pipe_success = True
                break

            if not pipe_success:
                Editor.ShowMessageBox(RDBG_TITLE, 'Named pipe could not be opened to remedybg. Make sure remedybg version is above 0.3.8')
                return False
            
            win32pipe.SetNamedPipeHandleState(self.cmd_pipe, win32pipe.PIPE_READMODE_MESSAGE, None, None)

            assert self.event_pipe == None
            name = name + '-events'
            self.event_pipe = win32file.CreateFile(name, win32file.GENERIC_READ|256, \
                0, None, win32file.OPEN_EXISTING, 0, None)
            win32pipe.SetNamedPipeHandleState(self.event_pipe, win32pipe.PIPE_READMODE_MESSAGE, None, None)

            print("RDBG: Connection established")

            for bp in Editor.GetBreakpoints():
                self.send_command(RDBG_Command.ADD_BREAKPOINT_AT_FILENAME_LINE, id=bp[0], filename=bp[1], line=bp[2])

        except FileNotFoundError as not_found:
            Editor.ShowMessageBox(RDBG_TITLE, str(not_found) + ': ' + _rdbg_options.executable)
            return False
        except pywintypes.error as connection_error:
            Editor.ShowMessageBox(RDBG_TITLE, str(connection_error))
            return False
        except OSError as os_error:
            Editor.ShowMessageBox(RDBG_TITLE, str(os_error))
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
            state:RDBG_TargetState = self.send_command(RDBG_Command.GET_TARGET_STATE)
            if state == RDBG_TargetState.NONE:
                self.send_command(RDBG_Command.START_DEBUGGING)
            elif state == RDBG_TargetState.SUSPENDED:
                self.send_command(RDBG_Command.CONTINUE_EXECUTION)
            elif state == RDBG_TargetState.EXECUTING:
                pass
            if _rdbg_options.output_debug_text:
                Editor.ShowOutput()

    def stop(self):
        if self.cmd_pipe is not None:
            state:RDBG_TargetState = _rdbg_session.send_command(RDBG_Command.GET_TARGET_STATE)
            if state == RDBG_TargetState.SUSPENDED or state == RDBG_TargetState.EXECUTING:
                _rdbg_session.send_command(RDBG_Command.STOP_DEBUGGING)

    def next_breakpoint_ignored(self):
        if self.ignore_next_remove_breakpoint:
            self.ignore_next_remove_breakpoint = False
            return True
        return False

    def update_active_project(self)->bool:
        active_project:str = Editor.GetActiveProject() + ';' + Editor.GetBuildConfig() + ';' + Editor.GetBuildPlatform()
        if active_project != self.active_project:
            self.active_project = active_project
            return True
        return False

    def update(self)->bool:
        global _rdbg_options
        global _rdbg_options_override

        tm:float = time.time()

        # do regular checks every one second
        if tm - self.last_poll_time >= 1.0:
            self.last_poll_time = tm

            if self.process is None:
                return False

            if self.process is not None and self.process.poll() is not None:
                print('RDBG: RemedyBG quit with code: %i' % (self.process.poll()))
                self.process = None
                self.close(stop=False)
                return False

            if self.update_active_project():
                if _rdbg_options.keep_session:
                    self.process = None
                else:
                    print('RDBG: Active project changed. Closing session...')
                self.close(stop=False)
                return False

        if self.process is not None and self.event_pipe is not None:
            try:
                buffer, nbytes, result = win32pipe.PeekNamedPipe(self.event_pipe, 0)
                if nbytes:
                    hr, data = win32file.ReadFile(self.event_pipe, nbytes, None)
                    event_buffer = io.BytesIO(data)
                    event_type = int.from_bytes(event_buffer.read(2), 'little')
                    if event_type == RDBG_EventType.OUTPUT_DEBUG_STRING and _rdbg_options.output_debug_text:
                        text = event_buffer.read(int.from_bytes(event_buffer.read(2), 'little')).decode('utf-8')
                        print('RDBG:', text.strip())
                    elif event_type == RDBG_EventType.KIND_BREAKPOINT_RESOLVED:
                        bp_id = int.from_bytes(event_buffer.read(4), 'little')
                        if bp_id in self.breakpoints_rdbg:
                            filename, new_line = self.get_breakpoint(bp_id)
                            id_10x, filename_old, line = self.breakpoints_rdbg[bp_id]

                            if filename != '':
                                self.breakpoints_rdbg[bp_id] = (id_10x, filename_old, new_line)
                                Editor.UpdateBreakpoint(id_10x, new_line)
                            else:
                                self.breakpoints_rdbg.pop(bp_id)
                                self.breakpoints.pop(id_10x)
                                self.ignore_next_remove_breakpoint = True
                                Editor.RemoveBreakpointById(id_10x)
                    elif event_type == RDBG_EventType.BREAKPOINT_ADDED:
                        bp_id = int.from_bytes(event_buffer.read(4), 'little')
                        if bp_id not in self.breakpoints_rdbg:
                            filename, line = self.get_breakpoint(bp_id)
                            if filename != '':
                                filename = filename.replace('\\', '/')
                                id_10x:int = Editor.AddBreakpoint(filename, line)
                                self.breakpoints_rdbg[bp_id] = (id_10x, filename, line)
                                self.breakpoints[id_10x] = bp_id
                    elif event_type == RDBG_EventType.BREAKPOINT_REMOVED:
                        bp_id = int.from_bytes(event_buffer.read(4), 'little')
                        if bp_id in self.breakpoints_rdbg:
                            id_10x, filename, line = self.breakpoints_rdbg[bp_id]
                            if id_10x in self.breakpoints:
                                self.breakpoints.pop(id_10x)
                            self.breakpoints_rdbg.pop(bp_id)
                            self.ignore_next_remove_breakpoint = True
                            Editor.RemoveBreakpointById(id_10x)
                    elif event_type == RDBG_EventType.SOURCE_LOCATION_CHANGED:
                        filename:str = event_buffer.read(int.from_bytes(event_buffer.read(2), 'little')).decode('utf-8')
                        line:int = int.from_bytes(event_buffer.read(4), 'little')
                        reason:RDBG_SourceLocChangedReason = int.from_bytes(event_buffer.read(4), 'little')
                        if reason != RDBG_SourceLocChangedReason.DRIVER:
                            filename = filename.replace('\\', '/')
                            Editor.OpenFile(filename)
                            Editor.SetCursorPos((0, line-1)) # convert to index-based
                            if reason == RDBG_SourceLocChangedReason.BREAKPOINT_HIT or \
                               reason == RDBG_SourceLocChangedReason.EXCEPTION_HIT or \
                               reason == RDBG_SourceLocChangedReason.STEP_OVER or \
                               reason == RDBG_SourceLocChangedReason.STEP_IN or  \
                               reason == RDBG_SourceLocChangedReason.NON_USER_BREAKPOINT or \
                               reason == RDBG_SourceLocChangedReason.DEBUG_BREAK:
                               self.target_state = RDBG_TargetState.SUSPENDED
                    elif event_type == RDBG_EventType.BREAKPOINT_MODIFIED:
                        # used for enabling/disabling breakpoints, we don't have that now
                        pass
                    elif event_type == RDBG_EventType.EXIT_PROCESS:
                        exit_code:int = int.from_bytes(event_buffer.read(4), 'little')
                        print('RDBG: Debugging terminted with exit code:', exit_code)
                        self.target_state = RDBG_TargetState.NONE

                        if not _rdbg_options.stop_debug_on_build:
                            _rdbg_options_override = True
                            Editor.RemoveSettingOverride('BuildBeforeStartDebugging')
                            _rdbg_options_override = False

                        if _rdbg_options.stop_debug_command and _rdbg_options.stop_debug_command != '':
                            print('RDBG: Execute:', _rdbg_options.stop_debug_command)
                            Editor.ExecuteCommand(_rdbg_options.stop_debug_command)
                    elif event_type == RDBG_EventType.TARGET_STARTED:
                        print('RDBG: Debugging started')
                        self.target_state = RDBG_TargetState.EXECUTING

                        if not _rdbg_options.stop_debug_on_build:
                            _rdbg_options_override = True
                            Editor.OverrideSetting('BuildBeforeStartDebugging', 'false')
                            _rdbg_options_override = False

                        if _rdbg_options.start_debug_command and _rdbg_options.start_debug_command != '':
                            print('RDBG: Execute:', _rdbg_options.start_debug_command)
                            Editor.ExecuteCommand(_rdbg_options.start_debug_command)
                        self.snap_remedybg_window()
                    elif event_type == RDBG_EventType.TARGET_CONTINUED:
                        self.target_state = RDBG_TargetState.EXECUTING

            except win32api.error as pipe_error:
                print('RDBG:', pipe_error)
                self.close(stop=False)
                return False
            
        return True

def RDBG_StartDebugging():
    global _rdbg_session
    global _rdbg_options

    if _rdbg_session is not None:
        if _rdbg_session.update_active_project():
            if _rdbg_options.keep_session:
                _rdbg_session.process = None
            else:
                print('RDBG: Project config/platform changed. Restarting RemedyBG ...')
                
            _rdbg_session.close(stop=False)
            _rdbg_session = None
            RDBG_StartDebugging()

        # poll for debugger state. if we are in the middle of debugging, then continue, otherwise run/build-run
        state:RDBG_TargetState = _rdbg_session.send_command(RDBG_Command.GET_TARGET_STATE)
        if state == RDBG_TargetState.NONE:
            if _rdbg_options.build_before_debug:
                _rdbg_session.run_after_build = True    # Checking this in BuildFinished callback
            else:
                _rdbg_session.run()
        elif state == RDBG_TargetState.SUSPENDED:
            _rdbg_session.run()
    else:
        if Editor.GetWorkspaceFilename() == '':
            Editor.ShowMessageBox(RDBG_TITLE, 'No Workspace is opened for debugging')
            return

        print('RDBG: Workspace: ' + Editor.GetWorkspaceFilename())

        _rdbg_session = RDBG_Session()
        if _rdbg_session.open():
            if _rdbg_options.build_before_debug:
                _rdbg_session.run_after_build = True    # Checking this in BuildFinished callback
            else:
                _rdbg_session.run()			
        else:
            _rdbg_session = None
    
def RDBG_StopDebugging():
    global _rdbg_session
    if _rdbg_session is not None:
        _rdbg_session.stop()        

def RDBG_RestartDebugging():
    global _rdbg_session
    if _rdbg_session is not None:
        _rdbg_session.send_command(RDBG_Command.RESTART_DEBUGGING)		

def RDBG_RunToCursor():
    global _rdbg_session
    if _rdbg_session is not None:
        filename:str = Editor.GetCurrentFilename()
        if filename != '':
            _rdbg_session.send_command(RDBG_Command.RUN_TO_FILE_AT_LINE, filename=filename, line=Editor.GetCursorPos()[1])

def RDBG_GoToCursor():
    global _rdbg_session
    if _rdbg_session is not None:
        filename:str = Editor.GetCurrentFilename()
        if filename != '':
            _rdbg_session.send_command(RDBG_Command.GOTO_FILE_AT_LINE, filename=filename, line=Editor.GetCursorPos()[1])

def RDBG_StepInto():
    global _rdbg_session
    if _rdbg_session is not None:
        _rdbg_session.send_command(RDBG_Command.STEP_INTO_BY_LINE)

def RDBG_StepOver():
    global _rdbg_session
    if _rdbg_session is not None:
        _rdbg_session.send_command(RDBG_Command.STEP_OVER_BY_LINE)

def RDBG_StepOut():
    global _rdbg_session
    if _rdbg_session is not None:
        _rdbg_session.send_command(RDBG_Command.STEP_OUT)

def RDBG_AddSelectionToWatch():
    global _rdbg_session
    if _rdbg_session is not None:
        selection:str = Editor.GetSelection()
        if selection != '':
            _rdbg_session.send_command(RDBG_Command.ADD_WATCH, expr=selection)
        
def _RDBG_WorkspaceOpened():
    global _rdbg_session
    if _rdbg_session is not None:
        print('RDBG: Closing previous debug session "%s".' % (_rdbg_session.name))
        _rdbg_session.close()
        _rdbg_session = None

def _RDBG_AddBreakpoint(id, filename, line):
    global _rdbg_session
    if _rdbg_session is not None:
        _rdbg_session.send_command(RDBG_Command.ADD_BREAKPOINT_AT_FILENAME_LINE, id=id, filename=filename, line=line)
        _rdbg_session.send_command(RDBG_Command.GOTO_FILE_AT_LINE, filename=filename, line=line)

def _RDBG_RemoveBreakpoint(id, filename, line):
    global _rdbg_session
    if _rdbg_session is not None and not _rdbg_session.next_breakpoint_ignored():
        _rdbg_session.send_command(RDBG_Command.DELETE_BREAKPOINT, id=id, filename=filename, line=line)

def _RDBG_UpdateBreakpoint(id, filename, line):
    global _rdbg_session
    if _rdbg_session is not None:
        _rdbg_session.send_command(RDBG_Command.UPDATE_BREAKPOINT_LINE, id=id, line=line)

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
    if not _rdbg_options_override:
        _rdbg_options = RDBG_Options()

def _RDBG_StartDebugging()->bool:
    if _rdbg_options.hook_calls:
        RDBG_StartDebugging()
        return True
    else:
        return False

def _RDBG_StopDebugging()->bool:
    if _rdbg_options.hook_calls:
        RDBG_StopDebugging()
        return True
    else:
        return False

def _RDBG_RestartDebugging()->bool:
    if _rdbg_options.hook_calls:
        RDBG_RestartDebugging()
        return True
    else:
        return False

def _RDBG_ProjectBuild(filename:str)->bool:
    if _rdbg_options.stop_debug_on_build and _rdbg_session is not None:
        _rdbg_session.stop()        
    return False

_rdbg_session:RDBG_Session = None
_rdbg_options:RDBG_Options = RDBG_Options()
_rdbg_options_override:bool = False

Editor.AddBreakpointAddedFunction(_RDBG_AddBreakpoint)
Editor.AddBreakpointRemovedFunction(_RDBG_RemoveBreakpoint)
Editor.AddBreakpointUpdatedFunction(_RDBG_UpdateBreakpoint)

Editor.AddOnWorkspaceOpenedFunction(_RDBG_WorkspaceOpened)
Editor.AddBuildFinishedFunction(_RDBG_BuildFinished)
Editor.AddUpdateFunction(_RDBG_Update)
Editor.AddOnSettingsChangedFunction(_RDBG_SettingsChanged)

Editor.AddStartDebuggingFunction(_RDBG_StartDebugging)
Editor.AddStopDebuggingFunction(_RDBG_StopDebugging)
Editor.AddRestartDebuggingFunction(_RDBG_RestartDebugging)

Editor.AddProjectBuildFunction(_RDBG_ProjectBuild)
