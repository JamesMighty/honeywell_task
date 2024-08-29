
FILES_SEP = " -> "
SERVER_SEP = ":"

GREEN = "green"
RED = "red"
ORANGE = "orange"
BLUE = "blue"
BLACK = "black"


WIDGET_DEFAULTS = {
    "disabledforeground": "#b4b4b4",
    }

LABEL_DEFAULTS = {
    "anchor": "nw",
    "compound": "left",
    "justify": "left",
    **WIDGET_DEFAULTS
}

LISTBOX_DEFAULTS = {
    "background": "white",
    "cursor": "xterm",
    "disabledforeground": "#b4b4b4",
    "font": "TkFixedFont",
    "highlightcolor": "#d9d9d9",
    "selectbackground": "#d9d9d9",
    "selectforeground": "black",
    "exportselection": False
}
