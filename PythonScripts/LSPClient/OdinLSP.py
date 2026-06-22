# OdinLSP.py - Odin language support for 10x (10xeditor.com)
#
# A thin configuration layer on top of the generic LSPClient module (same
# folder). It points the generic Language Server Protocol client at OLS, the
# Odin Language Server (https://github.com/DanielGavin/ols), and exposes the
# editor features: completion, hover docs, signature help, go-to-definition,
# find-references and live diagnostics.
#
# ---------------------------------------------------------------------------
# INSTALL
#   1. Copy the LSPClient folder (this file lives alongside LSPClient.py) to:
#          %appdata%\10x\PythonScripts
#   2. Install OLS so that "ols" (ols.exe) is on your PATH, or set
#      OdinLSP.Command to its full path. Build instructions:
#          https://github.com/DanielGavin/ols
#   3. (Recommended) Add an ols.json to your project root so OLS can find the
#      Odin core/vendor collections. Minimal example:
#          {
#            "collections": [
#              { "name": "core",   "path": "C:/Odin/core" },
#              { "name": "vendor", "path": "C:/Odin/vendor" }
#            ],
#            "enable_document_symbols": true,
#            "enable_hover": true,
#            "enable_snippets": true
#          }
#
# SETTINGS (Settings.10x_settings)
#   OdinLSP.Command            Command line used to launch the server.
#                              Default: "ols". Examples:
#                                  OdinLSP.Command: ols
#                                  OdinLSP.Command: C:/tools/ols/ols.exe
#   OdinLSP.Enabled            "true"/"false" (default true)
#   OdinLSP.AutoComplete       "true"/"false" - auto-trigger as you type (default true)
#   OdinLSP.Diagnostics        "true"/"false" - line diagnostic in status bar (default true)
#   OdinLSP.DiagnosticsLevel   lowest severity to show: error|warning|info|hint
#                              e.g. "error" shows errors only (default "hint" = all)
#   OdinLSP.InterceptCommands  "true"/"false" - drive the language server from
#                              10x's built-in GoToSymbolDefinition /
#                              FindSymbolReferences / Autocomplete /
#                              ShowFunctionArgsInfo commands so the editor's
#                              default key bindings work (default true)
#   OdinLSP.LogVerbose         "true"/"false" - log server traffic (default false)
#
# KEY BINDINGS - with InterceptCommands on (the default), 10x's standard
# bindings for GoToSymbolDefinition, FindSymbolReferences, Autocomplete and
# ShowFunctionArgsInfo already drive the language server in Odin files; no
# setup needed. To bind the functions explicitly instead (Settings -> Key
# Bindings):
#   Control Space:       OdinLSP_Completion()
#   F12:                 OdinLSP_GotoDefinition()
#   Control K:           OdinLSP_Hover()
#   Shift F12:           OdinLSP_FindReferences()
#   Control Shift Space: OdinLSP_SignatureHelp()
#   (no binding needed)  OdinLSP_ShowDiagnostics()
#   (no binding needed)  OdinLSP_Restart()
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
    name="OdinLSP",
    language_id="odin",
    extensions=(".odin",),
    default_command="ols",
    trigger_chars=".",
    # OLS reads its config from ols.json at the project root; prefer that as the
    # root marker so the right collections/build dir are picked up. (".git" is
    # left out so a git submodule's own .git doesn't get picked as the root.)
    root_markers=("ols.json", "ols.json5"),
)


# --- commands to bind to keys ----------------------------------------------

def OdinLSP_Completion():
    _client.complete()


def OdinLSP_Hover():
    _client.hover()


def OdinLSP_SignatureHelp():
    _client.signature_help()


def OdinLSP_GotoDefinition():
    _client.goto_definition()


def OdinLSP_FindReferences():
    _client.find_references()


def OdinLSP_ShowDiagnostics():
    _client.show_all_diagnostics()


def OdinLSP_Restart():
    _client.restart()


def OdinLSP_Status():
    _client.status()


N10X.Editor.CallOnMainThread(_client.register)
