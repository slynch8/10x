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

    @staticmethod
    def GetNames():
        names = []

        for type in CompletionType:
            names.append( type.name )

        return names


class CompletionState:

    _prefix = "[UESnippet Completion Active] "

    def __init__(self, insertSingleProperty : bool = False) -> None:
        self._currentText = ""
        self._origPos = ()
        self._currentTab = 1
        self._insertSingleProperty = insertSingleProperty
        self._currentReplacementText = ""


    def SetCurrentReplacmentText(self, rep : str):
        self._currentReplacementText = rep

    def GetCurrentReplacementText(self) -> str:
        return self._currentReplacementText

    def GetIsSingleProperty(self ) -> bool:
        return self._insertSingleProperty

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
            print( f"Replacements: {self.GetReplacements()} INDEX: {index}")
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
                if len(N10X.Editor.GetSelection()):
                    N10X.Editor.ExecuteCommand("Delete")
                rep = self.InsertReplacementText(rep)
                N10X.Editor.SetSelection(pos, (pos[0]+len(rep), pos[1]))
                found = True
                break

        return found

    def InsertReplacementText( self, rep ) -> str:
        self.SetCurrentReplacmentText( rep )
        N10X.Editor.InsertText(rep)
        return rep

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
        parm = self.GetCurrentReplacementParm()
        return parm

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

    def __init__(self, insertSingleProperty : bool = False) -> None:
        super().__init__(insertSingleProperty)
    
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

    def __init__(self, insertSingleProperty : bool = False) -> None:
        super().__init__(insertSingleProperty)
    
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

    def __init__(self, insertSingleProperty : bool = False) -> None:
        super().__init__(insertSingleProperty)

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

    def __init__(self, insertSingleProperty : bool = False) -> None:
        super().__init__(insertSingleProperty)
    
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

    def __init__(self, insertSingleProperty : bool = False) -> None:
        super().__init__(insertSingleProperty)
    
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

    def __init__(self, insertSingleProperty : bool = False) -> None:
        super().__init__(insertSingleProperty)
    
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


class MetaCompletionState(CompletionState):

    _defaultProperty = ""
    _oneParm = "meta = ($1)"
    _replacements = []
    _subReplacements = {}

    def __init__(self) -> None:
        super().__init__()
        self._subReplacement = []

    def GetReplacements(self) -> list:
        if len(self.GetSubReplacement()):
            return self.GetSubReplacement()
        return self._replacements

    def GetCompletionTypeName(self) -> str:
        return ""

    def GetDefault(self) -> str:
        return "";

    def GetOneParm(self) -> str:
        val = N10X.Editor.GetSetting("UE.OneParm_META_UPROPERTY")

        if len(val) == 0:
            return self._oneParm
        return val

    def GetTwoParm(self) -> str:
        return ""

    def RemoveDefault(self)-> bool:
        return False

    def SetSubReplacement( self, reps : list[str] ):
        self._subReplacement = reps

    def GetSubReplacement( self ) -> list[str]:
        return self._subReplacement

    def GetSubReplacements(self) -> dict:
        return {}

    def IncrementReplacementParm(self) -> str:
        print( f"Current Replacement: {self.GetCurrentReplacementText()}")
        curRep = self.GetCurrentReplacementText()

        if curRep in self.GetSubReplacements():
            self.SetSubReplacement( self.GetSubReplacements()[curRep])
            if len(self.GetSubReplacement()) == 0:
                N10X.Editor.ExecuteCommand("Delete")
                print( "END IT")
                _EndCompletionState()
                return ""
        else:
            self.SetSubReplacement( [] )
        return super().IncrementReplacementParm()
        

