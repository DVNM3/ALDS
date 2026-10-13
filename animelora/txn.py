"""Undo for long commands: snapshot what a command will touch; if it is stopped (or fails), delete what it
generated and put the snapshot back, so the project looks exactly as before the command."""
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
    """with Transaction(base, keep=..., replace=..., new_in=..., remove_if_new=...):
        keep          files/dirs the command updates in place -> copied now, copy restored on rollback
        replace       files/dirs the command throws away and rebuilds -> moved aside now, moved back on rollback
        new_in        dirs whose new entries are the command's output -> those entries deleted on rollback
        remove_if_new paths that don't exist yet -> deleted entirely on rollback (e.g. a brand new project)
    The backup lives in `base` (same drive, so moving is instant) and is removed when the command succeeds."""

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
        return False  # let the exception through

    def rollback(self):
        for p in self.fresh:  # the whole thing was created by this command
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
                    _remove(p)  # didn't exist before the command
        _remove(self.backup)
        print("[undo] stopped - everything this command generated was removed")


# ---- what each command touches ----

def scan_txn(project: Project):
    s = project.scan_dir
    return Transaction(project.dir,
                       keep=[project.path("project.json"), s / "frames.json", s / "detections.json", s / "ccip.npy",
                             s / "clusters.json", s / "fp_ref.npy", project.clusters_dir],
                       new_in=[project.frames_dir, s], remove_if_new=[project.dir])


def clusters_txn(project: Project):
    """re-cluster, split, autoskip: cluster list + contact sheets, OP/ED flags, new fingerprints"""
    s = project.scan_dir
    return Transaction(project.dir,
                       keep=[project.path("project.json"), s / "frames.json", s / "clusters.json",
                             s / "fp_ref.npy", project.clusters_dir],
                       new_in=[s])


def build_txn(project: Project, name: str, ref_dir=None):
    """Call build.check_overwrite first: this moves sorted/ aside. Caption history goes too - its snapshots
    belong to the old captions. The project's crop cache (cache.py) is left out on purpose: what a stopped
    build analysed stays valid and makes the next build faster."""
    c = project.char_dir(name)
    return Transaction(project.dir,
                       replace=[c / "sorted", c / "_deleted", c / "_dropped", c / "_caption_history",
                                c / "build.json", c / "emb.npz", c / "report.txt"]
                       + ([Path(ref_dir)] if ref_dir else []),
                       remove_if_new=[c])


def export_txn(project: Project, name: str, out_dir: Path, config_dir=None):
    """`keep` (a copy, not a move) for the dataset folder, so export's own check that it never writes into a
    folder it didn't create still sees the folder as it is."""
    c = project.char_dir(name)
    return Transaction(project.dir, keep=[out_dir],
                       new_in=[c] + ([Path(config_dir)] if config_dir else []),
                       remove_if_new=[out_dir])
