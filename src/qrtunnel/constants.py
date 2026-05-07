"""Shared display constants and package metadata."""

__version__ = "3.7.0"

CLR_G = "\033[32m"  # Standard Green (Success/Selected)
CLR_Y = "\033[93m"  # Bright Yellow (Warnings/Focus)
CLR_R = "\033[31m"  # Standard Red (Errors)
CLR_B = "\033[34m"  # Standard Blue (Info)
CLR_C = "\033[36m"  # Standard Cyan (Directories)
CLR_M = "\033[35m"  # Standard Magenta (Headers)
CLR_W = "\033[37m"  # Standard White
CLR_DIM = "\033[90m"  # Bright Black (Grey)
CLR_BLD = "\033[1m"  # Bold
CLR_RST = "\033[0m"  # Reset
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR = "\033[2J\033[H"

DOT = "●"
OK = f"{CLR_G}{DOT}{CLR_RST}"
ERR = f"{CLR_R}{DOT}{CLR_RST}"
WRN = f"{CLR_Y}{DOT}{CLR_RST}"
INFO = f"{CLR_B}{DOT}{CLR_RST}"

W = 64  # panel width
