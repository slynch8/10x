import N10X
import os
import re
import xml.etree.ElementTree as ET

cppExtensions = [
    "inl"
    ,"h","hh","hpp","h++","hp","hxx"
    ,"c","cc","cpp","c++","cp","cxx"
]

allowedSymbolTypes = [
    "Class"
    , "Struct"
    , "InlineMemberFunctionDefinition"
    , "MemberFunctionDeclaration"
    , "FunctionDeclaration"
]


# return the path to Unreal Engine if it is present
def _GetUE5ProjectFilePath():
    projFiles = N10X.Editor.GetWorkspaceProjectFiles()
    for p in projFiles:
        if "UE5.vcxproj" in p:
            return p
    return None

# returns true is this appears to be an Unreal Engine 5 workspace
def _IsUE5Workspace():
    path = _GetUE5ProjectFilePath()
    if path:
        return True
    return False

# returns an array of include paths (forward single slash) for the given project file
def _GetIncludePaths(projFilePath):
    includePaths = []
    includeText= ""
    rsValue = ""

    #parse vcxproj file to find include paths
    tree = ET.parse(projFilePath)
    root = tree.getroot()
    
    #search include paths
    nodeName = _GetXMLNameSpace(root.tag) + "IncludePath"

    for includePath in root.iter(nodeName):
        includeText += includePath.text

    #split include paths by semi colon and put in array
    for includeText in includeText.split(";"):
        includePaths.append(includeText.replace(os.sep, '/'))

    #remove any empty entry in includePaths
    includePaths = list(filter(None, includePaths))

    # search additional include directories too
    for child in root.iter():
        if "ProjectAdditionalIncludeDirectories" in child.tag:
            includePaths.append(child.text.replace(os.sep, '/'))

    return includePaths

# returns the value of the RootNamespace tag. In the UE5 case, this is the name of the 
# current module / Game 
def _GetRootNamespace(projFilePath):
    rsValue = ""

    #parse vcxproj file to find include paths
    tree = ET.parse(projFilePath)
    root = tree.getroot()

    rootNamespaceTag = _GetXMLNameSpace(root.tag) + "RootNamespace"
    rs = root.find(".//" + rootNamespaceTag)
    if rs is not None:
        rsValue = rs.text

    return rsValue

# helper to extract the xml namespace
def _GetXMLNameSpace(tag):
    namespace = ""
    if tag.startswith("{"):
        namespace = tag.split("}")[0] + "}"
    return namespace

# locate the shortest common path for the current active project
def _FindShortestIncludePath(path, includePathArray, activeProject):
    #activeProject = N10X.Editor.GetActiveProject()
    activeProjectDir = os.path.dirname(activeProject)

    #Find the shortest relative path by looking through includePaths
    shortestPath = path
    shortestPathLength = len(path)
    for i in includePathArray:
        #Find normalised path to remove any relative parts, and convert to forward slashes for comparison
        if os.path.isabs( i ):
            possiblePrefix = i.replace(os.sep, '/')
        else:
            possiblePrefix = os.path.normpath(activeProjectDir + "/" + i).replace(os.sep, '/')
        #print(" Path: " + possiblePrefix + "\n")

        if path.startswith(possiblePrefix):
            candidate = path[len(possiblePrefix)+1:]
            candidateLength = len(candidate)
            #print("Found path candidate: " + candidate)
            if candidateLength < shortestPathLength:
                shortestPath = candidate
                shortestPathLength = candidateLength

    #print("Best path candidate: " + shortestPath)
    return shortestPath


