import shutil
import time
from pathlib import Path

from .common import Project


def _remove(p: Path):
    if p.is_dir() and not p.is_symlink():
        shutil.rmtree(p, ignore_errors=True)
    elif p.exists():
        p.unlink()


class Transaction:
    def __init__(self, base, keep=(), replace=(), new_in=(), remove_if_new=()):
        as_paths = lambda xs: [Path(x) for x in xs]
        self.base = Path(base)
        self.keep, self.replace = as_paths(keep), as_paths(replace)
        self.new_in, self.remove_if_new = as_paths(new_in), as_paths(remove_if_new)
        self.backup = self.base / f".undo_{time.time_ns()}"

    def __enter__(self):
        self.fresh = [p for p in self.remove_if_new if not p.exists()]
        self.listing = {d: ({x.name for x in d.iterdir()} if d.exists() else set()) for d in self.new_in}
        self.backup.mkdir(parents=True)
        for i, p in enumerate(self.keep):
            if p.is_dir():
                shutil.copytree(p, self.backup / f"k{i}")
            elif p.exists():
                shutil.copy2(p, self.backup / f"k{i}")
        for i, p in enumerate(self.replace):
            if p.exists():
                shutil.move(str(p), str(self.backup / f"r{i}"))
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            _remove(self.backup)
        else:
            self.rollback()
        return False

    def rollback(self):
        for p in self.fresh:
            _remove(p)
        for d, before in self.listing.items():
            if d.exists():
                for x in d.iterdir():
                    if x.name not in before and not x.name.startswith(".undo_"):
                        _remove(x)
        for prefix, paths in (("k", self.keep), ("r", self.replace)):
            for i, p in enumerate(paths):
                src = self.backup / f"{prefix}{i}"
                if src.exists():
                    _remove(p)
                    p.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(p))
                elif p.exists() and not any(p == f or f in p.parents for f in self.fresh):
                    _remove(p)
        _remove(self.backup)
        print("[undo] stopped - everything this command generated was removed")


def scan_txn(project: Project):
    s = project.scan_dir
    return Transaction(project.dir,
                       keep=[project.path("project.json"), s / "frames.json", s / "detections.json", s / "ccip.npy",
                             s / "clusters.json", s / "fp_ref.npy", project.clusters_dir],
                       new_in=[project.frames_dir, s], remove_if_new=[project.dir])


def clusters_txn(project: Project):
    s = project.scan_dir
    return Transaction(project.dir,
                       keep=[project.path("project.json"), s / "frames.json", s / "clusters.json",
                             s / "fp_ref.npy", project.clusters_dir],
                       new_in=[s])


def build_txn(project: Project, name: str, ref_dir=None):
    c = project.char_dir(name)
    return Transaction(project.dir,
                       replace=[c / "sorted", c / "_deleted", c / "_dropped", c / "_caption_history",
                                c / "build.json", c / "emb.npz", c / "ccip.npz", c / "report.txt"]
                       + ([Path(ref_dir)] if ref_dir else []),
                       remove_if_new=[c])


def export_txn(project: Project, name: str, out_dir: Path, config_dir=None):
    c = project.char_dir(name)
    return Transaction(project.dir, keep=[out_dir],
                       new_in=[c] + ([Path(config_dir)] if config_dir else []),
                       remove_if_new=[out_dir])