class UPROPERTYMetaCompletionState(MetaCompletionState):
    
    # These are the current values for UPROPERTY META macros as of Sept 2025 found in ObjectMacros.h
    _replacements = [
                    "ToolTip = \"$2\"",
                    "ShortTooltip = \"$2\"",
                    "DocumentationPolicy",
                    "AllowAbstract = \"$2\"",
                    "AllowAnyActor",
                    "AllowedClasses = \"$2\"",
                    "AllowPreserveRatio",
                    "AllowPrivateAccess",
                    "ArrayClamp = \"$2\"",
                    "AssetBundles",
                    "BlueprintBaseOnly",
                    "BlueprintCompilerGeneratedDefaults",
                    "ClampMin = \"$2\"",
                    "ClampMax = \"$2\"",
                    "ConfigHierarchyEditable",
                    "ContentDir",
                    "Delta",
                    "DeprecatedProperty",
                    "DisallowedAssetDataTags",
                    "DisallowedClasses",
                    "DisplayAfter = \"$2\"",
                    "DisplayName = \"$2\"",
                    "DisplayPriority = \"$2\"",
                    "DisplayThumbnail = \"$2\"",   
                    "EditCondition = \"$2\"",
                    "EditConditionHides",
                    "EditFixedOrder",
                    "ExactClass = \"$2\"",
                    "ExposeFunctionCategories = \"$2\"",
                    "ExposeOnSpawn = \"$2\"",
                    "FilePathFilter = \"$2\"",
                    "RelativeToGameDir",
                    "FixedIncrement",
                    "ForceRebuildProperty",
                    "ForceShowEngineContent",
                    "ForceShowPluginContent",
                    "HideAlphaChannel",
                    "HideInDetailPanel",
                    "HideViewOptions",
                    "IgnoreForMemberInitializationTest",
                    "InlineEditConditionToggle",
                    "LinearDeltaSensitivity",
                    "LongPackageName",
                    "MakeEditWidget",
                    "MakeStructureDefaultValue",
                    "MetaClass",
                    "MustImplement",
                    "ObjectMustImplement",
                    "Multiple",
                    "MaxLength",
                    "MultiLine",
                    "PasswordField",
                    "NoElementDuplicate",
                    "NoResetToDefault",
                    "NoEditInline",
                    "NoSpinbox",
                    "OnlyPlaceable",
                    "RelativePath",
                    "RelativeToGameContentDir",
                    "RequiredAssetDataTags",
                    "ScriptName = \"$2\"",
                    "ScriptNoExport",
                    "ShowOnlyInnerProperties",
                    "ShowTreeView",
                    "SliderExponent",
                    "TitleProperty",
                    "UIMin",
                    "UIMax",
                    "Units",
                    "ForceUnits",
                    "Untracked",
                    "DevelopmentOnly", 
                    "NeedsLatentFixup",
                    "LatentCallbackTarget",
                    "GetOptions",
                    "PinHiddenByDefault",
                    "ValidEnumValues",
                    "InvalidEnumValues",
                    "GetRestrictedEnumValues",
                    "GetAssetFilter",
                    "GetClassFilter",
                    "GetAllowedClasses",
                    "GetDisallowedClasses",
                    "AllowEditInlineCustomization",
                    "NeverAsPin", 
                    "PinShownByDefault", 
                    "AlwaysAsPin", 
                    "CustomizeProperty",
                    "OverridingInputProperty",
                    "RequiredInput"
                    ]
    _replacements.sort()

    _subReplacments =   {
                           "AllowAbstract = \"$2\"" : ["true", "false"],
                           "AllowedClasses = \"$2\"" : [],
                           "ArrayClamp = \"$2\"" : [],
                           "ClampMin = \"$2\"" : [],
                           "ClampMax = \"$2\"" : [],
                           "DisplayAfter = \"$2\"" : [],
                           "DisplayName = \"$2\"" : [],
                           "DisplayPriority = \"$2\"" : [],
                           "DisplayThumbnail = \"$2\"" : ["true", "false"],
                           "EditCondition = \"$2\"" : [],
                           "ExactClass = \"$2\"" : ["true", "false"],
                           "ExposeFunctionCategories = \"$2\"": [],
                           "ExposeOnSpawn = \"$2\"" : ["true", "false"],
                           "FilePathFilter = \"$2\"" : [],  
                           "ScriptName = \"$2\"" : [],
                           "ShortTooltip = \"$2\"" : [],
                           "ToolTip = \"$2\"" : [],
                        }

    def __init__(self) -> None:
        super().__init__()

    def GetSubReplacements(self) -> dict:
        return self._subReplacments

class UCLASSMetaCompletionState(MetaCompletionState):
    
    # These are the current values for UPROPERTY META macros as of Sept 2025 found in ObjectMacros.h
    _replacements = [
                    "ToolTip = \"$2\"",
                    "ShortTooltip = \"$2\"",
                    "DocumentationPolicy",
                    "BlueprintSpawnableComponent",
                    "ChildCanTick",
                    "ChildCannotTick",
                    "DebugTreeLeaf",
                    "IgnoreCategoryKeywordsInSubclasses",
                    "DeprecatedNode",
                    "DeprecationMessage = \"$2\"",
                    "DisplayName = \"$2\"",
                    "ScriptName = \"$2\"",
                    "IsBlueprintBase = \"$2\"",
                    "KismetHideOverrides = \"$2\"",
                    "LoadBehavior",
                    "ProhibitedInterfaces = \"$2\"",
                    "RestrictedToClasses = \"$2\"",
                    "ShowWorldContextPin",
                    "DontUseGenericSpawnObject",
                    "ExposedAsyncProxy",
                    "BlueprintThreadSafe",
                    "UsesHierarchy"
                    ]
    _replacements.sort()

    _subReplacments =   {
                           "DeprecationMessage = \"$2\"" : [],
                           "DisplayName = \"$2\"" : [],
                           "IsBlueprintBase = \"$2\"" : ["true", "false"],
                           "KismetHideOverrides = \"$2\"" : [],
                           "ProhibitedInterfaces = \"$2\"" : [],
                           "RestrictedToClasses = \"$2\"" : [],
                           "ShortTooltip = \"$2\"" : [],
                           "ToolTip = \"$2\"" : [],
                           "ScriptName = \"$2\"" : []
                           
                        }

    def __init__(self) -> None:
        super().__init__()

    def GetSubReplacements(self) -> dict:
        return self._subReplacments

