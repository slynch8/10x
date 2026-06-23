# JaiLSP.py - Jai language support for 10x (10xeditor.com)
#
# A thin configuration layer on top of the generic LSPClient module (same
# folder). It points the generic Language Server Protocol client at jails, the
# Jai Language Server (https://github.com/SogoCZE/jails), and exposes the
# editor features: completion, hover docs, signature help, go-to-definition,
# find-references and live diagnostics.
#
# ---------------------------------------------------------------------------
# INSTALL
#   1. Copy the LSPClient folder (this file lives alongside LSPClient.py) to:
#          %appdata%\10x\PythonScripts
#   2. Install jails so that "jails" (jails.exe) is on your PATH, or set
#      JaiLSP.Command to its full path. Build instructions:
#          https://github.com/SogoCZE/jails
#      jails needs to know where the Jai compiler is; follow its README to
#      point it at your jai/ install (typically via its own config).
#   3. Add a jails.json to your project root so jails knows the build entry
#      point (the file you pass to the compiler). Minimal example:
#          {
#            "buildRoot": "main.jai"
#          }
#      Without it, jails falls back to treating the opened file's folder as the
#      workspace, which gives weaker cross-file results.
#   4. Enable it (opt-in). Add to Settings.10x_settings:
#          JaiLSP.Enabled: true
#      then restart 10x. Until you do this the client is completely inert.
#
# SETTINGS (Settings.10x_settings)
#   JaiLSP.Command             Command line used to launch the server.
#                              Default: "jails". Examples:
#                                  JaiLSP.Command: jails
#                                  JaiLSP.Command: C:/tools/jails/jails.exe
#   JaiLSP.Enabled             "true"/"false" - OPT-IN, default false. Set this
#                              to "true" to turn the client on (then restart 10x);
#                              until then it is completely inert.
#   JaiLSP.AutoComplete        "true"/"false" - auto-trigger as you type (default true)
#   JaiLSP.Diagnostics         "true"/"false" - line diagnostic in status bar (default true)
#   JaiLSP.DiagnosticsLevel    lowest severity to show: error|warning|info|hint
#                              e.g. "error" shows errors only (default "hint" = all)
#   JaiLSP.MaxResults          max completion items shown, most-relevant first (default 50)
#   JaiLSP.InterceptCommands   "true"/"false" - drive the language server from
#                              10x's built-in GoToSymbolDefinition /
#                              FindSymbolReferences / Autocomplete /
#                              ShowFunctionArgsInfo / ShowSymbolInfo commands so
#                              the editor's default key bindings work (default true)
#   JaiLSP.LogVerbose          "true"/"false" - log server traffic (default false)
#
# KEY BINDINGS - with InterceptCommands on (the default), 10x's standard
# bindings for GoToSymbolDefinition, FindSymbolReferences, Autocomplete,
# ShowFunctionArgsInfo and ShowSymbolInfo already drive the language server in
# Jai files; no setup needed. To bind the functions explicitly instead
# (Settings -> Key Bindings):
#   Control Space:       JaiLSP_Completion()
#   F12:                 JaiLSP_GotoDefinition()
#   Control K:           JaiLSP_Hover()
#   Shift F12:           JaiLSP_FindReferences()
#   Control Shift Space: JaiLSP_SignatureHelp()
#   (no binding needed)  JaiLSP_ShowDiagnostics()
#   (no binding needed)  JaiLSP_Restart()
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
    name="JaiLSP",
    language_id="jai",
    extensions=(".jai",),
    default_command="jails",
    # "." for member access on structs/enums. Jai has no "::"-style path
    # operator (constants are "name :: value"), so a single trigger char.
    trigger_chars=".",
    # jails reads the build entry point from jails.json at the project root;
    # prefer that, then fall back to common Jai build files. (".git" is left out
    # so a git submodule's own .git doesn't get picked as the root.)
    root_markers=("jails.json", "first.jai", "build.jai", "main.jai"),
)


# --- commands to bind to keys ----------------------------------------------

def JaiLSP_Completion():
    _client.complete()


def JaiLSP_Hover():
    _client.hover()


def JaiLSP_SignatureHelp():
    _client.signature_help()


def JaiLSP_GotoDefinition():
    _client.goto_definition()


def JaiLSP_FindReferences():
    _client.find_references()


def JaiLSP_ShowDiagnostics():
    _client.show_all_diagnostics()


def JaiLSP_Restart():
    _client.restart()


def JaiLSP_Status():
    _client.status()


N10X.Editor.CallOnMainThread(_client.register)
