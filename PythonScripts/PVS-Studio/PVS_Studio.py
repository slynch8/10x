import subprocess
import threading
import xml.etree.ElementTree as ET
from N10X import Editor as editor

"""
PVS-Studio: https://pvs-studio.com/en/docs/manual/0035/
"""

def __print(msg: str):
    editor.LogToBuildOutput(msg)
    editor.LogToBuildOutput('\n')

def __read_plog(plog_file):
    tree = ET.parse(plog_file)
    root = tree.getroot()

    sln_path = root.find('Solution_Path')
    if sln_path:
        sln_ver = sln_path.find('SolutionVersion')
        plog_ver = sln_path.find('PlogVersion')
        __print(f'Visual Studio: {sln_ver.text}')
        __print(f'Plog Version: {sln_ver.text}')

    for it in root.findall('PVS-Studio_Analysis_Log'):
        project_name = it.find('Project').text
        error_code = it.find('ErrorCode').text
        short_file = it.find('ShortFile').text
        line = it.find('Line').text
        false_alarm = it.find('FalseAlarm').text
        message = it.find('Message').text

        __print(f'Project[{project_name}] - Error[{error_code}] - Alarm[{false_alarm}]')
        __print(f'\t{short_file} - {line}')
        __print(f'\t{message}')


def __pvs_studio_run(cmd: str, plog_file: str):
    __print(f'{cmd}\n')
    process = subprocess.Popen(cmd)
    process.wait()
    __read_plog(plog_file)

def PVSStudioCmd():
    editor.ClearBuildOutput()
    editor.Clear10xOutput()

    editor.ShowBuildOutput()

    __print('===== PVS-STUDIO =====')

    workspace = editor.GetWorkspaceFilename()
    exe = 'C:\Program Files (x86)\PVS-Studio\PVS-Studio_Cmd.exe'
    arg_sln = f'--target "{workspace}"'
    arg_log = f'--output "{workspace}.plog"'
    arg_cfg = f'--configuration {editor.GetBuildConfig()}'
    arg_plat = f'--platform {editor.GetBuildPlatform()}'
    cmd = f'{exe} {arg_sln} {arg_cfg} {arg_plat} {arg_log}'

    plog_file = f'{editor.GetWorkspaceFilename()}.plog'

    t = threading.Thread(
        target=__pvs_studio_run,
        args=(cmd, plog_file,))
    t.start()
