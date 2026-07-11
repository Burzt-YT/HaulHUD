from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading
from typing import Callable, Optional

user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

VK_MAP = {
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "space": 0x20, "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
}

def parse_hotkey_string(hotkey: str) -> tuple[int, int]:
    parts = [p.strip().lower() for p in hotkey.split("+") if p.strip()]
    mods = 0
    vk = None
    for p in parts:
        if p in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif p == "alt":
            mods |= MOD_ALT
        elif p == "shift":
            mods |= MOD_SHIFT
        elif p == "win":
            mods |= MOD_WIN
        else:
            key = p if len(p) > 1 else p.upper()
            vk = VK_MAP.get(key)
    if vk is None:
        raise ValueError(f"Could not parse key from hotkey string: {hotkey!r}")
    return mods, vk

class GlobalHotkeyListener:

    def __init__(self, hotkey: str, on_trigger: Callable[[], None]) -> None:
        self._hotkey_str = hotkey
        self._on_trigger = on_trigger
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._stop_requested = False
        self._hotkey_id = 1

    def start(self) -> None:
        if user32 is None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if user32 is None or self._thread_id is None:
            return
        self._stop_requested = True
        user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def update_hotkey(self, hotkey: str) -> None:
        if user32 is None or self._thread_id is None:
            self._hotkey_str = hotkey
            return
        user32.PostThreadMessageW(
            self._thread_id, WM_QUIT, 0, 0
        )
        self._hotkey_str = hotkey
        self.start()

    def _run(self) -> None:
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        try:
            mods, vk = parse_hotkey_string(self._hotkey_str)
        except ValueError:
            return

        if not user32.RegisterHotKey(None, self._hotkey_id, mods, vk):
            return

        msg = wintypes.MSG()
        try:
            while not self._stop_requested:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:
                    break
                if msg.message == WM_HOTKEY:
                    self._on_trigger()
        finally:
            user32.UnregisterHotKey(None, self._hotkey_id)
