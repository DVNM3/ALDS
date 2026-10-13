"""Cooperative stop for long operations.

The GUI's stop button sets a flag; the pipeline's long loops call check(), which raises Cancelled at the next
frame / image / block. (Gradio's own `cancels=` only stops the browser from waiting - the Python worker
thread would keep running.) The Transaction around the command then removes what it generated.
"""
import threading

_flag = threading.Event()


class Cancelled(Exception):
    """Raised inside a long operation after the user pressed stop."""


def request():
    _flag.set()


def reset():
    _flag.clear()


def check():
    if _flag.is_set():
        raise Cancelled()
