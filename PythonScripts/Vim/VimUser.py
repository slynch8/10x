import N10X
from Vim import UserHandledResult, Key

#------------------------------------------------------------------------
# VimUser - Comes with handlers to override default Vim bindings.
# Designed to be edited locally so users can avoid having to merge Vim.py
#------------------------------------------------------------------------

"""
Key handler for command mode
"""
def UserHandleCommandModeKey(key: Key) -> UserHandledResult:

    #
    # Testing/Examples
    #
    do_test = False
    if do_test:
        # Testing - pass ctrl+h back to 10x to open find and replace.
        if key == Key("H", control=True):
            return UserHandledResult.PASS_TO_10X
        
        # Testing - handle ctrl+u and print Hello World
        if key == Key("U", control=True):
            print("Hello World")
            return UserHandledResult.HANDLED

    #
    # Add own keybindings below
    #


    # Default - do nothing
    return UserHandledResult.UNHANDLED

"""
Key handler for insert mode
"""
def UserHandleInsertModeKey(key: Key) -> UserHandledResult:

    #
    # Testing/Examples
    #
    do_test = False
    if do_test:
        # Testing - pass ctrl+z back to 10x to undo
        if key == Key("V", control=True):
            return UserHandledResult.PASS_TO_10X

    #
    # Add own keybindings below
    #

    # Default - do nothing
    return UserHandledResult.UNHANDLED


"""
Command handler for commandline mode, e.g. :q, :w, etc.
"""
def UserHandleCommandline(command) -> UserHandledResult:

    #
    # Testing/Examples
    #
    do_test = False
    if do_test:
        # Testing - print current filename.
        if command == ":filename":
            print(N10X.Editor.GetCurrentFilename())
            return UserHandledResult.HANDLED
        
        # Testing - print Hello World
        if command == ":hello":
            print("Hello World")
            return UserHandledResult.HANDLED

    #
    # Add own commands below
    #


    # Default - do nothing
    return UserHandledResult.UNHANDLED