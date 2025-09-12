
# Generate Visual Studio Project Files for Unreal Engine Projects
This script can be used to generate the .sln file that 10x is using for a Visual Studio Workspace

In order for this script to succeed, the following setting values need to be placed in the Settings.10x_settings file:

UE.Project:                         <Absolute path to uproject, using \ for path delimiters. EG: E:\Unreal\MyProj\MyProj.uproject>
UE.InstallDir:                      <Absolute path to UnrealEngine install. EG: D:\UnrealEngine>

# Use the value specified here for the UE.GenVSProjCommand. So just copy the following line and put directly into your settings file:
UE.GenVSProjCommand:                dotnet "{ueInstallDir}\Engine\Binaries\DotNET\UnrealBuildTool\UnrealBuildTool.dll" -projectfiles -project="{ueProject}" -game -engine -progress -log="{logPath}"

Once these settings are in place, create a new keystroke in your key map. For example:
Alt Shift Control G:        GenerateVSProjectFiles()

You will need to save your workspace prior to running this script.

## Do NOT turn of Intellisense generation

I want to leave these instructions here so that at a later time it will be possible to turn off the generation of intellisense data, but unfortunately, as of 9/11/2025,
generating Intellisense data has a side effect which generates the IncludePath tags in the project files, which is used by the AddInclude.py script to properly
add header files for types under the cursor.

Until I find a solution to this problem, reverting back to REQUIRING the bGenerateIntelliSenseData to `true`


## REFRAIN FROM THE FOLLOWING FOR NOW ( see note above )

Also, I highly recommend turning OFF Intellisense generation ( as we are using 10X after all! ) for your projects.

You can do this by modifying the BuildConfiguration.xml file found in `<dir of your .sln file>/Saved/UnrealBuildTool/BuildConfiguration.xml`.

By default, that file will look like this:

`<?xml version="1.0" encoding="utf-8" ?>
<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">
</Configuration>`

Add the following between those `Configuration` tags:

`<ProjectFileGenerator>
    <bGenerateIntelliSenseData>false</bGenerateIntelliSenseData>
</ProjectFileGenerator>`

so the default BuildConfiguration.xml file after the addition of the new tags should look like this:

`<?xml version="1.0" encoding="utf-8" ?>
<Configuration xmlns="https://www.unrealengine.com/BuildConfiguration">
    <ProjectFileGenerator>
        <bGenerateIntelliSenseData>false</bGenerateIntelliSenseData>
    </ProjectFileGenerator>
</Configuration>`
