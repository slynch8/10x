# CSharpLSP.py - C# language support for 10x (10xeditor.com)
#
# A thin configuration layer on top of the generic LSPClient module (same
# folder). It points the generic Language Server Protocol client at the official
# Microsoft C# language server - "Microsoft.CodeAnalysis.LanguageServer", the
# Roslyn-based server that ships inside the VS Code C# Dev Kit - and exposes the
# editor features: completion, hover docs, signature help, go-to-definition,
# find-references and live diagnostics.
#
# Unlike most servers, Roslyn does NOT auto-discover the project on startup: the
# client has to tell it what to load via the custom "solution/open" (or
# "project/open") notification after initialize. This file does that through the
# generic client's on_initialized hook - see _open_roslyn_workspace below.
#
# ---------------------------------------------------------------------------
# INSTALL
#   1. Copy the LSPClient folder (this file lives alongside LSPClient.py) to:
#          %appdata%\10x\PythonScripts
#   2. Install the .NET SDK (https://dotnet.microsoft.com/download). The server
#      is published as a .NET global tool, and "dotnet tool install" needs the
#      SDK; match the tool's target (currently .NET 10), so install the .NET 10
#      SDK. (Installing the SDK also installs the matching runtime.)
#   3. Install the official Roslyn server, published by Microsoft as the
#      "roslyn-language-server" .NET global tool on nuget.org. It is prerelease
#      only for now, hence --prerelease:
#          dotnet tool install --global roslyn-language-server --prerelease
#      This puts roslyn-language-server(.exe) in %USERPROFILE%\.dotnet\tools,
#      which the SDK installer adds to your PATH. (An editor package manager such
#      as Neovim's Mason "roslyn" is another way to obtain the same server.)
#   4. (Optional) The default command is already "roslyn-language-server --stdio",
#      so once the global tool is on your PATH nothing more is needed. Only set
#      CSharpLSP.Command to override it - e.g. when the tool is NOT on PATH:
#          CSharpLSP.Command: C:/Users/<you>/.dotnet/tools/roslyn-language-server.exe --stdio
#      ("--stdio" is required - the client talks to the server over stdio.)
#   5. Open a folder containing a .sln / .slnx (preferred) or a .csproj. The
#      server is told which one to load automatically (see the on_initialized
#      hook); a solution gives the best cross-project results.
#   6. Enable it (opt-in). Add to Settings.10x_settings:
#          CSharpLSP.Enabled: true
#      then restart 10x. Until you do this the client is completely inert.
#   7. Remove ".cs" from 10x's ParserExtensions setting. 10x lists ".cs" there
#      by default, which makes its built-in parser also handle C# files; that
#      competes with the language server (duplicate/incorrect completion and
#      symbol navigation). Edit the ParserExtensions line in Settings.10x_settings
#      to drop ".cs" (leave the other extensions). If you skip this, CSharpLSP
#      logs a WARNING at startup naming the clashing extension.
#
# SETTINGS (Settings.10x_settings)
#   CSharpLSP.Command          Optional override for the server command line.
#                              Not needed with a normal install: the default is
#                              "roslyn-language-server --stdio", which works once
#                              the global tool is on PATH. Set it only to point
#                              at a different path/flags, e.g. when the tool is
#                              not on PATH:
#                                  CSharpLSP.Command: C:/Users/you/.dotnet/tools/roslyn-language-server.exe --stdio
#   CSharpLSP.Enabled          "true"/"false" - OPT-IN, default false. Set this
#                              to "true" to turn the client on (then restart 10x);
#                              until then it is completely inert.
#   CSharpLSP.AutoComplete     "true"/"false" - auto-trigger as you type (default true)
#   CSharpLSP.Diagnostics      "true"/"false" - line diagnostic in status bar (default true)
#   CSharpLSP.DiagnosticsLevel lowest severity to show: error|warning|info|hint
#                              e.g. "warning" shows errors+warnings (default "error" = errors only)
#   CSharpLSP.MaxResults       max completion items shown, most-relevant first (default 50)
#   CSharpLSP.InterceptCommands "true"/"false" - drive the language server from
#                              10x's built-in GoToSymbolDefinition /
#                              FindSymbolReferences / Autocomplete /
#                              ShowFunctionArgsInfo / ShowSymbolInfo /
#                              ToggleComment / CommentLine / UncommentLine
#                              commands so the editor's default key bindings work
#                              (default true)
#   CSharpLSP.Commenting       "true"/"false" - handle ToggleComment /
#                              CommentLine / UncommentLine using "//" (default
#                              true); set false for 10x's built-in commenting
#   CSharpLSP.LogVerbose       "true"/"false" - log server traffic (default false)
#
# KEY BINDINGS - with InterceptCommands on (the default), 10x's standard
# bindings for GoToSymbolDefinition, FindSymbolReferences, Autocomplete,
# ShowFunctionArgsInfo, ShowSymbolInfo, ToggleComment, CommentLine and
# UncommentLine already drive the language server (commenting uses "//") in C#
# files; no setup needed. To bind the functions explicitly instead (Settings ->
# Key Bindings):
#   Control Space:       CSharpLSP_Completion()
#   F12:                 CSharpLSP_GotoDefinition()
#   Control K:           CSharpLSP_Hover()
#   Shift F12:           CSharpLSP_FindReferences()
#   Control Shift Space: CSharpLSP_SignatureHelp()
#   Control Shift /:      CSharpLSP_ToggleComment()   (10x default)
#   Control K, Control C: CSharpLSP_CommentLine()     (10x default)
#   Control K, Control U: CSharpLSP_UncommentLine()   (10x default)
#   (no binding needed)  CSharpLSP_ShowDiagnostics()
#   (no binding needed)  CSharpLSP_Restart()
# ---------------------------------------------------------------------------

