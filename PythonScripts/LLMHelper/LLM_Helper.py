# LLMHelper.py — Ollama chat (print-only) + direct call via KeyBindings
# To bind a shortcut: Settings → Key Bindings then add for example:
#   Control F9: LLM_SendSelectionToChat()
# (The Python function is called directly by the keymap.)

import os
import json
import urllib.request
import urllib.error
import N10X

LLM_HOST: str | None = None
LLM_MODEL: str | None = None

ICON_OK  = "✅"
ICON_WRN = "⚠️"
ICON_ERR = "🛑"
ICON_BOT = "🤖"

# ---------- Init provider (env -> globals) ----------
def __initialize_llm_provider(_dt: float = 0.0) -> None:
    global LLM_HOST, LLM_MODEL

    host = (
        os.getenv("10X_LLM_HOST")
        or os.getenv("10x_LLM_HOST")
        or os.getenv("10x_llm_host")
        or ""
    ).strip()

    model = (
        os.getenv("10X_LLM_MODEL")
        or os.getenv("10x_LLM_MODEL")
        or os.getenv("10x_llm_model")
        or ""
    ).strip()

    LLM_HOST = host if host else None
    LLM_MODEL = model if model else None

    if LLM_HOST:
        print(f"LLMHelper: {ICON_OK} LLM HOST found: '{LLM_HOST}'")
    else:
        print(f"LLMHelper: {ICON_WRN} LLM HOST not found!")

    if LLM_MODEL:
        print(f"LLMHelper: {ICON_OK} LLM MODEL selected '{LLM_MODEL}'")
    else:
        print(f"LLMHelper: {ICON_WRN} LLM MODEL not found!")

    try:
        N10X.Editor.RemoveUpdateFunction(__initialize_llm_provider)
    except Exception:
        pass

# ---------- HTTP helper ----------
def __http_post_json(url: str, payload: dict, timeout: float = 60.0) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

# ---------- Ollama chat ----------
def __llm_ollama_chat(question: str) -> str | None:
    """
    Sends 'question' to Ollama via /api/chat with the LLM_MODEL model.
    Displays the response via print and returns it.
    """
    global LLM_HOST, LLM_MODEL

    if not question or not question.strip():
        print(f"{ICON_WRN} LLMHelper: empty question.")
        return None

    host = (LLM_HOST or "http://localhost:11434").rstrip("/")
    model = (LLM_MODEL or "").strip()

    if not model:
        print(f"{ICON_ERR} LLMHelper: no model (LLM_MODEL) is defined.")
        return None

    url = f"{host}/api/chat"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": question.strip()}],
        "stream": False,
    }

    try:
        resp = __http_post_json(url, body, timeout=120.0)
        msg = resp.get("message") or {}
        content = (msg.get("content") or resp.get("response") or "").strip()

        if content:
            print(f"{ICON_OK} {ICON_BOT} Ollama ({model}):\n{content}")
            return content
        else:
            print(f"{ICON_WRN} LLMHelper: empty response from Ollama.")
            return None

    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = str(e)
        print(f"{ICON_ERR} LLMHelper: HTTP {e.code} on {url} — {detail}")
    except urllib.error.URLError as e:
        print(f"{ICON_ERR} LLMHelper: connection failed to {url} — {e.reason}")
    except Exception as e:
        print(f"{ICON_ERR} LLMHelper: unexpected error — {e}")

    return None

# ---------- Selection utilities ----------
def __get_selection_text() -> str:
    try:
        # The correct 10x API to retrieve the selection
        return N10X.Editor.GetSelection()
    except Exception as e:
        print(f"{ICON_ERR} LLMHelper: error retrieving selection — {e}")
        return ""

# ---------- Function called directly by the keybinding ----------
def LLMHelperCmd() -> None:
    sel = __get_selection_text()
    if not sel.strip():
        print(f"{ICON_WRN} LLMHelper: no selection. Select text then retry.")
        return
    __llm_ollama_chat(sel)

# ---------- Schedule init in the update cycle ----------
try:
    N10X.Editor.AddUpdateFunction(__initialize_llm_provider)
except Exception:
    pass
