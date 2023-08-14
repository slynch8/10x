#------------------------------------------------------------------------
import N10X
import subprocess

TORTOISE_EXE = "TortoiseProc.exe"

class TortoiseSVN_Options():
    def __init__(self):
        self.bin_path = N10X.Editor.GetSetting("TortoiseSVN.TortoisePath")

def TortoiseSVNLog():
    global _svn_options

    if (len(N10X.Editor.GetCurrentFilename()) == 0):
        return

    try:
        subprocess.Popen([_svn_options.bin_path,
                        '/command:log',
                        '/path:' +  N10X.Editor.GetCurrentFilename()],
                        shell=False, stdin=None, stdout=None, stderr=None, 
                        close_fds=True)
    except FileNotFoundError:
        print('[TortoiseSVN]: TortoiseProc executable "' + _svn_options.bin_path + '" could not be found')

def TortoiseSVNDiff():
    global _svn_options

    if (len(N10X.Editor.GetCurrentFilename()) == 0):
        return

    try:
        subprocess.Popen([_svn_options.bin_path,
                        '/command:diff',
                        '/path:' +  N10X.Editor.GetCurrentFilename()],
                        shell=False, stdin=None, stdout=None, stderr=None, 
                        close_fds=True)
    except FileNotFoundError:
        print('[TortoiseSVN]: TortoiseProc executable "' + _svn_options.bin_path + '" could not be found')

def TortoiseSVNBlame():
    global _svn_options

    if (len(N10X.Editor.GetCurrentFilename()) == 0):
        return

    try:
        subprocess.Popen([_svn_options.bin_path,
                        '/command:blame',
                        '/path:' +  N10X.Editor.GetCurrentFilename(),
                        '/line:' + str(N10X.Editor.GetCursorPos()[1] + 1),
                        '/startrev:1',
                        '/endrev:HEAD'],
                        shell=False, stdin=None, stdout=None, stderr=None, 
                        close_fds=True)
    except FileNotFoundError:
        print('[TortoiseSVN]: TortoiseProc executable "' + _svn_options.bin_path + '" could not be found')    


def InitialiseTortoiseSVN():
    global _svn_options
    _svn_options = TortoiseSVN_Options()
    if not N10X.Editor.GetSetting("TortoiseSVN.TortoisePath"):
        N10X.Editor.SetSetting("TortoiseSVN.TortoisePath", TORTOISE_EXE)

N10X.Editor.CallOnMainThread(InitialiseTortoiseSVN)