import N10X
import time
import os
from enum import Enum

global g_state

class CompletionType(Enum):
    UPROPERTY = 1,
    UFUNCTION = 2,
    UCLASS = 3,
    UINTERFACE = 4,
    UDELEGATE = 5,
    USTRUCT = 6

class CompletionState:

    _prefix = "[UESnippet Completion Active] "

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
            index = self.GetReplacements().index(match)
        except(ValueError):
            pass
        return index

    def GetMatchByIndex(self, index : int ) -> str:
        result = ""
        try:
            result = self.GetReplacements()[index]
        except(IndexError):
            pass
        return result

    @staticmethod
    def SetStatusBarText(text):
        N10X.Editor.SetStatusBarText( CompletionState._prefix + text)

    def GetReplacements(self) -> list:
        return []

    def FindReplacement(self, curText):
        found = False
        pos = self.GetOriginalPos()

        replacements = self.GetReplacements()

        for rep in replacements:
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

    def GetCompletionTypeName(self) -> str:
        return ""

    def GetDefault(self) -> str:
        return ""

    def GetOneParm(self) -> str:
        return ""


    def GetTwoParm(self) -> str:
        return ""


    def RemoveDefault(self)-> bool:
        found = False
        pos = N10X.Editor.GetCursorPos()
        line = N10X.Editor.GetLine(pos[1])

        prop = self.GetDefault()
        
        if line.lstrip().rstrip() == prop:

            x = line.find(self.GetCompletionTypeName())
            N10X.Editor.SetSelection((x, pos[1]), (x+len(prop), pos[1]))
            N10X.Editor.ExecuteCommand("Delete")
            found = True

        return found


class UPROPERTYCompletionState(CompletionState):
    # UPROPERTY support
    # Default UPROPERTY values if no Setting values established. Use UE.Default_UPROPERTY
    # to allow user to set the Default UPROPERTY in the 10x settings file
    _defaultProperty = "UPROPERTY(VisibleDefaultsOnly, BlueprintReadOnly, Category = \"\")"
    _oneUPROPParm = "UPROPERTY($1, BlueprintReadOnly, Category = \"\")"
    _twoUPROPParm = "UPROPERTY($1, $2, Category = \"\")"

    # These are the current values for UPROPERTY macros as of Sept 2025 found in ObjectMacros.h
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

    def __init__(self) -> None:
        super().__init__()
    
    def GetReplacements(self) -> list:
        return self._replacements

    def GetCompletionTypeName(self) -> str:
        return "UPROPERTY"

    def GetDefault(self) -> str:
        val = N10X.Editor.GetSetting("UE.Default_UPROPERTY")

        if len(val) == 0:
            return self._defaultProperty
        return val;

    def GetOneParm(self) -> str:
        val = N10X.Editor.GetSetting("UE.OneParm_UPROPERTY")

        if len(val) == 0:
            return self._oneUPROPParm
        return val

    def GetTwoParm(self) -> str:
        val = N10X.Editor.GetSetting("UE.TwoParm_UPROPERTY")

        if len(val) == 0:
            return self._twoUPROPParm
        return val

class UFUNCTIONCompletionState(CompletionState):
    # UFUNCTION support
    _defaultFunction = "UFUNCTION(BlueprintCallable, Category = \"\")"
    _oneUFUNCParm = "UFUNCTION($1, Category = \"\")"

    _replacements = [
                    "BlueprintImplementableEvent",
                    "BlueprintNativeEvent",
                    "SealedEvent",
                    "Exec",
                    "Server",
                    "Client",
                    "NetMulticast",
                    "Reliable",
                    "Unreliable",
                    "BlueprintPure",
                    "BlueprintCallable",
                    "BlueprintGetter",
                    "BlueprintSetter",
                    "BlueprintAuthorityOnly",
                    "BlueprintCosmetic",
                    "BlueprintInternalUseOnly",
                    "CallInEditor",
                    "CustomThunk",
                    "Category",
                    "FieldNotify",
                    "WithValidation",
                    "ServiceRequest",
                    "ServiceResponse",
                    "Variadic",
                    "ReturnDisplayName", 
                    "InternalUseParam", 
                    "ForceAsFunction", 
                    "IgnoreTypePromotion" ]
    _replacements.sort()

    def __init__(self) -> None:
        super().__init__()
    
    def GetReplacements(self) -> list:
        return self._replacements

    def GetCompletionTypeName(self) -> str:
        return "UFUNCTION"

    def GetDefault(self) -> str:
        val = N10X.Editor.GetSetting("UE.Default_UFUNCTION")

        if len(val) == 0:
            return self._defaultFunction
        return val;

    def GetOneParm(self) -> str:
        val = N10X.Editor.GetSetting("UE.OneParm_UFUNCTION")

        if len(val) == 0:
            return self._oneUFUNCParm
        return val

