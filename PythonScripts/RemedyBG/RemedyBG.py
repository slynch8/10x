import N10X
import subprocess
import io
from typing import NamedTuple
import time

DETACHED_PROCESS = 0x00000008
REMEDYBG_PROCESS = "remedybg.exe"

class RemedyBGBreakpoint(NamedTuple):
    filename : str
    line_index : str

remedybg_started:bool = False
remedybg_path:str = None
remedybg_proc_id:int = 0
remedybg_active_project:str = None
remedybg_breakpoints:RemedyBGBreakpoint = []
remedybg_run_after_build = False

def _RemedyBGFindProcess()->bool:
    global remedybg_path
    global remedybg_proc_id

    args = "wmic process where \"name='%s'\" get ExecutablePath,ProcessId" % (REMEDYBG_PROCESS)
    result:subprocess.CompletedProcess = subprocess.run(args, shell=True, capture_output=True)
    if result.returncode == 0:
        buf = io.StringIO(result.stdout.decode('UTF-8'))
        if buf.readline().startswith("ExecutablePath"):
            proc_id = 0
            while True:
                l = buf.readline()
                if not l or l.strip() == '':
                    break
                remedybg_proc_info = l.strip().split(' ')
                remedybg_path = remedybg_proc_info[0]
                if len(remedybg_proc_info) > 2:
                    proc_id = int(remedybg_proc_info[2])
                    if proc_id == remedybg_proc_id:
                        return True
            remedybg_proc_id = proc_id
            return True if proc_id != 0 else False
        else:
            remedybg_path = None
            remedybg_proc_id = 0
            return False
    else:
        remedybg_path = None
        remedybg_proc_id = 0
        print('[RemedyBG]: Error searching for remedybg process (wmic command)')
        return False

def _RemedyBGExecuteProcess():
    global remedybg_path
    global remedybg_proc_id

    remedybg_exe = N10X.Editor.GetSetting("RemedyBG.Path")
    if not remedybg_exe:
        remedybg_exe = REMEDYBG_PROCESS
    
    debug_cmd = N10X.Editor.GetDebugCommand()
    debug_args = N10X.Editor.GetDebugCommandArgs()
    debug_cwd = N10X.Editor.GetDebugCommandCwd()

    p = subprocess.Popen(remedybg_exe + ' "' + debug_cmd + '" ' + debug_args, 
                         shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS, cwd=debug_cwd)
    if p.pid:
        remedybg_path = remedybg_exe
        remedybg_proc_id = p.pid    
        print('remedybg.exe: ' + str(remedybg_proc_id))

def _RemedyBGStopProcess():
    global remedybg_path
    global remedybg_proc_id
    if remedybg_proc_id != 0:
        print('[RemedyBG]: Stopping remedybg.exe, pid: ' + str(remedybg_proc_id))
        subprocess.run("taskkill /F /PID " + str(remedybg_proc_id), shell=True)
        time.sleep(0.1)
        
    remedybg_path = None
    remedybg_proc_id = 0

def _RemedyBGAddBreakpoint(filename, line_index):
    global remedybg_breakpoints

    if not (filename, line_index) in remedybg_breakpoints:
        remedybg_breakpoints.append(RemedyBGBreakpoint(filename, line_index))

        if remedybg_started and remedybg_proc_id != 0:
            subprocess.Popen([remedybg_path, "add-breakpoint-at-file" , filename, str(line_index + 1)], 
                            shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)
    
def _RemedyBGRemoveBreakpoint(filename, line_index):
    global remedybg_breakpoints

    if (filename, line_index) in remedybg_breakpoints:
        remedybg_breakpoints.remove(RemedyBGBreakpoint(filename, line_index))
        if remedybg_started and remedybg_proc_id != 0:
            subprocess.Popen([remedybg_path, "remove-breakpoint-at-file" , filename, str(line_index + 1)], 
                            shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)

def _RemedyBGOnWorkspaceOpened():
    RemedyBGStop()

def _RemedyBGSyncCurrentBreakpoints():
    for b in remedybg_breakpoints:
        # we have to wait a bit before submitting each breakpoint to remedy otherwise it won't accept all of them
        # TODO: come up with a better solution, because this obviously stalls the editor
        time.sleep(0.1) 
        subprocess.Popen([remedybg_path, "add-breakpoint-at-file" , b.filename, str(b.line_index + 1)], 
                          shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)

def _RemedyBGStartDebug():
    if remedybg_started and remedybg_proc_id != 0:
        subprocess.Popen([remedybg_path, "start-debugging"], 
                        shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)

