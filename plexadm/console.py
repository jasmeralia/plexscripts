from __future__ import annotations


class Color:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def colorize(text: str, color: str) -> str:
    return f"{color}{text}{Color.ENDC}"


def ok(text: str) -> str:
    return colorize(text, Color.OKGREEN)


def info(text: str) -> str:
    return colorize(text, Color.OKCYAN)


def warn(text: str) -> str:
    return colorize(text, Color.WARNING)


def fail(text: str) -> str:
    return colorize(text, Color.FAIL)