def AddInclude():
    x, y = N10X.Editor.GetCursorPos()
    symbol = N10X.Editor.GetCurrentSymbolType()

    symbolTypeFound = False
    for symType in allowedSymbolTypes:
        if symbol == symType:
            symbolTypeFound = True
            break

    if symbolTypeFound == False:
        return

    currentPath = N10X.Editor.GetCurrentFilename()
    dir, file = os.path.split(currentPath)
    name, extension = file.split(".")
    
    # ensure that this code will only run on
    # c/c++ files
    extensionFound = False
    for ext in cppExtensions:
        if extension == ext:
            extensionFound = True
            break

    if extensionFound == False:
        return

    # cache GotoFunctionImplementation and force it off temporarily
    oldGotoFunctionImplementation = N10X.Editor.GetSetting("GotoFunctionImplementation") 
    N10X.Editor.SetSetting("GotoFunctionImplementation", "false") 

    # grab the filepath for the current symbol
    path = N10X.Editor.GetSymbolDefinitionFilename(N10X.Editor.GetCursorPos())

    # restore GotoFunctionImplementation to old value
    N10X.Editor.SetSetting("GotoFunctionImplementation", oldGotoFunctionImplementation) 

    # dont bother including if the symbol
    # is defined in the current file
    if path == currentPath:
        return
    
    # get the include paths for the active project
    activeProject = N10X.Editor.GetActiveProject() 
    includePaths = _GetIncludePaths(activeProject)

    # add the include paths from Unreal Engine plugins and engine code
    # TODO: Find a more general way to determine this kind of dependency, and make sure this works for all workspace types
    isUE = False
    engineIncludePaths = []
    engineProjectFile = ""

    if _IsUE5Workspace():
        isUE = True
        engineProjectFile = _GetUE5ProjectFilePath()
        engineIncludePaths = _GetIncludePaths(engineProjectFile)
        includePaths = includePaths + engineIncludePaths

    #N10X.Editor.LogTo10XOutput( f"[AddInclude] Active Project: {activeProject}\n\tActive Project Dir: {os.path.dirname(activeProject)}\n\tpath: {path}\n\tcurrentPath: {currentPath}\n" )
    # incs = '\n\t'.join(includePaths)
    # N10X.Editor.LogTo10XOutput( f"[AddInclude] IncludePaths: \n{incs}\n")

    # trim the path if possible
    commonpath = path
    try:
        commonpath = os.path.commonpath((path, currentPath))
    except ValueError:
        print( "[AddInclude] Paths on seperate drives?")

    relpath = os.path.relpath(path, commonpath)    
    relpath = _FindShortestIncludePath(path, includePaths, activeProject)

    # windows backslash separators are undefined behavior
    relpathStandard = relpath.replace(os.sep, '/')

    # If this is a UE project, let's try and see if we can
    # reduce the include path to just the Public and Private 
    # include directories plus whatever subdirectory the symbol
    # may be in
    if os.path.isabs(relpathStandard) and isUE:
        ns = _GetRootNamespace(activeProject)
        wsFileName = N10X.Editor.GetWorkspaceFilename()
        solutionDir, solutionFile = os.path.split(wsFileName)
        publicFiles = solutionDir + '/Source/' + ns + "/Public/"
        privateFiles = solutionDir + '/Source/' + ns + "/Private/"
        if relpathStandard.startswith(publicFiles):
            relpathStandard = relpathStandard[len(publicFiles):]
        elif relpathStandard.startswith(privateFiles):
            relpathStandard = relpathStandard[len(privateFiles):]
    
    output = f"#include \"{relpathStandard}\""

    otherDir, otherFile = os.path.split(path)
    
    # early out if file is already included
    result = re.search(f"#include\s\".*{otherFile}\"", N10X.Editor.GetFileText())
    
    if result:
        return

    # append the found file at the bottom of already included files
    #
    # TODO: this will probably break if .inl files are included
    # at the bottom of .h files
    for i in range(N10X.Editor.GetLineCount() - 1, 0, -1):
        line = N10X.Editor.GetLine(i)
        result = re.search("#include", line)
        if result:
            # -2 to also trim the newline char
            N10X.Editor.SetCursorPos((len(line)-2,i))
            # Make sure the cursor is placed at the end of the line, even if there is ws
            N10X.Editor.ExecuteCommand("MoveToLineEnd")
            N10X.Editor.PushUndoGroup()
            N10X.Editor.InsertText(f"\n{output}")
            N10X.Editor.SetCursorPos((x, y+1))
            N10X.Editor.PopUndoGroup()
            return
        N10X.Editor.SetCursorPos((x, y+1))
    
    N10X.Editor.PushUndoGroup()
    # in the odd case that there aren't already includes in the file
    # find first uncommented line
    topY = 0

    line = N10X.Editor.GetLine(topY)
    while re.search(r"//", line):
        topY = topY + 1
        line = N10X.Editor.GetLine(topY)

    N10X.Editor.SetCursorPos((0,topY))
    # if there are top-level comments, add a newline
    if topY > 0:
        N10X.Editor.InsertText(f"\n")
    N10X.Editor.InsertText(f"{output}\n")
    if not line.isspace():
        N10X.Editor.InsertText(f"\n")

    N10X.Editor.SetCursorPos((x, y + 1))
    N10X.Editor.PopUndoGroup()