import os
import sys
import glob
import hashlib
import tempfile

import N10X

try:
    from LSPClient import LanguageServerClient, path_to_uri
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
    from LSPClient import LanguageServerClient, path_to_uri


def _open_roslyn_workspace(client):
    """Tell the Roslyn server which workspace to load.

    Microsoft.CodeAnalysis.LanguageServer does not open a project on its own -
    it waits for the client's custom "solution/open" / "project/open"
    notification (both are Roslyn extensions, not standard LSP). We prefer a
    solution (.sln/.slnx) so the whole project graph loads; otherwise we hand it
    every .csproj we can find under the project root. Called from the generic
    client's on_initialized hook, so client.root_path and client.conn are ready."""
    root = client.root_path
    if not root or not client.conn:
        return
    solutions = sorted(glob.glob(os.path.join(root, "*.sln")) +
                       glob.glob(os.path.join(root, "*.slnx")))
    if solutions:
        client.conn.notify("solution/open", {"solution": path_to_uri(solutions[0])})
        client.log("opened solution " + os.path.basename(solutions[0]))
        return
    # No solution - collect projects. Look at the root first, then fall back to a
    # recursive scan (a repo can keep its .csproj files a level or two down).
    projects = glob.glob(os.path.join(root, "*.csproj"))
    if not projects:
        projects = glob.glob(os.path.join(root, "**", "*.csproj"), recursive=True)
    if projects:
        client.conn.notify(
            "project/open",
            {"projects": [path_to_uri(p) for p in sorted(projects)]})
        client.log("opened %d project(s)" % len(projects))
    else:
        client.log("no .sln/.slnx/.csproj found under " + root +
                   "; open a folder that contains one")


def _roslyn_working_dir(root):
    """Where to launch the Roslyn server so it stops littering the project root.

    The generic client normally runs the server with cwd = project root. Roslyn
    writes relative scratch directories (notably a literal "{}" folder) into its
    cwd, so with the default that debris lands in the user's source tree. We
    redirect it to a per-project folder under the OS temp dir instead. The
    server still finds the project fine - it is handed absolute paths via the
    initialize rootUri and the solution/open / project/open notifications
    (see _open_roslyn_workspace), not via cwd. Returns None when we have no
    root, which makes the client fall back to its default (the root)."""
    if not root:
        return None
    # Tag the temp dir with a hash of the root so different projects don't share
    # a working dir (and their "{}" scratch can't collide).
    tag = hashlib.sha1(os.path.abspath(root).encode("utf-8")).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(), "10x-CSharpLSP", tag)


_client = LanguageServerClient(
    name="CSharpLSP",
    language_id="csharp",
    # .cs source; .csx scripts and .cake build files share the C# grammar.
    extensions=(".cs", ".csx", ".cake"),
    # The official Roslyn server, installed as the "roslyn-language-server" .NET
    # global tool (dotnet tool install --global roslyn-language-server
    # --prerelease), which the SDK puts on PATH. "--stdio" is required - the
    # transport is JSON-RPC over stdio. Override with the full path via
    # CSharpLSP.Command if the tool is not on PATH.
    default_command="roslyn-language-server --stdio",
    # "." for member access.
    trigger_chars=".",
    line_comment="//",
    # C# project files are variably named, so match them as globs (find_project_root
    # treats a marker containing "*"/"?" as a glob). Prefer the solution so the
    # server loads the whole project graph; fall back to a single project file.
    root_markers=("*.sln", "*.slnx", "*.csproj"),
    # Skip build output and NuGet/tool caches in the file-watch scan.
    ignore_dirs=("bin", "obj", "packages", ".nuget"),
    # Roslyn needs to be told what to open once initialize completes.
    on_initialized=_open_roslyn_workspace,
    # Roslyn writes relative scratch dirs (a "{}" folder) into its cwd; launch
    # it under %TEMP% instead of the project root so it doesn't litter the tree.
    server_cwd=_roslyn_working_dir,
    # Roslyn never PUSHes diagnostics (no textDocument/publishDiagnostics); it
    # only answers PULL requests (textDocument/diagnostic). Opt in so errors and
    # warnings actually show up, the way push-based servers (ols) do by default.
    pull_diagnostics=True,
)


# --- commands to bind to keys ----------------------------------------------

def CSharpLSP_Completion():
    _client.complete()


def CSharpLSP_Hover():
    _client.hover()


def CSharpLSP_SignatureHelp():
    _client.signature_help()


def CSharpLSP_GotoDefinition():
    _client.goto_definition()


def CSharpLSP_FindReferences():
    _client.find_references()


def CSharpLSP_ShowDiagnostics():
    _client.show_all_diagnostics()


def CSharpLSP_ToggleComment():
    _client.toggle_comment()


def CSharpLSP_CommentLine():
    _client.comment_line()


def CSharpLSP_UncommentLine():
    _client.uncomment_line()


def CSharpLSP_Restart():
    _client.restart()


def CSharpLSP_Status():
    _client.status()


N10X.Editor.CallOnMainThread(_client.register)
