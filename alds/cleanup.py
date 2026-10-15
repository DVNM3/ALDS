import shutil
from pathlib import Path

from .cache import unused_images
from .common import frame_in_use
from .i18n import t
from .negatives import KEPT_FOLDERS, remove_empty_folders
from .scan import load_state
from .versions import prune_store


def disk_usage(project):
    seen = set()

    def size(p: Path) -> int:
        if not p.exists():
            return 0
        total = 0
        for f in [p] if p.is_file() else p.rglob("*"):
            if not f.is_file():
                continue
            st = f.stat()
            if st.st_nlink > 1:
                if (st.st_dev, st.st_ino) in seen:
                    continue
                seen.add((st.st_dev, st.st_ino))
            total += st.st_size
        return total

    rows = [("frames", size(project.frames_dir)), ("scan", size(project.scan_dir)),
            ("clusters", size(project.clusters_dir))]
    if project.chars_dir.exists():
        for c in sorted(p for p in project.chars_dir.iterdir() if p.is_dir()):
            rows.append((f"characters/{c.name}", size(c)))
    return rows + [("cache", size(project.dir / "cache")), ("previews", size(project.previews_dir)),
                   ("episodes", size(project.dir / "episodes"))]


def fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def clean(project, mode="safe"):
    before = sum(b for _, b in disk_usage(project))
    removed_files = 0
    if mode == "all":
        if project.frames_dir.exists():
            removed_files += sum(1 for _ in project.frames_dir.rglob("*.jpg"))
            shutil.rmtree(project.frames_dir)
        shutil.rmtree(project.dir / "cache", ignore_errors=True)
        proj = project.load("project.json", {"videos": []})
        proj["frames_deleted"] = True
        project.save("project.json", proj)
    else:
        frames, dets, _ = load_state(project)
        needed = {d["frame"] for d in dets if d["feat"] >= 0}
        for i, f in enumerate(frames):
            if i in needed and frame_in_use(f):
                continue
            p = project.path(f["file"])
            if p.exists():
                p.unlink()
                removed_files += 1
        for f in unused_images(project):
            f.unlink()
    shutil.rmtree(project.previews_dir, ignore_errors=True)
    if project.chars_dir.exists():
        sub = ("_thumbs", "_dropped") + (("_deleted",) if mode == "all" else ())
        for c in project.chars_dir.iterdir():
            for name in sub:
                shutil.rmtree(c / name, ignore_errors=True)
            prune_store(c / "versions")
            for name in KEPT_FOLDERS:
                remove_empty_folders(c / name)
    after = sum(b for _, b in disk_usage(project))
    print(t("✅ Deleted {n} frames and freed {size}.", n=removed_files, size=fmt_bytes(before - after)))
