# RemedyBG debugger integration 

## Usage
Select your active project, Run `RemedyBGStart` command, it will either launch a new RemedyBG session or detect the opened RemedyBG instance on your machine. After that, all your breakpoints in 10x, will be synced with your RemedyBG session. 

## Commands
- **RemedyBGStart**: Detects running RemedyBG instance and starts syncing breakpoints. When you change active debugging session, you should Run this command again, so RemedyBG session will be renewed with new debug commands.
- **RemedyBGStop**: Stops debugging session. It will also close RemedyBG instance and removes all breakpoints
- **RemedyBGRun**: Executes debug

