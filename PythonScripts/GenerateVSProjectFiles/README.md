
# Generate Visual Studio Project Files
This script can be used to generate the .sln file that 10x is using for a Visual Studio Workspace

In order for this script to succeed, the following setting values need to be placed in the Settings.10x_settings file:

UE.Project:                         <Absolute path to uproject, using \ for path delimiters. EG: E:\Unreal\MyProj\MyProj.uproject>
UE.InstallDir:                      <Absolute path to UnrealEngine install. EG: D:\UnrealEngine>

# Use the value specified here for the UE.GenVSProjCommand. So just copy the following line and put directly into your settings file:
UE.GenVSProjCommand:                dotnet "{ueInstallDir}\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.dll" -projectfiles -project="{ueProject}" -game -engine -progress -log="{logPath}"

Once these settings are in place, create a new keystroke in your key map. For example:
Alt Shift Control G:        GenerateVSProjectFiles()

You will need to save your workspace prior to running this script.