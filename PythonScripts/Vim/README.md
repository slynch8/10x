# Vim Script

The vim script provides the most common vim functionality for 10x but note that it is not a complete implementation.
This script is still in development but is also very usable.
We welcome pull requests for fixes and features and discussion can be found in the Vim channel of the 10x Discord.

Vim modes supported:
- Command
- Insert
- Visual
- Visual Line/Block
- Commandline 
 

## Vim Settings

Vim specific settings that can be added to 10x settings

|Setting                        |Value        |Description|
|:---                           |:---         |:---       |
Vim                             |bool         |Enables vim script
VimExitInsertModeCharSequence   |2 or 3 chars |Char sequence to exit insert mode, e.g. `jk `
VimUse10xCommandPanel           |bool         |Use 10x command panel for commandline mode, i.e. when typing `:`
VimUse10xFindPanel              |bool         |Use 10x find panel for searching, i.e. when typing `/`
VimSneakEnabled                 |bool         |Enable vim-sneak motion with `s` and `S`

## Customizing vim 

**Due to the way 10x updates python scripts it will not update Vim.py if you have local edits, because of this we recommend that you try to customize vim in the following way.**

The vim script provides some level of key binding customization without modifying the core script (Vim.py) with the help of VimUser.py.
VimUser.py is rarely edited by maintainers and is designed to have local modifications, allowing the core script to be updated without conflicts.
Inside VimUser.py there are multiple handlers with example code showing you how to use these functions.


