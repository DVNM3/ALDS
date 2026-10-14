import threading

_flag = threading.Event()


class Cancelled(Exception):
    pass


def request():
    _flag.set()


def reset():
    _flag.clear()


def check():
    if _flag.is_set():
        raise Cancelled()
