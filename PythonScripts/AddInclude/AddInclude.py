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

    # grab the filepath for the current symbol
    path = N10X.Editor.GetSymbolDefinitionFilename(N10X.Editor.GetCursorPos())

    # dont bother including if the symbol
    # is defined in the current file
    if path == currentPath:
        return

    # trim the path if possible
    #
    # TODO: could check against include paths and
    # use the shortest path available
    commonpath = os.path.commonpath((path, currentPath))
    relpath = os.path.relpath(path, commonpath)

    # windows backslash separators are undefined behavior
    relpathStandard = relpath.replace(os.sep, '/')

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
