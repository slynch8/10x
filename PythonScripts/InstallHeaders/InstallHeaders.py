import N10X
import os
import tempfile
import shutil
import subprocess

WINDOWSH_URL:str = 'https://github.com/Leandros/WindowsHModular/archive/refs/heads/master.zip'
WINDOWSH_NAME:str = 'WindowsHModular-master'

CH_URL:str = 'https://github.com/eliphatfs/c-std-headers/archive/refs/heads/main.zip'
CH_NAME:str = 'c-std-headers-main'

def _InstallHeaders(url, name, include_subdir):
    if N10X.Editor.GetWorkspaceOpenComplete()[0]:
        headers_tempfile = os.path.join(tempfile.gettempdir(), tempfile.gettempprefix() + name + '.zip')
        result = subprocess.run(['powershell', 'Invoke-WebRequest', url, '-O', headers_tempfile])
        if result.returncode == 0:
            shutil.unpack_archive(headers_tempfile, N10X.Editor.GetAppDataWorkspacePath())
            includes_dir = os.path.join(N10X.Editor.GetAppDataWorkspacePath(), name, include_subdir)
            N10X.Editor.AddWorkspaceAdditionalInclude(includes_dir.replace('\\', '/'))
            print('InstallHeaders: Added include directory "' + os.path.normpath(includes_dir) + '"')
    else:
        print('InstallHeaders: No workspace is opened')    

def InstallHeadersWindows():
    _InstallHeaders(WINDOWSH_URL, WINDOWSH_NAME, os.path.join('include', 'win32'))

def InstallHeadersC():
    _InstallHeaders(CH_URL, CH_NAME, 'include')
