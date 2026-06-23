# RustLSP.py - Rust language support for 10x (10xeditor.com)
#
# A thin configuration layer on top of the generic LSPClient module (same
# folder). It points the generic Language Server Protocol client at
# rust-analyzer (https://rust-analyzer.github.io/) and exposes the editor
# features: completion, hover docs, signature help, go-to-definition,
# find-references and live diagnostics.
#
# ---------------------------------------------------------------------------
# INSTALL
#   1. Copy the LSPClient folder (this file lives alongside LSPClient.py) to:
#          %appdata%\10x\PythonScripts
#   2. Install rust-analyzer so that "rust-analyzer" (rust-analyzer.exe) is on
#      your PATH, or set RustLSP.Command to its full path. Options:
#          rustup component add rust-analyzer
#            (then it lives in ~/.rustup; either add that to PATH or use
#             RustLSP.Command: rustup run stable rust-analyzer)
#          or download a release binary from:
#            https://github.com/rust-lang/rust-analyzer/releases
#   3. Open a Cargo project (a folder containing Cargo.toml). rust-analyzer
#      discovers the workspace and its dependencies from there. Non-Cargo
#      projects need a rust-project.json at the root.
#   4. Enable it (opt-in). Add to Settings.10x_settings:
#          RustLSP.Enabled: true
#      then restart 10x. Until you do this the client is completely inert.
#
# SETTINGS (Settings.10x_settings)
#   RustLSP.Command            Command line used to launch the server.
#                              Default: "rust-analyzer". Examples:
#                                  RustLSP.Command: rust-analyzer
#                                  RustLSP.Command: rustup run stable rust-analyzer
#                                  RustLSP.Command: C:/tools/rust-analyzer.exe
#   RustLSP.Enabled            "true"/"false" - OPT-IN, default false. Set this
#                              to "true" to turn the client on (then restart 10x);
#                              until then it is completely inert.
#   RustLSP.AutoComplete       "true"/"false" - auto-trigger as you type (default true)
#   RustLSP.Diagnostics        "true"/"false" - line diagnostic in status bar (default true)
#   RustLSP.DiagnosticsLevel   lowest severity to show: error|warning|info|hint
#                              e.g. "error" shows errors only (default "hint" = all)
#   RustLSP.MaxResults         max completion items shown, most-relevant first (default 50)
#   RustLSP.InterceptCommands  "true"/"false" - drive the language server from
#                              10x's built-in GoToSymbolDefinition /
#                              FindSymbolReferences / Autocomplete /
#                              ShowFunctionArgsInfo / ShowSymbolInfo commands so
#                              the editor's default key bindings work (default true)
#   RustLSP.LogVerbose         "true"/"false" - log server traffic (default false)
#
# KEY BINDINGS - with InterceptCommands on (the default), 10x's standard
# bindings for GoToSymbolDefinition, FindSymbolReferences, Autocomplete,
# ShowFunctionArgsInfo and ShowSymbolInfo already drive the language server in
# Rust files; no setup needed. To bind the functions explicitly instead
# (Settings -> Key Bindings):
#   Control Space:       RustLSP_Completion()
#   F12:                 RustLSP_GotoDefinition()
#   Control K:           RustLSP_Hover()
#   Shift F12:           RustLSP_FindReferences()
#   Control Shift Space: RustLSP_SignatureHelp()
#   (no binding needed)  RustLSP_ShowDiagnostics()
#   (no binding needed)  RustLSP_Restart()
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
    name="RustLSP",
    language_id="rust",
    extensions=(".rs",),
    default_command="rust-analyzer",
    # "." for fields/methods, ":" for "::" path segments.
    trigger_chars=".:",
    # Prefer the Cargo manifest as the project root so rust-analyzer loads the
    # workspace; rust-project.json covers non-Cargo projects. (".git" is left
    # out so a git submodule's own .git doesn't get picked as the root.)
    root_markers=("Cargo.toml", "rust-project.json"),
    # Skip Cargo's build output in the file-watch scan.
    ignore_dirs=("target",),
)


# --- commands to bind to keys ----------------------------------------------

def RustLSP_Completion():
    _client.complete()


def RustLSP_Hover():
    _client.hover()


def RustLSP_SignatureHelp():
    _client.signature_help()


def RustLSP_GotoDefinition():
    _client.goto_definition()


def RustLSP_FindReferences():
    _client.find_references()


def RustLSP_ShowDiagnostics():
    _client.show_all_diagnostics()


def RustLSP_Restart():
    _client.restart()


def RustLSP_Status():
    _client.status()


N10X.Editor.CallOnMainThread(_client.register)
