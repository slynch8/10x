#------------------------------------------------------------------------
import N10X
import os

#------------------------------------------------------------------------
def IsSkipChar(c):
    return c == " " or c == "\t"

#------------------------------------------------------------------------
# Skip the largest possible number of spaces or tabs.
#
# @Cleanup: Merge both cases
def OnInterceptKey(key, shift, control, alt):
    if key == "Left":
        (x, y) = N10X.Editor.GetCursorPos()

        line = N10X.Editor.GetLine(y).rstrip()
        count = len(line)

        if count > 0 and x > count:
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

        line = N10X.Editor.GetLine(y).rstrip()
        count = len(line)

        if count > 0 and x < count and x+1 < count and IsSkipChar(line[x+1]):
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
N10X.Editor.AddOnInterceptKeyFunction(OnInterceptKey)
