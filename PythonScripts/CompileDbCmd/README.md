# CompileDb single file compiler

This scripts opens a compilation database file (compile_commands.json) and uses it's commands to compile files in the workspace.  
For questions or suggestions, please contact `septag@pm.me` ([github profile](https://github.com/septag))

## Configuration

Add these to your *10x_settings* file:

- `CompileDb.Path`: Path to generated `compile_commands.json` file. Valid variables that you can use in path: `$(WorkspaceDirectory)`. (Default=`$(WorkspaceDirectory)/build/compile_commands.json`)

## Commands

- **CompDbCompile**: Compiles currently focused file, if the source file can be found in the compilation database


