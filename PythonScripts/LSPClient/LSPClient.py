# LSPClient.py - Generic Language Server Protocol client for 10x (10xeditor.com)
#
# A reusable LSP client that can be driven by any language server. It handles
# the transport (JSON-RPC over the server's stdio), the document-sync
# lifecycle, diagnostics and the common editor features (completion, hover,
# signature help, go-to-definition, find-references), and wires them into the
# 10x editor event hooks.
#
# This file defines classes only - importing it has NO side effects (it never
# registers editor hooks on its own). To use it, create a per-language script
# that instantiates LanguageServerClient and calls .register(). See the
# PythonLSP script for a complete example:
#
#     import sys, N10X
#     from LSPClient import LanguageServerClient
#
#     client = LanguageServerClient(
#         name="PythonLSP", language_id="python", extensions=(".py", ".pyi"),
#         default_command="pylsp", fallback_argv=[sys.executable, "-m", "pylsp"],
#         trigger_chars=".")
#
#     def MyLang_Completion():     client.complete()
#     def MyLang_GotoDefinition(): client.goto_definition()
#     ...
#     N10X.Editor.CallOnMainThread(client.register)
#
# Per-client settings are read from "<name>.<key>" in Settings.10x_settings:
#     <name>.Command        Command line used to launch the server (overrides
#                           the default). e.g. "PythonLSP.Command: pylsp"
#     <name>.Enabled        "true"/"false" - OPT-IN, default false. The client
#                           is completely inert until this is "true": no server
#                           is launched and no editor hooks are registered.
#                           Takes effect on the next 10x restart.
#     <name>.AutoComplete   "true"/"false" - auto-trigger completion as you type
#                           (after identifier or trigger chars, debounced).
#                           Default true; set "false" to use the keybinding only.
#     <name>.InterceptCommands  "true"/"false" - hook 10x's built-in commands
#                           (GoToSymbolDefinition, GoToSymbolDefinitionUnderMouse,
#                           FindSymbolReferences, Autocomplete,
#                           ShowFunctionArgsInfo, ShowSymbolInfo, and - when the
#                           language defines a comment token - ToggleComment /
#                           CommentLine / UncommentLine) so the default key
#                           bindings drive the language server for files we
#                           handle. Default true; set "false" to require the
#                           per-language <Name>_* functions instead.
#     <name>.Commenting     "true"/"false" - handle 10x's ToggleComment /
#                           CommentLine / UncommentLine for files we handle,
#                           using the language's comment token (default true).
#                           Set "false" to fall back to 10x's built-in
#                           commenting. Only applies when a token is configured.
#     <name>.Diagnostics    "true"/"false" - show the diagnostic under the
#                           cursor in the status bar (default true)
#     <name>.DiagnosticsLevel  lowest severity to show: error | warning | info |
#                           hint. e.g. "warning" shows errors+warnings, "hint"
#                           shows everything (default "error" = errors only).
#                           Applies to the status bar and build output.
#     <name>.MaxResults     Max completion items to show, most-relevant first
#                           (default 50). Useful for servers like rust-analyzer
#                           that return the whole scope.
#     <name>.LogVerbose     "true"/"false" - log server traffic to the output
#                           panel (default false)
#
# Threading: a background thread only reads/parses the server's stdout. Every
# N10X.Editor.* call happens on the main thread inside the update loop, so the
# editor is never blocked waiting on the server.
#
# Coordinates: LSP positions are 0-based (line, character), matching 10x's
# (column, line) cursor coordinates. Characters are treated as column indices,
# which is correct for ASCII / BMP text.
# ---------------------------------------------------------------------------

import os
import re
import glob
import html
import json
import time
import queue
import shutil
import threading
import subprocess

import N10X

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_SEVERITY = {1: "Error", 2: "Warning", 3: "Info", 4: "Hint"}
# LSP severity -> MSVC compiler keyword. 10x parses build output in the Visual
# Studio "file(line,col): <keyword> CODE: message" style; error/warning/note are
# the keywords it recognises, so info and hint are folded onto "note".
_MSVC_SEVERITY = {1: "error", 2: "warning", 3: "note", 4: "note"}
# "<name>.DiagnosticsLevel" value -> the highest LSP severity *number* to show
# (1=Error is most severe, 4=Hint least). A diagnostic is displayed only when
# its severity number is <= this threshold, so "error" shows errors only,
# "warning" shows errors+warnings, etc. Default ("hint") shows everything.
_SEVERITY_LEVELS = {"error": 1, "errors": 1, "warning": 2, "warnings": 2,
                    "info": 3, "information": 3, "hint": 4, "hints": 4,
                    "all": 4}
# Note: ".git" is deliberately NOT a marker. A git submodule has its own .git
# entry, so find_project_root (which stops at the innermost dir with a marker)
# would pick the submodule rather than walking up to the real workspace root.
_DEFAULT_ROOT_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg",
                         "requirements.txt", "Pipfile", "package.json",
                         "Cargo.toml", "go.mod", "tsconfig.json")
# Language-agnostic directories the workspace file-watch scan never descends
# into (VCS/editor metadata, generic build/dependency output) - keeps the
# periodic mtime walk cheap. Language-specific dirs (e.g. Rust's "target",
# Python venvs) are passed per-client via LanguageServerClient(ignore_dirs=...)
# so adding a language never means editing this module.
_COMMON_IGNORE_DIRS = frozenset((
    ".git", ".svn", ".hg", ".idea", ".vs", ".vscode",
    "node_modules", "build", "dist", ".cache"))


def _log(tag, msg):
    print(f"[{tag}] {msg}")


# ===========================================================================
# Path / URI helpers
# ===========================================================================

def path_to_uri(path):
    path = os.path.abspath(path).replace("\\", "/")
    if not path.startswith("/"):
        path = "/" + path  # drive-letter paths -> /C:/...
    safe = []
    for ch in path:
        if ch.isalnum() or ch in "/-_.~:!$&'()*+,;=@":
            safe.append(ch)
        else:
            safe.append("%%%02X" % ord(ch))
    return "file://" + "".join(safe)


