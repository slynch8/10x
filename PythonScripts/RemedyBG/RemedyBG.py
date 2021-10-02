import N10X
import subprocess
import io

DETACHED_PROCESS = 0x00000008
REMEDYBG_PROCESS = "remedybg.exe"
remedybg_path:str = None

def _find_remedybg_process()->bool:
    global remedybg_path

    args = "wmic process where \"name='%s'\" get ExecutablePath" % (REMEDYBG_PROCESS)
    result:subprocess.CompletedProcess = subprocess.run(args, shell=True, capture_output=True)
    if result.returncode == 0:
        buf = io.StringIO(result.stdout.decode('UTF-8'))
        if buf.readline().startswith("ExecutablePath"):
            remedybg_path = buf.readline().strip()
            print('RemedyBG Ready: ' + remedybg_path)
            return True
        else:
            remedybg_path = None
            return False
    else:
        remedybg_path = None
        print('[RemedyBG.py]: Error searching for remedybg process (wmic command)')
        return False

def _SetBreakpoint(filename, line_index):
    if remedybg_path:
        subprocess.Popen([remedybg_path, "add-breakpoint-at-file" , filename, str(line_index + 1)], 
                         shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)

def _RemoveBreakpoint(filename, line_index):
    if remedybg_path:
        subprocess.Popen([remedybg_path, "remove-breakpoint-at-file" , filename, str(line_index + 1)], 
                          shell=False, stdin=None, stdout=None, stderr=None, close_fds=True, creationflags=DETACHED_PROCESS)

def RemedyBGStartSync():
    if not _find_remedybg_process():
        print('[RemedyBG.py]: remedybg is not running, open it up and try again')
    else:
        print('[RemedyBG.py]: remedybg instance found: ' + remedybg_path)
        N10X.Editor.AddBreakpointAddedFunction(_SetBreakpoint)
        N10X.Editor.AddBreakpointRemovedFunction(_RemoveBreakpoint)

def RemedyBGEndSync():
    global remedybg_path
    remedybg_path = None