class UDELEGATECompletionState(UFUNCTIONCompletionState):
    # UDELEGATE support
    _default = "UDELEGATE(BlueprintCallable, Category = \"\")"
    _oneParm = "UDELEGATE($1, Category = \"\")"

    def __init__(self) -> None:
        super().__init__()

    def GetCompletionTypeName(self) -> str:
        return "UDELEGATE"

    def GetDefault(self) -> str:
        val = N10X.Editor.GetSetting("UE.Default_UDELEGATE")

        if len(val) == 0:
            return self._default
        return val;

    def GetOneParm(self) -> str:
        val = N10X.Editor.GetSetting("UE.OneParm_UDELEGATE")

        if len(val) == 0:
            return self._oneParm
        return val

class UCLASSCompletionState(CompletionState):
    # UCLASS support
    _default = "UCLASS(BlueprintType)"
    _oneParm = "UCLASS($1)"

    _replacements = [
                    "classGroup",
                    "Within", 
                    "BlueprintType",
                    "NotBlueprintType",
                    "Blueprintable",
                    "NotBlueprintable",
                    "MinimalAPI",
                    "customConstructor",
                    "CustomFieldNotify",
                    "Intrinsic",
                    "noexport",
                    "placeable",
                    "notplaceable",
                    "DefaultToInstanced",
                    "Const",
                    "Abstract",
                    "deprecated",
                    "Transient",
                    "nonTransient",
                    "Optional",
                    "config",
                    "perObjectConfig",
                    "configdonotcheckdefaults",
                    "defaultconfig",
                    "EditorConfig",
                    "editinlinenew",
                    "noteditinlinenew",
                    "hidedropdown",
                    "showCategories",
                    "hideCategories",
                    "ComponentWrapperClass",
                    "showFunctions",
                    "hideFunctions",
                    "autoExpandCategories",
                    "autoCollapseCategories",
                    "dontAutoCollapseCategories",
                    "collapseCategories",
                    "dontCollapseCategories",
                    "prioritizeCategories",
                    "AdvancedClassDisplay",
                    "ConversionRoot",
                    "Experimental",
                    "EarlyAccessPreview",
                    "SparseClassDataType",
                    "CustomThunkTemplates"
                     ]
    _replacements.sort()

    def __init__(self) -> None:
        super().__init__()
    
    def GetReplacements(self) -> list:
        return self._replacements

    def GetCompletionTypeName(self) -> str:
        return "UCLASS"

    def GetDefault(self) -> str:
        val = N10X.Editor.GetSetting("UE.Default_UCLASS")

        if len(val) == 0:
            return self._default
        return val;

    def GetOneParm(self) -> str:
        val = N10X.Editor.GetSetting("UE.OneParm_UCLASS")

        if len(val) == 0:
            return self._oneParm
        return val

class UINTERFACEfaceCompletionState(CompletionState):
    # UCLASS support
    _default = "UINTERFACE(Blueprintable)"
    _oneParm = "UINTERFACE($1)"

    _replacements = [
                    "MinimalAPI",
                    "Blueprintable",
                    "NotBlueprintable",
                    "ConversionRoot"
                     ]
    _replacements.sort()

    def __init__(self) -> None:
        super().__init__()
    
    def GetReplacements(self) -> list:
        return self._replacements

    def GetCompletionTypeName(self) -> str:
        return "UINTERFACE"

    def GetDefault(self) -> str:
        val = N10X.Editor.GetSetting("UE.Default_UINTERFACE")

        if len(val) == 0:
            return self._default
        return val;

    def GetOneParm(self) -> str:
        val = N10X.Editor.GetSetting("UE.OneParm_UINTERFACE")

        if len(val) == 0:
            return self._oneParm
        return val