class USTRUCTMetaCompletionState(MetaCompletionState):
    
    # These are the current values for UPROPERTY META macros as of Sept 2025 found in ObjectMacros.h
    _replacements = [
                    "ToolTip = \"$2\"",
                    "ShortTooltip = \"$2\"",
                    "DocumentationPolicy",
                    "HasNativeBreak = \"$2\"",
                    "HasNativeMake = \"$2\"",
                    "HiddenByDefault",
                    "DisableSplitPin"
                    ]
    _replacements.sort()

    _subReplacments =   {
                           
                            "ShortTooltip = \"$2\"" : [],
                            "ToolTip = \"$2\"" : [],
                            "HasNativeBreak = \"$2\"" : [],
                            "HasNativeMake = \"$2\"" : [],
                           
                        }

    def __init__(self) -> None:
        super().__init__()

    def GetSubReplacements(self) -> dict:
        return self._subReplacments

class UFUNCTIONMetaCompletionState(MetaCompletionState):
    
    # These are the current values for UPROPERTY META macros as of Sept 2025 found in ObjectMacros.h
    _replacements = [
                    "ToolTip = \"$2\"",
                    "ShortTooltip = \"$2\"",
                    "DocumentationPolicy",
                    "AdvancedDisplay = \"$2\"",
                    "ArrayParm = \"$2\"",
                    "ArrayTypeDependentParams = \"$2\"",
                    "AutoCreateRefTerm",
                    "HidePinAssetPicker",
                    "BlueprintInternalUseOnly",
                    "BlueprintProtected",
                    "CallableWithoutWorldContext",
                    "CommutativeAssociativeBinaryOperator",
                    "CompactNodeTitle = \"$2\"",
                    "CustomStructureParam = \"$2\"",
                    "DefaultToSelf",
                    "DeprecatedFunction",
                    "ExpandEnumAsExecs = \"$2\"",
                    "ExpandBoolAsExecs",
                    "ScriptName = \"$2\"",
                    "ScriptNoExport", 
                    "ScriptMethod",
                    "ScriptMethodSelfReturn",
                    "ScriptMethodMutable",
                    "ScriptOperator",
                    "ScriptConstant",
                    "ScriptConstantHost",
                    "HidePin = \"$2\"",
                    "HideSpawnParms",
                    "Keywords = \"$2\"",
                    "Latent",
                    "LatentInfo = \"$2\"",
                    "MaterialParameterCollectionFunction",
                    "NativeBreakFunc",
                    "NativeMakeFunc",
                    "UnsafeDuringActorConstruction",
                    "WorldContext = \"$2\"",
                    "BlueprintAutocast",
                    "NotBlueprintThreadSafe",
                    "DeterminesOutputType = \"$2\"",
                    "DynamicOutputParam",
                    "DataTablePin",
                    "SetParam",
                    "MapParam",
                    "MapKeyParam",
                    "MapValueParam",
                    "Bitmask",
                    "BitmaskEnum",
                    "Bitflags",
                    "UseEnumValuesAsMaskValuesInEditor",
                    "AnimBlueprintFunction",
                    "DeprecationMessage = \"$2\"",
                    "DisplayName = \"$2\"",
                    "InternalUseParam = \"$2\"",
                    ]
    _replacements.sort()

    _subReplacments =   {
                           
                            "ShortTooltip = \"$2\"" : [],
                            "ToolTip = \"$2\"" : [],
                            "AdvancedDisplay = \"$2\"" : [],
                            "ArrayParm = \"$2\"" : [],
                            "ArrayTypeDependentParams = \"$2\"" : [],
                            "CompactNodeTitle = \"$2\"" : [],
                            "CustomStructureParam = \"$2\"" : [],
                            "DeprecationMessage = \"$2\"" : [],
                            "DeterminesOutputType = \"$2\"" : [],
                            "DisplayName = \"$2\"" : [],
                            "ExpandEnumAsExecs = \"$2\"" : [],
                            "HidePin = \"$2\"" : [],
                            "InternalUseParam = \"$2\"" : [],
                            "Keywords = \"$2\"" : [],
                            "LatentInfo = \"$2\"" : [],
                            "WorldContext = \"$2\"" : [],
                            "ScriptName = \"$2\"" : []






                                                       
                        }

    def __init__(self) -> None:
        super().__init__()

    def GetSubReplacements(self) -> dict:
        return self._subReplacments
        


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

