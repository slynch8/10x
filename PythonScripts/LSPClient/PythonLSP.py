# PythonLSP.py - Python language support for 10x (10xeditor.com)
#
# A thin configuration layer on top of the generic LSPClient module (same
# folder). It points the generic Language Server Protocol client at a Python
# language server (default: python-lsp-server / "pylsp") and exposes the editor
# features: completion, hover docs, signature help, go-to-definition,
# find-references and live diagnostics.
#
# ---------------------------------------------------------------------------
# INSTALL
#   1. Copy the LSPClient folder (this file lives alongside LSPClient.py) to:
#          %appdata%\10x\PythonScripts
#   2. Install a Python language server, e.g.:
#          pip install python-lsp-server
#      (or:  pip install pyright   and set PythonLSP.Command - see below)
#
# SETTINGS (Settings.10x_settings)
#   PythonLSP.Command          Command line used to launch the server.
#                              Default: "pylsp", falling back to
#                              "<python> -m pylsp" if pylsp is not on PATH.
#                              Examples:
#                                  PythonLSP.Command: pylsp
#                                  PythonLSP.Command: pyright-langserver --stdio
#   PythonLSP.Enabled          "true"/"false" (default true)
#   PythonLSP.AutoComplete     "true"/"false" - auto-trigger as you type (default false)
#   PythonLSP.Diagnostics      "true"/"false" - line diagnostic in status bar (default true)
#   PythonLSP.LogVerbose       "true"/"false" - log server traffic (default false)
#
# KEY BINDINGS (Settings -> Key Bindings) - bind the functions you want:
#   Control Space:       PythonLSP_Completion()
#   F12:                 PythonLSP_GotoDefinition()
#   Control K:           PythonLSP_Hover()
#   Shift F12:           PythonLSP_FindReferences()
#   Control Shift Space: PythonLSP_SignatureHelp()
#   (no binding needed)  PythonLSP_ShowDiagnostics()
#   (no binding needed)  PythonLSP_Restart()
# ---------------------------------------------------------------------------

import os
import sys

import N10X

try:
    from LSPClient import LanguageServerClient
except ImportError:
    # 10x normally puts every PythonScripts subfolder on sys.path, so the bare
    # import above works. If it didn't, add this file's own folder (which also
    # contains LSPClient.py) to sys.path and retry.
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        if _here not in sys.path:
            sys.path.append(_here)
    except NameError:
        pass
    from LSPClient import LanguageServerClient


_client = LanguageServerClient(
    name="PythonLSP",
    language_id="python",
    extensions=(".py", ".pyi", ".pyw"),
    default_command="pylsp",
    fallback_argv=[sys.executable, "-m", "pylsp"],
    trigger_chars=".",
)


# --- commands to bind to keys ----------------------------------------------

def PythonLSP_Completion():
    _client.complete()


def PythonLSP_Hover():
    _client.hover()


def PythonLSP_SignatureHelp():
    _client.signature_help()


def PythonLSP_GotoDefinition():
    _client.goto_definition()


def PythonLSP_FindReferences():
    _client.find_references()


def PythonLSP_ShowDiagnostics():
    _client.show_all_diagnostics()


def PythonLSP_Restart():
    _client.restart()


def PythonLSP_Status():
    _client.status()


N10X.Editor.CallOnMainThread(_client.register)
