from pathlib import Path

import numpy as np

FILE = "negatives.npz"
FEATS = "ccip.npz"


def load(char_dir: Path):
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
    import shutil
    dst = Path(char_dir) / "_deleted" / png.parent.relative_to(Path(char_dir) / "sorted") / png.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(png), str(dst))
    if png.with_suffix(".txt").exists():
        shutil.move(str(png.with_suffix(".txt")), str(dst.with_suffix(".txt")))
    return dst


def reject(char_dir: Path, name: str) -> bool:
    feats, _ = build_features(char_dir)
    if name not in feats:
        return False
    add(char_dir, name, feats[name])
    return True


def look_alikes(char_dir: Path, names=None):
    _, negs = load(char_dir)
    feats, refs = build_features(char_dir)
    names = [n for n in (feats if names is None else names) if n in feats]
    if negs is None or refs is None or not names:
        return {}
    mask, margin = like_rejected(np.stack([feats[n] for n in names]), refs, negs)
    return {n: float(m) for n, m, hit in zip(names, margin, mask) if hit}


def nearest(feats, negs):
    from .identity import ccip_cross
    return ccip_cross(np.asarray(feats, np.float32), negs).min(1)


def like_rejected(feats, refs, negs):
    from .build import match_score
    pos = match_score(np.asarray(feats, np.float32), refs)
    margin = pos - nearest(feats, negs)
    return margin > 0, margin
