"""Saved build analysis, so a rebuild with other settings doesn't redo the slow model passes.

Per detection (keyed by detection id, checked against its frame file and boxes, so a changed scan recomputes
it instead of reusing stale data): the crop boxes (half-body detection), CCIP features of half/head crops,
sharpness/contrast, OCR words, WD14 tags per tagger, the portrait class and the face pose. Thresholds (match,
dedup, contrast, OCR confidence, min size) are applied afterwards, so changing them reuses everything.
Per reference set: the CCIP match score of every detection, and which cluster members are used as references.

The written PNGs are kept as well (cache/images/, as cut or upscaled) and hard-linked into sorted/, so they
take no extra disk space while a build uses them. (An image edited in place in sorted/ is edited in the cache
too, and the next build uses the edited version.)

One cache per project, shared by all of its characters: projects/<p>/cache/.
"""
import hashlib
import os
import pickle
import shutil

import numpy as np

VERSION = 1        # bump when crop geometry or the meaning of a stored value changes
MAX_REF_SETS = 8   # match scores are kept for this many recent reference sets
# PNG is lossless at every level. On 1.2 MP crops: level 6 (Pillow's default) 84 ms and 0.83 MB, level 3
# 44 ms and +7% size, level 1 54 ms and +59% (the bigger file costs more to write than it saves).
PNG_LEVEL = 3


def digest(*arrays) -> str:
    h = hashlib.sha1()
    for a in arrays:
        h.update(np.ascontiguousarray(a).tobytes())
    return h.hexdigest()


class CropCache:
    def __init__(self, project, fresh=False):
        self.dir = project.dir / "cache"
        self.file = self.dir / "crops.pkl"
        self.img_dir = self.dir / "images"
        self.entries, self.matches, self.central = {}, {}, {}
        self.computed = 0  # model passes / measurements done in this build (not taken from the cache)
        data = None
        if self.file.exists() and not fresh:
            try:
                data = pickle.loads(self.file.read_bytes())
            except Exception:
                pass
        if data and data.get("version") == VERSION:
            self.entries, self.matches, self.central = data["entries"], data["matches"], data["central"]
        else:  # fresh, missing, unreadable or from an older version: start over, images included
            shutil.rmtree(self.dir, ignore_errors=True)

    def entry(self, det, frame):
        """The cached record of one detection: {"crops": {type: {...}}, "poses": {head box: pose}, ...}."""
        sig = (frame["file"], tuple(det["box"]), tuple(det["head"]) if det["head"] else None)
        e = self.entries.get(det["id"])
        if e is None or e["sig"] != sig:
            if e is not None:
                for f in self.img_dir.glob(f"{det['id']}_*"):
                    f.unlink()
            e = self.entries[det["id"]] = {"sig": sig, "crops": {}, "poses": {}}
        return e

    def get(self, rec, key, compute):
        """rec[key], computing and storing it first when missing."""
        if key not in rec:
            rec[key] = compute()
            self.computed += 1
        return rec[key]

    def scores(self, key, ids, compute):
        """Scores of detections `ids` against one reference set (`key`); compute(missing ids) -> scores."""
        known = self.matches.pop(key, {})
        missing = [i for i in ids if i not in known]
        if missing:
            known.update(zip(missing, compute(missing).tolist()))
            self.computed += 1
        self.matches[key] = known  # most recently used last
        for old in list(self.matches)[:-MAX_REF_SETS]:
            del self.matches[old]
        return np.array([known[i] for i in ids], np.float32)

    def image(self, det_id, ctype, size, compute):
        """Path of a written crop (size 0 = as cut from the frame, else upscaled to that size), made with
        compute() -> PIL image when missing."""
        p = self.img_dir / f"{det_id}_{ctype}_{size}.png"
        if not p.exists():
            self.img_dir.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.stem + ".tmp.png")
            compute().save(tmp, compress_level=PNG_LEVEL)
            tmp.replace(p)
            self.computed += 1
        return p

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps({"version": VERSION, "entries": self.entries, "matches": self.matches,
                                      "central": self.central}, protocol=pickle.HIGHEST_PROTOCOL))
        tmp.replace(self.file)


def unused_images(project):
    """Cached images no build links to any more (only the cache holds them)."""
    d = project.dir / "cache" / "images"
    return [f for f in d.glob("*.png") if f.stat().st_nlink == 1] if d.exists() else []


def link_or_copy(src, dst):
    """Hard link (no extra disk space, same drive) or a copy when linking isn't possible."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
