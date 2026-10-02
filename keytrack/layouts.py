"""ANSI 键盘布局、键名归一化、手指映射。

数据库里的键名有两套历史来源：
- pynput 风格（早期指标路）：字母小写，空格是 " "，回车 "\n"，退格 "backspace"
- RIME 风格（v2 lua 分钟桶）：X11 keysym，空格 "space"，回车 "Return"，退格 "BackSpace"

norm_key() 把两套命名统一映射到布局里的物理键 id（小写），
组合键只计实际按下的主键，不额外虚构修饰键；布局外功能键返回 None。
"""

from __future__ import annotations

# 每行的物理键：(id, 显示名, 相对宽度, 手指)
# 手指：lp/lr/lm/li = 左手小/无名/中/食指，ri/rm/rr/rp = 右手食/中/无名/小指，th = 拇指
ANSI_ROWS: list[list[tuple[str, str, float, str]]] = [
    [("`", "`", 1, "lp"), ("1", "1", 1, "lp"), ("2", "2", 1, "lr"), ("3", "3", 1, "lm"),
     ("4", "4", 1, "li"), ("5", "5", 1, "li"), ("6", "6", 1, "ri"), ("7", "7", 1, "ri"),
     ("8", "8", 1, "rm"), ("9", "9", 1, "rr"), ("0", "0", 1, "rp"), ("-", "-", 1, "rp"),
     ("=", "=", 1, "rp"), ("backspace", "⌫", 2, "rp")],
    [("tab", "⇥", 1.5, "lp"), ("q", "q", 1, "lp"), ("w", "w", 1, "lr"), ("e", "e", 1, "lm"),
     ("r", "r", 1, "li"), ("t", "t", 1, "li"), ("y", "y", 1, "ri"), ("u", "u", 1, "ri"),
     ("i", "i", 1, "rm"), ("o", "o", 1, "rr"), ("p", "p", 1, "rp"), ("[", "[", 1, "rp"),
     ("]", "]", 1, "rp"), ("\\", "\\", 1.5, "rp")],
    [("caps", "⇪", 1.75, "lp"), ("a", "a", 1, "lp"), ("s", "s", 1, "lr"), ("d", "d", 1, "lm"),
     ("f", "f", 1, "li"), ("g", "g", 1, "li"), ("h", "h", 1, "ri"), ("j", "j", 1, "ri"),
     ("k", "k", 1, "rm"), ("l", "l", 1, "rr"), (";", ";", 1, "rp"), ("'", "'", 1, "rp"),
     ("return", "⏎", 2.25, "rp")],
    [("shift", "⇧", 2.25, "lp"), ("z", "z", 1, "lp"), ("x", "x", 1, "lr"), ("c", "c", 1, "lm"),
     ("v", "v", 1, "li"), ("b", "b", 1, "li"), ("n", "n", 1, "ri"), ("m", "m", 1, "ri"),
     (",", ",", 1, "rm"), (".", ".", 1, "rr"), ("/", "/", 1, "rp"), ("shift_r", "⇧", 2.75, "rp")],
    [("ctrl", "⌃", 1.25, "lp"), ("alt", "⌥", 1.25, "lp"), ("cmd", "⌘", 1.5, "th"),
     ("space", "", 6.5, "th"),
     ("cmd_r", "⌘", 1.5, "th"), ("alt_r", "⌥", 1.25, "rp"), ("ctrl_r", "⌃", 1.25, "rp")],
]

FINGER_NAMES = {
    "lp": "左手小指", "lr": "左手无名指", "lm": "左手中指", "li": "左手食指",
    "ri": "右手食指", "rm": "右手中指", "rr": "右手无名指", "rp": "右手小指",
    "th": "拇指",
}
LEFT_FINGERS = {"lp", "lr", "lm", "li"}
RIGHT_FINGERS = {"ri", "rm", "rr", "rp"}

_ALIAS = {
    " ": "space", "space": "space", "Space": "space",
    "\n": "return", "\r": "return", "enter": "return", "Return": "return",
    "backspace": "backspace", "BackSpace": "backspace", "delete": "backspace",
    "\t": "tab", "tab": "tab", "Tab": "tab",
    "shift": "shift", "Shift": "shift", "Shift_L": "shift",
    "shift_r": "shift_r", "Shift_R": "shift_r",
    "caps_lock": "caps", "Caps_Lock": "caps",
    "cmd": "cmd", "Super_L": "cmd", "cmd_r": "cmd_r", "Super_R": "cmd_r",
    "ctrl": "ctrl", "Control_L": "ctrl", "ctrl_r": "ctrl_r", "Control_R": "ctrl_r",
    "alt": "alt", "Alt_L": "alt", "Meta_L": "alt", "option": "alt",
    "alt_r": "alt_r", "Alt_R": "alt_r", "Meta_R": "alt_r",
}
_LAYOUT_IDS = {k for row in ANSI_ROWS for k, *_ in row}


# X11 keysym 和 Shift 后的符号都归到 ANSI 物理键。
_SYMBOLS = dict(zip("~!@#$%^&*()_+{}|:\"<>?", "`1234567890-=[]\\;',./"))
_ALIAS.update({
    "grave": "`", "asciitilde": "`", "exclam": "1", "at": "2", "numbersign": "3",
    "dollar": "4", "percent": "5", "asciicircum": "6", "ampersand": "7", "asterisk": "8",
    "parenleft": "9", "parenright": "0", "minus": "-", "underscore": "-", "equal": "=", "plus": "=",
    "bracketleft": "[", "braceleft": "[", "bracketright": "]", "braceright": "]", "backslash": "\\",
    "bar": "\\", "semicolon": ";", "colon": ";", "apostrophe": "'", "quotedbl": "'",
    "comma": ",", "less": ",", "period": ".", "greater": ".", "slash": "/", "question": "/",
})
_ALIAS = {k.lower(): v for k, v in _ALIAS.items()}


def norm_key(name: str) -> str | None:
    """一次组合键事件只映射一次；独立修饰键事件仍按左右键计数。"""
    if not isinstance(name, str) or not name:
        return None
    # Literal '+' is the shifted '=' key, not a separator.
    base = name if len(name) == 1 else name.rsplit("+", 1)[-1]
    if not base and name.endswith("++"):
        base = "+"
    low = base.lower()
    if low in _ALIAS:
        return _ALIAS[low]
    if base in _SYMBOLS:
        return _SYMBOLS[base]
    return low if low in _LAYOUT_IDS else None
