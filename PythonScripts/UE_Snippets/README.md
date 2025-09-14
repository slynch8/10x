
# Unreal Engine MACRO Snippets
This script provides code completion support for Unreal Engine Macros. This include UPROPERTY, UFUNCTION, UCLASS, UINTERFACE, UDELEGATE, and USTRUCT. Simply use 10x auto completion to insert one of the macros, then place your cursor inside the parens and hit CONTROL+Space. Do that for as many parameters as you would like for that Macro type.

While inside one of these macros, you can also hook the MetaMacroCompletion() command to a hotkey in order to insert `meta = ()` syntax that is also aware of valid meta tags associated with the outer macro type. 