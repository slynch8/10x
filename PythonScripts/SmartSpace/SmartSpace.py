#------------------------------------------------------------------------
import N10X
import os

#------------------------------------------------------------------------
def IsSkipChar(c):
    return c == " " or c == "\t"

#------------------------------------------------------------------------
def OnInterceptKey(key, shift, control, alt):
    if key == "Left":
        (x, y) = N10X.Editor.GetCursorPos()

        line = N10X.Editor.GetLine(y)
        count = len(line)

        if count == 2 and x != 0:
            # We are at the end of the current line. The next line is empty
            # count is two (\r\n) and the cursor still returns the end
            # position of the last line position and visually the cursor is
            # in the new line aligned with indentation by design. If you now
            # click on the left, it should jump from the visual position to
            # the beginning of the empty line.
            #
            # VisualEmptyLine:
            N10X.Editor.SetCursorPos((0, y+1))
        elif count > 0 and x > count:
            N10X.Editor.SetCursorPos((0, y))
        elif count > 0 and x < count and x-1 > -1 and IsSkipChar(line[x-1]):
            move = True
            a = 0

            # Look backward, but at least 2 spaces in row
            for i in range(int(x), -1, -1):
                a += 1;
                if not IsSkipChar(line[i-1]):
                    if a < 2:
                        move = False
                    break

            if move:
                N10X.Editor.SetCursorPos((i, y))
                return True

    elif key == "Right":
        (x, y) = N10X.Editor.GetCursorPos()

        line = N10X.Editor.GetLine(y)
        count = len(line)

        if count == 2 and x != 0:
            # VisualEmptyLine:
            N10X.Editor.SetCursorPos((0, y+1))
        elif count > 0 and x < count and x+1 < count and IsSkipChar(line[x+1]):
            move = True
            a = 0

            # Look forward, but at least 2 spaces in row
            for i in range(int(x), count, 1):
                a += 1;
                if not IsSkipChar(line[i]):
                    if a < 2:
                        move = False
                    break

            if move:
                N10X.Editor.SetCursorPos((i, y))
                return True


#------------------------------------------------------------------------
# uncomment this line to skip the largest possible number of spaces or tabs
# while moving
N10X.Editor.AddOnInterceptKeyFunction(OnInterceptKey)
