import os
import shutil
import threading
import time
from pathlib import Path

from .common import IMAGE_EXTS, PROJECTS_DIR, VIDEO_EXTS, load_json

EPISODES = "episodes"
CHUNK = 1 << 20
SEARCH_SECONDS = 4.0
SKIP_DIRS = {"appdata", "node_modules", "$recycle.bin", "system volume information", "windows", "program files",
             "program files (x86)", "programdata", ".git", ".venv", "site-packages"}

_dialog = threading.Lock()


def _ask(kind, title, initial=None, filetypes=None):
    import tkinter as tk
    from tkinter import filedialog
    with _dialog:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            root.update()
            options = {"parent": root, "title": title}
            if initial and Path(initial).is_dir():
                options["initialdir"] = str(initial)
            if kind == "folder":
                found = filedialog.askdirectory(mustexist=True, **options)
                return [str(Path(found))] if found else []
            return [str(Path(f)) for f in filedialog.askopenfilenames(filetypes=filetypes or [], **options)]
        finally:
            root.destroy()


def choose_videos(title, initial=None):
    pattern = " ".join("*" + ext for ext in sorted(VIDEO_EXTS))
    return _ask("files", title, initial, [("Video", pattern), ("*", "*.*")])


def choose_folder(title, initial=None):
    return _ask("folder", title, initial)


def is_video(path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


def videos_in(folder):
    folder = Path(folder)
    return sorted(f for f in folder.iterdir() if is_video(f)) if folder.is_dir() else []


def same_file(a: Path, b: Path) -> bool:
    try:
        size = a.stat().st_size
        if size != b.stat().st_size:
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            for offset in {0, max(0, size - CHUNK)}:
                fa.seek(offset)
                fb.seek(offset)
                if fa.read(CHUNK) != fb.read(CHUNK):
                    return False
        return True
    except OSError:
        return False


def known_folders():
    folders = []
    if PROJECTS_DIR.exists():
        for project in sorted(PROJECTS_DIR.iterdir()):
            for video in load_json(project / "project.json", {}).get("videos", []):
                folders.append(Path(video["path"]).parent)
    from .aitk import load_settings
    last = load_settings().get("episodes_dir")
    if last:
        folders.insert(0, Path(last))
    home = Path.home()
    folders += [home / "Downloads", home / "Videos", home / "Desktop", home / "Documents", home]
    if hasattr(os, "listdrives"):
        folders += [Path(d) for d in os.listdrives()]
    return list(dict.fromkeys(f for f in folders if f.is_dir()))


def _walk(root: Path, depth: int):
    level = [root]
    for _ in range(depth + 1):
        following = []
        for folder in level:
            yield folder
            try:
                with os.scandir(folder) as entries:
                    for e in entries:
                        if (e.is_dir(follow_symlinks=False) and not e.name.startswith(".")
                                and e.name.lower() not in SKIP_DIRS):
                            following.append(Path(e.path))
            except OSError:
                continue
        level = following


def locate(copy: Path, folders, seconds=SEARCH_SECONDS):
    copy = Path(copy)
    deadline = time.monotonic() + seconds
    seen = set()
    projects = PROJECTS_DIR.resolve()
    for root in folders:
        for folder in _walk(Path(root), 1 if len(Path(root).parts) == 1 else 3):
            if time.monotonic() > deadline:
                return None
            if folder in seen:
                continue
            seen.add(folder)
            candidate = folder / copy.name
            try:
                if (candidate.is_file() and candidate.resolve() != copy.resolve()
                        and not candidate.resolve().is_relative_to(projects) and same_file(candidate, copy)):
                    return candidate.resolve()
            except OSError:
                continue
    return None


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while (path.with_name(f"{path.stem}_{n}{path.suffix}")).exists():
        n += 1
    return path.with_name(f"{path.stem}_{n}{path.suffix}")


def adopt_dropped(project_dir: Path, uploads, folders=None):
    folders = known_folders() if folders is None else folders
    adopted = []
    for upload in map(Path, uploads):
        if not upload.is_file():
            continue
        original = locate(upload, folders)
        if original:
            upload.unlink(missing_ok=True)
            adopted.append((original, True))
            continue
        store = Path(project_dir) / EPISODES
        store.mkdir(parents=True, exist_ok=True)
        dest = store / upload.name
        if dest.exists() and same_file(dest, upload):
            upload.unlink(missing_ok=True)
        else:
            dest = unique_path(dest)
            shutil.move(str(upload), str(dest))
        adopted.append((dest.resolve(), False))
    return adopted


def image_files(folder):
    folder = Path(folder) if folder else None
    if not folder or not folder.is_dir():
        return []
    return sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS)


def sync_images(folder: Path, wanted):
    folder = Path(folder)
    wanted = [Path(f) for f in wanted or [] if Path(f).suffix.lower() in IMAGE_EXTS and Path(f).is_file()]
    keep = {f.name for f in wanted}
    for old in image_files(folder):
        if old.name not in keep:
            old.unlink()
    if not wanted:
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
        return []
    folder.mkdir(parents=True, exist_ok=True)
    for src in wanted:
        dest = folder / src.name
        if src.resolve() == dest.resolve():
            continue
        if dest.exists() and dest.read_bytes() == src.read_bytes():
            continue
        if dest.exists():
            dest = unique_path(dest)
        shutil.copy2(src, dest)
    return image_files(folder)
