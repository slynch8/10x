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
#                           ShowFunctionArgsInfo, ShowSymbolInfo, FindFunction,
#                           FindSymbol, and - when the language defines a
#                           comment token - ToggleComment /
#                           CommentLine / UncommentLine) so the default key
#                           bindings drive the language server for files we
#                           handle. Default true; set "false" to require the
#                           per-language <Name>_* functions instead.
#     <name>.SignatureHelp  "true"/"false" - put 10x's function-args box up when
#                           you type a call's "(" (default true). It is never
#                           re-opened by the cursor moving back between the
#                           parentheses - ShowFunctionArgsInfo does that on
#                           demand. Set "false" for on demand only.
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
#     <name>.FuzzyComplete  "true"/"false" - match completion items on a
#                           subsequence of what you've typed rather than a
#                           literal prefix, so "gcp" finds "GetCursorPos" and
#                           "updcur" finds "UpdateCursorMode" (default true;
#                           set "false" for prefix matching only).
#                           Matches rank best-first: prefix beats word-boundary
#                           (camelCase / "_") beats mid-word, and runs of
#                           adjacent characters beat scattered ones.
#     <name>.SymbolCache    "true"/"false" - keep a project-wide symbol cache
#                           for the find-symbol panel (default true). The panel
#                           filters the list it is given, so it has to be handed
#                           every symbol in the project each time it opens -
#                           which is why the list is cached - filled shortly
#                           after the server starts, so the first FindSymbol
#                           opens on a full list. Set "false" if you
#                           would rather not pay the memory (a copy of every
#                           symbol in the project) or the background refreshes:
#                           the find-symbol feature then turns off with it
#                           (FindSymbol, ListSymbols and RefreshSymbols all just
#                           say so in the status bar) and only the explicit
#                           "<name> symbols <text>" search remains.
#     <name>.SymbolCacheSeconds  How long that cache stays fresh, in seconds
#                           (default 60): once older it is still served
#                           instantly, then refreshed in the background (a save
#                           refreshes it too). 0 keeps find-symbol working but
#                           holds nothing between opens - every open then waits
#                           on the server, and RefreshSymbols has nothing to
#                           rebuild. Ignored when SymbolCache is "false".
#     <name>.LogVerbose     "true"/"false" - log server traffic to the output
#                           panel (default false)
#
# Threading: a background thread only reads/parses the server's stdout. Every
# N10X.Editor.* call happens on the main thread inside the update loop, so the
# editor is never blocked waiting on the server. Anything reached from pump() is
# therefore on the editor's critical path and must stay cheap - responses over
# MAX_RESPONSE_BYTES are dropped unparsed for exactly this reason, and a reply
# that needs real work done to it (workspace/symbol, which can run to six
# figures of symbols) registers a transform that runs on the reader thread, so
# the main thread only ever receives a finished result. Adding a feature that
# processes whole-project data means doing the same: the editor must never
# wait.
#
# Coordinates: LSP positions are 0-based (line, character), matching 10x's
# (column, line) cursor coordinates. Characters are treated as column indices,
# which is correct for ASCII / BMP text.
# ---------------------------------------------------------------------------

import os
import re
import gc
import functools
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
# Biggest response we will parse. Parsing costs several times the wire size in
# Python objects and seconds of main-thread CPU, so a server that answers an
# empty workspace/symbol query with a whole huge project would stall the editor
# - anything past this is drained and dropped instead (see _drain_oversize).
# Well clear of normal traffic: a large completion or diagnostics reply is ~1 MB.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
# Our own JSON-RPC error code for that drop, so a handler can tell it apart from
# anything the server said.
ERR_RESPONSE_TOO_LARGE = -32001
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


# Memoized: this is a per-character Python loop and the project-symbol path
# calls it once per symbol over a file set that repeats heavily, where it was
# 91% of the work. Bounded so a long session can't grow it without limit, but
# sized above the file count of any dump that can reach us (MAX_RESPONSE_BYTES
# caps a symbol reply at ~100k symbols): an LRU smaller than the working set
# cycles without ever hitting.
@functools.lru_cache(maxsize=65536)
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


def path_within(directory, path):
    """Whether `path` sits inside `directory`. Case-insensitive on Windows, and
    False rather than an exception when the two are on different drives."""
    try:
        d = os.path.normcase(os.path.abspath(directory))
        p = os.path.normcase(os.path.abspath(path))
        return d == p or os.path.commonpath([d, p]) == d
    except (ValueError, TypeError, OSError):
        return False


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


def _flatten(text):
    """Collapse text to a single line: every run of whitespace (newlines and the
    indentation servers use to wrap long signatures included) becomes one space."""
    return " ".join((text or "").split())


def _clean_signature_text(text):
    """Run server-supplied signature/parameter text through the same cleanups the
    hover box needs (fences, HTML entities, Markdown escapes)."""
    return strip_markdown_escapes(strip_markup_html(strip_code_fences(text or "")))


def signature_items(result, max_len=200, max_items=16):
    """Render a textDocument/signatureHelp result as the rows of 10x's
    function-args box (N10X.Editor.ShowFunctionArgsListBox): one overload per
    row, the active one LAST, since 10x highlights the bottom row.

        void Copy(byte[] src)
        void Copy(byte[] src, int count)     <- active, highlighted by 10x

    Rows are plain text, collapsed to a single line (server labels can span
    lines) and capped at `max_len`. Returns [] when there is nothing worth
    showing, so callers can leave the box alone rather than blank it."""
    if not isinstance(result, dict):
        return []
    sigs = [s for s in (result.get("signatures") or []) if isinstance(s, dict)]
    if not sigs:
        return []
    active = result.get("activeSignature")
    if not isinstance(active, int) or not 0 <= active < len(sigs):
        active = 0
    # Active overload last - 10x highlights the bottom row. Truncation drops the
    # other overloads from the top for the same reason: the active one stays.
    order = [i for i in range(len(sigs)) if i != active] + [active]
    rows = []
    for i in order[-max_items:]:
        row = _flatten(_clean_signature_text(sigs[i].get("label") or ""))
        if row:
            rows.append(row[:max_len])
    return rows


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


_WORD_SEPARATORS = "_-./\\:<>(),&*[]"


def _is_word_start(text, i):
    """True when text[i] begins a word - the string's start, after a separator,
    or the upper/digit that starts a camelCase hump."""
    if i == 0:
        return True
    prev, cur = text[i - 1], text[i]
    if prev in _WORD_SEPARATORS:
        return True
    return ((cur.isupper() and not prev.isupper())
            or (cur.isdigit() and not prev.isdigit()))


