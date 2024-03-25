'''
RemedyBG debugger integration for 10x (10xeditor.com) 
RemedyBG: https://remedybg.handmade.network/ (should be above 0.3.8)
Version: 0.11.10
Original Script author: septag@discord / septag@pm.me

To get started go to Settings.10x_settings, and enable the hook, by adding this line:
    RemedyBG.Hook: true
This will make RemedyBG hook into the editor and act as the default debugger
	
If RemedyBG.exe is not in your PATH env var you must also set RemedyBG.Path (see below)
You can add other options listed below in 'RDBG_Options' as individual lines in the settings file.
Other commands are listed below in 'Commands' and `Extras` 

RDBG_Options: 
    - RemedyBG.Hook: (default=False) Hook RemedyBg into default Start/Stop/Restart debugging commands instead of the msvc debugger integration
    - RemedyBG.Path: Path to remedybg.exe. If not set, the script will assume remedybg.exe is in PATH or current dir
    - RemedyBG.OutputDebugText: (default=True) receives and output debug text to 10x output
    - RemedyBG.WorkDir: Path that remedy will use as a working directory
    - RemedyBG.KeepSessionOnActiveChange: (default=False) when active project or config is changed, it leaves the previously opened RemedyBG session
                                           This is useful when you want to debug multiple binaries within a project like client/server apps
    - RemedyBG.StartProcessExtraCommand: Extra 10x command that will be executed after process is started in RemedyBG. Several commands can be separated by semicolon.
    - RemedyBG.StopProcessExtraCommand: Extra 10x command that will be executed after process is stopped in RemedyBG. Several commands can be separated by semicolon.
    - RemedyBG.BringToForegroundOnSuspended: (default=True) Bring debugger to front when debugging session is paused

Commands:
    - RDBG_StartDebugging: Same behavior as default StartDebugging. Launches remedybg if not opened before and runs the executable in the debugger. 
                           If "BuildBeforeStartDebugging" option is set, it builds it before running the session
                           If debugger is already running, it does nothing
                           If debugger is in suspend/pause state, it continues the debugger
    - RDBG_StopDebugging: Stops if debugger is running
    - RDBG_RestartDebugging: Restart debugging 
    - RDBG_OpenDebugger: Only opens debugger but doesn't run the session

Extras:
    - RDBG_RunToCursor: Run up to selected cursor. User should already started a debugging session before calling this
    - RDBG_GoToCursor: Goes to selected cursor in remedybg and bring it to foreground
    - RDBG_AddSelectionToWatch: Adds selected text to remedybg's watch window #1
    - RDBG_StepInto: Steps into line when debugging, also updates the cursor position in 10x according to position in remedybg
    - RDBG_StepOver: Steps over the line when debugging, also updates the cursor position in 10x according to position in remedybg
    - RDBG_StepOut: Steps out of the current line when debugging, also updates the cursor position in 10x according to position in remedybg
    - RDBG_UnbindSession: Unbinds any session files for the current Config/Platform build configuration. 
                          This is useful when you have already binded a session file to configuration before but want to clear it
    - RDBG_Reset: Saves any opened sessions in RemedyBG, quits the debugger and closes the connection.

RemedyBG sessions:
    As of version 0.11.0, RemedyBG session support has been added to the plugin.
    If you save RemedyBG session while connected to the project. It will store the reference to the session file 
    and it will load that next time instead of starting a new session

History:
  0.11.11
    - Minor bug fixed when opening a workspace for json sessions for the first time and start debugging

  0.11.10
    - Fix for the stepper arrow. Now it shows where your program is actually at. Won't show the arrow for callstack walks and other things

  0.11.9
    - Now StepIn/StepOut starts debugging and steps into the program with the new RemedyBG update (0.3.9.8)
    - Minor improvement to OpenDebugger command
    - Debugger suspend event now works when we pause the program in RemedyBG (0.3.9.8)
    - RestartDebugging starts the session if not it's started before

  0.11.8
    - Fixed bugs and improved `KeepSessionOnActiveChange` experience. Now when user switches from one workspace/config to another, RemedyBG sessions are properly retained and reloaded
    - Fixed a bug when we do not receive events right after RemedyBG session opens
    - Fixed a bug with 10x debug state not updated properly when RemedyBG is closed by user
    - `StartProcessExtraCommand` and `StopProcessExtraCommand` now receives several commands, semicolon separated

  0.11.7
    - Minor cleanups

  0.11.6
    - Removed start_after_build workaround. Since 10x is now getting debugger state and starting the debugger correctly after build itself
    - Getting better in sync with 10x by calling OnDebuggerStarted/OnDebuggerStopped/OnDebuggerPaused/OnDebuggerResumed functions

  0.11.5
    - Now BringToForegroundWindow is only called when we are not stepping
    - Fixed the arrow icon not disappearing when executable is stopped
    - Fixed StepOut events not acting accordingly
    
  0.11.4
    - Added StepIn/StepOut/StepOver callbacks to hook them with new 10x commands

  0.11.3
    - Adding step line arrow in debug mode with the new 10x API
    - Using new SetForegroundWindow() API instead of enumerating windows and calling win32 api
    - Change 10x status bar color based on debugging state
    - Add .lower() to boolean settings for less strict checking

  0.11.2
    - Fixed RDBG_Reset command
    - new 'RDBG_UnbindSession' command to unbind the session file from current configuration

  0.11.1
    - Syncing breakpoints from RemedyBG when pre-existing session is used
    - Fixes and improvements for 'BringToForegroundOnSuspended'. Now both 10x and RemedyBG windows will come into foreground on suspend when the setting is enabled
    - Fixed OpenDebugger command

  0.11.0
    - Added RDBG_OpenDebugger command 
    - Remove SnapWindow setting
    - Added 'BringToForegroundOnSuspended' setting
    - RemedyBG Sessions support. It will keep track of saved sessions in RemedyBG for each config/project and try to load them instead of a fresh session

  0.10.6
    - RemedyBG.Path can now be both the executable or directory. In case of directory, we will attempt to append 'remedybg.exe' to the end of it

  0.10.5 
    - Fixed STEP_OUT command
    
  0.10.4
    - Fix a recursive error bug, when trying to close the connection on errors in send_command

  0.10.3:
    - Gracefully quitting RemedyBG 

  0.10.2:
    - moved the initialise onto the main thread

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
import win32file, win32pipe, pywintypes, win32api, ctypes.wintypes
import io, os, ctypes, time, typing, subprocess
import json

from N10X import Editor

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
RDBG_HANDLE = typing.Any
RDBG_PREFIX:str = '\\\\.\\pipe\\'
RDBG_TITLE:str = 'RemedyBG'
RDBG_PROCESS_POLL_INTERVAL:float = 1.0

class RDBG_Options():
    def __init__(self):
        global gOptionsOverride

        self.executable = Editor.GetSetting("RemedyBG.Path").strip()
        if not self.executable:
            self.executable = 'remedybg.exe'
        if os.path.isdir(self.executable):
            self.executable = os.path.join(self.executable, 'remedybg.exe')

        self.output_debug_text = True
        output_debug_text = Editor.GetSetting("RemedyBG.OutputDebugText") 
        if output_debug_text and output_debug_text == 'false':
            self.output_debug_text = False
        else:
            self.output_debug_text = True

        hook_calls = Editor.GetSetting("RemedyBG.Hook")
        if hook_calls and hook_calls.lower() == 'true':
            self.hook_calls = True
        else:
            self.hook_calls = False

        gOptionsOverride = True
        if self.hook_calls:
            Editor.OverrideSetting('VisualStudioSync', 'false')
        else:
            Editor.RemoveSettingOverride('VisualStudioSync')
        gOptionsOverride = False

        keep_session = Editor.GetSetting("RemedyBG.KeepSessionOnActiveChange")
        if keep_session and keep_session.lower() == 'true':
            self.keep_session = True
        else:
            self.keep_session = False

        if  Editor.GetSetting("StopDebuggingOnBuild") and Editor.GetSetting("StopDebuggingOnBuild").lower() == 'true':
            self.stop_debug_on_build = True
        else:
            self.stop_debug_on_build = False

        self.start_debug_command:str = Editor.GetSetting("RemedyBG.StartProcessExtraCommand").strip()
        self.stop_debug_command:str = Editor.GetSetting("RemedyBG.StopProcessExtraCommand").strip()

        bring_to_foreground_on_suspend = Editor.GetSetting("RemedyBG.BringToForegroundOnSuspended")
        if  bring_to_foreground_on_suspend and bring_to_foreground_on_suspend.lower() == 'false':
            self.bring_to_foreground_on_suspend:bool = False
        else:
            self.bring_to_foreground_on_suspend:bool = True

class RDBG_TargetState(IntEnum):
    NONE = 1
    SUSPENDED = 2
    EXECUTING = 3

class RDBG_TargetBehavior(IntEnum):
    TARGET_STOP_DEBUGGING = 1
    TARGET_ABORT_COMMAND = 2

class RDBG_ModifiedSessionBehavior(IntEnum):
    IF_SESSION_IS_MODIFIED_SAVE_AND_CONTINUE = 1
    IF_SESSION_IS_MODIFIED_CONTINUE_WITHOUT_SAVING = 2
    IF_SESSION_IS_MODIFIED_ABORT_COMMAND = 3

class RDBG_Command(IntEnum):
    BRING_DEBUGGER_TO_FOREGROUND = 50
    SET_WINDOW_POS = 51
    GET_WINDOW_POS = 52
    SET_BRING_TO_FOREGROUND_ON_SUSPENDED = 53
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
    STEP_OUT = 311
    CONTINUE_EXECUTION = 312
    RUN_TO_FILE_AT_LINE = 313
    GET_BREAKPOINTS = 600
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
        self.last_poll_time:float = 0
        self.ignore_next_remove_breakpoint:bool = False
        self.breakpoints = {}    # key=10x breakpoint id
        self.breakpoints_rdbg = {}  # key=remedybg breakpoint id
        self.target_state:RDBG_TargetState = RDBG_TargetState.NONE
        self.active_project:str = ""    # Format: project_path;config;platform
        self.session_refs = []  # contains remedybg session filepath for each project config (see active_project formatting)
        self.rdbg_current_session_filepath = None
        self.first_start = True

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
            self.close()
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
    
    def sync_breakpoints(self, two_way:bool):
        # send all breakpoints from 10x to RemedyBG
        for bp in Editor.GetBreakpoints():
            self.send_command(RDBG_Command.ADD_BREAKPOINT_AT_FILENAME_LINE, id=bp[0], filename=bp[1], line=bp[2])

        if two_way:
            rdbg_bps = self.send_command(RDBG_Command.GET_BREAKPOINTS)
            if not rdbg_bps or rdbg_bps == 0:
                return
            
            for bp in rdbg_bps:
                bp_id = bp['id']
                if bp_id not in self.breakpoints_rdbg:
                    id_10x:int = Editor.AddBreakpoint(bp['filename'], bp['line'])
                    self.breakpoints_rdbg[bp_id] = (id_10x, bp['filename'], bp['line'])
                    self.breakpoints[id_10x] = bp_id

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
        elif cmd == RDBG_Command.STEP_OUT:
            pass
        elif cmd == RDBG_Command.STOP_DEBUGGING:
            pass
        elif cmd == RDBG_Command.RESTART_DEBUGGING:
            pass
        elif cmd == RDBG_Command.CONTINUE_EXECUTION:
            pass
        elif cmd == RDBG_Command.BRING_DEBUGGER_TO_FOREGROUND:
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
        elif cmd == RDBG_Command.COMMAND_EXIT_DEBUGGER:
            cmd_buffer.write(ctypes.c_uint8(RDBG_TargetBehavior.TARGET_STOP_DEBUGGING))
            cmd_buffer.write(ctypes.c_uint8(RDBG_ModifiedSessionBehavior.IF_SESSION_IS_MODIFIED_CONTINUE_WITHOUT_SAVING))
        elif cmd == RDBG_Command.SET_BRING_TO_FOREGROUND_ON_SUSPENDED:
            cmd_buffer.write(ctypes.c_uint8(cmd_args['enabled']))
        elif cmd == RDBG_Command.GET_IS_SESSION_MODIFIED:
            pass
        elif cmd == RDBG_Command.GET_SESSION_FILENAME:
            pass
        elif cmd == RDBG_Command.SAVE_SESSION:
            pass
        elif cmd == RDBG_Command.GET_BREAKPOINTS:
            pass
        else:
            assert 0
            return 0		# not implemented

        try:
            out_data = win32pipe.TransactNamedPipe(self.cmd_pipe, cmd_buffer.getvalue(), 8192, None)
        except pywintypes.error as pipe_error:
            print('RDBG', pipe_error)
            self.close(ignore_send_command=True)
            return 0

        # Process result. Always get 2-byte result code
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
            elif cmd == RDBG_Command.GET_IS_SESSION_MODIFIED:
                return bool.from_bytes(out_buffer.read(1), 'little')
            elif cmd == RDBG_Command.GET_SESSION_FILENAME:
                strlen = int.from_bytes(out_buffer.read(2), 'little')
                return out_buffer.read(strlen).decode('utf-8')
            elif cmd == RDBG_Command.GET_BREAKPOINTS:
                num_bps = int.from_bytes(out_buffer.read(2), 'little')
                bps = []
                for i in range(num_bps):
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
                            bps.append({'id': uid, 'filename': filename, 'line': line_num})

                        case RDBG_BreakpointKind.ADDRESS:
                            address:int = int.from_bytes(out_buffer.read(8), 'little')

                        case RDBG_BreakpointKind.PROCESSOR:
                            address_expression:str = out_buffer.read(int.from_bytes(out_buffer.read(2), 'little')).decode('utf-8')
                            num_bytes:int = int.from_bytes(out_buffer.read(1), 'little')
                            access_kind:int = int.from_bytes(out_buffer.read(1), 'little')                    
                return bps  
        else:
            # TODO: we have to ignore this error for now. because when RemedyBG is not currently focused, we will get an error
            if cmd == RDBG_Command.BRING_DEBUGGER_TO_FOREGROUND:
                return 1
            
            print('RDBG: ' + str(cmd) + ' failed')
            if result_code == RDBG_CommandResult.FAILED_OPENING_FILE:
                print('RDBG: Error opening file')
            return 0

        return 1
    
    def get_work_dir(self)->str:
        debug_cwd = Editor.GetDebugCommandCwd().strip()
        work_dir = Editor.GetSetting("RemedyBG.WorkDir")
        if not work_dir:
            work_dir = os.path.dirname(os.path.abspath(Editor.GetWorkspaceFilename()))
            if debug_cwd:
                # if debug_cwd not a valid directory. cwd might be relative path. so try appending debug_cwd to the end of workspace_dir and use that instead 
                # otherwise it's an absolute path, so just use debug_cwd instead
                if not os.path.isdir(debug_cwd):
                    potential_work_dir = os.path.join(work_dir, debug_cwd)
                    if os.path.isdir(potential_work_dir):
                        work_dir = potential_work_dir
                else:
                    work_dir = debug_cwd
                    
        return os.path.abspath(work_dir)

    def save_session_ref(self):
        workspace_path:str = Editor.GetAppDataWorkspacePath()
        if os.path.isdir(workspace_path):
            session_list_file = os.path.join(workspace_path, 'rdbg_sessions.json')
            with open(session_list_file, 'w') as f:
                json.dump(self.session_refs, f, indent = 2)

    def load_session_ref(self)->str:
        try:
            workspace_path:str = Editor.GetAppDataWorkspacePath()
            session_list_file = os.path.join(workspace_path, 'rdbg_sessions.json')
            if os.path.isfile(session_list_file):
                with open(session_list_file, 'r') as f:
                    self.session_refs = json.load(f)
        except:
            pass

    def check_session_for_config(self)->str:
        if not self.process or not self.cmd_pipe:
            return None
        
        session_filepath = self.send_command(RDBG_Command.GET_SESSION_FILENAME)
        if session_filepath == 0:
            return None
        
        projname:str = self.active_project
        session_exists:bool = False
        for session_ref in self.session_refs:
            if session_ref['name'] == projname:
                session_exists = True
                if session_ref['session_filepath'] != session_filepath:
                    session_ref['session_filepath'] = session_filepath
                    self.save_session_ref()
                return session_ref['session_filepath']
        
        if not session_exists:
            self.session_refs.append({'name': projname, 'session_filepath': session_filepath })
            self.save_session_ref()

        return None

    def open_existing(self)->bool:
        # first check if we have already spawned the process and it's still alive (poll)
        global gProcessCache
        if self.name not in gProcessCache:
            return False
        self.process = gProcessCache[self.name]
        if self.process.poll() is not None:
            del gProcessCache[self.name]
            return False

        try:
            assert self.cmd_pipe == None
            name = RDBG_PREFIX + self.name
            self.cmd_pipe = win32file.CreateFile(name, win32file.GENERIC_READ|win32file.GENERIC_WRITE, 0, None, win32file.OPEN_EXISTING, 0, None)
            win32pipe.SetNamedPipeHandleState(self.cmd_pipe, win32pipe.PIPE_READMODE_MESSAGE, None, None)
            
            assert self.event_pipe == None
            name = name + '-events'
            self.event_pipe = win32file.CreateFile(name, win32file.GENERIC_READ|256, 0, None, win32file.OPEN_EXISTING, 0, None)
            win32pipe.SetNamedPipeHandleState(self.event_pipe, win32pipe.PIPE_READMODE_MESSAGE, None, None)

            print("RDBG: Connection re-established")

            self.sync_breakpoints(two_way=False)
            return True
        except:
            if self.cmd_pipe:
                win32file.CloseHandle(self.cmd_pipe)
                self.cmd_pipe = None

            if self.event_pipe is not None:
                win32file.CloseHandle(self.event_pipe)
                self.event_pipe = None            
            return False

    def open(self)->bool:
        try:
            self.load_session_ref()
            self.rdbg_current_session_filepath = None
            session_filepath:str = None
            for session_ref in self.session_refs:
                if session_ref['name'] == self.active_project:
                    session_filepath = session_ref['session_filepath']
                    if not os.path.isfile(session_filepath):
                        session_ref['session_filepath'] = ''
                        session_filepath = None
                        self.save_session_ref()
                    break

            if session_filepath and os.path.isfile(session_filepath):
                args = gOptions.executable + ' --servername ' + self.name + ' "' + session_filepath + '"'
                work_dir = self.get_work_dir()
            else:
                debug_cmd = Editor.GetDebugCommand().strip()
                debug_args = Editor.GetDebugCommandArgs().strip()

                if debug_cmd == '':
                    Editor.ShowMessageBox(RDBG_TITLE, 'Debug command is empty. Perhaps active project is not set in workspace tree?')
                    return False

                work_dir = self.get_work_dir()
                args = gOptions.executable + ' --servername ' + self.name + ' "' + Editor.GetWorkspaceExePath() + '"' + (' ' if debug_args!='' else '') + debug_args

            if work_dir != '' and not os.path.isdir(work_dir):
                Editor.ShowMessageBox(RDBG_TITLE, 'Debugger working directory is invalid: ' + work_dir)

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
                    self.cmd_pipe = win32file.CreateFile(name, win32file.GENERIC_READ|win32file.GENERIC_WRITE, 0, None, win32file.OPEN_EXISTING, 0, None)
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
            self.event_pipe = win32file.CreateFile(name, win32file.GENERIC_READ|256, 0, None, win32file.OPEN_EXISTING, 0, None)
            win32pipe.SetNamedPipeHandleState(self.event_pipe, win32pipe.PIPE_READMODE_MESSAGE, None, None)

            self.save_session_ref()
            if session_filepath:
                print("RDBG: Connection established. Session:", session_filepath)
                self.rdbg_current_session_filepath = session_filepath
                self.sync_breakpoints(two_way=True)
            else:
                print("RDBG: Connection established")
                self.sync_breakpoints(two_way=False)
        except FileNotFoundError as not_found:
            Editor.ShowMessageBox(RDBG_TITLE, str(not_found) + ': ' + gOptions.executable)
            return False
        except pywintypes.error as connection_error:
            Editor.ShowMessageBox(RDBG_TITLE, str(connection_error))
            return False
        except OSError as os_error:
            Editor.ShowMessageBox(RDBG_TITLE, str(os_error))
            return False
        
        return True

    def close(self, ignore_send_command:bool = False):
        if not ignore_send_command and self.process and self.cmd_pipe and self.rdbg_current_session_filepath:
            self.send_command(RDBG_Command.SAVE_SESSION)
            self.rdbg_current_session_filepath = None

        if not ignore_send_command and self.process is not None and self.cmd_pipe:
            self.send_command(RDBG_Command.COMMAND_EXIT_DEBUGGER)

        if self.cmd_pipe:
            win32file.CloseHandle(self.cmd_pipe)
            self.cmd_pipe = None

        if self.event_pipe is not None:
            win32file.CloseHandle(self.event_pipe)
            self.event_pipe = None

        if self.process is not None:
            self.process.wait()
            print('RDBG: RemedyBG quit with code: %i' % (self.process.returncode))
            self.process = None

        Editor.ClearStatusBarColour()
        Editor.ClearDebuggerStepLine()
        Editor.OnDebuggerStopped()

        self.target_state:RDBG_TargetState = RDBG_TargetState.NONE
        self.first_start = True
        print("RDBG: Connection closed")

    def unbind_session_file(self):
        projname:str = self.active_project
        session_exists:bool = False
        for session_ref in self.session_refs:
            if session_ref['name'] == projname:
                print('RDBG: Unbinding session file from the current config:', session_ref['session_filepath'])
                session_ref['session_filepath'] = ''
                self.save_session_ref()
                return True
        return False

    def run(self):
        global gOptions
        if self.cmd_pipe is not None:
            state:RDBG_TargetState = self.send_command(RDBG_Command.GET_TARGET_STATE)
            if state == RDBG_TargetState.NONE:
                r = self.send_command(RDBG_Command.START_DEBUGGING)
                if r and self.first_start:
                    self.first_start = False
                    self.update()

            elif state == RDBG_TargetState.SUSPENDED:
                self.send_command(RDBG_Command.CONTINUE_EXECUTION)
            elif state == RDBG_TargetState.EXECUTING:
                pass
            if gOptions.output_debug_text:
                Editor.ShowOutput()

    def stop(self):
        if self.cmd_pipe is not None:
            state:RDBG_TargetState = gSession.send_command(RDBG_Command.GET_TARGET_STATE)
            if state == RDBG_TargetState.SUSPENDED or state == RDBG_TargetState.EXECUTING:
                gSession.send_command(RDBG_Command.STOP_DEBUGGING)

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
        global gOptions
        global gOptionsOverride
        global gProcessCache

        tm:float = time.time()
 
        # do regular checks (every 3 secs)
        if tm - self.last_poll_time >= 3.0:
            self.last_poll_time = tm

            if self.process is None:
                return False
            
            # Check if the user closed the RemedyBG manually
            if self.process is not None and self.process.poll() is not None:
                print('RDBG: RemedyBG quit with code: %i' % (self.process.poll()))
                self.process = None
                self.close()
                return False
            
            # Check if the active config/project has changed
            if self.update_active_project():
                if gOptions.keep_session:
                    gProcessCache[self.name] = self.process
                    self.process = None
                else:
                    print('RDBG: Active project changed. Closing session...')
                self.close()
                return False
            
            self.check_session_for_config()
            
        # Read events from event_pipe
        if self.process is not None and self.event_pipe is not None:
            try:
                buffer, nbytes, result = win32pipe.PeekNamedPipe(self.event_pipe, 0)
                if nbytes:
                    hr, data = win32file.ReadFile(self.event_pipe, nbytes, None)
                    event_buffer = io.BytesIO(data)
                    event_type = int.from_bytes(event_buffer.read(2), 'little')
                    if event_type == RDBG_EventType.OUTPUT_DEBUG_STRING and gOptions.output_debug_text:
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
                            filename_win = filename
                            filename = filename.replace('\\', '/')
                            if reason == RDBG_SourceLocChangedReason.BREAKPOINT_HIT or \
                               reason == RDBG_SourceLocChangedReason.EXCEPTION_HIT or \
                               reason == RDBG_SourceLocChangedReason.STEP_OVER or \
                               reason == RDBG_SourceLocChangedReason.STEP_IN or  \
                               reason == RDBG_SourceLocChangedReason.STEP_OUT or \
                               reason == RDBG_SourceLocChangedReason.NON_USER_BREAKPOINT or \
                               reason == RDBG_SourceLocChangedReason.DEBUG_BREAK:
                                
                                Editor.SetDebuggerStepLine(filename_win, line-1) # convert to index-based
                                
                                if reason != RDBG_SourceLocChangedReason.EXCEPTION_HIT: Editor.SetStatusBarColour((202, 131, 0))
                                else: Editor.SetStatusBarColour((145, 18, 18))
                                
                                self.target_state = RDBG_TargetState.SUSPENDED
                                Editor.OnDebuggerPaused()

                                # Bring to foreground only if we are not stepping
                                if gOptions.bring_to_foreground_on_suspend and \
                                    (reason != RDBG_SourceLocChangedReason.STEP_OVER and \
                                     reason != RDBG_SourceLocChangedReason.STEP_IN and \
                                     reason != RDBG_SourceLocChangedReason.STEP_OUT):
                                    Editor.SetForegroundWindow()
                                    self.send_command(RDBG_Command.BRING_DEBUGGER_TO_FOREGROUND)
                            elif filename:
                                Editor.OpenFile(filename)
                                Editor.SetCursorPos((0, line-1)) # convert to index-based

                    elif event_type == RDBG_EventType.BREAKPOINT_MODIFIED:
                        # used for enabling/disabling breakpoints, we don't have that now
                        pass
                    elif event_type == RDBG_EventType.EXIT_PROCESS:
                        exit_code:int = int.from_bytes(event_buffer.read(4), 'little')
                        print('RDBG: Debugging terminated with exit code:', exit_code)
                        self.target_state = RDBG_TargetState.NONE
                        Editor.OnDebuggerStopped()
                        Editor.ClearStatusBarColour()
                        Editor.ClearDebuggerStepLine()

                        if gOptions.stop_debug_command and gOptions.stop_debug_command != '':
                            print('RDBG: Execute:', gOptions.stop_debug_command)
                            Editor.ExecuteCommand(gOptions.stop_debug_command)
                            cmds = gOptions.stop_debug_command.split(';')
                            for cmd in cmds:
                                if cmd.strip() != '':
                                    Editor.ExecuteCommand(cmd)

                    elif event_type == RDBG_EventType.TARGET_STARTED:
                        print('RDBG: Debugging started')
                        self.target_state = RDBG_TargetState.EXECUTING
                        Editor.OnDebuggerStarted()
                        Editor.SetStatusBarColour((202, 81, 0))

                        if gOptions.start_debug_command and gOptions.start_debug_command != '':
                            print('RDBG: Execute:', gOptions.start_debug_command)
                            cmds = gOptions.start_debug_command.split(';')
                            for cmd in cmds:
                                if cmd.strip() != '':
                                    Editor.ExecuteCommand(cmd)
                    elif event_type == RDBG_EventType.TARGET_CONTINUED:
                        Editor.ClearDebuggerStepLine()
                        Editor.SetStatusBarColour((202, 81, 0))
                        self.target_state = RDBG_TargetState.EXECUTING
                        Editor.OnDebuggerResumed()

            except win32api.error as pipe_error:
                print('RDBG:', pipe_error)
                self.close()
                return False
            
        return True

def RDBG_StartDebugging(run_after_open = True):
    global gSession
    global gOptions
    global gProcessCache

    if gSession is not None:
        if gSession.update_active_project():
            if gOptions.keep_session:
                gProcessCache[gSession.name] = gSession.process
                gSession.process = None
            else:
                print('RDBG: Project config/platform changed. Restarting RemedyBG ...')
                
            gSession.close()
            gSession = None
            RDBG_StartDebugging()
        
        if run_after_open:
            gSession.run()
    else:
        if Editor.GetWorkspaceFilename() == '':
            Editor.ShowMessageBox(RDBG_TITLE, 'No Workspace is opened for debugging')
            return

        print('RDBG: Workspace: ' + Editor.GetWorkspaceFilename())

        gSession = RDBG_Session()
        if gSession.open_existing() or gSession.open():
            if run_after_open:
                gSession.run()			
        else:
            gSession = None
    
def RDBG_StopDebugging():
    global gSession
    if gSession is not None:
        gSession.stop()        

def RDBG_Reset():
    global gSession
    global gOptionsOverride
    
    Editor.ClearStatusBarColour()
    Editor.ClearDebuggerStepLine()
    gOptionsOverride = False

    if gSession is not None:
        gSession.stop()
        gSession.close()
        gSession = None

def RDBG_RestartDebugging():
    global gSession
    if gSession is not None:
        gSession.send_command(RDBG_Command.RESTART_DEBUGGING)	
    else:
        RDBG_StartDebugging()	

def RDBG_RunToCursor():
    global gSession
    if gSession is not None:
        filename:str = Editor.GetCurrentFilename()
        if filename != '':
            gSession.send_command(RDBG_Command.RUN_TO_FILE_AT_LINE, filename=filename, line=Editor.GetCursorPos()[1])

def RDBG_GoToCursor():
    global gSession
    if gSession is not None:
        filename:str = Editor.GetCurrentFilename()
        if filename != '':
            gSession.send_command(RDBG_Command.GOTO_FILE_AT_LINE, filename=filename, line=Editor.GetCursorPos()[1])

def RDBG_StepInto():
    global gSession
    if gSession is not None:
        gSession.send_command(RDBG_Command.STEP_INTO_BY_LINE)

def RDBG_StepOver():
    global gSession
    if gSession is not None:
        gSession.send_command(RDBG_Command.STEP_OVER_BY_LINE)
    else:
        RDBG_StartDebugging(run_after_open=False)
        RDBG_StepOver()

def RDBG_StepOut():
    global gSession
    if gSession is not None:
        gSession.send_command(RDBG_Command.STEP_OUT)
    else:
        RDBG_StartDebugging(run_after_open=False)
        RDBG_StepOver()


def RDBG_AddSelectionToWatch():
    global gSession
    if gSession is not None:
        selection:str = Editor.GetSelection()
        if selection != '':
            gSession.send_command(RDBG_Command.ADD_WATCH, expr=selection)

def RDBG_OpenDebugger():
    RDBG_StartDebugging(run_after_open=False)

def RDBG_UnbindSession():
    global gSession
    if gSession is not None:
        if gSession.unbind_session_file():
            gSession.close()
            gSession = None
        
def _RDBG_WorkspaceOpened():
    global gSession
    if gSession is not None:
        print('RDBG: Closing previous debug session "%s".' % (gSession.name))
        gSession.close()
        gSession = None

def _RDBG_AddBreakpoint(id, filename, line):
    global gSession
    if gSession is not None:
        gSession.send_command(RDBG_Command.ADD_BREAKPOINT_AT_FILENAME_LINE, id=id, filename=filename, line=line)
        gSession.send_command(RDBG_Command.GOTO_FILE_AT_LINE, filename=filename, line=line)

def _RDBG_RemoveBreakpoint(id, filename, line):
    global gSession
    if gSession is not None and not gSession.next_breakpoint_ignored():
        gSession.send_command(RDBG_Command.DELETE_BREAKPOINT, id=id, filename=filename, line=line)

def _RDBG_UpdateBreakpoint(id, filename, line):
    global gSession
    if gSession is not None:
        gSession.send_command(RDBG_Command.UPDATE_BREAKPOINT_LINE, id=id, line=line)

def _RDBG_Update():
    global gSession

    if gSession is not None:
        if not gSession.update():
            gSession = None

def _RDBG_SettingsChanged():
    global gOptions
    if not gOptionsOverride:
        gOptions = RDBG_Options()

def _RDBG_StartDebugging()->bool:
    if gOptions.hook_calls:
        RDBG_StartDebugging()
        return True
    else:
        return False

def _RDBG_StopDebugging()->bool:
    if gOptions.hook_calls:
        RDBG_StopDebugging()
        return True
    else:
        return False

def _RDBG_RestartDebugging()->bool:
    if gOptions.hook_calls:
        RDBG_RestartDebugging()
        return True
    else:
        return False

def _RDBG_ProjectBuild(filename:str)->bool:
    if gOptions.stop_debug_on_build and gSession is not None:
        gSession.stop()        
    return False

def _RDBG_StepOverHit():
    if gOptions.hook_calls:
        RDBG_StepOver()

def _RDBG_StepIntoHit():
    if gOptions.hook_calls:
        RDBG_StepInto()

def _RDBG_StepOutHit():
    if gOptions.hook_calls:
        RDBG_StepOut()

def InitialiseRemedy():
    global gOptions
    gOptions = RDBG_Options()

    Editor.AddBreakpointAddedFunction(_RDBG_AddBreakpoint)
    Editor.AddBreakpointRemovedFunction(_RDBG_RemoveBreakpoint)
    Editor.AddBreakpointUpdatedFunction(_RDBG_UpdateBreakpoint)

    Editor.AddOnWorkspaceOpenedFunction(_RDBG_WorkspaceOpened)
    Editor.AddUpdateFunction(_RDBG_Update)
    Editor.AddOnSettingsChangedFunction(_RDBG_SettingsChanged)

    Editor.AddStartDebuggingFunction(_RDBG_StartDebugging)
    Editor.AddStopDebuggingFunction(_RDBG_StopDebugging)
    Editor.AddRestartDebuggingFunction(_RDBG_RestartDebugging)

    Editor.AddProjectBuildFunction(_RDBG_ProjectBuild)

    Editor.AddDebugStepOverFunction(_RDBG_StepOverHit)
    Editor.AddDebugStepIntoFunction(_RDBG_StepIntoHit)
    Editor.AddDebugStepOutFunction(_RDBG_StepOutHit)

gSession:RDBG_Session = None
gOptions:RDBG_Options = None
gOptionsOverride:bool = False
gProcessCache = {} # key = self.name, value = subprocess.Popen. Only populate this with KeepSessionOnActiveChange setting

Editor.CallOnMainThread(InitialiseRemedy)

