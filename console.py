"""Console output helpers with optional ANSI color support."""

import os
import sys


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
BRIGHT_MAGENTA = "\033[95m"

# Semantic console roles. Each role is a tuple of ANSI codes applied
# with paint(text, *ROLE).
USER_INPUT = (BOLD, CYAN)
USER_TEXT = (CYAN,)
ARACELI_INPUT = (BOLD, BRIGHT_MAGENTA)
ARACELI_TEXT = (BRIGHT_MAGENTA,)
SYSTEM_MESSAGE = (DIM,)
SYSTEM_ERROR = (RED,)

_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_STD_OUTPUT_HANDLE = -11

_enabled = False


def init_colors() -> bool:
    """Detect, and on Windows enable, ANSI color support.

    Returns whether colors are active. Colors are disabled when the
    NO_COLOR environment variable is set or when stdout is not a
    terminal (for example when output is redirected to a file).
    """

    global _enabled

    if os.environ.get("NO_COLOR"):
        _enabled = False
        return False

    if not sys.stdout.isatty():
        _enabled = False
        return False

    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
            mode = ctypes.c_uint32()

            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                _enabled = False
                return False

            if not mode.value & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
                if not kernel32.SetConsoleMode(
                    handle,
                    mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING,
                ):
                    _enabled = False
                    return False

        except Exception:
            _enabled = False
            return False

    _enabled = True
    return True


def colors_enabled() -> bool:
    """Return whether colored output is currently active."""

    return _enabled


def paint(text: str, *codes: str) -> str:
    """Wrap text in ANSI codes when colors are enabled."""

    if not _enabled or not codes:
        return text

    return "".join(codes) + text + RESET
