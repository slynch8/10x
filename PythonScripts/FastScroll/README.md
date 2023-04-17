# FastScroll 10x-editor script

With this script, you can add the ability to scroll faster with keyboard shortcuts. It also mimics smooth scrolling, more like mousewheel scrolling.

## Usage
Copy the script into `%AppData%\Roaming\10x\PythonScripts`. Open "Key bindings" and assign any shortcuts to `FastScrollUp` and `FastScrollDown` commands. Example:

```
PageUp:			    FastScrollUp
PageDown:			FastScrollDown
```

## Customization
There are two global variables in `FastScroll.py` that you can modify to customize the speed and amount of scrolling.

```
FASTSCROLL_PAGE_SIZE:int = 15
FASTSCROLL_SCROLL_SPEED:int = 3
```

`FASTSCROLL_PAGE_SIZE` is the number of lines it does at each scroll. And `FASTSCROLL_SCROLL_SPEED` is the speed of scrolling.


