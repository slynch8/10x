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

remedybg_path:str = None
remedybg_proc_id:int = 0
remedybg_active_project:str = None
remedybg_breakpoints:RemedyBGBreakpoint = []

def _RemedyBGFindProcess()->bool:
    global remedybg_path
    global remedybg_proc_id

    args = "wmic process where \"name='%s'\" get ExecutablePath,ProcessId" % (REMEDYBG_PROCESS)
    result:subprocess.CompletedProcess = subprocess.run(args, shell=True, capture_output=True)
    if result.returncode == 0:
        buf = io.StringIO(result.stdout.decode('UTF-8'))
        if buf.readline().startswith("ExecutablePath"):
            remedybg_proc_info = buf.readline().strip().split(' ')
            remedybg_path = remedybg_proc_info[0]
            remedybg_proc_id = int(remedybg_proc_info[2])
            return True
        else:
            remedybg_path = None
            remedybg_proc_id = 0
            return False
    else:
        remedybg_path = None
        print('[RemedyBG.py]: Error searching for remedybg process (wmic command)')
        return False

def _RemedyBGStopProcess():
    global remedybg_path
    global remedybg_proc_id
    if remedybg_proc_id != 0:
        print('[RemedyBG.py]: Stopping remedybg.exe, pid: ' + str(remedybg_proc_id))
        subprocess.run("taskkill /PID " + str(remedybg_proc_id), shell=True)
        
    remedybg_path = None
    remedybg_proc_id = 0

def _RemedyBGAddBreakpoint(filename, line_index):
    global remedybg_breakpoints
    remedybg_breakpoints.append(RemedyBGBreakpoint(filename, line_index))

    if remedybg_proc_id != 0:
        subprocess.Popen([remedybg_path, "add-breakpoint-at-file" , filename, str(line_index + 1)], 
                         shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)
    
def _RemedyBGRemoveBreakpoint(filename, line_index):
    global remedybg_breakpoints

    try:
        remedybg_breakpoints.remove(RemedyBGBreakpoint(filename, line_index))
    except:
        pass

    if remedybg_proc_id != 0:
        subprocess.Popen([remedybg_path, "remove-breakpoint-at-file" , filename, str(line_index + 1)], 
                          shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)

def _RemedyBGOnWorkspaceOpened():
    RemedyBGStop()

def RemedyBGStart():
    global remedybg_path
    global remedybg_proc_id
    global remedybg_active_project

    active_project:str = N10X.Editor.GetActiveProject()

    if not _RemedyBGFindProcess() and remedybg_proc_id == 0:
        print('[RemedyBG.py]: remedybg is not running, opening a new debugging session ...')
        remedybg_exe = N10X.Editor.GetSetting("RemedyBG.Path")
        if not remedybg_exe:
            remedybg_exe = REMEDYBG_PROCESS
        workspace_exe = N10X.Editor.GetWorkspaceExePath()
        p = subprocess.Popen([remedybg_exe, workspace_exe], 
                            shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)
        if p.pid:
            remedybg_path = remedybg_exe
            remedybg_proc_id = p.pid
    else:
        print('[RemedyBG.py]: remedybg instance found: ' + remedybg_path + ', ProcId: ' + str(remedybg_proc_id))
        if remedybg_active_project != None and remedybg_active_project != active_project:
            print('[RemedyBG.py]: remedybg is on a different project, reopening with a new session ...')
            remedybg_active_project = active_project
            _RemedyBGStopProcess()
            RemedyBGStart()

    remedybg_active_project = active_project

    if remedybg_proc_id != 0:
        for b in remedybg_breakpoints:
            time.sleep(0.5)
            subprocess.Popen([remedybg_path, "add-breakpoint-at-file" , b.filename, str(b.line_index + 1)], 
                              shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)

def RemedyBGStop():
    global remedybg_breakpoints

    _RemedyBGStopProcess()
    N10X.Editor.ExecuteCommand('RemoveAllBreakpoints')
    remedybg_breakpoints = []
    
def RemedyBGRun():
    if remedybg_proc_id != 0:
        subprocess.Popen([remedybg_path, "start-debugging"], 
                        shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)


N10X.Editor.AddOnWorkspaceOpenedFunction(_RemedyBGOnWorkspaceOpened)
N10X.Editor.AddBreakpointAddedFunction(_RemedyBGAddBreakpoint)
N10X.Editor.AddBreakpointRemovedFunction(_RemedyBGRemoveBreakpoint)


