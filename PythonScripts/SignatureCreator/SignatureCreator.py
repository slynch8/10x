import N10X
from Utilities import *


def _IsFunctionDefinition(Type: str) -> bool:
    return Type == "MemberFunctionDefinition" or Type == "FunctionDefinition"


def _IsCurrentLineFunctionDeclaration():
    CurrentLineText = SourceCodeLine.FromCurrentLine()
    return CurrentLineText.HasAny(["MemberFunctionDeclaration", "FunctionDeclaration"])


def _MakeImplementationSignature():
    DeclarationLine = N10X.Editor.GetCurrentLine()
    X, LineNum = N10X.Editor.GetCursorPos()

    FunctionArgStart = DeclarationLine.find("(")
    FunctionArgEnd = DeclarationLine.rfind(")")
    FunctionName = DeclarationLine[0:FunctionArgStart].split()[-1]

    ReturnTypeEnd = DeclarationLine.find(FunctionName)

    # Remove all macro from return type, mainly to remove any MODULENAME_API defines
    # TODO: We probably also want to remove Defines from function args, like UPARAM
    ReturnType = str(SourceCodeLine(DeclarationLine[0:ReturnTypeEnd], LineNum).RemoveAll("Define"))

    ReturnType = ReturnType.replace("virtual", "")
    ReturnType = ReturnType.replace("static", "")

    ReturnType = ReturnType.lstrip()

    # Trailing specifiers can include const, override, final,
    # Obviously we don't want implementation for = 0, = default,  = delete
    FunctionTrailingSpecifiers = DeclarationLine[FunctionArgEnd + 1:]
    FunctionTrailingSpecifiers = FunctionTrailingSpecifiers.replace(";", "")
    FunctionTrailingSpecifiers = FunctionTrailingSpecifiers.replace("override", "")
    FunctionTrailingSpecifiers = FunctionTrailingSpecifiers.replace("final", "")
    FunctionTrailingSpecifiers = FunctionTrailingSpecifiers.rstrip()

    # Extract function arguments from selected line
    FunctionArgs = SourceCodeLine(DeclarationLine[FunctionArgStart + 1:FunctionArgEnd], LineNum, FunctionArgStart + 1)

    FunctionArgs.Split(",")
    # Remove any parts that doesn't have FunctionArg in them
    # Consider example
    # Initial args "FVector a = (4.f, 2.f), int b = 42"
    # Parts after FilteredArgs.Split(","):
    #   1. FVector a = (4.f
    #   2. 2.f)
    #   3. int b = 42
    # Now we need to remove all parts that doesn't have FunctionArg in them, in our example part No. 2
    FunctionArgs.FilterParts("FunctionArg")

    # Now we should have following parts:
    # 1. FVector a = (4.f
    # 2. int b = 42
    #
    # And we want to build a string like "FVector a, int b"
    # Essentially we to split each part by "=" take first part and remove any redundant spaces to the right
    # Resulting list must be ["FVector a", "int b"]
    FunctionArgs = [str(Part).split("=")[0].rstrip() for Part in FunctionArgs]

    Delimiter = ','
    FunctionArgs = Delimiter.join(FunctionArgs)

    ScopeName = N10X.Editor.GetCurrentScopeName() + "::" if N10X.Editor.GetCurrentScopeName() else ""

    return ReturnType + ScopeName + FunctionName + "(" + FunctionArgs + ")" + FunctionTrailingSpecifiers


# Returns line number (starts counting from 0) and actual string where line is found
# So the real line number is return + 1
# But you want to do any API calls to 10x you need line number that starts counting from zero (returned one)
# So if you want a real line number you need to +1
def _FindLineNumber(LineToFind: str, Text: str):
    i = 0
    for Line in Text.splitlines():
        if LineToFind in Line:
            return i, Line
        i = i + 1

    return -1, None


def _Define(bToggleSourceHeader: bool):
    if not _IsCurrentLineFunctionDeclaration():
        print("You haven't selected function declaration, nothing to generate!")
        return

    Signature = _MakeImplementationSignature()
    SourceToPaste = Signature + "\n{\n\n}"

    if bToggleSourceHeader:
        N10X.Editor.ExecuteCommand("CppParser.ToggleSourceHeader")

    PageText: str = N10X.Editor.GetFileText()

    # Check whether function is already defined in the file
    # Remember we could have multiple declarations in the file, so we need to check all of them
    SearchPageTextSlice = PageText
    AccumulatedLineNum = 0
    while True:
        SignatureIndex = SearchPageTextSlice.find(Signature)

        # No more signatures in text
        if SignatureIndex == -1:
            break

        LineNum, Line = _FindLineNumber(Signature, SearchPageTextSlice)
        AccumulatedLineNum += LineNum
        for X in range(0, len(Line)):
            SymType = N10X.Editor.GetSymbolType((X, AccumulatedLineNum))
            if _IsFunctionDefinition(SymType):
                print("Function " + Signature + " already defined")
                N10X.Editor.SetCursorPos((X, AccumulatedLineNum))
                return

        SignatureIndex += len(Line)
        SearchPageTextSlice = SearchPageTextSlice[SignatureIndex:]

    # TODO: Function must be pasted between previous and next function, so order is maintained
    PageText += "\n\n" + SourceToPaste
    N10X.Editor.SetFileText(PageText)

    LineNum, Line = _FindLineNumber(Signature, PageText)
    # Set position to be in the curly brackets, so we can start typing right away
    N10X.Editor.SetCursorPos((4, LineNum + 2))


def Define():
    FileName = N10X.Editor.GetCurrentFilename()
    Extension = FileName.split('.')[-1]

    # If we happen to call define when we are in "Source" file we defenetily want it to be defined in current file, so no Toggle Source/Header
    if Extension in ["cpp", "cxx", "c"]:
        _Define(False)
    else:
        _Define(True)


def DefineInCurrentFile():
    _Define(False)
