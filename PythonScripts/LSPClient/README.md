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
  filtered to what you've typed and capped at `MaxResults`.
- **Hover** - documentation for the symbol under the cursor, shown in 10x's
  inline hover box.
- **Signature help** - the active function signature.
- **Go to definition** - opens the target file at the definition (with a couple
  of retries for servers that answer `null` until the workspace finishes loading).
- **Find references** - shown in 10x's symbol-references list.
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
  `Autocomplete`, `ShowFunctionArgsInfo`, `ShowSymbolInfo`, and (when a comment
  token is configured) `ToggleComment` / `CommentLine` / `UncommentLine`.
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
| `<name>.InterceptCommands`  | `true` / `false`                | `true`             | Hook 10x's built-in commands so the default key bindings drive the language server for files this client handles. Set `false` to require the per-language `<Name>_*` functions instead. |
| `<name>.Commenting`         | `true` / `false`                | `true`             | Handle `ToggleComment` / `CommentLine` / `UncommentLine` using the language's comment token. Set `false` to fall back to 10x's built-in commenting. Only applies when the language defines a token. |
| `<name>.Diagnostics`        | `true` / `false`                | `true`             | Show the diagnostic under the cursor in the status bar and publish diagnostics to the build-output panel. |
| `<name>.DiagnosticsLevel`   | `error` / `warning` / `info` / `hint` | `error`      | Lowest severity to show. `error` = errors only; `warning` = errors + warnings; `hint` = everything. Applies to the status bar and build output. |
| `<name>.MaxResults`         | integer                         | `50`               | Max completion items to show, most-relevant first. Useful for servers like rust-analyzer that return the whole scope. |
| `<name>.LogVerbose`         | `true` / `false`                | `false`            | Log server traffic to the output panel. |

## Key bindings

With `InterceptCommands` on (the default), 10x's standard bindings already drive
the language server, so no setup is needed. To bind the per-language functions
explicitly instead (Settings -> Key Bindings), use `<Name>_Completion()`,
`<Name>_GotoDefinition()`, `<Name>_Hover()`, `<Name>_FindReferences()`,
`<Name>_SignatureHelp()`, `<Name>_ToggleComment()`, `<Name>_CommentLine()`,
`<Name>_UncommentLine()`, `<Name>_ShowDiagnostics()`, `<Name>_Restart()` and
`<Name>_Status()`. The comment commands map to 10x's defaults:
`Control Shift /` (toggle), `Control K, Control C` (comment),
`Control K, Control U` (uncomment).

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
  gives the best cross-project results.
- **Remove `.cs` from `ParserExtensions`.** 10x lists `.cs` there by default,
  which makes its built-in parser fight the language server; drop `.cs` from that
  setting (see the note under [Installation](#installation)). CSharpLSP logs a
  `WARNING` at startup if it's still present.
