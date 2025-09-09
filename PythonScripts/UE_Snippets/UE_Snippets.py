import N10X
import time
import os

global g_state

class CompletionState:
    _defaultProperty = "UPROPERTY(VisibleDefaultsOnly, BlueprintReadOnly, Category = \"\")"
    _oneParm = "UPROPERTY($1, BlueprintReadOnly, Category = \"\")"
    _twoParm = "UPROPERTY($1, $2, Category = \"\")"

    # These are the current values as of Sept 2025 found in ObjectMacros.h
    _replacements = ["Const", 
                    "Config",
                    "GlobalConfig",
                    "Localized",
                    "Transient",
                    "DuplicateTransient",
                    "NonPIETransient",
                    "NonPIEDuplicateTransient",
                    "Ref",
                    "Export",
                    "NoClear",
                    "EditFixedSize",
                    "Replicated",
                    "ReplicatedUsing",
                    "NotReplicated",
                    "Interp",
                    "NonTransactional",
                    "Instanced",
                    "BlueprintAssignable",
                    "Category",
                    "SimpleDisplay",
                    "AdvancedDisplay",
                    "EditAnywhere",
                    "EditInstanceOnly",
                    "EditDefaultsOnly",
                    "VisibleAnywhere",
                    "VisibleInstanceOnly",
                    "VisibleDefaultsOnly",
                    "BlueprintReadOnly",
                    "BlueprintGetter",
                    "BlueprintReadWrite",
                    "BlueprintSetter",
                    "AssetRegistrySearchable",
                    "SaveGame",
                    "BlueprintCallable",
                    "BlueprintAuthorityOnly",
                    "TextExportTransient",
                    "SkipSerialization",
                    "HideSelfPin", 
                    "FieldNotify" ]
    _replacements.sort()
    _prefix = "[UEProperty Completion Active] "

    def __init__(self) -> None:
        self._currentText = ""
        self._origPos = ()
        self._currentTab = 1

    def GetCurrentCompletion(self) -> str:
        return self._currentText

    def SetCurrentCompletion(self, comp : str):
        self._currentText = comp

    def GetOriginalPos(self) -> tuple:
        return self._origPos

    def SetOriginalPos(self, pos : tuple):
        self._origPos = pos

    def GetMatchIndex(self, match : str) -> int:
        index : int = -1
        try:
            index = CompletionState._replacements.index(match)
        except(ValueError):
            pass
        return index

    def GetMatchByIndex(self, index : int ) -> str:
        result : str = N10X.Editor.GetSelection()
        try:
            result = CompletionState._replacements[index]
        except(IndexError):
            pass
        return result

    @staticmethod
    def SetStatusBarText(text):
        N10X.Editor.SetStatusBarText( CompletionState._prefix + text)

    # def SetStatusBarText(self, text):
    #     CompletionState.SetN10XStatusBarText(text)

    def FindReplacement(self, curText):
        found = False
        pos = self.GetOriginalPos()

        for rep in CompletionState._replacements:
            if rep.startswith(curText):
                N10X.Editor.ExecuteCommand("Delete")
                N10X.Editor.InsertText(rep)
                N10X.Editor.SetSelection(pos, (pos[0]+len(rep), pos[1]))
                found = True
                break

        return found

    def SetCurrentTabNum(self, num : int ):
        self._currentTab = num;

    def GetCurrentTabNum(self) -> int:
        return self._currentTab

    def GetCurrentReplacementParm(self) -> str:
        return "$" + str(self.GetCurrentTabNum())

    def GetNextReplacementParm(self) -> str:
        return "$" + str(self.GetCurrentTabNum() + 1)

    def IncrementReplacementParm(self) -> str:
        self._currentTab = self._currentTab + 1
        return self.GetCurrentReplacementParm()

    @staticmethod
    def GetDefaultProperty() -> str:
        val = N10X.Editor.GetSetting("UE.Default_UPROPERTY")

        if len(val) == 0:
            return CompletionState._defaultProperty
        return val;

    @staticmethod
    def GetOneParmProperty() -> str:
        val = N10X.Editor.GetSetting("UE.OneParm_UPROPERTY")

        if len(val) == 0:
            return CompletionState._oneParm
        return val

    @staticmethod
    def GetTwoParmProperty() -> str:
        val = N10X.Editor.GetSetting("UE.TwoParm_UPROPERTY")

        if len(val) == 0:
            return CompletionState._twoParm
        return val

    @staticmethod
    def RemoveDefaultUPROPERTY()-> bool:
        found = False
        pos = N10X.Editor.GetCursorPos()
        line = N10X.Editor.GetLine(pos[1])

        prop = CompletionState.GetDefaultProperty()

        if line.lstrip().rstrip() == prop:
            x = line.find("UPROPERTY")
            N10X.Editor.SetSelection((x, pos[1]), (x+len(prop), pos[1]))
            N10X.Editor.ExecuteCommand("Delete")
            found = True

        return found