class USTRUCTCompletionState(CompletionState):
    # USTRUCT support
    _default = "USTRUCT(BlueprintCallable, Category = \"\")"
    _oneParm = "USTRUCT($1, Category = \"\")"

    _replacements = [
                    "NoExport",
                    "Atomic",
                    "Immutable",
                    "BlueprintType",
                    "BlueprintInternalUseOnly",
                    "BlueprintInternalUseOnlyHierarchical"
                    ]
    _replacements.sort()

    def __init__(self) -> None:
        super().__init__()
    
    def GetReplacements(self) -> list:
        return self._replacements

    def GetCompletionTypeName(self) -> str:
        return "USTRUCT"

    def GetDefault(self) -> str:
        val = N10X.Editor.GetSetting("UE.Default_USTRUCT")

        if len(val) == 0:
            return self._default
        return val;

    def GetOneParm(self) -> str:
        val = N10X.Editor.GetSetting("UE.OneParm_USTRUCT")

        if len(val) == 0:
            return self._oneParm
        return val


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
        else:
            # Allow for scrubbing through values without
            # having to make a first match
            match = g_state.GetMatchByIndex(0)
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


def _InstallCompletionState(completionType : CompletionType = CompletionType.UPROPERTY ):
    global g_state

    match completionType:
        case CompletionType.UPROPERTY:
            g_state = UPROPERTYCompletionState()
        case CompletionType.UFUNCTION:
            g_state = UFUNCTIONCompletionState()
        case CompletionType.UCLASS:
            g_state = UCLASSCompletionState()
        case CompletionType.UINTERFACE:
            g_state = UINTERFACEfaceCompletionState()
        case CompletionType.UDELEGATE:
            g_state = UDELEGATECompletionState()
        case CompletionType.USTRUCT:
            g_state = USTRUCTCompletionState()

def _InstallHook( prop, completionType : CompletionType = CompletionType.UPROPERTY ):
    global g_state

    pos = N10X.Editor.GetCursorPos()
    line = N10X.Editor.GetLine(pos[1])

    g_state.RemoveDefault()
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
    global g_state
    _InstallCompletionState()
    _InstallHook(g_state.GetOneParm())

def InsertUPROPERTY_TwoParm():
    """
    Call this script to insert a default UPROPERTY at the cursor location that 
    has a $1 parameter as the first parameter, and a $2 in the second parameter
    to the macro. 

    This allows you to use case sensitive completion to select a value property 
    value. You can also use up and down arrows to explore valid completions. 

    Use Tab to jump from the $1 value to the $2 value.
    
    Hit the ESCAPE key to end UPROPERTY selection mode.

    Use the UE.TwoParm_UPROPERTY setting to establish the default in the 10X
    settings file. If UE.TwoParm_UPROPERTY is not found, a default is inserted
    """
    global g_state
    _InstallCompletionState()
    _InstallHook(g_state.GetTwoParm())    
    
def InsertDefaultUPROPERTY():
    """
    Call this script to insert a default UPROPERTY at the cursor location.
    Use the UE.DefaultProperty setting to establish the default in the 10X
    settings file. If UE.DefaultProperty is not found, a default is inserted
    """

    global g_state
    _InstallCompletionState()
    N10X.Editor.InsertText(g_state.GetDefault())

def InsertUFUNCTION_OneParm():
    """
    Call this script to insert a default UFUNCTION at the cursor location that 
    has a $1 parameter as the first parameter to the macro. This allows you to use
    case sensitive completion to select a value property value. You can also use up and
    down arrows to explore valid completions.

    Hit the ESCAPE key to end UFUNCTION selection mode.

    Use the UE.OneParm_UFUNCTION setting to establish the default in the 10X
    settings file. If UE.OneParm_UFUNCTION is not found, a default is inserted
    """
    global g_state
    _InstallCompletionState( CompletionType.UFUNCTION )

    _InstallHook(g_state.GetOneParm())

def InsertDefaultUFUNCTION():
    """
    Call this script to insert a default UFUNCTION at the cursor location.
    Use the UE.DefaultFunction setting to establish the default in the 10X
    settings file. If UE.DefaultFunction is not found, a default is inserted
    """
    global g_state
    _InstallCompletionState( CompletionType.UFUNCTION )

    N10X.Editor.InsertText( g_state.GetDefault() )