def fuzzy_score(candidate, word):
    """Score `word` as a subsequence of `candidate` (case-insensitive), or None
    when the characters don't all appear in order. Lower is better.

    A matched character is free when it directly follows the previous match (so
    runs of adjacent characters stay cheap), costs 1 at a word start and 3
    mid-word. That is what makes "gcp" rank "GetCursorPos" above
    "GetTypeCompletionPath", and any prefix match score 0. Where the match ends
    and how long the candidate is only break ties."""
    low = candidate.lower()
    score, i, prev = 0, 0, -1
    for ch in word:
        i = low.find(ch, i)
        if i < 0:
            return None
        if i != prev + 1:
            score += 1 if _is_word_start(candidate, i) else 3
        prev = i
        i += 1
    return (score, prev, len(candidate))


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
    parsed messages is done by the owner on the main thread - so a request whose
    reply needs real work done to it registers a transform (see request()),
    which runs on the reader thread and hands the main thread a finished result.
    """

    def __init__(self, argv, cwd, log=None, verbose=None, env=None):
        self._log = log or (lambda m: None)
        self._verbose = verbose or (lambda: False)
        self.incoming = queue.Queue()
        self.outgoing = queue.Queue()
        self._next_id = 1
        self.alive = False
        # request id -> callable(result) run on the reader thread. Touched from
        # both threads, hence the lock.
        self._transforms = {}
        self._transform_lock = threading.Lock()

        # env overrides are merged onto the editor's own environment rather than
        # replacing it - the server still needs PATH, HOME, etc. to run.
        proc_env = None
        if env:
            proc_env = dict(os.environ)
            proc_env.update({str(k): str(v) for k, v in env.items()})

        self.proc = subprocess.Popen(
            argv, cwd=cwd, env=proc_env,
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

    def request(self, method, params, transform=None):
        """Send a request, returning its id so the caller can match a reply.

        transform, if given, is applied to the result on the READER thread
        before the reply is queued, so heavy post-processing never lands on the
        editor's main thread. It must be pure and touch no N10X.Editor API.
        Registered before the write so a fast reply can't beat it."""
        rid = self._next_id
        self._next_id += 1
        if transform is not None:
            with self._transform_lock:
                self._transforms[rid] = transform
        self._write({"jsonrpc": "2.0", "id": rid, "method": method,
                     "params": params})
        return rid

    def _take_transform(self, rid):
        with self._transform_lock:
            return self._transforms.pop(rid, None)

    def _apply_transform(self, msg):
        """Reader thread: turn a reply's raw result into whatever the caller
        actually wants, before the main thread ever sees it. A transform that
        raises becomes an error reply rather than passing raw data through -
        the handler is written against the transformed shape."""
        rid = msg.get("id")
        if rid is None or "result" not in msg or "method" in msg:
            return msg
        fn = self._take_transform(rid)
        if fn is None:
            return msg
        try:
            msg["result"] = fn(msg["result"])
        except Exception as e:
            msg.pop("result", None)
            msg["error"] = {"code": -32002, "message": f"post-processing failed: {e}"}
        return msg

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
                if length > MAX_RESPONSE_BYTES:
                    self._drain_oversize(stream, length)
                    continue
                # Chunks are joined rather than accumulated with +=, which
                # recopies the whole buffer on every read.
                parts, got = [], 0
                while got < length:
                    chunk = stream.read(length - got)
                    if not chunk:
                        raise EOFError()
                    parts.append(chunk)
                    got += len(chunk)
                try:
                    msg = json.loads(b"".join(parts).decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                self.incoming.put(self._apply_transform(msg))
        except (EOFError, OSError, ValueError):
            pass
        finally:
            self.alive = False
            self.incoming.put({"__lsp_internal__": "exited"})

    def _drain_oversize(self, stream, length):
        """Throw away a response too big to parse, without ever holding it.

        Parsing one costs several times its wire size in Python objects and
        seconds of CPU, which is how a huge project turns a symbol dump into a
        stalled editor. The bytes still have to come off the pipe or the stream
        desyncs, so read past them in fixed blocks and keep only enough of the
        head to work out which request died - the waiting handler has to be
        failed rather than left pending forever."""
        head, got = b"", 0
        while got < length:
            chunk = stream.read(min(1 << 20, length - got))
            if not chunk:
                raise EOFError()
            if len(head) < 1024:
                head += chunk[:1024 - len(head)]
            got += len(chunk)
        # A message carrying "method" is the server calling us, not answering
        # us, so its id belongs to the server's numbering, not our pending map.
        rid = None
        if b'"method"' not in head:
            m = re.search(br'"id"\s*:\s*(\d+)', head)
            if m:
                rid = int(m.group(1))
                self._take_transform(rid)
        self.incoming.put({"__lsp_oversize__": {"id": rid, "length": length}})

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
                 on_initialized=None, server_cwd=None, pull_diagnostics=False,
                 server_env=None):
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
        # Environment overrides for the server process: a dict, or a
        # callable(client) -> dict evaluated at launch (so it can read settings).
        self.server_env = server_env
        self.disabled = False

        self.conn = None
        self.initialized = False
        self.server_caps = {}    # capabilities from the initialize result
        self.root_uri = None
        self.root_path = None
        self._sync_kind = 1  # server textDocumentSync.change: 0 none/1 full/2 incremental
        self.pending = {}        # request id -> handler(result, error)
        self.docs = {}           # uri -> {"version", "text", "filename"}
        self._skipped_docs = set()  # uris over MaxFileSize; never sent to server
        self.diagnostics = {}    # uri -> [Diagnostic]
        self._last_sync = 0.0
        self._sync_interval = 0.35
        self._completion_due = 0.0   # time.time() at which to auto-fire completion
        self._auto_delay = 0.12      # debounce window for as-you-type completion
        self._last_completion_id = None  # newest in-flight completion request id
        self._completion_inflight = False  # a completion request is awaiting reply
        self._completion_req_pos = None  # cursor (x, y) when that request was sent
        self._autocomplete_visible = False  # our completion popup is on screen
        # Auto signature help ("function args info"). While the cursor sits
        # inside a call's parentheses we keep 10x's function-args box filled with
        # the signature for that call. See _refresh_signature_help.
        self._sig_anchor = None      # (x, y) of the "(" of the call we're inside
        self._sig_items = []         # rows last handed to the args box
        self._sig_due = 0.0          # time.time() at which to (re-)request it
        self._sig_dirty = False      # input happened; re-check on the next tick
        self._sig_visible = False    # the args box is (believed) on screen
        self._sig_tries = 0          # requests made for the current call
        self._sig_typed_open = False # a "(" was typed since the last tick
        self._sig_session = False    # this call's box is ours to fill
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
        # Project-wide symbol cache behind the find-symbol panel. The panel
        # filters the list it is handed, so it wants every symbol each time it
        # opens - one workspace/symbol round trip per open would be far too slow
        # on a big project. See list_symbols.
        self._symbol_cache = []          # (name, path, line, char, length)
        self._symbol_cache_time = 0.0    # time.time() the cache was last filled
        self._symbol_cache_inflight = False  # a background refresh is in flight
        # Whether an empty workspace/symbol query dumps the workspace on this
        # server: None until we've tried, False for servers that answer nothing
        # (Roslyn) so we go straight to searching for the word under the cursor.
        self._symbol_dump = None
        self._symbol_dump_tries = 0      # empty dump replies seen so far
        self._symbol_warm_due = 0.0      # time.time() to (re)try filling it
        self._registered = False         # register() wired the editor hooks up
        self._hooks = None               # (add, remove, handler) for those hooks

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

    def _resolve_server_env(self):
        """Environment overrides for the server process. Merges the per-language
        server_env (a dict, or a callable(client) -> dict so it can react to
        settings) with the user's "<name>.ServerEnv" setting, which wins.

        The setting is a semicolon- or comma-separated list of KEY=VALUE pairs:
            CSharpLSP.ServerEnv: DOTNET_GCConserveMemory=9; DOTNET_gcServer=0
        Mostly useful for memory/GC tuning of servers that run on a VM - see the
        LowMemory notes in CSharpLSP.py."""
        env = {}
        src = self.server_env
        if callable(src):
            try:
                src = src(self)
            except Exception as e:
                self.log(f"server_env callable failed ({e}); ignoring")
                src = None
        if src:
            env.update(src)
        raw = self.setting("ServerEnv").strip()
        for pair in re.split(r"[;,]", raw):
            pair = pair.strip()
            if not pair:
                continue
            key, sep, value = pair.partition("=")
            if not sep or not key.strip():
                self.log(f"ignoring malformed {self.name}.ServerEnv entry '{pair}' "
                         f"(expected KEY=VALUE)")
                continue
            env[key.strip()] = value.strip()
        if env and self._verbose():
            self.log("server env overrides: " +
                     ", ".join(f"{k}={v}" for k, v in sorted(env.items())))
        return env

    @staticmethod
    def _editor_workspace_root():
        """The directory of the workspace 10x has open, or "" if none.

        GetWorkspaceFilename gives the workspace/solution file the user actually
        opened (10x's own ".10x", or a ".sln"), so its directory is the project
        being worked on."""
        try:
            ws = (N10X.Editor.GetWorkspaceFilename() or "").strip()
        except Exception:
            return ""
        if not ws:
            return ""
        d = os.path.dirname(os.path.abspath(ws))
        return d if os.path.isdir(d) else ""

    def _resolve_root(self, root_hint):
        """Where to root the language server.

        10x's own workspace wins whenever the file we're starting for lives
        inside it. Walking up from that file instead stops at the innermost
        marker, which roots a nested crate or .csproj at itself and hides the
        rest of the project from workspace/symbol - and since the root is fixed
        at startup, whichever file you happened to open first would decide what
        find-symbol can ever see. A file outside the workspace (a dependency's
        source, say) still falls back to the walk."""
        ws = self._editor_workspace_root()
        if ws and path_within(ws, root_hint):
            return ws
        return find_project_root(root_hint, self.root_markers)

    def ensure_started(self, root_hint):
        if self.conn and self.conn.alive:
            return True
        if not self.is_enabled():
            return False

        self.root_path = self._resolve_root(root_hint)
        self.root_uri = path_to_uri(self.root_path)
        argv = self._server_argv()
        if not argv:
            self.log("no server command configured; set " + self.name + ".Command")
            return False
        cwd = self._resolve_server_cwd()
        env = self._resolve_server_env()
        try:
            self.conn = LSPConnection(argv, cwd, log=self.log,
                                      verbose=self._verbose, env=env)
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
                    "symbol": {"dynamicRegistration": False},
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
                    "signatureHelp": {
                        # 10x's function-args box shows plain rows, so we only
                        # ever render signature labels - no parameter detail is
                        # asked for. contextSupport tells the server whether a
                        # request came from a trigger char or is a re-trigger
                        # while the same call is still being typed.
                        "contextSupport": True,
                        "signatureInformation": {
                            "documentationFormat": ["plaintext", "markdown"],
                        },
                    },
                    "definition": {"linkSupport": True},
                    "references": {},
                    "documentSymbol": {
                        # Accept the modern nested DocumentSymbol[] shape (we
                        # flatten it) as well as the legacy flat
                        # SymbolInformation[]; _on_document_symbols handles both.
                        "hierarchicalDocumentSymbolSupport": True,
                    },
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
        # Keep the whole capability set: some commands need to know up front
        # whether the server implements a request at all (e.g. pylsp answers
        # workspace/symbol with MethodNotFound - see list_symbols).
        self.server_caps = caps
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
        # Get the project's symbols on their way now, so the first FindSymbol
        # opens on a full list instead of triggering the fetch itself.
        self._warm_symbol_cache()
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
        self.server_caps = {}
        self.pending.clear()
        self.docs.clear()
        self._skipped_docs.clear()
        self.diagnostics.clear()
        self.disabled = False
        # A signature on screen belongs to the server that answered for it.
        self._hide_signature()
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
        # The symbol cache describes the workspace as that server saw it.
        self._symbol_cache = []
        self._symbol_cache_time = 0.0
        self._symbol_cache_inflight = False
        self._symbol_dump = None
        self._symbol_dump_tries = 0
        self._symbol_warm_due = 0.0

    # -- document sync -----------------------------------------------------

    def _ready(self):
        return bool(self.conn and self.conn.alive and self.initialized)

    def _max_file_bytes(self):
        """"<name>.MaxFileSize" in KB, as bytes. 0/unset means no limit."""
        try:
            return max(0, int(self.setting("MaxFileSize", "0"))) * 1024
        except (TypeError, ValueError):
            return 0

    def _too_big(self, filename, text):
        """Whether this file is over the MaxFileSize limit. Oversized files are
        never sent to the server: we hold their full text in self.docs and (on
        full-sync servers) resend all of it on every edit, and the server then
        parses and holds its own copy. Generated files - .designer.cs, huge
        interop bindings - are the usual offenders."""
        limit = self._max_file_bytes()
        if not limit:
            return False
        size = len(text.encode("utf-8", "ignore")) if text else 0
        if size <= limit:
            return False
        self.log(f"skipping {os.path.basename(filename)}: {size // 1024} KB "
                 f"exceeds {self.name}.MaxFileSize ({limit // 1024} KB); "
                 f"language features are off for this file")
        return True

    def did_open(self, filename):
        if not self._ready():
            return
        uri = path_to_uri(filename)
        if uri in self.docs:
            return
        if uri in self._skipped_docs:
            return
        try:
            text = N10X.Editor.GetFileText(filename)
        except Exception:
            text = N10X.Editor.GetFileText()
        if text is None:
            text = ""
        if self._too_big(filename, text):
            # Remember it so we don't re-read and re-warn on every sync tick.
            self._skipped_docs.add(uri)
            return
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
        # A save is when the project's symbols actually change, so top the
        # find-symbol cache up in the background. Only when we already have one:
        # an empty cache means either nobody has opened the panel yet or this
        # server doesn't answer empty queries, and neither wants a request here.
        if (self._symbol_cache_enabled() and self._symbol_cache
                and self._symbol_cache_stale()):
            self._refresh_symbol_cache()

    # -- request helpers ---------------------------------------------------

    def _doc_pos_params(self, pos=None):
        filename = N10X.Editor.GetCurrentFilename()
        if not self.handles(filename):
            return None
        # The server was never told about an oversized file, so asking it about a
        # position in one would be answered against a document it doesn't have.
        if path_to_uri(filename) in self._skipped_docs:
            return None
        x, y = N10X.Editor.GetCursorPos()
        if pos is not None:
            x = pos[0]
            y = pos[1]
            
        return {"textDocument": {"uri": path_to_uri(filename)},
                "position": {"line": y, "character": x}}

    def _send_request(self, method, params, handler, transform=None):
        """transform runs on the reader thread before `handler` is called on the
        main thread with its output - see LSPConnection.request."""
        if not self._ready():
            self.log("server not ready")
            return None
        rid = self.conn.request(method, params, transform=transform)
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

        if "__lsp_oversize__" in msg:
            info = msg["__lsp_oversize__"]
            mb = info["length"] / (1024.0 * 1024.0)
            self.log(f"dropped a {mb:.0f} MB response unparsed - over the "
                     f"{MAX_RESPONSE_BYTES // (1024 * 1024)} MB cap "
                     f"(MAX_RESPONSE_BYTES); parsing it would have stalled the "
                     f"editor")
            handler = (self.pending.pop(info["id"], None)
                       if info.get("id") is not None else None)
            if handler:
                handler(None, {"code": ERR_RESPONSE_TOO_LARGE,
                               "message": f"response too large ({mb:.0f} MB)"})
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

    def _all_ignore_dirs(self):
        """Directory names the workspace scan skips: the built-in set plus
        anything in "<name>.IgnoreDirs" (comma/semicolon separated), e.g.

            CSharpLSP.IgnoreDirs: Generated, ThirdParty, TestData

        Matching is on the directory NAME at any depth, not on a path."""
        extra = self.setting("IgnoreDirs").strip()
        if not extra:
            return self.ignore_dirs
        names = {p.strip() for p in re.split(r"[;,]", extra) if p.strip()}
        return self.ignore_dirs | names

    def _snapshot_watched_files(self):
        """Map every workspace file we handle to its mtime. Cheap enough to run
        on a few-second cadence; heavy/irrelevant directories are skipped. Used
        as the baseline for detecting create/change/delete between scans."""
        snap = {}
        root = self.root_path
        if not root or not os.path.isdir(root):
            return snap
        ignore = self._all_ignore_dirs()
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
        fuzzy = self._fuzzy_complete()
        ranked = False
        if word:
            def _match(it):
                return it.get("filterText") or it.get("label") or ""
            if fuzzy:
                # Subsequence match ("gcp" -> "GetCursorPos"), ordered by how
                # well each item matches: a scattered hit shouldn't outrank a
                # prefix hit just because the server ranked it higher.
                scored = []
                for it in items:
                    s = fuzzy_score(_match(it), word)
                    if s is not None:
                        scored.append((s, it.get("sortText") or "",
                                       it.get("label") or "", it))
                scored.sort(key=lambda e: e[:3])
                items = [e[3] for e in scored]
                ranked = True
            else:
                items = [it for it in items
                         if _match(it).lower().startswith(word)]
        # Order by the server's relevance ranking (sortText) so the closest
        # match - e.g. "found" - sits at the top; label breaks ties stably.
        if not ranked:
            items = sorted(items, key=lambda it: (it.get("sortText") is None,
                                                  it.get("sortText") or "",
                                                  it.get("label") or ""))
        limit = self._max_results()
        if self._verbose():
            try:
                x, y = N10X.Editor.GetCursorPos()
            except Exception:
                x, y = ("?", "?")
            self.log(f"completion: {len(items)} items after "
                     f"{'fuzzy ' if fuzzy else ''}filter (cap {limit}); "
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

    def _fuzzy_complete(self):
        """Whether to match completion items on a subsequence of the typed word
        instead of a literal prefix (default true; "<name>.FuzzyComplete").
        Set "false" for literal prefix matching only."""
        return self.setting("FuzzyComplete", "true").strip().lower() != "false"

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

    # -- signature help ("function args info") -----------------------------
    #
    # 10x owns the box: ShowFunctionArgsListBox fills it with one row per
    # overload, the user picks one with up/down, and an empty list takes it down.
    # Two rules follow. The rows go up ONCE per call - re-pushing them resets the
    # user's selection - and only when the user types the call's "(", so a box
    # they dismissed stays dismissed until ShowFunctionArgsInfo.

    def signature_help_enabled(self):
        """On unless turned off, and only for a server that implements signature
        help on a 10x build that has the function-args box."""
        return (self.setting("SignatureHelp") != "false"
                and bool(self.server_caps.get("signatureHelpProvider"))
                and hasattr(N10X.Editor, "ShowFunctionArgsListBox"))

    def _code_brackets(self, line):
        """[(index, char), ...] for every bracket and ";" in `line` that isn't
        inside a string literal or a line comment - i.e. the ones that actually
        nest code, so "f(\"a)b\")" isn't read as an unbalanced call.

        Quote handling is deliberately minimal: a single quote only opens a
        literal when the same line closes it, so Rust lifetimes ("&'a T") and
        stray apostrophes in comments don't swallow the rest of the line."""
        out = []
        i, n, quote = 0, len(line), ""
        while i < n:
            c = line[i]
            if quote:
                if c == "\\":
                    i += 2
                    continue
                if c == quote:
                    quote = ""
            elif c == '"' or (c == "'" and "'" in line[i + 1:]):
                quote = c
            elif self.line_comment and line.startswith(self.line_comment, i):
                break  # rest of the line is a comment
            elif c in "()[]{};":
                out.append((i, c))
            i += 1
        return out

    def _enclosing_call_paren(self, max_lines=24):
        """(x, y) of the "(" of the innermost call the cursor is inside, else
        None. This is what decides whether the args box should be up at all, and
        - because it identifies the specific call - when to throw away a
        signature because the user moved into a different one.

        Scans backwards from the cursor, bracket-matching as it goes. Balanced
        [...] and {...} are transparent (an argument can be a list or an object
        literal). An unmatched "[" is transparent too - the cursor is inside a
        list that is itself an argument - but an unmatched "{" is a block (or a
        statement-level literal) and an unmatched ";" ends the statement, so in
        both cases there is no enclosing call to describe."""
        try:
            x, y = N10X.Editor.GetCursorPos()
        except Exception:
            return None
        depth = {")": 0, "]": 0, "}": 0}
        for ln in range(y, max(-1, y - max_lines), -1):
            try:
                text, _ = self._split_eol(N10X.Editor.GetLine(ln) or "")
            except Exception:
                return None
            if ln == y:
                text = text[:x]
            for i, c in reversed(self._code_brackets(text)):
                if c in depth:
                    depth[c] += 1
                elif c == "(":
                    if depth[")"] == 0:
                        return (i, ln)
                    depth[")"] -= 1
                elif c == "[":
                    if depth["]"]:
                        depth["]"] -= 1
                elif c == "{":
                    if not depth["}"]:
                        return None
                    depth["}"] -= 1
                elif c == ";" and not depth[")"]:
                    return None
        return None

    def _show_signature(self):
        """Open 10x's function-args box, once per call.

        The position is the caret as it is when a call is opened - just after the
        "(" - which is what 10x binds the box to and tracks the arguments from.
        ShowFunctionArgsInfo mid-call passes the same place, so the box always
        appears at the start of the argument list."""
        if not self._sig_items:
            return
        if self._sig_anchor is not None:
            pos = (self._sig_anchor[0] + 1, self._sig_anchor[1])
        else:
            try:
                pos = N10X.Editor.GetCursorPos()
            except Exception:
                pos = None
        if self._verbose():
            self.log(f"args box at {pos}: {len(self._sig_items)} row(s); "
                     f"{self._sig_items[0]!r}")
        try:
            if pos is None:
                N10X.Editor.ShowFunctionArgsListBox(self._sig_items)
            else:
                N10X.Editor.ShowFunctionArgsListBox(self._sig_items, pos)
            self._sig_visible = True
        except AttributeError:
            # Older 10x without the function-args box: fall back to a one-shot
            # hover box, which the next key press dismisses.
            self._show_hover_box("\n".join(self._sig_items), None)
        except Exception as e:
            self.log(f"ShowFunctionArgsListBox failed: {e}")

    def _clear_args_box(self):
        """Take the args box off screen. An empty list dismisses it, as it does
        the autocomplete one."""
        if not self._sig_visible:
            return
        self._sig_visible = False
        try:
            N10X.Editor.ShowFunctionArgsListBox([])
        except Exception:
            pass

    def _hide_signature(self):
        """End the session: there is no call under the cursor to describe."""
        self._sig_anchor = None
        self._sig_items = []
        self._sig_due = 0.0
        self._sig_tries = 0
        self._sig_session = False
        self._clear_args_box()

    def _refresh_signature_help(self, now):
        """Re-evaluate the args box after an input event: end the session when the
        cursor leaves the call, start one when the user types a call's "(", and
        otherwise leave the box alone."""
        opened, self._sig_typed_open = self._sig_typed_open, False
        if not self._ready():
            self._hide_signature()
            return
        try:
            if not self.handles(N10X.Editor.GetCurrentFilename()):
                self._hide_signature()
                return
        except Exception:
            return
        anchor = self._enclosing_call_paren()
        if anchor is None:
            self._hide_signature()
            return
        if not self.signature_help_enabled():
            # Auto-open off: a box from ShowFunctionArgsInfo stays until the
            # cursor leaves that call.
            if anchor != self._sig_anchor:
                self._hide_signature()
            return
        if anchor != self._sig_anchor:
            # A different call: take the old rows down so a signature is never
            # left up against the wrong arguments.
            self._sig_anchor = anchor
            self._sig_items = []
            self._sig_session = False
            self._clear_args_box()
        if opened and not self._sig_session:
            # The user just typed this call's "(". Tested outside the branch
            # above because the cursor-move event for the same keystroke can land
            # first, updating the anchor before this flag is seen.
            self._sig_session = True
            self._sig_tries = 0
            self._sig_due = now
        elif (self._sig_session and not self._sig_items
                and self._sig_tries < 3):
            # Our call, nothing to show yet (server still loading, or the line
            # didn't parse). Retry as the user types, but only a few times so an
            # "if (x" doesn't ask forever.
            due = now + self._auto_delay
            if not self._sig_due or due < self._sig_due:
                self._sig_due = due

    def _request_signature_help(self, manual=False):
        params = self._doc_pos_params()
        if params is None:
            if manual:
                N10X.Editor.SetStatusBarText(f"{self.name}: no signature")
            return
        # We advertise contextSupport, so say why we're asking: an automatic
        # request always follows a typed "(".
        if manual:
            context = {"triggerKind": 1,          # Invoked
                       "isRetrigger": bool(self._sig_items)}
        else:
            context = {"triggerKind": 2,          # TriggerCharacter
                       "triggerCharacter": "(",
                       "isRetrigger": self._sig_tries > 0}
            self._sig_tries += 1
        params["context"] = context
        self.sync_current(force=True)
        anchor = self._sig_anchor
        self._send_request("textDocument/signatureHelp", params,
                           lambda r, e: self._on_signature(r, e, anchor, manual))

    def _on_signature(self, result, error, anchor=None, manual=True):
        # The cursor can move to another call while the server answers; a reply
        # that no longer describes the call we're in is dropped.
        if not manual and anchor != self._sig_anchor:
            return
        items = [] if error else signature_items(result)
        if not manual and items == self._sig_items and self._sig_visible:
            return  # 10x is already showing this list - leave the user's choice
        if not items:
            if manual:
                N10X.Editor.SetStatusBarText(f"{self.name}: no signature")
            # Otherwise leave the box alone: a null answer mid-edit shouldn't
            # blank what the user is reading.
            return
        self._sig_items = items
        self._show_signature()

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
        self._present_locations(items, "reference")

    def _present_locations(self, items, noun):
        """Hand a list of (path, line, index, length) tuples to 10x's navigable
        symbol-references list. `noun` names them for status/log text (e.g.
        "reference", "symbol"). Falls back to the output panel on older 10x."""
        if not items:
            N10X.Editor.SetStatusBarText(f"{self.name}: no {noun}s found")
            return
        try:
            N10X.Editor.ShowSymbolReferences(items)
        except AttributeError:
            # Older 10x without ShowSymbolReferences: log to the output panel.
            self.log(f"{len(items)} {noun}(s):")
            for path, line, index, _ in items:
                self.log(f"  {path}:{line + 1}:{index + 1}")
            N10X.Editor.SetStatusBarText(
                f"{self.name}: {len(items)} {noun}(s) - see output panel")
        except Exception as e:
            self.log(f"ShowSymbolReferences failed: {e}")

    def _present_functions(self, items):
        """Hand (name, path, line, char, length) tuples for the CURRENT file to
        10x's find-function panel, which filters them itself. Falls back to the
        symbol-references list on 10x builds without the panel."""
        if not items:
            N10X.Editor.SetStatusBarText(f"{self.name}: no functions found")
            return
        show = getattr(N10X.Editor, "ShowFindFunctionPanel", None)
        if show:
            try:
                # Uncomment for debugging
                #self.log(f"find-function panel: {len(items)} function(s): "
                #         f"{self._preview(items)}")
                show([(name, line, char) for name, _p, line, char, _l in items])
                return
            except Exception as e:
                self.log(f"ShowFindFunctionPanel failed: {e}")
        self._present_locations([it[1:] for it in items], "function")

    def _present_symbols(self, items, noun="symbol"):
        """Hand (name, path, line, char, length) tuples to 10x's find-symbol
        panel, which filters them itself. Falls back as above."""
        if not items:
            N10X.Editor.SetStatusBarText(f"{self.name}: no {noun}s found")
            return
        show = getattr(N10X.Editor, "ShowFindSymbolPanel", None)
        if show:
            try:
                # Uncomment for debugging
                #self.log(f"find-symbol panel: {len(items)} {noun}(s): "
                #         f"{self._preview(items, with_file=True)}")
                show([(name, path, line, char)
                      for name, path, line, char, _l in items])
                return
            except Exception as e:
                self.log(f"ShowFindSymbolPanel failed: {e}")
        self._present_locations([it[1:] for it in items], noun)

    @staticmethod
    def _preview(items, limit=8, with_file=False):
        """The first few rows as "name:line" for the panel log line."""
        rows = ", ".join(
            f"{name}:{os.path.basename(path) + ':' if with_file else ''}{line + 1}"
            for name, path, line, _c, _l in items[:limit])
        return rows + (", ..." if len(items) > limit else "")

    @staticmethod
    def _qualified_name(name, container):
        """The panels show one string per row and match against all of it, so
        the enclosing class/namespace goes in the name: "Update (Player)"."""
        name = name or "?"
        return f"{name} ({container})" if container else name

    # LSP SymbolKind values that are "functions" for list_symbols: Method (6),
    # Constructor (9), Function (12). Other kinds (classes, fields, ...) are the
    # symbols a function lives in, not functions themselves, so we skip them.
    _FUNCTION_SYMBOL_KINDS = frozenset((6, 9, 12))

    def _on_document_symbols(self, result, error, filename):
        if error or not result:
            N10X.Editor.SetStatusBarText(f"{self.name}: no symbols found")
            return
        # textDocument/documentSymbol returns either a nested DocumentSymbol[]
        # (each with a "range"/"selectionRange" and possibly "children") or a
        # flat SymbolInformation[] (each with a "location"). Flatten both to a
        # single list of function-like symbols.
        default_path = uri_to_path(path_to_uri(filename))
        seen, items = set(), []

        def add(name, kind, path, rng, container=""):
            if kind not in self._FUNCTION_SYMBOL_KINDS or not rng:
                return
            start = rng.get("start", {})
            line = start.get("line", 0)
            index = start.get("character", 0)
            key = (path, line, index)
            if key in seen:
                return
            seen.add(key)
            end = rng.get("end", {})
            length = (end.get("character", index) - index
                      if end.get("line", line) == line else 0)
            items.append((self._qualified_name(name, container), path, line,
                          index, max(length, 0)))

        def walk(nodes, container=""):
            for node in nodes:
                name = node.get("name") or ""
                if "location" in node:            # SymbolInformation
                    loc = node.get("location", {})
                    add(name, node.get("kind"), uri_to_path(loc.get("uri", "")),
                        loc.get("range"), node.get("containerName") or "")
                else:                             # DocumentSymbol
                    # selectionRange points at the name; nicer to land on than
                    # the whole body range. Fall back to range if it's missing.
                    add(name, node.get("kind"), default_path,
                        node.get("selectionRange") or node.get("range"),
                        container)
                    # Methods are qualified by the class/namespace they're in.
                    walk(node.get("children") or [], name)

        walk(result)
        # File order: the find-function panel lists them as it is given them,
        # and reading a file top to bottom is how you look for a function in it.
        items.sort(key=lambda it: (it[1], it[2], it[3]))
        # The panel has no filename column - every row jumps within the current
        # file - so a server that answered with symbols from elsewhere (rare,
        # SymbolInformation only) goes to the old list instead.
        if all(it[1] == default_path for it in items):
            self._present_functions(items)
        else:
            self._present_symbols(items, "function")

    def _symbol_items(self, result):
        """A workspace/symbol result as sorted (name, path, line, char, length)
        tuples.

        Runs on the READER thread as a request transform, because on a large
        project this is hundreds of milliseconds of work and the editor must
        never wait for it. Keep it pure: no self state, no N10X.Editor calls.

        It returns a flat SymbolInformation[] (or, in LSP 3.17, a
        WorkspaceSymbol[]); both carry a "location". A WorkspaceSymbol may give
        only {"uri": ...} with no range (it expects a workspaceSymbol/resolve
        round-trip) - we just land at the top of that file in that case. Every
        symbol kind is kept here (this is the project-wide index), unlike
        list_functions which is functions only."""
        seen, items = set(), []
        for sym in result or []:
            loc = sym.get("location", {}) or {}
            path = uri_to_path(loc.get("uri", ""))
            if not path:
                continue
            rng = loc.get("range", {}) or {}
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
            items.append((self._qualified_name(sym.get("name"),
                                               sym.get("containerName") or ""),
                          path, line, index, max(length, 0)))
        items.sort(key=lambda it: (it[0].lower(), it[1], it[2]))
        return items

    def _on_workspace_symbols(self, result, error, query="", dump=False):
        """dump marks the reply to the empty whole-workspace query - the one
        that fills the find-symbol panel - as opposed to a search for a term."""
        if error:
            # -32601 is MethodNotFound: the server doesn't implement
            # workspace/symbol (pylsp, for one, despite answering
            # textDocument/documentSymbol quite happily).
            self._note_dump_too_large(error)
            if (error or {}).get("code") == -32601:
                self._no_workspace_symbols()
            else:
                self.log(f"workspace/symbol failed: {error}")
                N10X.Editor.SetStatusBarText(
                    f"{self.name}: symbol search failed - see output panel")
            return
        # Already tuples: _symbol_items ran on the reader thread.
        items = result or []
        if dump:
            # Worth knowing whether or not we're keeping the list: with the cache
            # off it is what saves a wasted round trip on every single open.
            if items:
                self._note_dump_filled(items)
            else:
                # Don't conclude anything yet - the server may still be indexing.
                self._note_empty_dump()
        if not items:
            # workspace/symbol is a search, not a dump. Servers differ on what an
            # empty query means: rust-analyzer answers with the workspace's types,
            # Roslyn returns nothing at all. When the whole-workspace query comes
            # back empty, search for what the cursor is on instead - that is all
            # such a server can answer.
            if dump:
                term = (self._selected_text() or self._word_at_cursor()).strip()
                if term:
                    self._send_request(
                        "workspace/symbol", {"query": term},
                        lambda r, e: self._on_workspace_symbols(r, e, term),
                        transform=self._symbol_items)
                    return
            if query:
                N10X.Editor.SetStatusBarText(
                    f"{self.name}: no symbols matching '{query}'")
            else:
                N10X.Editor.SetStatusBarText(
                    f"{self.name}: this server needs a search term - put the "
                    f"cursor on a word, or type '{self.name} symbols <text>'")
            return
        self._present_symbols(items)

    def _on_symbol_cache(self, result, error):
        """Reply to a background refresh: fill the cache, show nothing. A failed
        or empty refresh leaves the previous list in place - better than nothing
        the next time the panel opens."""
        self._symbol_cache_inflight = False
        if error:
            self._note_dump_too_large(error)
            return
        if not self._symbol_cache_enabled():
            return
        items = result or []
        if not items:
            self._note_empty_dump()
            return
        self._note_dump_filled(items)

    def _note_dump_too_large(self, error):
        """Give up on whole-workspace dumps when one came back too big to parse.

        _symbol_dump is the "this server won't hand over the workspace" flag, and
        a project too big to parse is the same situation from here: the panel
        falls back to searching for a term, which is bounded."""
        if (error or {}).get("code") != ERR_RESPONSE_TOO_LARGE:
            return
        self._symbol_dump = False
        self._symbol_cache = []
        self._symbol_cache_time = 0.0
        self.log("this project's symbol dump is too big to hold, so find-symbol "
                 "will search for a term instead of listing everything. Use "
                 f"'{self.name} symbols <text>', or set {self.name}.SymbolCache: "
                 f"false to turn the feature off.")
        N10X.Editor.SetStatusBarText(
            f"{self.name}: project too large to list every symbol - use "
            f"'{self.name} symbols <text>'")

    def _symbol_cache_enabled(self):
        """"<name>.SymbolCache" (default true): whether we keep a project-wide
        symbol list for the find-symbol panel at all.

        Turning it off is the way to opt out of the whole feature - the list is
        a copy of every symbol in the project, refreshed in the background, and
        on a big project that is real memory and real server work. The panel
        cannot work without it (it filters the list it is handed), so
        find-symbol goes with it - we still claim the FindSymbol command and
        say why, rather than let 10x fall back to its own panel, which has
        nothing of value for a file the server handles. The explicit
        "<name> symbols <text>" search still works, being a one-shot server
        query that keeps nothing.

        Drops whatever is cached when it sees the setting turned off, so the
        memory goes back without waiting for a restart."""
        on = self.setting("SymbolCache", "true").strip().lower() != "false"
        if not on and self._symbol_cache:
            self._symbol_cache = []
            self._symbol_cache_time = 0.0
        return on

    def _symbol_cache_seconds(self):
        """"<name>.SymbolCacheSeconds": how long the find-symbol panel's cached
        project symbols count as fresh. 0 keeps find-symbol working but holds
        nothing between opens (every open asks the server and waits for the
        reply). Only meaningful while _symbol_cache_enabled."""
        try:
            return max(0, int(self.setting("SymbolCacheSeconds", "60")))
        except (TypeError, ValueError):
            return 60

    # An empty answer to the whole-workspace query is ambiguous: the server may
    # have no dump to give (Roslyn), or may simply not have finished indexing -
    # which is the usual case in the first seconds after startup. Believing the
    # first one strands find-symbol in cursor-word fallback for the rest of the
    # session, so retry on this backoff before concluding anything.
    _SYMBOL_DUMP_RETRIES = (2.0, 5.0, 12.0, 30.0)

    # After a dump lands, how long to wait before checking whether the server
    # has since indexed more. Servers answer as soon as they have something,
    # which early in a session is often only part of the project.
    _SYMBOL_GROWTH_RECHECK = 10.0

    def _note_dump_filled(self, items):
        """Record a successful whole-workspace dump.

        While the symbol count is still climbing, line up another pass: the
        server keeps indexing after it first answers, and without this an early
        partial list sits there until something else happens to refresh it."""
        grew = len(items) > len(self._symbol_cache)
        self._symbol_dump = True
        self._symbol_dump_tries = 0
        if not self._symbol_cache_seconds():
            return                       # not keeping it; nothing to top up
        self._symbol_cache = items
        self._symbol_cache_time = time.time()
        if grew and self._symbol_cache_enabled():
            self._symbol_warm_due = time.time() + self._SYMBOL_GROWTH_RECHECK
        if self._verbose():
            self.log(f"cached {len(items)} project symbol(s)"
                     f"{' - still growing, will re-check' if grew else ''}")

    def _note_empty_dump(self):
        """Record an empty whole-workspace reply; schedule another go, or give
        up once the backoff is exhausted."""
        self._symbol_dump_tries += 1
        if self._symbol_dump_tries > len(self._SYMBOL_DUMP_RETRIES):
            self._symbol_dump = False    # settled: this server won't dump
            return
        # Only worth a timed retry if we'd keep the result; with no cache the
        # next panel open re-asks anyway, which is what advances the count.
        if not self._symbol_cache_enabled() or not self._symbol_cache_seconds():
            return
        delay = self._SYMBOL_DUMP_RETRIES[self._symbol_dump_tries - 1]
        self._symbol_warm_due = time.time() + delay
        if self._verbose():
            self.log(f"empty workspace dump (try {self._symbol_dump_tries}); "
                     f"retrying in {delay:.0f}s")

    def _warm_symbol_cache(self, delay=1.5):
        """Fill the find-symbol cache in the background, without being asked.

        The panel is only useful if it already knows the project, so the first
        FindSymbol should not be the thing that goes and fetches it - nor should
        the user have to run RefreshSymbols by hand."""
        if not self._symbol_cache_enabled() or not self._symbol_cache_seconds():
            return
        self._symbol_warm_due = time.time() + delay

    def _symbol_cache_stale(self):
        """Whether the cached symbols are old enough to be worth re-fetching.
        Also the save throttle: a save only refreshes once the list is stale, so
        a save-heavy edit loop can't re-dump the workspace on every keystroke."""
        ttl = self._symbol_cache_seconds()
        return bool(ttl) and time.time() - self._symbol_cache_time >= ttl

    def _refresh_symbol_cache(self):
        """Re-ask the server for the whole workspace, off to one side: whatever
        panel is on screen keeps the list it was handed, and the reply only
        updates the cache for the next open."""
        if self._symbol_cache_inflight or not self._ready():
            return
        if not self._symbol_cache_enabled() or not self._symbol_cache_seconds():
            # A zero TTL keeps nothing between opens, so there is no list here
            # for a background refresh to fill.
            return
        if self._symbol_dump is False:
            return
        if self.server_caps and not self.server_caps.get("workspaceSymbolProvider"):
            return
        self._symbol_cache_inflight = True
        if self._send_request("workspace/symbol", {"query": ""},
                              self._on_symbol_cache,
                              transform=self._symbol_items) is None:
            self._symbol_cache_inflight = False

    def _symbol_cache_off(self):
        """Say why the find-symbol panel has nothing, when the user turned the
        cache off. Points at the one symbol search that still works without it."""
        N10X.Editor.SetStatusBarText(
            f"{self.name}: find-symbol is off ({self.name}.SymbolCache: false) - "
            f"type '{self.name} symbols <text>' to search the server")

    def _no_workspace_symbols(self):
        """Tell the user this server can't do a project-wide symbol search."""
        msg = (f"{self.name}: server has no project-wide symbol search "
               f"(workspace/symbol) - use ListFunctions for the current file")
        self.log(msg)
        N10X.Editor.SetStatusBarText(msg)

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
        # Not every server implements every request; these two decide whether
        # ListFunctions / ListSymbols can work at all (pylsp, for one, has no
        # workspace/symbol).
        self.log(f"  documentSymbol  : "
                 f"{bool(self.server_caps.get('documentSymbolProvider'))} "
                 f"(ListFunctions)")
        self.log(f"  workspaceSymbol : "
                 f"{bool(self.server_caps.get('workspaceSymbolProvider'))} "
                 f"(ListSymbols)")
        if not self._symbol_cache_enabled():
            self.log(f"  symbol cache    : off "
                     f"(setting: {self.name}.SymbolCache: false; find-symbol "
                     f"disabled, '{self.name} symbols <text>' still works)")
        else:
            ttl = self._symbol_cache_seconds()
            age = (int(time.time() - self._symbol_cache_time)
                   if self._symbol_cache else -1)
            self.log(f"  symbol cache    : "
                     f"{len(self._symbol_cache)} symbol(s)"
                     f"{f', {age}s old' if age >= 0 else ''} "
                     f"(ttl {ttl}s{', off' if not ttl else ''}"
                     f"{', server has no workspace dump' if self._symbol_dump is False else ''}"
                     f"{f', {self._symbol_dump_tries} empty repl(y/ies), retrying' if self._symbol_dump is None and self._symbol_dump_tries else ''}"
                     f"{', warm-up pending' if self._symbol_warm_due else ''})")
        ws = self._editor_workspace_root()
        from_ws = bool(ws) and (os.path.normcase(ws)
                                == os.path.normcase(self.root_path or ""))
        self.log(f"  root            : {self.root_path} "
                 f"({'10x workspace' if from_ws else 'walked up from a file'})")
        self.log(f"  current file    : {fn}")
        self.log(f"  handled         : {self.handles(fn)}")
        self.log(f"  open documents  : {len(self.docs)}")
        limit = self._max_file_bytes()
        self.log(f"  max file size   : "
                 f"{str(limit // 1024) + ' KB' if limit else 'unlimited'}"
                 f"{f' ({len(self._skipped_docs)} skipped)' if self._skipped_docs else ''}")
        extra = sorted(self._all_ignore_dirs() - self.ignore_dirs)
        self.log(f"  extra ignores   : {', '.join(extra) if extra else '(none)'}")
        env = self._resolve_server_env()
        self.log(f"  server env      : "
                 f"{', '.join(f'{k}={v}' for k, v in sorted(env.items())) or '(none)'}")

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
        """ShowFunctionArgsInfo / the "signature" command: put the overloads for
        the call under the cursor up now, at that call's opening "(". The only
        way back once the box has been dismissed."""
        self._sig_anchor = self._enclosing_call_paren()
        self._sig_items = []
        self._sig_due = 0.0
        self._sig_tries = 0
        self._sig_session = True
        self._request_signature_help(manual=True)

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

    def list_functions(self):
        """List the functions/methods in the CURRENT file in 10x's find-function
        panel (via textDocument/documentSymbol). The panel does its own
        filtering, so the whole file's list is handed over each time."""
        filename = N10X.Editor.GetCurrentFilename()
        if not self.handles(filename):
            return
        if path_to_uri(filename) in self._skipped_docs:
            N10X.Editor.SetStatusBarText(
                f"{self.name}: file skipped (over {self.name}.MaxFileSize)")
            return
        self.sync_current(force=True)
        params = {"textDocument": {"uri": path_to_uri(filename)}}
        self._send_request(
            "textDocument/documentSymbol", params,
            lambda r, e: self._on_document_symbols(r, e, filename))

    def list_symbols(self, query=None):
        """Show the project's symbols in 10x's find-symbol panel (via
        workspace/symbol).

        The panel filters the list it is handed, so it wants every symbol each
        time it opens - one server round trip per open would make it too slow to
        use on a real project. So an unqualified call is served from a cache:
        the first one asks the server for the whole workspace, later ones open
        instantly off the cache and refresh it in the background (see
        _refresh_symbol_cache). Saving a file refreshes it too, and
        "<name>.SymbolCacheSeconds: 0" makes every open wait on the server
        instead of holding a list. "<name>.SymbolCache: false" opts out of the
        feature altogether - see _symbol_cache_enabled.

        LSP has no "give me every symbol" request, only a search, and servers
        differ on what an empty query means: rust-analyzer answers with the
        workspace's types, Roslyn returns nothing at all. When the empty query
        comes back empty we search for the selected text, falling back to the
        word under the cursor - all such a server can do. Passing a query
        explicitly ("<Name> symbols <text>" in the command panel) always
        searches the server and bypasses the cache."""
        if not self._ready():
            self.log("server not ready")
            return
        # Some servers (pylsp) implement documentSymbol but not workspace/symbol.
        # They say so at initialize; better to explain than to fire a request
        # that comes back MethodNotFound.
        if self.server_caps and not self.server_caps.get("workspaceSymbolProvider"):
            self._no_workspace_symbols()
            return
        if query is not None:
            query = query.strip()
            self._send_request("workspace/symbol", {"query": query},
                               lambda r, e: self._on_workspace_symbols(r, e, query),
                               transform=self._symbol_items)
            return
        # No query means "fill the panel with the project", which is the cache's
        # job; with the cache off there is nothing to fill it from.
        if not self._symbol_cache_enabled():
            self._symbol_cache_off()
            return
        ttl = self._symbol_cache_seconds()
        if ttl and self._symbol_cache:
            self._present_symbols(self._symbol_cache)
            if self._symbol_cache_stale():
                self._refresh_symbol_cache()
            return
        if self._symbol_dump is False:
            # This server has already told us it won't dump the workspace, so go
            # straight to searching for what the cursor is on.
            term = (self._selected_text() or self._word_at_cursor()).strip()
            if not term:
                N10X.Editor.SetStatusBarText(
                    f"{self.name}: this server needs a search term - put the "
                    f"cursor on a word, or type '{self.name} symbols <text>'")
                return
            self._send_request("workspace/symbol", {"query": term},
                               lambda r, e: self._on_workspace_symbols(r, e, term),
                               transform=self._symbol_items)
            return
        # Nothing cached yet: ask for the workspace and show it when it lands.
        self._send_request(
            "workspace/symbol", {"query": ""},
            lambda r, e: self._on_workspace_symbols(r, e, "", dump=True),
            transform=self._symbol_items)

    def refresh_symbols(self):
        """Drop the cached project symbols and fetch them again now. For when
        the find-symbol panel is behind after a branch switch or a build."""
        if not self._symbol_cache_enabled():
            self._symbol_cache_off()
            return
        if not self._symbol_cache_seconds():
            N10X.Editor.SetStatusBarText(
                f"{self.name}: nothing to rebuild - {self.name}."
                f"SymbolCacheSeconds is 0, so find-symbol already asks the "
                f"server on every open")
            return
        self._symbol_cache = []
        self._symbol_cache_time = 0.0
        self._symbol_dump = None
        self._symbol_dump_tries = 0
        if not self._ready():
            self.log("server not ready")
            return
        self._refresh_symbol_cache()
        N10X.Editor.SetStatusBarText(f"{self.name}: refreshing project symbols")

    def _selected_text(self):
        """The selected text when it's a single-line snippet we can search for,
        else "". Used to seed the project-wide symbol search."""
        try:
            text = N10X.Editor.GetSelection() or ""
        except Exception:
            return ""
        text = text.strip()
        return "" if "\n" in text or "\r" in text else text

    def _word_at_cursor(self):
        """The whole identifier the cursor sits in or next to (unlike
        _completion_word, which stops at the cursor). "" if there isn't one."""
        try:
            line = N10X.Editor.GetCurrentLine() or ""
            x, _ = N10X.Editor.GetCursorPos()
        except Exception:
            return ""
        if not line:
            return ""
        x = max(0, min(x, len(line)))

        def is_word(c):
            return c.isalnum() or c == "_"

        start = x
        while start > 0 and is_word(line[start - 1]):
            start -= 1
        end = x
        while end < len(line) and is_word(line[end]):
            end += 1
        return line[start:end]

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
        # A typed character can open or close a call, so re-check the args box on
        # the next tick, by which point the character is in the buffer.
        self._sig_dirty = True
        if not ch:
            return
        # Only act when the focused file is one we handle; otherwise typing in
        # another language's file (e.g. after switching workspaces) would queue
        # requests that just get rejected.
        try:
            if not self.handles(N10X.Editor.GetCurrentFilename()):
                return
        except Exception:
            return
        # A typed "(" is the one thing that opens the args box by itself;
        # _refresh_signature_help consumes this on the next tick.
        if ch == "(":
            self._sig_typed_open = True
        # As-you-type completion: schedule a (debounced) completion request when
        # an identifier char or a trigger char is typed. Each keystroke pushes
        # the due time forward, so a burst of typing fires a single request once
        # the user pauses for _auto_delay seconds.
        if self.setting("AutoComplete") == "false":
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
            # Any caret movement can take us into or out of a call's parentheses
            # (and non-char keys such as backspace/arrows only surface here), so
            # re-evaluate the args box on the next tick.
            if cur != prev:
                self._sig_dirty = True
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
            # Fill / retry the find-symbol cache in the background.
            if self._symbol_warm_due and now >= self._symbol_warm_due:
                self._symbol_warm_due = 0.0
                if self._ready():
                    self._refresh_symbol_cache()
            # Fire any debounced diagnostic pulls (pull-diagnostics clients only).
            if self._ready():
                self._flush_diag_pulls(now)
            # Re-check the args box once per input event, before the completion
            # branch below - that one returns early.
            if self._sig_dirty:
                self._sig_dirty = False
                self._refresh_signature_help(now)
            if self._ready() and self._sig_due and now >= self._sig_due:
                self._sig_due = 0.0
                self._request_signature_help()
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
            "symbols": self.list_symbols,
            "listsymbols": self.list_symbols,
            "functions": self.list_functions,
            "listfunctions": self.list_functions,
            "refreshsymbols": self.refresh_symbols,
            "reloadsymbols": self.refresh_symbols,
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
            raw = text.strip()
            prefix = self.name.lower()
            if not raw.lower().startswith(prefix):
                return False
            rest = raw[len(prefix):]
            # Only handle the friendly "<name> <command>" form (space/colon/dash
            # separator). A bare "<Name>_<Func>" string is one of our exported
            # functions, which 10x executes directly from the command panel - if
            # we matched it here too the command would run twice (the doubled
            # find-references output).
            if rest and rest[0] not in " :-":
                return False
            # Longest match wins, so multi-word commands ("list symbols") still
            # resolve and anything left over is an argument: "<Name> symbols
            # Widget" searches for "Widget". The argument keeps its original
            # case - it's a search term, not a command name.
            tokens = rest.lstrip(" :_-").split()
            fn, arg = None, ""
            for i in range(len(tokens), 0, -1):
                fn = self._command_table().get(
                    "".join(tokens[:i]).lower().replace("_", ""))
                if fn is not None:
                    arg = " ".join(tokens[i:])
                    break
            # Only the project-wide symbol search takes an argument; trailing
            # text on anything else is a typo, not a command we know.
            if fn is None or (arg and fn != self.list_symbols):
                self.log(f"unknown command '{text}'. Try: {self.name} status | "
                         f"complete | hover | signature | definition | references | "
                         f"functions | symbols [text] | refresh symbols | "
                         f"diagnostics | restart")
                return True
            if arg:
                fn(arg)
            else:
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
            "findfunction": self.list_functions,
            # Claimed even with SymbolCache off, when list_symbols does nothing
            # but say so in the status bar: 10x's own find-symbol panel has
            # nothing of value to show for a file the server handles, so a
            # blank panel would only be confusing.
            "findsymbol": self.list_symbols,
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
    
    def _on_workspace_opened(self, *args):
        """10x opened a different workspace. A server still rooted at the old one
        would answer about the wrong project, so retire it; the next handled file
        starts a fresh one at the new root."""
        try:
            if not (self.conn and self.conn.alive):
                return
            new_root = self._editor_workspace_root()
            if not new_root or path_within(new_root, self.root_path or ""):
                return
            self.log(f"workspace changed to {new_root} - restarting the server "
                     f"(was rooted at {self.root_path})")
            self.restart()
        except Exception as e:
            self.log(f"workspace-opened handler failed: {e}")

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
        self._retire_previous()
        self._check_parser_conflict()
        # Each handler is bound once and kept: the editor's Remove* functions
        # have to be handed the same object that Add* was given (see unregister).
        self._hooks = [
            ("AddOnFileOpenedFunction", "RemoveOnFileOpenedFunction",
             self._on_file_opened),
            ("AddPostFileSaveFunction", "RemovePostFileSaveFunction",
             self._on_post_save),
            ("AddOnCharKeyFunction", "RemoveOnCharKeyFunction",
             self._on_char_key),
            ("AddCursorMovedFunction", "RemoveCursorMovedFunction",
             self._on_cursor_moved),
            ("AddUpdateFunction", "RemoveUpdateFunction", self._on_update),
            ("AddExitingFunction", "RemoveExitingFunction", self._on_exit),
            ("AddCommandPanelHandlerFunction",
             "RemoveCommandPanelHandlerFunction", self._on_command_panel),
            ("AddInterceptCommandFunction", "RemoveInterceptCommandFunction",
             self._on_intercept_command),
            ("AddSymbolMouseHoverFunction", "RemoveSymbolMouseHoverFunction",
             self._on_mouse_hover),
            ("AddOnWorkspaceOpenedFunction", "RemoveOnWorkspaceOpenedFunction",
             self._on_workspace_opened),
        ]
        for add_name, _remove_name, handler in self._hooks:
            add = getattr(N10X.Editor, add_name, None)
            if add is None:
                self.log(f"{add_name} unavailable on this 10x build")
                continue
            try:
                add(handler)
            except Exception as e:
                self.log(f"{add_name} failed: {e}")
        self._registered = True
        try:
            cur = N10X.Editor.GetCurrentFilename()
            if self.handles(cur) and self.ensure_started(cur):
                self.did_open(cur)
        except Exception:
            pass
        self.log(f"registered (server: {' '.join(self._server_argv())})")

    def unregister(self):
        """Undo register(): drop the editor hooks and shut the server down."""
        for _add_name, remove_name, handler in (self._hooks or []):
            remove = getattr(N10X.Editor, remove_name, None)
            if remove is None:
                continue
            try:
                remove(handler)
            except Exception as e:
                self.log(f"{remove_name} failed: {e}")
        self._hooks = None
        self._registered = False
        try:
            self._teardown()
        except Exception:
            pass
        # Belt and braces, and after the teardown that clears it: a hook we
        # failed to remove would otherwise restart the server on the next update
        # tick. is_enabled() is False once disabled, which ensure_started checks.
        self.disabled = True

    def _retire_previous(self):
        """Shut down an earlier instance of this client, if one is still hooked
        up.

        10x re-executes the per-language scripts whenever a script file changes,
        so a deploy builds a second client while the first is still registered:
        every command then runs twice. The reload clears
        sys.modules, so a module-level registry would not survive it."""
        try:
            stale = [o for o in gc.get_objects()
                     if type(o).__name__ == type(self).__name__
                     and o is not self
                     and getattr(o, "name", None) == self.name
                     # No attribute at all means an instance from an older
                     # version of this file, which was registered by definition.
                     and getattr(o, "_registered", True)]
        except Exception as e:
            self.log(f"could not look for a previous instance: {e}")
            return
        for old in stale:
            try:
                old.unregister()
                self.log("retired the previous instance (script reload)")
            except Exception as e:
                self.log(f"could not retire the previous instance: {e}")
