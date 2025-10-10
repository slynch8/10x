# LLMHelper - 10x Editor Plugin

A plugin for the [10x Editor](https://10xeditor.com/) that integrates Ollama LLM directly into your workflow. Send selected code or text to your local Ollama instance and get AI responses directly in the editor's output panel.

## Features

- 🤖 **Direct Ollama Integration**: Send selected text to Ollama with a simple keyboard shortcut
- ⚡ **Fast & Local**: Uses your local Ollama instance - no internet required
- 🔧 **Configurable**: Choose any Ollama model via environment variables
- 📝 **Print Output**: Responses appear in the 10x Editor output panel
- 🎯 **Simple API**: Single command to call from key bindings

## Prerequisites

- [10x Editor](https://10xeditor.com/) installed
- [Ollama](https://ollama.ai/) installed and running locally
- At least one Ollama model downloaded (e.g., `ollama pull codellama`)

## Installation

### 1. Set up environment variables

Add these environment variables to your system:

**Windows (PowerShell):**
```powershell
[System.Environment]::SetEnvironmentVariable('10X_LLM_HOST', 'http://localhost:11434', 'User')
[System.Environment]::SetEnvironmentVariable('10X_LLM_MODEL', 'codellama', 'User')
```

**Windows (Command Prompt):**
```powershell
setx 10X_LLM_HOST "http://localhost:11434"
setx 10X_LLM_MODEL "codellama"
```

2. Install the plugin

- Copy LLMHelper.py to your 10x Editor workspace or plugins directory
- Open 10x Editor
- Press Ctrl+F9 to reload Python scripts

You should see initialization messages in the output panel:
```
LLMHelper: ✅ LLM HOST found: 'http://localhost:11434'
LLMHelper: ✅ LLM MODEL selected 'codellama'
```


3. Configure keyboard shortcut

Go to Settings → Key Bindings (or press Ctrl+K)  
Add this line:
```
Control F9: LLMHelperCmd()
```
Save and close

## Usage

Select text in the editor (code, comments, questions, etc.)  
Press your configured shortcut (e.g., Ctrl+Alt+L)  
The selected text is sent to Ollama  
The response appears in the Output Panel  


## Example
Select this code:
```py
def fibonacci(n):
    # TODO: implement
    pass
```

Press Ctrl+Alt+L, and Ollama will generate:
```py
✅ 🤖 Ollama (codellama):
Here's an implementation of the fibonacci function:

def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)
```


## Troubleshooting
"⚠️ LLM HOST not found!"
* Ensure environment variables are set correctly
* Restart 10x Editor after setting environment variables
* Check spelling: 10X_LLM_HOST (case-insensitive)

"⚠️ LLM MODEL not found!"
* Set the 10X_LLM_MODEL environment variable
* Verify the model exists: ollama list

"🛑 connection failed to http://localhost:11434"
* Start Ollama: ollama serve (or ensure Ollama app is running)
* Check if Ollama is listening: curl http://localhost:11434/api/tags

"⚠️ no selection. Select text then retry."
* You need to select text before triggering the command
* Make sure text is highlighted in the editor

"🛑 error retrieving selection"
* The 10x API might have changed
* Check the 10x documentation
* File an issue with details


## Changelog
**v1.0.0**
* Initial release
* Basic Ollama integration
* Environment variable configuration
* Print-only output mode
