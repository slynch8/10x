import N10X
import os
import tempfile
import shutil
import subprocess

WINDOWSH_URL:str = 'https://github.com/Leandros/WindowsHModular/archive/refs/heads/master.zip'
WINDOWSH_NAME:str = 'WindowsHModular-master'

def WindowsHeadersInstall():
    if N10X.Editor.GetWorkspaceOpenComplete()[0]:
        windows_headers_tempfile = os.path.join(tempfile.gettempdir(), tempfile.gettempprefix() + 'windowsh.zip')
        result = subprocess.run(['powershell', 'Invoke-WebRequest', WINDOWSH_URL, '-O', windows_headers_tempfile])
        if result.returncode == 0:
            shutil.unpack_archive(windows_headers_tempfile, N10X.Editor.GetAppDataWorkspacePath())
            windowsh_includes_dir = os.path.join(N10X.Editor.GetAppDataWorkspacePath(), WINDOWSH_NAME, 'include', 'win32')
            windowsh_includes_dir = os.path.normpath(windowsh_includes_dir)
            N10X.Editor.AddWorkspaceAdditionalInclude(windowsh_includes_dir)
            print('WindowsHeaders: Added include directory "' + windowsh_includes_dir + '"')
    else:
        print('WindowsHeaders: No workspace is opened')
