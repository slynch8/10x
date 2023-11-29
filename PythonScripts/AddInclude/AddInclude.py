import N10X
import os
import re

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

def AddInclude():
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

    # grab the filepath for the current symbol
    N10X.Editor.ExecuteCommand("GotoSymbolDefinition");
    path = N10X.Editor.GetCurrentFilename();

    # dont bother including if the symbol
    # is defined in the current file
    if path == currentPath:
        return

    N10X.Editor.ExecuteCommand("PrevLocation");

    # trim the path if possible
    #
    # TODO: could check against include paths and
    # use the shortest path available
    commonpath = os.path.commonpath((path, currentPath))
    relpath = os.path.relpath(path, commonpath)
    output = f"#include \"{relpath}\""

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
            N10X.Editor.PushUndoGroup()
            N10X.Editor.InsertText(f"\n{output}")
            N10X.Editor.PopUndoGroup()
            return
    
    # in the odd case that there arn't already includes in the file
    N10X.Editor.SetCursorPos((0,0))
    N10X.Editor.PushUndoGroup()
    N10X.Editor.InsertText(f"\n{output}")
    N10X.Editor.PopUndoGroup()