def uri_to_path(uri):
    if uri.startswith("file://"):
        uri = uri[len("file://"):]
    out = []
    i = 0
    while i < len(uri):
        if uri[i] == "%" and i + 2 < len(uri):
            try:
                out.append(chr(int(uri[i + 1:i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(uri[i])
        i += 1
    path = "".join(out)
    if len(path) >= 3 and path[0] == "/" and path[2] == ":":
        path = path[1:]  # /C:/... -> C:/...
    return os.path.normpath(path)


def find_project_root(file_path, markers):
    """Walk up from a file looking for a project marker; fall back to its dir.

    A marker is normally a literal filename (e.g. "Cargo.toml"), but one that
    contains a shell wildcard ("*" or "?") is matched as a glob against the
    directory's contents - so a language whose project files are variably named
    (e.g. C#'s "*.sln"/"*.csproj") can still find its root."""
    d = os.path.dirname(os.path.abspath(file_path))
    cur = d
    while True:
        for m in markers:
            if "*" in m or "?" in m:
                if glob.glob(os.path.join(cur, m)):
                    return cur
            elif os.path.exists(os.path.join(cur, m)):
                return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return d
        cur = parent


def extract_markup(contents):
    """Normalise LSP hover contents (string | {value} | MarkupContent | list)."""
    if contents is None:
        return ""
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict):
        return contents.get("value", "")
    if isinstance(contents, list):
        return "\n\n".join(extract_markup(c) for c in contents)
    return str(contents)


def strip_code_fences(text):
    """Drop Markdown code-fence lines (``` or ```lang) while keeping the code
    inside them. 10x's hover box shows text verbatim rather than rendering
    Markdown, so fences a server wraps content in - e.g. OLS emits every Odin
    signature as "```odin\\n<sig>\\n```" - would otherwise show up as literal ```
    lines. Only whole-line fences are removed; inline `code` spans, the "---"
    section separators and everything else are left as-is."""
    if not text or "```" not in text:
        return text
    out = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence  # toggle: this line opens or closes a block
            continue                 # and is dropped either way
        out.append(line)
    # Trim only blank lines the stripping may have left at the very ends; keep
    # interior blank lines (they separate sections) and any code indentation.
    return "\n".join(out).strip("\n")


def strip_markup_html(text):
    """Decode HTML entities a server embeds in Markdown hover text - the
    C#/Roslyn server pads with &nbsp; and escapes generics as &lt;T&gt;. 10x's
    hover box shows text verbatim and never decodes HTML, so the raw entities
    would show literally. Non-breaking spaces (&nbsp; -> \\xa0) are folded to
    normal spaces so they don't render oddly."""
    if not text or "&" not in text:
        return text
    return html.unescape(text).replace("\xa0", " ")


# Backslash before an ASCII punctuation char = a Markdown escape of that char.
_MD_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")


def strip_markdown_escapes(text):
    """Undo Markdown backslash conventions for verbatim display. Markdown lets a
    server escape any ASCII punctuation with a backslash (the C#/Roslyn server
    emits things like my\\_field or List\\<T\\>) and end a line with a trailing
    "\\" to force a hard line break. 10x shows hover text verbatim, so those
    backslashes show up literally. Drop a lone trailing "\\" at each line end (the
    newline is already there), then drop the escaping backslash before
    punctuation. A backslash not followed by punctuation - e.g. a Windows path
    like C:\\Users - is left alone."""
    if not text or "\\" not in text:
        return text
    # Hard-line-break backslash at the end of a line / the whole string.
    text = re.sub(r"\\(?=\n)", "", text)
    if text.endswith("\\"):
        text = text[:-1]
    # "\<punct>" -> "<punct>".
    return _MD_ESCAPE.sub(r"\1", text)


def first_location(result):
    """Normalise Location | Location[] | LocationLink[] to (uri, range)."""
    if not result:
        return None
    if isinstance(result, dict):
        if "uri" in result:
            return result["uri"], result.get("range", {})
        if "targetUri" in result:
            return result["targetUri"], result.get("targetSelectionRange",
                                                    result.get("targetRange", {}))
        return None
    if isinstance(result, list) and result:
        return first_location(result[0])
    return None


def offset_to_pos(text, offset):
    """Convert a character offset in `text` to an LSP {line, character}."""
    line = text.count("\n", 0, offset)
    last_nl = text.rfind("\n", 0, offset)
    return {"line": line, "character": offset - (last_nl + 1)}


def incremental_change(old, new):
    """Single LSP incremental contentChange describing old -> new (a range
    replace covering everything between the common prefix and common suffix),
    or None when the text is unchanged. Positions are computed against `old`,
    which is what the server currently holds."""
    if old == new:
        return None
    old_len, new_len = len(old), len(new)
    p = 0
    max_p = min(old_len, new_len)
    while p < max_p and old[p] == new[p]:
        p += 1
    s = 0
    max_s = min(old_len, new_len) - p
    while s < max_s and old[old_len - 1 - s] == new[new_len - 1 - s]:
        s += 1
    return {"range": {"start": offset_to_pos(old, p),
                      "end": offset_to_pos(old, old_len - s)},
            "text": new[p:new_len - s]}


# ===========================================================================
# JSON-RPC transport over the server's stdio
# ===========================================================================

class LSPConnection:
    """Spawns the language server and pumps JSON-RPC messages over stdio.

    Reading happens on a background thread (parsed messages are pushed onto
    self.incoming). Writing happens from the main thread. All handling of the
    parsed messages is done by the owner on the main thread.
    """

    def __init__(self, argv, cwd, log=None, verbose=None):
        self._log = log or (lambda m: None)
        self._verbose = verbose or (lambda: False)
        self.incoming = queue.Queue()
        self.outgoing = queue.Queue()
        self._next_id = 1
        self.alive = False

        self.proc = subprocess.Popen(
            argv, cwd=cwd,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, creationflags=_NO_WINDOW)
        self.alive = True

        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._errreader = threading.Thread(target=self._stderr_loop, daemon=True)
        self._errreader.start()
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._writer.start()

    # -- outgoing ----------------------------------------------------------

    def _write(self, payload):
        if not self.alive or self.proc.stdin is None:
            return
        try:
            body = json.dumps(payload)
        except (TypeError, ValueError) as e:
            self._log(f"encode failed: {e}")
            return
        data = body.encode("utf-8")
        header = ("Content-Length: %d\r\n\r\n" % len(data)).encode("ascii")
        # Hand the framed bytes to the writer thread instead of writing to the
        # pipe here. A server that is busy (e.g. reparsing a large file) and not
        # draining its stdin would otherwise block this call - and since _write
        # runs on the editor's main thread, that freezes the editor.
        self.outgoing.put(header + data)
        if self._verbose():
            self._log("--> " + body[:300])

    def _write_loop(self):
        # Runs on a background thread: the blocking write/flush happens here, off
        # the main thread. No N10X.Editor calls (main-thread only) - logging uses
        # plain print via self._log, which is thread-safe enough.
        stream = self.proc.stdin
        while True:
            chunk = self.outgoing.get()
            if chunk is None:  # shutdown sentinel
                break
            try:
                stream.write(chunk)
                stream.flush()
            except (OSError, ValueError) as e:
                self.alive = False
                self._log(f"write failed: {e}")
                break

    def request(self, method, params):
        """Send a request, returning its id so the caller can match a reply."""
        rid = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": rid, "method": method,
                     "params": params})
        return rid

    def notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    def respond(self, rid, result=None, error=None):
        msg = {"jsonrpc": "2.0", "id": rid}
        if error is not None:
            msg["error"] = error
        else:
            msg["result"] = result
        self._write(msg)

    # -- incoming ----------------------------------------------------------

    def _read_loop(self):
        stream = self.proc.stdout
        try:
            while True:
                headers = {}
                while True:
                    line = stream.readline()
                    if not line:
                        raise EOFError()
                    line = line.strip()
                    if not line:
                        break  # blank line ends the header block
                    if b":" in line:
                        k, _, v = line.partition(b":")
                        headers[k.strip().lower()] = v.strip()
                length = int(headers.get(b"content-length", b"0"))
                if length <= 0:
                    continue
                body = b""
                while len(body) < length:
                    chunk = stream.read(length - len(body))
                    if not chunk:
                        raise EOFError()
                    body += chunk
                try:
                    self.incoming.put(json.loads(body.decode("utf-8")))
                except json.JSONDecodeError:
                    pass
        except (EOFError, OSError, ValueError):
            pass
        finally:
            self.alive = False
            self.incoming.put({"__lsp_internal__": "exited"})

    def _stderr_loop(self):
        # Runs on a background thread, so it must not call any N10X.Editor API
        # (those are main-thread only). Hand lines to the main thread via the
        # incoming queue, where they are logged from pump().
        stream = self.proc.stderr
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    self.incoming.put({"__lsp_stderr__": line})
        except (OSError, ValueError):
            pass

    def shutdown(self):
        if self.alive:
            try:
                self.request("shutdown", None)
                self.notify("exit", None)
            except Exception:
                pass
        self.alive = False
        self.outgoing.put(None)  # stop the writer thread
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
        except Exception:
            pass


# ===========================================================================
# High-level, language-agnostic client + 10x integration
# ===========================================================================

class LanguageServerClient:
    """Manages one language server and bridges it to the 10x editor.

    Parameters:
        name            Identifier used for logging, status-bar text and the
                        settings prefix ("<name>.Command", etc.).
        language_id     LSP languageId sent in didOpen (e.g. "python").
        extensions      Iterable of file extensions this client handles
                        (e.g. (".py", ".pyi")).
        default_command Default server command line, used when "<name>.Command"
                        is not set (e.g. "pylsp" or "clangd --stdio").
        fallback_argv   Optional argv list to try when the first token of the
                        resolved command is not found on PATH (e.g.
                        [sys.executable, "-m", "pylsp"]).
        trigger_chars   Characters that auto-trigger completion when
                        "<name>.AutoComplete" is true (e.g. ".").
        line_comment    Line-comment token for this language (e.g. "//" or "#").
                        When set, the ToggleComment / CommentLine / UncommentLine
                        commands comment or uncomment the selected lines with it.
                        Commenting is a pure editor-side text edit - it does not
                        use the language server (LSP has no comment API).
        root_markers    Optional iterable of project-root marker filenames.
        init_options    Optional dict passed as initializationOptions.
        on_initialized  Optional callback(client) invoked once, right after the
                        server replies to "initialize" and we've sent the
                        "initialized" notification. Lets a language script do
                        server-specific post-init work - e.g. the Roslyn C#
                        server does not auto-load a project, so CSharpLSP uses
                        this to send its custom "solution/open" notification.
        ignore_dirs     Optional iterable of language-specific directory names
                        the workspace file-watch scan should skip (e.g.
                        ("target",) for Rust). Merged with the common set
                        (_COMMON_IGNORE_DIRS); keep language-specific entries
                        here in the per-language script rather than in this
                        module so new languages don't need to edit it.
        server_cwd      Optional working directory for the server process.
                        Default (None) launches it with cwd = project root.
                        Pass a path, or a callable(root_path) -> path, to point
                        it elsewhere - useful for servers that scribble relative
                        scratch/log dirs (Roslyn writes a "{}" folder) into
                        their cwd and would otherwise clutter the project root.
        pull_diagnostics
                        Opt in to LSP 3.17 "pull" diagnostics for this client.
                        Most servers (ols, rust-analyzer, pylsp) PUSH diagnostics
                        via textDocument/publishDiagnostics, which we always
                        handle. A few - notably the Roslyn C# server - never push
                        and instead expect the client to REQUEST diagnostics with
                        textDocument/diagnostic. Set this True for those, and the
                        client advertises the capability, pulls after open/edit,
                        and re-pulls on workspace/diagnostic/refresh. Default
                        False, so push-only servers are completely unaffected.
    """

    def __init__(self, name, language_id, extensions, default_command="",
                 fallback_argv=None, trigger_chars="", root_markers=None,
                 init_options=None, ignore_dirs=None, line_comment="",
                 on_initialized=None, server_cwd=None, pull_diagnostics=False):
        self.name = name
        self.language_id = language_id
        self.extensions = tuple(extensions)
        self.default_command = default_command
        self.fallback_argv = fallback_argv
        self.trigger_chars = trigger_chars or ""
        self.line_comment = line_comment or ""
        self.root_markers = tuple(root_markers) if root_markers else _DEFAULT_ROOT_MARKERS
        self.init_options = init_options or {}
        self.on_initialized = on_initialized
        # Working directory for the server process. By default the server is
        # launched with cwd = project root, which is what most servers expect.
        # Some servers (notably Roslyn) write scratch/log directories into their
        # cwd, littering the project root; such a client can pass server_cwd to
        # redirect those relative writes elsewhere (e.g. under %TEMP%). May be a
        # path string, or a callable(root_path) -> path evaluated at launch (so
        # it can derive a per-project temp dir). None keeps the current
        # behaviour (cwd = root). See ensure_started.
        self.server_cwd = server_cwd
        # Pull-diagnostics support (opt-in; see the constructor docstring). When
        # on we request diagnostics rather than waiting for the server to push
        # them - required for servers like Roslyn that never publishDiagnostics.
        self.pull_diagnostics = bool(pull_diagnostics)
        self._pull_active = False        # became live after initialize
        self._diag_result_ids = {}       # uri -> last resultId (unchanged reports)
        self._diag_pending = set()       # uris queued for a debounced pull
        self._diag_pull_due = 0.0        # time.time() at which to flush the queue
        self._diag_pull_delay = 0.35     # debounce so we don't pull every keystroke
        self.ignore_dirs = _COMMON_IGNORE_DIRS | frozenset(ignore_dirs or ())
        self.disabled = False

        self.conn = None
        self.initialized = False
        self.root_uri = None
        self.root_path = None
        self._sync_kind = 1  # server textDocumentSync.change: 0 none/1 full/2 incremental
        self.pending = {}        # request id -> handler(result, error)
        self.docs = {}           # uri -> {"version", "text", "filename"}
        self.diagnostics = {}    # uri -> [Diagnostic]
        self._last_sync = 0.0
        self._sync_interval = 0.35
        self._completion_due = 0.0   # time.time() at which to auto-fire completion
        self._auto_delay = 0.12      # debounce window for as-you-type completion
        self._last_completion_id = None  # newest in-flight completion request id
        self._completion_inflight = False  # a completion request is awaiting reply
        self._completion_req_pos = None  # cursor (x, y) when that request was sent
        self._autocomplete_visible = False  # our completion popup is on screen
        self._last_cursor_pos = None     # (x, y) at the previous cursor-move event
        self._last_line_text = None      # current line text at that event (edit vs move)
        self._last_status_line = -1
        self._next_start_attempt = 0.0  # backoff for auto-starting the server
        self._verbose_flag = False       # cached so background threads can read it
        self._retry_due = 0.0            # time.time() at which to run _retry_action
        self._retry_action = None        # deferred re-request (see _schedule_retry)
        # Watched-file support. Servers like ols keep an in-memory workspace
        # index and refresh an unopened file only when told it changed on disk
        # (via workspace/didChangeWatchedFiles). rust-analyzer watches the FS
        # itself and pylsp re-reads on demand, so they don't register a watcher
        # with us; ols does, which is what enables our polling scan below.
        self._watch_enabled = False      # server asked us to watch files
        self._watch_mtimes = {}          # path -> mtime, baseline for diffing
        self._last_watch_scan = 0.0
        self._watch_interval = 2.0       # seconds between workspace mtime scans

    # -- logging / settings ------------------------------------------------

    def log(self, msg):
        _log(self.name, msg)

    def setting(self, key, default=""):
        # N10X.Editor.* is main-thread only; never call this from a worker thread.
        val = N10X.Editor.GetSetting(f"{self.name}.{key}")
        return val if val else default

    def _refresh_verbose(self):
        """Refresh the cached LogVerbose flag. Call only on the main thread."""
        self._verbose_flag = self.setting("LogVerbose") == "true"

    def _verbose(self):
        # Returns the cached flag so it is safe to call from any thread (e.g. the
        # connection's writer/reader). The flag is refreshed on the main thread.
        return self._verbose_flag

    def handles(self, filename):
        return bool(filename) and filename.endswith(self.extensions)

    # -- lifecycle ---------------------------------------------------------

    def _server_argv(self):
        cmd = self.setting("Command").strip()
        if cmd:
            return cmd.split()
        parts = self.default_command.split()
        if parts:
            exe = shutil.which(parts[0])
            if exe:
                return [exe] + parts[1:]
        if self.fallback_argv:
            return list(self.fallback_argv)
        return parts

    def is_enabled(self):
        """Whether this client is turned on. Opt-in: a server stays off (and has
        no impact at all - see register) until the user explicitly sets
        "<name>.Enabled: true" in Settings.10x_settings."""
        return not self.disabled and self.setting("Enabled", "false").strip().lower() == "true"

    def disable(self):
        """Disables LSP client e.g. if cannot run due to missing LSP"""
        self.log(f"disabling, to restart execute {self.name}_Restart.")
        self.disabled = True

    def _resolve_server_cwd(self):
        """Working directory to launch the server in. Defaults to the project
        root; server_cwd (a path or a callable(root_path) -> path) overrides it
        so servers that write relative scratch/log dirs don't litter the root.
        Falls back to the root if the override is empty or can't be created."""
        target = self.server_cwd
        if callable(target):
            try:
                target = target(self.root_path)
            except Exception as e:
                self.log(f"server_cwd callable failed ({e}); using project root")
                target = None
        if not target:
            return self.root_path
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as e:
            self.log(f"could not create working dir '{target}' ({e}); "
                     f"using project root")
            return self.root_path
        return target

    def ensure_started(self, root_hint):
        if self.conn and self.conn.alive:
            return True
        if not self.is_enabled():
            return False

        self.root_path = find_project_root(root_hint, self.root_markers)
        self.root_uri = path_to_uri(self.root_path)
        argv = self._server_argv()
        if not argv:
            self.log("no server command configured; set " + self.name + ".Command")
            return False
        cwd = self._resolve_server_cwd()
        try:
            self.conn = LSPConnection(argv, cwd,
                                      log=self.log, verbose=self._verbose)
        except FileNotFoundError:
            self.log(f"could not launch server: '{argv[0]}' not found. "
                     f"Install it or set {self.name}.Command.")
            self.conn = None
            self.disable()
            return False
        except Exception as e:
            self.log(f"failed to start server: {e}")
            self.conn = None
            return False

        self.log(f"started '{' '.join(argv)}' (root: {self.root_path})")
        self._send_initialize()
        return True

    def _send_initialize(self):
        params = {
            "processId": os.getpid(),
            "rootUri": self.root_uri,
            "rootPath": self.root_path,
            "workspaceFolders": [{"uri": self.root_uri,
                                  "name": os.path.basename(self.root_path) or "root"}],
            "capabilities": {
                "workspace": {
                    "configuration": True,
                    "workspaceFolders": True,
                    "didChangeConfiguration": {"dynamicRegistration": True},
                    # Let servers register file watchers with us. We don't watch
                    # the FS via the OS; instead, when a server registers we run
                    # a throttled mtime scan of the workspace (see _scan_watched
                    # _files) and report changes. This keeps ols's index fresh
                    # for files edited while not open in the editor.
                    "didChangeWatchedFiles": {"dynamicRegistration": True},
                },
                "textDocument": {
                    "synchronization": {"didSave": True, "willSave": False,
                                        "dynamicRegistration": False},
                    "completion": {
                        "dynamicRegistration": False,
                        "completionItem": {"snippetSupport": False,
                                           "documentationFormat": ["plaintext", "markdown"]},
                    },
                    "hover": {"contentFormat": ["plaintext", "markdown"]},
                    "signatureHelp": {},
                    "definition": {"linkSupport": True},
                    "references": {},
                    "publishDiagnostics": {"relatedInformation": False},
                },
            },
            "initializationOptions": self.init_options,
        }
        if self.pull_diagnostics:
            # Advertise LSP 3.17 pull diagnostics. dynamicRegistration is False:
            # Roslyn ignores dynamic registration and just answers the pull
            # requests, so we drive them ourselves from initialize onward
            # (see _on_initialized / _pull_diagnostics_for).
            params["capabilities"]["textDocument"]["diagnostic"] = {
                "dynamicRegistration": False,
                "relatedDocumentSupport": True,
            }
            # refreshSupport tells the server it may ask us to re-pull via
            # workspace/diagnostic/refresh. Roslyn fires that once background
            # analysis finishes - which is when the first real errors appear -
            # so without this the errors often never show up.
            params["capabilities"]["workspace"]["diagnostics"] = {
                "refreshSupport": True,
            }
        rid = self.conn.request("initialize", params)
        self.pending[rid] = self._on_initialized

    def _on_initialized(self, result, error):
        if error:
            self.log(f"initialize failed: {error}")
            return
        # Honour the server's document-sync mode. textDocumentSync may be a bare
        # number or an object with a "change" field: 0 none, 1 full, 2 incremental.
        caps = (result or {}).get("capabilities", {}) or {}
        sync = caps.get("textDocumentSync", 1)
        self._sync_kind = sync.get("change", 1) if isinstance(sync, dict) else sync
        if self._verbose():
            self.log(f"server sync kind: {self._sync_kind} "
                     f"(0=none,1=full,2=incremental)")
        self.conn.notify("initialized", {})
        self.initialized = True
        # Turn on pull diagnostics now the server is up. We don't gate on the
        # server advertising a diagnosticProvider: Roslyn is known not to
        # advertise one (dotnet/roslyn#76624) yet still answers the requests.
        # A pull that comes back MethodNotFound flips this back off (see
        # _on_pull_diagnostics) so we don't keep asking a server that can't.
        self._pull_active = self.pull_diagnostics
        N10X.Editor.SetStatusBarText(f"{self.name}: ready")
        # Server-specific post-init step (e.g. the Roslyn C# server needs an
        # explicit "solution/open"). Run before opening documents so the server
        # already knows the workspace when the didOpen notifications arrive.
        if self.on_initialized:
            try:
                self.on_initialized(self)
            except Exception as e:
                self.log(f"on_initialized hook failed: {e}")
        try:
            for fn in N10X.Editor.GetOpenFiles() or []:
                if self.handles(fn):
                    self.did_open(fn)
        except Exception:
            pass

    def restart(self):
        self._teardown()
        fn = N10X.Editor.GetCurrentFilename()
        if self.handles(fn) and self.ensure_started(fn):
            self.log("restarted")

    def _teardown(self):
        if self.conn:
            self.conn.shutdown()
        self.conn = None
        self.initialized = False
        self.pending.clear()
        self.docs.clear()
        self.diagnostics.clear()
        self.disabled = False
        # Drop pull-diagnostics state with the connection; it re-arms on the
        # next initialize.
        self._pull_active = False
        self._diag_result_ids = {}
        self._diag_pending = set()
        self._diag_pull_due = 0.0
        # Watchers are per-connection (re-registered by the server on the next
        # initialize), so drop them with the server.
        self._watch_enabled = False
        self._watch_mtimes = {}

    # -- document sync -----------------------------------------------------

    def _ready(self):
        return bool(self.conn and self.conn.alive and self.initialized)

    def did_open(self, filename):
        if not self._ready():
            return
        uri = path_to_uri(filename)
        if uri in self.docs:
            return
        try:
            text = N10X.Editor.GetFileText(filename)
        except Exception:
            text = N10X.Editor.GetFileText()
        if text is None:
            text = ""
        self.docs[uri] = {"version": 1, "text": text, "filename": filename}
        self.conn.notify("textDocument/didOpen", {
            "textDocument": {"uri": uri, "languageId": self.language_id,
                             "version": 1, "text": text}})
        self._schedule_diag_pull(uri)

    def did_close(self, uri):
        doc = self.docs.pop(uri, None)
        self.diagnostics.pop(uri, None)
        if doc and self._ready():
            self.conn.notify("textDocument/didClose",
                             {"textDocument": {"uri": uri}})

    def sync_current(self, force=False):
        """Push the current buffer to the server as a full didChange if changed."""
        if not self._ready():
            return
        filename = N10X.Editor.GetCurrentFilename()
        if not self.handles(filename):
            return
        uri = path_to_uri(filename)
        if uri not in self.docs:
            self.did_open(filename)
            return
        text = N10X.Editor.GetFileText(filename)
        if text is None:
            return
        doc = self.docs[uri]
        if text == doc["text"]:
            return  # nothing changed; `force` only governs whether callers
            # request features, not whether we resend identical content.
        if self._sync_kind == 0:
            doc["text"] = text  # server doesn't want changes; just track locally
            return
        if self._sync_kind == 2:
            # Incremental: send only the edited range. Crucial for large files -
            # full-text resync on every keystroke is what makes typing lag.
            change = incremental_change(doc["text"], text)
            changes = [change] if change is not None else [{"text": text}]
        else:
            changes = [{"text": text}]
        doc["text"] = text
        doc["version"] += 1
        self.conn.notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": doc["version"]},
            "contentChanges": changes})
        # Push-diagnostics servers re-publish on their own after this didChange;
        # pull servers won't, so re-request for the edited doc (debounced).
        self._schedule_diag_pull(uri)

    def did_save(self, filename):
        if not self.handles(filename) or not self._ready():
            return
        self.sync_current(force=True)
        uri = path_to_uri(filename)
        if uri in self.docs:
            self.conn.notify("textDocument/didSave",
                             {"textDocument": {"uri": uri}})

    # -- request helpers ---------------------------------------------------

    def _doc_pos_params(self, pos=None):
        filename = N10X.Editor.GetCurrentFilename()
        if not self.handles(filename):
            return None
        x, y = N10X.Editor.GetCursorPos()
        if pos is not None:
            x = pos[0]
            y = pos[1]
            
        return {"textDocument": {"uri": path_to_uri(filename)},
                "position": {"line": y, "character": x}}

    def _send_request(self, method, params, handler):
        if not self._ready():
            self.log("server not ready")
            return None
        rid = self.conn.request(method, params)
        self.pending[rid] = handler
        return rid

    def _schedule_retry(self, action, delay=0.4):
        """Run `action` once on a later update tick. Used to re-issue a request
        that came back empty because the server hadn't finished analysing the
        file yet (common right after a file/workspace opens)."""
        self._retry_action = action
        self._retry_due = time.time() + delay

    # -- main-thread message pump -----------------------------------------

    def pump(self):
        if not self.conn:
            return
        for _ in range(200):  # bounded so we never stall the editor
            try:
                msg = self.conn.incoming.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle(msg)
            except Exception as e:
                self.log(f"error handling message: {e}")

    def _handle(self, msg):
        if msg.get("__lsp_internal__") == "exited":
            if self.initialized:
                self.log("server process exited")
            self.initialized = False
            return

        if "__lsp_stderr__" in msg:
            if self._verbose():
                self.log("stderr: " + msg["__lsp_stderr__"])
            return

        if "id" in msg and ("result" in msg or "error" in msg):
            handler = self.pending.pop(msg["id"], None)
            if handler:
                handler(msg.get("result"), msg.get("error"))
            return

        method = msg.get("method")
        if method is None:
            return
        if "id" in msg:
            self._handle_server_request(msg["id"], method, msg.get("params"))
        else:
            self._handle_notification(method, msg.get("params"))

    def _handle_server_request(self, rid, method, params):
        if method == "workspace/configuration":
            items = (params or {}).get("items", [])
            self.conn.respond(rid, [{} for _ in items])
        elif method == "workspace/workspaceFolders":
            self.conn.respond(rid, [{"uri": self.root_uri,
                                     "name": os.path.basename(self.root_path) or "root"}])
        elif method == "client/registerCapability":
            self._apply_registrations((params or {}).get("registrations", []))
            self.conn.respond(rid, None)
        elif method == "client/unregisterCapability":
            self._apply_unregistrations((params or {}).get("unregisterations", []))
            self.conn.respond(rid, None)
        elif method in ("workspace/diagnostic/refresh",
                        "workspace/semanticTokens/refresh",
                        "workspace/inlayHint/refresh",
                        "workspace/codeLens/refresh"):
            # Server signalled its results may be stale. Ack, and for diagnostics
            # re-pull every open doc - this is how Roslyn tells us that project
            # load / background analysis finished and errors are now available.
            self.conn.respond(rid, None)
            if method == "workspace/diagnostic/refresh":
                self._pull_all_open()
        else:
            # workDoneProgress/create, etc. - just ack.
            self.conn.respond(rid, None)

    def _apply_registrations(self, registrations):
        for reg in registrations or []:
            if reg.get("method") == "workspace/didChangeWatchedFiles":
                # The server wants us to tell it when workspace files change.
                # Enable our polling scan and seed the baseline so the first
                # scan only reports genuine changes, not the whole tree.
                if not self._watch_enabled:
                    self._watch_enabled = True
                    self._watch_mtimes = self._snapshot_watched_files()
                    self._last_watch_scan = time.time()
                if self._verbose():
                    self.log("file watching enabled (server registered "
                             "workspace/didChangeWatchedFiles)")

    def _apply_unregistrations(self, unregistrations):
        for reg in unregistrations or []:
            if reg.get("method") == "workspace/didChangeWatchedFiles":
                self._watch_enabled = False
                self._watch_mtimes = {}

    def _snapshot_watched_files(self):
        """Map every workspace file we handle to its mtime. Cheap enough to run
        on a few-second cadence; heavy/irrelevant directories are skipped. Used
        as the baseline for detecting create/change/delete between scans."""
        snap = {}
        root = self.root_path
        if not root or not os.path.isdir(root):
            return snap
        ignore = self.ignore_dirs
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune noisy directories in place so os.walk never descends them.
            dirnames[:] = [d for d in dirnames if d not in ignore]
            for fn in filenames:
                if not fn.endswith(self.extensions):
                    continue
                path = os.path.join(dirpath, fn)
                try:
                    snap[path] = os.path.getmtime(path)
                except OSError:
                    pass
        return snap

    def _scan_watched_files(self, now):
        """Diff the workspace against the last snapshot and tell the server
        about any created/changed/deleted files it cares about. This is what
        keeps ols's index correct for files edited while not open (e.g. a
        project-wide rename touching an unopened definition file)."""
        if not (self._watch_enabled and self._ready()):
            return
        if now - self._last_watch_scan < self._watch_interval:
            return
        self._last_watch_scan = now
        new = self._snapshot_watched_files()
        old = self._watch_mtimes
        changes = []
        for path, mtime in new.items():
            if path not in old:
                changes.append((path, 1))           # Created
            elif mtime != old[path]:
                changes.append((path, 2))           # Changed
        for path in old:
            if path not in new:
                changes.append((path, 3))           # Deleted
        self._watch_mtimes = new
        if not changes:
            return
        if self._verbose():
            self.log(f"watched files changed: {len(changes)} "
                     f"(notifying {self.name} server)")
        self.conn.notify("workspace/didChangeWatchedFiles", {
            "changes": [{"uri": path_to_uri(p), "type": t} for p, t in changes]})

    def _handle_notification(self, method, params):
        if method == "textDocument/publishDiagnostics":
            self._on_diagnostics(params or {})
        elif method in ("window/showMessage", "window/logMessage"):
            text = (params or {}).get("message", "")
            if text and self._verbose():
                self.log("server: " + text)

    # -- diagnostics -------------------------------------------------------

    def _min_severity(self):
        """Highest LSP severity number to display (1=Error..4=Hint); anything
        less severe (higher number) is hidden. Set "<name>.DiagnosticsLevel" to
        error|warning|info|hint. Default ("error") shows errors only."""
        val = (self.setting("DiagnosticsLevel", "error") or "error").strip().lower()
        return _SEVERITY_LEVELS.get(val, 1)

    def _visible_diags(self, diags):
        """Filter diagnostics down to those at or above the configured severity
        threshold. Missing severity is treated as Error (always shown)."""
        thr = self._min_severity()
        return [d for d in diags if d.get("severity", 1) <= thr]

    # -- pull diagnostics (opt-in; see pull_diagnostics) -------------------

    def _schedule_diag_pull(self, uri, delay=None):
        """Queue a debounced textDocument/diagnostic request for uri. No-op
        unless this client opted into pull diagnostics and the server is live."""
        if not (self._pull_active and uri):
            return
        self._diag_pending.add(uri)
        self._diag_pull_due = time.time() + (self._diag_pull_delay
                                             if delay is None else delay)

    def _flush_diag_pulls(self, now):
        """Send any queued diagnostic pulls once the debounce window elapses."""
        if not (self._pull_active and self._diag_pending and self._diag_pull_due):
            return
        if now < self._diag_pull_due:
            return
        self._diag_pull_due = 0.0
        pending = self._diag_pending
        self._diag_pending = set()
        for uri in pending:
            # Skip files that were closed while queued.
            if uri in self.docs:
                self._pull_diagnostics_for(uri)

    def _pull_diagnostics_for(self, uri):
        if not (self._pull_active and self._ready()):
            return
        params = {"textDocument": {"uri": uri}}
        prev = self._diag_result_ids.get(uri)
        if prev:
            params["previousResultId"] = prev
        rid = self.conn.request("textDocument/diagnostic", params)
        self.pending[rid] = lambda result, error, u=uri: \
            self._on_pull_diagnostics(u, result, error)

    def _pull_all_open(self):
        """Re-request diagnostics for every open document. Used when the server
        asks us to refresh (workspace/diagnostic/refresh) - e.g. Roslyn fires
        this once background analysis finishes, which is typically when the
        first real errors become available."""
        for uri in list(self.docs):
            self._schedule_diag_pull(uri, delay=0.0)

    def _on_pull_diagnostics(self, uri, result, error):
        if error:
            # -32601 = MethodNotFound: this server doesn't do pull diagnostics
            # after all, so stop asking (and rely on push, if it pushes).
            if isinstance(error, dict) and error.get("code") == -32601:
                self._pull_active = False
                self.log("server does not support pull diagnostics; disabling")
            elif self._verbose():
                self.log(f"diagnostic pull failed: {error}")
            return
        report = result or {}
        self._apply_diag_report(uri, report)
        # A full report may also carry diagnostics for related files (e.g. other
        # files affected by this edit). Apply those too.
        for ruri, rrep in (report.get("relatedDocuments") or {}).items():
            self._apply_diag_report(ruri, rrep or {})

    def _apply_diag_report(self, uri, report):
        """Fold one document diagnostic report into our diagnostic state.
        'full' replaces the file's diagnostics; 'unchanged' keeps them."""
        rid = report.get("resultId")
        if rid:
            self._diag_result_ids[uri] = rid
        if report.get("kind") == "unchanged":
            return
        self._on_diagnostics({"uri": uri,
                              "diagnostics": report.get("items", []) or []})

    def _on_diagnostics(self, params):
        uri = params.get("uri")
        if uri is None:
            return
        diags = params.get("diagnostics", []) or []
        self.diagnostics[uri] = diags
        errs = sum(1 for d in diags if d.get("severity") == 1)
        warns = sum(1 for d in diags if d.get("severity") == 2)
        cur = N10X.Editor.GetCurrentFilename()
        if cur and path_to_uri(cur) == uri:
            # Only summarise severities the user actually wants shown.
            parts = [f"{errs} error(s)"]
            if self._min_severity() >= 2:
                parts.append(f"{warns} warning(s)")
            N10X.Editor.SetStatusBarText(f"{self.name}: " + ", ".join(parts))
        self._last_status_line = -1  # force refresh on next cursor move
        self._publish_to_build_output()

    def _publish_to_build_output(self):
        """Render every known diagnostic into 10x's build output as MSVC-style
        compiler lines so they appear as navigable errors/warnings.

        publishDiagnostics replaces the full diagnostic set for one file at a
        time, so we clear and re-emit all files' diagnostics on each update.
        That keeps the build output in sync with the server without dropping
        entries for files other than the one that just changed.
        """
        if self.setting("Diagnostics") == "false":
            return
        try:
            N10X.Editor.ClearBuildOutput()
        except AttributeError:
            return  # older 10x without the build-output API; nothing to do
        lines = []
        for uri, diags in self.diagnostics.items():
            diags = self._visible_diags(diags)
            if not diags:
                continue
            path = uri_to_path(uri)
            for d in sorted(diags, key=lambda x: x.get("range", {})
                            .get("start", {}).get("line", 0)):
                start = d.get("range", {}).get("start", {})
                line = start.get("line", 0) + 1
                col = start.get("character", 0) + 1
                sev = _MSVC_SEVERITY.get(d.get("severity", 1), "error")
                code = d.get("code", "")
                code = f" {code}" if code not in ("", None) else ""
                src = d.get("source", "")
                src = f"{src}: " if src else ""
                # Collapse multi-line messages so each diagnostic is one line.
                msg = " ".join(str(d.get("message", "")).splitlines())
                # Visual Studio format: path(line,col): severity CODE: message
                lines.append(f"{path}({line},{col}): {sev}{code}: {src}{msg}")
        if lines:
            N10X.Editor.LogToBuildOutput("\n".join(lines) + "\n")
        try:
            N10X.Editor.ParseBuildOutput()
        except AttributeError:
            pass

    def show_line_diagnostic(self):
        if self.setting("Diagnostics") == "false":
            return
        filename = N10X.Editor.GetCurrentFilename()
        if not self.handles(filename):
            return
        diags = self._visible_diags(self.diagnostics.get(path_to_uri(filename)) or [])
        if not diags:
            return
        _, y = N10X.Editor.GetCursorPos()
        if y == self._last_status_line:
            return
        for d in diags:
            rng = d.get("range", {})
            start = rng.get("start", {}).get("line", -1)
            end = rng.get("end", {}).get("line", start)
            if start <= y <= end:
                sev = _SEVERITY.get(d.get("severity", 1), "Info")
                N10X.Editor.SetStatusBarText(
                    f"{self.name} {sev}: {d.get('message', '').splitlines()[0]}")
                self._last_status_line = y
                return

    def show_all_diagnostics(self):
        filename = N10X.Editor.GetCurrentFilename()
        if not filename:
            return
        # Only respond for files this client handles. Several language clients
        # register the same command/intercept hooks, so a single "show
        # diagnostics" reaches all of them; without this guard the clients that
        # don't handle the current file (e.g. JaiLSP on a .py file) would each
        # overwrite the status bar with their own "no diagnostics" message.
        if not self.handles(filename):
            return
        diags = self._visible_diags(self.diagnostics.get(path_to_uri(filename), []))
        if not diags:
            N10X.Editor.SetStatusBarText(f"{self.name}: no diagnostics")
            return
        self.log(f"Diagnostics for {os.path.basename(filename)}:")
        for d in sorted(diags, key=lambda x: x.get("range", {})
                        .get("start", {}).get("line", 0)):
            line = d.get("range", {}).get("start", {}).get("line", 0) + 1
            sev = _SEVERITY.get(d.get("severity", 1), "Info")
            src = d.get("source", "")
            src = f"{src}: " if src else ""
            self.log(f"  L{line} [{sev}] {src}{d.get('message', '')}")

    # -- feature response handlers ----------------------------------------

    def _on_completion(self, result, error, rid=None):
        # Ignore responses from superseded completion requests (see
        # _request_completion) so a late, stale reply can't replace the list.
        if rid is not None and rid != self._last_completion_id:
            if self._verbose():
                self.log(f"completion: ignoring stale response (req {rid}, "
                         f"latest {self._last_completion_id})")
            return
        # This is the reply to the newest request: nothing is in flight now.
        self._completion_inflight = False
        # Drop the reply if the editing point moved since we asked. This is the
        # race fix for accepting a suggestion: the accept inserts text and moves
        # the cursor, and a slightly-late completion reply would otherwise pop the
        # list straight back up. Unlike the cursor-move guard this needs no
        # ordering between events - we simply compare positions when the reply
        # actually arrives.
        if self._completion_req_pos is not None:
            try:
                if N10X.Editor.GetCursorPos() != self._completion_req_pos:
                    if self._verbose():
                        self.log("completion: cursor moved since request; dropping reply")
                    return
            except Exception:
                pass
        if error:
            self.log(f"completion error: {error}")
            return
        if result is None:
            if self._verbose():
                self.log("completion: null result")
            return
        items = result.get("items", result) if isinstance(result, dict) else result
        if not items:
            if self._verbose():
                self.log("completion: 0 items returned by server")
            if self._autocomplete_visible:
                self._hide_autocomplete()
            return
        # Order by the server's relevance ranking (sortText). Servers like
        # rust-analyzer encode "most relevant first" there; falling back to the
        # label keeps a stable order for items that omit it.
        prefix = self._line_prefix()
        word = self._completion_word().lower()
        # Narrow to items that match what's been typed after the trigger. Many
        # servers (ols, rust-analyzer) return the whole member/scope set after a
        # "." and expect the client to filter as the user types. Match against
        # filterText (the field intended for this) when present, else the label.
        if word:
            def _match(it):
                return (it.get("filterText") or it.get("label") or "").lower()
            items = [it for it in items if _match(it).startswith(word)]
        # Order by the server's relevance ranking (sortText) so the closest
        # match - e.g. "found" - sits at the top; label breaks ties stably.
        items = sorted(items, key=lambda it: (it.get("sortText") is None,
                                              it.get("sortText") or "",
                                              it.get("label") or ""))
        limit = self._max_results()
        if self._verbose():
            try:
                x, y = N10X.Editor.GetCursorPos()
            except Exception:
                x, y = ("?", "?")
            self.log(f"completion: {len(items)} items after filter (cap {limit}); "
                     f"cursor=({x},{y}) word={word!r} line_prefix={prefix!r}")
        labels, seen = [], set()
        for it in items:
            text = self._completion_full_text(it)
            if self._verbose() and len(labels) < 5:
                self.log(f"   item label={it.get('label')!r} -> insert={text!r}")
            if text and text not in seen:
                seen.add(text)
                labels.append(text)
                if len(labels) >= limit:
                    break
        if not labels:
            # Nothing matches what's typed now (e.g. the word was edited down to
            # a prefix no item shares). Don't leave a stale list on screen.
            if self._autocomplete_visible:
                self._hide_autocomplete()
            return
        self._show_autocomplete(labels)

    def _max_results(self):
        """Maximum completion items to show (servers like rust-analyzer return
        the whole scope). Configurable via "<name>.MaxResults"."""
        try:
            return max(1, int(self.setting("MaxResults", "50")))
        except (TypeError, ValueError):
            return 50

    def _line_prefix(self):
        """Text on the current line to the left of the cursor."""
        try:
            line = N10X.Editor.GetCurrentLine() or ""
        except Exception:
            return ""
        x, _ = N10X.Editor.GetCursorPos()
        return line[:x]

    def _completion_word(self):
        """The identifier fragment immediately before the cursor (e.g. "f" in
        "tile.f"). Used to filter the server's items down to what the user has
        actually typed. Empty right after a trigger char like "." (so the full
        member set is shown)."""
        prefix = self._line_prefix()
        i = len(prefix)
        while i > 0 and (prefix[i - 1].isalnum() or prefix[i - 1] == "_"):
            i -= 1
        return prefix[i:]

    def _completion_full_text(self, item):
        """The complete text to insert for an item - the whole word/qualifier
        (e.g. "found", "UpdateCursorMode"), with no stripping. 10x replaces the
        partially-typed word for us (see _completion_replace_pos), so it wants
        the full suggestion rather than just the not-yet-typed remainder."""
        edit = item.get("textEdit") or {}
        return (edit.get("newText") or item.get("insertText")
                or item.get("label") or "")

    def _completion_replace_pos(self):
        """(x, y) where the word being completed begins. Passed to
        ShowAutocomplete so that, on accept, 10x replaces the partially-typed
        word with the chosen full suggestion instead of inserting at the cursor
        (which would duplicate the typed prefix, e.g. "tile.ffound")."""
        x, y = N10X.Editor.GetCursorPos()
        return (x - len(self._completion_word()), y)

    def _show_autocomplete(self, labels):
        """Call 10x's ShowAutocomplete, tolerant of signature/format differences.

        We pass the start of the word under the cursor as the position so 10x
        replaces that word with the full suggestion.""" 
        pos = self._completion_replace_pos()
        last_err = None
        try:
            N10X.Editor.ShowAutocomplete(labels, pos)
            self._autocomplete_visible = True
            return True
        except Exception as e:
            last_err = e
        self.log(f"ShowAutocomplete failed for all formats: {last_err}")
        return False

    def _hide_autocomplete(self):
        """Dismiss the autocomplete popup. Completion is word-scoped, so a
        word-breaking key (space, punctuation, newline) ends the current
        identifier and the in-progress list is no longer relevant. 10x doesn't
        close our popup on its own in that case, so we do it explicitly.

        Also cancels any pending as-you-type request and drops the newest
        in-flight request id, so a completion response that arrives after the
        word ended can't re-open the list a moment later."""
        self._completion_due = 0.0
        self._last_completion_id = None
        self._completion_inflight = False
        if not self._autocomplete_visible:
            return  # nothing on screen to dismiss
        self._autocomplete_visible = False
        # We know ShowAutocomplete exists; an empty list dismisses the popup.
        try:
            N10X.Editor.ShowAutocomplete([])
            return
        except Exception:
            pass

    def _show_hover_box(self, text, pos):
        """Display `text` in 10x's inline hover box at `pos` (an (x, y) cursor
        position). Falls back to a message box / status bar on older builds that
        predate the ShowHoverBox API."""
        if pos is None:
            try:
                pos = N10X.Editor.GetCursorPos()
            except Exception:
                pos = None
        try:
            N10X.Editor.ShowHoverBox(pos, text)
            return
        except AttributeError:
            pass  # older 10x without ShowHoverBox; fall back below
        except Exception as e:
            self.log(f"ShowHoverBox failed: {e}")
        try:
            N10X.Editor.ShowMessageBox(self.name, text)
        except Exception:
            N10X.Editor.SetStatusBarText(f"{self.name}: " + " ".join(text.splitlines()))

    def _on_hover(self, result, error, pos=None):
        text = strip_markdown_escapes(strip_markup_html(strip_code_fences(extract_markup(result.get("contents"))))) if result else ""
        if not text.strip():
            N10X.Editor.SetStatusBarText(f"{self.name}: no hover info")
            return
        self._show_hover_box(text, pos)

    def _on_signature(self, result, error, pos=None):
        if error or not result or not result.get("signatures"):
            N10X.Editor.SetStatusBarText(f"{self.name}: no signature")
            return
        sigs = result["signatures"]
        active = result.get("activeSignature", 0) or 0
        sig = sigs[active] if active < len(sigs) else sigs[0]
        label = sig.get("label", "")
        if not label.strip():
            N10X.Editor.SetStatusBarText(f"{self.name}: no signature")
            return
        self._show_hover_box(label, pos)

    def _on_definition(self, result, error, retry=0):
        loc = first_location(result)
        if not loc:
            # rust-analyzer (and other servers) answer null until the file's
            # crate/workspace has finished loading, which is why a cold
            # go-to-definition "only works after editing the file". Re-issue the
            # request a couple of times before giving up.
            if not error and retry < 2:
                self._schedule_retry(
                    lambda r=retry: self.goto_definition(_retry=r + 1),
                    delay=0.4 * (retry + 1))
                return
            N10X.Editor.SetStatusBarText(f"{self.name}: no definition found")
            return
        uri, rng = loc
        start = rng.get("start", {})
        pos = (start.get("character", 0), start.get("line", 0))
        path = uri_to_path(uri)
        # Pass the target position straight to OpenFile so the file opens at the
        # definition. Opening first and then moving the cursor records the top
        # of the file (the initial cursor spot) in the cursor history, which
        # clutters jump-back navigation.
        N10X.Editor.OpenFile(path, N10X.Editor.GetCurrentPanelGridPos(), pos)
        N10X.Editor.ScrollCursorIntoView()

    def _on_references(self, result, error):
        if error or not result:
            N10X.Editor.SetStatusBarText(f"{self.name}: no references found")
            return
        # Build (filename, line, index, length) tuples for ShowSymbolReferences.
        # Coordinates are 0-based to match the rest of 10x's API (GetCursorPos /
        # OpenFile). `length` is the symbol's width when its range stays on one
        # line; 0 lets 10x work it out (e.g. multi-line or zero-width ranges).
        seen, items = set(), []
        for loc in result:
            path = uri_to_path(loc.get("uri", ""))
            rng = loc.get("range", {})
            start = rng.get("start", {})
            line = start.get("line", 0)
            index = start.get("character", 0)
            key = (path, line, index)
            if key in seen:
                continue
            seen.add(key)
            end = rng.get("end", {})
            length = (end.get("character", index) - index
                      if end.get("line", line) == line else 0)
            if length < 0:
                length = 0
            items.append((path, line, index, length))
        if not items:
            N10X.Editor.SetStatusBarText(f"{self.name}: no references found")
            return
        try:
            N10X.Editor.ShowSymbolReferences(items)
        except AttributeError:
            # Older 10x without ShowSymbolReferences: log to the output panel.
            self.log(f"{len(items)} reference(s):")
            for path, line, index, _ in items:
                self.log(f"  {path}:{line + 1}:{index + 1}")
            N10X.Editor.SetStatusBarText(
                f"{self.name}: {len(items)} reference(s) - see output panel")
        except Exception as e:
            self.log(f"ShowSymbolReferences failed: {e}")

    # -- public commands (wire these to keybindings) ----------------------

    def _request_completion(self):
        params = self._doc_pos_params()
        if params is None:
            if self._verbose():
                self.log("completion skipped: current file not handled / no params")
            return
        params["context"] = {"triggerKind": 1}  # Invoked
        if self._verbose():
            p = params["position"]
            self.log(f"requesting completion at line {p['line']}, char {p['character']}")
        rid = self._send_request("textDocument/completion", params, self._on_completion)
        # Only the newest completion request's response should be shown; rapid
        # typing can leave older requests in flight whose (slower, less-specific)
        # replies would otherwise land later and clobber the right list. Tag the
        # handler with its id so _on_completion can drop stale responses.
        self._last_completion_id = rid
        self._completion_inflight = rid is not None
        # Remember where we asked. If the cursor has moved by the time the reply
        # lands (the user accepted a suggestion, clicked away or backspaced), the
        # reply is stale and must not re-open the popup - see _on_completion.
        try:
            self._completion_req_pos = N10X.Editor.GetCursorPos()
        except Exception:
            self._completion_req_pos = None
        if rid is not None:
            self.pending[rid] = (lambda res, err, _id=rid:
                                 self._on_completion(res, err, _id))

    def complete(self):
        self.sync_current(force=True)
        self._request_completion()

    def status(self):
        """Log the current client state to the output panel (for debugging)."""
        fn = N10X.Editor.GetCurrentFilename()
        self.log("---- status ----")
        self.log(f"  enabled         : {self.is_enabled()} "
                 f"(setting: {self.setting('Enabled') or '(unset=off)'})")
        self.log(f"  autocomplete    : {self.setting('AutoComplete') or '(unset=true)'}")
        self.log(f"  commenting      : {self.commenting_enabled()} "
                 f"(setting: {self.setting('Commenting') or '(unset=on)'}, "
                 f"token: {self.line_comment or 'none'})")
        self.log(f"  server argv     : {self._server_argv()}")
        self.log(f"  connection      : {'alive' if (self.conn and self.conn.alive) else 'none/dead'}")
        self.log(f"  initialized     : {self.initialized}")
        self.log(f"  root            : {self.root_path}")
        self.log(f"  current file    : {fn}")
        self.log(f"  handled         : {self.handles(fn)}")
        self.log(f"  open documents  : {len(self.docs)}")

    def hover(self, pos=None):
        params = self._doc_pos_params(pos)
        if params is None:
            return
        self.sync_current(force=True)
        # If pos is none capture where the request was made so the async reply can place the
        # hover box there (the cursor may move before the server answers).
        if pos is None:
            pos = N10X.Editor.GetCursorPos()
        self._send_request("textDocument/hover", params,
                           lambda r, e: self._on_hover(r, e, pos))

    def signature_help(self):
        params = self._doc_pos_params()
        if params is None:
            return
        self.sync_current(force=True)
        pos = N10X.Editor.GetCursorPos()
        self._send_request("textDocument/signatureHelp", params,
                           lambda r, e: self._on_signature(r, e, pos))

    def goto_definition(self, _retry=0):
        params = self._doc_pos_params()
        if params is None:
            return
        self.sync_current(force=True)
        self._send_request("textDocument/definition", params,
                           lambda r, e: self._on_definition(r, e, _retry))

    def find_references(self):
        params = self._doc_pos_params()
        if params is None:
            return
        params["context"] = {"includeDeclaration": True}
        self.sync_current(force=True)
        self._send_request("textDocument/references", params, self._on_references)

    # -- comment toggling --------------------------------------------------
    # Commenting is a purely editor-side text edit (LSP has no comment API), so
    # these work without a running server. They act on whole lines: the current
    # line, or every line touched by the selection.

    def commenting_enabled(self):
        """Whether the comment commands (ToggleComment / CommentLine /
        UncommentLine) are active: the language defined a line-comment token and
        the "<name>.Commenting" setting isn't turned off. Default on; set
        "<name>.Commenting: false" to hand commenting back to 10x's built-in."""
        if not self.line_comment:
            return False
        return self.setting("Commenting", "true").strip().lower() != "false"

    @staticmethod
    def _split_eol(line):
        """Split a line from GetLine into (content, trailing_eol) so we can
        rewrite the content and put the original "\\r\\n"/"\\n" back verbatim."""
        i = len(line)
        while i > 0 and line[i - 1] in "\r\n":
            i -= 1
        return line[:i], line[i:]

    def _comment_line_range(self):
        """(y0, y1) inclusive line range a comment command applies to: the
        selection if there is one, otherwise the single cursor line. A selection
        that ends at column 0 of a line doesn't include that line."""
        try:
            (sx, sy), (ex, ey) = N10X.Editor.GetCursorSelection()
        except Exception:
            _, y = N10X.Editor.GetCursorPos()
            return y, y
        if (sy, sx) > (ey, ex):
            sx, sy, ex, ey = ex, ey, sx, sy
        if (sx, sy) == (ex, ey):
            return sy, sy  # empty selection == just the cursor line
        if ey > sy and ex == 0:
            ey -= 1
        return sy, ey

    def toggle_comment(self):
        """Comment or uncomment the current line / selected lines - the ones
        already commented decide the direction (10x's ToggleComment)."""
        self._apply_comment("toggle")

    def comment_line(self):
        """Comment the current line / selected lines (10x's CommentLine)."""
        self._apply_comment("comment")

    def uncomment_line(self):
        """Uncomment the current line / selected lines (10x's UncommentLine)."""
        self._apply_comment("uncomment")

    def _apply_comment(self, mode):
        """Add or remove the line-comment token across the target line range.
        `mode` is "comment", "uncomment" or "toggle". No-op (the caller lets
        10x's default run) when commenting is disabled or the file isn't ours."""
        if not self.commenting_enabled():
            return
        if not self.handles(N10X.Editor.GetCurrentFilename()):
            return
        token = self.line_comment
        y0, y1 = self._comment_line_range()
        rows = []
        for y in range(y0, y1 + 1):
            content, eol = self._split_eol(N10X.Editor.GetLine(y) or "")
            rows.append([y, content, eol])
        nonblank = [c for _, c, _ in rows if c.strip()]
        if not nonblank:
            return
        if mode == "toggle":
            # Comment unless every non-blank line is already commented.
            commenting = not all(c.lstrip().startswith(token) for c in nonblank)
        else:
            commenting = (mode == "comment")
        # Comment at the shallowest indent so the tokens line up with the
        # least-indented code in the block.
        indent = min(len(c) - len(c.lstrip()) for c in nonblank)
        N10X.Editor.PushUndoGroup()
        N10X.Editor.BeginTextUpdate()
        try:
            for y, content, eol in rows:
                if not content.strip():
                    continue  # leave blank lines untouched
                stripped = content.lstrip()
                if commenting:
                    if stripped.startswith(token):
                        continue  # already commented; don't double it up
                    new = content[:indent] + token + " " + content[indent:]
                else:
                    if not stripped.startswith(token):
                        continue  # not commented; nothing to strip
                    ws = content[:len(content) - len(stripped)]
                    rest = stripped[len(token):]
                    if rest.startswith(" "):
                        rest = rest[1:]
                    new = ws + rest
                N10X.Editor.SetLine(y, new + eol)
        finally:
            N10X.Editor.EndTextUpdate()
            N10X.Editor.PopUndoGroup()

    # -- 10x event hooks ---------------------------------------------------

    def _on_file_opened(self, filename=None, *args):
        try:
            if not filename:
                filename = N10X.Editor.GetCurrentFilename()
            if self.handles(filename) and self.ensure_started(filename):
                self.did_open(filename)
        except Exception as e:
            self.log(f"on_file_opened error: {e}")

    def _on_post_save(self, filename=None, *args):
        try:
            if not filename:
                filename = N10X.Editor.GetCurrentFilename()
            self.did_save(filename)
        except Exception as e:
            self.log(f"on_post_save error: {e}")

    def _on_char_key(self, ch=None, *args):
        # As-you-type completion: schedule a (debounced) completion request when
        # an identifier char or a trigger char is typed. Each keystroke pushes
        # the due time forward, so a burst of typing fires a single request once
        # the user pauses for _auto_delay seconds.
        if not ch or self.setting("AutoComplete") == "false":
            return
        # Only schedule completion when the focused file is one we handle;
        # otherwise typing in another language's file (e.g. after switching
        # workspaces) would queue requests that just get rejected.
        try:
            if not self.handles(N10X.Editor.GetCurrentFilename()):
                return
        except Exception:
            return
        if ch in self.trigger_chars or ch.isalnum() or ch == "_":
            self._completion_due = time.time() + self._auto_delay
        else:
            # A word-breaking char (space, punctuation, etc.) ends the current
            # identifier, so the in-progress completion list no longer applies -
            # dismiss it (completion is word-scoped).
            self._hide_autocomplete()

    def _on_cursor_moved(self, *args):
        try:
            try:
                cur = N10X.Editor.GetCursorPos()
            except Exception:
                cur = None
            try:
                line = N10X.Editor.GetCurrentLine() or ""
            except Exception:
                line = None
            prev = self._last_cursor_pos
            prev_line = self._last_line_text
            self._last_cursor_pos = cur
            self._last_line_text = line
            # Keep the popup tied to the word being edited; react to how the
            # cursor moved (only while something completion-related is live). The
            # key distinction is an *edit* (the line's text changed) versus a pure
            # cursor *move* (arrow keys, click), which must leave the list alone:
            #   - moved to another line: abandon the word, dismiss.
            #   - same line, no text change: caret moved through the text without
            #     editing it - leave the list exactly as-is (don't re-filter or
            #     dismiss); the suggestions still belong to that word.
            #   - same line, edited, +1: forward typing, left to _on_char_key
            #     (re-arms on word chars, dismisses on word-breakers).
            #   - same line, edited, leftward: backspace/delete - stay open while a
            #     word remains and re-arm a debounced re-filter to track the
            #     shorter prefix; dismiss only once the whole word is gone.
            #   - same line, edited, bigger jump: accepting a suggestion (inserts
            #     the remainder) or a multi-char edit - the list no longer applies.
            if (prev is not None and cur is not None and cur != prev
                    and (self._completion_due or self._completion_inflight
                         or self._autocomplete_visible)):
                same_line = (cur[1] == prev[1])
                dx = cur[0] - prev[0]
                edited = (prev_line is not None and line is not None
                          and line != prev_line)
                if not same_line:
                    self._hide_autocomplete()
                elif not edited:
                    pass  # caret moved through the word; leave the list untouched
                elif dx == 1:
                    pass  # forward typing
                elif dx < 0:
                    if self._completion_word():
                        self._completion_due = time.time() + self._auto_delay
                    else:
                        self._hide_autocomplete()  # entire word deleted
                else:
                    self._hide_autocomplete()  # accept / multi-char insert
            self.show_line_diagnostic()
        except Exception:
            pass

    def _on_update(self, *args):
        try:
            self.pump()
            now = time.time()
            # Deferred re-request (e.g. a goto-definition that came back empty
            # while the server was still indexing) fires as soon as it's due.
            if self._retry_action and now >= self._retry_due:
                action = self._retry_action
                self._retry_action = None
                self._retry_due = 0.0
                if self._ready():
                    action()
            # Fire any debounced diagnostic pulls (pull-diagnostics clients only).
            if self._ready():
                self._flush_diag_pulls(now)
            # Completion fires as soon as it's due (not throttled).
            if (self._ready() and self._completion_due
                    and now >= self._completion_due):
                self._completion_due = 0.0
                self.sync_current(force=True)
                self._request_completion()
                self._last_sync = now
                return
            # Throttled housekeeping. Runs even before the server is ready so a
            # workspace whose Python files are already open gets picked up
            # without a file-open event (e.g. switching to a restored tab).
            if now - self._last_sync >= self._sync_interval:
                self._last_sync = now
                self._refresh_verbose()
                self._reconcile_open_files(now)
                if self._ready():
                    self.sync_current()
                    # Self-throttled (no-op unless this server registered a
                    # watcher and the scan interval has elapsed). Of our current
                    # servers only ols registers one; rust-analyzer/pylsp don't.
                    self._scan_watched_files(now)
        except Exception as e:
            self.log(f"update error: {e}")

    def _reconcile_open_files(self, now):
        """Keep the server's open-document set in step with the editor's open
        handled files: start the server if needed, open newly-seen files and
        close ones no longer open. This makes startup robust to missed
        file-open events and to files already open when the workspace loads."""
        try:
            open_handled = [f for f in (N10X.Editor.GetOpenFiles() or [])
                            if self.handles(f)]
        except Exception:
            return
        if not open_handled:
            # Nothing we handle is open anymore (e.g. the user switched to a
            # different workspace/language). Shut the server down rather than
            # leave it running in the background against a workspace we've left.
            # It will be relaunched - with the correct root - when one of our
            # files is opened again.
            if self.conn:
                self.log("no handled files open; shutting server down")
                self._teardown()
            return
        if not self._ready():
            # Bring the server up if a handled file is open; _on_initialized
            # opens the full set once it finishes initializing. Backed off so a
            # missing/failing server isn't relaunched every tick.
            if open_handled and now >= self._next_start_attempt:
                self._next_start_attempt = now + 3.0
                self.ensure_started(open_handled[0])
            return
        open_uris = set()
        for fn in open_handled:
            uri = path_to_uri(fn)
            open_uris.add(uri)
            if uri not in self.docs:
                self.did_open(fn)
        for uri in list(self.docs.keys()):
            if uri not in open_uris:
                self.did_close(uri)

    def _on_exit(self):
        try:
            self._teardown()
        except Exception:
            pass

    # Command-panel commands, keyed by their normalised (lowercased, spaces and
    # underscores removed) name. Lets you drive the client by typing
    # "<name> <command>" into the 10x command panel - no keybinding needed.
    def _command_table(self):
        return {
            "status": self.status,
            "complete": self.complete,
            "completion": self.complete,
            "hover": self.hover,
            "signature": self.signature_help,
            "signaturehelp": self.signature_help,
            "definition": self.goto_definition,
            "gotodefinition": self.goto_definition,
            "references": self.find_references,
            "findreferences": self.find_references,
            "diagnostics": self.show_all_diagnostics,
            "showdiagnostics": self.show_all_diagnostics,
            "restart": self.restart,
            "comment": self.toggle_comment,
            "togglecomment": self.toggle_comment,
            "commentline": self.comment_line,
            "uncommentline": self.uncomment_line,
        }

    def _on_command_panel(self, text=None, *args):
        try:
            if not text:
                return False
            low = text.strip().lower()
            prefix = self.name.lower()
            if not low.startswith(prefix):
                return False
            rest = low[len(prefix):]
            # Only handle the friendly "<name> <command>" form (space/colon/dash
            # separator). A bare "<Name>_<Func>" string is one of our exported
            # functions, which 10x executes directly from the command panel - if
            # we matched it here too the command would run twice (the doubled
            # find-references output).
            if rest and rest[0] not in " :-":
                return False
            cmd = rest.lstrip(" :_-").replace(" ", "").replace("_", "")
            fn = self._command_table().get(cmd)
            if fn is None:
                self.log(f"unknown command '{text}'. Try: {self.name} status | "
                         f"complete | hover | signature | definition | references | "
                         f"diagnostics | restart")
                return True
            fn()
            return True
        except Exception as e:
            self.log(f"command panel error: {e}")
            return True

    # 10x's built-in command names (as passed to an intercept handler) mapped to
    # our LSP feature, keyed by the normalised (lowercased, spaces removed) name.
    # Intercepting these makes the editor's default key bindings (e.g. F12 for
    # GoToSymbolDefinition, Ctrl+Space for Autocomplete) drive the language
    # server for files we handle, with no per-language key binding needed.
    # GoToSymbolDefinitionUnderMouse reuses the goto_definition handler: 10x moves
    # the caret to the symbol under the mouse before the command fires, so reading
    # the cursor position (as goto_definition does) targets the right symbol.
    def _intercept_table(self):
        table = {
            "gotosymboldefinition": self.goto_definition,
            "gotosymboldefinitionundermouse": self.goto_definition,
            "findsymbolreferences": self.find_references,
            "autocomplete": self.complete,
            "showfunctionargsinfo": self.signature_help,
            "showsymbolinfo": self.hover,
        }
        # Comment commands only when commenting is enabled (a token is
        # configured and "<name>.Commenting" isn't off); otherwise leave 10x's
        # built-in commenting in charge.
        if self.commenting_enabled():
            table["togglecomment"] = self.toggle_comment
            table["commentline"] = self.comment_line
            table["uncommentline"] = self.uncomment_line
        return table

    def _on_intercept_command(self, command=None, *args):
        """Intercept a built-in editor command. Returns True when we've handled
        it (so 10x suppresses its default behaviour), else a falsey value so the
        command runs normally. We only claim a command for files we handle while
        the server is ready - otherwise the editor's own behaviour stands."""
        try:
            if not command or self.setting("InterceptCommands") == "false":
                return False
            fn = self._intercept_table().get(command.replace(" ", "").lower())
            if fn is None:
                return False
            if not self.handles(N10X.Editor.GetCurrentFilename()):
                return False
            # The comment commands are pure text edits and need no server; every
            # other intercepted command does, so let 10x's default run (rather
            # than swallow the key and do nothing) until the server is up.
            offline = (self.toggle_comment, self.comment_line, self.uncomment_line)
            if fn not in offline and not self._ready():
                return False
            if self._verbose():
                self.log(f"intercepting command: {command}")
            fn()
            return True
        except Exception as e:
            self.log(f"intercept command error: {e}")
            return False
    
    def _on_mouse_hover(self, pos):
        self.hover(pos)

    def _check_parser_conflict(self):
        """Warn if 10x's built-in parser is set to handle one of our extensions.

        10x parses a configured set of file extensions itself (the
        "ParserExtensions" setting) to drive its own completion / symbol
        navigation. Some are there by default - notably ".cs" - and when the
        built-in parser and the language server both claim a file they compete
        (duplicate or wrong completions, symbol jumps going to the parser's
        index instead of the server's). We can't edit the setting for the user,
        so we just flag the overlap and tell them to remove it. Main-thread only
        (reads a setting); call from register()."""
        raw = N10X.Editor.GetSetting("ParserExtensions") or ""
        if not raw:
            return
        # Always a comma-separated list, e.g. ".cpp, .cs,.h,.inl, .hlsl" - entries
        # may carry surrounding spaces (including a space before the dot). Split
        # on commas, strip each entry, and compare as dot-less lowercase tokens.
        have = {tok.strip().lstrip(".").lower()
                for tok in raw.split(",") if tok.strip()}
        clash = sorted(e.lstrip(".").lower() for e in self.extensions
                       if e.lstrip(".").lower() in have)
        if clash:
            exts = ", ".join("." + c for c in clash)
            self.log("WARNING: 10x's built-in parser also handles " + exts +
                     " (the ParserExtensions setting). Remove " + exts +
                     " from ParserExtensions so " + self.name + " drives these "
                     "files - otherwise the built-in parser competes with the "
                     "language server (duplicate/incorrect completion and symbol "
                     "navigation).")

    def register(self):
        """Wire this client into the 10x editor events. Call once, on the main
        thread (e.g. via N10X.Editor.CallOnMainThread).

        Opt-in: if "<name>.Enabled" is not "true" we register nothing at all, so
        a client the user hasn't turned on has zero impact - no event hooks, no
        server, no command/intercept handlers. Enabling it takes effect on the
        next 10x restart (when this runs again)."""
        if not self.is_enabled():
            self.log(f"disabled; set {self.name}.Enabled: true to turn it on "
                     f"(then restart 10x)")
            return
        self._refresh_verbose()
        self._check_parser_conflict()
        N10X.Editor.AddOnFileOpenedFunction(self._on_file_opened)
        N10X.Editor.AddPostFileSaveFunction(self._on_post_save)
        N10X.Editor.AddOnCharKeyFunction(self._on_char_key)
        N10X.Editor.AddCursorMovedFunction(self._on_cursor_moved)
        N10X.Editor.AddUpdateFunction(self._on_update)
        N10X.Editor.AddExitingFunction(self._on_exit)
        try:
            N10X.Editor.AddCommandPanelHandlerFunction(self._on_command_panel)
        except Exception as e:
            self.log(f"command panel registration failed: {e}")
        try:
            N10X.Editor.AddInterceptCommandFunction(self._on_intercept_command)
        except Exception as e:
            self.log(f"command interception unavailable: {e}")
        try:
            cur = N10X.Editor.GetCurrentFilename()
            if self.handles(cur) and self.ensure_started(cur):
                self.did_open(cur)
        except Exception:
            pass
        try:
            N10X.Editor.AddSymbolMouseHoverFunction(self._on_mouse_hover)
        except Exception as e:
            pass
        self.log(f"registered (server: {' '.join(self._server_argv())})")
