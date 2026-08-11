# ZigLSP.py - Zig language support for 10x (10xeditor.com)
#
# A thin configuration layer on top of the generic LSPClient module (same
# folder). It points the generic Language Server Protocol client at zls, the
# Zig Language Server (https://github.com/zigtools/zls), and exposes the
# editor features: completion, hover docs, signature help, go-to-definition,
# find-references and live diagnostics.
#
# ---------------------------------------------------------------------------
# INSTALL
#   1. Copy the LSPClient folder (this file lives alongside LSPClient.py) to:
#          %appdata%\10x\PythonScripts
#   2. Install zls so that "zls" (zls.exe) is on your PATH, or set
#      ZigLSP.Command to its full path. Build instructions:
#          https://github.com/zigtools/zls
#      zls needs to know where the zig compiler is; follow its README to
#      point it at your zls/ install (typically via path).
#   3. Enable it (opt-in). Add to Settings.10x_settings:
#          ZigLSP.Enabled: true
#      then restart 10x. Until you do this the client is completely inert.
#
# SETTINGS (Settings.10x_settings)
#   ZigLSP.Command             Command line used to launch the server.
#                              Default: "zls". Examples:
#                                  ZigLSP.Command: zls
#                                  ZigLSP.Command: C:/tools/zls/zls.exe
#   ZigLSP.Enabled             "true"/"false" - OPT-IN, default false. Set this
#                              to "true" to turn the client on (then restart 10x);
#                              until then it is completely inert.
#   ZigLSP.AutoComplete        "true"/"false" - auto-trigger as you type (default true)
#   ZigLSP.Diagnostics         "true"/"false" - line diagnostic in status bar (default true)
#   ZigLSP.DiagnosticsLevel    lowest severity to show: error|warning|info|hint
#                              e.g. "warning" shows errors+warnings (default "error" = errors only)
#   ZigLSP.MaxResults          max completion items shown, most-relevant first (default 50)
#   ZigLSP.InterceptCommands   "true"/"false" - drive the language server from
#                              10x's built-in GoToSymbolDefinition /
#                              FindSymbolReferences / Autocomplete /
#                              ShowFunctionArgsInfo / ShowSymbolInfo /
#                              ToggleComment / CommentLine / UncommentLine
#                              commands so the editor's default key bindings work
#                              (default true)
#   ZigLSP.Commenting          "true"/"false" - handle ToggleComment /
#                              CommentLine / UncommentLine using "//" (default
#                              true); set false for 10x's built-in commenting
#   ZigLSP.LogVerbose          "true"/"false" - log server traffic (default false)
#
# KEY BINDINGS - with InterceptCommands on (the default), 10x's standard
# bindings for GoToSymbolDefinition, FindSymbolReferences, Autocomplete,
# ShowFunctionArgsInfo, ShowSymbolInfo, ToggleComment, CommentLine and
# UncommentLine already drive the language server (commenting uses "//") in zig
# files; no setup needed. To bind the functions explicitly instead (Settings ->
# Key Bindings):
#   Control Space:       ZigLSP_Completion()
#   F12:                 ZigLSP_GotoDefinition()
#   Control K:           ZigLSP_Hover()
#   Shift F12:           ZigLSP_FindReferences()
#   Control Shift Space: ZigLSP_SignatureHelp()
#   Control Shift /:      ZigLSP_ToggleComment()   (10x default)
#   Control K, Control C: ZigLSP_CommentLine()     (10x default)
#   Control K, Control U: ZigLSP_UncommentLine()   (10x default)
#   (no binding needed)  ZigLSP_ShowDiagnostics()
#   (no binding needed)  ZigLSP_Restart()
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
    name="ZigLSP",
    language_id="zig",
    extensions=(".zig",),
    default_command="zls",
    # "." for member access on structs/enums. zig has no "::"-style path
    # operator, so a single trigger char.
    trigger_chars=".",
    line_comment="//",
    root_markers=("build.zig.zon", """build.zig", "main.zig"),
)


# --- commands to bind to keys ----------------------------------------------

def ZigLSP_Completion():
    _client.complete()


def ZigLSP_Hover():
    _client.hover()


def ZigLSP_SignatureHelp():
    _client.signature_help()


def ZigLSP_GotoDefinition():
    _client.goto_definition()


def ZigLSP_FindReferences():
    _client.find_references()


def ZigLSP_ShowDiagnostics():
    _client.show_all_diagnostics()


def ZigLSP_ToggleComment():
    _client.toggle_comment()


def ZigLSP_CommentLine():
    _client.comment_line()


def ZigLSP_UncommentLine():
    _client.uncomment_line()


def ZigLSP_Restart():
    _client.restart()


def ZigLSP_Status():
    _client.status()


N10X.Editor.CallOnMainThread(_client.register)
