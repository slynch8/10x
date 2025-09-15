
# Unreal Engine MACRO Snippets
This script provides code completion support for Unreal Engine Macros. This include UPROPERTY, UFUNCTION, UCLASS, UINTERFACE, UDELEGATE, and USTRUCT. Simply use 10x auto completion to insert one of the macros, then place your cursor inside the parens and hit CONTROL+Space. Do that for as many parameters as you would like for that Macro type.

While inside one of these macros, you can also hook the MetaMacroCompletion() command to a hotkey in order to insert `meta = ()` syntax that is also aware of valid meta tags associated with the outer macro type. 

Hit the Escape key to exit the completion state. Most of the time, hitting tab will also end the completion state, unless there is a value associated with a parameter that is looking for code completion. Tab will take you to the $1 replacement parameter.