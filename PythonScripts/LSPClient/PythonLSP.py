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
#   3. Install a linter so you get DIAGNOSTICS (errors/warnings). A bare
#      "pip install python-lsp-server" ships only jedi, so completion, hover
#      and go-to-definition work but no diagnostics are ever produced. Add at
#      least pyflakes (genuine errors) - pycodestyle adds style warnings:
#          pip install pyflakes pycodestyle
#      or pull in every pylsp plugin at once:
#          pip install "python-lsp-server[all]"
#      Install into the SAME Python that runs pylsp; it auto-detects plugins on
#      startup, so restart the server afterwards (PythonLSP_Restart()).
#      (pyright bundles its own type checker, so this step is pylsp-specific.)
#   4. Enable it (opt-in). Add to Settings.10x_settings:
#          PythonLSP.Enabled: true
#      then restart 10x. Until you do this the client is completely inert.
#
# SETTINGS (Settings.10x_settings)
#   PythonLSP.Command          Command line used to launch the server.
#                              Default: "pylsp", falling back to
#                              "<python> -m pylsp" if pylsp is not on PATH.
#                              Examples:
#                                  PythonLSP.Command: pylsp
#                                  PythonLSP.Command: pyright-langserver --stdio
#   PythonLSP.Enabled          "true"/"false" - OPT-IN, default false. Set this
#                              to "true" to turn the client on (then restart 10x);
#                              until then it is completely inert.
#   PythonLSP.AutoComplete     "true"/"false" - auto-trigger as you type (default true)
#   PythonLSP.Diagnostics      "true"/"false" - line diagnostic in status bar (default true)
#   PythonLSP.DiagnosticsLevel lowest severity to show: error|warning|info|hint
#                              e.g. "warning" shows errors+warnings (default "error" = errors only)
#   PythonLSP.InterceptCommands "true"/"false" - drive the language server from
#                              10x's built-in GoToSymbolDefinition /
#                              FindSymbolReferences / Autocomplete /
#                              ShowFunctionArgsInfo / ShowSymbolInfo /
#                              ToggleComment / CommentLine / UncommentLine
#                              commands so the editor's default key bindings work
#                              (default true)
#   PythonLSP.Commenting       "true"/"false" - handle ToggleComment /
#                              CommentLine / UncommentLine using "#" (default
#                              true); set false for 10x's built-in commenting
#   PythonLSP.LogVerbose       "true"/"false" - log server traffic (default false)
#
# KEY BINDINGS - with InterceptCommands on (the default), 10x's standard
# bindings for GoToSymbolDefinition, FindSymbolReferences, Autocomplete,
# ShowFunctionArgsInfo, ShowSymbolInfo, ToggleComment, CommentLine and
# UncommentLine already drive the language server (commenting uses "#") in Python
# files; no setup needed. To bind the functions explicitly instead (Settings ->
# Key Bindings):
#   Control Space:       PythonLSP_Completion()
#   F12:                 PythonLSP_GotoDefinition()
#   Control K:           PythonLSP_Hover()
#   Shift F12:           PythonLSP_FindReferences()
#   Control Shift Space: PythonLSP_SignatureHelp()
#   Control Shift /:      PythonLSP_ToggleComment()   (10x default)
#   Control K, Control C: PythonLSP_CommentLine()     (10x default)
#   Control K, Control U: PythonLSP_UncommentLine()   (10x default)
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
    trigger_chars=".",
    line_comment="#",
    # Skip virtualenvs and tool caches in the file-watch scan.
    ignore_dirs=("__pycache__", ".venv", "venv", "env", "__pypackages__",
                 ".mypy_cache", ".pytest_cache", ".ruff_cache",
                 ".tox", ".nox", ".eggs"),
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


def PythonLSP_ToggleComment():
    _client.toggle_comment()


def PythonLSP_CommentLine():
    _client.comment_line()


def PythonLSP_UncommentLine():
    _client.uncomment_line()


def PythonLSP_Restart():
    _client.restart()


def PythonLSP_Status():
    _client.status()


N10X.Editor.CallOnMainThread(_client.register)
