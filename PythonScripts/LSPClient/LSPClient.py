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
#     <name>.SymbolFilterMinChars  Only ask the server once the filter is this
#                           long (default 3); shorter ones are answered from
#                           the cache, which keeps the blocking wait for
#                           queries selective enough to be worth it.
#     <name>.SymbolSource   Where the find-symbol list comes from:
#                           "workspace" - one workspace/symbol request, which
#                           only covers what the server's project index holds;
#                           "documents" - scan the project's files with
#                           documentSymbol, which sees every symbol in every
#                           file but costs a request per file (paced across
#                           update ticks, files closed again behind it);
#                           "auto" - workspace/symbol, falling back to the scan
#                           once the server's index proves empty (default).
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
#     <name>.SlowMainThreadMs  Diagnostic, off by default (0). Set to a
#                           millisecond budget (8 is half a 60fps frame) to log
#                           which of our editor callbacks overran it, and which
#                           phase of the update tick was to blame. "<name>
#                           status" lists the worst offenders seen so far.
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
# Windows thread priorities. Our threads inherit the editor's otherwise, so
# they compete with its UI thread for CPU - moving work off the main thread
# does not help if it just starves it instead.
_PRIORITY_BELOW_NORMAL = -1
_PRIORITY_LOWEST = -2


def lower_thread_priority(level=_PRIORITY_BELOW_NORMAL):
    """Drop the CALLING thread's priority. No-op off Windows or on failure."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        # HANDLE is pointer-sized; without this ctypes truncates it to int and
        # the call silently fails on 64-bit.
        k32.GetCurrentThread.restype = ctypes.c_void_p
        k32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
        return bool(k32.SetThreadPriority(k32.GetCurrentThread(), level))
    except Exception:
        return False
# Biggest response we will parse; past this it is dropped unparsed (see
# _drain_oversize). Well clear of normal traffic - a big reply is ~1 MB.
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
ERR_RESPONSE_TOO_LARGE = -32001    # our own code for that drop
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


# Memoized: a per-character loop called once per symbol, over a file set that
# repeats heavily. Sized above any project's file count - an LRU smaller than
# the working set cycles without ever hitting.
@functools.lru_cache(maxsize=65536)
def uri_to_path(uri):
    if not uri:
        return ""          # os.path.normpath("") is ".", a directory - never a file
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


def same_file(a, b):
    """Whether two paths name the same file. Case-insensitive on Windows."""
    if not a or not b:
        return False
    try:
        return (os.path.normcase(os.path.abspath(a))
                == os.path.normcase(os.path.abspath(b)))
    except (ValueError, TypeError, OSError):
        return False


def file_uri_path(uri):
    """The local path for a file:// URI, or "" for anything else. A path that
    names no real file can crash 10x's symbol panel, so filter here."""
    if not uri or not uri.startswith("file://"):
        return ""
    return uri_to_path(uri)


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


# Block size for the prefix/suffix scan below. Comparing slices runs at C
# speed; only the one block that differs is then walked character by character.
_DIFF_BLOCK = 4096