def _HandleKeyStroke( key ):
    global g_state

    if key != "Backspace":
        g_state.SetCurrentCompletion( g_state.GetCurrentCompletion() + key)

    found = g_state.FindReplacement( g_state.GetCurrentCompletion() )
    
    if not found:
        # Let's see if there is a replacement with the currently selected text PLUS the new key.
        # This allows you to type 'Rep' to match Replicated and then 'U' to match ReplicatedUsing
        curSelect = N10X.Editor.GetSelection()

        if g_state.FindReplacement( curSelect + key):
            g_state.SetCurrentCompletion( curSelect + key)

    g_state.SetStatusBarText( g_state.GetCurrentCompletion() )

    return True

def _HandleCompletion(key, shift, control, alt):
    #print(f"Key hit: {key} shift: {shift} control: {control} alt: {alt}")

    handled = True
    global g_state

    if key == 'Escape':
        N10X.Editor.RemoveOnInterceptKeyFunction( _HandleCompletion )
        N10X.Editor.RemoveOnInterceptCharKeyFunction( _HandleKeyStroke )
        
        N10X.Editor.SetCursorPos( g_state.GetOriginalPos())
        g_state = CompletionState()
        handled = False
        g_state.SetStatusBarText("Deactivated")

    elif key == "Backspace":
        curRepl = g_state.GetCurrentReplacementParm()
        if g_state.GetCurrentCompletion() == curRepl:
            return True

        g_state.SetCurrentCompletion( g_state.GetCurrentCompletion()[:-1])
        
        if len(g_state.GetCurrentCompletion()) == 0:
            pos = g_state.GetOriginalPos()
            N10X.Editor.ExecuteCommand("Delete")
            N10X.Editor.InsertText(curRepl)
            N10X.Editor.SetSelection(pos, (pos[0]+len(curRepl), pos[1]))
        else:
            _HandleKeyStroke( key )

        g_state.SetStatusBarText( g_state.GetCurrentCompletion() )
        handled = True

    elif key == "Down" or key == "Up":
        curText = N10X.Editor.GetSelection()
        index = g_state.GetMatchIndex(curText)

        if index != -1:
            inc = 1 if key == "Down" else -1
            match = g_state.GetMatchByIndex(index+inc)
            g_state.FindReplacement( match )

        handled = True
        g_state.SetStatusBarText( g_state.GetCurrentCompletion() )
    elif key == "Tab":
        handled = True
        pos = N10X.Editor.GetCursorPos()
        line = N10X.Editor.GetLine(pos[1])

        x = line.find(g_state.GetNextReplacementParm())

        if x != -1:
            g_state.SetOriginalPos((x, pos[1]))
            g_state.SetCurrentCompletion("")
            N10X.Editor.SetSelection((x, pos[1]), (x+2, pos[1]))
            g_state.IncrementReplacementParm()

    return handled

def _InstallHook( prop ):
    global g_state
    g_state = CompletionState()

    pos = N10X.Editor.GetCursorPos()
    line = N10X.Editor.GetLine(pos[1])

    CompletionState.RemoveDefaultUPROPERTY()
    N10X.Editor.InsertText(prop)

    pos = N10X.Editor.GetCursorPos()
    line = N10X.Editor.GetLine(pos[1])
    x = line.find( g_state.GetCurrentReplacementParm())

    g_state.SetOriginalPos((x, pos[1]))
    N10X.Editor.SetSelection((x, pos[1]), (x+2, pos[1]))
    N10X.Editor.AddOnInterceptKeyFunction( _HandleCompletion )
    N10X.Editor.AddOnInterceptCharKeyFunction( _HandleKeyStroke )
    g_state.SetStatusBarText("Active")


def InsertUPROPERTY_OneParm():
    """
    Call this script to insert a default UPROPERTY at the cursor location that 
    has a $1 parameter as the first parameter to the macro. This allows you to use
    case sensitive completion to select a value property value. You can also use up and
    down arrows to explore valid completions.

    Hit the ESCAPE key to end UPROPERTY selection mode.

    Use the UE.OneParm_UPROPERTY setting to establish the default in the 10X
    settings file. If UE.DefaultProperty is not found, a default is inserted
    """
    _InstallHook(CompletionState.GetOneParmProperty())

def InsertUPROPERTY_TwoParm():
    """
    Call this script to insert a default UPROPERTY at the cursor location that 
    has a $1 parameter as the first parameter, and a $2 in the second parameter
    to the macro. 

    This allows you to use case sensitive completion to select a value property 
    value. You can also use up and down arrows to explore valid completions. 

    Use Tab to jump from the $1 value to the $2 value.
    
    Hit the ESCAPE key to end UPROPERTY selection mode.

    Use the UE.OneParm_UPROPERTY setting to establish the default in the 10X
    settings file. If UE.DefaultProperty is not found, a default is inserted
    """
    _InstallHook(CompletionState.GetTwoParmProperty())    
    
def InsertDefaultUPROPERTY():
    """
    Call this script to insert a default UPROPERTY at the cursor location.
    Use the UE.DefaultProperty setting to establish the default in the 10X
    settings file. If UE.DefaultProperty is not found, a default is inserted
    """
    N10X.Editor.InsertText(CompletionState.GetDefaultProperty())