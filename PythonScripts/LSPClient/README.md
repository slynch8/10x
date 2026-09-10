# LSPClient - Language Server Protocol support for 10x

A generic, reusable [Language Server Protocol](https://microsoft.github.io/language-server-protocol/)
client for the [10x editor](https://www.10xeditor.com). `LSPClient.py` handles
the transport, document sync, diagnostics and editor features; the small
per-language scripts in this folder (`PythonLSP.py`, `RustLSP.py`, `OdinLSP.py`,
`JaiLSP.py`, `CSharpLSP.py`) just point it at a specific language server.

Adding a new language is a few lines - instantiate `LanguageServerClient` with a
command and file extensions and call `.register()`. See any of the existing
per-language scripts for a complete example.

## Installation

1. Copy the whole `LSPClient` folder into `%appdata%\10x\PythonScripts` (the
   per-language scripts must sit alongside `LSPClient.py`).
2. Install the language server you want (see [per-language notes](#per-language-setup) below).
3. Enable the client - it is **opt-in** and completely inert until you do. Add to
   `Settings.10x_settings`:
   ```
   PythonLSP.Enabled: true
   ```
   (use `RustLSP.Enabled`, `OdinLSP.Enabled`, `JaiLSP.Enabled`,
   `CSharpLSP.Enabled` for the others).
4. Restart 10x.

`LSPClient.py` defines classes only - importing it registers no editor hooks and
has no side effects. Only the per-language scripts wire anything up, and only
when their `Enabled` setting is `true`.

> **Note - the `ParserExtensions` setting.** 10x's built-in parser handles a
> configured list of extensions itself (the `ParserExtensions` setting) for its
> own completion/symbol navigation. If one of them is also handled by a language
> server, the two compete (duplicate or wrong completions, symbol jumps hitting
> the parser's index instead of the server's). Remove any extension you want the
> LSP to own from `ParserExtensions`. This bites C# in particular: 10x lists
> `.cs` there by default, so **remove `.cs` when using `CSharpLSP`**. On startup
> a client logs a `WARNING` naming any of its extensions it finds still in
> `ParserExtensions`.

## Features

- **Completion** - manual (keybinding) and auto-trigger as you type (debounced),
  filtered to what you've typed (fuzzy subsequence by default, see
  `FuzzyComplete`) and capped at `MaxResults`.
- **Hover** - documentation for the symbol under the cursor, shown in 10x's
  inline hover box.
- **Signature help ("function args info")** - shown in 10x's function-args box
  (`ShowFunctionArgsListBox`) when you type a call's `(`, and left up until you
  leave the parentheses. One overload per row, the active one last - 10x
  highlights the bottom row, and you pick a different overload with the up/down
  keys, so the list is put up once and left alone after that (it stays where it
  opened rather than following the caret). Moving the cursor back between an
  existing pair of parentheses does *not* bring it back: once dismissed it stays
  dismissed, and `ShowFunctionArgsInfo` (Ctrl+Shift+Space) re-opens it at the
  call's `(`. See the `SignatureHelp` setting.
- **Go to definition** - opens the target file at the definition (with a couple
  of retries for servers that answer `null` until the workspace finishes loading).
- **Find references** - shown in 10x's symbol-references list.
- **List functions** - the functions/methods in the current file
  (`textDocument/documentSymbol`), shown in 10x's find-function panel
  (`ShowFindFunctionPanel`) with the enclosing class in the name, in file order,
  so you can filter and jump straight to one.
- **List symbols** - the project's symbols (`workspace/symbol`) in 10x's
  find-symbol panel (`ShowFindSymbolPanel`). The panel filters the list it is
  handed, so it gets every symbol each time it opens; asking the server on every
  open would be far too slow, so the list is **cached** (see
  `SymbolCacheSeconds`): the cache is filled in the background shortly after the
  server starts, so the first FindSymbol opens on a full project list rather than
  triggering the fetch itself - you should never need to open a file or run
  `RefreshSymbols` to get results. Later opens are served instantly and refresh
  the cache in the background. Saving a file refreshes it too, and
  `<Name> refresh symbols` / `<Name>_RefreshSymbols()` rebuilds it on demand.

  **Where the list comes from** is `SymbolSource`. `workspace/symbol` is one
  request, but it only ever returns what the server's project index holds, and
  servers cap how much of it they return (OLS: 100 results). The
  `documents` source instead asks each file in the project for its own symbols
  (`textDocument/documentSymbol`), which has neither gap. It costs a request per
  file, so the scan is paced across update ticks - a few files at a time, at
  most four requests outstanding, and a cap on how much file text is read per
  tick - and files the scan opened are closed again behind it. Files you have
  open are left alone. Every language defaults to `auto`, which uses
  `workspace/symbol` and falls back to the scan only if that turns out to be
  empty.

  Servers index in the background and answer as soon as they have *something*,
  so early replies are partial or empty. Both cases are handled: an empty reply
  is retried on a backoff (2s, 5s, 12s, 30s) before the client concludes the
  server has no project dump to give, and after a dump lands the client
  re-checks every 10s for as long as the symbol count keeps climbing, stopping
  once it settles. So the list fills itself in over the first few seconds of a
  session rather than staying stuck at whatever the server knew first.

  LSP has no "give me every symbol" request, only a search, and some servers
  (Roslyn) return nothing for an empty query. For those the panel falls back to
  searching for the selected text or the word under the cursor, and
  `<Name> symbols <text>` searches the server directly, bypassing the cache.
  Server support varies - see [per-language setup](#per-language-setup).

  That cache is a copy of every symbol in the project, so on a large one it
  costs real memory and a background refresh every so often. `SymbolCache:
  false` opts out: the cache is dropped, and `FindSymbol` /
  `<Name>_ListSymbols()` / `<Name>_RefreshSymbols()` just say so in the status
  bar. `FindSymbol` stays intercepted rather than falling back to 10x's own
  panel, which has nothing of value to show for a file the server handles. Only
  `<Name> symbols <text>` - a one-shot server query that keeps nothing - still
  works.
- **Diagnostics** - live errors/warnings from the server, surfaced two ways: the
  diagnostic under the cursor in the status bar, and all diagnostics rendered
  into the build-output panel as navigable MSVC-style lines. Filterable by
  severity via `DiagnosticsLevel`.
- **Commenting** - `ToggleComment` / `CommentLine` / `UncommentLine` using the
  language's line-comment token. This is a pure editor-side text edit (LSP has no
  comment API), so it works without a running server. Acts on the current line or
  every line the selection touches, comments at the block's shallowest indent,
  and leaves blank lines untouched.
- **Command interception** - with `InterceptCommands` on (the default), 10x's
  built-in commands drive the language server for files the client handles, so
  the editor's standard key bindings just work. Intercepted commands:
  `GoToSymbolDefinition`, `GoToSymbolDefinitionUnderMouse`, `FindSymbolReferences`,
  `Autocomplete`, `ShowFunctionArgsInfo`, `ShowSymbolInfo`, `FindFunction`,
  `FindSymbol`, and (when a comment token is configured) `ToggleComment` /
  `CommentLine` / `UncommentLine`.
- **Project root** - the language server is rooted at the workspace 10x has
  open (`GetWorkspaceFilename`), which is the project you actually opened. Only
  when there is no workspace, or the file is outside it, does the client fall
  back to walking up from the file looking for a marker (`Cargo.toml`, `*.sln`,
  `ols.json`, ...). That walk stops at the *innermost* marker, so a nested crate
  or `.csproj` would root the server at itself and hide the rest of the project
  from find-symbol - and since the root is fixed when the server starts,
  whichever file you opened first would decide what it could ever see. Opening a
  different workspace restarts the server at the new root. `<Name> status` shows
  which root is in use and where it came from.
- **Watched files** - for servers that ask for it (e.g. OLS), a throttled
  workspace mtime scan notifies the server about files changed on disk while not
  open, keeping its index fresh.

## Settings

All settings are read from `Settings.10x_settings` and prefixed with the client
name, e.g. `PythonLSP.Enabled`, `RustLSP.Command`. Replace `<name>` below with
the client you're configuring (`PythonLSP`, `RustLSP`, `OdinLSP`, `JaiLSP`,
`CSharpLSP`).

| Setting                     | Values                          | Default            | Description |
|-----------------------------|---------------------------------|--------------------|-------------|
| `<name>.Enabled`            | `true` / `false`                | `false`            | Opt-in master switch. The client is completely inert (no server launched, no hooks) until this is `true`. Takes effect on the next 10x restart. |
| `<name>.Command`            | command line                    | *(per language)*   | Command used to launch the server, overriding the built-in default. E.g. `pylsp`, `rustup run stable rust-analyzer`, `C:/tools/ols.exe`. |
| `<name>.AutoComplete`       | `true` / `false`                | `true`             | Auto-trigger completion as you type (after identifiers or trigger chars, debounced). Set `false` to use the keybinding only. |
| `<name>.SignatureHelp`      | `true` / `false`                | `true`             | Open 10x's function-args box when you type a call's `(`. It is never re-opened by the cursor moving back between the parentheses - `ShowFunctionArgsInfo` does that on demand. Set `false` for on demand only. |
| `<name>.InterceptCommands`  | `true` / `false`                | `true`             | Hook 10x's built-in commands so the default key bindings drive the language server for files this client handles. Set `false` to require the per-language `<Name>_*` functions instead. |
| `<name>.Commenting`         | `true` / `false`                | `true`             | Handle `ToggleComment` / `CommentLine` / `UncommentLine` using the language's comment token. Set `false` to fall back to 10x's built-in commenting. Only applies when the language defines a token. |
| `<name>.Diagnostics`        | `true` / `false`                | `true`             | Show the diagnostic under the cursor in the status bar and publish diagnostics to the build-output panel. |
| `<name>.DiagnosticsLevel`   | `error` / `warning` / `info` / `hint` | `error`      | Lowest severity to show. `error` = errors only; `warning` = errors + warnings; `hint` = everything. Applies to the status bar and build output. |
| `<name>.MaxResults`         | integer                         | `50`               | Max completion items to show, most-relevant first. Useful for servers like rust-analyzer that return the whole scope. |
| `<name>.FuzzyComplete`      | `true` / `false`                | `true`             | Match completion items on a *subsequence* of what you've typed rather than a literal prefix, so `gcp` finds `GetCursorPos` and `updcur` finds `UpdateCursorMode`. Matches are ranked best-first: a prefix beats a word-boundary hit (camelCase hump or after `_`), which beats a mid-word hit, and runs of adjacent characters beat scattered ones. Set `false` for literal prefix matching only. |
| `<name>.MaxFileSize`        | integer (KB)                    | `0` (unlimited)    | Skip files larger than this: they are never sent to the server, so neither side holds their text and language features are off for them. Aimed at huge generated files. |
| `<name>.IgnoreDirs`         | comma/semicolon list            | *(none)*           | Extra directory **names** (matched at any depth) to skip in the workspace file-watch scan, on top of the built-in list. E.g. `Generated, ThirdParty`. |
| `<name>.ServerEnv`          | `KEY=VALUE; KEY2=VALUE2`        | *(none)*           | Environment variables for the server process, merged over the editor's environment. Mainly for tuning servers that run on a VM - see [memory use](#memory-use). |
| `<name>.SlowMainThreadMs`   | integer (ms)                    | `0` (off)          | Diagnostic. Set to a millisecond budget (`8` is half a 60fps frame) and the client logs any of its editor callbacks that overran it, naming the phase of the update tick responsible. `<Name> status` lists the worst offenders seen. Off by default; useful when the editor feels stuttery and you want to know whether the LSP client is the cause. |
| `<name>.SymbolFilterMinChars` | integer                      | `3`                | Only ask the server once the filter is this long; shorter filters are answered from the cache, so the blocking wait is spent only on queries selective enough to be worth it. Ignored when there is no cache to fall back on. |
| `<name>.SymbolSource`       | `auto` / `workspace` / `documents` | `auto` | Where the find-symbol list comes from. `workspace` = one `workspace/symbol` request, limited to whatever the server's project index holds. `documents` = scan the project's files with `documentSymbol`, which sees every symbol in every file but costs a request per file. `auto` = try `workspace/symbol`, fall back to the scan when its index proves empty. |
| `<name>.SymbolCache`        | `true` / `false`                | `true`             | Keep a project-wide symbol cache for the find-symbol panel. The panel filters the list it is handed, so it needs every symbol in the project each time it opens - hence the cache. Set `false` to skip that memory and the background refreshes; **find-symbol turns off with it** - `FindSymbol` is still intercepted (so 10x doesn't open its own empty-looking panel) but, like `ListSymbols` / `RefreshSymbols`, only says so in the status bar. `<Name> symbols <text>` still works. |
| `<name>.SymbolCacheSeconds` | integer (seconds)               | `60`               | How long that cache stays fresh. Once older than this the panel is still served instantly, then the cache refreshes in the background (a save refreshes it too). `0` keeps find-symbol working but holds nothing between opens - every open then waits on the server, and `RefreshSymbols` has nothing to rebuild. Ignored when `SymbolCache` is `false`. |
| `<name>.LogVerbose`         | `true` / `false`                | `false`            | Log server traffic to the output panel. |

## Key bindings

With `InterceptCommands` on (the default), 10x's standard bindings already drive
the language server, so no setup is needed. To bind the per-language functions
explicitly instead (Settings -> Key Bindings), use `<Name>_Completion()`,
`<Name>_GotoDefinition()`, `<Name>_Hover()`, `<Name>_FindReferences()`,
`<Name>_ListFunctions()`, `<Name>_ListSymbols()`, `<Name>_SignatureHelp()`,
`<Name>_ToggleComment()`, `<Name>_CommentLine()`,
`<Name>_UncommentLine()`, `<Name>_ShowDiagnostics()`, `<Name>_RefreshSymbols()`,
`<Name>_Restart()` and `<Name>_Status()`. The comment commands map to 10x's defaults:
`Control Shift /` (toggle), `Control K, Control C` (comment),
`Control K, Control U` (uncomment).

## Command panel

Every feature can also be run by typing `<Name> <command>` into 10x's command
panel, no keybinding needed - e.g. `RustLSP status`, `CSharpLSP diagnostics`,
`PythonLSP restart`. Commands: `status`, `complete`, `hover`, `signature`,
`definition`, `references`, `functions`, `symbols [text]`, `refresh symbols`,
`diagnostics`, `restart`, `comment`, `commentline`, `uncommentline`.

`symbols` is the only one that takes an argument - the term to search the project
for, e.g. `RustLSP symbols Widget`. That searches the server directly, and is
the one symbol command that still works with `SymbolCache: false`; without an
argument the panel opens on the cached project symbols (`refresh symbols`
rebuilds that cache).

### Very large projects

The find-symbol cache asks the server for *every* symbol in the project, so its
cost scales with the project. Three things bound it:

- **Responses over 32 MB are dropped unparsed** (`MAX_RESPONSE_BYTES`). Parsing
  costs several times the wire size in Python objects and seconds of CPU, so a
  project too big to hold is refused rather than swallowed. The client then falls
  back to term search - `<Name> symbols <text>` - and says so in the status bar.
- **The symbol list is built on the reader thread**, never the main one. A reply
  that needs real work registers a *transform* (`LSPConnection.request`) which
  runs off the critical path, so the editor's main thread only ever receives a
  finished result. On a 120k-symbol reply that is 1.4 s of background work and
  0.1 ms on the main thread.
- **Saves only refresh a stale cache**, not every save, so a save-heavy edit loop
  can't re-dump the workspace repeatedly.
- **`SymbolCache: false`** opts out entirely if you would rather not pay for it.

Most servers also cap `workspace/symbol` results themselves, which limits this
further - but the cap varies by server and version, so it isn't relied on.

## Memory use

Nearly all of the memory belongs to the **language server process**, not to this
client. The server holds parsed syntax trees, compilations and symbol tables for
everything it has been told to load, so the levers that matter are (in order):

1. **Load less.** This is by far the biggest lever on a large repo. For C#, if
   10x has a `.sln`/`.slnx` open as its workspace, Roslyn is pointed at exactly
   that one automatically - no configuration needed. Otherwise the client opens
   the first solution at the project root, or, failing that, *every* `.csproj`
   under it, and Roslyn holds them all in memory. Set `CSharpLSP.Solution` to
   avoid that fallback when your 10x workspace is a `.10x` file or a folder.
2. **Tune the runtime.** Roslyn runs on .NET, so its footprint is largely GC
   policy. `CSharpLSP.LowMemory: true` sets `DOTNET_GCConserveMemory=9` and
   `DOTNET_gcServer=0` for the server process. Measured on a synthetic 400-file /
   4800-method project: **peak working set 362 MB -> 183 MB (-49%)**, with no
   measurable cost to project load time (7.1s both ways) or completion latency
   (51 ms median both ways). The extra collection work scales with heap size, so
   on a very large solution expect to trade some CPU for the saving. Use
   `<name>.ServerEnv` to set other variables by hand.
3. **Skip huge files.** `<name>.MaxFileSize` (in KB) stops oversized files being
   sent at all. Both sides hold a copy of every open document, and on full-sync
   servers the whole text is resent on each edit, so a few multi-MB generated
   files cost more than they look. Skipped files get no language features, and
   the output panel says which ones were skipped.

`<name>.IgnoreDirs` only prunes *this client's* workspace file-watch scan (used
for `workspace/didChangeWatchedFiles`); it does not stop the server from indexing
those directories, so treat it as a CPU/IO saving rather than a memory one. Run
`<Name>_Status()` to see the limits, extra ignores and server env currently in
effect.

## Per-language setup

### Python (`PythonLSP.py`)

- **Extensions:** `.py`, `.pyi`, `.pyw` &nbsp;·&nbsp; **Comment token:** `#`
- **Server:** [python-lsp-server](https://github.com/python-lsp/python-lsp-server) (`pylsp`), default command `pylsp` (falls back to `<python> -m pylsp`).
- **Install:**
  ```
  pip install python-lsp-server
  ```
- **Diagnostics need a linter.** A bare `pylsp` install ships only jedi
  (completion/hover/go-to work, but no diagnostics). Add at least pyflakes for
  real errors; pycodestyle adds style warnings:
  ```
  pip install pyflakes pycodestyle
  ```
  or pull in every plugin at once:
  ```
  pip install "python-lsp-server[all]"
  ```
  Install into the same Python that runs `pylsp`, then restart the server
  (`PythonLSP_Restart()`).
- **No project-wide symbol search.** pylsp does not implement
  `workspace/symbol` at all (it answers `Method Not Found`), so
  `PythonLSP_ListSymbols()` reports that the server can't do it.
  `PythonLSP_ListFunctions()` (current file) works fine. pyright does implement
  it - see below.
- **Alternative server:** pyright - `pip install pyright` and set
  `PythonLSP.Command: pyright-langserver --stdio`.

### Rust (`RustLSP.py`)

- **Extensions:** `.rs` &nbsp;·&nbsp; **Comment token:** `//`
- **Server:** [rust-analyzer](https://rust-analyzer.github.io/), default command `rust-analyzer`.
- **Install:** put `rust-analyzer` on your PATH, or set `RustLSP.Command` to its full path:
  ```
  rustup component add rust-analyzer
  ```
  (then add `~/.rustup` to PATH, or use `RustLSP.Command: rustup run stable rust-analyzer`),
  or download a release binary from
  https://github.com/rust-lang/rust-analyzer/releases.
- **Project:** open a Cargo project (a folder with `Cargo.toml`); rust-analyzer
  discovers the workspace and dependencies from there. Non-Cargo projects need a
  `rust-project.json` at the root.
- **Symbol search:** rust-analyzer searches *types only* by default. It reads two
  suffixes on the query, which you can pass through the command panel: `#`
  includes every symbol kind (functions, consts, ...) and `*` widens the search to
  dependencies. So `RustLSP symbols parse#` finds functions named `parse`. An
  empty query returns the workspace's types plus the crate roots.

### Odin (`OdinLSP.py`)

- **Extensions:** `.odin` &nbsp;·&nbsp; **Comment token:** `//`
- **Server:** [OLS](https://github.com/DanielGavin/ols) (the Odin Language Server), default command `ols`.
- **Install:** build OLS so `ols` (`ols.exe`) is on your PATH, or set
  `OdinLSP.Command` to its full path (build instructions in the OLS repo).
- **Project (recommended):** add an `ols.json` to your project root so OLS can
  find the Odin core/vendor collections:
  ```json
  {
    "collections": [
      { "name": "core",   "path": "C:/Odin/core" },
      { "name": "vendor", "path": "C:/Odin/vendor" }
    ],
    "enable_document_symbols": true,
    "enable_hover": true,
    "enable_snippets": true
  }
  ```
- **Symbol search:** OLS advertises `workspace/symbol` but returned no results at
  all in testing (every query, including exact names, after a full index warm-up),
  so `OdinLSP_ListSymbols()` will likely come up empty. There is no ols.json
  option to change this. `OdinLSP_ListFunctions()` (current file) works.

### Jai (`JaiLSP.py`)

- **Extensions:** `.jai` &nbsp;·&nbsp; **Comment token:** `//`
- **Server:** [jails](https://github.com/SogoCZE/jails) (the Jai Language Server), default command `jails`.
- **Install:** build jails so `jails` (`jails.exe`) is on your PATH, or set
  `JaiLSP.Command` to its full path. jails needs to know where the Jai compiler
  is - follow its README to point it at your `jai/` install.
- **Project:** add a `jails.json` to your project root naming the build entry point:
  ```json
  {
    "buildRoot": "main.jai"
  }
  ```
  Without it, jails treats the opened file's folder as the workspace, which gives
  weaker cross-file results.
- **Symbol search:** works with a search term (it matches struct members too, so
  `Widget` also finds `Widget.size`). An empty query returns `null`, so put the
  cursor on a word or type `JaiLSP symbols <text>`.

### C# (`CSharpLSP.py`)

- **Extensions:** `.cs`, `.csx`, `.cake` &nbsp;·&nbsp; **Comment token:** `//`
- **Server:** the official Roslyn-based C# server (the one behind the VS Code C#
  Dev Kit), published by Microsoft as the **`roslyn-language-server`** .NET
  global tool on nuget.org. Default command `roslyn-language-server --stdio`.
- **Install:**
  1. Install the [.NET SDK](https://dotnet.microsoft.com/download) - match the
     tool's target (currently **.NET 10**), so grab the .NET 10 SDK. (The SDK is
     needed by `dotnet tool install` and bundles the matching runtime.)
  2. Install the tool (prerelease-only for now):
     ```
     dotnet tool install --global roslyn-language-server --prerelease
     ```
     This puts `roslyn-language-server(.exe)` in `%USERPROFILE%\.dotnet\tools`,
     which the SDK adds to your PATH. (Neovim's Mason `roslyn` / `roslyn.nvim`
     are another way to obtain the same server.)
  3. That's it - the default command is already `roslyn-language-server --stdio`,
     so with the tool on your PATH you don't need to set anything else; just
     enable the client (`CSharpLSP.Enabled: true`). Set `CSharpLSP.Command` only
     to override the default, e.g. if the tool isn't on PATH:
     ```
     CSharpLSP.Command: C:/Users/you/.dotnet/tools/roslyn-language-server.exe --stdio
     ```
- **Project:** open a folder containing a `.sln` / `.slnx` (preferred) or a
  `.csproj`. Unlike most servers, Roslyn does not auto-load a project on
  startup, so `CSharpLSP.py` sends the server the Roslyn-specific
  `solution/open` / `project/open` notification once it initializes - a solution
  gives the best cross-project results. What gets opened, in order: an explicit
  `CSharpLSP.Solution`; the solution 10x itself has open (via
  `GetWorkspaceFilename()`, which is skipped when the workspace is a `.10x` file
  rather than a solution); the first `.sln`/`.slnx` at the project root; else
  every `.csproj` found underneath.
- **Memory:** Roslyn is the heaviest of the servers here. `CSharpLSP.Solution`
  (load one solution/project instead of all of them) and `CSharpLSP.LowMemory:
  true` (GC tuning, roughly halves peak working set) are the two levers - see
  [memory use](#memory-use).
- **Symbol search:** Roslyn needs a real search term - an empty
  `workspace/symbol` query returns nothing at all. Put the cursor on a word, or
  type `CSharpLSP symbols <text>` in the command panel.
- **Remove `.cs` from `ParserExtensions`.** 10x lists `.cs` there by default,
  which makes its built-in parser fight the language server; drop `.cs` from that
  setting (see the note under [Installation](#installation)). CSharpLSP logs a
  `WARNING` at startup if it's still present.
