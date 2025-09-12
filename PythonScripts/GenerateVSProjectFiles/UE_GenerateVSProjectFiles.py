#------------------------------------------------------------------------
import N10X
import os
from datetime import datetime
import threading



# In order for this method to succeed, the following setting values need to be placed in the Settings.10x_settings file:

# UE.Project:                         <Absolute path to uproject, using \ for path delimiters. EG: E:\Unreal\MyProj\MyProj.uproject>
# UE.InstallDir:                      <Absolute path to UnrealEngine install. EG: D:\UnrealEngine>

# # Use the value specified here for the UE.GenVSProjCommand. So just copy the following line and put directly into your settings file:
# UE.GenVSProjCommand:                dotnet "{ueInstallDir}\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.dll" -projectfiles -project="{ueProject}" -game -engine -progress -log="{logPath}"

# Once these settings are in place, create a new keystroke in your key map. For example:
# Alt Shift Control G:        UE_GenerateVSProjectFiles()


def _genProjectFilesInBackground( command ):
    os.system(command)


def UE_GenerateVSProjectFiles():
    N10X.Editor.LogTo10XOutput("\n\n[UE] Generate Visual Studio Project\n")

    ueProject = N10X.Editor.GetSetting("UE.Project")
    ueInstallDir = N10X.Editor.GetSetting("UE.InstallDir")
    ueCommand = N10X.Editor.GetSetting("UE.GenVSProjCommand")


    index = ueProject.rindex("\\")
    if index == -1:
        index = ueProject.rindex("/")

    slice = len(ueProject) - index
    currentDateTime = datetime.now()
    timeStr = currentDateTime.strftime("%Y.%m.%d-%H.%M.%S")
    logPath = ueProject[:-slice] + f"\\Saved\\Logs\\10x-{timeStr}.log"      

    fullCommand = ueCommand.format( ueProject = ueProject, ueInstallDir = ueInstallDir, logPath = logPath)
    #N10X.Editor.LogTo10XOutput(f"[UE] ueProject: {ueProject}\n[UE] ueInstallDir: {ueInstallDir}\n[UE] logPath: {logPath}\n[UE] ueCommand: {ueCommand}\n")
    #N10X.Editor.LogTo10XOutput("[UE] Full Command:" + fullCommand + "\n")

    N10X.Editor.SetStatusBarText(f"[UE_GenerateVSProjectFiles] Generating project files. The workspace will reopen momentarily.")

    thread = threading.Thread(target=_genProjectFilesInBackground, args=(fullCommand, ))
    thread.start()

    