def InsertUCLASS_OneParm():
    """
    Call this script to insert a default UCLASS at the cursor location that 
    has a $1 parameter as the first parameter to the macro. This allows you to use
    case sensitive completion to select a value property value. You can also use up and
    down arrows to explore valid completions.

    Hit the ESCAPE key to end UCLASS selection mode.

    Use the UE.OneParm_UCLASS setting to establish the default in the 10X
    settings file. If UE.OneParm_UCLASS is not found, a default is inserted
    """
    global g_state
    _InstallCompletionState( CompletionType.UCLASS )

    _InstallHook(g_state.GetOneParm())

def InsertDefaultUCLASS():
    """
    Call this script to insert a default UCLASS at the cursor location.
    Use the UE.DefaultFunction setting to establish the default in the 10X
    settings file. If UE.DefaultClass is not found, a default is inserted
    """
    global g_state
    _InstallCompletionState( CompletionType.UCLASS )

    N10X.Editor.InsertText( g_state.GetDefault() )

def InsertUINTERFACE_OneParm():
    """
    Call this script to insert a default UINTERFACE at the cursor location that 
    has a $1 parameter as the first parameter to the macro. This allows you to use
    case sensitive completion to select a value property value. You can also use up and
    down arrows to explore valid completions.

    Hit the ESCAPE key to end UINTERFACE selection mode.

    Use the UE.OneParm_UINTERFACE setting to establish the default in the 10X
    settings file. If UE.OneParm_UINTERFACE is not found, a default is inserted
    """
    global g_state
    _InstallCompletionState( CompletionType.UINTERFACE )

    _InstallHook(g_state.GetOneParm())

def InsertDefaultUINTERFACE():
    """
    Call this script to insert a default UINTERFACE at the cursor location.
    Use the UE.DefaultFunction setting to establish the default in the 10X
    settings file. If UE.DefaultClass is not found, a default is inserted
    """
    global g_state
    _InstallCompletionState( CompletionType.UINTERFACE )

    N10X.Editor.InsertText( g_state.GetDefault() )

def InsertUDELEGATE_OneParm():
    """
    Call this script to insert a default UDELEGATE at the cursor location that 
    has a $1 parameter as the first parameter to the macro. This allows you to use
    case sensitive completion to select a value property value. You can also use up and
    down arrows to explore valid completions.

    Hit the ESCAPE key to end UDELEGATE selection mode.

    Use the UE.OneParm_UDELEGATE setting to establish the default in the 10X
    settings file. If UE.OneParm_UDELEGATE is not found, a default is inserted
    """
    global g_state
    _InstallCompletionState( CompletionType.UDELEGATE )

    _InstallHook(g_state.GetOneParm())

def InsertDefaultUDELEGATE():
    """
    Call this script to insert a default UDELEGATE at the cursor location.
    Use the UE.DefaultFunction setting to establish the default in the 10X
    settings file. If UE.DefaultClass is not found, a default is inserted
    """
    global g_state
    _InstallCompletionState( CompletionType.UDELEGATE )

    N10X.Editor.InsertText( g_state.GetDefault() )


def InsertUSTRUCT_OneParm():
    """
    Call this script to insert a default USTRUCT at the cursor location that 
    has a $1 parameter as the first parameter to the macro. This allows you to use
    case sensitive completion to select a value property value. You can also use up and
    down arrows to explore valid completions.

    Hit the ESCAPE key to end USTRUCT selection mode.

    Use the UE.OneParm_USTRUCT setting to establish the default in the 10X
    settings file. If UE.OneParm_USTRUCT is not found, a default is inserted
    """
    global g_state
    _InstallCompletionState( CompletionType.USTRUCT )

    _InstallHook(g_state.GetOneParm())

def InsertDefaultUSTRUCT():
    """
    Call this script to insert a default USTRUCT at the cursor location.
    Use the UE.DefaultFunction setting to establish the default in the 10X
    settings file. If UE.DefaultClass is not found, a default is inserted
    """
    global g_state
    _InstallCompletionState( CompletionType.USTRUCT )

    N10X.Editor.InsertText( g_state.GetDefault() )