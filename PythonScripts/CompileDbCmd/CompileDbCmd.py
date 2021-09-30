# Single file compile command for projects with compile commands database
# For questions, bugs and suggestions, contact septag@pm.me

import N10X
import os
import json
import subprocess
from typing import NamedTuple
import time

class CompileEntry(NamedTuple):
    cwd : str
    args : str

compile_entries = {}

def ParseCompDb():
    global compile_entries

    workspace_dir:str = os.path.dirname(os.path.normpath(N10X.Editor.GetWorkspaceFilename()))
    compdb_path:str = N10X.Editor.GetSetting("CompileDb.Path")
    if compdb_path == "":
        compdb_path = os.path.join(workspace_dir, 'build', 'compile_commands.json')
    compdb_path = compdb_path.replace('$(WorkspaceDirectory)', workspace_dir)
    compdb_path = os.path.normpath(compdb_path)
    
    if os.path.isfile(compdb_path):
        print('[CompileCmdSupport.py]: Parsing compilation database: ' + compdb_path)
        start : float = time.perf_counter()
        with open(compdb_path, 'r') as f:
            compiledb_data = json.load(f)
            f.close()

        for compile_entry in compiledb_data:
            compile_entries[compile_entry['file']] = CompileEntry(compile_entry['directory'], compile_entry['command'])
        print('[CompileCmdSupport.py]: Parse time: %fs' % (time.perf_counter() - start))

def CompDbCompile():
    cur_filename:str = N10X.Editor.GetCurrentFilename()
    if cur_filename in compile_entries:
        entry : CompileEntry = compile_entries[cur_filename]
        N10X.Editor.LogToBuildOutput(entry.args + '\n')
        result : subprocess.CompletedProcess = subprocess.run(entry.args, cwd=entry.cwd, shell=True, capture_output=True)
        if result.stderr != None and len(result.stderr) > 0:
            N10X.Editor.LogToBuildOutput(result.stderr.decode('UTF-8'))
        elif result.stdout != None and len(result.stdout) > 0:
            N10X.Editor.LogToBuildOutput(result.stdout.decode('UTF-8'))
        else:
            N10X.Editor.LogToBuildOutput('0 Errors, 0 Warnings\n')

def CompDbReload():
    global compile_entries
    if N10X.Editor.GetWorkspaceOpenComplete():
        compile_entries.clear()
        ParseCompDb()

N10X.Editor.AddOnWorkspaceOpenedFunction(ParseCompDb)
