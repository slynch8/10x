import N10X
import sys,os,subprocess,glob,re,time
import threading
from subprocess import Popen
from subprocess import PIPE, run
from subprocess import check_output

DETACHED_PROCESS = 0x00000008

def process_exists(process_name):
    call = 'TASKLIST', '/FI', 'imagename eq %s' % process_name
    # use buildin check_output right away
    output = subprocess.check_output(call).decode()
    # check in last line for process name
    last_line = output.strip().split('\r\n')[-1]
    # because Fail message could be translated
    return last_line.lower().startswith(process_name.lower())

def IsRemedyBGRunning():
	return process_exists( "RemedyBG.exe" )

def SetBreakpoint(filename, line_index):
	if IsRemedyBGRunning()==True:
		p = Popen(["G:/tools/remedybg/remedybg.exe","add-breakpoint-at-file",filename,str(line_index + 1)], shell=False,stdin=None,stdout=None,stderr=None,close_fds=True,creationflags=DETACHED_PROCESS)

def RemoveBreakpoint(filename, line_index):
	if IsRemedyBGRunning()==True:
		p = Popen(["G:/tools/remedybg/remedybg.exe","remove-breakpoint-at-file",filename,str(line_index + 1)], shell=False,stdin=None,stdout=None,stderr=None,close_fds=True,creationflags=DETACHED_PROCESS)


N10X.Editor.AddBreakpointAddedFunction(SetBreakpoint)
N10X.Editor.AddBreakpointRemovedFunction(RemoveBreakpoint)