def _EndCompletionState():
    global g_state
    N10X.Editor.RemoveOnInterceptKeyFunction( _HandleCompletion )
    N10X.Editor.RemoveOnInterceptCharKeyFunction( _HandleKeyStroke )
    
    N10X.Editor.SetCursorPos(N10X.Editor.GetSelectionEnd())
    g_state = CompletionState()
    g_state.SetStatusBarText("Deactivated")
    g_state = None

def _HandleCompletion(key, shift, control, alt):
    #print(f"Key hit: {key} shift: {shift} control: {control} alt: {alt}")

    handled = True
    global g_state

    if key == 'Escape':
        _EndCompletionState()

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

        print(f"Current Completion: {g_state.GetCurrentCompletion()}")
        x = line.find(g_state.GetNextReplacementParm())

        if x != -1:
            g_state.SetOriginalPos((x, pos[1]))
            g_state.SetCurrentCompletion("")
            N10X.Editor.SetSelection((x, pos[1]), (x+2, pos[1]))
            g_state.IncrementReplacementParm()
        else:
            if g_state.GetIsSingleProperty():
                _EndCompletionState()

    return handled


def _InstallCompletionState(completionType : CompletionType = CompletionType.UPROPERTY, single : bool = False ):
    global g_state

    match completionType:
        case CompletionType.UPROPERTY:
            g_state = UPROPERTYCompletionState(single)
        case CompletionType.UFUNCTION:
            g_state = UFUNCTIONCompletionState(single)
        case CompletionType.UCLASS:
            g_state = UCLASSCompletionState(single)
        case CompletionType.UINTERFACE:
            g_state = UINTERFACEfaceCompletionState(single)
        case CompletionType.UDELEGATE:
            g_state = UDELEGATECompletionState(single)
        case CompletionType.USTRUCT:
            g_state = USTRUCTCompletionState(single)

def _InstallMetaCompletionState( completionType : CompletionType = CompletionType.UPROPERTY):
    global g_state

    match completionType:
        case CompletionType.UPROPERTY:
            g_state = UPROPERTYMetaCompletionState()
        case CompletionType.UCLASS:
            g_state = UCLASSMetaCompletionState()
        case CompletionType.USTRUCT:
            g_state = USTRUCTMetaCompletionState()
        case CompletionType.UFUNCTION:
            g_state = UFUNCTIONMetaCompletionState()

def _InstallHook( prop, completionType : CompletionType = CompletionType.UPROPERTY ):
    global g_state

    origPos = N10X.Editor.GetCursorPos()
    line = N10X.Editor.GetLine(origPos[1])

    if not g_state.GetIsSingleProperty():
        g_state.RemoveDefault()
    N10X.Editor.InsertText(prop)

    pos = N10X.Editor.GetCursorPos()
    line = N10X.Editor.GetLine(pos[1])

    if g_state.GetIsSingleProperty():
        g_state.SetOriginalPos(origPos)
        N10X.Editor.SetSelection(origPos, (origPos[0] + len(prop), pos[1]))
    else:
        x = line.find( g_state.GetCurrentReplacementParm())

        g_state.SetOriginalPos((x, pos[1]))
        N10X.Editor.SetSelection((x, pos[1]), (x+2, pos[1]))

    N10X.Editor.AddOnInterceptKeyFunction( _HandleCompletion )
    N10X.Editor.AddOnInterceptCharKeyFunction( _HandleKeyStroke )
    g_state.SetStatusBarText("Active")

def _DetermineMacroScope():
    global g_state

    type = _GetUEMacroScope()
    if type is not None:
        _InstallMetaCompletionState( type )
        _InstallHook(g_state.GetOneParm())

    
def _GetUEMacroScope() -> CompletionType :
    curLine = N10X.Editor.GetLine( N10X.Editor.GetCursorPos()[1])
    prefix = curLine[: curLine.find('(') ]
    prefix = prefix.lstrip().rstrip()

    print(f"prefix {prefix}")
    if prefix in CompletionType.GetNames():
        return CompletionType[prefix]

    return None
    
def _LookForCodeComplete(key, shift, control, alt):
    global g_state
    handled = False
    
    if key == "Space" and control:
        type = _GetUEMacroScope()
        if type is not None:
            _InstallCompletionState( type, True )
            _InstallHook( g_state.GetReplacements()[0], type)
            print( f"Code complete called and inside MACRO {type.name}")
            handled = True

    return handled

def MetaMacroCompletion():
    _DetermineMacroScope()


N10X.Editor.AddOnInterceptKeyFunction( _LookForCodeComplete )
