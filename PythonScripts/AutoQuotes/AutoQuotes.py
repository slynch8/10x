import N10X

QUOTE = '"'

def OnInterceptCharKey(c):
    try:
        if c != QUOTE:
            return False

        # Intercepts are global, so only act inside a text editor
        if not N10X.Editor.TextEditorHasFocus():
            return False

        # --- Wrap selection: "Text" ---
        selection = N10X.Editor.GetSelection()
        if selection:
            start, end = N10X.Editor.GetCursorSelection()
            # Make sure start comes before end, whichever way it was selected
            if (start[1], start[0]) > (end[1], end[0]):
                start, end = end, start

            if start[1] == end[1]:
                # Single-line selection: rewrite the line directly
                y = start[1]
                line = N10X.Editor.GetLine(y)
                new_line = line[:start[0]] + QUOTE + line[start[0]:end[0]] + QUOTE + line[end[0]:]
                N10X.Editor.SetLine(y, new_line)
                N10X.Editor.ClearSelection()
                N10X.Editor.SetCursorPos((end[0] + 2, y))
            else:
                # Multi-line selection: delete it, then insert the wrapped text
                N10X.Editor.SendKey("Delete")
                N10X.Editor.InsertText(QUOTE + selection + QUOTE)
            return True

        # --- Auto-pair ---
        x, y = N10X.Editor.GetCursorPos()
        line = N10X.Editor.GetLine(y)
        next_char = line[x] if x < len(line) else ""
        prev_char = line[x - 1] if x > 0 else ""

        # Typing " before an existing closing " just steps over it
        if next_char == QUOTE:
            N10X.Editor.SetCursorPos((x + 1, y))
            return True

        # Don't auto-pair after a word character or another quote
        if prev_char.isalnum() or prev_char == "_" or prev_char == QUOTE:
            return False

        N10X.Editor.InsertText(QUOTE + QUOTE)
        N10X.Editor.SetCursorPos((x + 1, y))
        return True

    except Exception as e:
        N10X.Editor.LogTo10XOutput("AutoQuote error: " + str(e))
        return False

def OnInterceptKey(key, shift, control, alt):
    try:
        if key not in ("Backspace", "Back"):
            return False
        if control or alt or shift:
            return False
        if not N10X.Editor.TextEditorHasFocus():
            return False
        if N10X.Editor.GetSelection():
            return False  # let normal backspace delete the selection

        x, y = N10X.Editor.GetCursorPos()
        line = N10X.Editor.GetLine(y)
        prev_char = line[x - 1] if 0 < x <= len(line) else ""
        next_char = line[x] if x < len(line) else ""

        # Cursor sits between a "" pair: remove both quotes
        if prev_char == QUOTE and next_char == QUOTE:
            N10X.Editor.SetLine(y, line[:x - 1] + line[x + 1:])
            N10X.Editor.SetCursorPos((x - 1, y))
            return True

        return False
    except Exception as e:
        N10X.Editor.LogTo10XOutput("AutoQuote backspace error: " + str(e))
        return False

N10X.Editor.AddOnInterceptKeyFunction(OnInterceptKey)

N10X.Editor.AddOnInterceptCharKeyFunction(OnInterceptCharKey)