def RemedyBGStart():
    global remedybg_path
    global remedybg_proc_id
    global remedybg_active_project
    global remedybg_started

    if remedybg_started:
        return

    active_project:str = N10X.Editor.GetActiveProject()
    cur_proc_id = remedybg_proc_id
    if remedybg_proc_id == 0 or (not _RemedyBGFindProcess()) or cur_proc_id != remedybg_proc_id:
        _RemedyBGExecuteProcess()
    else:
        print('[RemedyBG]: remedybg instance found: ' + remedybg_path + ', ProcId: ' + str(remedybg_proc_id))
        if remedybg_active_project != None and remedybg_active_project != active_project:
            print('[RemedyBG]: remedybg is on a different project, reopening with a new session ...')
            remedybg_active_project = active_project
            _RemedyBGStopProcess()
            RemedyBGStart()

    remedybg_active_project = active_project

    if remedybg_proc_id != 0:
        _RemedyBGSyncCurrentBreakpoints()
        remedybg_started = True
        print('RemedyBG debugging session started.')

def RemedyBGStop():
    global remedybg_breakpoints
    global remedybg_started

    if remedybg_started:
        _RemedyBGStopProcess()
        N10X.Editor.ExecuteCommand('RemoveAllBreakpoints')
        remedybg_breakpoints = []
        remedybg_started = False
        print('RemedyBG debugging session stopped.')

def RemedyBGRun():
    global remedybg_run_after_build

    if not remedybg_started:
        print('[RemedyBG]: remedybg session is not started, starting a new session ...')
        RemedyBGStart()
        time.sleep(0.1)

    if remedybg_started and remedybg_proc_id == 0:
        _RemedyBGExecuteProcess()
        _RemedyBGSyncCurrentBreakpoints()
        time.sleep(0.1)

    build_before_debug = True if \
        (N10X.Editor.GetSetting("BuildBeforeStartDebugging") and N10X.Editor.GetSetting("BuildBeforeStartDebugging")[0] == 't') else False
    if build_before_debug:
        remedybg_run_after_build = True
        N10X.Editor.ExecuteCommand('BuildActiveWorkspace')
    else:
        _RemedyBGStartDebug()

def _RemedyBGBuildFinished(result):
    global remedybg_run_after_build
    if remedybg_run_after_build and result:
        _RemedyBGStartDebug()
    remedybg_run_after_build = False

def _RemedyBGRunToCursor():
    if remedybg_started and remedybg_proc_id != 0:
        filename = N10X.Editor.GetCurrentFilename()
        line_index = N10X.Editor.GetCursorPos()[1]
        subprocess.Popen([remedybg_path, "run-to-cursor", filename, str(line_index + 1)], 
                    shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)

def RemedyBGRunToCursor(*, deny_rebuild=False):
    """
    Provides RunToCursor behaviour from VisualStudio/RemedyBG (Control + F10)
    Command also:
      rebuilds the workspace if BuildBeforeStartDebugging is set
      tries to launch the debugger
      syncs the breakpoints
    deny_rebuild option can be passed to the function to ignore settings
    this allows you to have 2 bindings. For example:
      Control F10 to run and rebuild
      Control Shift F10 to run without rebuild
    """
    global remedybg_run_to_cursor_after_build
    if not remedybg_started:
        print('[RemedyBG.py]: remedybg session is not started, starting a new session ...')
        RemedyBGStart()
        time.sleep(0.1)

    if remedybg_started and remedybg_proc_id == 0:
        _RemedyBGExecuteProcess()
        _RemedyBGSyncCurrentBreakpoints()
        time.sleep(0.1)

    build_before_debug = True if \
        (N10X.Editor.GetSetting("BuildBeforeStartDebugging") and N10X.Editor.GetSetting("BuildBeforeStartDebugging")[0] == 't') else False
    if deny_rebuild:
        build_before_debug = False

    if build_before_debug:
        remedybg_run_to_cursor_after_build = True
        N10X.Editor.ExecuteCommand('BuildActiveWorkspace')
    else:
        _RemedyBGRunToCursor()

N10X.Editor.AddOnWorkspaceOpenedFunction(_RemedyBGOnWorkspaceOpened)
N10X.Editor.AddBreakpointAddedFunction(_RemedyBGAddBreakpoint)
N10X.Editor.AddBreakpointRemovedFunction(_RemedyBGRemoveBreakpoint)
N10X.Editor.AddBuildFinishedFunction(_RemedyBGBuildFinished)

