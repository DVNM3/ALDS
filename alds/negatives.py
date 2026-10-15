import shutil
from pathlib import Path

import numpy as np

FILE = "negatives.npz"
FEATS = "ccip.npz"


def load(char_dir: Path, file=FILE):
    p = Path(char_dir) / file
    if not p.exists():
        return [], None
    with np.load(p) as z:
        return z["names"].tolist(), z["feats"]


def _save(char_dir: Path, names, feats, file=FILE):
    p = Path(char_dir) / file
    if not names:
        p.unlink(missing_ok=True)
        return
    tmp = p.with_name(p.stem + ".tmp.npz")
    try:
        np.savez(tmp, names=np.array(names), feats=np.asarray(feats, np.float32))
        tmp.replace(p)
    finally:
        tmp.unlink(missing_ok=True)


def build_features(char_dir: Path):
    p = Path(char_dir) / FEATS
    if not p.exists():
        return {}, None
    with np.load(p) as z:
        return dict(zip(z["stems"].tolist(), z["feats"])), z["refs"]


def other_features(char_dir: Path):
    p = Path(char_dir) / FEATS
    if not p.exists():
        return None
    with np.load(p) as z:
        return z["others"] if "others" in z else None


def combine(*arrays):
    arrays = [a for a in arrays if a is not None and len(a)]
    return np.concatenate(arrays) if arrays else None


def add(char_dir: Path, name: str, feat, file=FILE):
    names, feats = load(char_dir, file)
    if name in names:
        return
    feats = feat[None] if feats is None else np.concatenate([feats, feat[None]])
    _save(char_dir, names + [name], feats, file)


def remove(char_dir: Path, name: str, file=FILE):
    names, feats = load(char_dir, file)
    if name in names:
        i = names.index(name)
        _save(char_dir, names[:i] + names[i + 1:], np.delete(feats, i, axis=0), file)


def clear(char_dir: Path):
    _save(char_dir, [], None)


def move_pair(png: Path, dst_dir: Path) -> Path:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / png.name
    shutil.move(str(png), str(dst))
    txt = png.with_suffix(".txt")
    if txt.exists():
        try:
            shutil.move(str(txt), str(dst.with_suffix(".txt")))
        except BaseException:
            shutil.move(str(dst), str(png))
            raise
    prune_empty(png.parent)
    return dst


KEPT_FOLDERS = ("sorted", "_deleted")


def prune_empty(folder: Path):
    try:
        while folder.name not in KEPT_FOLDERS and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent
    except OSError:
        pass


def remove_empty_folders(root: Path) -> int:
    if not root.is_dir():
        return 0
    removed = 0
    for folder in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            if not any(folder.iterdir()):
                folder.rmdir()
                removed += 1
        except OSError:
            pass
    return removed


def trash(char_dir: Path, png: Path) -> Path:
    char_dir = Path(char_dir)
    return move_pair(png, char_dir / "_deleted" / png.parent.relative_to(char_dir / "sorted"))


def look_alikes(char_dir: Path, names=None):
    from . import positives
    _, negs = load(char_dir)
    feats, refs = build_features(char_dir)
    names = [n for n in (feats if names is None else names) if n in feats]
    if negs is None or refs is None or not names:
        return {}
    _, confirmed = positives.load(char_dir)
    mask, margin = like_rejected(np.stack([feats[n] for n in names]), refs, negs, confirmed)
    return {n: float(m) for n, m, hit in zip(names, margin, mask) if hit}


def nearest(feats, negs):
    from .identity import ccip_cross
    return ccip_cross(np.asarray(feats, np.float32), negs).min(1)


def like_rejected(feats, refs, negs, confirmed=None):
    from .build import identity_score
    pos = identity_score(np.asarray(feats, np.float32), refs, confirmed)
    margin = pos - nearest(feats, negs)
    return margin > 0, margin
