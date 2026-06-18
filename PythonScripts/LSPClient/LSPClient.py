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
#     <name>.Enabled        "true"/"false" (default true)
#     <name>.AutoComplete   "true"/"false" - auto-trigger completion as you type
#                           (after identifier or trigger chars, debounced).
#                           Default false (use the keybinding instead).
#     <name>.Diagnostics    "true"/"false" - show the diagnostic under the
#                           cursor in the status bar (default true)
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
import json
import time
import queue
import shutil
import threading
import subprocess

import N10X

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_SEVERITY = {1: "Error", 2: "Warning", 3: "Info", 4: "Hint"}
_DEFAULT_ROOT_MARKERS = ("pyproject.toml", "setup.py", "setup.cfg",
                         "requirements.txt", ".git", "Pipfile", "package.json",
                         "Cargo.toml", "go.mod", "tsconfig.json")


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
    """Walk up from a file looking for a project marker; fall back to its dir."""
    d = os.path.dirname(os.path.abspath(file_path))
    cur = d
    while True:
        for m in markers:
            if os.path.exists(os.path.join(cur, m)):
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
        self._wlock = threading.Lock()
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

    # -- outgoing ----------------------------------------------------------

    def _write(self, payload):
        if not self.alive or self.proc.stdin is None:
            return
        data = json.dumps(payload).encode("utf-8")
        header = ("Content-Length: %d\r\n\r\n" % len(data)).encode("ascii")
        try:
            with self._wlock:
                self.proc.stdin.write(header + data)
                self.proc.stdin.flush()
            if self._verbose():
                self._log("--> " + json.dumps(payload)[:300])
        except (OSError, ValueError) as e:
            self.alive = False
            self._log(f"write failed: {e}")

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
        root_markers    Optional iterable of project-root marker filenames.
        init_options    Optional dict passed as initializationOptions.
    """

    def __init__(self, name, language_id, extensions, default_command="",
                 fallback_argv=None, trigger_chars="", root_markers=None,
                 init_options=None):
        self.name = name
        self.language_id = language_id
        self.extensions = tuple(extensions)
        self.default_command = default_command
        self.fallback_argv = fallback_argv
        self.trigger_chars = trigger_chars or ""
        self.root_markers = tuple(root_markers) if root_markers else _DEFAULT_ROOT_MARKERS
        self.init_options = init_options or {}

        self.conn = None
        self.initialized = False
        self.root_uri = None
        self.root_path = None
        self.pending = {}        # request id -> handler(result, error)
        self.docs = {}           # uri -> {"version", "text", "filename"}
        self.diagnostics = {}    # uri -> [Diagnostic]
        self._last_sync = 0.0
        self._sync_interval = 0.35
        self._completion_due = 0.0   # time.time() at which to auto-fire completion
        self._auto_delay = 0.12      # debounce window for as-you-type completion
        self._last_completion_id = None  # newest in-flight completion request id
        self._last_status_line = -1
        self._next_start_attempt = 0.0  # backoff for auto-starting the server
        self._verbose_flag = False       # cached so background threads can read it

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

    def ensure_started(self, root_hint):
        if self.conn and self.conn.alive:
            return True
        if self.setting("Enabled") == "false":
            return False

        self.root_path = find_project_root(root_hint, self.root_markers)
        self.root_uri = path_to_uri(self.root_path)
        argv = self._server_argv()
        if not argv:
            self.log("no server command configured; set " + self.name + ".Command")
            return False
        try:
            self.conn = LSPConnection(argv, self.root_path,
                                      log=self.log, verbose=self._verbose)
        except FileNotFoundError:
            self.log(f"could not launch server: '{argv[0]}' not found. "
                     f"Install it or set {self.name}.Command.")
            self.conn = None
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
        rid = self.conn.request("initialize", params)
        self.pending[rid] = self._on_initialized

    def _on_initialized(self, result, error):
        if error:
            self.log(f"initialize failed: {error}")
            return
        self.conn.notify("initialized", {})
        self.initialized = True
        N10X.Editor.SetStatusBarText(f"{self.name}: ready")
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
        if text == doc["text"] and not force:
            return
        doc["text"] = text
        doc["version"] += 1
        self.conn.notify("textDocument/didChange", {
            "textDocument": {"uri": uri, "version": doc["version"]},
            "contentChanges": [{"text": text}]})

    def did_save(self, filename):
        if not self.handles(filename) or not self._ready():
            return
        self.sync_current(force=True)
        uri = path_to_uri(filename)
        if uri in self.docs:
            self.conn.notify("textDocument/didSave",
                             {"textDocument": {"uri": uri}})

    # -- request helpers ---------------------------------------------------

    def _doc_pos_params(self):
        filename = N10X.Editor.GetCurrentFilename()
        if not self.handles(filename):
            return None
        x, y = N10X.Editor.GetCursorPos()
        return {"textDocument": {"uri": path_to_uri(filename)},
                "position": {"line": y, "character": x}}

    def _send_request(self, method, params, handler):
        if not self._ready():
            self.log("server not ready")
            return None
        rid = self.conn.request(method, params)
        self.pending[rid] = handler
        return rid

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
        else:
            # registerCapability, workDoneProgress/create, etc. - just ack.
            self.conn.respond(rid, None)

    def _handle_notification(self, method, params):
        if method == "textDocument/publishDiagnostics":
            self._on_diagnostics(params or {})
        elif method in ("window/showMessage", "window/logMessage"):
            text = (params or {}).get("message", "")
            if text and self._verbose():
                self.log("server: " + text)

    # -- diagnostics -------------------------------------------------------

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
            N10X.Editor.SetStatusBarText(
                f"{self.name}: {errs} error(s), {warns} warning(s)")
        self._last_status_line = -1  # force refresh on next cursor move

    def show_line_diagnostic(self):
        if self.setting("Diagnostics") == "false":
            return
        filename = N10X.Editor.GetCurrentFilename()
        if not self.handles(filename):
            return
        diags = self.diagnostics.get(path_to_uri(filename))
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
        diags = self.diagnostics.get(path_to_uri(filename), [])
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
            return
        # Order by the server's relevance ranking (sortText). Servers like
        # rust-analyzer encode "most relevant first" there; falling back to the
        # label keeps a stable order for items that omit it.
        items = sorted(items, key=lambda it: (it.get("sortText") is None,
                                              it.get("sortText") or "",
                                              it.get("label") or ""))
        prefix = self._line_prefix()
        limit = self._max_results()
        if self._verbose():
            try:
                x, y = N10X.Editor.GetCursorPos()
            except Exception:
                x, y = ("?", "?")
            self.log(f"completion: {len(items)} items (cap {limit}); "
                     f"cursor=({x},{y}) line_prefix={prefix!r}")
        labels, seen = [], set()
        for it in items:
            text = self._completion_insert_text(it, prefix)
            if self._verbose() and len(labels) < 5:
                edit = it.get("textEdit") or {}
                raw = edit.get("newText") or it.get("insertText") or it.get("label")
                self.log(f"   raw={raw!r} -> insert={text!r}")
            if text and text not in seen:
                seen.add(text)
                labels.append(text)
                if len(labels) >= limit:
                    break
        if not labels:
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

    def _completion_insert_text(self, item, prefix):
        """Turn an LSP completion item into the string to hand 10x.

        On accept, 10x inserts our string at the cursor and deletes nothing -
        so whatever the user has already typed before the cursor stays put.
        LSP items, however, give the full word/qualifier (e.g. "UpdateCursorMode"
        after typing "Update", or "Mode.VISUAL" after "Mode."). We strip the
        leading part of the item that duplicates the text already on the line
        immediately before the cursor, leaving only the remainder to insert.
        """
        edit = item.get("textEdit") or {}
        raw = edit.get("newText") or item.get("insertText") or item.get("label")
        if not raw:
            return ""
        # Longest suffix of `prefix` that the item also starts with (matched
        # case-insensitively so e.g. "upd" still lines up with "Update").
        overlap = 0
        for k in range(min(len(prefix), len(raw)), 0, -1):
            if prefix[-k:].lower() == raw[:k].lower():
                overlap = k
                break
        return raw[overlap:]

    def _show_autocomplete(self, labels):
        """Call 10x's ShowAutocomplete, tolerant of signature/format differences."""
        pos = N10X.Editor.GetCursorPos()
        attempts = (
            lambda: N10X.Editor.ShowAutocomplete(labels, pos),
            lambda: N10X.Editor.ShowAutocomplete(labels),
            lambda: N10X.Editor.ShowAutocomplete([{"text": l} for l in labels], pos),
            lambda: N10X.Editor.ShowAutocomplete([{"label": l} for l in labels], pos),
        )
        last_err = None
        for attempt in attempts:
            try:
                attempt()
                return True
            except Exception as e:
                last_err = e
        self.log(f"ShowAutocomplete failed for all formats: {last_err}")
        return False

    def _on_hover(self, result, error):
        text = extract_markup(result.get("contents")) if result else ""
        if not text.strip():
            N10X.Editor.SetStatusBarText(f"{self.name}: no hover info")
            return
        N10X.Editor.ShowMessageBox(f"{self.name} Hover", text)

    def _on_signature(self, result, error):
        if error or not result or not result.get("signatures"):
            N10X.Editor.SetStatusBarText(f"{self.name}: no signature")
            return
        sigs = result["signatures"]
        active = result.get("activeSignature", 0) or 0
        sig = sigs[active] if active < len(sigs) else sigs[0]
        N10X.Editor.SetStatusBarText(f"{self.name}: " + sig.get("label", ""))

    def _on_definition(self, result, error):
        loc = first_location(result)
        if not loc:
            N10X.Editor.SetStatusBarText(f"{self.name}: no definition found")
            return
        uri, rng = loc
        start = rng.get("start", {})
        N10X.Editor.OpenFile(uri_to_path(uri))
        N10X.Editor.SetCursorPos((start.get("character", 0), start.get("line", 0)))
        N10X.Editor.ScrollCursorIntoView()

    def _on_references(self, result, error):
        if error or not result:
            N10X.Editor.SetStatusBarText(f"{self.name}: no references found")
            return
        self.log(f"{len(result)} reference(s):")
        for loc in result:
            line = loc.get("range", {}).get("start", {}).get("line", 0) + 1
            self.log(f"  {uri_to_path(loc.get('uri', ''))}:{line}")
        N10X.Editor.SetStatusBarText(
            f"{self.name}: {len(result)} reference(s) - see output panel")

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
        self.log(f"  enabled setting : {self.setting('Enabled') or '(unset=true)'}")
        self.log(f"  autocomplete    : {self.setting('AutoComplete') or '(unset=false)'}")
        self.log(f"  server argv     : {self._server_argv()}")
        self.log(f"  connection      : {'alive' if (self.conn and self.conn.alive) else 'none/dead'}")
        self.log(f"  initialized     : {self.initialized}")
        self.log(f"  root            : {self.root_path}")
        self.log(f"  current file    : {fn}")
        self.log(f"  handled         : {self.handles(fn)}")
        self.log(f"  open documents  : {len(self.docs)}")

    def hover(self):
        params = self._doc_pos_params()
        if params is None:
            return
        self.sync_current(force=True)
        self._send_request("textDocument/hover", params, self._on_hover)

    def signature_help(self):
        params = self._doc_pos_params()
        if params is None:
            return
        self.sync_current(force=True)
        self._send_request("textDocument/signatureHelp", params, self._on_signature)

    def goto_definition(self):
        params = self._doc_pos_params()
        if params is None:
            return
        self.sync_current(force=True)
        self._send_request("textDocument/definition", params, self._on_definition)

    def find_references(self):
        params = self._doc_pos_params()
        if params is None:
            return
        params["context"] = {"includeDeclaration": True}
        self.sync_current(force=True)
        self._send_request("textDocument/references", params, self._on_references)

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
        if not ch or self.setting("AutoComplete") != "true":
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

    def _on_cursor_moved(self, *args):
        try:
            self.show_line_diagnostic()
        except Exception:
            pass

    def _on_update(self, *args):
        try:
            self.pump()
            now = time.time()
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
        }

    def _on_command_panel(self, text=None, *args):
        try:
            if not text:
                return False
            low = text.strip().lower()
            prefix = self.name.lower()
            if not low.startswith(prefix):
                return False
            cmd = low[len(prefix):].lstrip(" :_-").replace(" ", "").replace("_", "")
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

    def register(self):
        """Wire this client into the 10x editor events. Call once, on the main
        thread (e.g. via N10X.Editor.CallOnMainThread)."""
        self._refresh_verbose()
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
            cur = N10X.Editor.GetCurrentFilename()
            if self.handles(cur) and self.ensure_started(cur):
                self.did_open(cur)
        except Exception:
            pass
        self.log(f"registered (server: {' '.join(self._server_argv())})")
