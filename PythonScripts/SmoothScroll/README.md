# SmoothScroll 10x-editor script

With this script, you can add the ability to scroll faster with keyboard shortcuts. It also mimics smooth scrolling, more like mousewheel scrolling.

## Usage
Copy the script into `%AppData%\Roaming\10x\PythonScripts`. Open "Key bindings" and assign any shortcuts to `SmoothScrollUp` and `SmoothScrollDown` commands. Example:

```
PageUp:			    SmoothScrollUp
PageDown:			SmoothScrollDown
```

## Customization
There are two global variables in `SmoothScroll.py` that you can modify to customize the speed and amount of scrolling.

```
SMOOTHSCROLL_PAGE_SIZE:int = 15
SMOOTHSCROLL_SCROLL_SPEED:int = 3
```

`SMOOTHSCROLL_PAGE_SIZE` is the number of lines it does at each scroll. And `SMOOTHSCROLL_SCROLL_SPEED` is the speed of scrolling.


