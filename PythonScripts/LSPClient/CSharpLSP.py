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
# MEMORY - Roslyn holds syntax trees, compilations and symbols for everything it
# has been told to load, so it is the heaviest server this client drives. Three
# settings bring it down, most effective first:
#   CSharpLSP.Solution         Path to the .sln/.slnx/.csproj to load, absolute
#                              or relative to the project root. USUALLY NOT
#                              NEEDED: if 10x has a .sln/.slnx open as its
#                              workspace, that one is used automatically. Set
#                              this when 10x's workspace is a .10x file or a
#                              folder, to avoid the fallback - which opens the
#                              first solution found at the root, or, if there is
#                              none, EVERY .csproj under it (Roslyn then keeps
#                              them all in memory). Pointing it at one project
#                              graph is the biggest saving there is.
#                                  CSharpLSP.Solution: src/MyApp.sln
#   CSharpLSP.LowMemory        "true"/"false" (default false). Runs the server
#                              with DOTNET_GCConserveMemory=9 and
#                              DOTNET_gcServer=0, trading GC CPU for footprint.
#                              Measured on a 400-file/4800-method project: peak
#                              working set 362 MB -> 183 MB (-49%), with no
#                              measurable change in load time or completion
#                              latency. The GC cost grows with heap size, so a
#                              very large solution may feel it.
#   CSharpLSP.MaxFileSize      KB; files bigger than this are never sent to the
#                              server (no language features for them). Aimed at
#                              huge generated files - .designer.cs and friends.
#   CSharpLSP.ServerEnv        "KEY=VALUE; KEY2=VALUE2" - extra environment for
#                              the server process, applied over LowMemory. E.g.
#                              a hard cap: DOTNET_GCHeapHardLimit=1E000000 (hex
#                              bytes). A hard limit makes the server FAIL rather
#                              than exceed it, so leave headroom.
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
#   (no binding needed)  CSharpLSP_ListFunctions()    (functions in this file)
#   (no binding needed)  CSharpLSP_ListSymbols()      (project-wide symbol search)
#   (no binding needed)  CSharpLSP_RefreshSymbols()   (re-read the project's symbols)
#   Control Shift Space: CSharpLSP_SignatureHelp()
#   Control Shift /:      CSharpLSP_ToggleComment()   (10x default)
#   Control K, Control C: CSharpLSP_CommentLine()     (10x default)
#   Control K, Control U: CSharpLSP_UncommentLine()   (10x default)
#   (no binding needed)  CSharpLSP_ShowDiagnostics()
#   (no binding needed)  CSharpLSP_Restart()
#
# NOTE - CSharpLSP_ListSymbols() searches the project for the selected text (or
# the word under the cursor); type "CSharpLSP symbols <text>" in the command
# panel to search for something else. Roslyn returns nothing for an empty query,
# so it always needs a search term.
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

    # An explicit CSharpLSP.Solution wins over discovery. This is the biggest
    # lever on the server's memory: everything Roslyn loads (syntax trees,
    # compilations, symbols) is held for the whole project graph it is told to
    # open, so pointing it at one .sln/.csproj instead of every project in a
    # large repo is what actually keeps the footprint down.
    configured = client.setting("Solution").strip()
    if configured:
        path = configured if os.path.isabs(configured) else \
            os.path.join(root, configured)
        if not os.path.isfile(path):
            client.log(f"CSharpLSP.Solution '{configured}' not found "
                       f"(looked at {path}); falling back to discovery")
        elif path.lower().endswith((".sln", ".slnx")):
            client.conn.notify("solution/open", {"solution": path_to_uri(path)})
            client.log("opened solution " + os.path.basename(path) +
                       " (CSharpLSP.Solution)")
            return
        else:
            client.conn.notify("project/open",
                               {"projects": [path_to_uri(path)]})
            client.log("opened project " + os.path.basename(path) +
                       " (CSharpLSP.Solution)")
            return

    # No explicit setting - if 10x itself has a solution open, that IS the answer:
    # it's the one the user chose, it may live outside the detected project root,
    # and it saves loading anything else. GetWorkspaceFilename also returns 10x's
    # own workspace format (e.g. "G:/Projects/10x/10x.10x"), which Roslyn can't
    # read, so only take it when it really is a solution.
    workspace = ""
    try:
        workspace = N10X.Editor.GetWorkspaceFilename() or ""
    except Exception as e:
        client.log(f"could not read the 10x workspace filename ({e})")
    if workspace.lower().endswith((".sln", ".slnx")) and os.path.isfile(workspace):
        client.conn.notify("solution/open", {"solution": path_to_uri(workspace)})
        client.log("opened solution " + os.path.basename(workspace) +
                   " (10x workspace)")
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
        # A recursive scan in a big repo can hand Roslyn dozens of projects, and
        # it holds them all in memory. Point out the cheaper option.
        if len(projects) > 5:
            client.log(f"  ({len(projects)} projects is a lot to hold in memory - "
                       f"set CSharpLSP.Solution to one .sln/.csproj to load less)")
    else:
        client.log("no .sln/.slnx/.csproj found under " + root +
                   "; open a folder that contains one")


def _roslyn_server_env(client):
    """Environment for the Roslyn server process.

    Roslyn runs on .NET, so its memory is largely a GC policy question. With
    "CSharpLSP.LowMemory: true" we ask the runtime to trade CPU for footprint:

      DOTNET_GCConserveMemory=9  most aggressive setting (0-9); makes the GC
                                 compact and release memory far more eagerly.
      DOTNET_gcServer=0          workstation GC - one heap instead of a
                                 per-core one (this machine has 12 cores).

    Measured on a synthetic 400-file / 4800-method project: peak working set
    fell from 362 MB to 183 MB (-49%) with no measurable cost to load time
    (7.1s both ways) or completion latency (51 ms median both ways). The CPU
    cost of the extra collections grows with heap size, so on a very large
    solution expect to trade some responsiveness for the saving.

    Anything in CSharpLSP.ServerEnv is applied on top of this and wins."""
    if client.setting("LowMemory", "false").strip().lower() != "true":
        return {}
    return {"DOTNET_GCConserveMemory": "9", "DOTNET_gcServer": "0"}


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
    # Roslyn is a .NET process, so its footprint is mostly GC policy - see
    # _roslyn_server_env for what "CSharpLSP.LowMemory: true" actually sets.
    server_env=_roslyn_server_env,
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


def CSharpLSP_ListSymbols():
    _client.list_symbols()


def CSharpLSP_ListFunctions():
    _client.list_functions()


def CSharpLSP_RefreshSymbols():
    _client.refresh_symbols()


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