def incremental_change(old, new):
    """Single LSP incremental contentChange describing old -> new (a range
    replace covering everything between the common prefix and common suffix),
    or None when the text is unchanged. Positions are computed against `old`,
    which is what the server currently holds."""
    if old == new:
        return None
    old_len, new_len = len(old), len(new)
    limit = min(old_len, new_len)
    b = _DIFF_BLOCK
    p = 0
    while p + b <= limit and old[p:p + b] == new[p:p + b]:
        p += b
    while p < limit and old[p] == new[p]:
        p += 1
    s = 0
    max_s = limit - p
    while (s + b <= max_s
           and old[old_len - s - b:old_len - s] == new[new_len - s - b:new_len - s]):
        s += b
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
        # Blocking write/flush happens here, off the main thread. No
        # N10X.Editor calls - logging goes through plain print.
        lower_thread_priority()
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
        """Send a request, returning its id. `transform` runs on the READER
        thread before the reply is queued - keep it pure, no N10X.Editor. It is
        registered before the write so a fast reply cannot beat it."""
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
        """Reader thread: reshape a reply before the main thread sees it. A
        transform that raises becomes an error reply, never raw data - handlers
        are written against the transformed shape."""
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
        # Below normal: this parses replies and builds symbol rows, which on a
        # big project is sustained CPU the editor should always outrank.
        lower_thread_priority()
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
        """Throw away a response too big to parse, without ever holding it. The
        bytes must still leave the pipe or the stream desyncs; the head is kept
        only to fail the handler waiting on it."""
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
        lower_thread_priority(_PRIORITY_LOWEST)
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
                 symbol_source="auto",
                 init_options=None, ignore_dirs=None, line_comment="",
                 on_initialized=None, server_cwd=None, pull_diagnostics=False,
                 server_env=None):
        self.name = name
        self.language_id = language_id
        # Default for "<name>.SymbolSource" - a client whose server is known to
        # have a thin workspace/symbol can ship with "documents".
        self.symbol_source = symbol_source
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
        self._buffer_dirty = False       # a key edit since the last full read
        # Longest we will trust the cheap change signals before re-reading the
        # buffer anyway, for edits that arrive by a route we cannot observe.
        self._sync_safety = 2.0
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
        self._watch_baseline = False     # has that baseline been taken yet
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
        # Project-wide documentSymbol scan (see _start_document_scan).
        self._scan_active = False
        self._scan_gen = 0               # bumped on abort; stale readers stop
        self._scan_reader_done = False   # the prefetch thread reached the end
        self._scan_rows = []             # rows gathered so far
        self._scan_opened = set()        # uris we opened and must close again
        self._scan_inflight = 0
        self._scan_total = 0
        self._scan_done = 0              # files whose reply has come back
        self._scan_started = 0.0
        self._scan_progress = 0.0        # last time the scan moved at all
        self._scan_ready = None          # bounded queue of (path, uri, text)
        # Off-main-thread work, delivered back through _drain_background().
        self._bg_results = queue.Queue()
        self._bg_busy = set()            # tags with a job in flight
        self._symbol_warm_due = 0.0      # time.time() to (re)try filling it
        self._slow_ms_flag = 0.0         # cached SlowMainThreadMs; 0 = off
        self._slow_stats = {}            # handler -> [calls over, worst ms, last log]
        self._tick_phases = {}           # phase -> ms, for the last update tick
        self._funclist_token = 0         # newest ListFunctions request
        self._funclist_file = ""         # file the function panel is showing
        self._funclist_rows = (None, [])  # (file, rows) for the open panel
        self._funclist_filter = ""       # what is typed in that panel now
        self._funclist_asked = None      # file we have a fetch outstanding for
        # Live find-symbol filtering (the panel's filter callback).
        self._getsym_token = 0           # newest workspace/symbol query
        self._getsym_sent = None         # query we last asked the server for
        self._getsym_rows = (None, [])   # (query, rows) most recent answer
        self._getsym_seen = 0.0          # last time the panel asked us
        self._getsym_forced = ""         # query from "<name> symbols <text>"
        self._getsym_indexed = False     # has this server ever answered with rows
        self._getsym_retry = ("", 0, 0.0)  # (query, attempts, when to re-ask)
        self._panel_file = ""            # file the panel was opened from
        self._argv_cache = None          # (Command setting, resolved argv)
        # Set once we know which thread the editor calls us on - NOT here:
        # 10x runs the script on one thread and dispatches CallOnMainThread and
        # the hooks on another, so __init__'s thread is the wrong answer.
        self._main_thread = None
        self._warned_off_thread = False
        self._spawn_gen = 0              # bumped on teardown; stale spawns drop
        self._registered = False         # register() wired the editor hooks up
        self._hooks = None               # (add, remove, handler) for those hooks

    # -- logging / settings ------------------------------------------------

    def log(self, msg):
        _log(self.name, msg)

    def setting(self, key, default=""):
        """Read "<name>.<key>". Main thread only: off-thread this corrupts the
        interpreter's error state rather than raising, so workers must be handed
        setting values by their caller."""
        if self._main_thread is not None and threading.get_ident() != self._main_thread:
            if not self._warned_off_thread:
                self._warned_off_thread = True
                self.log(f"BUG: setting('{key}') read off the main thread; "
                         f"pass the value in from the caller instead")
            return default
        val = N10X.Editor.GetSetting(f"{self.name}.{key}")
        return val if val else default

    def _refresh_verbose(self):
        """Refresh cached settings that hot paths read. Main thread only."""
        self._verbose_flag = self.setting("LogVerbose") == "true"
        try:
            self._slow_ms_flag = max(0.0, float(self.setting("SlowMainThreadMs", "0")))
        except (TypeError, ValueError):
            self._slow_ms_flag = 0.0

    def _verbose(self):
        # Returns the cached flag so it is safe to call from any thread (e.g. the
        # connection's writer/reader). The flag is refreshed on the main thread.
        return self._verbose_flag

    def _timed(self, name, fn):
        """Wrap an editor callback so it reports when it overruns its budget.
        10x only times CallOnMainThread callbacks, leaving the update tick and
        input hooks - the ones that fire constantly - unmeasured."""
        def wrapper(*args, **kwargs):
            if not self._slow_ms_flag:
                return fn(*args, **kwargs)
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                ms = (time.perf_counter() - start) * 1000.0
                if ms >= self._slow_ms_flag:
                    self._note_slow(name, ms)
        return wrapper

    def _note_slow(self, name, ms):
        """Record and (sparingly) report a main-thread overrun. Rate-limited:
        logging every slow frame would itself be the slow thing."""
        stat = self._slow_stats.get(name)
        if stat is None:
            stat = self._slow_stats[name] = [0, 0.0, 0.0]
        stat[0] += 1
        stat[1] = max(stat[1], ms)
        now = time.time()
        if now - stat[2] >= 2.0:
            stat[2] = now
            detail = ""
            if name == "Update" and self._tick_phases:
                worst = sorted(self._tick_phases.items(), key=lambda kv: -kv[1])
                detail = " - " + ", ".join(f"{k} {v:.0f}ms" for k, v in worst[:4])
            self.log(f"SLOW main thread: {name} took {ms:.0f} ms "
                     f"(budget {self._slow_ms_flag:.0f} ms, {stat[0]} overrun(s), "
                     f"worst {stat[1]:.0f} ms){detail}")

    def handles(self, filename):
        return bool(filename) and filename.endswith(self.extensions)

    # -- lifecycle ---------------------------------------------------------

    def _resolve_argv(self, cmd):
        """Resolve the configured command to an argv. Worker-safe: takes the
        setting's value rather than reading it, since the PATH scan is slow
        enough to want off the main thread."""
        if cmd:
            return cmd.split()
        parts = self.default_command.split()
        exe = shutil.which(parts[0]) if parts else None
        if exe:
            return [exe] + parts[1:]
        if self.fallback_argv:
            return list(self.fallback_argv)
        return parts

    def _server_argv(self):
        """The resolved argv, cached. Only for callers that can afford a PATH
        scan; startup resolves on a worker instead (see ensure_started)."""
        cmd = self.setting("Command").strip()
        if self._argv_cache is not None and self._argv_cache[0] == cmd:
            return list(self._argv_cache[1])
        argv = self._resolve_argv(cmd)
        self._argv_cache = (cmd, list(argv))
        return argv

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
        """The directory of the workspace 10x has open, or "" if none - the
        project the user actually opened, unlike a walk up from a file."""
        try:
            ws = (N10X.Editor.GetWorkspaceFilename() or "").strip()
        except Exception:
            return ""
        if not ws:
            return ""
        d = os.path.dirname(os.path.abspath(ws))
        return d if os.path.isdir(d) else ""

    def _resolve_root(self, root_hint):
        """Where to root the server: 10x's workspace when the file is inside it,
        else a marker walk up from the file. The walk stops at the innermost
        marker, which would root a nested crate at itself."""
        ws = self._editor_workspace_root()
        if ws and path_within(ws, root_hint):
            return ws
        return find_project_root(root_hint, self.root_markers)

    def ensure_started(self, root_hint):
        """Make sure the server is coming up; True only once connected. The
        spawn runs on a worker, so this returns False meanwhile - callers treat
        that as "not yet" and _on_initialized opens the files."""
        if self.conn and self.conn.alive:
            return True
        if not self.is_enabled():
            return False
        if "spawn" in self._bg_busy:
            return False                 # already on its way

        # Settings and editor state have to be read here, on the main thread.
        # Resolving them against the filesystem does not, so that goes below.
        self.root_path = self._resolve_root(root_hint)
        self.root_uri = path_to_uri(self.root_path)
        cmd = self.setting("Command").strip()
        cached = (list(self._argv_cache[1])
                  if self._argv_cache is not None and self._argv_cache[0] == cmd
                  else None)
        cwd = self._resolve_server_cwd()
        env = self._resolve_server_env()
        log, verbose, gen = self.log, self._verbose, self._spawn_gen

        def spawn():
            # Worker thread: no N10X.Editor here. Both the PATH scan and the
            # process launch happen out here; the exception comes back as data
            # so the main thread can decide what to do about it.
            try:
                argv = cached if cached is not None else self._resolve_argv(cmd)
                if not argv:
                    return None, None, None
                return LSPConnection(argv, cwd, log=log, verbose=verbose,
                                     env=env), None, argv
            except Exception as e:
                return None, e, None

        self._run_off_thread(
            "spawn", spawn, lambda res: self._on_server_spawned(res, cmd, gen))
        return False

    def _on_server_spawned(self, result, cmd, gen):
        """Main thread: adopt the server the worker launched, or report why it
        could not be."""
        conn, err, argv = result
        if err is None and conn is None:
            self.log("no server command configured; set " + self.name + ".Command")
            return
        if argv:
            self._argv_cache = (cmd, list(argv))
        if err is not None:
            if isinstance(err, FileNotFoundError):
                self.log(f"could not launch server: "
                         f"'{(argv or [cmd or self.default_command])[0]}' not "
                         f"found. Install it or set {self.name}.Command.")
                self.disable()
            else:
                self.log(f"failed to start server: {err}")
            return
        # A restart or shutdown while we were launching leaves this one orphaned.
        stale = (gen != self._spawn_gen or not self.is_enabled()
                 or (self.conn and self.conn.alive))
        if stale:
            try:
                conn.shutdown()
            except Exception:
                pass
            return
        self.conn = conn
        self.log(f"started '{' '.join(argv)}' (root: {self.root_path})")
        self._send_initialize()

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
        if self.handles(fn):
            # Comes up on a worker thread; _on_server_spawned logs when it does.
            self.ensure_started(fn)

    def _teardown(self):
        # Any spawn still in flight belongs to the previous generation now.
        self._spawn_gen += 1
        self._argv_cache = None
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
        self._watch_baseline = False
        # The symbol cache describes the workspace as that server saw it.
        self._symbol_cache = []
        self._symbol_cache_time = 0.0
        self._symbol_cache_inflight = False
        self._getsym_indexed = False
        self._getsym_retry = ("", 0, 0.0)
        self._symbol_dump = None
        self._symbol_dump_tries = 0
        self._symbol_warm_due = 0.0
        # The connection is gone, so nothing to close - just drop the state.
        self._scan_gen += 1
        self._scan_active = False
        self._scan_ready = None
        self._scan_reader_done = False
        self._scan_rows = []
        self._scan_opened = set()
        self._scan_inflight = 0

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
        self.docs[uri] = {"version": 1, "text": text, "filename": filename,
                          "synced_at": time.time()}
        try:
            self.docs[uri]["lines"] = N10X.Editor.GetLineCount()
            self.docs[uri]["clean"] = not N10X.Editor.IsModified()
        except Exception:
            self.docs[uri]["lines"] = None
            self.docs[uri]["clean"] = False
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

    def _buffer_may_have_changed(self, doc):
        """Whether it is worth reading the whole buffer again. GetFileText
        costs time proportional to the file and this runs several times a
        second, so these cheaper signals gate it."""
        if self._buffer_dirty:
            return True
        try:
            # An unmodified buffer matches what is on disk, and we read it at
            # didOpen (or at the last save), so there is nothing to resend.
            # Any edit flips this before we look again.
            if not N10X.Editor.IsModified() and doc.get("clean"):
                return False
            lines = N10X.Editor.GetLineCount()
            if lines != doc.get("lines"):
                return True
            # Most edits land on the line the caret is on, and one line is
            # cheap to fetch even when the file is not.
            x, y = N10X.Editor.GetCursorPos()
            probe = N10X.Editor.GetLine(y)
            was = doc.get("probe")
            doc["probe"] = (y, probe)
            if was is not None and was[0] == y and was[1] != probe:
                return True
        except Exception:
            return True          # no cheap signal available - be correct, not fast
        return (time.time() - doc.get("synced_at", 0.0)) >= self._sync_safety

    def sync_current(self, force=False):
        """Push the current buffer to the server as a didChange if it changed.
        `force` means the caller wants current content, not that the buffer must
        be re-read - unchanged means the server's copy is already right."""
        if not self._ready():
            return
        filename = N10X.Editor.GetCurrentFilename()
        if not self.handles(filename):
            return
        uri = path_to_uri(filename)
        if uri not in self.docs:
            self.did_open(filename)
            return
        doc = self.docs[uri]
        if not self._buffer_may_have_changed(doc):
            return
        text = N10X.Editor.GetFileText(filename)
        if text is None:
            return
        self._buffer_dirty = False
        doc["synced_at"] = time.time()
        try:
            doc["lines"] = N10X.Editor.GetLineCount()
            doc["clean"] = not N10X.Editor.IsModified()
        except Exception:
            doc["lines"] = None
            doc["clean"] = False
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

    # Longest pump() will spend draining replies before leaving the rest for the
    # next tick. A message can cost real time to handle (a big diagnostics set,
    # or a log line per message when LogVerbose is on), so a count alone does
    # not bound this - only a clock does.
    _PUMP_BUDGET_MS = 6.0

    def pump(self):
        if not self.conn:
            return
        deadline = time.perf_counter() + self._PUMP_BUDGET_MS / 1000.0
        for _ in range(200):
            try:
                msg = self.conn.incoming.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle(msg)
            except Exception as e:
                self.log(f"error handling message: {e}")
            # Checked every message: perf_counter is far cheaper than handling
            # one, and checking in batches lets a few slow messages overshoot.
            # The queue keeps what we do not take; the next tick continues here.
            if time.perf_counter() >= deadline:
                break

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
                    self._watch_baseline = False
                    self._last_watch_scan = time.time()
                    # Seeded off-thread: on a few thousand files the walk is a
                    # quarter of a second, and this fires during startup.
                    ignore = self._all_ignore_dirs()
                    self._run_off_thread(
                        "watch-scan",
                        lambda ig=ignore: self._snapshot_watched_files(ig),
                        self._on_watch_baseline)
                if self._verbose():
                    self.log("file watching enabled (server registered "
                             "workspace/didChangeWatchedFiles)")

    def _apply_unregistrations(self, unregistrations):
        for reg in unregistrations or []:
            if reg.get("method") == "workspace/didChangeWatchedFiles":
                self._watch_enabled = False
                self._watch_mtimes = {}
                self._watch_baseline = False

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

    def _snapshot_watched_files(self, ignore):
        """Map every workspace file we handle to its mtime, as the baseline for
        detecting changes. Runs on a worker, so `ignore` must come from the
        caller - resolving it reads a setting."""
        snap = {}
        root = self.root_path
        if not root or not os.path.isdir(root):
            return snap
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
        """Tell the server about files created/changed/deleted on disk, which
        keeps its index right for files edited while not open. The walk runs on
        a worker: it is slow and this fires every couple of seconds."""
        if not (self._watch_enabled and self._ready() and self._watch_baseline):
            return
        if now - self._last_watch_scan < self._watch_interval:
            return
        self._last_watch_scan = now
        ignore = self._all_ignore_dirs()
        self._run_off_thread("watch-scan",
                             lambda ig=ignore: self._snapshot_watched_files(ig),
                             self._on_watch_snapshot)

    def _on_watch_baseline(self, new):
        """First snapshot: the starting point, so nothing is reported changed."""
        self._watch_mtimes = new
        self._watch_baseline = True
        self._last_watch_scan = time.time()

    def _on_watch_snapshot(self, new):
        if not (self._watch_enabled and self._ready()):
            return
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
        """Push (name, path, line, char, length) rows into the open find-function
        panel, which takes (name, line, char)."""
        try:
            N10X.Editor.SetFindFunctionPanelSymbols(
                [(name, line, char) for name, _p, line, char, _l in items])
        except Exception as e:
            self.log(f"SetFindFunctionPanelSymbols failed: {e}")

    def _on_function_filter(self, filter_text=None, *args):
        """10x asks for the function list, on open and on every filter change.

        The panel is already up, so we answer whenever the server does - no
        waiting, and nothing stale: a reply for a file we have left is dropped
        by _on_document_symbols."""
        try:
            filename = N10X.Editor.GetCurrentFilename() or self._funclist_file
            if not self.handles(filename) or not self._ready():
                return
            if path_to_uri(filename) in self._skipped_docs:
                return
            self._funclist_file = filename
            self._funclist_filter = (filter_text or "").strip()
            # The list itself cannot change while the panel is up, so fetch
            # once and re-filter it here on every keystroke.
            if self._funclist_rows[0] == filename:
                self._present_functions(
                    self._match_rows(self._funclist_rows[1],
                                     self._funclist_filter))
                return
            if self._funclist_asked == filename:
                return          # already asked; the reply will fill the panel
            self._funclist_asked = filename
            self.sync_current(force=True)
            self._funclist_token += 1
            token = self._funclist_token
            self._send_request(
                "textDocument/documentSymbol",
                {"textDocument": {"uri": path_to_uri(filename)}},
                lambda r, e: self._on_document_symbols(r, e, filename, token))
        except Exception as e:
            self.log(f"function filter failed: {e}")


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

    def _on_document_symbols(self, result, error, filename, token=None):
        # The panel must never open on the wrong file's functions: drop a reply
        # that a newer request has superseded, or that describes a file we have
        # navigated away from while it was in flight.
        if token is not None and token != self._funclist_token:
            return
        try:
            current = N10X.Editor.GetCurrentFilename()
        except Exception:
            current = filename
        if current and not same_file(current, filename):
            return
        if error or not result:
            N10X.Editor.SetStatusBarText(f"{self.name}: no symbols found")
            # Record the (empty) answer, or the fetch guard blocks every later
            # keystroke in this session.
            self._funclist_rows = (filename, [])
            self._funclist_asked = None
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
        # The panel has no filename column, so every row jumps within the
        # current file. Drop anything a server placed elsewhere (rare, and
        # SymbolInformation only) rather than jump to the wrong line.
        rows = [it for it in items if it[1] == default_path]
        self._funclist_rows = (filename, rows)
        self._funclist_asked = None
        self._present_functions(self._match_rows(rows, self._funclist_filter))

    def _symbol_items(self, result):
        """A workspace/symbol reply as sorted (name, path, line, char) rows.
        Runs on the READER thread as a request transform - keep it pure. A
        WorkspaceSymbol may carry no range, in which case we land at line 0."""
        seen, items = set(), []
        for sym in result or []:
            loc = sym.get("location", {}) or {}
            # Anything that is not a real file on disk is dropped - see
            # file_uri_path. A bad filename here can crash the editor.
            path = file_uri_path(loc.get("uri", ""))
            if not path:
                continue
            rng = loc.get("range", {}) or {}
            start = rng.get("start", {})
            line = max(0, start.get("line", 0) or 0)
            index = max(0, start.get("character", 0) or 0)
            key = (path, line, index)
            if key in seen:
                continue
            seen.add(key)
            items.append((self._qualified_name(sym.get("name"),
                                               sym.get("containerName") or ""),
                          path, line, index))
        items.sort(key=lambda it: (it[0].lower(), it[1], it[2]))
        return items


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
        """Give up on whole-workspace dumps when one came back too big to
        parse. Reuses _symbol_dump: from here it is the same situation as a
        server that will not dump, and the fallback term search is bounded."""
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
        """"<name>.SymbolCache" (default true). Off means no cached list, and
        find-symbol goes with it since the panel filters what it is handed;
        "<name> symbols <text>" still works. Drops the cache when turned off."""
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

    # -- background work --------------------------------------------------
    #
    # The editor's main thread must do nothing but talk to the editor. Anything
    # that walks the filesystem, reads files or chews through a big list runs
    # here instead and comes back on a later tick.

    def _run_off_thread(self, tag, fn, done):
        """Run fn() on a worker thread; call done(result) on a later update
        tick. One job per tag at a time; fn must touch no N10X.Editor API."""
        if tag in self._bg_busy:
            return False
        self._bg_busy.add(tag)

        def work():
            lower_thread_priority(_PRIORITY_LOWEST)   # nothing waits on these
            try:
                res, err = fn(), None
            except Exception as e:                # noqa: BLE001 - reported below
                res, err = None, e
            self._bg_results.put((tag, res, err, done))

        threading.Thread(target=work, daemon=True).start()
        return True

    def _drain_background(self):
        """Hand finished background work back on the main thread."""
        while True:
            try:
                tag, res, err, done = self._bg_results.get_nowait()
            except queue.Empty:
                return
            self._bg_busy.discard(tag)
            if err is not None:
                self.log(f"background {tag} failed: {err}")
                continue
            try:
                done(res)
            except Exception as e:
                self.log(f"background {tag} handler failed: {e}")

    # -- project-wide documentSymbol scan ---------------------------------
    #
    # workspace/symbol is only as good as the server's index, and servers cap
    # it (OLS at 100). documentSymbol has no cap but needs the file open on the
    # server, so the scan is paced across ticks and closes each file behind it.
    _SCAN_POPS_PER_TICK = 8            # files handed to the server per tick
    # Requests outstanding. Kept low: each one is a file open on the server,
    # and a wider window drives its peak memory up sharply.
    _SCAN_MAX_INFLIGHT = 4
    # Files read ahead of the main thread, bounded so our own peak memory does
    # not scale with the project.
    _SCAN_PREFETCH = 32
    # Give up if nothing moves for this long. A server that drops a reply would
    # otherwise leave the scan running for ever, and no later one could start.
    _SCAN_STALL_SECONDS = 60.0

    def _symbol_source(self):
        """"<name>.SymbolSource": "workspace" (one workspace/symbol request),
        "documents" (documentSymbol per file - complete, a request each), or
        "auto" (workspace/symbol, falling back to the scan when it is empty)."""
        val = (self.setting("SymbolSource", self.symbol_source)
               or "auto").strip().lower()
        return val if val in ("auto", "workspace", "documents") else "auto"

    @staticmethod
    def _document_symbol_rows(result, default_path):
        """One file's documentSymbol reply as (name, path, line, char) rows,
        children included - the shape the panel takes, so the cache needs no
        further work. Runs on the READER thread: keep it pure."""
        rows = []

        def walk(nodes, container=""):
            for node in nodes or []:
                name = node.get("name") or ""
                if "location" in node:            # SymbolInformation
                    loc = node.get("location", {}) or {}
                    path = file_uri_path(loc.get("uri", "")) or default_path
                    rng = loc.get("range") or {}
                    cont = node.get("containerName") or container
                else:                             # DocumentSymbol
                    path = default_path
                    rng = node.get("selectionRange") or node.get("range") or {}
                    cont = container
                start = rng.get("start", {})
                line = max(0, start.get("line", 0) or 0)
                ch = max(0, start.get("character", 0) or 0)
                if path:
                    rows.append((LanguageServerClient._qualified_name(name, cont),
                                 path, line, ch))
                # Members are qualified by the type/namespace holding them.
                walk(node.get("children") or [], name)

        walk(result)
        return rows

    def _start_document_scan(self, reason=""):
        """Begin walking the project, asking each file for its symbols.
        Enumerating and reading happen on workers; the main thread only sends
        requests and collects rows."""
        if self._scan_active or not self._ready():
            return
        if self.server_caps and not self.server_caps.get("documentSymbolProvider"):
            self.log("server has no documentSymbol support, so the project "
                     "cannot be scanned for symbols")
            return
        # Read on the main thread while we still can: the reader thread must
        # not touch N10X.Editor, and both of these are settings lookups.
        limit = self._max_file_bytes()
        already_open = set(self.docs) | set(self._skipped_docs)
        ignore = self._all_ignore_dirs()
        self._scan_active = True
        self._scan_started = time.time()
        self._scan_progress = self._scan_started
        self._scan_reason = reason
        # None means "enumerating": the pump must not mistake an empty queue
        # for a finished scan before the file list has arrived.
        self._scan_ready = None
        self._scan_reader_done = False
        self._scan_done = 0
        self._scan_total = 0
        self._scan_gen += 1
        gen = self._scan_gen
        self._run_off_thread(
            "scan-enumerate",
            lambda: self._collect_scan_files(ignore),
            lambda paths: self._on_scan_files(paths, limit, already_open, gen))

    def _collect_scan_files(self, ignore):
        """Worker thread: just the file list. Reading them is the prefetch
        thread's job, so we never hold the whole project's text at once."""
        return sorted(self._snapshot_watched_files(ignore))

    def _scan_reader(self, paths, limit, already_open, gen):
        """Prefetch thread: read files a little ahead of the main thread. The
        bounded queue parks this when the editor is not consuming, so peak
        memory does not scale with the project."""
        lower_thread_priority(_PRIORITY_LOWEST)   # background indexing only
        q = self._scan_ready
        queued = 0
        for path in paths:
            if not self._scan_active or gen != self._scan_gen:
                return
            uri = path_to_uri(path)
            if uri in already_open:
                item = (path, uri, None)      # the server already has this one
            else:
                try:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except OSError:
                    continue
                if limit and len(text.encode("utf-8", "ignore")) > limit:
                    continue
                item = (path, uri, text)
            while True:
                if not self._scan_active or gen != self._scan_gen:
                    return
                try:
                    q.put(item, timeout=0.2)
                    queued += 1
                    break
                except queue.Full:
                    continue
        try:
            # The count is what was really queued: files skipped as unreadable
            # or oversized never reach the editor, so paths would overstate it.
            q.put(("__end__", queued), timeout=2.0)
        except Exception:
            pass

    def _on_scan_files(self, paths, limit, already_open, gen):
        if not self._scan_active or gen != self._scan_gen:
            return                      # aborted while we were enumerating
        if not paths:
            self._scan_active = False
            return
        self._scan_rows = []
        self._scan_inflight = 0
        self._scan_done = 0
        self._scan_total = len(paths)
        self._scan_reader_done = False
        self._scan_ready = queue.Queue(maxsize=self._SCAN_PREFETCH)
        threading.Thread(
            target=self._scan_reader,
            args=(paths, limit, already_open, gen), daemon=True).start()
        reason = getattr(self, "_scan_reason", "")
        self.log(f"scanning {len(paths)} file(s) for project symbols"
                 f"{' (' + reason + ')' if reason else ''}")

    def _abort_document_scan(self):
        self._scan_reason = ""
        self._scan_gen += 1             # tells the prefetch thread to stop
        for uri in list(self._scan_opened):
            self._close_scanned(uri)
        self._scan_active = False
        self._scan_ready = None
        self._scan_reader_done = False
        self._scan_rows = []
        self._scan_inflight = 0

    def _close_scanned(self, uri):
        """Close a file the scan opened. Never touches self.docs - a file the
        user actually has open was not opened by us and must stay open."""
        if uri not in self._scan_opened:
            return
        self._scan_opened.discard(uri)
        if self._ready():
            self.conn.notify("textDocument/didClose",
                             {"textDocument": {"uri": uri}})

    def _scan_one(self, entry):
        """Hand one already-read file to the server. Editor/IO work is done:
        this is a notify and a request, nothing more."""
        path, uri, text = entry
        if text is not None:
            self.conn.notify("textDocument/didOpen", {
                "textDocument": {"uri": uri, "languageId": self.language_id,
                                 "version": 1, "text": text}})
            self._scan_opened.add(uri)
        rid = self._send_request(
            "textDocument/documentSymbol", {"textDocument": {"uri": uri}},
            lambda r, e, u=uri: self._on_scan_symbols(r, e, u),
            transform=lambda r, pth=path: self._document_symbol_rows(r, pth))
        if rid is None:
            self._close_scanned(uri)
            return False
        self._scan_inflight += 1
        return True

    def _pump_document_scan(self):
        """Advance the scan a little. The files are already read, so all this
        does is send - kept rationed anyway so a tick stays predictable."""
        if not self._scan_active or self._scan_ready is None:
            return
        if not self._ready():
            self._abort_document_scan()
            return
        for _ in range(self._SCAN_POPS_PER_TICK):
            if self._scan_inflight >= self._SCAN_MAX_INFLIGHT:
                break
            try:
                item = self._scan_ready.get_nowait()
            except queue.Empty:
                break                   # the reader has not caught up yet
            if item and item[0] == "__end__":
                self._scan_reader_done = True
                self._scan_total = item[1]
                break
            self._scan_one(item)
            self._scan_progress = time.time()
        if (self._scan_reader_done and not self._scan_inflight
                and self._scan_ready.empty()):
            self._finish_document_scan()
        elif time.time() - self._scan_progress > self._SCAN_STALL_SECONDS:
            self.log(f"symbol scan stalled with {self._scan_inflight} request(s) "
                     f"outstanding; giving up so a later one can run")
            self._abort_document_scan()

    def _on_scan_symbols(self, result, error, uri):
        self._scan_inflight = max(0, self._scan_inflight - 1)
        self._close_scanned(uri)
        self._scan_done += 1
        self._scan_progress = time.time()
        if not error and result:
            # Appended as each file lands, so finishing costs nothing. Files go
            # out in order with only a few requests in flight, so the list ends
            # up in roughly file order; the panel filters on what you type, so
            # exact ordering does not matter enough to sort for.
            self._scan_rows.extend(result)
        if (self._scan_active and self._scan_reader_done
                and not self._scan_inflight
                and self._scan_ready is not None and self._scan_ready.empty()):
            self._finish_document_scan()

    def _finish_document_scan(self):
        rows, total = self._scan_rows, self._scan_total
        took = time.time() - self._scan_started
        self._scan_active = False
        self._scan_ready = None
        self._scan_reader_done = False
        self._scan_rows = []
        self._scan_inflight = 0
        if not rows:
            self.log(f"scanned {total} file(s), found no symbols")
            return
        self._symbol_cache = rows
        self._symbol_cache_time = time.time()
        self._symbol_dump = True
        self._symbol_dump_tries = 0
        self.log(f"indexed {len(rows)} symbol(s) from {total} file(s) "
                 f"in {took:.1f}s")

    def _note_dump_filled(self, items):
        """Record a successful dump, and while the symbol count is still
        climbing line up another pass - servers keep indexing after they first
        answer, so an early list is usually partial."""
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
            if self._symbol_source() == "auto":
                self._warm_symbol_cache(delay=0.5)   # routes to the scan now
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
        """Fill the find-symbol cache in the background, so the first
        FindSymbol opens on a full list instead of triggering the fetch."""
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
        source = self._symbol_source()
        if source == "documents":
            self._start_document_scan()
            return
        if self._symbol_dump is False:
            # No whole-project list from this server, and none needed: typing
            # in the panel queries it directly. Only "documents" scans.
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
        if self._slow_stats:
            worst = sorted(self._slow_stats.items(), key=lambda kv: -kv[1][1])
            self.log(f"  main-thread     : {len(self._slow_stats)} handler(s) over "
                     f"{self._slow_ms_flag:.0f} ms")
            for name, (count, peak, _last) in worst[:5]:
                self.log(f"      {name:<24} {count:>5} overrun(s), worst {peak:.0f} ms")
        elif not self._slow_ms_flag:
            self.log(f"  main-thread     : not measured (set "
                     f"{self.name}.SlowMainThreadMs: 8 to report stutters)")
        else:
            self.log(f"  main-thread     : nothing over {self._slow_ms_flag:.0f} ms")
        self.log(f"  symbol source   : {self._symbol_source()}"
                 f"{f' (scanning {self._scan_done}/{self._scan_total})' if self._scan_active else ''}")
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
        self._funclist_file = filename
        self._funclist_rows = (None, [])     # this session re-fetches once
        self._funclist_filter = ""
        self._funclist_asked = None
        # 10x asks us for the list on open and on every filter change, so the
        # panel never waits on us.
        try:
            N10X.Editor.ShowFindFunctionPanel(self._on_function_filter)
        except Exception as e:
            self.log(f"ShowFindFunctionPanel failed: {e}")

    def list_symbols(self, query=None):
        """Open 10x's find-symbol panel on the project's symbols. An unqualified
        call is served from the cache; a query ("<Name> symbols <text>") always
        searches the server. Typing in the panel goes to _on_get_symbols."""
        try:
            self._panel_file = N10X.Editor.GetCurrentFilename() or ""
        except Exception:
            self._panel_file = ""
        # A fresh panel session re-queries: the file may have changed since the
        # last one, so previous answers for a filter are not to be trusted.
        self._getsym_sent = None
        self._getsym_rows = (None, [])
        self._getsym_retry = ("", 0, 0.0)
        # A query typed as "<Name> symbols <text>" seeds the panel until the
        # user types their own filter.
        self._getsym_forced = (query or "").strip()
        if not self._ready():
            self.log("server not ready")
            return
        # Some servers (pylsp) implement documentSymbol but not workspace/symbol.
        # They say so at initialize; better to explain than to fire a request
        # that comes back MethodNotFound.
        if self.server_caps and not self.server_caps.get("workspaceSymbolProvider"):
            self._no_workspace_symbols()
            return
        # No query means "fill the panel with the project", which is the cache's
        # job; with the cache off there is nothing to fill it from.
        if not self._symbol_cache_enabled():
            self._symbol_cache_off()
            return
        # _on_get_symbols answers the panel and pushes better rows as the
        # server replies, so this returns at once with nothing to wait for.
        try:
            N10X.Editor.ShowFindSymbolPanel(self._on_get_symbols)
        except Exception as e:
            self.log(f"ShowFindSymbolPanel failed: {e}")
            return
        if self._symbol_source() == "documents":
            self._start_document_scan()
        elif not self._symbol_cache or self._symbol_cache_stale():
            self._refresh_symbol_cache()

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
        self._abort_document_scan()
        if not self._ready():
            self.log("server not ready")
            return
        if self._symbol_source() == "documents":
            self._start_document_scan("rebuild requested")
        else:
            self._refresh_symbol_cache()
        N10X.Editor.SetStatusBarText(f"{self.name}: refreshing project symbols")


    # -- comment toggling --------------------------------------------------
    # Commenting is a purely editor-side text edit (LSP has no comment API), so
    # these work without a running server.

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
        # ... and our copy of the buffer is now stale, so the next sync must
        # actually re-read it rather than trust the cheap change signals.
        self._buffer_dirty = True
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
        # The editor calls this every frame, so it is the authority on which
        # thread is "the main thread" - cheaper than being wrong.
        self._main_thread = threading.get_ident()
        # Phase timings, so an overrun says which part was slow rather than
        # just that the tick was. perf_counter is ~50ns; only phases that
        # actually cost something are recorded.
        phases = self._tick_phases
        phases.clear()
        mark = [time.perf_counter()]

        def lap(label):
            if not self._slow_ms_flag:
                return
            t = time.perf_counter()
            ms = (t - mark[0]) * 1000.0
            mark[0] = t
            if ms >= 1.0:
                phases[label] = phases.get(label, 0.0) + ms

        try:
            self.pump()
            lap("pump")
            now = time.time()
            # Deferred re-request (e.g. a goto-definition that came back empty
            # while the server was still indexing) fires as soon as it's due.
            if self._retry_action and now >= self._retry_due:
                action = self._retry_action
                self._retry_action = None
                self._retry_due = 0.0
                if self._ready():
                    action()
                lap("retry")
            self._pump_symbol_retry(now)
            # Collect anything a worker thread finished, then feed the scan.
            self._drain_background()
            lap("background")
            self._pump_document_scan()
            lap("scan")
            # Fill / retry the find-symbol cache in the background.
            if self._symbol_warm_due and now >= self._symbol_warm_due:
                self._symbol_warm_due = 0.0
                if self._ready():
                    self._refresh_symbol_cache()
                lap("symbol-refresh")
            # Fire any debounced diagnostic pulls (pull-diagnostics clients only).
            if self._ready():
                self._flush_diag_pulls(now)
                lap("diagnostics")
            # Re-check the args box once per input event, before the completion
            # branch below - that one returns early.
            if self._sig_dirty:
                self._sig_dirty = False
                self._refresh_signature_help(now)
                lap("signature-refresh")
            if self._ready() and self._sig_due and now >= self._sig_due:
                self._sig_due = 0.0
                self._request_signature_help()
                lap("signature-request")
            # Completion fires as soon as it's due (not throttled).
            if (self._ready() and self._completion_due
                    and now >= self._completion_due):
                self._completion_due = 0.0
                self.sync_current(force=True)
                lap("completion-sync")
                self._request_completion()
                lap("completion-request")
                self._last_sync = now
                return
            # Throttled housekeeping. Runs even before the server is ready so a
            # workspace whose Python files are already open gets picked up
            # without a file-open event (e.g. switching to a restored tab).
            if now - self._last_sync >= self._sync_interval:
                self._last_sync = now
                self._refresh_verbose()
                lap("refresh-settings")
                self._reconcile_open_files(now)
                lap("reconcile-open-files")
                if self._ready():
                    self.sync_current()
                    lap("sync-current")
                    # Self-throttled (no-op unless this server registered a
                    # watcher and the scan interval has elapsed). Of our current
                    # servers only ols registers one; rust-analyzer/pylsp don't.
                    self._scan_watched_files(now)
                    lap("watch-scan")
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

    # -- live find-symbol filtering ----------------------------------------

    _GETSYM_LIMIT = 300              # rows handed back for one filter
    # How long after the panel last asked us we still consider it open. Only a
    # guard against writing into a panel the user closed; the setter does not
    # open one, so err generous - a slow server must not lose its answer.
    _GETSYM_FRESH = 60.0

    def _on_get_symbols(self, filter_text=None, symbols=None, *args):
        """10x asks us for symbols each time the find-symbol filter changes.

        Synchronous, so we answer from what we already hold and start a
        workspace/symbol query for the typed text; its reply refreshes the
        panel a moment later. That is what makes servers with a capped or empty
        whole-project dump (rust-analyzer, Roslyn) usable - a search is what
        workspace/symbol is actually for."""
        if symbols is None:
            symbols = []
        try:
            if not self._owns_symbol_panel():
                return symbols
            self._getsym_seen = time.time()
            query = (filter_text or "").strip() or self._getsym_forced
            if filter_text:
                self._getsym_forced = ""      # the user is driving now
            rows, how = self._rows_for_query(query), "cache"
            # Short filters come off the cache. With no cache to fall back on
            # (servers that never hand over a project list) we must still ask.
            worth_asking = (len(query) >= self._symbol_filter_min_chars()
                            or not self._symbol_cache)
            if query and worth_asking and self._ready():
                # Results are pushed when they arrive - nothing to wait for.
                self._query_symbols(query)
            if not rows:
                rows = self._status_rows(query)
                how = "status"
            rows = rows[:self._GETSYM_LIMIT]
            self._set_symbol_rows(rows)
            symbols.extend(rows)
            if self._verbose():
                self.log(f"get-symbols {query!r} -> {len(rows)} row(s) ({how})")
        except Exception as e:
            self.log(f"get-symbols failed: {e}")
        return symbols

    def _symbol_filter_min_chars(self):
        """Shortest filter worth asking the server about. One or two characters
        match half the project, so the cache answers those for free; the block
        is spent where the query is actually selective."""
        try:
            return max(0, int(self.setting("SymbolFilterMinChars", "3")))
        except (TypeError, ValueError):
            return 3

    def _set_symbol_rows(self, rows):
        """Push rows into the open find-symbol panel."""
        try:
            N10X.Editor.SetFindSymbolPanelSymbols(rows)
        except Exception as e:
            self.log(f"SetFindSymbolPanelSymbols failed: {e}")

    def _pending_row(self, message):
        """One non-symbol row explaining why the panel is empty. Anchored to a
        real file so selecting it cannot mislead, and never cached."""
        path = self._panel_file
        if not path or not os.path.isfile(path):
            try:
                path = N10X.Editor.GetCurrentFilename() or ""
            except Exception:
                path = ""
        if not path or not os.path.isfile(path):
            return []
        return [(message, path, 0, 0)]

    def _waiting_message(self, query=""):
        """What to say while there is nothing to show yet."""
        if self._scan_active and self._scan_total:
            return (f"[{self.name}] scanning project - {self._scan_done} of "
                    f"{self._scan_total} files...")
        if query:
            return f"[{self.name}] searching for '{query}'..."
        return f"[{self.name}] searching project, please wait..."

    def _status_rows(self, query):
        """The row to show when there are no symbols: still searching, or the
        server answered and found none. Never push an empty list - the panel
        then shows nothing at all and does not redraw until the filter
        changes."""
        answered, _rows = self._getsym_rows
        if query and answered == query:
            if self._getsym_retry[0] == query:
                # Empty so far, but the server has never returned a symbol -
                # it is most likely still indexing, so keep asking.
                return self._pending_row(f"[{self.name}] indexing - no matches "
                                         f"for '{query}' yet...")
            return self._pending_row(f"[{self.name}] no symbols matching "
                                     f"'{query}'")
        return self._pending_row(self._waiting_message(query))

    def _owns_symbol_panel(self):
        """Whether this client should answer for the panel now. Several clients
        are usually registered, and only the one handling the file the panel was
        opened from should contribute."""
        try:
            cur = N10X.Editor.GetCurrentFilename() or ""
        except Exception:
            cur = ""
        # The panel may hold focus, in which case there is no current file and
        # the one it was opened from is the best answer we have.
        return self.handles(cur or self._panel_file)

    @staticmethod
    def _rank_rows(rows, query):
        """Best matches first, using the same scoring as completion: a prefix
        beats a word start beats mid-word. Servers do not rank for us -
        rust-analyzer returns MovingSphere before Sphere for "sphere"."""
        if not query:
            return rows
        q = query.lower()
        ranked = []
        for row in rows:
            score = fuzzy_score(row[0], q)
            # Rows the server matched some other way go last, in their order.
            ranked.append(((0,) + score if score else (1, 0, 0), row))
        ranked.sort(key=lambda pair: pair[0])
        return [row for _key, row in ranked]

    # Most we collect for one keystroke, and the largest cache we will run the
    # subsequence pass over. The cache is sorted by name, so bounding either
    # pass by position would hide whole stretches of the alphabet - the dear
    # pass is skipped outright instead.
    _MATCH_CANDIDATES = 1500
    _FUZZY_MAX_ROWS = 20000

    @staticmethod
    def _match_rows(rows, query):
        """Rows matching `query`, best first. Substring hits are collected
        first because that test runs at C speed; the subsequence scan only runs
        when they are too few to be worth showing."""
        if not query:
            return rows
        q = query.lower()
        cap = LanguageServerClient._MATCH_CANDIDATES
        hits = []
        for r in rows:
            if q in r[0].lower():
                hits.append(r)
                if len(hits) >= cap:
                    break
        if len(hits) < 50 and len(rows) <= LanguageServerClient._FUZZY_MAX_ROWS:
            seen = {id(r) for r in hits}
            for r in rows:
                if id(r) not in seen and fuzzy_score(r[0], q):
                    hits.append(r)
                    if len(hits) >= cap:
                        break
        return LanguageServerClient._rank_rows(hits, query)

    def _rows_for_query(self, query):
        """Best rows we can produce for `query` without waiting on the server:
        the last answer if it was for this query, else the cache filtered."""
        got_q, got_rows = self._getsym_rows
        if query and got_q == query:
            return got_rows
        return self._match_rows(self._symbol_cache, query)

    # A server still building its index answers at once with nothing, and the
    # panel only calls us again when the filter text changes.
    _GETSYM_RETRIES = (1.0, 2.0, 4.0, 8.0, 15.0)

    def _schedule_symbol_retry(self, query, got_rows):
        """Arrange to re-ask an empty query, until the server proves indexed."""
        if got_rows:
            self._getsym_indexed = True
            self._getsym_retry = ("", 0, 0.0)
            return
        # A filled cache is equally good proof that the index is up.
        if self._getsym_indexed or self._symbol_cache:
            return                      # indexed and empty means empty
        prev_q, tries, _due = self._getsym_retry
        tries = tries + 1 if query == prev_q else 1
        if tries > len(self._GETSYM_RETRIES):
            self._getsym_retry = ("", 0, 0.0)   # out of patience; empty it is
            return
        self._getsym_retry = (query, tries,
                              time.time() + self._GETSYM_RETRIES[tries - 1])

    def _pump_symbol_retry(self, now):
        query, tries, due = self._getsym_retry
        if not query or not due or now < due:
            return
        self._getsym_retry = (query, tries, 0.0)
        if now - self._getsym_seen > self._GETSYM_FRESH or not self._ready():
            return
        if self._getsym_sent != query:
            # The user typed on; that query owns the panel and will arrange its
            # own retry if it also comes back empty.
            self._getsym_retry = ("", 0, 0.0)
            return
        self._getsym_sent = None        # or the repeat query is skipped
        self._query_symbols(query)

    def _query_symbols(self, query):
        """Ask the server for symbols matching `query`, superseding any older
        query. Skipped when we already asked for exactly this text."""
        if query == self._getsym_sent:
            return
        self._getsym_sent = query
        self._getsym_token += 1
        token = self._getsym_token
        self._send_request(
            "workspace/symbol", {"query": query},
            lambda r, e: self._on_symbol_query(r, e, query, token),
            transform=lambda res, q=query: self._rank_rows(
                self._symbol_items(res), q))

    def _on_symbol_query(self, result, error, query, token):
        if error or token != self._getsym_token:
            return
        rows = result or []
        self._getsym_rows = (query, rows)
        self._schedule_symbol_retry(query, bool(rows))
        # Only while the panel is plainly still up, so a late reply cannot
        # write into one the user has closed.
        if time.time() - self._getsym_seen > self._GETSYM_FRESH:
            return
        self._set_symbol_rows(rows[:self._GETSYM_LIMIT]
                              if rows else self._status_rows(query))
        if self._verbose():
            self.log(f"pushed {len(rows)} row(s) for {query!r} "
                     f"{(time.time() - self._getsym_seen):.2f}s after the panel "
                     f"last asked")

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
        # This arrives via CallOnMainThread, so it is the editor's thread.
        # Claim it before the first setting read below.
        self._main_thread = threading.get_ident()
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
        # Wrapped in place so the same object is handed to Remove* later.
        self._hooks = [(a, r, self._timed(a[3:-8] if a.startswith("Add") else a, h))
                       for a, r, h in self._hooks]
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
        # The configured command, not the resolved path: resolving means a
        # PATH scan, and _on_server_spawned logs the full argv anyway.
        self.log(f"registered (server: "
                 f"{self.setting('Command').strip() or self.default_command})")

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
