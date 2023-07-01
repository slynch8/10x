from N10X import Editor

g_ssCurScroll:int = -1
g_ssTargetScroll:int = -1
g_ssScrollSpeed:int = 0
g_ssScrollOffset:int = 0
SMOOTH_PAGE_SIZE:int = 15
SMOOTH_SCROLL_SPEED:int = 3

def SmoothScrollDown():
    global g_ssCurScroll, g_ssTargetScroll, g_ssScrollSpeed, g_ssScrollOffset
    if g_ssScrollSpeed == 0:
        col, line = Editor.GetCursorPos()
        g_ssCurScroll = line
        g_ssTargetScroll = g_ssCurScroll + SMOOTH_PAGE_SIZE
        g_ssScrollSpeed = SMOOTH_SCROLL_SPEED
        g_ssScrollOffset = Editor.GetCursorPos()[1] - Editor.GetScrollLine()

def SmoothScrollUp():
    global g_ssCurScroll, g_ssTargetScroll, g_ssScrollSpeed, g_ssScrollOffset
    if g_ssScrollSpeed == 0:
        col, line = Editor.GetCursorPos()
        g_ssCurScroll = line
        g_ssTargetScroll = g_ssCurScroll - SMOOTH_PAGE_SIZE
        g_ssScrollSpeed = -SMOOTH_SCROLL_SPEED
        g_ssScrollOffset = Editor.GetCursorPos()[1] - Editor.GetScrollLine()

def _SmoothScrollUpdate():
    global g_ssCurScroll, g_ssTargetScroll, g_ssScrollSpeed
    if g_ssScrollSpeed != 0:
        g_ssCurScroll = g_ssCurScroll + g_ssScrollSpeed
        if g_ssScrollSpeed > 0:
            g_ssCurScroll = g_ssTargetScroll if g_ssCurScroll > g_ssTargetScroll else g_ssCurScroll
        elif g_ssScrollSpeed < 0:
            g_ssCurScroll = g_ssTargetScroll if g_ssCurScroll < g_ssTargetScroll else g_ssCurScroll

        Editor.SetScrollLine(g_ssCurScroll - g_ssScrollOffset)
        if g_ssCurScroll == g_ssTargetScroll:
            Editor.SetCursorPos((0, g_ssTargetScroll))
            g_ssScrollSpeed = 0
    
Editor.AddUpdateFunction(_SmoothScrollUpdate)
