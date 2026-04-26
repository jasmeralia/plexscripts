from __future__ import annotations

import math


def count_digits(number: int) -> int:
    return int(math.log10(abs(number))) + 1 if number else 1


def progress_prefix(index: int, total: int) -> str:
    if total <= 0:
        return "[0/0] "
    percent = index / total
    width = count_digits(total)
    return f"[{percent:7.2%} {index:>{width}}/{total}] "
