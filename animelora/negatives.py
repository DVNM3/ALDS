"""Learning from review: images marked "not this character" become negative references.

A negative is the CCIP feature of a rejected image. They are kept in characters/<c>/negatives.npz (with the
image names, for undo), outside what a rebuild replaces, so what was taught carries over to every rebuild.

A crop counts as the rejected character when it is closer to some negative than to the character's own
references:  distance to the nearest negative < match score (build.match_score against the references).
A correct image is closer to its own character, so one mistaken rejection doesn't throw out the rest.
Review uses this to point at the remaining images that look like what was rejected; build drops such crops.

Plain deletion (a bad frame of the right character) teaches nothing: only the explicit "not this character"
action does.
"""
from pathlib import Path

import numpy as np

FILE = "negatives.npz"
FEATS = "ccip.npz"  # written by build: CCIP feature of every kept image + the references it was matched with


def load(char_dir: Path):
    """-> (names, features (n, d)) of the rejected images; empty when nothing was rejected yet."""
    p = Path(char_dir) / FILE
    if not p.exists():
        return [], None
    z = np.load(p)
    return z["names"].tolist(), z["feats"]


def _save(char_dir: Path, names, feats):
    p = Path(char_dir) / FILE
    if not names:
        p.unlink(missing_ok=True)
        return
    tmp = p.with_name(p.stem + ".tmp.npz")
    np.savez(tmp, names=np.array(names), feats=np.asarray(feats, np.float32))
    tmp.replace(p)


def build_features(char_dir: Path):
    """-> ({image name: feature}, references) from the last build, or ({}, None) for builds made before."""
    p = Path(char_dir) / FEATS
    if not p.exists():
        return {}, None
    z = np.load(p)
    return dict(zip(z["stems"].tolist(), z["feats"])), z["refs"]


def add(char_dir: Path, name: str, feat):
    names, feats = load(char_dir)
    if name in names:
        return
    feats = feat[None] if feats is None else np.concatenate([feats, feat[None]])
    _save(char_dir, names + [name], feats)


def remove(char_dir: Path, name: str):
    names, feats = load(char_dir)
    if name in names:
        i = names.index(name)
        _save(char_dir, names[:i] + names[i + 1:], np.delete(feats, i, axis=0))


def clear(char_dir: Path):
    _save(char_dir, [], None)


def trash(char_dir: Path, png: Path) -> Path:
    """Move an image (and its caption) from sorted/ to the review trash _deleted/, keeping its folder."""
    import shutil
    dst = Path(char_dir) / "_deleted" / png.parent.relative_to(Path(char_dir) / "sorted") / png.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(png), str(dst))
    if png.with_suffix(".txt").exists():
        shutil.move(str(png.with_suffix(".txt")), str(dst.with_suffix(".txt")))
    return dst


def reject(char_dir: Path, name: str) -> bool:
    """Learn image `name` (a stem of the last build) as another character. False for builds made before
    this existed (no ccip.npz): rebuild once."""
    feats, _ = build_features(char_dir)
    if name not in feats:
        return False
    add(char_dir, name, feats[name])
    return True


def look_alikes(char_dir: Path, names=None):
    """-> {name: margin} for images of the last build (all, or the given names) that are closer to a rejected
    image than to the references (the bigger the margin, the more alike); empty when nothing was rejected."""
    _, negs = load(char_dir)
    feats, refs = build_features(char_dir)
    names = [n for n in (feats if names is None else names) if n in feats]
    if negs is None or refs is None or not names:
        return {}
    mask, margin = like_rejected(np.stack([feats[n] for n in names]), refs, negs)
    return {n: float(m) for n, m, hit in zip(names, margin, mask) if hit}


def nearest(feats, negs):
    """Distance from each feature to its nearest negative."""
    from .identity import ccip_cross
    return ccip_cross(np.asarray(feats, np.float32), negs).min(1)


def like_rejected(feats, refs, negs):
    """-> (bool mask: closer to a negative than to the references, margin = match score - negative distance)"""
    from .build import match_score
    pos = match_score(np.asarray(feats, np.float32), refs)
    margin = pos - nearest(feats, negs)
    return margin > 0, margin
