import json
import re
import threading
import urllib.request

from . import __version__

LATEST_API = "https://api.github.com/repos/DVNM3/ALDS/releases/latest"
RELEASES_PAGE = "https://github.com/DVNM3/ALDS/releases/latest"
_found = {}


def version_tuple(text):
    return tuple(int(x) for x in re.findall(r"\d+", text or "")[:3])


def latest_tag(timeout=5):
    request = urllib.request.Request(LATEST_API, headers={"Accept": "application/vnd.github+json",
                                                          "User-Agent": "ALDS/" + __version__})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response).get("tag_name", "")


def check():
    try:
        tag = latest_tag()
    except Exception:
        return None
    return tag if version_tuple(tag) > version_tuple(__version__) else None


def start():
    from .aitk import load_settings
    if load_settings().get("check_updates", True):
        threading.Thread(target=lambda: _found.update(tag=check()), daemon=True).start()


def newer():
    return _found.get("tag")
