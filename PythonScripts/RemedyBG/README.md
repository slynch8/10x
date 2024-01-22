
# RemedyBG debugger integration
RemedyBG: https://remedybg.handmade.network/  

Note that this script only works with RemedyBG version 0.3.8 and above. Some features might also be unavailable for the early versions. It is recommended to get the latest version of RemedyBG.

## Features

- Replaces visual-studio debugger integration with RemedyBG
- Supports RemedyBG session files. Saving a session file while debugger is open will bind the session file to your specific Config/Platform and preserves all extra debugger session data on the next runs
- Two way breakpoint syncing between RemedyBG / 10x
- Cursor position syncing in 10x when execution suspends
- Resolves breakpoints on the RemedyBG side, so invalid or unreachable breakpoints will be cleaned out from the editor
- Can execute custom 10x commands when debugging target is started or stopped
- StepInto/StepOut/StepOver/RunToCursor commands 
- Can divert all debugger output text into 10x output window
- AddSelectionToWatch: Adds a selected text in 10x to debugger's watch window
- GotoCursor: RemedyBG will jump to the current cursor in 10x editor

## Installation

- First, Copy the script file (RemedyBG.py) in to `%appdata%\10x\PythonScripts\` directory or just run `RemedyBG_Install.bat` and then restart 10x editor.
- By this time, you should be able to see `RDBG_` family of commands in command panel (CTRL+SHIFT+X).
- Set `RemedyBG.Path` setting to the correct path of your remedybg.exe binary
- Now you can add the setting `RemedyBG.Hook: true` to hook RemedyBG instead of the default visual-studio debugger. So every time you run debugging commands like "Start debugger (F5)" a new RemedyBG session will be opened. If you wish to keep visual-studio debugger integration, you can just assign different shortcuts to `RDBG_StartDebugging`/`RDBG_StopDebugging` and `RDBG_RestartDebugging` commands.

## Additional settings and commands

For more details on additional settings and commands. Please refer to the comments section in the script itself [here](./RemedyBG.py).

# RemedyBG Debugger Updater 
Version: 0.1.0

**Note that you don't need the updater to use the debugger, the steps below are optional**

Requires the following python modules to be installed:
- requests
- BeautifulSoup4
        
To install these modules in 10x's python use the pip command with python3 and set  
the target to be 10x's installation directory:

> python3 -m pip install --target="C:\Program Files\PureDevSoftware\10x\Lib\site-packages"
> requests

> python3 -m pip install --target="C:\Program Files\PureDevSoftware\10x\Lib\site-packages"
> BeautifulSoup4

**You can get the Portal Token from the itch.io download page url for RemedyBG:**  
- in any browser login to itch.io
- navigate to https://remedybg.itch.io/remedybg
- if you havnt purchased RemedyBG, do so now.  Support the dev!
- click the "Download" button
- The PortalToken value will be in the url for the downloads page
    e.g: https://remedybg.itch.io/remedybg/download/{PortalToken}
    
    

**You can get the Itch.io Login Cookie and Token by reading the saved cookies via your browser:**
- in chrome login to itch.io
- press f12 and go to the "application" tab
- under "storage" expand "Cookies"
- use the "itchio" value for RemedyBG_Updater.ItchLoginCookie
- use the "itchio_token" value for RemedyBG_Updater.ItchLoginToken
