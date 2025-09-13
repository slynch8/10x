from N10X import Editor as Editor
import re

def _GetForwardDeclInsertionPos(startPos, endPos, symName, symType):

    #Editor.SetSelection(startPos, endPos)

    lineToInsert = -1
    column = 0
    prefix = symType
    firstBlankLinePos = -1
    existingDeclsFound = False

    for i in range(startPos[1], endPos[1], 1):
        line = Editor.GetLine(i)
        #print(f"LINE: {i} Value: `{line.lstrip().rstrip()}`")
        if len(line.lstrip().rstrip()) == 0 and lineToInsert == -1:
            lineToInsert = i
            firstBlankLinePos = i
        else:
            result = re.search(".*\\bclass\\b.*(\\w);", line) if symType == "class" else re.search(".*\\bstruct\\b.*(\\w);", line)
            
            if result:
                declName = result.group().lstrip().removeprefix(prefix)
                #print(f"declName {declName}")
                if declName.rstrip()[-1] == ";":
                    if declName.lstrip().removesuffix(";") == symName:
                        # Forward Declaration already present
                        column = -1;
                        break;
                    else:
                        # Found another decl, so let's keep looking to place
                        # new decl after the last forward declaration
                        existingDeclsFound = True
                        lineToInsert = i+1

        #print(f"\tLine To Insert: {lineToInsert}")

    if existingDeclsFound == False or lineToInsert == -1:
        lineToInsert = startPos[1]+1
        
    return (column,lineToInsert)



def _GetEndOfIncludesPos():
    x = 0
    y = 0

    for i in range(Editor.GetLineCount() - 1, 0, -1):
        line = Editor.GetLine(i)
        result = re.search("#include", line)
        if result:
            # -2 to also trim the newline char
            Editor.SetCursorPos((len(line)-2,i))
            # Make sure the cursor is placed at the end of the line, even if there is ws
            Editor.ExecuteCommand("MoveToLineEnd")
            pos = Editor.GetCursorPos()
            return pos

    return (0,0)

def _FindInsertionPoint( currentScopePos, symName, symType ):
    includePos = _GetEndOfIncludesPos()
    insertPos = _GetForwardDeclInsertionPos(includePos, currentScopePos, symName, symType )

    return insertPos

# Adds a forward declaration of whatever token the cursor is currently on
def AddForwardDeclaration():
    Editor.PushUndoGroup()
    origPos = Editor.GetCursorPos()
    
    Editor.ExecuteCommand("SelectCurrentWord")
    symName = Editor.GetSelection()
    symType = Editor.GetSymbolType(origPos).lower()
    Editor.ExecuteCommand("SelectCurrentScope")
    currentScopePos = Editor.GetSelectionStart()

    insertPos = _FindInsertionPoint( currentScopePos, symName, symType )

    if insertPos[0] != -1:

        #print(f"Insert POS: {insertPos}")

        output = f"{symType} {symName};\n"

        Editor.BeginTextUpdate()
        Editor.SetCursorPos(insertPos)

        Editor.InsertText(f"{output}")
        Editor.SetCursorPos((origPos[0], origPos[1]+1)) 
        Editor.EndTextUpdate() 
    else:
        Editor.LogTo10XOutput(f"[AddForwardDeclaration] {symName} alread present as a forward declaration")
        Editor.SetCursorPos(origPos) 

    Editor.PopUndoGroup()
    